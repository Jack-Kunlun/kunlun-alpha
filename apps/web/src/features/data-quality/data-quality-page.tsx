import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DataQualityPanel } from "./data-quality-panel";
import { useDataQuality, type DataQualityFilters } from "./use-data-quality";
import { MarketCoveragePanel } from "./market-coverage-panel";
import { useMarketCoverage } from "./use-market-coverage";

function FilterField({
  id,
  label,
  value,
  onChange,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="w-40"
      />
    </div>
  );
}

/**
 * Data-quality page: a real route that reads persisted quality events through
 * the shared API client and renders explicit loading / empty / error /
 * forbidden / success states.
 */
export function DataQualityPage() {
  const [draft, setDraft] = useState<DataQualityFilters>({});
  const [applied, setApplied] = useState<DataQualityFilters>({});
  const result = useDataQuality(applied);
  const coverageResult = useMarketCoverage(applied);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setApplied({ ...draft });
  };

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-xl font-semibold">数据质量</h2>
        <p className="text-sm text-muted-foreground">
          按交易日、来源、证券（如 600519.SH）查看已记录的基金质量事件与日线行情观测
        </p>
      </header>

      <form onSubmit={submit} className="flex flex-wrap items-end gap-4">
        <FilterField
          id="dq-date"
          label="日期"
          value={draft.date ?? ""}
          onChange={(value) => setDraft((prev) => ({ ...prev, date: value }))}
          placeholder="2026-08-13"
        />
        <FilterField
          id="dq-source"
          label="来源（覆盖支持）"
          value={draft.source ?? ""}
          onChange={(value) => setDraft((prev) => ({ ...prev, source: value }))}
          placeholder="akshare-tencent"
        />
        <FilterField
          id="dq-code"
          label="证券"
          value={draft.unifiedCode ?? ""}
          onChange={(value) => setDraft((prev) => ({ ...prev, unifiedCode: value }))}
          placeholder="600519.SH"
        />
        <Button type="submit">查询</Button>
      </form>
      <p className="text-xs text-muted-foreground">
        行情覆盖支持
        tushare-pro、akshare-tencent、akshare-sina、akshare-eastmoney；基金质量事件仍按其记录来源筛选。
      </p>

      <section aria-labelledby="fund-quality-events-heading" className="space-y-3">
        <div>
          <h3 id="fund-quality-events-heading" className="text-lg font-semibold">
            基金质量事件
          </h3>
          <p className="text-sm text-muted-foreground">
            仅展示已记录的异常事件；行情拒绝、缺口与全市场覆盖尚未接入此列表。
          </p>
        </div>
        {result.status === "loading" && (
          <p role="status" className="text-muted-foreground">
            基金质量事件加载中…
          </p>
        )}
        {result.status === "empty" && (
          <p className="text-muted-foreground">当前条件下暂无已记录的基金质量事件</p>
        )}
        {result.status === "error" && (
          <p role="alert" className="text-destructive">
            基金质量事件加载失败，请稍后重试
          </p>
        )}
        {result.status === "forbidden" && (
          <p role="alert" className="text-destructive">
            无权访问基金质量事件
          </p>
        )}
        {result.status === "success" && result.data !== null && (
          <DataQualityPanel records={result.data} />
        )}
      </section>

      <section aria-labelledby="market-coverage-heading" className="space-y-3">
        <div>
          <h3 id="market-coverage-heading" className="text-lg font-semibold">
            日线入库概览
          </h3>
          <p className="text-sm text-muted-foreground">
            当前仅接入已观测到的日线数据；行情拒绝证据、缺口分析、来源差异与全市场覆盖仍未接入。
          </p>
        </div>
        {coverageResult.status === "loading" && (
          <p role="status" className="text-muted-foreground">
            日线行情覆盖加载中…
          </p>
        )}
        {coverageResult.status === "error" && (
          <p role="alert" className="text-destructive">
            日线行情覆盖加载失败，请稍后重试
          </p>
        )}
        {coverageResult.status === "forbidden" && (
          <p role="alert" className="text-destructive">
            无权访问日线行情覆盖
          </p>
        )}
        {coverageResult.status === "success" && coverageResult.data !== null && (
          <MarketCoveragePanel response={coverageResult.data} />
        )}
      </section>
    </div>
  );
}
