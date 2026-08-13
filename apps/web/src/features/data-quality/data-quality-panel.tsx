import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export interface DataQualityRecord {
  id: string;
  kind: string;
  date: string;
  source: string;
  unifiedCode: string | null;
  detail: string;
  evidenceLink: string;
}

interface DataQualityPanelProps {
  records: DataQualityRecord[];
}

/**
 * Data quality status panel.
 *
 * Shows every record's detail (kind, date, source, instrument and a link to
 * the raw evidence) — deliberately not only aggregate totals, so anomalies
 * can be located and traced to their source.
 */
export function DataQualityPanel({ records }: DataQualityPanelProps) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">数据质量</h2>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>类型</TableHead>
            <TableHead>日期</TableHead>
            <TableHead>来源</TableHead>
            <TableHead>证券</TableHead>
            <TableHead>明细</TableHead>
            <TableHead>原始证据</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {records.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center text-muted-foreground">
                暂无质量问题
              </TableCell>
            </TableRow>
          ) : (
            records.map((record) => (
              <TableRow key={record.id}>
                <TableCell>{record.kind}</TableCell>
                <TableCell>{record.date}</TableCell>
                <TableCell>{record.source}</TableCell>
                <TableCell>{record.unifiedCode ?? "—"}</TableCell>
                <TableCell>{record.detail}</TableCell>
                <TableCell>
                  <a href={record.evidenceLink} className="underline">
                    查看
                  </a>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
