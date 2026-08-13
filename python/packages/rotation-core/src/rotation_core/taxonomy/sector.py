"""Sector taxonomy and membership.

Models a sector hierarchy (industry / concept / theme) with aliases, validity
windows and source priority. An instrument can belong to multiple sectors at
once (multi-membership); membership history is retained via validity windows,
and alias conflicts resolve by source priority. Temporary hotspots must never
be written into the fixed industry classification — they belong in THEME
sectors with explicit validity.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Sector:
    """A sector node in the taxonomy."""

    sector_id: str
    name: str
    parent_id: str | None
    kind: str
    source: str
    valid_from: str
    valid_to: str | None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class SectorMembership:
    """An instrument's membership in a sector with a validity window."""

    unified_code: str
    sector_id: str
    valid_from: str
    valid_to: str | None
    source: str


class SectorTaxonomy:
    """Queryable sector taxonomy with alias resolution and source priority."""

    def __init__(
        self,
        sectors: list[Sector],
        memberships: list[SectorMembership],
        source_priority: list[str],
    ) -> None:
        self._sectors = {s.sector_id: s for s in sectors}
        self._priority = {source: i for i, source in enumerate(source_priority)}
        self._memberships = self._dedupe(memberships)

        # Alias/name -> sector ids, ordered by source priority.
        self._alias_index: dict[str, list[str]] = {}
        for sector in sectors:
            names = [sector.name, *sector.aliases]
            for name in names:
                self._alias_index.setdefault(name, []).append(sector.sector_id)
        for name, ids in self._alias_index.items():
            self._alias_index[name] = sorted(
                ids, key=lambda sid: self._priority.get(self._sectors[sid].source, 1 << 30)
            )

    def _dedupe(self, memberships: list[SectorMembership]) -> list[SectorMembership]:
        # Keep the highest-priority source per (unified_code, sector_id).
        best: dict[tuple[str, str], SectorMembership] = {}
        for m in memberships:
            key = (m.unified_code, m.sector_id)
            current = best.get(key)
            if current is None or self._priority.get(m.source, 1 << 30) < self._priority.get(
                current.source, 1 << 30
            ):
                best[key] = m
        return list(best.values())

    def resolve(self, name_or_alias: str) -> str | None:
        """Resolve a name/alias to a sector id (source priority breaks ties)."""
        ids = self._alias_index.get(name_or_alias)
        return ids[0] if ids else None

    def members_of(self, sector_id: str, date: str) -> list[str]:
        """Instruments belonging to a sector on ``date`` (multi-membership)."""
        result: list[str] = []
        for m in self._memberships:
            if m.sector_id != sector_id:
                continue
            if m.valid_from <= date and (m.valid_to is None or date <= m.valid_to):
                result.append(m.unified_code)
        return sorted(result)

    def sectors_of(self, unified_code: str, date: str) -> list[str]:
        """Sectors an instrument belongs to on ``date`` (multi-membership)."""
        result: list[str] = []
        for m in self._memberships:
            if m.unified_code != unified_code:
                continue
            if m.valid_from <= date and (m.valid_to is None or date <= m.valid_to):
                result.append(m.sector_id)
        return sorted(result)

    def history(self, unified_code: str) -> list[SectorMembership]:
        """All membership records (including expired ones) for an instrument."""
        return [m for m in self._memberships if m.unified_code == unified_code]
