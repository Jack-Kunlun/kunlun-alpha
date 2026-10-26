import { useRef, useState } from "react";
import { DetailDrawer } from "@/components/detail-drawer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { MarketCoverageResponse } from "@kunlun/shared-types";
import { formatShanghaiTime } from "./format-shanghai-time";
import { MarketCoverageHistoryPanel } from "./market-coverage-history-panel";
import type { MarketCoverageDaysQuery } from "./market-coverage-days";
import { selectMarketCoveragePage } from "./market-coverage-browser";

interface MarketCoveragePanelProps {
  response: MarketCoverageResponse;
}

type SelectedMarketCoverageDays = MarketCoverageDaysQuery & {
  selectionKey: string;
};

export function MarketCoveragePanel({ response }: MarketCoveragePanelProps) {
  const [selected, setSelected] = useState<SelectedMarketCoverageDays | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [query, setQuery] = useState("");
  const [pageIndex, setPageIndex] = useState(0);
  const page = selectMarketCoveragePage(response.rows, query, pageIndex);
  const latestReturnedDate = response.rows.reduce<string | null>(
    (latest, row) => (latest === null || row.lastDate > latest ? row.lastDate : latest),
    null,
  );
  const returnedSecurityCount = new Set(response.rows.map((row) => row.unifiedCode)).size;
  const earlierDateHint = response.truncated
    ? "早于前 100 组中的最晚日（仅作相对提示，不代表缺失）"
    : "早于本次返回最晚日（仅作相对提示，不代表缺失）";
  const activeSelection =
    selected !== null &&
    response.window.dateFrom === selected.dateFrom &&
    response.window.dateTo === selected.dateTo &&
    response.window.asOf === selected.selectionKey &&
    response.rows.some(
      (row) => row.unifiedCode === selected.unifiedCode && row.source === selected.source,
    )
      ? selected
      : null;
  return (
    <div className="space-y-3">
      <div className="text-sm text-muted-foreground">
        <p>
          统计范围：日线 RAW 与支持来源（{response.window.dateFrom} 至 {response.window.dateTo}）。
        </p>
        <p>
          口径：仅表示已观测到的行情日，不代表完整覆盖、质量合格或价格版本优选；asOf：
          {formatShanghaiTime(response.window.asOf)}。
        </p>
        <p>每个“最新”时间分别按字段取最大值，可能来自不同记录。</p>
        <p>点击某行“查看已入库日期”可读取该证券与来源的已观测日期，并选择历史查询窗口。</p>
      </div>
      <div className="space-y-1 text-sm text-muted-foreground" aria-label="本次返回概览">
        <p>
          本次返回最晚行情日：{latestReturnedDate ?? "—"} · 证券数：{returnedSecurityCount} ·
          证券/来源组数：{response.rows.length}
          {response.truncated ? "（仅统计前 100 组）" : "（本次返回全部分组）"}
        </p>
        <p>
          缺口判断：未知（缺少应有交易日依据）。较早日期只表示早于本次返回的最晚日，不代表确认缺失。
        </p>
        {response.truncated && (
          <p>仅统计本次返回的前 100 组，最晚日与组数均为局部结果；还有其他分组未显示。</p>
        )}
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="grid w-full gap-2 sm:max-w-sm">
          <Label htmlFor="coverage-result-search">检索本次返回</Label>
          <Input
            id="coverage-result-search"
            placeholder="证券代码或来源"
            value={query}
            aria-describedby="coverage-result-scope"
            onChange={(event) => {
              setQuery(event.target.value);
              setPageIndex(0);
            }}
          />
        </div>
        <Button
          type="button"
          variant="outline"
          disabled={query.length === 0 && page.currentPage === 0}
          onClick={() => {
            setQuery("");
            setPageIndex(0);
          }}
        >
          重置本次检索
        </Button>
      </div>
      <p id="coverage-result-scope" className="text-xs text-muted-foreground">
        仅检索本次已返回的分组，每页 20
        组，不另发请求；截断时不包含未返回分组。查找其他结果请使用上方查询条件。
      </p>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p role="status" className="text-sm text-muted-foreground">
          匹配 {page.matchedCount} / {response.rows.length} 组 · 第 {page.currentPage + 1} /{" "}
          {page.pageCount} 页
        </p>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={page.currentPage === 0}
            onClick={() => setPageIndex(page.currentPage - 1)}
          >
            上一页分组
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={page.currentPage >= page.pageCount - 1}
            onClick={() => setPageIndex(page.currentPage + 1)}
          >
            下一页分组
          </Button>
        </div>
      </div>
      <div className="overflow-x-auto">
        <Table aria-label="行情日线覆盖列表" className="min-w-[1180px]">
          <TableHeader>
            <TableRow>
              <TableHead>证券</TableHead>
              <TableHead>来源</TableHead>
              <TableHead>观测日数</TableHead>
              <TableHead>首个交易日</TableHead>
              <TableHead>末个已观测交易日</TableHead>
              <TableHead>最新行情时间（event_time，上海）</TableHead>
              <TableHead>最新可用时间（available_time，上海）</TableHead>
              <TableHead>最新入库时间（processing_time，上海）</TableHead>
              <TableHead className="sticky right-0 z-10 w-40 bg-background shadow-[-1px_0_0_var(--border)]">
                操作
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {page.rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={9} className="text-muted-foreground">
                  {response.rows.length === 0
                    ? "当前条件下暂无已观测到的日线行情"
                    : "本次返回中没有匹配的分组，请调整本次检索，或使用上方查询条件读取其他结果。"}
                </TableCell>
              </TableRow>
            ) : (
              page.rows.map((row) => (
                <TableRow key={`${row.unifiedCode}-${row.source}`}>
                  <TableCell>{row.unifiedCode}</TableCell>
                  <TableCell>{row.source}</TableCell>
                  <TableCell>{row.observedBarDays}</TableCell>
                  <TableCell>{row.firstDate}</TableCell>
                  <TableCell>
                    <span>{row.lastDate}</span>
                    {latestReturnedDate !== null && row.lastDate < latestReturnedDate && (
                      <span className="block text-xs text-muted-foreground">{earlierDateHint}</span>
                    )}
                  </TableCell>
                  <TableCell>{formatShanghaiTime(row.latestEventTime)}</TableCell>
                  <TableCell>{formatShanghaiTime(row.latestAvailableTime)}</TableCell>
                  <TableCell>{formatShanghaiTime(row.latestProcessingTime)}</TableCell>
                  <TableCell className="sticky right-0 z-10 w-40 bg-background shadow-[-1px_0_0_var(--border)]">
                    <Button
                      type="button"
                      variant="link"
                      size="sm"
                      aria-label={`查看已入库日期 ${row.unifiedCode} ${row.source}`}
                      aria-haspopup="dialog"
                      onClick={(event) => {
                        triggerRef.current = event.currentTarget;
                        setSelected({
                          dateFrom: response.window.dateFrom,
                          dateTo: response.window.dateTo,
                          unifiedCode: row.unifiedCode,
                          source: row.source,
                          selectionKey: response.window.asOf,
                        });
                      }}
                    >
                      查看已入库日期
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
      {response.truncated && (
        <p role="status" className="text-sm text-amber-700 dark:text-amber-300">
          结果超过 100 个证券/来源组，仅显示前 100 组；请缩小日期、来源或证券筛选。
        </p>
      )}
      <DetailDrawer
        open={activeSelection !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title="已入库日期"
        description={
          activeSelection === null
            ? "查看证券与来源的已观测日期。"
            : `${activeSelection.unifiedCode} · ${activeSelection.source}。日期明细独立查询，不代表完整覆盖。`
        }
        returnFocusRef={triggerRef}
      >
        {activeSelection !== null && (
          <MarketCoverageHistoryPanel
            key={`${activeSelection.unifiedCode}-${activeSelection.source}-${activeSelection.dateFrom}-${activeSelection.dateTo}-${activeSelection.selectionKey}`}
            selection={activeSelection}
          />
        )}
      </DetailDrawer>
    </div>
  );
}
