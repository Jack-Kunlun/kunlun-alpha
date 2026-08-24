# Event Extraction Failure Runbook

## Scope

This runbook covers `event-extraction-pipeline-v1` (`P3-N07`). The consumer is fail-closed: only a validated `MarketEvent`
can reach `ExtractionStore.commit_validated`; every model/provider failure remains outside the fact layer.

## Queue dispositions

| Status            | Queue action | Meaning |
| ----------------- | ------------ | ------- |
| `STORED`          | Ack          | Event and success audit were committed atomically. |
| `DUPLICATE`       | Ack          | The derived idempotency key already has a committed event. |
| `RETRY_SCHEDULED` | Retry at time | Classified transient failure, still below the bounded attempt limit. |
| `REJECTED`        | Ack + review | Permanent or exhausted failure persisted in the isolated outcome store. |

Never acknowledge a message when the store cannot persist the returned retry/rejection audit outcome.

## Classification

- Retryable: `MODEL_TIMEOUT`, `MODEL_RATE_LIMIT`, `MODEL_TRANSIENT`, `STORE_TRANSIENT`.
- Permanent: unavailable/deleted/unlicensed source, missing registered configuration, invalid JSON/candidate, oversized
  response, evidence mismatch, low confidence, domain validation failure, permanent provider error.
- Exhausted transient failures become `RETRY_EXHAUSTED`; do not reset their attempt counter automatically.

## Required storage guarantees

`commit_validated(idempotency_key, event, result)` must atomically write the fact event and its `STORED` audit record. It
must be put-if-absent on `idempotency_key`. `record_outcome` stores duplicates, retries, and rejections in an isolated audit
area that is never queried as market fact data. Raw provider output is retained there for controlled replay and must not be
emitted to logs or metrics.

## Triage and replay

1. Locate the isolated result using `request_id`, `extraction_run_id`, or `idempotency_key`.
2. Inspect `FailureReason`, `detail_code`, attempt, deployment ID, configuration fingerprint, and raw-output SHA-256.
3. For malformed/evidence failures, review raw output only in the restricted audit store; never copy it into logs.
4. Fix or register a new immutable prompt/model/profile version. Do not edit an existing version.
5. Replay with a new decision context only when semantics should change. A retry of the same decision must retain the same
   document version, routing key, profile ID, decision time, extraction run ID, and attempt progression.
6. Confirm the replay produced `STORED` or `DUPLICATE` and that no rejected candidate was inserted into the fact table.

## Alerts

Alert on aggregate reason and deployment ID only. Do not label metrics with raw security symbols, request IDs, content IDs,
account data, source text, provider output, or exception messages.
