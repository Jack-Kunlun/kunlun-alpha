from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from seat_core import Alias, AliasType, SeatKind, SeatProfile, compute_seat_id
from seat_core.resolution import (
    AliasResolutionRequest,
    NormalizationPolicy,
    ResolutionAuditLog,
    ResolutionPolicy,
    ResolutionResult,
    ResolutionStatus,
    ReviewDecision,
    ReviewOutcome,
    ReviewQueue,
    normalize_alias_name,
    resolve_alias,
)

T0 = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
T1 = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)
T2 = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
T3 = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)


def make_profile(
    identity_key: str,
    *,
    seat_kind: SeatKind = SeatKind.BROKER_BRANCH,
    valid_from: datetime = T0,
    valid_to: datetime | None = None,
    available_time: datetime = T0,
) -> SeatProfile:
    return SeatProfile.from_identity(
        identity_key,
        canonical_name=identity_key,
        seat_kind=seat_kind,
        valid_from=valid_from,
        valid_to=valid_to,
        available_time=available_time,
        revision_id=f"{identity_key}-profile-rev-1",
        source="seat-master",
        source_version="2026-08",
        evidence_id=f"evidence-{identity_key}",
    )


def make_alias(
    alias_id: str,
    seat_id: str,
    name: str,
    *,
    valid_from: datetime = T0,
    valid_to: datetime | None = None,
    available_time: datetime = T0,
) -> Alias:
    return Alias(
        alias_id=alias_id,
        seat_id=seat_id,
        name=name,
        alias_type=AliasType.SOURCE,
        valid_from=valid_from,
        valid_to=valid_to,
        available_time=available_time,
        source="vendor-seat-feed",
        source_version="2026-08",
        evidence_id=f"evidence-{alias_id}",
        revision_id=f"{alias_id}-rev-1",
    )


def request(
    request_id: str,
    raw_name: str,
    *,
    decision_time: datetime = T2,
    seat_kind_hint: SeatKind | None = SeatKind.BROKER_BRANCH,
    source: str = "vendor-seat-feed",
    source_version: str = "2026-08",
    evidence_id: str | None = None,
) -> AliasResolutionRequest:
    return AliasResolutionRequest(
        request_id=request_id,
        raw_name=raw_name,
        decision_time=decision_time,
        source=source,
        source_version=source_version,
        evidence_id=evidence_id or f"input-{request_id}",
        seat_kind_hint=seat_kind_hint,
    )


def test_normalization_is_versioned_and_handles_width_case_space_and_suffix() -> None:
    policy = NormalizationPolicy()

    assert (
        normalize_alias_name("  ＡＬＰＨＡ　Ｓｅｃｕｒｉｔｉｅｓ证券营业部  ", policy)
        == "alphasecurities"
    )
    assert policy.version == "seat-normalization-v1"


def test_policy_floors_versions_and_fingerprint_all_configuration() -> None:
    for threshold in (Decimal("0"), Decimal("0.8999")):
        with pytest.raises(ValueError, match="auto_score_threshold"):
            ResolutionPolicy(auto_score_threshold=threshold)
    for margin in (Decimal("0"), Decimal("0.0499")):
        with pytest.raises(ValueError, match="minimum_margin"):
            ResolutionPolicy(minimum_margin=margin)
    with pytest.raises(ValueError, match="version"):
        NormalizationPolicy(version="seat-normalization-v2")
    with pytest.raises(ValueError, match="algorithm_version"):
        ResolutionPolicy(algorithm_version="seat-resolution-v2")

    default = ResolutionPolicy()
    stricter = ResolutionPolicy(auto_score_threshold=Decimal("0.9500"))
    wider_margin = ResolutionPolicy(minimum_margin=Decimal("0.1000"))
    stricter_accuracy = ResolutionPolicy(golden_accuracy_threshold=Decimal("1.0000"))
    normalization_changed = ResolutionPolicy(
        normalization_policy=NormalizationPolicy(strip_common_suffixes=("营业部",))
    )
    assert default.policy_fingerprint != stricter.policy_fingerprint
    assert default.policy_fingerprint != wider_margin.policy_fingerprint
    assert default.policy_fingerprint != stricter_accuracy.policy_fingerprint
    assert default.policy_fingerprint != normalization_changed.policy_fingerprint


