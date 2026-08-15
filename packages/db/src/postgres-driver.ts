import { Pool, type PoolClient, type PoolConfig } from "pg";

import type { ColumnDefinition, SqlDriver, TableDefinition } from "./migrations";

type QueryExecutor = Pick<Pool, "query"> | Pick<PoolClient, "query">;
type DisposalState = { error?: unknown };

const IDENTIFIER_PATTERN = /^[a-z_][a-z0-9_]*$/;
const ALLOWED_SQL_TYPES = new Set([
  "BIGINT",
  "BOOLEAN",
  "DATE",
  "DOUBLE PRECISION",
  "INTEGER",
  "JSONB",
  "TEXT",
  "TIMESTAMPTZ",
  "UUID",
]);
const MIGRATION_LOCK_KEY = "kunlun-alpha.schema-migrations";

/**
 * PostgreSQL implementation of the migration SQL driver.
 *
 * A transaction driver always keeps using the same checked-out client. This
 * is important for PostgreSQL, where using pool.query for part of a
 * transaction can silently send statements to different connections.
 */
export class PostgresSqlDriver implements SqlDriver {
  private readonly pool: Pool;
  private readonly executor: QueryExecutor;
  private readonly scopedClient: PoolClient | undefined;
  private readonly disposalState: DisposalState;

  constructor(
    poolOrConfig: Pool | PoolConfig,
    executor?: QueryExecutor,
    disposalState: DisposalState = {},
  ) {
    this.pool = isPool(poolOrConfig) ? poolOrConfig : new Pool(poolOrConfig);
    this.executor = executor ?? this.pool;
    this.scopedClient = isPoolClient(executor) ? executor : undefined;
    this.disposalState = disposalState;
  }

  async withMigrationLock<T>(operation: (driver: SqlDriver) => Promise<T>): Promise<T> {
    const client = await this.pool.connect();
    let result!: T;
    let operationError: unknown;
    let cleanupError: unknown;
    const scopedState: DisposalState = {};
    let lockAcquired = false;
    try {
      try {
        await client.query("SELECT pg_advisory_lock(hashtext($1))", [MIGRATION_LOCK_KEY]);
        lockAcquired = true;
        result = await operation(new PostgresSqlDriver(this.pool, client, scopedState));
      } catch (error) {
        operationError = error;
      }
      cleanupError = scopedState.error;
      if (lockAcquired) {
        try {
          await client.query("SELECT pg_advisory_unlock(hashtext($1))", [MIGRATION_LOCK_KEY]);
        } catch (error) {
          cleanupError ??= error;
        }
      } else {
        cleanupError ??= operationError;
      }
    } finally {
      releaseClient(client, cleanupError);
    }
    if (operationError !== undefined) {
      throw operationError;
    }
    if (cleanupError !== undefined) {
      throw cleanupError;
    }
    return result;
  }

  async transaction<T>(operation: (driver: SqlDriver) => Promise<T>): Promise<T> {
    if (this.scopedClient) {
      return this.runTransaction(this.scopedClient, operation, (error) => {
        this.disposalState.error ??= error;
      });
    }
    const client = await this.pool.connect();
    let rollbackError: unknown;
    try {
      return await this.runTransaction(client, operation, (error) => {
        rollbackError = error;
      });
    } finally {
      releaseClient(client, rollbackError);
    }
  }

  private async runTransaction<T>(
    client: PoolClient,
    operation: (driver: SqlDriver) => Promise<T>,
    onRollbackError?: (error: unknown) => void,
  ): Promise<T> {
    try {
      await client.query("BEGIN");
      const transaction = new PostgresSqlDriver(this.pool, client, this.disposalState);
      const result = await operation(transaction);
      await client.query("COMMIT");
      return result;
    } catch (error) {
      try {
        await client.query("ROLLBACK");
      } catch (rollbackError) {
        onRollbackError?.(rollbackError);
      }
      throw error;
    }
  }

