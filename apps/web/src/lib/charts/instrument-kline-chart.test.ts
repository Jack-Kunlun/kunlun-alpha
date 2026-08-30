import { beforeEach, describe, expect, it, vi } from "vitest";
import type { InstrumentDailyBar } from "@kunlun/shared-types";
import { toInstrumentKlineData } from "./instrument-kline-chart";

const chartMocks = vi.hoisted(() => {
  const series = { setData: vi.fn() };
  const timeScale = { fitContent: vi.fn() };
  let crosshairMoveHandler: ((params: unknown) => void) | null = null;
  const chart = {
    addSeries: vi.fn(() => series),
    applyOptions: vi.fn(),
    clearCrosshairPosition: vi.fn(),
    resize: vi.fn(),
    remove: vi.fn(),
    setCrosshairPosition: vi.fn(),
    subscribeCrosshairMove: vi.fn((handler: (params: unknown) => void) => {
      crosshairMoveHandler = handler;
    }),
    unsubscribeCrosshairMove: vi.fn(),
    timeScale: vi.fn(() => timeScale),
  };
  return {
    chart,
    series,
    timeScale,
    createChart: vi.fn(() => chart),
    emitCrosshairMove(params: unknown) {
      crosshairMoveHandler?.(params);
    },
  };
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
    chartMocks.chart.clearCrosshairPosition.mockClear();
    chartMocks.chart.resize.mockClear();
    chartMocks.chart.remove.mockClear();
    chartMocks.chart.setCrosshairPosition.mockClear();
    chartMocks.chart.subscribeCrosshairMove.mockClear();
    chartMocks.chart.unsubscribeCrosshairMove.mockClear();
    chartMocks.timeScale.fitContent.mockClear();
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

  it("reports exact hovered bars and supports keyboard-oriented view control", async () => {
    const { createInstrumentKlineChart } = await import("./instrument-kline-chart");
    const container = { clientWidth: 640, clientHeight: 300 } as unknown as HTMLElement;
    const onBarChange = vi.fn();
    const handle = createInstrumentKlineChart(container, [bar], {
      theme: "light",
      onBarChange,
    });

    expect(chartMocks.createChart).toHaveBeenCalledWith(
      container,
      expect.objectContaining({ width: 640, height: 300 }),
    );
    chartMocks.emitCrosshairMove({ time: bar.date });
    expect(onBarChange).toHaveBeenLastCalledWith(bar);
    chartMocks.emitCrosshairMove({ time: { year: 2026, month: 8, day: 25 } });
    expect(onBarChange).toHaveBeenLastCalledWith(bar);
    chartMocks.emitCrosshairMove({});
    expect(onBarChange).toHaveBeenLastCalledWith(null);

    expect(handle.focusBar(0)).toBe(bar);
    expect(chartMocks.chart.setCrosshairPosition).toHaveBeenCalledWith(
      10.5,
      bar.date,
      chartMocks.series,
    );
    expect(handle.focusBar(5)).toBeNull();

    handle.resetView();
    expect(chartMocks.chart.clearCrosshairPosition).toHaveBeenCalledOnce();
    expect(chartMocks.timeScale.fitContent).toHaveBeenCalledTimes(2);
    handle.destroy();
    expect(chartMocks.chart.unsubscribeCrosshairMove).toHaveBeenCalledOnce();
  });
});
