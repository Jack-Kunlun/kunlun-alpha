"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { AlertCircle, BellRing, Clock3, Plus, RefreshCw, ShieldCheck } from "lucide-react";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../../components/ui/table";
import {
  requestId,
  useWatchlistAlerts,
  type AlertPreview,
  type CreateWatchlistAlertRuleRequest,
  type WatchlistAlertRule,
} from "./use-watchlist-alerts";

const OUTCOME_LABELS: Record<string, string> = {
  TRIGGERED: "已触发",
  CONDITION_NOT_MET: "未达条件",
  THROTTLED: "节流中",
  QUIET_PERIOD: "免打扰",
  RULE_DISABLED: "已停用",
};

export function AlertsPage() {
  const alerts = useWatchlistAlerts();
  const [preview, setPreview] = useState<AlertPreview | null>(null);

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

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 rounded-2xl border bg-gradient-to-br from-amber-50 via-background to-sky-50 p-6 dark:from-amber-950/20 dark:to-sky-950/20 md:flex-row md:items-end md:justify-between">
        <div className="space-y-2">
          <Badge variant="outline" className="w-fit gap-1">
            <ShieldCheck className="h-3.5 w-3.5" /> 研究提醒
          </Badge>
          <h1 className="text-3xl font-semibold tracking-tight">自选规则与预警</h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            用固定指标和比较条件监控自选证券。规则版本、抑制原因与通知结果均保留历史。
          </p>
        </div>
        <div className="text-right text-xs text-muted-foreground">
          <p>规则语言 {workspace.ruleLanguage}</p>
          <p>更新于 {formatTime(workspace.generatedAt)}</p>
        </div>
      </header>

      <div className="grid gap-6 xl:grid-cols-[380px_minmax(0,1fr)]">
        <RuleComposer disabled={alerts.submitting} onCreate={alerts.createRule} />
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">规则清单</h2>
              <p className="text-sm text-muted-foreground">只支持白名单字段与比较运算符。</p>
            </div>
            <Button variant="outline" size="sm" onClick={() => void alerts.refresh()}>
              <RefreshCw className="mr-2 h-4 w-4" /> 刷新
            </Button>
          </div>
          {workspace.rules.length === 0 ? (
            <EmptyRules />
          ) : (
            <div className="grid gap-3 lg:grid-cols-2">
              {workspace.rules.map((rule) => (
                <RuleCard
                  key={rule.ruleId}
                  rule={rule}
                  disabled={alerts.submitting}
                  onToggle={alerts.toggleRule}
                  onPreview={async (request) => setPreview(await alerts.preview(request))}
                />
              ))}
            </div>
          )}
          {preview ? (
            <div className="rounded-xl border border-sky-200 bg-sky-50 p-4 text-sm dark:border-sky-900 dark:bg-sky-950/30">
              <strong>{OUTCOME_LABELS[preview.outcome] ?? preview.outcome}</strong>
              <span className="ml-2 text-muted-foreground">{preview.detail}</span>
            </div>
          ) : null}
        </section>
      </div>

      <HistoryTable history={workspace.history} />
    </div>
  );
}

