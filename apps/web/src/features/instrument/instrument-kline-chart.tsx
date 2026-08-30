import type { InstrumentDailyBar } from "@kunlun/shared-types";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import {
  createInstrumentKlineChart,
  toInstrumentKlineData,
  type InstrumentKlineChartHandle,
} from "@/lib/charts/instrument-kline-chart";

export function InstrumentKlineChart({ bars }: { bars: readonly InstrumentDailyBar[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<InstrumentKlineChartHandle | null>(null);
  const instructionsId = useId();
  const [activeDate, setActiveDate] = useState<string | null>(null);
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
      const chart = createInstrumentKlineChart(container, bars, {
        onBarChange: (bar) => setActiveDate(bar?.date ?? null),
      });
      chartRef.current = chart;
      return () => {
        active = false;
        if (chartRef.current === chart) chartRef.current = null;
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

  const latestBar = bars.at(-1) ?? null;
  const activeBar =
    (activeDate === null ? null : bars.find((bar) => bar.date === activeDate)) ?? latestBar;
  const activeIndex =
    activeBar === null ? -1 : bars.findIndex((bar) => bar.date === activeBar.date);

  const focusIndex = (index: number) => {
    const bar = chartRef.current?.focusBar(index) ?? null;
    if (bar !== null) setActiveDate(bar.date);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      focusIndex(Math.max(0, activeIndex - 1));
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      focusIndex(Math.min(bars.length - 1, activeIndex + 1));
    } else if (event.key === "Home") {
      event.preventDefault();
      focusIndex(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusIndex(bars.length - 1);
    } else if (event.key === "Escape") {
      event.preventDefault();
      chartRef.current?.resetView();
      setActiveDate(null);
    }
  };

  const resetView = () => {
    chartRef.current?.resetView();
    setActiveDate(null);
    containerRef.current?.focus();
  };

  return (
    <section className="space-y-3" aria-label="日 K 线交互图表">
      {activeBar !== null && (
        <div
          aria-live="polite"
          aria-atomic="true"
          className="rounded-xl border bg-slate-50/70 p-3 dark:bg-slate-900/40"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs text-muted-foreground">当前指针</p>
              <p className="font-mono text-sm font-semibold">{activeBar.date}</p>
            </div>
            <Button type="button" size="sm" variant="outline" onClick={resetView}>
              重置视图
            </Button>
          </div>
          <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs sm:grid-cols-4 xl:grid-cols-6">
            {[
              ["开", activeBar.open],
              ["高", activeBar.high],
              ["低", activeBar.low],
              ["收", activeBar.close],
              ["成交量", activeBar.volume],
              ["成交额", activeBar.amount],
            ].map(([label, value]) => (
              <div key={label} className="min-w-0">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="truncate font-mono font-medium" title={value}>
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      <div
        ref={containerRef}
        role="application"
        aria-label="日 K 线图，仅用于研究参考"
        aria-describedby={instructionsId}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        className="h-[280px] w-full min-w-0 rounded-xl border bg-white outline-none focus-visible:ring-2 focus-visible:ring-ring sm:h-[360px] xl:h-[420px] dark:bg-slate-950"
      />
      <p id={instructionsId} className="text-xs text-muted-foreground">
        聚焦图表后可用左右方向键逐根查看，Home / End 跳到首尾，Esc 重置视图。
      </p>
    </section>
  );
}
