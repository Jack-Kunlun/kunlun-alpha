import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { useApiObjectQuery } from "@/lib/use-api-query";
import { useInstrumentBars } from "./use-instrument-bars";
import { useInstrumentIntelligence } from "./use-instrument-intelligence";

vi.mock("@/lib/use-api-query", () => ({
  useApiObjectQuery: vi.fn(() => ({ status: "loading", data: null, error: null })),
}));

function Probe({ asOf, refresh }: { asOf: string | null; refresh: boolean }) {
  useInstrumentIntelligence("600519.SH", asOf, refresh);
  useInstrumentBars("600519.SH", asOf, 250, refresh);
  return null;
}

describe("daily details refresh lifecycle", () => {
  it.each([
    [null, true, 30_000],
    [null, false, 0],
    ["2026-10-23T08:00:00Z", true, 0],
  ] as const)("coordinates detail and bar refresh for %s / %s", (asOf, refresh, interval) => {
    vi.mocked(useApiObjectQuery).mockClear();
    renderToStaticMarkup(<Probe asOf={asOf} refresh={refresh} />);
    expect(vi.mocked(useApiObjectQuery).mock.calls.map((call) => call[3])).toEqual([
      interval,
      interval,
    ]);
  });
});
