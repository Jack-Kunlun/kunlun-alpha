import {
  CandlestickSeries,
  ColorType,
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import type { InstrumentDailyBar } from "@kunlun/shared-types";

const DECIMAL = /^(0|[1-9][0-9]*)(\.[0-9]+)?$/;
const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const DEFAULT_HEIGHT = 360;
const MIN_WIDTH = 240;

export type InstrumentKlineTheme = "light" | "dark";

export interface InstrumentKlineChartOptions {
  theme?: InstrumentKlineTheme;
  height?: number;
}

export interface InstrumentKlineChartHandle {
  setData(bars: readonly InstrumentDailyBar[]): void;
  setTheme(theme: InstrumentKlineTheme): void;
  resize(): void;
  destroy(): void;
}

function invalid(field: string): Error {
  return new Error("invalid instrument Kline chart field: " + field);
}

function finiteNonNegative(value: string, field: string): number {
  if (!DECIMAL.test(value)) throw invalid(field);
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) throw invalid(field);
  return number;
}

function validDate(value: string): boolean {
  const match = DATE.exec(value);
  if (match === null) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return false;
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
  );
}

/**
 * Convert exact decimal wire values only at the canvas boundary. The API and
 * all feature state continue to carry prices, volume, and amount as strings.
 */
export function toInstrumentKlineData(
  bars: readonly InstrumentDailyBar[],
): CandlestickData<Time>[] {
  let previousDate: string | null = null;
  return bars.map((bar) => {
    if (!validDate(bar.date)) throw invalid("date");
    if (previousDate !== null && bar.date <= previousDate) {
      throw invalid("date-order");
    }
    previousDate = bar.date;

    const open = finiteNonNegative(bar.open, "open");
    const high = finiteNonNegative(bar.high, "high");
    const low = finiteNonNegative(bar.low, "low");
    const close = finiteNonNegative(bar.close, "close");
    finiteNonNegative(bar.volume, "volume");
    finiteNonNegative(bar.amount, "amount");
    if (high < Math.max(open, close)) throw invalid("high-low");
    if (low > Math.min(open, close) || low > high) throw invalid("high-low");

    return { time: bar.date, open, high, low, close };
  });
}

export function instrumentKlineThemeFromDocument(): InstrumentKlineTheme {
  if (typeof document === "undefined") return "light";
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function themeOptions(theme: InstrumentKlineTheme) {
  const dark = theme === "dark";
  return {
    layout: {
      background: { type: ColorType.Solid, color: dark ? "#0f172a" : "#ffffff" },
      textColor: dark ? "#cbd5e1" : "#475569",
    },
    grid: {
      vertLines: { color: dark ? "#1e293b" : "#e2e8f0" },
      horzLines: { color: dark ? "#1e293b" : "#e2e8f0" },
    },
    rightPriceScale: { borderColor: dark ? "#334155" : "#cbd5e1" },
    timeScale: { borderColor: dark ? "#334155" : "#cbd5e1" },
  } as const;
}

function widthOf(container: HTMLElement): number {
  const width = container.clientWidth;
  return Number.isFinite(width) && width > 0 ? width : MIN_WIDTH;
}

function heightOf(container: HTMLElement, fallback: number): number {
  const height = container.clientHeight;
  return Number.isFinite(height) && height > 0 ? height : fallback;
}

function mediaQuery(): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return null;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)");
}

function interactionOptions(reducedMotion: boolean) {
  return {
    kineticScroll: { mouse: !reducedMotion, touch: !reducedMotion },
    handleScroll: {
      mouseWheel: !reducedMotion,
      pressedMouseMove: !reducedMotion,
      horzTouchDrag: !reducedMotion,
      vertTouchDrag: !reducedMotion,
    },
  } as const;
}

/** Create and own one chart instance. No data fetching occurs in this adapter. */
export function createInstrumentKlineChart(
  container: HTMLElement,
  bars: readonly InstrumentDailyBar[],
  options: InstrumentKlineChartOptions = {},
): InstrumentKlineChartHandle {
  const data = toInstrumentKlineData(bars);
  const fallbackHeight = options.height ?? DEFAULT_HEIGHT;
  const initialTheme = options.theme ?? instrumentKlineThemeFromDocument();
  const reducedMotionQuery = mediaQuery();
  const chart: IChartApi = createChart(container, {
    width: widthOf(container),
    height: fallbackHeight,
    autoSize: false,
    ...themeOptions(initialTheme),
    ...interactionOptions(reducedMotionQuery?.matches ?? false),
  });
  const series: ISeriesApi<"Candlestick"> = chart.addSeries(CandlestickSeries, {
    upColor: "#ef4444",
    downColor: "#22c55e",
    borderVisible: false,
    wickUpColor: "#ef4444",
    wickDownColor: "#22c55e",
  });
  series.setData(data);
  chart.timeScale().fitContent();

  let destroyed = false;
  const resize = (width = widthOf(container), height = heightOf(container, fallbackHeight)) => {
    if (destroyed) return;
    if (width > 0 && height > 0) chart.resize(width, height);
  };
  const resizeObserver =
    typeof ResizeObserver === "function"
      ? new ResizeObserver((entries) => {
          const rect = entries[0]?.contentRect;
          resize(rect?.width, rect?.height);
        })
      : null;
  resizeObserver?.observe(container);
  const windowResize = () => resize();
  if (resizeObserver === null && typeof window !== "undefined") {
    window.addEventListener("resize", windowResize);
  }

  const updateMotion = () => {
    chart.applyOptions(interactionOptions(reducedMotionQuery?.matches ?? false));
  };
  if (reducedMotionQuery !== null) {
    reducedMotionQuery.addEventListener?.("change", updateMotion);
  }

  const themeObserver =
    typeof MutationObserver === "function" && typeof document !== "undefined"
      ? new MutationObserver(() => {
          handle.setTheme(instrumentKlineThemeFromDocument());
        })
      : null;
  themeObserver?.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class"],
  });

  const handle: InstrumentKlineChartHandle = {
    setData(nextBars) {
      const nextData = toInstrumentKlineData(nextBars);
      if (destroyed) return;
      series.setData(nextData);
      chart.timeScale().fitContent();
    },
    setTheme(theme) {
      if (destroyed) return;
      chart.applyOptions(themeOptions(theme));
    },
    resize() {
      resize();
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      resizeObserver?.disconnect();
      themeObserver?.disconnect();
      reducedMotionQuery?.removeEventListener?.("change", updateMotion);
      if (resizeObserver === null && typeof window !== "undefined") {
        window.removeEventListener("resize", windowResize);
      }
      chart.remove();
    },
  };

  return handle;
}
