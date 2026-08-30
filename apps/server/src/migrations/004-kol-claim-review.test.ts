import { describe, expect, it } from "vitest";
import { MemorySqlDriver, MigrationRunner } from "@kunlun/db";
import { migrations } from "./index";

describe("KOL claim review migration", () => {
  it("registers candidate lookup and append-only review constraints", async () => {
    const driver = new MemorySqlDriver();
    const runner = new MigrationRunner(driver);
    await runner.migrate(migrations);
    const migration = migrations.find((item) => item.version === 4);
    expect(migration).toBeDefined();
    const candidate = migration?.up.find(
      (table) => table.name === "kol_claim_candidate_projection",
    );
    const review = migration?.up.find((table) => table.name === "kol_claim_reviews");
    expect(candidate?.constraints).toEqual(
      expect.arrayContaining([
        expect.stringContaining("PRIMARY KEY"),
        expect.stringContaining("confidence_bps"),
      ]),
    );
    expect(candidate?.columns.map((item) => item.name)).toContain("previous_available_at");
    expect(candidate?.columns.map((item) => item.name)).toContain("canonical_payload");
    expect(review?.constraints).toEqual(
      expect.arrayContaining([
        expect.stringContaining("FOREIGN KEY"),
        expect.stringContaining("decision"),
      ]),
    );
    expect(
      review?.indexes?.some(
        (item) => item.unique && item.columns.includes("submission_fingerprint"),
      ),
    ).toBe(true);
  });

  it("declares same-candidate predecessor and relation-derived single-head constraints", () => {
    const migration = migrations.find((item) => item.version === 4);
    const candidate = migration?.up.find(
      (table) => table.name === "kol_claim_candidate_projection",
    );
    const review = migration?.up.find((table) => table.name === "kol_claim_reviews");
    expect(review?.constraints).toEqual(
      expect.arrayContaining([
        expect.stringContaining(
          "FOREIGN KEY (previous_review_id, candidate_id, candidate_revision_id)",
        ),
      ]),
    );
    expect(candidate?.constraints).toEqual(
      expect.arrayContaining([
        expect.stringContaining("previous_available_at"),
        expect.stringContaining("candidate_revision_available_uq"),
      ]),
    );
    expect(review?.indexes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          name: "kol_claim_reviews_root_uq",
          unique: true,
          predicate: "previous_review_id IS NULL",
        }),
      ]),
    );
  });
});
