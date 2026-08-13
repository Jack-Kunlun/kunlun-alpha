/**
 * In-memory SQL driver for tests.
 *
 * Simulates tables, primary-key constraints and rows so migration and
 * repository behaviour can be verified without a live database.
 */

import type { SqlDriver, TableDefinition } from "./migrations";

interface MemoryTable {
  definition: TableDefinition;
  rows: Record<string, unknown>[];
}

export class MemorySqlDriver implements SqlDriver {
  private readonly tables = new Map<string, MemoryTable>();

  async createTable(table: TableDefinition): Promise<void> {
    if (this.tables.has(table.name)) {
      throw new Error(`table ${table.name} already exists`);
    }
    this.tables.set(table.name, { definition: table, rows: [] });
  }

  async dropTable(name: string): Promise<void> {
    this.tables.delete(name);
  }

  async listTables(): Promise<string[]> {
    return [...this.tables.keys()].sort();
  }

  async hasTable(name: string): Promise<boolean> {
    return this.tables.has(name);
  }

  async insert(table: string, row: Record<string, unknown>): Promise<void> {
    const target = this.tables.get(table);
    if (!target) {
      throw new Error(`table ${table} does not exist`);
    }
    const primaryKey = target.definition.columns.find((c) => c.primaryKey);
    if (primaryKey) {
      const value = row[primaryKey.name];
      const duplicate = target.rows.some((r) => r[primaryKey.name] === value);
      if (duplicate) {
        throw new Error(`duplicate primary key ${String(value)} in table ${table}`);
      }
    }
    target.rows.push({ ...row });
  }

  async query(table: string): Promise<Record<string, unknown>[]> {
    const target = this.tables.get(table);
    if (!target) {
      return [];
    }
    return target.rows.map((r) => ({ ...r }));
  }
}
