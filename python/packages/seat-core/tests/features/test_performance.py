"""P4-N04 point-in-time seat performance feature tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TypedDict, Unpack

import pytest
from seat_core.features.performance import (
    PERFORMANCE_ALGORITHM_VERSION,
    PERFORMANCE_FEATURE_SCHEMA_VERSION,
    PERFORMANCE_POLICY_VERSION,
    DailyPriceObservation,
    ExclusionReason,
    LimitState,
    PerformanceInputError,
    PerformancePolicy,
    PerformanceRequest,
    PerformanceStatus,
    StyleObservation,
    compute_seat_performance,
)
from seat_core.models import Currency, Trade, compute_seat_id


class FixtureCalendar:
    """Small deterministic calendar fake for the feature boundary."""

    def __init__(self, holidays: set[date] | None = None) -> None:
        self.holidays = holidays or set()

    def is_trading_day(self, day: str, exchange: str) -> bool:
        del exchange
        value = date.fromisoformat(day)
        return value.weekday() < 5 and value not in self.holidays

    def next_trading_day(self, day: str, exchange: str) -> str:
        del exchange
        value = date.fromisoformat(day) + timedelta(days=1)
        while not self.is_trading_day(value.isoformat(), "SH"):
            value += timedelta(days=1)
        return value.isoformat()


SEAT_ID = compute_seat_id("broker:alpha")
DECISION_TIME = datetime(2026, 1, 12, 8, 0, tzinfo=UTC)


class PolicyOverrides(TypedDict, total=False):
    calendar_version: str
    min_samples: int
    min_style_samples: int
    min_style_share: Decimal


def _policy(**overrides: Unpack[PolicyOverrides]) -> PerformancePolicy:
    base = PerformancePolicy(
        min_samples=1,
        allowed_style_tags=("MOMENTUM", "VALUE"),
        min_style_samples=1,
        min_style_share=Decimal("0.50"),
    )
    return replace(base, **overrides)


def _request(
    *,
    decision_time: datetime = DECISION_TIME,
    policy: PerformancePolicy | None = None,
) -> PerformanceRequest:
    return PerformanceRequest(
        seat_id=SEAT_ID,
        window_start=date(2026, 1, 5),
        window_end=date(2026, 1, 9),
        decision_time=decision_time,
        policy=_policy() if policy is None else policy,
    )


def _trade(
    instrument_id: str,
    *,
    trade_id: str = "trade-1",
    revision_id: str = "revision-1",
    previous_revision_id: str | None = None,
    trade_date: date = date(2026, 1, 5),
    available_time: datetime = datetime(2026, 1, 12, 8, tzinfo=UTC),
    net_amount: Decimal = Decimal("100.00"),
    seat_id: str = SEAT_ID,
) -> Trade:
    return Trade(
        trade_id=trade_id,
        revision_id=revision_id,
        previous_revision_id=previous_revision_id,
        seat_id=seat_id,
        raw_seat_name="Alpha Branch",
        instrument_id=instrument_id,
        trade_date=trade_date,
        currency=Currency.CNY,
        buy_amount=net_amount,
        sell_amount=Decimal("0"),
        net_amount=net_amount,
        source="dragon-tiger",
        source_version="2026-01",
        raw_record_id=f"raw-{trade_id}-{revision_id}",
        evidence_id=f"evidence-{trade_id}-{revision_id}",
        available_time=available_time,
    )


def _bar(
    instrument_id: str,
    trade_date: date,
    close: str,
    *,
    available_time: datetime = datetime(2026, 1, 12, 8, tzinfo=UTC),
    raw_capture_id: str | None = None,
    replacement_version: int = 1,
    source: str = "prices",
    source_version: str = "prices-2026-01",
    data_version: str = "prices-data-v1",
    event_time: datetime | None = None,
    adjustment: str = "FORWARD_ADJUSTED",
    session: str = "CONTINUOUS",
    schema_version: str = "daily-bar-v1",
    revision_id: str = "bar-revision-1",
    suspended: bool = False,
) -> DailyPriceObservation:
    return DailyPriceObservation(
        instrument_id=instrument_id,
        trade_date=trade_date,
        close=Decimal(close),
        event_time=event_time
        or datetime(trade_date.year, trade_date.month, trade_date.day, 15, tzinfo=UTC),
        available_time=available_time,
        raw_capture_id=raw_capture_id or f"capture-{instrument_id}-{trade_date}",
        replacement_version=replacement_version,
        source=source,
        source_version=source_version,
        data_version=data_version,
        adjustment=adjustment,
        session=session,
        schema_version=schema_version,
        revision_id=revision_id,
        suspended=suspended,
    )


def _path_bars(instrument_id: str, closes: list[str]) -> list[DailyPriceObservation]:
    days = [
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 9),
        date(2026, 1, 12),
    ]
    return [_bar(instrument_id, day, close) for day, close in zip(days, closes, strict=True)]


def _style(
    tag: str,
    *,
    observation_id: str = "style-1",
    previous_revision_id: str | None = None,
    revision_id: str | None = None,
    source: str = "style-source",
    source_version: str = "style-2026-01",
    observation_time: datetime = datetime(2026, 1, 6, 8, tzinfo=UTC),
    available_time: datetime = datetime(2026, 1, 12, 8, tzinfo=UTC),
    taxonomy_version: str = "style-taxonomy-v1",
) -> StyleObservation:
    return StyleObservation(
        seat_id=SEAT_ID,
        observation_id=observation_id,
        style_tag=tag,
        observation_time=observation_time,
        available_time=available_time,
        taxonomy_version=taxonomy_version,
        source=source,
        source_version=source_version,
        evidence_id=f"style-evidence-{observation_id}",
        revision_id=revision_id or f"style-revision-{observation_id}",
        previous_revision_id=previous_revision_id,
    )


def test_performance_computes_decimal_t1_t3_t5_win_rate_and_worst_path_drawdown() -> None:
    first = _path_bars("600519.SH", ["100", "101", "103", "105", "104", "106"])
    second = _path_bars("000001.SZ", ["200", "198", "202", "204", "200", "198"])

    result = compute_seat_performance(
        _request(),
        [
            _trade("600519.SH", trade_id="trade-1", revision_id="revision-1"),
            _trade("000001.SZ", trade_id="trade-2", revision_id="revision-2"),
        ],
        [*first, *second],
        calendar=FixtureCalendar(),
    )

    assert result.status is PerformanceStatus.PUBLISHED
    assert result.sample_count == 2
    assert result.performance is not None
    assert result.performance.t_plus_1_return == Decimal("0")
    assert result.performance.t_plus_3_return == Decimal("0.035")
    assert result.performance.t_plus_5_return == Decimal("0.025")
    assert result.performance.win_rate == Decimal("0.5")
    assert result.performance.max_drawdown == Decimal("198") / Decimal("204") - Decimal("1")
    assert all(
        isinstance(value, Decimal)
        for value in (
            result.performance.t_plus_1_return,
            result.performance.t_plus_3_return,
            result.performance.t_plus_5_return,
            result.performance.win_rate,
            result.performance.max_drawdown,
        )
    )
    assert result.decision_time == DECISION_TIME
    assert result.logical_available_time == DECISION_TIME
    assert result.policy_fingerprint == _request().policy.fingerprint


def test_calendar_skips_weekends_and_holidays_without_natural_day_substitution() -> None:
    calendar = FixtureCalendar({date(2026, 1, 7)})
    result = compute_seat_performance(
        _request(),
        [_trade("600519.SH")],
        [
            _bar("600519.SH", date(2026, 1, 5), "100"),
            _bar("600519.SH", date(2026, 1, 6), "101"),
            _bar("600519.SH", date(2026, 1, 8), "103"),
            _bar("600519.SH", date(2026, 1, 9), "104"),
            _bar("600519.SH", date(2026, 1, 12), "105"),
            _bar("600519.SH", date(2026, 1, 13), "106"),
        ],
        calendar=calendar,
    )

    assert result.sample_count == 1
    assert result.performance is not None
    assert result.performance.t_plus_1_return == Decimal("0.01")
    assert result.samples[0].path_dates == (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 8),
        date(2026, 1, 9),
        date(2026, 1, 12),
        date(2026, 1, 13),
    )


def test_available_time_boundary_is_inclusive_and_future_bar_is_not_used() -> None:
    exact = _bar("600519.SH", date(2026, 1, 5), "100")
    future = _bar(
        "600519.SH",
        date(2026, 1, 6),
        "101",
        available_time=datetime(2026, 1, 12, 8, 0, 1, tzinfo=UTC),
    )

    result = compute_seat_performance(
        _request(),
        [_trade("600519.SH")],
        [exact, future],
        calendar=FixtureCalendar(),
    )

    assert result.sample_count == 0
    assert result.samples[0].exclusion_reason is ExclusionReason.MISSING_PRICE


def test_trade_available_time_boundary_is_inclusive() -> None:
    result = compute_seat_performance(
        _request(),
        [_trade("600519.SH", available_time=DECISION_TIME)],
        _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"]),
        calendar=FixtureCalendar(),
    )
    assert result.sample_count == 1


def test_old_trade_revision_is_not_double_counted_and_fork_fails_closed() -> None:
    old = _trade("600519.SH", revision_id="revision-1")
    latest = _trade(
        "600519.SH",
        revision_id="revision-2",
        previous_revision_id="revision-1",
    )
    result = compute_seat_performance(
        _request(),
        [old, latest],
        _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"]),
        calendar=FixtureCalendar(),
    )
    assert result.sample_count == 1
    assert result.samples[0].trade_revision_id == "revision-2"

    fork = _trade(
        "600519.SH",
        revision_id="revision-3",
        previous_revision_id="revision-1",
    )
    with pytest.raises(PerformanceInputError, match="fork"):
        compute_seat_performance(
            _request(),
            [old, latest, fork],
            _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"]),
            calendar=FixtureCalendar(),
        )


def test_duplicate_visible_latest_fails_closed() -> None:
    trade = _trade("600519.SH")
    with pytest.raises(PerformanceInputError, match="duplicate"):
        compute_seat_performance(
            _request(),
            [trade, trade],
            _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"]),
            calendar=FixtureCalendar(),
        )


@pytest.mark.parametrize(
    ("bar_kwargs", "reason"),
    [
        ({"suspended": True}, ExclusionReason.SUSPENDED),
        ({"close": "0"}, ExclusionReason.NON_POSITIVE_PRICE),
    ],
)
def test_invalid_path_data_excludes_whole_sample_without_shift(
    bar_kwargs: dict[str, object], reason: ExclusionReason
) -> None:
    bars = _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"])
    replacement = bars[2]
    if "close" in bar_kwargs:
        bars[2] = _bar("600519.SH", replacement.trade_date, str(bar_kwargs["close"]))
    else:
        bars[2] = _bar("600519.SH", replacement.trade_date, "102", suspended=True)

    result = compute_seat_performance(
        _request(), [_trade("600519.SH")], bars, calendar=FixtureCalendar()
    )
    assert result.sample_count == 0
    assert result.samples[0].exclusion_reason is reason
    assert result.samples[0].path_dates[3] == date(2026, 1, 8)


def test_mixed_adjustment_sequence_is_excluded_with_stable_reason() -> None:
    bars = _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"])
    bars[3] = _bar("600519.SH", date(2026, 1, 8), "103", adjustment="RAW")

    result = compute_seat_performance(
        _request(), [_trade("600519.SH")], bars, calendar=FixtureCalendar()
    )
    assert result.sample_count == 0
    assert result.samples[0].exclusion_reason is ExclusionReason.PRICE_SERIES_AMBIGUOUS


def test_low_sample_and_empty_states_keep_diagnostics_but_publish_no_metrics() -> None:
    policy = _policy(min_samples=2)
    result = compute_seat_performance(
        _request(policy=policy),
        [_trade("600519.SH")],
        _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"]),
        calendar=FixtureCalendar(),
    )
    assert result.status is PerformanceStatus.INSUFFICIENT_SAMPLES
    assert result.sample_count == 1
    assert result.performance is None
    assert result.preference is None

    empty = compute_seat_performance(_request(policy=policy), [], [], calendar=FixtureCalendar())
    assert empty.status is PerformanceStatus.NO_SAMPLES
    assert empty.sample_count == 0
    assert empty.performance is None


def test_style_preference_is_controlled_pit_and_fingerprinted() -> None:
    policy = _policy(min_style_samples=2, min_style_share=Decimal("0.50"))
    observations = [
        _style("MOMENTUM", observation_id="style-1"),
        _style("MOMENTUM", observation_id="style-2"),
        _style("UNKNOWN", observation_id="style-3"),
        _style(
            "VALUE",
            observation_id="style-future",
            available_time=datetime(2026, 1, 12, 8, 0, 1, tzinfo=UTC),
        ),
    ]
    result = compute_seat_performance(
        _request(policy=policy),
        [_trade("600519.SH")],
        _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"]),
        style_observations=observations,
        calendar=FixtureCalendar(),
    )

    assert result.preference is not None
    assert result.preference.style_tags == ("MOMENTUM",)
    assert result.preference.taxonomy_version == "style-taxonomy-v1"
    assert result.style_sample_count == 2
    assert len(result.style_exclusions) == 1
    assert result.style_exclusions[0].observation_id == "style-3"
    assert result.style_exclusions[0].reason == "unknown_style_tag"
    assert (
        result.policy_fingerprint
        != _policy(min_style_samples=2, min_style_share=Decimal("0.60")).policy_fingerprint
    )


def test_provenance_contains_trade_revision_and_every_selected_bar_identity() -> None:
    result = compute_seat_performance(
        _request(),
        [_trade("600519.SH")],
        _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"]),
        calendar=FixtureCalendar(),
    )

    sample = result.samples[0]
    assert sample.included is True
    assert sample.trade_revision_id == "revision-1"
    assert len(sample.bars) == 6
    assert sample.bars[0].raw_capture_id == "capture-600519.SH-2026-01-05"
    assert sample.bars[0].replacement_version == 1
    assert sample.bars[0].source_version == "prices-2026-01"
    assert result.algorithm_version
    assert result.policy_version


def test_naive_decision_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _request(decision_time=datetime(2026, 1, 12, 8))


def test_visible_revision_with_missing_predecessor_fails_closed() -> None:
    broken = _trade(
        "600519.SH",
        revision_id="revision-2",
        previous_revision_id="missing-revision",
    )
    with pytest.raises(PerformanceInputError, match="predecessor"):
        compute_seat_performance(
            _request(),
            [broken],
            _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"]),
            calendar=FixtureCalendar(),
        )


def test_future_revision_fork_does_not_change_past_point_in_time_result() -> None:
    old = _trade(
        "600519.SH",
        revision_id="revision-1",
        available_time=datetime(2026, 1, 12, 7, tzinfo=UTC),
    )
    future_a = _trade(
        "600519.SH",
        revision_id="revision-2",
        previous_revision_id="revision-1",
        available_time=datetime(2026, 1, 12, 9, tzinfo=UTC),
    )
    future_b = _trade(
        "600519.SH",
        revision_id="revision-3",
        previous_revision_id="revision-1",
        available_time=datetime(2026, 1, 12, 9, tzinfo=UTC),
    )
    bars = _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"])
    baseline = compute_seat_performance(_request(), [old], bars, calendar=FixtureCalendar())
    with_future = compute_seat_performance(
        _request(), [old, future_a, future_b], bars, calendar=FixtureCalendar()
    )
    assert with_future.performance == baseline.performance
    assert with_future.samples == baseline.samples


def test_future_revision_cycle_and_bad_order_do_not_block_past() -> None:
    old = _trade(
        "600519.SH",
        revision_id="revision-1",
        available_time=datetime(2026, 1, 12, 7, tzinfo=UTC),
    )
    cycle_a = _trade(
        "600519.SH",
        revision_id="revision-2",
        previous_revision_id="revision-3",
        available_time=datetime(2026, 1, 12, 9, tzinfo=UTC),
    )
    cycle_b = _trade(
        "600519.SH",
        revision_id="revision-3",
        previous_revision_id="revision-2",
        available_time=datetime(2026, 1, 12, 9, tzinfo=UTC),
    )
    result = compute_seat_performance(
        _request(),
        [old, cycle_a, cycle_b],
        _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"]),
        calendar=FixtureCalendar(),
    )
    assert result.sample_count == 1

    late_parent = _trade(
        "600519.SH",
        revision_id="revision-4",
        available_time=datetime(2026, 1, 12, 10, tzinfo=UTC),
    )
    early_child = _trade(
        "600519.SH",
        revision_id="revision-5",
        previous_revision_id="revision-4",
        available_time=datetime(2026, 1, 12, 9, tzinfo=UTC),
    )
    result_with_bad_future = compute_seat_performance(
        _request(),
        [old, late_parent, early_child],
        _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"]),
        calendar=FixtureCalendar(),
    )
    assert result_with_bad_future.performance == result.performance


def test_sample_contains_complete_trade_provenance_for_replay() -> None:
    trade = _trade("600519.SH", previous_revision_id=None)
    result = compute_seat_performance(
        _request(),
        [trade],
        _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"]),
        calendar=FixtureCalendar(),
    )
    sample = result.samples[0]
    assert sample.trade_source == trade.source
    assert sample.trade_source_version == trade.source_version
    assert sample.trade_raw_record_id == trade.raw_record_id
    assert sample.trade_evidence_id == trade.evidence_id
    assert sample.trade_available_time == trade.available_time
    assert sample.trade_previous_revision_id == trade.previous_revision_id


def test_bar_sequence_ignores_per_date_revision_and_uses_highest_visible_replacement() -> None:
    bars = _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"])
    bars = [replace(bar, revision_id=f"revision-{index}") for index, bar in enumerate(bars)]
    bars[1] = replace(
        bars[1],
        close=Decimal("111"),
        replacement_version=2,
        raw_capture_id="capture-replacement-2",
    )
    result = compute_seat_performance(
        _request(), [_trade("600519.SH")], bars, calendar=FixtureCalendar()
    )
    assert result.sample_count == 1
    assert result.samples[0].bars[1].close == Decimal("111")
    assert result.samples[0].bars[1].replacement_version == 2


def test_limit_states_are_retained_as_observation_provenance_not_fill_semantics() -> None:
    bars = _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"])
    bars[1] = replace(bars[1], limit_state=LimitState.LIMIT_UP)
    bars[2] = replace(bars[2], limit_state=LimitState.LIMIT_DOWN)
    result = compute_seat_performance(
        _request(), [_trade("600519.SH")], bars, calendar=FixtureCalendar()
    )
    assert result.sample_count == 1
    assert result.samples[0].bars[1].limit_state is LimitState.LIMIT_UP
    assert result.samples[0].bars[2].limit_state is LimitState.LIMIT_DOWN


def test_style_revision_chain_selects_visible_latest_and_future_revision_is_invariant() -> None:
    old = _style("MOMENTUM", observation_id="style-1")
    latest = _style(
        "VALUE",
        observation_id="style-1",
        previous_revision_id=old.revision_id,
        revision_id="style-revision-2",
    )
    future = replace(
        latest,
        revision_id="style-revision-future",
        previous_revision_id=latest.revision_id,
        available_time=datetime(2026, 1, 12, 9, tzinfo=UTC),
    )
    bars = _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"])
    baseline = compute_seat_performance(
        _request(),
        [_trade("600519.SH")],
        bars,
        style_observations=[old],
        calendar=FixtureCalendar(),
    )
    with_latest = compute_seat_performance(
        _request(),
        [_trade("600519.SH")],
        bars,
        style_observations=[old, latest],
        calendar=FixtureCalendar(),
    )
    with_future = compute_seat_performance(
        _request(),
        [_trade("600519.SH")],
        bars,
        style_observations=[old, latest, future],
        calendar=FixtureCalendar(),
    )
    assert baseline.style_sample_count == 1
    assert with_latest.style_sample_count == 1
    assert with_latest.style_observations[0].revision_id == latest.revision_id
    assert with_future.style_observations == with_latest.style_observations


def test_visible_style_revision_breaks_fail_closed() -> None:
    broken = _style(
        "MOMENTUM",
        observation_id="style-broken",
        revision_id="style-revision-2",
        previous_revision_id="style-revision-missing",
    )
    with pytest.raises(PerformanceInputError, match="style.*predecessor"):
        compute_seat_performance(
            _request(),
            [_trade("600519.SH")],
            _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"]),
            style_observations=[broken],
            calendar=FixtureCalendar(),
        )


def test_visible_style_fork_and_cycle_fail_closed() -> None:
    root = _style("MOMENTUM", observation_id="style-fork", revision_id="style-root")
    fork_a = _style(
        "MOMENTUM",
        observation_id="style-fork",
        revision_id="style-a",
        previous_revision_id="style-root",
    )
    fork_b = _style(
        "VALUE",
        observation_id="style-fork",
        revision_id="style-b",
        previous_revision_id="style-root",
    )
    bars = _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"])
    with pytest.raises(PerformanceInputError, match="style.*fork"):
        compute_seat_performance(
            _request(),
            [_trade("600519.SH")],
            bars,
            style_observations=[root, fork_a, fork_b],
            calendar=FixtureCalendar(),
        )

    cycle_a = _style(
        "MOMENTUM",
        observation_id="style-cycle",
        revision_id="style-cycle-a",
        previous_revision_id="style-cycle-b",
    )
    cycle_b = _style(
        "VALUE",
        observation_id="style-cycle",
        revision_id="style-cycle-b",
        previous_revision_id="style-cycle-a",
    )
    with pytest.raises(PerformanceInputError, match="style.*cycle"):
        compute_seat_performance(
            _request(),
            [_trade("600519.SH")],
            bars,
            style_observations=[cycle_a, cycle_b],
            calendar=FixtureCalendar(),
        )


def test_style_exclusion_retains_observation_identity_and_reason() -> None:
    unknown = _style("UNKNOWN", observation_id="style-unknown")
    result = compute_seat_performance(
        _request(),
        [_trade("600519.SH")],
        _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"]),
        style_observations=[unknown],
        calendar=FixtureCalendar(),
    )
    exclusion = result.style_exclusions[0]
    assert exclusion.observation_id == unknown.observation_id
    assert exclusion.revision_id == unknown.revision_id
    assert exclusion.reason == "unknown_style_tag"


def test_non_increasing_calendar_fails_closed() -> None:
    class BadCalendar(FixtureCalendar):
        def next_trading_day(self, day: str, exchange: str) -> str:
            del exchange
            return day

    with pytest.raises(PerformanceInputError, match="strictly later"):
        compute_seat_performance(
            _request(),
            [_trade("600519.SH")],
            _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"]),
            calendar=BadCalendar(),
        )


def test_logical_available_time_is_maximum_of_contributing_inputs_and_none_without_inputs() -> None:
    trade_available = datetime(2026, 1, 12, 7, tzinfo=UTC)
    bar_available = datetime(2026, 1, 12, 7, 30, tzinfo=UTC)
    bars = [
        replace(bar, available_time=bar_available)
        for bar in _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"])
    ]
    result = compute_seat_performance(
        _request(),
        [replace(_trade("600519.SH"), available_time=trade_available)],
        bars,
        calendar=FixtureCalendar(),
    )
    assert result.logical_available_time == bar_available

    empty = compute_seat_performance(_request(), [], [], calendar=FixtureCalendar())
    assert empty.logical_available_time is None


def test_future_prices_and_style_observations_do_not_change_past_result() -> None:
    bars = _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"])
    baseline = compute_seat_performance(
        _request(), [_trade("600519.SH")], bars, calendar=FixtureCalendar()
    )
    future_bars = [
        replace(
            bars[1],
            close=Decimal("999"),
            available_time=datetime(2026, 1, 12, 9, tzinfo=UTC),
            raw_capture_id="future-price",
        )
    ]
    future_style = _style(
        "MOMENTUM",
        observation_id="future-style",
        revision_id="style-revision-future",
        available_time=datetime(2026, 1, 12, 9, tzinfo=UTC),
    )
    with_future = compute_seat_performance(
        _request(),
        [_trade("600519.SH")],
        [*bars, *future_bars],
        style_observations=[future_style],
        calendar=FixtureCalendar(),
    )
    assert with_future.performance == baseline.performance
    assert with_future.samples == baseline.samples


def test_revision_specific_trade_ids_share_root_lineage_and_count_latest_once() -> None:
    root = _trade(
        "600519.SH",
        trade_id="trade-root-raw-root-revision-1",
        revision_id="revision-root",
    )
    successor = _trade(
        "600519.SH",
        trade_id="trade-successor-raw-successor-revision-2",
        revision_id="revision-successor",
        previous_revision_id="revision-root",
    )
    result = compute_seat_performance(
        _request(),
        [root, successor],
        _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"]),
        calendar=FixtureCalendar(),
    )
    assert result.sample_count == 1
    assert result.samples[0].trade_id == successor.trade_id
    assert result.samples[0].trade_lineage_id == "dragon-tiger:revision-root"


def test_same_trade_date_different_event_time_is_ambiguous_not_replacement() -> None:
    bars = _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"])
    bars.append(
        _bar(
            "600519.SH",
            date(2026, 1, 6),
            "999",
            event_time=datetime(2026, 1, 6, 16, tzinfo=UTC),
            replacement_version=2,
            raw_capture_id="different-event-time",
        )
    )
    result = compute_seat_performance(
        _request(), [_trade("600519.SH")], bars, calendar=FixtureCalendar()
    )
    assert result.sample_count == 0
    assert result.samples[0].exclusion_reason is ExclusionReason.PRICE_SERIES_AMBIGUOUS


def test_adjusted_split_path_wins_over_raw_interference_without_pseudo_return() -> None:
    adjusted = _path_bars("600519.SH", ["100", "100", "100", "100", "100", "100"])
    raw_interference = replace(
        adjusted[3],
        close=Decimal("50"),
        adjustment="RAW",
        data_version="raw-data-v1",
        raw_capture_id="raw-split-interference",
    )
    result = compute_seat_performance(
        _request(),
        [_trade("600519.SH")],
        [*adjusted, raw_interference],
        calendar=FixtureCalendar(),
    )
    assert result.sample_count == 1
    assert result.performance is not None
    assert result.performance.t_plus_5_return == Decimal("0")


def test_style_source_namespace_prevents_collision_and_exclusion_is_replayable() -> None:
    source_a = _style("UNKNOWN", observation_id="shared-id", source="source-a")
    source_b = _style("MOMENTUM", observation_id="shared-id", source="source-b")
    result = compute_seat_performance(
        _request(),
        [_trade("600519.SH")],
        _path_bars("600519.SH", ["100", "101", "102", "103", "104", "105"]),
        style_observations=[source_a, source_b],
        calendar=FixtureCalendar(),
    )
    assert result.style_sample_count == 1
    assert len(result.style_exclusions) == 1
    exclusion = result.style_exclusions[0]
    assert exclusion.source == source_a.source
    assert exclusion.source_version == source_a.source_version
    assert exclusion.evidence_id == source_a.evidence_id
    assert exclusion.available_time == source_a.available_time
    assert exclusion.observation_id == source_a.observation_id
    assert exclusion.revision_id == source_a.revision_id
    assert exclusion.reason == "unknown_style_tag"


def test_calendar_version_and_public_facade_versions_are_stable_and_fingerprinted() -> None:
    import seat_core

    assert seat_core.PERFORMANCE_ALGORITHM_VERSION == PERFORMANCE_ALGORITHM_VERSION
    assert seat_core.PERFORMANCE_FEATURE_SCHEMA_VERSION == PERFORMANCE_FEATURE_SCHEMA_VERSION
    assert seat_core.PERFORMANCE_POLICY_VERSION == PERFORMANCE_POLICY_VERSION
    assert _policy().fingerprint != replace(_policy(), calendar_version="calendar-v2").fingerprint
