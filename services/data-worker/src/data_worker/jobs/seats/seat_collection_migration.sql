CREATE TABLE IF NOT EXISTS seat_collection_raw_records (
    source TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    raw_record_id TEXT PRIMARY KEY,
    previous_revision_id TEXT,
    raw_payload BYTEA NOT NULL,
    raw_payload_hash CHAR(64) NOT NULL CHECK (raw_payload_hash ~ '^[0-9a-f]{64}$'),
    revision_key TEXT NOT NULL,
    revision_accepted BOOLEAN NOT NULL,
    is_latest BOOLEAN NOT NULL,
    CHECK (is_latest = FALSE OR revision_accepted = TRUE),
    raw_json JSONB NOT NULL,
    UNIQUE (source, revision_id)
);

CREATE INDEX IF NOT EXISTS idx_seat_collection_raw_latest
    ON seat_collection_raw_records (revision_key, is_latest);

CREATE UNIQUE INDEX IF NOT EXISTS uq_seat_collection_raw_latest
    ON seat_collection_raw_records (revision_key)
    WHERE is_latest = TRUE;

CREATE TABLE IF NOT EXISTS seat_collection_normalized (
    trade_id TEXT PRIMARY KEY,
    raw_record_id TEXT NOT NULL REFERENCES seat_collection_raw_records(raw_record_id),
    trade_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS seat_collection_rejected (
    raw_record_id TEXT NOT NULL REFERENCES seat_collection_raw_records(raw_record_id),
    reason TEXT NOT NULL,
    rejected_json JSONB NOT NULL,
    PRIMARY KEY (raw_record_id, reason)
);

CREATE TABLE IF NOT EXISTS seat_collection_batches (
    route_key TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_version TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    batch_fingerprint TEXT NOT NULL,
    expected_previous_checkpoint TEXT,
    checkpoint_token TEXT,
    result_json JSONB NOT NULL,
    PRIMARY KEY (route_key, batch_id),
    UNIQUE (route_key, request_fingerprint, batch_fingerprint)
);

CREATE TABLE IF NOT EXISTS seat_collection_checkpoints (
    route_key TEXT PRIMARY KEY,
    checkpoint_token TEXT,
    batch_id TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    batch_fingerprint TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
