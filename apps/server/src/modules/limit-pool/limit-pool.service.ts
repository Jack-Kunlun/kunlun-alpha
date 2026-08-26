import type { LimitPoolLadderLevel, LimitPoolTerminalSnapshot } from "@kunlun/shared-types";
import { ForbiddenException, Inject, Injectable } from "@nestjs/common";
import type { LimitPoolAuthorizer } from "./limit-pool-authorizer";
import type { ParsedLimitPoolQuery } from "./limit-pool-query";
import type { LimitPoolRepository, StoredLimitPoolSnapshot } from "./limit-pool.repository";
import { LIMIT_POOL_AUTHORIZER, LIMIT_POOL_REPOSITORY } from "./limit-pool.tokens";

function unique(values: readonly string[]): string[] {
  return [...new Set(values)].sort();
}

function assertSnapshot(snapshot: StoredLimitPoolSnapshot, asOf: string): void {
  if (Date.parse(snapshot.eventTime) > Date.parse(snapshot.availableTime)) {
    throw new Error("limit-pool event time is after available time");
  }
  if (
    Date.parse(snapshot.eventTime) > Date.parse(asOf) ||
    Date.parse(snapshot.availableTime) > Date.parse(asOf)
  ) {
    throw new Error("limit-pool repository returned future data");
  }
  const { payload } = snapshot;
  const identities = new Set<string>();
  const topSources = new Set(snapshot.sourceVersions);
  const topEvidence = new Set(snapshot.evidenceIds);
  for (const entry of payload.entries) {
    if (identities.has(entry.instrumentId)) {
      throw new Error("duplicate instrument evidence identity");
    }
    identities.add(entry.instrumentId);
    if (
      Date.parse(entry.eventTime) > Date.parse(entry.availableTime) ||
      Date.parse(entry.eventTime) > Date.parse(snapshot.eventTime) ||
      Date.parse(entry.availableTime) > Date.parse(snapshot.availableTime) ||
      Date.parse(entry.eventTime) > Date.parse(asOf) ||
      Date.parse(entry.availableTime) > Date.parse(asOf)
    ) {
      throw new Error("instrument evidence is not point-in-time eligible");
    }
    if (!topSources.has(entry.sourceVersion) || !topEvidence.has(entry.evidenceId)) {
      throw new Error("instrument evidence is missing from snapshot provenance");
    }
    if (
      entry.firstSealTime !== null &&
      Date.parse(entry.firstSealTime) > Date.parse(entry.eventTime)
    ) {
      throw new Error("first seal time is after instrument event time");
    }
    if (
      entry.lastSealTime !== null &&
      Date.parse(entry.lastSealTime) > Date.parse(entry.eventTime)
    ) {
      throw new Error("last seal time is after instrument event time");
    }
    if (
      entry.firstSealTime !== null &&
      entry.lastSealTime !== null &&
      Date.parse(entry.firstSealTime) > Date.parse(entry.lastSealTime)
    ) {
      throw new Error("first seal time is after last seal time");
    }
  }
  const up = payload.entries.filter((entry) => entry.side === "LIMIT_UP");
  const down = payload.entries.filter((entry) => entry.side === "LIMIT_DOWN");
  const sealed = up.filter((entry) => entry.state === "SEALED");
  if (up.length !== payload.limitUpCount) {
    throw new Error("limit-up count does not match evidence rows");
  }
  if (down.length !== payload.limitDownCount) {
    throw new Error("limit-down count does not match evidence rows");
  }
  if (sealed.length !== payload.sealedCount) {
    throw new Error("sealed count does not match evidence rows");
  }
  if (payload.entries.reduce((sum, entry) => sum + entry.openCount, 0) !== payload.totalOpenCount) {
    throw new Error("open count does not match evidence rows");
  }

  const seenLevels = new Set<number>();
  for (const level of payload.ladder) {
    if (seenLevels.has(level.streakDays)) throw new Error("duplicate ladder level");
    seenLevels.add(level.streakDays);
    const actual = up.filter((entry) => entry.streakDays === level.streakDays).length;
    if (actual !== level.count) throw new Error("ladder count does not match evidence rows");
    if (level.promotedCount > level.count || level.promotedCount > level.previousDayEligibleCount) {
      throw new Error("invalid promotion numerator");
    }
    if (level.previousDayEligibleCount === 0 && level.promotedCount !== 0) {
      throw new Error("promotion has no eligible denominator");
    }
  }
  if (up.some((entry) => !seenLevels.has(entry.streakDays))) {
    throw new Error("limit-up evidence row is missing from ladder");
  }
}

function ladderOf(snapshot: StoredLimitPoolSnapshot): LimitPoolLadderLevel[] {
  return snapshot.payload.ladder
    .map((level) => ({
      ...level,
      promotionRateBps:
        level.previousDayEligibleCount === 0
          ? null
          : Math.round((level.promotedCount * 10_000) / level.previousDayEligibleCount),
      algorithmVersion: snapshot.ladderAlgorithmVersion,
    }))
    .sort((left, right) => right.streakDays - left.streakDays);
}

