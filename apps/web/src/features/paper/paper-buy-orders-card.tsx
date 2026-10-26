import { useId, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { PAPER_ORDER_STATUSES } from "./paper-buy-orders";
import {
  readPaperOrderBrowser,
  selectPaperOrders,
  type PaperOrderBrowser,
  type PaperOrderFilters,
} from "./paper-order-browser";
import { PaperOrderDetailDrawer } from "./paper-order-detail-drawer";
import { PaperInstrumentLink } from "./paper-instrument-link";
import { formatPaperLedgerTime } from "./paper-terminal-display";

export function PaperBuyOrdersCard({ workspace }: { workspace: unknown }) {
  let model: PaperOrderBrowser;
  try {
    model = readPaperOrderBrowser(workspace);
  } catch {
    return (
      <p role="alert" className="text-sm text-red-700 dark:text-red-300">
        模拟成交记录不可用，请刷新账本核对。
      </p>
    );
  }
  return <PaperOrders model={model} />;
}

const selectClass =
  "h-9 w-full cursor-pointer rounded-md border border-input bg-background px-3 text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none";

function PaperOrders({ model }: { model: PaperOrderBrowser }) {
  const id = useId();
  const [filters, setFilters] = useState<PaperOrderFilters>({
    text: "",
    side: "ALL",
    status: "ALL",
  });
  const [page, setPage] = useState(1);
  const result = selectPaperOrders(model.rows, filters, page);
  function change(next: Partial<PaperOrderFilters>) {
    setFilters((previous) => ({ ...previous, ...next }));
    setPage(1);
  }
  const filtered = filters.text.length > 0 || filters.side !== "ALL" || filters.status !== "ALL";
  return (
    <Card>
      <CardHeader>
        <CardTitle>模拟订单记录</CardTitle>
        <p className="text-sm text-muted-foreground">
          人工假设价格下的模拟记录，均价与手续费均来自服务端；不代表真实行情或真实成交。点击证券代码可查看当前已入库日线。
        </p>
        <p className="text-xs text-muted-foreground">
          工作区快照：
          <time dateTime={model.generatedAt}>{formatPaperLedgerTime(model.generatedAt)}</time>
          （北京时间）。按订单更新时间倒序，仅筛选本次已读取记录。
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {model.degraded ? (
          <p role="alert" className="text-sm text-destructive">
            账本存在异常，以下仅供按原快照查阅，不能作为交易许可。
          </p>
        ) : null}
        <div className="grid items-end gap-4 sm:grid-cols-2 xl:grid-cols-[minmax(14rem,2fr)_1fr_1fr_auto]">
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-search`}>搜索证券或订单编号</Label>
            <Input
              id={`${id}-search`}
              type="search"
              placeholder="证券代码或订单编号片段"
              value={filters.text}
              maxLength={128}
              onChange={(event) => change({ text: event.target.value })}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-side`}>订单方向</Label>
            <select
              id={`${id}-side`}
              className={selectClass}
              value={filters.side}
              onChange={(event) =>
                change({ side: event.target.value as PaperOrderFilters["side"] })
              }
            >
              <option value="ALL">全部方向</option>
              <option value="BUY">模拟买入</option>
              <option value="SELL">模拟卖出</option>
            </select>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-status`}>订单状态</Label>
            <select
              id={`${id}-status`}
              className={selectClass}
              value={filters.status}
              onChange={(event) =>
                change({ status: event.target.value as PaperOrderFilters["status"] })
              }
            >
              <option value="ALL">全部状态</option>
              {Object.entries(PAPER_ORDER_STATUSES).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <Button
            type="button"
            variant="outline"
            disabled={!filtered}
            className="cursor-pointer disabled:cursor-not-allowed"
            onClick={() => change({ text: "", side: "ALL", status: "ALL" })}
          >
            重置筛选
          </Button>
        </div>
        <p
          role="status"
          className="text-sm text-muted-foreground"
        >{`显示 ${result.count} / ${model.rows.length} 笔 · 第 ${result.page} / ${result.pageCount} 页`}</p>
        {result.rows.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {model.rows.length === 0
              ? "暂无模拟订单"
              : "没有符合条件的模拟订单，请调整或重置筛选。"}
          </p>
        ) : (
          <div
            role="region"
            aria-label="模拟订单记录，可横向滚动"
            tabIndex={0}
            className="overflow-x-auto rounded-md border focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none [&>[data-slot=table-container]]:overflow-visible"
          >
            <Table className="min-w-[960px]">
              <TableHeader>
                <TableRow>
                  {[
                    "证券",
                    "方向",
                    "状态",
                    "数量",
                    "已成交",
                    "模拟均价（CNY）",
                    "手续费（CNY）",
                    "记录时间",
                    "详情",
                  ].map((label) => (
                    <TableHead key={label}>{label}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {result.rows.map((row) => (
                  <TableRow key={`${model.generatedAt}:${row.id}`}>
                    <TableCell className="font-mono">
                      <PaperInstrumentLink instrumentId={row.instrument} />
                    </TableCell>
                    <TableCell>{row.side}</TableCell>
                    <TableCell>{row.status}</TableCell>
                    <TableCell>{row.quantity}</TableCell>
                    <TableCell>{row.filled}</TableCell>
                    <TableCell className="font-mono">{row.price ?? "—"}</TableCell>
                    <TableCell className="font-mono">{row.fees}</TableCell>
                    <TableCell>
                      <time dateTime={row.time}>{formatPaperLedgerTime(row.time)}</time>
                    </TableCell>
                    <TableCell>
                      <PaperOrderDetailDrawer row={row} generatedAt={model.generatedAt} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        <div className="flex flex-wrap justify-end gap-2" aria-label="模拟订单分页">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={result.page <= 1}
            className="cursor-pointer disabled:cursor-not-allowed"
            onClick={() => setPage(result.page - 1)}
          >
            上一页订单
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={result.page >= result.pageCount}
            className="cursor-pointer disabled:cursor-not-allowed"
            onClick={() => setPage(result.page + 1)}
          >
            下一页订单
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
