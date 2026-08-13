#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { existsSync } from "node:fs";

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
const scriptDir = dirname(fileURLToPath(import.meta.url));
const prettier = resolve(scriptDir, "../../node_modules/prettier/bin/prettier.cjs");
const result = spawnSync(process.execPath, [prettier, mode, ...files], {
  encoding: "utf8",
  stdio: "inherit",
});
process.exit(result.status ?? 1);
