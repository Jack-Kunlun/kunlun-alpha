import { defineConfig } from "vitest/config";

/**
 * Root-level Vitest config for the Kunlun Alpha monorepo.
 *
 * Tests live next to the code they exercise (`*.test.ts` / `*.spec.ts`)
 * so tooling (turbo caching, editors) discovers them consistently.
 *
 * Coverage is reported but NOT enforced here as a hard gate — the policy
 * in P0-N13 is that tests must assert real behavior, not inflate numbers.
 * Use `--coverage` explicitly when a reviewer wants the report.
 */
export default defineConfig({
  test: {
    include: ["**/*.{test,spec}.{ts,tsx}"],
    exclude: ["**/node_modules/**", "**/dist/**", "**/build/**", "**/coverage/**", "**/.next/**"],
    environment: "node",
  },
});
