import { MemorySqlDriver, MigrationRunner } from "@kunlun/db";
import { describe, expect, it } from "vitest";
import { migrations } from "./index";

describe("seat and KOL intelligence migration", () => {
  it("separates public seat facts, Claims and controlled evidence", async () => {
    const driver = new MemorySqlDriver();
    await new MigrationRunner(driver).migrate(migrations);
    const migration = migrations.find((item) => item.version === 7);
    const names = migration?.up.map((table) => table.name);
    const claim = migration?.up.find((table) => table.name === "kol_claim_intelligence_revisions");

    expect(names).toEqual(
      expect.arrayContaining([
        "seat_trade_intelligence_revisions",
        "kol_claim_intelligence_revisions",
        "intelligence_evidence_revisions",
      ]),
    );
    expect(claim?.columns.map((column) => column.name)).toEqual(
      expect.arrayContaining(["claim_id", "kol_id", "deleted", "processing_time"]),
    );
    expect(claim?.columns.map((column) => column.name)).not.toEqual(
      expect.arrayContaining(["order_id", "account_id", "fill_id"]),
    );
  });
});
