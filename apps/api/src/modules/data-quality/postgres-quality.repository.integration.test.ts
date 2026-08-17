import { randomUUID } from "node:crypto";

import { Pool } from "pg";
import { describe, expect, it } from "vitest";

import { PostgresQualityRepository } from "./postgres-quality.repository";

const dsn = process.env.KUNLUN_TEST_POSTGRES_DSN;
const run = dsn ? describe : describe.skip;

const CREATE_TABLES = `
CREATE TABLE fund_observation_evidence (
  record_id TEXT PRIMARY KEY,
  raw_capture_id TEXT NOT NULL,
  raw_object_id TEXT NOT NULL,
  checksum TEXT NOT NULL,
  source TEXT NOT NULL,
  source_revision TEXT,
  schema_version TEXT NOT NULL,
  normalizer_version TEXT NOT NULL,
  payload_digest TEXT NOT NULL,
  item_ordinal INTEGER NOT NULL CHECK (item_ordinal >= 0),
  event_time TIMESTAMPTZ,
  publish_time TIMESTAMPTZ,
  ingest_time TIMESTAMPTZ,
  available_time TIMESTAMPTZ,
  processing_time TIMESTAMPTZ,
  UNIQUE (raw_capture_id, item_ordinal)
);

CREATE TABLE fund_quality_events (
  event_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  semantic_key TEXT NOT NULL,
  detail TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE fund_quality_event_evidence (
  quality_event_id TEXT NOT NULL REFERENCES fund_quality_events(event_id),
  evidence_id TEXT NOT NULL REFERENCES fund_observation_evidence(record_id),
  PRIMARY KEY (quality_event_id, evidence_id)
);
`;

async function createSchema(schema: string): Promise<void> {
  const pool = new Pool({ connectionString: dsn });
  try {
    await pool.query(`CREATE SCHEMA "${schema}"`);
  } finally {
    await pool.end();
  }
}

async function dropSchema(schema: string): Promise<void> {
  const pool = new Pool({ connectionString: dsn });
  try {
    await pool.query(`DROP SCHEMA "${schema}" CASCADE`);
  } finally {
    await pool.end();
  }
}

async function seed(pool: Pool): Promise<void> {
  await pool.query(CREATE_TABLES);
  // Evidence rows carry sensitive raw-object fields on purpose, so the test can
  // prove the repository never surfaces them.
  await pool.query(
    `INSERT INTO fund_observation_evidence
       (record_id, raw_capture_id, raw_object_id, checksum, source, schema_version,
        normalizer_version, payload_digest, item_ordinal, ingest_time, available_time)
     VALUES
       ('ev-1', 'cap-1', 's3://bucket/secret/raw-object-1', 'deadbeef', 'provider-a', 'fund-v1',
        'norm-v1', 'digest-1', 0, '2026-08-13T01:30:00Z', '2026-08-13T01:31:00Z'),
       ('ev-2', 'cap-2', 's3://bucket/secret/raw-object-2', 'cafebabe', 'provider-b', 'fund-v1',
        'norm-v1', 'digest-2', 0, '2026-08-14T01:30:00Z', '2026-08-14T01:31:00Z')`,
  );
  await pool.query(
    `INSERT INTO fund_quality_events (event_id, kind, semantic_key, detail, created_at) VALUES
       ('evt-1', 'SOURCE_CONFLICT', 'nav:600519.SH:2026-08-13',
        'SOURCE_CONFLICT:detail_sha256=aaaa', '2026-08-13T01:32:00Z'),
       ('evt-2', 'SOURCE_CONFLICT', 'nav:518880.SH:2026-08-14',
        'SOURCE_CONFLICT:detail_sha256=bbbb', '2026-08-14T01:32:00Z')`,
  );
  await pool.query(
    `INSERT INTO fund_quality_event_evidence (quality_event_id, evidence_id) VALUES
       ('evt-1', 'ev-1'),
       ('evt-2', 'ev-2')`,
  );
}

run("PostgresQualityRepository integration", () => {
  it("queries persisted events by date, code, source and kind, exposing only safe fields", async () => {
    const schema = `dq_test_${randomUUID().replaceAll("-", "")}`;
    await createSchema(schema);
    const pool = new Pool({ connectionString: dsn, options: `-c search_path="${schema}"` });
    try {
      await seed(pool);
      const repository = new PostgresQualityRepository(pool);

      expect(await repository.query({})).toHaveLength(2);
      expect((await repository.query({ date: "2026-08-13" })).map((r) => r.id)).toEqual(["evt-1"]);
      expect((await repository.query({ unifiedCode: "600519.SH" })).map((r) => r.id)).toEqual(["evt-1"]);
      expect((await repository.query({ source: "provider-a" })).map((r) => r.id)).toEqual(["evt-1"]);
      expect(await repository.query({ kind: "SOURCE_CONFLICT" })).toHaveLength(2);
      expect(await repository.query({ dateFrom: "2026-08-13", dateTo: "2026-08-14" })).toHaveLength(2);

      const evidence = await repository.getEvidence("evt-1");
      expect(evidence?.source).toBe("provider-a");
      expect(evidence?.schemaVersion).toBe("fund-v1");
      expect(evidence).not.toHaveProperty("raw_object_id");
      expect(evidence).not.toHaveProperty("raw_capture_id");
      expect(evidence).not.toHaveProperty("checksum");
      expect(evidence).not.toHaveProperty("payload_digest");

      const serialized = JSON.stringify(await repository.query({}));
      expect(serialized).not.toContain("s3://bucket/secret");
      expect(serialized).not.toContain("raw_object_id");
      expect(serialized).not.toContain("checksum");
    } finally {
      await pool.end();
      await dropSchema(schema);
    }
  });
});
