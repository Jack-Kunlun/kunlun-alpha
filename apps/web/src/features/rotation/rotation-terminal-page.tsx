import type { HotTopicSnapshot } from "@kunlun/shared-types";
import {
  Activity,
  ArrowRight,
  Clock3,
  Flame,
  GitCompareArrows,
  History,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import {
  buildRotationTimeline,
  buildTopicComparison,
  formatShanghaiTime,
  HOT_TOPIC_LIFECYCLE,
  HOT_TOPIC_LIFECYCLE_LABELS,
  type RotationTimelineItem,
} from "./rotation-terminal-model";
import type { RotationTerminalData, RotationTerminalResult } from "./types";
import { useRotationTerminal, type RotationTerminalFilters } from "./use-rotation-terminal";

function shanghaiLocalInput(now = new Date()): string {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(now)
      .map((part) => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

export function shanghaiLocalToIso(value: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}:00+08:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

function ContinuityNotice({ messages }: { messages: readonly string[] }) {
  if (messages.length === 0) return null;
  return (
    <div role="status" className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4">
      <div className="flex items-center gap-2 font-medium">
        <TriangleAlert className="size-4" aria-hidden="true" />
        数据断点已显式保留
      </div>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
        {messages.map((message) => (
          <li key={message}>{message}</li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted-foreground">界面不插值、不补线，也不以动画掩盖缺口。</p>
    </div>
  );
}

function LifecycleRail({ topics }: { topics: readonly HotTopicSnapshot[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Flame className="size-5 text-amber-500" aria-hidden="true" /> 热点生命周期
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          生命周期来自 `hot-score-v1` 快照，不推导或冒充未暴露的板块生命周期状态。
        </p>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {HOT_TOPIC_LIFECYCLE.map((lifecycle) => {
          const matching = topics
            .filter((topic) => topic.lifecycle === lifecycle)
            .sort((left, right) => right.scoreBps - left.scoreBps);
          return (
            <section key={lifecycle} className="rounded-xl border bg-muted/20 p-4">
              <div className="flex items-center justify-between gap-2">
                <strong>{HOT_TOPIC_LIFECYCLE_LABELS[lifecycle]}</strong>
                <Badge variant="outline">查询内 {matching.length}</Badge>
              </div>
              <p className="mt-3 min-h-10 text-sm text-muted-foreground">
                {matching
                  .slice(0, 2)
                  .map((topic) => topic.topicName)
                  .join("、") || "当前无热点"}
              </p>
            </section>
          );
        })}
      </CardContent>
    </Card>
  );
}

function ComparisonPanel({ topics }: { topics: readonly HotTopicSnapshot[] }) {
  const rows = buildTopicComparison(topics);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <GitCompareArrows className="size-5 text-cyan-600" aria-hidden="true" />
          热点强度对比
        </CardTitle>
        <p className="text-sm text-muted-foreground">图形与同源明细共同使用排序后的快照行。</p>
      </CardHeader>
      <CardContent className="grid gap-6 xl:grid-cols-[1.1fr_1fr]">
        <div role="img" aria-label="热点得分与置信度对比图" className="space-y-4">
          {rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无热点可比较</p>
          ) : (
            rows.map((row) => (
              <div key={row.topicId} className="space-y-1.5">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="truncate font-medium">{row.topicName}</span>
                  <span className="font-mono">{(row.scoreBps / 100).toFixed(1)}</span>
                </div>
                <div className="grid gap-1" aria-hidden="true">
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-amber-500"
                      style={{ width: `${row.scoreBps / 100}%` }}
                    />
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-cyan-600"
                      style={{ width: `${row.confidenceBps / 100}%` }}
                    />
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
        <Table aria-label="热点强度同源明细">
          <TableHeader>
            <TableRow>
              <TableHead>热点</TableHead>
              <TableHead>阶段</TableHead>
              <TableHead>得分</TableHead>
              <TableHead>置信</TableHead>
              <TableHead>事件</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.topicId}>
                <TableCell>{row.topicName}</TableCell>
                <TableCell>{HOT_TOPIC_LIFECYCLE_LABELS[row.lifecycle]}</TableCell>
                <TableCell className="font-mono">{(row.scoreBps / 100).toFixed(1)}</TableCell>
                <TableCell className="font-mono">{(row.confidenceBps / 100).toFixed(1)}%</TableCell>
                <TableCell>{row.eventCount}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function TimelineDetail({
  item,
  data,
}: {
  item: RotationTimelineItem;
  data: RotationTerminalData;
}) {
  const relatedEvents = data.marketEvents.filter((event) =>
    item.relatedEventIds.includes(event.eventId),
  );
  const unresolvedCount = item.relatedEventIds.length - relatedEvents.length;
  return (
    <div className="space-y-5 text-sm">
      <dl className="grid gap-3 sm:grid-cols-2">
        <div>
          <dt className="text-muted-foreground">上海时间</dt>
          <dd className="font-mono">{formatShanghaiTime(item.timestamp)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">算法 / 模型版本</dt>
          <dd className="break-all">{item.algorithmVersion}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">证据窗口</dt>
          <dd>
            {item.windowStart === null ? "-" : formatShanghaiTime(item.windowStart)} 至{" "}
            {item.windowEnd === null ? "-" : formatShanghaiTime(item.windowEnd)}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">来源版本</dt>
          <dd className="break-all">{item.sourceVersions.join("、") || "未提供"}</dd>
        </div>
      </dl>
      <div>
        <h3 className="font-medium">证据标识</h3>
        <p className="mt-1 break-all text-muted-foreground">
          {item.evidenceIds.join("、") || item.relatedEventIds.join("、") || "未提供"}
        </p>
      </div>
      {relatedEvents.length > 0 && (
        <div className="space-y-3">
          <h3 className="font-medium">关联结构化事件</h3>
          {relatedEvents.map((event) => (
            <article key={event.eventId} className="rounded-lg border p-3">
              <strong>{event.headline}</strong>
              <p className="mt-1 text-muted-foreground">{event.summary}</p>
              {event.evidence.map((evidence) => (
                <blockquote key={evidence.evidenceId} className="mt-2 border-l-2 pl-3 text-xs">
                  {evidence.excerpt} · {evidence.sourceId}/{evidence.sourceVersion}
                </blockquote>
              ))}
            </article>
          ))}
        </div>
      )}
      {unresolvedCount > 0 && (
        <p role="status" className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3">
          {unresolvedCount} 条关联事件尚不可得或记录缺失，未使用替代证据补齐。
        </p>
      )}
    </div>
  );
}

function RotationTimeline({ data }: { data: RotationTerminalData }) {
  const items = buildRotationTimeline(data);
  const [selected, setSelected] = useState<RotationTimelineItem | null>(null);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <History className="size-5" aria-hidden="true" /> 轮动与事件时间轴
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          全部时间统一显示为 Asia/Shanghai；轮动按 timestamp 与 evidenceEnd 截断。
        </p>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">当前回放点没有时间轴事件</p>
        ) : (
          <ol className="relative space-y-3 border-l pl-6">
            {items.map((item) => (
              <li key={`${item.kind}:${item.id}`} className="relative rounded-xl border p-4">
                <span className="absolute top-5 -left-[1.82rem] size-3 rounded-full border-2 border-background bg-foreground" />
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline">{item.marker}</Badge>
                      <strong>{item.title}</strong>
                    </div>
                    <p className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
                      <Clock3 className="size-3" aria-hidden="true" />
                      {formatShanghaiTime(item.timestamp)}
                    </p>
                  </div>
                  <Button type="button" variant="outline" onClick={() => setSelected(item)}>
                    查看证据 <ArrowRight aria-hidden="true" />
                  </Button>
                </div>
                <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted-foreground">
                  <span>置信 {(item.confidenceBps / 100).toFixed(1)}%</span>
                  {item.scoreBps !== null && <span>得分 {(item.scoreBps / 100).toFixed(1)}</span>}
                  <span>版本 {item.algorithmVersion}</span>
                </div>
              </li>
            ))}
          </ol>
        )}
        <Dialog open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
          <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>{selected?.title ?? "证据详情"}</DialogTitle>
              <DialogDescription>原始标识、窗口和版本信息，不推断真实交易行为。</DialogDescription>
            </DialogHeader>
            {selected && <TimelineDetail item={selected} data={data} />}
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}

export function RotationTerminalView({ result }: { result: RotationTerminalResult }) {
  if (result.status === "loading") {
    return (
      <div role="status" className="rounded-xl border p-8">
        正在加载轮动与热点回放…
      </div>
    );
  }
  if (result.status === "forbidden") {
    return (
      <div role="alert" className="rounded-xl border border-destructive/40 p-8">
        无权访问轮动与热点终端
      </div>
    );
  }
  if (result.status === "error" || result.data === null) {
    return (
      <div className="space-y-4">
        <ContinuityNotice messages={result.continuity} />
        <div role="alert" className="rounded-xl border border-destructive/40 p-8">
          轮动与热点数据加载失败，请检查数据源后重试
        </div>
      </div>
    );
  }
  if (result.status === "empty") {
    return (
      <div className="space-y-4">
        <ContinuityNotice messages={result.continuity} />
        <div className="rounded-xl border p-8 text-muted-foreground">当前回放点暂无数据</div>
      </div>
    );
  }
  const data = result.data;
  const latestEmotion = [...data.snapshots].sort(
    (left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp),
  )[0];
  return (
    <div className="space-y-6">
      <ContinuityNotice messages={result.continuity} />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardContent className="p-5">
            <p className="text-xs text-muted-foreground">热点快照</p>
            <strong className="mt-2 block font-mono text-3xl">{data.hotTopics.length}</strong>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-xs text-muted-foreground">轮动事件</p>
            <strong className="mt-2 block font-mono text-3xl">{data.rotationEvents.length}</strong>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-xs text-muted-foreground">可见事件证据</p>
            <strong className="mt-2 block font-mono text-3xl">{data.marketEvents.length}</strong>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-xs text-muted-foreground">最近情绪 / 置信</p>
            <strong className="mt-2 block font-mono text-xl">
              {latestEmotion
                ? `${latestEmotion.score.toFixed(3)} / ${(latestEmotion.confidence * 100).toFixed(0)}%`
                : "无快照"}
            </strong>
          </CardContent>
        </Card>
      </div>
      <LifecycleRail topics={data.hotTopics} />
      <ComparisonPanel topics={data.hotTopics} />
      <RotationTimeline data={data} />
    </div>
  );
}

interface DraftFilters {
  date: string;
  asOfLocal: string;
  algorithmVersion: string;
  sectorId: string;
  lifecycle: "ALL" | HotTopicSnapshot["lifecycle"];
}

export function RotationTerminalPage() {
  const initialLocal = shanghaiLocalInput();
  const initial: DraftFilters = {
    date: initialLocal.slice(0, 10),
    asOfLocal: initialLocal,
    algorithmVersion: "",
    sectorId: "",
    lifecycle: "ALL",
  };
  const initialAsOf = shanghaiLocalToIso(initialLocal) ?? new Date().toISOString();
  const [draft, setDraft] = useState(initial);
  const [validation, setValidation] = useState<string | null>(null);
  const [applied, setApplied] = useState<RotationTerminalFilters>({
    date: initial.date,
    asOf: initialAsOf,
  });
  const result = useRotationTerminal(applied);
  const replayLabel = useMemo(() => formatShanghaiTime(applied.asOf), [applied.asOf]);

  return (
    <section className="space-y-6" aria-labelledby="rotation-terminal-title">
      <header className="overflow-hidden rounded-2xl border bg-gradient-to-br from-amber-500/10 via-background to-cyan-500/10 p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.22em] text-muted-foreground">
              观势 · 知势 · 策势
            </p>
            <h2 id="rotation-terminal-title" className="mt-2 text-3xl font-semibold tracking-tight">
              轮动与热点终端
            </h2>
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
              以同一回放点连接热点生命周期、板块交叉事件和结构化事件证据。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">
              <History aria-hidden="true" /> {replayLabel}
            </Badge>
            <Badge variant="secondary">
              <ShieldCheck aria-hidden="true" /> 仅供研究，不产生真实订单
            </Badge>
          </div>
        </div>
      </header>

      <form
        className="grid gap-4 rounded-2xl border bg-card p-5 md:grid-cols-2 xl:grid-cols-6"
        onSubmit={(event) => {
          event.preventDefault();
          const asOf = shanghaiLocalToIso(draft.asOfLocal);
          if (asOf === null || !draft.asOfLocal.startsWith(`${draft.date}T`)) {
            setValidation("回放点必须是所选交易日内的有效上海时间");
            return;
          }
          setValidation(null);
          setApplied({
            date: draft.date,
            asOf,
            ...(draft.algorithmVersion.trim()
              ? { algorithmVersion: draft.algorithmVersion.trim() }
              : {}),
            ...(draft.sectorId.trim() ? { sectorId: draft.sectorId.trim() } : {}),
            ...(draft.lifecycle === "ALL" ? {} : { lifecycle: draft.lifecycle }),
          });
        }}
      >
        <div className="grid gap-2">
          <Label htmlFor="rotation-date">交易日</Label>
          <Input
            id="rotation-date"
            type="date"
            value={draft.date}
            onChange={(event) => {
              const date = event.target.value;
              setDraft((current) => ({ ...current, date, asOfLocal: `${date}T15:00` }));
            }}
          />
        </div>
        <div className="grid gap-2 xl:col-span-2">
          <Label htmlFor="rotation-as-of">回放点（上海时间）</Label>
          <Input
            id="rotation-as-of"
            type="datetime-local"
            value={draft.asOfLocal}
            onChange={(event) =>
              setDraft((current) => ({ ...current, asOfLocal: event.target.value }))
            }
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="rotation-version">轮动算法版本</Label>
          <Input
            id="rotation-version"
            value={draft.algorithmVersion}
            placeholder="rotation_event_v2"
            onChange={(event) =>
              setDraft((current) => ({ ...current, algorithmVersion: event.target.value }))
            }
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="rotation-sector">板块 ID</Label>
          <Input
            id="rotation-sector"
            value={draft.sectorId}
            placeholder="sector-gold"
            onChange={(event) =>
              setDraft((current) => ({ ...current, sectorId: event.target.value }))
            }
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="rotation-lifecycle">热点阶段</Label>
          <select
            id="rotation-lifecycle"
            className="h-9 rounded-md border bg-background px-3 text-sm"
            value={draft.lifecycle}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                lifecycle: event.target.value as DraftFilters["lifecycle"],
              }))
            }
          >
            <option value="ALL">全部阶段</option>
            {HOT_TOPIC_LIFECYCLE.map((lifecycle) => (
              <option key={lifecycle} value={lifecycle}>
                {HOT_TOPIC_LIFECYCLE_LABELS[lifecycle]}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-end md:col-span-2 xl:col-span-6">
          <Button type="submit">
            <Activity aria-hidden="true" /> 应用历史回放
          </Button>
        </div>
        {validation && (
          <p role="alert" className="text-sm text-destructive md:col-span-2 xl:col-span-6">
            {validation}
          </p>
        )}
      </form>

      <RotationTerminalView result={result} />
    </section>
  );
}
