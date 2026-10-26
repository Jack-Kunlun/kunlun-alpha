import { useEffect, useState, type FormEvent } from "react";
import type { MarketQualityStatus } from "@kunlun/shared-types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { MarketCoveragePanel } from "./market-coverage-panel";
import {
  MARKET_COVERAGE_SOURCES,
  validateDataQualityFilters,
  type DataQualityFilterDraft,
  type DataQualityFilterErrors,
} from "./data-quality-filters";
import { useMarketCoverage } from "./use-market-coverage";
import { MarketQualityEvidencePanel } from "./market-quality-evidence-panel";
import {
  useMarketQualityEvidence,
  type MarketQualityEvidenceFilters,
} from "./use-market-quality-evidence";
import type { DataQualityFilters } from "./use-data-quality";

const selectClassName =
  "h-9 w-full min-w-40 rounded-md border border-input bg-transparent px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30";

function FilterError({ id, message }: { id: string; message: string | undefined }) {
  if (message === undefined) return null;
  return (
    <p id={`${id}-error`} role="alert" className="text-xs text-destructive">
      {message}
    </p>
  );
}

function DataQualityResults({
  filters,
  status,
  onLoadingChange,
  activeTab,
}: {
  filters: DataQualityFilters;
  status: MarketQualityStatus | undefined;
  onLoadingChange: (loading: boolean) => void;
  activeTab: string;
}) {
  const coverageResult = useMarketCoverage(filters);
  const marketEvidenceFilters: MarketQualityEvidenceFilters = {
    date: filters.date,
    source: filters.source,
    unifiedCode: filters.unifiedCode,
    status,
  };
  const [marketEvidenceOffset, setMarketEvidenceOffset] = useState(0);
  const [marketEvidenceSnapshotId, setMarketEvidenceSnapshotId] = useState<string | null>(null);
  const marketEvidenceResult = useMarketQualityEvidence(marketEvidenceFilters, {
    snapshotId: marketEvidenceSnapshotId,
    offset: marketEvidenceOffset,
    limit: 20,
  });

  useEffect(() => {
    onLoadingChange(
      coverageResult.status === "loading" || marketEvidenceResult.status === "loading",
    );
  }, [coverageResult.status, marketEvidenceResult.status, onLoadingChange]);

  return (
    <div
      className="space-y-6"
      aria-busy={coverageResult.status === "loading" || marketEvidenceResult.status === "loading"}
    >
      <TabsContent
        value="coverage"
        forceMount
        hidden={activeTab !== "coverage"}
        className="space-y-3"
      >
        <div>
          <h3 id="market-coverage-heading" className="text-lg font-semibold">
            日线入库概览
          </h3>
          <p className="text-sm text-muted-foreground">
            覆盖日期精确匹配交易日；日期明细单独按当前查询时刻读取，不构成共同快照。
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
        {coverageResult.status === "empty" && (
          <p className="text-muted-foreground">当前条件下暂无已观测到的日线行情</p>
        )}
        {coverageResult.status === "success" && coverageResult.data !== null && (
          <MarketCoveragePanel response={coverageResult.data} />
        )}
      </TabsContent>

      <TabsContent
        value="evidence"
        forceMount
        hidden={activeTab !== "evidence"}
        className="space-y-3"
      >
        <div>
          <h3 id="market-quality-evidence-heading" className="text-lg font-semibold">
            行情质量证据
          </h3>
          <p className="text-sm text-muted-foreground">
            仅展示已发布的脱敏 REJECTED/FILTERED
            证据快照，不读取原始行情文件。日期筛选按证据请求窗口与输入日期是否相交；查询翻页固定在同一
            snapshotId。
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
      </TabsContent>
    </div>
  );
}

function emptyDraft(): DataQualityFilterDraft {
  return { date: "", source: "", unifiedCode: "", status: "" };
}

