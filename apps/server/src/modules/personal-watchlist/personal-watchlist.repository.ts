import { createHash } from "node:crypto";
import type {
  PersonalWatchlistImportRequest,
  PersonalWatchlistResponse,
  WatchlistMarketState,
} from "@kunlun/shared-types";
import type { OnModuleDestroy } from "@nestjs/common";
import { BadRequestException, ConflictException, Injectable } from "@nestjs/common";
import type { Pool } from "pg";
interface Row {
  code: string;
  name: string;
  added_at: Date;
  status: WatchlistMarketState["status"] | null;
  last_attempt_at: Date | null;
  last_success_at: Date | null;
  error_code: WatchlistMarketState["errorCode"];
}
@Injectable()
export class PersonalWatchlistRepository implements OnModuleDestroy {
  constructor(private readonly pool: Pool) {}
  async onModuleDestroy(): Promise<void> {
    await this.pool.end();
  }
  async list(ownerId: string): Promise<PersonalWatchlistResponse> {
    const { rows } = await this.pool.query<Row>(
      `SELECT i.code, i.name, i.added_at, s.status, s.last_attempt_at, s.last_success_at, s.error_code
      FROM personal_watchlist_items i LEFT JOIN personal_watchlist_market_state s ON s.code=i.code
      WHERE i.owner_id=$1 ORDER BY i.position`,
      [ownerId],
    );
    return {
      schemaVersion: "personal-watchlist-response-v1",
      items: rows.map((row) => ({
        code: row.code,
        name: row.name,
        addedAt: row.added_at.toISOString(),
        market: {
          status: row.status ?? "PENDING",
          lastAttemptAt: row.last_attempt_at?.toISOString() ?? null,
          lastSuccessAt: row.last_success_at?.toISOString() ?? null,
          errorCode: row.error_code,
        },
      })),
    };
  }
  async importItems(
    ownerId: string,
    command: PersonalWatchlistImportRequest,
  ): Promise<PersonalWatchlistResponse> {
    const hash = createHash("sha256").update(JSON.stringify(command.items)).digest("hex");
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", [
        "personal-watchlist:" + ownerId,
      ]);
      const previous = await client.query<{ command_hash: string }>(
        "SELECT command_hash FROM personal_watchlist_imports WHERE owner_id=$1 AND client_request_id=$2",
        [ownerId, command.clientRequestId],
      );
      if (previous.rows[0]) {
        if (previous.rows[0].command_hash !== hash)
          throw new ConflictException("导入请求已被其他内容使用");
      } else {
        const existing = await client.query<{ code: string }>(
          "SELECT code FROM personal_watchlist_items WHERE owner_id=$1",
          [ownerId],
        );
        if (
          new Set([...existing.rows.map((x) => x.code), ...command.items.map((x) => x.code)]).size >
          2000
        )
          throw new BadRequestException("自选最多保存 2000 项");
        await client.query(
          `INSERT INTO personal_watchlist_items(owner_id, code, name, added_at, position)
          SELECT $1, item->>'code', item->>'name', now(),
            (SELECT COALESCE(MAX(position),0) FROM personal_watchlist_items WHERE owner_id=$1)+ordinal
          FROM jsonb_array_elements($2::jsonb) WITH ORDINALITY AS incoming(item,ordinal)
          ON CONFLICT (owner_id,code) DO NOTHING`,
          [ownerId, JSON.stringify(command.items)],
        );
        await client.query(
          "INSERT INTO personal_watchlist_imports(owner_id,client_request_id,command_hash,completed_at) VALUES($1,$2,$3,now())",
          [ownerId, command.clientRequestId, hash],
        );
      }
      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
    return this.list(ownerId);
  }
}
