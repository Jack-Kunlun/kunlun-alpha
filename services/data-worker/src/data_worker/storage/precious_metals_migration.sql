-- Canonical additive P1-R07 fund schema.  migrations.py acquires the
-- transaction lock before executing this resource on the same connection.
-- pg_advisory_xact_lock(hashtext('kunlun-alpha.schema-migrations'))

CREATE TABLE data_worker_schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  checksum TEXT NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL
);

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

CREATE TABLE fund_logical_observations (
  observation_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  source TEXT NOT NULL,
  source_revision TEXT,
  semantic_key TEXT NOT NULL,
  content_digest TEXT NOT NULL,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  UNIQUE (kind, source, semantic_key, source_revision, content_digest)
);

CREATE TABLE fund_observation_evidence_links (
  observation_id TEXT NOT NULL REFERENCES fund_logical_observations(observation_id),
  evidence_id TEXT NOT NULL REFERENCES fund_observation_evidence(record_id),
  PRIMARY KEY (observation_id, evidence_id)
);

CREATE TABLE fund_metadata_observations (
  record_id TEXT PRIMARY KEY REFERENCES fund_observation_evidence(record_id),
  observation_id TEXT NOT NULL REFERENCES fund_logical_observations(observation_id),
  unified_code TEXT NOT NULL,
  payload JSONB NOT NULL,
  semantic_key TEXT NOT NULL,
  evidence_id TEXT NOT NULL REFERENCES fund_observation_evidence(record_id)
);

CREATE TABLE fund_nav_observations (
  record_id TEXT PRIMARY KEY REFERENCES fund_observation_evidence(record_id),
  observation_id TEXT NOT NULL REFERENCES fund_logical_observations(observation_id),
  unified_code TEXT NOT NULL,
  reference_date DATE NOT NULL,
  value NUMERIC(30, 12) NOT NULL CHECK (value >= 0),
  semantic_key TEXT NOT NULL,
  evidence_id TEXT NOT NULL REFERENCES fund_observation_evidence(record_id)
);

CREATE TABLE fund_inav_observations (
  record_id TEXT PRIMARY KEY REFERENCES fund_observation_evidence(record_id),
  observation_id TEXT NOT NULL REFERENCES fund_logical_observations(observation_id),
  unified_code TEXT NOT NULL,
  reference_date DATE NOT NULL,
  value NUMERIC(30, 12) NOT NULL CHECK (value >= 0),
  semantic_key TEXT NOT NULL,
  evidence_id TEXT NOT NULL REFERENCES fund_observation_evidence(record_id)
);

CREATE TABLE fund_benchmark_observations (
  record_id TEXT PRIMARY KEY REFERENCES fund_observation_evidence(record_id),
  observation_id TEXT NOT NULL REFERENCES fund_logical_observations(observation_id),
  unified_code TEXT NOT NULL,
  reference_date DATE NOT NULL,
  benchmark TEXT NOT NULL,
  semantic_key TEXT NOT NULL,
  evidence_id TEXT NOT NULL REFERENCES fund_observation_evidence(record_id)
);

CREATE TABLE fund_fee_observations (
  record_id TEXT PRIMARY KEY REFERENCES fund_observation_evidence(record_id),
  observation_id TEXT NOT NULL REFERENCES fund_logical_observations(observation_id),
  unified_code TEXT NOT NULL,
  reference_date DATE NOT NULL,
  management_fee_rate NUMERIC(30, 12) NOT NULL CHECK (management_fee_rate >= 0),
  semantic_key TEXT NOT NULL,
  evidence_id TEXT NOT NULL REFERENCES fund_observation_evidence(record_id)
);

CREATE TABLE fund_rejections (
  record_id TEXT PRIMARY KEY REFERENCES fund_observation_evidence(record_id),
  kind TEXT NOT NULL,
  reason TEXT NOT NULL,
  payload JSONB NOT NULL,
  raw_capture_id TEXT NOT NULL
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

CREATE INDEX idx_fund_evidence_source_time
  ON fund_observation_evidence (source, ingest_time, record_id);
CREATE INDEX idx_fund_logical_semantic
  ON fund_logical_observations (kind, source, semantic_key);
CREATE INDEX idx_fund_nav_key
  ON fund_nav_observations (unified_code, reference_date);
CREATE INDEX idx_fund_inav_key
  ON fund_inav_observations (unified_code, reference_date);
CREATE INDEX idx_fund_benchmark_key
  ON fund_benchmark_observations (unified_code, reference_date);
CREATE INDEX idx_fund_fee_key
  ON fund_fee_observations (unified_code, reference_date);
