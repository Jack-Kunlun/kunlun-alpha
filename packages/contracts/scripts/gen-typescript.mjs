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
import { fileURLToPath, pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const checkMode = process.argv.includes("--check");

const SCHEMAS_DIR = resolve(__dirname, "..", "schemas");
const TYPES_OUTPUT = resolve(__dirname, "..", "..", "shared-types", "src", "index.ts");

/**
 * Remove `allOf` elements that carry Draft-07 `if`/`then`/`else` constraints.
 *
 * json-schema-to-typescript does not understand conditional constraints and
 * renders an `if`-bearing `allOf` element as a catch-all `{ [k: string]:
 * unknown }` index signature, which breaks the closed-object contract implied
 * by `additionalProperties: false`. TypeScript cannot faithfully express a
 * discriminated "deleted implies deletedAt" union through this generator, and
 * that invariant is enforced at runtime by the generated Python DTO and the
 * domain model. So the conditional is dropped from the TypeScript type surface
 * while the Schema keeps it authoritative for the other languages.
 *
 * Returns a shallow copy when a change is needed, otherwise the input schema,
 * so schemas that do not use conditional constraints are never touched.
 */
export function stripConditionalAllOf(schema) {
  if (!schema || typeof schema !== "object" || !Array.isArray(schema.allOf)) {
    return schema;
  }
  const filtered = schema.allOf.filter(
    (el) => !el || typeof el !== "object" || !("if" in el || "then" in el || "else" in el),
  );
  if (filtered.length === schema.allOf.length) {
    return schema;
  }
  const copy = { ...schema };
  if (filtered.length === 0) {
    delete copy.allOf;
  } else {
    copy.allOf = filtered;
  }
  return copy;
}

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
    const ts = await compile(stripConditionalAllOf(schema), schema.title || file.replace(".json", ""), {
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

const isMain =
  process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isMain) {
  main().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}
