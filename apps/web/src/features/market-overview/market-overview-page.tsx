import type { MarketOverviewSnapshot } from "@kunlun/shared-types";
import { Badge } from "@/components/ui/badge";
import { useTerminalFilters } from "@/app/filter-context";
import type { ObjectQueryResult } from "@/lib/use-api-query";
import { useMarketOverview } from "./use-market-overview";
import { MarketDataStatus } from "@/features/market-data-status/market-data-status";

function shanghaiTime(value: string | null): string {
  if (value === null) return "暂无";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function exactDecimal(value: string): string {
  const [whole = "0", fraction] = value.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return fraction === undefined ? grouped : `${grouped}.${fraction}`;
}

function MetricCard({
  eyebrow,
  value,
  detail,
}: {
  eyebrow: string;
  value: string;
  detail: string;
}) {
  return (
    <article className="rounded-2xl border bg-card p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
        {eyebrow}
      </p>
      <strong className="mt-3 block font-mono text-2xl tracking-tight">{value}</strong>
      <p className="mt-2 text-xs text-muted-foreground">{detail}</p>
    </article>
  );
}

function MissingMetric({ label }: { label: string }) {
  return (
    <article className="rounded-2xl border border-dashed bg-muted/20 p-5">
      <p className="text-sm font-medium">{label}</p>
      <p className="mt-2 text-sm text-muted-foreground">当前点时无可用数据，不以零值代替。</p>
    </article>
  );
}

function OverviewContent({ snapshot }: { snapshot: MarketOverviewSnapshot }) {
  const sampleLabel =
    snapshot.dataCutoffTime === null
      ? "无数据"
      : snapshot.mode === "HISTORICAL"
        ? "历史点时"
        : "历史日线";
  const sampleVariant = snapshot.dataCutoffTime === null ? "destructive" : "outline";
  const breadth = snapshot.breadth;
  const turnover = snapshot.turnover;
  return (
    <div className="space-y-6">
      <section className="grid gap-4 rounded-2xl border bg-card/70 p-5 md:grid-cols-[1fr_auto]">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={sampleVariant}>{sampleLabel}</Badge>
            <Badge variant="outline">仅代表当前入库样本，不代表全市场</Badge>
          </div>
          <p className="mt-3 text-sm text-muted-foreground">
            请求点时 {shanghaiTime(snapshot.requestedAsOf)} · 数据截止{" "}
            {shanghaiTime(snapshot.dataCutoffTime)}
          </p>
        </div>
        <div className="text-left text-xs text-muted-foreground md:text-right">
          <p>{snapshot.sourceVersions.length} 个源版本</p>
          <p>{snapshot.evidenceIds.length} 条证据标识</p>
          <p className="mt-2 max-w-xl break-all">{snapshot.sourceVersions.join(" · ")}</p>
        </div>
      </section>

      <section aria-labelledby="overview-indices" className="space-y-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            Pulse
          </p>
          <h2 id="overview-indices" className="text-xl font-semibold">
            核心指数
          </h2>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {snapshot.indices.length === 0 ? (
            <MissingMetric label="指数" />
          ) : (
            snapshot.indices.map((index) => (
              <MetricCard
                key={index.instrumentId}
                eyebrow={`${index.name} · ${index.instrumentId}`}
                value={exactDecimal(index.value)}
                detail={`${index.changeBps >= 0 ? "+" : ""}${(index.changeBps / 100).toFixed(2)}% · ${shanghaiTime(index.dataTime)}`}
              />
            ))
          )}
        </div>
      </section>

      <section aria-label="样本涨跌分布与成交额" className="grid gap-4 md:grid-cols-2">
        {breadth === null ? (
          <MissingMetric label="样本涨跌分布" />
        ) : (
          <MetricCard
            eyebrow="样本涨跌分布"
            value={`${breadth.advancingCount} ↑ / ${breadth.decliningCount} ↓`}
            detail={`上涨占比 ${(breadth.advancingRatioBps / 100).toFixed(1)}% · 可比较样本 ${breadth.sampleSize}`}
          />
        )}
        {turnover === null ? (
          <MissingMetric label="成交额" />
        ) : (
          <MetricCard
            eyebrow="样本成交额"
            value={`¥${exactDecimal(turnover.amountCny)}`}
            detail={`${turnover.sampleSize} 个可比较样本 · 精确十进制汇总`}
          />
        )}
      </section>

      <p className="rounded-xl border border-dashed p-4 text-xs text-muted-foreground">
        日线截至上一可用交易日，不是实时行情。刷新页面只重新查询已入库数据。当前系统没有真实账户或真实下单路径。
      </p>
    </div>
  );
}

export function MarketOverviewView({
  result,
}: {
  result: ObjectQueryResult<MarketOverviewSnapshot>;
}) {
  if (result.status === "loading") {
    return <p role="status">正在加载市场总览…</p>;
  }
  if (result.status === "forbidden") {
    return (
      <p role="alert" className="text-destructive">
        无权访问市场总览
      </p>
    );
  }
  if (result.status === "error") {
    return (
      <p role="alert" className="text-destructive">
        市场数据流中断：{result.error?.message}
      </p>
    );
  }
  if (result.status === "empty" || result.data === null) {
    return <p className="text-muted-foreground">该点时暂无市场总览数据</p>;
  }
  return <OverviewContent snapshot={result.data} />;
}

export function MarketOverviewPage() {
  const { value: filters } = useTerminalFilters();
  const result = useMarketOverview(filters.asOf);
  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
          Market overview · Point-in-time
        </p>
        <h2 className="text-2xl font-semibold tracking-tight">已入库日线样本概览</h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          汇总已入库股票样本的涨跌分布与成交额，显示实际日期和来源；样本数量不代表全市场覆盖。
        </p>
      </header>
      <MarketDataStatus historical={filters.asOf !== null} />
      <MarketOverviewView result={result} />
    </div>
  );
}
