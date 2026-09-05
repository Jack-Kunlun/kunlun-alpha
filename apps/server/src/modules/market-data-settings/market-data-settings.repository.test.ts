import { describe, expect, it, vi } from "vitest";
import {
  MarketDataSettingsRepositoryError,
  PostgresMarketDataSettingsRepository,
} from "./market-data-settings.repository";

function row(overrides: Record<string, unknown> = {}) {
  return {
    provider: "akshare",
    revision: 0,
    token_ciphertext: null,
    token_nonce: null,
    token_tag: null,
    encryption_version: null,
    key_version: null,
    updated_at: null,
    ...overrides,
  };
}

describe("PostgresMarketDataSettingsRepository", () => {
  it.each([
    { provider: "unknown" },
    { revision: -1 },
    { token_ciphertext: "partial" },
    { provider: "tushare" },
    { updated_at: "not-a-time" },
    { revision: 1, updated_at: null },
  ])("rejects malformed persisted rows without returning secret details", async (overrides) => {
    const pool = {
      query: vi.fn().mockResolvedValue({ rows: [row(overrides)], rowCount: 1 }),
    };
    const repository = new PostgresMarketDataSettingsRepository(pool as never);

    await expect(repository.get()).rejects.toThrow(MarketDataSettingsRepositoryError);
    await expect(repository.get()).rejects.not.toThrow(/partial|cipher|token/i);
  });

  it("rolls back a settings write when the audit insert fails", async () => {
    const client = {
      query: vi
        .fn()
        .mockResolvedValueOnce({ rows: [] })
        .mockResolvedValueOnce({ rows: [] })
        .mockResolvedValueOnce({ rows: [] })
        .mockResolvedValueOnce({ rows: [] })
        .mockRejectedValueOnce(new Error("secret-looking driver error"))
        .mockResolvedValueOnce({ rows: [] }),
      release: vi.fn(),
    };
    const pool = { connect: vi.fn().mockResolvedValue(client) };
    const repository = new PostgresMarketDataSettingsRepository(pool as never);

    await expect(
      repository.compareAndSet({
        expectedRevision: 0,
        provider: "akshare",
        tokenEnvelope: null,
        tokenAction: "CLEAR",
        actorId: "9b596d16-8aae-4a10-8aa7-88c8c9f7458e",
        updatedAt: "2026-09-05T00:00:00.000Z",
      }),
    ).rejects.toThrow(MarketDataSettingsRepositoryError);
    expect(client.query).toHaveBeenCalledWith("ROLLBACK");
    expect(client.query.mock.calls.map((call: unknown[]) => String(call[0]))).not.toContain(
      "COMMIT",
    );
    expect(client.release).toHaveBeenCalledOnce();
  });
});
