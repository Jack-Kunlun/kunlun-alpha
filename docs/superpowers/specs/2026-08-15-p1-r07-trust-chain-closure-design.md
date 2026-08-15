# P1-R07 Trust-Chain Closure Design

## Status and scope

This design closes the five blocking findings from the final P1-R07 audit.
It does not redesign the already accepted raw landing zone, scheduler lease
model, logical-observation/evidence split, or fund migration ledger. It does
not start P1-R08 and does not add API, Web, ClickHouse, Phase 2, broker, QMT,
or live-trading behavior.

## 1. Trusted normalization context

Raw provider bytes remain the only observation input. After
`RawStorage.put()`, the collector reads the object back with checksum and size
verification and decodes that verified copy. A new immutable trusted context
is then built from the manifest and the collector clock.

The context owns `source`, `raw_capture_id`, `raw_object_id`, checksum,
`ingest_time`, the transport `available_time` floor, `processing_time`,
`endpoint_kind`, `run_id`, and `source_revision`. Payload fields cannot replace
these values. Payload `availableTime` may make an observation available later,
never earlier. Payload `rawObjectId`, when present, must exactly equal the
manifest object ID. Event and publish times may come from decoded content but
must satisfy the complete chronological ordering.

`endpoint_kind` is validated against the five fund endpoint kinds:
`metadata`, `nav`, `inav`, `benchmark`, and `fees`. Route identifiers are
validated before raw capture and replay.

## 2. Safe rejected-record diagnostics

Raw malformed content is already retained in the immutable landing zone, so a
rejection row does not need raw values. Rejections persist only:

- a controlled reason code;
- a bounded list of field names;
- item/content digest;
- evidence identity and trusted route metadata.

They never persist `repr(item)`, exception text, Pydantic input values, bearer
tokens, cookies, DSNs, headers, request bodies, or arbitrary nested strings.
Human-readable messages are generated from controlled reason codes rather than
external exception strings.

## 3. Provider error classification

The provider fetch boundary catches the existing `market_core` provider error
taxonomy and converts it to scheduler errors with controlled categories:

- timeout, rate-limit, and unavailable are transient;
- auth, not-found, and data-error are permanent;
- an unknown exception is recorded as `internal` and never leaves a task in
  `RUNNING`.

No original provider message is stored. The mapping is tested through the
actual `TaskScheduler -> FundCollector -> provider` call path, not only through
a helper function.

## 4. Deterministic rescan and replay lineage

Recovery remains an at-least-once rescan from the provider's first page; no
opaque remote cursor is persisted. Each captured page receives immutable route
metadata plus a trusted `page_ordinal` and `attempt_id`. The checkpoint stores
the active attempt ID, committed page count, last capture ID, cursor hashes,
and completion state.

Replay selects one attempt explicitly. It orders pages by `page_ordinal`,
requires a contiguous zero-based sequence, rejects duplicate ordinals and
unknown cursor transitions, and never falls back to page zero. Restarted
rescans produce a new attempt under the same run, so old and new captures stay
auditable without making replay ambiguous. All five endpoint kinds share this
route and replay contract. A missing source revision is represented by a
controlled sentinel in route identity; legacy manifests without the complete
route are rejected from routed replay.

## 5. Exact migration-state verification

The canonical SQL artifact, independent checksum ledger, global advisory lock,
and same-connection transaction remain unchanged. The verifier is extended to
compare the complete PostgreSQL catalog state for every task-owned table:

- columns, order, type, nullability, and defaults;
- primary keys, unique constraints, check expressions;
- foreign-key columns, referenced table/columns, update/delete action;
- indexes, ordered columns/expressions, access method, uniqueness, predicate;
- absence of extra task-owned constraints and indexes.

Expected metadata is explicit and tied to the canonical SQL checksum. Any
missing, changed, or additional task-owned metadata fails before the migration
ledger advances. Live tests mutate one catalog dimension at a time and verify
fail-closed behavior and transaction rollback.

## Error handling and recovery

All new validation happens before page persistence. A page containing invalid
provenance creates a safe rejection when the item can be identified; a route
or raw-object integrity failure aborts the page. PostgreSQL conflicts and
migration drift remain fail-closed. Recovery never deletes historical raw
captures or overwrites observations.

## Verification design

The five workstreams each begin with a focused failing regression test and end
with narrow GREEN verification. Final acceptance requires focused fund/raw/
scheduler tests, full data-worker and market-core suites, live PostgreSQL
migration/restart/concurrency tests, Ruff format/check, BasedPyright, DB/API
tests/builds, LF and diff checks, and a fresh independent Terra audit.

## Non-goals

- Exact remote-cursor resume.
- Canonical-value selection for conflicting source observations.
- API/Web quality-event reads (P1-R08).
- New provider SDKs or production dependencies.
- Spot, futures, physical bullion, broker, QMT, or real-order behavior.
