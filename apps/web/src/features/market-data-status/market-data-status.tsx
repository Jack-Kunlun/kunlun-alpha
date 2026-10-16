import type { MarketDataSyncStatus } from "@kunlun/shared-types";
import { Badge } from "@/components/ui/badge";
import type { ObjectQueryResult } from "@/lib/use-api-query";
import { useMarketDataStatus } from "./use-market-data-status";

const STATUS_LABEL: Record<MarketDataSyncStatus["status"], string> = {
  UNKNOWN: "状态未知",
  RUNNING: "任务运行中",
  SUCCEEDED: "任务成功",
  FAILED: "本次失败",
};
const ERROR_LABEL: Record<NonNullable<MarketDataSyncStatus["errorCode"]>, string> = {
  SOURCE_ERROR: "数据源请求失败，已入库行情保留。",
  VALIDATION_ERROR: "采集数据或配置校验失败，已入库行情保留。",
  SYNC_ERROR: "采集任务未完成，请检查任务日志；已入库行情保留。",
  NO_RUN: "暂无采集任务记录。",
  STATUS_UNAVAILABLE: "采集状态未配置或暂时不可读。",
  INVALID_STATUS: "采集记录无法验证，当前状态未知。",
  SCOPE_MISMATCH: "采集清单与当前日线样本不一致，当前状态未知。",
  RUN_STATUS_EXPIRED: "上次任务未结束，当前状态待确认。",
};

function TaskTime({ value }: { value: string | null }) {
  if (value === null) return <span>暂无</span>;
  return (
    <time dateTime={value}>
      {new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(new Date(value))}
    </time>
  );
}

function StatusContent({
  result,
  instrumentId,
}: {
  result: ObjectQueryResult<MarketDataSyncStatus>;
  instrumentId?: string | undefined;
}) {
  if (result.status === "loading") return <p role="status">正在查询采集状态…</p>;
  if (result.status === "forbidden") return <p role="alert">无权查看采集状态</p>;
  if (result.status === "error") return <p role="alert">采集状态暂时不可用，请稍后重试。</p>;
  if (result.status === "empty" || result.data === null) return <p>暂无采集任务记录。</p>;
  const data = result.data;
  if (instrumentId && data.symbols.length > 0 && !data.symbols.includes(instrumentId)) {
    return <p>此标的不在当前采集清单，请以该标的数据截止时间为准。</p>;
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={data.status === "FAILED" ? "destructive" : "outline"}>
          {STATUS_LABEL[data.status]}
        </Badge>
        <span className="text-xs text-muted-foreground">
          {data.provider === "akshare" ? "AKShare" : "Tushare"} · 当前清单 {data.symbols.length}{" "}
          个标的
        </span>
      </div>
      <dl className="grid gap-3 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs text-muted-foreground">最近尝试</dt>
          <dd className="mt-1">
            <TaskTime value={data.lastAttemptAt} />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">最近任务成功</dt>
          <dd className="mt-1">
            <TaskTime value={data.lastSuccessAt} />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">本次结束</dt>
          <dd className="mt-1">
            <TaskTime value={data.lastFinishedAt} />
          </dd>
        </div>
      </dl>
      {data.errorCode !== null && (
        <p role={data.status === "FAILED" ? "alert" : "status"}>{ERROR_LABEL[data.errorCode]}</p>
      )}
      {data.lastSuccessResult !== null && (
        <p className="text-xs text-muted-foreground">
          最近成功任务：请求 {data.lastSuccessResult.requests} · 接收{" "}
          {data.lastSuccessResult.receivedBars} · 写入 {data.lastSuccessResult.writtenBars}
        </p>
      )}
      {data.status === "SUCCEEDED" && data.lastSuccessResult?.writtenBars === 0 && (
        <p className="text-xs text-muted-foreground">本次检查没有新增写入。</p>
      )}
    </div>
  );
}

export function MarketDataStatusView({
  result,
  historical = false,
  instrumentId,
}: {
  result: ObjectQueryResult<MarketDataSyncStatus>;
  historical?: boolean | undefined;
  instrumentId?: string | undefined;
}) {
  return (
    <section
      aria-label="当前采集任务"
      className="space-y-3 rounded-2xl border bg-card/70 p-5 text-sm"
    >
      <h3 className="font-semibold">当前采集任务</h3>
      {historical && (
        <p className="text-xs text-muted-foreground">当前采集状态，不随历史点时变化。</p>
      )}
      <StatusContent result={result} instrumentId={instrumentId} />
      <p className="text-xs text-muted-foreground">
        行情日期以数据区域的“数据截止”为准；任务成功不代表产生新行情。任务时间均为北京时间。
      </p>
    </section>
  );
}

export function MarketDataStatus({
  historical,
  instrumentId,
}: {
  historical?: boolean | undefined;
  instrumentId?: string | undefined;
}) {
  const result = useMarketDataStatus();
  return (
    <MarketDataStatusView result={result} historical={historical} instrumentId={instrumentId} />
  );
}
