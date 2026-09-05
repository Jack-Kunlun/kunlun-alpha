import type { Pool, PoolClient } from "pg";
import type { OnModuleDestroy } from "@nestjs/common";
import { randomUUID } from "node:crypto";
import {
  MARKET_DATA_SETTINGS_INSTANCE_ID,
  MARKET_DATA_SETTINGS_ENCRYPTION_VERSION,
  MARKET_DATA_SETTINGS_KEY_VERSION,
  type EncryptedTokenEnvelope,
  type MarketDataSettingsRepository,
  type MarketDataProvider,
  type PersistedMarketDataSettings,
} from "./market-data-settings.types";

interface SettingsRow {
  provider: MarketDataProvider;
  revision: number;
  token_ciphertext: string | null;
  token_nonce: string | null;
  token_tag: string | null;
  encryption_version: string | null;
  key_version: string | null;
  updated_at: Date | string | null;
}

export class MarketDataSettingsConflictError extends Error {
  constructor() {
    super("market-data settings revision conflict");
    this.name = "MarketDataSettingsConflictError";
  }
}

export class MarketDataSettingsRepositoryError extends Error {
  constructor() {
    super("market-data settings storage unavailable");
    this.name = "MarketDataSettingsRepositoryError";
  }
}

const SELECT_SQL = `
SELECT provider, revision, token_ciphertext, token_nonce, token_tag,
       encryption_version, key_version, updated_at
FROM market_data_instance_settings
WHERE instance_id = $1
`;

export class PostgresMarketDataSettingsRepository
  implements MarketDataSettingsRepository, OnModuleDestroy
{
  constructor(private readonly pool: Pool) {}

  async onModuleDestroy(): Promise<void> {
    await this.pool.end();
  }

  async get(): Promise<PersistedMarketDataSettings | null> {
    try {
      const result = await this.pool.query<SettingsRow>(SELECT_SQL, [
        MARKET_DATA_SETTINGS_INSTANCE_ID,
      ]);
      return toSettings(result.rows[0]);
    } catch {
      throw new MarketDataSettingsRepositoryError();
    }
  }

  async compareAndSet(input: {
    expectedRevision: number;
    provider: MarketDataProvider;
    tokenEnvelope: EncryptedTokenEnvelope | null;
    tokenAction: "KEEP" | "REPLACE" | "CLEAR";
    actorId: string;
    updatedAt: string;
  }): Promise<PersistedMarketDataSettings> {
    let client: PoolClient | undefined;
    try {
      client = await this.pool.connect();
      await client.query("BEGIN");
      await client.query("SELECT pg_advisory_xact_lock(hashtext($1))", [
        "kunlun-alpha.market-data-settings.default",
      ]);
      const currentResult = await client.query<SettingsRow>(`${SELECT_SQL} FOR UPDATE`, [
        MARKET_DATA_SETTINGS_INSTANCE_ID,
      ]);
      const current = currentResult.rows[0];
      const currentSettings = toSettings(current);
      if (current === undefined) {
        if (input.expectedRevision !== 0) throw new MarketDataSettingsConflictError();
        await client.query(
          `INSERT INTO market_data_instance_settings (
             instance_id, provider, revision, token_ciphertext, token_nonce, token_tag,
             encryption_version, key_version, updated_at
           ) VALUES ($1, $2, 1, $3, $4, $5, $6, $7, $8::timestamptz)`,
          [
            MARKET_DATA_SETTINGS_INSTANCE_ID,
            input.provider,
            input.tokenEnvelope?.ciphertext ?? null,
            input.tokenEnvelope?.nonce ?? null,
            input.tokenEnvelope?.tag ?? null,
            input.tokenEnvelope?.encryptionVersion ?? null,
            input.tokenEnvelope?.keyVersion ?? null,
            input.updatedAt,
          ],
        );
      } else {
        if (currentSettings === null || currentSettings.revision !== input.expectedRevision) {
          throw new MarketDataSettingsConflictError();
        }
        await client.query(
          `UPDATE market_data_instance_settings
           SET provider = $1,
               revision = $2,
               token_ciphertext = $3,
               token_nonce = $4,
               token_tag = $5,
               encryption_version = $6,
               key_version = $7,
               updated_at = $8::timestamptz
           WHERE instance_id = $9 AND revision = $10`,
          [
            input.provider,
            current.revision + 1,
            input.tokenEnvelope?.ciphertext ?? null,
            input.tokenEnvelope?.nonce ?? null,
            input.tokenEnvelope?.tag ?? null,
            input.tokenEnvelope?.encryptionVersion ?? null,
            input.tokenEnvelope?.keyVersion ?? null,
            input.updatedAt,
            MARKET_DATA_SETTINGS_INSTANCE_ID,
            input.expectedRevision,
          ],
        );
      }
      const nextRevision = current === undefined ? 1 : current.revision + 1;
      await client.query(
        `INSERT INTO market_data_settings_audit (
           audit_id, instance_id, revision, provider, token_action, actor_id, recorded_at
         ) VALUES ($1, $2, $3, $4, $5, $6, $7::timestamptz)`,
        [
          randomUUID(),
          MARKET_DATA_SETTINGS_INSTANCE_ID,
          nextRevision,
          input.provider,
          input.tokenAction,
          input.actorId,
          input.updatedAt,
        ],
      );
      await client.query("COMMIT");
      return {
        provider: input.provider,
        revision: nextRevision,
        tokenEnvelope: input.tokenEnvelope,
        updatedAt: input.updatedAt,
      };
    } catch (error) {
      if (client !== undefined) {
        try {
          await client.query("ROLLBACK");
        } catch {
          // Preserve the safe storage error below.
        }
      }
      if (error instanceof MarketDataSettingsConflictError) throw error;
      throw new MarketDataSettingsRepositoryError();
    } finally {
      client?.release();
    }
  }
}

