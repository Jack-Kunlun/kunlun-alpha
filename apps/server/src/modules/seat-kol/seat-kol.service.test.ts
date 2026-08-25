import { ForbiddenException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import {
  InMemorySeatKolWorkbenchRepository,
  LOCAL_PREVIEW_SEAT_KOL_SNAPSHOT,
} from "./in-memory-seat-kol.repository";
import { SeatKolWorkbenchService } from "./seat-kol.service";

const AS_OF = "2026-08-25T09:00:00.000Z";

describe("SeatKolWorkbenchService", () => {
  it("returns a filtered point-in-time snapshot with auditable metrics", async () => {
    const service = new SeatKolWorkbenchService(
      new InMemorySeatKolWorkbenchRepository([LOCAL_PREVIEW_SEAT_KOL_SNAPSHOT]),
    );
    const [snapshot] = await service.workbench({
      asOf: AS_OF,
      entityType: "KOL",
      reviewStatus: "IN_REVIEW",
      query: "600519.SH",
    });
    expect(snapshot?.seats).toEqual([]);
    expect(snapshot?.kols).toHaveLength(1);
    expect(snapshot?.reviewQueue).toHaveLength(1);
    expect(snapshot?.kols[0]?.claims[0]?.claimMeaning).toBe(
      "PUBLIC_WORDING_CLAIM_NOT_BROKER_TRADE",
    );
    for (const metric of snapshot?.kols[0]?.metrics ?? []) {
      expect(metric).toMatchObject({
        algorithmVersion: expect.any(String),
        policyVersion: expect.any(String),
        sampleCount: expect.any(Number),
        dataCutoffTime: expect.any(String),
      });
    }
  });

  it("returns empty before the snapshot and rejects unknown filters", async () => {
    const service = new SeatKolWorkbenchService(
      new InMemorySeatKolWorkbenchRepository([LOCAL_PREVIEW_SEAT_KOL_SNAPSHOT]),
    );
    await expect(service.workbench({ asOf: "2026-08-25T07:59:59.000Z" })).resolves.toEqual([]);
    await expect(service.workbench({ asOf: AS_OF, rawSql: "DROP" })).rejects.toThrow(
      "unknown filter",
    );
  });

  it("supports a controlled forbidden state", async () => {
    const service = new SeatKolWorkbenchService(new InMemorySeatKolWorkbenchRepository(), {
      canRead: async () => false,
    });
    await expect(service.workbench({ asOf: AS_OF })).rejects.toThrow(ForbiddenException);
  });
});
