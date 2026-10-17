import type {
  InstrumentBarsResponse,
  PersonalWatchlistImportRequest,
  PersonalWatchlistResponse,
  ServerWatchlistItem,
  WatchlistInputItem,
  WatchlistMarketState,
} from "@kunlun/shared-types";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiClient, type ApiClient } from "@/lib/api-client";
import { useApiObjectQuery } from "@/lib/use-api-query";
import { instrumentBarsPath, instrumentBarsQuery } from "./use-instrument-bars";
import {
  completePersonalWatchlistMigration,
  getOrCreatePersonalWatchlistMigration,
  isPersonalWatchlistCode,
  parseWatchlistText,
  personalWatchlistMigrationKey,
  readPersonalWatchlist,
  readPersonalWatchlistMigration,
  watchlistStorageKey,
  type PersonalWatchlistItem,
} from "./personal-watchlist";

const PERSONAL_WATCHLIST_PATH = "/v1/personal-watchlist";
const PERSONAL_WATCHLIST_IMPORT_PATH = `${PERSONAL_WATCHLIST_PATH}/import`;
const REFRESH_INTERVAL_MS = 30_000;

export type PersonalWatchlistNameConflict = Pick<ServerWatchlistItem, "code" | "name">;

export interface PersonalWatchlistImportResult {
  data: PersonalWatchlistResponse;
  nameConflicts: PersonalWatchlistNameConflict[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function timestamp(value: unknown): value is string | null {
  return (
    value === null ||
    (typeof value === "string" && Number.isFinite(Date.parse(value)) && value.includes("T"))
  );
}

function marketState(value: unknown): value is WatchlistMarketState {
  if (!isRecord(value)) return false;
  const statuses = ["PENDING", "RUNNING", "SUCCEEDED", "EMPTY", "FAILED", "UNSUPPORTED"];
  const errorCodes = [null, "SOURCE_ERROR", "VALIDATION_ERROR", "SYNC_ERROR", "UNSUPPORTED_MARKET"];
  return (
    statuses.includes(String(value.status)) &&
    timestamp(value.lastAttemptAt) &&
    timestamp(value.lastSuccessAt) &&
    errorCodes.includes(value.errorCode as (typeof errorCodes)[number])
  );
}

function serverWatchlistItem(value: unknown): value is ServerWatchlistItem {
  return (
    isRecord(value) &&
    typeof value.code === "string" &&
    isPersonalWatchlistCode(value.code) &&
    typeof value.name === "string" &&
    value.name.trim().length > 0 &&
    value.name.length <= 80 &&
    !/[<>\u0000-\u001f]/.test(value.name) &&
    timestamp(value.addedAt) &&
    typeof value.addedAt === "string" &&
    marketState(value.market)
  );
}

export function validatePersonalWatchlistResponse(value: unknown): PersonalWatchlistResponse {
  if (
    !isRecord(value) ||
    value.schemaVersion !== "personal-watchlist-response-v1" ||
    !Array.isArray(value.items) ||
    value.items.length > 2000 ||
    !value.items.every(serverWatchlistItem)
  ) {
    throw new Error("服务端自选响应格式无效");
  }
  const codes = new Set(value.items.map((item) => item.code));
  if (codes.size !== value.items.length) throw new Error("服务端自选包含重复代码");
  return value as unknown as PersonalWatchlistResponse;
}

function missingCodes(
  response: PersonalWatchlistResponse,
  expected: readonly PersonalWatchlistItem[],
): string[] {
  const present = new Set(response.items.map((item) => item.code));
  return expected.filter((item) => !present.has(item.code)).map((item) => item.code);
}

function nameConflicts(
  response: PersonalWatchlistResponse,
  expected: readonly PersonalWatchlistItem[],
): PersonalWatchlistNameConflict[] {
  const actual = new Map(response.items.map((item) => [item.code, item.name]));
  return expected.flatMap((item) => {
    const name = actual.get(item.code);
    return name !== undefined && name !== item.name ? [{ code: item.code, name }] : [];
  });
}

export async function loadPersonalWatchlist(
  client: Pick<ApiClient, "get"> = apiClient,
): Promise<PersonalWatchlistResponse> {
  const response: unknown = await client.get<unknown>(PERSONAL_WATCHLIST_PATH);
  return validatePersonalWatchlistResponse(response);
}

export async function importPersonalWatchlist(
  client: Pick<ApiClient, "post">,
  items: readonly PersonalWatchlistItem[],
  clientRequestId: string,
): Promise<PersonalWatchlistImportResult> {
  const request: PersonalWatchlistImportRequest = {
    schemaVersion: "personal-watchlist-import-v1",
    clientRequestId,
    items: parseWatchlistText(items.map((item) => `${item.code} ${item.name}`).join("\n")) as [
      WatchlistInputItem,
      ...WatchlistInputItem[],
    ],
  };
  const rawResponse: unknown = await client.post<PersonalWatchlistImportRequest, unknown>(
    PERSONAL_WATCHLIST_IMPORT_PATH,
    request,
  );
  const data = validatePersonalWatchlistResponse(rawResponse);
  const missing = missingCodes(data, items);
  if (missing.length > 0) {
    throw new Error(`服务端尚未确认这些代码：${missing.join("、")}`);
  }
  return { data, nameConflicts: nameConflicts(data, items) };
}

export function personalWatchlistQuotePath(code: string): string {
  return instrumentBarsPath(code);
}

export function personalWatchlistQuoteQuery(): Record<string, string> {
  return instrumentBarsQuery(null, 1);
}

type LoadStatus = "idle" | "loading" | "error" | "forbidden" | "success";
type MigrationStatus = "idle" | "migrating" | "error" | "complete";

interface PersonalWatchlistState {
  ownerId: string | null;
  status: LoadStatus;
  data: PersonalWatchlistResponse | null;
  error: Error | null;
  refreshing: boolean;
  isImporting: boolean;
  migrationStatus: MigrationStatus;
  migrationError: Error | null;
  migrationNameConflicts: PersonalWatchlistNameConflict[];
}

function initialState(ownerId: string | null): PersonalWatchlistState {
  return {
    ownerId,
    status: ownerId === null ? "idle" : "loading",
    data: null,
    error: null,
    refreshing: false,
    isImporting: false,
    migrationStatus: "idle",
    migrationError: null,
    migrationNameConflicts: [],
  };
}

function errorOf(value: unknown): Error {
  return value instanceof Error ? value : new Error(String(value));
}

function storageForMigration(ownerId: string): Storage {
  const storage = window.localStorage;
  // Access the marker key before reading to surface browser storage restrictions consistently.
  storage.getItem(personalWatchlistMigrationKey(ownerId));
  return storage;
}

function createRequestId(): string {
  const randomUUID = globalThis.crypto?.randomUUID;
  if (typeof randomUUID !== "function") throw new Error("当前浏览器无法生成安全的导入请求编号");
  return randomUUID.call(globalThis.crypto);
}

export interface UsePersonalWatchlistResult extends PersonalWatchlistState {
  refresh(): void;
  retryMigration(): Promise<void>;
  importItems(items: readonly PersonalWatchlistItem[]): Promise<PersonalWatchlistImportResult>;
}

export function usePersonalWatchlist(ownerId: string | null): UsePersonalWatchlistResult {
  const [state, setState] = useState(() => initialState(ownerId));
  const latestResponse = useRef<PersonalWatchlistResponse | null>(null);
  const refreshRef = useRef<(() => void) | null>(null);
  const retryMigrationRef = useRef<(() => Promise<void>) | null>(null);
  const mutationInFlight = useRef(false);
  const mutationVersion = useRef(0);
  const pendingImport = useRef<{ ownerId: string; fingerprint: string; requestId: string } | null>(
    null,
  );

  useEffect(() => {
    let active = true;
    let inFlight = false;
    let automaticMigrationAttempted = false;
    latestResponse.current = null;
    mutationInFlight.current = false;
    mutationVersion.current = 0;
    pendingImport.current = null;
    setState(initialState(ownerId));

    const update = (change: (previous: PersonalWatchlistState) => PersonalWatchlistState) => {
      if (!active) return;
      setState((previous) => (previous.ownerId === ownerId ? change(previous) : previous));
    };

    const migrateLegacy = async (current: PersonalWatchlistResponse): Promise<void> => {
      if (ownerId === null || typeof window === "undefined" || mutationInFlight.current) return;
      mutationInFlight.current = true;
      try {
        const storage = storageForMigration(ownerId);
        const legacy = readPersonalWatchlist(storage, watchlistStorageKey(ownerId));
        if (legacy.length === 0) return;

        const prior = readPersonalWatchlistMigration(storage, ownerId);
        const missing = missingCodes(current, legacy);
        if (
          prior?.status === "COMPLETE" &&
          prior.itemsFingerprint === JSON.stringify(legacy) &&
          missing.length === 0
        ) {
          update((previous) => ({
            ...previous,
            migrationStatus: "complete",
            migrationError: null,
            migrationNameConflicts: nameConflicts(current, legacy),
          }));
          return;
        }

        if (missing.length === 0) {
          const command = getOrCreatePersonalWatchlistMigration(storage, ownerId, legacy);
          completePersonalWatchlistMigration(storage, ownerId, command);
          update((previous) => ({
            ...previous,
            migrationStatus: "complete",
            migrationError: null,
            migrationNameConflicts: nameConflicts(current, legacy),
          }));
          return;
        }

        const command = getOrCreatePersonalWatchlistMigration(storage, ownerId, legacy);
        update((previous) => ({
          ...previous,
          migrationStatus: "migrating",
          migrationError: null,
          migrationNameConflicts: [],
        }));
        const result = await importPersonalWatchlist(apiClient, legacy, command.clientRequestId);
        if (!active) return;
        completePersonalWatchlistMigration(storage, ownerId, command);
        latestResponse.current = result.data;
        update((previous) => ({
          ...previous,
          data: result.data,
          migrationStatus: "complete",
          migrationError: null,
          migrationNameConflicts: result.nameConflicts,
        }));
      } catch (cause) {
        update((previous) => ({
          ...previous,
          migrationStatus: "error",
          migrationError: errorOf(cause),
        }));
      } finally {
        mutationInFlight.current = false;
      }
    };

    const load = async (allowAutomaticMigration: boolean): Promise<void> => {
      if (ownerId === null || inFlight) return;
      inFlight = true;
      const versionAtStart = mutationVersion.current;
      update((previous) => ({
        ...previous,
        status: previous.data === null ? "loading" : "success",
        refreshing: previous.data !== null,
        error: null,
      }));
      try {
        const data = await loadPersonalWatchlist();
        if (!active) return;
        if (versionAtStart !== mutationVersion.current) return;
        latestResponse.current = data;
        update((previous) => ({
          ...previous,
          status: "success",
          data,
          refreshing: false,
          error: null,
        }));
        if (allowAutomaticMigration && !automaticMigrationAttempted) {
          automaticMigrationAttempted = true;
          await migrateLegacy(data);
        }
      } catch (cause) {
        if (!active) return;
        if (versionAtStart !== mutationVersion.current) return;
        if (cause instanceof ApiError && cause.status === 403) {
          latestResponse.current = null;
          update((previous) => ({
            ...previous,
            status: "forbidden",
            data: null,
            refreshing: false,
            error: errorOf(cause),
          }));
        } else {
          update((previous) => ({
            ...previous,
            status: previous.data === null ? "error" : "success",
            refreshing: false,
            error: errorOf(cause),
          }));
        }
      } finally {
        inFlight = false;
      }
    };

    const retryMigration = async (): Promise<void> => {
      const data = latestResponse.current;
      if (data !== null) await migrateLegacy(data);
    };

    refreshRef.current = () => void load(true);
    retryMigrationRef.current = retryMigration;
    void load(true);
    const interval =
      ownerId === null ? null : window.setInterval(() => void load(true), REFRESH_INTERVAL_MS);

    return () => {
      active = false;
      if (interval !== null) window.clearInterval(interval);
      if (refreshRef.current !== null) refreshRef.current = null;
      if (retryMigrationRef.current === retryMigration) retryMigrationRef.current = null;
    };
  }, [ownerId]);

  const refresh = useCallback(() => refreshRef.current?.(), []);

  const retryMigration = useCallback(async () => {
    await retryMigrationRef.current?.();
  }, []);

  const importItems = useCallback(
    async (items: readonly PersonalWatchlistItem[]): Promise<PersonalWatchlistImportResult> => {
      if (ownerId === null) throw new Error("请先登录后再保存自选");
      if (mutationInFlight.current) throw new Error("自选正在保存或迁移，请稍后重试");
      const normalized = parseWatchlistText(
        items.map((item) => `${item.code} ${item.name}`).join("\n"),
      );
      const fingerprint = JSON.stringify(normalized);
      let pending = pendingImport.current;
      if (pending === null || pending.ownerId !== ownerId || pending.fingerprint !== fingerprint) {
        pending = { ownerId, fingerprint, requestId: createRequestId() };
        pendingImport.current = pending;
      }
      mutationInFlight.current = true;
      setState((previous) =>
        previous.ownerId === ownerId ? { ...previous, isImporting: true } : previous,
      );
      try {
        const result = await importPersonalWatchlist(apiClient, normalized, pending.requestId);
        mutationVersion.current += 1;
        latestResponse.current = result.data;
        setState((previous) =>
          previous.ownerId === ownerId
            ? {
                ...previous,
                status: "success",
                data: result.data,
                error: null,
                isImporting: false,
              }
            : previous,
        );
        pendingImport.current = null;
        return result;
      } catch (cause) {
        setState((previous) =>
          previous.ownerId === ownerId ? { ...previous, isImporting: false } : previous,
        );
        throw cause;
      } finally {
        mutationInFlight.current = false;
      }
    },
    [ownerId],
  );

  const viewState = state.ownerId === ownerId ? state : initialState(ownerId);
  return { ...viewState, refresh, retryMigration, importItems };
}

export function usePersonalWatchlistQuote(code: string, enabled: boolean) {
  const canQuery = enabled && /^[0-9]{6}\.(SH|SZ|BJ)$/.test(code);
  return useApiObjectQuery(
    () =>
      apiClient.get<InstrumentBarsResponse>(
        personalWatchlistQuotePath(code),
        personalWatchlistQuoteQuery(),
      ),
    [code],
    canQuery,
    REFRESH_INTERVAL_MS,
  );
}
