-- Phase 2 persisted replay schema.
-- Derived minute snapshots and rotation events remain versioned, PIT-attributed
-- and immutable across algorithm versions. There is intentionally no TTL.

CREATE TABLE IF NOT EXISTS emotion_snapshots_v1
(
    snapshot_id         String,
    trading_date        Date,
    event_time          DateTime64(3, 'UTC'),
    algorithm_version   LowCardinality(String),
    score               Decimal(12, 8),
    ladder_json         String,
    freshness_seconds   UInt32,
    sample_size         UInt32,
    confidence          Decimal(9, 8),
    source_versions     Array(String),
    evidence_ids        Array(String),
    available_time      DateTime64(3, 'UTC'),
    processing_time     DateTime64(3, 'UTC'),
    replacement_version UInt64,
    payload_digest      FixedString(64)
)
ENGINE = ReplacingMergeTree(replacement_version)
PARTITION BY toYYYYMM(event_time)
ORDER BY
(
    trading_date,
    event_time,
    algorithm_version,
    available_time,
    payload_digest
)
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS sector_rotation_events_v1
(
    event_id            String,
    trading_date        Date,
    event_time          DateTime64(3, 'UTC'),
    event_type          LowCardinality(String),
    from_sector         Nullable(String),
    to_sector           String,
    confidence          Decimal(9, 8),
    evidence_start      DateTime64(3, 'UTC'),
    evidence_end        DateTime64(3, 'UTC'),
    sample_size         UInt32,
    algorithm_version   LowCardinality(String),
    source_versions     Array(String),
    evidence_ids        Array(String),
    available_time      DateTime64(3, 'UTC'),
    processing_time     DateTime64(3, 'UTC'),
    replacement_version UInt64,
    payload_digest      FixedString(64)
)
ENGINE = ReplacingMergeTree(replacement_version)
PARTITION BY toYYYYMM(event_time)
ORDER BY
(
    trading_date,
    event_time,
    algorithm_version,
    event_id,
    available_time,
    payload_digest
)
SETTINGS index_granularity = 8192;
