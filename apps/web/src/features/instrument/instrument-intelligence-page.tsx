import type { FormEvent, ReactNode } from "react";
import { useState } from "react";
import type { InstrumentIntelligenceDetail } from "@kunlun/shared-types";
import { useNavigate, useParams } from "react-router";
import { useTerminalFilters } from "@/app/filter-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { ObjectQueryResult } from "@/lib/use-api-query";
import { isCanonicalInstrumentId, useInstrumentIntelligence } from "./use-instrument-intelligence";

type SectionMetadata =
  InstrumentIntelligenceDetail["sections"][keyof InstrumentIntelligenceDetail["sections"]];

const STATUS_LABEL: Readonly<Record<SectionMetadata["status"], string>> = {
  AVAILABLE: "可用",
  EMPTY: "无数据",
  UNAVAILABLE: "不可用",
};

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

function decimal(value: string): string {
  const [whole = "0", fraction] = value.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return fraction === undefined ? grouped : grouped + "." + fraction;
}

function SectionFrame({
  title,
  eyebrow,
  section,
  children,
}: {
  title: string;
  eyebrow: string;
  section: SectionMetadata;
  children: ReactNode;
}) {
  const variant = section.status === "UNAVAILABLE" ? "destructive" : "outline";
  return (
    <Card className="overflow-hidden border-slate-200/80 shadow-sm">
      <CardHeader className="border-b bg-slate-50/70">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold tracking-[0.18em] text-slate-500 uppercase">
              {eyebrow}
            </p>
            <CardTitle className="mt-1 text-lg">{title}</CardTitle>
          </div>
          <Badge variant={variant}>{STATUS_LABEL[section.status]}</Badge>
        </div>
        <div className="grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
          <span>数据截止 {shanghaiTime(section.dataCutoffTime)}</span>
          <span className="sm:text-right">
            {section.sourceVersions.length} 个版本 · {section.evidenceIds.length} 条证据
          </span>
        </div>
      </CardHeader>
      <CardContent className="pt-5">
        {section.status === "UNAVAILABLE" ? (
          <p
            role="alert"
            className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
          >
            数据源当前不可用：{section.unavailableReason}
          </p>
        ) : section.status === "EMPTY" ? (
          <p className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">
            该点时没有满足可见性门槛的数据，不以最新值或零值代替。
          </p>
        ) : (
          children
        )}
      </CardContent>
    </Card>
  );
}