function toSettings(row: SettingsRow | undefined): PersistedMarketDataSettings | null {
  if (row === undefined) return null;
  if (row.provider !== "akshare" && row.provider !== "tushare") {
    throw new MarketDataSettingsRepositoryError();
  }
  if (!Number.isSafeInteger(row.revision) || row.revision < 0) {
    throw new MarketDataSettingsRepositoryError();
  }
  const envelopeValues = [
    row.token_ciphertext,
    row.token_nonce,
    row.token_tag,
    row.encryption_version,
    row.key_version,
  ];
  const anyEnvelope = envelopeValues.some((value) => value !== null);
  const fullEnvelope = envelopeValues.every((value) => value !== null);
  if (anyEnvelope && !fullEnvelope) throw new MarketDataSettingsRepositoryError();
  const updatedAt = toIso(row.updated_at);
  if ((row.revision === 0 && updatedAt !== null) || (row.revision > 0 && updatedAt === null)) {
    throw new MarketDataSettingsRepositoryError();
  }
  const tokenEnvelope = fullEnvelope
    ? {
        ciphertext: row.token_ciphertext as string,
        nonce: row.token_nonce as string,
        tag: row.token_tag as string,
        encryptionVersion: row.encryption_version as EncryptedTokenEnvelope["encryptionVersion"],
        keyVersion: row.key_version as string,
      }
    : null;
  if (tokenEnvelope !== null) {
    if (
      tokenEnvelope.encryptionVersion !== MARKET_DATA_SETTINGS_ENCRYPTION_VERSION ||
      tokenEnvelope.keyVersion !== MARKET_DATA_SETTINGS_KEY_VERSION ||
      !isBase64(tokenEnvelope.ciphertext, 1, 256) ||
      !isBase64(tokenEnvelope.nonce, 12, 12) ||
      !isBase64(tokenEnvelope.tag, 16, 16)
    ) {
      throw new MarketDataSettingsRepositoryError();
    }
  }
  if (row.provider === "tushare" && tokenEnvelope === null) {
    throw new MarketDataSettingsRepositoryError();
  }
  return {
    provider: row.provider,
    revision: row.revision,
    tokenEnvelope,
    updatedAt,
  };
}

function toIso(value: Date | string | null): string | null {
  if (value === null) return null;
  if (value instanceof Date) {
    if (!Number.isFinite(value.getTime())) throw new MarketDataSettingsRepositoryError();
    return value.toISOString();
  }
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) {
    throw new MarketDataSettingsRepositoryError();
  }
  return new Date(value).toISOString();
}

function isBase64(value: string, minBytes: number, maxBytes: number): boolean {
  if (
    typeof value !== "string" ||
    !/^[A-Za-z0-9+/]*={0,2}$/.test(value) ||
    value.length % 4 === 1
  ) {
    return false;
  }
  const decoded = Buffer.from(value, "base64");
  return (
    decoded.length >= minBytes && decoded.length <= maxBytes && decoded.toString("base64") === value
  );
}
