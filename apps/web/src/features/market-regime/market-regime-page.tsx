import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MarketRegimeTimeline } from "./market-regime-timeline";
import {
  useMarketRegime,
  type MarketRegimeFilters,
  type MarketRegimeResult,
} from "./use-market-regime";

function shanghaiToday(): string {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return value.year + "-" + value.month + "-" + value.day;
}

function Field({
  id,
  label,
  value,
  placeholder,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="w-48"
      />
    </div>
  );
}

export function MarketRegimeView({ result }: { result: MarketRegimeResult }) {
  if (result.status === "loading") {
    return (
      <p role="status" className="text-muted-foreground">
        正在加载历史情绪与轮动…
      </p>
    );
  }
  if (result.status === "forbidden") {
    return (
      <p role="alert" className="text-destructive">
        无权访问市场情绪与轮动回放
      </p>
    );
  }
  if (result.status === "error") {
    return (
      <p role="alert" className="text-destructive">
        回放加载失败：{result.error?.message}
      </p>
    );
  }
  if (result.status === "empty" || result.data === null) {
    return <p className="text-muted-foreground">该交易日暂无可回放数据</p>;
  }
  return <MarketRegimeTimeline snapshots={result.data.snapshots} events={result.data.events} />;
}

export function MarketRegimePage() {
  const initial: MarketRegimeFilters = { date: shanghaiToday() };
  const [draft, setDraft] = useState(initial);
  const [applied, setApplied] = useState(initial);
  const result = useMarketRegime(applied);

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <p className="text-xs font-medium uppercase tracking-[0.2em] text-muted-foreground">
          观势 · 知势 · 策势
        </p>
        <h2 className="text-2xl font-semibold">市场情绪与板块轮动</h2>
        <p className="text-sm text-muted-foreground">
          按交易日、算法版本和板块回放已持久化的分钟快照与轮动证据
        </p>
      </header>

      <form
        className="flex flex-wrap items-end gap-4 rounded-lg border bg-card p-4"
        onSubmit={(event) => {
          event.preventDefault();
          setApplied({ ...draft });
        }}
      >
        <Field
          id="regime-date"
          label="交易日"
          value={draft.date}
          placeholder="2026-08-13"
          onChange={(date) => setDraft((current) => ({ ...current, date }))}
        />
        <Field
          id="regime-version"
          label="算法版本"
          value={draft.algorithmVersion ?? ""}
          placeholder="emotion_score_v1"
          onChange={(algorithmVersion) => setDraft((current) => ({ ...current, algorithmVersion }))}
        />
        <Field
          id="regime-sector"
          label="板块"
          value={draft.sectorId ?? ""}
          placeholder="sector-gold"
          onChange={(sectorId) => setDraft((current) => ({ ...current, sectorId }))}
        />
        <Button type="submit">回放</Button>
      </form>

      <MarketRegimeView result={result} />
    </div>
  );
}
