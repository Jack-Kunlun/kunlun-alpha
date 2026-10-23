import { useMemo, useState } from "react";
import type { InstrumentBarsResponse } from "@kunlun/shared-types";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { prepareInstrumentBarsCsv } from "./instrument-bars-export";

export function InstrumentBarsExportButton({
  data,
  instrumentId,
  mode,
  asOf,
}: {
  data: InstrumentBarsResponse;
  instrumentId: string;
  mode: InstrumentBarsResponse["mode"];
  asOf: string;
}) {
  const [notice, setNotice] = useState<{
    data: InstrumentBarsResponse;
    error: boolean;
    message: string;
  } | null>(null);
  const prepared = useMemo(() => {
    if (
      data.instrumentId !== instrumentId ||
      data.mode !== mode ||
      (mode === "HISTORICAL" && data.requestedAsOf !== asOf)
    ) {
      return { value: null, error: "日线与当前查询不一致，暂不可导出。" };
    }
    try {
      return { value: prepareInstrumentBarsCsv(data), error: null };
    } catch (cause) {
      return {
        value: null,
        error: `暂不可导出：${cause instanceof Error ? cause.message : "日线数据不可用"}`,
      };
    }
  }, [data, instrumentId, mode, asOf]);

  function download() {
    if (prepared.value === null) return;
    let url: string | null = null;
    let anchor: HTMLAnchorElement | null = null;
    try {
      url = URL.createObjectURL(new Blob([prepared.value.csv], { type: "text/csv;charset=utf-8" }));
      anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = prepared.value.filename;
      anchor.hidden = true;
      document.body.append(anchor);
      anchor.click();
      setNotice({
        data,
        error: false,
        message: `已生成 ${prepared.value.barCount} 根日线的 CSV，浏览器将开始下载。`,
      });
    } catch {
      setNotice({ data, error: true, message: "无法生成或启动 CSV 下载，请重试。" });
    } finally {
      anchor?.remove();
      if (url !== null) URL.revokeObjectURL(url);
    }
  }

  return (
    <div className="space-y-2 pt-2">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-label="导出当前窗口 CSV"
          aria-describedby="instrument-bars-export-scope"
          disabled={prepared.value === null}
          onClick={download}
        >
          <Download aria-hidden="true" /> 导出当前窗口
        </Button>
        <p id="instrument-bars-export-scope" className="text-xs text-muted-foreground">
          仅导出本次返回的 {data.barCount} 根日线，保留 RAW 价格、日期、来源与查询点时。
        </p>
      </div>
      {prepared.error !== null ? (
        <p role="alert" className="text-xs text-destructive">
          {prepared.error}
        </p>
      ) : null}
      {prepared.value !== null && notice?.data === data ? (
        <p
          role={notice.error ? "alert" : "status"}
          className={notice.error ? "text-xs text-destructive" : "text-xs text-muted-foreground"}
        >
          {notice.message}
        </p>
      ) : null}
    </div>
  );
}
