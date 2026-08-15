-- Canonical Phase 1 corporate-action schema.
--
-- The stable source event id and semantic versions are part of identity so
-- multiple actions can share an instrument and ex-date without overwriting
-- one another.  raw_capture_id remains provenance only.  There is no TTL.
-- available_time is the physical revision key for the same PIT-revision
-- retention reason; it is not semantic identity.
-- revision_fingerprint is a versioned SHA-256 of every persisted field and is
-- part of the physical key for deterministic conflict detection.

CREATE TABLE IF NOT EXISTS corporate_actions_v2
(
    unified_code        String,
    exchange            LowCardinality(String),
    ex_date             Date,
    event_time          DateTime64(3, 'UTC'),
    action_type         LowCardinality(String),
    source              LowCardinality(String),
    source_event_id     String,
    data_version        LowCardinality(String),
    source_version      String,
    raw_capture_id      String,
    available_time      DateTime64(3, 'UTC'),
    ingest_time         DateTime64(3, 'UTC'),
    processing_time     DateTime64(3, 'UTC'),
    replacement_version UInt64,
    description         String,
    per_share_cash      Nullable(Decimal(20, 8)),
    per_share_stock     Nullable(Decimal(20, 8)),
    ratio               Nullable(Decimal(20, 8)),
    revision_fingerprint FixedString(64) MATERIALIZED toFixedString(hex(SHA256(concat(
        'kunlun-p1-r06-fingerprint-v2|',
        'unified_code:S:', hex(unified_code), '|',
        'exchange:S:', hex(exchange), '|',
        'ex_date:D:', toString(toYYYYMMDD(ex_date)), '|',
        'event_time:T64:', toString(toUnixTimestamp64Milli(event_time)), '|',
        'action_type:S:', hex(action_type), '|',
        'source:S:', hex(source), '|',
        'source_event_id:S:', hex(source_event_id), '|',
        'data_version:S:', hex(data_version), '|',
        'source_version:S:', hex(source_version), '|',
        'raw_capture_id:S:', hex(raw_capture_id), '|',
        'available_time:T64:', toString(toUnixTimestamp64Milli(available_time)), '|',
        'ingest_time:T64:', toString(toUnixTimestamp64Milli(ingest_time)), '|',
        'processing_time:T64:', toString(toUnixTimestamp64Milli(processing_time)), '|',
        'replacement_version:U64:', toString(replacement_version), '|',
        'description:S:', hex(description), '|',
        'per_share_cash:', if(isNull(per_share_cash), 'N', concat('V:D20,8:', toString(CAST(assumeNotNull(per_share_cash), 'Decimal(20,8)')))), '|',
        'per_share_stock:', if(isNull(per_share_stock), 'N', concat('V:D20,8:', toString(CAST(assumeNotNull(per_share_stock), 'Decimal(20,8)')))), '|',
        'ratio:', if(isNull(ratio), 'N', concat('V:D20,8:', toString(CAST(assumeNotNull(ratio), 'Decimal(20,8)')))), '|'
    ))), 64)
)
ENGINE = ReplacingMergeTree(replacement_version)
PARTITION BY toYYYYMM(ex_date)
ORDER BY
(
    unified_code,
    ex_date,
    action_type,
    source,
    source_event_id,
    data_version,
    source_version,
    available_time,
    revision_fingerprint
)
SETTINGS index_granularity = 8192;
