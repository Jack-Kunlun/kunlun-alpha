"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { useSearchParams } from "react-router";
import { Activity, AlertCircle, BellRing, Clock3, RefreshCw, ShieldCheck } from "lucide-react";
import type {
  UpdateWatchlistAlertRuleRequest,
  WatchlistAlertEvaluationRun,
} from "@kunlun/shared-types";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import {
  requestId,
  useWatchlistAlerts,
  type AlertPreview,
  type WatchlistAlertRule,
} from "./use-watchlist-alerts";

import { CreateRuleDrawer } from "./create-rule-drawer";
import {
  createRuleInstrument,
  filterAlertRules,
  type RuleEnabledFilter,
} from "./alert-rule-filters";

import { ALERT_HISTORY_OUTCOMES as OUTCOME_LABELS } from "./alert-history";
import { AlertHistoryCard } from "./alert-history-card";

export function evaluationRunStatus(run: Pick<WatchlistAlertEvaluationRun, "failed">): {
  title: string;
  role: "alert" | "status";
  tone: "failure" | "success";
} {
  return run.failed > 0
    ? { title: "行情评估存在失败", role: "alert", tone: "failure" }
    : { title: "最新行情评估完成", role: "status", tone: "success" };
}

export function AlertsPage() {
  const alerts = useWatchlistAlerts();
  const [searchParams, setSearchParams] = useSearchParams();
  const [instrumentQuery, setInstrumentQuery] = useState("");
  const [enabledFilter, setEnabledFilter] = useState<RuleEnabledFilter>("all");
  const [preview, setPreview] = useState<AlertPreview | null>(null);
  const [evaluationRun, setEvaluationRun] = useState<WatchlistAlertEvaluationRun | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const requestedInstrumentId = createRuleInstrument(searchParams);

  function clearFilters() {
    setInstrumentQuery("");
    setEnabledFilter("all");
  }

  function clearCreateRequest() {
    if (!searchParams.has("createFor")) return;
    const next = new URLSearchParams(searchParams);
    next.delete("createFor");
    setSearchParams(next, { replace: true });
  }

  async function evaluateLatest() {
    setActionError(null);
    try {
      setEvaluationRun(await alerts.evaluateLatest());
    } catch (cause) {
      setActionError(errorMessage(cause, "最新行情评估失败"));
    }
  }

  if (alerts.state === "loading")
    return <PageState title="正在读取预警规则" detail="同步规则版本与投递历史。" />;
  if (alerts.state === "forbidden") {
    return (
      <PageState
        title="当前终端未配置预警所有者"
        detail="请由服务端配置本地研究用户，客户端不能代填身份。"
      />
    );
  }
  if (alerts.state === "error") {
    return (
      <PageState
        title="预警工作区暂不可用"
        detail={alerts.error ?? "请检查服务与数据库状态。"}
        action={<Button onClick={() => void alerts.refresh()}>重新加载</Button>}
      />
    );
  }

  const workspace = alerts.workspace;
  if (!workspace) return null;
  const visibleRules = filterAlertRules(workspace.rules, instrumentQuery, enabledFilter);
  const evaluationStatus = evaluationRun ? evaluationRunStatus(evaluationRun) : null;

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 rounded-2xl border bg-gradient-to-br from-amber-50 via-background to-sky-50 p-6 dark:from-amber-950/20 dark:to-sky-950/20 md:flex-row md:items-end md:justify-between">
        <div className="space-y-2">
          <Badge variant="outline" className="w-fit gap-1">
            <ShieldCheck className="h-3.5 w-3.5" /> 研究提醒
          </Badge>
          <h2 className="text-3xl font-semibold tracking-tight">自选规则与预警</h2>
          <p className="max-w-2xl text-sm text-muted-foreground">
            用固定指标和比较条件监控自选证券。规则版本、抑制原因与通知结果均保留历史。
          </p>
        </div>
        <div className="text-right text-xs text-muted-foreground">
          <p>规则语言 {workspace.ruleLanguage}</p>
          <p>更新于 {formatTime(workspace.generatedAt)}</p>
        </div>
      </header>

      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">规则清单</h2>
            <p className="text-sm text-muted-foreground">新规则仅可选择当前支持自动评估的字段。</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <CreateRuleDrawer
              disabled={alerts.submitting || alerts.refreshing}
              requestedInstrumentId={requestedInstrumentId}
              onClose={clearCreateRequest}
              onCreate={async (request) => {
                await alerts.createRule(request);
                clearFilters();
              }}
            />
            <Button
              variant="outline"
              size="sm"
              disabled={alerts.submitting || alerts.refreshing || workspace.rules.length === 0}
              aria-busy={alerts.submitting}
              onClick={() => void evaluateLatest()}
            >
              <Activity className="mr-2 h-4 w-4" /> 立即评估最新行情
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={alerts.submitting || alerts.refreshing}
              aria-busy={alerts.refreshing}
              onClick={() => void alerts.refresh()}
            >
              <RefreshCw className="mr-2 h-4 w-4" /> {alerts.refreshing ? "刷新中…" : "刷新"}
            </Button>
          </div>
        </div>
        {alerts.error && (
          <p role="alert" className="text-sm text-destructive">
            {alerts.error}；保留上次读取的规则和当前输入，可重试刷新。
          </p>
        )}
        <div className="grid items-end gap-4 rounded-xl border bg-card p-4 sm:grid-cols-[minmax(0,1fr)_12rem_auto]">
          <Field label="证券代码筛选">
            <Input
              value={instrumentQuery}
              placeholder="输入代码，如 600519.SH"
              onChange={(event) => setInstrumentQuery(event.target.value)}
            />
          </Field>
          <Field label="启用状态">
            <select
              className="h-9 w-full rounded-md border bg-background px-3 text-sm"
              value={enabledFilter}
              onChange={(event) => setEnabledFilter(event.target.value as RuleEnabledFilter)}
            >
              <option value="all">全部状态</option>
              <option value="enabled">已启用</option>
              <option value="disabled">已停用</option>
            </select>
          </Field>
          <Button
            type="button"
            variant="outline"
            disabled={instrumentQuery === "" && enabledFilter === "all"}
            onClick={clearFilters}
          >
            清除筛选
          </Button>
        </div>
        <p role="status" className="text-sm text-muted-foreground">
          显示 {visibleRules.length} / {workspace.rules.length} 条规则
        </p>
        {workspace.rules.length === 0 ? (
          <EmptyRules />
        ) : visibleRules.length === 0 ? (
          <div className="rounded-xl border border-dashed p-8 text-center">
            <p className="font-medium">没有符合筛选条件的规则</p>
            <p className="mt-1 text-sm text-muted-foreground">
              调整证券代码或启用状态，或清除筛选。
            </p>
          </div>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {visibleRules.map((rule) => (
              <RuleCard
                key={rule.ruleId}
                rule={rule}
                disabled={alerts.submitting || alerts.refreshing}
                onToggle={alerts.toggleRule}
                onUpdate={alerts.updateRule}
                onPreview={async (request) => setPreview(await alerts.preview(request))}
              />
            ))}
          </div>
        )}
        {actionError ? (
          <p
            role="alert"
            className="rounded-lg border border-destructive/40 p-3 text-sm text-destructive"
          >
            {actionError}
          </p>
        ) : null}
        {preview ? (
          <div className="rounded-xl border border-sky-200 bg-sky-50 p-4 text-sm dark:border-sky-900 dark:bg-sky-950/30">
            <strong>{OUTCOME_LABELS[preview.outcome] ?? preview.outcome}</strong>
            <span className="ml-2 text-muted-foreground">{preview.detail}</span>
          </div>
        ) : null}
        {evaluationRun && evaluationStatus ? (
          <div
            role={evaluationStatus.role}
            className={
              evaluationStatus.tone === "failure"
                ? "rounded-xl border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive"
                : "rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm dark:border-emerald-900 dark:bg-emerald-950/30"
            }
          >
            <strong>{evaluationStatus.title}</strong>
            <span className="ml-2 text-muted-foreground">
              已评估 {evaluationRun.evaluated}，数据不足 {evaluationRun.skippedNoData}，暂不支持{" "}
              {evaluationRun.skippedUnsupported}，失败 {evaluationRun.failed}
            </span>
          </div>
        ) : null}
      </section>

      <AlertHistoryCard workspace={workspace} />
    </div>
  );
}

