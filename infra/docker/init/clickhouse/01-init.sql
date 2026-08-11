-- Kunlun Alpha — ClickHouse 初始化脚本
-- 首次启动时由 docker-entrypoint-initdb.d 自动执行

-- 市场行情表（示例 schema，Phase 1 完善）
CREATE TABLE IF NOT EXISTS kunlun.market_bars
(
    instrument_code LowCardinality(String),
    trade_date      Date,
    open            Float64,
    high            Float64,
    low             Float64,
    close           Float64,
    volume          UInt64,
    amount          Float64,
    ingested_at     DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(trade_date)
ORDER BY (instrument_code, trade_date)
SETTINGS index_granularity = 8192;

-- 市场情绪快照表（示例 schema，Phase 2 完善）
CREATE TABLE IF NOT EXISTS kunlun.market_emotion
(
    trade_date        Date,
    emotion_score     Float32,
    limit_up_count    UInt16,
    limit_down_count  UInt16,
    broken_board_count UInt16,
    serial_board_max  UInt8,
    computed_at       DateTime DEFAULT now(),
    version           LowCardinality(String) DEFAULT 'v1'
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(trade_date)
ORDER BY (trade_date, version)
SETTINGS index_granularity = 8192;

-- 日志：确认初始化完成
SELECT 'ClickHouse init complete' AS status;
