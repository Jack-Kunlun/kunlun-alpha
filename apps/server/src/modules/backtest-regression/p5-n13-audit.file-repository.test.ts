import { mkdtemp, mkdir, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { LOCAL_PREVIEW_ARTIFACT, LOCAL_PREVIEW_BASELINE } from "./backtest-regression.fixture";
import { FileBacktestRegressionRepository } from "./file-backtest-regression.repository";
import { canonicalJson } from "./backtest-regression.validation";

async function writeIdentity(
  root: string,
  artifactSha256: string,
  runId = "local-preview-run",
): Promise<void> {
  const suiteId = "p5-core-chain";
  const identityDir = join(root, "identities", suiteId);
  await mkdir(identityDir, { recursive: true });
  await writeFile(
    join(identityDir, `${runId}.ref.json`),
    canonicalJson({ schemaVersion: "backtest-regression-ref-v1", suiteId, runId, artifactSha256 }),
  );
}

async function writeObject(root: string, artifact = LOCAL_PREVIEW_ARTIFACT): Promise<string> {
  const digest = artifact.artifactSha256;
  const objectDir = join(root, "objects", "sha256", digest.slice(0, 2));
  await mkdir(objectDir, { recursive: true });
  await writeFile(join(objectDir, `${digest}.json`), canonicalJson(artifact));
  return digest;
}

describe("P5-N13 file repository safety", () => {
  it("reads the approved baseline from the explicit .baseline.json layout", async () => {
    const root = await mkdtemp(join(tmpdir(), "p5-n13-file-repository-"));
    await mkdir(join(root, "baselines"), { recursive: true });
    const baselinePath = join(root, "baselines", "p5-core-chain.baseline.json");
    await writeFile(baselinePath, canonicalJson(LOCAL_PREVIEW_BASELINE));

    const repository = new FileBacktestRegressionRepository(root);

    await expect(repository.getBaseline("p5-core-chain")).resolves.toEqual(LOCAL_PREVIEW_BASELINE);
  });

  it("rejects an existing root-internal symlink instead of following it", async () => {
    const root = await mkdtemp(join(tmpdir(), "p5-n13-file-repository-"));
    const outside = await mkdtemp(join(tmpdir(), "p5-n13-file-outside-"));
    await symlink(outside, join(root, "baselines"), "dir");

    const repository = new FileBacktestRegressionRepository(root);

    await expect(repository.getBaseline("p5-core-chain")).rejects.toThrow();
  });

  it("rejects root and final-file symlinks", async () => {
    const realRoot = await mkdtemp(join(tmpdir(), "p5-n13-file-repository-"));
    const outside = await mkdtemp(join(tmpdir(), "p5-n13-file-outside-"));
    const rootAlias = join(outside, "root-alias");
    await symlink(realRoot, rootAlias, "dir");
    const rootRepository = new FileBacktestRegressionRepository(rootAlias);
    await expect(rootRepository.getBaseline("p5-core-chain")).rejects.toThrow();

    const root = await mkdtemp(join(tmpdir(), "p5-n13-file-repository-"));
    await mkdir(join(root, "baselines"), { recursive: true });
    const outsideBaseline = join(outside, "outside.baseline.json");
    await writeFile(outsideBaseline, canonicalJson(LOCAL_PREVIEW_BASELINE));
    await symlink(outsideBaseline, join(root, "baselines", "p5-core-chain.baseline.json"));
    await expect(
      new FileBacktestRegressionRepository(root).getBaseline("p5-core-chain"),
    ).rejects.toThrow();
  });

  it("rejects suite and digest-prefix symlinks while listing identities", async () => {
    const root = await mkdtemp(join(tmpdir(), "p5-n13-file-repository-"));
    const outside = await mkdtemp(join(tmpdir(), "p5-n13-file-outside-"));
    await mkdir(join(root, "identities"), { recursive: true });
    await symlink(outside, join(root, "identities", "p5-core-chain"), "dir");
    await expect(new FileBacktestRegressionRepository(root).list()).rejects.toThrow();

    const prefixRoot = await mkdtemp(join(tmpdir(), "p5-n13-file-repository-"));
    const digest = LOCAL_PREVIEW_ARTIFACT.artifactSha256;
    await writeIdentity(prefixRoot, digest);
    await mkdir(join(prefixRoot, "objects", "sha256"), { recursive: true });
    await symlink(outside, join(prefixRoot, "objects", "sha256", digest.slice(0, 2)), "dir");
    await expect(new FileBacktestRegressionRepository(prefixRoot).list()).rejects.toThrow();
  });

  it("rejects traversal and ref-object digest mismatches", async () => {
    const root = await mkdtemp(join(tmpdir(), "p5-n13-file-repository-"));
    const digest = await writeObject(root);
    await writeIdentity(root, digest);
    const repository = new FileBacktestRegressionRepository(root);
    await expect(repository.getBaseline("../escape")).rejects.toThrow();

    const mismatchRoot = await mkdtemp(join(tmpdir(), "p5-n13-file-repository-"));
    const objectDigest = await writeObject(mismatchRoot);
    const wrongDigest = "b".repeat(64);
    const wrongObjectDir = join(mismatchRoot, "objects", "sha256", wrongDigest.slice(0, 2));
    await mkdir(wrongObjectDir, { recursive: true });
    await writeFile(
      join(wrongObjectDir, `${wrongDigest}.json`),
      canonicalJson(LOCAL_PREVIEW_ARTIFACT),
    );
    await writeIdentity(mismatchRoot, wrongDigest);
    expect(objectDigest).not.toBe(wrongDigest);
    await expect(new FileBacktestRegressionRepository(mismatchRoot).list()).rejects.toThrow();
  });
});
