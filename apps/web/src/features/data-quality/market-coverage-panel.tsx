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

interface MarketCoveragePanelProps {
  response: MarketCoverageResponse;
}

export function MarketCoveragePanel({ response }: MarketCoveragePanelProps) {
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
      </div>
      <div className="overflow-x-auto">
        <Table aria-label="行情日线覆盖列表" className="min-w-[1180px]">
          <TableHeader>
            <TableRow>
              <TableHead>证券</TableHead>
              <TableHead>来源</TableHead>
              <TableHead>观测日数</TableHead>
              <TableHead>首个交易日</TableHead>
              <TableHead>末个交易日</TableHead>
              <TableHead>最新行情时间（event_time，上海）</TableHead>
              <TableHead>最新可用时间（available_time，上海）</TableHead>
              <TableHead>最新入库时间（processing_time，上海）</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {response.rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="text-muted-foreground">
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
                  <TableCell>{row.lastDate}</TableCell>
                  <TableCell>{formatShanghaiTime(row.latestEventTime)}</TableCell>
                  <TableCell>{formatShanghaiTime(row.latestAvailableTime)}</TableCell>
                  <TableCell>{formatShanghaiTime(row.latestProcessingTime)}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
      {response.truncated && (
        <p role="status" className="text-sm text-amber-700 dark:text-amber-300">
          结果超过 100 条，请缩小日期、来源或证券筛选。
        </p>
      )}
    </div>
  );
}