def test_exact_alias_and_name_change_auto_resolve_without_using_display_name_as_id() -> None:
    profile = make_profile("broker:alpha-001")
    seat_id = profile.seat_id
    aliases = (
        make_alias("alpha-old", seat_id, "Alpha Securities营业部", valid_to=T1),
        make_alias("alpha-new", seat_id, "Alpha Securities营业厅", valid_from=T1),
    )

    result = resolve_alias(
        request("req-alpha", "ＡＬＰＨＡ　ＳＥＣＵＲＩＴＩＥＳ营业厅"),
        profiles=(profile,),
        aliases=aliases,
    )

    assert result.status is ResolutionStatus.AUTO
    assert result.selected_seat_id == seat_id
    assert result.candidates[0].score == Decimal("1.0000")
    assert "normalized_exact" in result.candidates[0].rule_hits
    assert [item.alias_id for item in result.candidates[0].evidence] == ["alpha-new"]
    assert result.algorithm_version == "seat-resolution-v1"
    assert result.policy_version == "seat-resolution-policy-v1"


def test_institution_match_can_auto_resolve_but_type_conflict_requires_review() -> None:
    profile = make_profile("exchange:institution-001", seat_kind=SeatKind.INSTITUTION)
    alias = make_alias("institution-1", profile.seat_id, "Institution Desk")

    exact = resolve_alias(
        request("req-institution", "Institution Desk", seat_kind_hint=SeatKind.INSTITUTION),
        profiles=(profile,),
        aliases=(alias,),
    )
    conflict = resolve_alias(
        request("req-institution-conflict", "Institution Desk"),
        profiles=(profile,),
        aliases=(alias,),
    )

    assert exact.status is ResolutionStatus.AUTO
    assert conflict.status is ResolutionStatus.REVIEW
    assert conflict.selected_seat_id is None
    assert conflict.candidates[0].type_conflict


def test_missing_seat_kind_hint_cannot_auto_resolve_exact_alias() -> None:
    profile = make_profile("broker:alpha-001")
    alias = make_alias("alpha-1", profile.seat_id, "Alpha Securities营业部")

    result = resolve_alias(
        request("req-missing-hint", "Alpha Securities营业部", seat_kind_hint=None),
        profiles=(profile,),
        aliases=(alias,),
    )

    assert result.status is ResolutionStatus.REVIEW
    assert result.selected_seat_id is None
    assert "missing_seat_kind_hint" in result.reason


def test_forged_auto_result_violates_resolution_invariants() -> None:
    profile = make_profile("broker:alpha-001")
    alias = make_alias("alpha-1", profile.seat_id, "Alpha Securities营业部")
    result = resolve_alias(
        request("req-forged-auto", "Alpha Securities营业部"),
        profiles=(profile,),
        aliases=(alias,),
    )
    assert result.status is ResolutionStatus.AUTO

    with pytest.raises(ValueError, match="AUTO"):
        replace(result, selected_seat_id=None)
    with pytest.raises(ValueError, match="AUTO"):
        replace(result, confidence=Decimal("0.8000"))
    with pytest.raises(ValueError, match="AUTO|fingerprint"):
        replace(result, seat_kind_hint=None)


def test_unknown_seat_and_low_confidence_name_never_auto_merge() -> None:
    unknown_profile = make_profile("source:unknown:row-001", seat_kind=SeatKind.UNKNOWN)
    unknown_alias = make_alias("unknown-1", unknown_profile.seat_id, "Unknown Seat")

    known_unknown = resolve_alias(
        request("req-unknown-seat", "Unknown Seat", seat_kind_hint=SeatKind.UNKNOWN),
        profiles=(unknown_profile,),
        aliases=(unknown_alias,),
    )
    no_candidate = resolve_alias(
        request("req-unknown-name", "No Such Seat"),
        profiles=(unknown_profile,),
        aliases=(unknown_alias,),
    )

    assert known_unknown.status is ResolutionStatus.REVIEW
    assert known_unknown.selected_seat_id is None
    assert no_candidate.status is ResolutionStatus.REVIEW
    assert no_candidate.selected_seat_id is None
    assert "low_confidence" in no_candidate.reason


