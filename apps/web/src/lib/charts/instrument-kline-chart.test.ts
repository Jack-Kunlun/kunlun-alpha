import { beforeEach, describe, expect, it, vi } from "vitest";
import type { InstrumentDailyBar } from "@kunlun/shared-types";
import { toInstrumentKlineData } from "./instrument-kline-chart";

const chartMocks = vi.hoisted(() => {
  const series = { setData: vi.fn() };
  const chart = {
    addSeries: vi.fn(() => series),
    applyOptions: vi.fn(),
    resize: vi.fn(),
    remove: vi.fn(),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
  };
  return { chart, series, createChart: vi.fn(() => chart) };
});

vi.mock("lightweight-charts", () => ({
  CandlestickSeries: {},
  ColorType: { Solid: "solid" },
  createChart: chartMocks.createChart,
}));

const bar: InstrumentDailyBar = {
  date: "2026-08-25",
  eventTime: "2026-08-25T07:00:00.000Z",
  open: "10.0000",
  high: "11.0000",
  low: "9.0000",
  close: "10.5000",
  volume: "9007199254740993",
  amount: "9007199254740993.25",
  suspended: false,
  dataVersion: "bars-v2",
  source: "tushare-pro",
  sourceVersion: "tushare-v1",
  evidenceId: "evidence-1",
  availableTime: "2026-08-25T07:01:00.000Z",
  processingTime: "2026-08-25T07:02:00.000Z",
};

describe("instrument Kline chart adapter", () => {
  beforeEach(() => {
    chartMocks.createChart.mockClear();
    chartMocks.chart.addSeries.mockClear();
    chartMocks.chart.applyOptions.mockClear();
    chartMocks.chart.resize.mockClear();
    chartMocks.chart.remove.mockClear();
    chartMocks.series.setData.mockClear();
  });

  it("converts exact wire scalars only at the rendering boundary", () => {
    expect(toInstrumentKlineData([bar])).toEqual([
      {
        time: "2026-08-25",
        open: 10,
        high: 11,
        low: 9,
        close: 10.5,
      },
    ]);
  });

  it.each([
    { ...bar, close: "NaN" },
    { ...bar, amount: "-1" },
    { ...bar, high: "8.0000" },
  ])("rejects invalid chart data %#", (invalid) => {
    expect(() => toInstrumentKlineData([invalid])).toThrow("invalid");
  });

  it("owns chart lifecycle and exposes no network behavior", async () => {
    const { createInstrumentKlineChart } = await import("./instrument-kline-chart");
    const container = { clientWidth: 640, clientHeight: 360 } as unknown as HTMLElement;
    const handle = createInstrumentKlineChart(container, [bar], { theme: "light" });

    expect(chartMocks.createChart).toHaveBeenCalledOnce();
    expect(chartMocks.series.setData).toHaveBeenCalledOnce();
    handle.setTheme("dark");
    handle.setData([bar]);
    expect(chartMocks.chart.applyOptions).toHaveBeenCalled();
    expect(chartMocks.series.setData).toHaveBeenCalledTimes(2);
    handle.destroy();
    handle.destroy();
    expect(chartMocks.chart.remove).toHaveBeenCalledOnce();
  });
});
