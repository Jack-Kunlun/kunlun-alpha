# KOL performance and consensus v1

## Scope

P4-N09 produces three research-only features: `kol_attention_score`,
`consensus_score`, and `claim_score`. They describe public wording and subsequent
market observations. They are not broker facts, orders, fills, or executable
prices and cannot place a real order.

## Point-in-time policy

- A Claim revision enters calculation at its own `available_time`, never at an
  earlier `publish_time` or a predecessor's time.
- A later textual or directional revision creates a new performance sample from
  its own first tradable observation. It never rewrites the predecessor sample.
- Review status is part of evaluation state. A same-text revision that changes
  from `IN_REVIEW` to `APPROVED` becomes eligible only from that revision's own
  `available_time`; approval never backfills an earlier unapproved snapshot.
- Claim lineage validation uses only revisions visible at the requested cutoff.
  A malformed future revision cannot change or block an older historical replay.
- Price replacements are visible only when their `available_time` is not later
  than the feature `decision_time`. The highest visible `replacement_version`
  wins even if an older version is ingested again later. Each instrument must
  use exactly one `{source, source_version, data_version, interval, session,
  adjustment}` series; cross-series input and duplicate highest versions fail
  closed rather than competing by replacement number.
- Calculation requires one visible, versioned `TradingCalendarSnapshot` per
  affected market. Its coverage must include Claim availability through the
  requested decision time, and every daily price must match an expected session.
  Calendar snapshots use a monotonic `replacement_version`; the highest visible
  replacement from one source series wins, while ties or mixed series fail closed.
- The entry is the first non-suspended expected session whose close time is not
  earlier than Claim `available_time`. No expected session yields
  `WAITING_FOR_ENTRY`; a missing expected price yields `MISSING_PRICE`. Both are
  `PENDING`, not permanent exclusions.
- Horizons count non-suspended expected sessions after entry. A missing session
  price stops the path instead of allowing a later date to move forward into an
  earlier horizon. Every observed suspension before or after entry remains in
  provenance and does not count as a tradable step.
- A tombstone removes the lineage from active attention and consensus at
  `deleted_at`. Historical public performance remains in the audit result and
  records `withdrawn_at`; the deletion time participates in `data_cutoff_time`.
  Tombstones are terminal and cannot be followed by a resurrected revision.
  Because performance measures what followed a statement while it was public,
  deletion does not truncate an already-started historical return horizon.
- Revision chains must be complete, linear, monotonic, and unambiguous. Missing
  predecessors, forks, duplicate revisions, or ambiguous price replacements
  fail closed.

## Formulas

All prices and returns use `Decimal`. Published feature values use integer basis
points and round half-even.

### `kol_attention_score`

For each KOL, approved active Claims in the configured lookback receive a
linear recency weight and a confidence weight:

```text
weighted_count = sum((confidence_bps / 10000) * recency_weight)
score_bps = min(10000, weighted_count / attention_saturation * 10000)
```

### `consensus_score`

Only approved active Claims at or above the high-grade confidence threshold are
eligible. Each KOL contributes at most its latest Claim per instrument:

```text
score_bps = 10000 * sum(direction_sign * confidence_bps) / sum(confidence_bps)
```

`BULLISH=+1`, `BEARISH=-1`, and `NEUTRAL=0`. The value is unpublished until the
configured minimum number of distinct KOLs is present. A zero total confidence
weight is also reported as `INSUFFICIENT_SAMPLES` rather than divided or imputed.

### `claim_score`

For a mature approved directional Claim revision, each raw horizon return is
multiplied by the Claim direction. The average signed return is capped by the
versioned return cap and mapped to `[0, 10000]`. The final score is the equal
weight average of this outcome score and `confidence_bps`. Low-confidence or
immature Claims are never marked `high_grade`.

## Versions and provenance

Every output carries algorithm version, policy version, policy fingerprint,
decision time, data cutoff time, sample count, structured Claim references,
structured price references, complete selected calendar snapshots, and a
canonical SHA-256 input fingerprint. Claim references include `{source, claim_id,
revision_id}`, content version, public times, review state, confidence, and
evidence revision IDs, so equal revision strings from separate sources cannot
collide. Price references retain every observed path item, including intermediate
non-horizon sessions, entry/exit and skipped-suspension revisions, raw captures,
prices, data/source versions, availability, and replacement versions. Calendar
objects retain all expected sessions and expose their own canonical fingerprint.
Performance results also embed the selected calendar snapshots and known
withdrawal time.