def test_ambiguity_near_match_and_type_conflict_fail_to_review() -> None:
    alpha = make_profile("broker:alpha-001")
    beta = make_profile("broker:beta-002")
    aliases = (
        make_alias("alpha-1", alpha.seat_id, "Shared Securities营业部"),
        make_alias("beta-1", beta.seat_id, "Shared Securities营业部"),
    )

    ambiguous = resolve_alias(
        request("req-ambiguous", "Shared Securities营业部"),
        profiles=(alpha, beta),
        aliases=aliases,
    )
    low_confidence = resolve_alias(
        request("req-low-confidence", "Shared"),
        profiles=(alpha,),
        aliases=(aliases[0],),
    )

    assert ambiguous.status is ResolutionStatus.REVIEW
    assert ambiguous.selected_seat_id is None
    assert ambiguous.candidates[0].score == ambiguous.candidates[1].score
    assert low_confidence.status is ResolutionStatus.REVIEW
    assert low_confidence.selected_seat_id is None


def test_future_and_expired_aliases_are_excluded_at_decision_time() -> None:
    profile = make_profile("broker:alpha-001")
    future = make_alias("future", profile.seat_id, "Future Branch", available_time=T3)
    expired = make_alias("expired", profile.seat_id, "Expired Branch", valid_to=T1)

    future_result = resolve_alias(
        request("req-future", "Future Branch", decision_time=T2),
        profiles=(profile,),
        aliases=(future,),
    )
    expired_result = resolve_alias(
        request("req-expired", "Expired Branch", decision_time=T2),
        profiles=(profile,),
        aliases=(expired,),
    )

    assert future_result.status is ResolutionStatus.REJECT
    assert expired_result.status is ResolutionStatus.REJECT

    future_profile = make_profile("broker:future-profile-001", available_time=T3)
    expired_profile = make_profile("broker:expired-profile-001", valid_to=T1)
    assert (
        resolve_alias(
            request("req-future-profile", "Future Profile Branch"),
            profiles=(future_profile,),
            aliases=(
                make_alias("future-profile", future_profile.seat_id, "Future Profile Branch"),
            ),
        ).status
        is ResolutionStatus.REJECT
    )
    assert (
        resolve_alias(
            request("req-expired-profile", "Expired Profile Branch"),
            profiles=(expired_profile,),
            aliases=(
                make_alias("expired-profile", expired_profile.seat_id, "Expired Profile Branch"),
            ),
        ).status
        is ResolutionStatus.REJECT
    )


def test_golden_samples_meet_documented_accuracy_threshold_and_are_deterministic() -> None:
    alpha = make_profile("broker:alpha-001")
    beta = make_profile("broker:beta-002")
    institution = make_profile("exchange:institution-001", seat_kind=SeatKind.INSTITUTION)
    profiles = (alpha, beta, institution)
    aliases = (
        make_alias("alpha-1", alpha.seat_id, "Alpha Securities营业部"),
        make_alias("beta-1", beta.seat_id, "Beta Capital营业厅"),
        make_alias("institution-1", institution.seat_id, "Institution Desk"),
    )
    samples = (
        ("ＡＬＰＨＡ　ＳＥＣＵＲＩＴＩＥＳ营业部", alpha.seat_id, SeatKind.BROKER_BRANCH),
        ("beta capital营业厅", beta.seat_id, SeatKind.BROKER_BRANCH),
        ("Institution Desk", institution.seat_id, SeatKind.INSTITUTION),
    )
    policy = ResolutionPolicy()
    results = tuple(
        resolve_alias(
            request(f"golden-{index}", raw_name, seat_kind_hint=seat_kind),
            profiles=profiles,
            aliases=aliases,
            policy=policy,
        )
        for index, (raw_name, _, seat_kind) in enumerate(samples)
    )

    correct = sum(
        result.status is ResolutionStatus.AUTO and result.selected_seat_id == expected_seat_id
        for result, (_, expected_seat_id, _) in zip(results, samples, strict=True)
    )
    accuracy = Decimal(correct) / Decimal(len(samples))

    assert accuracy >= policy.golden_accuracy_threshold
    assert results == tuple(
        resolve_alias(
            request(f"golden-{index}", raw_name, seat_kind_hint=seat_kind),
            profiles=profiles,
            aliases=aliases,
            policy=policy,
        )
        for index, (raw_name, _, seat_kind) in enumerate(samples)
    )


