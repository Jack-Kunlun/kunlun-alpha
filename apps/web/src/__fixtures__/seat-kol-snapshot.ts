import type { SeatKolWorkbenchSnapshot } from "@kunlun/shared-types";

export const LOCAL_PREVIEW_SEAT_KOL_SNAPSHOT = {
  schemaVersion: "seat-kol-workbench-v1",
  snapshotId: "1".repeat(64),
  decisionTime: "2026-08-25T08:00:00.000Z",
  dataCutoffTime: "2026-08-25T06:00:00.000Z",
  sourceVersion: "seat-kol-local-preview-v1",
  mode: "LOCAL_PREVIEW",
  dataMeaning: "RESEARCH_ONLY_PUBLIC_DATA_NOT_BROKER_EXECUTION",
  seats: [
    {
      seatId: `seat-${"a".repeat(64)}`,
      displayName: "华东示例营业部",
      seatKind: "BROKER_BRANCH",
      aliases: ["华东样例席位"],
      metrics: [
        {
          metricName: "seat_t_plus_1_return_bps",
          label: "公开上榜后 T+1",
          valueBps: 328,
          sampleCount: 42,
          confidenceBps: 7600,
          algorithmVersion: "seat-performance-v1",
          policyVersion: "seat-performance-policy-v1",
          dataCutoffTime: "2026-08-25T06:00:00.000Z",
        },
      ],
      evidence: [
        {
          evidenceId: "seat-evidence-1",
          source: "preview",
          sourceVersion: "v1",
          availableTime: "2026-08-25T06:00:00.000Z",
          excerpt: "公开龙虎榜脱敏证据",
          locator: "local-preview://seat/1",
        },
      ],
      timeline: [
        {
          entryId: "seat-entry-1",
          kind: "PUBLIC_TRADE",
          occurTime: "2026-08-24T06:00:00.000Z",
          availableTime: "2026-08-25T06:00:00.000Z",
          title: "公开记录进入窗口",
          evidenceIds: ["seat-evidence-1"],
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
          dataCutoffTime: "2026-08-25T06:00:00.000Z",
        },
      ],
      claims: [
        {
          claimId: "claim-1",
          revisionId: "claim-1-r1",
          statement: "公开表述：关注 600519.SH",
          instrumentId: "600519.SH",
          direction: "BULLISH",
          reviewStatus: "IN_REVIEW",
          confidenceBps: 7800,
          publishTime: "2026-08-24T02:00:00.000Z",
          availableTime: "2026-08-24T02:05:00.000Z",
          deleted: false,
          claimMeaning: "PUBLIC_WORDING_CLAIM_NOT_BROKER_TRADE",
          evidence: [
            {
              evidenceId: "kol-evidence-1",
              source: "preview",
              sourceVersion: "v1",
              availableTime: "2026-08-24T02:05:00.000Z",
              excerpt: "公开表述脱敏证据",
              locator: "local-preview://kol/1",
            },
          ],
        },
      ],
      evidence: [
        {
          evidenceId: "kol-evidence-1",
          source: "preview",
          sourceVersion: "v1",
          availableTime: "2026-08-24T02:05:00.000Z",
          excerpt: "公开表述脱敏证据",
          locator: "local-preview://kol/1",
        },
      ],
      timeline: [
        {
          entryId: "kol-entry-1",
          kind: "CLAIM",
          occurTime: "2026-08-24T02:00:00.000Z",
          availableTime: "2026-08-24T02:05:00.000Z",
          title: "公开表述进入审核",
          evidenceIds: ["kol-evidence-1"],
        },
      ],
    },
  ],
  cooccurrences: [
    {
      cooccurrenceId: "co-1",
      leftEntityType: "SEAT",
      leftEntityId: `seat-${"a".repeat(64)}`,
      leftDisplayName: "华东示例营业部",
      rightEntityType: "KOL",
      rightEntityId: "kol-preview-1",
      rightDisplayName: "公开内容样例 KOL",
      scoreBps: 6420,
      sampleCount: 8,
      algorithmVersion: "seat-kol-cooccurrence-v1",
      policyVersion: "seat-kol-cooccurrence-policy-v1",
      dataCutoffTime: "2026-08-25T06:00:00.000Z",
      evidenceIds: ["seat-evidence-1", "kol-evidence-1"],
    },
  ],
  reviewQueue: [
    {
      candidateId: "candidate-1",
      revisionId: "candidate-1-r1",
      statement: "公开表述：关注 600519.SH",
      instrumentId: "600519.SH",
      confidenceBps: 7800,
      reviewStatus: "IN_REVIEW",
      availableTime: "2026-08-24T02:05:00.000Z",
      reviewMeaning: "PUBLIC_WORDING_REVIEW_NOT_FACT_OR_EXECUTION",
      evidence: [
        {
          evidenceId: "kol-evidence-1",
          source: "preview",
          sourceVersion: "v1",
          availableTime: "2026-08-24T02:05:00.000Z",
          excerpt: "公开表述脱敏证据",
          locator: "local-preview://kol/1",
        },
      ],
    },
  ],
} satisfies SeatKolWorkbenchSnapshot;
