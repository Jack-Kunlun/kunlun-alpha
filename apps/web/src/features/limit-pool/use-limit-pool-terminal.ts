import type { LimitPoolTerminalSnapshot } from "@kunlun/shared-types";
import { useEffect, useState } from "react";
import { ApiError, apiClient, type ApiClient } from "@/lib/api-client";

interface LimitPoolTerminalQueryBase {
  mode: "CURRENT" | "HISTORICAL";
  asOf?: string;
}

type NoLimitPoolVersionSelector = {
  algorithmVersion?: never;
  ladderAlgorithmVersion?: never;
  limitRuleVersion?: never;
  materializerVersion?: never;
};

type CompleteLimitPoolVersionSelector = {
  algorithmVersion: string;
  ladderAlgorithmVersion: string;
  limitRuleVersion: string;
  materializerVersion: string;
};

export type LimitPoolTerminalQuery = LimitPoolTerminalQueryBase &
  (NoLimitPoolVersionSelector | CompleteLimitPoolVersionSelector);

export type LimitPoolTerminalResult =
  | { status: "loading"; data: null; error: null }
  | { status: "success"; data: LimitPoolTerminalSnapshot; error: null }
  | { status: "forbidden"; data: null; error: Error }
  | { status: "error"; data: null; error: Error };

export function refreshIntervalForMode(mode: LimitPoolTerminalQuery["mode"]): number | null {
  return mode === "CURRENT" ? 30_000 : null;
}

export function requestLimitPoolTerminal(
  client: ApiClient,
  query: LimitPoolTerminalQuery,
): Promise<LimitPoolTerminalSnapshot> {
  const suppliedVersionCount = [
    query.algorithmVersion,
    query.ladderAlgorithmVersion,
    query.limitRuleVersion,
    query.materializerVersion,
  ].filter((value) => value !== undefined).length;
  if (suppliedVersionCount !== 0 && suppliedVersionCount !== 4) {
    return Promise.reject(new Error("limit-pool version vector must be complete"));
  }
  return client.get<LimitPoolTerminalSnapshot>("/v1/limit-pool", {
    mode: query.mode,
    ...(query.asOf === undefined ? {} : { asOf: query.asOf }),
    ...(query.algorithmVersion === undefined ? {} : { algorithmVersion: query.algorithmVersion }),
    ...(query.ladderAlgorithmVersion === undefined
      ? {}
      : { ladderAlgorithmVersion: query.ladderAlgorithmVersion }),
    ...(query.limitRuleVersion === undefined ? {} : { limitRuleVersion: query.limitRuleVersion }),
    ...(query.materializerVersion === undefined
      ? {}
      : { materializerVersion: query.materializerVersion }),
  });
}

export function useLimitPoolTerminal(
  query: LimitPoolTerminalQuery,
  enabled = true,
): LimitPoolTerminalResult {
  const {
    mode,
    asOf,
    algorithmVersion,
    ladderAlgorithmVersion,
    limitRuleVersion,
    materializerVersion,
  } = query;
  const [result, setResult] = useState<LimitPoolTerminalResult>({
    status: "loading",
    data: null,
    error: null,
  });

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    let latestRequest = 0;
    const load = async (): Promise<void> => {
      const requestId = ++latestRequest;
      try {
        const data = await requestLimitPoolTerminal(apiClient, {
          mode,
          ...(asOf === undefined ? {} : { asOf }),
          ...(algorithmVersion === undefined ? {} : { algorithmVersion }),
          ...(ladderAlgorithmVersion === undefined ? {} : { ladderAlgorithmVersion }),
          ...(limitRuleVersion === undefined ? {} : { limitRuleVersion }),
          ...(materializerVersion === undefined ? {} : { materializerVersion }),
        } as LimitPoolTerminalQuery);
        if (active && requestId === latestRequest) {
          setResult({ status: "success", data, error: null });
        }
      } catch (caught) {
        if (!active || requestId !== latestRequest) return;
        const error = caught instanceof Error ? caught : new Error("未知错误");
        setResult({
          status: caught instanceof ApiError && caught.status === 403 ? "forbidden" : "error",
          data: null,
          error,
        });
      }
    };
    void load();
    const interval = refreshIntervalForMode(mode);
    const timer = interval === null ? undefined : window.setInterval(() => void load(), interval);
    return () => {
      active = false;
      if (timer !== undefined) window.clearInterval(timer);
    };
  }, [
    algorithmVersion,
    asOf,
    enabled,
    ladderAlgorithmVersion,
    limitRuleVersion,
    materializerVersion,
    mode,
  ]);

  return result;
}
