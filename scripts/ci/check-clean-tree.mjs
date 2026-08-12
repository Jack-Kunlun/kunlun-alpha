#!/usr/bin/env node
/**
 * Verify the working tree stays clean after a build.
 *
 * CI runs `pnpm build` and then this script. A non-empty `git status`
 * means build outputs leaked into tracked/untracked files (e.g. a
 * generated file not covered by .gitignore), which would make local
 * builds and CI diverge. Run from the repo root.
 *
 * Usage: `node scripts/ci/check-clean-tree.mjs`
 */

import { execFileSync } from "node:child_process";

const status = execFileSync("git", ["status", "--porcelain"], {
  encoding: "utf8",
  stdio: ["ignore", "pipe", "inherit"],
}).trim();

if (status.length > 0) {
  console.error("[check-clean-tree] Working tree is dirty after build:");
  console.error(status);
  console.error(
    "\nExpected a clean tree. Add ignored paths to .gitignore or fix generators.",
  );
  process.exit(1);
}

console.log("[check-clean-tree] OK: working tree is clean.");
