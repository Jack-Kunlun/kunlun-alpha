import { describe, expect, it } from "vitest";

import {
  computeSeatId,
  validateAliasPayload,
  validatePerformancePayload,
  validatePreferencePayload,
  validateSeatProfilePayload,
  validateTradePayload,
} from "./index";

const TIMES = {
  validFrom: "2026-08-24T08:00:00Z",
  validTo: "2026-08-27T08:00:00Z",
  availableTime: "2026-08-24T08:01:00Z",
};

async function profilePayload(): Promise<Record<string, unknown>> {
  return {
    schemaVersion: "seat-profile-v1",
    seatIdAlgorithm: "seat-id-v1",
    seatId: await computeSeatId("broker:alpha-001"),
    identityKey: "broker:alpha-001",
    seatKind: "BROKER_BRANCH",
    canonicalName: "Alpha Branch",
    ...TIMES,
    revisionId: "profile-rev-1",
    previousRevisionId: null,
    source: "seat-master",
    sourceVersion: "2026-08",
    evidenceId: "evidence-profile-1",
    lineage: [],
  };
}

function validTradePayload(): Record<string, unknown> {
  return {
    schemaVersion: "seat-trade-v1",
    tradeId: "trade-1",
    revisionId: "trade-1-rev-1",
    previousRevisionId: null,
    seatId: "seat-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    rawSeatName: "Alpha Branch",
    instrumentId: "600519.SH",
    tradeDate: "2026-08-21",
    currency: "CNY",
    buyAmount: "999999999999999999999999999999.1200",
    sellAmount: "0.0001",
    netAmount: "999999999999999999999999999999.1199",
    source: "exchange-disclosure",
    sourceVersion: "2026-08",
    rawRecordId: "raw-lhb-1",
    evidenceId: "evidence-trade-1",
    availableTime: "2026-08-24T08:01:00Z",
  };
}

