/**
 * Shared data-fetching hook with explicit loading / empty / error / forbidden
 * / success states. Built on the shared ApiClient so components never hand-roll
 * fetch calls or error handling.
 */

import { useEffect, useReducer } from "react";
import { ApiError } from "./api-client";

export type QueryStatus = "loading" | "empty" | "error" | "forbidden" | "success";

export interface QueryResult<T> {
  status: QueryStatus;
  data: T[] | null;
  error: Error | null;
}

export interface ObjectQueryResult<T> {
  status: QueryStatus;
  data: T | null;
  error: Error | null;
}

export interface QueryRefreshScheduler {
  setInterval(callback: () => void, intervalMs: number): number;
  clearInterval(intervalId: number): void;
}

export function scheduleQueryRefresh(
  callback: () => void,
  intervalMs: number,
  scheduler: QueryRefreshScheduler = window,
): () => void {
  if (intervalMs <= 0) return () => undefined;
  const intervalId = scheduler.setInterval(callback, intervalMs);
  return () => scheduler.clearInterval(intervalId);
}

type Action<T> =
  | { type: "start" }
  | { type: "success"; data: T[] }
  | { type: "empty"; data: T[] }
  | { type: "error"; error: Error }
  | { type: "forbidden"; error: Error };

function reducer<T>(state: QueryResult<T>, action: Action<T>): QueryResult<T> {
  switch (action.type) {
    case "start":
      return { status: "loading", data: null, error: null };
    case "success":
      return { status: "success", data: action.data, error: null };
    case "empty":
      return { status: "empty", data: action.data, error: null };
    case "error":
      return { status: "error", data: null, error: action.error };
    case "forbidden":
      return { status: "forbidden", data: null, error: action.error };
    default:
      return state;
  }
}

type ObjectAction<T> =
  | { type: "start" }
  | { type: "success"; data: T }
  | { type: "empty" }
  | { type: "error"; error: Error }
  | { type: "forbidden"; error: Error };

function objectReducer<T>(
  state: ObjectQueryResult<T>,
  action: ObjectAction<T>,
): ObjectQueryResult<T> {
  switch (action.type) {
    case "start":
      return { status: "loading", data: null, error: null };
    case "success":
      return { status: "success", data: action.data, error: null };
    case "empty":
      return { status: "empty", data: null, error: null };
    case "error":
      return { status: "error", data: null, error: action.error };
    case "forbidden":
      return { status: "forbidden", data: null, error: action.error };
    default:
      return state;
  }
}

export function useApiQuery<T>(
  fetcher: () => Promise<T[]>,
  deps: readonly unknown[],
): QueryResult<T> {
  const [result, dispatch] = useReducer(reducer<T>, { status: "loading", data: null, error: null });

  useEffect(() => {
    let cancelled = false;
    dispatch({ type: "start" });

    fetcher()
      .then((data) => {
        if (cancelled) return;
        dispatch({ type: data.length === 0 ? "empty" : "success", data });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 403) {
          dispatch({ type: "forbidden", error });
        } else {
          dispatch({
            type: "error",
            error: error instanceof Error ? error : new Error(String(error)),
          });
        }
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return result;
}

/** Object variant; the existing list-query data shape remains unchanged. */
export function useApiObjectQuery<T>(
  fetcher: () => Promise<T>,
  deps: readonly unknown[],
  enabled = true,
  refreshIntervalMs = 0,
): ObjectQueryResult<T> {
  const [refreshKey, refresh] = useReducer((value: number) => value + 1, 0);
  const [result, dispatch] = useReducer(objectReducer<T>, {
    status: enabled ? "loading" : "empty",
    data: null,
    error: null,
  });

  useEffect(() => {
    if (!enabled || refreshIntervalMs <= 0) return undefined;
    return scheduleQueryRefresh(refresh, refreshIntervalMs);
  }, [enabled, refreshIntervalMs]);

  useEffect(() => {
    let cancelled = false;
    if (!enabled) {
      dispatch({ type: "empty" });
      return () => {
        cancelled = true;
      };
    }
    dispatch({ type: "start" });

    fetcher()
      .then((data) => {
        if (!cancelled) dispatch({ type: "success", data });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const normalized = error instanceof Error ? error : new Error(String(error));
        if (error instanceof ApiError && error.status === 403) {
          dispatch({ type: "forbidden", error: normalized });
        } else {
          dispatch({ type: "error", error: normalized });
        }
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled, refreshKey]);

  return result;
}
