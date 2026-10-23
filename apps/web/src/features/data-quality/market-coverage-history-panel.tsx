import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { MarketCoverageDaysSelection } from "./market-coverage-days";
import { MarketCoverageDaysPanel } from "./market-coverage-days-panel";
import {
  validateMarketCoverageHistoryWindow,
  type MarketCoverageHistoryErrors,
  type MarketCoverageHistoryWindow,
} from "./market-coverage-history";
import { useMarketCoverageDays } from "./use-market-coverage-days";

function HistoryResults({
  selection,
  onLoadingChange,
}: {
  selection: MarketCoverageDaysSelection;
  onLoadingChange: (loading: boolean) => void;
}) {
  const result = useMarketCoverageDays(selection);
  useEffect(() => {
    onLoadingChange(result.status === "loading");
  }, [result.status, onLoadingChange]);
  return <MarketCoverageDaysPanel result={result} selection={selection} />;
}

export function MarketCoverageHistoryPanel({
  selection,
}: {
  selection: MarketCoverageDaysSelection;
}) {
  const initialWindow = { dateFrom: selection.dateFrom, dateTo: selection.dateTo };
  const [draft, setDraft] = useState<MarketCoverageHistoryWindow>(initialWindow);
  const [applied, setApplied] = useState<MarketCoverageHistoryWindow>(initialWindow);
  const [errors, setErrors] = useState<MarketCoverageHistoryErrors>({});
  const [generation, setGeneration] = useState(0);
  const [isLoading, setIsLoading] = useState(true);

  const apply = (window: MarketCoverageHistoryWindow) => {
    setApplied(window);
    setDraft(window);
    setErrors({});
    setIsLoading(true);
    setGeneration((value) => value + 1);
  };
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isLoading) return;
    const validation = validateMarketCoverageHistoryWindow(draft);
    if (!validation.ok) {
      setErrors(validation.errors);
      return;
    }
    apply(validation.window);
  };
  const update = (key: keyof MarketCoverageHistoryWindow, value: string) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setErrors({});
  };

  return (
    <section aria-label="日线历史窗口检索" className="space-y-3 rounded-md border p-3">
      <div className="space-y-1">
        <h4 className="font-semibold">已入库日期 · {selection.unifiedCode}</h4>
        <p className="text-sm text-muted-foreground">来源：{selection.source}</p>
        <p id="dq-history-window-hint" className="text-sm text-muted-foreground">
          选择历史窗口（含起止日，最多 366 个自然日）。此处筛选只作用于该证券与来源的日期明细。
        </p>
      </div>
      <form
        onSubmit={submit}
        noValidate
        className="flex flex-wrap items-end gap-4"
        autoComplete="off"
      >
        {(["dateFrom", "dateTo"] as const).map((key) => {
          const id = key === "dateFrom" ? "dq-history-date-from" : "dq-history-date-to";
          return (
            <div key={key} className="grid min-w-40 gap-2">
              <Label htmlFor={id}>{key === "dateFrom" ? "开始日期" : "结束日期"}</Label>
              <Input
                id={id}
                type="date"
                value={draft[key]}
                onChange={(event) => update(key, event.target.value)}
                aria-invalid={errors[key] !== undefined}
                aria-describedby={
                  errors[key] === undefined ? "dq-history-window-hint" : `${id}-error`
                }
                className="w-40 cursor-text dark:[color-scheme:dark] [&::-webkit-calendar-picker-indicator]:cursor-pointer"
              />
              {errors[key] !== undefined && (
                <p id={`${id}-error`} role="alert" className="text-xs text-destructive">
                  {errors[key]}
                </p>
              )}
            </div>
          );
        })}
        <div className="flex flex-wrap gap-2">
          <Button
            type="submit"
            disabled={isLoading}
            aria-busy={isLoading}
            className={isLoading ? "disabled:cursor-progress" : undefined}
          >
            {isLoading ? "查询中…" : "查询日期"}
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={isLoading}
            onClick={() => apply(initialWindow)}
          >
            恢复汇总窗口
          </Button>
        </div>
      </form>
      <p className="text-sm text-muted-foreground">
        当前明细窗口：{applied.dateFrom} 至 {applied.dateTo}
      </p>
      <div aria-busy={isLoading}>
        <HistoryResults
          key={generation}
          selection={{ ...selection, ...applied }}
          onLoadingChange={setIsLoading}
        />
      </div>
    </section>
  );
}
