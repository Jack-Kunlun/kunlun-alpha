import { useState } from "react";
import {
  Archive,
  Clock3,
  Database,
  Fingerprint,
  Landmark,
  Link2,
  MessageSquareQuote,
  Search,
  ShieldAlert,
  UsersRound,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { SeatKolWorkbenchSnapshot } from "./types";
import { useSeatKolWorkbench, type SeatKolWorkbenchFilters } from "./use-seat-kol-workbench";
import "./seat-kol-workbench.css";

type Metric = SeatKolWorkbenchSnapshot["seats"][number]["metrics"][number];
type Evidence = SeatKolWorkbenchSnapshot["seats"][number]["evidence"][number];
type Timeline = SeatKolWorkbenchSnapshot["seats"][number]["timeline"];

function shanghaiTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function metricValue(metric: Metric): string {
  if (metric.valueBps === null) return "待成熟";
  const value = metric.valueBps / 100;
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function MetricTile({ metric }: { metric: Metric }) {
  return (
    <article className="seat-kol-metric">
      <div className="flex items-start justify-between gap-3">
        <span>{metric.label}</span>
        <Badge variant={metric.confidenceBps < 6000 ? "destructive" : "outline"}>
          置信 {(metric.confidenceBps / 100).toFixed(0)}%
        </Badge>
      </div>
      <strong>{metricValue(metric)}</strong>
      <dl>
        <div>
          <dt>样本</dt>
          <dd>{metric.sampleCount}</dd>
        </div>
        <div>
          <dt>算法</dt>
          <dd>{metric.algorithmVersion}</dd>
        </div>
        <div>
          <dt>策略</dt>
          <dd>{metric.policyVersion}</dd>
        </div>
        <div>
          <dt>截止</dt>
          <dd>{shanghaiTime(metric.dataCutoffTime)}</dd>
        </div>
      </dl>
    </article>
  );
}

function EvidenceList({ evidence }: { evidence: readonly Evidence[] }) {
  return (
    <div className="space-y-2">
      {evidence.map((item) => (
        <blockquote key={item.evidenceId} className="seat-kol-evidence">
          <p>{item.excerpt}</p>
          <footer>
            {item.source} · {item.sourceVersion} · {shanghaiTime(item.availableTime)}
          </footer>
        </blockquote>
      ))}
    </div>
  );
}

function TimelineList({ entries }: { entries: Timeline }) {
  return (
    <ol className="seat-kol-timeline">
      {entries.map((entry) => (
        <li key={entry.entryId}>
          <span aria-hidden="true" />
          <div>
            <strong>{entry.title}</strong>
            <small>
              {shanghaiTime(entry.availableTime)} · {entry.kind}
            </small>
          </div>
        </li>
      ))}
    </ol>
  );
}

function SeatProfiles({ snapshot }: { snapshot: SeatKolWorkbenchSnapshot }) {
  return (
    <section className="space-y-4" aria-labelledby="seat-profiles-heading">
      <div className="seat-kol-section-title">
        <Landmark />
        <div>
          <h2 id="seat-profiles-heading">席位档案</h2>
          <p>公开龙虎榜身份、别名与后续统计</p>
        </div>
      </div>
      {snapshot.seats.map((seat) => (
        <Card key={seat.seatId} className="seat-kol-profile-card">
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle>{seat.displayName}</CardTitle>
                <p className="seat-kol-id">{seat.seatId}</p>
              </div>
              <Badge variant="secondary">{seat.seatKind}</Badge>
            </div>
            <div className="flex flex-wrap gap-2">
              {seat.aliases.map((alias) => (
                <Badge key={alias} variant="outline">
                  {alias}
                </Badge>
              ))}
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="seat-kol-metric-grid">
              {seat.metrics.map((metric) => (
                <MetricTile key={metric.metricName} metric={metric} />
              ))}
            </div>
            <div className="grid gap-5 lg:grid-cols-2">
              <div>
                <h3 className="seat-kol-subtitle">证据视图</h3>
                <EvidenceList evidence={seat.evidence} />
              </div>
              <div>
                <h3 className="seat-kol-subtitle">公开时间轴</h3>
                <TimelineList entries={seat.timeline} />
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </section>
  );
}

function KolProfiles({ snapshot }: { snapshot: SeatKolWorkbenchSnapshot }) {
  return (
    <section className="space-y-4" aria-labelledby="kol-profiles-heading">
      <div className="seat-kol-section-title">
        <MessageSquareQuote />
        <div>
          <h2 id="kol-profiles-heading">KOL 公开表述</h2>
          <p>Claim 是公开措辞记录，不是券商成交或持仓事实</p>
        </div>
      </div>
      {snapshot.kols.map((kol) => (
        <Card key={kol.kolId} className="seat-kol-profile-card">
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle>{kol.displayName}</CardTitle>
                <p className="seat-kol-id">{kol.kolId}</p>
              </div>
              <Badge>公开内容研究</Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="seat-kol-metric-grid">
              {kol.metrics.map((metric) => (
                <MetricTile key={metric.metricName} metric={metric} />
              ))}
            </div>
            <div className="space-y-3">
              {kol.claims.map((claim) => (
                <article key={`${claim.claimId}:${claim.revisionId}`} className="seat-kol-claim">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">公开表述 Claim</Badge>
                    <Badge
                      variant={claim.reviewStatus === "APPROVED" ? "secondary" : "destructive"}
                    >
                      {claim.reviewStatus}
                    </Badge>
                    <span>{claim.instrumentId}</span>
                    <span>{claim.direction}</span>
                  </div>
                  <p>{claim.statement}</p>
                  <div className="seat-kol-claim-warning">
                    <ShieldAlert />
                    不是券商成交、订单、持仓或账户事实
                  </div>
                  <EvidenceList evidence={claim.evidence} />
                </article>
              ))}
            </div>
            <TimelineList entries={kol.timeline} />
          </CardContent>
        </Card>
      ))}
    </section>
  );
}

function RelationsAndReview({ snapshot }: { snapshot: SeatKolWorkbenchSnapshot }) {
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <section aria-labelledby="cooccurrence-heading" className="space-y-3">
        <div className="seat-kol-section-title">
          <Link2 />
          <div>
            <h2 id="cooccurrence-heading">共现观察</h2>
            <p>只表示公开数据中的共同出现</p>
          </div>
        </div>
        {snapshot.cooccurrences.map((item) => (
          <Card key={item.cooccurrenceId} className="seat-kol-relation">
            <CardContent>
              <div className="seat-kol-relation-names">
                <span>{item.leftDisplayName}</span>
                <strong>{(item.scoreBps / 100).toFixed(0)}</strong>
                <span>{item.rightDisplayName}</span>
              </div>
              <p>
                样本 {item.sampleCount} · {item.algorithmVersion} · {item.policyVersion}
              </p>
              <p>数据截止 {shanghaiTime(item.dataCutoffTime)}</p>
            </CardContent>
          </Card>
        ))}
      </section>
      <section aria-labelledby="review-queue-heading" className="space-y-3">
        <div className="seat-kol-section-title">
          <Archive />
          <div>
            <h2 id="review-queue-heading">Claim 审核队列</h2>
            <p>审核公开措辞，不验证成交真实性</p>
          </div>
        </div>
        {snapshot.reviewQueue.map((item) => (
          <Card key={`${item.candidateId}:${item.revisionId}`} className="seat-kol-review">
            <CardContent>
              <div className="flex items-center justify-between gap-3">
                <Badge variant="outline">{item.reviewStatus}</Badge>
                <span>{(item.confidenceBps / 100).toFixed(0)}% 置信</span>
              </div>
              <p>{item.statement}</p>
              <small>
                {item.instrumentId} · {shanghaiTime(item.availableTime)}
              </small>
            </CardContent>
          </Card>
        ))}
      </section>
    </div>
  );
}

function StateCard({ title, detail }: { title: string; detail: string }) {
  return (
    <Card className="seat-kol-state">
      <CardContent>
        <UsersRound />
        <h2>{title}</h2>
        <p>{detail}</p>
      </CardContent>
    </Card>
  );
}

export function SeatKolWorkbenchPage() {
  const [filters, setFilters] = useState<SeatKolWorkbenchFilters>({
    entityType: "ALL",
    reviewStatus: "ALL",
    query: "",
  });
  const [asOfInput, setAsOfInput] = useState(() => new Date().toISOString().slice(0, 16));
  const asOfDate = new Date(asOfInput);
  const asOf = Number.isNaN(asOfDate.getTime()) ? new Date().toISOString() : asOfDate.toISOString();
  const result = useSeatKolWorkbench(filters, asOf);
  const snapshot = result.data?.[0];

  return (
    <div className="seat-kol-shell">
      <header className="seat-kol-hero">
        <div>
          <span className="seat-kol-kicker">
            <Fingerprint />
            PHASE 4 · PUBLIC INTELLIGENCE
          </span>
          <h2>席位 × KOL 情报台</h2>
          <p>把公开席位事实与 KOL 公开表述放在同一条可审计时间线上，不把相关性包装成成交事实。</p>
        </div>
        <div className="seat-kol-hero-meta">
          <span>
            <Clock3 />
            回放 {asOfInput.replace("T", " ")}
          </span>
          <span>
            <Database />
            {snapshot?.sourceVersion ?? "等待数据源"}
          </span>
          {snapshot?.mode === "LOCAL_PREVIEW" && <Badge variant="outline">本地脱敏预览</Badge>}
        </div>
      </header>

      <Card className="seat-kol-filter-card">
        <CardContent>
          <div className="seat-kol-filter-grid">
            <div>
              <Label htmlFor="seat-kol-query">搜索档案、证券或表述</Label>
              <div className="seat-kol-search">
                <Search />
                <Input
                  id="seat-kol-query"
                  value={filters.query}
                  onChange={(event) =>
                    setFilters((current) => ({ ...current, query: event.target.value }))
                  }
                  placeholder="600519.SH / 席位 / KOL"
                />
              </div>
            </div>
            <div>
              <Label htmlFor="seat-kol-entity">实体类型</Label>
              <select
                id="seat-kol-entity"
                value={filters.entityType}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    entityType: event.target.value as SeatKolWorkbenchFilters["entityType"],
                  }))
                }
              >
                <option value="ALL">全部</option>
                <option value="SEAT">席位</option>
                <option value="KOL">KOL</option>
              </select>
            </div>
            <div>
              <Label htmlFor="seat-kol-review">审核状态</Label>
              <select
                id="seat-kol-review"
                value={filters.reviewStatus}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    reviewStatus: event.target.value as SeatKolWorkbenchFilters["reviewStatus"],
                  }))
                }
              >
                <option value="ALL">全部</option>
                <option value="UNREVIEWED">未审核</option>
                <option value="IN_REVIEW">审核中</option>
                <option value="APPROVED">已批准</option>
                <option value="REJECTED">已拒绝</option>
              </select>
            </div>
            <div>
              <Label htmlFor="seat-kol-as-of">历史回放时点</Label>
              <Input
                id="seat-kol-as-of"
                type="datetime-local"
                value={asOfInput}
                onChange={(event) => setAsOfInput(event.target.value)}
              />
            </div>
            <Button
              variant="outline"
              onClick={() => setFilters({ entityType: "ALL", reviewStatus: "ALL", query: "" })}
            >
              重置筛选
            </Button>
          </div>
        </CardContent>
      </Card>

      {result.status === "loading" && (
        <StateCard title="正在装载审计链" detail="同步档案、证据、统计与审核队列。" />
      )}
      {result.status === "empty" && (
        <StateCard title="暂无符合条件的数据" detail="调整回放时点或筛选条件后重试。" />
      )}
      {result.status === "error" && (
        <StateCard title="工作台数据加载失败" detail="保留当前筛选条件并检查 server 状态。" />
      )}
      {result.status === "forbidden" && (
        <StateCard title="无权访问席位与 KOL 工作台" detail="请申请公开情报读取权限。" />
      )}
      {result.status === "success" && snapshot && (
        <section className="space-y-8" aria-label="席位与 KOL 审计结果">
          <div className="seat-kol-audit-strip">
            <span>决策时点 {shanghaiTime(snapshot.decisionTime)}</span>
            <span>数据截止 {shanghaiTime(snapshot.dataCutoffTime)}</span>
            <span>{snapshot.dataMeaning}</span>
          </div>
          <div className="grid gap-8 2xl:grid-cols-2">
            <SeatProfiles snapshot={snapshot} />
            <KolProfiles snapshot={snapshot} />
          </div>
          <RelationsAndReview snapshot={snapshot} />
        </section>
      )}
    </div>
  );
}
