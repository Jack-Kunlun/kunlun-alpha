import { describe, expect, it } from "vitest";
import { validateSectorMembershipPayload, validateSectorPayload } from "./pit-validation";

const provenance = {
  source: "local-curated-reference",
  sourceVersion: "2026.08.30.1",
  availableTime: "2026-08-29T16:00:00Z",
  evidenceId: "repo:data/reference/local-terminal-instruments-v1.json",
};

describe("persisted point-in-time validation", () => {
  it("accepts null as the open-ended sector validity boundary", () => {
    expect(
      validateSectorPayload({
        sectorId: "cn-industry-food-beverage",
        name: "食品饮料",
        parentId: null,
        kind: "INDUSTRY",
        ...provenance,
        validFrom: "2026-08-30",
        validTo: null,
        aliases: [],
      }),
    ).toMatchObject({ validTo: null });
  });

  it("accepts null as the open-ended membership validity boundary", () => {
    expect(
      validateSectorMembershipPayload({
        unifiedCode: "600519.SH",
        sectorId: "cn-industry-food-beverage",
        ...provenance,
        validFrom: "2026-08-30",
        validTo: null,
      }),
    ).toMatchObject({ validTo: null });
  });

  it("rejects a sector without its required validity start", () => {
    expect(() =>
      validateSectorPayload({
        sectorId: "cn-industry-food-beverage",
        name: "食品饮料",
        parentId: null,
        kind: "INDUSTRY",
        ...provenance,
        validTo: null,
        aliases: [],
      }),
    ).toThrow("invalid persisted Sector payload");
  });

  it("rejects a membership without its required validity start", () => {
    expect(() =>
      validateSectorMembershipPayload({
        unifiedCode: "600519.SH",
        sectorId: "cn-industry-food-beverage",
        ...provenance,
        validTo: null,
      }),
    ).toThrow("invalid persisted SectorMembership payload");
  });
});
