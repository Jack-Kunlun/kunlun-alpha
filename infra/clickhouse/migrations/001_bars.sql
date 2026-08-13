-- ClickHouse market data schema: minute and daily bars.
--
-- Ordering key is (unified_code, timestamp) to match the dominant query
-- pattern (one instrument over a time range). Partitioning is monthly
-- (toYYYYMM) to avoid over-partitioning. ReplacingMergeTree makes batch
-- writes idempotent: re-inserting the same (unified_code, timestamp) row
-- replaces the previous one instead of duplicating it.

CREATE TABLE IF NOT EXISTS bars_minute (
    unified_code String,
    exchange LowCardinality(String),
    date Date,
    timestamp DateTime64(3, 'UTC'),
    open Decimal(20, 4),
    high Decimal(20, 4),
    low Decimal(20, 4),
    close Decimal(20, 4),
    volume UInt64,
    amount Decimal(20, 2),
    price_type LowCardinality(String)
) ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (unified_code, timestamp)
TTL timestamp + INTERVAL 3 YEAR;

CREATE TABLE IF NOT EXISTS bars_daily (
    unified_code String,
    exchange LowCardinality(String),
    date Date,
    timestamp DateTime64(3, 'UTC'),
    open Decimal(20, 4),
    high Decimal(20, 4),
    low Decimal(20, 4),
    close Decimal(20, 4),
    volume UInt64,
    amount Decimal(20, 2),
    price_type LowCardinality(String)
) ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (unified_code, timestamp)
TTL timestamp + INTERVAL 10 YEAR;
