import { Link } from "react-router";
import { useId, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useTerminalFilters } from "@/app/filter-context";
import type { ObjectQueryResult, QueryStatus } from "@/lib/use-api-query";
import { DailyComparisonExportButton } from "./daily-comparison-export-button";
import {
  formatDailyComparisonChange,
  formatDailyComparisonDecimal,
  sortDailyComparisonRows,
  type DailyComparison,
  type DailyComparisonRow,
  type DailyComparisonSort,
  type DailyComparisonSortDirection,
  type DailyComparisonSortKey,
} from "./daily-comparison";

const DEFAULT_SORT: DailyComparisonSort = { key: "close", direction: "descending" };
const SHANGHAI_DATE_TIME_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function formatShanghaiDateTime(value: string): string {
  const parts = SHANGHAI_DATE_TIME_FORMATTER.formatToParts(new Date(value));
  const part = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((valuePart) => valuePart.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")} ${part("hour")}:${part("minute")}:${part("second")}`;
}

function rowStatus(row: DailyComparisonRow): { label: string; detail: string | null } {
  switch (row.status) {
    case "EMPTY":
      return { label: "暂无日线", detail: null };
    case "FORBIDDEN":
      return { label: "无权访问", detail: null };
    case "ERROR":
      return { label: "读取失败", detail: null };
    case "INVALID":
      return { label: "数据异常", detail: "返回日线未通过字段、点时或来源校验" };
    case "AVAILABLE":
      if (!row.dateAligned) return { label: "日期不一致", detail: row.changeReason };
      if (row.changeReason !== null) return { label: "涨跌幅未计算", detail: row.changeReason };
      return { label: "可比较", detail: null };
  }
}

function sortButtonLabel(
  label: string,
  key: DailyComparisonSortKey,
  sort: DailyComparisonSort,
): string {
  const nextDirection: DailyComparisonSortDirection =
    sort.key === key && sort.direction === "descending" ? "ascending" : "descending";
  return `按${label}${nextDirection === "ascending" ? "升序" : "降序"}排序`;
}

function SortHeader({
  label,
  sortKey,
  sort,
  onSort,
  align = "left",
}: {
  label: string;
  sortKey: DailyComparisonSortKey;
  sort: DailyComparisonSort;
  onSort: (key: DailyComparisonSortKey) => void;
  align?: "left" | "right";
}) {
  const active = sort.key === sortKey;
  const direction = active ? sort.direction : "none";
  const indicator = active ? (sort.direction === "ascending" ? "↑" : "↓") : "↕";
  return (
    <TableHead aria-sort={direction} className={align === "right" ? "text-right" : undefined}>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className={`h-8 cursor-pointer ${align === "right" ? "ml-auto" : "-ml-3"}`}
        aria-label={sortButtonLabel(label, sortKey, sort)}
        onClick={() => onSort(sortKey)}
      >
        {label}
        <span aria-hidden="true" className="text-muted-foreground">
          {indicator}
        </span>
      </Button>
    </TableHead>
  );
}

function InstrumentName({ row, detailAsOf }: { row: DailyComparisonRow; detailAsOf?: string }) {
  const { hrefForRoute } = useTerminalFilters();
  return (
    <Link
      to={
        detailAsOf === undefined
          ? hrefForRoute(`/instruments/${encodeURIComponent(row.instrumentId)}`)
          : `/instruments/${encodeURIComponent(row.instrumentId)}?asOf=${encodeURIComponent(detailAsOf)}`
      }
      aria-label={`查看${row.name}日线`}
      className="inline-flex flex-col rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      <span className="font-medium text-primary hover:underline">{row.name}</span>
      <span className="font-mono text-xs text-muted-foreground">{row.instrumentId}</span>
    </Link>
  );
}

function ComparisonBody({
  comparison,
  sort,
  onSort,
  watchlistPage,
  detailAsOf,
}: {
  comparison: DailyComparison;
  sort: DailyComparisonSort;
  onSort: (key: DailyComparisonSortKey) => void;
  watchlistPage: boolean;
  detailAsOf?: string;
}) {
  const rows = sortDailyComparisonRows(comparison, sort);
  const emptyCount = comparison.rows.filter((row) => row.status === "EMPTY").length;
  const allEmpty = emptyCount === comparison.rows.length;
  const allForbidden = comparison.rows.every((row) => row.status === "FORBIDDEN");

  return (
    <>
      {allEmpty && (
        <p className="text-sm text-muted-foreground" role="status">
          {watchlistPage
            ? "本次本页自选在该点时均暂无日线数据。"
            : "八个配置样本在该点时均暂无日线数据。"}
        </p>
      )}
      {allForbidden && (
        <p className="text-sm text-destructive" role="alert">
          当前账号无权访问这些样本的日线。
        </p>
      )}
      <div className="rounded-xl border">
        <Table className="min-w-[920px]">
          <caption className="sr-only">
            {watchlistPage ? "本次本页自选" : "首发八个日线样本"}
            的收盘价、前一可见日线涨跌幅、成交额、日期和来源
          </caption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">标的</TableHead>
              <SortHeader
                label="收盘价"
                sortKey="close"
                sort={sort}
                onSort={onSort}
                align="right"
              />
              <SortHeader
                label="较前一可见日线涨跌幅"
                sortKey="change"
                sort={sort}
                onSort={onSort}
                align="right"
              />
              <SortHeader
                label="成交额"
                sortKey="amount"
                sort={sort}
                onSort={onSort}
                align="right"
              />
              <TableHead scope="col">行情日 / 基准日</TableHead>
              <TableHead scope="col">来源 / 版本</TableHead>
              <TableHead scope="col">状态</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => {
              const state = rowStatus(row);
              const destructive = ["ERROR", "FORBIDDEN", "INVALID"].includes(row.status);
              const badgeVariant = destructive ? "destructive" : "outline";
              return (
                <TableRow key={row.instrumentId}>
                  <TableCell>
                    <InstrumentName row={row} detailAsOf={detailAsOf} />
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {row.latest === null ? "—" : formatDailyComparisonDecimal(row.latest.close)}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {formatDailyComparisonChange(row.changeHundredthsOfPercent)}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {row.latest === null ? "—" : formatDailyComparisonDecimal(row.latest.amount)}
                  </TableCell>
                  <TableCell>
                    {row.latest === null ? (
                      "—"
                    ) : (
                      <span className="inline-flex flex-col">
                        <span>{row.latest.date}</span>
                        <span className="text-xs text-muted-foreground">
                          基准 {row.previous?.date ?? "—"}
                        </span>
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="max-w-64 whitespace-normal">
                    {row.latest === null ? (
                      "—"
                    ) : (
                      <span className="inline-flex flex-col break-all text-xs">
                        <span>
                          {row.latest.source} · {row.latest.sourceVersion}
                        </span>
                        <span className="text-muted-foreground">
                          数据版本 {row.latest.dataVersion}
                        </span>
                        {row.previous !== null &&
                          (row.latest.source !== row.previous.source ||
                            row.latest.sourceVersion !== row.previous.sourceVersion) && (
                            <span className="text-muted-foreground">
                              基准 {row.previous.source} · {row.previous.sourceVersion}
                            </span>
                          )}
                        {row.previous !== null &&
                          row.latest.dataVersion !== row.previous.dataVersion && (
                            <span className="text-muted-foreground">
                              基准数据版本 {row.previous.dataVersion}
                            </span>
                          )}
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    <span className="inline-flex flex-col items-start gap-1">
                      <Badge variant={badgeVariant}>{state.label}</Badge>
                      {state.detail !== null && (
                        <span className="max-w-48 text-xs text-muted-foreground">
                          {state.detail}
                        </span>
                      )}
                    </span>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </>
  );
}

export function DailyComparisonTable({
  result,
  referenceStatus,
  scope = "samples",
  detailAsOf,
}: {
  result: ObjectQueryResult<DailyComparison>;
  referenceStatus: QueryStatus;
  scope?: "samples" | "watchlist-page";
  detailAsOf?: string;
}) {
  const titleId = useId();
  const watchlistPage = scope === "watchlist-page";
  const [sort, setSort] = useState<DailyComparisonSort>(DEFAULT_SORT);
  function onSort(key: DailyComparisonSortKey) {
    setSort((previous) => ({
      key,
      direction:
        previous.key === key && previous.direction === "descending" ? "ascending" : "descending",
    }));
  }

  return (
    <section aria-labelledby={titleId} className="min-w-0 space-y-3">
      <header className="space-y-1">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 id={titleId} className="text-lg font-semibold">
            {watchlistPage ? "本页自选日线对比" : "日线对比"}
          </h3>
          {result.status === "success" && result.data !== null && (
            <p className="text-xs text-muted-foreground">
              固定点时 {formatShanghaiDateTime(result.data.requestedAsOf)} 北京时间
            </p>
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          {watchlistPage
            ? "仅含打开时本页的沪深北自选；排序仅针对本次样本，不代表全部自选或全市场。"
            : "仅含配置的八个沪深股票样本。"}
          行情日 {result.data?.comparisonDate ?? "暂无"}，统一基准日{" "}
          {result.data?.baselineDate ?? "暂无"}；涨跌幅较前一可见日线计算，价格未复权（RAW）。
        </p>
      </header>

      {watchlistPage && (
        <DailyComparisonExportButton
          comparison={
            referenceStatus === "success" && result.status === "success" ? result.data : null
          }
          expectedAsOf={detailAsOf}
          sort={sort}
        />
      )}

      {referenceStatus === "loading" ? (
        <p role="status" className="text-sm text-muted-foreground">
          正在确定市场总览的固定点时…
        </p>
      ) : referenceStatus === "forbidden" ? (
        <p role="alert" className="text-sm text-destructive">
          无权读取市场总览，无法确定日线对比点时。
        </p>
      ) : referenceStatus === "error" ? (
        <p role="alert" className="text-sm text-destructive">
          市场总览读取失败，无法确定日线对比点时。
        </p>
      ) : referenceStatus === "empty" ? (
        <p role="status" className="text-sm text-muted-foreground">
          该点时暂无市场总览，无法读取日线对比。
        </p>
      ) : result.status === "loading" ? (
        <p role="status" className="text-sm text-muted-foreground">
          正在加载日线对比…
        </p>
      ) : result.status === "forbidden" ? (
        <p role="alert" className="text-sm text-destructive">
          无权访问日线对比
        </p>
      ) : result.status === "error" ? (
        <p role="alert" className="text-sm text-destructive">
          日线对比加载失败
        </p>
      ) : result.status === "empty" || result.data === null ? (
        <p role="status" className="text-sm text-muted-foreground">
          该点时暂无日线对比数据
        </p>
      ) : (
        <ComparisonBody
          comparison={result.data}
          sort={sort}
          onSort={onSort}
          watchlistPage={watchlistPage}
          detailAsOf={detailAsOf}
        />
      )}
    </section>
  );
}
