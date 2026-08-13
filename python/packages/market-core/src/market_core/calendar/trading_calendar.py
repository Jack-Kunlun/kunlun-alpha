"""A-share trading calendar.

Python port of the TypeScript calendar in packages/contracts/src/calendar.
Both read the same session templates and seed holidays from
packages/contracts/calendar/ — the single source of truth.

Times are local clock HH:MM in Asia/Shanghai; sessions are half-open
[start, end). A session that crosses midnight (start > end, e.g. a night
session 21:00 -> 02:30) belongs to the trading day on which it starts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol, cast
from zoneinfo import ZoneInfo

ExchangeId = Literal["SH", "SZ", "BJ"]
SessionKind = Literal["CONTINUOUS", "OPEN_AUCTION", "CLOSE_AUCTION", "BREAK", "NIGHT"]
HolidayReason = Literal["PUBLIC_HOLIDAY", "TEMPORARY_CLOSURE", "SPECIAL"]
NonTradingReason = Literal["WEEKEND", "PUBLIC_HOLIDAY", "TEMPORARY_CLOSURE", "SPECIAL"]

MARKET_TIMEZONE = "Asia/Shanghai"
_TZ = ZoneInfo(MARKET_TIMEZONE)

_CONTRACTS_DIR = Path(__file__).resolve().parents[6] / "packages" / "contracts" / "calendar"


@dataclass(frozen=True)
class TradingSession:
    """A named time interval within a trading day."""

    session_id: str
    kind: SessionKind
    start: str
    end: str
    exchange: ExchangeId
    crosses_midnight: bool = False


@dataclass(frozen=True)
class TradingDay:
    """Per-date status record for an exchange."""

    date: str
    exchange: ExchangeId
    is_trading_day: bool
    reason: NonTradingReason | None = None
    note: str | None = None


@dataclass(frozen=True)
class Holiday:
    """A scheduled exchange closure (public holiday or ad-hoc closure)."""

    date: str
    exchange: ExchangeId
    reason: HolidayReason
    note: str | None = None


@dataclass(frozen=True)
class SessionAtResult:
    """The session containing an instant and the trading day it belongs to."""

    session: TradingSession
    date: str


class TradingCalendar(Protocol):
    """Queryable calendar over trading days and sessions.

    Real provider-synced calendars (P1-N07) must implement the same interface.
    """

    def sessions_for(self, day: str, exchange: str) -> list[TradingSession]: ...

    def is_trading_day(self, day: str, exchange: str) -> bool: ...

    def trading_day(self, day: str, exchange: str) -> TradingDay: ...

    def session_at(self, instant: datetime, exchange: str) -> SessionAtResult | None: ...

    def next_trading_day(self, day: str, exchange: str) -> str: ...


def _to_session(raw: dict[str, object]) -> TradingSession:
    return TradingSession(
        session_id=str(raw["sessionId"]),
        kind=cast(SessionKind, raw["kind"]),
        start=str(raw["start"]),
        end=str(raw["end"]),
        exchange=cast(ExchangeId, raw["exchange"]),
        crosses_midnight=bool(raw.get("crossesMidnight", False)),
    )


def _to_holiday(raw: dict[str, object]) -> Holiday:
    return Holiday(
        date=str(raw["date"]),
        exchange=cast(ExchangeId, raw["exchange"]),
        reason=cast(HolidayReason, raw["reason"]),
        note=raw.get("note"),  # type: ignore[arg-type]
    )


def _load_rules() -> tuple[dict[str, list[TradingSession]], list[Holiday]]:
    with (_CONTRACTS_DIR / "session-templates.json").open(encoding="utf-8") as f:
        templates = json.load(f)
    with (_CONTRACTS_DIR / "holidays.json").open(encoding="utf-8") as f:
        holidays = json.load(f)
    exchange_templates = cast(dict[str, dict[str, object]], templates["exchanges"])
    sessions = {
        key: [
            _to_session(cast(dict[str, object], s)) for s in cast(list[object], value["sessions"])
        ]
        for key, value in exchange_templates.items()
    }
    holiday_models = [
        _to_holiday(cast(dict[str, object], h)) for h in cast(list[object], holidays["holidays"])
    ]
    return sessions, holiday_models


def _to_minutes(clock: str) -> int:
    hour, minute = clock.split(":")
    return int(hour) * 60 + int(minute)


def _add_days(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def _is_weekend(day: str) -> bool:
    return date.fromisoformat(day).weekday() >= 5  # Sat=5, Sun=6


class StaticTradingCalendar:
    """Default in-memory calendar built from shared templates and seed holidays.

    ``templates`` maps an exchange key to its sessions and ``holidays`` is the
    closure list; both default to the shared rule tables in
    packages/contracts/calendar/.
    """

    def __init__(
        self,
        templates: dict[str, list[TradingSession]] | None = None,
        holidays: list[Holiday] | None = None,
    ) -> None:
        default_templates, default_holidays = _load_rules()
        self._templates = templates if templates is not None else default_templates
        effective_holidays = holidays if holidays is not None else default_holidays
        self._holidays_by_key: dict[str, Holiday] = {
            f"{h.date}:{h.exchange}": h for h in effective_holidays
        }

    def sessions_for(self, day: str, exchange: str) -> list[TradingSession]:
        return self._templates.get(exchange, []) if self.is_trading_day(day, exchange) else []

    def is_trading_day(self, day: str, exchange: str) -> bool:
        return not _is_weekend(day) and f"{day}:{exchange}" not in self._holidays_by_key

    def trading_day(self, day: str, exchange: str) -> TradingDay:
        holiday = self._holidays_by_key.get(f"{day}:{exchange}")
        if holiday is not None:
            return TradingDay(
                date=day,
                exchange=cast(ExchangeId, exchange),
                is_trading_day=False,
                reason=holiday.reason,
                note=holiday.note,
            )
        if _is_weekend(day):
            return TradingDay(
                date=day,
                exchange=cast(ExchangeId, exchange),
                is_trading_day=False,
                reason="WEEKEND",
            )
        return TradingDay(date=day, exchange=cast(ExchangeId, exchange), is_trading_day=True)

    def session_at(self, instant: datetime, exchange: str) -> SessionAtResult | None:
        local = instant.astimezone(_TZ)
        day = local.date().isoformat()
        minutes = local.hour * 60 + local.minute
        sessions = self._templates.get(exchange, [])

        # A cross-midnight session belongs to its start trading day: the
        # evening part [start, 24:00) matches the start day, while the early
        # morning part [00:00, end) is matched by the *previous* day below.
        if self.is_trading_day(day, exchange):
            for session in sessions:
                start = _to_minutes(session.start)
                end = _to_minutes(session.end)
                crosses = session.crosses_midnight or start > end
                if crosses:
                    if minutes >= start:
                        return SessionAtResult(session, day)
                elif start <= minutes < end:
                    return SessionAtResult(session, day)

        yesterday = _add_days(day, -1)
        if self.is_trading_day(yesterday, exchange):
            for session in sessions:
                start = _to_minutes(session.start)
                end = _to_minutes(session.end)
                crosses = session.crosses_midnight or start > end
                if crosses and minutes < end:
                    return SessionAtResult(session, yesterday)
        return None

    def next_trading_day(self, day: str, exchange: str) -> str:
        candidate = _add_days(day, 1)
        for _ in range(366):
            if self.is_trading_day(candidate, exchange):
                return candidate
            candidate = _add_days(candidate, 1)
        raise RuntimeError(f"No trading day found within 365 days after {day}")


# The default A-share calendar (SH/SZ/BJ session templates + seed holidays).
DEFAULT_CALENDAR: TradingCalendar = StaticTradingCalendar()
