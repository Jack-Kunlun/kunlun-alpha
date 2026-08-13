import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MarketRegimeTimeline, type EmotionSnapshot } from "./market-regime-timeline";

const snapshots: EmotionSnapshot[] = [
  {
    date: "2026-08-13",
    timestamp: "2026-08-13T01:30:00.000Z",
    score: 0.4,
    version: "emotion_score_v1",
    ladder: [{ board: 2, count: 3 }],
  },
  {
    date: "2026-08-13",
    timestamp: "2026-08-13T01:31:00.000Z",
    score: 0.5,
    version: "emotion_score_v1",
    ladder: [{ board: 3, count: 2 }],
  },
];

describe("MarketRegimeTimeline", () => {
  it("renders the minute timeline with scores", () => {
    const html = renderToStaticMarkup(<MarketRegimeTimeline snapshots={snapshots} />);
    expect(html).toContain("0.400");
    expect(html).toContain("0.500");
    expect(html).toContain("2板×3");
  });

  it("shows the algorithm version", () => {
    const html = renderToStaticMarkup(<MarketRegimeTimeline snapshots={snapshots} />);
    expect(html).toContain("emotion_score_v1");
  });

  it("renders an empty state without snapshots", () => {
    const html = renderToStaticMarkup(<MarketRegimeTimeline snapshots={[]} />);
    expect(html).toContain("该交易日暂无快照");
  });
});
