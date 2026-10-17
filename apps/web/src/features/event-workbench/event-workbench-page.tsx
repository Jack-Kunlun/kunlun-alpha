import { useMemo, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  Clock3,
  DatabaseZap,
  Radar,
  ScanSearch,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { ApiError } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { buildFeedbackSubmission, submitEventFeedback, type FeedbackDraft } from "./event-feedback";
import type { HotTopicSnapshot, MarketEvent } from "./types";
import { useEventWorkbench, type EventWorkbenchFilters } from "./use-event-workbench";
import "./event-workbench.css";

const EVENT_LABELS: Record<MarketEvent["eventType"], string> = {
  CORPORATE: "公司事项",
  EARNINGS: "业绩",
  FINANCING: "融资",
  REGULATORY: "监管",
  POLICY: "政策",
  MACRO: "宏观",
  INDUSTRY: "行业",
  MARKET: "市场",
  RISK: "风险",
  OTHER: "其他",
};

const LIFECYCLE_LABELS: Record<HotTopicSnapshot["lifecycle"], string> = {
  EMERGING: "萌芽",
  RISING: "升温",
  HOT: "炽热",
  COOLING: "降温",
  DORMANT: "沉寂",
};

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

function confidenceLabel(value: number): string {
  if (value >= 8000) return "高置信";
  if (value >= 6000) return "中置信";
  return "低置信推断";
}

function TopicCard({ topic }: { topic: HotTopicSnapshot }) {
  return (
    <Card className="event-topic-card min-w-[16rem] gap-4 py-5">
      <CardHeader className="gap-3 px-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="event-topic-title">{topic.topicName}</CardTitle>
            <CardDescription>
              {topic.eventCount} 条事件 · {topic.sourceCount} 个来源
            </CardDescription>
          </div>
          <Badge variant={topic.lifecycle === "HOT" ? "destructive" : "secondary"}>
            {LIFECYCLE_LABELS[topic.lifecycle]}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="px-5">
        <div className="flex items-end justify-between">
          <span className="event-score">{(topic.scoreBps / 100).toFixed(1)}</span>
          <span className="text-xs text-muted-foreground">HotScore / 100</span>
        </div>
        <div className="event-score-track" aria-label={`热点强度 ${topic.scoreBps / 100}`}>
          <span style={{ width: `${topic.scoreBps / 100}%` }} />
        </div>
        <div className="mt-3 flex justify-between text-xs text-muted-foreground">
          <span>置信 {(topic.confidenceBps / 100).toFixed(0)}%</span>
          <span>{topic.algorithmVersion}</span>
        </div>
      </CardContent>
    </Card>
  );
}

function FeedbackPanel({ event }: { event: MarketEvent }) {
  const [draft, setDraft] = useState<FeedbackDraft>({
    action: "CONFIRM",
    reasonCode: "ACCURATE",
    comment: "",
    correctedInstrumentId: "",
  });
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "forbidden" | "error">("idle");

  const submit = async (formEvent: React.FormEvent) => {
    formEvent.preventDefault();
    setStatus("sending");
    try {
      const requestId =
        globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${event.eventId.slice(0, 12)}`;
      await submitEventFeedback(buildFeedbackSubmission(event, draft, requestId));
      setStatus("sent");
    } catch (error) {
      setStatus(error instanceof ApiError && error.status === 403 ? "forbidden" : "error");
    }
  };

  return (
    <form onSubmit={submit} className="event-feedback-panel space-y-3">
      <div className="flex items-center gap-2">
        <ShieldCheck className="size-4" />
        <h3 className="font-medium">人工校正</h3>
        <Badge variant="outline">追加式审计</Badge>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor="event-feedback-action">判断</Label>
          <select
            id="event-feedback-action"
            className="event-native-control"
            value={draft.action}
            onChange={(event) => {
              const action = event.target.value as FeedbackDraft["action"];
              setDraft((current) => ({
                ...current,
                action,
                reasonCode: action === "CONFIRM" ? "ACCURATE" : "OTHER",
              }));
            }}
          >
            <option value="CONFIRM">确认准确</option>
            <option value="REJECT">拒绝事件</option>
            <option value="CORRECT">提交更正</option>
          </select>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="event-feedback-reason">原因</Label>
          <select
            id="event-feedback-reason"
            className="event-native-control"
            value={draft.reasonCode}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                reasonCode: event.target.value as FeedbackDraft["reasonCode"],
              }))
            }
          >
            <option value="ACCURATE">准确</option>
            <option value="WRONG_TYPE">类型错误</option>
            <option value="WRONG_ENTITY">标的错误</option>
            <option value="WRONG_EVIDENCE">证据错误</option>
            <option value="DUPLICATE">重复事件</option>
            <option value="NOT_MARKET_EVENT">非市场事件</option>
            <option value="OTHER">其他</option>
          </select>
        </div>
      </div>
      {draft.action === "CORRECT" && (
        <div className="grid gap-2">
          <Label htmlFor="event-feedback-instrument">更正证券</Label>
          <Input
            id="event-feedback-instrument"
            placeholder="600519.SH"
            value={draft.correctedInstrumentId}
            onChange={(event) =>
              setDraft((current) => ({ ...current, correctedInstrumentId: event.target.value }))
            }
          />
        </div>
      )}
      <div className="grid gap-2">
        <Label htmlFor="event-feedback-comment">备注（可选，不进入日志）</Label>
        <Input
          id="event-feedback-comment"
          maxLength={1000}
          value={draft.comment}
          onChange={(event) => setDraft((current) => ({ ...current, comment: event.target.value }))}
        />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" size="sm" disabled={status === "sending"}>
          {status === "sending" ? "提交中…" : "记录反馈"}
        </Button>
        <span aria-live="polite" className="text-xs text-muted-foreground">
          {status === "sent" && "反馈已追加，需复核后才能进入新评测集"}
          {status === "forbidden" && "当前身份无反馈权限"}
          {status === "error" && "反馈提交失败，请保留当前事件 ID"}
        </span>
      </div>
    </form>
  );
}

function EventDetail({ event }: { event: MarketEvent }) {
  return (
    <Card className="event-detail-card sticky top-6 gap-5 py-5">
      <CardHeader className="px-5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge>{EVENT_LABELS[event.eventType]}</Badge>
          <Badge variant={event.confidenceBps < 6000 ? "destructive" : "outline"}>
            {confidenceLabel(event.confidenceBps)} {(event.confidenceBps / 100).toFixed(0)}%
          </Badge>
        </div>
        <CardTitle className="event-detail-title mt-2">{event.headline}</CardTitle>
        <CardDescription>{event.summary}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5 px-5">
        <div className="event-fact-grid">
          <div>
            <span>可用时间</span>
            <strong>{shanghaiTime(event.availableTime)}</strong>
          </div>
          <div>
            <span>样本证据</span>
            <strong>{event.evidence.length} 条</strong>
          </div>
          <div>
            <span>模型版本</span>
            <strong>{event.modelProvenance.modelVersion}</strong>
          </div>
          <div>
            <span>Prompt</span>
            <strong>{event.modelProvenance.promptVersion}</strong>
          </div>
        </div>
        <section className="space-y-2" aria-label="证据原文">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ScanSearch className="size-4" /> 原文证据
          </div>
          {event.evidence.map((evidence) => (
            <blockquote key={evidence.evidenceId} className="event-evidence">
              <p>{evidence.excerpt}</p>
              <footer>
                {evidence.sourceId} · [{evidence.startOffset}, {evidence.endOffset}) ·{" "}
                {shanghaiTime(evidence.availableTime)}
              </footer>
            </blockquote>
          ))}
        </section>
        <div className="event-provenance">
          <DatabaseZap className="size-4" />
          <span title={event.modelProvenance.configurationFingerprint}>
            配置 {event.modelProvenance.configurationFingerprint.slice(0, 12)}…
          </span>
          <span>Schema {event.modelProvenance.outputSchemaVersion}</span>
        </div>
        <FeedbackPanel event={event} />
      </CardContent>
    </Card>
  );
}

function Workbench({ events, topics }: { events: MarketEvent[]; topics: HotTopicSnapshot[] }) {
  const [selectedId, setSelectedId] = useState(events[0]?.eventId ?? "");
  const selected = events.find((event) => event.eventId === selectedId) ?? events[0] ?? null;
  return (
    <div className="space-y-7">
      {topics.length > 0 && (
        <section aria-labelledby="hot-topics-heading">
          <div className="mb-3 flex items-center justify-between">
            <h2 id="hot-topics-heading" className="event-section-title">
              <Radar /> 热点雷达
            </h2>
            <span className="text-xs text-muted-foreground">point-in-time snapshots</span>
          </div>
          <div className="event-topic-rail">
            {topics.map((topic) => (
              <TopicCard key={topic.snapshotId} topic={topic} />
            ))}
          </div>
        </section>
      )}
      <section className="event-workbench-grid" aria-labelledby="event-stream-heading">
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 id="event-stream-heading" className="event-section-title">
              <Activity /> 事件脉冲
            </h2>
            <span className="text-xs text-muted-foreground">{events.length} 条已验证事件</span>
          </div>
          <div className="space-y-2">
            {events.map((event) => (
              <button
                type="button"
                key={event.eventId}
                onClick={() => setSelectedId(event.eventId)}
                aria-pressed={selected?.eventId === event.eventId}
                className="event-stream-item"
              >
                <span className="event-stream-time">{shanghaiTime(event.availableTime)}</span>
                <span className="min-w-0 flex-1">
                  <strong>{event.headline}</strong>
                  <small>{event.instrumentIds.join(" · ") || "宏观/行业事件"}</small>
                </span>
                <span className="event-stream-confidence">
                  {(event.confidenceBps / 100).toFixed(0)}%
                </span>
                <ArrowUpRight className="size-4" />
              </button>
            ))}
          </div>
        </div>
        <div>
          {selected ? (
            <EventDetail event={selected} />
          ) : (
            <p className="text-muted-foreground">暂无事件详情</p>
          )}
        </div>
      </section>
    </div>
  );
}

export function EventWorkbenchPage() {
  const [draft, setDraft] = useState<EventWorkbenchFilters>({ minimumConfidenceBps: "6000" });
  const [filters, setFilters] = useState<EventWorkbenchFilters>({ minimumConfidenceBps: "6000" });
  const asOf = useMemo(() => new Date().toISOString(), []);
  const result = useEventWorkbench(filters, asOf);
  const loading = result.events.status === "loading" || result.topics.status === "loading";
  const forbidden = result.events.status === "forbidden" || result.topics.status === "forbidden";
  const error = result.events.status === "error" ? result.events.error : result.topics.error;
  const events = result.events.data ?? [];
  const topics = result.topics.data ?? [];

  return (
    <div className="event-workbench-shell">
      <header className="event-hero">
        <div className="event-hero-kicker">
          <Sparkles /> EVENT INTELLIGENCE · PHASE 3
        </div>
        <div className="event-hero-copy">
          <div>
            <h2>事件观势台</h2>
            <p>从原文证据到热点生命周期，每一条判断都带着时间、版本与置信度。</p>
          </div>
          <div className="event-asof">
            <Clock3 />
            <span>决策截面</span>
            <strong>{shanghaiTime(asOf)}</strong>
          </div>
        </div>
      </header>

      <form
        className="event-filter-bar"
        onSubmit={(event) => {
          event.preventDefault();
          setFilters({ ...draft });
        }}
      >
        <div>
          <Label htmlFor="event-date-from">起始日</Label>
          <Input
            id="event-date-from"
            type="date"
            value={draft.dateFrom ?? ""}
            onChange={(event) =>
              setDraft((current) => ({ ...current, dateFrom: event.target.value }))
            }
          />
        </div>
        <div>
          <Label htmlFor="event-date-to">结束日</Label>
          <Input
            id="event-date-to"
            type="date"
            value={draft.dateTo ?? ""}
            onChange={(event) =>
              setDraft((current) => ({ ...current, dateTo: event.target.value }))
            }
          />
        </div>
        <div>
          <Label htmlFor="event-instrument">证券</Label>
          <Input
            id="event-instrument"
            placeholder="600519.SH"
            value={draft.instrumentId ?? ""}
            onChange={(event) =>
              setDraft((current) => ({ ...current, instrumentId: event.target.value }))
            }
          />
        </div>
        <div>
          <Label htmlFor="event-confidence">最低置信 BPS</Label>
          <Input
            id="event-confidence"
            inputMode="numeric"
            value={draft.minimumConfidenceBps ?? ""}
            onChange={(event) =>
              setDraft((current) => ({ ...current, minimumConfidenceBps: event.target.value }))
            }
          />
        </div>
        <Button type="submit">
          <ScanSearch />
          筛选
        </Button>
      </form>

      {loading && (
        <div role="status" className="event-state">
          <Radar className="event-radar-spin" />
          正在扫描事件与热点…
        </div>
      )}
      {!loading && forbidden && (
        <div role="alert" className="event-state event-state-error">
          <ShieldCheck />
          当前身份无权访问事件情报
        </div>
      )}
      {!loading && !forbidden && error && (
        <div role="alert" className="event-state event-state-error">
          <DatabaseZap />
          数据加载失败：{error.message}
        </div>
      )}
      {!loading && !forbidden && !error && events.length === 0 && topics.length === 0 && (
        <div className="event-state">
          <Radar />
          当前截面暂无可用事件或热点
        </div>
      )}
      {!loading && !forbidden && !error && (events.length > 0 || topics.length > 0) && (
        <Workbench events={events} topics={topics} />
      )}
    </div>
  );
}
