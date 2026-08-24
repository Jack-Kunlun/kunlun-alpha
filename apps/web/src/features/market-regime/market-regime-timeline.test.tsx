import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MarketRegimeTimeline } from "./market-regime-timeline";
import type { MarketEmotionSnapshot, SectorRotationEvent } from "./types";

const snapshots: MarketEmotionSnapshot[] = [
  {
    date: "2026-08-13",
    timestamp: "2026-08-13T01:30:00.000Z",
    score: 0.4,
    algorithmVersion: "emotion_score_v1",
    ladder: [{ board: 2, count: 3 }],
    freshnessSeconds: 12,
    sampleSize: 100,
    confidence: 0.9,
    sourceVersions: ["limit-v2"],
    evidenceIds: ["snapshot-1"],
  },
];

const events: SectorRotationEvent[] = [
  {
    eventId: "a".repeat(64),
    date: "2026-08-13",
    eventType: "CROSSOVER",
    fromSector: "黄金",
    toSector: "白银",
    timestamp: "2026-08-13T01:35:00.000Z",
    confidence: 0.8,
    evidenceStart: "2026-08-13T01:30:00.000Z",
    evidenceEnd: "2026-08-13T01:35:00.000Z",
    sampleSize: 6,
    algorithmVersion: "rotation_event_v2",
    sourceVersions: ["snapshot-v2"],
    evidenceIds: ["event-1"],
  },
];

describe("MarketRegimeTimeline", () => {
  it("shows version, freshness, sample and confidence", () => {
    const html = renderToStaticMarkup(
      <MarketRegimeTimeline snapshots={snapshots} events={events} />,
    );
    expect(html).toContain("emotion_score_v1");
    expect(html).toContain("100");
    expect(html).toContain("12s");
    expect(html).toContain("90%");
  });

  it("renders rotation direction and evidence window", () => {
    const html = renderToStaticMarkup(
      <MarketRegimeTimeline snapshots={snapshots} events={events} />,
    );
    expect(html).toContain("黄金");
    expect(html).toContain("白银");
    expect(html).toContain("rotation_event_v2");
  });

  it("renders independent empty regions", () => {
    const html = renderToStaticMarkup(<MarketRegimeTimeline snapshots={[]} events={[]} />);
    expect(html).toContain("暂无情绪快照");
    expect(html).toContain("暂无轮动事件");
  });
});
