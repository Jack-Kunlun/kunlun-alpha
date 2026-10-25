import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatPaperLedgerTime } from "./paper-terminal-display";
import type { PaperRiskView } from "./paper-risk-preview";

export function PaperRiskPreviewPanel({ risk }: { risk: PaperRiskView }) {
  return (
    <section aria-label="模拟风险检查结果" className="min-w-0 space-y-3 border-t pt-4">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="font-semibold">模拟风险检查</h3>
        <Badge variant="destructive">存在阻断</Badge>
      </div>
      <p className="text-sm text-muted-foreground">
        风险口径 {risk.policyVersion} ·{" "}
        <time dateTime={risk.time}>{formatPaperLedgerTime(risk.time)}</time>
      </p>
      <p className="text-sm">
        模拟执行入口尚未开放。检查结果不构成交易许可，不提交订单，也不改变账本。
      </p>
      <div
        role="region"
        aria-label="逐项风险检查，可横向滚动"
        tabIndex={0}
        className="min-w-0 overflow-x-auto rounded-md border focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none [&>[data-slot=table-container]]:overflow-visible"
      >
        <Table className="min-w-[640px]">
          <TableHeader>
            <TableRow>
              <TableHead>检查项</TableHead>
              <TableHead>本次值</TableHead>
              <TableHead>约束</TableHead>
              <TableHead>结论</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {risk.rows.map((row) => (
              <TableRow key={row.code}>
                <TableCell>{row.name}</TableCell>
                <TableCell className="max-w-60 font-mono whitespace-normal break-all">
                  {row.actual}
                </TableCell>
                <TableCell className="font-mono">{row.limit}</TableCell>
                <TableCell>
                  <Badge variant={row.passed ? "secondary" : "destructive"}>
                    {row.passed ? "符合" : "阻断"}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}