def test_review_queue_and_audit_log_are_immutable_idempotent_and_conflict_safe() -> None:
    profile = make_profile("broker:alpha-001")
    alias = make_alias("alpha-1", profile.seat_id, "Alpha Securities营业部")
    result = resolve_alias(
        request("req-review", "Alpha"),
        profiles=(profile,),
        aliases=(alias,),
    )
    assert result.status is ResolutionStatus.REVIEW

    queue = ReviewQueue()
    queued = queue.enqueue(result)
    assert queue.items == ()
    assert queued.enqueue(result) == queued
    with pytest.raises(ValueError, match="request_id"):
        queued.enqueue(
            resolve_alias(
                request("req-review", "Alpha", source="different-source"),
                profiles=(profile,),
                aliases=(alias,),
            )
        )
    with pytest.raises(ValueError, match="candidate"):
        queued.record_decision(
            ReviewDecision(
                request_id=result.request_id,
                outcome=ReviewOutcome.APPROVE,
                seat_id=compute_seat_id("broker:not-a-candidate"),
                reviewer="sol",
                reviewed_at=T3,
                reason="wrong candidate regression",
                algorithm_version=result.algorithm_version,
                policy_version=result.policy_version,
                policy_fingerprint=result.policy_fingerprint,
                request_fingerprint=result.request_fingerprint,
                resolution_fingerprint=result.resolution_fingerprint,
                input_name=result.raw_name,
                input_evidence_ids=result.input_evidence_ids,
                review_evidence_ids=("review-evidence-wrong-seat",),
            )
        )

    decision = ReviewDecision(
        request_id=result.request_id,
        outcome=ReviewOutcome.APPROVE,
        seat_id=profile.seat_id,
        reviewer="sol",
        reviewed_at=T3,
        reason="verified against institution source",
        algorithm_version=result.algorithm_version,
        policy_version=result.policy_version,
        policy_fingerprint=result.policy_fingerprint,
        request_fingerprint=result.request_fingerprint,
        resolution_fingerprint=result.resolution_fingerprint,
        input_name=result.raw_name,
        input_evidence_ids=result.input_evidence_ids,
        review_evidence_ids=("review-evidence-1",),
    )
    decided = queued.record_decision(decision)
    assert decided.record_decision(decision) == decided
    with pytest.raises(ValueError, match="request_id"):
        decided.record_decision(replace(decision, reason="conflicting review"))

    reject_result = resolve_alias(
        request("req-review-reject", "Alpha"),
        profiles=(profile,),
        aliases=(alias,),
    )
    reject_queue = ReviewQueue().enqueue(reject_result)
    reject_decision = ReviewDecision(
        request_id=reject_result.request_id,
        outcome=ReviewOutcome.REJECT,
        seat_id=None,
        reviewer="sol",
        reviewed_at=T3,
        reason="insufficient independent evidence",
        algorithm_version=reject_result.algorithm_version,
        policy_version=reject_result.policy_version,
        policy_fingerprint=reject_result.policy_fingerprint,
        request_fingerprint=reject_result.request_fingerprint,
        resolution_fingerprint=reject_result.resolution_fingerprint,
        input_name=reject_result.raw_name,
        input_evidence_ids=reject_result.input_evidence_ids,
        review_evidence_ids=("review-evidence-reject-1",),
    )
    assert reject_queue.record_decision(reject_decision).decisions == (reject_decision,)

    log = ResolutionAuditLog().record_resolution(result).record_review(decision)
    assert log.record_resolution(result) == log
    assert log.record_review(decision) == log
    with pytest.raises(ValueError, match="request_id"):
        log.record_resolution(
            resolve_alias(
                request("req-review", "Alpha", source_version="different-version"),
                profiles=(profile,),
                aliases=(alias,),
            )
        )


def test_request_fingerprint_covers_all_request_identity_fields_and_policy_fingerprint() -> None:
    profile = make_profile("broker:alpha-001")
    alias = make_alias("alpha-1", profile.seat_id, "Alpha Securities营业部")
    base = resolve_alias(
        request("req-fingerprint", "Alpha", evidence_id="input-a"),
        profiles=(profile,),
        aliases=(alias,),
    )
    queue = ReviewQueue().enqueue(base)

    variants = (
        request("req-fingerprint", "Alpha", source="source-b", evidence_id="input-a"),
        request("req-fingerprint", "Alpha", source_version="version-b", evidence_id="input-a"),
        request("req-fingerprint", "Alpha", decision_time=T3, evidence_id="input-a"),
        request(
            "req-fingerprint",
            "Alpha",
            seat_kind_hint=SeatKind.INSTITUTION,
            evidence_id="input-a",
        ),
        request("req-fingerprint", "Alpha", evidence_id="input-b"),
    )
    for variant in variants:
        changed = resolve_alias(variant, profiles=(profile,), aliases=(alias,))
        assert changed.request_fingerprint != base.request_fingerprint
        with pytest.raises(ValueError, match="request_id"):
            queue.enqueue(changed)

    stricter = resolve_alias(
        request("req-fingerprint", "Alpha", evidence_id="input-a"),
        profiles=(profile,),
        aliases=(alias,),
        policy=ResolutionPolicy(auto_score_threshold=Decimal("0.9500")),
    )
    assert stricter.policy_fingerprint != base.policy_fingerprint
    with pytest.raises(ValueError, match="request_id"):
        queue.enqueue(stricter)


