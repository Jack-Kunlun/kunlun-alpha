"""Deterministic, point-in-time seat event-study performance features.

This module deliberately accepts narrow snapshots instead of importing the
market service or its storage implementation.  An adapter may map
``market_core.storage.StoredBar`` and its public ``TradingCalendar`` to these
types before calling :func:`compute_seat_performance`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from seat_core.models import Trade

PERFORMANCE_FEATURE_SCHEMA_VERSION = "seat-performance-feature-v1"
PERFORMANCE_ALGORITHM_VERSION = "seat-performance-algorithm-v1"
PERFORMANCE_POLICY_VERSION = "seat-performance-policy-v1"
DEFAULT_BAR_SCHEMA_VERSION = "daily-bar-v1"

_SEAT_ID_RE = re.compile(r"^seat-[0-9a-f]{64}$")
_INSTRUMENT_ID_RE = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$")


class TradingCalendarProtocol(Protocol):
    """Small public calendar boundary required by the feature calculator."""

    def is_trading_day(self, day: str, exchange: str) -> bool: ...

    def next_trading_day(self, day: str, exchange: str) -> str: ...


class PerformanceStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    INSUFFICIENT_SAMPLES = "INSUFFICIENT_SAMPLES"
    NO_SAMPLES = "NO_SAMPLES"


class ExclusionReason(StrEnum):
    TRADE_AFTER_DECISION = "trade_after_decision"
    NET_NOT_POSITIVE = "net_not_positive"
    NON_TRADING_TRADE_DATE = "non_trading_trade_date"
    MISSING_PRICE = "missing_price"
    SUSPENDED = "suspended"
    NON_POSITIVE_PRICE = "non_positive_price"
    PRICE_POLICY_MISMATCH = "price_policy_mismatch"
    PRICE_SERIES_AMBIGUOUS = "price_series_ambiguous"


class LimitState(StrEnum):
    UNKNOWN = "UNKNOWN"
    NONE = "NONE"
    LIMIT_UP = "LIMIT_UP"
    LIMIT_DOWN = "LIMIT_DOWN"


class PerformanceInputError(ValueError):
    """Fail-closed input error for revision or immutable snapshot corruption."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _require_non_empty(value: str, name: str) -> None:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_aware(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_decimal(value: Decimal, name: str) -> None:
    if type(value) is not Decimal:
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")


def _require_date(value: date, name: str) -> None:
    if type(value) is not date:
        raise TypeError(f"{name} must be date")


def _require_seat_id(value: str) -> None:
    if type(value) is not str or _SEAT_ID_RE.fullmatch(value) is None:
        raise ValueError("seat_id must match seat-[0-9a-f]{64}")


def _require_instrument_id(value: str) -> None:
    if type(value) is not str or _INSTRUMENT_ID_RE.fullmatch(value) is None:
        raise ValueError("instrument_id must use canonical unified code form")


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


@dataclass(frozen=True, slots=True)
class DailyPriceObservation:
    """Immutable PIT daily adjusted close with complete sequence provenance.

    ``replacement_version`` is the storage replacement revision for the same
    semantic bar identity.  The calculator selects the highest visible
    replacement only when every other sequence identity is equal.
    """

    instrument_id: str
    trade_date: date
    event_time: datetime
    close: Decimal
    available_time: datetime
    raw_capture_id: str
    replacement_version: int
    source: str
    source_version: str
    data_version: str
    adjustment: str
    session: str
    schema_version: str
    revision_id: str | None = None
    limit_state: LimitState = LimitState.UNKNOWN
    suspended: bool = False
    interval: str = "DAILY"

    def __post_init__(self) -> None:
        _require_instrument_id(self.instrument_id)
        _require_date(self.trade_date, "trade_date")
        _require_aware(self.event_time, "event_time")
        _require_decimal(self.close, "close")
        _require_aware(self.available_time, "available_time")
        for name in (
            "raw_capture_id",
            "source",
            "source_version",
            "data_version",
            "adjustment",
            "session",
            "schema_version",
            "interval",
        ):
            _require_non_empty(getattr(self, name), name)
        if self.revision_id is not None:
            _require_non_empty(self.revision_id, "revision_id")
        if type(self.replacement_version) is not int or self.replacement_version < 1:
            raise ValueError("replacement_version must be a positive integer")
        if type(self.limit_state) is not LimitState:
            raise TypeError("limit_state must be LimitState")
        if type(self.suspended) is not bool:
            raise TypeError("suspended must be bool")


