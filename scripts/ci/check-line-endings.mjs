#!/usr/bin/env node
/**
 * Check that tracked text files never contain a CR byte.
 *
 * The repo normalizes to LF via `.gitattributes` (`* text=auto eol=lf`).
 * A CR in a tracked file means someone committed a CRLF or mixed-line
 * file (e.g. via a tool that bypassed git's renormalization). CI runs
 * this on Linux, Windows and macOS, so it must not rely on Bash-only
 * features -- plain Node only.
 *
 * Files whose attributes deliberately use CRLF (.bat / .cmd) or binary
 * formats are skipped. Usage: `node scripts/ci/check-line-endings.mjs`.
 */

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { basename } from "node:path";

// Binary extensions from .gitattributes + common build/asset formats.
const BINARY_RE =
  /\.(png|jpg|jpeg|gif|pdf|docx|xlsx|parquet|woff2?|eot|ttf|ico|zip|gz|lockb?)$/i;
// Files configured with `text eol=crlf`.
const CRLF_RE = /\.(bat|cmd)$/i;

const tracked = execFileSync(
  "git",
  // -z: NUL-separated, no quoting; core.quotepath=false: no octal escapes
  // for non-ASCII names, so extension filters below actually match.
  ["-c", "core.quotepath=false", "ls-files", "-z"],
  { encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] },
)
  .split("\0")
  .map((line) => line.trim())
  .filter((f) => f.length > 0 && !BINARY_RE.test(f) && !CRLF_RE.test(f));

const offenders = [];
for (const file of tracked) {
  const buf = readFileSync(file);
  if (buf.includes(0x0d)) {
    offenders.push(file);
  }
}

if (offenders.length > 0) {
  console.error(
    `[check-line-endings] ${offenders.length} file(s) contain CR bytes ` +
      "(expected LF-only text, see .gitattributes):",
  );
  for (const f of offenders) {
    console.error(`  - ${f}`);
  }
  process.exit(1);
}

console.log(
  `[check-line-endings] OK: ${tracked.length} text files, LF-only.`,
);
