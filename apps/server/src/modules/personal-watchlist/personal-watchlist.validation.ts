import { BadRequestException } from "@nestjs/common";
import type { PersonalWatchlistImportRequest, WatchlistInputItem } from "@kunlun/shared-types";
const CODE = /^(?:[0-9]{6}\.(?:SH|SZ|BJ)|HK:[0-9]{5}|NEEQ:[0-9]{6}|SGE:AU99\.99)$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value))
    throw new BadRequestException("无效的自选导入");
  return value as Record<string, unknown>;
}
export function parseWatchlistImport(raw: unknown): PersonalWatchlistImportRequest {
  const body = object(raw);
  if (
    Object.keys(body).sort().join() !== "clientRequestId,items,schemaVersion" ||
    body.schemaVersion !== "personal-watchlist-import-v1" ||
    typeof body.clientRequestId !== "string" ||
    !UUID.test(body.clientRequestId) ||
    !Array.isArray(body.items) ||
    body.items.length < 1 ||
    body.items.length > 2000
  )
    throw new BadRequestException("无效的自选导入");
  const items = new Map<string, WatchlistInputItem>();
  for (const value of body.items as unknown[]) {
    const item = object(value);
    if (
      Object.keys(item).sort().join() !== "code,name" ||
      typeof item.code !== "string" ||
      !CODE.test(item.code) ||
      typeof item.name !== "string" ||
      item.name.trim() !== item.name ||
      [...item.name].length < 1 ||
      [...item.name].length > 80 ||
      /[<>\u0000-\u001f\u007f]/u.test(item.name)
    )
      throw new BadRequestException("自选代码或名称无效");
    if (!items.has(item.code)) items.set(item.code, { code: item.code, name: item.name });
  }
  const [first, ...rest] = [...items.values()];
  if (first === undefined) throw new BadRequestException("自选不能为空");
  return {
    schemaVersion: "personal-watchlist-import-v1",
    clientRequestId: body.clientRequestId,
    items: [first, ...rest],
  };
}
