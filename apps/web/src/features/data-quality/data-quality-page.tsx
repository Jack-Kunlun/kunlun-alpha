import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DataQualityPanel } from "./data-quality-panel";
import { useDataQuality, type DataQualityFilters } from "./use-data-quality";
import { MarketCoveragePanel } from "./market-coverage-panel";
import { useMarketCoverage } from "./use-market-coverage";
import { MarketQualityEvidencePanel } from "./market-quality-evidence-panel";
import {
  useMarketQualityEvidence,
  type MarketQualityEvidenceFilters,
} from "./use-market-quality-evidence";

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
    <div className="grid gap-2">
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
  const [marketStatusDraft, setMarketStatusDraft] = useState("");
  const [marketStatusApplied, setMarketStatusApplied] = useState("");
  const [marketEvidenceOffset, setMarketEvidenceOffset] = useState(0);
  const [marketEvidenceSnapshotId, setMarketEvidenceSnapshotId] = useState<string | null>(null);
  const result = useDataQuality(applied);
  const coverageResult = useMarketCoverage(applied);
  const marketEvidenceFilters: MarketQualityEvidenceFilters = {
    date: applied.date,
    source: applied.source,
    unifiedCode: applied.unifiedCode,
    status: marketStatusApplied || undefined,
  };
  const marketEvidenceResult = useMarketQualityEvidence(marketEvidenceFilters, {
    snapshotId: marketEvidenceSnapshotId,
    offset: marketEvidenceOffset,
    limit: 20,
  });

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setApplied({ ...draft });
    setMarketStatusApplied(marketStatusDraft);
    setMarketEvidenceOffset(0);
    setMarketEvidenceSnapshotId(null);
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
        <FilterField
          id="dq-market-status"
          label="行情证据状态"
          value={marketStatusDraft}
          onChange={setMarketStatusDraft}
          placeholder="REJECTED / FILTERED"
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
            本列表仅展示基金质量事件；行情拒绝证据已在下方独立区块按公开快照展示，缺口分析与全市场覆盖不在本页范围内。
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
            当前仅接入已观测到的日线数据；行情质量证据在下方独立区块展示，缺口分析、来源差异与全市场覆盖不在本区块内。
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

      <section aria-labelledby="market-quality-evidence-heading" className="space-y-3">
        <div>
          <h3 id="market-quality-evidence-heading" className="text-lg font-semibold">
            行情质量证据
          </h3>
          <p className="text-sm text-muted-foreground">
            仅展示已发布的脱敏 REJECTED/FILTERED
            证据快照，不读取原始行情文件，也不宣称没有质量问题或全市场覆盖完整。
            日期筛选按证据请求窗口与输入日期是否相交；翻页固定在同一 snapshotId。
          </p>
        </div>
        <MarketQualityEvidencePanel
          result={marketEvidenceResult}
          onPrevious={() => setMarketEvidenceOffset((value) => Math.max(0, value - 20))}
          onNext={() => {
            const page = marketEvidenceResult.data;
            if (page?.hasMore) {
              setMarketEvidenceSnapshotId(page.snapshotId);
              setMarketEvidenceOffset(page.offset + page.limit);
            }
          }}
        />
      </section>
    </div>
  );
}
