import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { readPaperAccountCosts, type PaperAccountCosts } from "./paper-account-costs";
import { formatPaperLedgerTime } from "./paper-terminal-display";

export function PaperAccountCostsCard({ workspace }: { workspace: unknown }) {
  let summary: PaperAccountCosts;
  try {
    summary = readPaperAccountCosts(workspace);
  } catch {
    return (
      <p
        role="alert"
        className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900 dark:border-red-900 dark:bg-red-950/40 dark:text-red-100"
      >
        成本与费用汇总暂不可用，请刷新账本核对。
      </p>
    );
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>成本与费用</CardTitle>
        <CardDescription>按当前服务端工作区汇总，不代表行情市值或收益。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {summary.degraded ? (
          <p role="alert" className="text-sm text-amber-800 dark:text-amber-200">
            账本标记异常，请先核对后再使用此汇总。
          </p>
        ) : null}
        <dl className="grid gap-4 sm:grid-cols-3">
          {[
            ["持仓成本合计", `${summary.positionCost} CNY`],
            ["累计模拟手续费", `${summary.paidFees} CNY`],
            ["有成交订单", `${summary.filledOrderCount} 笔`],
          ].map(([label, value]) => (
            <div key={label} className="min-w-0 space-y-2 rounded-lg border p-4">
              <dt className="text-sm text-muted-foreground">{label}</dt>
              <dd className="break-all font-mono text-xl font-semibold">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="text-xs text-muted-foreground">
          持仓成本含相应买入费用，请勿重复相加。累计手续费取所有订单已有成交的费用；部分成交后取消的订单也计入，不含未发生的费用。
        </p>
        <p className="text-xs text-muted-foreground">
          工作区快照时间：
          <time dateTime={summary.generatedAt}>{formatPaperLedgerTime(summary.generatedAt)}</time>
          。有成交订单数不等于成交回报条数。
        </p>
      </CardContent>
    </Card>
  );
}
