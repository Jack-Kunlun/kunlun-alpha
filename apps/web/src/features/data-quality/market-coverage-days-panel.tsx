import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { MarketCoverageDaysResponse, MarketCoverageObservedDay } from "@kunlun/shared-types";
import type { ObjectQueryResult } from "@/lib/use-api-query";
import { formatShanghaiTime } from "./format-shanghai-time";
import type { MarketCoverageDaysQuery } from "./market-coverage-days";

export const MARKET_COVERAGE_DAYS_PAGE_SIZE = 50;

export function getMarketCoverageDaysPage(
  days: readonly MarketCoverageObservedDay[],
  pageIndex: number,
): { currentPage: number; pageCount: number; days: MarketCoverageObservedDay[] } {
  const pageCount = Math.max(1, Math.ceil(days.length / MARKET_COVERAGE_DAYS_PAGE_SIZE));
  const currentPage = Math.min(Math.max(0, pageIndex), pageCount - 1);
  return {
    currentPage,
    pageCount,
    days: days.slice(
      currentPage * MARKET_COVERAGE_DAYS_PAGE_SIZE,
      (currentPage + 1) * MARKET_COVERAGE_DAYS_PAGE_SIZE,
    ),
  };
}

interface MarketCoverageDaysPanelProps {
  result: ObjectQueryResult<MarketCoverageDaysResponse>;
  selection: MarketCoverageDaysQuery;
}

function matchesSelection(
  response: MarketCoverageDaysResponse,
  selection: MarketCoverageDaysQuery,
): boolean {
  return (
    response.unifiedCode === selection.unifiedCode &&
    response.source === selection.source &&
    response.window.dateFrom === selection.dateFrom &&
    response.window.dateTo === selection.dateTo
  );
}

export function MarketCoverageDaysPanel({ result, selection }: MarketCoverageDaysPanelProps) {
  const [pageIndex, setPageIndex] = useState(0);
  const response = result.data;

  if (
    result.status === "loading" ||
    (response !== null && !matchesSelection(response, selection))
  ) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        已观测日期加载中…
      </p>
    );
  }
  if (result.status === "forbidden") {
    return (
      <p role="alert" className="text-sm text-destructive">
        无权访问已观测日期
      </p>
    );
  }
  if (result.status === "error" || response === null) {
    return (
      <p role="alert" className="text-sm text-destructive">
        已观测日期暂不可用，请稍后重试
      </p>
    );
  }
  if (result.status === "empty" || response.days.length === 0) {
    return (
      <div className="space-y-1 text-sm text-muted-foreground">
        <p>当前窗口暂无已观测日期。</p>
        <p>
          这不表示缺失，也不表示价格合格；独立查询 asOf：{formatShanghaiTime(response.window.asOf)}
          ，可能与上方汇总不同。
        </p>
      </div>
    );
  }

  const { currentPage, pageCount, days } = getMarketCoverageDaysPage(response.days, pageIndex);

  return (
    <div className="space-y-3 rounded-md border p-3" aria-label="已观测日期明细">
      <div className="space-y-1 text-sm text-muted-foreground">
        <p>
          已观测日期：{response.unifiedCode} · {response.source} · {response.window.dateFrom} 至{" "}
          {response.window.dateTo}
        </p>
        <p>
          独立查询 asOf：{formatShanghaiTime(response.window.asOf)}
          ，可能与上方汇总不同；仅表示已观测到的日期，不代表完整率、缺失检测或价格合格。
        </p>
      </div>
      <div className="overflow-x-auto">
        <Table aria-label="已观测日期明细列表" className="min-w-[900px]">
          <TableHeader>
            <TableRow>
              <TableHead>日期</TableHead>
              <TableHead>最新行情时间（上海）</TableHead>
              <TableHead>最新可用时间（上海）</TableHead>
              <TableHead>最新入库时间（上海）</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {days.map((day) => (
              <TableRow key={day.date}>
                <TableCell>{day.date}</TableCell>
                <TableCell>{formatShanghaiTime(day.latestEventTime)}</TableCell>
                <TableCell>{formatShanghaiTime(day.latestAvailableTime)}</TableCell>
                <TableCell>{formatShanghaiTime(day.latestProcessingTime)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {pageCount > 1 && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setPageIndex((value) => Math.max(0, value - 1))}
            disabled={currentPage === 0}
          >
            上一页
          </Button>
          <span>
            第 {currentPage + 1}/{pageCount} 页，共 {response.days.length} 个已观测日期
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setPageIndex((value) => Math.min(pageCount - 1, value + 1))}
            disabled={currentPage >= pageCount - 1}
          >
            下一页
          </Button>
        </div>
      )}
    </div>
  );
}
