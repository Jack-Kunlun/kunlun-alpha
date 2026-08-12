// @ts-check
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

/**
 * Unified ESLint flat config for the Kunlun Alpha monorepo.
 *
 * Layers:
 *   1. Global ignores (build output, vendored code, generated files).
 *   2. typescript-eslint recommended (applies to .ts/.tsx and plain .js).
 *   3. React Hooks rules — scoped to apps/web only.
 *
 * Any lint error blocks merge (see P0-N13 quality gate).
 */
export default tseslint.config(
  {
    ignores: [
      "**/node_modules/**",
      "**/dist/**",
      "**/build/**",
      "**/coverage/**",
      "**/.next/**",
      "**/.turbo/**",
      ".venv/**",
      "**/*.d.ts",
      "**/*.js.map",
      "**/*.d.ts.map",
      // NestJS emits .js next to sources during local builds.
      "apps/api/src/**/*.js",
      // Generated schema outputs.
      "packages/contracts/generated/**",
    ],
  },
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/consistent-type-imports": "error",
    },
  },
  {
    files: ["apps/web/**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.flat.recommended.rules,
    },
  },
);