function RuleCard({
  rule,
  disabled,
  onToggle,
  onUpdate,
  onPreview,
}: {
  rule: WatchlistAlertRule;
  disabled: boolean;
  onToggle: (ruleId: string, enabled: boolean) => Promise<void>;
  onUpdate: (ruleId: string, request: UpdateWatchlistAlertRuleRequest) => Promise<void>;
  onPreview: (
    request: Parameters<ReturnType<typeof useWatchlistAlerts>["preview"]>[0],
  ) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState(rule.name);
  const [draftThreshold, setDraftThreshold] = useState(rule.condition.threshold);
  const [expectedRevision, setExpectedRevision] = useState(rule.revision);
  const [clientRequestId, setClientRequestId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const instrumentId = rule.instrumentIds[0];
  const now = new Date().toISOString();
  const automaticallyEvaluated =
    rule.condition.field === "LAST_PRICE" || rule.condition.field === "CHANGE_BPS";

  function beginEdit() {
    setDraftName(rule.name);
    setDraftThreshold(rule.condition.threshold);
    setExpectedRevision(rule.revision);
    setClientRequestId(requestId("edit"));
    setActionError(null);
    setEditing(true);
  }

  function cancelEdit() {
    setDraftName(rule.name);
    setDraftThreshold(rule.condition.threshold);
    setClientRequestId(null);
    setActionError(null);
    setEditing(false);
  }

  async function saveEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    const commandRequestId = clientRequestId ?? requestId("edit");
    setClientRequestId(commandRequestId);
    setSaving(true);
    setActionError(null);
    try {
      await onUpdate(rule.ruleId, {
        clientRequestId: commandRequestId,
        expectedRevision,
        name: draftName,
        threshold: draftThreshold,
      });
      setEditing(false);
      setClientRequestId(null);
    } catch (cause) {
      setActionError(
        httpStatus(cause) === 409
          ? "规则版本已变化或请求标识冲突；刷新后重新编辑。"
          : errorMessage(cause, "规则修改失败；请检查版本后重试"),
      );
    } finally {
      setSaving(false);
    }
  }

  async function toggle() {
    setActionError(null);
    try {
      await onToggle(rule.ruleId, !rule.enabled);
    } catch (cause) {
      setActionError(errorMessage(cause, "规则状态修改失败"));
    }
  }

  async function showPreview() {
    if (!instrumentId || previewing) return;
    setPreviewing(true);
    setActionError(null);
    try {
      await onPreview({
        ruleId: rule.ruleId,
        eventId: requestId("preview"),
        instrumentId,
        field: rule.condition.field,
        featureName: rule.condition.featureName,
        observedValue: rule.condition.threshold,
        eventTime: now,
        availableTime: now,
      });
    } catch (cause) {
      setActionError(errorMessage(cause, "规则预览失败"));
    } finally {
      setPreviewing(false);
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="text-base">{rule.name}</CardTitle>
            <CardDescription>
              修订 {rule.revision} · {rule.instrumentIds.join("、")}
            </CardDescription>
          </div>
          <Badge variant={rule.enabled ? "default" : "secondary"}>
            {rule.enabled ? "启用" : "停用"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-lg bg-muted/60 p-3 font-mono text-sm">
          {rule.condition.field} {rule.condition.operator} {rule.condition.threshold}
        </div>
        {!automaticallyEvaluated ? (
          <p className="text-sm text-amber-700 dark:text-amber-300">
            该规则使用的指标本版本不自动评估。
          </p>
        ) : null}
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Clock3 className="h-3.5 w-3.5" /> 节流 {rule.throttleSeconds} 秒 ·{" "}
          {rule.quietPeriod ? "已设免打扰" : "无免打扰"}
        </div>
        {editing ? (
          <form
            className="space-y-3 rounded-lg border p-3"
            aria-busy={saving}
            onSubmit={(event) => void saveEdit(event)}
          >
            <Field label="规则名称">
              <Input
                value={draftName}
                disabled={disabled || saving}
                required
                maxLength={80}
                onChange={(event) => {
                  setDraftName(event.target.value);
                  setClientRequestId(requestId("edit"));
                  setActionError(null);
                }}
              />
            </Field>
            <Field label="十进制阈值">
              <Input
                inputMode="decimal"
                value={draftThreshold}
                disabled={disabled || saving}
                required
                maxLength={80}
                onChange={(event) => {
                  setDraftThreshold(event.target.value);
                  setClientRequestId(requestId("edit"));
                  setActionError(null);
                }}
              />
            </Field>
            {actionError ? (
              <p role="alert" className="text-sm text-destructive">
                {actionError}
              </p>
            ) : null}
            <div className="flex gap-2">
              <Button size="sm" disabled={disabled || saving} type="submit">
                {saving ? "保存中…" : "保存修改"}
              </Button>
              <Button
                size="sm"
                type="button"
                variant="outline"
                disabled={saving}
                onClick={cancelEdit}
              >
                取消
              </Button>
            </div>
          </form>
        ) : (
          <div className="flex flex-wrap gap-2">
            {automaticallyEvaluated ? (
              <Button
                size="sm"
                variant="outline"
                disabled={disabled || previewing || !instrumentId}
                aria-busy={previewing}
                onClick={() => void showPreview()}
              >
                {previewing ? "预览中…" : "阈值预览"}
              </Button>
            ) : null}
            <Button size="sm" variant="outline" disabled={disabled} onClick={beginEdit}>
              编辑
            </Button>
            <Button
              size="sm"
              variant={rule.enabled ? "secondary" : "default"}
              disabled={disabled}
              aria-busy={disabled}
              onClick={() => void toggle()}
            >
              {rule.enabled ? "停用" : "启用"}
            </Button>
          </div>
        )}
        {!editing && actionError ? (
          <p role="alert" className="text-sm text-destructive">
            {actionError}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function EmptyRules() {
  return (
    <div className="rounded-xl border border-dashed p-10 text-center">
      <BellRing className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
      <h3 className="font-medium">还没有预警规则</h3>
      <p className="mt-1 text-sm text-muted-foreground">点击“新建规则”创建第一条提醒。</p>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Label className="flex flex-col items-stretch gap-2">
      <span className="leading-5">{label}</span>
      {children}
    </Label>
  );
}

function PageState({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex min-h-[420px] items-center justify-center">
      <div className="max-w-md rounded-2xl border bg-card p-8 text-center shadow-sm">
        <AlertCircle className="mx-auto mb-4 h-9 w-9 text-muted-foreground" />
        <h2 className="text-xl font-semibold">{title}</h2>
        <p className="mt-2 text-sm text-muted-foreground">{detail}</p>
        {action ? <div className="mt-5">{action}</div> : null}
      </div>
    </div>
  );
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function httpStatus(error: unknown): number | null {
  if (typeof error !== "object" || error === null) return null;
  const status = (error as { status?: unknown }).status;
  return typeof status === "number" ? status : null;
}
