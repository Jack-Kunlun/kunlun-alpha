import { useEffect, useRef, useState } from "react";
import { ApiError, apiClient } from "@/lib/api-client";
import {
  capturePaperRiskContext,
  readPaperRiskPreview,
  type PaperRiskContext,
  type PaperRiskView,
} from "./paper-risk-preview";
import { paperRequestId } from "./use-paper-terminal";
import {
  buildPaperPreviewCommand,
  readPaperPreview,
  type PaperPreviewFormValues,
  type PaperPreviewDisplay,
} from "./paper-preview";

export function usePaperPreview(accountId: string) {
  const [result, setResult] = useState<PaperPreviewDisplay | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [context, setContext] = useState<PaperRiskContext | null>(null);
  const [risk, setRisk] = useState<PaperRiskView | null>(null);
  const [riskPending, setRiskPending] = useState(false);
  const [riskError, setRiskError] = useState<string | null>(null);
  const busy = useRef(false),
    generation = useRef(0);
  useEffect(
    () => () => {
      generation.current++;
    },
    [],
  );
  function clear() {
    generation.current++;
    setResult(null);
    setError(null);
    setContext(null);
    setRisk(null);
    setRiskError(null);
  }
  async function preview(values: PaperPreviewFormValues): Promise<boolean> {
    if (busy.current) return false;
    clear();
    const parsed = buildPaperPreviewCommand(values, paperRequestId("preview"));
    if (parsed.command === null) {
      setError(parsed.error);
      return false;
    }
    setPending(true);
    busy.current = true;
    const current = generation.current;
    try {
      const value = await apiClient.post<typeof parsed.command, unknown>(
        "/v1/paper/previews",
        parsed.command,
      );
      if (current !== generation.current) return false;
      const result = readPaperPreview(value, parsed.command, accountId);
      setContext(result.kind === "target" ? capturePaperRiskContext(value) : null);
      setResult(result);
      return true;
    } catch {
      if (current === generation.current) setError("试算暂不可用，请核对输入或刷新账本后重试。");
      return false;
    } finally {
      setPending(false);
      busy.current = false;
    }
  }
  async function checkRisk(): Promise<void> {
    if (context === null || busy.current) return;
    busy.current = true;
    const current = generation.current;
    setRisk(null);
    setRiskError(null);
    setRiskPending(true);
    try {
      const value = await apiClient.post<unknown, unknown>(
        "/v1/paper/risk-previews",
        context.allocation,
      );
      if (current === generation.current) setRisk(readPaperRiskPreview(value, context));
    } catch (error) {
      if (current === generation.current)
        setRiskError(
          error instanceof ApiError && error.status === 409
            ? "试算基准已变化，请重新试算。"
            : error instanceof ApiError && error.status === 403
              ? "无权执行风险检查。"
              : "风险检查暂不可用，试算结果已保留，请重试。",
        );
    } finally {
      busy.current = false;
      setRiskPending(false);
    }
  }
  return { result, pending, error, risk, riskPending, riskError, clear, preview, checkRisk };
}
