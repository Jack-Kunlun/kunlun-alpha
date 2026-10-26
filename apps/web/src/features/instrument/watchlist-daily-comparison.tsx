import { useEffect, useRef, useState } from "react";
import type { ServerWatchlistItem } from "@kunlun/shared-types";
import { useTerminalFilters } from "@/app/filter-context";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { apiClient } from "@/lib/api-client";
import { useApiObjectQuery } from "@/lib/use-api-query";
import { DailyComparisonTable } from "@/features/market-overview/daily-comparison-table";
import { loadDailyComparison } from "@/features/market-overview/use-daily-comparison";
import type { DailyComparisonStock } from "@/features/market-overview/daily-comparison";
import { isCanonicalInstrumentId } from "./use-instrument-intelligence";

export interface WatchlistComparisonRequest {
  requestedAsOf: string;
  stocks: readonly DailyComparisonStock[];
}

export function watchlistComparisonStocks(
  items: readonly Pick<ServerWatchlistItem, "code" | "name">[],
): DailyComparisonStock[] {
  if (items.length > 20) throw new Error("只能对比本页最多 20 项自选");
  const seen = new Set<string>();
  return items
    .filter((item) => {
      if (!isCanonicalInstrumentId(item.code) || seen.has(item.code)) return false;
      seen.add(item.code);
      return true;
    })
    .map((item) => ({ instrumentId: item.code, name: item.name, sector: "" }));
}

function ComparisonQuery({
  request,
  onRetry,
}: {
  request: WatchlistComparisonRequest;
  onRetry: () => void;
}) {
  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => () => abortRef.current?.abort(), []);
  const result = useApiObjectQuery(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    return loadDailyComparison(request.requestedAsOf, apiClient, request.stocks, controller.signal);
  }, [request]);
  return (
    <div className="min-w-0 space-y-4">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={result.status === "loading"}
        aria-busy={result.status === "loading"}
        className="cursor-pointer disabled:cursor-progress"
        onClick={onRetry}
      >
        {result.status === "loading" ? "正在查询…" : "重新查询"}
      </Button>
      <DailyComparisonTable
        result={result}
        referenceStatus="success"
        scope="watchlist-page"
        detailAsOf={request.requestedAsOf}
      />
    </div>
  );
}

export function WatchlistDailyComparison({ items }: { items: readonly ServerWatchlistItem[] }) {
  const { value: filters } = useTerminalFilters();
  const stocks = watchlistComparisonStocks(items);
  const [request, setRequest] = useState<WatchlistComparisonRequest | null>(null);
  const [generation, setGeneration] = useState(0);
  function open() {
    if (stocks.length === 0) return;
    setRequest({ requestedAsOf: filters.asOf ?? new Date().toISOString(), stocks });
    setGeneration((value) => value + 1);
  }
  function retry() {
    if (request === null) return;
    setGeneration((value) => value + 1);
  }
  return (
    <Dialog open={request !== null} onOpenChange={(next) => (next ? open() : setRequest(null))}>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="outline"
          disabled={stocks.length === 0}
          title={
            stocks.length === 0 ? "本页没有可对比的沪深北标的" : "仅查询本页已保存的沪深北自选"
          }
        >
          对比本页日线
        </Button>
      </DialogTrigger>
      <DialogContent className="inset-y-0 right-0 left-auto flex h-dvh max-h-dvh w-full max-w-full translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden rounded-none p-0 sm:max-w-6xl">
        <DialogHeader className="shrink-0 border-b p-5 pr-12 text-left">
          <DialogTitle>自选日线对比</DialogTitle>
          <DialogDescription>
            打开时固定本页标的和查询点时，最多 20
            项；重新查询沿用本次点时，查看最新快照可关闭后重新打开。观察项不参与。价格不是实时或可成交价格。
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto p-4 sm:p-6">
          {request !== null ? (
            <>
              <p className="mb-4 text-xs text-muted-foreground">
                本次 {request.stocks.length} 项沪深北自选 · 查询固定点时的两根可见日线 ·
                行情任务状态不替代数据日期。点击证券名称按本次点时查看日线详情。
              </p>
              <ComparisonQuery key={generation} request={request} onRetry={retry} />
            </>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
