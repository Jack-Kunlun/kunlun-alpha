"""P4-N06 KOL content and claim domain tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from ashare_contracts import KolContent as KolContentDTO
from kol_core import (
    ClaimAttribution,
    ClaimDirection,
    ClaimEvidenceReference,
    ClaimStatementKind,
    ClaimUncertainty,
    ContentType,
    EvidenceGrade,
    ExecutionSemantics,
    KolClaim,
    KolContent,
    KolEvidence,
    KolMention,
    KolPositionClaim,
    LocatorType,
    MentionType,
    PositionDirection,
    PositionTimeHorizon,
    ReviewStatus,
    from_contract,
    parse_kol_claim_payload,
    parse_kol_content_payload,
    parse_kol_evidence_payload,
    parse_kol_mention_payload,
    parse_kol_position_claim_payload,
    to_contract,
    validate_evidence_binding,
    validate_position_claim_link,
)
from pydantic import ValidationError

T0 = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=1)
T2 = T0 + timedelta(minutes=2)
T3 = T0 + timedelta(minutes=3)
T4 = T0 + timedelta(minutes=4)


def make_content(
    *,
    content_id: str = "content-1",
    content_version: str = "content-version-1",
    revision_id: str = "content-revision-1",
    previous_revision_id: str | None = None,
    available_time: datetime = T3,
    deleted: bool = False,
    deleted_at: datetime | None = None,
) -> KolContent:
    return KolContent(
        content_id=content_id,
        content_version=content_version,
        revision_id=revision_id,
        previous_revision_id=previous_revision_id,
        kol_id="kol-1",
        content_type=ContentType.POST,
        title="A public statement",
        body="A public statement about an instrument.",
        event_time=None,
        publish_time=T0,
        ingest_time=T1,
        processing_time=T2,
        available_time=available_time,
        source="social-platform",
        source_version="platform-v1",
        deleted=deleted,
        deleted_at=deleted_at,
        deletion_reason="author-request" if deleted else None,
    )


def make_evidence(
    content: KolContent,
    *,
    content_version: str | None = None,
    available_time: datetime = T4,
    revision_id: str = "evidence-revision-1",
    previous_revision_id: str | None = None,
) -> KolEvidence:
    return KolEvidence(
        evidence_id="evidence-1",
        revision_id=revision_id,
        previous_revision_id=previous_revision_id,
        content_id=content.content_id,
        content_version=content_version or content.content_version,
        content_available_time=content.available_time,
        source="social-platform",
        source_version="platform-v1",
        locator_type=LocatorType.TEXT_RANGE,
        locator="chars:0-18",
        excerpt="A public statement",
        evidence_grade=EvidenceGrade.PRIMARY_SOURCE,
        evidence_grade_version="evidence-grade-v1",
        available_time=available_time,
    )


def make_claim(content: KolContent, evidence: KolEvidence) -> KolClaim:
    return KolClaim(
        claim_id="claim-1",
        revision_id="claim-revision-1",
        previous_revision_id=None,
        content_id=content.content_id,
        content_version=content.content_version,
        content_available_time=content.available_time,
        kol_id=content.kol_id,
        statement="This is a public statement.",
        statement_kind=ClaimStatementKind.DIRECT,
        instrument_id="600519.SH",
        direction=ClaimDirection.BULLISH,
        attribution=ClaimAttribution.SELF,
        uncertainty=ClaimUncertainty.NONE,
        confidence_bps=8000,
        review_status=ReviewStatus.UNREVIEWED,
        event_time=T0,
        publish_time=T0,
        ingest_time=T1,
        processing_time=T2,
        available_time=T4,
        source="claim-extractor",
        source_version="extractor-v1",
        evidence=(
            ClaimEvidenceReference(
                evidence_id=evidence.evidence_id,
                evidence_revision_id=evidence.revision_id,
                content_id=evidence.content_id,
                content_version=evidence.content_version,
                content_available_time=evidence.content_available_time,
                evidence_available_time=evidence.available_time,
                source=evidence.source,
                source_version=evidence.source_version,
            ),
        ),
        deleted=False,
        deleted_at=None,
        deletion_reason=None,
    )


def test_content_revision_is_immutable_and_deleted_content_keeps_metadata() -> None:
    original = make_content()
    correction = make_content(
        content_version="content-version-2",
        revision_id="content-revision-2",
        previous_revision_id=original.revision_id,
    )
    tombstone = make_content(
        content_version="content-version-3",
        revision_id="content-revision-3",
        previous_revision_id=correction.revision_id,
        available_time=T4,
        deleted=True,
        deleted_at=T4,
    )

    assert original.content_version != correction.content_version
    assert correction.previous_revision_id == original.revision_id
    assert tombstone.deleted is True
    assert tombstone.body == original.body
    assert tombstone.content_fingerprint == original.content_fingerprint
    assert not tombstone.visible_at(T4)

    with pytest.raises(ValueError, match="previous_revision_id"):
        replace(original, revision_id="same", previous_revision_id="same")


def test_content_time_order_excludes_future_payload_and_does_not_order_event_time() -> None:
    content = make_content(available_time=T3)
    assert not content.visible_at(T3 - timedelta(microseconds=1))
    assert content.visible_at(T3)

    with pytest.raises(ValueError, match="processing_time|available_time"):
        make_content(available_time=T1)

    retrospective = replace(content, event_time=T4)
    assert retrospective.event_time == T4


def test_evidence_is_bound_to_content_version_and_restricted_locator() -> None:
    content = make_content()
    evidence = make_evidence(content)
    assert validate_evidence_binding(content, evidence) is None
    assert evidence.locator == "chars:0-18"
    assert evidence.excerpt == "A public statement"

    wrong_version = make_evidence(content, content_version="other-version")
    with pytest.raises(ValueError, match="content version"):
        validate_evidence_binding(content, wrong_version)

    with pytest.raises(ValueError, match="locator"):
        replace(evidence, locator="")


def test_mention_is_an_occurrence_not_an_assertion() -> None:
    mention = KolMention(
        mention_id="mention-1",
        revision_id="mention-revision-1",
        previous_revision_id=None,
        content_id="content-1",
        content_version="content-version-1",
        kol_id="kol-1",
        mention_type=MentionType.INSTRUMENT,
        surface_text="600519",
        start_offset=0,
        end_offset=6,
        available_time=T3,
        source="mention-parser",
        source_version="parser-v1",
    )
    assert mention.mention_type is MentionType.INSTRUMENT
    with pytest.raises((ValidationError, TypeError)):
        parse_kol_mention_payload(
            {**to_contract(mention).model_dump(by_alias=True), "assertion": True}
        )


def test_claim_requires_evidence_and_preserves_ambiguity_paraphrase_and_review() -> None:
    content = make_content()
    evidence = make_evidence(content)
    claim = make_claim(content, evidence)
    assert claim.evidence[0].evidence_id == evidence.evidence_id
    assert claim.confidence_bps == 8000
    assert claim.review_status is ReviewStatus.UNREVIEWED

    paraphrase = replace(
        claim,
        statement_kind=ClaimStatementKind.PARAPHRASE,
        uncertainty=ClaimUncertainty.AMBIGUOUS,
    )
    assert paraphrase.statement_kind is ClaimStatementKind.PARAPHRASE

    with pytest.raises(ValueError, match="evidence"):
        replace(claim, evidence=())
    with pytest.raises(ValueError, match="confidence"):
        replace(claim, confidence_bps=10001)
    with pytest.raises(ValueError, match="instrument"):
        replace(claim, instrument_id="600519")


def test_claim_rejects_evidence_mismatch_and_future_availability() -> None:
    content = make_content()
    evidence = make_evidence(content)
    claim = make_claim(content, evidence)

    with pytest.raises(ValueError, match="content version"):
        replace(
            claim,
            evidence=(replace(claim.evidence[0], content_version="other-version"),),
        )

    with pytest.raises(ValueError, match="available"):
        replace(claim, available_time=T2)


def test_position_claim_links_exact_claim_revision_and_is_not_executable() -> None:
    content = make_content()
    claim = make_claim(content, make_evidence(content))
    position = KolPositionClaim(
        position_claim_id="position-claim-1",
        revision_id="position-revision-1",
        previous_revision_id=None,
        claim_id=claim.claim_id,
        claim_revision_id=claim.revision_id,
        kol_id=claim.kol_id,
        instrument_id=claim.instrument_id,
        position=PositionDirection.LONG,
        time_horizon=PositionTimeHorizon.SWING,
        execution_semantics=ExecutionSemantics.NON_EXECUTABLE_POSITION_CLAIM,
        confidence_bps=claim.confidence_bps,
        review_status=claim.review_status,
        event_time=claim.event_time,
        publish_time=claim.publish_time,
        ingest_time=claim.ingest_time,
        processing_time=claim.processing_time,
        available_time=claim.available_time,
        source=claim.source,
        source_version=claim.source_version,
        deleted=False,
        deleted_at=None,
        deletion_reason=None,
    )
    assert validate_position_claim_link(position, claim) is None
    payload = to_contract(position).model_dump(by_alias=True)
    assert not {"tradeId", "orderId", "fillId", "brokerAccount", "fillPrice"}.intersection(payload)

    with pytest.raises(ValueError, match="claim revision"):
        validate_position_claim_link(
            replace(position, claim_revision_id="other-revision"),
            claim,
        )


def test_generated_dto_round_trip_and_unknown_payload_fail_closed() -> None:
    content = make_content()
    dto = to_contract(content)
    assert isinstance(dto, KolContentDTO)
    assert from_contract(dto) == content

    payload = dto.model_dump(by_alias=True, mode="json")
    with pytest.raises(ValidationError):
        parse_kol_content_payload({**payload, "unknown": True})
    with pytest.raises(TypeError, match="deleted"):
        parse_kol_content_payload({**payload, "deleted": 1})


def test_parse_claim_payload_applies_domain_validation_after_generated_dto() -> None:
    content = make_content()
    evidence = make_evidence(content)
    claim = make_claim(content, evidence)
    payload = to_contract(claim).model_dump(by_alias=True, mode="json")
    assert parse_kol_claim_payload(payload) == claim

    with pytest.raises((ValidationError, ValueError), match="previous_revision_id|revision"):
        parse_kol_claim_payload(
            {**payload, "previousRevisionId": payload["revisionId"]},
        )
    with pytest.raises(TypeError, match="confidenceBps"):
        parse_kol_claim_payload({**payload, "confidenceBps": 8000.0})


def test_parse_evidence_and_position_claim_payloads_are_public_boundaries() -> None:
    content = make_content()
    evidence = make_evidence(content)
    claim = make_claim(content, evidence)
    position = KolPositionClaim(
        position_claim_id="position-claim-1",
        revision_id="position-revision-1",
        previous_revision_id=None,
        claim_id=claim.claim_id,
        claim_revision_id=claim.revision_id,
        kol_id=claim.kol_id,
        instrument_id=claim.instrument_id,
        position=PositionDirection.LONG,
        time_horizon=PositionTimeHorizon.SWING,
        execution_semantics=ExecutionSemantics.NON_EXECUTABLE_POSITION_CLAIM,
        confidence_bps=claim.confidence_bps,
        review_status=claim.review_status,
        event_time=claim.event_time,
        publish_time=claim.publish_time,
        ingest_time=claim.ingest_time,
        processing_time=claim.processing_time,
        available_time=claim.available_time,
        source=claim.source,
        source_version=claim.source_version,
        deleted=False,
        deleted_at=None,
        deletion_reason=None,
    )
    assert (
        parse_kol_evidence_payload(to_contract(evidence).model_dump(by_alias=True, mode="json"))
        == evidence
    )
    assert (
        parse_kol_position_claim_payload(
            to_contract(position).model_dump(by_alias=True, mode="json")
        )
        == position
    )
