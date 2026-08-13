-- ClickHouse corporate actions table.
--
-- Corporate actions are low-frequency reference data keyed by
-- (unified_code, ex_date); the ordering key matches the look-up pattern of
-- "all actions for an instrument since a date".

CREATE TABLE IF NOT EXISTS corporate_actions (
    unified_code String,
    exchange LowCardinality(String),
    ex_date Date,
    action_type LowCardinality(String),
    description String,
    per_share_cash Nullable(Decimal(20, 4)),
    per_share_stock Nullable(Decimal(20, 4)),
    ratio Nullable(Decimal(20, 4))
) ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(ex_date)
ORDER BY (unified_code, ex_date);
