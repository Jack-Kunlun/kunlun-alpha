"use client";

import { useEffect, useRef, useState, type FormEvent, type Ref } from "react";
import type { PaperTerminalWorkspace } from "@kunlun/shared-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatPaperLedgerTime, parsePaperTerminalDisplay } from "./paper-terminal-display";
import { validatePaperTerminalCreateInput } from "./paper-terminal-form";
import { paperRequestId, usePaperTerminal } from "./use-paper-terminal";
import { PaperPreviewDrawer } from "./paper-preview-drawer";
import { PaperReconciliationCard } from "./paper-reconciliation-card";
import { PaperBuyOrdersCard } from "./paper-buy-orders-card";

function StateCard({
  title,
  detail,
  retry,
  titleRef,
  retryRef,
  role = "status",
}: {
  title: string;
  detail: string;
  retry?: () => void | Promise<boolean>;
  titleRef?: Ref<HTMLDivElement>;
  retryRef?: Ref<HTMLButtonElement>;
  role?: "status" | "alert";
}) {
  return (
    <section
      aria-label={title}
      className="min-h-[75vh] bg-[radial-gradient(circle_at_top_left,rgba(217,119,6,0.14),transparent_36%),linear-gradient(145deg,#fffaf0,#f8fafc)] p-6 dark:bg-none dark:bg-slate-950"
    >
      <Card className="mx-auto mt-20 max-w-xl border-amber-200" role={role}>
        <CardHeader>
          <CardTitle
            ref={titleRef}
            tabIndex={-1}
            className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
          >
            {title}
          </CardTitle>
          <CardDescription>{detail}</CardDescription>
        </CardHeader>
        {retry ? (
          <CardContent>
            <Button ref={retryRef} className="cursor-pointer" onClick={() => void retry()}>
              重新加载
            </Button>
          </CardContent>
        ) : null}
      </Card>
    </section>
  );
}

