"""Board ladder (consecutive limit-up counts) and advancement rates.

Consecutive-board counting walks backwards over a trading-day sequence — never
natural days — so weekends do not break a streak and a suspended day does not
count as a broken board. The snapshot reports the distribution of board counts
and the advancement rate from board N to N+1 (e.g. 1 -> 2).

P2-R01: the snapshot carries an algorithm version and the suspended-day
exclusions that shaped each streak, so results stay auditable.

P2-R01 (round 3): the limit-up history may use typed :class:`LimitUpRecord`
values (carrying source_version / evidence_id / available_time) in place of a
bare bool, so the ladder provenance is traceable back to the exact data that
produced each streak. A bare bool stays supported for compatibility.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from emotion_core.pit import Instant
from emotion_core.provenance import SampleProvenance

LADDER_VERSION = "board_ladder_v1"


@dataclass(frozen=True)
class LimitUpRecord:
    """A traceable limit-up observation for one instrument on one trading day.

    Carries whether the instrument was limit-up plus the source_version /
    evidence_id / available_time provenance, so the board ladder can attribute
    each counted board back to the exact data that produced it.
    """

    is_limit_up: bool
    source_version: str
    evidence_id: str
    available_time: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "available_time", Instant.parse(self.available_time).isoformat())
        if not self.source_version.strip():
            raise ValueError("source_version must be non-empty (missing provenance)")
        if not self.evidence_id.strip():
            raise ValueError("evidence_id must be non-empty (missing evidence)")


def _is_limit_up(value: bool | LimitUpRecord | None) -> bool:
    """Extract the limit-up flag from a bool or a typed record."""
    if value is None:
        return False
    if isinstance(value, LimitUpRecord):
        return value.is_limit_up
    return value


@dataclass(frozen=True)
class BoardLadderSnapshot:
    """Distribution of consecutive limit-up counts plus advancement rates."""

    date: str
    boards: dict[int, list[str]]
    advancement: dict[int, float]
    provenance: SampleProvenance
    exclusions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    version: str = LADDER_VERSION


def consecutive_boards(
    code: str,
    date: str,
    trading_days: list[str],
    limit_up_history: Mapping[str, Mapping[str, bool | LimitUpRecord]],
    suspended: dict[str, set[str]] | None = None,
) -> int:
    """The consecutive limit-up count ending on ``date`` for ``code``.

    Walks backwards over the trading-day sequence; suspended days are skipped
    (they do not break the streak) and the first non-limit-up trading day ends
    the streak.
    """
    suspended_days = (suspended or {}).get(code, set())
    history = limit_up_history.get(code, {})
    if date not in trading_days:
        return 0

    count = 0
    index = trading_days.index(date)
    for day in reversed(trading_days[: index + 1]):
        if day in suspended_days:
            continue
        if _is_limit_up(history.get(day)):
            count += 1
        else:
            break
    return count


def compute_board_ladder(
    date: str,
    trading_days: list[str],
    limit_up_history: Mapping[str, Mapping[str, bool | LimitUpRecord]],
    suspended: dict[str, set[str]] | None = None,
) -> BoardLadderSnapshot:
    """Compute the board ladder and advancement rates for ``date``.

    ``trading_days`` is the ascending trading-day sequence ending at ``date``.
    ``limit_up_history[code][day]`` is whether ``code`` was limit-up that day,
    either as a bare bool or a typed :class:`LimitUpRecord` (which also carries
    the source_version / evidence_id / available_time provenance).
    """
    codes = list(limit_up_history.keys())
    board_counts = {
        code: consecutive_boards(code, date, trading_days, limit_up_history, suspended)
        for code in codes
    }

    # Record, per code, the suspended trading days that fell inside the observed
    # window — these are the exclusions that shaped the streak.
    window = set(trading_days)
    exclusions: dict[str, tuple[str, ...]] = {}
    for code, days in (suspended or {}).items():
        within = tuple(sorted(day for day in days if day in window))
        if within:
            exclusions[code] = within

    boards: dict[int, list[str]] = {}
    for code, count in board_counts.items():
        if count > 0:
            boards.setdefault(count, []).append(code)

    # Structured provenance: instruments on the ladder are included; the rest
    # are excluded with a reason so the sample is fully auditable.
    included = tuple(sorted(code for code, count in board_counts.items() if count > 0))
    excluded = {code: "not_on_ladder" for code, count in board_counts.items() if count == 0}

    # Aggregate the source versions and evidence ids from the typed records that
    # shaped each counted streak, so the ladder is traceable to its inputs.
    source_versions: list[str] = []
    evidence_ids: list[str] = []
    for code in included:
        for value in limit_up_history.get(code, {}).values():
            if isinstance(value, LimitUpRecord) and value.is_limit_up:
                source_versions.append(value.source_version)
                evidence_ids.append(value.evidence_id)

    # Advancement: of the codes with N boards yesterday, how many are limit-up today.
    advancement: dict[int, float] = {}
    if len(trading_days) >= 2:
        yesterday = trading_days[-2]
        today = date
        for n in sorted(boards.keys()):
            yesterday_n = [
                code
                for code in codes
                if consecutive_boards(code, yesterday, trading_days, limit_up_history, suspended)
                == n
            ]
            if not yesterday_n:
                continue
            advanced = sum(
                1 for code in yesterday_n if _is_limit_up(limit_up_history.get(code, {}).get(today))
            )
            advancement[n] = advanced / len(yesterday_n)

    provenance = SampleProvenance(
        algorithm_version=LADDER_VERSION,
        as_of=date,
        included=included,
        excluded=excluded,
        source_versions=tuple(dict.fromkeys(source_versions)),
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
    )

    return BoardLadderSnapshot(
        date=date,
        boards=boards,
        advancement=advancement,
        provenance=provenance,
        exclusions=exclusions,
    )
