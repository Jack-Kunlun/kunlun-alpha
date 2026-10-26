import { useRef } from "react";
import { Link } from "react-router";
import type { WatchlistAlertHistory } from "@kunlun/shared-types";
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
import { currentInstrumentDailyHref } from "@/features/instrument/instrument-daily-link";
import {
  ALERT_HISTORY_DELIVERY,
  ALERT_HISTORY_OUTCOMES,
  formatAlertHistoryTime,
} from "./alert-history";

export function AlertHistoryDetailFields({
  row,
  generatedAt,
}: {
  row: WatchlistAlertHistory;
  generatedAt: string;
}) {
  const fields = [
    ["证券", row.instrumentId],
    ["评估结果", ALERT_HISTORY_OUTCOMES[row.outcome]],
    ["观测值（原值）", row.observedValue ?? "无观测值"],
    ["本次读取的通知状态", ALERT_HISTORY_DELIVERY[row.notificationStatus]],
    ["历史记录编号", row.historyId],
    ["规则编号", row.ruleId],
    ["规则修订编号", row.revisionId],
    ["事件编号", row.eventId],
    ["通知编号", row.notificationId ?? "未产生通知"],
  ];
  return (
    <>
      <dl className="grid gap-5 text-sm">
        {fields.map(([label, value]) => (
          <div key={label} className="min-w-0">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="mt-2 break-all font-mono">{value}</dd>
          </div>
        ))}
        {(
          [
            ["事件时间", row.eventTime],
            ["数据可用时间", row.availableTime],
            ["记录写入时间", row.createdAt],
            ["本次读取时间", generatedAt],
          ] as const
        ).map(([label, time]) => (
          <div key={label} className="min-w-0">
            <dt className="text-muted-foreground">{label}（北京时间）</dt>
            <dd className="mt-2">
              <time dateTime={time}>{formatAlertHistoryTime(time)}</time>
              <span className="mt-1 block break-all font-mono text-xs text-muted-foreground">
                {time}
              </span>
            </dd>
          </div>
        ))}
      </dl>
      <section className="mt-6 space-y-2 text-sm" aria-label="评估说明">
        <h3 className="font-medium">评估说明</h3>
        <p className="break-words whitespace-pre-wrap">{row.detail}</p>
      </section>
    </>
  );
}

export function AlertHistoryDetail({
  row,
  generatedAt,
}: {
  row: WatchlistAlertHistory;
  generatedAt: string;
}) {
  const title = useRef<HTMLHeadingElement>(null);
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="cursor-pointer"
          aria-label={`查看 ${row.instrumentId} 评估记录 ${row.historyId} 详情`}
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
            评估记录详情
          </DialogTitle>
          <DialogDescription>
            已保存的评估证据，通知状态以本次读取为准。当前日线用于继续研究，不代表触发时行情。
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto p-6">
          <AlertHistoryDetailFields row={row} generatedAt={generatedAt} />
        </div>
        <DialogFooter className="shrink-0 border-t p-4">
          <AlertHistoryCurrentDailyLink instrumentId={row.instrumentId} />
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

export function AlertHistoryCurrentDailyLink({ instrumentId }: { instrumentId: string }) {
  const href = currentInstrumentDailyHref(instrumentId);
  return href === null ? null : (
    <Button asChild variant="outline" className="cursor-pointer">
      <Link to={href} aria-label={`查看 ${instrumentId} 当前已入库日线`}>
        查看当前日线
      </Link>
    </Button>
  );
}
