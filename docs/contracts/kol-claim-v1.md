# KOL claim contract v1

This contract models public KOL content and statements as immutable, versioned
research evidence. It does not model broker activity, orders, fills,
positions, accounts, or executable quantities.

## Versioned boundary

The JSON Schema identifiers are:

- `kol-content-v1`
- `kol-mention-v1`
- `kol-evidence-v1`
- `kol-claim-v1`
- `kol-position-claim-v1`

The domain algorithm version is `kol-domain-v1`. Content fingerprints use
`sha256-kol-content-v1`: UTF-8 bytes of `title`, one NUL separator, and UTF-8
bytes of `body`, hashed with SHA-256 and encoded as lowercase hexadecimal.
The generated TypeScript and Pydantic classes are transport shapes only.
Untrusted payloads must be passed through the `kol` runtime validators or the
`kol_core.parse_*_payload` functions before entering domain code.

## Content, mentions, and evidence

`KolContent` is immutable at each `(content_id, content_version)` and carries
`revision_id`/`previous_revision_id`. A correction appends a new revision;
the old content remains addressable. A deletion is a tombstone: it retains
the original content fingerprint and provenance and adds deletion metadata.
`event_time` is optional and may be retrospective. It is not required to be
before `publish_time`.

`KolMention` records an occurrence or reference in an exact content version.
It is not an assertion and cannot be used as a claim without an explicit
`KolClaim`.

`KolEvidence` is an immutable locator for an exact content version. The
locator is bounded (`url`, `text_range`, `time_range`, or `page`) and the
required non-empty excerpt is bounded. Evidence records carry `source` and
`source_version`, `available_time`, and the content's available time. Domain
validation requires the evidence to bind to the exact content ID and version;
the evidence must not be available before that content.

## Claim semantics

Every `KolClaim` has a canonical instrument symbol such as `600519.SH`, a
direction, attribution, uncertainty, review status, integer confidence in
basis points (`0..10000`), the five timezone-aware instants
`event_time/publish_time/ingest_time/processing_time/available_time`, and one
or more evidence references. The operational time order is:

```text
publish_time <= ingest_time <= processing_time <= available_time
```

No ordering is imposed between `event_time` and `publish_time`, because a
statement can discuss a retrospective event. A claim's available time cannot
precede the available time of its content or any evidence reference.

`DIRECT`, `QUOTE`, `PARAPHRASE`, and `AMBIGUOUS` are explicit statement kinds.
Attribution and uncertainty must not be inferred away. An ambiguous,
reported, or paraphrased statement remains a claim with its recorded review
state; it is not silently promoted to a direct fact.

`KolPositionClaim` links a specific claim revision and is explicitly marked
`NON_EXECUTABLE_POSITION_CLAIM`. It is descriptive KOL content, not a Trade,
order, fill, broker confirmation, account fact, fill price, or executable
quantity. The schemas intentionally contain no `tradeId`, `orderId`, `fillId`,
broker account, fill price, or executable quantity fields.

## Point-in-time visibility

`visible_at(payload, decision_time)` is true only when the payload's
`available_time <= decision_time`, both instants are timezone-aware, and the
payload is not deleted. A future revision or future deletion therefore cannot
change an earlier point-in-time view. Callers must query the visible revision
chain rather than replacing historical content in place.

## Parsing and conversion

The generated DTOs are intentionally limited to transport representation.
They do not replace cross-field validation. `kol_core` uses generated
Pydantic DTO validation at the parse boundary and then constructs frozen
domain dataclasses. Domain construction rechecks revision self-links, strict
boolean/integer fields, timestamps, canonical symbols, evidence binding,
content fingerprints, deletion metadata, and position-claim linkage.

The public Python surface is `kol_core`; the public TypeScript runtime surface
is `@kunlun/contracts/kol`. Consumers must use these public imports rather
than importing generated implementation modules directly.

## Provenance and deletion

Content, evidence, and claims retain `source`, `source_version`, exact version
identities, and all applicable available times. Revisions use
`previous_revision_id`; a revision cannot point to itself. Deletion does not
erase the source content, evidence, fingerprint, or revision chain. It adds a
deletion reason and timestamp while preserving the auditable historical
record.

## Evidence grade

`KolEvidence` requires `evidence_grade` and
`evidence_grade_version=evidence-grade-v1`. The grade describes provenance
strength, not truth or correctness:

- `PRIMARY_SOURCE`: the locator points to original public content or an
  authoritative first-party publication.
- `SECONDARY_SOURCE`: an identifiable independent report or quotation that
  preserves a source locator.
- `TERTIARY_SOURCE`: an aggregation, index, or derivative compilation.
- `UNCLASSIFIED`: the source is retained but its provenance grade is not
  established.

No grade is a truth label. Claims do not derive an aggregate grade; each
claim retains the grade on its separately versioned evidence record. The
excerpt is required and non-empty, with a maximum length of 4,000 characters.

## Claim combination and canonical instruments

The conservative v1 combination matrix is fixed:

- `QUOTE` requires `QUOTED` or `REPORTED` attribution, never `SELF`.
- `AMBIGUOUS` requires non-`NONE` uncertainty.
- `APPROVED` means only `PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION`.
  It does not mean the statement is true, traded, filled, or broker-confirmed.

Canonical instrument IDs use the shared market parser's suffix form. The
prefix rule must agree with the suffix, so `600519.SH` is valid while
`600519.SZ` and `000001.SH` are rejected.

## Aggregate trust boundary and revision graph

Single-record parsers are DTO syntax boundaries only and do not constitute
trusted storage input. The trusted entry points are the public aggregate
parsers `parse_kol_domain_snapshot_payload` in Python and
`parseKolDomainSnapshotPayload` in TypeScript. They accept complete Content,
Evidence, Claim, and PositionClaim collections and validate:

- one logical ID plus unique revision ID per entity;
- exactly one root, same-logical-ID `previous_revision_id`, no cycles, no
  forks, and strictly increasing `available_time` along every revision edge;
- Evidence bound to an actual Content ID/version and matching availability;
- Claim evidence references bound to actual Evidence ID/revision and matching
  Content/source/availability;
- PositionClaim linked to the actual Claim ID/revision and matching identity.

The aggregate PIT API selects the latest revision whose `available_time` is at
or before `decision_time` for each logical entity. A future correction cannot
alter an earlier selection. A deletion tombstone becomes the latest selected
state only after its own available time, while the aggregate retains the
historical content and evidence revisions for audit.

## Field limits and cross-language parity

Identifiers, source names, and source versions are 1..256 characters. Titles
are 1..10,000, content bodies 1..1,000,000, statements 1..10,000, surface
mentions 1..1,000, locators 1..2,048, excerpts 1..4,000, and deletion reasons
1..1,000. Mention offsets are integers in 0..1,000,000. Confidence is an
integer in 0..10,000 basis points. JSON Schema, TypeScript runtime validators,
and Python domain construction enforce the same limits and reject unknown
fields. Content fingerprints are recomputed at both runtime boundaries using
the versioned UTF-8 `title + NUL + body` SHA-256 algorithm.
