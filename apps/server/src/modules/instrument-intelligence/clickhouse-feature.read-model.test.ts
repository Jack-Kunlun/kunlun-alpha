import { describe, expect, it } from "vitest";
import {
  type ClickHouseIntelligenceConfig,
  ClickHouseJsonClient,
} from "./clickhouse-json-client";
import { ClickHouseInstrumentFeatureRepository } from "./clickhouse-feature.read-model";

const config: ClickHouseIntelligenceConfig = {
  url: "http://clickhouse.test:8123",
  database: "kunlun",
  user: "reader",
  timeoutMs: 1000,
};

describe("ClickHouse instrument feature read model", () => {
  it("returns all latest visible features in one request", async () => {
    const requests: RequestInit[] = [];
    const fetcher = async (_input: string | URL, init?: RequestInit): Promise<Response> => {
      requests.push(init ?? {});
      return new Response(
        JSON.stringify({
          feature_name: "momentum",
          feature_version: "v1",
          feature_fingerprint: "sha256:" + "1".repeat(64),
          algorithm_version: "momentum-v1",
          value_type: "DECIMAL",
          value_json: "\"0.125\"",
          event_time: "2026-08-25T07:00:00.000000Z",
          available_time: "2026-08-25T07:01:00.000000Z",
          processing_time: "2026-08-25T07:02:00.000000Z",
          lineage_checksum: "sha256:" + "2".repeat(64),
          source_kind: "BATCH",
          source_snapshot_version: "snapshot-v1",
          revision_id: "sha256:" + "3".repeat(64),
        }) + "\n",
        { status: 200 },
      );
    };
    const repository = new ClickHouseInstrumentFeatureRepository(
      new ClickHouseJsonClient(config, fetcher),
    );

    const values = await repository.load("600519.SH", "2026-08-25T08:00:00.000Z");

    expect(values).toHaveLength(1);
    expect(values[0]?.value).toBe("0.125");
    expect(requests).toHaveLength(1);
    expect(String(requests[0]?.body)).toContain("processing_time <=");
  });
});
