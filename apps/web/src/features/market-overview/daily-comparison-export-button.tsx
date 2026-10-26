import { useId, useMemo, useState } from "react";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { downloadJsonFile } from "@/lib/download-json";
import type { DailyComparison, DailyComparisonSort } from "./daily-comparison";
import { prepareDailyComparisonSnapshot } from "./daily-comparison-export";

export function DailyComparisonExportButton({
  comparison,
  expectedAsOf,
  sort,
}: {
  comparison: DailyComparison | null;
  expectedAsOf: string | undefined;
  sort: DailyComparisonSort;
}) {
  const scopeId = useId();
  const prepared = useMemo(() => {
    if (comparison === null || expectedAsOf === undefined) return null;
    try {
      return prepareDailyComparisonSnapshot(comparison, expectedAsOf, sort);
    } catch {
      return null;
    }
  }, [comparison, expectedAsOf, sort]);
  const [notice, setNotice] = useState<{
    comparison: DailyComparison;
    key: string;
    error: boolean;
    text: string;
  } | null>(null);
  const key = `${sort.key}|${sort.direction}`;
  const currentNotice =
    prepared !== null && notice?.comparison === comparison && notice.key === key ? notice : null;
  function download() {
    if (prepared === null || comparison === null) return;
    try {
      downloadJsonFile(prepared);
      setNotice({ comparison, key, error: false, text: "已生成对比快照，浏览器将开始下载。" });
    } catch {
      setNotice({
        comparison,
        key,
        error: true,
        text: "无法启动快照下载，请重试；当前对比结果已保留。",
      });
    }
  }
  return (
    <div className="space-y-2 py-2">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          size="sm"
          variant="outline"
          aria-label="下载本次对比 JSON"
          aria-describedby={scopeId}
          disabled={prepared === null}
          onClick={download}
          className="cursor-pointer disabled:cursor-not-allowed"
        >
          <Download aria-hidden="true" />
          {currentNotice?.error ? "重试下载快照" : "下载本次对比"}
        </Button>
        <p id={scopeId} className="text-xs text-muted-foreground">
          {prepared === null
            ? "本次查询完成并通过校验后可下载。"
            : `JSON 保留本次 ${prepared.sampleCount} 项、当前排序、固定点时、原始数值、状态及来源；仅下载当前结果。`}
        </p>
      </div>
      {currentNotice !== null ? (
        <p
          role={currentNotice.error ? "alert" : "status"}
          className={
            currentNotice.error ? "text-xs text-destructive" : "text-xs text-muted-foreground"
          }
        >
          {currentNotice.text}
        </p>
      ) : null}
    </div>
  );
}
