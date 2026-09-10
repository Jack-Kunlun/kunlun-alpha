-- Dedicated role bootstrap for the private Tushare instrument-master provider.
--
-- This file is intentionally not mounted into PostgreSQL's automatic init
-- directory.  An administrator must opt into the instrument-master profile.
-- Password values are supplied through psql's environment bridge and are never
-- written into this file or passed as command-line arguments.

\set ON_ERROR_STOP 1
\set QUIET 1
\getenv im_migrator_password INSTRUMENT_MASTER_MIGRATOR_PASSWORD
\getenv im_runtime_password INSTRUMENT_MASTER_RUNTIME_PASSWORD

\if :{?im_migrator_password}
\else
\echo 'INSTRUMENT_MASTER_MIGRATOR_PASSWORD is required'
SELECT 1 / 0;
\endif
\if `test -n "$INSTRUMENT_MASTER_MIGRATOR_PASSWORD" && printf true || printf false`
\else
\echo 'INSTRUMENT_MASTER_MIGRATOR_PASSWORD must be non-empty'
SELECT 1 / 0;
\endif
\if :{?im_runtime_password}
\else
\echo 'INSTRUMENT_MASTER_RUNTIME_PASSWORD is required'
SELECT 1 / 0;
\endif
\if `test -n "$INSTRUMENT_MASTER_RUNTIME_PASSWORD" && printf true || printf false`
\else
\echo 'INSTRUMENT_MASTER_RUNTIME_PASSWORD must be non-empty'
SELECT 1 / 0;
\endif

-- All role, membership, schema and default-privilege changes are atomic.
BEGIN;

DO $bootstrap$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'kunlun_im_owner') THEN
        CREATE ROLE kunlun_im_owner;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'kunlun_im_migrator') THEN
        CREATE ROLE kunlun_im_migrator;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'kunlun_im_runtime') THEN
        CREATE ROLE kunlun_im_runtime;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'kunlun_im_reader') THEN
        CREATE ROLE kunlun_im_reader;
    END IF;
END
$bootstrap$;

ALTER ROLE kunlun_im_owner
    NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD NULL;
ALTER ROLE kunlun_im_migrator
    LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD :'im_migrator_password';
ALTER ROLE kunlun_im_runtime
    LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD :'im_runtime_password';
ALTER ROLE kunlun_im_reader
    NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD NULL;

-- The shared V1-V4 ledger is an existing prerequisite.  These grants are
-- intentionally not CREATE/UPDATE privileges and fail closed if the ledger
-- has not been installed yet.
REVOKE ALL ON SCHEMA kunlun FROM kunlun_im_migrator;
REVOKE ALL ON TABLE kunlun.data_worker_schema_migrations
    FROM kunlun_im_migrator;
GRANT USAGE ON SCHEMA kunlun TO kunlun_im_migrator;
GRANT SELECT ON TABLE kunlun.data_worker_schema_migrations
    TO kunlun_im_migrator;

REVOKE kunlun_im_owner FROM kunlun_im_runtime, kunlun_im_reader;
GRANT kunlun_im_owner TO kunlun_im_migrator
    WITH INHERIT FALSE, SET TRUE, ADMIN FALSE;

CREATE SCHEMA IF NOT EXISTS kunlun_instrument_provider
    AUTHORIZATION kunlun_im_owner;
ALTER SCHEMA kunlun_instrument_provider OWNER TO kunlun_im_owner;
REVOKE ALL ON SCHEMA kunlun_instrument_provider FROM PUBLIC;
REVOKE CREATE ON SCHEMA kunlun_instrument_provider
    FROM kunlun_im_migrator, kunlun_im_runtime, kunlun_im_reader;
GRANT USAGE, CREATE ON SCHEMA kunlun_instrument_provider TO kunlun_im_owner;

ALTER DEFAULT PRIVILEGES FOR ROLE kunlun_im_owner
    IN SCHEMA kunlun_instrument_provider
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE kunlun_im_owner
    IN SCHEMA kunlun_instrument_provider
    REVOKE ALL ON FUNCTIONS FROM PUBLIC;

COMMIT;

\unset im_migrator_password
\unset im_runtime_password
