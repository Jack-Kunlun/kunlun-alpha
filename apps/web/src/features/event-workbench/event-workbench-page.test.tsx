import { renderToStaticMarkup } from "react-dom/server";
import type { HotTopicSnapshot, MarketEvent } from "@kunlun/shared-types";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EventWorkbenchPage } from "./event-workbench-page";
import { useEventWorkbench } from "./use-event-workbench";

vi.mock("./use-event-workbench", () => ({ useEventWorkbench: vi.fn() }));
const mocked = vi.mocked(useEventWorkbench);

const event = {
  schemaVersion: "market-event-v1",
  eventId: "a".repeat(64),
  eventType: "CORPORATE",
  headline: "样例公司发布重大事项公告",
  summary: "这是带有证据与版本的结构化事件。",
  occurTime: "2026-08-24T01:00:00.000Z",
  publishTime: "2026-08-24T01:00:00.000Z",
  availableTime: "2026-08-24T02:00:00.000Z",
  instrumentIds: ["600519.SH"],
  sectorIds: ["sector-food"],
  evidence: [
    {
      evidenceId: "b".repeat(64),
      contentRecordId: "record-1",
      contentVersionId: "c".repeat(64),
      sourceId: "cninfo",
      sourceVersion: "v1",
      availableTime: "2026-08-24T01:00:00.000Z",
      startOffset: 0,
      endOffset: 12,
      excerpt: "样例公司发布重大事项公告",
    },
  ],
  modelProvenance: {
    producerType: "MODEL",
    provider: "provider-a",
    modelId: "event-extractor",
    modelVersion: "model-v1",
    promptVersion: "event-candidate-extraction@v1",
    outputSchemaVersion: "market-event-v1",
    configurationFingerprint: "d".repeat(64),
    extractionRunId: "run-1",
    processingTime: "2026-08-24T02:00:00.000Z",
  },
  confidenceBps: 8500,
} as MarketEvent;

const topic = {
  schemaVersion: "hot-topic-snapshot-v1",
  snapshotId: "e".repeat(64),
  topicId: "topic-ai",
  topicName: "人工智能",
  lifecycle: "HOT",
  decisionTime: "2026-08-24T02:00:00.000Z",
  windowStart: "2026-08-23T02:00:00.000Z",
  windowEnd: "2026-08-24T02:00:00.000Z",
  scoreBps: 8120,
  confidenceBps: 7600,
  components: {
    evidenceQualityBps: 8500,
    recencyBps: 9000,
    sourceDiversityBps: 5000,
    breadthBps: 4000,
    momentumBps: 7000,
  },
  eventCount: 4,
  recentEventCount: 3,
  staleEventCount: 1,
  sourceCount: 2,
  instrumentCount: 2,
  sectorCount: 1,
  eventIds: [event.eventId],
  policyFingerprint: "f".repeat(64),
  algorithmVersion: "hot-score-v1",
} as HotTopicSnapshot;

describe("EventWorkbenchPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders loading, empty, error and forbidden states", () => {
    mocked.mockReturnValue({
      events: { status: "loading", data: null, error: null },
      topics: { status: "loading", data: null, error: null },
    });
    expect(renderToStaticMarkup(<EventWorkbenchPage />)).toContain("正在扫描");
    mocked.mockReturnValue({
      events: { status: "empty", data: [], error: null },
      topics: { status: "empty", data: [], error: null },
    });
    expect(renderToStaticMarkup(<EventWorkbenchPage />)).toContain("暂无可用事件");
    mocked.mockReturnValue({
      events: { status: "error", data: null, error: new Error("offline") },
      topics: { status: "empty", data: [], error: null },
    });
    expect(renderToStaticMarkup(<EventWorkbenchPage />)).toContain("数据加载失败");
    mocked.mockReturnValue({
      events: { status: "forbidden", data: null, error: new Error("denied") },
      topics: { status: "empty", data: [], error: null },
    });
    expect(renderToStaticMarkup(<EventWorkbenchPage />)).toContain("无权访问事件情报");
  });

  it("renders topic score, event facts, evidence and provenance", () => {
    mocked.mockReturnValue({
      events: { status: "success", data: [event], error: null },
      topics: { status: "success", data: [topic], error: null },
    });
    const html = renderToStaticMarkup(<EventWorkbenchPage />);
    expect(html).toContain("事件观势台");
    expect(html).toContain("人工智能");
    expect(html).toContain("81.2");
    expect(html).toContain("样例公司发布重大事项公告");
    expect(html).toContain("cninfo");
    expect(html).toContain("model-v1");
    expect(html).toContain("人工校正");
  });

  it("associates filter and feedback labels with controls", () => {
    mocked.mockReturnValue({
      events: { status: "success", data: [event], error: null },
      topics: { status: "success", data: [topic], error: null },
    });
    const html = renderToStaticMarkup(<EventWorkbenchPage />);
    for (const id of [
      "event-date-from",
      "event-date-to",
      "event-instrument",
      "event-confidence",
      "event-feedback-action",
      "event-feedback-reason",
      "event-feedback-comment",
    ]) {
      expect(html).toContain(`for="${id}"`);
    }
  });
});
