import { describe, expect, it } from "vitest";
import type { Pool, PoolClient } from "pg";
import { PostgresSqlDriver } from "./postgres-driver";
import type { SqlDriver } from "./migrations";

describe("PostgresSqlDriver", () => {
  it("releases a client when BEGIN fails", async () => {
    let released = false;
    const client = {
      query: async (sql: string) => {
        if (sql === "BEGIN") {
          throw new Error("begin failed");
        }
        return { rows: [], rowCount: 0 };
      },
      release: () => {
        released = true;
      },
    } as unknown as PoolClient;
    const pool = {
      connect: async () => client,
    } as unknown as Pool;
    const driver = new PostgresSqlDriver(pool);

    await expect(driver.transaction(async () => 1)).rejects.toThrow("begin failed");
    expect(released).toBe(true);
  });

  it("passes the lock-scoped driver to the callback", async () => {
    let released = false;
    const client = {
      query: async () => ({ rows: [{ table_name: "tasks", exists: true }], rowCount: 0 }),
      release: () => {
        released = true;
      },
    } as unknown as PoolClient;
    const pool = {
      connect: async () => client,
    } as unknown as Pool;
    const driver = new PostgresSqlDriver(pool);
    const withLock = driver.withMigrationLock.bind(driver) as unknown as <T>(
      callback: (scoped: SqlDriver) => Promise<T>,
    ) => Promise<T>;

    await expect(withLock(async (scoped) => scoped.listTables())).resolves.toEqual(["tasks"]);
    expect(released).toBe(true);
  });

  it("destroys a client when advisory unlock fails", async () => {
    let releaseError: Error | undefined;
    let unlock = false;
    const client = {
      query: async (sql: string) => {
        if (sql.includes("pg_advisory_unlock")) {
          unlock = true;
          throw new Error("unlock failed");
        }
        return { rows: [], rowCount: 0 };
      },
      release: (error?: Error) => {
        releaseError = error;
      },
    } as unknown as PoolClient;
    const pool = {
      connect: async () => client,
    } as unknown as Pool;
    const driver = new PostgresSqlDriver(pool);
    const withLock = driver.withMigrationLock.bind(driver) as unknown as <T>(
      callback: (scoped: SqlDriver) => Promise<T>,
    ) => Promise<T>;

    await expect(withLock(async () => 1)).rejects.toThrow("unlock failed");
    expect(unlock).toBe(true);
    expect(releaseError?.message).toBe("unlock failed");
  });

  it("destroys a client when rollback fails", async () => {
    let releaseError: Error | undefined;
    const client = {
      query: async (sql: string) => {
        if (sql === "ROLLBACK") {
          throw new Error("rollback failed");
        }
        if (sql === "COMMIT") {
          return { rows: [], rowCount: 0 };
        }
        return { rows: [], rowCount: 0 };
      },
      release: (error?: Error) => {
        releaseError = error;
      },
    } as unknown as PoolClient;
    const pool = {
      connect: async () => client,
    } as unknown as Pool;
    const driver = new PostgresSqlDriver(pool);

    await expect(
      driver.transaction(async () => {
        throw new Error("operation failed");
      }),
    ).rejects.toThrow("operation failed");
    expect(releaseError?.message).toBe("rollback failed");
  });
});
