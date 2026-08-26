import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { RotationTerminalView, shanghaiLocalToIso } from "./rotation-terminal-page";
import type { RotationTerminalData, RotationTerminalResult } from "./types";

const data = {
  asOf: "2026-08-24T03:00:00.000Z",
  snapshots: [
    {
      timestamp: "2026-08-24T02:00:00.000Z",
      score: 0.42,
      confidence: 0.9,
    },
  ],
  rotationEvents: [
    {
      eventId: "a".repeat(64),
      eventType: "CROSSOVER",
      fromSector: "黄金",
      toSector: "白银",
      timestamp: "2026-08-24T02:05:00.000Z",
      evidenceStart: "2026-08-24T02:00:00.000Z",
      evidenceEnd: "2026-08-24T02:05:00.000Z",
      confidence: 0.8,
      algorithmVersion: "rotation_event_v2",
      sourceVersions: ["snapshot-v2"],
      evidenceIds: ["rotation-evidence-1"],
    },
  ],
  hotTopics: [
    {
      snapshotId: "b".repeat(64),
      topicId: "topic-ai",
      topicName: "人工智能",
      lifecycle: "HOT",
      decisionTime: "2026-08-24T02:06:00.000Z",
      windowStart: "2026-08-24T01:06:00.000Z",
      windowEnd: "2026-08-24T02:06:00.000Z",
      scoreBps: 8120,
      confidenceBps: 7600,
      eventCount: 1,
      eventIds: ["c".repeat(64)],
      policyFingerprint: "f".repeat(64),
      algorithmVersion: "hot-score-v1",
    },
  ],
  marketEvents: [
    {
      eventId: "c".repeat(64),
      headline: "AI 产业链发布新进展",
      eventType: "INDUSTRY",
      occurTime: "2026-08-24T01:30:00.000Z",
      availableTime: "2026-08-24T02:04:00.000Z",
      confidenceBps: 8500,
      evidence: [],
      modelProvenance: { modelVersion: "model-v1", promptVersion: "prompt-v1" },
    },
  ],
} as unknown as RotationTerminalData;

function view(status: RotationTerminalResult["status"]): RotationTerminalResult {
  return {
    status,
    data: status === "success" || status === "partial" || status === "empty" ? data : null,
    error: status === "error" || status === "forbidden" ? new Error("x") : null,
    continuity:
      status === "partial" || status === "empty" || status === "error"
        ? ["热点事件引用存在缺口"]
        : [],
  };
}

describe("RotationTerminalView", () => {
  it.each([
    ["loading", "正在加载"],
    ["error", "加载失败"],
    ["forbidden", "无权访问"],
  ] as const)("renders %s", (status, marker) => {
    expect(renderToStaticMarkup(<RotationTerminalView result={view(status)} />)).toContain(marker);
  });

  it("renders same-source comparison, lifecycle, versions and Shanghai timeline", () => {
    const html = renderToStaticMarkup(<RotationTerminalView result={view("success")} />);
    expect(html).toContain("热点生命周期");
    expect(html).toContain("热点得分与置信度对比图");
    expect(html).toContain("热点强度同源明细");
    expect(html).toContain("人工智能");
    expect(html).toContain("rotation_event_v2");
    expect(html).toContain("2026-08-24 10:05:00");
  });

  it("makes partial-source gaps explicit", () => {
    const html = renderToStaticMarkup(<RotationTerminalView result={view("partial")} />);
    expect(html).toContain("数据断点已显式保留");
    expect(html).toContain("热点事件引用存在缺口");
  });

  it("keeps continuity gaps visible in the empty state", () => {
    const html = renderToStaticMarkup(<RotationTerminalView result={view("empty")} />);
    expect(html).toContain("当前回放点暂无数据");
    expect(html).toContain("数据断点已显式保留");
    expect(html).toContain("热点事件引用存在缺口");
  });

  it("keeps source gaps visible in the terminal error state", () => {
    const html = renderToStaticMarkup(<RotationTerminalView result={view("error")} />);
    expect(html).toContain("轮动与热点数据加载失败");
    expect(html).toContain("数据断点已显式保留");
    expect(html).toContain("热点事件引用存在缺口");
  });

  it("converts Shanghai local replay controls to UTC", () => {
    expect(shanghaiLocalToIso("2026-08-24T15:00")).toBe("2026-08-24T07:00:00.000Z");
    expect(shanghaiLocalToIso("invalid")).toBeNull();
  });
});
