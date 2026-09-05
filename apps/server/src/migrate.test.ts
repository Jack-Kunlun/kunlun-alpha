import { describe, expect, it } from "vitest";
import { migrationSetForMode } from "./migrate";

describe("migration CLI modes", () => {
  it("selects only market-data settings migration for the isolated settings DSN", () => {
    expect(migrationSetForMode(true).map((migration) => migration.version)).toEqual([11]);
  });

  it("keeps the normal migration set unchanged", () => {
    expect(migrationSetForMode(false).map((migration) => migration.version)).toEqual(
      expect.arrayContaining([1, 10, 11]),
    );
  });
});
