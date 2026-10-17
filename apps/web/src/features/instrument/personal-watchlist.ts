export interface PersonalWatchlistItem {
  code: string;
  name: string;
}

export interface WatchlistStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const CANONICAL_INSTRUMENT = /^[0-9]{6}\.(SH|SZ|BJ)$/;
const OBSERVATION_REFERENCE = /^(?:HK:[0-9]{5}|NEEQ:[0-9]{6}|SGE:AU99\.99)$/;
const MAX_ITEMS = 2000;

export function watchlistStorageKey(ownerId: string): string {
  if (!ownerId) throw new Error("请先登录后再导入自选");
  return `kunlun:personal-watchlist:v1:${encodeURIComponent(ownerId)}`;
}

function validItem(value: unknown): value is PersonalWatchlistItem {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Record<string, unknown>;
  return (
    typeof item.code === "string" &&
    (CANONICAL_INSTRUMENT.test(item.code) || OBSERVATION_REFERENCE.test(item.code)) &&
    typeof item.name === "string" &&
    item.name.trim().length > 0 &&
    item.name.length <= 80 &&
    !/[<>\u0000-\u001f]/.test(item.name)
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

export function readPersonalWatchlist(
  storage: WatchlistStorage,
  key: string,
): PersonalWatchlistItem[] {
  const raw = storage.getItem(key);
  if (raw === null) return [];
  try {
    const data: unknown = JSON.parse(raw);
    if (typeof data !== "object" || data === null) throw new Error();
    const record = data as Record<string, unknown>;
    if (
      record.schemaVersion !== "personal-watchlist-v1" ||
      !Array.isArray(record.items) ||
      record.items.length > MAX_ITEMS ||
      !record.items.every(validItem)
    )
      throw new Error();
    const items = uniqueItems(record.items);
    if (items.length !== record.items.length) throw new Error();
    return items;
  } catch {
    throw new Error("本机自选数据无法读取，已保留原内容，请恢复数据后重试");
  }
}

/** Called under a browser Web Lock; merge with the latest stored list before writing. */
export function savePersonalWatchlist(
  storage: WatchlistStorage,
  key: string,
  incoming: readonly PersonalWatchlistItem[],
): PersonalWatchlistItem[] {
  if (!incoming.every(validItem)) throw new Error("导入内容无效");
  const items = uniqueItems([...readPersonalWatchlist(storage, key), ...incoming]);
  storage.setItem(key, JSON.stringify({ schemaVersion: "personal-watchlist-v1", items }));
  return items;
}

export function personalWatchlistHref(item: PersonalWatchlistItem): string | null {
  return CANONICAL_INSTRUMENT.test(item.code) ? `/instruments/${item.code}` : null;
}
