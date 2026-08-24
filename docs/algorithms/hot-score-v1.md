# HotScore V1

## Contract

- Algorithm version: `hot-score-v1`
- Input: immutable `MarketEvent` plus a versioned `TopicObservation`
- Output: immutable `HotTopicSnapshot` with content-addressed `snapshot_id`
- Window: `(decision_time - lookback, decision_time]`, left-open and right-closed
- Arithmetic: integer basis points only; all division uses deterministic half-up rounding

An observation becomes available at `assignment_available_time`, which must not predate its event. Any event or assignment
newer than `decision_time` is rejected rather than silently filtered. Events exactly at the left boundary are stale; events
exactly at the decision time are eligible.

## Deduplication

`event_id` is the idempotency identity inside a topic. Repeated identical observations count once. The same event ID with a
different relevance, assignment fingerprint, topic identity, or availability time is a conflict and fails the calculation.

## Components

For event `i`:

```text
quality_i = round_half_up(event_confidence_bps_i * topic_relevance_bps_i / 10000)
```

The five BPS components are:

1. `evidence_quality_bps`: average `quality_i`; event count alone cannot raise it.
2. `recency_bps`: average linear time-decay weight, 10000 at decision time and approaching 0 at the left boundary.
3. `source_diversity_bps`: unique evidence sources divided by the configured saturation count, capped at 10000.
4. `breadth_bps`: capped sum of unique canonical instruments and sector IDs using configured integer steps.
5. `momentum_bps`: recent quality intensity versus duration-normalized prior-window intensity, centered at 5000 and capped
   to `[0, 10000]`. Activity saturates at the configured event count.

Default score:

```text
HotScore = round_half_up(
    quality * 4000
  + recency * 2000
  + source_diversity * 1500
  + breadth * 1000
  + momentum * 1500
) / 10000
```

The component weights must total exactly 10000. Every parameter contributes to `policy_fingerprint`; changing any parameter
creates a distinct policy identity and must not overwrite snapshots produced under another fingerprint.

## Confidence and sparse data

Snapshot confidence combines evidence quality and source diversity, then applies a sample factor that reaches full weight at
four eligible events. A single excellent event can become `RISING`, but cannot become `HOT` under the default
`minimum_hot_events = 2` and retains visibly low snapshot confidence.

## Lifecycle

- `DORMANT`: no eligible event in the lookback window.
- `COOLING`: a prior `HOT`/`RISING` snapshot falls by at least `cooling_drop_bps` under the same policy.
- `HOT`: score reaches the hot threshold and minimum sample count.
- `RISING`: score reaches the rising threshold.
- `EMERGING`: eligible evidence exists but does not reach the rising threshold.

Lifecycle comparison requires the same topic and policy fingerprint and a strictly earlier prior snapshot.
