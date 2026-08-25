"""P4-N09 KOL feature aggregation tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from feature_core.kol import (
    FeatureStatus,
    KolFeatureBundle,
    KolFeatureInputError,
    KolFeatureName,
    KolFeaturePolicy,
    KolFeatureValue,
    compute_kol_features,
)
from kol_core import (
    ClaimAttribution,
    ClaimDirection,
    ClaimEvidenceReference,
    ClaimStatementKind,
    ClaimUncertainty,
    KolClaim,
    ReviewStatus,
)
from kol_core.performance import (
    ClaimPerformancePolicy,
    TradablePriceObservation,
    TradingCalendarSnapshot,
    TradingSession,
)

T0 = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)


def _claim(
    kol_id: str,
    claim_id: str,
    direction: ClaimDirection,
    *,
    confidence_bps: int = 8000,
    available_time: datetime = T0,
    revision_id: str | None = None,
    previous_revision_id: str | None = None,
    deleted: bool = False,
    deleted_at: datetime | None = None,
    source: str = "claim-source",
    review_status: ReviewStatus = ReviewStatus.APPROVED,
) -> KolClaim:
    revision = revision_id or f"{claim_id}-r1"
    content_time = available_time - timedelta(minutes=2)
    evidence_time = available_time - timedelta(minutes=1)
    return KolClaim(
        claim_id=claim_id,
        revision_id=revision,
        previous_revision_id=previous_revision_id,
        content_id=f"content-{claim_id}",
        content_version=f"content-version-{revision}",
        content_available_time=content_time,
        kol_id=kol_id,
        statement=f"{kol_id} public statement",
        statement_kind=ClaimStatementKind.DIRECT,
        instrument_id="600519.SH",
        direction=direction,
        attribution=ClaimAttribution.SELF,
        uncertainty=ClaimUncertainty.NONE,
        confidence_bps=confidence_bps,
        review_status=review_status,
        event_time=available_time - timedelta(minutes=4),
        publish_time=available_time - timedelta(minutes=4),
        ingest_time=available_time - timedelta(minutes=3),
        processing_time=available_time - timedelta(minutes=2),
        available_time=available_time,
        source=source,
        source_version="v1",
        evidence=(
            ClaimEvidenceReference(
                evidence_id=f"evidence-{revision}",
                evidence_revision_id=f"evidence-revision-{revision}",
                content_id=f"content-{claim_id}",
                content_version=f"content-version-{revision}",
                content_available_time=content_time,
                evidence_available_time=evidence_time,
                source=source,
                source_version="v1",
            ),
        ),
        deleted=deleted,
        deleted_at=deleted_at,
        deletion_reason="source-deleted" if deleted else None,
    )


def _prices(
    values: tuple[str, ...] = ("100", "110", "120", "130"),
) -> list[TradablePriceObservation]:
    observations: list[TradablePriceObservation] = []
    for day, value in enumerate(values):
        event_time = T0 + timedelta(days=day)
        observations.append(
            TradablePriceObservation(
                instrument_id="600519.SH",
                trade_date=date(2026, 8, 1) + timedelta(days=day),
                event_time=event_time,
                price=Decimal(value),
                available_time=event_time + timedelta(minutes=5),
                suspended=False,
                source="market-source",
                source_version="v1",
                data_version="bars-v1",
                raw_capture_id=f"capture-{day}",
                revision_id=f"bar-r{day}",
            )
        )
    return observations


def _calendar(
    *,
    start_day: int = -2,
    end_day: int = 12,
) -> tuple[TradingCalendarSnapshot, ...]:
    return (
        TradingCalendarSnapshot(
            market="SH",
            coverage_start_time=T0 + timedelta(days=start_day, hours=-1),
            coverage_end_time=T0 + timedelta(days=end_day, hours=1),
            sessions=tuple(
                TradingSession(
                    trade_date=date(2026, 8, 1) + timedelta(days=day),
                    close_time=T0 + timedelta(days=day),
                )
                for day in range(start_day, end_day + 1)
            ),
            available_time=T0 - timedelta(days=10),
            source="calendar-source",
            source_version="v1",
            data_version="calendar-v1",
            snapshot_id="calendar-sh-v1",
        ),
    )


def _feature(
    bundle: KolFeatureBundle,
    name: KolFeatureName,
    entity_id: str,
) -> KolFeatureValue:
    return next(
        item
        for item in bundle.features
        if item.feature_name is name and item.entity_id == entity_id
    )


def test_attention_consensus_and_claim_score_are_versioned_and_auditable() -> None:
    claims = [
        _claim("kol-1", "claim-1", ClaimDirection.BULLISH),
        _claim("kol-2", "claim-2", ClaimDirection.BULLISH, confidence_bps=9000),
        _claim("kol-3", "claim-3", ClaimDirection.BEARISH, confidence_bps=6000),
    ]
    policy = KolFeaturePolicy(
        high_grade_confidence_bps=7000,
        performance_policy=ClaimPerformancePolicy(horizons=(1,)),
    )
    bundle = compute_kol_features(
        claims,
        _prices(),
        _calendar(),
        T0 + timedelta(days=4),
        policy,
    )

    attention = _feature(bundle, KolFeatureName.KOL_ATTENTION_SCORE, "kol-1")
    consensus = _feature(bundle, KolFeatureName.CONSENSUS_SCORE, "600519.SH")
    claim_score = _feature(
        bundle,
        KolFeatureName.CLAIM_SCORE,
        "claim-source:claim-1:claim-1-r1",
    )
    assert attention.value_bps is not None and attention.value_bps > 0
    assert consensus.status is FeatureStatus.PUBLISHED
    assert consensus.sample_count == 2
    assert consensus.value_bps == 10000
    assert claim_score.value_bps is not None
    assert claim_score.high_grade is True
    assert bundle.policy_fingerprint == policy.fingerprint
    assert bundle.data_cutoff_time is not None
    assert all(item.input_claims for item in bundle.features)
    assert all(item.input_fingerprint.startswith("sha256:") for item in bundle.features)


def test_low_confidence_claim_never_enters_high_grade_consensus() -> None:
    claims = [
        _claim("kol-1", "claim-1", ClaimDirection.BULLISH, confidence_bps=9000),
        _claim("kol-low", "claim-low", ClaimDirection.BEARISH, confidence_bps=2000),
    ]
    policy = KolFeaturePolicy(
        high_grade_confidence_bps=7000,
        performance_policy=ClaimPerformancePolicy(horizons=(1,)),
    )
    bundle = compute_kol_features(
        claims,
        _prices(),
        _calendar(),
        T0 + timedelta(days=4),
        policy,
    )
    consensus = _feature(bundle, KolFeatureName.CONSENSUS_SCORE, "600519.SH")
    low_score = _feature(
        bundle,
        KolFeatureName.CLAIM_SCORE,
        "claim-source:claim-low:claim-low-r1",
    )
    assert consensus.status is FeatureStatus.INSUFFICIENT_SAMPLES
    assert consensus.sample_count == 1
    assert consensus.value_bps is None
    assert consensus.high_grade is False
    assert low_score.high_grade is False


def test_tombstone_removes_attention_and_consensus_without_erasing_claim_score() -> None:
    root = _claim("kol-1", "claim-1", ClaimDirection.BULLISH)
    tombstone = _claim(
        "kol-1",
        "claim-1",
        ClaimDirection.BULLISH,
        revision_id="claim-1-deleted",
        previous_revision_id=root.revision_id,
        available_time=T0 + timedelta(days=1),
        deleted=True,
        deleted_at=T0 + timedelta(days=2),
    )
    policy = KolFeaturePolicy(
        minimum_consensus_kols=1,
        performance_policy=ClaimPerformancePolicy(horizons=(1,)),
    )
    bundle = compute_kol_features(
        [root, tombstone],
        _prices(),
        _calendar(),
        T0 + timedelta(days=4),
        policy,
    )
    names = {(item.feature_name, item.entity_id) for item in bundle.features}
    assert (KolFeatureName.KOL_ATTENTION_SCORE, "kol-1") not in names
    assert (KolFeatureName.CONSENSUS_SCORE, "600519.SH") not in names
    claim_score = _feature(
        bundle,
        KolFeatureName.CLAIM_SCORE,
        "claim-source:claim-1:claim-1-r1",
    )
    assert claim_score.status is FeatureStatus.PUBLISHED
    assert bundle.performance.samples[0].withdrawn_at == tombstone.deleted_at
    assert bundle.data_cutoff_time == tombstone.deleted_at


def test_future_revision_does_not_change_historical_feature_snapshot() -> None:
    root = _claim("kol-1", "claim-1", ClaimDirection.BULLISH)
    future = _claim(
        "kol-1",
        "claim-1",
        ClaimDirection.BEARISH,
        revision_id="claim-1-r2",
        previous_revision_id=root.revision_id,
        available_time=T0 + timedelta(days=3),
    )
    policy = KolFeaturePolicy(
        minimum_consensus_kols=1,
        performance_policy=ClaimPerformancePolicy(horizons=(1,)),
    )
    historical = compute_kol_features(
        [root, future],
        _prices(),
        _calendar(),
        T0 + timedelta(days=2),
        policy,
    )
    consensus = _feature(historical, KolFeatureName.CONSENSUS_SCORE, "600519.SH")
    assert consensus.value_bps == 10000
    assert tuple(item.revision_id for item in consensus.input_claims) == (root.revision_id,)
    assert [item.claim_revision_id for item in historical.performance.samples] == [root.revision_id]


def test_zero_total_confidence_consensus_is_not_published() -> None:
    claim = _claim(
        "kol-zero",
        "claim-zero",
        ClaimDirection.BULLISH,
        confidence_bps=0,
    )
    policy = KolFeaturePolicy(
        minimum_consensus_kols=1,
        high_grade_confidence_bps=0,
        performance_policy=ClaimPerformancePolicy(horizons=(1,)),
    )
    bundle = compute_kol_features(
        [claim],
        _prices(),
        _calendar(),
        T0 + timedelta(days=4),
        policy,
    )
    consensus = _feature(bundle, KolFeatureName.CONSENSUS_SCORE, "600519.SH")
    assert consensus.status is FeatureStatus.INSUFFICIENT_SAMPLES
    assert consensus.sample_count == 1
    assert consensus.value_bps is None
    assert consensus.high_grade is False


def test_simultaneous_claims_for_one_kol_and_instrument_fail_closed() -> None:
    bullish = _claim("kol-tie", "claim-a", ClaimDirection.BULLISH)
    bearish = _claim("kol-tie", "claim-b", ClaimDirection.BEARISH)
    policy = KolFeaturePolicy(
        minimum_consensus_kols=1,
        performance_policy=ClaimPerformancePolicy(horizons=(1,)),
    )
    with pytest.raises(KolFeatureInputError, match="simultaneous Claims"):
        compute_kol_features(
            [bullish, bearish],
            _prices(),
            _calendar(),
            T0 + timedelta(days=4),
            policy,
        )


def test_structured_claim_references_disambiguate_shared_revision_ids() -> None:
    claims = [
        _claim(
            "kol-1",
            "claim-1",
            ClaimDirection.BULLISH,
            revision_id="shared-r1",
            source="source-a",
        ),
        _claim(
            "kol-2",
            "claim-2",
            ClaimDirection.BULLISH,
            revision_id="shared-r1",
            source="source-b",
        ),
    ]
    policy = KolFeaturePolicy(
        minimum_consensus_kols=2,
        performance_policy=ClaimPerformancePolicy(horizons=(1,)),
    )
    bundle = compute_kol_features(
        claims,
        _prices(),
        _calendar(),
        T0 + timedelta(days=4),
        policy,
    )
    consensus = _feature(bundle, KolFeatureName.CONSENSUS_SCORE, "600519.SH")
    assert {(item.source, item.claim_id, item.revision_id) for item in consensus.input_claims} == {
        ("source-a", "claim-1", "shared-r1"),
        ("source-b", "claim-2", "shared-r1"),
    }
    assert consensus.input_fingerprint.startswith("sha256:")


def test_exact_attention_bearish_consensus_and_claim_score_formulas() -> None:
    claim = _claim("kol-1", "claim-1", ClaimDirection.BEARISH)
    policy = KolFeaturePolicy(
        attention_lookback_days=20,
        attention_saturation=Decimal("2"),
        minimum_consensus_kols=1,
        high_grade_confidence_bps=0,
        performance_policy=ClaimPerformancePolicy(horizons=(1,)),
    )
    bundle = compute_kol_features(
        [claim],
        _prices(("100", "90")),
        _calendar(),
        T0 + timedelta(days=10),
        policy,
    )
    attention = _feature(bundle, KolFeatureName.KOL_ATTENTION_SCORE, "kol-1")
    consensus = _feature(bundle, KolFeatureName.CONSENSUS_SCORE, "600519.SH")
    claim_score = _feature(
        bundle,
        KolFeatureName.CLAIM_SCORE,
        "claim-source:claim-1:claim-1-r1",
    )
    assert attention.value_bps == 2000
    assert consensus.value_bps == -10000
    assert bundle.performance.samples[0].horizon_returns[0].signed_return == Decimal("0.1")
    assert claim_score.value_bps == 7750
    assert tuple(item.revision_id for item in claim_score.input_prices) == (
        "bar-r0",
        "bar-r1",
    )
    assert tuple(item.snapshot_id for item in claim_score.input_calendars) == ("calendar-sh-v1",)


def test_review_approval_transition_publishes_claim_score() -> None:
    root = _claim(
        "kol-1",
        "claim-1",
        ClaimDirection.BULLISH,
        review_status=ReviewStatus.IN_REVIEW,
    )
    approved = _claim(
        "kol-1",
        "claim-1",
        ClaimDirection.BULLISH,
        revision_id="claim-1-approved",
        previous_revision_id=root.revision_id,
        available_time=T0 + timedelta(days=1),
    )
    policy = KolFeaturePolicy(
        minimum_consensus_kols=1,
        performance_policy=ClaimPerformancePolicy(horizons=(1,)),
    )
    bundle = compute_kol_features(
        [root, approved],
        _prices(),
        _calendar(),
        T0 + timedelta(days=4),
        policy,
    )
    score = _feature(
        bundle,
        KolFeatureName.CLAIM_SCORE,
        "claim-source:claim-1:claim-1-approved",
    )
    assert score.status is FeatureStatus.PUBLISHED
    assert score.input_claims[0].review_status is ReviewStatus.APPROVED


def test_claim_score_fingerprint_covers_intermediate_prices_and_calendar() -> None:
    claim = _claim("kol-1", "claim-1", ClaimDirection.BULLISH)
    policy = KolFeaturePolicy(
        minimum_consensus_kols=1,
        performance_policy=ClaimPerformancePolicy(horizons=(2,)),
    )
    first = compute_kol_features(
        [claim],
        _prices(("100", "105", "110")),
        _calendar(),
        T0 + timedelta(days=4),
        policy,
    )
    second = compute_kol_features(
        [claim],
        _prices(("100", "106", "110")),
        _calendar(),
        T0 + timedelta(days=4),
        policy,
    )
    first_score = _feature(
        first,
        KolFeatureName.CLAIM_SCORE,
        "claim-source:claim-1:claim-1-r1",
    )
    second_score = _feature(
        second,
        KolFeatureName.CLAIM_SCORE,
        "claim-source:claim-1:claim-1-r1",
    )
    assert tuple(item.revision_id for item in first_score.input_prices) == (
        "bar-r0",
        "bar-r1",
        "bar-r2",
    )
    assert first_score.value_bps == second_score.value_bps
    assert first_score.input_fingerprint != second_score.input_fingerprint
    assert len(first_score.input_calendars) == 1
    assert first_score.input_calendars[0].fingerprint.startswith("sha256:")
