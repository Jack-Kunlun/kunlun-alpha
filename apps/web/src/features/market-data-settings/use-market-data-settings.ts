import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiClient, type ApiClient } from "@/lib/api-client";
import {
  getMarketDataSettings,
  isDefaultMarketDataSettings,
  marketDataSettingsErrorMessage,
  updateMarketDataSettings,
  type MarketDataSettingsUpdatePayload,
} from "./market-data-settings-client";
import type { MarketDataSettingsResponse } from "@kunlun/shared-types";

export type MarketDataSettingsQueryStatus =
  "loading" | "empty" | "error" | "forbidden" | "unavailable" | "success";

export interface MarketDataSettingsQuery {
  status: MarketDataSettingsQueryStatus;
  data: MarketDataSettingsResponse | null;
  error: Error | null;
}

export interface UseMarketDataSettingsResult {
  query: MarketDataSettingsQuery;
  saving: boolean;
  saveError: string | null;
  saved: boolean;
  refresh(): void;
  save(update: MarketDataSettingsUpdatePayload): Promise<MarketDataSettingsResponse | null>;
  clearSaveError(): void;
}

function queryForResponse(data: MarketDataSettingsResponse): MarketDataSettingsQuery {
  return {
    status: isDefaultMarketDataSettings(data) ? "empty" : "success",
    data,
    error: null,
  };
}

function queryForError(error: unknown): MarketDataSettingsQuery {
  const normalized = new Error(marketDataSettingsErrorMessage(error));
  if (error instanceof ApiError && error.status === 403) {
    return { status: "forbidden", data: null, error: normalized };
  }
  if (error instanceof ApiError && error.status === 503) {
    return { status: "unavailable", data: null, error: normalized };
  }
  return { status: "error", data: null, error: normalized };
}

const INITIAL_QUERY: MarketDataSettingsQuery = {
  status: "loading",
  data: null,
  error: null,
};

export function useMarketDataSettings(client: ApiClient = apiClient): UseMarketDataSettingsResult {
  const [query, setQuery] = useState<MarketDataSettingsQuery>(INITIAL_QUERY);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const mountedRef = useRef(false);
  const operationRef = useRef(0);
  const savingRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      operationRef.current += 1;
    };
  }, []);

  useEffect(() => {
    const operation = ++operationRef.current;
    let active = true;
    void getMarketDataSettings(client)
      .then((data) => {
        if (!active || !mountedRef.current || operation !== operationRef.current) return;
        setQuery(queryForResponse(data));
      })
      .catch((error: unknown) => {
        if (!active || !mountedRef.current || operation !== operationRef.current) return;
        setQuery(queryForError(error));
      });
    return () => {
      active = false;
    };
  }, [client, refreshVersion]);

  const refresh = useCallback(() => {
    if (savingRef.current) return;
    setSaveError(null);
    setSaved(false);
    setQuery({ status: "loading", data: null, error: null });
    setRefreshVersion((value) => value + 1);
  }, []);

  const clearSaveError = useCallback(() => setSaveError(null), []);

  const save = useCallback(
    async (update: MarketDataSettingsUpdatePayload) => {
      if (savingRef.current) return null;
      savingRef.current = true;
      setSaving(true);
      setSaveError(null);
      setSaved(false);
      const operation = ++operationRef.current;
      try {
        const data = await updateMarketDataSettings(client, update);
        if (!mountedRef.current || operation !== operationRef.current) return null;
        setQuery(queryForResponse(data));
        setSaved(true);
        return data;
      } catch (error: unknown) {
        if (mountedRef.current && operation === operationRef.current) {
          setSaveError(marketDataSettingsErrorMessage(error));
        }
        return null;
      } finally {
        savingRef.current = false;
        if (mountedRef.current && operation === operationRef.current) setSaving(false);
      }
    },
    [client],
  );

  return {
    query,
    saving,
    saveError,
    saved,
    refresh,
    save,
    clearSaveError,
  };
}
