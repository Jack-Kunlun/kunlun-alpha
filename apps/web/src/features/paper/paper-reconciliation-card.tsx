"use client";

import { useEffect, useRef, useState, type Ref } from "react";
import type { PaperReconciliationResult as Report } from "@kunlun/shared-types";
import { apiClient } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { readPaperReconciliation } from "./paper-reconciliation";
import { formatPaperLedgerTime } from "./paper-terminal-display";

export function PaperReconciliationCard({
  accountId,
  basis,
  disabled = false,
}: {
  accountId: string;
  basis: string;
  disabled?: boolean;
}) {
  const [report, setReport] = useState<Report | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const actionRef = useRef<HTMLButtonElement>(null);
  const restoreActionFocus = useRef(false);
  const active = useRef(false),
    busy = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    if (!pending && restoreActionFocus.current) {
      restoreActionFocus.current = false;
      // Native disabled actions lose focus. Restore only when the user has not moved elsewhere.
      if (document.activeElement === document.body) actionRef.current?.focus();
    }
  }, [pending]);
  async function check() {
    if (disabled || busy.current) return;
    restoreActionFocus.current = true;
    busy.current = true;
    setPending(true);
    setError(null);
    try {
      const result = readPaperReconciliation(
        await apiClient.get<unknown>("/v1/paper/reconciliation"),
        accountId,
        basis,
      );
      if (active.current) setReport(result);
    } catch (cause) {
      const status =
        typeof cause === "object" && cause !== null && "status" in cause ? cause.status : null;
      if (active.current)
        setError(
          status === 401 || status === 403
            ? "无权核对账簿，请重新登录后重试。"
            : "核对暂不可用，请稍后重试。",
        );
    } finally {
      busy.current = false;
      if (active.current) setPending(false);
    }
  }
  return (
    <PaperReconciliationResult
      actionRef={actionRef}
      report={report}
      pending={pending}
      error={error}
      disabled={disabled}
      onCheck={() => void check()}
    />
  );
}

export function PaperReconciliationResult({
  actionRef,
  report,
  pending,
  error,
  disabled = false,
  onCheck,
}: {
  actionRef?: Ref<HTMLButtonElement>;
  report: Report | null;
  pending: boolean;
  error: string | null;
  disabled?: boolean;
  onCheck: () => void;
}) {
  return (
    <Card>
      <CardHeader className="gap-4 sm:flex sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <CardTitle>账簿核对</CardTitle>
          <CardDescription>
            重新比对模拟执行流水与账户账本的现金、持仓数量和持仓成本。只读核对，不会修复或修改账本。
          </CardDescription>
        </div>
        <Button
          ref={actionRef}
          variant="outline"
          disabled={disabled || pending}
          aria-busy={pending}
          className={`cursor-pointer shrink-0 self-start ${pending ? "disabled:cursor-progress" : "disabled:cursor-not-allowed"}`}
          onClick={onCheck}
        >
          {pending ? "正在核对…" : error ? "重试核对" : report ? "重新核对" : "核对账簿"}
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? (
          <p role="alert" className="text-sm text-red-700 dark:text-red-300">
            {error}
            {report ? " 以下为上次成功返回的报告，未能确认当前状态。" : ""}
          </p>
        ) : null}
        {pending ? (
          <p role="status" className="text-sm text-muted-foreground">
            正在重新读取并核对；已有报告仅反映上次核对时刻。
          </p>
        ) : null}
        {report === null ? (
          <p className="text-sm text-muted-foreground">尚未核对。点击“核对账簿”查看当前结果。</p>
        ) : (
          <>
            <div
              role={report.status === "DRIFTED" ? "alert" : "status"}
              className={`rounded-xl border p-4 text-sm ${report.status === "MATCHED" ? "border-emerald-200 bg-emerald-50 text-emerald-950 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100" : "border-red-200 bg-red-50 text-red-950 dark:border-red-900 dark:bg-red-950/40 dark:text-red-100"}`}
            >
              <strong className="block">
                {report.status === "MATCHED" ? "账簿一致" : "发现账簿差异"}
              </strong>
              <p className="mt-2">
                核对时间：<time dateTime={report.asOf}>{formatPaperLedgerTime(report.asOf)}</time>
              </p>
              <p className="mt-1">
                差异：{report.diffs.length} 项 · 去重成交：{report.duplicateFillCount}
              </p>
              <p className="mt-2">
                {report.status === "MATCHED"
                  ? "核对时刻的现金、持仓数量和持仓成本一致。"
                  : "请先核查执行记录与账本差异，再使用相关资金和持仓信息。"}{" "}
                账本变更后需重新核对；此报告不代表真实券商对账。
              </p>
            </div>
            {report.diffs.length > 0 ? (
              <div
                role="region"
                aria-label="账簿差异明细，可横向滚动"
                tabIndex={0}
                className="overflow-x-auto rounded-md border focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none [&>[data-slot=table-container]]:overflow-visible"
              >
                <Table className="min-w-[720px]">
                  <TableHeader>
                    <TableRow>
                      {[
                        "核对项目",
                        "证券",
                        "执行流水应有值",
                        "账户账面值",
                        "差额（账面 − 应有）",
                      ].map((label) => (
                        <TableHead key={label}>{label}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {report.diffs.map((row) => (
                      <TableRow key={`${row.kind}:${row.instrumentId}`}>
                        <TableCell>
                          {
                            {
                              CASH: "现金（CNY）",
                              POSITION_QUANTITY: "持仓数量",
                              POSITION_COST: "持仓成本（CNY）",
                            }[row.kind]
                          }
                        </TableCell>
                        <TableCell className="font-mono">{row.instrumentId ?? "账户"}</TableCell>
                        <TableCell className="font-mono">{row.expected}</TableCell>
                        <TableCell className="font-mono">{row.observed}</TableCell>
                        <TableCell className="font-mono">{row.difference}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}
