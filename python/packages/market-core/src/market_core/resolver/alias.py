"""Point-in-time alias table (P3-N04).

Aliases express how a security is referenced in text over time. Time
semantics (single source of truth):

* ``available_time`` — when the system knew this alias (system knowledge);
  only ``available_time <= decision_time`` aliases may be used;
* ``effective_from`` / ``effective_to`` — business validity window; the
  reference time must fall inside it.

A later-known alias never leaks into an earlier decision: the caller passes
``decision_time`` and the table filters by it. The wall clock is never used.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from event_core.entities import normalize_surface

from market_core.resolver.models import require_aware


class AliasType(StrEnum):
    """Stable alias kinds consumed by the resolver."""

    SHORT_NAME = "short_name"
    """Official/common short name (e.g. 茅台 -> 600519.SH)."""

    FORMER_NAME = "former_name"
    """Former official name (e.g. 贵州茅台酒股份有限公司 -> old name)."""

    EQUIVALENT_NAME = "equivalent_name"
    """Other accepted equivalent name (e.g. 平安银行 -> 000001.SZ)."""


@dataclass(frozen=True)
class AliasEntry:
    """One immutable, auditable alias record."""

    alias_id: str
    alias: str
    alias_type: AliasType
    target: str
    """Canonical instrument id (unified code), e.g. ``600519.SH``."""

    effective_from: datetime
    effective_to: datetime | None
    """Business validity window; ``None`` means open-ended."""

    available_time: datetime
    """System knowledge time; must be ``<= decision_time`` to be usable."""

    source: str
    version: str
    reliability: int
    """Caller-provided reliability in integer basis points (0..10000)."""

    def __post_init__(self) -> None:
        if not self.alias_id:
            raise ValueError("alias_id must be non-empty")
        if not self.alias:
            raise ValueError("alias must be non-empty")
        if not self.target:
            raise ValueError("target must be non-empty")
        require_aware(self.effective_from, "effective_from")
        if self.effective_to is not None:
            require_aware(self.effective_to, "effective_to")
            if self.effective_to < self.effective_from:
                raise ValueError("effective_to must be >= effective_from")
        require_aware(self.available_time, "available_time")
        if not self.source:
            raise ValueError("source must be non-empty")
        if not self.version:
            raise ValueError("version must be non-empty")
        if type(self.reliability) is not int or not 0 <= self.reliability <= 10000:
            raise ValueError("reliability must be an integer in [0, 10000]")

    def visible_at(self, decision_time: datetime) -> bool:
        """Whether the system knew this alias at ``decision_time``."""
        return self.available_time <= decision_time

    def effective_at(self, reference_time: datetime) -> bool:
        """Whether the alias is business-valid at ``reference_time``."""
        if reference_time < self.effective_from:
            return False
        return not (self.effective_to is not None and reference_time > self.effective_to)


class AliasTable:
    """Immutable, decision-time-filtered alias index.

    Lookups filter by ``available_time <= decision_time`` and by business
    validity at ``reference_time``; nothing else is ever returned.
    """

    def __init__(self, entries: Iterable[AliasEntry]) -> None:
        by_id: dict[str, AliasEntry] = {}
        for entry in entries:
            previous = by_id.get(entry.alias_id)
            if previous is None:
                by_id[entry.alias_id] = entry
                continue
            if previous != entry:
                raise ValueError(f"conflicting duplicate alias_id: {entry.alias_id!r}")
        self._entries = tuple(sorted(by_id.values(), key=lambda entry: entry.alias_id))
        self._by_alias: dict[str, list[AliasEntry]] = {}
        for entry in self._entries:
            self._by_alias.setdefault(normalize_surface(entry.alias), []).append(entry)
        for alias, grouped in self._by_alias.items():
            self._by_alias[alias] = sorted(
                grouped,
                key=lambda e: e.alias_id,
            )

    @property
    def entries(self) -> tuple[AliasEntry, ...]:
        return self._entries

    def lookup(
        self,
        surface: str,
        *,
        decision_time: datetime,
        reference_time: datetime,
    ) -> tuple[AliasEntry, ...]:
        """Aliases matching ``surface`` that are both known and business-valid.

        Empty when no usable alias exists at the given times.
        """
        require_aware(decision_time, "decision_time")
        require_aware(reference_time, "reference_time")
        hits = [
            e
            for e in self._by_alias.get(normalize_surface(surface), ())
            if e.visible_at(decision_time) and e.effective_at(reference_time)
        ]
        return tuple(hits)


__all__ = [
    "AliasEntry",
    "AliasTable",
    "AliasType",
]
