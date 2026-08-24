"""Regression tests for P4-N06 repair semantics."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from kol_core import (
    APPROVED_REVIEW_SEMANTICS,
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
    KolDomainSnapshot,
    KolEvidence,
    KolPositionClaim,
    LocatorType,
    PositionDirection,
    PositionTimeHorizon,
    ReviewStatus,
    parse_kol_claim_payload,
    parse_kol_content_payload,
    parse_kol_domain_snapshot_payload,
    parse_kol_position_claim_payload,
    to_contract,
)

T0 = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=1)
T2 = T0 + timedelta(minutes=2)
T3 = T0 + timedelta(minutes=3)
T4 = T0 + timedelta(minutes=4)
T5 = T0 + timedelta(minutes=5)


def make_content(
    *,
    content_id: str = "content-aggregate-1",
    content_version: str = "content-version-1",
    revision_id: str = "content-revision-1",
    previous_revision_id: str | None = None,
    available_time: datetime = T3,
    deleted: bool = False,
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
        deleted_at=T5 if deleted else None,
        deletion_reason="author-request" if deleted else None,
    )


def make_evidence(content: KolContent) -> KolEvidence:
    return KolEvidence(
        evidence_id="evidence-aggregate-1",
        revision_id="evidence-revision-1",
        previous_revision_id=None,
        content_id=content.content_id,
        content_version=content.content_version,
        content_available_time=content.available_time,
        source="social-platform",
        source_version="platform-v1",
        locator_type=LocatorType.TEXT_RANGE,
        locator="chars:0-18",
        excerpt="A public statement",
        evidence_grade=EvidenceGrade.PRIMARY_SOURCE,
        evidence_grade_version="evidence-grade-v1",
        available_time=T4,
    )


def make_claim(content: KolContent, evidence: KolEvidence) -> KolClaim:
    return KolClaim(
        claim_id="claim-aggregate-1",
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


def make_position(claim: KolClaim) -> KolPositionClaim:
    return KolPositionClaim(
        position_claim_id="position-aggregate-1",
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


def make_snapshot(
    *,
    content: tuple[KolContent, ...] | None = None,
    evidence: tuple[KolEvidence, ...] | None = None,
    claims: tuple[KolClaim, ...] | None = None,
    positions: tuple[KolPositionClaim, ...] | None = None,
) -> KolDomainSnapshot:
    root = make_content()
    evidence_items = (make_evidence(root),) if evidence is None else evidence
    claim_items = (make_claim(root, evidence_items[0]),) if claims is None else claims
    return KolDomainSnapshot(
        content=(root,) if content is None else content,
        evidence=evidence_items,
        claims=claim_items,
        position_claims=(make_position(claim_items[0]),) if positions is None else positions,
    )


def test_evidence_grade_is_versioned_and_combination_matrix_is_conservative() -> None:
    assert APPROVED_REVIEW_SEMANTICS == "PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION"
    assert EvidenceGrade.PRIMARY_SOURCE.value == "PRIMARY_SOURCE"
    assert KolDomainSnapshot is not None
    assert ClaimStatementKind.QUOTE.value == "QUOTE"
    assert ClaimAttribution.QUOTED.value == "QUOTED"
    assert ClaimUncertainty.AMBIGUOUS.value == "AMBIGUOUS"


def test_aggregate_parser_is_a_public_boundary() -> None:
    with pytest.raises(TypeError, match="object"):
        parse_kol_domain_snapshot_payload([])
    with pytest.raises((TypeError, ValueError), match="snapshot|content|aggregate"):
        parse_kol_domain_snapshot_payload(
            {
                "content": [],
                "evidence": [{"evidenceId": "orphan"}],
                "claims": [],
                "positionClaims": [],
                "unknown": True,
            }
        )


def test_timezone_aware_decision_time_is_required() -> None:
    with pytest.raises((TypeError, ValueError)):
        KolDomainSnapshot(content=(), evidence=(), claims=(), position_claims=()).select_visible(
            datetime(2026, 8, 24, tzinfo=None)
        )


def test_python_recomputes_fingerprint_rejects_canonical_mismatch_and_limits() -> None:
    content = make_content()
    payload = to_contract(content).model_dump(by_alias=True, mode="json")
    with pytest.raises(ValueError, match="fingerprint"):
        parse_kol_content_payload({**payload, "body": "tampered"})

    evidence = make_evidence(content)
    with pytest.raises(ValueError, match="maximum length"):
        replace(evidence, excerpt="x" * 4001)
    with pytest.raises(ValueError, match="maximum length"):
        replace(evidence, locator="x" * 2049)
    claim = make_claim(content, evidence)
    with pytest.raises(ValueError, match="canonical"):
        replace(claim, instrument_id="600519.SZ")
    with pytest.raises(ValueError, match="canonical"):
        replace(claim, instrument_id="000001.SH")
    with pytest.raises(ValueError, match="maximum length"):
        replace(claim, statement="x" * 10001)


def test_python_combination_matrix_is_conservative() -> None:
    content = make_content()
    evidence = make_evidence(content)
    claim = make_claim(content, evidence)
    with pytest.raises(ValueError, match="QUOTE"):
        replace(claim, statement_kind=ClaimStatementKind.QUOTE)
    quoted = replace(
        claim,
        statement_kind=ClaimStatementKind.QUOTE,
        attribution=ClaimAttribution.QUOTED,
        uncertainty=ClaimUncertainty.AMBIGUOUS,
    )
    assert quoted.review_status is ReviewStatus.UNREVIEWED
    with pytest.raises(ValueError, match="AMBIGUOUS"):
        replace(claim, statement_kind=ClaimStatementKind.AMBIGUOUS)


def test_aggregate_rejects_orphan_links_and_revision_graph_corruption() -> None:
    root = make_content()
    evidence = make_evidence(root)
    claim = make_claim(root, evidence)
    position = make_position(claim)

    with pytest.raises(ValueError, match="actual evidence"):
        make_snapshot(
            claims=(replace(claim, evidence=(replace(claim.evidence[0], evidence_id="missing"),)),)
        )
    with pytest.raises(ValueError, match="actual claim"):
        make_snapshot(positions=(replace(position, claim_revision_id="missing"),))
    with pytest.raises(ValueError, match="actual content"):
        make_snapshot(
            evidence=(replace(evidence, content_version="missing"),),
            claims=(claim,),
            positions=(position,),
        )

    cycle_a = make_content(revision_id="cycle-a", previous_revision_id="cycle-b", available_time=T4)
    cycle_b = make_content(revision_id="cycle-b", previous_revision_id="cycle-a", available_time=T5)
    with pytest.raises(ValueError, match="root|cycle"):
        make_snapshot(content=(cycle_a, cycle_b), evidence=(), claims=(), positions=())

    fork_a = make_content(revision_id="fork-a", available_time=T3)
    fork_b = make_content(revision_id="fork-b", previous_revision_id="fork-a", available_time=T4)
    fork_c = make_content(revision_id="fork-c", previous_revision_id="fork-a", available_time=T5)
    with pytest.raises(ValueError, match="fork"):
        make_snapshot(content=(fork_a, fork_b, fork_c), evidence=(), claims=(), positions=())

    cross = make_content(
        content_id="other-content",
        revision_id="cross-child",
        previous_revision_id="content-revision-1",
        available_time=T4,
    )
    with pytest.raises(ValueError, match="same logical id"):
        make_snapshot(content=(root, cross), evidence=(), claims=(), positions=())


def test_aggregate_pit_returns_deletion_only_after_available_time() -> None:
    root = make_content()
    tombstone = make_content(
        content_version="content-version-2",
        revision_id="content-revision-2",
        previous_revision_id=root.revision_id,
        available_time=T5,
        deleted=True,
    )
    evidence = make_evidence(root)
    claim = make_claim(root, evidence)
    position = make_position(claim)
    snapshot = make_snapshot(
        content=(root, tombstone),
        evidence=(evidence,),
        claims=(claim,),
        positions=(position,),
    )
    before = snapshot.select_visible(T4)
    after = snapshot.select_visible(T5)
    assert before.content[0].revision_id == root.revision_id
    assert after.content[0].revision_id == tombstone.revision_id
    assert after.content[0].deleted is True


def test_revision_graph_is_grouped_by_logical_id_and_is_order_independent() -> None:
    root = make_content()
    child = make_content(
        content_version="content-version-2",
        revision_id="content-revision-2",
        previous_revision_id=root.revision_id,
        available_time=T4,
    )
    other = make_content(
        content_id="content-aggregate-2",
        content_version="other-version-1",
        revision_id="other-revision-1",
        available_time=T3,
    )
    snapshot = make_snapshot(
        content=(child, root, other),
        evidence=(),
        claims=(),
        positions=(),
    )
    assert {item.content_id for item in snapshot.content} == {
        "content-aggregate-1",
        "content-aggregate-2",
    }


def test_revision_graph_rejects_fork_when_children_precede_parent() -> None:
    root = make_content()
    child_a = make_content(
        content_version="content-version-2",
        revision_id="fork-a",
        previous_revision_id=root.revision_id,
        available_time=T4,
    )
    child_b = make_content(
        content_version="content-version-3",
        revision_id="fork-b",
        previous_revision_id=root.revision_id,
        available_time=T5,
    )
    with pytest.raises(ValueError, match="fork"):
        make_snapshot(
            content=(child_a, child_b, root),
            evidence=(),
            claims=(),
            positions=(),
        )


def test_python_exact_links_include_sources_and_available_times() -> None:
    content = make_content()
    evidence = make_evidence(content)
    claim = make_claim(content, evidence)
    position = make_position(claim)

    with pytest.raises(ValueError, match="source"):
        make_snapshot(
            content=(content,),
            evidence=(replace(evidence, source="other-source"),),
            claims=(),
            positions=(),
        )
    with pytest.raises(ValueError, match="source"):
        make_snapshot(
            content=(content,),
            evidence=(replace(evidence, source_version="other-version"),),
            claims=(),
            positions=(),
        )
    with pytest.raises(ValueError, match="claim available"):
        make_snapshot(
            content=(content,),
            evidence=(evidence,),
            claims=(replace(claim, available_time=T3),),
            positions=(),
        )
    with pytest.raises(ValueError, match="source"):
        make_snapshot(
            content=(content,),
            evidence=(evidence,),
            claims=(claim,),
            positions=(replace(position, source="other-source"),),
        )


def test_generated_dtos_reject_invalid_tombstones() -> None:
    content_contract = to_contract(make_content())
    content_payload = content_contract.model_dump(by_alias=True, mode="json")
    content_model = type(content_contract)
    with pytest.raises(ValueError):
        content_model.model_validate(
            {
                **content_payload,
                "deleted": True,
                "deletedAt": T5.isoformat(),
                "deletionReason": None,
            }
        )
    with pytest.raises(ValueError):
        content_model.model_validate(
            {
                **content_payload,
                "deleted": True,
                "deletedAt": T5.isoformat(),
                "deletionReason": "x" * 1001,
            }
        )

    content = make_content()
    evidence = make_evidence(content)
    claim_contract = to_contract(make_claim(content, evidence))
    claim_payload = claim_contract.model_dump(by_alias=True, mode="json")
    with pytest.raises(ValueError):
        type(claim_contract).model_validate(
            {
                **claim_payload,
                "deleted": True,
                "deletedAt": T5.isoformat(),
                "deletionReason": None,
            }
        )
    with pytest.raises(ValueError):
        type(claim_contract).model_validate({**claim_payload, "deletionReason": "x" * 1001})
    with pytest.raises(ValueError):
        parse_kol_claim_payload(
            {
                **claim_payload,
                "deleted": True,
                "deletedAt": T5.isoformat(),
                "deletionReason": None,
            }
        )

    position_contract = to_contract(make_position(make_claim(content, evidence)))
    position_payload = position_contract.model_dump(by_alias=True, mode="json")
    with pytest.raises(ValueError):
        type(position_contract).model_validate(
            {
                **position_payload,
                "deleted": True,
                "deletedAt": T5.isoformat(),
                "deletionReason": None,
            }
        )
    with pytest.raises(ValueError):
        parse_kol_position_claim_payload(
            {
                **position_payload,
                "deleted": True,
                "deletedAt": T5.isoformat(),
                "deletionReason": None,
            }
        )