describe("seat runtime identity validator", () => {
  it("computes and verifies the versioned identity without Number conversion", async () => {
    const seatId = await computeSeatId("broker:alpha-001");
    const result = await validateSeatProfilePayload({
      ...(await profilePayload()),
      seatId,
    });
    expect(result).toEqual({ valid: true, errors: [] });

    const forged = await validateSeatProfilePayload({
      ...(await profilePayload()),
      seatId: "seat-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    });
    expect(forged.valid).toBe(false);
  });

  it("rejects invalid time and lineage invariants", async () => {
    const invalidTime = await profilePayload();
    invalidTime.validTo = invalidTime.validFrom;
    expect((await validateSeatProfilePayload(invalidTime)).valid).toBe(false);

    const invalidLineage = await profilePayload();
    invalidLineage.lineage = [
      {
        lineageId: "lineage-1",
        relation: "MERGE",
        predecessorSeatIds: [invalidLineage.seatId],
        successorSeatIds: [invalidLineage.seatId],
        effectiveAt: invalidLineage.validFrom,
        source: "seat-master",
        sourceVersion: "2026-08",
        evidenceId: "evidence-lineage-1",
        revisionId: "lineage-1-rev-1",
      },
    ];
    const result = await validateSeatProfilePayload(invalidLineage);
    expect(result.valid).toBe(false);
    expect(result.errors.join(" ")).toMatch(/lineage|predecessor|successor|self/i);
  });

  it("rejects invalid enum values and malformed lineage seat ids through the public entry", async () => {
    const invalidKind = await profilePayload();
    invalidKind.seatKind = "ROBOT";
    expect((await validateSeatProfilePayload(invalidKind)).errors.join(" ")).toMatch(/seatKind/i);

    const invalidMember = await profilePayload();
    invalidMember.lineage = [
      {
        lineageId: "lineage-invalid-member",
        relation: "MERGE",
        predecessorSeatIds: [
          "not-a-seat-id",
          "seat-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        ],
        successorSeatIds: [invalidMember.seatId],
        effectiveAt: invalidMember.validFrom,
        source: "seat-master",
        sourceVersion: "2026-08",
        evidenceId: "evidence-lineage-invalid-member",
        revisionId: "lineage-invalid-member-rev-1",
      },
    ];
    expect((await validateSeatProfilePayload(invalidMember)).errors.join(" ")).toMatch(
      /predecessorSeatIds.*seat-/i,
    );
  });

  it("rejects duplicate lineage, out-of-range effectiveAt, and invalid cardinality", async () => {
    const duplicate = await profilePayload();
    const predecessorA = "seat-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const predecessorB = "seat-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    const merge = {
      lineageId: "lineage-duplicate",
      relation: "MERGE",
      predecessorSeatIds: [predecessorA, predecessorB],
      successorSeatIds: [duplicate.seatId],
      effectiveAt: duplicate.validFrom,
      source: "seat-master",
      sourceVersion: "2026-08",
      evidenceId: "evidence-lineage-duplicate",
      revisionId: "lineage-duplicate-rev-1",
    };
    duplicate.lineage = [merge, { ...merge }];
    expect((await validateSeatProfilePayload(duplicate)).errors.join(" ")).toMatch(
      /unique|duplicate/i,
    );

    const outOfRange = await profilePayload();
    outOfRange.lineage = [
      { ...merge, lineageId: "lineage-out-of-range", effectiveAt: outOfRange.validTo },
    ];
    expect((await validateSeatProfilePayload(outOfRange)).errors.join(" ")).toMatch(
      /half-open|inside|effectiveAt/i,
    );

    const invalidSplit = await profilePayload();
    invalidSplit.lineage = [
      {
        ...merge,
        lineageId: "lineage-invalid-split",
        relation: "SPLIT",
        predecessorSeatIds: [invalidSplit.seatId],
        successorSeatIds: [predecessorA],
      },
    ];
    expect((await validateSeatProfilePayload(invalidSplit)).errors.join(" ")).toMatch(
      /SPLIT|successor/i,
    );
  });
});

describe("seat runtime contract validators", () => {
  it("rejects invalid alias enum values", () => {
    expect(
      validateAliasPayload({
        schemaVersion: "alias-v1",
        aliasId: "alias-invalid-type",
        seatId: "seat-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        name: "Alpha Branch",
        aliasType: "ROBOT",
        validFrom: TIMES.validFrom,
        validTo: null,
        availableTime: TIMES.availableTime,
        source: "seat-master",
        sourceVersion: "2026-08",
        evidenceId: "evidence-alias-invalid-type",
        revisionId: "alias-invalid-type-rev-1",
        previousRevisionId: null,
      }).valid,
    ).toBe(false);
  });

  it("checks revision chains for alias, performance and preference", () => {
    expect(
      validateAliasPayload({
        schemaVersion: "alias-v1",
        aliasId: "alias-1",
        seatId: "seat-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        name: "Alpha Branch",
        aliasType: "OFFICIAL",
        validFrom: TIMES.validFrom,
        validTo: null,
        availableTime: TIMES.availableTime,
        source: "seat-master",
        sourceVersion: "2026-08",
        evidenceId: "evidence-alias-1",
        revisionId: "same",
        previousRevisionId: "same",
      }).valid,
    ).toBe(false);
    expect(
      validatePerformancePayload({
        schemaVersion: "seat-performance-v1",
        performanceId: "performance-1",
        seatId: "seat-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        windowStart: "2026-08-01",
        windowEnd: "2026-08-21",
        calculationVersion: "seat-performance-v1",
        sampleCount: 1,
        tPlus1Return: "0.0100",
        tPlus3Return: null,
        tPlus5Return: null,
        winRate: "1.0000",
        maxDrawdown: "0.0000",
        source: "feature-job",
        sourceVersion: "2026-08",
        evidenceId: "evidence-performance-1",
        revisionId: "same",
        previousRevisionId: "same",
        availableTime: TIMES.availableTime,
      }).valid,
    ).toBe(false);
    expect(
      validatePreferencePayload({
        schemaVersion: "seat-preference-v1",
        preferenceId: "preference-1",
        seatId: "seat-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        validFrom: TIMES.validFrom,
        validTo: null,
        preferenceVersion: "seat-preference-v1",
        styleTags: ["momentum"],
        confidenceBps: 7000,
        source: "feature-job",
        sourceVersion: "2026-08",
        evidenceId: "evidence-preference-1",
        revisionId: "same",
        previousRevisionId: "same",
        availableTime: TIMES.availableTime,
      }).valid,
    ).toBe(false);
  });

  it("checks revision chains for profile and trade", async () => {
    const profile = await profilePayload();
    profile.previousRevisionId = profile.revisionId;
    expect((await validateSeatProfilePayload(profile)).valid).toBe(false);

    const trade = validTradePayload();
    trade.previousRevisionId = trade.revisionId;
    expect(validateTradePayload(trade).valid).toBe(false);
  });

  it("uses exact decimal strings for large amounts and rejects number/negative inputs", () => {
    expect(validateTradePayload(validTradePayload())).toEqual({ valid: true, errors: [] });
    expect(validateTradePayload({ ...validTradePayload(), buyAmount: 1.0 })).toMatchObject({
      valid: false,
    });
    expect(validateTradePayload({ ...validTradePayload(), sellAmount: "-0.0001" })).toMatchObject({
      valid: false,
    });
    expect(
      validateTradePayload({
        ...validTradePayload(),
        netAmount: "999999999999999999999999999999.1200",
      }),
    ).toMatchObject({ valid: false });
  });
});
