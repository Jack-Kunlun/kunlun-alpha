import type { WatchlistInputItem } from "@kunlun/shared-types";

export type PersonalWatchlistItem = WatchlistInputItem;

export interface WatchlistStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export interface PersonalWatchlistMigrationCommand {
  schemaVersion: "personal-watchlist-migration-v1";
  itemsFingerprint: string;
  clientRequestId: string;
  status: "PENDING" | "COMPLETE";
}

const CANONICAL_INSTRUMENT = /^[0-9]{6}\.(SH|SZ|BJ)$/;
const OBSERVATION_REFERENCE = /^(?:HK:[0-9]{5}|NEEQ:[0-9]{6}|SGE:AU99\.99)$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const MAX_ITEMS = 2000;

export function watchlistStorageKey(ownerId: string): string {
  if (!ownerId) throw new Error("请先登录后再迁移自选");
  return `kunlun:personal-watchlist:v1:${encodeURIComponent(ownerId)}`;
}

export function personalWatchlistMigrationKey(ownerId: string): string {
  if (!ownerId) throw new Error("请先登录后再迁移自选");
  return `kunlun:personal-watchlist-migration:v1:${encodeURIComponent(ownerId)}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isPersonalWatchlistCode(value: string): boolean {
  return CANONICAL_INSTRUMENT.test(value) || OBSERVATION_REFERENCE.test(value);
}

function validItem(value: unknown): value is PersonalWatchlistItem {
  if (!isRecord(value)) return false;
  return (
    typeof value.code === "string" &&
    isPersonalWatchlistCode(value.code) &&
    typeof value.name === "string" &&
    value.name.trim().length > 0 &&
    value.name.length <= 80 &&
    !/[<>\u0000-\u001f]/.test(value.name)
  );
}

function uniqueItems(items: readonly PersonalWatchlistItem[]): PersonalWatchlistItem[] {
  const unique = new Map<string, PersonalWatchlistItem>();
  for (const item of items) if (!unique.has(item.code)) unique.set(item.code, item);
  if (unique.size > MAX_ITEMS) throw new Error(`自选数量不能超过 ${MAX_ITEMS} 项`);
  return [...unique.values()];
}

export function parseWatchlistText(text: string): PersonalWatchlistItem[] {
  if (text.length > 250_000) throw new Error("导入内容过长，请分批添加");
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length === 0 || lines.length > MAX_ITEMS)
    throw new Error(`请填写 1–${MAX_ITEMS} 行自选代码与名称`);
  return uniqueItems(
    lines.map((line, index) => {
      const match = /^(\S+)\s+(.+)$/.exec(line);
      const item = { code: match?.[1]?.toUpperCase() ?? "", name: match?.[2]?.trim() ?? "" };
      if (!validItem(item)) throw new Error(`第 ${index + 1} 行格式无效，请使用“统一代码 名称”`);
      return item;
    }),
  );
}

/** Reads the previous browser list as a migration source and never writes to it. */
export function readPersonalWatchlist(
  storage: Pick<WatchlistStorage, "getItem">,
  key: string,
): PersonalWatchlistItem[] {
  const raw = storage.getItem(key);
  if (raw === null) return [];
  try {
    const data: unknown = JSON.parse(raw);
    if (!isRecord(data)) throw new Error();
    if (
      data.schemaVersion !== "personal-watchlist-v1" ||
      !Array.isArray(data.items) ||
      data.items.length > MAX_ITEMS ||
      !data.items.every(validItem)
    )
      throw new Error();
    const items = uniqueItems(data.items);
    if (items.length !== data.items.length) throw new Error();
    return items;
  } catch {
    throw new Error("本机自选备份无法读取，原内容已保留，请检查浏览器存储后重试");
  }
}

function fingerprint(items: readonly PersonalWatchlistItem[]): string {
  return JSON.stringify(uniqueItems(items));
}

function isMigrationCommand(value: unknown): value is PersonalWatchlistMigrationCommand {
  return (
    isRecord(value) &&
    value.schemaVersion === "personal-watchlist-migration-v1" &&
    typeof value.itemsFingerprint === "string" &&
    typeof value.clientRequestId === "string" &&
    UUID.test(value.clientRequestId) &&
    (value.status === "PENDING" || value.status === "COMPLETE")
  );
}

export function readPersonalWatchlistMigration(
  storage: Pick<WatchlistStorage, "getItem">,
  ownerId: string,
): PersonalWatchlistMigrationCommand | null {
  const raw = storage.getItem(personalWatchlistMigrationKey(ownerId));
  if (raw === null) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (!isMigrationCommand(value)) throw new Error();
    return value;
  } catch {
    throw new Error("本机迁移记录无法读取，原自选备份仍保留");
  }
}

function createRequestId(): string {
  const randomUUID = globalThis.crypto?.randomUUID;
  if (typeof randomUUID !== "function") throw new Error("当前浏览器无法生成安全的迁移请求编号");
  return randomUUID.call(globalThis.crypto);
}

/** Reuses a pending id after a lost response; a completed snapshot gets a fresh id if retried. */
export function getOrCreatePersonalWatchlistMigration(
  storage: WatchlistStorage,
  ownerId: string,
  items: readonly PersonalWatchlistItem[],
  requestIdFactory: () => string = createRequestId,
): PersonalWatchlistMigrationCommand {
  const itemsFingerprint = fingerprint(items);
  const existing = readPersonalWatchlistMigration(storage, ownerId);
  if (existing?.itemsFingerprint === itemsFingerprint && existing.status === "PENDING") {
    return existing;
  }
  const clientRequestId = requestIdFactory();
  if (!UUID.test(clientRequestId)) throw new Error("迁移请求编号无效");
  const command: PersonalWatchlistMigrationCommand = {
    schemaVersion: "personal-watchlist-migration-v1",
    itemsFingerprint,
    clientRequestId,
    status: "PENDING",
  };
  storage.setItem(personalWatchlistMigrationKey(ownerId), JSON.stringify(command));
  return command;
}

export function completePersonalWatchlistMigration(
  storage: WatchlistStorage,
  ownerId: string,
  command: PersonalWatchlistMigrationCommand,
): PersonalWatchlistMigrationCommand {
  const current = readPersonalWatchlistMigration(storage, ownerId);
  if (
    current === null ||
    current.clientRequestId !== command.clientRequestId ||
    current.itemsFingerprint !== command.itemsFingerprint
  ) {
    throw new Error("迁移记录已变化，原自选备份仍保留");
  }
  const completed: PersonalWatchlistMigrationCommand = { ...current, status: "COMPLETE" };
  storage.setItem(personalWatchlistMigrationKey(ownerId), JSON.stringify(completed));
  return completed;
}

export function personalWatchlistHref(item: PersonalWatchlistItem): string | null {
  return CANONICAL_INSTRUMENT.test(item.code) ? `/instruments/${item.code}` : null;
}