export function DataQualityPage() {
  const [draft, setDraft] = useState<DataQualityFilterDraft>(emptyDraft);
  const [applied, setApplied] = useState<DataQualityFilters>({});
  const [statusApplied, setStatusApplied] = useState<MarketQualityStatus | undefined>(undefined);
  const [filterErrors, setFilterErrors] = useState<DataQualityFilterErrors>({});
  const [queryGeneration, setQueryGeneration] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("coverage");

  const updateDraft = (key: keyof DataQualityFilterDraft, value: string) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setFilterErrors((current) => ({ ...current, [key]: undefined }));
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const validation = validateDataQualityFilters(draft);
    if (!validation.ok) {
      setFilterErrors(validation.errors);
      return;
    }
    setFilterErrors({});
    setApplied(validation.filters);
    setStatusApplied(validation.status);
    setIsLoading(true);
    setQueryGeneration((value) => value + 1);
  };

  const reset = () => {
    setDraft(emptyDraft());
    setFilterErrors({});
    setApplied({});
    setStatusApplied(undefined);
    setIsLoading(true);
    setQueryGeneration((value) => value + 1);
  };

  const fieldErrorProps = (id: string, message: string | undefined) => ({
    "aria-invalid": message !== undefined,
    "aria-describedby": message === undefined ? undefined : `${id}-error`,
  });

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold tracking-tight">数据质量</h2>
        <p className="text-sm text-muted-foreground">
          按日期、来源、证券查看日线覆盖与已发布行情异常证据。
        </p>
      </header>

      <form onSubmit={submit} className="flex flex-wrap items-end gap-4" autoComplete="off">
        <div className="grid min-w-40 gap-2">
          <Label htmlFor="dq-date">日期</Label>
          <Input
            id="dq-date"
            type="date"
            value={draft.date}
            onChange={(event) => updateDraft("date", event.target.value)}
            className="w-40 cursor-text dark:[color-scheme:dark] [&::-webkit-calendar-picker-indicator]:cursor-pointer"
            {...fieldErrorProps("dq-date", filterErrors.date)}
          />
          <FilterError id="dq-date" message={filterErrors.date} />
        </div>
        <div className="grid min-w-40 gap-2">
          <Label htmlFor="dq-source">来源</Label>
          <select
            id="dq-source"
            value={draft.source}
            onChange={(event) => updateDraft("source", event.target.value)}
            className={selectClassName}
            {...fieldErrorProps("dq-source", filterErrors.source)}
          >
            <option value="">全部来源</option>
            {MARKET_COVERAGE_SOURCES.map((source) => (
              <option key={source} value={source}>
                {source}
              </option>
            ))}
          </select>
          <FilterError id="dq-source" message={filterErrors.source} />
        </div>
        <div className="grid min-w-40 gap-2">
          <Label htmlFor="dq-code">证券</Label>
          <Input
            id="dq-code"
            value={draft.unifiedCode}
            onChange={(event) => updateDraft("unifiedCode", event.target.value)}
            placeholder="600519.SH"
            className="w-40 font-mono"
            {...fieldErrorProps("dq-code", filterErrors.unifiedCode)}
          />
          <FilterError id="dq-code" message={filterErrors.unifiedCode} />
        </div>
        <div className="grid min-w-40 gap-2">
          <Label htmlFor="dq-evidence-status">证据状态</Label>
          <select
            id="dq-evidence-status"
            value={draft.status}
            onChange={(event) => updateDraft("status", event.target.value)}
            className={selectClassName}
            {...fieldErrorProps("dq-evidence-status", filterErrors.status)}
          >
            <option value="">全部异常状态</option>
            <option value="REJECTED">REJECTED</option>
            <option value="FILTERED">FILTERED</option>
          </select>
          <FilterError id="dq-evidence-status" message={filterErrors.status} />
        </div>
        <div className="flex gap-2">
          <Button
            type="submit"
            disabled={isLoading}
            aria-busy={isLoading}
            className="cursor-pointer disabled:cursor-progress"
          >
            {isLoading ? "查询中…" : "查询"}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={reset}
            className="cursor-pointer disabled:cursor-not-allowed"
          >
            重置
          </Button>
        </div>
      </form>
      <div className="space-y-1 text-xs text-muted-foreground">
        <p>本页按当前查询时间读取，不使用全局历史点时；证据以快照发布时间为准。</p>
        <p>覆盖日期按交易日精确筛选；行情证据日期按请求窗口与输入日期是否相交筛选。</p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList aria-label="数据质量视图">
          <TabsTrigger value="coverage">日线入库概览</TabsTrigger>
          <TabsTrigger value="evidence">行情质量证据</TabsTrigger>
        </TabsList>
        <DataQualityResults
          key={queryGeneration}
          filters={applied}
          status={statusApplied}
          onLoadingChange={setIsLoading}
          activeTab={activeTab}
        />
      </Tabs>
    </div>
  );
}