function empty(query: ParsedLimitPoolQuery): LimitPoolTerminalSnapshot {
  return {
    schemaVersion: "limit-pool-terminal-v1",
    mode: query.mode,
    requestedAsOf: query.asOf,
    tradingDate: null,
    previousTradingDate: null,
    dataCutoffTime: null,
    availableTime: null,
    completeness: "EMPTY",
    missingReasons: ["该时点没有已物化的限涨跌停算法快照"],
    freshness: { status: "NO_DATA", ageSeconds: null },
    algorithmVersion: query.algorithmVersion ?? null,
    ladderAlgorithmVersion: query.ladderAlgorithmVersion ?? null,
    limitRuleVersion: query.limitRuleVersion ?? null,
    materializerVersion: query.materializerVersion ?? null,
    revision: null,
    limitUpCount: 0,
    limitDownCount: 0,
    sealedCount: 0,
    totalOpenCount: 0,
    ladder: [],
    entries: [],
    sourceVersions: [],
    evidenceIds: [],
    dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
  };
}

@Injectable()
export class LimitPoolService {
  constructor(
    @Inject(LIMIT_POOL_REPOSITORY) private readonly repository: LimitPoolRepository,
    @Inject(LIMIT_POOL_AUTHORIZER) private readonly authorizer: LimitPoolAuthorizer,
  ) {}

  async getSnapshot(
    request: unknown,
    query: ParsedLimitPoolQuery,
  ): Promise<LimitPoolTerminalSnapshot> {
    if (!(await this.authorizer.canRead(request))) throw new ForbiddenException();
    const snapshot = await this.repository.findSnapshot({
      asOf: query.asOf,
      ...(query.algorithmVersion === undefined ? {} : { algorithmVersion: query.algorithmVersion }),
      ...(query.ladderAlgorithmVersion === undefined
        ? {}
        : { ladderAlgorithmVersion: query.ladderAlgorithmVersion }),
      ...(query.limitRuleVersion === undefined ? {} : { limitRuleVersion: query.limitRuleVersion }),
      ...(query.materializerVersion === undefined
        ? {}
        : { materializerVersion: query.materializerVersion }),
    });
    if (snapshot === null) return empty(query);
    if (
      (query.algorithmVersion !== undefined &&
        snapshot.algorithmVersion !== query.algorithmVersion) ||
      (query.ladderAlgorithmVersion !== undefined &&
        snapshot.ladderAlgorithmVersion !== query.ladderAlgorithmVersion) ||
      (query.limitRuleVersion !== undefined &&
        snapshot.limitRuleVersion !== query.limitRuleVersion) ||
      (query.materializerVersion !== undefined &&
        snapshot.materializerVersion !== query.materializerVersion)
    ) {
      throw new Error("limit-pool repository returned the wrong algorithm version");
    }
    assertSnapshot(snapshot, query.asOf);
    const ageSeconds = Math.max(
      0,
      Math.floor((Date.parse(query.asOf) - Date.parse(snapshot.eventTime)) / 1_000),
    );
    const freshnessStatus =
      query.mode === "HISTORICAL"
        ? "HISTORICAL"
        : ageSeconds <= 90
          ? "FRESH"
          : ageSeconds <= 300
            ? "DELAYED"
            : "STALE";
    return {
      schemaVersion: "limit-pool-terminal-v1",
      mode: query.mode,
      requestedAsOf: query.asOf,
      tradingDate: snapshot.tradingDate,
      previousTradingDate: snapshot.payload.previousTradingDate,
      dataCutoffTime: snapshot.eventTime,
      availableTime: snapshot.availableTime,
      completeness: snapshot.payload.completeness,
      missingReasons: [...snapshot.payload.missingReasons],
      freshness: { status: freshnessStatus, ageSeconds },
      algorithmVersion: snapshot.algorithmVersion,
      ladderAlgorithmVersion: snapshot.ladderAlgorithmVersion,
      limitRuleVersion: snapshot.limitRuleVersion,
      materializerVersion: snapshot.materializerVersion,
      revision: snapshot.revision,
      limitUpCount: snapshot.payload.limitUpCount,
      limitDownCount: snapshot.payload.limitDownCount,
      sealedCount: snapshot.payload.sealedCount,
      totalOpenCount: snapshot.payload.totalOpenCount,
      ladder: ladderOf(snapshot),
      entries: snapshot.payload.entries
        .map((entry) => ({
          ...entry,
          algorithmVersion: snapshot.algorithmVersion,
          ladderAlgorithmVersion: snapshot.ladderAlgorithmVersion,
          limitRuleVersion: snapshot.limitRuleVersion,
          materializerVersion: snapshot.materializerVersion,
          dataMeaning: "LIMIT_POOL_ALGORITHM_OUTPUT" as const,
        }))
        .sort(
          (left, right) =>
            right.streakDays - left.streakDays ||
            left.instrumentId.localeCompare(right.instrumentId),
        ),
      sourceVersions: unique(snapshot.sourceVersions),
      evidenceIds: unique(snapshot.evidenceIds),
      dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
    };
  }
}
