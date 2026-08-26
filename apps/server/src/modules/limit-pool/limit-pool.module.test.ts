import { describe, expect, it } from "vitest";
import { resolveLimitPoolClickHouseConfig } from "./limit-pool.module";

describe("resolveLimitPoolClickHouseConfig", () => {
  it("inherits the complete Emotion ClickHouse configuration used by Compose", () => {
    expect(
      resolveLimitPoolClickHouseConfig({
        EMOTION_CLICKHOUSE_URL: "http://clickhouse:8123",
        EMOTION_CLICKHOUSE_DATABASE: "kunlun_test",
        EMOTION_CLICKHOUSE_USER: "kunlun_reader",
        EMOTION_CLICKHOUSE_PASSWORD: "local-secret",
      }),
    ).toEqual({
      url: "http://clickhouse:8123",
      database: "kunlun_test",
      user: "kunlun_reader",
      password: "local-secret",
    });
  });

  it("keeps limit-pool settings ahead of dashboard and Emotion fallbacks", () => {
    expect(
      resolveLimitPoolClickHouseConfig({
        LIMIT_POOL_CLICKHOUSE_URL: "http://limit-pool:8123",
        LIMIT_POOL_CLICKHOUSE_DATABASE: "limit_pool",
        LIMIT_POOL_CLICKHOUSE_USER: "limit_pool_reader",
        LIMIT_POOL_CLICKHOUSE_PASSWORD: "limit-pool-secret",
        DASHBOARD_CLICKHOUSE_URL: "http://dashboard:8123",
        DASHBOARD_CLICKHOUSE_DATABASE: "dashboard",
        DASHBOARD_CLICKHOUSE_USER: "dashboard_reader",
        DASHBOARD_CLICKHOUSE_PASSWORD: "dashboard-secret",
        EMOTION_CLICKHOUSE_URL: "http://emotion:8123",
        EMOTION_CLICKHOUSE_DATABASE: "emotion",
        EMOTION_CLICKHOUSE_USER: "emotion_reader",
        EMOTION_CLICKHOUSE_PASSWORD: "emotion-secret",
      }),
    ).toEqual({
      url: "http://limit-pool:8123",
      database: "limit_pool",
      user: "limit_pool_reader",
      password: "limit-pool-secret",
    });
  });
});
