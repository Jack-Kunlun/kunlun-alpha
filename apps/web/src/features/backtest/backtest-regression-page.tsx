import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useBacktestRegression, useBacktestRegressionComparison, useBacktestRegressionRuns } from "./use-backtest-regressions";
import type { RegressionArtifact, RegressionComparison, RegressionRunSummary } from "./types";

function StateMessage({ kind, children }: { kind: "status" | "alert"; children: React.ReactNode }) {
  return (
    <p role={kind} className={kind === "alert" ? "text-destructive" : "text-muted-foreground"}>
      {children}
    </p>
  );
}

function MetricValue({ metric }: { metric: { status: string; value: string | null } }) {
  return <span>{metric.value ?? `不可用（${metric.status}）`}</span>;
}

export function BacktestRegressionReport({
  artifact,
  comparison,
  summary,
}: {
  artifact: RegressionArtifact;
  comparison: RegressionComparison;
  summary: RegressionRunSummary;
}) {
  const inputs = artifact.inputs;
  const results = artifact.results;
  const versions = artifact.versions;
  const diffs = comparison.diffs;
  const navTimes = inputs.navObservations.map((item) => item.observationTime);
  const statusMatched = comparison.status === "MATCHED";

  return (
    <div className="space-y-6" data-testid="backtest-regression-report">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">回测回归 · 证据账本</h1>
          <Badge variant={statusMatched ? "default" : "destructive"}>
            {statusMatched ? "MATCHED" : "DRIFTED"}
          </Badge>
          {summary.preview && <Badge variant="secondary">LOCAL_PREVIEW</Badge>}
        </div>
        <p className="text-sm text-muted-foreground">
          每个数字都绑定到 manifest、输入 lineage、代码摘要与人工审核记录；这是证据完整度，不是投资置信度。
        </p>
      </header>

      <section aria-labelledby="regression-overview" className="grid gap-4 md:grid-cols-3">
        <h2 id="regression-overview" className="sr-only">回测回归摘要</h2>
        <Card>
          <CardHeader><CardTitle className="text-sm">运行状态</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">
            <p>{artifact.suiteId} / {artifact.runId}</p>
            <p className="text-muted-foreground">fixture: {artifact.fixtureId}</p>
            <p className="text-muted-foreground">窗口: {navTimes[0]} 至 {navTimes.at(-1)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">摘要绑定</CardTitle></CardHeader>
          <CardContent className="space-y-1 break-all font-mono text-xs">
            <p>candidate: {comparison.candidateSha256}</p>
            <p>baseline: {comparison.baselineSha256}</p>
            <p>availability: {summary.availability}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">证据完整度</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">
            <p>{artifact.trust.evidenceIntegrityConfidence}</p>
            <p className="text-muted-foreground">trust: {artifact.trust.mode}</p>
            <p className="text-muted-foreground">基线不会自动更新或接受</p>
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader><CardTitle>版本矩阵与结果</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="overflow-x-auto">
            <Table>
              <TableCaption>引擎、执行、组合、估值与 metrics 的固定版本</TableCaption>
              <TableHeader><TableRow><TableHead>组件</TableHead><TableHead>版本</TableHead><TableHead>结果</TableHead></TableRow></TableHeader>
              <TableBody>
                {Object.entries(versions).map(([name, version]) => (
                  <TableRow key={name}><TableCell>{name}</TableCell><TableCell className="font-mono text-xs">{version}</TableCell><TableCell><Badge variant="outline">pinned</Badge></TableCell></TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Card><CardContent className="pt-4"><p className="text-xs text-muted-foreground">orders / fills</p><p className="text-lg font-semibold">{results.counts.orders} / {results.counts.fills}</p></CardContent></Card>
            <Card><CardContent className="pt-4"><p className="text-xs text-muted-foreground">总 PnL</p><p className="text-lg font-semibold">{results.pnl.total}</p></CardContent></Card>
            <Card><CardContent className="pt-4"><p className="text-xs text-muted-foreground">final NAV</p><p className="text-lg font-semibold">{results.finalNav}</p></CardContent></Card>
            <Card><CardContent className="pt-4"><p className="text-xs text-muted-foreground">nav observations</p><p className="text-lg font-semibold">{results.counts.navObservations}</p></CardContent></Card>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="performance metrics">
            {Object.entries(results.metrics).map(([name, metric]) => (
              <div key={name} className="min-w-0 rounded-md border p-3 text-sm"><p className="text-xs text-muted-foreground">{name}</p><p className="break-all font-mono"><MetricValue metric={metric} /></p></div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>确定性差异</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableCaption>按分类与 RFC6901 JSON Pointer 稳定排序；artifactSha256 自身不参与 tree diff</TableCaption>
            <TableHeader><TableRow><TableHead>分类</TableHead><TableHead>JSON Pointer</TableHead><TableHead>baseline</TableHead><TableHead>candidate</TableHead><TableHead>状态</TableHead></TableRow></TableHeader>
            <TableBody>
              {diffs.length === 0 ? (
                <TableRow><TableCell colSpan={5}>没有差异；依赖与工具链也已比较。</TableCell></TableRow>
              ) : diffs.map((diff) => (
                <TableRow key={`${diff.category}:${diff.pointer}`}>
                  <TableCell><Badge variant="outline">{diff.category}</Badge></TableCell>
                  <TableCell className="max-w-[22rem] break-all font-mono text-xs">{diff.pointer}</TableCell>
                  <TableCell className="max-w-[14rem] break-all font-mono text-xs">{JSON.stringify(diff.baselineValue)}</TableCell>
                  <TableCell className="max-w-[14rem] break-all font-mono text-xs">{JSON.stringify(diff.candidateValue)}</TableCell>
                  <TableCell>{diff.status}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <footer className="rounded-lg border bg-muted/30 p-4 text-sm text-muted-foreground">
        <h2 className="font-medium text-foreground">人工审核边界</h2>
        <p className="mt-1">baseline approval 必须由人工绑定 reviewedArtifactSha256 与 evidence refs；CI 只读比较，任何算法、输入、依赖、工具链或结果漂移都会失败。</p>
      </footer>
    </div>
  );
}

export function BacktestRegressionPage() {
  const runs = useBacktestRegressionRuns();
  const summary = runs.data?.[0];
  const runId = summary?.runId ?? "";
  const artifact = useBacktestRegression(runId);
  const comparison = useBacktestRegressionComparison(runId, summary?.suiteId ?? "");

  if (runs.status === "loading") return <StateMessage kind="status">正在读取回测证据账本…</StateMessage>;
  if (runs.status === "empty") return <StateMessage kind="status">暂无已审核的回测回归运行</StateMessage>;
  if (runs.status === "forbidden") return <StateMessage kind="alert">无权访问回测回归报告</StateMessage>;
  if (runs.status === "error") return <StateMessage kind="alert">回测回归报告加载失败：{runs.error?.message}</StateMessage>;
  if (summary === undefined) return <StateMessage kind="status">暂无可展示的回归摘要</StateMessage>;
  if (artifact.status === "loading" || comparison.status === "loading") return <StateMessage kind="status">正在校验制品摘要与比较结果…</StateMessage>;
  if (artifact.status === "forbidden" || comparison.status === "forbidden") return <StateMessage kind="alert">无权访问回测回归制品</StateMessage>;
  if (artifact.status === "error" || comparison.status === "error") return <StateMessage kind="alert">回测回归制品不可用</StateMessage>;
  if (artifact.data === null || comparison.data === null) return <StateMessage kind="status">暂无可展示的回归制品</StateMessage>;

  return <BacktestRegressionReport artifact={artifact.data} comparison={comparison.data} summary={summary} />;
}
