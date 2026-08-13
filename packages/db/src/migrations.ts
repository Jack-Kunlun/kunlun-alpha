/**
 * Versioned SQL migrations.
 *
 * Migrations are declared as structured table definitions (rather than raw
 * SQL) so drivers can apply them against any backend and tests can verify
 * constraints. The runner records applied versions in a schema_migrations
 * table: an empty database upgrades fully, re-running skips applied versions
 * (idempotent), and rollback drops tables in reverse order.
 */

export interface ColumnDefinition {
  name: string;
  type: string;
  primaryKey?: boolean;
  notNull?: boolean;
}

export interface TableDefinition {
  name: string;
  columns: ColumnDefinition[];
}

export interface Migration {
  version: number;
  name: string;
  up: TableDefinition[];
  down: string[];
}

export interface SqlDriver {
  createTable(table: TableDefinition): Promise<void>;
  dropTable(name: string): Promise<void>;
  listTables(): Promise<string[]>;
  hasTable(name: string): Promise<boolean>;
  insert(table: string, row: Record<string, unknown>): Promise<void>;
  query(table: string): Promise<Record<string, unknown>[]>;
}

const MIGRATIONS_TABLE = "schema_migrations";

export class MigrationRunner {
  constructor(private readonly driver: SqlDriver) {}

  async migrate(migrations: Migration[]): Promise<number> {
    await this.ensureMigrationsTable();
    const applied = await this.appliedVersions();
    const sorted = [...migrations].sort((a, b) => a.version - b.version);

    let count = 0;
    for (const migration of sorted) {
      if (applied.has(migration.version)) {
        continue;
      }
      for (const table of migration.up) {
        await this.driver.createTable(table);
      }
      await this.driver.insert(MIGRATIONS_TABLE, {
        version: migration.version,
        name: migration.name,
      });
      applied.add(migration.version);
      count += 1;
    }
    return count;
  }

  async rollback(migrations: Migration[], targetVersion: number): Promise<number> {
    await this.ensureMigrationsTable();
    const applied = await this.appliedVersions();
    const sorted = [...migrations]
      .filter((m) => m.version > targetVersion)
      .sort((a, b) => b.version - a.version);

    let count = 0;
    for (const migration of sorted) {
      if (!applied.has(migration.version)) {
        continue;
      }
      for (const tableName of migration.down) {
        await this.driver.dropTable(tableName);
      }
      count += 1;
    }
    return count;
  }

  async appliedVersions(): Promise<Set<number>> {
    await this.ensureMigrationsTable();
    const rows = await this.driver.query(MIGRATIONS_TABLE);
    return new Set(rows.map((r) => Number(r.version)));
  }

  private async ensureMigrationsTable(): Promise<void> {
    if (!(await this.driver.hasTable(MIGRATIONS_TABLE))) {
      await this.driver.createTable({
        name: MIGRATIONS_TABLE,
        columns: [
          { name: "version", type: "INTEGER", primaryKey: true, notNull: true },
          { name: "name", type: "TEXT", notNull: true },
        ],
      });
    }
  }
}
