"""Event extraction, isolation, retry, and idempotency acceptance tests (P3-N07)."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from event_core.models import MarketEvent, ProducerType
from intelligence_engine.llm import (
    Deployment,
    DeploymentOperation,
    ExtractionProfile,
    ModelSpec,
    PromptSpec,
    VersionRegistry,
)
from intelligence_engine.pipelines.events import (
    EVENT_CANDIDATE_SCHEMA_VERSION,
    CommitDisposition,
    EventExtractionConsumer,
    ExtractionRequest,
    ExtractionResult,
    ExtractionStatus,
    ExtractionStoreTransientError,
    FailureReason,
    ModelRateLimitError,
    ModelTimeoutError,
    ProviderInvocation,
    RetryPolicy,
    SourceDocument,
)

CREATED = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)
PUBLISH = datetime(2026, 8, 24, 0, 30, tzinfo=UTC)
AVAILABLE = datetime(2026, 8, 24, 1, 30, tzinfo=UTC)
DECISION = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)
PROCESSING = datetime(2026, 8, 24, 2, 1, tzinfo=UTC)
SOURCE_TEXT = "公司发布重大事项公告"


class FakeGateway:
    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = list(responses)
        self.invocations: list[ProviderInvocation] = []

    def generate(self, invocation: ProviderInvocation) -> str:
        self.invocations.append(invocation)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class MemoryExtractionStore:
    def __init__(self) -> None:
        self.events: dict[str, MarketEvent] = {}
        self.committed_audits: list[ExtractionResult] = []
        self.other_outcomes: list[ExtractionResult] = []
        self.fail_commit = False
        self.force_race = False

    def find_committed(self, idempotency_key: str) -> MarketEvent | None:
        return self.events.get(idempotency_key)

    def commit_validated(
        self,
        idempotency_key: str,
        event: MarketEvent,
        result: ExtractionResult,
    ) -> CommitDisposition:
        if self.fail_commit:
            raise ExtractionStoreTransientError("unavailable")
        if self.force_race or idempotency_key in self.events:
            if idempotency_key not in self.events:
                self.events[idempotency_key] = event
            return CommitDisposition.ALREADY_EXISTS
        self.events[idempotency_key] = event
        self.committed_audits.append(result)
        return CommitDisposition.COMMITTED

    def record_outcome(self, result: ExtractionResult) -> None:
        self.other_outcomes.append(result)


def registry(*, minimum_confidence_bps: int = 7000) -> VersionRegistry:
    prompt = PromptSpec(
        prompt_id="event-candidate-extraction",
        version="v1",
        template="Extract strict event candidate JSON from {{content}}.",
        variables=("content",),
        output_schema_version="market-event-v1",
        created_at=CREATED,
    )
    model = ModelSpec(
        provider_id="provider-a",
        model_id="event-extractor",
        version="model-v1",
        api_variant="structured-output",
        credential_env_ref="KUNLUN_LLM_API_KEY",
        temperature_milli=0,
        max_output_tokens=4096,
        created_at=CREATED,
        seed=7,
    )
    profile = ExtractionProfile(
        profile_id="market-event-extraction",
        version="v1",
        prompt_id=prompt.prompt_id,
        prompt_version=prompt.version,
        model_provider_id=model.provider_id,
        model_id=model.model_id,
        model_version=model.version,
        output_schema_version="market-event-v1",
        minimum_confidence_bps=minimum_confidence_bps,
        created_at=CREATED,
    )
    deployment = Deployment(
        deployment_id="release-1",
        profile_id=profile.profile_id,
        primary_profile_version=profile.version,
        candidate_profile_version=None,
        candidate_allocation_bps=0,
        operation=DeploymentOperation.RELEASE,
        effective_at=datetime(2026, 8, 24, 1, 0, tzinfo=UTC),
        created_at=datetime(2026, 8, 24, 1, 0, tzinfo=UTC),
    )
    return (
        VersionRegistry()
        .register_prompt(prompt)
        .register_model(model)
        .register_profile(profile)
        .register_deployment(deployment)
    )


def document() -> SourceDocument:
    return SourceDocument(
        content_record_id="raw-record-1",
        content_version_id="a" * 64,
        source_id="cninfo",
        source_version="v1",
        raw_text=SOURCE_TEXT,
        publish_time=PUBLISH,
        available_time=AVAILABLE,
        usage_allowed=True,
    )


def request(*, attempt: int = 1, source: SourceDocument | None = None) -> ExtractionRequest:
    return ExtractionRequest(
        request_id=f"request-{attempt}",
        extraction_run_id="run-1",
        profile_id="market-event-extraction",
        routing_key="a" * 64,
        document=source or document(),
        decision_time=DECISION,
        processing_time=PROCESSING,
        attempt=attempt,
    )


def candidate_payload(*, confidence_bps: int | float = 8500) -> dict[str, object]:
    return {
        "schemaVersion": EVENT_CANDIDATE_SCHEMA_VERSION,
        "eventType": "CORPORATE",
        "headline": "某公司发布重大事项公告",
        "summary": "公司公告披露一项可追溯的重大事项。",
        "occurTime": PUBLISH.isoformat().replace("+00:00", "Z"),
        "instrumentIds": ["600519.SH"],
        "sectorIds": ["sector-food"],
        "evidenceSpans": [
            {
                "startOffset": 0,
                "endOffset": len(SOURCE_TEXT),
                "excerpt": SOURCE_TEXT,
            }
        ],
        "confidenceBps": confidence_bps,
    }


def output(payload: dict[str, object] | None = None) -> str:
    return json.dumps(payload or candidate_payload(), ensure_ascii=False)


def consumer(
    responses: list[str | Exception],
    *,
    store: MemoryExtractionStore | None = None,
    minimum_confidence_bps: int = 7000,
) -> tuple[EventExtractionConsumer, FakeGateway, MemoryExtractionStore]:
    gateway = FakeGateway(responses)
    storage = store or MemoryExtractionStore()
    return (
        EventExtractionConsumer(
            registry(minimum_confidence_bps=minimum_confidence_bps),
            gateway,
            storage,
            retry_policy=RetryPolicy(
                max_attempts=3,
                initial_delay_seconds=5,
                maximum_delay_seconds=20,
            ),
        ),
        gateway,
        storage,
    )


def test_valid_candidate_is_rebuilt_with_trusted_provenance_and_committed() -> None:
    worker, gateway, store = consumer([output()])
    result = worker.handle(request())
    assert result.status is ExtractionStatus.STORED
    assert result.event is not None
    assert len(store.events) == 1
    assert len(store.committed_audits) == 1
    assert store.other_outcomes == []
    assert result.event.model_provenance.producer_type is ProducerType.MODEL
    assert result.event.model_provenance.provider == "provider-a"
    assert result.event.model_provenance.prompt_version == "event-candidate-extraction@v1"
    assert (
        result.event.model_provenance.configuration_fingerprint == result.configuration_fingerprint
    )
    assert result.event.available_time == PROCESSING
    assert result.event.evidence[0].content_version_id == "a" * 64
    assert result.event.evidence[0].excerpt == SOURCE_TEXT
    assert (
        gateway.invocations[0].rendered_prompt
        == f"Extract strict event candidate JSON from {SOURCE_TEXT}."
    )


def test_duplicate_request_skips_provider_and_does_not_duplicate_fact() -> None:
    worker, gateway, store = consumer([output(), output()])
    first = worker.handle(request())
    second = worker.handle(request(attempt=2))
    assert first.status is ExtractionStatus.STORED
    assert second.status is ExtractionStatus.DUPLICATE
    assert len(gateway.invocations) == 1
    assert len(store.events) == 1
    assert store.other_outcomes[-1].status is ExtractionStatus.DUPLICATE


@pytest.mark.parametrize(
    ("raw_output", "reason"),
    [
        ("not-json", FailureReason.INVALID_JSON),
        (output(candidate_payload(confidence_bps=6999)), FailureReason.LOW_CONFIDENCE),
        (output(candidate_payload(confidence_bps=8500.5)), FailureReason.INVALID_CANDIDATE),
    ],
)
def test_invalid_or_low_confidence_output_is_isolated(
    raw_output: str,
    reason: FailureReason,
) -> None:
    worker, _, store = consumer([raw_output])
    result = worker.handle(request())
    assert result.status is ExtractionStatus.REJECTED
    assert result.failure is not None
    assert result.failure.reason is reason
    assert result.failure.raw_provider_output == raw_output
    assert result.failure.raw_output_sha256 is not None
    assert store.events == {}
    assert store.other_outcomes == [result]


def test_extra_forged_provenance_is_rejected_by_exact_candidate_contract() -> None:
    payload = candidate_payload()
    payload["modelProvenance"] = {"provider": "forged"}
    worker, _, store = consumer([output(payload)])
    result = worker.handle(request())
    assert result.status is ExtractionStatus.REJECTED
    assert result.failure is not None
    assert result.failure.reason is FailureReason.INVALID_CANDIDATE
    assert store.events == {}


@pytest.mark.parametrize("mutation", ["outside", "mismatch"])
def test_evidence_must_match_exact_trusted_source(mutation: str) -> None:
    payload = candidate_payload()
    spans = cast(list[dict[str, object]], payload["evidenceSpans"])
    span = spans[0]
    if mutation == "outside":
        span["endOffset"] = 999
    else:
        span["excerpt"] = "伪造证据"
    worker, _, store = consumer([output(payload)])
    result = worker.handle(request())
    assert result.status is ExtractionStatus.REJECTED
    assert result.failure is not None
    assert result.failure.reason is FailureReason.EVIDENCE_MISMATCH
    assert store.events == {}


def test_domain_invalid_vendor_symbol_never_enters_fact_layer() -> None:
    payload = candidate_payload()
    payload["instrumentIds"] = ["SH.600519"]
    worker, _, store = consumer([output(payload)])
    result = worker.handle(request())
    assert result.status is ExtractionStatus.REJECTED
    assert result.failure is not None
    assert result.failure.reason is FailureReason.EVENT_VALIDATION
    assert store.events == {}


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ModelTimeoutError("timeout"), FailureReason.MODEL_TIMEOUT),
        (ModelRateLimitError("rate limit"), FailureReason.MODEL_RATE_LIMIT),
    ],
)
def test_transient_provider_failure_has_bounded_retry(
    error: Exception,
    reason: FailureReason,
) -> None:
    worker, _, store = consumer([error])
    result = worker.handle(request())
    assert result.status is ExtractionStatus.RETRY_SCHEDULED
    assert result.failure is not None
    assert result.failure.reason is reason
    assert result.retry_at == PROCESSING + timedelta(seconds=5)
    assert store.events == {}


def test_retry_exhaustion_is_permanently_isolated() -> None:
    worker, _, store = consumer([ModelTimeoutError("timeout")])
    result = worker.handle(request(attempt=3))
    assert result.status is ExtractionStatus.REJECTED
    assert result.failure is not None
    assert result.failure.reason is FailureReason.RETRY_EXHAUSTED
    assert result.retry_at is None
    assert store.events == {}


@pytest.mark.parametrize(
    "source",
    [
        dataclasses.replace(document(), usage_allowed=False),
        dataclasses.replace(
            document(),
            available_time=datetime(2026, 8, 24, 3, 0, tzinfo=UTC),
        ),
        dataclasses.replace(document(), deleted=True, deleted_at=DECISION),
    ],
)
def test_unusable_source_is_rejected_before_provider(source: SourceDocument) -> None:
    worker, gateway, store = consumer([output()])
    result = worker.handle(request(source=source))
    assert result.status is ExtractionStatus.REJECTED
    assert result.failure is not None
    assert result.failure.reason is FailureReason.SOURCE_UNAVAILABLE
    assert gateway.invocations == []
    assert store.events == {}


def test_store_transient_failure_retries_without_claiming_success() -> None:
    store = MemoryExtractionStore()
    store.fail_commit = True
    worker, _, _ = consumer([output()], store=store)
    result = worker.handle(request())
    assert result.status is ExtractionStatus.RETRY_SCHEDULED
    assert result.failure is not None
    assert result.failure.reason is FailureReason.STORE_TRANSIENT
    assert store.events == {}
    assert store.committed_audits == []


def test_concurrent_commit_returns_existing_event_as_duplicate() -> None:
    store = MemoryExtractionStore()
    store.force_race = True
    worker, _, _ = consumer([output()], store=store)
    result = worker.handle(request())
    assert result.status is ExtractionStatus.DUPLICATE
    assert result.event is not None
    assert len(store.events) == 1
    assert store.committed_audits == []


def test_same_retry_context_builds_same_event_identity() -> None:
    first_worker, _, _ = consumer([output()])
    second_worker, _, _ = consumer([output()])
    first = first_worker.handle(request(attempt=1))
    second = second_worker.handle(request(attempt=2))
    assert first.event is not None
    assert second.event is not None
    assert first.event.event_id == second.event.event_id
    assert first.idempotency_key == second.idempotency_key
