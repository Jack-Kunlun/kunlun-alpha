-- Additive V5 calendar-quality evidence ledger.
-- The tables contain derived, redacted evidence only; V3/V4 source rows remain
-- immutable and are never updated by this migration.

CREATE TABLE calendar_quality_assessments (
    assessment_id UUID PRIMARY KEY,
    operation_id TEXT NOT NULL,
    operation_key_hash BYTEA NOT NULL,
    content_fingerprint BYTEA NOT NULL,
    exchange TEXT NOT NULL,
    calendar_year INTEGER NOT NULL,
    status TEXT NOT NULL,
    coverage_level TEXT NOT NULL,
    confirmed_through DATE,
    detected_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    source_count INTEGER NOT NULL,
    missing_date_count INTEGER NOT NULL,
    conflict_date_count INTEGER NOT NULL,
    confirmed_days_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT calendar_quality_assessments_operation_uk UNIQUE (operation_key_hash),
    CONSTRAINT calendar_quality_assessments_operation_id_ck CHECK (operation_id <> ''),
    CONSTRAINT calendar_quality_assessments_operation_hash_ck
        CHECK (octet_length(operation_key_hash) = 32),
    CONSTRAINT calendar_quality_assessments_content_hash_ck
        CHECK (octet_length(content_fingerprint) = 32),
    CONSTRAINT calendar_quality_assessments_exchange_ck
        CHECK (exchange IN ('SH', 'SZ', 'BJ')),
    CONSTRAINT calendar_quality_assessments_year_ck
        CHECK (calendar_year BETWEEN 1 AND 9999),
    CONSTRAINT calendar_quality_assessments_status_ck
        CHECK (status IN ('COMPLETE', 'INDETERMINATE', 'MISSING_COVERAGE', 'CONFLICT')),
    CONSTRAINT calendar_quality_assessments_coverage_ck
        CHECK (coverage_level IN ('UNKNOWN', 'INDETERMINATE', 'CONFIRMED_HORIZON', 'FINAL_YEAR')),
    CONSTRAINT calendar_quality_assessments_confirmed_ck
        CHECK (
            (coverage_level IN ('UNKNOWN', 'INDETERMINATE') AND confirmed_through IS NULL)
            OR (coverage_level = 'CONFIRMED_HORIZON'
                AND confirmed_through BETWEEN make_date(calendar_year, 1, 1)
                AND make_date(calendar_year, 12, 31))
            OR (coverage_level = 'FINAL_YEAR'
                AND confirmed_through = make_date(calendar_year, 12, 31))
        ),
    CONSTRAINT calendar_quality_assessments_window_ck
        CHECK (detected_at <= available_at),
    CONSTRAINT calendar_quality_assessments_counts_ck
        CHECK (source_count >= 0 AND missing_date_count >= 0 AND conflict_date_count >= 0),
    CONSTRAINT calendar_quality_assessments_confirmed_days_ck
        CHECK (jsonb_typeof(confirmed_days_json) = 'array')
);

