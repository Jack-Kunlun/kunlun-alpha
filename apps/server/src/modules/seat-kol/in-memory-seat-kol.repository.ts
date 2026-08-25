import type { SeatKolWorkbenchSnapshot } from "@kunlun/shared-types";
import type { SeatKolWorkbenchRepository } from "./seat-kol-repository";
import type { SeatKolWorkbenchQuery } from "./seat-kol.types";

const CUTOFF = "2026-08-25T06:00:00.000Z";
const SEAT_ID = `seat-${"a".repeat(64)}`;

const seatEvidence = {
  evidenceId: "seat-evidence-preview-1",
  source: "sse-public-preview",
  sourceVersion: "sanitized-v1",
  availableTime: CUTOFF,
  excerpt: "本地脱敏样例：公开龙虎榜席位名称与金额记录。",
  locator: "local-preview://seat/1",
} as const;

const kolEvidence = {
  evidenceId: "kol-evidence-preview-1",
  source: "public-content-preview",
  sourceVersion: "sanitized-v1",
  availableTime: CUTOFF,
  excerpt: "本地脱敏样例：公开表述提及关注 600519.SH，不代表真实成交。",
  locator: "local-preview://kol/1",
} as const;

export const LOCAL_PREVIEW_SEAT_KOL_SNAPSHOT: SeatKolWorkbenchSnapshot = {
  schemaVersion: "seat-kol-workbench-v1",
  snapshotId: "1".repeat(64),
  decisionTime: "2026-08-25T08:00:00.000Z",
  dataCutoffTime: CUTOFF,
  sourceVersion: "seat-kol-local-preview-v1",
  mode: "LOCAL_PREVIEW",
  dataMeaning: "RESEARCH_ONLY_PUBLIC_DATA_NOT_BROKER_EXECUTION",
  seats: [
    {
      seatId: SEAT_ID,
      displayName: "华东示例营业部",
      seatKind: "BROKER_BRANCH",
      aliases: ["华东样例席位", "沪市样例营业部"],
      metrics: [
        {
          metricName: "seat_t_plus_1_return_bps",
          label: "公开上榜后 T+1",
          valueBps: 328,
          sampleCount: 42,
          confidenceBps: 7600,
          algorithmVersion: "seat-performance-v1",
          policyVersion: "seat-performance-policy-v1",
          dataCutoffTime: CUTOFF,
        },
        {
          metricName: "seat_win_rate_bps",
          label: "样本胜率",
          valueBps: 5714,
          sampleCount: 42,
          confidenceBps: 7200,
          algorithmVersion: "seat-performance-v1",
          policyVersion: "seat-performance-policy-v1",
          dataCutoffTime: CUTOFF,
        },
      ],
      evidence: [seatEvidence],
      timeline: [
        {
          entryId: "seat-timeline-preview-1",
          kind: "PUBLIC_TRADE",
          occurTime: "2026-08-22T07:00:00.000Z",
          availableTime: CUTOFF,
          title: "公开龙虎榜样例记录进入研究窗口",
          evidenceIds: [seatEvidence.evidenceId],
        },
      ],
    },
  ],
  kols: [
    {
      kolId: "kol-preview-1",
      displayName: "公开内容样例 KOL",
      metrics: [
        {
          metricName: "kol_attention_score",
          label: "公开内容关注度",
          valueBps: 6840,
          sampleCount: 6,
          confidenceBps: 8100,
          algorithmVersion: "kol-feature-algorithm-v1",
          policyVersion: "kol-feature-policy-v1",
          dataCutoffTime: CUTOFF,
        },
        {
          metricName: "claim_score",
          label: "公开表述历史评分",
          valueBps: 7330,
          sampleCount: 3,
          confidenceBps: 7800,
          algorithmVersion: "kol-feature-algorithm-v1",
          policyVersion: "kol-feature-policy-v1",
          dataCutoffTime: CUTOFF,
        },
      ],
      claims: [
        {
          claimId: "claim-preview-1",
          revisionId: "claim-preview-1-r1",
          statement: "公开表述：关注 600519.SH 的后续变化。",
          instrumentId: "600519.SH",
          direction: "BULLISH",
          reviewStatus: "IN_REVIEW",
          confidenceBps: 7800,
          publishTime: "2026-08-24T02:00:00.000Z",
          availableTime: "2026-08-24T02:05:00.000Z",
          deleted: false,
          claimMeaning: "PUBLIC_WORDING_CLAIM_NOT_BROKER_TRADE",
          evidence: [kolEvidence],
        },
      ],
      evidence: [kolEvidence],
      timeline: [
        {
          entryId: "kol-timeline-preview-1",
          kind: "CLAIM",
          occurTime: "2026-08-24T02:00:00.000Z",
          availableTime: "2026-08-24T02:05:00.000Z",
          title: "公开表述进入 Claim 审核队列",
          evidenceIds: [kolEvidence.evidenceId],
        },
      ],
    },
  ],
  cooccurrences: [
    {
      cooccurrenceId: "cooccurrence-preview-1",
      leftEntityType: "SEAT",
      leftEntityId: SEAT_ID,
      leftDisplayName: "华东示例营业部",
      rightEntityType: "KOL",
      rightEntityId: "kol-preview-1",
      rightDisplayName: "公开内容样例 KOL",
      scoreBps: 6420,
      sampleCount: 8,
      algorithmVersion: "seat-kol-cooccurrence-v1",
      policyVersion: "seat-kol-cooccurrence-policy-v1",
      dataCutoffTime: CUTOFF,
      evidenceIds: [seatEvidence.evidenceId, kolEvidence.evidenceId],
    },
  ],
  reviewQueue: [
    {
      candidateId: "candidate-preview-1",
      revisionId: "candidate-preview-1-r1",
      statement: "公开表述：关注 600519.SH 的后续变化。",
      instrumentId: "600519.SH",
      confidenceBps: 7800,
      reviewStatus: "IN_REVIEW",
      availableTime: "2026-08-24T02:05:00.000Z",
      reviewMeaning: "PUBLIC_WORDING_REVIEW_NOT_FACT_OR_EXECUTION",
      evidence: [kolEvidence],
    },
  ],
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function matches(value: string, query: string): boolean {
  return value.toLocaleLowerCase("zh-CN").includes(query.toLocaleLowerCase("zh-CN"));
}

export class InMemorySeatKolWorkbenchRepository implements SeatKolWorkbenchRepository {
  constructor(private readonly snapshots: readonly SeatKolWorkbenchSnapshot[] = []) {}

  async latest(query: SeatKolWorkbenchQuery): Promise<SeatKolWorkbenchSnapshot | null> {
    const snapshot = [...this.snapshots]
      .filter((item) => item.decisionTime <= query.asOf)
      .sort((left, right) => right.decisionTime.localeCompare(left.decisionTime))[0];
    if (!snapshot) return null;

    const needle = query.query ?? "";
    const seats =
      query.entityType === "KOL"
        ? []
        : snapshot.seats.filter(
            (seat) =>
              !needle ||
              matches(seat.seatId, needle) ||
              matches(seat.displayName, needle) ||
              seat.aliases.some((alias) => matches(alias, needle)),
          );
    const kols =
      query.entityType === "SEAT"
        ? []
        : snapshot.kols.filter(
            (kol) =>
              !needle ||
              matches(kol.kolId, needle) ||
              matches(kol.displayName, needle) ||
              kol.claims.some(
                (claim) => matches(claim.statement, needle) || matches(claim.instrumentId, needle),
              ),
          );
    const visibleIds = new Set([
      ...seats.map((seat) => seat.seatId),
      ...kols.map((kol) => kol.kolId),
    ]);
    const cooccurrences = snapshot.cooccurrences.filter(
      (item) =>
        visibleIds.has(item.leftEntityId) ||
        visibleIds.has(item.rightEntityId) ||
        (!needle && query.entityType === "ALL"),
    );
    const reviewQueue =
      query.entityType === "SEAT"
        ? []
        : snapshot.reviewQueue.filter(
            (item) =>
              (query.reviewStatus === "ALL" || item.reviewStatus === query.reviewStatus) &&
              (!needle || matches(item.statement, needle) || matches(item.instrumentId, needle)),
          );

    return clone({ ...snapshot, seats, kols, cooccurrences, reviewQueue });
  }
}
