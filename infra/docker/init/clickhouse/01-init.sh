#!/bin/sh

# Fresh-volume wrapper: execute the same canonical migrations used by the
# explicit existing-volume migrator.  This script is intentionally mounted
# under docker-entrypoint-initdb.d; canonical SQL lives at a separate, read-only
# mount so it cannot be mistaken for an obsolete ad-hoc init schema.
set -eu

database="${CLICKHOUSE_DB:-kunlun}"
user="${CLICKHOUSE_USER:-default}"
password="${CLICKHOUSE_PASSWORD:-}"
migration_dir="${KUNLUN_CLICKHOUSE_MIGRATIONS_DIR:-/opt/kunlun/clickhouse/migrations}"

case "${database}" in
  ""|[0-9]*|*[!A-Za-z0-9_]*)
    echo "invalid ClickHouse database identifier: ${database}" >&2
    exit 1
    ;;
esac

set -- --user "${user}"
if [ -n "${password}" ]; then
  set -- "$@" --password "${password}"
fi

# The official image creates CLICKHOUSE_DB before invoking init scripts.  The
# IF NOT EXISTS guard also keeps the wrapper safe if that ordering changes.
clickhouse-client "$@" --query "CREATE DATABASE IF NOT EXISTS \`${database}\`"

for migration in 001_bars.sql 002_corporate_actions.sql; do
  path="${migration_dir}/${migration}"
  if [ ! -f "${path}" ]; then
    echo "missing canonical ClickHouse migration: ${path}" >&2
    exit 1
  fi
  clickhouse-client "$@" --database "${database}" --multiquery < "${path}"
done

echo "ClickHouse fresh initialization complete (${database})"
