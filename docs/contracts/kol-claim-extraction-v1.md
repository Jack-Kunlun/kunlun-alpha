# KOL Claim Extraction Candidate v1

`KolClaimExtractionCandidate` is an unreviewed, versioned public-speech candidate. It is not a fact, `Trade`, order, fill, account, executable quantity, or `PositionClaim`. A model may return only a request source index and exact offsets; the trusted pipeline resolves content/media identity, revision, evidence grade, and available time from the point-in-time source snapshot.

## Contract

- Schema versions are `claim-extraction-candidate-v1`, `claim-review-submission-v1`, and `claim-review-v1`.
- The candidate semantic label is `PUBLIC_SPEECH_CANDIDATE_NOT_FACT_OR_EXECUTION`; initial review status is always `UNREVIEWED`.
- Actions are `BUY`, `SELL`, `HOLDING`, and `WATCH`; `HOLDING` does not emit a `PositionClaim`.
- `QUOTE` requires `QUOTED` or `REPORTED` attribution. `AMBIGUOUS` cannot be self-attributed. `APPROVED` means only that the public wording was reviewed, never that it is true, traded, or executable.
- `EXACT` has an aware `eventTime` and no `eventDate`; `DATE_ONLY` has a real calendar `eventDate` and no time; `UNKNOWN` has neither. No midnight or invented offset is permitted.
- Instrument identity uses the shared prefix-rule parser and only canonical forms such as `600519.SH`; exchange suffix mismatches and names are rejected.
- Content anchors bind an exact content ID/version/revision and code-point half-open slice. Media anchors additionally bind exact media/evidence revisions and selected segment indexes. The excerpt must equal the trusted source slice.
- `confidenceBps` is an integer in `[0,10000]` and cannot exceed selected media confidence or quality. Evidence grades describe provenance strength, not truth and are retained per anchor plus a conservative aggregate.
- `publishTime <= ingestTime <= processingTime <= availableTime`; source availability, authorization and deletion are evaluated at `decisionTime`. Corrections and tombstones append a new revision and never erase prior evidence.
- Candidate identity is deterministic and recomputable across Python and TypeScript. `kol-claim-candidate-id-v1` hashes canonical JSON of the semantic statement, canonical instrument/event fields, evidence grade and every exact content/media anchor provenance field. `kol-claim-revision-id-v1` hashes canonical JSON of the full published candidate revision, excluding only `revisionId` and `previousRevisionId`; the store supplies the predecessor through CAS. Canonical JSON is UTF-8, recursively key-sorted, with RFC3339 instants normalized to UTC. Fixed content, media and tombstone fixtures live at `packages/contracts/src/kol/claim-extraction-identity-fixtures.json`.

## Review boundary

`claim-review-submission-v1` is the only client payload. It has no reviewer, server time, candidate state, evidence, or provenance fields. The server resolves the exact candidate revision from the PostgreSQL candidate projection, obtains authenticated reviewer context and server time, and appends a linear review with a CAS predecessor and idempotency fingerprint. The review endpoint cannot create or upload a candidate.

## Reproducibility and privacy

The candidate records algorithm, prompt/model/configuration/policy/run fingerprints and all selected source revisions. Pipeline audits contain only opaque SHA-256 fingerprints, status/reason codes and timestamps; raw prompt, model output, source text and secrets are never logged. Fake extractor/store ports are used in tests; no network or model SDK is part of this node.

Generated DTOs under `python/packages/ashare-contracts` and `packages/shared-types` are transport shapes. Untrusted payloads must pass the TypeScript runtime validators or Python `parse_claim_*_payload` functions before entering the frozen domain.
## Runtime and trust boundary

`ClaimExtractionCandidate` generated DTOs are transport shapes, not the
authoritative untrusted-payload validator. External and cross-process input
must pass the `@kunlun/contracts/kol` runtime validator and the server-owned
`ClaimCandidateMaterializer`; the materializer derives projection fingerprints
and never accepts a client `integrityValid` value.

The server review projection is append-only by `(candidateId, revisionId)`.
Candidate heads and review heads are selected from predecessor relationships,
not timestamps. A source deletion or correction is represented by a later
candidate tombstone revision, so review of an older revision is rejected once
the new head is visible. Tombstone effective time is `deletedAt`; before that
instant, point-in-time lookup returns the predecessor even when tombstone
`availableTime` has passed. At or after `deletedAt`, the candidate is
unavailable.

PostgreSQL stores the bounded, validated canonical candidate JSON in
`canonical_payload`. Reads recompute candidate/revision IDs and both
payload/integrity fingerprints. Candidate successors carry a database-derived
`previous_available_at`; a composite foreign key and strict-time check reject
forged, equal or reversed predecessor timestamps. `integrityValid` is not a
trusted stored field.

The local Docker `server` and `server-migrate` use the same non-secret
PostgreSQL URL/search path. The runtime variable is
`CLAIM_REVIEW_POSTGRES_DSN`; `server-migrate` runs the registered migration 004
before the server starts. The default authorizer remains fail-closed because
this repository has no trusted HTTP identity provider; deployment must inject
an authenticated internal principal rather than relying on client headers.
