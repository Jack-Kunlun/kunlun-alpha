import { useState, useRef, type Ref, type FormEvent } from "react";
import type { PaperTerminalWorkspace } from "@kunlun/shared-types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { formatPaperLedgerTime } from "./paper-terminal-display";
import type { PaperPreviewDisplay, PaperPreviewFormValues } from "./paper-preview";
import { usePaperPreview } from "./use-paper-preview";
import { PaperRiskPreviewPanel } from "./paper-risk-preview-panel";
import type { PaperRiskView } from "./paper-risk-preview";

export function PaperPreviewDrawer({
  accountId,
  disabled,
  onCommitted,
  onBuyBusy,
}: {
  accountId: string;
  disabled: boolean;
  onCommitted?: (workspace: PaperTerminalWorkspace) => void;
  onBuyBusy?: (busy: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [buyOpen, setBuyOpen] = useState(false);
  const buyTriggerRef = useRef<HTMLButtonElement>(null);
  const buyAcceptedRef = useRef(false);
  const [values, setValues] = useState<PaperPreviewFormValues>({
    instrumentId: "",
    price: "",
    score: "0.3",
    confidence: "1",
    lotSize: "100",
  });
  const model = usePaperPreview(
    accountId,
    (workspace) => {
      buyAcceptedRef.current = true;
      onCommitted?.(workspace);
    },
    onBuyBusy,
  );
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (await model.preview(values)) setOpen(false);
  }
  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (model.pending || model.riskPending || model.buyPending) return;
          if (next) model.clear();
          setOpen(next);
        }}
      >
        <DialogTrigger asChild>
          <Button
            variant="outline"
            disabled={disabled || model.riskPending || model.buyPending}
            className={`cursor-pointer ${model.riskPending || model.buyPending ? "disabled:cursor-progress" : "disabled:cursor-not-allowed"}`}
          >
            试算仓位
          </Button>
        </DialogTrigger>
        <DialogContent
          className="top-0 right-0 left-auto flex h-dvh max-h-dvh w-full max-w-lg translate-x-0 translate-y-0 flex-col gap-0 rounded-none p-0 sm:max-w-lg"
          showCloseButton={false}
          onEscapeKeyDown={(event) => {
            if (model.pending) event.preventDefault();
          }}
          onInteractOutside={(event) => {
            if (model.pending) event.preventDefault();
          }}
        >
          <DialogHeader className="border-b p-6">
            <DialogTitle>模拟仓位试算</DialogTitle>
            <DialogDescription>
              按人工假设计算目标和调整数量。结果不提交订单、不改变账本，也不代表风控通过。
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(event) => void submit(event)}
            className="flex min-h-0 flex-1 flex-col"
            aria-busy={model.pending}
          >
            <div className="flex-1 space-y-5 overflow-y-auto p-6">
              <fieldset className="grid gap-4" disabled={model.pending}>
                <legend className="mb-3 text-sm font-semibold">标的与价格假设</legend>
                <Field
                  label="证券代码"
                  value={values.instrumentId}
                  maxLength={9}
                  pending={model.pending}
                  onChange={(value) => setValues({ ...values, instrumentId: value })}
                />
                <Field
                  label="假设参考价（CNY）"
                  value={values.price}
                  maxLength={32}
                  pending={model.pending}
                  onChange={(value) => setValues({ ...values, price: value })}
                />
                <p className="text-xs leading-5 text-muted-foreground">
                  参考价由你输入，不读取行情；模拟买入价格最多支持 8
                  位小数。本次试算使用当前模拟账本，不随全局历史点时回放。
                </p>
              </fieldset>
              <fieldset className="grid gap-4" disabled={model.pending}>
                <legend className="mb-3 text-sm font-semibold">信号与数量假设</legend>
                <Field
                  label="假设信号强度（0–1）"
                  value={values.score}
                  maxLength={20}
                  pending={model.pending}
                  onChange={(value) => setValues({ ...values, score: value })}
                />
                <Field
                  label="假设可信度（0–1）"
                  value={values.confidence}
                  maxLength={20}
                  pending={model.pending}
                  onChange={(value) => setValues({ ...values, confidence: value })}
                />
                <Field
                  label="整手单位（股）"
                  value={values.lotSize}
                  maxLength={5}
                  pending={model.pending}
                  onChange={(value) => setValues({ ...values, lotSize: value })}
                />
              </fieldset>
              <p className="text-xs leading-5 text-muted-foreground">
                策略口径 1.0.0：目标权重为信号强度 × 假设可信度，上限 30%；保留 5%
                账面现金，可信度低于 0.5
                时拒绝。整手单位为人工假设，不自动识别交易所规则；金额不含费用。
              </p>
              {model.error !== null ? (
                <p role="alert" className="text-sm text-red-700 dark:text-red-300">
                  {model.error}
                </p>
              ) : null}
            </div>
            <DialogFooter className="border-t p-6">
              <Button
                type="button"
                variant="outline"
                disabled={model.pending}
                className="cursor-pointer disabled:cursor-progress"
                onClick={() => setOpen(false)}
              >
                取消
              </Button>
              <Button
                type="submit"
                disabled={model.pending}
                className="cursor-pointer disabled:cursor-progress"
              >
                {model.pending ? "正在试算…" : "生成试算"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      {model.result !== null ? (
        <PaperPreviewResult
          result={model.result}
          risk={model.risk}
          riskPending={model.riskPending}
          riskError={model.riskError}
          buyPending={model.buyPending}
          buyTriggerRef={buyTriggerRef}
          onBuyOpen={() => {
            buyAcceptedRef.current = false;
            setBuyOpen(true);
          }}
          onRiskCheck={() => void model.checkRisk()}
        />
      ) : null}
      {model.result?.kind === "target" && model.result.side === "BUY" ? (
        <Dialog
          open={buyOpen}
          onOpenChange={(next) => {
            if (!model.buyPending) setBuyOpen(next);
          }}
        >
          <DialogContent
            showCloseButton={!model.buyPending}
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              if (!buyAcceptedRef.current) buyTriggerRef.current?.focus();
            }}
            onEscapeKeyDown={(e) => {
              if (model.buyPending) e.preventDefault();
            }}
            onInteractOutside={(e) => {
              if (model.buyPending) e.preventDefault();
            }}
          >
            <DialogHeader>
              <DialogTitle>确认模拟买入</DialogTitle>
              <DialogDescription>
                按本次人工价格假设全额模拟成交，服务端会重新核对试算和账簿，并更新模拟资金与持仓。
              </DialogDescription>
            </DialogHeader>
            <dl className="grid grid-cols-2 gap-4 text-sm">
              <Value title="证券" value={model.result.instrumentId} />
              <Value title="模拟买入数量" value={`${model.result.quantity} 股`} />
              <Value title="假设参考价" value={`${model.result.price} CNY`} />
              <Value title="参考金额（未含费用）" value={`${model.result.notional} CNY`} />
            </dl>
            <p className="text-sm text-muted-foreground">
              模拟手续费按金额的 0.03% 计算，最低 1
              CNY，按分计入持仓成本。仅支持模拟买入，不连接券商；价格来自你的人工假设。
            </p>
            {model.buyError !== null ? (
              <p role="alert" className="text-sm text-red-700 dark:text-red-300">
                {model.buyError}
              </p>
            ) : null}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={model.buyPending}
                className="cursor-pointer disabled:cursor-progress"
                onClick={() => setBuyOpen(false)}
              >
                取消
              </Button>
              <Button
                type="button"
                disabled={model.buyPending}
                aria-busy={model.buyPending}
                className="cursor-pointer disabled:cursor-progress"
                onClick={() => {
                  void model.buy().then((ok) => {
                    if (ok) setBuyOpen(false);
                  });
                }}
              >
                {model.buyPending ? "正在模拟买入…" : "确认模拟买入"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}
    </>
  );
}

