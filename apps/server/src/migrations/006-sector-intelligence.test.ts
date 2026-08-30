import { MemorySqlDriver, MigrationRunner } from "@kunlun/db";
import { describe, expect, it } from "vitest";
import { migrations } from "./index";

describe("sector intelligence migration", () => {
  it("defines point-in-time sector and membership projections", async () => {
    const driver = new MemorySqlDriver();
    await new MigrationRunner(driver).migrate(migrations);
    const migration = migrations.find((item) => item.version === 6);
    const names = migration?.up.map((table) => table.name);
    const membership = migration?.up.find((table) => table.name === "sector_membership_revisions");

    expect(names).toEqual(
      expect.arrayContaining(["sector_master_revisions", "sector_membership_revisions"]),
    );
    expect(membership?.columns.map((column) => column.name)).toEqual(
      expect.arrayContaining(["instrument_id", "sector_id", "processing_time"]),
    );
    expect(membership?.indexes?.[0]?.columns).toContain("instrument_id");
  });
});
