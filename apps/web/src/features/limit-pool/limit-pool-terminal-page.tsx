import type {
  LimitPoolSide,
  LimitPoolState,
  LimitPoolTerminalEntry,
  LimitPoolTerminalSnapshot,
} from "@kunlun/shared-types";
import { Download, History, Radio, Search, ShieldCheck } from "lucide-react";
import { useState } from "react";
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
import { downloadLimitPoolCsv } from "./limit-pool-export";
import {
  VirtualizedLimitPoolTable,
  type LimitPoolSort,
  type LimitPoolSortKey,
} from "./virtualized-limit-pool-table";
import {
  useLimitPoolTerminal,
  type LimitPoolTerminalQuery,
  type LimitPoolTerminalResult,
} from "./use-limit-pool-terminal";

interface Filters {
  search: string;
  side: LimitPoolSide | "ALL";
  state: LimitPoolState | "ALL";
  minimumStreak: number;
}

function compare(
  left: LimitPoolTerminalEntry,
  right: LimitPoolTerminalEntry,
  key: LimitPoolSortKey,
): number {
  if (key === "streakDays" || key === "openCount") return left[key] - right[key];
  return String(left[key] ?? "").localeCompare(String(right[key] ?? ""), "zh-CN");
}

export function filterAndSortLimitPool(
  entries: readonly LimitPoolTerminalEntry[],
  filters: Filters,
  sort: LimitPoolSort,
): LimitPoolTerminalEntry[] {
  const keyword = filters.search.trim().toLocaleLowerCase("zh-CN");
  return entries
    .filter((entry) => filters.side === "ALL" || entry.side === filters.side)
    .filter((entry) => filters.state === "ALL" || entry.state === filters.state)
    .filter((entry) => entry.streakDays >= filters.minimumStreak)
    .filter(
      (entry) =>
        keyword === "" ||
        entry.instrumentId.toLocaleLowerCase().includes(keyword) ||
        entry.name.toLocaleLowerCase("zh-CN").includes(keyword),
    )
    .sort((left, right) => {
      const result = compare(left, right, sort.key);
      return (
        (sort.direction === "asc" ? result : -result) ||
        left.instrumentId.localeCompare(right.instrumentId)
      );
    });
}

function freshnessLabel(snapshot: LimitPoolTerminalSnapshot): string {
  if (snapshot.freshness.status === "HISTORICAL") return "历史点时";
  if (snapshot.freshness.status === "NO_DATA") return "无数据";
  if (snapshot.freshness.status === "FRESH")
    return `实时 · ${snapshot.freshness.ageSeconds ?? 0} 秒`;
  if (snapshot.freshness.status === "DELAYED")
    return `延迟 ${snapshot.freshness.ageSeconds ?? 0} 秒`;
  return `陈旧 ${snapshot.freshness.ageSeconds ?? 0} 秒 · 非实时`;
}

export function shanghaiLocalToIso(value: string): string | undefined {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return undefined;
  const parsed = new Date(`${value}:00+08:00`);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString();
}

