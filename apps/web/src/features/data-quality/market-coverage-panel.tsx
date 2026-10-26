import { useRef, useState } from "react";
import { DetailDrawer } from "@/components/detail-drawer";
import { Button } from "@/components/ui/button";
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

interface MarketCoveragePanelProps {
  response: MarketCoverageResponse;
}

type SelectedMarketCoverageDays = MarketCoverageDaysQuery & {
  selectionKey: string;
};

export function MarketCoveragePanel({ response }: MarketCoveragePanelProps) {
  const [selected, setSelected] = useState<SelectedMarketCoverageDays | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
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
            {response.rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={9} className="text-muted-foreground">
                  当前条件下暂无已观测到的日线行情
                </TableCell>
              </TableRow>
            ) : (
              response.rows.map((row) => (
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
