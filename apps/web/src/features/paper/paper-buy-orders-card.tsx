import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { readPaperBuyOrders, type PaperBuyOrderRow } from "./paper-buy-orders";
import { formatPaperLedgerTime } from "./paper-terminal-display";

export function PaperBuyOrdersCard({ workspace }: { workspace: unknown }) {
  let rows: PaperBuyOrderRow[];
  try {
    rows = readPaperBuyOrders(workspace);
  } catch {
    return (
      <p role="alert" className="text-sm text-red-700 dark:text-red-300">
        模拟成交记录不可用，请刷新账本核对。
      </p>
    );
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>模拟订单记录</CardTitle>
        <p className="text-sm text-muted-foreground">
          人工假设价格下的模拟记录，均价与手续费均来自服务端；不代表真实行情或真实成交。
        </p>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无模拟订单</p>
        ) : (
          <div
            role="region"
            aria-label="模拟订单记录，可横向滚动"
            tabIndex={0}
            className="overflow-x-auto rounded-md border focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none [&>[data-slot=table-container]]:overflow-visible"
          >
            <Table className="min-w-[800px]">
              <TableHeader>
                <TableRow>
                  {[
                    "证券",
                    "方向",
                    "状态",
                    "数量",
                    "已成交",
                    "模拟均价（CNY）",
                    "手续费（CNY）",
                    "记录时间",
                  ].map((label) => (
                    <TableHead key={label}>{label}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="font-mono">{row.instrument}</TableCell>
                    <TableCell>{row.side}</TableCell>
                    <TableCell>{row.status}</TableCell>
                    <TableCell>{row.quantity}</TableCell>
                    <TableCell>{row.filled}</TableCell>
                    <TableCell className="font-mono">{row.price ?? "—"}</TableCell>
                    <TableCell className="font-mono">{row.fees}</TableCell>
                    <TableCell>
                      <time dateTime={row.time}>{formatPaperLedgerTime(row.time)}</time>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
