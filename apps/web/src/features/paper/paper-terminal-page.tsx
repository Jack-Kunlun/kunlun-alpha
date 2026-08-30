"use client";

import { useState, type FormEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { paperRequestId, usePaperTerminal } from "./use-paper-terminal";

function StateCard({
  title,
  detail,
  retry,
}: {
  title: string;
  detail: string;
  retry?: () => void;
}) {
  return (
    <section
      aria-label={title}
      className="min-h-[75vh] bg-[radial-gradient(circle_at_top_left,rgba(217,119,6,0.14),transparent_36%),linear-gradient(145deg,#fffaf0,#f8fafc)] p-6 dark:from-slate-950 dark:to-slate-900"
    >
      <Card className="mx-auto mt-20 max-w-xl border-amber-200" role="status">
        <CardHeader>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{detail}</CardDescription>
        </CardHeader>
        {retry ? (
          <CardContent>
            <Button onClick={retry}>重新加载</Button>
          </CardContent>
        ) : null}
      </Card>
    </section>
  );
}

export function PaperTerminalPage() {
  const terminal = usePaperTerminal();
  const [accountName, setAccountName] = useState("本地研究账户");
  const [initialCapital, setInitialCapital] = useState("100000");
  const [instrumentId, setInstrumentId] = useState("600519.SH");
  const [price, setPrice] = useState("100");
  const [message, setMessage] = useState<string | null>(null);

  if (terminal.state === "loading") {
    return <StateCard title="正在加载模拟组合" detail="正在读取模拟账本、订单、风控与对账状态。" />;
  }
  if (terminal.state === "forbidden") {
    return <StateCard title="无权访问模拟组合" detail="当前身份没有 paper:read 权限。" />;
  }
  if (terminal.state === "error") {
    return (
      <StateCard
        title="模拟组合加载失败"
        detail={terminal.error ?? "请求失败"}
        retry={terminal.refresh}
      />
    );
  }
  if (terminal.state === "unavailable" || terminal.workspace?.status === "UNAVAILABLE") {
    return (
      <StateCard
        title="模拟引擎暂不可用"
        detail={terminal.workspace?.limitations.join("；") ?? "请检查 quant-engine 健康状态。"}
        retry={terminal.refresh}
      />
    );
  }
  const workspace = terminal.workspace;
  if (workspace === null) {
    return (
      <StateCard title="模拟组合暂无数据" detail="工作区响应为空。" retry={terminal.refresh} />
    );
  }
  const durable = workspace.persistenceMode === "DURABLE_COMMAND_JOURNAL";

  const createAccount = async (event: FormEvent) => {
    event.preventDefault();
    setMessage(null);
    try {
      await terminal.createAccount({
        schemaVersion: "paper-terminal-create-account-v1",
        clientRequestId: paperRequestId("create"),
        name: accountName,
        initialCapital,
      });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "创建模拟账户失败");
    }
  };

  const simulate = async (event: FormEvent) => {
    event.preventDefault();
    setMessage(null);
    try {
      await terminal.simulate({
        schemaVersion: "paper-terminal-simulation-v1",
        clientRequestId: paperRequestId("simulate"),
        instrumentId: instrumentId.toUpperCase(),
        price,
        score: "1",
        confidence: "1",
        lotSize: 100,
      });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "模拟演练失败");
    }
  };

  return (
    <section
      aria-labelledby="paper-terminal-title"
      className="min-h-screen bg-[radial-gradient(circle_at_12%_0%,rgba(245,158,11,0.18),transparent_32%),radial-gradient(circle_at_90%_20%,rgba(15,118,110,0.12),transparent_30%),linear-gradient(145deg,#fffaf0,#f8fafc_55%,#ecfdf5)] p-4 text-slate-950 dark:bg-slate-950 dark:text-slate-50 sm:p-8"
    >
      <div className="mx-auto max-w-[1480px] space-y-6">
        <header className="rounded-3xl border border-amber-200 bg-white/90 p-6 shadow-[0_24px_70px_-42px_rgba(180,83,9,0.65)] dark:border-amber-900 dark:bg-slate-900/90 sm:p-8">
          <div className="flex flex-col justify-between gap-6 xl:flex-row xl:items-end">
            <div>
              <div className="mb-3 flex flex-wrap gap-2">
                <Badge className="bg-amber-500 text-amber-950">仅模拟</Badge>
                <Badge variant="outline">{durable ? "重启恢复日志" : "易失内存模式"}</Badge>
                <Badge variant="outline">无券商路径</Badge>
              </div>
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-amber-700">
                Paper Portfolio
              </p>
              <h2
                id="paper-terminal-title"
                className="mt-2 text-3xl font-black tracking-tight sm:text-5xl"
              >
                模拟组合控制台
              </h2>
              <p className="mt-4 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300 sm:text-base">
                从信号分配、服务端风控、模拟订单、全额成交到双账簿对账，所有步骤均保留事件摘要。
              </p>
            </div>
            <div className="max-w-lg rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-950 dark:border-red-900 dark:bg-red-950/40 dark:text-red-100">
              <strong className="block">当前能力边界</strong>
              {workspace.limitations.join("；")}
            </div>
          </div>
        </header>

        {message ? (
          <div
            role="alert"
            className="rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-900"
          >
            {message}
          </div>
        ) : null}

        {workspace.account === null ? (
          <Card className="border-amber-200 bg-white/95 dark:bg-slate-900">
            <CardHeader>
              <CardTitle>创建本地模拟账户</CardTitle>
              <CardDescription>
                {durable
                  ? "账户命令写入本地哈希日志，服务重启后会校验并恢复。"
                  : "账户只保存在 quant-engine 当前进程内，服务重启后会清空。"}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form className="grid gap-4 md:grid-cols-[1fr_1fr_auto]" onSubmit={createAccount}>
                <label className="space-y-2 text-sm font-medium">
                  账户名称
                  <Input
                    value={accountName}
                    maxLength={80}
                    onChange={(event) => setAccountName(event.target.value)}
                  />
                </label>
                <label className="space-y-2 text-sm font-medium">
                  初始资金（CNY）
                  <Input
                    value={initialCapital}
                    inputMode="decimal"
                    onChange={(event) => setInitialCapital(event.target.value)}
                  />
                </label>
                <Button className="self-end" disabled={terminal.submitting}>
                  创建账户
                </Button>
              </form>
            </CardContent>
          </Card>
        ) : (
          <>
            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              {[
                ["账户净值", `${workspace.account.nav} CNY`],
                ["可用现金", `${workspace.account.cash} CNY`],
                ["持仓数量", String(workspace.account.positions.length)],
                ["账本事件", String(workspace.audit.accountEventCount)],
              ].map(([label, value]) => (
                <Card key={label} className="border-slate-200 bg-white/95 dark:bg-slate-900">
                  <CardHeader className="pb-2">
                    <CardDescription>{label}</CardDescription>
                    <CardTitle className="font-mono text-2xl">{value}</CardTitle>
                  </CardHeader>
                </Card>
              ))}
            </section>

            <Card className="border-emerald-200 bg-white/95 dark:bg-slate-900">
              <CardHeader>
                <CardTitle>运行信号到成交演练</CardTitle>
                <CardDescription>
                  固定使用 30% 单标的上限、100 股整手和服务端风险检查；报价仅用于本次模拟。
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form className="grid gap-4 md:grid-cols-[1fr_1fr_auto]" onSubmit={simulate}>
                  <label className="space-y-2 text-sm font-medium">
                    证券代码
                    <Input
                      value={instrumentId}
                      onChange={(event) => setInstrumentId(event.target.value)}
                    />
                  </label>
                  <label className="space-y-2 text-sm font-medium">
                    模拟可执行报价（CNY）
                    <Input
                      value={price}
                      inputMode="decimal"
                      onChange={(event) => setPrice(event.target.value)}
                    />
                  </label>
                  <Button
                    className="self-end bg-emerald-700 hover:bg-emerald-800"
                    disabled={terminal.submitting}
                  >
                    执行模拟闭环
                  </Button>
                </form>
              </CardContent>
            </Card>

            <section className="grid gap-4 lg:grid-cols-3">
              <Card className="border-slate-200 bg-white/95 dark:bg-slate-900 lg:col-span-2">
                <CardHeader>
                  <CardTitle>模拟订单</CardTitle>
                  <CardDescription>
                    订单意图不可发送至券商；状态来自不可变执行事件。
                  </CardDescription>
                </CardHeader>
                <CardContent className="overflow-x-auto">
                  {workspace.orders.length === 0 ? (
                    <p role="status" className="py-8 text-center text-sm text-slate-500">
                      尚无模拟订单
                    </p>
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>证券</TableHead>
                          <TableHead>方向</TableHead>
                          <TableHead>状态</TableHead>
                          <TableHead>数量</TableHead>
                          <TableHead>均价</TableHead>
                          <TableHead>费用</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {workspace.orders.map((order) => (
                          <TableRow key={order.orderId}>
                            <TableCell className="font-mono">{order.instrumentId}</TableCell>
                            <TableCell>{order.side}</TableCell>
                            <TableCell>
                              <Badge variant="outline">{order.status}</Badge>
                            </TableCell>
                            <TableCell>
                              {order.filledQuantity}/{order.quantity}
                            </TableCell>
                            <TableCell>{order.averageFillPrice ?? "-"}</TableCell>
                            <TableCell>{order.totalFees}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
              </Card>
              <Card className="border-slate-200 bg-slate-950 text-slate-50">
                <CardHeader>
                  <CardTitle>风控与对账</CardTitle>
                  <CardDescription className="text-slate-400">
                    服务端 fail-closed 检查与双账簿结果。
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4 text-sm">
                  <p>
                    风险：
                    <strong>
                      {workspace.latestRisk === null
                        ? "尚未运行"
                        : workspace.latestRisk.allowed
                          ? "通过"
                          : "拒绝"}
                    </strong>
                  </p>
                  <p>
                    对账：<strong>{workspace.reconciliation?.status ?? "尚未运行"}</strong>
                  </p>
                  <p>
                    重复成交：<strong>{workspace.reconciliation?.duplicateFillCount ?? 0}</strong>
                  </p>
                  <p className="break-all text-xs text-slate-400">
                    执行摘要：{workspace.audit.executionDigest ?? "暂无"}
                  </p>
                </CardContent>
              </Card>
            </section>

            <Card className="border-slate-200 bg-white/95 dark:bg-slate-900">
              <CardHeader>
                <CardTitle>模拟持仓</CardTitle>
                <CardDescription>可用数量遵循当日买入不可立即卖出的模拟约束。</CardDescription>
              </CardHeader>
              <CardContent>
                {workspace.account.positions.length === 0 ? (
                  <p className="py-6 text-center text-sm text-slate-500">暂无持仓</p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>证券</TableHead>
                        <TableHead>数量</TableHead>
                        <TableHead>可用</TableHead>
                        <TableHead>成本</TableHead>
                        <TableHead>市值</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {workspace.account.positions.map((position) => (
                        <TableRow key={position.instrumentId}>
                          <TableCell className="font-mono">{position.instrumentId}</TableCell>
                          <TableCell>{position.quantity}</TableCell>
                          <TableCell>{position.availableQuantity}</TableCell>
                          <TableCell>{position.costAmount}</TableCell>
                          <TableCell>{position.marketValue}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </section>
  );
}