@dataclass(frozen=True, slots=True)
class StyleObservation:
    """Controlled style evidence; no free-text inference is performed."""

    seat_id: str
    observation_id: str
    style_tag: str
    observation_time: datetime
    available_time: datetime
    taxonomy_version: str
    source: str
    source_version: str
    evidence_id: str
    revision_id: str
    previous_revision_id: str | None = None

    def __post_init__(self) -> None:
        _require_seat_id(self.seat_id)
        for name in (
            "observation_id",
            "style_tag",
            "taxonomy_version",
            "source",
            "source_version",
            "evidence_id",
            "revision_id",
        ):
            _require_non_empty(getattr(self, name), name)
        _require_aware(self.observation_time, "observation_time")
        _require_aware(self.available_time, "available_time")
        if self.previous_revision_id is not None:
            _require_non_empty(self.previous_revision_id, "previous_revision_id")
            if self.previous_revision_id == self.revision_id:
                raise ValueError("previous_revision_id must differ from revision_id")


@dataclass(frozen=True, slots=True)
class PerformancePolicy:
    """Versioned calculation and controlled-style policy."""

    policy_version: str = PERFORMANCE_POLICY_VERSION
    algorithm_version: str = PERFORMANCE_ALGORITHM_VERSION
    min_samples: int = 1
    interval: str = "DAILY"
    adjustment: str = "FORWARD_ADJUSTED"
    session: str = "CONTINUOUS"
    bar_schema_version: str = DEFAULT_BAR_SCHEMA_VERSION
    calendar_version: str = "calendar-v1"
    allowed_style_tags: tuple[str, ...] = ()
    taxonomy_version: str = "style-taxonomy-v1"
    min_style_samples: int = 3
    min_style_share: Decimal = Decimal("0.50")

    def __post_init__(self) -> None:
        for name in (
            "policy_version",
            "algorithm_version",
            "interval",
            "adjustment",
            "session",
            "bar_schema_version",
            "calendar_version",
            "taxonomy_version",
        ):
            _require_non_empty(getattr(self, name), name)
        if type(self.min_samples) is not int or self.min_samples < 0:
            raise ValueError("min_samples must be a non-negative integer")
        if type(self.min_style_samples) is not int or self.min_style_samples < 1:
            raise ValueError("min_style_samples must be a positive integer")
        if type(self.allowed_style_tags) is not tuple:
            raise TypeError("allowed_style_tags must be a tuple")
        if len(set(self.allowed_style_tags)) != len(self.allowed_style_tags):
            raise ValueError("allowed_style_tags must not contain duplicates")
        for tag in self.allowed_style_tags:
            _require_non_empty(tag, "allowed_style_tags item")
        _require_decimal(self.min_style_share, "min_style_share")
        if not Decimal("0") <= self.min_style_share <= Decimal("1"):
            raise ValueError("min_style_share must be in [0, 1]")

    @property
    def fingerprint(self) -> str:
        payload = {
            "algorithmVersion": self.algorithm_version,
            "adjustment": self.adjustment,
            "allowedStyleTags": list(self.allowed_style_tags),
            "barSchemaVersion": self.bar_schema_version,
            "calendarVersion": self.calendar_version,
            "interval": self.interval,
            "minSamples": self.min_samples,
            "minStyleSamples": self.min_style_samples,
            "minStyleShare": _decimal_text(self.min_style_share),
            "policyVersion": self.policy_version,
            "session": self.session,
            "taxonomyVersion": self.taxonomy_version,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"

    @property
    def policy_fingerprint(self) -> str:
        return self.fingerprint


@dataclass(frozen=True, slots=True)
class PerformanceRequest:
    seat_id: str
    window_start: date
    window_end: date
    decision_time: datetime
    policy: PerformancePolicy

    def __post_init__(self) -> None:
        _require_seat_id(self.seat_id)
        _require_date(self.window_start, "window_start")
        _require_date(self.window_end, "window_end")
        if self.window_end < self.window_start:
            raise ValueError("window_end must be greater than or equal to window_start")
        _require_aware(self.decision_time, "decision_time")
        if type(self.policy) is not PerformancePolicy:
            raise TypeError("policy must be PerformancePolicy")


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    sample_count: int
    t_plus_1_return: Decimal
    t_plus_3_return: Decimal
    t_plus_5_return: Decimal
    win_rate: Decimal
    max_drawdown: Decimal


@dataclass(frozen=True, slots=True)
class PerformanceSample:
    """One included or excluded event with replayable input provenance."""

    trade_id: str
    trade_lineage_id: str
    trade_revision_id: str
    trade_previous_revision_id: str | None
    trade_source: str
    trade_source_version: str
    trade_raw_record_id: str
    trade_evidence_id: str
    trade_available_time: datetime
    instrument_id: str
    trade_date: date
    included: bool
    exclusion_reason: ExclusionReason | None
    path_dates: tuple[date, ...]
    bars: tuple[DailyPriceObservation, ...]
    event_returns: tuple[Decimal, ...]
    max_drawdown: Decimal | None


@dataclass(frozen=True, slots=True)
class StyleShare:
    style_tag: str
    sample_count: int
    share: Decimal


@dataclass(frozen=True, slots=True)
class StyleExclusion:
    observation_id: str
    revision_id: str
    source: str
    source_version: str
    evidence_id: str
    available_time: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class StylePreferenceFeature:
    style_tags: tuple[str, ...]
    sample_count: int
    taxonomy_version: str
    shares: tuple[StyleShare, ...]
    min_style_samples: int
    min_style_share: Decimal
    policy_fingerprint: str


@dataclass(frozen=True, slots=True)
class SeatPerformanceFeature:
    schema_version: str
    seat_id: str
    window_start: date
    window_end: date
    decision_time: datetime
    logical_available_time: datetime | None
    status: PerformanceStatus
    sample_count: int
    performance: PerformanceMetrics | None
    preference: StylePreferenceFeature | None
    samples: tuple[PerformanceSample, ...]
    style_sample_count: int
    style_observations: tuple[StyleObservation, ...]
    style_exclusions: tuple[StyleExclusion, ...]
    algorithm_version: str
    policy_version: str
    policy_fingerprint: str


@dataclass(frozen=True, slots=True)
class _SelectedTrade:
    trade: Trade
    lineage_id: str


def _select_latest_visible_lineages(entries: Sequence[Trade]) -> tuple[_SelectedTrade, ...]:
    by_revision: dict[str, Trade] = {}
    children: dict[str, list[Trade]] = {}
    for entry in entries:
        if entry.revision_id in by_revision:
            raise PerformanceInputError(
                "duplicate_trade_revision",
                f"duplicate visible trade revision {entry.revision_id!r}",
            )
        by_revision[entry.revision_id] = entry
    for entry in entries:
        previous = entry.previous_revision_id
        if previous is None:
            continue
        predecessor = by_revision.get(previous)
        if predecessor is None:
            raise PerformanceInputError(
                "missing_predecessor",
                f"visible trade revision {entry.revision_id!r} has missing predecessor",
            )
        if predecessor.available_time > entry.available_time:
            raise PerformanceInputError(
                "invalid_revision_order",
                f"trade revision {entry.revision_id!r} is available before its predecessor",
            )
        children.setdefault(previous, []).append(entry)

    for predecessor_id, successors in children.items():
        if len(successors) > 1:
            raise PerformanceInputError(
                "revision_fork",
                f"trade revision fork at {predecessor_id!r}",
            )

    states: dict[str, int] = {}

    def visit(entry: Trade) -> None:
        state = states.get(entry.revision_id, 0)
        if state == 1:
            raise PerformanceInputError(
                "revision_cycle",
                f"trade revision cycle at {entry.revision_id!r}",
            )
        if state == 2:
            return
        states[entry.revision_id] = 1
        if entry.previous_revision_id is not None:
            visit(by_revision[entry.previous_revision_id])
        states[entry.revision_id] = 2

    for entry in entries:
        visit(entry)
    root_by_revision: dict[str, str] = {}

    def root_revision(entry: Trade) -> str:
        known = root_by_revision.get(entry.revision_id)
        if known is not None:
            return known
        current = entry
        visited: set[str] = set()
        while current.previous_revision_id is not None:
            if current.revision_id in visited:
                raise PerformanceInputError(
                    "revision_cycle",
                    f"trade revision cycle at {current.revision_id!r}",
                )
            visited.add(current.revision_id)
            current = by_revision[current.previous_revision_id]
        root_by_revision[entry.revision_id] = current.revision_id
        return current.revision_id

    components: dict[str, list[Trade]] = {}
    for entry in entries:
        components.setdefault(root_revision(entry), []).append(entry)

    selected: list[_SelectedTrade] = []
    for root_id, component in components.items():
        terminals = tuple(entry for entry in component if not children.get(entry.revision_id))
        if len(terminals) != 1:
            raise PerformanceInputError(
                "duplicate_latest",
                f"multiple latest visible trade revisions for root {root_id!r}",
            )
        selected.append(
            _SelectedTrade(
                trade=terminals[0],
                lineage_id=f"{terminals[0].source}:{root_id}",
            )
        )
    return tuple(
        sorted(
            selected,
            key=lambda item: (
                item.trade.trade_date,
                item.trade.instrument_id,
                item.trade.trade_id,
                item.lineage_id,
            ),
        )
    )


def _select_latest_trades(
    trades: Iterable[Trade],
    decision_time: datetime,
) -> tuple[_SelectedTrade, ...]:
    groups: dict[str, list[Trade]] = {}
    for trade in trades:
        if type(trade) is not Trade:
            raise TypeError("trades must contain Trade instances")
        groups.setdefault(trade.source, []).append(trade)

    selected: list[_SelectedTrade] = []
    for source in sorted(groups):
        visible = tuple(
            sorted(
                (entry for entry in groups[source] if entry.available_time <= decision_time),
                key=lambda item: (item.available_time, item.revision_id),
            )
        )
        if not visible:
            continue
        selected.extend(_select_latest_visible_lineages(visible))
    return tuple(selected)


def _path_dates(
    trade: Trade,
    calendar: TradingCalendarProtocol,
) -> tuple[date, ...] | None:
    exchange = trade.instrument_id.rsplit(".", maxsplit=1)[1]
    if not calendar.is_trading_day(trade.trade_date.isoformat(), exchange):
        return None
    dates = [trade.trade_date]
    for _ in range(5):
        previous_day = dates[-1]
        next_day = calendar.next_trading_day(previous_day.isoformat(), exchange)
        try:
            next_date = date.fromisoformat(next_day)
        except ValueError as exc:
            raise PerformanceInputError(
                "invalid_calendar",
                f"calendar returned invalid date {next_day!r}",
            ) from exc
        if next_date <= previous_day:
            raise PerformanceInputError(
                "invalid_calendar",
                "calendar next_trading_day must be strictly later",
            )
        if not calendar.is_trading_day(next_day, exchange):
            raise PerformanceInputError(
                "invalid_calendar",
                f"calendar returned a non-trading day {next_day!r}",
            )
        dates.append(next_date)
    return tuple(dates)


def _price_sequence_key(
    bar: DailyPriceObservation,
) -> tuple[str, str, str, str, str, str, str]:
    return (
        bar.source,
        bar.source_version,
        bar.data_version,
        bar.interval,
        bar.adjustment,
        bar.session,
        bar.schema_version,
    )


def _semantic_bar_key(
    bar: DailyPriceObservation,
) -> tuple[str, str, str, str, str, str, str, str, str]:
    return (
        bar.instrument_id,
        bar.event_time.isoformat(),
        bar.interval,
        bar.adjustment,
        bar.session,
        bar.source,
        bar.source_version,
        bar.data_version,
        bar.schema_version,
    )


def _matches_policy(bar: DailyPriceObservation, policy: PerformancePolicy) -> bool:
    return (
        bar.interval == policy.interval
        and bar.adjustment == policy.adjustment
        and bar.session == policy.session
        and bar.schema_version == policy.bar_schema_version
    )


def _select_price_path(
    trade: Trade,
    path_dates: tuple[date, ...],
    prices: Sequence[DailyPriceObservation],
    request: PerformanceRequest,
) -> tuple[tuple[DailyPriceObservation, ...], ExclusionReason | None]:
    by_date: dict[date, list[DailyPriceObservation]] = {day: [] for day in path_dates}
    for bar in prices:
        if (
            bar.instrument_id == trade.instrument_id
            and bar.trade_date in by_date
            and bar.available_time <= request.decision_time
        ):
            by_date[bar.trade_date].append(bar)

    if any(not rows for rows in by_date.values()):
        return (), ExclusionReason.MISSING_PRICE

    selected: list[DailyPriceObservation] = []
    for day in path_dates:
        rows = by_date[day]
        matching = [row for row in rows if _matches_policy(row, request.policy)]
        if not matching:
            if any(
                _matches_policy(row, request.policy)
                for values in by_date.values()
                for row in values
            ):
                return (), ExclusionReason.PRICE_SERIES_AMBIGUOUS
            return (), ExclusionReason.PRICE_POLICY_MISMATCH
        keys = {_price_sequence_key(row) for row in matching}
        if len(keys) != 1:
            return (), ExclusionReason.PRICE_SERIES_AMBIGUOUS
        semantic_keys = {_semantic_bar_key(row) for row in matching}
        if len(semantic_keys) != 1:
            return (), ExclusionReason.PRICE_SERIES_AMBIGUOUS
        highest_version = max(row.replacement_version for row in matching)
        highest = [row for row in matching if row.replacement_version == highest_version]
        if len(highest) != 1:
            return (), ExclusionReason.PRICE_SERIES_AMBIGUOUS
        selected.append(highest[0])

    if len({_price_sequence_key(row) for row in selected}) != 1:
        return (), ExclusionReason.PRICE_SERIES_AMBIGUOUS
    for bar in selected:
        if bar.suspended:
            return (), ExclusionReason.SUSPENDED
        if bar.close <= 0:
            return (), ExclusionReason.NON_POSITIVE_PRICE
    return tuple(selected), None


def _event_returns(bars: Sequence[DailyPriceObservation]) -> tuple[Decimal, ...]:
    start = bars[0].close
    return tuple(bar.close / start - Decimal("1") for bar in bars[1:])


def _path_max_drawdown(bars: Sequence[DailyPriceObservation]) -> Decimal:
    peak = bars[0].close
    worst = Decimal("0")
    for bar in bars:
        if bar.close > peak:
            peak = bar.close
        drawdown = bar.close / peak - Decimal("1")
        if drawdown < worst:
            worst = drawdown
    return worst


def _excluded_sample(
    trade: Trade,
    lineage_id: str,
    reason: ExclusionReason,
    path_dates: tuple[date, ...] = (),
) -> PerformanceSample:
    return PerformanceSample(
        trade_id=trade.trade_id,
        trade_lineage_id=lineage_id,
        trade_revision_id=trade.revision_id,
        trade_previous_revision_id=trade.previous_revision_id,
        trade_source=trade.source,
        trade_source_version=trade.source_version,
        trade_raw_record_id=trade.raw_record_id,
        trade_evidence_id=trade.evidence_id,
        trade_available_time=trade.available_time,
        instrument_id=trade.instrument_id,
        trade_date=trade.trade_date,
        included=False,
        exclusion_reason=reason,
        path_dates=path_dates,
        bars=(),
        event_returns=(),
        max_drawdown=None,
    )


def _select_latest_visible_style(entries: Sequence[StyleObservation]) -> StyleObservation:
    by_revision: dict[str, StyleObservation] = {}
    children: dict[str, list[StyleObservation]] = {}
    for entry in entries:
        if entry.revision_id in by_revision:
            raise PerformanceInputError(
                "duplicate_style_revision",
                f"duplicate visible style revision {entry.revision_id!r}",
            )
        by_revision[entry.revision_id] = entry
    for entry in entries:
        previous = entry.previous_revision_id
        if previous is None:
            continue
        predecessor = by_revision.get(previous)
        if predecessor is None:
            raise PerformanceInputError(
                "missing_style_predecessor",
                f"visible style revision {entry.revision_id!r} has missing predecessor",
            )
        if predecessor.available_time > entry.available_time:
            raise PerformanceInputError(
                "invalid_style_revision_order",
                f"style revision {entry.revision_id!r} is available before its predecessor",
            )
        children.setdefault(previous, []).append(entry)
    for predecessor_id, successors in children.items():
        if len(successors) > 1:
            raise PerformanceInputError(
                "style_revision_fork",
                f"style revision fork at {predecessor_id!r}",
            )

    states: dict[str, int] = {}

    def visit(entry: StyleObservation) -> None:
        state = states.get(entry.revision_id, 0)
        if state == 1:
            raise PerformanceInputError(
                "style_revision_cycle",
                f"style revision cycle at {entry.revision_id!r}",
            )
        if state == 2:
            return
        states[entry.revision_id] = 1
        if entry.previous_revision_id is not None:
            visit(by_revision[entry.previous_revision_id])
        states[entry.revision_id] = 2

    for entry in entries:
        visit(entry)
    terminals = tuple(entry for entry in entries if not children.get(entry.revision_id))
    if len(terminals) != 1:
        raise PerformanceInputError(
            "duplicate_style_latest",
            "multiple latest visible style revisions",
        )
    return terminals[0]


def _style_features(
    request: PerformanceRequest,
    observations: Iterable[StyleObservation],
) -> tuple[
    StylePreferenceFeature | None,
    int,
    tuple[StyleObservation, ...],
    tuple[StyleExclusion, ...],
]:
    groups: dict[tuple[str, str], list[StyleObservation]] = {}
    for observation in observations:
        if type(observation) is not StyleObservation:
            raise TypeError("style_observations must contain StyleObservation instances")
        if observation.seat_id == request.seat_id:
            groups.setdefault((observation.source, observation.observation_id), []).append(
                observation
            )

    included: list[StyleObservation] = []
    exclusions: list[StyleExclusion] = []
    for key in sorted(groups):
        visible = tuple(
            sorted(
                (
                    observation
                    for observation in groups[key]
                    if observation.available_time <= request.decision_time
                ),
                key=lambda item: (item.available_time, item.revision_id),
            )
        )
        if not visible:
            continue
        observation = _select_latest_visible_style(visible)
        observation_day = observation.observation_time.date()
        if not request.window_start <= observation_day <= request.window_end:
            exclusions.append(
                StyleExclusion(
                    observation_id=observation.observation_id,
                    revision_id=observation.revision_id,
                    source=observation.source,
                    source_version=observation.source_version,
                    evidence_id=observation.evidence_id,
                    available_time=observation.available_time,
                    reason="style_outside_window",
                )
            )
            continue
        if observation.taxonomy_version != request.policy.taxonomy_version:
            exclusions.append(
                StyleExclusion(
                    observation_id=observation.observation_id,
                    revision_id=observation.revision_id,
                    source=observation.source,
                    source_version=observation.source_version,
                    evidence_id=observation.evidence_id,
                    available_time=observation.available_time,
                    reason="taxonomy_version_mismatch",
                )
            )
            continue
        if observation.style_tag not in request.policy.allowed_style_tags:
            exclusions.append(
                StyleExclusion(
                    observation_id=observation.observation_id,
                    revision_id=observation.revision_id,
                    source=observation.source,
                    source_version=observation.source_version,
                    evidence_id=observation.evidence_id,
                    available_time=observation.available_time,
                    reason="unknown_style_tag",
                )
            )
            continue
        included.append(observation)

    counts = {tag: 0 for tag in request.policy.allowed_style_tags}
    for observation in included:
        counts[observation.style_tag] += 1
    sample_count = len(included)
    shares = tuple(
        StyleShare(
            style_tag=tag,
            sample_count=counts[tag],
            share=(Decimal(counts[tag]) / Decimal(sample_count) if sample_count else Decimal("0")),
        )
        for tag in request.policy.allowed_style_tags
    )
    tags = tuple(
        share.style_tag
        for share in shares
        if share.sample_count > 0 and share.share >= request.policy.min_style_share
    )
    preference = None
    if sample_count >= request.policy.min_style_samples and tags:
        preference = StylePreferenceFeature(
            style_tags=tags,
            sample_count=sample_count,
            taxonomy_version=request.policy.taxonomy_version,
            shares=shares,
            min_style_samples=request.policy.min_style_samples,
            min_style_share=request.policy.min_style_share,
            policy_fingerprint=request.policy.fingerprint,
        )
    return preference, sample_count, tuple(included), tuple(exclusions)


def compute_seat_performance(
    request: PerformanceRequest,
    trades: Iterable[Trade],
    prices: Iterable[DailyPriceObservation],
    *,
    calendar: TradingCalendarProtocol,
    style_observations: Iterable[StyleObservation] = (),
) -> SeatPerformanceFeature:
    """Compute a strictly PIT event-study feature for one seat and window.

    The caller supplies an immutable snapshot.  Every trade and bar used must
    have ``available_time <= request.decision_time``; bars are selected only
    from one explicit daily adjusted sequence.
    """

    price_snapshot = tuple(prices)
    if any(type(bar) is not DailyPriceObservation for bar in price_snapshot):
        raise TypeError("prices must contain DailyPriceObservation instances")
    selected = _select_latest_trades(trades, request.decision_time)
    samples: list[PerformanceSample] = []
    for selected_trade in selected:
        trade = selected_trade.trade
        lineage_id = selected_trade.lineage_id
        if trade.seat_id != request.seat_id:
            continue
        if not request.window_start <= trade.trade_date <= request.window_end:
            continue
        if trade.net_amount <= 0:
            samples.append(_excluded_sample(trade, lineage_id, ExclusionReason.NET_NOT_POSITIVE))
            continue
        path_dates = _path_dates(trade, calendar)
        if path_dates is None:
            samples.append(
                _excluded_sample(trade, lineage_id, ExclusionReason.NON_TRADING_TRADE_DATE)
            )
            continue
        bars, reason = _select_price_path(trade, path_dates, price_snapshot, request)
        if reason is not None:
            samples.append(_excluded_sample(trade, lineage_id, reason, path_dates))
            continue
        returns = _event_returns(bars)
        samples.append(
            PerformanceSample(
                trade_id=trade.trade_id,
                trade_lineage_id=lineage_id,
                trade_revision_id=trade.revision_id,
                trade_previous_revision_id=trade.previous_revision_id,
                trade_source=trade.source,
                trade_source_version=trade.source_version,
                trade_raw_record_id=trade.raw_record_id,
                trade_evidence_id=trade.evidence_id,
                trade_available_time=trade.available_time,
                instrument_id=trade.instrument_id,
                trade_date=trade.trade_date,
                included=True,
                exclusion_reason=None,
                path_dates=path_dates,
                bars=bars,
                event_returns=returns,
                max_drawdown=_path_max_drawdown(bars),
            )
        )

    ordered_samples = tuple(
        sorted(samples, key=lambda item: (item.trade_date, item.instrument_id, item.trade_id))
    )
    included = tuple(sample for sample in ordered_samples if sample.included)
    sample_count = len(included)
    performance: PerformanceMetrics | None = None
    if sample_count >= request.policy.min_samples and sample_count > 0:
        performance = PerformanceMetrics(
            sample_count=sample_count,
            t_plus_1_return=sum((sample.event_returns[0] for sample in included), Decimal("0"))
            / Decimal(sample_count),
            t_plus_3_return=sum((sample.event_returns[2] for sample in included), Decimal("0"))
            / Decimal(sample_count),
            t_plus_5_return=sum((sample.event_returns[4] for sample in included), Decimal("0"))
            / Decimal(sample_count),
            win_rate=Decimal(sum(sample.event_returns[4] > 0 for sample in included))
            / Decimal(sample_count),
            max_drawdown=min(
                (sample.max_drawdown for sample in included if sample.max_drawdown is not None),
                default=Decimal("0"),
            ),
        )

    preference, style_sample_count, style_inputs, style_exclusions = _style_features(
        request, style_observations
    )
    if performance is None:
        preference = None
    contributing_times = [
        timestamp
        for sample in included
        for timestamp in (
            sample.trade_available_time,
            *(bar.available_time for bar in sample.bars),
        )
    ]
    contributing_times.extend(observation.available_time for observation in style_inputs)
    logical_available_time = max(contributing_times) if contributing_times else None
    status = (
        PerformanceStatus.NO_SAMPLES
        if sample_count == 0
        else PerformanceStatus.INSUFFICIENT_SAMPLES
        if performance is None
        else PerformanceStatus.PUBLISHED
    )
    return SeatPerformanceFeature(
        schema_version=PERFORMANCE_FEATURE_SCHEMA_VERSION,
        seat_id=request.seat_id,
        window_start=request.window_start,
        window_end=request.window_end,
        decision_time=request.decision_time,
        logical_available_time=logical_available_time,
        status=status,
        sample_count=sample_count,
        performance=performance,
        preference=preference,
        samples=ordered_samples,
        style_sample_count=style_sample_count,
        style_observations=style_inputs,
        style_exclusions=style_exclusions,
        algorithm_version=request.policy.algorithm_version,
        policy_version=request.policy.policy_version,
        policy_fingerprint=request.policy.fingerprint,
    )


__all__ = [
    "DailyPriceObservation",
    "ExclusionReason",
    "LimitState",
    "PERFORMANCE_ALGORITHM_VERSION",
    "PERFORMANCE_FEATURE_SCHEMA_VERSION",
    "PERFORMANCE_POLICY_VERSION",
    "PerformanceInputError",
    "PerformanceMetrics",
    "PerformancePolicy",
    "PerformanceRequest",
    "PerformanceSample",
    "PerformanceStatus",
    "SeatPerformanceFeature",
    "StyleObservation",
    "StyleExclusion",
    "StylePreferenceFeature",
    "StyleShare",
    "TradingCalendarProtocol",
    "compute_seat_performance",
]
