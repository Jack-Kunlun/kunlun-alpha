"""Trading calendar tests (Python port of the TS suite).

Driven by the same fixtures file as the TypeScript suite
(packages/contracts/calendar/fixtures.json) so both calendars stay aligned.
Instants are UTC ISO 8601; calendars interpret them in Asia/Shanghai.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TypedDict, cast

import pytest
from market_core.calendar.trading_calendar import (
    DEFAULT_CALENDAR,
    ExchangeId,
    SessionAtResult,
    SessionKind,
    StaticTradingCalendar,
    TradingSession,
)


class ExpectedSession(TypedDict):
    sessionId: str
    date: str


class BoundaryFixture(TypedDict):
    name: str
    instant: str
    exchange: str
    expected: ExpectedSession | None


class NightBoundaryFixture(TypedDict):
    name: str
    instant: str
    expected: ExpectedSession | None


class TradingDayFixture(TypedDict):
    date: str
    exchange: str
    isTradingDay: bool
    reason: str | None


class NextTradingDayFixture(TypedDict):
    date: str
    exchange: str
    expected: str


_FIXTURES = cast(
    dict[str, object],
    json.loads(
        (
            Path(__file__).resolve().parents[4]
            / "packages"
            / "contracts"
            / "calendar"
            / "fixtures.json"
        ).read_text(encoding="utf-8"),
    ),
)


def _instant(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _assert_session(result: SessionAtResult | None, expected: ExpectedSession | None) -> None:
    if expected is None:
        assert result is None
    else:
        assert result is not None
        assert result.session.session_id == expected["sessionId"]
        assert result.date == expected["date"]


def _to_minute(clock: str) -> int:
    hour, minute = clock.split(":")
    return int(hour) * 60 + int(minute)


def _from_json(raw: dict[str, object]) -> TradingSession:
    return TradingSession(
        session_id=str(raw["sessionId"]),
        kind=cast(SessionKind, raw["kind"]),
        start=str(raw["start"]),
        end=str(raw["end"]),
        exchange=cast(ExchangeId, raw["exchange"]),
        crosses_midnight=bool(raw.get("crossesMidnight", False)),
    )


@pytest.mark.parametrize(
    "fixture",
    cast(list[BoundaryFixture], _FIXTURES["boundaries"]),
    ids=lambda f: f["name"],
)
def test_session_at_boundaries(fixture: BoundaryFixture) -> None:
    result = DEFAULT_CALENDAR.session_at(_instant(fixture["instant"]), fixture["exchange"])
    _assert_session(result, fixture["expected"])


def test_cross_midnight_night_calendar() -> None:
    night = cast(dict[str, object], _FIXTURES["nightCalendar"])
    night_calendar = StaticTradingCalendar(
        templates={
            cast(str, night["exchange"]): [
                _from_json(cast(dict[str, object], s))
                for s in cast(list[object], night["sessions"])
            ]
        }
    )
    exchange = cast(str, night["exchange"])
    for fixture in cast(list[NightBoundaryFixture], _FIXTURES["nightBoundaries"]):
        result = night_calendar.session_at(_instant(fixture["instant"]), exchange)
        _assert_session(result, fixture["expected"])


@pytest.mark.parametrize(
    "fixture",
    cast(list[TradingDayFixture], _FIXTURES["tradingDays"]),
    ids=lambda f: f"{f['date']} {f['exchange']}",
)
def test_trading_days(fixture: TradingDayFixture) -> None:
    assert (
        DEFAULT_CALENDAR.is_trading_day(fixture["date"], fixture["exchange"])
        is fixture["isTradingDay"]
    )
    day = DEFAULT_CALENDAR.trading_day(fixture["date"], fixture["exchange"])
    assert day.is_trading_day is fixture["isTradingDay"]
    if fixture.get("reason") is not None:
        assert day.reason == fixture["reason"]


@pytest.mark.parametrize(
    "fixture",
    cast(list[NextTradingDayFixture], _FIXTURES["nextTradingDay"]),
    ids=lambda f: f"{f['date']} {f['exchange']}",
)
def test_next_trading_day(fixture: NextTradingDayFixture) -> None:
    assert (
        DEFAULT_CALENDAR.next_trading_day(fixture["date"], fixture["exchange"])
        == fixture["expected"]
    )


def test_template_integrity() -> None:
    for exchange in ("SH", "SZ", "BJ"):
        sessions = DEFAULT_CALENDAR.sessions_for("2026-08-13", exchange)
        assert len(sessions) > 0
        starts = [_to_minute(s.start) for s in sessions]
        assert starts == sorted(starts)


def test_regular_weekday_is_trading_day() -> None:
    for exchange in ("SH", "SZ", "BJ"):
        assert DEFAULT_CALENDAR.is_trading_day("2026-08-13", exchange)
        assert DEFAULT_CALENDAR.is_trading_day("2026-08-14", exchange)


def test_natural_day_never_substitutes_trading_day() -> None:
    assert not DEFAULT_CALENDAR.is_trading_day("2026-08-15", "SH")  # Saturday
    assert not DEFAULT_CALENDAR.is_trading_day("2026-08-16", "SH")  # Sunday
    assert not DEFAULT_CALENDAR.is_trading_day("2026-01-01", "SZ")  # New Year
