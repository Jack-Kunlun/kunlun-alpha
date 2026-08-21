"""Board ladder (consecutive limit-up counts) and advancement rates.

``board_ladder_v2`` is the public migration boundary: ladder history accepts
only :class:`LimitUpRecord`, every calculation requires an :class:`Instant`
``decision_time``, and ``provenance.as_of`` is that canonical decision instant.
Missing or future records are excluded explicitly rather than being interpreted
as either a true or a false limit-up observation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from emotion_core.pit import Instant
from emotion_core.provenance import SampleProvenance

LADDER_VERSION = "board_ladder_v2"


def _runtime_value(value: object) -> object:
    """Preserve runtime validation for fields that also have static types."""
    return value


@dataclass(frozen=True)
class LimitUpRecord:
    """A traceable point-in-time limit-up observation."""

    is_limit_up: bool
    event_time: Instant
    available_time: Instant
    source_version: str
    evidence_id: str

    def __post_init__(self) -> None:
        is_limit_up = _runtime_value(self.is_limit_up)
        event_time = _runtime_value(self.event_time)
        available_time = _runtime_value(self.available_time)
        source_version = _runtime_value(self.source_version)
        evidence_id = _runtime_value(self.evidence_id)

        if not isinstance(is_limit_up, bool):
            raise TypeError("is_limit_up must be a bool")
        if not isinstance(event_time, Instant):
            raise TypeError("event_time must be an Instant")
        if not isinstance(available_time, Instant):
            raise TypeError("available_time must be an Instant")
        if event_time > available_time:
            raise ValueError("event_time must be <= available_time")
        if not isinstance(source_version, str) or not source_version.strip():
            raise ValueError("source_version must be non-empty (missing provenance)")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ValueError("evidence_id must be non-empty (missing evidence)")


@dataclass(frozen=True)
class BoardLadderSnapshot:
    """Distribution of consecutive limit-up counts plus advancement rates."""

    date: str
    boards: dict[int, list[str]]
    advancement: dict[int, float]
    provenance: SampleProvenance
    exclusions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    version: str = LADDER_VERSION


def _require_decision_time(value: object) -> Instant:
    if not isinstance(value, Instant):
        raise TypeError("decision_time must be an Instant")
    return value


def _require_record(value: object) -> LimitUpRecord:
    if not isinstance(value, LimitUpRecord):
        raise TypeError("limit_up_history values must be LimitUpRecord")
    return value


def _validate_history(limit_up_history: Mapping[str, Mapping[str, LimitUpRecord]]) -> None:
    for records in limit_up_history.values():
        for value in records.values():
            _require_record(value)


def _availability_reason(record: LimitUpRecord, decision_time: Instant) -> str | None:
    if record.event_time > decision_time:
        return "event_after_decision_time"
    if record.available_time > decision_time:
        return "not_available_at_decision_time"
    return None


def _streak_info(
    code: str,
    date: str,
    trading_days: list[str],
    limit_up_history: Mapping[str, Mapping[str, LimitUpRecord]],
    decision_time: Instant,
    suspended: dict[str, set[str]] | None,
) -> tuple[int, dict[str, LimitUpRecord], dict[str, str]]:
    """Return streak count, records used, and unavailable-day reasons."""
    suspended_days = (suspended or {}).get(code, set())
    history = limit_up_history.get(code, {})
    if date not in trading_days:
        return 0, {}, {}

    count = 0
    used: dict[str, LimitUpRecord] = {}
    unavailable: dict[str, str] = {}
    index = trading_days.index(date)
    for day in reversed(trading_days[: index + 1]):
        if day in suspended_days:
            continue
        value = history.get(day)
        if value is None:
            unavailable[day] = "missing_at_decision_time"
            break
        record = _require_record(value)
        reason = _availability_reason(record, decision_time)
        if reason is not None:
            unavailable[day] = reason
            break
        used[day] = record
        if not record.is_limit_up:
            break
        count += 1
    return count, used, unavailable


def consecutive_boards(
    code: str,
    date: str,
    trading_days: list[str],
    limit_up_history: Mapping[str, Mapping[str, LimitUpRecord]],
    suspended: dict[str, set[str]] | None = None,
    *,
    decision_time: Instant,
) -> int:
    """Return the point-in-time consecutive limit-up count ending on ``date``.

    Suspended days are skipped. A typed record whose event or availability is
    after ``decision_time`` is also skipped and therefore is neither true nor
    false for the streak.
    """
    decision = _require_decision_time(decision_time)
    _validate_history(limit_up_history)
    count, _, _ = _streak_info(
        code,
        date,
        trading_days,
        limit_up_history,
        decision,
        suspended,
    )
    return count


def compute_board_ladder(
    date: str,
    trading_days: list[str],
    limit_up_history: Mapping[str, Mapping[str, LimitUpRecord]],
    suspended: dict[str, set[str]] | None = None,
    *,
    decision_time: Instant,
) -> BoardLadderSnapshot:
    """Compute the v2 ladder at the mandatory point-in-time decision boundary.

    ``limit_up_history`` must contain only :class:`LimitUpRecord` values, and
    the snapshot's ``provenance.as_of`` is the canonical ``decision_time``.
    """
    decision = _require_decision_time(decision_time)
    _validate_history(limit_up_history)
    codes = sorted(limit_up_history)

    board_counts: dict[str, int] = {}
    used_records: dict[tuple[str, str], LimitUpRecord] = {}
    unavailable: dict[tuple[str, str], str] = {}

    def record_streak(code: str, day: str) -> int:
        count, used, unavailable_days = _streak_info(
            code,
            day,
            trading_days,
            limit_up_history,
            decision,
            suspended,
        )
        for record_day, record in used.items():
            used_records[(code, record_day)] = record
        for unavailable_day, reason in unavailable_days.items():
            unavailable[(code, unavailable_day)] = reason
        return count

    for code in codes:
        board_counts[code] = record_streak(code, date)

    boards: dict[int, list[str]] = {}
    for code, count in board_counts.items():
        if count > 0:
            boards.setdefault(count, []).append(code)

    window = set(trading_days)
    exclusions: dict[str, tuple[str, ...]] = {}
    for code, days in (suspended or {}).items():
        within = tuple(sorted(day for day in days if day in window))
        if within:
            exclusions[code] = within

    # Advancement uses the same point-in-time filter as the current streak.
    advancement: dict[int, float] = {}
    if len(trading_days) >= 2:
        yesterday = trading_days[-2]
        today = date
        denominators: dict[int, int] = {}
        numerators: dict[int, int] = {}
        for code in codes:
            yesterday_count = record_streak(code, yesterday)
            if yesterday_count <= 0:
                continue

            today_record = limit_up_history.get(code, {}).get(today)
            if today_record is None:
                unavailable[(code, today)] = "missing_at_decision_time"
                continue

            record = _require_record(today_record)
            reason = _availability_reason(record, decision)
            if reason is not None:
                unavailable[(code, today)] = reason
                continue

            denominators[yesterday_count] = denominators.get(yesterday_count, 0) + 1
            used_records[(code, today)] = record
            if record.is_limit_up:
                numerators[yesterday_count] = numerators.get(yesterday_count, 0) + 1

        for board_count, denominator in denominators.items():
            if denominator:
                advancement[board_count] = numerators.get(board_count, 0) / denominator

    included = tuple(sorted(code for code, count in board_counts.items() if count > 0))
    excluded = {code: "not_on_ladder" for code, count in board_counts.items() if count == 0}
    for (code, day), reason in sorted(unavailable.items()):
        excluded[f"{code}:{day}"] = reason

    provenance_records = [
        record
        for _, record in sorted(
            used_records.items(),
            key=lambda item: (item[1].event_time, item[0][0], item[0][1]),
        )
    ]
    provenance = SampleProvenance(
        algorithm_version=LADDER_VERSION,
        as_of=decision.isoformat(),
        included=included,
        excluded=excluded,
        source_versions=tuple(
            dict.fromkeys(record.source_version for record in provenance_records)
        ),
        evidence_ids=tuple(dict.fromkeys(record.evidence_id for record in provenance_records)),
    )

    return BoardLadderSnapshot(
        date=date,
        boards=boards,
        advancement=advancement,
        provenance=provenance,
        exclusions=exclusions,
    )
