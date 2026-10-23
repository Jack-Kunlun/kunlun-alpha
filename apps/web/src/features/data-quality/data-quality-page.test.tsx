import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DataQualityPage } from "./data-quality-page";
import { useDataQuality } from "./use-data-quality";
import { useMarketCoverage } from "./use-market-coverage";
import {
  useMarketQualityEvidence,
  useMarketQualityEvidenceDetail,
} from "./use-market-quality-evidence";

vi.mock("./use-data-quality", () => ({ useDataQuality: vi.fn() }));
vi.mock("./use-market-coverage", () => ({ useMarketCoverage: vi.fn() }));
vi.mock("./use-market-quality-evidence", () => ({
  useMarketQualityEvidence: vi.fn(),
  useMarketQualityEvidenceDetail: vi.fn(),
}));

const mockedUseDataQuality = vi.mocked(useDataQuality);
const mockedUseMarketCoverage = vi.mocked(useMarketCoverage);
const mockedUseMarketQualityEvidence = vi.mocked(useMarketQualityEvidence);
const mockedUseMarketQualityEvidenceDetail = vi.mocked(useMarketQualityEvidenceDetail);

const coverage = {
  schemaVersion: "market-data-coverage-v1" as const,
  scope: "DAILY_RAW_SUPPORTED_SOURCES" as const,
  meaning: "OBSERVED_ONLY" as const,
  window: {
    dateFrom: "2026-09-01",
    dateTo: "2026-09-04",
    asOf: "2026-09-05T02:00:00.000Z",
  },
  rows: [],
  truncated: false,
};

const evidencePage = {
  schemaVersion: "market-quality-evidence-v1" as const,
  snapshotId: "a".repeat(64),
  publishedAt: "2026-09-05T02:00:00.000Z",
  snapshotRecordCount: 0,
  matchingRecordCount: 0,
  offset: 0,
  limit: 20,
  hasMore: false,
  records: [],
};

describe("DataQualityPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseMarketCoverage.mockReturnValue({ status: "success", data: coverage, error: null });
    mockedUseMarketQualityEvidence.mockReturnValue({
      status: "success",
      data: evidencePage,
      error: null,
    });
    mockedUseMarketQualityEvidenceDetail.mockReturnValue({
      status: "empty",
      data: null,
      error: null,
    });
  });

  it("presents only daily coverage and market evidence with accessible filters", () => {
    const html = renderToStaticMarkup(<DataQualityPage />);

    expect(html).toContain("日线入库概览");
    expect(html).toContain("行情质量证据");
    expect(html).not.toContain("基金质量事件");
    expect(mockedUseDataQuality).not.toHaveBeenCalled();
    expect(html).toContain('for="dq-date"');
    expect(html).toContain('type="date"');
    expect(html).toContain('for="dq-source"');
    expect(html).toContain('for="dq-code"');
    expect(html).toContain('for="dq-evidence-status"');
    expect(html).toContain("查询");
    expect(html).toContain("重置");
    const queryButton = html.match(/<button\b[^>]*type="submit"[^>]*>/)?.[0];
    expect(queryButton).toBeDefined();
    expect(queryButton).toContain('disabled=""');
    expect(queryButton).toContain('aria-busy="true"');
    expect(html).toContain("快照发布时间");
    expect(html).toContain("日期筛选按证据请求窗口与输入日期是否相交");
  });

  it("keeps coverage and evidence failures independent", () => {
    mockedUseMarketCoverage.mockReturnValue({
      status: "error",
      data: null,
      error: new Error("coverage secret"),
    });
    const html = renderToStaticMarkup(<DataQualityPage />);

    expect(html).toContain("日线行情覆盖加载失败");
    expect(html).toContain("当前公开快照没有行情质量证据记录");
    expect(html).toContain("快照发布时间");
    expect(html).not.toContain("coverage secret");
    expect(html).not.toContain("基金质量事件");
  });

  it("does not equate an empty coverage result with an empty evidence snapshot", () => {
    mockedUseMarketQualityEvidence.mockReturnValue({
      status: "success",
      data: { ...evidencePage, snapshotRecordCount: 1, matchingRecordCount: 0 },
      error: null,
    });
    const html = renderToStaticMarkup(<DataQualityPage />);

    expect(html).toContain("当前条件下暂无已观测到的日线行情");
    expect(html).toContain("当前筛选条件下暂无行情质量证据记录");
    expect(html).toContain("快照发布时间");
  });
});
