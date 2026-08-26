import { MemorySqlDriver, MigrationRunner } from "@kunlun/db";
import { describe, expect, it } from "vitest";
import { migrations } from "./index";

describe("instrument master intelligence migration", () => {
  it("keeps immutable point-in-time identity revisions", async () => {
    const driver = new MemorySqlDriver();
    await new MigrationRunner(driver).migrate(migrations);
    const table = migrations
      .find((migration) => migration.version === 5)
      ?.up.find((candidate) => candidate.name === "instrument_master_revisions");

    expect(table?.columns.map((column) => column.name)).toEqual(
      expect.arrayContaining([
        "instrument_id",
        "effective_from",
        "available_time",
        "processing_time",
        "payload_fingerprint",
      ]),
    );
    expect(table?.constraints).toEqual(
      expect.arrayContaining([
        expect.stringContaining("visibility_ck"),
        expect.stringContaining("payload_fingerprint"),
      ]),
    );
  });
});
