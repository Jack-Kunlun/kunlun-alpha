import { useRef } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import type { PaperBuyOrderRow } from "./paper-buy-orders";
import { PaperInstrumentLink } from "./paper-instrument-link";
import { formatPaperLedgerTime } from "./paper-terminal-display";

export function PaperOrderDetailFields({
  row,
  generatedAt,
}: {
  row: PaperBuyOrderRow;
  generatedAt: string;
}) {
  return (
    <>
      <dl className="grid gap-5 text-sm sm:grid-cols-2">
        {[
          ["订单编号", row.id],
          ["方向", row.side],
          ["状态", row.status],
          ["委托数量", String(row.quantity)],
          ["已成交数量", String(row.filled)],
          ["模拟成交均价（CNY）", row.price ?? "未成交"],
          ["累计模拟手续费（CNY）", row.fees],
        ].map(([label, value]) => (
          <div key={label} className={label === "订单编号" ? "min-w-0 sm:col-span-2" : "min-w-0"}>
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="mt-2 break-all font-mono">{value}</dd>
          </div>
        ))}
        <div>
          <dt className="text-muted-foreground">证券</dt>
          <dd className="mt-2">
            <PaperInstrumentLink instrumentId={row.instrument} />
          </dd>
        </div>
        {(
          [
            ["订单更新时间", row.time],
            ["工作区快照时间", generatedAt],
          ] as const
        ).map(([label, time]) => (
          <div key={label} className="min-w-0 sm:col-span-2">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="mt-2 break-all">
              <time dateTime={time}>{formatPaperLedgerTime(time)}</time>
              <span className="mt-1 block font-mono text-xs text-muted-foreground">{time}</span>
            </dd>
          </div>
        ))}
      </dl>
      <section className="mt-6 space-y-2 text-sm" aria-label="订单说明">
        <h3 className="font-medium">订单说明</h3>
        <p className="break-words whitespace-pre-wrap">{row.explanation}</p>
      </section>
    </>
  );
}

export function PaperOrderDetailDrawer({
  row,
  generatedAt,
}: {
  row: PaperBuyOrderRow;
  generatedAt: string;
}) {
  const title = useRef<HTMLHeadingElement>(null);
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="cursor-pointer"
          aria-label={`查看 ${row.instrument} 模拟订单 ${row.id} 详情`}
        >
          查看详情
        </Button>
      </DialogTrigger>
      <DialogContent
        className="top-0 right-0 left-auto flex h-dvh max-h-dvh w-full max-w-xl translate-x-0 translate-y-0 flex-col gap-0 rounded-none p-0 sm:max-w-xl"
        showCloseButton={false}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          title.current?.focus();
        }}
      >
        <DialogHeader className="shrink-0 border-b p-6 text-left">
          <DialogTitle ref={title} tabIndex={-1}>
            模拟订单详情
          </DialogTitle>
          <DialogDescription>
            本次账本快照中的订单原值，仅用于模拟研究查阅，不代表真实行情或真实成交。
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto p-6">
          <PaperOrderDetailFields row={row} generatedAt={generatedAt} />
        </div>
        <DialogFooter className="shrink-0 border-t p-4">
          <DialogClose asChild>
            <Button type="button" variant="outline" className="cursor-pointer">
              关闭详情
            </Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
