import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { DataQualityRecord } from "./types";
import { evidenceUrl } from "./use-data-quality";

interface DataQualityPanelProps {
  records: DataQualityRecord[];
}

/**
 * Data quality table.
 *
 * Shows every record's detail — kind, trading date, source, instrument, reason,
 * freshness and algorithm/schema version — and links evidence only through the
 * safe internal endpoint. It deliberately lists every anomaly rather than only
 * aggregate totals.
 */
export function DataQualityPanel({ records }: DataQualityPanelProps) {
  return (
    <Table aria-label="数据质量事件列表">
      <TableHeader>
        <TableRow>
          <TableHead>类型</TableHead>
          <TableHead>日期</TableHead>
          <TableHead>来源</TableHead>
          <TableHead>证券</TableHead>
          <TableHead>明细</TableHead>
          <TableHead>版本</TableHead>
          <TableHead>证据</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {records.map((record) => (
          <TableRow key={record.id}>
            <TableCell>{record.kind}</TableCell>
            <TableCell>{record.date}</TableCell>
            <TableCell>{record.source ?? "—"}</TableCell>
            <TableCell>{record.unifiedCode ?? "—"}</TableCell>
            <TableCell>{record.detail}</TableCell>
            <TableCell>{record.schemaVersion}</TableCell>
            <TableCell>
              <a href={evidenceUrl(record.id)} className="underline">
                查看
              </a>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
