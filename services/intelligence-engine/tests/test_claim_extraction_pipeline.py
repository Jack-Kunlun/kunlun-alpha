from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from intelligence_engine.llm.models import ResolvedProfile
from intelligence_engine.pipelines.claims import ClaimExtractionConsumer
from intelligence_engine.pipelines.claims.candidate import parse_claim_extraction_response
from intelligence_engine.pipelines.claims.fake import (
    FakeClaimExtractor,
    InMemoryClaimAuditSink,
    InMemoryClaimCandidateStore,
)
from intelligence_engine.pipelines.claims.models import (
    ClaimContentSource,
    ClaimExtractionPolicy,
    ClaimExtractionRequest,
    ClaimFailureReason,
    ClaimMediaSegment,
    ClaimMediaSource,
    ClaimProcessStatus,
)
from intelligence_engine.pipelines.media.fake import fake_media_profile
from kol_core.extraction import EvidenceGrade

MOMENT = datetime(2025, 1, 1, tzinfo=UTC)


def _request() -> ClaimExtractionRequest:
    source = ClaimContentSource(
        source_index=0,
        content_id="content-1",
        content_version="v1",
        content_revision_id="content-r1",
        text="公开表述",
        available_time=MOMENT.replace(hour=2),
        publish_time=MOMENT,
        ingest_time=MOMENT.replace(hour=1),
        processing_time=MOMENT.replace(hour=1, minute=30),
        source="test",
        source_version="v1",
        evidence_grade=EvidenceGrade.PRIMARY_SOURCE,
    )
    profile: ResolvedProfile = fake_media_profile(MOMENT)
    return ClaimExtractionRequest(
        request_id="request-1",
        extraction_run_id="run-1",
        sources=(source,),
        decision_time=MOMENT.replace(hour=3),
        processing_time=MOMENT.replace(hour=3),
        resolved_profile=profile,
        instrument_index=("600519.SH",),
    )


def _raw() -> dict[str, object]:
    return {
        "schemaVersion": "claim-extraction-response-v1",
        "sourceIndex": 0,
        "statement": "公开表述",
        "action": "BUY",
        "polarity": "AFFIRMED",
        "conditionality": "UNCONDITIONAL",
        "statementKind": "DIRECT",
        "attribution": "SELF",
        "eventTimeStatus": "UNKNOWN",
        "eventTime": None,
        "eventDate": None,
        "instrumentIndex": 0,
        "confidenceBps": 8000,
        "anchors": [{"sourceIndex": 0, "startOffset": 0, "endOffset": 4, "excerpt": "公开表述"}],
    }


def test_claim_extraction_consumer_public_boundary_exists() -> None:
    assert ClaimExtractionConsumer.__name__ == "ClaimExtractionConsumer"


def test_candidate_response_requires_one_instrument_selector() -> None:
    request = _request()
    with pytest.raises(ValueError):
        parse_claim_extraction_response(
            _raw() | {"instrumentId": "600519.SH"},
            request,
            ClaimExtractionConsumer(FakeClaimExtractor([]), InMemoryClaimCandidateStore()).policy,
        )


def test_consumer_is_idempotent_and_does_not_mutate_frozen_candidate() -> None:
    request = _request()
    extractor = FakeClaimExtractor([_raw()])
    store = InMemoryClaimCandidateStore()
    consumer = ClaimExtractionConsumer(extractor, store)
    first = consumer.handle(request)
    second = consumer.handle(request)
    assert first.status is ClaimProcessStatus.COMMITTED
    assert second.status is ClaimProcessStatus.ALREADY_COMMITTED
    assert first.candidate is not None
    assert first.candidate.previous_revision_id is None
    assert len(extractor.calls) == 1


def test_store_claim_has_an_explicit_in_progress_state() -> None:
    store = InMemoryClaimCandidateStore()
    assert store.claim("same") is ClaimProcessStatus.COMMITTED
    assert store.claim("same") is ClaimProcessStatus.IN_PROGRESS
    store.release("same")
    assert store.claim("same") is ClaimProcessStatus.COMMITTED


def test_candidate_identity_binds_trusted_source_revision() -> None:
    request = _request()
    policy = ClaimExtractionPolicy()
    first = parse_claim_extraction_response(_raw(), request, policy)
    alternate_source = replace(
        request.sources[0], content_id="content-2", content_revision_id="content-r2"
    )
    alternate = parse_claim_extraction_response(
        _raw(), replace(request, sources=(alternate_source,)), policy
    )
    assert first.candidate_id != alternate.candidate_id


def test_low_confidence_reaches_policy_rejection_branch() -> None:
    policy = ClaimExtractionPolicy(minimum_confidence_bps=9_000)
    audit_sink = InMemoryClaimAuditSink()
    result = ClaimExtractionConsumer(
        FakeClaimExtractor([_raw()]),
        InMemoryClaimCandidateStore(),
        policy=policy,
        audit_sink=audit_sink,
    ).handle(_request())
    assert result.status is ClaimProcessStatus.REJECTED
    assert result.failure is ClaimFailureReason.LOW_CONFIDENCE
    assert result.audit is not None
    assert result.audit.reason == "low_confidence"
    assert audit_sink.records == [result.audit]


