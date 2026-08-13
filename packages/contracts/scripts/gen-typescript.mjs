#!/usr/bin/env node

/**
 * Generate TypeScript types from JSON Schema contracts.
 *
 * Usage:
 *   node scripts/gen-typescript.mjs          # generate
 *   node scripts/gen-typescript.mjs --check  # verify generated == schema
 */

import { compile } from "json-schema-to-typescript";
import { readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const checkMode = process.argv.includes("--check");

const SCHEMAS_DIR = resolve(__dirname, "..", "schemas");
const TYPES_OUTPUT = resolve(__dirname, "..", "..", "shared-types", "src", "index.ts");

/**
 * Normalize the generated output with Prettier so it matches the repo's
 * `format:check` gate. Without this the raw json-schema-to-typescript output
 * (extra blank lines between interfaces) would fail the Prettier check.
 */
function formatWithPrettier(code) {
  const prettierBin = resolve(
    __dirname,
    "..",
    "..",
    "..",
    "node_modules",
    "prettier",
    "bin",
    "prettier.cjs",
  );
  const result = spawnSync(process.execPath, [prettierBin, "--stdin-filepath", "index.ts"], {
    input: code,
    encoding: "utf8",
  });
  if (result.status === 0 && result.stdout) {
    return result.stdout;
  }
  return code;
}

async function main() {
  if (!existsSync(SCHEMAS_DIR)) {
    console.error(`Schemas directory not found: ${SCHEMAS_DIR}`);
    process.exit(1);
  }

  // Collect *.json recursively (supports subdirectories such as schemas/instrument/).
  const schemaFiles = readdirSync(SCHEMAS_DIR, { recursive: true })
    .filter((f) => typeof f === "string" && f.endsWith(".json"))
    .sort();

  if (schemaFiles.length === 0) {
    console.warn("No schema files found in", SCHEMAS_DIR);
    process.exit(checkMode ? 1 : 0);
  }

  const types = [];
  for (const file of schemaFiles) {
    const schemaPath = resolve(SCHEMAS_DIR, file);
    const schema = JSON.parse(readFileSync(schemaPath, "utf-8"));
    const ts = await compile(schema, schema.title || file.replace(".json", ""), {
      bannerComment: "",
      style: { singleQuote: false, semi: true, tabWidth: 2, printWidth: 100 },
    });
    types.push(ts);
  }

  const header = [
    "/** Shared domain types. Generated from packages/contracts/schemas/. DO NOT EDIT BY HAND. */",
    "",
  ].join("\n");
  const output = formatWithPrettier((header + types.join("\n\n")).trimEnd() + "\n");

  // Ensure output directory exists
  const outDir = dirname(TYPES_OUTPUT);
  if (!existsSync(outDir)) {
    mkdirSync(outDir, { recursive: true });
  }

  if (checkMode) {
    if (existsSync(TYPES_OUTPUT)) {
      const existing = readFileSync(TYPES_OUTPUT, "utf-8");
      if (existing !== output) {
        console.error("ERROR: Generated TypeScript types are out of sync with JSON Schema.");
        console.error("Run `pnpm gen:typescript` from packages/contracts/ to regenerate.");
        process.exit(1);
      }
      console.log("TypeScript types are in sync with JSON Schema.");
    } else {
      console.error("ERROR: TypeScript output file does not exist:", TYPES_OUTPUT);
      process.exit(1);
    }
  } else {
    writeFileSync(TYPES_OUTPUT, output, "utf-8");
    console.log("Generated TypeScript types ->", TYPES_OUTPUT);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
