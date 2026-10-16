#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { existsSync } from "node:fs";

export function runPrettier(files, mode, spawn = spawnSync) {
  const scriptDir = dirname(fileURLToPath(import.meta.url));
  const prettier = resolve(scriptDir, "../../node_modules/prettier/bin/prettier.cjs");
  // Windows CreateProcess has a 32,767 UTF-16 character limit. Reserve
  // quoting/escaping space and keep every invocation below half that limit.
  const argumentSize = (value) => value.length * 2 + 3;
  const baseSize = [process.execPath, prettier, mode].reduce(
    (size, value) => size + argumentSize(value),
    1,
  );
  const batches = [];
  let batch = [];
  let size = baseSize;
  for (const file of files) {
    const fileSize = argumentSize(file);
    if (baseSize + fileSize > 16000) throw new Error("Prettier file path is too long");
    if (size + fileSize > 16000) {
      batches.push(batch);
      batch = [];
      size = baseSize;
    }
    batch.push(file);
    size += fileSize;
  }
  if (batch.length > 0) batches.push(batch);

  let status = 0;
  for (const files of batches) {
    const result = spawn(process.execPath, [prettier, mode, ...files], {
      encoding: "utf8",
      stdio: "inherit",
    });
    if (result.error) process.stderr.write(`Prettier could not start: ${result.error.message}\n`);
    status ||= result.status ?? 1;
  }
  return status;
}

function main() {
  const git = spawnSync("git", ["ls-files", "-z"], { encoding: "utf8" });
  if (git.status !== 0) {
    process.stderr.write(git.stderr);
    process.exit(git.status ?? 1);
  }

  const supported = new Set([
    ".css",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
  ]);
  const files = git.stdout
    .split("\0")
    .filter(Boolean)
    .filter((file) => existsSync(file))
    .filter((file) => supported.has(file.slice(file.lastIndexOf("."))));

  const mode = process.argv.includes("--write") ? "--write" : "--check";
  process.exit(runPrettier(files, mode));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
