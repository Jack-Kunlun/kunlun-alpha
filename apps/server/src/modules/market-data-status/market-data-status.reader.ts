import { constants } from "node:fs";
import { lstat, open } from "node:fs/promises";
import { join } from "node:path";
import type { MarketDataSyncStatus } from "@kunlun/shared-types";

const SCHEMA_VERSION = "market-data-sync-status-v1" as const;
const MAX_BYTES = 65_536;
const RUN_UNCONFIRMED_AFTER_MS = 15 * 60_000;
const FIELDS = [
  "schemaVersion",
  "status",
  "provider",
  "symbols",
  "lastAttemptAt",
  "lastFinishedAt",
  "lastSuccessAt",
  "lastSuccessResult",
  "errorCode",
] as const;
const RESULT_FIELDS = ["requests", "receivedBars", "writtenBars", "dailyRefreshed"] as const;
const WORKER_ERRORS = ["SOURCE_ERROR", "VALIDATION_ERROR", "SYNC_ERROR"] as const;
type StatusError = NonNullable<MarketDataSyncStatus["errorCode"]>;

function object(value: unknown, fields: readonly string[]): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error();
  const result = value as Record<string, unknown>;
  const keys = Object.keys(result);
  if (keys.length !== fields.length || keys.some((key) => !fields.includes(key))) throw new Error();
  return result;
}

function timestamp(value: unknown, now: number): number | null {
  if (value === null) return null;
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,9})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(
      value,
    )
  )
    throw new Error();
  const instant = Date.parse(value);
  const day = value.slice(0, 10);
  if (
    !Number.isFinite(instant) ||
    instant > now + 60_000 ||
    new Date(`${day}T00:00:00Z`).toISOString().slice(0, 10) !== day
  )
    throw new Error();
  return instant;
}

function parse(value: unknown, now: number): MarketDataSyncStatus {
  const data = object(value, FIELDS);
  if (
    data["schemaVersion"] !== SCHEMA_VERSION ||
    !["RUNNING", "SUCCEEDED", "FAILED"].includes(String(data["status"])) ||
    !["akshare", "tushare"].includes(String(data["provider"]))
  )
    throw new Error();
  const symbols = data["symbols"];
  if (
    !Array.isArray(symbols) ||
    symbols.length < 1 ||
    symbols.length > 100 ||
    symbols.some(
      (symbol: unknown) => typeof symbol !== "string" || !/^\d{6}\.(SH|SZ|BJ)$/.test(symbol),
    ) ||
    new Set(symbols).size !== symbols.length
  )
    throw new Error();
  const attempt = timestamp(data["lastAttemptAt"], now);
  const finished = timestamp(data["lastFinishedAt"], now);
  const success = timestamp(data["lastSuccessAt"], now);
  if (attempt === null || (finished !== null && finished < attempt)) throw new Error();
  const result = data["lastSuccessResult"];
  if ((success === null) !== (result === null)) throw new Error();
  if (result !== null) {
    const counts = object(result, RESULT_FIELDS);
    for (const field of ["requests", "receivedBars", "writtenBars"]) {
      if (!Number.isSafeInteger(counts[field]) || (counts[field] as number) < 0) throw new Error();
    }
    if (
      typeof counts["dailyRefreshed"] !== "boolean" ||
      (counts["writtenBars"] as number) > (counts["receivedBars"] as number)
    )
      throw new Error();
  }
  if (data["status"] === "RUNNING") {
    if (finished !== null || data["errorCode"] !== null || (success !== null && success > attempt))
      throw new Error();
  } else if (data["status"] === "SUCCEEDED") {
    if (finished === null || success !== finished || result === null || data["errorCode"] !== null)
      throw new Error();
  } else if (
    finished === null ||
    !WORKER_ERRORS.includes(data["errorCode"] as (typeof WORKER_ERRORS)[number]) ||
    (success !== null && success > attempt)
  )
    throw new Error();
  // The exact closed shape and every value above are validated before crossing this boundary.
  return data as unknown as MarketDataSyncStatus;
}

export class MarketDataStatusReader {
  constructor(
    private readonly root: string | undefined,
    private readonly symbols: readonly string[],
    private readonly provider: "akshare" | "tushare" = "akshare",
    private readonly clock: () => Date = () => new Date(),
  ) {}

  private unknown(errorCode: StatusError): MarketDataSyncStatus {
    return {
      schemaVersion: SCHEMA_VERSION,
      status: "UNKNOWN",
      provider: this.provider,
      symbols: [...this.symbols],
      lastAttemptAt: null,
      lastFinishedAt: null,
      lastSuccessAt: null,
      lastSuccessResult: null,
      errorCode,
    };
  }

  async read(): Promise<MarketDataSyncStatus> {
    if (!this.root) return this.unknown("STATUS_UNAVAILABLE");
    try {
      const directory = await lstat(this.root);
      if (!directory.isDirectory() || directory.isSymbolicLink())
        return this.unknown("INVALID_STATUS");
      const path = join(this.root, "market-data-sync-status.json");
      const before = await lstat(path);
      if (!before.isFile() || before.isSymbolicLink() || before.size > MAX_BYTES)
        return this.unknown("INVALID_STATUS");
      const handle = await open(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
      let payload: unknown;
      try {
        const metadata = await handle.stat();
        if (!metadata.isFile() || metadata.size > MAX_BYTES) return this.unknown("INVALID_STATUS");
        const bytes = Buffer.alloc(MAX_BYTES + 1);
        const { bytesRead } = await handle.read(bytes, 0, bytes.length, 0);
        if (bytesRead > MAX_BYTES) return this.unknown("INVALID_STATUS");
        payload = JSON.parse(bytes.subarray(0, bytesRead).toString("utf8")) as unknown;
      } finally {
        await handle.close();
      }
      const now = this.clock().getTime();
      const status = parse(payload, now);
      if (
        status.provider !== this.provider ||
        status.symbols.length !== this.symbols.length ||
        status.symbols.some((symbol) => !this.symbols.includes(symbol))
      )
        return this.unknown("SCOPE_MISMATCH");
      if (
        status.status === "RUNNING" &&
        now - Date.parse(status.lastAttemptAt as string) > RUN_UNCONFIRMED_AFTER_MS
      )
        return { ...status, status: "UNKNOWN", errorCode: "RUN_STATUS_EXPIRED" };
      return status;
    } catch (error) {
      const code =
        typeof error === "object" && error !== null && "code" in error ? error.code : undefined;
      if (code === "ENOENT") return this.unknown("NO_RUN");
      if (code === "EACCES" || code === "EPERM") return this.unknown("STATUS_UNAVAILABLE");
      return this.unknown("INVALID_STATUS");
    }
  }
}
