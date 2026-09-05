import { EventEmitter } from "node:events";
import { describe, expect, it } from "vitest";
import {
  attachMarketDataSettingsPoolError,
  marketDataSettingsPoolOptions,
} from "./market-data-settings.module";

describe("market-data settings pool", () => {
  it("uses bounded timeouts for settings and worker reads", () => {
    expect(marketDataSettingsPoolOptions("postgresql://settings.test/kunlun")).toEqual({
      connectionString: "postgresql://settings.test/kunlun",
      max: 4,
      connectionTimeoutMillis: 1_000,
      statement_timeout: 4_000,
      lock_timeout: 1_000,
      idle_in_transaction_session_timeout: 4_500,
    });
  });

  it("handles idle pool errors without exposing driver details", () => {
    const pool = new EventEmitter();
    expect(() => {
      attachMarketDataSettingsPoolError(pool as never);
      pool.emit("error", new Error("postgresql://secret.example"));
    }).not.toThrow();
  });
});
