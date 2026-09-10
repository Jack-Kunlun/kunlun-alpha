-- Calendar source snapshots are sparse closure evidence, not a trading-day calendar.

CREATE TABLE IF NOT EXISTS calendar_snapshot_versions (
    version_id UUID PRIMARY KEY,
    source TEXT NOT NULL,
    exchange TEXT NOT NULL,
    year INTEGER NOT NULL,
    fingerprint BYTEA NOT NULL,
    operation_key_hash BYTEA,
    persisted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT calendar_snapshot_versions_source_ck CHECK (source <> ''),
    CONSTRAINT calendar_snapshot_versions_exchange_ck CHECK (exchange IN ('SH', 'SZ', 'BJ')),
    CONSTRAINT calendar_snapshot_versions_year_ck CHECK (year BETWEEN 1 AND 9999),
    CONSTRAINT calendar_snapshot_versions_fingerprint_ck CHECK (octet_length(fingerprint) = 32),
    CONSTRAINT calendar_snapshot_versions_operation_hash_ck
        CHECK (operation_key_hash IS NULL OR octet_length(operation_key_hash) = 32),
    CONSTRAINT calendar_snapshot_versions_scope_uk UNIQUE (version_id, source, exchange, year),
    CONSTRAINT calendar_snapshot_versions_operation_key_uk UNIQUE (operation_key_hash)
);

CREATE TABLE IF NOT EXISTS calendar_snapshot_holidays (
    version_id UUID NOT NULL,
    source TEXT NOT NULL,
    exchange TEXT NOT NULL,
    year INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    holiday_date DATE NOT NULL,
    reason TEXT NOT NULL,
    note TEXT,
    CONSTRAINT calendar_snapshot_holidays_pkey PRIMARY KEY (version_id, ordinal),
    CONSTRAINT calendar_snapshot_holidays_version_scope_fkey
        FOREIGN KEY (version_id, source, exchange, year)
        REFERENCES calendar_snapshot_versions (version_id, source, exchange, year)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT calendar_snapshot_holidays_source_ck CHECK (source <> ''),
    CONSTRAINT calendar_snapshot_holidays_exchange_ck CHECK (exchange IN ('SH', 'SZ', 'BJ')),
    CONSTRAINT calendar_snapshot_holidays_year_ck CHECK (year BETWEEN 1 AND 9999),
    CONSTRAINT calendar_snapshot_holidays_ordinal_ck CHECK (ordinal >= 0),
    CONSTRAINT calendar_snapshot_holidays_reason_ck
        CHECK (reason IN ('PUBLIC_HOLIDAY', 'TEMPORARY_CLOSURE', 'SPECIAL')),
    CONSTRAINT calendar_snapshot_holidays_date_year_ck
        CHECK (year = EXTRACT(YEAR FROM holiday_date)::INTEGER)
);

CREATE TABLE IF NOT EXISTS calendar_snapshot_latest (
    source TEXT NOT NULL,
    exchange TEXT NOT NULL,
    year INTEGER NOT NULL,
    version_id UUID NOT NULL,
    CONSTRAINT calendar_snapshot_latest_pkey PRIMARY KEY (source, exchange, year),
    CONSTRAINT calendar_snapshot_latest_version_scope_fkey
        FOREIGN KEY (version_id, source, exchange, year)
        REFERENCES calendar_snapshot_versions (version_id, source, exchange, year)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT calendar_snapshot_latest_source_ck CHECK (source <> ''),
    CONSTRAINT calendar_snapshot_latest_exchange_ck CHECK (exchange IN ('SH', 'SZ', 'BJ')),
    CONSTRAINT calendar_snapshot_latest_year_ck CHECK (year BETWEEN 1 AND 9999)
);

CREATE TABLE IF NOT EXISTS calendar_snapshot_corrections (
    correction_id UUID PRIMARY KEY,
    version_id UUID NOT NULL,
    source TEXT NOT NULL,
    exchange TEXT NOT NULL,
    year INTEGER NOT NULL,
    correction_date DATE NOT NULL,
    reason TEXT NOT NULL,
    note TEXT NOT NULL,
    author TEXT NOT NULL,
    persisted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT calendar_snapshot_corrections_version_scope_fkey
        FOREIGN KEY (version_id, source, exchange, year)
        REFERENCES calendar_snapshot_versions (version_id, source, exchange, year)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT calendar_snapshot_corrections_source_ck CHECK (source <> ''),
    CONSTRAINT calendar_snapshot_corrections_exchange_ck CHECK (exchange IN ('SH', 'SZ', 'BJ')),
    CONSTRAINT calendar_snapshot_corrections_year_ck CHECK (year BETWEEN 1 AND 9999),
    CONSTRAINT calendar_snapshot_corrections_date_year_ck
        CHECK (year = EXTRACT(YEAR FROM correction_date)::INTEGER)
);

CREATE TABLE IF NOT EXISTS calendar_snapshot_audit (
    audit_id UUID PRIMARY KEY,
    version_id UUID NOT NULL,
    source TEXT NOT NULL,
    exchange TEXT NOT NULL,
    year INTEGER NOT NULL,
    kind TEXT NOT NULL,
    entry TEXT NOT NULL,
    persisted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT calendar_snapshot_audit_version_scope_fkey
        FOREIGN KEY (version_id, source, exchange, year)
        REFERENCES calendar_snapshot_versions (version_id, source, exchange, year)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT calendar_snapshot_audit_source_ck CHECK (source <> ''),
    CONSTRAINT calendar_snapshot_audit_exchange_ck CHECK (exchange IN ('SH', 'SZ', 'BJ')),
    CONSTRAINT calendar_snapshot_audit_year_ck CHECK (year BETWEEN 1 AND 9999)
);

CREATE OR REPLACE FUNCTION calendar_snapshot_history_immutable()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'calendar snapshot history is immutable';
END;
$$;

CREATE TRIGGER calendar_snapshot_versions_immutable
BEFORE UPDATE OR DELETE ON calendar_snapshot_versions
FOR EACH ROW EXECUTE FUNCTION calendar_snapshot_history_immutable();

CREATE TRIGGER calendar_snapshot_holidays_immutable
BEFORE UPDATE OR DELETE ON calendar_snapshot_holidays
FOR EACH ROW EXECUTE FUNCTION calendar_snapshot_history_immutable();

CREATE TRIGGER calendar_snapshot_corrections_immutable
BEFORE UPDATE OR DELETE ON calendar_snapshot_corrections
FOR EACH ROW EXECUTE FUNCTION calendar_snapshot_history_immutable();

CREATE TRIGGER calendar_snapshot_audit_immutable
BEFORE UPDATE OR DELETE ON calendar_snapshot_audit
FOR EACH ROW EXECUTE FUNCTION calendar_snapshot_history_immutable();
