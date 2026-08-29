import type { InstrumentDailyBar } from "@kunlun/shared-types";
import { useEffect, useRef, useState } from "react";
import {
  createInstrumentKlineChart,
  toInstrumentKlineData,
} from "@/lib/charts/instrument-kline-chart";

export function InstrumentKlineChart({ bars }: { bars: readonly InstrumentDailyBar[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [chartFailure, setChartFailure] = useState<{
    bars: readonly InstrumentDailyBar[];
    error: Error;
  } | null>(null);

  let validationError: Error | null = null;
  try {
    // Validate during render as well as in the adapter so malformed API data
    // is represented by the component's error state before chart setup.
    toInstrumentKlineData(bars);
  } catch (error: unknown) {
    validationError = error instanceof Error ? error : new Error(String(error));
  }
  const validationMessage = validationError?.message ?? null;

  useEffect(() => {
    if (validationMessage !== null) return undefined;
    const container = containerRef.current;
    if (container === null) return undefined;
    let active = true;
    try {
      const chart = createInstrumentKlineChart(container, bars);
      return () => {
        active = false;
        chart.destroy();
      };
    } catch (error: unknown) {
      const failure = error instanceof Error ? error : new Error(String(error));
      queueMicrotask(() => {
        if (active) setChartFailure({ bars, error: failure });
      });
      return () => {
        active = false;
      };
    }
  }, [bars, validationMessage]);

  if (validationError !== null) {
    return (
      <p
        role="alert"
        className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
      >
        日 K 线图数据无效：{validationError.message}
      </p>
    );
  }

  const chartError = chartFailure?.bars === bars ? chartFailure.error : null;
  if (chartError !== null) {
    return (
      <p
        role="alert"
        className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
      >
        日 K 线图加载失败：{chartError.message}
      </p>
    );
  }

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label="日 K 线图，仅用于研究参考"
      tabIndex={0}
      className="h-[360px] min-h-[280px] w-full min-w-0 rounded-xl border bg-white outline-none focus-visible:ring-2 focus-visible:ring-ring dark:bg-slate-950"
    />
  );
}
