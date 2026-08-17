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
          dispatch({ type: "error", error: error instanceof Error ? error : new Error(String(error)) });
        }
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return result;
}