export function formatShanghaiTime(value: string | null): string {
  if (value === null) return "-";
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

function StateMessage({
  result,
}: {
  result: Exclude<LimitPoolTerminalResult, { status: "success" }>;
}) {
  if (result.status === "loading")
    return (
      <div role="status" className="rounded-xl border p-8">
        正在加载涨跌停快照…
      </div>
    );
  if (result.status === "forbidden")
    return (
      <div role="alert" className="rounded-xl border border-destructive/40 p-8">
        无权查看涨跌停终端
      </div>
    );
  return (
    <div role="alert" className="rounded-xl border border-destructive/40 p-8">
      涨跌停数据流中断，请稍后重试
    </div>
  );
}

export function LimitPoolEvidenceDetails({ entry }: { entry: LimitPoolTerminalEntry }) {
  const rows = [
    ["证券", `${entry.name} · ${entry.instrumentId}`],
    ["状态", `${entry.side} / ${entry.state} / ${entry.streakDays} 连板`],
    ["事件时间（上海）", formatShanghaiTime(entry.eventTime)],
    ["可得时间（上海）", formatShanghaiTime(entry.availableTime)],
    [
      "首次 / 最近封板（上海）",
      `${formatShanghaiTime(entry.firstSealTime)} / ${formatShanghaiTime(entry.lastSealTime)}`,
    ],
    ["修订", String(entry.revision)],
    ["来源版本", entry.sourceVersion],
    ["证据 ID", entry.evidenceId],
    ["算法版本", entry.algorithmVersion],
    ["梯队版本", entry.ladderAlgorithmVersion],
    ["规则版本", entry.limitRuleVersion],
    ["物化器版本", entry.materializerVersion],
  ];
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
        算法输出，不代表可成交价格；当前系统不存在真实下单路径。
      </div>
      <dl className="grid gap-3 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="grid gap-1 border-b pb-3">
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">{label}</dt>
            <dd className="break-all font-mono">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function EvidenceDrawer({
  entry,
  onClose,
}: {
  entry: LimitPoolTerminalEntry | null;
  onClose(): void;
}) {
  return (
    <Dialog
      open={entry !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="top-0 right-0 left-auto h-dvh max-h-dvh w-full max-w-xl translate-x-0 translate-y-0 overflow-y-auto rounded-none sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>个股证据链</DialogTitle>
          <DialogDescription>展示该行实际使用的时点、修订、来源与算法语义。</DialogDescription>
        </DialogHeader>
        {entry && <LimitPoolEvidenceDetails entry={entry} />}
      </DialogContent>
    </Dialog>
  );
}

export function LimitPoolTerminalView({
  result,
  filters,
  sort,
  selected,
  onFilters,
  onSort,
  onSelect,
}: {
  result: LimitPoolTerminalResult;
  filters: Filters;
  sort: LimitPoolSort;
  selected: LimitPoolTerminalEntry | null;
  onFilters(filters: Filters): void;
  onSort(key: LimitPoolSortKey): void;
  onSelect(entry: LimitPoolTerminalEntry | null): void;
}) {
  if (result.status !== "success") return <StateMessage result={result} />;
  const snapshot = result.data;
  const visible = filterAndSortLimitPool(snapshot.entries, filters, sort);
  if (snapshot.completeness === "EMPTY") {
    return (
      <div role="status" className="rounded-xl border border-dashed p-12 text-center">
        该时点没有限涨跌停快照
      </div>
    );
  }
  return (
    <div className="space-y-5">
      {snapshot.completeness === "PARTIAL" && (
        <section
          role="status"
          className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4"
        >
          <strong>数据不完整</strong>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
            {snapshot.missingReasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </section>
      )}
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="涨跌停概览">
        {[
          ["涨停", snapshot.limitUpCount, "text-red-600"],
          ["跌停", snapshot.limitDownCount, "text-emerald-600"],
          ["封板", snapshot.sealedCount, "text-amber-600"],
          ["开板次数", snapshot.totalOpenCount, "text-foreground"],
        ].map(([label, value, className]) => (
          <Card key={String(label)}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-muted-foreground">{label}</CardTitle>
            </CardHeader>
            <CardContent className={`font-mono text-3xl font-semibold ${String(className)}`}>
              {value}
            </CardContent>
          </Card>
        ))}
      </section>

      <Card>
        <CardHeader className="gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <CardTitle>连板梯队与晋级率</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              晋级率 = 当日晋级数 / 前一交易日对应候选数；分母为 0 时不展示。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant={snapshot.freshness.status === "STALE" ? "destructive" : "secondary"}>
              {freshnessLabel(snapshot)}
            </Badge>
            <Badge variant="outline">算法 {snapshot.algorithmVersion}</Badge>
            <Badge variant="outline">梯队 {snapshot.ladderAlgorithmVersion}</Badge>
            <Badge variant="outline">规则 {snapshot.limitRuleVersion}</Badge>
            <Badge variant="outline">物化 {snapshot.materializerVersion}</Badge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {snapshot.ladder.map((level) => (
            <div key={level.streakDays} className="rounded-xl border bg-muted/20 p-4">
              <div className="text-sm text-muted-foreground">{level.streakDays} 连板</div>
              <div className="mt-1 flex items-end justify-between gap-2">
                <strong className="font-mono text-2xl">{level.count}</strong>
                <span className="font-mono text-sm">
                  晋级{" "}
                  {level.promotionRateBps === null
                    ? "-"
                    : `${(level.promotionRateBps / 100).toFixed(2)}%`}
                </span>
              </div>
              <div className="mt-2 text-xs text-muted-foreground">
                {level.promotedCount} / {level.previousDayEligibleCount} 个候选
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="gap-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle>证券池</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                筛选后 {visible.length} / {snapshot.entries.length} 条；仅渲染可视窗口。
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              onClick={() => downloadLimitPoolCsv(snapshot, visible)}
              disabled={visible.length === 0}
            >
              <Download aria-hidden="true" />
              导出当前结果
            </Button>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className="grid gap-1.5">
              <Label htmlFor="limit-pool-search">证券</Label>
              <div className="relative">
                <Search
                  aria-hidden="true"
                  className="absolute top-2.5 left-3 size-4 text-muted-foreground"
                />
                <Input
                  id="limit-pool-search"
                  className="pl-9"
                  value={filters.search}
                  placeholder="代码或名称"
                  onChange={(event) => onFilters({ ...filters, search: event.target.value })}
                />
              </div>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="limit-pool-side">方向</Label>
              <select
                id="limit-pool-side"
                className="h-9 rounded-md border bg-background px-3 text-sm"
                value={filters.side}
                onChange={(event) =>
                  onFilters({ ...filters, side: event.target.value as Filters["side"] })
                }
              >
                <option value="ALL">全部</option>
                <option value="LIMIT_UP">涨停</option>
                <option value="LIMIT_DOWN">跌停</option>
              </select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="limit-pool-state">状态</Label>
              <select
                id="limit-pool-state"
                className="h-9 rounded-md border bg-background px-3 text-sm"
                value={filters.state}
                onChange={(event) =>
                  onFilters({ ...filters, state: event.target.value as Filters["state"] })
                }
              >
                <option value="ALL">全部</option>
                <option value="SEALED">封板</option>
                <option value="OPENED">开板</option>
                <option value="LIMIT_DOWN">跌停</option>
              </select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="limit-pool-streak">最少连板</Label>
              <Input
                id="limit-pool-streak"
                type="number"
                min={0}
                max={99}
                value={filters.minimumStreak}
                onChange={(event) =>
                  onFilters({
                    ...filters,
                    minimumStreak: Math.max(0, Number(event.target.value) || 0),
                  })
                }
              />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {visible.length === 0 ? (
            <div className="rounded-xl border border-dashed p-10 text-center text-muted-foreground">
              没有符合筛选条件的证券
            </div>
          ) : (
            <VirtualizedLimitPoolTable
              entries={visible}
              sort={sort}
              onSort={onSort}
              onSelect={(entry) => onSelect(entry)}
            />
          )}
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-3 rounded-xl border bg-muted/20 p-4 text-xs text-muted-foreground">
        <ShieldCheck aria-hidden="true" className="size-4" />
        <span>数据截止 {formatShanghaiTime(snapshot.dataCutoffTime)}</span>
        <span>可得 {formatShanghaiTime(snapshot.availableTime)}</span>
        <span>修订 {snapshot.revision}</span>
        <span>证据 {snapshot.evidenceIds.length} 条</span>
      </div>
      <EvidenceDrawer entry={selected} onClose={() => onSelect(null)} />
    </div>
  );
}

export function LimitPoolTerminalPage() {
  const [mode, setMode] = useState<LimitPoolTerminalQuery["mode"]>("CURRENT");
  const [historicalLocal, setHistoricalLocal] = useState("");
  const [algorithmVersion, setAlgorithmVersion] = useState("");
  const [ladderAlgorithmVersion, setLadderAlgorithmVersion] = useState("");
  const [limitRuleVersion, setLimitRuleVersion] = useState("");
  const [materializerVersion, setMaterializerVersion] = useState("");
  const historicalAsOf = shanghaiLocalToIso(historicalLocal);
  const normalizedVersions = {
    algorithmVersion: algorithmVersion.trim(),
    ladderAlgorithmVersion: ladderAlgorithmVersion.trim(),
    limitRuleVersion: limitRuleVersion.trim(),
    materializerVersion: materializerVersion.trim(),
  };
  const suppliedVersionCount = Object.values(normalizedVersions).filter(Boolean).length;
  const hasCompleteVersionVector = suppliedVersionCount === 0 || suppliedVersionCount === 4;
  const hasValidHistoricalTime = mode === "CURRENT" || historicalAsOf !== undefined;
  const query: LimitPoolTerminalQuery =
    suppliedVersionCount === 4
      ? {
          mode,
          ...(mode === "HISTORICAL" && historicalAsOf !== undefined
            ? { asOf: historicalAsOf }
            : {}),
          algorithmVersion: normalizedVersions.algorithmVersion,
          ladderAlgorithmVersion: normalizedVersions.ladderAlgorithmVersion,
          limitRuleVersion: normalizedVersions.limitRuleVersion,
          materializerVersion: normalizedVersions.materializerVersion,
        }
      : {
          mode,
          ...(mode === "HISTORICAL" && historicalAsOf !== undefined
            ? { asOf: historicalAsOf }
            : {}),
        };
  const result = useLimitPoolTerminal(query, hasCompleteVersionVector && hasValidHistoricalTime);
  const [filters, setFilters] = useState<Filters>({
    search: "",
    side: "ALL",
    state: "ALL",
    minimumStreak: 0,
  });
  const [sort, setSort] = useState<LimitPoolSort>({ key: "streakDays", direction: "desc" });
  const [selected, setSelected] = useState<LimitPoolTerminalEntry | null>(null);
  const changeSort = (key: LimitPoolSortKey): void =>
    setSort((current) => ({
      key,
      direction: current.key === key && current.direction === "desc" ? "asc" : "desc",
    }));

  return (
    <section className="space-y-6" aria-labelledby="limit-pool-title">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
            Decision Terminal · Point-in-time
          </p>
          <h2 id="limit-pool-title" className="mt-2 text-3xl font-semibold tracking-tight">
            涨跌停与连板终端
          </h2>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
            查看版本化证券池、连板梯队、晋级率与逐股证据。所有结果仅供研究。
          </p>
        </div>
        <div className="flex max-w-5xl flex-wrap items-end gap-2 rounded-xl border bg-card p-3">
          <Button
            type="button"
            variant={mode === "CURRENT" ? "default" : "outline"}
            size="sm"
            onClick={() => setMode("CURRENT")}
          >
            <Radio aria-hidden="true" />
            当前
          </Button>
          <Button
            type="button"
            variant={mode === "HISTORICAL" ? "default" : "outline"}
            size="sm"
            onClick={() => setMode("HISTORICAL")}
          >
            <History aria-hidden="true" />
            历史
          </Button>
          {mode === "HISTORICAL" && (
            <div className="grid gap-1">
              <Label htmlFor="limit-pool-asof" className="text-xs">
                历史时点（上海）
              </Label>
              <Input
                id="limit-pool-asof"
                type="datetime-local"
                value={historicalLocal}
                onChange={(event) => setHistoricalLocal(event.target.value)}
              />
            </div>
          )}
          <div className="grid w-full gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <div className="grid gap-1">
              <Label htmlFor="limit-pool-version" className="text-xs">
                池算法版本
              </Label>
              <Input
                id="limit-pool-version"
                value={algorithmVersion}
                placeholder="全部留空或完整填写"
                onChange={(event) => setAlgorithmVersion(event.target.value)}
              />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="limit-pool-ladder-version" className="text-xs">
                梯队算法版本
              </Label>
              <Input
                id="limit-pool-ladder-version"
                value={ladderAlgorithmVersion}
                placeholder="board_ladder_v2"
                onChange={(event) => setLadderAlgorithmVersion(event.target.value)}
              />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="limit-pool-rule-version" className="text-xs">
                涨跌停规则版本
              </Label>
              <Input
                id="limit-pool-rule-version"
                value={limitRuleVersion}
                placeholder="规则契约版本"
                onChange={(event) => setLimitRuleVersion(event.target.value)}
              />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="limit-pool-materializer-version" className="text-xs">
                物化器版本
              </Label>
              <Input
                id="limit-pool-materializer-version"
                value={materializerVersion}
                placeholder="物化器实现版本"
                onChange={(event) => setMaterializerVersion(event.target.value)}
              />
            </div>
          </div>
        </div>
      </header>
      {!hasCompleteVersionVector ? (
        <div role="alert" className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-8">
          请填写完整版本向量（池、梯队、规则、物化器），或全部留空。
        </div>
      ) : !hasValidHistoricalTime ? (
        <div role="status" className="rounded-xl border border-dashed p-8">
          请选择有效的历史时点
        </div>
      ) : (
        <LimitPoolTerminalView
          result={result}
          filters={filters}
          sort={sort}
          selected={selected}
          onFilters={setFilters}
          onSort={changeSort}
          onSelect={setSelected}
        />
      )}
    </section>
  );
}
