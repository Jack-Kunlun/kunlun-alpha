-- Additive, immutable V4 storage for trusted SZSE direct-daily calendar runs.
-- This schema is deliberately independent from the sparse V3 calendar tables.

CREATE TABLE official_calendar_scan_runs (
    run_id UUID PRIMARY KEY,
    authority TEXT NOT NULL,
    exchange TEXT NOT NULL,
    calendar_year INTEGER NOT NULL,
    parser_version TEXT NOT NULL,
    source_version TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    compiled_catalog_sha256 BYTEA NOT NULL,
    manifest_member_sha256 BYTEA NOT NULL,
    manifest_raw_sha256 BYTEA NOT NULL,
    proof_sha256 BYTEA NOT NULL,
    manifest_raw_evidence_id UUID NOT NULL,
    manifest_artifact_id UUID NOT NULL,
    manifest_capture_id UUID NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    cutoff_at TIMESTAMPTZ NOT NULL,
    source_nowdate DATE NOT NULL,
    coverage_level TEXT NOT NULL,
    confirmed_through DATE,
    run_disposition TEXT NOT NULL,
    persisted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT official_calendar_scan_runs_authority_ck CHECK (authority = 'SZSE'),
    CONSTRAINT official_calendar_scan_runs_exchange_ck CHECK (exchange = 'SZ'),
    CONSTRAINT official_calendar_scan_runs_year_ck CHECK (calendar_year BETWEEN 1 AND 9999),
    CONSTRAINT official_calendar_scan_runs_parser_version_ck CHECK (parser_version = 'szse-direct-daily-v4'),
    CONSTRAINT official_calendar_scan_runs_source_version_ck CHECK (source_version = 'szse-direct-daily-v4'),
    CONSTRAINT official_calendar_scan_runs_contract_version_ck CHECK (contract_version = 'calendar-scan-run-v4'),
    CONSTRAINT official_calendar_scan_runs_policy_ck CHECK (policy_id = 'szse-direct-daily-v1'),
    CONSTRAINT official_calendar_scan_runs_catalog_digest_ck CHECK (octet_length(compiled_catalog_sha256) = 32),
    CONSTRAINT official_calendar_scan_runs_manifest_member_digest_ck CHECK (octet_length(manifest_member_sha256) = 32),
    CONSTRAINT official_calendar_scan_runs_manifest_raw_digest_ck CHECK (octet_length(manifest_raw_sha256) = 32),
    CONSTRAINT official_calendar_scan_runs_proof_digest_ck CHECK (octet_length(proof_sha256) = 32),
    CONSTRAINT official_calendar_scan_runs_window_ck CHECK (opened_at <= cutoff_at),
    CONSTRAINT official_calendar_scan_runs_coverage_ck CHECK (
        (coverage_level = 'INDETERMINATE' AND confirmed_through IS NULL)
        OR (coverage_level IN ('CONFIRMED_HORIZON', 'FINAL_YEAR')
            AND confirmed_through BETWEEN make_date(calendar_year, 1, 1) AND make_date(calendar_year, 12, 31))
    ),
    CONSTRAINT official_calendar_scan_runs_final_ck CHECK (
        coverage_level <> 'FINAL_YEAR' OR confirmed_through = make_date(calendar_year, 12, 31)
    ),
    CONSTRAINT official_calendar_scan_runs_disposition_ck CHECK (
        run_disposition IN ('CONFIRMED', 'OUT_OF_ORDER', 'DUPLICATE', 'CONFLICT')
    )
);