export function PaperTerminalPage() {
  const terminal = usePaperTerminal();
  const [buyPending, setBuyPending] = useState(false);
  const refreshButtonRef = useRef<HTMLButtonElement>(null);
  const stateCardTitleRef = useRef<HTMLDivElement>(null);
  const stateCardRetryRef = useRef<HTMLButtonElement>(null);
  const [restoreFocusRequested, setRestoreFocusRequested] = useState(false);
  const focusRestoreCompletedRef = useRef(false);
  const [accountName, setAccountName] = useState("本地研究账户");
  const [initialCapital, setInitialCapital] = useState("100000");
  const [clientRequestId, setClientRequestId] = useState(() => paperRequestId("create"));
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  useEffect(() => {
    if (
      !restoreFocusRequested ||
      focusRestoreCompletedRef.current ||
      terminal.state === "loading"
    ) {
      return;
    }
    const focusTarget =
      refreshButtonRef.current ?? stateCardRetryRef.current ?? stateCardTitleRef.current;
    if (focusTarget !== null) {
      focusTarget.focus();
      focusRestoreCompletedRef.current = true;
    }
  }, [restoreFocusRequested, terminal.state, terminal.workspace]);

  function acceptBuy(workspace: PaperTerminalWorkspace) {
    focusRestoreCompletedRef.current = false;
    setRestoreFocusRequested(true);
    setMessage({ kind: "success", text: "模拟买入已完成，资金、持仓与记录已更新。" });
    terminal.accept(workspace);
  }

  const refresh = async () => {
    setMessage(null);
    focusRestoreCompletedRef.current = false;
    const refreshed = await terminal.refresh();
    setRestoreFocusRequested(true);
    return refreshed;
  };

  const submitCreateAccount = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (terminal.submitting) return;
    setMessage(null);
    const validationError = validatePaperTerminalCreateInput(accountName, initialCapital);
    if (validationError !== null) {
      setMessage({ kind: "error", text: validationError });
      return;
    }
    try {
      await terminal.createAccount({
        schemaVersion: "paper-terminal-create-account-v1",
        clientRequestId,
        name: accountName,
        initialCapital,
      });
      setCreateDialogOpen(false);
      const refreshed = await terminal.refresh();
      setRestoreFocusRequested(true);
      setMessage({
        kind: refreshed ? "success" : "error",
        text: refreshed ? "账户已创建，账本已刷新。" : "账户已创建，但账本刷新失败，请重新加载。",
      });
    } catch {
      setMessage({
        kind: "error",
        text: "账户创建暂不可用，请稍后重试。",
      });
    }
  };

  if (terminal.state === "loading") {
    return (
      <StateCard
        title="正在加载模拟账本"
        detail="正在读取服务端模拟账户与账本快照。"
        titleRef={stateCardTitleRef}
      />
    );
  }
  if (terminal.state === "forbidden") {
    return (
      <StateCard
        title="无权访问模拟账本"
        detail="当前账号无权访问此账本。"
        titleRef={stateCardTitleRef}
        role="alert"
      />
    );
  }
  if (terminal.state === "error") {
    return (
      <StateCard
        title="模拟账本加载失败"
        detail="当前无法读取模拟账本，请稍后重试。"
        retry={refresh}
        titleRef={stateCardTitleRef}
        retryRef={stateCardRetryRef}
        role="alert"
      />
    );
  }
  if (terminal.state === "unavailable" || terminal.workspace?.status === "UNAVAILABLE") {
    return (
      <StateCard
        title="模拟账本暂不可用"
        detail="服务端当前无法提供账户账本，请稍后重试。"
        retry={refresh}
        titleRef={stateCardTitleRef}
        retryRef={stateCardRetryRef}
        role="alert"
      />
    );
  }
  if (terminal.workspace === null) {
    return (
      <StateCard
        title="账户账本数据无效"
        detail="服务没有返回可读取的工作区。"
        retry={refresh}
        titleRef={stateCardTitleRef}
        retryRef={stateCardRetryRef}
        role="alert"
      />
    );
  }

  const display = parsePaperTerminalDisplay(terminal.workspace);
  if (display.kind === "invalid") {
    return (
      <StateCard
        title="账户账本数据无效"
        detail={display.message}
        retry={refresh}
        titleRef={stateCardTitleRef}
        retryRef={stateCardRetryRef}
        role="alert"
      />
    );
  }
  const durable = display.persistenceMode === "DURABLE_COMMAND_JOURNAL";
  const account = display.kind === "account" ? display.account : null;

  return (
    <section
      aria-labelledby="paper-terminal-title"
      className="min-h-screen bg-[radial-gradient(circle_at_12%_0%,rgba(245,158,11,0.18),transparent_32%),radial-gradient(circle_at_90%_20%,rgba(15,118,110,0.12),transparent_30%),linear-gradient(145deg,#fffaf0,#f8fafc_55%,#ecfdf5)] p-4 text-slate-950 dark:bg-none dark:bg-slate-950 dark:text-slate-50 sm:p-8"
    >
      <div className="mx-auto max-w-[1480px] space-y-6">
        <header className="rounded-3xl border border-amber-200 bg-white/90 p-6 shadow-[0_24px_70px_-42px_rgba(180,83,9,0.65)] dark:border-amber-900 dark:bg-slate-900/90 sm:p-8">
          <div className="flex flex-col justify-between gap-6 xl:flex-row xl:items-end">
            <div>
              <div className="mb-3 flex flex-wrap gap-2">
                <Badge className="bg-amber-500 text-amber-950">仅模拟</Badge>
                <Badge variant="outline">{durable ? "服务端保存，重启后保留" : "重启后清空"}</Badge>
                <Badge variant="outline">无券商路径</Badge>
              </div>
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-amber-700">
                Paper Portfolio
              </p>
              <h2
                id="paper-terminal-title"
                className="mt-2 text-3xl font-black tracking-tight sm:text-5xl"
              >
                模拟账户
              </h2>
              <p className="mt-4 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300 sm:text-base">
                查看模拟资金与持仓，按人工假设试算并确认受控模拟买入。卖出与真实交易尚未开放；金额不代表真实资金或实时估值。
              </p>
              <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                当前账本独立于全局历史点时上下文，不随其回放。
              </p>
            </div>
            <div className="flex max-w-lg flex-col gap-3">
              <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
                <strong className="block">模拟账本与受控买入</strong>
                账本数据不会随全局历史点时切换。
              </div>
              <Button
                ref={refreshButtonRef}
                variant="outline"
                disabled={buyPending}
                className="cursor-pointer self-start disabled:cursor-progress"
                onClick={() => void refresh()}
              >
                刷新账本
              </Button>
            </div>
          </div>
        </header>

        {message !== null && !createDialogOpen ? (
          <div
            role={message.kind === "success" ? "status" : "alert"}
            className={
              message.kind === "success"
                ? "rounded-xl border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-900"
                : "rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-900"
            }
          >
            {message.text}
          </div>
        ) : null}

        {display.kind === "account" && display.workspaceStatus === "DEGRADED" ? (
          <div
            role="alert"
            className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100"
          >
            账本存在异常，请核对后再使用资金与持仓信息
          </div>
        ) : null}

        {display.kind === "account" && terminal.workspace.account !== null ? (
          <PaperPreviewDrawer
            key={display.generatedAt}
            accountId={terminal.workspace.account.accountId}
            disabled={display.workspaceStatus !== "READY" || display.account.status !== "ACTIVE"}
            onCommitted={acceptBuy}
            onBuyBusy={setBuyPending}
          />
        ) : null}

        {display.kind === "account" && terminal.workspace.account !== null ? (
          <PaperReconciliationCard
            key={`${terminal.workspace.account.accountId}:${display.generatedAt}`}
            accountId={terminal.workspace.account.accountId}
            basis={display.generatedAt}
            disabled={buyPending}
          />
        ) : null}

        {display.kind === "empty" ? (
          <Card className="border-amber-200 bg-white/95 dark:bg-slate-900">
            <CardHeader>
              <CardTitle>尚未创建模拟账户</CardTitle>
              <CardDescription>
                创建后可在此查看模拟资金、持仓成本与账本记录。
                {durable ? " 服务端保存，重启后保留。" : " 当前运行期间有效，重启后清空。"}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Dialog
                open={createDialogOpen}
                onOpenChange={(open) => {
                  if (terminal.submitting) return;
                  setCreateDialogOpen(open);
                  if (open) {
                    setMessage(null);
                    setRestoreFocusRequested(false);
                    focusRestoreCompletedRef.current = false;
                  }
                }}
              >
                <DialogTrigger asChild>
                  <Button className="cursor-pointer">创建账户</Button>
                </DialogTrigger>
                <DialogContent showCloseButton={false}>
                  <DialogHeader>
                    <DialogTitle>创建模拟账户</DialogTitle>
                    <DialogDescription>
                      填写账户名称和模拟初始资金，创建后查看账本。
                    </DialogDescription>
                  </DialogHeader>
                  <form className="grid gap-4" onSubmit={submitCreateAccount}>
                    <label className="grid gap-2 text-sm font-medium">
                      账户名称
                      <Input
                        value={accountName}
                        maxLength={80}
                        autoComplete="off"
                        aria-required="true"
                        disabled={terminal.submitting}
                        className="disabled:cursor-progress"
                        onChange={(event) => {
                          setAccountName(event.target.value);
                          setClientRequestId(paperRequestId("create"));
                          setMessage(null);
                        }}
                      />
                    </label>
                    <label className="grid gap-2 text-sm font-medium">
                      初始资金（CNY）
                      <Input
                        value={initialCapital}
                        inputMode="decimal"
                        maxLength={32}
                        aria-required="true"
                        disabled={terminal.submitting}
                        className="disabled:cursor-progress"
                        onChange={(event) => {
                          setInitialCapital(event.target.value);
                          setClientRequestId(paperRequestId("create"));
                          setMessage(null);
                        }}
                      />
                    </label>
                    {message?.kind === "error" ? (
                      <p role="alert" className="text-sm text-red-700">
                        {message.text}
                      </p>
                    ) : null}
                    <DialogFooter>
                      <Button
                        type="button"
                        variant="outline"
                        className="cursor-pointer disabled:cursor-progress"
                        disabled={terminal.submitting}
                        onClick={() => setCreateDialogOpen(false)}
                      >
                        取消
                      </Button>
                      <Button
                        type="submit"
                        className="cursor-pointer disabled:cursor-progress"
                        disabled={terminal.submitting}
                      >
                        {terminal.submitting ? "创建中…" : "创建账户"}
                      </Button>
                    </DialogFooter>
                  </form>
                </DialogContent>
              </Dialog>
            </CardContent>
          </Card>
        ) : (
          <>
            {account !== null ? (
              <>
                <Card className="border-slate-200 bg-white/95 dark:bg-slate-900">
                  <CardHeader className="flex flex-row items-start justify-between gap-4">
                    <div className="min-w-0">
                      <CardDescription>模拟账户</CardDescription>
                      <CardTitle className="mt-2 break-all text-2xl">{account.name}</CardTitle>
                    </div>
                    <Badge className="shrink-0" variant="outline">
                      {account.status === "ACTIVE"
                        ? "正常"
                        : account.status === "SUSPENDED"
                          ? "已暂停"
                          : "已关闭"}
                    </Badge>
                  </CardHeader>
                  <CardContent className="grid gap-2 text-sm text-slate-600 dark:text-slate-300 sm:grid-cols-2">
                    <p>
                      账本截止时间：
                      <time dateTime={account.dataCutoffTime}>
                        {formatPaperLedgerTime(account.dataCutoffTime)}
                      </time>
                    </p>
                    <p>基础币种：{account.baseCurrency}</p>
                  </CardContent>
                </Card>

                <section
                  aria-label="账户资金与账本摘要"
                  className="grid gap-4 md:grid-cols-2 xl:grid-cols-4"
                >
                  {[
                    ["初始资金", `${account.initialCapital} CNY`],
                    ["账面现金", `${account.cash} CNY`],
                    ["持仓数量", String(account.positions.length)],
                    ["账本事件", String(account.eventCount)],
                  ].map(([label, value]) => (
                    <Card key={label} className="border-slate-200 bg-white/95 dark:bg-slate-900">
                      <CardHeader className="pb-2">
                        <CardDescription>{label}</CardDescription>
                        <CardTitle className="break-all font-mono text-2xl">{value}</CardTitle>
                      </CardHeader>
                    </Card>
                  ))}
                </section>

                <Card className="border-slate-200 bg-white/95 dark:bg-slate-900">
                  <CardHeader>
                    <CardTitle>持仓</CardTitle>
                    <CardDescription>
                      成本按服务端账本原值展示；当前页面不提供行情估值。
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {account.positions.length === 0 ? (
                      <p role="status" className="py-6 text-center text-sm text-slate-500">
                        暂无持仓
                      </p>
                    ) : (
                      <div className="overflow-x-auto">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>证券</TableHead>
                              <TableHead>数量</TableHead>
                              <TableHead>可用数量</TableHead>
                              <TableHead>持仓成本（CNY）</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {account.positions.map((position) => (
                              <TableRow key={position.instrumentId}>
                                <TableCell className="font-mono">{position.instrumentId}</TableCell>
                                <TableCell>{position.quantity}</TableCell>
                                <TableCell>{position.availableQuantity}</TableCell>
                                <TableCell>{position.costAmount}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </>
            ) : null}
          </>
        )}
        {display.kind === "account" ? <PaperBuyOrdersCard workspace={terminal.workspace} /> : null}
      </div>
    </section>
  );
}
