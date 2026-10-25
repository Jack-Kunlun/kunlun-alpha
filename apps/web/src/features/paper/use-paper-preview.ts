import { useState } from "react";
import { apiClient } from "@/lib/api-client";
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
  function clear() {
    setResult(null);
    setError(null);
  }
  async function preview(values: PaperPreviewFormValues): Promise<boolean> {
    if (pending) return false;
    clear();
    const parsed = buildPaperPreviewCommand(values, paperRequestId("preview"));
    if (parsed.command === null) {
      setError(parsed.error);
      return false;
    }
    setPending(true);
    try {
      const value = await apiClient.post<typeof parsed.command, unknown>(
        "/v1/paper/previews",
        parsed.command,
      );
      setResult(readPaperPreview(value, parsed.command, accountId));
      return true;
    } catch {
      setError("试算暂不可用，请核对输入或刷新账本后重试。");
      return false;
    } finally {
      setPending(false);
    }
  }
  return { result, pending, error, clear, preview };
}
