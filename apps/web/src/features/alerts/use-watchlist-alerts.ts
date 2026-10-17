"use client";

import { useCallback, useEffect, useState } from "react";
import type {
  UpdateWatchlistAlertRuleRequest,
  WatchlistAlertEvaluationRun,
  WatchlistAlertsWorkspace,
} from "@kunlun/shared-types";
import { apiClient } from "../../lib/api-client";

export type WatchlistAlertRule = WatchlistAlertsWorkspace["rules"][number];

export interface CreateWatchlistAlertRuleRequest {
  clientRequestId: string;
  name: string;
  enabled: boolean;
  instrumentIds: string[];
  condition: WatchlistAlertRule["condition"];
  quietPeriod: WatchlistAlertRule["quietPeriod"];
  throttleSeconds: number;
  notificationChannel: "IN_APP";
}

export interface PreviewWatchlistAlertRequest {
  ruleId: string;
  eventId: string;
  instrumentId: string;
  field: WatchlistAlertRule["condition"]["field"];
  featureName: string | null;
  observedValue: string;
  eventTime: string;
  availableTime: string;
}

export interface AlertPreview {
  outcome: WatchlistAlertsWorkspace["history"][number]["outcome"];
  detail: string;
}

type LoadState = "loading" | "ready" | "empty" | "forbidden" | "error";

export function useWatchlistAlerts() {
  const [workspace, setWorkspace] = useState<WatchlistAlertsWorkspace | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const accept = useCallback((next: WatchlistAlertsWorkspace) => {
    setWorkspace(next);
    setState(next.rules.length === 0 && next.history.length === 0 ? "empty" : "ready");
    setError(null);
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setState((current) => (current === "ready" || current === "empty" ? current : "loading"));
    setError(null);
    try {
      accept(await apiClient.get<WatchlistAlertsWorkspace>("/v1/watchlist-alerts"));
    } catch (cause) {
      const status = httpStatus(cause);
      setState((current) =>
        status === 401 || status === 403
          ? "forbidden"
          : current === "ready" || current === "empty"
            ? current
            : "error",
      );
      setError(message(cause));
    } finally {
      setRefreshing(false);
    }
  }, [accept]);

  useEffect(() => {
    let active = true;
    void apiClient
      .get<WatchlistAlertsWorkspace>("/v1/watchlist-alerts")
      .then((next) => {
        if (active) accept(next);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        const status = httpStatus(cause);
        setState(status === 401 || status === 403 ? "forbidden" : "error");
        setError(message(cause));
      });
    return () => {
      active = false;
    };
  }, [accept]);

  const createRule = useCallback(
    async (request: CreateWatchlistAlertRuleRequest) => {
      setSubmitting(true);
      try {
        accept(
          await apiClient.post<CreateWatchlistAlertRuleRequest, WatchlistAlertsWorkspace>(
            "/v1/watchlist-alerts/rules",
            request,
          ),
        );
      } finally {
        setSubmitting(false);
      }
    },
    [accept],
  );

  const toggleRule = useCallback(
    async (ruleId: string, enabled: boolean) => {
      setSubmitting(true);
      try {
        accept(
          await apiClient.post<
            { clientRequestId: string; enabled: boolean },
            WatchlistAlertsWorkspace
          >(`/v1/watchlist-alerts/rules/${ruleId}/toggle`, {
            clientRequestId: requestId("toggle"),
            enabled,
          }),
        );
      } finally {
        setSubmitting(false);
      }
    },
    [accept],
  );

  const updateRule = useCallback(
    async (ruleId: string, request: UpdateWatchlistAlertRuleRequest) => {
      setSubmitting(true);
      try {
        accept(
          await apiClient.post<UpdateWatchlistAlertRuleRequest, WatchlistAlertsWorkspace>(
            `/v1/watchlist-alerts/rules/${encodeURIComponent(ruleId)}`,
            request,
          ),
        );
      } finally {
        setSubmitting(false);
      }
    },
    [accept],
  );

  const preview = useCallback(async (request: PreviewWatchlistAlertRequest) => {
    return apiClient.post<PreviewWatchlistAlertRequest, AlertPreview>(
      "/v1/watchlist-alerts/preview",
      request,
    );
  }, []);

  const evaluateLatest = useCallback(async (): Promise<WatchlistAlertEvaluationRun> => {
    setSubmitting(true);
    try {
      const result = await apiClient.post<Record<string, never>, WatchlistAlertEvaluationRun>(
        "/v1/watchlist-alerts/evaluate-latest",
        {},
      );
      await refresh();
      return result;
    } finally {
      setSubmitting(false);
    }
  }, [refresh]);

  return {
    workspace,
    state,
    error,
    submitting,
    refreshing,
    refresh,
    createRule,
    toggleRule,
    updateRule,
    preview,
    evaluateLatest,
  };
}

export function requestId(action: string): string {
  return `${action}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function httpStatus(error: unknown): number | null {
  if (typeof error !== "object" || error === null) return null;
  const candidate = error as { status?: unknown; response?: { status?: unknown } };
  if (typeof candidate.status === "number") return candidate.status;
  return typeof candidate.response?.status === "number" ? candidate.response.status : null;
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : "预警工作区加载失败";
}