def test_review_requires_existing_matching_resolution_and_separate_review_evidence() -> None:
    profile = make_profile("broker:alpha-001")
    alias = make_alias("alpha-1", profile.seat_id, "Alpha Securities营业部")
    result = resolve_alias(request("req-audit", "Alpha"), profiles=(profile,), aliases=(alias,))
    decision = ReviewDecision(
        request_id=result.request_id,
        outcome=ReviewOutcome.REJECT,
        seat_id=None,
        reviewer="sol",
        reviewed_at=T3,
        reason="no independent confirmation",
        algorithm_version=result.algorithm_version,
        policy_version=result.policy_version,
        policy_fingerprint=result.policy_fingerprint,
        request_fingerprint=result.request_fingerprint,
        resolution_fingerprint=result.resolution_fingerprint,
        input_name=result.raw_name,
        input_evidence_ids=result.input_evidence_ids,
        review_evidence_ids=("manual-evidence-1", "manual-evidence-2"),
    )
    with pytest.raises(ValueError, match="orphan"):
        ResolutionAuditLog().record_review(decision)

    log = ResolutionAuditLog().record_resolution(result)
    with pytest.raises(ValueError, match="fingerprint"):
        log.record_review(replace(decision, resolution_fingerprint="resolution-wrong"))
    with pytest.raises(ValueError, match="input"):
        log.record_review(replace(decision, input_name="different-input"))
    assert log.record_review(decision).entries[-1] == decision

    with pytest.raises(ValueError, match="independent|separate"):
        replace(decision, review_evidence_ids=result.input_evidence_ids)


def test_versioned_golden_fixture_has_twenty_samples_and_safe_auto_accuracy() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "golden-v1.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["fixture_version"] == "seat-resolution-golden-v1"
    assert fixture["sample_count"] == 20
    assert len(fixture["samples"]) == fixture["sample_count"]
    policy = ResolutionPolicy()
    assert fixture["policy_version"] == policy.version
    assert fixture["normalization_policy_version"] == policy.normalization_policy.version

    profiles = (
        make_profile("broker:alpha-001"),
        make_profile("broker:beta-002"),
        make_profile("broker:gamma-003"),
        make_profile("exchange:institution-001", seat_kind=SeatKind.INSTITUTION),
        make_profile("source:unknown:row-001", seat_kind=SeatKind.UNKNOWN),
        make_profile("broker:collision-a-001"),
        make_profile("broker:collision-b-002"),
        make_profile("broker:future-profile-001", available_time=T3),
        make_profile("broker:expired-profile-001", valid_to=T1),
    )
    aliases = (
        make_alias(
            "alpha-main",
            profiles[0].seat_id,
            "Alpha Securities营业部",
            valid_to=T1,
        ),
        make_alias(
            "alpha-former",
            profiles[0].seat_id,
            "Alpha Former营业部",
            valid_to=T1,
        ),
        make_alias("alpha-new", profiles[0].seat_id, "Alpha Securities营业厅", valid_from=T1),
        make_alias("beta-main", profiles[1].seat_id, "Beta Capital营业厅"),
        make_alias("gamma-main", profiles[2].seat_id, "Gamma Securities营业部"),
        make_alias("institution-main", profiles[3].seat_id, "Institution Desk"),
        make_alias("unknown-main", profiles[4].seat_id, "Unknown Seat"),
        make_alias("collision-a", profiles[5].seat_id, "Shared Securities营业部"),
        make_alias("collision-b", profiles[6].seat_id, "Shared Securities营业部"),
        make_alias("future-alias", profiles[0].seat_id, "Future Branch", available_time=T3),
        make_alias("expired-alias", profiles[0].seat_id, "Expired Branch", valid_to=T1),
        make_alias("future-profile-alias", profiles[7].seat_id, "Future Profile Branch"),
        make_alias("expired-profile-alias", profiles[8].seat_id, "Expired Profile Branch"),
    )

    results: list[ResolutionResult] = []
    for sample in fixture["samples"]:
        hint = sample.get("seat_kind_hint")
        result = resolve_alias(
            request(
                sample["id"],
                sample["raw_name"],
                decision_time=datetime.fromisoformat(sample["decision_time"]),
                seat_kind_hint=None if hint is None else SeatKind(hint),
            ),
            profiles=profiles,
            aliases=aliases,
            policy=policy,
        )
        results.append(result)
        assert result.status.value == sample["expected_status"]
        expected_identity = sample.get("expected_identity_key")
        if expected_identity is not None:
            expected_seat_id = compute_seat_id(expected_identity)
            assert result.candidates[0].seat_id == expected_seat_id
            if sample["expected_status"] == "AUTO":
                assert result.selected_seat_id == expected_seat_id
        if sample["expected_status"] != "AUTO":
            assert result.status is not ResolutionStatus.AUTO

    correct: int = 0
    for result, sample in zip(results, fixture["samples"], strict=True):
        matches = result.status.value == sample["expected_status"]
        expected_identity = sample.get("expected_identity_key")
        if matches and expected_identity is not None:
            expected_seat_id = compute_seat_id(expected_identity)
            matches = bool(result.candidates) and result.candidates[0].seat_id == expected_seat_id
            if sample["expected_status"] == "AUTO":
                matches = matches and result.selected_seat_id == expected_seat_id
        if matches:
            correct += 1
    accuracy = Decimal(correct) / Decimal(fixture["sample_count"])
    assert accuracy >= policy.golden_accuracy_threshold


