import type { PreciousMetalsTerminalSnapshot } from "@kunlun/shared-types";
import {
  Bell,
  CircleDollarSign,
  Clock3,
  Droplets,
  Gem,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { useTerminalFilters } from "@/app/filter-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ObjectQueryResult } from "@/lib/use-api-query";
import { usePreciousMetalsTerminal } from "./use-precious-metals-terminal";

type Fund = PreciousMetalsTerminalSnapshot["funds"][number];

const COMMODITY_LABEL = {
  GOLD: "黄金",
  SILVER: "白银",
  OTHER: "其他",
} as const;

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

function decimal(value: string | null, maximumFractionDigits = 4): string {
  if (value === null) return "—";
  const [whole = "0", fraction = ""] = value.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const clipped = fraction.slice(0, maximumFractionDigits).replace(/0+$/, "");
  return clipped === "" ? grouped : `${grouped}.${clipped}`;
}

function freshnessBadge(value: "FRESH" | "STALE" | "MISSING") {
  const label = { FRESH: "新鲜", STALE: "已过时", MISSING: "缺失" }[value];
  return <Badge variant={value === "FRESH" ? "secondary" : "destructive"}>{label}</Badge>;
}

function premium(value: string | null): string {
  if (value === null) return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value + " bp";
  return `${numeric > 0 ? "+" : ""}${value} bp`;
}

function alertHref(fund: Fund): string {
  const query = new URLSearchParams({
    instrument: fund.alertContext.instrumentId,
    field: "FEATURE_VALUE",
    featureName: fund.alertContext.premiumFeatureName,
  });
  return "/watchlists?" + query.toString();
}

function FundTable({ funds }: { funds: readonly Fund[] }) {
  return (
    <Card className="overflow-hidden border-amber-200/70 bg-white/95 shadow-xl shadow-amber-950/5">
      <CardHeader className="border-b border-amber-100 bg-gradient-to-r from-amber-50 to-slate-50">
        <CardTitle className="flex items-center gap-2 text-lg">
          <Gem aria-hidden="true" className="size-5 text-amber-600" />
          场内基金对比
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-16">排名</TableHead>
              <TableHead className="min-w-44">基金</TableHead>
              <TableHead>交易所价格</TableHead>
              <TableHead>NAV / iNAV</TableHead>
              <TableHead>溢折价</TableHead>
              <TableHead>成交额</TableHead>
              <TableHead>时效</TableHead>
              <TableHead className="text-right">预警</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {funds.map((fund) => (
              <TableRow key={fund.unifiedCode} className="align-top">
                <TableCell className="font-mono text-lg font-black text-amber-700">
                  {fund.ranking?.rank.toString().padStart(2, "0") ?? "—"}
                </TableCell>
                <TableCell>
                  <strong className="block">{fund.displayName}</strong>
                  <span className="font-mono text-xs text-muted-foreground">
                    {fund.unifiedCode} · {fund.assetType}
                  </span>
                  <div className="mt-2 flex flex-wrap gap-1">
                    <Badge variant="outline">{COMMODITY_LABEL[fund.underlyingCommodity]}</Badge>
                    <Badge variant="outline">交易 {fund.tradingCurrency}</Badge>
                    <Badge variant="outline">净值 {fund.navCurrency}</Badge>
                  </div>
                </TableCell>
                <TableCell>
                  <strong className="font-mono text-base">
                    {decimal(fund.market?.close ?? null, 6)}
                  </strong>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {fund.market?.date ?? "无可见行情"}
                  </p>
                </TableCell>
                <TableCell className="font-mono text-xs">
                  <p>NAV {decimal(fund.valuation.navValue, 6)}</p>
                  <p className="mt-1">iNAV {decimal(fund.valuation.inavValue, 6)}</p>
                  <p className="mt-1 font-sans text-muted-foreground">
                    参考 {fund.valuation.referenceKind ?? "不可用"}
                  </p>
                </TableCell>
                <TableCell>
                  <strong
                    className={
                      fund.valuation.premiumDiscountBps?.startsWith("-")
                        ? "font-mono text-emerald-700"
                        : "font-mono text-amber-700"
                    }
                  >
                    {premium(fund.valuation.premiumDiscountBps)}
                  </strong>
                  <p className="mt-1 text-xs text-muted-foreground">仅研究参考</p>
                </TableCell>
                <TableCell className="font-mono">
                  {decimal(fund.market?.turnoverCny ?? null, 2)}
                  <p className="mt-1 font-sans text-xs text-muted-foreground">CNY</p>
                </TableCell>
                <TableCell>
                  {freshnessBadge(fund.valuation.freshness)}
                  <p className="mt-2 text-xs text-muted-foreground">
                    {shanghaiTime(fund.valuation.availableTime)}
                  </p>
                </TableCell>
                <TableCell className="text-right">
                  <Button asChild size="sm" variant="outline">
                    <Link to={alertHref(fund)}>
                      <Bell aria-hidden="true" />
                      溢折价预警
                    </Link>
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function TerminalContent({ snapshot }: { snapshot: PreciousMetalsTerminalSnapshot }) {
  const [query, setQuery] = useState("");
  const [commodity, setCommodity] = useState<"ALL" | Fund["underlyingCommodity"]>("ALL");
  const funds = useMemo(
    () =>
      snapshot.funds.filter(
        (fund) =>
          (commodity === "ALL" || fund.underlyingCommodity === commodity) &&
          (query.trim() === "" ||
            fund.unifiedCode.includes(query.trim().toUpperCase()) ||
            fund.displayName.includes(query.trim())),
      ),
    [commodity, query, snapshot.funds],
  );
  const freshCount = snapshot.funds.filter((fund) => fund.valuation.freshness === "FRESH").length;

  return (
    <div className="space-y-6">
      <header className="relative overflow-hidden rounded-[2rem] border border-amber-300/30 bg-slate-950 px-6 py-8 text-white shadow-2xl shadow-amber-950/15 sm:px-9 sm:py-10">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_12%_10%,rgba(251,191,36,0.24),transparent_28%),radial-gradient(circle_at_88%_35%,rgba(226,232,240,0.16),transparent_25%)]" />
        <div className="relative grid gap-8 xl:grid-cols-[1fr_auto] xl:items-end">
          <div>
            <div className="flex flex-wrap gap-2">
              <Badge className="border-amber-300/30 bg-amber-300/10 text-amber-200">场内基金</Badge>
              <Badge className="border-white/15 bg-white/5 text-slate-200">
                {snapshot.mode === "CURRENT" ? "当前点时" : "历史回放"}
              </Badge>
              <Badge className="border-white/15 bg-white/5 text-slate-200">
                {snapshot.status === "PARTIAL" ? "部分数据" : "数据可用"}
              </Badge>
            </div>
            <p className="mt-6 text-xs font-semibold tracking-[0.28em] text-amber-300 uppercase">
              Exchange-listed precious metals
            </p>
            <h2 className="mt-2 text-3xl font-black tracking-tight sm:text-5xl">
              贵金属基金观察台
            </h2>
            <p className="mt-4 max-w-3xl text-sm leading-7 text-slate-300 sm:text-base">
              同屏比较交易所价格、NAV/iNAV、溢折价、流动性、版本化特征与公开事件。只读取决策时点前已可见的数据。
            </p>
          </div>
          <dl className="grid grid-cols-2 gap-x-5 gap-y-2 rounded-2xl border border-white/10 bg-white/5 p-4 text-xs backdrop-blur">
            <dt className="text-slate-400">数据点时</dt>
            <dd className="text-right font-mono">{shanghaiTime(snapshot.effectiveAsOf)}</dd>
            <dt className="text-slate-400">基金样本</dt>
            <dd className="text-right font-mono">{snapshot.sampleSize}</dd>
            <dt className="text-slate-400">来源版本</dt>
            <dd className="text-right font-mono">{snapshot.sourceVersions.length}</dd>
            <dt className="text-slate-400">证据记录</dt>
            <dd className="text-right font-mono">{snapshot.evidenceIds.length}</dd>
          </dl>
        </div>
      </header>

      <section className="grid gap-4 md:grid-cols-3">
        <Card className="border-amber-200 bg-amber-50/70">
          <CardContent className="flex items-center gap-4 pt-6">
            <CircleDollarSign className="size-8 text-amber-700" />
            <div>
              <p className="text-xs text-muted-foreground">成交额排名</p>
              <strong>{snapshot.rankingMetric}</strong>
            </div>
          </CardContent>
        </Card>
        <Card className="border-slate-200 bg-slate-50/80">
          <CardContent className="flex items-center gap-4 pt-6">
            <Clock3 className="size-8 text-slate-600" />
            <div>
              <p className="text-xs text-muted-foreground">估值参考新鲜</p>
              <strong>
                {freshCount} / {snapshot.sampleSize}
              </strong>
            </div>
          </CardContent>
        </Card>
        <Card className="border-cyan-200 bg-cyan-50/70">
          <CardContent className="flex items-center gap-4 pt-6">
            <Droplets className="size-8 text-cyan-700" />
            <div>
              <p className="text-xs text-muted-foreground">事件时间线</p>
              <strong>{snapshot.events.length} 条可见事件</strong>
            </div>
          </CardContent>
        </Card>
      </section>

      <div className="flex flex-col gap-3 rounded-2xl border bg-card p-4 sm:flex-row sm:items-end">
        <label className="flex-1 space-y-2 text-sm font-medium">
          基金代码或类型
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="518880.SH 或 黄金"
          />
        </label>
        <label className="space-y-2 text-sm font-medium">
          底层品类
          <select
            className="flex h-9 min-w-40 rounded-md border border-input bg-transparent px-3 text-sm"
            value={commodity}
            onChange={(event) => setCommodity(event.target.value as typeof commodity)}
          >
            <option value="ALL">全部</option>
            <option value="GOLD">黄金</option>
            <option value="SILVER">白银</option>
            <option value="OTHER">其他</option>
          </select>
        </label>
      </div>

      {snapshot.gaps.length > 0 && (
        <Card className="border-amber-300 bg-amber-50/80">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <TriangleAlert className="size-4" />
              数据断点已显式保留
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 sm:grid-cols-2">
            {snapshot.gaps.map((item, index) => (
              <p
                key={`${item.scope}-${item.instrumentId}-${index}`}
                className="text-sm text-amber-950"
              >
                <strong>{item.scope}</strong> · {item.instrumentId ?? "全局"} · {item.message}
              </p>
            ))}
          </CardContent>
        </Card>
      )}

      {funds.length === 0 ? (
        <p className="rounded-2xl border border-dashed p-8 text-center text-muted-foreground">
          当前筛选没有匹配的场内贵金属基金。
        </p>
      ) : (
        <FundTable funds={funds} />
      )}

      <section className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <Card>
          <CardHeader>
            <CardTitle>公开事件时间线</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {snapshot.events.length === 0 ? (
              <p className="text-sm text-muted-foreground">该点时没有关联公开事件。</p>
            ) : (
              snapshot.events.map((event) => (
                <article key={event.eventId} className="rounded-2xl border p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <Badge variant="outline">{event.eventType}</Badge>
                    <time className="text-xs text-muted-foreground">
                      {shanghaiTime(event.publishTime)}
                    </time>
                  </div>
                  <h3 className="mt-3 font-semibold">{event.headline}</h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{event.summary}</p>
                  <p className="mt-3 text-xs text-muted-foreground">
                    置信 {(event.confidenceBps / 100).toFixed(1)}% · {event.modelVersion} ·{" "}
                    {event.evidenceIds.length} 条证据
                  </p>
                </article>
              ))
            )}
          </CardContent>
        </Card>
        <Card className="border-slate-300 bg-slate-950 text-white">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="size-5 text-amber-300" />
              估值与执行边界
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm leading-6 text-slate-300">
            <p>NAV 与 iNAV 只用于研究参考和溢折价观察，不是交易所可成交价格。</p>
            <p>
              页面只覆盖交易所上市 ETF/LOF/基金，不包含现货、期货、保证金、换月、交割或实物业务。
            </p>
            <p>当前系统没有真实账户、真实券商连接或真实下单路径。预警只创建站内观察规则。</p>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

export function PreciousMetalsTerminalView({
  result,
}: {
  result: ObjectQueryResult<PreciousMetalsTerminalSnapshot>;
}) {
  if (result.status === "loading") return <p role="status">正在加载贵金属基金终端…</p>;
  if (result.status === "forbidden")
    return (
      <p role="alert" className="text-destructive">
        无权访问贵金属基金终端
      </p>
    );
  if (result.status === "error")
    return (
      <p role="alert" className="text-destructive">
        贵金属基金数据加载失败：{result.error?.message}
      </p>
    );
  if (result.status === "empty" || result.data === null || result.data.status === "EMPTY") {
    return <p className="text-muted-foreground">该点时没有可见的场内贵金属基金。</p>;
  }
  if (result.data.status === "UNAVAILABLE") {
    return (
      <p role="alert" className="text-destructive">
        贵金属基金身份数据源不可用，终端已失败关闭。
      </p>
    );
  }
  return <TerminalContent snapshot={result.data} />;
}

export function PreciousMetalsTerminalPage() {
  const { value: filters } = useTerminalFilters();
  return <PreciousMetalsTerminalView result={usePreciousMetalsTerminal(filters.asOf)} />;
}
