from __future__ import annotations

import pytest
from rotation_core.taxonomy import Sector, SectorMembership, SectorTaxonomy, TaxonomyConflictError

_DECISION = "2026-08-13T02:00:00Z"


def _sector(
    sector_id: str,
    name: str,
    *,
    source: str = "src-a",
    valid_from: str = "2020-01-01",
    valid_to: str | None = None,
    available_time: str = "2020-01-01T00:00:00Z",
    aliases: tuple[str, ...] = (),
) -> Sector:
    return Sector(
        sector_id,
        name,
        None,
        "INDUSTRY",
        source,
        valid_from,
        valid_to,
        "taxonomy-v1",
        available_time,
        f"sector-{sector_id}-{source}-{valid_from}",
        aliases,
    )


def _membership(
    code: str,
    sector_id: str,
    valid_from: str,
    valid_to: str | None,
    *,
    source: str = "src-a",
    available_time: str = "2020-01-01T00:00:00Z",
    evidence_id: str | None = None,
) -> SectorMembership:
    return SectorMembership(
        code,
        sector_id,
        valid_from,
        valid_to,
        source,
        "membership-v1",
        available_time,
        evidence_id or f"membership-{code}-{sector_id}-{source}-{valid_from}",
    )


def test_non_overlapping_histories_from_one_source_are_preserved() -> None:
    taxonomy = SectorTaxonomy(
        [_sector("s1", "黄金")],
        [
            _membership("600000.SH", "s1", "2020-01-01", "2021-12-31"),
            _membership("600000.SH", "s1", "2022-01-01", None),
        ],
        ["src-a"],
    )
    assert len(taxonomy.history("600000.SH")) == 2
    assert taxonomy.members_of("s1", "2021-01-01", decision_time=_DECISION) == ["600000.SH"]
    assert taxonomy.members_of("s1", "2026-01-01", decision_time=_DECISION) == ["600000.SH"]


def test_overlapping_conflict_resolves_only_at_query_time_by_source_priority() -> None:
    taxonomy = SectorTaxonomy(
        [_sector("s1", "黄金")],
        [
            _membership("600000.SH", "s1", "2020-01-01", None, source="src-b"),
            _membership("600000.SH", "s1", "2025-01-01", None, source="src-a"),
        ],
        ["src-a", "src-b"],
    )
    winner = taxonomy.memberships_of("s1", "2026-01-01", decision_time=_DECISION)
    assert winner[0].source == "src-a"
    assert len(taxonomy.history("600000.SH")) == 2


def test_membership_unavailable_at_decision_time_is_excluded() -> None:
    taxonomy = SectorTaxonomy(
        [_sector("s1", "黄金")],
        [
            _membership(
                "600000.SH",
                "s1",
                "2020-01-01",
                None,
                available_time="2026-08-13T03:00:00Z",
            )
        ],
        ["src-a"],
    )
    assert taxonomy.members_of("s1", "2026-08-13", decision_time=_DECISION) == []


def test_multi_membership_and_expired_history() -> None:
    taxonomy = SectorTaxonomy(
        [_sector("s1", "黄金"), _sector("s2", "人工智能")],
        [
            _membership("600000.SH", "s1", "2020-01-01", None),
            _membership("600000.SH", "s2", "2024-01-01", None),
            _membership("600002.SH", "s1", "2020-01-01", "2023-12-31"),
        ],
        ["src-a"],
    )
    assert taxonomy.sectors_of("600000.SH", "2026-01-01", decision_time=_DECISION) == ["s1", "s2"]
    assert taxonomy.members_of("s1", "2026-01-01", decision_time=_DECISION) == ["600000.SH"]


def test_alias_resolution_is_point_in_time() -> None:
    taxonomy = SectorTaxonomy(
        [
            _sector("old", "旧行业", valid_to="2024-12-31", aliases=("新能源",)),
            _sector("new", "新行业", valid_from="2025-01-01", aliases=("新能源",)),
        ],
        [],
        ["src-a"],
    )
    assert taxonomy.resolve("新能源", "2024-01-01", decision_time=_DECISION) == "old"
    assert taxonomy.resolve("新能源", "2026-01-01", decision_time=_DECISION) == "new"


def test_equally_authoritative_overlapping_conflict_fails_closed() -> None:
    taxonomy = SectorTaxonomy(
        [_sector("s1", "黄金")],
        [
            _membership("600000.SH", "s1", "2020-01-01", None, evidence_id="evidence-a"),
            SectorMembership(
                "600000.SH",
                "s1",
                "2025-01-01",
                None,
                "src-a",
                "membership-v2",
                "2020-01-01T00:00:00Z",
                "evidence-b",
            ),
        ],
        ["src-a"],
    )
    with pytest.raises(TaxonomyConflictError):
        taxonomy.members_of("s1", "2026-01-01", decision_time=_DECISION)
