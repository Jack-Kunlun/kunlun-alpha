"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { rankingAcceptanceSnapshot } from "./ranking-fixture";
import {
  clampMinimumScore,
  defaultRankingFilters,
  exclusionReasonLabel,
  filterRankingRows,
  formatPercent,
  formatScore,
  formatShanghaiTime,
  missingPolicyLabel,
  missingReasonLabel,
  rankingContextNotice,
  rankingSectors,
} from "./ranking-terminal-model";
import type {
  RankingContribution,
  RankingFeatureSpec,
  RankingFilters,
  RankingRow,
  RankingSnapshot,
  RankingSpec,
  RankingTerminalResult,
} from "./types";

interface RankingTerminalViewProps {
  result: RankingTerminalResult;
  initialFilters?: Partial<RankingFilters>;
  contextNotice?: string | null;
}

function TerminalState({
  title,
  message,
  tone,
}: {
  title: string;
  message: string;
  tone: "neutral" | "danger";
}) {
  return (
    <section
      aria-label="Intelligence Ranking 状态"
      className="min-h-[70vh] bg-[radial-gradient(circle_at_top_left,rgba(14,116,144,0.12),transparent_38%),linear-gradient(135deg,#f8fafc,#ecfeff)] p-4 sm:p-8"
    >
      <Card
        className={`mx-auto mt-16 max-w-xl border-2 ${tone === "danger" ? "border-red-200" : "border-cyan-200"}`}
        role={tone === "danger" ? "alert" : "status"}
      >
        <CardHeader>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{message}</CardDescription>
        </CardHeader>
      </Card>
    </section>
  );
}

export function ContributionEvidence({
  item,
  feature,
}: {
  item: RankingContribution;
  feature: RankingFeatureSpec;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <strong className="text-sm text-slate-950">{item.label}</strong>
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">
            {item.direction === "LOWER_IS_BETTER" ? "越低越优" : "越高越优"}
          </Badge>
          <Badge variant="outline">{missingPolicyLabel(feature.missingPolicy)}</Badge>
        </div>
      </div>
      {item.missingReason ? (
        <p className="mt-3 text-sm font-medium text-amber-700">
          缺失：{missingReasonLabel(item.missingReason)}；按“
          {missingPolicyLabel(feature.missingPolicy)}”执行。
        </p>
      ) : null}
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-5">
        {item.missingReason === null ? (
          <>
            <div>
              <dt className="text-slate-500">原始值</dt>
              <dd className="font-mono text-slate-900">{item.rawValue}</dd>
            </div>
            <div>
              <dt className="text-slate-500">标准化分</dt>
              <dd className="font-mono text-slate-900">{formatScore(item.normalizedScoreBps)}</dd>
            </div>
          </>
        ) : null}
        <div>
          <dt className="text-slate-500">配置权重</dt>
          <dd className="font-mono text-slate-900">{formatPercent(item.configuredWeightBps)}</dd>
        </div>
        <div>
          <dt className="text-slate-500">有效权重</dt>
          <dd className="font-mono text-slate-900">{formatPercent(item.effectiveWeightBps)}</dd>
        </div>
        <div>
          <dt className="text-slate-500">贡献分</dt>
          <dd className="font-mono font-semibold text-cyan-800">
            {formatScore(item.contributionBps)}
          </dd>
        </div>
      </dl>
      <p className="mt-3 break-all text-xs text-slate-500">
        来源：{item.source ?? "无可用来源"} · 可用时间：
        {item.availableTime ? formatShanghaiTime(item.availableTime) : "快照时点不可用"}
      </p>
    </div>
  );
}

export function RankingEvidenceDialog({ row, spec }: { row: RankingRow; spec: RankingSpec }) {
  const missingItems = row.contributions.filter((item) => item.missingReason !== null);
  const missingCount = missingItems.length;
  const featureByKey = new Map(spec.features.map((feature) => [feature.key, feature]));
  const reweightedItems = row.contributions.filter(
    (item) => item.missingReason === null && item.effectiveWeightBps !== item.configuredWeightBps,
  );
  return (
    <Dialog>
      <div className="flex flex-col items-end gap-1">
        <DialogTrigger asChild>
          <Button variant="outline" size="sm">
            查看贡献{missingCount > 0 ? ` · 缺失 ${missingCount}` : ""}
          </Button>
        </DialogTrigger>
        {missingItems.map((item) => {
          const feature = featureByKey.get(item.featureKey);
          if (!feature || !item.missingReason) return null;
          return (
            <span
              key={item.featureKey}
              className="max-w-72 whitespace-normal text-xs text-amber-700"
            >
              {item.label}：{missingReasonLabel(item.missingReason)} ·{" "}
              {missingPolicyLabel(feature.missingPolicy)} · 配置{" "}
              {formatPercent(item.configuredWeightBps)} → 有效{" "}
              {formatPercent(item.effectiveWeightBps)} · 贡献 {formatScore(item.contributionBps)}
            </span>
          );
        })}
        {reweightedItems.map((item) => (
          <span
            key={`reweighted-${item.featureKey}`}
            className="max-w-72 whitespace-normal text-xs text-cyan-700"
          >
            {item.label}：配置 {formatPercent(item.configuredWeightBps)} → 有效{" "}
            {formatPercent(item.effectiveWeightBps)}
          </span>
        ))}
      </div>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {row.instrumentName} · {row.instrumentId}
          </DialogTitle>
          <DialogDescription>
            总分严格等于各项贡献之和；过滤不会重算总分或全局名次。
          </DialogDescription>
        </DialogHeader>
        {row.exclusionReasons.length > 0 ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            未进入排名：
            {row.exclusionReasons
              .map((reason) => exclusionReasonLabel(reason, spec.features))
              .join("；")}
          </div>
        ) : null}
        <div className="space-y-3">
          {row.contributions.map((item) => {
            const feature = featureByKey.get(item.featureKey);
            return feature ? (
              <ContributionEvidence key={item.featureKey} item={item} feature={feature} />
            ) : (
              <p key={item.featureKey} className="text-sm text-red-700" role="alert">
                RankingSpec 缺少特征定义：{item.featureKey}
              </p>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function SnapshotEvidence({ snapshot }: { snapshot: RankingSnapshot }) {
  return (
    <section aria-labelledby="ranking-evidence-title" className="grid gap-4 lg:grid-cols-3">
      <Card className="border-slate-200 lg:col-span-2">
        <CardHeader>
          <CardTitle id="ranking-evidence-title" className="text-base">
            RankingSpec 与快照证据
          </CardTitle>
          <CardDescription>同一 spec、输入指纹与 as-of 只产生一个稳定排序快照。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm sm:grid-cols-2">
          <p>
            <span className="text-slate-500">Spec：</span>
            <strong>{snapshot.spec.specId}</strong> v{snapshot.spec.version}
          </p>
          <p>
            <span className="text-slate-500">算法：</span>
            <strong>{snapshot.spec.algorithmVersion}</strong>
          </p>
          <p className="break-all font-mono text-xs sm:col-span-2">
            <span className="font-sans text-slate-500">Snapshot ID：</span>
            {snapshot.snapshotId}
          </p>
          <p className="break-all font-mono text-xs sm:col-span-2">
            <span className="font-sans text-slate-500">Input fingerprint：</span>
            {snapshot.inputFingerprint}
          </p>
        </CardContent>
      </Card>
      <Card className="border-cyan-200 bg-cyan-950 text-cyan-50">
        <CardHeader>
          <CardTitle className="text-base">点时边界</CardTitle>
          <CardDescription className="text-cyan-100/70">
            只使用 available_time 不晚于 as-of 的特征。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>数据快照：{formatShanghaiTime(snapshot.asOf)}</p>
          <p>生成时间：{formatShanghaiTime(snapshot.generatedAt)}</p>
          <p>最低覆盖率：{formatPercent(snapshot.spec.minimumCoverageBps)}</p>
        </CardContent>
      </Card>
    </section>
  );
}

function RankingSuccess({
  snapshot,
  initialFilters,
  contextNotice,
}: {
  snapshot: RankingSnapshot;
  initialFilters?: Partial<RankingFilters>;
  contextNotice?: string | null;
}) {
  const [filters, setFilters] = useState<RankingFilters>({
    ...defaultRankingFilters,
    ...initialFilters,
  });
  const sectors = useMemo(() => rankingSectors(snapshot), [snapshot]);
  const rows = useMemo(() => filterRankingRows(snapshot, filters), [filters, snapshot]);

  return (
    <section
      aria-labelledby="ranking-page-title"
      className="min-h-screen bg-[radial-gradient(circle_at_15%_0%,rgba(8,145,178,0.15),transparent_32%),radial-gradient(circle_at_90%_18%,rgba(245,158,11,0.10),transparent_30%),linear-gradient(145deg,#f8fafc,#ecfeff_48%,#fff7ed)] p-4 text-slate-950 sm:p-8"
    >
      <div className="mx-auto max-w-[1480px] space-y-6">
        <header className="overflow-hidden rounded-3xl border border-cyan-200 bg-white/90 p-6 shadow-[0_24px_70px_-40px_rgba(8,145,178,0.7)] backdrop-blur sm:p-8">
          <div className="flex flex-col justify-between gap-6 xl:flex-row xl:items-end">
            <div className="max-w-3xl">
              <div className="mb-3 flex flex-wrap gap-2">
                <Badge className="bg-amber-500 text-amber-950 hover:bg-amber-500">
                  版本化研究快照
                </Badge>
                <Badge variant="outline">离线数据</Badge>
              </div>
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-cyan-700">
                Intelligence Ranking
              </p>
              <h1
                id="ranking-page-title"
                className="mt-2 text-3xl font-black tracking-tight sm:text-5xl"
              >
                股票智能排序
              </h1>
              <p className="mt-4 max-w-2xl text-sm leading-6 text-slate-600 sm:text-base">
                将点时特征组合为可解释排名，逐项展示标准化分、有效权重、贡献与缺失原因。
              </p>
            </div>
            <div className="rounded-2xl border border-amber-300 bg-amber-50 px-5 py-4 text-sm text-amber-950 xl:max-w-md">
              <strong className="block">研究排序，不构成收益保证</strong>
              <span>当前尚未接入实时 Ranking 读取端，不产生 Signal、OrderIntent 或订单。</span>
            </div>
          </div>
        </header>

        {contextNotice ? (
          <div
            className="rounded-2xl border border-orange-300 bg-orange-50 px-5 py-4 text-sm text-orange-950"
            role="note"
          >
            <strong className="block">URL 上下文未应用</strong>
            {contextNotice}
          </div>
        ) : null}

        <SnapshotEvidence snapshot={snapshot} />

        <Card className="border-slate-200 bg-white/95">
          <CardHeader>
            <CardTitle>筛选排名</CardTitle>
            <CardDescription>
              筛选只作用于已生成快照，不在浏览器中重新计算分数或名次。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
              <label className="space-y-2 text-sm font-medium xl:col-span-2">
                股票代码或名称
                <Input
                  value={filters.query}
                  placeholder="例如 600519 或 平安"
                  onChange={(event) =>
                    setFilters((current) => ({ ...current, query: event.target.value }))
                  }
                />
              </label>
              <label className="space-y-2 text-sm font-medium">
                行业
                <select
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  value={filters.sector ?? "ALL"}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      sector: event.target.value === "ALL" ? null : event.target.value,
                    }))
                  }
                >
                  <option value="ALL">全部行业</option>
                  {sectors.map((sector) => (
                    <option key={sector} value={sector}>
                      {sector}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-2 text-sm font-medium">
                最低分（0-100）
                <Input
                  inputMode="decimal"
                  min="0"
                  max="100"
                  step="0.01"
                  type="number"
                  value={filters.minimumScoreBps === null ? "" : filters.minimumScoreBps / 100}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      minimumScoreBps: clampMinimumScore(event.target.value),
                    }))
                  }
                />
              </label>
              <div className="flex flex-col justify-end gap-3">
                <label className="flex min-h-9 items-center gap-2 text-sm font-medium">
                  <input
                    className="size-4 accent-cyan-700"
                    type="checkbox"
                    checked={filters.includeExcluded}
                    onChange={(event) =>
                      setFilters((current) => ({
                        ...current,
                        includeExcluded: event.target.checked,
                      }))
                    }
                  />
                  显示未入榜记录
                </label>
                <Button variant="outline" onClick={() => setFilters(defaultRankingFilters)}>
                  重置筛选
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="overflow-hidden border-slate-200 bg-white/95">
          <CardHeader className="border-b border-slate-100">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <CardTitle>排序结果</CardTitle>
                <CardDescription>显示 {rows.length} 条；全局名次保持不变。</CardDescription>
              </div>
              <Badge variant="outline">Spec v{snapshot.spec.version}</Badge>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {rows.length === 0 ? (
              <div className="p-12 text-center" role="status">
                <p className="text-lg font-semibold">当前筛选没有匹配记录</p>
                <p className="mt-2 text-sm text-slate-500">调整股票、行业或最低分条件后重试。</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-20">名次</TableHead>
                      <TableHead className="min-w-48">股票</TableHead>
                      <TableHead>行业</TableHead>
                      <TableHead>综合分</TableHead>
                      <TableHead>覆盖率</TableHead>
                      <TableHead className="text-right">解释</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((row) => (
                      <TableRow key={row.instrumentId} className="align-top">
                        <TableCell>
                          {row.rank === null ? (
                            <Badge variant="outline">未入榜</Badge>
                          ) : (
                            <span className="font-mono text-lg font-black text-cyan-800">
                              {String(row.rank).padStart(2, "0")}
                            </span>
                          )}
                        </TableCell>
                        <TableCell>
                          <strong className="block">{row.instrumentName}</strong>
                          <span className="font-mono text-xs text-slate-500">
                            {row.instrumentId}
                          </span>
                          {row.exclusionReasons.length > 0 ? (
                            <span className="mt-1 block max-w-72 whitespace-normal text-xs text-amber-700">
                              {row.exclusionReasons
                                .map((reason) =>
                                  exclusionReasonLabel(reason, snapshot.spec.features),
                                )
                                .join("；")}
                            </span>
                          ) : null}
                        </TableCell>
                        <TableCell>{row.sector}</TableCell>
                        <TableCell>
                          <strong className="font-mono text-lg">{formatScore(row.scoreBps)}</strong>
                          {row.scoreBps !== null ? (
                            <div className="mt-2 h-1.5 w-28 overflow-hidden rounded-full bg-slate-100">
                              <div
                                className="h-full rounded-full bg-gradient-to-r from-cyan-700 to-amber-400"
                                style={{ width: `${row.scoreBps / 100}%` }}
                              />
                            </div>
                          ) : null}
                        </TableCell>
                        <TableCell>{formatPercent(row.coverageBps)}</TableCell>
                        <TableCell className="text-right">
                          <RankingEvidenceDialog row={row} spec={snapshot.spec} />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </section>
  );
}

export function RankingTerminalView({
  result,
  initialFilters,
  contextNotice,
}: RankingTerminalViewProps) {
  if (result.state === "loading") {
    return (
      <TerminalState
        title="正在加载 Intelligence Ranking"
        message="正在读取排名快照与版本证据。"
        tone="neutral"
      />
    );
  }
  if (result.state === "forbidden") {
    return <TerminalState title="无权查看股票智能排序" message={result.message} tone="danger" />;
  }
  if (result.state === "error") {
    return <TerminalState title="排名快照加载失败" message={result.message} tone="danger" />;
  }
  return (
    <RankingSuccess
      snapshot={result.snapshot}
      initialFilters={initialFilters}
      contextNotice={contextNotice}
    />
  );
}

export function RankingTerminalPage() {
  const [searchParams] = useSearchParams();
  return (
    <RankingTerminalView
      result={{ state: "success", snapshot: rankingAcceptanceSnapshot }}
      contextNotice={rankingContextNotice(searchParams)}
    />
  );
}
