import { lstat, readdir, readFile, realpath } from "node:fs/promises";
import { isAbsolute, join, relative, resolve, sep } from "node:path";
import { TextDecoder } from "node:util";
import type {
  BacktestRegressionArtifact,
  BacktestRegressionBaseline,
  BacktestRegressionRunSummary,
} from "@kunlun/shared-types";
import type { BacktestRegressionRepository } from "./backtest-regression.types";
import {
  BacktestRegressionUnavailableError,
  assertSafeId,
  assertSha256,
  exactObject,
  parseBacktestRegressionArtifact,
  parseBacktestRegressionBaseline,
  parseCanonicalBacktestRegressionJson,
} from "./backtest-regression.validation";

function compareAscii(left: string, right: string): number {
  const length = Math.min(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    if (left.charCodeAt(index) !== right.charCodeAt(index)) {
      return left.charCodeAt(index) - right.charCodeAt(index);
    }
  }
  return left.length - right.length;
}

async function assertContained(root: string, target: string): Promise<void> {
  const rootPath = resolve(root);
  const targetPath = resolve(target);
  const pathFromRoot = relative(rootPath, targetPath);
  if (pathFromRoot === ".." || pathFromRoot.startsWith(`..${sep}`) || isAbsolute(pathFromRoot)) {
    throw new BacktestRegressionUnavailableError("artifact path escapes configured root");
  }
  try {
    if ((await lstat(rootPath)).isSymbolicLink()) {
      throw new BacktestRegressionUnavailableError("artifact root must not be a symlink");
    }
  } catch (error) {
    if (error instanceof BacktestRegressionUnavailableError) throw error;
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      throw new BacktestRegressionUnavailableError("artifact root cannot be inspected");
    }
  }
  let current = rootPath;
  for (const part of pathFromRoot === "" ? [] : pathFromRoot.split(sep)) {
    if (!part || part === "." || part === "..") {
      throw new BacktestRegressionUnavailableError("artifact path is not canonical");
    }
    current = join(current, part);
    try {
      const stat = await lstat(current);
      if (stat.isSymbolicLink())
        throw new BacktestRegressionUnavailableError("artifact path contains a symlink");
      if (current !== targetPath && !stat.isDirectory()) {
        throw new BacktestRegressionUnavailableError("artifact path ancestor is not a directory");
      }
    } catch (error) {
      if (error instanceof BacktestRegressionUnavailableError) throw error;
      if ((error as NodeJS.ErrnoException).code === "ENOENT") break;
      throw new BacktestRegressionUnavailableError("artifact path cannot be inspected");
    }
  }
  try {
    const rootReal = await realpath(rootPath);
    const targetReal = await realpath(targetPath);
    const realRelative = relative(rootReal, targetReal);
    if (realRelative === ".." || realRelative.startsWith(`..${sep}`) || isAbsolute(realRelative)) {
      throw new BacktestRegressionUnavailableError("artifact realpath escapes configured root");
    }
  } catch (error) {
    if (error instanceof BacktestRegressionUnavailableError) throw error;
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      throw new BacktestRegressionUnavailableError("artifact realpath cannot be inspected");
    }
  }
}

async function readJson(root: string, path: string): Promise<Record<string, unknown>> {
  try {
    await assertContained(root, path);
    const stat = await lstat(path);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error("not a regular file");
    const raw = await readFile(path);
    const text = new TextDecoder("utf-8", { fatal: true }).decode(raw);
    return parseCanonicalBacktestRegressionJson(text);
  } catch (error) {
    if (error instanceof BacktestRegressionUnavailableError) throw error;
    throw new BacktestRegressionUnavailableError(
      `artifact file is unavailable or corrupt: ${path}`,
    );
  }
}

export class FileBacktestRegressionRepository implements BacktestRegressionRepository {
  private readonly root: string;

  constructor(root: string) {
    if (root.trim().length === 0)
      throw new BacktestRegressionUnavailableError("artifact root is empty");
    this.root = resolve(root);
  }

  private objectPath(digest: string): string {
    const safeDigest = assertSha256(digest, "artifact digest");
    return join(this.root, "objects", "sha256", safeDigest.slice(0, 2), `${safeDigest}.json`);
  }

  private async artifactFromRef(
    suiteId: string,
    refName: string,
  ): Promise<BacktestRegressionArtifact> {
    const runId = refName.endsWith(".ref.json") ? refName.slice(0, -".ref.json".length) : "";
    assertSafeId(suiteId, "suiteId");
    assertSafeId(runId, "runId");
    const refPath = join(this.root, "identities", suiteId, refName);
    const ref = exactObject(
      await readJson(this.root, refPath),
      ["schemaVersion", "suiteId", "runId", "artifactSha256"],
      "identity ref",
    );
    if (
      ref.schemaVersion !== "backtest-regression-ref-v1" ||
      ref.suiteId !== suiteId ||
      ref.runId !== runId
    ) {
      throw new BacktestRegressionUnavailableError("identity ref is invalid");
    }
    const digest = assertSha256(ref.artifactSha256, "identity ref artifactSha256");
    const artifact = parseBacktestRegressionArtifact(
      await readJson(this.root, this.objectPath(digest)),
    );
    if (
      artifact.suiteId !== suiteId ||
      artifact.runId !== runId ||
      artifact.artifactSha256 !== digest
    ) {
      throw new BacktestRegressionUnavailableError("artifact ref/object binding is invalid");
    }
    return artifact;
  }

  async list(): Promise<BacktestRegressionArtifact[]> {
    const identities = join(this.root, "identities");
    try {
      await assertContained(this.root, identities);
      const suites = await readdir(identities, { withFileTypes: true });
      const artifacts: BacktestRegressionArtifact[] = [];
      for (const suite of suites.sort((left, right) => compareAscii(left.name, right.name))) {
        if (suite.isSymbolicLink() || !suite.isDirectory())
          throw new BacktestRegressionUnavailableError("identity directory is invalid");
        assertSafeId(suite.name, "suiteId");
        const suitePath = join(identities, suite.name);
        await assertContained(this.root, suitePath);
        const refs = await readdir(suitePath, { withFileTypes: true });
        for (const ref of refs.sort((left, right) => compareAscii(left.name, right.name))) {
          if (ref.isSymbolicLink() || !ref.isFile() || !ref.name.endsWith(".ref.json")) {
            throw new BacktestRegressionUnavailableError("identity entry is invalid");
          }
          artifacts.push(await this.artifactFromRef(suite.name, ref.name));
        }
      }
      return artifacts;
    } catch (error) {
      if (error instanceof BacktestRegressionUnavailableError) throw error;
      throw new BacktestRegressionUnavailableError("artifact identity store is unavailable");
    }
  }

  async get(runId: string): Promise<BacktestRegressionArtifact> {
    assertSafeId(runId, "runId");
    const artifacts = await this.list();
    const artifact = artifacts.find((candidate) => candidate.runId === runId);
    if (artifact === undefined)
      throw new BacktestRegressionUnavailableError("regression run is missing");
    return artifact;
  }

  async getBaseline(baselineId: string): Promise<BacktestRegressionBaseline> {
    assertSafeId(baselineId, "baselineId");
    const path = join(this.root, "baselines", `${baselineId}.baseline.json`);
    return parseBacktestRegressionBaseline(await readJson(this.root, path));
  }

  source(): Pick<BacktestRegressionRunSummary, "availability" | "preview"> {
    return { availability: "FILE_ARTIFACT_ROOT", preview: false };
  }
}
