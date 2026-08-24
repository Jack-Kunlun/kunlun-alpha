import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { MarketEmotionSnapshot, SectorRotationEvent } from "./types";

interface MarketRegimeTimelineProps {
  snapshots: MarketEmotionSnapshot[];
  events: SectorRotationEvent[];
}

function percent(value: number): string {
  return (value * 100).toFixed(0) + "%";
}

export function MarketRegimeTimeline({ snapshots, events }: MarketRegimeTimelineProps) {
  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <div>
          <h2 className="text-lg font-semibold">市场情绪分钟回放</h2>
          <p className="text-sm text-muted-foreground">
            每条快照独立展示算法版本、样本、时效和证据置信度
          </p>
        </div>
        <Table aria-label="市场情绪分钟回放">
          <TableHeader>
            <TableRow>
              <TableHead>时间</TableHead>
              <TableHead>情绪分</TableHead>
              <TableHead>梯队</TableHead>
              <TableHead>样本</TableHead>
              <TableHead>时效</TableHead>
              <TableHead>置信度</TableHead>
              <TableHead>版本</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {snapshots.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground">
                  该条件下暂无情绪快照
                </TableCell>
              </TableRow>
            ) : (
              snapshots.map((snapshot) => (
                <TableRow key={snapshot.timestamp + ":" + snapshot.algorithmVersion}>
                  <TableCell>{snapshot.timestamp}</TableCell>
                  <TableCell>{snapshot.score.toFixed(3)}</TableCell>
                  <TableCell>
                    {snapshot.ladder.map((item) => item.board + "板×" + item.count).join("、") ||
                      "—"}
                  </TableCell>
                  <TableCell>{snapshot.sampleSize}</TableCell>
                  <TableCell>{snapshot.freshnessSeconds}s</TableCell>
                  <TableCell>{percent(snapshot.confidence)}</TableCell>
                  <TableCell>{snapshot.algorithmVersion}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-lg font-semibold">板块轮动事件</h2>
          <p className="text-sm text-muted-foreground">事件身份稳定，证据窗口可用于重叠回放去重</p>
        </div>
        <Table aria-label="板块轮动事件">
          <TableHeader>
            <TableRow>
              <TableHead>时间</TableHead>
              <TableHead>类型</TableHead>
              <TableHead>方向</TableHead>
              <TableHead>证据窗口</TableHead>
              <TableHead>样本</TableHead>
              <TableHead>置信度</TableHead>
              <TableHead>版本</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground">
                  该条件下暂无轮动事件
                </TableCell>
              </TableRow>
            ) : (
              events.map((event) => (
                <TableRow key={event.eventId}>
                  <TableCell>{event.timestamp}</TableCell>
                  <TableCell>{event.eventType}</TableCell>
                  <TableCell>
                    {event.fromSector ?? "—"} → {event.toSector}
                  </TableCell>
                  <TableCell>
                    {event.evidenceStart} 至 {event.evidenceEnd}
                  </TableCell>
                  <TableCell>{event.sampleSize}</TableCell>
                  <TableCell>{percent(event.confidence)}</TableCell>
                  <TableCell>{event.algorithmVersion}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </section>
    </div>
  );
}