CREATE TABLE calendar_quality_assessment_sources (
    assessment_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    source_id UUID NOT NULL,
    source_kind TEXT NOT NULL,
    source_name TEXT NOT NULL,
    exchange TEXT NOT NULL,
    calendar_year INTEGER NOT NULL,
    coverage_level TEXT NOT NULL,
    confirmed_through DATE,
    captured_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    content_fingerprint BYTEA NOT NULL,
    source_fingerprint BYTEA NOT NULL,
    evidence_links_json JSONB NOT NULL,
    days_json JSONB NOT NULL,
    closures_json JSONB NOT NULL,
    CONSTRAINT calendar_quality_assessment_sources_pkey PRIMARY KEY (assessment_id, ordinal),
    CONSTRAINT calendar_quality_assessment_sources_id_uk UNIQUE (assessment_id, source_id),
    CONSTRAINT calendar_quality_assessment_sources_assessment_fkey
        FOREIGN KEY (assessment_id) REFERENCES calendar_quality_assessments (assessment_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT calendar_quality_assessment_sources_ordinal_ck CHECK (ordinal >= 0),
    CONSTRAINT calendar_quality_assessment_sources_kind_ck
        CHECK (source_kind IN ('SPARSE', 'OFFICIAL', 'SECONDARY')),
    CONSTRAINT calendar_quality_assessment_sources_exchange_ck
        CHECK (exchange IN ('SH', 'SZ', 'BJ')),
    CONSTRAINT calendar_quality_assessment_sources_year_ck
        CHECK (calendar_year BETWEEN 1 AND 9999),
    CONSTRAINT calendar_quality_assessment_sources_coverage_ck
        CHECK (coverage_level IN ('UNKNOWN', 'INDETERMINATE', 'CONFIRMED_HORIZON', 'FINAL_YEAR')),
    CONSTRAINT calendar_quality_assessment_sources_hash_ck
        CHECK (octet_length(content_fingerprint) = 32),
    CONSTRAINT calendar_quality_assessment_sources_source_hash_ck
        CHECK (octet_length(source_fingerprint) = 32),
    CONSTRAINT calendar_quality_assessment_sources_links_ck
        CHECK (jsonb_typeof(evidence_links_json) = 'array'
               AND jsonb_array_length(evidence_links_json) > 0),
    CONSTRAINT calendar_quality_assessment_sources_days_ck
        CHECK (jsonb_typeof(days_json) = 'array'),
    CONSTRAINT calendar_quality_assessment_sources_closures_ck
        CHECK (jsonb_typeof(closures_json) = 'array'),
    CONSTRAINT calendar_quality_assessment_sources_window_ck
        CHECK (captured_at <= available_at)
);

CREATE TABLE calendar_quality_assessment_days (
    assessment_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    calendar_date DATE NOT NULL,
    is_trading_day BOOLEAN NOT NULL,
    reason TEXT,
    CONSTRAINT calendar_quality_assessment_days_pkey PRIMARY KEY (assessment_id, ordinal),
    CONSTRAINT calendar_quality_assessment_days_date_uk UNIQUE (assessment_id, calendar_date),
    CONSTRAINT calendar_quality_assessment_days_assessment_fkey
        FOREIGN KEY (assessment_id) REFERENCES calendar_quality_assessments (assessment_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT calendar_quality_assessment_days_ordinal_ck CHECK (ordinal >= 0),
    CONSTRAINT calendar_quality_assessment_days_reason_ck
        CHECK (reason IS NULL OR reason IN ('WEEKEND', 'PUBLIC_HOLIDAY', 'TEMPORARY_CLOSURE', 'SPECIAL'))
);

CREATE TABLE calendar_quality_missing_dates (
    assessment_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    calendar_date DATE NOT NULL,
    CONSTRAINT calendar_quality_missing_dates_pkey PRIMARY KEY (assessment_id, ordinal),
    CONSTRAINT calendar_quality_missing_dates_date_uk UNIQUE (assessment_id, calendar_date),
    CONSTRAINT calendar_quality_missing_dates_assessment_fkey
        FOREIGN KEY (assessment_id) REFERENCES calendar_quality_assessments (assessment_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT calendar_quality_missing_dates_ordinal_ck CHECK (ordinal >= 0)
);

CREATE TABLE calendar_quality_alerts (
    alert_id UUID PRIMARY KEY,
    assessment_id UUID NOT NULL,
    kind TEXT NOT NULL,
    calendar_date DATE,
    detail_code TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    source_count INTEGER NOT NULL,
    evidence_fingerprint BYTEA NOT NULL,
    CONSTRAINT calendar_quality_alerts_assessment_fkey
        FOREIGN KEY (assessment_id) REFERENCES calendar_quality_assessments (assessment_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT calendar_quality_alerts_kind_ck
        CHECK (kind IN ('MISSING_COVERAGE', 'SOURCE_CONFLICT', 'TEMPORARY_CLOSURE')),
    CONSTRAINT calendar_quality_alerts_detail_ck
        CHECK (detail_code IN ('DATE_NOT_CONFIRMED', 'DAY_STATUS_DISAGREEMENT', 'EXPLICIT_CLOSURE_EVIDENCE')),
    CONSTRAINT calendar_quality_alerts_hash_ck
        CHECK (octet_length(evidence_fingerprint) = 32),
    CONSTRAINT calendar_quality_alerts_counts_ck CHECK (source_count >= 0),
    CONSTRAINT calendar_quality_alerts_window_ck CHECK (detected_at <= available_at),
    CONSTRAINT calendar_quality_alerts_identity_uk
        UNIQUE (assessment_id, kind, calendar_date, evidence_fingerprint)
);

CREATE TABLE calendar_quality_alert_sources (
    alert_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    source_id UUID NOT NULL,
    evidence_ref TEXT NOT NULL,
    artifact_sha256 BYTEA NOT NULL,
    CONSTRAINT calendar_quality_alert_sources_pkey PRIMARY KEY (alert_id, ordinal),
    CONSTRAINT calendar_quality_alert_sources_alert_fkey
        FOREIGN KEY (alert_id) REFERENCES calendar_quality_alerts (alert_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT calendar_quality_alert_sources_ordinal_ck CHECK (ordinal >= 0),
    CONSTRAINT calendar_quality_alert_sources_ref_ck CHECK (evidence_ref <> ''),
    CONSTRAINT calendar_quality_alert_sources_digest_ck CHECK (octet_length(artifact_sha256) = 32)
);

CREATE TABLE calendar_quality_manual_overlays (
    overlay_id UUID PRIMARY KEY,
    operation_id TEXT NOT NULL,
    operation_key_hash BYTEA NOT NULL,
    assessment_id UUID NOT NULL,
    source_id UUID NOT NULL,
    calendar_date DATE NOT NULL,
    decision TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    note TEXT NOT NULL,
    author TEXT NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT calendar_quality_manual_overlays_operation_uk UNIQUE (operation_key_hash),
    CONSTRAINT calendar_quality_manual_overlays_operation_id_ck CHECK (operation_id <> ''),
    CONSTRAINT calendar_quality_manual_overlays_operation_hash_ck
        CHECK (octet_length(operation_key_hash) = 32),
    CONSTRAINT calendar_quality_manual_overlays_assessment_fkey
        FOREIGN KEY (assessment_id) REFERENCES calendar_quality_assessments (assessment_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT calendar_quality_manual_overlays_source_fkey
        FOREIGN KEY (assessment_id, source_id)
        REFERENCES calendar_quality_assessment_sources (assessment_id, source_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT calendar_quality_manual_overlays_decision_ck
        CHECK (decision IN ('TRADING', 'NON_TRADING', 'REVIEW')),
    CONSTRAINT calendar_quality_manual_overlays_reason_ck CHECK (reason_code <> ''),
    CONSTRAINT calendar_quality_manual_overlays_author_ck CHECK (author <> '')
);

CREATE TABLE calendar_quality_audit (
    audit_id UUID PRIMARY KEY,
    assessment_id UUID NOT NULL,
    operation_key_hash BYTEA NOT NULL,
    action TEXT NOT NULL,
    entry TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT calendar_quality_audit_assessment_fkey
        FOREIGN KEY (assessment_id) REFERENCES calendar_quality_assessments (assessment_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT calendar_quality_audit_operation_hash_ck
        CHECK (octet_length(operation_key_hash) = 32),
    CONSTRAINT calendar_quality_audit_action_ck
        CHECK (action IN ('ASSESSMENT_CREATED', 'MANUAL_OVERLAY_CREATED')),
    CONSTRAINT calendar_quality_audit_entry_ck CHECK (entry <> '')
);

CREATE FUNCTION calendar_quality_history_immutable()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'calendar quality history is immutable';
END;
$$;

CREATE FUNCTION calendar_quality_no_truncate()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'calendar quality history is immutable';
END;
$$;

CREATE TRIGGER calendar_quality_assessments_immutable
BEFORE UPDATE OR DELETE ON calendar_quality_assessments
FOR EACH ROW EXECUTE FUNCTION calendar_quality_history_immutable();

CREATE TRIGGER calendar_quality_assessment_sources_immutable
BEFORE UPDATE OR DELETE ON calendar_quality_assessment_sources
FOR EACH ROW EXECUTE FUNCTION calendar_quality_history_immutable();

CREATE TRIGGER calendar_quality_assessment_days_immutable
BEFORE UPDATE OR DELETE ON calendar_quality_assessment_days
FOR EACH ROW EXECUTE FUNCTION calendar_quality_history_immutable();

CREATE TRIGGER calendar_quality_missing_dates_immutable
BEFORE UPDATE OR DELETE ON calendar_quality_missing_dates
FOR EACH ROW EXECUTE FUNCTION calendar_quality_history_immutable();

CREATE TRIGGER calendar_quality_alerts_immutable
BEFORE UPDATE OR DELETE ON calendar_quality_alerts
FOR EACH ROW EXECUTE FUNCTION calendar_quality_history_immutable();

CREATE TRIGGER calendar_quality_alert_sources_immutable
BEFORE UPDATE OR DELETE ON calendar_quality_alert_sources
FOR EACH ROW EXECUTE FUNCTION calendar_quality_history_immutable();

CREATE TRIGGER calendar_quality_manual_overlays_immutable
BEFORE UPDATE OR DELETE ON calendar_quality_manual_overlays
FOR EACH ROW EXECUTE FUNCTION calendar_quality_history_immutable();

CREATE TRIGGER calendar_quality_audit_immutable
BEFORE UPDATE OR DELETE ON calendar_quality_audit
FOR EACH ROW EXECUTE FUNCTION calendar_quality_history_immutable();

CREATE TRIGGER calendar_quality_assessments_no_truncate
BEFORE TRUNCATE ON calendar_quality_assessments
EXECUTE FUNCTION calendar_quality_no_truncate();

CREATE TRIGGER calendar_quality_assessment_sources_no_truncate
BEFORE TRUNCATE ON calendar_quality_assessment_sources
EXECUTE FUNCTION calendar_quality_no_truncate();

CREATE TRIGGER calendar_quality_assessment_days_no_truncate
BEFORE TRUNCATE ON calendar_quality_assessment_days
EXECUTE FUNCTION calendar_quality_no_truncate();

CREATE TRIGGER calendar_quality_missing_dates_no_truncate
BEFORE TRUNCATE ON calendar_quality_missing_dates
EXECUTE FUNCTION calendar_quality_no_truncate();

CREATE TRIGGER calendar_quality_alerts_no_truncate
BEFORE TRUNCATE ON calendar_quality_alerts
EXECUTE FUNCTION calendar_quality_no_truncate();

CREATE TRIGGER calendar_quality_alert_sources_no_truncate
BEFORE TRUNCATE ON calendar_quality_alert_sources
EXECUTE FUNCTION calendar_quality_no_truncate();

CREATE TRIGGER calendar_quality_manual_overlays_no_truncate
BEFORE TRUNCATE ON calendar_quality_manual_overlays
EXECUTE FUNCTION calendar_quality_no_truncate();

CREATE TRIGGER calendar_quality_audit_no_truncate
BEFORE TRUNCATE ON calendar_quality_audit
EXECUTE FUNCTION calendar_quality_no_truncate();
