import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DataQualityPanel } from "./data-quality-panel";
import { useDataQuality, type DataQualityFilters } from "./use-data-quality";

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

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setApplied({ ...draft });
  };

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">数据质量</h1>
        <p className="text-sm text-muted-foreground">
          按交易日、来源、证券（如 600519.SH）定位数据质量问题
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
          label="来源"
          value={draft.source ?? ""}
          onChange={(value) => setDraft((prev) => ({ ...prev, source: value }))}
          placeholder="provider-a"
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

      {result.status === "loading" && (
        <p role="status" className="text-muted-foreground">
          加载中…
        </p>
      )}
      {result.status === "empty" && (
        <p className="text-muted-foreground">暂无质量问题</p>
      )}
      {result.status === "error" && (
        <p role="alert" className="text-destructive">
          加载失败：{result.error?.message}
        </p>
      )}
      {result.status === "forbidden" && (
        <p role="alert" className="text-destructive">
          无权访问数据质量
        </p>
      )}
      {result.status === "success" && result.data !== null && (
        <DataQualityPanel records={result.data} />
      )}
    </div>
  );
}
