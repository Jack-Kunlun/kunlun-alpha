import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MarketQualityEvidencePage } from "@kunlun/shared-types";
import { MarketQualityEvidencePanel } from "./market-quality-evidence-panel";
import { useMarketQualityEvidenceDetail } from "./use-market-quality-evidence";

vi.mock("./use-market-quality-evidence", () => ({
  useMarketQualityEvidenceDetail: vi.fn(),
}));

const mockedDetail = vi.mocked(useMarketQualityEvidenceDetail);
const emptyPage: MarketQualityEvidencePage = {
  schemaVersion: "market-quality-evidence-v1",
  snapshotId: "a".repeat(64),
  publishedAt: "2026-09-01T01:02:00.000Z",
  snapshotRecordCount: 0,
  matchingRecordCount: 0,
  offset: 0,
  limit: 20,
  hasMore: false,
  records: [],
};

describe("MarketQualityEvidencePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedDetail.mockReturnValue({ status: "empty", data: null, error: null });
  });

  it("distinguishes unavailable, forbidden, complete-empty, and filtered-empty states", () => {
    expect(
      renderToStaticMarkup(
        <MarketQualityEvidencePanel
          result={{ status: "error", data: null, error: new Error("secret") }}
          onPrevious={() => undefined}
          onNext={() => undefined}
        />,
      ),
    ).toContain("行情质量证据暂不可用");
    expect(
      renderToStaticMarkup(
        <MarketQualityEvidencePanel
          result={{ status: "forbidden", data: null, error: new Error("secret") }}
          onPrevious={() => undefined}
          onNext={() => undefined}
        />,
      ),
    ).toContain("无权访问行情质量证据");
    const completeEmpty = renderToStaticMarkup(
      <MarketQualityEvidencePanel
        result={{ status: "success", data: emptyPage, error: null }}
        onPrevious={() => undefined}
        onNext={() => undefined}
      />,
    );
    expect(completeEmpty).toContain("当前公开快照没有行情质量证据记录");
    expect(completeEmpty).toContain("不表示行情没有质量问题");
    expect(
      renderToStaticMarkup(
        <MarketQualityEvidencePanel
          result={{
            status: "success",
            data: { ...emptyPage, snapshotRecordCount: 1, matchingRecordCount: 0 },
            error: null,
          }}
          onPrevious={() => undefined}
          onNext={() => undefined}
        />,
      ),
    ).toContain("当前筛选条件下暂无行情质量证据记录");
  });

  it("renders bounded evidence fields and snapshot pagination without raw fields", () => {
    const page: MarketQualityEvidencePage = {
      ...emptyPage,
      snapshotRecordCount: 1,
      matchingRecordCount: 1,
      hasMore: true,
      records: [
        {
          evidenceId: `mqe-${"b".repeat(64)}`,
          source: "akshare-sina",
          unifiedCode: "600519.SH",
          interval: "MINUTE_1",
          requestedStart: "2026-08-01",
          requestedEnd: "2026-08-31",
          status: "FILTERED",
          reasonCode: "SINA_OVERFETCH_OUTSIDE_REQUEST",
          captureAvailableAt: "2026-09-01T01:00:00.000Z",
          qualityRecordedAt: "2026-09-01T01:01:00.000Z",
          rejectedRecordCount: 0,
          qualityEventCount: 0,
          filteredRecordCount: 1,
          qualityEvents: [],
          filteredRecords: [
            {
              rawRowIndex: 2,
              timestamp: "2026-09-02T01:00:00.000Z",
              requestedStart: "2026-08-01",
              requestedEnd: "2026-08-31",
              reasonCode: "SINA_OVERFETCH_OUTSIDE_REQUEST",
            },
          ],
        },
      ],
    };
    const html = renderToStaticMarkup(
      <MarketQualityEvidencePanel
        result={{ status: "success", data: page, error: null }}
        onPrevious={() => undefined}
        onNext={() => undefined}
      />,
    );
    expect(html).toContain("SINA_OVERFETCH_OUTSIDE_REQUEST");
    expect(html).toContain("固定快照");
    expect(html).toContain("查看详情");
    expect(html).not.toContain("rawChecksum");
    expect(html).not.toContain("secret-sentinel");
  });
});
