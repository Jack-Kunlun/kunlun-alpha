import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MarketRegimeView } from "./market-regime-page";

describe("MarketRegimeView states", () => {
  it.each([
    ["loading", "正在加载"],
    ["empty", "暂无可回放数据"],
    ["error", "回放加载失败"],
    ["forbidden", "无权访问"],
  ] as const)("renders %s", (status, marker) => {
    const html = renderToStaticMarkup(
      <MarketRegimeView
        result={{
          status,
          data: status === "empty" ? { snapshots: [], events: [] } : null,
          error: status === "error" || status === "forbidden" ? new Error("x") : null,
        }}
      />,
    );
    expect(html).toContain(marker);
  });

  it("renders successful persisted replay", () => {
    const html = renderToStaticMarkup(
      <MarketRegimeView
        result={{
          status: "success",
          error: null,
          data: {
            snapshots: [
              {
                date: "2026-08-13",
                timestamp: "2026-08-13T01:30:00.000Z",
                score: 0.4,
                algorithmVersion: "emotion_score_v1",
                ladder: [],
                freshnessSeconds: 10,
                sampleSize: 100,
                confidence: 0.9,
                sourceVersions: ["v1"],
                evidenceIds: ["e1"],
              },
            ],
            events: [],
          },
        }}
      />,
    );
    expect(html).toContain("emotion_score_v1");
  });
});
