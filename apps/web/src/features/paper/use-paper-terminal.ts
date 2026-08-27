"use client";

import { useCallback, useEffect, useState } from "react";
import type {
  PaperTerminalCreateAccountCommand,
  PaperTerminalSimulationCommand,
  PaperTerminalWorkspace,
} from "@kunlun/shared-types";
import { apiClient } from "@/lib/api-client";

export type PaperTerminalState =
  "loading" | "empty" | "ready" | "unavailable" | "forbidden" | "error";

export function usePaperTerminal() {
  const [workspace, setWorkspace] = useState<PaperTerminalWorkspace | null>(null);
  const [state, setState] = useState<PaperTerminalState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const accept = useCallback((value: PaperTerminalWorkspace) => {
    setWorkspace(value);
    setState(
      value.status === "EMPTY" ? "empty" : value.status === "UNAVAILABLE" ? "unavailable" : "ready",
    );
    setError(null);
  }, []);

  const refresh = useCallback(async () => {
    setState("loading");
    try {
      accept(await apiClient.get<PaperTerminalWorkspace>("/v1/paper/workspace"));
    } catch (cause) {
      setFailure(cause, setState, setError);
    }
  }, [accept]);

  useEffect(() => {
    let active = true;
    void apiClient
      .get<PaperTerminalWorkspace>("/v1/paper/workspace")
      .then((value) => {
        if (active) accept(value);
      })
      .catch((cause: unknown) => {
        if (active) setFailure(cause, setState, setError);
      });
    return () => {
      active = false;
    };
  }, [accept]);

  const createAccount = useCallback(
    async (command: PaperTerminalCreateAccountCommand) => {
      setSubmitting(true);
      try {
        accept(
          await apiClient.post<PaperTerminalCreateAccountCommand, PaperTerminalWorkspace>(
            "/v1/paper/accounts",
            command,
          ),
        );
      } finally {
        setSubmitting(false);
      }
    },
    [accept],
  );

  const simulate = useCallback(
    async (command: PaperTerminalSimulationCommand) => {
      setSubmitting(true);
      try {
        accept(
          await apiClient.post<PaperTerminalSimulationCommand, PaperTerminalWorkspace>(
            "/v1/paper/simulations",
            command,
          ),
        );
      } finally {
        setSubmitting(false);
      }
    },
    [accept],
  );

  return { workspace, state, error, submitting, refresh, createAccount, simulate };
}

export function paperRequestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function setFailure(
  cause: unknown,
  setState: (state: PaperTerminalState) => void,
  setError: (message: string) => void,
) {
  const status =
    typeof cause === "object" && cause !== null && "status" in cause
      ? (cause as { status?: unknown }).status
      : null;
  setState(status === 401 || status === 403 ? "forbidden" : "error");
  setError(cause instanceof Error ? cause.message : "模拟组合工作区加载失败");
}