function DetailContent({ detail }: { detail: InstrumentIntelligenceDetail }) {
  const identity = detail.sections.identity.data;
  const market = detail.sections.market.data;
  const emotion = detail.sections.emotion.data;
  return (
    <div className="space-y-6">
      <header className="relative overflow-hidden rounded-3xl border bg-slate-950 p-6 text-white shadow-xl sm:p-8">
        <div className="absolute inset-y-0 right-0 w-1/2 bg-[radial-gradient(circle_at_center,rgba(251,191,36,0.22),transparent_66%)]" />
        <div className="relative grid gap-6 lg:grid-cols-[1fr_auto] lg:items-end">
          <div>
            <div className="flex flex-wrap gap-2">
              <Badge className="border-amber-300/40 bg-amber-300/10 text-amber-200">
                {detail.mode === "CURRENT" ? "当前点时" : "历史回放"}
              </Badge>
              <Badge className="border-white/20 bg-white/5 text-slate-200">
                {detail.snapshotBoundary.consistency}
              </Badge>
            </div>
            <p className="mt-6 text-sm text-slate-400">{detail.instrumentId}</p>
            <h2 className="mt-1 text-3xl font-semibold tracking-tight sm:text-4xl">
              {identity?.name ?? "个股 Intelligence"}
            </h2>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300">
              行情、市场情绪、板块、事件、公开龙虎榜、KOL Claim 与特征在同一 effectiveAsOf
              下聚合。跨库一致性为明确披露的 best effort。
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 text-right text-xs text-slate-400">
            <span>请求点时</span>
            <strong className="font-mono text-slate-100">
              {shanghaiTime(detail.requestedAsOf)}
            </strong>
            <span>生成时间</span>
            <strong className="font-mono text-slate-100">{shanghaiTime(detail.generatedAt)}</strong>
          </div>
        </div>
      </header>

      <section className="grid gap-4 lg:grid-cols-3">
        <SectionFrame title="证券身份" eyebrow="Identity" section={detail.sections.identity}>
          {identity && (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <dt className="text-muted-foreground">交易所 / 板块</dt>
              <dd className="text-right font-medium">
                {identity.exchange} / {identity.board}
              </dd>
              <dt className="text-muted-foreground">证券类型</dt>
              <dd className="text-right font-medium">{identity.type}</dd>
              <dt className="text-muted-foreground">交易状态</dt>
              <dd className="text-right font-medium">{identity.tradingStatus}</dd>
              <dt className="text-muted-foreground">上市日期</dt>
              <dd className="text-right font-medium">{identity.listDate ?? "暂无"}</dd>
            </dl>
          )}
        </SectionFrame>

        <SectionFrame title="最新可见行情" eyebrow="Market" section={detail.sections.market}>
          {market && (
            <div>
              <strong className="font-mono text-3xl tracking-tight">{decimal(market.close)}</strong>
              <p className="mt-1 text-xs text-muted-foreground">
                {market.date} · RAW · {market.dataVersion}
              </p>
              <dl className="mt-4 grid grid-cols-4 gap-2 text-center text-xs">
                <div>
                  <dt className="text-muted-foreground">开</dt>
                  <dd className="mt-1 font-mono">{market.open}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">高</dt>
                  <dd className="mt-1 font-mono">{market.high}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">低</dt>
                  <dd className="mt-1 font-mono">{market.low}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">额</dt>
                  <dd className="mt-1 font-mono">{decimal(market.amount)}</dd>
                </div>
              </dl>
            </div>
          )}
        </SectionFrame>

        <SectionFrame title="市场情绪" eyebrow="Emotion" section={detail.sections.emotion}>
          {emotion && (
            <div>
              <strong className="font-mono text-3xl">{emotion.score}</strong>
              <p className="mt-2 text-sm text-muted-foreground">
                置信度 {(emotion.confidenceBps / 100).toFixed(1)}% · 样本 {emotion.sampleSize}
              </p>
              <p className="mt-3 text-xs text-muted-foreground">{emotion.algorithmVersion}</p>
            </div>
          )}
        </SectionFrame>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <SectionFrame title="点时板块归属" eyebrow="Sector" section={detail.sections.sector}>
          <div className="flex flex-wrap gap-2">
            {detail.sections.sector.data.map((item) => (
              <span
                key={item.sectorId}
                className="rounded-full border bg-slate-50 px-3 py-1.5 text-sm"
              >
                {item.name} <span className="text-xs text-muted-foreground">{item.kind}</span>
              </span>
            ))}
          </div>
        </SectionFrame>

        <SectionFrame title="历史特征" eyebrow="Feature store" section={detail.sections.features}>
          <div className="space-y-3">
            {detail.sections.features.data.map((item) => (
              <article
                key={item.revisionId}
                className="grid gap-2 rounded-xl border p-3 sm:grid-cols-[1fr_auto]"
              >
                <div>
                  <h4 className="font-medium">{item.featureName}</h4>
                  <p className="text-xs text-muted-foreground">
                    {item.featureVersion} · {item.algorithmVersion}
                  </p>
                </div>
                <code className="max-w-64 overflow-hidden text-ellipsis rounded bg-slate-100 px-2 py-1 text-xs">
                  {JSON.stringify(item.value)}
                </code>
              </article>
            ))}
          </div>
        </SectionFrame>
      </section>

      <SectionFrame title="事件时间线" eyebrow="Market event" section={detail.sections.events}>
        <div className="space-y-3">
          {detail.sections.events.data.map((event) => (
            <article key={event.eventId} className="rounded-2xl border p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Badge variant="outline">{event.eventType}</Badge>
                <time className="text-xs text-muted-foreground">
                  {shanghaiTime(event.publishTime)}
                </time>
              </div>
              <h4 className="mt-3 font-semibold">{event.headline}</h4>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{event.summary}</p>
              <p className="mt-3 text-xs text-muted-foreground">
                置信 {(event.confidenceBps / 100).toFixed(1)}% · {event.modelVersion}
              </p>
            </article>
          ))}
        </div>
      </SectionFrame>

      <section className="grid gap-4 xl:grid-cols-2">
        <SectionFrame title="公开龙虎榜席位" eyebrow="Seat facts" section={detail.sections.seats}>
          <div className="space-y-3">
            {detail.sections.seats.data.map((seat) => (
              <article key={seat.revisionId} className="rounded-xl border p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h4 className="font-medium">{seat.rawSeatName}</h4>
                    <p className="text-xs text-muted-foreground">
                      {seat.tradeDate} · {seat.seatId}
                    </p>
                  </div>
                  <strong className="font-mono">{decimal(seat.netAmount)}</strong>
                </div>
                <p className="mt-3 text-xs text-muted-foreground">
                  公开龙虎榜事实，不是券商订单、账户成交或持仓。
                </p>
              </article>
            ))}
          </div>
        </SectionFrame>

        <SectionFrame
          title="KOL 公开表述"
          eyebrow="Claim, not trade"
          section={detail.sections.kolClaims}
        >
          <div className="space-y-3">
            {detail.sections.kolClaims.data.map((claim) => (
              <article
                key={claim.revisionId}
                className="rounded-xl border border-amber-200 bg-amber-50/50 p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">{claim.reviewStatus}</Badge>
                  <Badge variant="outline">{claim.direction}</Badge>
                  <span className="text-xs text-muted-foreground">
                    置信 {(claim.confidenceBps / 100).toFixed(1)}%
                  </span>
                </div>
                <blockquote className="mt-3 text-sm leading-6">{claim.statement}</blockquote>
                <p className="mt-3 text-xs font-medium text-amber-900">
                  这是公开表述 Claim，不代表真实成交、订单或持仓事实。
                </p>
              </article>
            ))}
          </div>
        </SectionFrame>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>证据索引</CardTitle>
        </CardHeader>
        <CardContent>
          {detail.evidence.length === 0 ? (
            <p className="text-sm text-muted-foreground">该点时没有可展示的证据引用。</p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {detail.evidence.map((evidence) => (
                <article key={evidence.evidenceId} className="rounded-xl border p-4">
                  <p className="break-all font-mono text-xs">{evidence.evidenceId}</p>
                  <p className="mt-2 text-sm">{evidence.excerpt ?? "仅保留受控引用标识"}</p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {evidence.source ?? "来源待解析"} · {shanghaiTime(evidence.availableTime)}
                  </p>
                  {evidence.locator && (
                    <a
                      className="mt-3 inline-flex text-sm font-medium text-blue-700 underline underline-offset-4"
                      href={evidence.locator}
                      target="_blank"
                      rel="noreferrer"
                    >
                      打开受控证据
                    </a>
                  )}
                </article>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <p className="rounded-xl border border-dashed p-4 text-xs text-muted-foreground">
        本页仅用于研究解释。当前系统无真实账户、真实券商连接或真实下单路径。
      </p>
    </div>
  );
}

export function InstrumentIntelligenceView({
  instrumentId,
  result,
}: {
  instrumentId: string;
  result: ObjectQueryResult<InstrumentIntelligenceDetail>;
}) {
  if (!isCanonicalInstrumentId(instrumentId)) {
    return (
      <p role="alert" className="text-destructive">
        证券代码必须使用 600519.SH 形式。
      </p>
    );
  }
  if (result.status === "loading") return <p role="status">正在装配个股 Intelligence…</p>;
  if (result.status === "forbidden")
    return (
      <p role="alert" className="text-destructive">
        无权访问个股 Intelligence
      </p>
    );
  if (result.status === "error") {
    return (
      <p role="alert" className="text-destructive">
        个股 Intelligence 加载失败：{result.error?.message}
      </p>
    );
  }
  if (result.status === "empty" || result.data === null) {
    return <p className="text-muted-foreground">该点时没有个股 Intelligence 响应。</p>;
  }
  return <DetailContent detail={result.data} />;
}

export function InstrumentDirectoryPage() {
  const navigate = useNavigate();
  const [value, setValue] = useState("600519.SH");
  const valid = isCanonicalInstrumentId(value);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (valid) navigate("/instruments/" + value);
  }
  return (
    <section className="mx-auto max-w-3xl py-8 sm:py-16">
      <p className="text-xs font-semibold tracking-[0.2em] text-muted-foreground uppercase">
        Instrument lens · Point-in-time
      </p>
      <h2 className="mt-3 text-3xl font-semibold tracking-tight">进入一只标的的证据链</h2>
      <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
        输入统一证券代码，查询同一 effectiveAsOf 下的行情、情绪、板块、事件、席位、KOL Claim
        与特征。
      </p>
      <form
        className="mt-8 flex flex-col gap-3 rounded-2xl border bg-card p-4 shadow-sm sm:flex-row"
        onSubmit={submit}
      >
        <Input
          aria-label="统一证券代码"
          value={value}
          onChange={(event) => setValue(event.target.value.toUpperCase())}
          placeholder="600519.SH"
        />
        <Button type="submit" disabled={!valid}>
          查看 Intelligence
        </Button>
      </form>
      {!valid && (
        <p className="mt-2 text-sm text-destructive">格式示例：600519.SH、000001.SZ、430047.BJ</p>
      )}
    </section>
  );
}

export function InstrumentIntelligencePage() {
  const { instrumentId = "" } = useParams();
  const { value: filters } = useTerminalFilters();
  const result = useInstrumentIntelligence(instrumentId, filters.asOf);
  return <InstrumentIntelligenceView instrumentId={instrumentId} result={result} />;
}
