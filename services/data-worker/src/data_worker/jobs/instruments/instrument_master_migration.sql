-- P1-N06 private Tushare instrument-master provider schema.
--
-- This resource is fully qualified and is applied only by the dedicated
-- provider migrator after the role bootstrap has created the private schema.
-- It never creates, alters, or references the legacy kunlun projection.

CREATE TABLE IF NOT EXISTS "kunlun_instrument_provider"."tushare_instrument_master_schema_migrations" (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS "kunlun_instrument_provider"."tushare_instrument_master_runs" (
    run_id UUID PRIMARY KEY,
    source TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    source_revision TEXT,
    manifest_date DATE NOT NULL,
    manifest_capture_id TEXT NOT NULL,
    manifest_object_id CHAR(64) NOT NULL,
    terminal TEXT NOT NULL,
    completeness TEXT NOT NULL,
    disposition TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT tushare_instrument_master_runs_source_ck
        CHECK (source = 'tushare-instrument-master'),
    CONSTRAINT tushare_instrument_master_runs_profile_ck
        CHECK (profile_version = 'tushare-instrument-profile-v1'),
    CONSTRAINT tushare_instrument_master_runs_schema_ck
        CHECK (schema_version = 'tushare-instrument-raw-v1'),
    CONSTRAINT tushare_instrument_master_runs_parser_ck
        CHECK (parser_version = 'tushare-instrument-parser-v1'),
    CONSTRAINT tushare_instrument_master_runs_manifest_capture_ck
        CHECK (manifest_capture_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CONSTRAINT tushare_instrument_master_runs_manifest_object_ck
        CHECK (manifest_object_id ~ '^[0-9a-f]{64}$'),
    CONSTRAINT tushare_instrument_master_runs_terminal_ck
        CHECK (terminal IN ('COMPLETE', 'INDETERMINATE', 'FAILED')),
    CONSTRAINT tushare_instrument_master_runs_completeness_ck
        CHECK (completeness IN ('COMPLETE', 'INDETERMINATE', 'REJECTED')),
    CONSTRAINT tushare_instrument_master_runs_disposition_ck
        CHECK (disposition IN ('SNAPSHOT_CANDIDATE', 'NO_HEAD_CHANGE', 'REJECTED')),
    CONSTRAINT tushare_instrument_master_runs_count_ck CHECK (record_count >= 0),
    CONSTRAINT tushare_instrument_master_runs_timeline_ck CHECK (opened_at <= completed_at),
    CONSTRAINT tushare_instrument_master_runs_manifest_uk
        UNIQUE (source, manifest_capture_id)
);

CREATE TABLE IF NOT EXISTS "kunlun_instrument_provider"."tushare_instrument_master_raw_refs" (
    run_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    ref_kind TEXT NOT NULL,
    api_name TEXT NOT NULL,
    status_partition TEXT NOT NULL,
    market_partition TEXT,
    offset_value INTEGER NOT NULL,
    capture_id TEXT NOT NULL,
    object_id CHAR(64) NOT NULL,
    raw_date DATE NOT NULL,
    request_identity TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    row_count INTEGER NOT NULL,
    state TEXT NOT NULL,
    source_revision TEXT,
    CONSTRAINT tushare_instrument_master_raw_refs_pkey PRIMARY KEY (run_id, ordinal),
    CONSTRAINT tushare_instrument_master_raw_refs_run_fkey FOREIGN KEY (run_id)
        REFERENCES "kunlun_instrument_provider"."tushare_instrument_master_runs"
        (run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT tushare_instrument_master_raw_refs_ordinal_ck CHECK (ordinal >= 0),
    CONSTRAINT tushare_instrument_master_raw_refs_kind_ck
        CHECK (ref_kind IN ('PAGE', 'ATTEMPT')),
    CONSTRAINT tushare_instrument_master_raw_refs_api_ck
        CHECK (api_name IN ('stock_basic', 'fund_basic')),
    CONSTRAINT tushare_instrument_master_raw_refs_status_ck
        CHECK (status_partition IN ('L', 'P', 'D')),
    CONSTRAINT tushare_instrument_master_raw_refs_market_ck
        CHECK ((api_name = 'stock_basic' AND market_partition IS NULL)
            OR (api_name = 'fund_basic' AND market_partition = 'E')),
    CONSTRAINT tushare_instrument_master_raw_refs_offset_ck CHECK (offset_value >= 0),
    CONSTRAINT tushare_instrument_master_raw_refs_capture_ck
        CHECK (capture_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CONSTRAINT tushare_instrument_master_raw_refs_object_ck
        CHECK (object_id ~ '^[0-9a-f]{64}$'),
    CONSTRAINT tushare_instrument_master_raw_refs_status_code_ck
        CHECK (status_code BETWEEN 0 AND 599),
    CONSTRAINT tushare_instrument_master_raw_refs_timeline_ck
        CHECK (observed_at <= available_at),
    CONSTRAINT tushare_instrument_master_raw_refs_count_ck CHECK (row_count >= 0),
    CONSTRAINT tushare_instrument_master_raw_refs_state_ck
        CHECK (state IN ('ACCEPTED_RESPONSE', 'REJECTED_RESPONSE', 'TRANSPORT_ERROR')),
    CONSTRAINT tushare_instrument_master_raw_refs_capture_uk UNIQUE (run_id, capture_id)
);

CREATE TABLE IF NOT EXISTS "kunlun_instrument_provider"."tushare_instrument_master_checkpoints" (
    profile_version TEXT NOT NULL,
    source TEXT NOT NULL,
    partition_ordinal INTEGER NOT NULL,
    next_offset INTEGER NOT NULL,
    run_id UUID NOT NULL,
    state TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT tushare_instrument_master_checkpoints_pkey
        PRIMARY KEY (profile_version, source),
    CONSTRAINT tushare_instrument_master_checkpoints_run_fkey FOREIGN KEY (run_id)
        REFERENCES "kunlun_instrument_provider"."tushare_instrument_master_runs"
        (run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT tushare_instrument_master_checkpoints_profile_ck
        CHECK (profile_version = 'tushare-instrument-profile-v1'),
    CONSTRAINT tushare_instrument_master_checkpoints_source_ck
        CHECK (source = 'tushare-instrument-master'),
    CONSTRAINT tushare_instrument_master_checkpoints_partition_ck
        CHECK (partition_ordinal BETWEEN 0 AND 4),
    CONSTRAINT tushare_instrument_master_checkpoints_offset_ck CHECK (next_offset >= 0),
    CONSTRAINT tushare_instrument_master_checkpoints_state_ck
        CHECK (state IN ('ACTIVE', 'COMPLETE', 'INDETERMINATE', 'FAILED'))
);

CREATE TABLE IF NOT EXISTS "kunlun_instrument_provider"."tushare_instrument_master_snapshots" (
    snapshot_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    source TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    terminal TEXT NOT NULL,
    completeness TEXT NOT NULL,
    disposition TEXT NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT tushare_instrument_master_snapshots_run_uk UNIQUE (run_id),
    CONSTRAINT tushare_instrument_master_snapshots_run_fkey FOREIGN KEY (run_id)
        REFERENCES "kunlun_instrument_provider"."tushare_instrument_master_runs"
        (run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT tushare_instrument_master_snapshots_source_ck
        CHECK (source = 'tushare-instrument-master'),
    CONSTRAINT tushare_instrument_master_snapshots_profile_ck
        CHECK (profile_version = 'tushare-instrument-profile-v1'),
    CONSTRAINT tushare_instrument_master_snapshots_terminal_ck
        CHECK (terminal IN ('COMPLETE', 'INDETERMINATE')),
    CONSTRAINT tushare_instrument_master_snapshots_completeness_ck
        CHECK (completeness IN ('COMPLETE', 'INDETERMINATE', 'REJECTED')),
    CONSTRAINT tushare_instrument_master_snapshots_disposition_ck
        CHECK (disposition IN ('SNAPSHOT_CANDIDATE', 'NO_HEAD_CHANGE', 'REJECTED')),
    CONSTRAINT tushare_instrument_master_snapshots_timeline_ck
        CHECK (available_at <= published_at)
);

CREATE TABLE IF NOT EXISTS "kunlun_instrument_provider"."tushare_instrument_master_revisions" (
    revision_id UUID PRIMARY KEY,
    snapshot_id UUID NOT NULL,
    unified_code TEXT NOT NULL,
    code TEXT NOT NULL,
    exchange TEXT NOT NULL,
    board TEXT NOT NULL,
    security_type TEXT NOT NULL,
    name TEXT NOT NULL,
    listing_lifecycle TEXT NOT NULL,
    trading_availability TEXT NOT NULL,
    risk_tags TEXT[] NOT NULL,
    list_date DATE,
    delist_date DATE,
    observed_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,
    source_revision TEXT,
    evidence_ref TEXT NOT NULL,
    payload_fingerprint CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT tushare_instrument_master_revisions_snapshot_fkey FOREIGN KEY (snapshot_id)
        REFERENCES "kunlun_instrument_provider"."tushare_instrument_master_snapshots"
        (snapshot_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT tushare_instrument_master_revisions_code_ck CHECK (
        unified_code ~ '^[0-9]{6}\.(SH|SZ|BJ)$'
        AND code ~ '^[0-9]{6}$'
        AND substring(unified_code, 1, 6) = code
        AND substring(unified_code, 8, 2) = exchange
    ),
    CONSTRAINT tushare_instrument_master_revisions_exchange_ck
        CHECK (exchange IN ('SH', 'SZ', 'BJ')),
    CONSTRAINT tushare_instrument_master_revisions_board_ck
        CHECK (board IN ('MAIN', 'CHINEXT', 'STAR', 'BSE')),
    CONSTRAINT tushare_instrument_master_revisions_type_ck
        CHECK (security_type IN ('STOCK', 'ETF', 'LOF', 'FUND')),
    CONSTRAINT tushare_instrument_master_revisions_lifecycle_ck
        CHECK (listing_lifecycle IN ('PRE_LISTING', 'LISTED', 'DELISTED', 'UNKNOWN')),
    CONSTRAINT tushare_instrument_master_revisions_availability_ck
        CHECK (trading_availability IN (
            'ACTIVE', 'SUSPENDED_FULL_DAY', 'SUSPENDED_PARTIAL', 'UNKNOWN'
        )),
    CONSTRAINT tushare_instrument_master_revisions_dates_ck
        CHECK (delist_date IS NULL OR list_date IS NULL OR list_date <= delist_date),
    CONSTRAINT tushare_instrument_master_revisions_timeline_ck
        CHECK (observed_at <= available_at),
    CONSTRAINT tushare_instrument_master_revisions_source_ck
        CHECK (source = 'tushare-instrument-master'),
    CONSTRAINT tushare_instrument_master_revisions_evidence_ck
        CHECK (evidence_ref ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CONSTRAINT tushare_instrument_master_revisions_fingerprint_ck
        CHECK (payload_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT tushare_instrument_master_revisions_payload_uk
        UNIQUE (unified_code, payload_fingerprint)
);

CREATE INDEX IF NOT EXISTS tushare_instrument_master_revisions_pit_idx
    ON "kunlun_instrument_provider"."tushare_instrument_master_revisions"
       (unified_code, available_at, created_at, revision_id);

CREATE TABLE IF NOT EXISTS "kunlun_instrument_provider"."tushare_instrument_master_snapshot_revisions" (
    snapshot_id UUID NOT NULL,
    revision_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    CONSTRAINT tushare_instrument_master_snapshot_revisions_pkey
        PRIMARY KEY (snapshot_id, revision_id),
    CONSTRAINT tushare_instrument_master_snapshot_revisions_snapshot_fkey
        FOREIGN KEY (snapshot_id)
        REFERENCES "kunlun_instrument_provider"."tushare_instrument_master_snapshots"
        (snapshot_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT tushare_instrument_master_snapshot_revisions_revision_fkey
        FOREIGN KEY (revision_id)
        REFERENCES "kunlun_instrument_provider"."tushare_instrument_master_revisions"
        (revision_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT tushare_instrument_master_snapshot_revisions_ordinal_ck
        CHECK (ordinal >= 0),
    CONSTRAINT tushare_instrument_master_snapshot_revisions_revision_uk
        UNIQUE (snapshot_id, ordinal)
);

CREATE TABLE IF NOT EXISTS "kunlun_instrument_provider"."tushare_instrument_master_heads" (
    unified_code TEXT PRIMARY KEY,
    revision_id UUID NOT NULL,
    ordering_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT tushare_instrument_master_heads_revision_uk UNIQUE (revision_id),
    CONSTRAINT tushare_instrument_master_heads_revision_fkey FOREIGN KEY (revision_id)
        REFERENCES "kunlun_instrument_provider"."tushare_instrument_master_revisions"
        (revision_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT tushare_instrument_master_heads_code_ck
        CHECK (unified_code ~ '^[0-9]{6}\.(SH|SZ|BJ)$')
);

CREATE TABLE IF NOT EXISTS "kunlun_instrument_provider"."tushare_instrument_master_removal_candidates" (
    candidate_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    unified_code TEXT NOT NULL,
    prior_revision_id UUID,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT tushare_instrument_master_removal_candidates_run_fkey FOREIGN KEY (run_id)
        REFERENCES "kunlun_instrument_provider"."tushare_instrument_master_runs"
        (run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT tushare_instrument_master_removal_candidates_prior_fkey
        FOREIGN KEY (prior_revision_id)
        REFERENCES "kunlun_instrument_provider"."tushare_instrument_master_revisions"
        (revision_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT tushare_instrument_master_removal_candidates_code_ck
        CHECK (unified_code ~ '^[0-9]{6}\.(SH|SZ|BJ)$'),
    CONSTRAINT tushare_instrument_master_removal_candidates_status_ck
        CHECK (status IN ('REMOVAL_CANDIDATE', 'INDETERMINATE', 'REVIEWED')),
    CONSTRAINT tushare_instrument_master_removal_candidates_evidence_ck
        CHECK (evidence_ref IS NULL OR evidence_ref ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
);

CREATE TABLE IF NOT EXISTS "kunlun_instrument_provider"."tushare_instrument_master_audit" (
    audit_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    snapshot_id UUID,
    unified_code TEXT,
    action TEXT NOT NULL,
    before_revision_id UUID,
    after_revision_id UUID,
    details JSONB NOT NULL,
    actor TEXT NOT NULL DEFAULT CURRENT_USER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT tushare_instrument_master_audit_run_fkey FOREIGN KEY (run_id)
        REFERENCES "kunlun_instrument_provider"."tushare_instrument_master_runs"
        (run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT tushare_instrument_master_audit_snapshot_fkey FOREIGN KEY (snapshot_id)
        REFERENCES "kunlun_instrument_provider"."tushare_instrument_master_snapshots"
        (snapshot_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT tushare_instrument_master_audit_before_fkey FOREIGN KEY (before_revision_id)
        REFERENCES "kunlun_instrument_provider"."tushare_instrument_master_revisions"
        (revision_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT tushare_instrument_master_audit_after_fkey FOREIGN KEY (after_revision_id)
        REFERENCES "kunlun_instrument_provider"."tushare_instrument_master_revisions"
        (revision_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT tushare_instrument_master_audit_action_ck CHECK (
        action IN (
            'RUN_ACCEPTED', 'RUN_REJECTED', 'SNAPSHOT_PUBLISHED',
            'REVISION_ADDED', 'REMOVAL_CANDIDATE', 'DUPLICATE', 'CONFLICT',
            'OUT_OF_ORDER_BLOCKED', 'ORDER_CONFLICT'
        )
    ),
    CONSTRAINT tushare_instrument_master_audit_code_ck
        CHECK (unified_code IS NULL OR unified_code ~ '^[0-9]{6}\.(SH|SZ|BJ)$'),
    CONSTRAINT tushare_instrument_master_audit_details_ck
        CHECK (jsonb_typeof(details) = 'object')
);

CREATE OR REPLACE FUNCTION "kunlun_instrument_provider"."tushare_instrument_master_history_immutable"()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION 'instrument master history is immutable';
END;
$$;

CREATE OR REPLACE FUNCTION "kunlun_instrument_provider"."tushare_instrument_master_current_actor"()
RETURNS TEXT
LANGUAGE sql
STABLE
SET search_path = pg_catalog, pg_temp
AS $$ SELECT CURRENT_USER::TEXT $$;

CREATE OR REPLACE FUNCTION "kunlun_instrument_provider"."tushare_instrument_master_audit_actor_immutable"()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    NEW.actor := CURRENT_USER::TEXT;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION "kunlun_instrument_provider"."tushare_instrument_master_publish_head"(
    p_unified_code TEXT,
    p_revision_id UUID,
    p_ordering_at TIMESTAMPTZ
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    target_available TIMESTAMPTZ;
    current_revision UUID;
    current_ordering TIMESTAMPTZ;
BEGIN
    IF p_ordering_at IS NULL THEN
        RAISE EXCEPTION 'instrument master ordering coordinate is invalid';
    END IF;
    SELECT r.available_at
      INTO target_available
      FROM "kunlun_instrument_provider"."tushare_instrument_master_revisions" AS r
     WHERE r.revision_id = p_revision_id
       AND r.unified_code = p_unified_code;
    IF target_available IS NULL THEN
        RAISE EXCEPTION 'instrument master revision identity mismatch';
    END IF;
    IF p_ordering_at < target_available THEN
        RAISE EXCEPTION 'instrument master ordering coordinate precedes revision';
    END IF;

    SELECT h.revision_id, h.ordering_at
      INTO current_revision, current_ordering
      FROM "kunlun_instrument_provider"."tushare_instrument_master_heads" AS h
     WHERE h.unified_code = p_unified_code
     FOR UPDATE;
    IF current_revision IS NOT NULL THEN
        IF current_ordering > p_ordering_at THEN
            RETURN FALSE;
        END IF;
        IF current_ordering = p_ordering_at AND current_revision <> p_revision_id THEN
            RAISE EXCEPTION 'instrument master ordering conflict';
        END IF;
    END IF;

    INSERT INTO "kunlun_instrument_provider"."tushare_instrument_master_heads"
        (unified_code, revision_id, ordering_at)
    VALUES (p_unified_code, p_revision_id, p_ordering_at)
    ON CONFLICT (unified_code) DO UPDATE
        SET revision_id = EXCLUDED.revision_id,
            ordering_at = EXCLUDED.ordering_at,
            updated_at = CURRENT_TIMESTAMP;
    RETURN TRUE;
END;
$$;

ALTER TABLE "kunlun_instrument_provider"."tushare_instrument_master_audit"
    ALTER COLUMN actor SET DEFAULT CURRENT_USER;

DROP TRIGGER IF EXISTS tushare_instrument_master_runs_immutable
    ON "kunlun_instrument_provider"."tushare_instrument_master_runs";
CREATE TRIGGER tushare_instrument_master_runs_immutable
BEFORE UPDATE OR DELETE
ON "kunlun_instrument_provider"."tushare_instrument_master_runs"
FOR EACH ROW EXECUTE FUNCTION
    "kunlun_instrument_provider"."tushare_instrument_master_history_immutable"();
DROP TRIGGER IF EXISTS tushare_instrument_master_raw_refs_immutable
    ON "kunlun_instrument_provider"."tushare_instrument_master_raw_refs";
CREATE TRIGGER tushare_instrument_master_raw_refs_immutable
BEFORE UPDATE OR DELETE
ON "kunlun_instrument_provider"."tushare_instrument_master_raw_refs"
FOR EACH ROW EXECUTE FUNCTION
    "kunlun_instrument_provider"."tushare_instrument_master_history_immutable"();
DROP TRIGGER IF EXISTS tushare_instrument_master_snapshots_immutable
    ON "kunlun_instrument_provider"."tushare_instrument_master_snapshots";
CREATE TRIGGER tushare_instrument_master_snapshots_immutable
BEFORE UPDATE OR DELETE
ON "kunlun_instrument_provider"."tushare_instrument_master_snapshots"
FOR EACH ROW EXECUTE FUNCTION
    "kunlun_instrument_provider"."tushare_instrument_master_history_immutable"();
DROP TRIGGER IF EXISTS tushare_instrument_master_revisions_immutable
    ON "kunlun_instrument_provider"."tushare_instrument_master_revisions";
CREATE TRIGGER tushare_instrument_master_revisions_immutable
BEFORE UPDATE OR DELETE
ON "kunlun_instrument_provider"."tushare_instrument_master_revisions"
FOR EACH ROW EXECUTE FUNCTION
    "kunlun_instrument_provider"."tushare_instrument_master_history_immutable"();
DROP TRIGGER IF EXISTS tushare_instrument_master_snapshot_revisions_immutable
    ON "kunlun_instrument_provider"."tushare_instrument_master_snapshot_revisions";
CREATE TRIGGER tushare_instrument_master_snapshot_revisions_immutable
BEFORE UPDATE OR DELETE
ON "kunlun_instrument_provider"."tushare_instrument_master_snapshot_revisions"
FOR EACH ROW EXECUTE FUNCTION
    "kunlun_instrument_provider"."tushare_instrument_master_history_immutable"();
DROP TRIGGER IF EXISTS tushare_instrument_master_removal_candidates_immutable
    ON "kunlun_instrument_provider"."tushare_instrument_master_removal_candidates";
CREATE TRIGGER tushare_instrument_master_removal_candidates_immutable
BEFORE UPDATE OR DELETE
ON "kunlun_instrument_provider"."tushare_instrument_master_removal_candidates"
FOR EACH ROW EXECUTE FUNCTION
    "kunlun_instrument_provider"."tushare_instrument_master_history_immutable"();
DROP TRIGGER IF EXISTS tushare_instrument_master_audit_immutable
    ON "kunlun_instrument_provider"."tushare_instrument_master_audit";
CREATE TRIGGER tushare_instrument_master_audit_immutable
BEFORE UPDATE OR DELETE
ON "kunlun_instrument_provider"."tushare_instrument_master_audit"
FOR EACH ROW EXECUTE FUNCTION
    "kunlun_instrument_provider"."tushare_instrument_master_history_immutable"();
DROP TRIGGER IF EXISTS tushare_instrument_master_audit_actor_immutable
    ON "kunlun_instrument_provider"."tushare_instrument_master_audit";
CREATE TRIGGER tushare_instrument_master_audit_actor_immutable
BEFORE INSERT
ON "kunlun_instrument_provider"."tushare_instrument_master_audit"
FOR EACH ROW EXECUTE FUNCTION
    "kunlun_instrument_provider"."tushare_instrument_master_audit_actor_immutable"();

REVOKE ALL ON SCHEMA "kunlun_instrument_provider" FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA "kunlun_instrument_provider" FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA "kunlun_instrument_provider" FROM PUBLIC;

GRANT USAGE ON SCHEMA "kunlun_instrument_provider"
    TO kunlun_im_runtime, kunlun_im_reader;

GRANT SELECT, INSERT ON
    "kunlun_instrument_provider"."tushare_instrument_master_runs",
    "kunlun_instrument_provider"."tushare_instrument_master_raw_refs",
    "kunlun_instrument_provider"."tushare_instrument_master_snapshots",
    "kunlun_instrument_provider"."tushare_instrument_master_revisions",
    "kunlun_instrument_provider"."tushare_instrument_master_snapshot_revisions",
    "kunlun_instrument_provider"."tushare_instrument_master_removal_candidates",
    "kunlun_instrument_provider"."tushare_instrument_master_audit"
    TO kunlun_im_runtime;
GRANT SELECT ON
    "kunlun_instrument_provider"."tushare_instrument_master_heads"
    TO kunlun_im_runtime;

GRANT SELECT ON
    "kunlun_instrument_provider"."tushare_instrument_master_snapshots",
    "kunlun_instrument_provider"."tushare_instrument_master_revisions",
    "kunlun_instrument_provider"."tushare_instrument_master_snapshot_revisions",
    "kunlun_instrument_provider"."tushare_instrument_master_heads",
    "kunlun_instrument_provider"."tushare_instrument_master_removal_candidates"
    TO kunlun_im_reader;

GRANT EXECUTE ON FUNCTION
    "kunlun_instrument_provider"."tushare_instrument_master_publish_head"(TEXT, UUID, TIMESTAMPTZ)
    TO kunlun_im_runtime;

REVOKE ALL ON FUNCTION
    "kunlun_instrument_provider"."tushare_instrument_master_history_immutable"()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION
    "kunlun_instrument_provider"."tushare_instrument_master_current_actor"()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION
    "kunlun_instrument_provider"."tushare_instrument_master_audit_actor_immutable"()
    FROM PUBLIC;
