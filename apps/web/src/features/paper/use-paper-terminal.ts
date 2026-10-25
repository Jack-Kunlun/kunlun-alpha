"use client";

import { useCallback, useEffect, useState } from "react";
import type {
  PaperTerminalCreateAccountCommand,
  PaperTerminalWorkspace,
} from "@kunlun/shared-types";
import { apiClient } from "@/lib/api-client";

export type PaperTerminalState =
  "loading" | "empty" | "ready" | "unavailable" | "forbidden" | "error";

export function usePaperTerminal() {
  const [workspace, setWorkspace] = useState<PaperTerminalWorkspace | null>(null);
  const [state, setState] = useState<PaperTerminalState>("loading");
  const [submitting, setSubmitting] = useState(false);

  const accept = useCallback((value: PaperTerminalWorkspace) => {
    setWorkspace(value);
    setState(
      value.status === "EMPTY" ? "empty" : value.status === "UNAVAILABLE" ? "unavailable" : "ready",
    );
  }, []);

  const refresh = useCallback(async (): Promise<boolean> => {
    setState("loading");
    try {
      accept(await apiClient.get<PaperTerminalWorkspace>("/v1/paper/workspace"));
      return true;
    } catch (cause) {
      setFailure(cause, setState);
      return false;
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
        if (active) setFailure(cause, setState);
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

  return { workspace, state, submitting, refresh, createAccount, accept };
}

export function paperRequestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function setFailure(cause: unknown, setState: (state: PaperTerminalState) => void) {
  const status =
    typeof cause === "object" && cause !== null && "status" in cause
      ? (cause as { status?: unknown }).status
      : null;
  setState(status === 401 || status === 403 ? "forbidden" : "error");
}
