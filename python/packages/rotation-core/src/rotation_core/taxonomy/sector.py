"""Point-in-time sector taxonomy and membership resolution."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from rotation_core.temporal import canonical_instant, parse_date, parse_instant

SectorKind = Literal["INDUSTRY", "CONCEPT", "THEME"]
_CODE_PATTERN = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")


class TaxonomyConflictError(ValueError):
    """Equally authoritative point-in-time records disagree."""


def _non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty")
    return value


def _valid_on(valid_from: str, valid_to: str | None, query_date: str) -> bool:
    return valid_from <= query_date and (valid_to is None or query_date <= valid_to)


@dataclass(frozen=True)
class Sector:
    """A traceable sector definition valid over an explicit interval."""

    sector_id: str
    name: str
    parent_id: str | None
    kind: SectorKind
    source: str
    valid_from: str
    valid_to: str | None
    source_version: str
    available_time: str
    evidence_id: str
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _non_empty(self.sector_id, "sector_id")
        _non_empty(self.name, "name")
        _non_empty(self.source, "source")
        _non_empty(self.source_version, "source_version")
        _non_empty(self.evidence_id, "evidence_id")
        if self.kind not in ("INDUSTRY", "CONCEPT", "THEME"):
            raise ValueError(f"unsupported sector kind: {self.kind!r}")
        parse_date(self.valid_from)
        if self.valid_to is not None:
            parse_date(self.valid_to)
            if self.valid_to < self.valid_from:
                raise ValueError("valid_to must be >= valid_from")
        if self.parent_id is not None:
            _non_empty(self.parent_id, "parent_id")
        if any(not alias.strip() for alias in self.aliases):
            raise ValueError("aliases must be non-empty")
        object.__setattr__(self, "available_time", canonical_instant(self.available_time))


@dataclass(frozen=True)
class SectorMembership:
    """A traceable instrument membership interval."""

    unified_code: str
    sector_id: str
    valid_from: str
    valid_to: str | None
    source: str
    source_version: str
    available_time: str
    evidence_id: str

    def __post_init__(self) -> None:
        if not _CODE_PATTERN.fullmatch(self.unified_code):
            raise ValueError("unified_code must use suffix form such as 600000.SH")
        _non_empty(self.sector_id, "sector_id")
        _non_empty(self.source, "source")
        _non_empty(self.source_version, "source_version")
        _non_empty(self.evidence_id, "evidence_id")
        parse_date(self.valid_from)
        if self.valid_to is not None:
            parse_date(self.valid_to)
            if self.valid_to < self.valid_from:
                raise ValueError("valid_to must be >= valid_from")
        object.__setattr__(self, "available_time", canonical_instant(self.available_time))


class SectorTaxonomy:
    """Interval-aware taxonomy with source-priority resolution at query time."""

    def __init__(
        self,
        sectors: list[Sector],
        memberships: list[SectorMembership],
        source_priority: list[str],
    ) -> None:
        if len(set(source_priority)) != len(source_priority):
            raise ValueError("source_priority must not contain duplicates")
        self._priority = {source: rank for rank, source in enumerate(source_priority)}
        self._sectors = sorted(
            set(sectors),
            key=lambda item: (
                item.sector_id,
                item.valid_from,
                item.available_time,
                item.source,
                item.source_version,
                item.evidence_id,
            ),
        )
        self._memberships = sorted(
            set(memberships),
            key=lambda item: (
                item.unified_code,
                item.sector_id,
                item.valid_from,
                item.available_time,
                item.source,
                item.source_version,
                item.evidence_id,
            ),
        )
        known_sector_ids = {sector.sector_id for sector in self._sectors}
        unknown = sorted({item.sector_id for item in self._memberships} - known_sector_ids)
        if unknown:
            raise ValueError(f"membership references unknown sector ids: {unknown}")

    def _rank(self, source: str) -> int:
        return self._priority.get(source, len(self._priority))

    def _choose_membership(
        self, candidates: list[SectorMembership], decision_time: str
    ) -> SectorMembership:
        best_rank = min(self._rank(item.source) for item in candidates)
        ranked = [item for item in candidates if self._rank(item.source) == best_rank]
        latest = max(parse_instant(item.available_time) for item in ranked)
        current = [item for item in ranked if parse_instant(item.available_time) == latest]
        semantic = {
            (
                item.unified_code,
                item.sector_id,
                item.valid_from,
                item.valid_to,
                item.source,
                item.source_version,
            )
            for item in current
        }
        if len(semantic) != 1:
            raise TaxonomyConflictError(
                f"conflicting memberships at {decision_time}: "
                f"{sorted(item.evidence_id for item in current)}"
            )
        return min(current, key=lambda item: item.evidence_id)

    def _choose_sector(self, candidates: list[Sector], decision_time: str) -> Sector:
        best_rank = min(self._rank(item.source) for item in candidates)
        ranked = [item for item in candidates if self._rank(item.source) == best_rank]
        latest = max(parse_instant(item.available_time) for item in ranked)
        current = [item for item in ranked if parse_instant(item.available_time) == latest]
        semantic = {
            (
                item.sector_id,
                item.name,
                item.parent_id,
                item.kind,
                item.valid_from,
                item.valid_to,
                item.source,
                item.source_version,
                item.aliases,
            )
            for item in current
        }
        if len(semantic) != 1:
            raise TaxonomyConflictError(
                f"conflicting sectors at {decision_time}: "
                f"{sorted(item.evidence_id for item in current)}"
            )
        return min(current, key=lambda item: item.evidence_id)

    def memberships_of(
        self, sector_id: str, query_date: str, *, decision_time: str
    ) -> tuple[SectorMembership, ...]:
        parse_date(query_date)
        decision = parse_instant(decision_time)
        grouped: dict[str, list[SectorMembership]] = defaultdict(list)
        for item in self._memberships:
            if item.sector_id != sector_id:
                continue
            if not _valid_on(item.valid_from, item.valid_to, query_date):
                continue
            if parse_instant(item.available_time) > decision:
                continue
            grouped[item.unified_code].append(item)
        return tuple(
            self._choose_membership(grouped[code], canonical_instant(decision_time))
            for code in sorted(grouped)
        )

    def members_of(self, sector_id: str, query_date: str, *, decision_time: str) -> list[str]:
        return [
            item.unified_code
            for item in self.memberships_of(
                sector_id,
                query_date,
                decision_time=decision_time,
            )
        ]

    def sectors_of(self, unified_code: str, query_date: str, *, decision_time: str) -> list[str]:
        parse_date(query_date)
        decision = parse_instant(decision_time)
        grouped: dict[str, list[SectorMembership]] = defaultdict(list)
        for item in self._memberships:
            if item.unified_code != unified_code:
                continue
            if not _valid_on(item.valid_from, item.valid_to, query_date):
                continue
            if parse_instant(item.available_time) > decision:
                continue
            grouped[item.sector_id].append(item)
        return [
            self._choose_membership(grouped[sector_id], decision_time).sector_id
            for sector_id in sorted(grouped)
        ]

    def resolve(self, name_or_alias: str, query_date: str, *, decision_time: str) -> str | None:
        parse_date(query_date)
        decision = parse_instant(decision_time)
        candidates = [
            sector
            for sector in self._sectors
            if name_or_alias in (sector.name, *sector.aliases)
            and _valid_on(sector.valid_from, sector.valid_to, query_date)
            and parse_instant(sector.available_time) <= decision
        ]
        return self._choose_sector(candidates, decision_time).sector_id if candidates else None

    def history(self, unified_code: str) -> list[SectorMembership]:
        return [item for item in self._memberships if item.unified_code == unified_code]
