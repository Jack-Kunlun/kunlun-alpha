import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  lstatSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  readlinkSync,
  rmSync,
  symlinkSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

const CLOSURE_ENTRIES = [
  "pyproject.toml",
  "uv.lock",
  ".python-version",
  "services/quant-engine/pyproject.toml",
  "services/quant-engine/src",
  "services/quant-engine/fixtures/regression/p5-core-chain.baseline.json",
  "python/packages/ashare-contracts/pyproject.toml",
  "python/packages/ashare-contracts/src",
  "python/packages/backtest-core/pyproject.toml",
  "python/packages/backtest-core/src",
  "python/packages/quant-core/pyproject.toml",
  "python/packages/quant-core/src",
];

function compareAscii(left, right) {
  const length = Math.min(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    if (left.charCodeAt(index) !== right.charCodeAt(index)) {
      return left.charCodeAt(index) - right.charCodeAt(index);
    }
  }
  return left.length - right.length;
}

function parseOption(args, name, fallback) {
  const index = args.indexOf(name);
  return index < 0 ? fallback : args[index + 1];
}

function assertRepoRoot(root) {
  if (!existsSync(join(root, "pyproject.toml")) || !existsSync(join(root, "uv.lock"))) {
    throw new Error("checkout root is missing pyproject.toml or uv.lock: " + root);
  }
}

function assertContained(root, target) {
  const pathFromRoot = relative(resolve(root), resolve(target));
  if (pathFromRoot === ".." || pathFromRoot.startsWith(".." + sep) || isAbsolute(pathFromRoot)) {
    throw new Error("path escapes isolated root: " + target);
  }
}

function copyEntry(source, destination) {
  const stat = lstatSync(source);
  mkdirSync(dirname(destination), { recursive: true });
  if (stat.isSymbolicLink()) {
    symlinkSync(readlinkSync(source), destination);
  } else if (stat.isDirectory()) {
    mkdirSync(destination, { recursive: true });
    for (const child of readdirSync(source).sort(compareAscii)) {
      copyEntry(join(source, child), join(destination, child));
    }
  } else if (stat.isFile()) {
    copyFileSync(source, destination);
  } else {
    throw new Error("unsupported checkout entry: " + source);
  }
}

function snapshotTree(root) {
  const snapshot = new Map();
  function visit(path, relativePath) {
    const stat = lstatSync(path);
    if (relativePath !== "") {
      if (stat.isSymbolicLink()) {
        snapshot.set(relativePath, { kind: "symlink", target: readlinkSync(path) });
        return;
      }
      if (stat.isDirectory()) {
        snapshot.set(relativePath, { kind: "directory" });
      } else if (stat.isFile()) {
        const bytes = readFileSync(path);
        snapshot.set(relativePath, {
          kind: "file",
          digest: createHash("sha256").update(bytes).digest("hex"),
          bytes,
        });
        return;
      } else {
        throw new Error("unsupported isolated entry: " + path);
      }
    }
    if (stat.isDirectory()) {
      for (const child of readdirSync(path).sort(compareAscii)) {
        const childPath = relativePath === "" ? child : relativePath + "/" + child;
        visit(join(path, child), childPath);
      }
    }
  }
  visit(root, "");
  return snapshot;
}

function snapshotDifferences(before, after) {
  const paths = new Set([...before.keys(), ...after.keys()]);
  const differences = [];
  for (const path of [...paths].sort(compareAscii)) {
    const left = before.get(path);
    const right = after.get(path);
    if (!left || !right || left.kind !== right.kind) {
      differences.push(path);
      continue;
    }
    if (left.kind === "symlink" && left.target !== right.target) {
      differences.push(path);
    } else if (left.kind === "file" && !left.bytes.equals(right.bytes)) {
      differences.push(path);
    }
  }
  return differences;
}

function gitStatusSnapshot(root) {
  const result = spawnSync("git", ["status", "--porcelain=v1", "--untracked-files=all"], {
    cwd: root,
    encoding: "utf8",
  });
  return result.status === 0 ? result.stdout : null;
}

