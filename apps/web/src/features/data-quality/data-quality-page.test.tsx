import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DataQualityRecord } from "./types";
import { DataQualityPage } from "./data-quality-page";
import { useDataQuality } from "./use-data-quality";
import { useMarketCoverage } from "./use-market-coverage";
import {
  useMarketQualityEvidence,
  useMarketQualityEvidenceDetail,
} from "./use-market-quality-evidence";

vi.mock("./use-data-quality", () => ({
  useDataQuality: vi.fn(),
  evidenceUrl: (id: string) => `/v1/data-quality/${encodeURIComponent(id)}/evidence`,
}));
vi.mock("./use-market-coverage", () => ({
  useMarketCoverage: vi.fn(),
}));
vi.mock("./use-market-quality-evidence", () => ({
  useMarketQualityEvidence: vi.fn(),
  useMarketQualityEvidenceDetail: vi.fn(),
}));

const mockedUseDataQuality = vi.mocked(useDataQuality);
const mockedUseMarketCoverage = vi.mocked(useMarketCoverage);
const mockedUseMarketQualityEvidence = vi.mocked(useMarketQualityEvidence);
const mockedUseMarketQualityEvidenceDetail = vi.mocked(useMarketQualityEvidenceDetail);

const sample: DataQualityRecord = {
  id: "fund-conflict-aaa",
  kind: "SOURCE_CONFLICT",
  unifiedCode: "600519.SH",
  date: "2026-08-13",
  source: "provider-a",
  detail: "多来源观测不一致，未选择权威值",
  createdAt: "2026-08-13T09:30:00.000Z",
  availableAt: "2026-08-13T09:30:00.000Z",
  schemaVersion: "fund-v1",
};

const coverage = {
  schemaVersion: "market-data-coverage-v1" as const,
  scope: "DAILY_RAW_SUPPORTED_SOURCES" as const,
  meaning: "OBSERVED_ONLY" as const,
  window: {
    dateFrom: "2026-09-01",
    dateTo: "2026-09-04",
    asOf: "2026-09-05T02:00:00.000Z",
  },
  rows: [
    {
      unifiedCode: "600519.SH",
      source: "tushare-pro" as const,
      observedBarDays: 2,
      firstDate: "2026-09-03",
      lastDate: "2026-09-04",
      latestEventTime: "2026-09-04T07:00:00.000Z",
      latestAvailableTime: "2026-09-04T07:01:00.000Z",
      latestProcessingTime: "2026-09-04T07:02:00.000Z",
    },
  ],
  truncated: false,
};

describe("DataQualityPage states", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseMarketCoverage.mockReturnValue({ status: "success", data: coverage, error: null });
    mockedUseMarketQualityEvidence.mockReturnValue({
      status: "success",
      data: {
        schemaVersion: "market-quality-evidence-v1",
        snapshotId: "a".repeat(64),
        publishedAt: "2026-09-05T02:00:00.000Z",
        snapshotRecordCount: 0,
        matchingRecordCount: 0,
        offset: 0,
        limit: 20,
        hasMore: false,
        records: [],
      },
      error: null,
    });
    mockedUseMarketQualityEvidenceDetail.mockReturnValue({
      status: "empty",
      data: null,
      error: null,
    });
  });

  it("renders the loading state", () => {
    mockedUseDataQuality.mockReturnValue({ status: "loading", data: null, error: null });
    expect(renderToStaticMarkup(<DataQualityPage />)).toContain("加载中");
  });

  it("renders the empty state", () => {
    mockedUseDataQuality.mockReturnValue({ status: "empty", data: [], error: null });
    expect(renderToStaticMarkup(<DataQualityPage />)).toContain(
      "当前条件下暂无已记录的基金质量事件",
    );
  });

  it("renders the error state", () => {
    mockedUseDataQuality.mockReturnValue({ status: "error", data: null, error: new Error("boom") });
    const html = renderToStaticMarkup(<DataQualityPage />);
    expect(html).toContain("基金质量事件加载失败");
    expect(html).not.toContain("boom");
  });

  it("renders the forbidden state", () => {
    mockedUseDataQuality.mockReturnValue({
      status: "forbidden",
      data: null,
      error: new Error("denied"),
    });
    expect(renderToStaticMarkup(<DataQualityPage />)).toContain("无权访问");
  });

  it("renders the success state with the detail panel", () => {
    mockedUseDataQuality.mockReturnValue({ status: "success", data: [sample], error: null });
    const html = renderToStaticMarkup(<DataQualityPage />);
    expect(html).toContain("SOURCE_CONFLICT");
    expect(html).toContain("600519.SH");
    expect(html).toContain('href="/v1/data-quality/fund-conflict-aaa/evidence"');
    expect(html).toContain("日线入库概览");
    expect(html).toContain("观测日数");
    expect(html).toContain("查看已入库日期");
  });

  it("associates labels with inputs for keyboard and screen-reader access", () => {
    mockedUseDataQuality.mockReturnValue({ status: "success", data: [sample], error: null });
    const html = renderToStaticMarkup(<DataQualityPage />);
    expect(html).toContain('for="dq-date"');
    expect(html).toContain('for="dq-source"');
    expect(html).toContain('for="dq-code"');
    expect(html).toContain('type="submit"');
  });

  it("announces loading and error states with live-region roles", () => {
    mockedUseDataQuality.mockReturnValue({ status: "loading", data: null, error: null });
    expect(renderToStaticMarkup(<DataQualityPage />)).toContain('role="status"');

    mockedUseDataQuality.mockReturnValue({ status: "error", data: null, error: new Error("x") });
    expect(renderToStaticMarkup(<DataQualityPage />)).toContain('role="alert"');

    mockedUseDataQuality.mockReturnValue({
      status: "forbidden",
      data: null,
      error: new Error("x"),
    });
    expect(renderToStaticMarkup(<DataQualityPage />)).toContain('role="alert"');
  });

  it("keeps coverage states independent from fund quality events", () => {
    mockedUseDataQuality.mockReturnValue({ status: "success", data: [sample], error: null });
    mockedUseMarketCoverage.mockReturnValue({
      status: "error",
      data: null,
      error: new Error("raw failure"),
    });
    const html = renderToStaticMarkup(<DataQualityPage />);
    expect(html).toContain("SOURCE_CONFLICT");
    expect(html).toContain("日线行情覆盖加载失败");
    expect(html).not.toContain("raw failure");
  });
});