CREATE TABLE official_calendar_evidence_refs (
    evidence_ref_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    role TEXT NOT NULL,
    source TEXT NOT NULL,
    raw_capture_id TEXT NOT NULL,
    raw_date DATE NOT NULL,
    raw_size INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    object_sha256 BYTEA NOT NULL,
    route_sha256 BYTEA NOT NULL,
    request_identity TEXT NOT NULL,
    identity_verified BOOLEAN NOT NULL,
    replay_verified BOOLEAN NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT official_calendar_evidence_refs_run_fkey
        FOREIGN KEY (run_id) REFERENCES official_calendar_scan_runs(run_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_evidence_refs_capture_uk UNIQUE (run_id, raw_capture_id),
    CONSTRAINT official_calendar_evidence_refs_scope_uk UNIQUE (run_id, evidence_ref_id),
    CONSTRAINT official_calendar_evidence_refs_identity_uk UNIQUE (run_id, source, raw_capture_id),
    CONSTRAINT official_calendar_evidence_refs_role_ck CHECK (role IN ('IDENTITY_ROOT', 'IDENTITY_PATH', 'IDENTITY_CONCAT', 'IDENTITY_JS', 'CATALOG', 'RESPONSE', 'STATE', 'MANIFEST')),
    CONSTRAINT official_calendar_evidence_refs_size_ck CHECK (raw_size >= 0),
    CONSTRAINT official_calendar_evidence_refs_digest_ck CHECK (octet_length(object_sha256) = 32 AND octet_length(route_sha256) = 32),
    CONSTRAINT official_calendar_evidence_refs_verification_ck CHECK (identity_verified AND replay_verified),
    CONSTRAINT official_calendar_evidence_refs_window_ck CHECK (observed_at <= available_at)
);

CREATE TABLE official_calendar_capture_attempts (
    run_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    attempt_id TEXT NOT NULL,
    capture_id TEXT NOT NULL,
    endpoint_kind TEXT NOT NULL,
    pass_number INTEGER,
    month INTEGER,
    status_code INTEGER NOT NULL,
    error_code TEXT,
    replay_allowed BOOLEAN NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    raw_evidence_ref_id UUID NOT NULL,
    state_evidence_ref_id UUID NOT NULL,
    PRIMARY KEY (run_id, ordinal),
    CONSTRAINT official_calendar_capture_attempts_run_fkey
        FOREIGN KEY (run_id) REFERENCES official_calendar_scan_runs(run_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_capture_attempts_raw_fkey
        FOREIGN KEY (run_id, raw_evidence_ref_id)
        REFERENCES official_calendar_evidence_refs(run_id, evidence_ref_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_capture_attempts_raw_capture_fkey
        FOREIGN KEY (run_id, capture_id)
        REFERENCES official_calendar_evidence_refs(run_id, raw_capture_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_capture_attempts_state_fkey
        FOREIGN KEY (run_id, state_evidence_ref_id)
        REFERENCES official_calendar_evidence_refs(run_id, evidence_ref_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_capture_attempts_ordinal_ck CHECK (ordinal BETWEEN 1 AND 28),
    CONSTRAINT official_calendar_capture_attempts_status_ck CHECK (status_code = 200 AND error_code IS NULL AND replay_allowed),
    CONSTRAINT official_calendar_capture_attempts_window_ck CHECK (observed_at <= available_at),
    CONSTRAINT official_calendar_capture_attempts_pass_month_ck CHECK (
        (ordinal <= 4 AND pass_number IS NULL AND month IS NULL)
        OR (ordinal > 4 AND pass_number IN (1, 2) AND month BETWEEN 1 AND 12)
    ),
    CONSTRAINT official_calendar_capture_attempts_edge_ck CHECK (
        (ordinal = 1 AND endpoint_kind = 'root' AND pass_number IS NULL AND month IS NULL)
        OR (ordinal = 2 AND endpoint_kind = 'path' AND pass_number IS NULL AND month IS NULL)
        OR (ordinal = 3 AND endpoint_kind = 'concat' AND pass_number IS NULL AND month IS NULL)
        OR (ordinal = 4 AND endpoint_kind = 'js' AND pass_number IS NULL AND month IS NULL)
        OR (ordinal > 4 AND endpoint_kind = 'page'
            AND pass_number = ((ordinal - 5) / 12) + 1
            AND month = ((ordinal - 5) % 12) + 1)
    ),
    CONSTRAINT official_calendar_capture_attempts_identity_uk UNIQUE (run_id, capture_id)
);

ALTER TABLE official_calendar_scan_runs
    ADD CONSTRAINT official_calendar_scan_runs_manifest_fkey
    FOREIGN KEY (run_id, manifest_raw_evidence_id)
    REFERENCES official_calendar_evidence_refs(run_id, evidence_ref_id)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE official_calendar_run_catalogs (
    run_id UUID NOT NULL,
    month INTEGER NOT NULL,
    catalog_id UUID NOT NULL,
    resource_id TEXT NOT NULL,
    raw_evidence_ref_id UUID NOT NULL,
    raw_artifact_sha256 BYTEA NOT NULL,
    PRIMARY KEY (run_id, month),
    CONSTRAINT official_calendar_run_catalogs_run_fkey
        FOREIGN KEY (run_id) REFERENCES official_calendar_scan_runs(run_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_run_catalogs_raw_fkey
        FOREIGN KEY (run_id, raw_evidence_ref_id)
        REFERENCES official_calendar_evidence_refs(run_id, evidence_ref_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_run_catalogs_month_ck CHECK (month BETWEEN 1 AND 12),
    CONSTRAINT official_calendar_run_catalogs_resource_ck CHECK (resource_id <> ''),
    CONSTRAINT official_calendar_run_catalogs_digest_ck CHECK (octet_length(raw_artifact_sha256) = 32),
    CONSTRAINT official_calendar_run_catalogs_catalog_uk UNIQUE (run_id, catalog_id),
    CONSTRAINT official_calendar_run_catalogs_scope_id_uk UNIQUE (run_id, month, catalog_id)
);

CREATE TABLE official_calendar_run_passes (
    run_id UUID NOT NULL,
    pass_number INTEGER NOT NULL,
    pass_id UUID NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    member_sha256 BYTEA NOT NULL,
    PRIMARY KEY (run_id, pass_number),
    CONSTRAINT official_calendar_run_passes_run_fkey
        FOREIGN KEY (run_id) REFERENCES official_calendar_scan_runs(run_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_run_passes_number_ck CHECK (pass_number IN (1, 2)),
    CONSTRAINT official_calendar_run_passes_window_ck CHECK (opened_at < finished_at),
    CONSTRAINT official_calendar_run_passes_digest_ck CHECK (octet_length(member_sha256) = 32),
    CONSTRAINT official_calendar_run_passes_id_uk UNIQUE (run_id, pass_id),
    CONSTRAINT official_calendar_run_passes_scope_id_uk UNIQUE (run_id, pass_number, pass_id)
);

CREATE TABLE official_calendar_run_pages (
    run_id UUID NOT NULL,
    pass_number INTEGER NOT NULL,
    month INTEGER NOT NULL,
    page_id UUID NOT NULL,
    pass_id UUID NOT NULL,
    catalog_id UUID NOT NULL,
    resource_id TEXT NOT NULL,
    raw_evidence_ref_id UUID NOT NULL,
    raw_artifact_sha256 BYTEA NOT NULL,
    canonical_payload_sha256 BYTEA NOT NULL,
    artifact_id UUID NOT NULL,
    capture_id UUID NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    source_nowdate DATE NOT NULL,
    PRIMARY KEY (run_id, pass_number, month),
    CONSTRAINT official_calendar_run_pages_run_fkey
        FOREIGN KEY (run_id) REFERENCES official_calendar_scan_runs(run_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_run_pages_pass_fkey
        FOREIGN KEY (run_id, pass_number) REFERENCES official_calendar_run_passes(run_id, pass_number)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_run_pages_pass_id_fkey
        FOREIGN KEY (run_id, pass_id) REFERENCES official_calendar_run_passes(run_id, pass_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_run_pages_pass_scope_fkey
        FOREIGN KEY (run_id, pass_number, pass_id)
        REFERENCES official_calendar_run_passes(run_id, pass_number, pass_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_run_pages_catalog_fkey
        FOREIGN KEY (run_id, month) REFERENCES official_calendar_run_catalogs(run_id, month)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_run_pages_catalog_id_fkey
        FOREIGN KEY (run_id, catalog_id) REFERENCES official_calendar_run_catalogs(run_id, catalog_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_run_pages_catalog_scope_fkey
        FOREIGN KEY (run_id, month, catalog_id)
        REFERENCES official_calendar_run_catalogs(run_id, month, catalog_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_run_pages_raw_fkey
        FOREIGN KEY (run_id, raw_evidence_ref_id)
        REFERENCES official_calendar_evidence_refs(run_id, evidence_ref_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_run_pages_pass_number_ck CHECK (pass_number IN (1, 2)),
    CONSTRAINT official_calendar_run_pages_month_ck CHECK (month BETWEEN 1 AND 12),
    CONSTRAINT official_calendar_run_pages_resource_ck CHECK (resource_id <> ''),
    CONSTRAINT official_calendar_run_pages_digest_ck CHECK (octet_length(raw_artifact_sha256) = 32 AND octet_length(canonical_payload_sha256) = 32),
    CONSTRAINT official_calendar_run_pages_window_ck CHECK (opened_at <= observed_at AND observed_at <= available_at),
    CONSTRAINT official_calendar_run_pages_page_uk UNIQUE (run_id, page_id),
    CONSTRAINT official_calendar_run_pages_capture_uk UNIQUE (run_id, capture_id)
);

CREATE TABLE official_calendar_snapshots (
    snapshot_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    authority TEXT NOT NULL,
    exchange TEXT NOT NULL,
    calendar_year INTEGER NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    terminal TEXT NOT NULL,
    coverage_level TEXT NOT NULL,
    confirmed_through DATE,
    supersedes_snapshot_id UUID,
    disposition TEXT NOT NULL,
    persisted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT official_calendar_snapshots_run_fkey
        FOREIGN KEY (run_id) REFERENCES official_calendar_scan_runs(run_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_snapshots_run_uk UNIQUE (run_id),
    CONSTRAINT official_calendar_snapshots_snapshot_run_uk UNIQUE (snapshot_id, run_id),
    CONSTRAINT official_calendar_snapshots_scope_uk UNIQUE (snapshot_id, authority, exchange, calendar_year),
    CONSTRAINT official_calendar_snapshots_parent_fkey
        FOREIGN KEY (supersedes_snapshot_id) REFERENCES official_calendar_snapshots(snapshot_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_snapshots_authority_ck CHECK (authority = 'SZSE'),
    CONSTRAINT official_calendar_snapshots_exchange_ck CHECK (exchange = 'SZ'),
    CONSTRAINT official_calendar_snapshots_year_ck CHECK (calendar_year BETWEEN 1 AND 9999),
    CONSTRAINT official_calendar_snapshots_window_ck CHECK (captured_at <= available_at),
    CONSTRAINT official_calendar_snapshots_terminal_ck CHECK (terminal IN ('COMPLETE', 'INDETERMINATE')),
    CONSTRAINT official_calendar_snapshots_coverage_ck CHECK (
        (coverage_level = 'INDETERMINATE' AND confirmed_through IS NULL)
        OR (coverage_level IN ('CONFIRMED_HORIZON', 'FINAL_YEAR')
            AND confirmed_through BETWEEN make_date(calendar_year, 1, 1) AND make_date(calendar_year, 12, 31))
    ),
    CONSTRAINT official_calendar_snapshots_terminal_coverage_ck CHECK (
        (coverage_level = 'FINAL_YEAR' AND terminal = 'COMPLETE')
        OR (coverage_level <> 'FINAL_YEAR' AND terminal = 'INDETERMINATE')
    ),
    CONSTRAINT official_calendar_snapshots_disposition_ck CHECK (disposition = 'SNAPSHOT_CREATED')
);

CREATE TABLE official_calendar_snapshot_evidence (
    snapshot_id UUID NOT NULL,
    run_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    evidence_ref_id UUID NOT NULL,
    role TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, ordinal),
    CONSTRAINT official_calendar_snapshot_evidence_snapshot_run_fkey
        FOREIGN KEY (snapshot_id, run_id) REFERENCES official_calendar_snapshots(snapshot_id, run_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_snapshot_evidence_run_ref_fkey
        FOREIGN KEY (run_id, evidence_ref_id)
        REFERENCES official_calendar_evidence_refs(run_id, evidence_ref_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_snapshot_evidence_ordinal_ck CHECK (ordinal BETWEEN 0 AND 68),
    CONSTRAINT official_calendar_snapshot_evidence_ref_uk UNIQUE (snapshot_id, evidence_ref_id),
    CONSTRAINT official_calendar_snapshot_evidence_role_ck CHECK (role IN ('IDENTITY_ROOT', 'IDENTITY_PATH', 'IDENTITY_CONCAT', 'IDENTITY_JS', 'CATALOG', 'RESPONSE', 'STATE', 'MANIFEST'))
);

CREATE TABLE official_calendar_snapshot_days (
    snapshot_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    calendar_date DATE NOT NULL,
    is_trading_day BOOLEAN NOT NULL,
    reason TEXT,
    PRIMARY KEY (snapshot_id, ordinal),
    CONSTRAINT official_calendar_snapshot_days_snapshot_fkey
        FOREIGN KEY (snapshot_id) REFERENCES official_calendar_snapshots(snapshot_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT official_calendar_snapshot_days_ordinal_ck CHECK (ordinal >= 0),
    CONSTRAINT official_calendar_snapshot_days_reason_ck CHECK (
        (is_trading_day AND reason IS NULL) OR (NOT is_trading_day AND reason = 'SPECIAL')
    ),
    CONSTRAINT official_calendar_snapshot_days_date_uk UNIQUE (snapshot_id, calendar_date)
);

CREATE INDEX official_calendar_snapshots_resolution_idx
    ON official_calendar_snapshots (authority, exchange, calendar_year, available_at, snapshot_id);
CREATE INDEX official_calendar_evidence_refs_timeline_idx
    ON official_calendar_evidence_refs (run_id, observed_at, available_at, evidence_ref_id);

CREATE OR REPLACE FUNCTION official_calendar_history_immutable()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'official calendar history is immutable';
END;
$$;

CREATE OR REPLACE FUNCTION official_calendar_no_truncate()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'official calendar history is immutable';
END;
$$;

CREATE OR REPLACE FUNCTION official_calendar_validate_run()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    snapshot_count INTEGER;
BEGIN
    PERFORM pg_catalog.set_config(
        'search_path',
        pg_catalog.format('pg_catalog,%I,pg_temp', TG_TABLE_SCHEMA),
        TRUE
    );
    IF (SELECT count(*) FROM official_calendar_evidence_refs WHERE run_id = NEW.run_id) <> 69
       OR (SELECT count(*) FROM official_calendar_capture_attempts WHERE run_id = NEW.run_id) <> 28
       OR (SELECT count(*) FROM official_calendar_run_catalogs WHERE run_id = NEW.run_id) <> 12
       OR (SELECT count(*) FROM official_calendar_run_passes WHERE run_id = NEW.run_id) <> 2
       OR (SELECT count(*) FROM official_calendar_run_pages WHERE run_id = NEW.run_id) <> 24
       OR (SELECT count(*) FROM official_calendar_evidence_refs
           WHERE run_id = NEW.run_id AND role = 'IDENTITY_ROOT') <> 1
       OR (SELECT count(*) FROM official_calendar_evidence_refs
           WHERE run_id = NEW.run_id AND role = 'IDENTITY_PATH') <> 1
       OR (SELECT count(*) FROM official_calendar_evidence_refs
           WHERE run_id = NEW.run_id AND role = 'IDENTITY_CONCAT') <> 1
       OR (SELECT count(*) FROM official_calendar_evidence_refs
           WHERE run_id = NEW.run_id AND role = 'IDENTITY_JS') <> 1
       OR (SELECT count(*) FROM official_calendar_evidence_refs
           WHERE run_id = NEW.run_id AND role = 'CATALOG') <> 12
       OR (SELECT count(*) FROM official_calendar_evidence_refs
           WHERE run_id = NEW.run_id AND role = 'RESPONSE') <> 24
       OR (SELECT count(*) FROM official_calendar_evidence_refs
           WHERE run_id = NEW.run_id AND role = 'STATE') <> 28
       OR (SELECT count(*) FROM official_calendar_evidence_refs
           WHERE run_id = NEW.run_id AND role = 'MANIFEST') <> 1
    THEN
        RAISE EXCEPTION 'official calendar run is incomplete';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM official_calendar_evidence_refs e
         WHERE e.run_id = NEW.run_id
           AND ((e.role IN ('IDENTITY_ROOT', 'IDENTITY_PATH', 'IDENTITY_CONCAT',
                            'IDENTITY_JS', 'RESPONSE')
                 AND e.source <> 'szse-calendar')
                OR (e.role = 'CATALOG' AND e.source <> 'szse-calendar-catalog')
                OR (e.role = 'STATE' AND e.source <> 'szse-calendar-state')
                OR (e.role = 'MANIFEST' AND e.source <> 'szse-calendar-manifest'))
    ) THEN
        RAISE EXCEPTION 'official calendar run is incomplete';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM official_calendar_capture_attempts a
          JOIN official_calendar_evidence_refs raw
            ON raw.run_id = a.run_id AND raw.evidence_ref_id = a.raw_evidence_ref_id
          JOIN official_calendar_evidence_refs state
            ON state.run_id = a.run_id AND state.evidence_ref_id = a.state_evidence_ref_id
         WHERE a.run_id = NEW.run_id
           AND ((a.ordinal = 1 AND raw.role <> 'IDENTITY_ROOT')
                OR (a.ordinal = 2 AND raw.role <> 'IDENTITY_PATH')
                OR (a.ordinal = 3 AND raw.role <> 'IDENTITY_CONCAT')
                OR (a.ordinal = 4 AND raw.role <> 'IDENTITY_JS')
                OR (a.ordinal > 4 AND raw.role <> 'RESPONSE')
                OR (a.ordinal = 1 AND a.endpoint_kind <> 'root')
                OR (a.ordinal = 2 AND a.endpoint_kind <> 'path')
                OR (a.ordinal = 3 AND a.endpoint_kind <> 'concat')
                OR (a.ordinal = 4 AND a.endpoint_kind <> 'js')
                OR (a.ordinal > 4 AND a.endpoint_kind <> 'page')
                OR (a.ordinal <= 4 AND (a.pass_number IS NOT NULL OR a.month IS NOT NULL))
                OR (a.ordinal > 4 AND (a.pass_number <> ((a.ordinal - 5) / 12) + 1
                                       OR a.month <> ((a.ordinal - 5) % 12) + 1))
                OR state.role <> 'STATE'
                OR raw.source <> 'szse-calendar'
                OR state.source <> 'szse-calendar-state'
                OR raw.raw_capture_id <> a.capture_id
                OR state.request_identity !~ '^PUT path_sha256=[0-9a-f]{64}$')
    ) THEN
        RAISE EXCEPTION 'official calendar run is incomplete';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM official_calendar_run_catalogs c
          JOIN official_calendar_evidence_refs e
            ON e.run_id = c.run_id AND e.evidence_ref_id = c.raw_evidence_ref_id
         WHERE c.run_id = NEW.run_id
           AND (e.role <> 'CATALOG' OR e.source <> 'szse-calendar-catalog'
                OR e.object_sha256 <> c.raw_artifact_sha256)
    ) THEN
        RAISE EXCEPTION 'official calendar run is incomplete';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM official_calendar_run_pages p
          LEFT JOIN official_calendar_evidence_refs e
            ON e.run_id = p.run_id AND e.evidence_ref_id = p.raw_evidence_ref_id
          LEFT JOIN official_calendar_run_passes pass
            ON pass.run_id = p.run_id AND pass.pass_number = p.pass_number
          LEFT JOIN official_calendar_run_catalogs catalog
            ON catalog.run_id = p.run_id AND catalog.month = p.month
         WHERE p.run_id = NEW.run_id
           AND (e.evidence_ref_id IS NULL OR e.role <> 'RESPONSE' OR e.source <> 'szse-calendar'
                OR e.object_sha256 <> p.raw_artifact_sha256
                OR e.observed_at <> p.observed_at OR e.available_at <> p.available_at
                OR pass.pass_id IS NULL OR p.pass_id IS DISTINCT FROM pass.pass_id
                OR catalog.catalog_id IS NULL OR p.catalog_id IS DISTINCT FROM catalog.catalog_id
                OR catalog.resource_id IS NULL OR p.resource_id IS DISTINCT FROM catalog.resource_id)
    ) THEN
        RAISE EXCEPTION 'official calendar run is incomplete';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM (
              SELECT a.observed_at, a.available_at,
                     lag(a.available_at) OVER (ORDER BY a.ordinal) AS previous_available
                FROM official_calendar_capture_attempts a
               WHERE a.run_id = NEW.run_id
          ) ordered
         WHERE ordered.previous_available IS NOT NULL
           AND (ordered.observed_at < ordered.previous_available
                OR ordered.available_at < ordered.previous_available)
    ) THEN
        RAISE EXCEPTION 'official calendar run evidence is not ordered';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM official_calendar_evidence_refs e
         WHERE e.run_id = NEW.run_id
           AND e.evidence_ref_id = NEW.manifest_raw_evidence_id
           AND e.role = 'MANIFEST'
           AND e.source = 'szse-calendar-manifest'
           AND e.object_sha256 = NEW.manifest_raw_sha256
           AND e.observed_at = NEW.cutoff_at
           AND e.available_at = NEW.cutoff_at
    ) THEN
        RAISE EXCEPTION 'official calendar run is incomplete';
    END IF;
    SELECT count(*)::INTEGER
      INTO snapshot_count
      FROM official_calendar_snapshots
     WHERE run_id = NEW.run_id;
    IF (NEW.run_disposition = 'CONFIRMED' AND snapshot_count <> 1)
       OR (NEW.run_disposition <> 'CONFIRMED' AND snapshot_count <> 0)
    THEN
        RAISE EXCEPTION 'official calendar run snapshot disposition is invalid';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION official_calendar_validate_append()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    target_run_id UUID;
    target_snapshot_id UUID;
    expected_days INTEGER;
    actual_days INTEGER;
BEGIN
    PERFORM pg_catalog.set_config(
        'search_path',
        pg_catalog.format('pg_catalog,%I,pg_temp', TG_TABLE_SCHEMA),
        TRUE
    );
    IF TG_TABLE_NAME = 'official_calendar_snapshot_days' THEN
        target_snapshot_id := (to_jsonb(NEW)->>'snapshot_id')::UUID;
        SELECT run_id
          INTO target_run_id
          FROM official_calendar_snapshots
         WHERE snapshot_id = target_snapshot_id;
    ELSE
        target_run_id := (to_jsonb(NEW)->>'run_id')::UUID;
    END IF;
    IF target_run_id IS NULL THEN
        RAISE EXCEPTION 'official calendar run graph is invalid';
    END IF;
    IF TG_TABLE_NAME = 'official_calendar_snapshots'
       AND (SELECT run_disposition FROM official_calendar_scan_runs WHERE run_id = target_run_id)
           <> 'CONFIRMED'
    THEN
        RAISE EXCEPTION 'official calendar run snapshot disposition is invalid';
    END IF;
    IF (SELECT count(*) FROM official_calendar_evidence_refs WHERE run_id = target_run_id) > 69
       OR (SELECT count(*) FROM official_calendar_capture_attempts WHERE run_id = target_run_id) > 28
       OR (SELECT count(*) FROM official_calendar_run_catalogs WHERE run_id = target_run_id) > 12
       OR (SELECT count(*) FROM official_calendar_run_passes WHERE run_id = target_run_id) > 2
       OR (SELECT count(*) FROM official_calendar_run_pages WHERE run_id = target_run_id) > 24
       OR (SELECT count(*) FROM official_calendar_snapshots WHERE run_id = target_run_id) > 1
       OR (SELECT count(*) FROM official_calendar_snapshot_evidence WHERE run_id = target_run_id) > 69
    THEN
        RAISE EXCEPTION 'official calendar run graph is immutable';
    END IF;
    IF TG_TABLE_NAME = 'official_calendar_snapshot_days' THEN
        SELECT make_date(calendar_year, 12, 31) - make_date(calendar_year, 1, 1) + 1
          INTO expected_days
          FROM official_calendar_snapshots
         WHERE snapshot_id = target_snapshot_id;
        SELECT count(*)
          INTO actual_days
          FROM official_calendar_snapshot_days
         WHERE snapshot_id = target_snapshot_id;
        IF actual_days > expected_days THEN
            RAISE EXCEPTION 'official calendar run graph is immutable';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION official_calendar_validate_snapshot()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
    DECLARE
        expected_days INTEGER;
        actual_days INTEGER;
        first_day DATE;
        last_day DATE;
        run_authority TEXT;
        run_exchange TEXT;
        run_year INTEGER;
        run_opened_at TIMESTAMPTZ;
        run_cutoff_at TIMESTAMPTZ;
        run_coverage_level TEXT;
        run_confirmed_through DATE;
        run_disposition TEXT;
BEGIN
    PERFORM pg_catalog.set_config(
        'search_path',
        pg_catalog.format('pg_catalog,%I,pg_temp', TG_TABLE_SCHEMA),
        TRUE
    );
    expected_days := make_date(NEW.calendar_year, 12, 31)
        - make_date(NEW.calendar_year, 1, 1) + 1;
    SELECT r.authority, r.exchange, r.calendar_year, r.opened_at, r.cutoff_at,
           r.coverage_level, r.confirmed_through, r.run_disposition
      INTO run_authority, run_exchange, run_year, run_opened_at, run_cutoff_at,
           run_coverage_level, run_confirmed_through, run_disposition
      FROM official_calendar_scan_runs AS r
     WHERE r.run_id = NEW.run_id;
    IF run_disposition <> 'CONFIRMED'
       OR NEW.disposition <> 'SNAPSHOT_CREATED'
       OR run_authority <> NEW.authority
       OR run_exchange <> NEW.exchange
       OR run_year <> NEW.calendar_year
       OR run_coverage_level IS DISTINCT FROM NEW.coverage_level
       OR run_confirmed_through IS DISTINCT FROM NEW.confirmed_through
       OR NEW.terminal IS DISTINCT FROM (CASE
           WHEN run_coverage_level = 'FINAL_YEAR' THEN 'COMPLETE'
           ELSE 'INDETERMINATE'
       END)
    THEN
        RAISE EXCEPTION 'official calendar run snapshot disposition is invalid';
    END IF;
    IF run_opened_at IS NULL
       OR run_cutoff_at IS NULL
       OR NEW.captured_at <> run_opened_at
       OR NEW.available_at <> run_cutoff_at
    THEN
        RAISE EXCEPTION 'official calendar snapshot window is not bound to run';
    END IF;
    SELECT count(*)::INTEGER, min(calendar_date), max(calendar_date)
      INTO actual_days, first_day, last_day
      FROM official_calendar_snapshot_days
     WHERE snapshot_id = NEW.snapshot_id;
    IF actual_days <> expected_days
       OR first_day <> make_date(NEW.calendar_year, 1, 1)
       OR last_day <> make_date(NEW.calendar_year, 12, 31)
       OR (SELECT count(*) FROM official_calendar_snapshot_evidence
           WHERE snapshot_id = NEW.snapshot_id AND run_id = NEW.run_id) <> 69
       OR (SELECT count(*) FROM official_calendar_evidence_refs WHERE run_id = NEW.run_id) <> 69
       OR (SELECT count(*) FROM official_calendar_capture_attempts WHERE run_id = NEW.run_id) <> 28
       OR (SELECT count(*) FROM official_calendar_run_catalogs WHERE run_id = NEW.run_id) <> 12
       OR (SELECT count(*) FROM official_calendar_run_passes WHERE run_id = NEW.run_id) <> 2
       OR (SELECT count(*) FROM official_calendar_run_pages WHERE run_id = NEW.run_id) <> 24
       OR (SELECT count(*) FROM official_calendar_evidence_refs
           WHERE run_id = NEW.run_id AND role = 'IDENTITY_ROOT') <> 1
       OR (SELECT count(*) FROM official_calendar_evidence_refs
           WHERE run_id = NEW.run_id AND role = 'IDENTITY_PATH') <> 1
       OR (SELECT count(*) FROM official_calendar_evidence_refs
           WHERE run_id = NEW.run_id AND role = 'IDENTITY_CONCAT') <> 1
       OR (SELECT count(*) FROM official_calendar_evidence_refs
           WHERE run_id = NEW.run_id AND role = 'IDENTITY_JS') <> 1
       OR (SELECT count(*) FROM official_calendar_evidence_refs
           WHERE run_id = NEW.run_id AND role = 'CATALOG') <> 12
       OR (SELECT count(*) FROM official_calendar_evidence_refs
           WHERE run_id = NEW.run_id AND role = 'RESPONSE') <> 24
       OR (SELECT count(*) FROM official_calendar_evidence_refs
           WHERE run_id = NEW.run_id AND role = 'STATE') <> 28
       OR (SELECT count(*) FROM official_calendar_evidence_refs
           WHERE run_id = NEW.run_id AND role = 'MANIFEST') <> 1
    THEN
        RAISE EXCEPTION 'official calendar snapshot is incomplete';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM official_calendar_evidence_refs e
         WHERE e.run_id = NEW.run_id
           AND ((e.role IN ('IDENTITY_ROOT', 'IDENTITY_PATH', 'IDENTITY_CONCAT',
                            'IDENTITY_JS', 'RESPONSE')
                 AND e.source <> 'szse-calendar')
                OR (e.role = 'CATALOG' AND e.source <> 'szse-calendar-catalog')
                OR (e.role = 'STATE' AND e.source <> 'szse-calendar-state')
                OR (e.role = 'MANIFEST' AND e.source <> 'szse-calendar-manifest'))
    ) THEN
        RAISE EXCEPTION 'official calendar snapshot is incomplete';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM official_calendar_capture_attempts a
          JOIN official_calendar_evidence_refs raw
            ON raw.run_id = a.run_id AND raw.evidence_ref_id = a.raw_evidence_ref_id
          JOIN official_calendar_evidence_refs state
            ON state.run_id = a.run_id AND state.evidence_ref_id = a.state_evidence_ref_id
         WHERE a.run_id = NEW.run_id
           AND ((a.ordinal = 1 AND raw.role <> 'IDENTITY_ROOT')
                OR (a.ordinal = 2 AND raw.role <> 'IDENTITY_PATH')
                OR (a.ordinal = 3 AND raw.role <> 'IDENTITY_CONCAT')
                OR (a.ordinal = 4 AND raw.role <> 'IDENTITY_JS')
                OR (a.ordinal > 4 AND raw.role <> 'RESPONSE')
                OR (a.ordinal = 1 AND a.endpoint_kind <> 'root')
                OR (a.ordinal = 2 AND a.endpoint_kind <> 'path')
                OR (a.ordinal = 3 AND a.endpoint_kind <> 'concat')
                OR (a.ordinal = 4 AND a.endpoint_kind <> 'js')
                OR (a.ordinal > 4 AND a.endpoint_kind <> 'page')
                OR (a.ordinal <= 4 AND (a.pass_number IS NOT NULL OR a.month IS NOT NULL))
                OR (a.ordinal > 4 AND (a.pass_number <> ((a.ordinal - 5) / 12) + 1
                                       OR a.month <> ((a.ordinal - 5) % 12) + 1))
                OR state.role <> 'STATE'
                OR raw.source <> 'szse-calendar'
                OR state.source <> 'szse-calendar-state'
                OR raw.raw_capture_id <> a.capture_id
                OR state.request_identity !~ '^PUT path_sha256=[0-9a-f]{64}$')
    ) THEN
        RAISE EXCEPTION 'official calendar snapshot is incomplete';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM official_calendar_run_catalogs c
          JOIN official_calendar_evidence_refs e
            ON e.run_id = c.run_id AND e.evidence_ref_id = c.raw_evidence_ref_id
         WHERE c.run_id = NEW.run_id
           AND (e.role <> 'CATALOG' OR e.source <> 'szse-calendar-catalog'
                OR e.object_sha256 <> c.raw_artifact_sha256)
    ) THEN
        RAISE EXCEPTION 'official calendar snapshot is incomplete';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM official_calendar_run_pages p
          LEFT JOIN official_calendar_evidence_refs e
            ON e.run_id = p.run_id AND e.evidence_ref_id = p.raw_evidence_ref_id
          LEFT JOIN official_calendar_run_passes pass
            ON pass.run_id = p.run_id AND pass.pass_number = p.pass_number
          LEFT JOIN official_calendar_run_catalogs catalog
            ON catalog.run_id = p.run_id AND catalog.month = p.month
         WHERE p.run_id = NEW.run_id
           AND (e.evidence_ref_id IS NULL OR e.role <> 'RESPONSE' OR e.source <> 'szse-calendar'
                OR e.object_sha256 <> p.raw_artifact_sha256
                OR e.observed_at <> p.observed_at OR e.available_at <> p.available_at
                OR pass.pass_id IS NULL OR p.pass_id IS DISTINCT FROM pass.pass_id
                OR catalog.catalog_id IS NULL OR p.catalog_id IS DISTINCT FROM catalog.catalog_id
                OR catalog.resource_id IS NULL OR p.resource_id IS DISTINCT FROM catalog.resource_id)
    ) THEN
        RAISE EXCEPTION 'official calendar snapshot is incomplete';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM official_calendar_evidence_refs e
         WHERE e.run_id = NEW.run_id
           AND e.evidence_ref_id = (SELECT r.manifest_raw_evidence_id
                                    FROM official_calendar_scan_runs r
                                    WHERE r.run_id = NEW.run_id)
           AND e.role = 'MANIFEST'
           AND e.source = 'szse-calendar-manifest'
           AND e.object_sha256 = (SELECT r.manifest_raw_sha256
                                  FROM official_calendar_scan_runs r
                                  WHERE r.run_id = NEW.run_id)
           AND e.observed_at = (SELECT r.cutoff_at
                                FROM official_calendar_scan_runs r
                                WHERE r.run_id = NEW.run_id)
           AND e.available_at = (SELECT r.cutoff_at
                                 FROM official_calendar_scan_runs r
                                 WHERE r.run_id = NEW.run_id)
    ) THEN
        RAISE EXCEPTION 'official calendar snapshot is incomplete';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM official_calendar_snapshot_evidence se
         WHERE se.snapshot_id = NEW.snapshot_id
           AND ((se.ordinal = 0 AND se.role <> 'IDENTITY_ROOT')
                OR (se.ordinal = 1 AND se.role <> 'STATE')
                OR (se.ordinal = 2 AND se.role <> 'IDENTITY_PATH')
                OR (se.ordinal = 3 AND se.role <> 'STATE')
                OR (se.ordinal = 4 AND se.role <> 'IDENTITY_CONCAT')
                OR (se.ordinal = 5 AND se.role <> 'STATE')
                OR (se.ordinal = 6 AND se.role <> 'IDENTITY_JS')
                OR (se.ordinal = 7 AND se.role <> 'STATE')
                OR (se.ordinal BETWEEN 8 AND 19 AND se.role <> 'CATALOG')
                OR (se.ordinal BETWEEN 20 AND 67
                    AND (((se.ordinal - 20) % 2 = 0 AND se.role <> 'RESPONSE')
                         OR ((se.ordinal - 20) % 2 = 1 AND se.role <> 'STATE')))
                OR (se.ordinal = 68 AND se.role <> 'MANIFEST'))
    ) THEN
        RAISE EXCEPTION 'official calendar snapshot evidence is not ordered';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM (
              SELECT e.observed_at, e.available_at,
                     lag(e.available_at) OVER (ORDER BY se.ordinal) AS previous_available
                FROM official_calendar_snapshot_evidence se
                JOIN official_calendar_evidence_refs e
                  ON e.run_id = se.run_id AND e.evidence_ref_id = se.evidence_ref_id
               WHERE se.snapshot_id = NEW.snapshot_id
          ) ordered
         WHERE ordered.previous_available IS NOT NULL
           AND (ordered.observed_at < ordered.previous_available
                OR ordered.available_at < ordered.previous_available)
    ) THEN
        RAISE EXCEPTION 'official calendar snapshot evidence is not ordered';
    END IF;
    IF EXISTS (
        SELECT 1 FROM official_calendar_snapshot_days d
        WHERE d.snapshot_id = NEW.snapshot_id
          AND d.calendar_date <> make_date(NEW.calendar_year, 1, 1) + d.ordinal
    ) THEN
        RAISE EXCEPTION 'official calendar snapshot days are not continuous';
    END IF;
    IF EXISTS (
        SELECT 1 FROM official_calendar_evidence_refs e
        WHERE e.run_id = NEW.run_id AND (e.observed_at < (SELECT opened_at FROM official_calendar_scan_runs WHERE run_id = NEW.run_id)
            OR e.available_at > (SELECT cutoff_at FROM official_calendar_scan_runs WHERE run_id = NEW.run_id))
    ) THEN
        RAISE EXCEPTION 'official calendar evidence is outside run window';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM official_calendar_snapshot_evidence se
          JOIN official_calendar_evidence_refs e ON e.evidence_ref_id = se.evidence_ref_id
         WHERE se.snapshot_id = NEW.snapshot_id
           AND (e.run_id <> NEW.run_id OR se.run_id <> NEW.run_id OR se.role <> e.role)
    ) THEN
        RAISE EXCEPTION 'official calendar snapshot evidence has wrong lineage';
    END IF;
    IF (SELECT min(ordinal) FROM official_calendar_snapshot_evidence WHERE snapshot_id = NEW.snapshot_id) <> 0
       OR (SELECT max(ordinal) FROM official_calendar_snapshot_evidence WHERE snapshot_id = NEW.snapshot_id) <> 68
    THEN
        RAISE EXCEPTION 'official calendar snapshot evidence is not ordered';
    END IF;
    IF NEW.supersedes_snapshot_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
          FROM official_calendar_snapshots parent
         WHERE parent.snapshot_id = NEW.supersedes_snapshot_id
           AND parent.authority = NEW.authority
           AND parent.exchange = NEW.exchange
           AND parent.calendar_year = NEW.calendar_year
           AND parent.available_at < NEW.available_at
    ) THEN
        RAISE EXCEPTION 'official calendar snapshot parent is invalid';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER official_calendar_scan_runs_immutable
BEFORE UPDATE OR DELETE ON official_calendar_scan_runs
FOR EACH ROW EXECUTE FUNCTION official_calendar_history_immutable();
CREATE CONSTRAINT TRIGGER official_calendar_scan_runs_complete
AFTER INSERT ON official_calendar_scan_runs
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION official_calendar_validate_run();
CREATE TRIGGER official_calendar_evidence_refs_immutable
BEFORE UPDATE OR DELETE ON official_calendar_evidence_refs
FOR EACH ROW EXECUTE FUNCTION official_calendar_history_immutable();
CREATE TRIGGER official_calendar_capture_attempts_immutable
BEFORE UPDATE OR DELETE ON official_calendar_capture_attempts
FOR EACH ROW EXECUTE FUNCTION official_calendar_history_immutable();
CREATE TRIGGER official_calendar_run_catalogs_immutable
BEFORE UPDATE OR DELETE ON official_calendar_run_catalogs
FOR EACH ROW EXECUTE FUNCTION official_calendar_history_immutable();
CREATE TRIGGER official_calendar_run_passes_immutable
BEFORE UPDATE OR DELETE ON official_calendar_run_passes
FOR EACH ROW EXECUTE FUNCTION official_calendar_history_immutable();
CREATE TRIGGER official_calendar_run_pages_immutable
BEFORE UPDATE OR DELETE ON official_calendar_run_pages
FOR EACH ROW EXECUTE FUNCTION official_calendar_history_immutable();
CREATE TRIGGER official_calendar_snapshots_immutable
BEFORE UPDATE OR DELETE ON official_calendar_snapshots
FOR EACH ROW EXECUTE FUNCTION official_calendar_history_immutable();
CREATE TRIGGER official_calendar_snapshot_evidence_immutable
BEFORE UPDATE OR DELETE ON official_calendar_snapshot_evidence
FOR EACH ROW EXECUTE FUNCTION official_calendar_history_immutable();
CREATE TRIGGER official_calendar_snapshot_days_immutable
BEFORE UPDATE OR DELETE ON official_calendar_snapshot_days
FOR EACH ROW EXECUTE FUNCTION official_calendar_history_immutable();

CREATE TRIGGER official_calendar_scan_runs_no_truncate
BEFORE TRUNCATE ON official_calendar_scan_runs FOR EACH STATEMENT EXECUTE FUNCTION official_calendar_no_truncate();
CREATE TRIGGER official_calendar_evidence_refs_no_truncate
BEFORE TRUNCATE ON official_calendar_evidence_refs FOR EACH STATEMENT EXECUTE FUNCTION official_calendar_no_truncate();
CREATE TRIGGER official_calendar_capture_attempts_no_truncate
BEFORE TRUNCATE ON official_calendar_capture_attempts FOR EACH STATEMENT EXECUTE FUNCTION official_calendar_no_truncate();
CREATE TRIGGER official_calendar_run_catalogs_no_truncate
BEFORE TRUNCATE ON official_calendar_run_catalogs FOR EACH STATEMENT EXECUTE FUNCTION official_calendar_no_truncate();
CREATE TRIGGER official_calendar_run_passes_no_truncate
BEFORE TRUNCATE ON official_calendar_run_passes FOR EACH STATEMENT EXECUTE FUNCTION official_calendar_no_truncate();
CREATE TRIGGER official_calendar_run_pages_no_truncate
BEFORE TRUNCATE ON official_calendar_run_pages FOR EACH STATEMENT EXECUTE FUNCTION official_calendar_no_truncate();
CREATE TRIGGER official_calendar_snapshots_no_truncate
BEFORE TRUNCATE ON official_calendar_snapshots FOR EACH STATEMENT EXECUTE FUNCTION official_calendar_no_truncate();
CREATE TRIGGER official_calendar_snapshot_evidence_no_truncate
BEFORE TRUNCATE ON official_calendar_snapshot_evidence FOR EACH STATEMENT EXECUTE FUNCTION official_calendar_no_truncate();
CREATE TRIGGER official_calendar_snapshot_days_no_truncate
BEFORE TRUNCATE ON official_calendar_snapshot_days FOR EACH STATEMENT EXECUTE FUNCTION official_calendar_no_truncate();

CREATE CONSTRAINT TRIGGER official_calendar_evidence_refs_append_guard
AFTER INSERT ON official_calendar_evidence_refs
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION official_calendar_validate_append();
CREATE CONSTRAINT TRIGGER official_calendar_capture_attempts_append_guard
AFTER INSERT ON official_calendar_capture_attempts
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION official_calendar_validate_append();
CREATE CONSTRAINT TRIGGER official_calendar_run_catalogs_append_guard
AFTER INSERT ON official_calendar_run_catalogs
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION official_calendar_validate_append();
CREATE CONSTRAINT TRIGGER official_calendar_run_passes_append_guard
AFTER INSERT ON official_calendar_run_passes
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION official_calendar_validate_append();
CREATE CONSTRAINT TRIGGER official_calendar_run_pages_append_guard
AFTER INSERT ON official_calendar_run_pages
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION official_calendar_validate_append();
CREATE CONSTRAINT TRIGGER official_calendar_snapshots_append_guard
AFTER INSERT ON official_calendar_snapshots
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION official_calendar_validate_append();
CREATE CONSTRAINT TRIGGER official_calendar_snapshot_evidence_append_guard
AFTER INSERT ON official_calendar_snapshot_evidence
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION official_calendar_validate_append();
CREATE CONSTRAINT TRIGGER official_calendar_snapshot_days_append_guard
AFTER INSERT ON official_calendar_snapshot_days
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION official_calendar_validate_append();

CREATE CONSTRAINT TRIGGER official_calendar_snapshots_complete
AFTER INSERT ON official_calendar_snapshots
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION official_calendar_validate_snapshot();
