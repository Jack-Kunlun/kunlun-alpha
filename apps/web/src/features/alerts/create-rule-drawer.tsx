"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { BellRing, Plus, X } from "lucide-react";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../../components/ui/dialog";
import {
  requestId,
  type CreateWatchlistAlertRuleRequest,
  type WatchlistAlertRule,
} from "./use-watchlist-alerts";

type AutoEvaluatedField = Extract<
  WatchlistAlertRule["condition"]["field"],
  "LAST_PRICE" | "CHANGE_BPS"
>;

export function CreateRuleDrawer({
  disabled,
  onCreate,
  requestedInstrumentId = null,
  onClose,
}: {
  disabled: boolean;
  onCreate: (request: CreateWatchlistAlertRuleRequest) => Promise<void>;
  requestedInstrumentId?: string | null;
  onClose?: () => void;
}) {
  const [manuallyOpen, setManuallyOpen] = useState(false);
  const open = manuallyOpen || requestedInstrumentId !== null;
  function close() {
    setManuallyOpen(false);
    onClose?.();
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (disabled) return;
        if (next) setManuallyOpen(true);
        else close();
      }}
    >
      <DialogTrigger asChild>
        <Button type="button" size="sm" disabled={disabled}>
          <Plus className="mr-2 h-4 w-4" /> 新建规则
        </Button>
      </DialogTrigger>
      <DialogContent
        className="top-0 right-0 left-auto flex h-dvh max-h-dvh w-full max-w-lg translate-x-0 translate-y-0 flex-col gap-0 rounded-none p-0 sm:max-w-lg"
        showCloseButton={false}
      >
        <CreateRuleForm
          key={requestedInstrumentId ?? "manual"}
          disabled={disabled}
          initialInstrumentId={requestedInstrumentId ?? "600519.SH"}
          onCancel={close}
          onCreate={async (request) => {
            await onCreate(request);
            close();
          }}
        />
        <DialogClose asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="absolute top-4 right-4"
            disabled={disabled}
            aria-label="关闭新建规则"
          >
            <X className="h-4 w-4" />
          </Button>
        </DialogClose>
      </DialogContent>
    </Dialog>
  );
}

export function CreateRuleForm({
  disabled,
  onCreate,
  onCancel,
  initialInstrumentId = "600519.SH",
}: {
  disabled: boolean;
  onCancel: () => void;
  onCreate: (request: CreateWatchlistAlertRuleRequest) => Promise<void>;
  initialInstrumentId?: string;
}) {
  const [name, setName] = useState("价格突破提醒");
  const [instrumentId, setInstrumentId] = useState(initialInstrumentId);
  const [field, setField] = useState<AutoEvaluatedField>("LAST_PRICE");
  const [operator, setOperator] = useState<WatchlistAlertRule["condition"]["operator"]>("GTE");
  const [threshold, setThreshold] = useState("1500.00");
  const [throttleSeconds, setThrottleSeconds] = useState("300");
  const [quietEnabled, setQuietEnabled] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (disabled) return;
    setError(null);
    try {
      await onCreate({
        clientRequestId: requestId("create"),
        name,
        enabled: true,
        instrumentIds: [instrumentId.toUpperCase()],
        condition: {
          field,
          operator,
          threshold,
          featureName: null,
        },
        quietPeriod: quietEnabled
          ? { timezone: "Asia/Shanghai", startMinute: 23 * 60, endMinute: 7 * 60 }
          : null,
        throttleSeconds: Number(throttleSeconds),
        notificationChannel: "IN_APP",
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "规则保存失败");
    }
  }

  return (
    <>
      <DialogHeader className="shrink-0 border-b px-6 py-5 pr-14 text-left">
        <DialogTitle className="flex items-center gap-2">
          <Plus className="h-5 w-5" /> 新建规则
        </DialogTitle>
        <DialogDescription>设置证券、触发条件与免打扰时段。</DialogDescription>
      </DialogHeader>
      <form
        className="flex min-h-0 flex-1 flex-col"
        aria-busy={disabled}
        onSubmit={(event) => void submit(event)}
      >
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-5">
          <Field label="规则名称">
            <Input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} />
          </Field>
          <Field label="证券代码">
            <Input
              value={instrumentId}
              placeholder="600519.SH"
              onChange={(event) => setInstrumentId(event.target.value)}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="指标">
              <select
                className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                value={field}
                onChange={(event) => setField(event.target.value as AutoEvaluatedField)}
              >
                <option value="LAST_PRICE">最新价</option>
                <option value="CHANGE_BPS">涨跌幅 BPS</option>
              </select>
            </Field>
            <Field label="运算符">
              <select
                className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                value={operator}
                onChange={(event) => setOperator(event.target.value as typeof operator)}
              >
                <option value="GT">大于</option>
                <option value="GTE">大于等于</option>
                <option value="LT">小于</option>
                <option value="LTE">小于等于</option>
                <option value="EQ">等于</option>
              </select>
            </Field>
          </div>
          <Field label="阈值">
            <Input
              inputMode="decimal"
              value={threshold}
              onChange={(event) => setThreshold(event.target.value)}
            />
          </Field>
          <Field label="节流秒数">
            <Input
              type="number"
              min={0}
              max={86400}
              value={throttleSeconds}
              onChange={(event) => setThrottleSeconds(event.target.value)}
            />
          </Field>
          <label className="flex items-center gap-2 rounded-lg border p-3 text-sm">
            <input
              type="checkbox"
              checked={quietEnabled}
              onChange={(event) => setQuietEnabled(event.target.checked)}
            />
            23:00 至次日 07:00 免打扰
          </label>
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </div>
        <DialogFooter className="shrink-0 border-t px-6 py-4">
          <Button type="button" variant="outline" disabled={disabled} onClick={onCancel}>
            取消
          </Button>
          <Button disabled={disabled} type="submit">
            <BellRing className="mr-2 h-4 w-4" /> 保存规则
          </Button>
        </DialogFooter>
      </form>
    </>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Label className="flex flex-col items-stretch gap-2">
      <span className="leading-5">{label}</span>
      {children}
    </Label>
  );
}
