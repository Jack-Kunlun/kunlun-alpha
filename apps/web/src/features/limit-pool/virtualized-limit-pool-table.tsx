import type { LimitPoolTerminalEntry } from "@kunlun/shared-types";
import { ArrowDown, ArrowUp, ChevronsUpDown, FileSearch } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export type LimitPoolSortKey =
  "instrumentId" | "name" | "side" | "streakDays" | "openCount" | "firstSealTime";

export interface LimitPoolSort {
  key: LimitPoolSortKey;
  direction: "asc" | "desc";
}

interface Props {
  entries: readonly LimitPoolTerminalEntry[];
  sort: LimitPoolSort;
  onSort(key: LimitPoolSortKey): void;
  onSelect(entry: LimitPoolTerminalEntry): void;
}

const ROW_HEIGHT = 52;
const VIEWPORT_HEIGHT = 520;
const OVERSCAN = 8;

export function virtualWindowFor(
  entryCount: number,
  scrollTop: number,
): { start: number; end: number } {
  const visibleCount = Math.ceil(VIEWPORT_HEIGHT / ROW_HEIGHT);
  const requestedStart = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const maximumStart = Math.max(0, entryCount - visibleCount);
  const start = Math.min(requestedStart, maximumStart);
  return { start, end: Math.min(entryCount, start + visibleCount + OVERSCAN * 2) };
}

function sortIcon(active: boolean, direction: LimitPoolSort["direction"]) {
  if (!active) return <ChevronsUpDown aria-hidden="true" className="size-3.5 opacity-45" />;
  return direction === "asc" ? (
    <ArrowUp aria-hidden="true" className="size-3.5" />
  ) : (
    <ArrowDown aria-hidden="true" className="size-3.5" />
  );
}

function SortHead({
  label,
  sortKey,
  sort,
  onSort,
}: {
  label: string;
  sortKey: LimitPoolSortKey;
  sort: LimitPoolSort;
  onSort(key: LimitPoolSortKey): void;
}) {
  const active = sort.key === sortKey;
  return (
    <TableHead
      aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}
    >
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="-ml-2 px-2"
        aria-label={`按${label}排序`}
        onClick={() => onSort(sortKey)}
      >
        {label}
        {sortIcon(active, sort.direction)}
      </Button>
    </TableHead>
  );
}

export function VirtualizedLimitPoolTable({ entries, sort, onSort, onSelect }: Props) {
  const [scrollTop, setScrollTop] = useState(0);
  const { start, end } = virtualWindowFor(entries.length, scrollTop);
  const visible = entries.slice(start, end);
  const topHeight = start * ROW_HEIGHT;
  const bottomHeight = Math.max(0, (entries.length - end) * ROW_HEIGHT);

  return (
    <div
      className="h-[520px] overflow-y-auto rounded-xl border bg-background"
      role="region"
      aria-label="涨跌停与连板证券池"
      tabIndex={0}
      onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
    >
      <Table aria-rowcount={entries.length + 1} className="min-w-[960px] table-fixed">
        <TableHeader className="sticky top-0 z-10 bg-background/95 backdrop-blur">
          <TableRow>
            <SortHead label="代码" sortKey="instrumentId" sort={sort} onSort={onSort} />
            <SortHead label="名称" sortKey="name" sort={sort} onSort={onSort} />
            <SortHead label="方向" sortKey="side" sort={sort} onSort={onSort} />
            <SortHead label="连板" sortKey="streakDays" sort={sort} onSort={onSort} />
            <TableHead>状态</TableHead>
            <TableHead>价格</TableHead>
            <SortHead label="开板" sortKey="openCount" sort={sort} onSort={onSort} />
            <SortHead label="首次封板" sortKey="firstSealTime" sort={sort} onSort={onSort} />
            <TableHead className="w-24">证据</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {topHeight > 0 && (
            <TableRow aria-hidden="true" className="border-0 hover:bg-transparent">
              <TableCell colSpan={9} style={{ height: topHeight, padding: 0 }} />
            </TableRow>
          )}
          {visible.map((entry, index) => (
            <TableRow
              key={entry.instrumentId}
              style={{ height: ROW_HEIGHT }}
              data-limit-pool-row="true"
              aria-rowindex={start + index + 2}
            >
              <TableCell className="font-mono text-xs">{entry.instrumentId}</TableCell>
              <TableCell className="truncate font-medium" title={entry.name}>
                {entry.name}
              </TableCell>
              <TableCell
                className={entry.side === "LIMIT_UP" ? "text-red-600" : "text-emerald-600"}
              >
                {entry.side === "LIMIT_UP" ? "涨停" : "跌停"}
              </TableCell>
              <TableCell className="font-mono font-semibold">{entry.streakDays || "-"}</TableCell>
              <TableCell>
                {entry.state === "SEALED" ? "封板" : entry.state === "OPENED" ? "开板" : "跌停"}
              </TableCell>
              <TableCell className="font-mono">{entry.priceCny}</TableCell>
              <TableCell className="font-mono">{entry.openCount}</TableCell>
              <TableCell className="font-mono text-xs">
                {entry.firstSealTime
                  ? new Date(entry.firstSealTime).toLocaleTimeString("zh-CN", {
                      hour12: false,
                      timeZone: "Asia/Shanghai",
                    })
                  : "-"}
              </TableCell>
              <TableCell>
                <Button
                  type="button"
                  size="icon-sm"
                  variant="ghost"
                  aria-label={`查看${entry.name}证据`}
                  onClick={() => onSelect(entry)}
                >
                  <FileSearch aria-hidden="true" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
          {bottomHeight > 0 && (
            <TableRow aria-hidden="true" className="border-0 hover:bg-transparent">
              <TableCell colSpan={9} style={{ height: bottomHeight, padding: 0 }} />
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
