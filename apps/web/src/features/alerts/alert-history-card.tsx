import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import {
  ALERT_HISTORY_DELIVERY,
  ALERT_HISTORY_OUTCOMES,
  readAlertHistory,
  selectAlertHistory,
  formatAlertHistoryTime,
  type AlertHistoryModel,
  type AlertHistoryFilters,
} from "./alert-history";
import { AlertHistoryDetail } from "./alert-history-detail";

export function AlertHistoryCard({ workspace }: { workspace: unknown }) {
  let model: AlertHistoryModel;
  try {
    model = readAlertHistory(workspace);
  } catch {
    return (
      <p role="alert" className="rounded-lg border p-4 text-sm text-destructive">
        评估历史数据不可用，请刷新后核对。
      </p>
    );
  }
  return <HistoryView model={model} />;
}
const selectClass =
  "h-9 w-full cursor-pointer rounded-md border border-input bg-background px-3 text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none";
function HistoryView({ model }: { model: AlertHistoryModel }) {
  const id = useId();
  const [filters, setFilters] = useState<AlertHistoryFilters>({
    query: "",
    outcome: "ALL",
    delivery: "ALL",
  });
  const [page, setPage] = useState(1);
  const result = selectAlertHistory(model.rows, filters, page);
  function change(next: Partial<AlertHistoryFilters>) {
    setFilters((old) => ({ ...old, ...next }));
    setPage(1);
  }
  const filtered = filters.query !== "" || filters.outcome !== "ALL" || filters.delivery !== "ALL";
  return (
    <Card>
      <CardHeader>
        <CardTitle>评估与通知历史</CardTitle>
        <CardDescription>
          仅检索本次返回的最近记录，最多 200 条；重复事件只保留一条，通知失败不会删除触发证据。
        </CardDescription>
        <p className="text-xs text-muted-foreground">
          读取时间：
          <time dateTime={model.generatedAt}>{formatAlertHistoryTime(model.generatedAt)}</time>
          （北京时间）。按数据可用时间倒序；观测值保留原值，不推测历史规则条件。
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid items-end gap-4 sm:grid-cols-2 xl:grid-cols-[minmax(14rem,2fr)_1fr_1fr_auto]">
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-query`}>历史证券或规则编号</Label>
            <Input
              id={`${id}-query`}
              type="search"
              placeholder="证券代码或规则编号片段"
              maxLength={128}
              value={filters.query}
              onChange={(e) => change({ query: e.target.value })}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-outcome`}>评估结果筛选</Label>
            <select
              id={`${id}-outcome`}
              className={selectClass}
              value={filters.outcome}
              onChange={(e) =>
                change({ outcome: e.target.value as AlertHistoryFilters["outcome"] })
              }
            >
              <option value="ALL">全部结果</option>
              {Object.entries(ALERT_HISTORY_OUTCOMES).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-delivery`}>通知投递筛选</Label>
            <select
              id={`${id}-delivery`}
              className={selectClass}
              value={filters.delivery}
              onChange={(e) =>
                change({ delivery: e.target.value as AlertHistoryFilters["delivery"] })
              }
            >
              <option value="ALL">全部投递状态</option>
              {Object.entries(ALERT_HISTORY_DELIVERY).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <Button
            type="button"
            variant="outline"
            className="cursor-pointer disabled:cursor-not-allowed"
            disabled={!filtered}
            onClick={() => change({ query: "", outcome: "ALL", delivery: "ALL" })}
          >
            重置历史筛选
          </Button>
        </div>
        <p
          role="status"
          className="text-sm text-muted-foreground"
        >{`本次读取 ${model.rows.length} 条，匹配 ${result.count} 条 · 第 ${result.page} / ${result.pageCount} 页`}</p>
        {result.rows.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            {model.rows.length === 0
              ? "尚无评估历史。规则被数据任务评估后，结果会显示在这里。"
              : "没有符合条件的评估记录，请调整或重置历史筛选。"}
          </p>
        ) : (
          <div
            role="region"
            aria-label="评估历史，可横向滚动"
            tabIndex={0}
            className="overflow-x-auto rounded-md border focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none [&>[data-slot=table-container]]:overflow-visible"
          >
            <Table className="min-w-[1000px]">
              <TableHeader>
                <TableRow>
                  {["数据可用时间", "证券", "结果", "观测值（原值）", "通知", "说明", "详情"].map(
                    (label) => (
                      <TableHead key={label}>{label}</TableHead>
                    ),
                  )}
                </TableRow>
              </TableHeader>
              <TableBody>
                {result.rows.map((row) => (
                  <TableRow key={`${model.generatedAt}:${row.historyId}`}>
                    <TableCell className="whitespace-nowrap">
                      <time dateTime={row.availableTime}>
                        {formatAlertHistoryTime(row.availableTime)}
                      </time>
                    </TableCell>
                    <TableCell className="font-mono">{row.instrumentId}</TableCell>
                    <TableCell>{ALERT_HISTORY_OUTCOMES[row.outcome]}</TableCell>
                    <TableCell className="font-mono">{row.observedValue ?? "无观测值"}</TableCell>
                    <TableCell>{ALERT_HISTORY_DELIVERY[row.notificationStatus]}</TableCell>
                    <TableCell className="max-w-xs truncate" title={row.detail}>
                      {row.detail}
                    </TableCell>
                    <TableCell>
                      <AlertHistoryDetail row={row} generatedAt={model.generatedAt} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        <div className="flex flex-wrap justify-end gap-2" aria-label="评估历史分页">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="cursor-pointer disabled:cursor-not-allowed"
            disabled={result.page <= 1}
            onClick={() => setPage(result.page - 1)}
          >
            上一页历史
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="cursor-pointer disabled:cursor-not-allowed"
            disabled={result.page >= result.pageCount}
            onClick={() => setPage(result.page + 1)}
          >
            下一页历史
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
