-- P5-N04 historical feature storage.
--
-- Rows are immutable revisions. Do not use ReplacingMergeTree or mutations to
-- collapse them: point-in-time queries must retain every historically visible
-- value and choose a revision using available_time at query time.
CREATE TABLE IF NOT EXISTS feature_history_v1
(
    registry_namespace_id LowCardinality(String),
    registry_head_fingerprint FixedString(71),
    feature_name LowCardinality(String),
    feature_version LowCardinality(String),
    feature_fingerprint FixedString(71),
    algorithm_version LowCardinality(String),
    entity_id String,
    event_time DateTime64(6, 'UTC'),
    available_time DateTime64(6, 'UTC'),
    processing_time DateTime64(6, 'UTC'),
    value_type LowCardinality(String),
    value_json String,
    value_checksum FixedString(71),
    materialization_id String,
    revision_nonce String,
    revision_id FixedString(71),
    input_checksum FixedString(71),
    calculator_implementation_fingerprint FixedString(71),
    input_manifest_checksum FixedString(71),
    lineage_checksum FixedString(71),
    source_kind LowCardinality(String),
    source_snapshot_version String,
    record_checksum FixedString(71),
    INDEX idx_feature_history_available_time available_time TYPE minmax GRANULARITY 1,
    INDEX idx_feature_history_revision_id revision_id TYPE bloom_filter(0.001) GRANULARITY 4,
    CONSTRAINT chk_feature_history_visibility
        CHECK event_time <= available_time AND available_time <= processing_time,
    CONSTRAINT chk_feature_history_value_type
        CHECK value_type IN ('BOOLEAN', 'INTEGER', 'DECIMAL', 'STRING', 'CATEGORY', 'VECTOR'),
    CONSTRAINT chk_feature_history_value_checksum
        CHECK match(value_checksum, '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT chk_feature_history_registry_head
        CHECK match(registry_head_fingerprint, '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT chk_feature_history_feature_fingerprint
        CHECK match(feature_fingerprint, '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT chk_feature_history_revision_nonce
        CHECK notEmpty(revision_nonce),
    CONSTRAINT chk_feature_history_revision_id
        CHECK match(revision_id, '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT chk_feature_history_input_checksum
        CHECK match(input_checksum, '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT chk_feature_history_calculator_fingerprint
        CHECK match(calculator_implementation_fingerprint, '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT chk_feature_history_manifest_checksum
        CHECK match(input_manifest_checksum, '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT chk_feature_history_lineage_checksum
        CHECK match(lineage_checksum, '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT chk_feature_history_record_checksum
        CHECK match(record_checksum, '^sha256:[0-9a-f]{64}$')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
-- High-cardinality entities stay in the sorting key, never in the partition
-- expression. The key follows the exact feature/version/entity query prefix.
ORDER BY
(
    registry_namespace_id,
    feature_name,
    feature_version,
    feature_fingerprint,
    entity_id,
    event_time,
    available_time,
    processing_time,
    revision_id
)
SETTINGS index_granularity = 8192;
