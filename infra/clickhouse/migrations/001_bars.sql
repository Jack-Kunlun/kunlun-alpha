-- Canonical Phase 1 market bars schema.
--
-- The physical revision key is the complete ORDER BY tuple below.  Semantic
-- identity excludes available_time but includes instrument, interval, event
-- time, session, price type, data/source versions, and provider source.
-- raw_capture_id is provenance only; replacement_version is the
-- ReplacingMergeTree version and is not identity.
-- available_time is the physical revision key so revisions that become
-- available at different times survive background merges; it is not part of
-- the semantic identity used by PIT readers.
-- revision_fingerprint is a versioned SHA-256 of every persisted field.  It is
-- part of the physical key so exact replays merge while same-identity/version
-- payload conflicts remain physically observable to PIT readers.
-- Point-in-time readers must filter available_time before selecting the highest
-- replacement_version.
-- There is intentionally no TTL.

CREATE TABLE IF NOT EXISTS bars_minute_v2
(
    unified_code       String,
    exchange           LowCardinality(String),
    interval           LowCardinality(String),
    event_time         DateTime64(3, 'UTC'),
    session            LowCardinality(String),
    price_type         LowCardinality(String),
    data_version       LowCardinality(String),
    source             LowCardinality(String),
    source_version     String,
    raw_capture_id     String,
    available_time     DateTime64(3, 'UTC'),
    ingest_time        DateTime64(3, 'UTC'),
    processing_time    DateTime64(3, 'UTC'),
    replacement_version UInt64,
    date               Date,
    open               Decimal(20, 4),
    high               Decimal(20, 4),
    low                Decimal(20, 4),
    close              Decimal(20, 4),
    volume             UInt64,
    amount             Decimal(30, 2),
    suspended          UInt8,
    revision_fingerprint FixedString(64) MATERIALIZED toFixedString(hex(SHA256(concat(
        'kunlun-p1-r06-fingerprint-v2|',
        'unified_code:S:', hex(unified_code), '|',
        'exchange:S:', hex(exchange), '|',
        'interval:S:', hex(interval), '|',
        'event_time:T64:', toString(toUnixTimestamp64Milli(event_time)), '|',
        'session:S:', hex(session), '|',
        'price_type:S:', hex(price_type), '|',
        'data_version:S:', hex(data_version), '|',
        'source:S:', hex(source), '|',
        'source_version:S:', hex(source_version), '|',
        'raw_capture_id:S:', hex(raw_capture_id), '|',
        'available_time:T64:', toString(toUnixTimestamp64Milli(available_time)), '|',
        'ingest_time:T64:', toString(toUnixTimestamp64Milli(ingest_time)), '|',
        'processing_time:T64:', toString(toUnixTimestamp64Milli(processing_time)), '|',
        'replacement_version:U64:', toString(replacement_version), '|',
        'date:D:', toString(toYYYYMMDD(date)), '|',
        'open:D20,4:', toString(CAST(open, 'Decimal(20,4)')), '|',
        'high:D20,4:', toString(CAST(high, 'Decimal(20,4)')), '|',
        'low:D20,4:', toString(CAST(low, 'Decimal(20,4)')), '|',
        'close:D20,4:', toString(CAST(close, 'Decimal(20,4)')), '|',
        'volume:U64:', toString(volume), '|',
        'amount:D30,2:', toString(CAST(amount, 'Decimal(30,2)')), '|',
        'suspended:U8:', toString(suspended), '|'
    ))), 64)
)
ENGINE = ReplacingMergeTree(replacement_version)
PARTITION BY toYYYYMM(event_time)
ORDER BY
(
    unified_code,
    interval,
    event_time,
    session,
    price_type,
    data_version,
    source,
    source_version,
    available_time,
    revision_fingerprint
)
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS bars_daily_v2
(
    unified_code       String,
    exchange           LowCardinality(String),
    interval           LowCardinality(String),
    event_time         DateTime64(3, 'UTC'),
    session            LowCardinality(String),
    price_type         LowCardinality(String),
    data_version       LowCardinality(String),
    source             LowCardinality(String),
    source_version     String,
    raw_capture_id     String,
    available_time     DateTime64(3, 'UTC'),
    ingest_time        DateTime64(3, 'UTC'),
    processing_time    DateTime64(3, 'UTC'),
    replacement_version UInt64,
    date               Date,
    open               Decimal(20, 4),
    high               Decimal(20, 4),
    low                Decimal(20, 4),
    close              Decimal(20, 4),
    volume             UInt64,
    amount             Decimal(30, 2),
    suspended          UInt8,
    revision_fingerprint FixedString(64) MATERIALIZED toFixedString(hex(SHA256(concat(
        'kunlun-p1-r06-fingerprint-v2|',
        'unified_code:S:', hex(unified_code), '|',
        'exchange:S:', hex(exchange), '|',
        'interval:S:', hex(interval), '|',
        'event_time:T64:', toString(toUnixTimestamp64Milli(event_time)), '|',
        'session:S:', hex(session), '|',
        'price_type:S:', hex(price_type), '|',
        'data_version:S:', hex(data_version), '|',
        'source:S:', hex(source), '|',
        'source_version:S:', hex(source_version), '|',
        'raw_capture_id:S:', hex(raw_capture_id), '|',
        'available_time:T64:', toString(toUnixTimestamp64Milli(available_time)), '|',
        'ingest_time:T64:', toString(toUnixTimestamp64Milli(ingest_time)), '|',
        'processing_time:T64:', toString(toUnixTimestamp64Milli(processing_time)), '|',
        'replacement_version:U64:', toString(replacement_version), '|',
        'date:D:', toString(toYYYYMMDD(date)), '|',
        'open:D20,4:', toString(CAST(open, 'Decimal(20,4)')), '|',
        'high:D20,4:', toString(CAST(high, 'Decimal(20,4)')), '|',
        'low:D20,4:', toString(CAST(low, 'Decimal(20,4)')), '|',
        'close:D20,4:', toString(CAST(close, 'Decimal(20,4)')), '|',
        'volume:U64:', toString(volume), '|',
        'amount:D30,2:', toString(CAST(amount, 'Decimal(30,2)')), '|',
        'suspended:U8:', toString(suspended), '|'
    ))), 64)
)
ENGINE = ReplacingMergeTree(replacement_version)
PARTITION BY toYYYYMM(event_time)
ORDER BY
(
    unified_code,
    interval,
    event_time,
    session,
    price_type,
    data_version,
    source,
    source_version,
    available_time,
    revision_fingerprint
)
SETTINGS index_granularity = 8192;