function run() {
  const args = process.argv.slice(2);
  const sourceRoot = resolve(parseOption(args, "--root", process.cwd()));
  assertRepoRoot(sourceRoot);
  const uvProjectRoot = resolve(process.env.KUNLUN_ORIGINAL_REPO_ROOT ?? process.cwd());
  assertRepoRoot(uvProjectRoot);
  const baselineInput = parseOption(
    args,
    "--baseline",
    "services/quant-engine/fixtures/regression/p5-core-chain.baseline.json",
  );
  const baselineSource = isAbsolute(baselineInput)
    ? resolve(baselineInput)
    : resolve(sourceRoot, baselineInput);
  assertContained(sourceRoot, baselineSource);
  if (!existsSync(baselineSource)) throw new Error("baseline does not exist: " + baselineSource);

  const statusBefore = gitStatusSnapshot(sourceRoot);
  const isolatedRoot = resolve(mkdtempSync(join(tmpdir(), "kunlun-backtest-regression-")));
  let childStatus = 1;
  let treeDifferences = [];
  let statusAfter = statusBefore;
  try {
    for (const entry of CLOSURE_ENTRIES) {
      const source = join(sourceRoot, entry);
      if (!existsSync(source)) throw new Error("required closure entry is missing: " + source);
      copyEntry(source, join(isolatedRoot, entry));
    }
    const isolatedBaseline = join(isolatedRoot, relative(sourceRoot, baselineSource));
    const pythonPath = [
      join(isolatedRoot, "services/quant-engine/src"),
      join(isolatedRoot, "python/packages/ashare-contracts/src"),
      join(isolatedRoot, "python/packages/backtest-core/src"),
      join(isolatedRoot, "python/packages/quant-core/src"),
    ].join(delimiter);
    const childEnvironment = {
      ...process.env,
      KUNLUN_REPO_ROOT: isolatedRoot,
      PYTHONPATH: pythonPath,
    };
    const before = snapshotTree(isolatedRoot);
    const child = spawnSync(
      process.env.UV_BINARY ?? "uv",
      [
        "--project",
        uvProjectRoot,
        "--no-cache",
        "run",
        "--no-sync",
        "python",
        "-B",
        "-m",
        "quant_engine.regression",
        "check",
        "--baseline",
        relative(isolatedRoot, isolatedBaseline),
      ],
      { cwd: isolatedRoot, env: childEnvironment, stdio: "inherit" },
    );
    childStatus = child.status ?? 1;

    const testChildWrite = parseOption(args, "--test-child-write", null);
    if (testChildWrite !== null) {
      const mutationPath = resolve(isolatedRoot, testChildWrite);
      assertContained(isolatedRoot, mutationPath);
      const mutationChild = spawnSync(
        process.execPath,
        [
          "-e",
          "const {mkdirSync,writeFileSync}=require('node:fs');const {dirname}=require('node:path');const path=process.env.KUNLUN_TEST_MUTATION_PATH;mkdirSync(dirname(path),{recursive:true});writeFileSync(path,'child mutation');",
        ],
        {
          cwd: isolatedRoot,
          env: { ...childEnvironment, KUNLUN_TEST_MUTATION_PATH: mutationPath },
        },
      );
      if (mutationChild.status !== 0) childStatus = mutationChild.status ?? 1;
    }
    const after = snapshotTree(isolatedRoot);
    treeDifferences = snapshotDifferences(before, after);
    statusAfter = gitStatusSnapshot(sourceRoot);
  } finally {
    rmSync(isolatedRoot, { recursive: true, force: true });
  }

  if (statusBefore !== statusAfter) {
    console.error("source checkout git status changed during isolated regression");
    childStatus = childStatus || 1;
  }
  if (treeDifferences.length > 0) {
    console.error("isolated regression tree changed: " + treeDifferences.join(", "));
    childStatus = childStatus || 1;
  }
  if (childStatus !== 0) process.exitCode = childStatus;
  else console.log("MATCHED; isolated closure had zero mutation");
}

try {
  run();
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