function Field({
  label,
  value,
  onChange,
  pending,
  maxLength,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  pending: boolean;
  maxLength: number;
}) {
  return (
    <label className="grid gap-2 text-sm font-medium">
      {label}
      <Input
        value={value}
        maxLength={maxLength}
        disabled={pending}
        aria-required="true"
        inputMode={label === "证券代码" ? "text" : "decimal"}
        autoComplete="off"
        className="disabled:cursor-progress"
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

export function PaperPreviewResult({
  result,
  risk = null,
  riskPending = false,
  riskError = null,
  onRiskCheck,
  onBuyOpen,
  buyPending = false,
  buyTriggerRef,
}: {
  result: PaperPreviewDisplay;
  risk?: PaperRiskView | null;
  riskPending?: boolean;
  riskError?: string | null;
  onRiskCheck?: () => void;
  onBuyOpen?: () => void;
  buyPending?: boolean;
  buyTriggerRef?: Ref<HTMLButtonElement>;
}) {
  return (
    <Card role="status" aria-label="仓位试算结果">
      <CardHeader>
        <CardTitle>仓位试算结果 · {result.instrumentId}</CardTitle>
        <p className="text-sm text-muted-foreground">
          仅预览，账本未改变 · 策略口径 {result.policyVersion} ·{" "}
          <time dateTime={result.time}>{formatPaperLedgerTime(result.time)}</time>
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {result.kind === "rejected" ? (
          <p>{result.reason}</p>
        ) : (
          <dl className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <Value title="当前持仓" value={`${result.current} 股`} />
            <Value title="试算目标持仓" value={`${result.target} 股`} />
            <Value
              title={result.side === "BUY" ? "试算增加数量" : "试算减少数量"}
              value={`${result.quantity} 股`}
            />
            <Value title="假设调整金额（未含费用）" value={`${result.notional} CNY`} />
            <Value title="假设参考价" value={`${result.price} CNY`} />
            <Value title="目标权重比例" value={result.weight} />
          </dl>
        )}
        <p className="text-xs text-muted-foreground">
          人工价格与信号假设，不是行情、模型建议或可执行报价。可对本次试算单独进行只读风险检查，金额未含费用。
        </p>
        {result.kind === "target" && onRiskCheck !== undefined ? (
          <Button
            type="button"
            variant="outline"
            disabled={riskPending || buyPending}
            aria-busy={riskPending || buyPending}
            className="cursor-pointer disabled:cursor-progress"
            onClick={onRiskCheck}
          >
            {riskPending ? "正在检查…" : riskError !== null ? "重试风险检查" : "检查模拟风险"}
          </Button>
        ) : null}
        {riskError !== null ? (
          <p role="alert" className="text-sm text-red-700 dark:text-red-300">
            {riskError}
          </p>
        ) : null}
        {risk !== null ? <PaperRiskPreviewPanel risk={risk} /> : null}
        {risk?.allowed &&
        result.kind === "target" &&
        result.side === "BUY" &&
        onBuyOpen !== undefined ? (
          <Button
            type="button"
            disabled={buyPending}
            aria-busy={buyPending}
            className="cursor-pointer disabled:cursor-progress"
            onClick={onBuyOpen}
            ref={buyTriggerRef}
          >
            {buyPending ? "正在模拟买入…" : "模拟买入"}
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}
function Value({ title, value }: { title: string; value: string }) {
  return (
    <div className="min-w-0 space-y-2">
      <dt className="text-muted-foreground">{title}</dt>
      <dd className="break-all font-mono font-semibold">{value}</dd>
    </div>
  );
}
