"""As-of instrument universe (P3-N04).

The caller passes Instrument snapshots that the system knew by a given time.
The resolver never fetches data; a snapshot whose ``available_time`` is in
the future is never visible at an earlier ``decision_time``.

Canonical symbol is the repository ``unified_code`` form (``600519.SH``);
vendor-specific symbols are never produced or consumed here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from ashare_contracts import Instrument
from event_core.entities import normalize_surface

from market_core.resolver.models import require_aware


def _snapshot_order_key(snapshot: InstrumentSnapshot) -> tuple[datetime, str, str, str]:
    """Deterministic ordering/selection key for one instrument's snapshots.

    ``(available_time, version, source, unified_code)``: the newest
    availability wins, ties break on version then source. All components are
    value-typed, so selection is stable across hash seeds, input order and
    repeated runs.
    """
    return (
        snapshot.available_time,
        snapshot.version,
        snapshot.source,
        snapshot.instrument.unified_code,
    )


@dataclass(frozen=True)
class InstrumentSnapshot:
    """One immutable record of an instrument known to the system."""

    instrument: Instrument
    available_time: datetime
    """System knowledge time; must be ``<= decision_time`` to be usable."""

    source: str
    version: str

    def __post_init__(self) -> None:
        require_aware(self.available_time, "available_time")
        if not self.source:
            raise ValueError("source must be non-empty")
        if not self.version:
            raise ValueError("version must be non-empty")

    @property
    def instrument_id(self) -> str:
        return self.instrument.unified_code

    @property
    def canonical_symbol(self) -> str:
        return self.instrument.unified_code

    def visible_at(self, decision_time: datetime) -> bool:
        """Whether the system knew this instrument at ``decision_time``."""
        return self.available_time <= decision_time


class InstrumentUniverse:
    """Immutable, canonical-id-indexed as-of snapshot set.

    All snapshots for an instrument id are kept (no flattening to the global
    newest snapshot). ``lookup``/``as_of`` select, per ``decision_time``, the
    newest snapshot whose ``available_time`` is not later than that decision;
    future snapshots are never visible and never shadow older versions.
    """

    def __init__(self, snapshots: Iterable[InstrumentSnapshot]) -> None:
        by_identity: dict[tuple[str, datetime, str, str], InstrumentSnapshot] = {}
        for snapshot in snapshots:
            identity = (
                snapshot.instrument_id,
                snapshot.available_time,
                snapshot.version,
                snapshot.source,
            )
            previous = by_identity.get(identity)
            if previous is None:
                by_identity[identity] = snapshot
                continue
            if previous.instrument != snapshot.instrument:
                raise ValueError(
                    "conflicting Instrument snapshots for "
                    f"{snapshot.instrument_id!r} at {snapshot.available_time!r}"
                )
        self._snapshots = tuple(sorted(by_identity.values(), key=_snapshot_order_key))
        by_id: dict[str, list[InstrumentSnapshot]] = {}
        for snapshot in self._snapshots:
            by_id.setdefault(snapshot.instrument_id, []).append(snapshot)
        for instrument_id, group in by_id.items():
            by_id[instrument_id] = sorted(group, key=_snapshot_order_key)
        self._by_id = by_id

    @property
    def snapshots(self) -> tuple[InstrumentSnapshot, ...]:
        return self._snapshots

    def _visible_group(
        self, instrument_id: str, decision_time: datetime
    ) -> tuple[InstrumentSnapshot, ...]:
        """Snapshots for one id that the system knew by ``decision_time``."""
        require_aware(decision_time, "decision_time")
        return tuple(s for s in self._by_id.get(instrument_id, ()) if s.visible_at(decision_time))

    def lookup(self, instrument_id: str, *, decision_time: datetime) -> InstrumentSnapshot | None:
        """The newest known-as-of snapshot for a canonical instrument id.

        Selects, among all snapshots visible at ``decision_time``, the one
        with the latest ``available_time`` (ties break on version/source).
        Returns ``None`` when the instrument is unknown or only known after
        ``decision_time`` (fail-closed for point-in-time).
        """
        visible = self._visible_group(normalize_surface(instrument_id).upper(), decision_time)
        if not visible:
            return None
        return max(visible, key=_snapshot_order_key)

    def as_of(self, decision_time: datetime) -> tuple[InstrumentSnapshot, ...]:
        """Exactly one newest known-as-of snapshot per instrument id.

        Each instrument id contributes its latest snapshot visible at
        ``decision_time``; ids are returned in canonical (sorted) order so the
        result is stable across input order and hash seeds.
        """
        require_aware(decision_time, "decision_time")
        out: list[InstrumentSnapshot] = []
        for instrument_id in sorted(self._by_id):
            snapshot = self.lookup(instrument_id, decision_time=decision_time)
            if snapshot is not None:
                out.append(snapshot)
        return tuple(out)


__all__ = [
    "InstrumentSnapshot",
    "InstrumentUniverse",
]
