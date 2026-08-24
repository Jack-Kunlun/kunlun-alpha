"""End-to-end P3-N04 tests: real ``extract_entities`` output must flow
directly into ``resolve_mentions`` without any fixture-provided semantics.

The extractor and resolver share the same field contract: surface is the
exact document slice, normalized_surface is the entity's own normalized
surface, and evidence is non-empty and auditable.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from event_core.entities.dictionary import DictionaryEntry, EntityLexicon
from event_core.entities.extractor import extract_entities
from event_core.entities.models import EntityType
from market_core.resolver import (
    AliasEntry,
    AliasTable,
    AliasType,
    ResolutionStatus,
    resolve_mentions,
)
from market_core.resolver.universe import InstrumentUniverse
from test_resolver_models import (
    T_PAST,
    make_instrument,
    snap,
)

T_2026 = datetime(2026, 8, 24, 8, 0, 0, tzinfo=UTC)


def e2e_lexicon() -> EntityLexicon:
    return EntityLexicon(
        [
            DictionaryEntry(
                entry_id="co-moutai",
                term="贵州茅台",
                entity_type=EntityType.COMPANY,
                aliases=("茅台",),
                confidence_bps=9000,
                source="test",
            ),
            DictionaryEntry(
                entry_id="sec-moutai",
                term="600519.SH",
                entity_type=EntityType.SECURITY,
                confidence_bps=9500,
                source="test",
            ),
            DictionaryEntry(
                entry_id="co-pingan-bank",
                term="平安",
                entity_type=EntityType.COMPANY,
                aliases=("平安",),
                confidence_bps=8000,
                source="test",
            ),
            DictionaryEntry(
                entry_id="co-pingan-group",
                term="中国平安",
                entity_type=EntityType.COMPANY,
                aliases=("平安",),
                confidence_bps=8000,
                source="test",
            ),
        ]
    )


def e2e_universe() -> InstrumentUniverse:
    return InstrumentUniverse(
        [
            snap(
                make_instrument(
                    "600519",
                    "SH",
                    "MAIN",
                    "STOCK",
                    "贵州茅台",
                    list_date=date(2001, 8, 27),
                ),
                T_PAST,
            ),
            snap(
                make_instrument(
                    "000001",
                    "SZ",
                    "MAIN",
                    "STOCK",
                    "平安银行",
                    list_date=date(1991, 4, 3),
                ),
                T_PAST,
            ),
            snap(
                make_instrument(
                    "601318",
                    "SH",
                    "MAIN",
                    "STOCK",
                    "中国平安",
                    list_date=date(2007, 3, 1),
                ),
                T_PAST,
            ),
        ]
    )


def e2e_aliases() -> AliasTable:
    return AliasTable(
        [
            AliasEntry(
                alias_id="a-pa",
                alias="平安",
                alias_type=AliasType.EQUIVALENT_NAME,
                target="000001.SZ",
                effective_from=T_PAST,
                effective_to=None,
                available_time=T_PAST,
                source="test",
                version="v1",
                reliability=8500,
            ),
            AliasEntry(
                alias_id="a-pg",
                alias="平安",
                alias_type=AliasType.EQUIVALENT_NAME,
                target="601318.SH",
                effective_from=T_PAST,
                effective_to=None,
                available_time=T_PAST,
                source="test",
                version="v1",
                reliability=8500,
            ),
        ]
    )


class TestExtractThenResolve:
    def test_real_mentions_resolve_without_fixture_semantics(self) -> None:
        text = "贵州茅台与平安同时发布公告"
        result = extract_entities(
            text,
            e2e_lexicon(),
            content_id="content-e2e",
            decision_time=T_2026,
        )
        resolutions = resolve_mentions(
            result.mentions,
            universe=e2e_universe(),
            aliases=e2e_aliases(),
            decision_time=T_2026,
            reference_time=T_2026,
            entity_candidates=result.candidates,
        )
        by_surface: dict[str, ResolutionStatus] = {}
        for r in resolutions:
            mention = next(m for m in result.mentions if m.mention_id == r.mention_id)
            by_surface[mention.surface] = r.status
        assert by_surface["贵州茅台"] is ResolutionStatus.RESOLVED
        # "平安" appears once; without a unique symbol context it is ambiguous.
        assert by_surface["平安"] is ResolutionStatus.AMBIGUOUS

    def test_e2e_evidence_present_and_deterministic(self) -> None:
        r1 = extract_entities(
            "贵州茅台发布公告",
            e2e_lexicon(),
            content_id="c-e2e",
            decision_time=T_2026,
        )
        r2 = extract_entities(
            "贵州茅台发布公告",
            e2e_lexicon(),
            content_id="c-e2e",
            decision_time=T_2026,
        )
        for m in r1.mentions:
            assert m.evidence
        assert [m.evidence for m in r1.mentions] == [m.evidence for m in r2.mentions]

    def test_e2e_normalized_surface_is_own_surface(self) -> None:
        result = extract_entities(
            "贵州茅台发布公告",
            e2e_lexicon(),
            content_id="c-e2e",
            decision_time=T_2026,
        )
        for m in result.mentions:
            assert m.normalized_surface == m.surface.casefold()
            assert m.normalized_surface != result.text

    def test_e2e_multi_candidates_flow_to_resolver(self) -> None:
        result = extract_entities(
            "平安今天大涨",
            e2e_lexicon(),
            content_id="c-e2e",
            decision_time=T_2026,
        )
        companies = [m for m in result.mentions if m.entity_type is EntityType.COMPANY]
        assert len(companies) == 1
        company = companies[0]
        company_candidates = [c for c in result.candidates if c.mention_id == company.mention_id]
        assert {c.target for c in company_candidates} == {
            "co-pingan-bank",
            "co-pingan-group",
        }
        resolutions = resolve_mentions(
            (company,),
            universe=e2e_universe(),
            aliases=e2e_aliases(),
            decision_time=T_2026,
            reference_time=T_2026,
            entity_candidates=result.candidates,
        )
        assert resolutions[0].status is ResolutionStatus.AMBIGUOUS
        assert {c.instrument_id for c in resolutions[0].candidates} == {
            "000001.SZ",
            "601318.SH",
        }

    def test_extraction_ambiguity_survives_incomplete_alias_data(self) -> None:
        result = extract_entities(
            "平安发布公告",
            e2e_lexicon(),
            content_id="c-e2e",
            decision_time=T_2026,
        )
        company = next(m for m in result.mentions if m.entity_type is EntityType.COMPANY)
        incomplete_aliases = AliasTable(e2e_aliases().entries[:1])
        resolution = resolve_mentions(
            (company,),
            universe=e2e_universe(),
            aliases=incomplete_aliases,
            decision_time=T_2026,
            reference_time=T_2026,
            entity_candidates=result.candidates,
        )[0]
        assert resolution.status is ResolutionStatus.AMBIGUOUS
        assert resolution.resolved_instrument_id is None
