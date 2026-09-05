import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MarketCoverageDaysResponse } from "@kunlun/shared-types";
import { apiClient } from "@/lib/api-client";
import { useApiObjectQuery } from "@/lib/use-api-query";
import { useMarketCoverageDays } from "./use-market-coverage-days";
import type { MarketCoverageDaysSelection } from "./market-coverage-days";

vi.mock("@/lib/use-api-query", () => ({
  useApiObjectQuery: vi.fn(),
}));

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn() },
}));

const mockedUseApiObjectQuery = vi.mocked(useApiObjectQuery);
const mockedGet = vi.mocked(apiClient.get);

const selection = {
  dateFrom: "2026-09-01",
  dateTo: "2026-09-04",
  unifiedCode: "600519.SH" as const,
  source: "tushare-pro" as const,
};

const response = {
  schemaVersion: "market-data-coverage-days-v1" as const,
  scope: "DAILY_RAW_SINGLE_SUPPORTED_SOURCE" as const,
  meaning: "OBSERVED_ONLY" as const,
  window: {
    dateFrom: selection.dateFrom,
    dateTo: selection.dateTo,
    asOf: "2026-09-05T02:00:00.000Z",
  },
  unifiedCode: selection.unifiedCode,
  source: selection.source,
  days: [],
} satisfies MarketCoverageDaysResponse;

function HookHarness({ selected }: { selected: MarketCoverageDaysSelection | null }) {
  useMarketCoverageDays(selected);
  return null;
}

describe("useMarketCoverageDays", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("disables the independent query without a selected row", () => {
    mockedUseApiObjectQuery.mockReturnValue({ status: "empty", data: null, error: null });
    renderToStaticMarkup(<HookHarness selected={null} />);
    expect(mockedUseApiObjectQuery).toHaveBeenCalledWith(
      expect.any(Function),
      [undefined, undefined, undefined, undefined, null],
      false,
    );
  });

  it("uses the shared API client and exact row/window parameters", async () => {
    mockedUseApiObjectQuery.mockReturnValue({ status: "loading", data: null, error: null });
    mockedGet.mockResolvedValue(response);
    const selected = { ...selection, selectionKey: "2026-09-05T02:00:00.000Z" };
    renderToStaticMarkup(<HookHarness selected={selected} />);
    expect(mockedUseApiObjectQuery).toHaveBeenCalledWith(
      expect.any(Function),
      [
        selected.dateFrom,
        selected.dateTo,
        selected.unifiedCode,
        selected.source,
        selected.selectionKey,
      ],
      true,
    );
    const fetcher = mockedUseApiObjectQuery.mock.calls.at(-1)?.[0];
    expect(fetcher).toBeDefined();
    await fetcher!();
    expect(mockedGet).toHaveBeenCalledWith("/v1/data-quality/market-coverage/days", {
      dateFrom: selected.dateFrom,
      dateTo: selected.dateTo,
      unifiedCode: selected.unifiedCode,
      source: selected.source,
    });
  });
});
