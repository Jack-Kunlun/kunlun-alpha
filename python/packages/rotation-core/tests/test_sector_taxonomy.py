"""Sector taxonomy tests.

Covers multi-membership, alias resolution (with conflict via source priority),
historical changes via validity windows, and current-vs-expired membership.
"""

from __future__ import annotations

from rotation_core.taxonomy import Sector, SectorMembership, SectorTaxonomy


def _taxonomy() -> SectorTaxonomy:
    sectors = [
        Sector("ind-gold", "黄金", None, "INDUSTRY", "src-a", "2020-01-01", None, ("贵金属",)),
        Sector("theme-ai", "人工智能", None, "THEME", "src-a", "2024-01-01", None, ("AI",)),
        Sector(
            "concept-low-alt", "低空经济", None, "CONCEPT", "src-b", "2025-01-01", None, ("低空",)
        ),
    ]
    memberships = [
        SectorMembership("600000.SH", "ind-gold", "2020-01-01", None, "src-a"),
        SectorMembership("600000.SH", "theme-ai", "2024-01-01", None, "src-a"),  # multi-membership
        SectorMembership("600001.SH", "concept-low-alt", "2025-01-01", None, "src-b"),
        SectorMembership("600002.SH", "ind-gold", "2020-01-01", "2023-12-31", "src-a"),  # expired
    ]
    return SectorTaxonomy(sectors, memberships, source_priority=["src-a", "src-b"])


def test_multi_membership() -> None:
    taxonomy = _taxonomy()
    sectors = taxonomy.sectors_of("600000.SH", "2025-06-01")
    assert sectors == ["ind-gold", "theme-ai"]


def test_members_of_respects_validity() -> None:
    taxonomy = _taxonomy()
    # 600002.SH membership expired at 2023-12-31.
    assert taxonomy.members_of("ind-gold", "2025-06-01") == ["600000.SH"]
    assert taxonomy.members_of("ind-gold", "2023-01-01") == ["600000.SH", "600002.SH"]


def test_alias_resolution() -> None:
    taxonomy = _taxonomy()
    assert taxonomy.resolve("贵金属") == "ind-gold"
    assert taxonomy.resolve("AI") == "theme-ai"
    assert taxonomy.resolve("黄金") == "ind-gold"


def test_alias_conflict_resolves_by_source_priority() -> None:
    # Two sectors share the alias "新能源"; src-a has higher priority.
    sectors = [
        Sector("ind-a", "行业A", None, "INDUSTRY", "src-a", "2020-01-01", None, ("新能源",)),
        Sector("ind-b", "行业B", None, "INDUSTRY", "src-b", "2020-01-01", None, ("新能源",)),
    ]
    taxonomy = SectorTaxonomy(sectors, [], ["src-a", "src-b"])
    assert taxonomy.resolve("新能源") == "ind-a"


def test_history_retains_expired_memberships() -> None:
    taxonomy = _taxonomy()
    history = taxonomy.history("600002.SH")
    assert len(history) == 1
    assert history[0].valid_to == "2023-12-31"
