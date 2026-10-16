import { Pool } from "pg";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PostgresWatchlistAlertsRepository } from "./postgres-watchlist-alerts.repository";
import type { StoredWatchlistAlertRule } from "./watchlist-alerts.types";

describe("PostgresWatchlistAlertsRepository rule revision append", () => {
  afterEach(() => vi.restoreAllMocks());

  it("checks the command inside a per-rule transaction before the expected revision", async () => {
    const statements: string[] = [];
    const client = fakeClient(statements, (statement) => {
      if (statement.includes("SELECT command_hash")) return { rows: [], rowCount: 0 };
      if (statement.includes("SELECT revision")) {
        return { rows: [{ revision: 1, revision_id: "d".repeat(64) }], rowCount: 1 };
      }
      if (statement.includes("INSERT INTO watchlist_alert_rule_revisions")) {
        return { rows: [{ command_hash: "c".repeat(64) }], rowCount: 1 };
      }
      return { rows: [], rowCount: null };
    });
    vi.spyOn(Pool.prototype, "connect").mockResolvedValue(client as unknown as never);
    const repository = new PostgresWatchlistAlertsRepository("postgres://unused");

    await expect(repository.appendRule(revision(), 1)).resolves.toBe("APPENDED");

    expect(statements[0]).toBe("BEGIN");
    expect(statements[1]).toContain("pg_advisory_xact_lock");
    expect(
      statements.findIndex((statement) => statement.includes("SELECT command_hash")),
    ).toBeLessThan(statements.findIndex((statement) => statement.includes("SELECT revision")));
    expect(statements.at(-1)).toBe("COMMIT");
    expect(client.release).toHaveBeenCalledOnce();
  });

  it("returns an identical committed command before checking a stale revision", async () => {
    const statements: string[] = [];
    const row = revision();
    const client = fakeClient(statements, (statement) => {
      if (statement.includes("SELECT command_hash")) {
        return { rows: [{ command_hash: row.commandHash }], rowCount: 1 };
      }
      return { rows: [], rowCount: null };
    });
    vi.spyOn(Pool.prototype, "connect").mockResolvedValue(client as unknown as never);
    const repository = new PostgresWatchlistAlertsRepository("postgres://unused");

    await expect(repository.appendRule(row, 0)).resolves.toBe("DUPLICATE");

    expect(statements.some((statement) => statement.includes("SELECT revision"))).toBe(false);
    expect(statements.some((statement) => statement.includes("INSERT INTO"))).toBe(false);
    expect(statements.at(-1)).toBe("COMMIT");
  });

  it("rejects a reused command id when its committed hash differs", async () => {
    const statements: string[] = [];
    const client = fakeClient(statements, (statement) => {
      if (statement.includes("SELECT command_hash")) {
        return { rows: [{ command_hash: "e".repeat(64) }], rowCount: 1 };
      }
      return { rows: [], rowCount: null };
    });
    vi.spyOn(Pool.prototype, "connect").mockResolvedValue(client as unknown as never);
    const repository = new PostgresWatchlistAlertsRepository("postgres://unused");

    await expect(repository.appendRule(revision(), 1)).resolves.toBe("COMMAND_CONFLICT");

    expect(statements.some((statement) => statement.includes("SELECT revision"))).toBe(false);
    expect(statements.some((statement) => statement.includes("INSERT INTO"))).toBe(false);
    expect(statements.at(-1)).toBe("COMMIT");
  });

  it("rejects a stale expected revision without inserting another row", async () => {
    const statements: string[] = [];
    const client = fakeClient(statements, (statement) => {
      if (statement.includes("SELECT command_hash")) return { rows: [], rowCount: 0 };
      if (statement.includes("SELECT revision")) {
        return { rows: [{ revision: 2, revision_id: "e".repeat(64) }], rowCount: 1 };
      }
      return { rows: [], rowCount: null };
    });
    vi.spyOn(Pool.prototype, "connect").mockResolvedValue(client as unknown as never);
    const repository = new PostgresWatchlistAlertsRepository("postgres://unused");

    await expect(repository.appendRule(revision(), 1)).resolves.toBe("STALE");

    expect(statements.some((statement) => statement.includes("INSERT INTO"))).toBe(false);
    expect(statements.at(-1)).toBe("COMMIT");
  });
});

function fakeClient(
  statements: string[],
  respond: (statement: string) => { rows: unknown[]; rowCount: number | null },
) {
  return {
    query: vi.fn().mockImplementation(async (statement: string) => {
      statements.push(statement);
      return respond(statement);
    }),
    release: vi.fn(),
  };
}

function revision(): StoredWatchlistAlertRule {
  return {
    ownerRef: "local-research-user",
    commandRequestId: "edit-command",
    commandHash: "c".repeat(64),
    rule: {
      schemaVersion: "watchlist-alert-rule-v1",
      ruleId: "a".repeat(64),
      revisionId: "b".repeat(64),
      revision: 2,
      name: "updated",
      enabled: true,
      instrumentIds: ["600519.SH"],
      condition: { field: "LAST_PRICE", operator: "GTE", threshold: "1500.00", featureName: null },
      quietPeriod: null,
      throttleSeconds: 300,
      notificationChannel: "IN_APP",
      createdAt: "2026-08-26T00:00:00.000Z",
      availableAt: "2026-08-26T01:00:00.000Z",
      previousRevisionId: "d".repeat(64),
    },
  };
}
