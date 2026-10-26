import { useId, useMemo, useState } from "react";
import type { InstrumentBarsResponse } from "@kunlun/shared-types";
import { List } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatShanghaiTime } from "@/features/data-quality/format-shanghai-time";
import { validateInstrumentBarsWindow } from "./instrument-bars-export";
import { selectInstrumentBarsPage } from "./instrument-bars-page";

export function InstrumentBarsDetailsButton({
  data,
  instrumentId,
  mode,
  asOf,
  onOpenChange,
}: {
  data: InstrumentBarsResponse;
  instrumentId: string;
  mode: InstrumentBarsResponse["mode"];
  asOf: string;
  onOpenChange?: (open: boolean) => void;
}) {
  const [openedData, setOpenedData] = useState<InstrumentBarsResponse | null>(null);
  const valid = useMemo(() => {
    if (
      data.instrumentId !== instrumentId ||
      data.mode !== mode ||
      (mode === "HISTORICAL" && data.requestedAsOf !== asOf)
    )
      return false;
    try {
      validateInstrumentBarsWindow(data);
      return true;
    } catch {
      return false;
    }
  }, [data, instrumentId, mode, asOf]);
  const errorId = useId();
  return (
    <div className="space-y-2 pt-2">
      <Dialog
        open={valid && openedData === data}
        onOpenChange={(open) => {
          setOpenedData(open ? data : null);
          onOpenChange?.(open);
        }}
      >
        <DialogTrigger asChild>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!valid}
            aria-describedby={!valid ? errorId : undefined}
          >
            <List aria-hidden="true" /> 查看明细
          </Button>
        </DialogTrigger>
        <DialogContent className="inset-y-0 right-0 left-auto flex h-dvh max-h-dvh w-full max-w-full translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden rounded-none p-0 sm:max-w-5xl">
          <DialogHeader className="shrink-0 border-b p-5 pr-12 text-left">
            <DialogTitle>日线明细 · {instrumentId}</DialogTitle>
            <DialogDescription>
              打开时窗口的 DAILY / RAW
              原始记录。查阅期间暂停自动刷新，关闭后恢复；仅用于历史研究，不是实时或可成交价格。
            </DialogDescription>
          </DialogHeader>
          <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
            {valid && openedData === data ? (
              <InstrumentBarsDetails key={data.effectiveAsOf} data={data} />
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
      {!valid ? (
        <p id={errorId} role="alert" className="text-xs text-destructive">
          日线明细暂不可用，请刷新当前日线窗口。
        </p>
      ) : null}
    </div>
  );
}

/** Receives the same validated response as the drawer action, without another request. */
export function InstrumentBarsDetails({ data }: { data: InstrumentBarsResponse }) {
  const dateId = useId();
  const [date, setDate] = useState("");
  const [page, setPage] = useState(0);
  const selection = selectInstrumentBarsPage(data.bars, date, page);
  return (
    <section className="min-w-0 space-y-4" aria-label="当前窗口日线明细">
      <div className="space-y-1 break-all rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
        <p className="font-medium text-foreground">
          {data.instrumentId} · {data.mode} · DAILY / RAW · 样本 {data.barCount} 根
        </p>
        <p>
          查询点时：
          <time dateTime={data.effectiveAsOf} title={data.effectiveAsOf}>
            {formatShanghaiTime(data.effectiveAsOf)}
          </time>
        </p>
        <p>数据截止：{formatShanghaiTime(data.dataCutoffTime)}</p>
        <p>来源版本：{data.sourceVersions.join(", ")}</p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="grid gap-2">
          <Label htmlFor={dateId}>查找日期</Label>
          <Input
            id={dateId}
            type="date"
            className="w-44"
            value={date}
            onChange={(event) => {
              setDate(event.target.value);
              setPage(0);
            }}
          />
        </div>
        <Button
          type="button"
          variant="outline"
          disabled={date === ""}
          onClick={() => {
            setDate("");
            setPage(0);
          }}
        >
          重置筛选
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        仅在本次返回的 {data.barCount}{" "}
        根日线内查找，不补齐缺失日期。最新日期在前；数值保留原始精度，成交量与成交额不另作单位换算。
      </p>
      {selection.matchedCount === 0 ? (
        <p
          role="status"
          className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground"
        >
          当前窗口内没有该日期的记录，可重置筛选；这不代表已确认休市或停牌。
        </p>
      ) : (
        <>
          <div
            role="region"
            aria-label="日线明细表，可横向滚动"
            tabIndex={0}
            className="overflow-x-auto rounded-lg border outline-none focus-visible:ring-2 focus-visible:ring-ring [&_[data-slot=table-container]]:overflow-visible"
          >
            <Table className="min-w-[900px]">
              <TableCaption className="sr-only">当前窗口日线原始记录，最新日期在前</TableCaption>
              <TableHeader>
                <TableRow>
                  {[
                    "日期",
                    "开盘",
                    "最高",
                    "最低",
                    "收盘",
                    "原始成交量",
                    "原始成交额",
                    "状态",
                    "来源与证据",
                  ].map((label, index) => (
                    <TableHead
                      key={label}
                      scope="col"
                      className={index > 0 && index < 7 ? "text-right" : undefined}
                    >
                      {label}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {selection.rows.map((bar) => (
                  <TableRow key={bar.date}>
                    <TableCell className="font-mono">
                      <time dateTime={bar.date}>{bar.date}</time>
                    </TableCell>
                    {(["open", "high", "low", "close", "volume", "amount"] as const).map(
                      (field) => (
                        <TableCell key={field} className="text-right font-mono tabular-nums">
                          {bar[field]}
                        </TableCell>
                      ),
                    )}
                    <TableCell>{bar.suspended ? "停牌" : "未标记停牌"}</TableCell>
                    <TableCell className="max-w-80 min-w-44 whitespace-normal">
                      <details className="text-xs">
                        <summary className="cursor-pointer rounded-sm break-all focus-visible:ring-2 focus-visible:ring-ring">
                          {bar.source}
                        </summary>
                        <dl className="mt-2 space-y-2 break-all">
                          {[
                            ["来源版本", bar.sourceVersion],
                            ["数据版本", bar.dataVersion],
                            ["证据", bar.evidenceId],
                            ["事件时间", bar.eventTime],
                            ["可见时间", bar.availableTime],
                            ["处理时间", bar.processingTime],
                          ].map(([label, value]) => (
                            <div key={label}>
                              <dt className="text-muted-foreground">{label}</dt>
                              <dd>
                                {label?.endsWith("时间") ? (
                                  <time dateTime={value} title={value}>
                                    {formatShanghaiTime(value ?? null)}
                                  </time>
                                ) : (
                                  value
                                )}
                              </dd>
                            </div>
                          ))}
                        </dl>
                      </details>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <nav
            aria-label="日线明细分页"
            className="flex flex-wrap items-center justify-between gap-3"
          >
            <Button
              type="button"
              size="sm"
              variant="outline"
              aria-label="日线明细上一页"
              disabled={selection.page === 0}
              onClick={() => setPage(selection.page - 1)}
            >
              上一页
            </Button>
            <p role="status" className="text-xs text-muted-foreground">
              {selection.page + 1} / {selection.pageCount} 页 · 共 {selection.matchedCount} 根
            </p>
            <Button
              type="button"
              size="sm"
              variant="outline"
              aria-label="日线明细下一页"
              disabled={selection.page + 1 >= selection.pageCount}
              onClick={() => setPage(selection.page + 1)}
            >
              下一页
            </Button>
          </nav>
        </>
      )}
    </section>
  );
}