def test_permanent_extractor_failure_releases_claim() -> None:
    request = _request()
    store = InMemoryClaimCandidateStore()
    audit_sink = InMemoryClaimAuditSink()
    failed = ClaimExtractionConsumer(FakeClaimExtractor([]), store, audit_sink=audit_sink).handle(
        request
    )
    assert failed.status is ClaimProcessStatus.REJECTED
    assert failed.failure is ClaimFailureReason.EXTRACTOR_FAILURE
    assert failed.audit is not None
    assert failed.audit.reason == "extractor_permanent_failure"
    retried = ClaimExtractionConsumer(FakeClaimExtractor([_raw()]), store).handle(request)
    assert retried.status is ClaimProcessStatus.COMMITTED


def test_policy_fingerprint_is_part_of_extraction_idempotency() -> None:
    request = _request()
    store = InMemoryClaimCandidateStore()
    first = ClaimExtractionConsumer(FakeClaimExtractor([_raw()]), store).handle(request)
    changed_policy = replace(ClaimExtractionPolicy(), pipeline_version="kol-claim-pipeline-v2")
    second = ClaimExtractionConsumer(
        FakeClaimExtractor([_raw()]), store, policy=changed_policy
    ).handle(request)
    assert first.status is ClaimProcessStatus.COMMITTED
    assert second.status is ClaimProcessStatus.REJECTED
    assert second.failure is ClaimFailureReason.CONFLICT
    assert second.idempotency_key != first.idempotency_key


def test_as_of_hides_tombstone_after_deletion_available_time() -> None:
    request = _request()
    store = InMemoryClaimCandidateStore()
    result = ClaimExtractionConsumer(FakeClaimExtractor([_raw()]), store).handle(request)
    assert result.candidate is not None
    root = result.candidate
    tombstone = replace(
        root,
        revision_id="revision-tombstone",
        previous_revision_id=root.revision_id,
        available_time=MOMENT.replace(hour=4),
        deleted=True,
        deleted_at=MOMENT.replace(hour=4),
        deletion_reason="撤回",
    )
    store.append("source-lifecycle", tombstone, root.revision_id)
    assert store.as_of(root.candidate_id, MOMENT.replace(hour=3, minute=30)) == root
    assert store.as_of(root.candidate_id, MOMENT.replace(hour=4)) is None


def test_tombstone_effective_time_is_deleted_at_not_available_time() -> None:
    request = _request()
    store = InMemoryClaimCandidateStore()
    result = ClaimExtractionConsumer(FakeClaimExtractor([_raw()]), store).handle(request)
    assert result.candidate is not None
    root = result.candidate
    tombstone = replace(
        root,
        revision_id="revision-tombstone-later",
        previous_revision_id=root.revision_id,
        available_time=MOMENT.replace(hour=4),
        deleted=True,
        deleted_at=MOMENT.replace(hour=5),
        deletion_reason="撤回",
    )
    store.append("source-lifecycle-later", tombstone, root.revision_id)
    assert store.as_of(root.candidate_id, MOMENT.replace(hour=3, minute=30)) == root
    assert store.as_of(root.candidate_id, MOMENT.replace(hour=4, minute=30)) == root
    assert store.as_of(root.candidate_id, MOMENT.replace(hour=5)) is None


def test_source_lifecycle_appends_a_candidate_tombstone() -> None:
    request = _request()
    store = InMemoryClaimCandidateStore()
    result = ClaimExtractionConsumer(FakeClaimExtractor([_raw()]), store).handle(request)
    assert result.candidate is not None
    root = result.candidate
    committed = store.append_source_tombstone(
        "content", "content-1", "content-r1", MOMENT.replace(hour=4), "source_corrected"
    )
    assert len(committed) == 1
    assert committed[0].candidate_id == root.candidate_id
    assert committed[0].previous_revision_id == root.revision_id
    assert committed[0].deleted is True


def test_media_candidate_identity_binds_evidence_revision() -> None:
    def media_request(evidence_revision_id: str) -> ClaimExtractionRequest:
        source = ClaimMediaSource(
            source_index=0,
            content_id="content-1",
            content_version="v1",
            content_revision_id="content-r1",
            evidence_id="evidence-1",
            evidence_revision_id=evidence_revision_id,
            media_id="media-1",
            media_version="v1",
            media_manifest_revision_id="manifest-r1",
            text="公开表述",
            segments=(ClaimMediaSegment(0, "公开表述", 0, 4),),
            available_time=MOMENT.replace(hour=2),
            content_available_time=MOMENT.replace(hour=1),
            evidence_available_time=MOMENT.replace(hour=2),
            publish_time=MOMENT,
            ingest_time=MOMENT.replace(hour=1),
            processing_time=MOMENT.replace(hour=1, minute=30),
            source="test",
            source_version="v1",
            evidence_grade=EvidenceGrade.PRIMARY_SOURCE,
            overall_confidence_bps=10_000,
            overall_quality_bps=10_000,
        )
        return replace(_request(), sources=(source,))

    raw = _raw() | {
        "anchors": [
            {
                "sourceIndex": 0,
                "startOffset": 0,
                "endOffset": 4,
                "excerpt": "公开表述",
                "segmentIndexes": [0],
            }
        ]
    }
    first = parse_claim_extraction_response(
        raw, media_request("evidence-r1"), ClaimExtractionPolicy()
    )
    second = parse_claim_extraction_response(
        raw, media_request("evidence-r2"), ClaimExtractionPolicy()
    )
    assert first.candidate_id != second.candidate_id