def test_audit_log_reuses_review_validation_for_status_candidate_and_fingerprint() -> None:
    profile = make_profile("broker:alpha-001")
    alias = make_alias("alpha-1", profile.seat_id, "Alpha Securities营业部")

    def decision_for(
        result: ResolutionResult,
        *,
        outcome: ReviewOutcome,
        seat_id: str | None,
    ) -> ReviewDecision:
        return ReviewDecision(
            request_id=result.request_id,
            outcome=outcome,
            seat_id=seat_id,
            reviewer="sol",
            reviewed_at=T3,
            reason="direct audit regression",
            algorithm_version=result.algorithm_version,
            policy_version=result.policy_version,
            policy_fingerprint=result.policy_fingerprint,
            request_fingerprint=result.request_fingerprint,
            resolution_fingerprint=result.resolution_fingerprint,
            input_name=result.raw_name,
            input_evidence_ids=result.input_evidence_ids,
            review_evidence_ids=(f"review-{result.request_id}",),
        )

    review = resolve_alias(request("audit-review", "Alpha"), profiles=(profile,), aliases=(alias,))
    audit = ResolutionAuditLog().record_resolution(review)
    with pytest.raises(ValueError, match="candidate"):
        audit.record_review(
            replace(
                decision_for(review, outcome=ReviewOutcome.APPROVE, seat_id=profile.seat_id),
                seat_id=compute_seat_id("broker:not-a-candidate"),
            )
        )
    with pytest.raises(ValueError, match="fingerprint"):
        audit.record_review(
            replace(
                decision_for(review, outcome=ReviewOutcome.REJECT, seat_id=None),
                resolution_fingerprint="resolution-wrong",
            )
        )

    auto = resolve_alias(
        request("audit-auto", "Alpha Securities营业部"),
        profiles=(profile,),
        aliases=(alias,),
    )
    with pytest.raises(ValueError, match="REVIEW"):
        ResolutionAuditLog().record_resolution(auto).record_review(
            decision_for(auto, outcome=ReviewOutcome.REJECT, seat_id=None)
        )

    rejected = resolve_alias(request("audit-reject", "No Candidate"), profiles=(), aliases=())
    assert rejected.status is ResolutionStatus.REJECT
    with pytest.raises(ValueError, match="REVIEW"):
        ResolutionAuditLog().record_resolution(rejected).record_review(
            decision_for(rejected, outcome=ReviewOutcome.REJECT, seat_id=None)
        )
