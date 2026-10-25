import { useId, useMemo, useState } from "react";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatPaperLedgerTime } from "./paper-terminal-display";
import {
  downloadPaperReconciliationExport,
  preparePaperReconciliationExport,
} from "./paper-reconciliation-export";

export function PaperReconciliationExportButton({
  report,
  accountId,
  basis,
  pending = false,
  disabled = false,
  checkError = null,
}: {
  report: unknown;
  accountId: string;
  basis: string;
  pending?: boolean;
  disabled?: boolean;
  checkError?: string | null;
}) {
  const scopeId = useId();
  const [notice, setNotice] = useState<{ report: unknown; error: boolean; text: string } | null>(
    null,
  );
  const prepared = useMemo(() => {
    if (report === null) return null;
    try {
      return preparePaperReconciliationExport(report, accountId, basis);
    } catch {
      return null;
    }
  }, [report, accountId, basis]);
  const available = prepared !== null && !pending && !disabled && checkError === null;
  const currentNotice = available && notice?.report === report ? notice : null;
  function download() {
    if (!available || prepared === null) return;
    try {
      downloadPaperReconciliationExport(prepared);
      setNotice({ report, error: false, text: "已生成核对报告，浏览器将开始下载。" });
    } catch {
      setNotice({ report, error: true, text: "无法生成或启动报告下载，请重试。" });
    }
  }
  return (
    <div className="space-y-2 border-t pt-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-label="下载核对报告 JSON"
          aria-describedby={scopeId}
          disabled={!available}
          className="cursor-pointer disabled:cursor-not-allowed"
          onClick={download}
        >
          <Download aria-hidden="true" />
          {currentNotice?.error ? "重试下载报告" : "下载核对报告"}
        </Button>
        <p id={scopeId} className="text-xs text-muted-foreground">
          {pending
            ? "正在重新核对，完成后可下载。"
            : checkError !== null
              ? "本次核对失败，请重新核对成功后下载。"
              : disabled
                ? "账本操作进行中，暂不可下载。"
                : prepared === null
                  ? "核对成功后可下载完整 JSON 报告。"
                  : "JSON 保留报告中的金额文本、核对时间、差异及账簿摘要，供本地留档复核。"}
        </p>
      </div>
      {currentNotice !== null ? (
        <p
          role={currentNotice.error ? "alert" : "status"}
          className={`text-xs ${currentNotice.error ? "text-destructive" : "text-muted-foreground"}`}
        >
          {currentNotice.text}
        </p>
      ) : null}
      {available &&
      typeof report === "object" &&
      report !== null &&
      "asOf" in report &&
      typeof report.asOf === "string" ? (
        <p className="text-xs text-muted-foreground">
          下载内容对应核对时间：
          <time dateTime={report.asOf}>{formatPaperLedgerTime(report.asOf)}</time>
          ；不包含完整账户流水，也不用于恢复账本。
        </p>
      ) : null}
    </div>
  );
}
