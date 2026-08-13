import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export interface LadderEntry {
  board: number;
  count: number;
}

export interface EmotionSnapshot {
  date: string;
  timestamp: string;
  score: number;
  version: string;
  ladder: LadderEntry[];
}

interface MarketRegimeTimelineProps {
  snapshots: EmotionSnapshot[];
}

/**
 * Market regime replay timeline.
 *
 * Shows the minute-by-minute emotion score for a trading day together with
 * the algorithm version that produced it, so historical replay and real-time
 * share the same口径.
 */
export function MarketRegimeTimeline({ snapshots }: MarketRegimeTimelineProps) {
  const version = snapshots[0]?.version ?? "unknown";

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">市场情绪时间轴</h2>
      <p className="text-sm text-muted-foreground">算法版本：{version}</p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>时间</TableHead>
            <TableHead>情绪分</TableHead>
            <TableHead>梯队</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {snapshots.length === 0 ? (
            <TableRow>
              <TableCell colSpan={3} className="text-center text-muted-foreground">
                该交易日暂无快照
              </TableCell>
            </TableRow>
          ) : (
            snapshots.map((snapshot) => (
              <TableRow key={snapshot.timestamp}>
                <TableCell>{snapshot.timestamp}</TableCell>
                <TableCell>{snapshot.score.toFixed(3)}</TableCell>
                <TableCell>
                  {snapshot.ladder.map((l) => `${l.board}板×${l.count}`).join("、") || "—"}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
