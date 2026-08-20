"""Premium / loss-making effect tests.

Covers unbiased sampling (suspended and one-word boards excluded), average
premium, win rate, high-to-close drawdown, point-in-time availability filtering
using :class:`PriceObservation` (fail-closed on missing/naive/unavailable), and
structured provenance/version fields.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from emotion_core.pit import Instant, PriceObservation
from emotion_core.premium import (
    PREMIUM_VERSION,
    compute_drawdown,
    compute_premium,
)


def _obs(
    value: str,
    available: str,
    *,
    event: str | None = None,
    source: str = "vendor-a",
    version: str = "quote_v1",
    evidence: str = "evt-1",
) -> PriceObservation:
    return PriceObservation(
        value=Decimal(value),
        event_time=Instant.parse(event or available),
        available_time=Instant.parse(available),
        source=source,
        source_version=version,
        evidence_id=evidence,
    )


_DECISION = Instant.parse("2026-08-14T02:00:00.000Z")


def test_average_premium_and_win_rate() -> None:
    pool = ["A", "B", "C"]
    yesterday_close = {
        "A": _obs("10.00", "2026-08-13T07:00:00.000Z"),
        "B": _obs("10.00", "2026-08-13T07:00:00.000Z"),
        "C": _obs("10.00", "2026-08-13T07:00:00.000Z"),
    }
    today_price = {
        "A": _obs("11.00", "2026-08-14T01:30:00.000Z"),  # +10%
        "B": _obs("9.50", "2026-08-14T01:30:00.000Z"),  # -5%
        "C": _obs("10.00", "2026-08-14T01:30:00.000Z"),  # 0%
    }

    result = compute_premium(pool, yesterday_close, today_price, decision_time=_DECISION)

    assert result.sample_size == 3
    assert result.average_premium == (Decimal("0.10") + Decimal("-0.05") + Decimal("0")) / 3
    assert isinstance(result.average_premium, Decimal)
    assert result.win_rate == Decimal("1") / Decimal("3")


def test_suspended_and_one_word_board_excluded() -> None:
    pool = ["A", "B", "C"]
    yesterday_close = {
        "A": _obs("10.00", "2026-08-13T07:00:00.000Z"),
        "B": _obs("10.00", "2026-08-13T07:00:00.000Z"),
        "C": _obs("10.00", "2026-08-13T07:00:00.000Z"),
    }
    today_price = {"A": _obs("11.00", "2026-08-14T01:30:00.000Z")}

    result = compute_premium(
        pool,
        yesterday_close,
        today_price,
        decision_time=_DECISION,
        suspended={"B"},
        one_word_board={"C"},
    )

    assert result.sample_size == 1
    assert result.average_premium == Decimal("0.10")
    assert result.provenance.excluded["B"] == "suspended"
    assert result.provenance.excluded["C"] == "one_word_board"


def test_empty_sample_returns_zero_with_provenance() -> None:
    result = compute_premium(
        ["A"],
        {"A": _obs("10.00", "2026-08-13T07:00:00.000Z")},
        {},
        decision_time=_DECISION,
        suspended={"A"},
    )
    assert result.sample_size == 0
    assert result.average_premium == Decimal("0")
    assert result.provenance.sample_size == 0
    assert result.provenance.excluded["A"] == "suspended"


def test_premium_result_carries_version_and_provenance() -> None:
    result = compute_premium(
        ["A"],
        {"A": _obs("10.00", "2026-08-13T07:00:00.000Z")},
        {"A": _obs("11.00", "2026-08-14T01:30:00.000Z")},
        decision_time=_DECISION,
    )
    assert result.version == PREMIUM_VERSION
    assert result.provenance.algorithm_version == PREMIUM_VERSION
    assert result.provenance.as_of == _DECISION.isoformat()
    assert result.provenance.included == ("A",)
    assert result.provenance.sample_size == 1
    assert "evt-1" in result.provenance.evidence_ids


def test_sample_unavailable_at_decision_time_is_excluded() -> None:
    pool = ["A", "B", "C"]
    yesterday_close = {
        "A": _obs("10.00", "2026-08-13T07:00:00.000Z"),
        "B": _obs("10.00", "2026-08-13T07:00:00.000Z"),
        "C": _obs("10.00", "2026-08-13T07:00:00.000Z"),
    }
    today_price = {
        "A": _obs("11.00", "2026-08-14T01:00:00.000Z"),
        "B": _obs("9.50", "2026-08-14T01:20:00.000Z"),
        "C": _obs("10.50", "2026-08-14T05:00:00.000Z"),  # leaks after decision
    }

    result = compute_premium(
        pool,
        yesterday_close,
        today_price,
        decision_time=Instant.parse("2026-08-14T01:30:00.000Z"),
    )

    assert result.sample_size == 2  # A and B only
    assert result.provenance.excluded["C"] == "unavailable_at_decision_time"


def test_available_exactly_at_decision_time_is_included() -> None:
    decision = Instant.parse("2026-08-14T01:30:00.000Z")
    result = compute_premium(
        ["A"],
        {"A": _obs("10.00", "2026-08-13T07:00:00.000Z")},
        {"A": _obs("11.00", "2026-08-14T01:30:00.000Z")},  # == decision
        decision_time=decision,
    )
    assert result.sample_size == 1


def test_yesterday_close_unavailable_is_excluded() -> None:
    # The prior close must also be available at the decision time; a close that
    # only becomes available after the decision must not be used.
    result = compute_premium(
        ["A"],
        {"A": _obs("10.00", "2026-08-14T09:00:00.000Z")},  # leaks
        {"A": _obs("11.00", "2026-08-14T01:00:00.000Z")},
        decision_time=Instant.parse("2026-08-14T02:00:00.000Z"),
    )
    assert result.sample_size == 0
    assert result.provenance.excluded["A"] == "unavailable_at_decision_time"


def test_missing_price_is_excluded_fail_closed() -> None:
    result = compute_premium(
        ["A"],
        {"A": _obs("10.00", "2026-08-13T07:00:00.000Z")},
        {},  # no today price -> fail closed, not fabricated
        decision_time=_DECISION,
    )
    assert result.sample_size == 0
    assert result.provenance.excluded["A"] == "missing_price"


def test_high_to_close_drawdown_structured_result() -> None:
    pool = ["A", "B"]
    today_high = {
        "A": _obs("12.00", "2026-08-14T01:30:00.000Z"),
        "B": _obs("10.00", "2026-08-14T01:30:00.000Z"),
    }
    today_close = {
        "A": _obs("11.00", "2026-08-14T01:30:00.000Z"),  # drawdown 1/12
        "B": _obs("9.00", "2026-08-14T01:30:00.000Z"),  # drawdown 1/10
    }

    result = compute_drawdown(pool, today_high, today_close, decision_time=_DECISION)

    # No bare float: a structured, versioned, provenance-carrying result.
    assert isinstance(result.average_drawdown, Decimal)
    expected = (Decimal("1") / Decimal("12") + Decimal("1") / Decimal("10")) / 2
    assert result.average_drawdown == expected
    assert result.provenance.sample_size == 2
    assert result.provenance.included == ("A", "B")


def test_drawdown_high_and_close_availability_independent() -> None:
    # high and close are independent observations; if the close leaks after the
    # decision, that instrument is excluded even when the high is available.
    pool = ["A"]
    today_high = {"A": _obs("12.00", "2026-08-14T01:00:00.000Z")}  # available
    today_close = {"A": _obs("11.00", "2026-08-14T07:00:00.000Z")}  # leaks

    result = compute_drawdown(
        pool,
        today_high,
        today_close,
        decision_time=Instant.parse("2026-08-14T03:00:00.000Z"),
    )
    assert result.average_drawdown == Decimal("0")
    assert result.provenance.excluded["A"] == "unavailable_at_decision_time"
    assert result.provenance.sample_size == 0


def test_premium_requires_decision_time() -> None:
    # decision_time is mandatory; there is no default pass-through that would
    # silently admit future data.
    with pytest.raises(TypeError):
        compute_premium(  # type: ignore[call-arg]
            ["A"],
            {"A": _obs("10.00", "2026-08-13T07:00:00.000Z")},
            {"A": _obs("11.00", "2026-08-14T01:00:00.000Z")},
        )