  async close(): Promise<void> {
    await this.pool.end();
  }

  async createTable(table: TableDefinition): Promise<void> {
    const tableName = quoteIdentifier(table.name);
    const definitions = table.columns.map((column) => columnSql(column));
    if (definitions.length === 0) {
      throw new Error(`table ${table.name} must define at least one column`);
    }
    await this.executor.query(`CREATE TABLE ${tableName} (${definitions.join(", ")})`);
  }

  async dropTable(name: string): Promise<void> {
    await this.executor.query(`DROP TABLE ${quoteIdentifier(name)}`);
  }

  async listTables(): Promise<string[]> {
    const result = await this.executor.query<{ table_name: string }>(
      "SELECT table_name FROM information_schema.tables " +
        "WHERE table_schema = current_schema() ORDER BY table_name",
    );
    return result.rows.map((row) => row.table_name);
  }

  async hasTable(name: string): Promise<boolean> {
    const result = await this.executor.query<{ exists: boolean }>(
      "SELECT EXISTS (" +
        "SELECT 1 FROM information_schema.tables " +
        "WHERE table_schema = current_schema() AND table_name = $1" +
        ") AS exists",
      [name],
    );
    return result.rows[0]?.exists === true;
  }

  async insert(table: string, row: Record<string, unknown>): Promise<void> {
    const entries = Object.entries(row);
    if (entries.length === 0) {
      throw new Error("cannot insert an empty row");
    }
    const columns = entries.map(([column]) => quoteIdentifier(column)).join(", ");
    const placeholders = entries.map((_, index) => `$${index + 1}`).join(", ");
    await this.executor.query(
      `INSERT INTO ${quoteIdentifier(table)} (${columns}) VALUES (${placeholders})`,
      entries.map(([, value]) => value),
    );
  }

  async query(table: string): Promise<Record<string, unknown>[]> {
    const result = await this.executor.query<Record<string, unknown>>(
      `SELECT * FROM ${quoteIdentifier(table)}`,
    );
    return result.rows.map((row) => ({ ...row }));
  }

  async delete(table: string, where: Record<string, unknown>): Promise<number> {
    const entries = Object.entries(where);
    if (entries.length === 0) {
      throw new Error("delete requires at least one predicate");
    }
    const predicates = entries
      .map(([column], index) => `${quoteIdentifier(column)} = $${index + 1}`)
      .join(" AND ");
    const result = await this.executor.query(
      `DELETE FROM ${quoteIdentifier(table)} WHERE ${predicates}`,
      entries.map(([, value]) => value),
    );
    return result.rowCount ?? 0;
  }
}

function quoteIdentifier(identifier: string): string {
  if (!IDENTIFIER_PATTERN.test(identifier)) {
    throw new Error(`unsafe SQL identifier: ${identifier}`);
  }
  return `"${identifier}"`;
}

function columnSql(column: ColumnDefinition): string {
  const type = column.type.trim().toUpperCase();
  if (!ALLOWED_SQL_TYPES.has(type)) {
    throw new Error(`unsupported SQL type: ${column.type}`);
  }
  const constraints = [column.primaryKey ? "PRIMARY KEY" : "", column.notNull ? "NOT NULL" : ""]
    .filter(Boolean)
    .join(" ");
  return `${quoteIdentifier(column.name)} ${type}${constraints ? ` ${constraints}` : ""}`;
}

function isPool(value: Pool | PoolConfig): value is Pool {
  return typeof value === "object" && value !== null && "connect" in value;
}

function isPoolClient(value: QueryExecutor | undefined): value is PoolClient {
  return typeof value === "object" && value !== null && "release" in value;
}

function releaseClient(client: PoolClient, error: unknown): void {
  if (error === undefined) {
    client.release();
    return;
  }
  client.release(error instanceof Error ? error : new Error(String(error)));
}
