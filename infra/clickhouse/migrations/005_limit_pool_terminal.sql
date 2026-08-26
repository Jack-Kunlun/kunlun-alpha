-- P6-N03 versioned point-in-time read model for the limit-pool terminal.
-- The producing pipeline must materialize the canonical Phase 2 algorithm
-- output. The terminal never reconstructs seal/open/streak facts from daily bars.
-- Historical rows remain immutable across algorithm and rule versions; no TTL.

CREATE TABLE IF NOT EXISTS limit_pool_terminal_snapshots_v2
(
    snapshot_id         String,
    trading_date        Date,
    event_time          DateTime64(3, 'UTC'),
    available_time      DateTime64(3, 'UTC'),
    revision            UInt32,
    algorithm_version   LowCardinality(String),
    ladder_algorithm_version LowCardinality(String),
    limit_rule_version  LowCardinality(String),
    materializer_version LowCardinality(String),
    source_versions     Array(String),
    evidence_ids        Array(String),
    payload_json        String,
    payload_digest      FixedString(64),
    processing_time     DateTime64(3, 'UTC'),
    replacement_version UInt64
)
ENGINE = ReplacingMergeTree(replacement_version)
PARTITION BY toYYYYMM(trading_date)
ORDER BY
(
    trading_date,
    event_time,
    algorithm_version,
    ladder_algorithm_version,
    limit_rule_version,
    materializer_version,
    revision,
    available_time,
    payload_digest
)
SETTINGS index_granularity = 8192;
