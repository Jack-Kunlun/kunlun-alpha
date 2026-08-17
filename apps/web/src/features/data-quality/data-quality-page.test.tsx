import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DataQualityRecord } from "./types";
import { DataQualityPage } from "./data-quality-page";
import { useDataQuality } from "./use-data-quality";

vi.mock("./use-data-quality", () => ({
  useDataQuality: vi.fn(),
  evidenceUrl: (id: string) => `/v1/data-quality/${encodeURIComponent(id)}/evidence`,
}));

const mockedUseDataQuality = vi.mocked(useDataQuality);

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

describe("DataQualityPage states", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the loading state", () => {
    mockedUseDataQuality.mockReturnValue({ status: "loading", data: null, error: null });
    expect(renderToStaticMarkup(<DataQualityPage />)).toContain("加载中");
  });

  it("renders the empty state", () => {
    mockedUseDataQuality.mockReturnValue({ status: "empty", data: [], error: null });
    expect(renderToStaticMarkup(<DataQualityPage />)).toContain("暂无质量问题");
  });

  it("renders the error state", () => {
    mockedUseDataQuality.mockReturnValue({ status: "error", data: null, error: new Error("boom") });
    expect(renderToStaticMarkup(<DataQualityPage />)).toContain("加载失败");
  });

  it("renders the forbidden state", () => {
    mockedUseDataQuality.mockReturnValue({ status: "forbidden", data: null, error: new Error("denied") });
    expect(renderToStaticMarkup(<DataQualityPage />)).toContain("无权访问");
  });

  it("renders the success state with the detail panel", () => {
    mockedUseDataQuality.mockReturnValue({ status: "success", data: [sample], error: null });
    const html = renderToStaticMarkup(<DataQualityPage />);
    expect(html).toContain("SOURCE_CONFLICT");
    expect(html).toContain("600519.SH");
    expect(html).toContain('href="/v1/data-quality/fund-conflict-aaa/evidence"');
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

    mockedUseDataQuality.mockReturnValue({ status: "forbidden", data: null, error: new Error("x") });
    expect(renderToStaticMarkup(<DataQualityPage />)).toContain('role="alert"');
  });
});
