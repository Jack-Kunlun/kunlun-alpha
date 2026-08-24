# 情绪与轮动持久化回放

## Storage

infra/clickhouse/migrations/003_emotion_rotation_replay.sql creates
emotion_snapshots_v1 and sector_rotation_events_v1. Both are versioned
ReplacingMergeTree tables without TTL. Algorithm versions coexist; evidence,
availability, processing time, replacement revision and payload digest remain
stored.

Apply and verify all canonical migrations:

~~~text
node scripts/ci/clickhouse-migration-smoke.mjs --migrate kunlun
~~~

## API

The API reads ClickHouse through a repository port. Required local variables:

~~~text
EMOTION_CLICKHOUSE_URL=http://localhost:8123
EMOTION_CLICKHOUSE_DATABASE=kunlun
EMOTION_CLICKHOUSE_USER=kunlun
EMOTION_CLICKHOUSE_PASSWORD=kunlun-local-dev
~~~

Endpoints:

~~~text
GET /api/v1/emotion/snapshots?date=2026-08-13&algorithmVersion=emotion_score_v1
GET /api/v1/emotion/rotation-events?date=2026-08-13&algorithmVersion=rotation_event_v2&sectorId=sector-gold
GET /api/v1/emotion/versions
~~~

Dates, versions and sector ids are validated before repository access. Provider
rows are parsed as untrusted values. Backend response bodies and credentials
are never returned in controlled errors.

## Web

Open /market-regime. The page uses the shared API client and renders loading,
empty, error, forbidden and success states. Each row displays algorithm
version, freshness, sample size and confidence; rotation rows also show the
evidence window.
