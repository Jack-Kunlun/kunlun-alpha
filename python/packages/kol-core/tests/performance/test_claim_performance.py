"""P4-N09 point-in-time Claim performance tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
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
    ClaimPerformanceExclusionReason,
    ClaimPerformanceInputError,
    ClaimPerformancePolicy,
    ClaimPerformanceStatus,
    TradablePriceObservation,
    TradingCalendarSnapshot,
    TradingSession,
    compute_claim_performance,
    select_active_claims,
)

T0 = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)


def _claim(
    *,
    claim_id: str = "claim-1",
    revision_id: str = "claim-r1",
    previous_revision_id: str | None = None,
    kol_id: str = "kol-1",
    available_time: datetime = T0,
    direction: ClaimDirection = ClaimDirection.BULLISH,
    statement: str = "公开看多",
    confidence_bps: int = 8000,
    review_status: ReviewStatus = ReviewStatus.APPROVED,
    deleted: bool = False,
    deleted_at: datetime | None = None,
) -> KolClaim:
    evidence_time = available_time - timedelta(minutes=1)
    content_time = evidence_time - timedelta(minutes=1)
    return KolClaim(
        claim_id=claim_id,
        revision_id=revision_id,
        previous_revision_id=previous_revision_id,
        content_id=f"content-{claim_id}",
        content_version=f"content-version-{revision_id}",
        content_available_time=content_time,
        kol_id=kol_id,
        statement=statement,
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
        source="claim-source",
        source_version="v1",
        evidence=(
            ClaimEvidenceReference(
                evidence_id=f"evidence-{revision_id}",
                evidence_revision_id=f"evidence-revision-{revision_id}",
                content_id=f"content-{claim_id}",
                content_version=f"content-version-{revision_id}",
                content_available_time=content_time,
                evidence_available_time=evidence_time,
                source="claim-source",
                source_version="v1",
            ),
        ),
        deleted=deleted,
        deleted_at=deleted_at,
        deletion_reason="source-deleted" if deleted else None,
    )


def _price(
    day: int,
    price: str,
    *,
    suspended: bool = False,
    available_delay: timedelta = timedelta(minutes=5),
    replacement_version: int = 1,
    revision_suffix: str = "base",
) -> TradablePriceObservation:
    event_time = T0 + timedelta(days=day)
    return TradablePriceObservation(
        instrument_id="600519.SH",
        trade_date=date(2026, 8, 1) + timedelta(days=day),
        event_time=event_time,
        price=Decimal(price),
        available_time=event_time + available_delay,
        suspended=suspended,
        source="market-source",
        source_version="v1",
        data_version="bars-v1",
        raw_capture_id=f"capture-{day}-{revision_suffix}",
        revision_id=f"bar-r{day}-{revision_suffix}",
        replacement_version=replacement_version,
    )


def _calendar(
    *,
    start_day: int = -2,
    end_day: int = 10,
) -> tuple[TradingCalendarSnapshot, ...]:
    sessions = tuple(
        TradingSession(
            trade_date=date(2026, 8, 1) + timedelta(days=day),
            close_time=T0 + timedelta(days=day),
        )
        for day in range(start_day, end_day + 1)
    )
    return (
        TradingCalendarSnapshot(
            market="SH",
            coverage_start_time=T0 + timedelta(days=start_day, hours=-1),
            coverage_end_time=T0 + timedelta(days=end_day, hours=1),
            sessions=sessions,
            available_time=T0 - timedelta(days=10),
            source="calendar-source",
            source_version="v1",
            data_version="calendar-v1",
            snapshot_id="calendar-sh-v1",
        ),
    )


def test_first_tradable_entry_skips_prepublication_and_suspension() -> None:
    prices = [
        _price(-1, "99"),
        _price(0, "100", suspended=True),
        _price(1, "100"),
        _price(2, "110"),
        _price(3, "90", suspended=True),
        _price(4, "120"),
    ]
    result = compute_claim_performance(
        [_claim()],
        prices,
        _calendar(),
        T0 + timedelta(days=5),
        ClaimPerformancePolicy(horizons=(1, 2)),
    )
    sample = result.samples[0]
    assert sample.status is ClaimPerformanceStatus.MATURE
    assert sample.entry_observation is not None
    assert sample.entry_observation.revision_id == "bar-r1-base"
    assert tuple(item.revision_id for item in sample.skipped_suspensions) == (
        "bar-r0-base",
        "bar-r3-base",
    )
    assert [item.signed_return for item in sample.horizon_returns] == [
        Decimal("0.1"),
        Decimal("0.2"),
    ]


def test_revision_uses_its_own_available_time_without_backfilling_root() -> None:
    root = _claim()
    correction = _claim(
        revision_id="claim-r2",
        previous_revision_id=root.revision_id,
        available_time=T0 + timedelta(days=2),
        direction=ClaimDirection.BEARISH,
        statement="两日后公开改为看空",
    )
    prices = [_price(day, str(100 + day * 10)) for day in range(0, 7)]
    historical = compute_claim_performance(
        [root, correction], prices, _calendar(), T0 + timedelta(days=1, hours=1)
    )
    current = compute_claim_performance(
        [root, correction],
        prices,
        _calendar(),
        T0 + timedelta(days=7),
        ClaimPerformancePolicy(horizons=(1,)),
    )
    assert [item.claim_revision_id for item in historical.samples] == [root.revision_id]
    assert [item.claim_revision_id for item in current.samples] == [
        root.revision_id,
        correction.revision_id,
    ]
    assert current.samples[0].entry_observation is not None
    assert current.samples[1].entry_observation is not None
    assert current.samples[0].entry_observation.event_time == T0
    assert current.samples[1].entry_observation.event_time == T0 + timedelta(days=2)
    assert select_active_claims([root, correction], T0 + timedelta(days=1)) == (root,)
    assert select_active_claims([root, correction], T0 + timedelta(days=3)) == (correction,)


def test_tombstone_stops_active_consensus_but_preserves_historical_performance() -> None:
    root = _claim()
    tombstone = _claim(
        revision_id="claim-r-deleted",
        previous_revision_id=root.revision_id,
        available_time=T0 + timedelta(days=1),
        deleted=True,
        deleted_at=T0 + timedelta(days=3),
    )
    prices = [_price(day, str(100 + day)) for day in range(0, 7)]
    before = T0 + timedelta(days=2)
    after = T0 + timedelta(days=6)
    assert select_active_claims([root, tombstone], before) == (root,)
    assert select_active_claims([root, tombstone], after) == ()
    result = compute_claim_performance(
        [root, tombstone],
        prices,
        _calendar(),
        after,
        ClaimPerformancePolicy(horizons=(1,)),
    )
    assert len(result.samples) == 1
    assert result.samples[0].withdrawn_at == tombstone.deleted_at
    assert result.samples[0].active_at_decision is False
    assert result.samples[0].status is ClaimPerformanceStatus.MATURE
    assert result.data_cutoff_time == tombstone.deleted_at


def test_late_price_revision_and_unavailable_horizon_are_point_in_time() -> None:
    root = _claim()
    prices = [
        _price(0, "100"),
        _price(1, "110"),
        _price(
            1,
            "200",
            available_delay=timedelta(days=3),
            replacement_version=2,
            revision_suffix="late",
        ),
    ]
    result = compute_claim_performance(
        [root],
        prices,
        _calendar(),
        T0 + timedelta(days=1, hours=1),
        ClaimPerformancePolicy(horizons=(1, 2)),
    )
    sample = result.samples[0]
    assert sample.status is ClaimPerformanceStatus.PENDING
    assert sample.exclusion_reason is ClaimPerformanceExclusionReason.INSUFFICIENT_HORIZON
    assert sample.horizon_returns[0].raw_return == Decimal("0.1")


def test_revision_fork_and_unapproved_claim_fail_closed_or_are_excluded() -> None:
    root = _claim()
    child_a = _claim(
        revision_id="claim-r2-a",
        previous_revision_id=root.revision_id,
        available_time=T0 + timedelta(days=1),
        statement="修订 A",
    )
    child_b = _claim(
        revision_id="claim-r2-b",
        previous_revision_id=root.revision_id,
        available_time=T0 + timedelta(days=2),
        statement="修订 B",
    )
    with pytest.raises(ClaimPerformanceInputError, match="fork"):
        compute_claim_performance(
            [root, child_a, child_b],
            [],
            _calendar(),
            T0 + timedelta(days=3),
        )

    unapproved = _claim(review_status=ReviewStatus.IN_REVIEW)
    excluded = compute_claim_performance(
        [unapproved],
        [],
        _calendar(),
        T0 + timedelta(days=1),
    ).samples[0]
    assert excluded.status is ClaimPerformanceStatus.EXCLUDED
    assert excluded.exclusion_reason is ClaimPerformanceExclusionReason.NOT_APPROVED


def test_future_revision_fork_is_invisible_before_the_historical_cutoff() -> None:
    root = _claim()
    future_a = _claim(
        revision_id="claim-r2-a",
        previous_revision_id=root.revision_id,
        available_time=T0 + timedelta(days=5),
        statement="未来修订 A",
    )
    future_b = _claim(
        revision_id="claim-r2-b",
        previous_revision_id=root.revision_id,
        available_time=T0 + timedelta(days=6),
        statement="未来修订 B",
    )
    historical_cutoff = T0 + timedelta(days=1)
    assert select_active_claims([root, future_a, future_b], historical_cutoff) == (root,)
    historical = compute_claim_performance(
        [root, future_a, future_b],
        [_price(0, "100"), _price(1, "110")],
        _calendar(),
        historical_cutoff,
        ClaimPerformancePolicy(horizons=(1,)),
    )
    assert [item.claim_revision_id for item in historical.samples] == [root.revision_id]
    with pytest.raises(ClaimPerformanceInputError, match="fork"):
        select_active_claims([root, future_a, future_b], T0 + timedelta(days=7))


def test_highest_visible_price_replacement_wins_over_a_late_stale_version() -> None:
    prices = [
        _price(
            0,
            "100",
            available_delay=timedelta(minutes=5),
            replacement_version=2,
            revision_suffix="corrected",
        ),
        _price(
            0,
            "999",
            available_delay=timedelta(minutes=10),
            replacement_version=1,
            revision_suffix="stale",
        ),
        _price(1, "110"),
    ]
    sample = compute_claim_performance(
        [_claim()],
        prices,
        _calendar(),
        T0 + timedelta(days=2),
        ClaimPerformancePolicy(horizons=(1,)),
    ).samples[0]
    assert sample.entry_observation is not None
    assert sample.entry_observation.revision_id == "bar-r0-corrected"
    assert sample.horizon_returns[0].raw_return == Decimal("0.1")


def test_deleted_tombstone_is_a_terminal_claim_revision() -> None:
    root = _claim()
    tombstone = _claim(
        revision_id="claim-r-deleted",
        previous_revision_id=root.revision_id,
        available_time=T0 + timedelta(days=1),
        deleted=True,
        deleted_at=T0 + timedelta(days=2),
    )
    resurrection = _claim(
        revision_id="claim-r-resurrected",
        previous_revision_id=tombstone.revision_id,
        available_time=T0 + timedelta(days=3),
        statement="非法恢复",
    )
    with pytest.raises(ClaimPerformanceInputError, match="tombstone must be terminal"):
        select_active_claims([root, tombstone, resurrection], T0 + timedelta(days=4))


def test_missing_session_price_is_pending_and_never_skips_to_a_later_date() -> None:
    sample = compute_claim_performance(
        [_claim()],
        [_price(0, "100"), _price(2, "120")],
        _calendar(),
        T0 + timedelta(days=3),
        ClaimPerformancePolicy(horizons=(1,)),
    ).samples[0]
    assert sample.status is ClaimPerformanceStatus.PENDING
    assert sample.exclusion_reason is ClaimPerformanceExclusionReason.MISSING_PRICE
    assert sample.missing_trade_dates == (date(2026, 8, 2),)
    assert sample.horizon_returns == ()


def test_all_suspended_sessions_wait_for_entry_and_preserve_provenance() -> None:
    sample = compute_claim_performance(
        [_claim()],
        [_price(0, "100", suspended=True), _price(1, "100", suspended=True)],
        _calendar(),
        T0 + timedelta(days=1, hours=1),
        ClaimPerformancePolicy(horizons=(1,)),
    ).samples[0]
    assert sample.status is ClaimPerformanceStatus.PENDING
    assert sample.exclusion_reason is ClaimPerformanceExclusionReason.WAITING_FOR_ENTRY
    assert sample.entry_observation is None
    assert tuple(item.revision_id for item in sample.skipped_suspensions) == (
        "bar-r0-base",
        "bar-r1-base",
    )
    assert sample.logical_available_time == _price(1, "100").available_time


def test_price_series_identity_mismatch_fails_closed() -> None:
    original = _price(0, "100", revision_suffix="series-a")
    other_series = replace(
        original,
        data_version="bars-v2",
        raw_capture_id="capture-series-b",
        revision_id="bar-r0-series-b",
        replacement_version=2,
    )
    with pytest.raises(ClaimPerformanceInputError, match="multiple price series"):
        compute_claim_performance(
            [_claim()],
            [original, other_series, _price(1, "110")],
            _calendar(),
            T0 + timedelta(days=2),
            ClaimPerformancePolicy(horizons=(1,)),
        )


def test_bearish_return_uses_direction_and_post_entry_suspension_does_not_count() -> None:
    sample = compute_claim_performance(
        [_claim(direction=ClaimDirection.BEARISH)],
        [
            _price(0, "100"),
            _price(1, "100", suspended=True),
            _price(2, "90"),
        ],
        _calendar(),
        T0 + timedelta(days=3),
        ClaimPerformancePolicy(horizons=(1,)),
    ).samples[0]
    assert sample.status is ClaimPerformanceStatus.MATURE
    assert sample.horizon_returns[0].raw_return == Decimal("-0.1")
    assert sample.horizon_returns[0].signed_return == Decimal("0.1")
    assert tuple(item.revision_id for item in sample.skipped_suspensions) == ("bar-r1-base",)


def test_approved_review_transition_is_evaluated_from_its_own_available_time() -> None:
    root = _claim(review_status=ReviewStatus.IN_REVIEW)
    approved = _claim(
        revision_id="claim-r-approved",
        previous_revision_id=root.revision_id,
        available_time=T0 + timedelta(days=1),
        review_status=ReviewStatus.APPROVED,
    )
    result = compute_claim_performance(
        [root, approved],
        [_price(1, "100"), _price(2, "110")],
        _calendar(),
        T0 + timedelta(days=3),
        ClaimPerformancePolicy(horizons=(1,)),
    )
    assert result.samples[0].exclusion_reason is ClaimPerformanceExclusionReason.NOT_APPROVED
    assert result.samples[1].status is ClaimPerformanceStatus.MATURE
    assert result.samples[1].entry_observation is not None
    assert result.samples[1].entry_observation.trade_date == date(2026, 8, 2)


def test_highest_visible_calendar_replacement_is_selected() -> None:
    baseline = _calendar()[0]
    corrected = replace(
        baseline,
        data_version="calendar-v2",
        snapshot_id="calendar-sh-v2",
        replacement_version=2,
        available_time=T0 - timedelta(days=5),
    )
    result = compute_claim_performance(
        [_claim()],
        [_price(0, "100"), _price(1, "110")],
        (baseline, corrected),
        T0 + timedelta(days=2),
        ClaimPerformancePolicy(horizons=(1,)),
    )
    assert result.calendar_snapshots == (corrected,)
    assert result.samples[0].calendar_snapshot_id == corrected.snapshot_id


def test_deletion_does_not_truncate_historical_public_performance_window() -> None:
    root = _claim()
    tombstone = _claim(
        revision_id="claim-r-deleted-early",
        previous_revision_id=root.revision_id,
        available_time=T0 + timedelta(days=1),
        deleted=True,
        deleted_at=T0 + timedelta(days=1),
    )
    result = compute_claim_performance(
        [root, tombstone],
        [_price(day, str(100 + day * 10)) for day in range(4)],
        _calendar(),
        T0 + timedelta(days=4),
        ClaimPerformancePolicy(horizons=(3,)),
    )
    sample = result.samples[0]
    assert sample.withdrawn_at == tombstone.deleted_at
    assert sample.status is ClaimPerformanceStatus.MATURE
    assert sample.horizon_returns[0].exit_observation.trade_date == date(2026, 8, 4)
