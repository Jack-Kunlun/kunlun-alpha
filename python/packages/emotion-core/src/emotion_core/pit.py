"""Point-in-time value objects for the emotion engine.

Two boundary primitives make point-in-time correctness explicit and hard to
misuse:

``Instant``
    A timezone-aware moment normalized to a canonical UTC instant. Naive or
    malformed timestamps are rejected at parse time, so every internal
    comparison, identity key, dedupe and first/last-seal computation operates on
    a single unambiguous representation. Equivalent representations of the same
    moment (``06:30-05:00`` and ``11:30Z``) compare equal, hash equal and sort
    together.

``PriceObservation``
    A :class:`~decimal.Decimal` value bound to its event and availability
    instants plus ``source`` / ``source_version`` / ``evidence_id`` provenance.
    ``available_at`` answers whether the observation may be used at a decision
    instant (inclusive of an exactly-equal boundary), so downstream code never
    consumes a value that leaks after the decision time and never uses an
    unattributed value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from functools import total_ordering


@total_ordering
@dataclass(frozen=True)
class Instant:
    """A timezone-aware moment normalized to UTC.

    Construct via :meth:`parse` (from an ISO 8601 string) or :meth:`from_datetime`
    (from an aware :class:`datetime`). Ordering, equality and hashing all use the
    canonical UTC instant, so mixed-offset representations of the same moment are
    treated as one event.
    """

    _utc: datetime

    @classmethod
    def parse(cls, value: object) -> Instant:
        """Parse an ISO 8601 string into a canonical UTC instant.

        Rejects ``None``, non-strings, malformed strings and naive datetimes
        (no timezone offset) — availability decisions must never rely on an
        ambiguous local time.
        """
        if not isinstance(value, str):
            raise ValueError("timestamp must be an ISO 8601 string")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"invalid timestamp: {value!r}") from exc
        return cls.from_datetime(parsed)

    @classmethod
    def from_datetime(cls, value: datetime) -> Instant:
        """Normalize an aware :class:`datetime` to a canonical UTC instant."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone required: naive datetime is rejected")
        return cls(value.astimezone(UTC))

    def as_utc(self) -> datetime:
        """Return the canonical UTC :class:`datetime`."""
        return self._utc

    def isoformat(self) -> str:
        """Return the canonical UTC ISO 8601 representation."""
        return self._utc.isoformat()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Instant):
            return NotImplemented
        return self._utc == other._utc

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Instant):
            return NotImplemented
        return self._utc < other._utc

    def __hash__(self) -> int:
        return hash(self._utc)


@dataclass(frozen=True)
class PriceObservation:
    """A Decimal price bound to its instants and provenance.

    ``value`` is a :class:`~decimal.Decimal`; a binary ``float`` is rejected at
    the boundary. ``event_time`` is when the value refers to; ``available_time``
    is when it became observable. ``source`` / ``source_version`` /
    ``evidence_id`` attribute the value so results stay auditable.
    """

    value: Decimal
    event_time: Instant
    available_time: Instant
    source: str
    source_version: str
    evidence_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _reject_binary_float(self.value))
        if not self.source.strip():
            raise ValueError("source must be non-empty (missing provenance)")
        if not self.source_version.strip():
            raise ValueError("source_version must be non-empty (missing provenance)")
        if not self.evidence_id.strip():
            raise ValueError("evidence_id must be non-empty (missing evidence)")

    def available_at(self, decision_time: Instant) -> bool:
        """Whether this observation may be used at ``decision_time``.

        Inclusive of an exactly-equal boundary: a value available at the same
        instant as the decision is usable.
        """
        return self.available_time <= decision_time


def _reject_binary_float(value: object) -> Decimal:
    """Convert an external numeric value to Decimal without ``Decimal(float)``."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a decimal value")
    if isinstance(value, float):
        raise TypeError("float is not an accepted decimal boundary value")
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc
