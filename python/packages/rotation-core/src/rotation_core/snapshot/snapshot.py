"""Sector snapshot computation.

Aggregates a sector's members into a versioned per-minute snapshot: average
change, turnover, breadth (fraction advancing), leader and strength. The
aggregation always uses the member set valid at the snapshot time. Missing
bars (no quote) and abnormal turnover (negative) are skipped, never inferred.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from market_core.models.validators import Bar

SNAPSHOT_VERSION = "sector_snapshot_v1"


@dataclass(frozen=True)
class SectorSnapshot:
    """A point-in-time snapshot of one sector."""

    sector_id: str
    date: str
    timestamp: str
    average_change: float
    turnover: Decimal
    breadth: float
    leader: str | None
    strength: float
    version: str = SNAPSHOT_VERSION


def compute_snapshot(
    sector_id: str,
    date: str,
    timestamp: str,
    members: list[str],
    bars: dict[str, Bar],
    prev_close: dict[str, Decimal],
) -> SectorSnapshot:
    """Compute a sector snapshot from the member set and their bars.

    ``bars`` maps a member code to its bar at ``timestamp``; a missing bar
    means the member has no quote at this instant and is skipped.
    """
    changes: list[Decimal] = []
    turnover = Decimal("0")
    advancing = 0
    leader: str | None = None
    leader_change: Decimal | None = None

    for code in members:
        bar = bars.get(code)
        if bar is None:
            continue  # missing quote
        if bar.amount < 0:
            continue  # abnormal turnover
        reference = prev_close.get(code)
        if reference is None or reference <= 0:
            continue
        change = (bar.close - reference) / reference
        changes.append(change)
        turnover += bar.amount
        if change > 0:
            advancing += 1
        if leader_change is None or change > leader_change:
            leader_change = change
            leader = code

    count = len(changes)
    average_change = sum(changes, Decimal("0")) / count if count else Decimal("0")
    breadth = Decimal(advancing) / count if count else Decimal("0")
    strength = 0.6 * _sigmoid(float(average_change * 20)) + 0.4 * float(breadth)

    return SectorSnapshot(
        sector_id=sector_id,
        date=date,
        timestamp=timestamp,
        average_change=round(float(average_change), 6),
        turnover=turnover,
        breadth=round(float(breadth), 6),
        leader=leader,
        strength=round(strength, 6),
    )


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class SnapshotAggregator:
    """Incremental aggregator: feeds bars one by one, then snapshots.

    Replaying the same bars produces the same snapshot as
    :func:`compute_snapshot`, keeping batch and streaming consistent.
    """

    def __init__(
        self, sector_id: str, date: str, members: list[str], prev_close: dict[str, Decimal]
    ) -> None:
        self._sector_id = sector_id
        self._date = date
        self._members = members
        self._prev_close = prev_close
        self._bars: dict[str, Bar] = {}

    def feed(self, bar: Bar) -> None:
        self._bars[bar.unified_code] = bar

    def snapshot(self, timestamp: str) -> SectorSnapshot:
        return compute_snapshot(
            self._sector_id,
            self._date,
            timestamp,
            self._members,
            self._bars,
            self._prev_close,
        )