function RuleComposer({
  disabled,
  onCreate,
}: {
  disabled: boolean;
  onCreate: (request: CreateWatchlistAlertRuleRequest) => Promise<void>;
}) {
  const [name, setName] = useState("价格突破提醒");
  const [instrumentId, setInstrumentId] = useState("600519.SH");
  const [field, setField] = useState<WatchlistAlertRule["condition"]["field"]>("LAST_PRICE");
  const [operator, setOperator] = useState<WatchlistAlertRule["condition"]["operator"]>("GTE");
  const [threshold, setThreshold] = useState("1500.00");
  const [featureName, setFeatureName] = useState("momentum_20d");
  const [throttleSeconds, setThrottleSeconds] = useState("300");
  const [quietEnabled, setQuietEnabled] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      await onCreate({
        clientRequestId: requestId("create"),
        name,
        enabled: true,
        instrumentIds: [instrumentId.toUpperCase()],
        condition: {
          field,
          operator,
          threshold,
          featureName: field === "FEATURE_VALUE" ? featureName : null,
        },
        quietPeriod: quietEnabled
          ? { timezone: "Asia/Shanghai", startMinute: 23 * 60, endMinute: 7 * 60 }
          : null,
        throttleSeconds: Number(throttleSeconds),
        notificationChannel: "IN_APP",
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "规则保存失败");
    }
  }

  return (
    <Card className="h-fit xl:sticky xl:top-6">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Plus className="h-5 w-5" /> 新建规则
        </CardTitle>
        <CardDescription>阈值使用最多 8 位小数的十进制文本，避免价格比较误差。</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={(event) => void submit(event)}>
          <Field label="规则名称">
            <Input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} />
          </Field>
          <Field label="证券代码">
            <Input
              value={instrumentId}
              placeholder="600519.SH"
              onChange={(event) => setInstrumentId(event.target.value)}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="指标">
              <select
                className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                value={field}
                onChange={(event) => setField(event.target.value as typeof field)}
              >
                <option value="LAST_PRICE">最新价</option>
                <option value="CHANGE_BPS">涨跌幅 BPS</option>
                <option value="EMOTION_SCORE_BPS">情绪分 BPS</option>
                <option value="FEATURE_VALUE">特征值</option>
              </select>
            </Field>
            <Field label="运算符">
              <select
                className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                value={operator}
                onChange={(event) => setOperator(event.target.value as typeof operator)}
              >
                <option value="GT">大于</option>
                <option value="GTE">大于等于</option>
                <option value="LT">小于</option>
                <option value="LTE">小于等于</option>
                <option value="EQ">等于</option>
              </select>
            </Field>
          </div>
          {field === "FEATURE_VALUE" ? (
            <Field label="特征名称">
              <Input value={featureName} onChange={(event) => setFeatureName(event.target.value)} />
            </Field>
          ) : null}
          <Field label="阈值">
            <Input
              inputMode="decimal"
              value={threshold}
              onChange={(event) => setThreshold(event.target.value)}
            />
          </Field>
          <Field label="节流秒数">
            <Input
              type="number"
              min={0}
              max={86400}
              value={throttleSeconds}
              onChange={(event) => setThrottleSeconds(event.target.value)}
            />
          </Field>
          <label className="flex items-center gap-2 rounded-lg border p-3 text-sm">
            <input
              type="checkbox"
              checked={quietEnabled}
              onChange={(event) => setQuietEnabled(event.target.checked)}
            />
            23:00 至次日 07:00 免打扰
          </label>
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          <Button className="w-full" disabled={disabled} type="submit">
            <BellRing className="mr-2 h-4 w-4" /> 保存规则
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function RuleCard({
  rule,
  disabled,
  onToggle,
  onPreview,
}: {
  rule: WatchlistAlertRule;
  disabled: boolean;
  onToggle: (ruleId: string, enabled: boolean) => Promise<void>;
  onPreview: (
    request: Parameters<ReturnType<typeof useWatchlistAlerts>["preview"]>[0],
  ) => Promise<void>;
}) {
  const instrumentId = rule.instrumentIds[0];
  const now = new Date().toISOString();
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
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Clock3 className="h-3.5 w-3.5" /> 节流 {rule.throttleSeconds} 秒 ·{" "}
          {rule.quietPeriod ? "已设免打扰" : "无免打扰"}
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={disabled || !instrumentId}
            onClick={() =>
              instrumentId &&
              void onPreview({
                ruleId: rule.ruleId,
                eventId: requestId("preview"),
                instrumentId,
                field: rule.condition.field,
                featureName: rule.condition.featureName,
                observedValue: rule.condition.threshold,
                eventTime: now,
                availableTime: now,
              })
            }
          >
            阈值预览
          </Button>
          <Button
            size="sm"
            variant={rule.enabled ? "secondary" : "default"}
            disabled={disabled}
            onClick={() => void onToggle(rule.ruleId, !rule.enabled)}
          >
            {rule.enabled ? "停用" : "启用"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function HistoryTable({
  history,
}: {
  history: NonNullable<ReturnType<typeof useWatchlistAlerts>["workspace"]>["history"];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>评估与通知历史</CardTitle>
        <CardDescription>重复事件只保留一条记录，通知失败不会删除触发证据。</CardDescription>
      </CardHeader>
      <CardContent>
        {history.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            尚无评估历史。规则被数据任务评估后，结果会显示在这里。
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>时间</TableHead>
                <TableHead>证券</TableHead>
                <TableHead>结果</TableHead>
                <TableHead>观测值</TableHead>
                <TableHead>通知</TableHead>
                <TableHead>说明</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {history.map((item) => (
                <TableRow key={item.historyId}>
                  <TableCell className="whitespace-nowrap">
                    {formatTime(item.availableTime)}
                  </TableCell>
                  <TableCell className="font-mono">{item.instrumentId}</TableCell>
                  <TableCell>
                    <Badge variant={item.outcome === "TRIGGERED" ? "default" : "outline"}>
                      {OUTCOME_LABELS[item.outcome] ?? item.outcome}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono">{item.observedValue ?? "-"}</TableCell>
                  <TableCell>{item.notificationStatus}</TableCell>
                  <TableCell className="max-w-md text-muted-foreground">{item.detail}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function EmptyRules() {
  return (
    <div className="rounded-xl border border-dashed p-10 text-center">
      <BellRing className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
      <h3 className="font-medium">还没有预警规则</h3>
      <p className="mt-1 text-sm text-muted-foreground">从左侧创建第一条固定条件规则。</p>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Label className="block space-y-2">
      <span>{label}</span>
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
        <h1 className="text-xl font-semibold">{title}</h1>
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
