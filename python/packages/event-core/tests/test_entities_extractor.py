"""Extractor behavior tests (P3-N04).

RED phase: the extractor skeleton returns no mentions, so every extraction
assertion fails. GREEN phase: full lexicon-based implementation passes.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from event_core.entities.dictionary import (
    DictionaryEntry,
    EntityLexicon,
    builtin_lexicon,
    lexicon_fingerprint,
)
from event_core.entities.extractor import OriginalRun, extract_entities
from event_core.entities.models import (
    EntityType,
    ExtractionPolicy,
    ExtractionReason,
    ExtractionResult,
    is_eligible,
)

T0 = datetime(2026, 8, 24, 8, 0, 0, tzinfo=UTC)


def d(
    entry_id: str,
    term: str,
    entity_type: EntityType,
    aliases: tuple[str, ...] = (),
    confidence_bps: int = 8000,
    available_from: datetime | None = None,
    available_to: datetime | None = None,
    source: str = "test",
) -> DictionaryEntry:
    return DictionaryEntry(
        entry_id=entry_id,
        term=term,
        entity_type=entity_type,
        aliases=aliases,
        confidence_bps=confidence_bps,
        available_from=available_from,
        available_to=available_to,
        source=source,
    )


def sample_lexicon() -> EntityLexicon:
    return EntityLexicon(
        [
            d("co-moutai", "贵州茅台", EntityType.COMPANY, aliases=("茅台",)),
            d("sec-moutai", "600519.SH", EntityType.SECURITY),
            d("co-pingan", "中国平安", EntityType.COMPANY, aliases=("平安",)),
            d("person-xiaoming", "李明", EntityType.PERSON),
            d("institution-csrc", "证监会", EntityType.INSTITUTION),
            d("policy-reg", "全面注册制", EntityType.POLICY),
            d("region-sh", "上海", EntityType.REGION),
        ]
    )


def extract(
    text: str,
    *,
    policy: ExtractionPolicy | None = None,
    original_runs: dict[tuple[int, int], OriginalRun] | None = None,
):
    return extract_entities(
        text,
        sample_lexicon(),
        content_id="content-1",
        decision_time=T0,
        policy=policy,
        original_runs=original_runs,
    )


def spans(result: ExtractionResult) -> list[tuple[int, int, str]]:
    return [(m.start_offset, m.end_offset, m.entity_type.value) for m in result.mentions]


class TestBasicExtraction:
    def test_company_full_name(self) -> None:
        result = extract("贵州茅台发布公告")
        types = {m.entity_type for m in result.mentions}
        assert EntityType.COMPANY in types
        company = next(m for m in result.mentions if m.entity_type is EntityType.COMPANY)
        assert company.surface == "贵州茅台"
        assert company.confidence_bps == 8000
        assert company.reason is ExtractionReason.LEXICON_EXACT

    def test_security_symbol(self) -> None:
        result = extract("贵州茅台（600519.SH）股价上涨")
        securities = [m for m in result.mentions if m.entity_type is EntityType.SECURITY]
        assert len(securities) == 1
        assert securities[0].surface == "600519.SH"
        assert securities[0].reason is ExtractionReason.SYMBOL_EXACT

    def test_all_six_kinds_in_one_text(self) -> None:
        text = "贵州茅台与证监会讨论全面注册制，李明在上海参会。"
        result = extract(text)
        assert {m.entity_type for m in result.mentions} == {
            EntityType.COMPANY,
            EntityType.INSTITUTION,
            EntityType.POLICY,
            EntityType.PERSON,
            EntityType.REGION,
        }

    def test_span_is_exact_slice(self) -> None:
        result = extract("上海与贵州茅台签约")
        for m in result.mentions:
            assert m.surface == result.text[m.start_offset : m.end_offset]

    def test_mentions_are_deterministic(self) -> None:
        a = extract("贵州茅台发布公告")
        b = extract("贵州茅台发布公告")
        assert [m.mention_id for m in a.mentions] == [m.mention_id for m in b.mentions]

    def test_aliases_match(self) -> None:
        result = extract("茅台提价")
        companies = [m for m in result.mentions if m.entity_type is EntityType.COMPANY]
        assert len(companies) == 1
        assert companies[0].surface == "茅台"


class TestChineseWithoutSpaces:
    def test_terms_inside_cjk_run(self) -> None:
        result = extract("茅台和贵州茅台同时出现")
        companies = [m for m in result.mentions if m.entity_type is EntityType.COMPANY]
        surfaces = {m.surface for m in companies}
        assert "茅台" in surfaces
        assert "贵州茅台" in surfaces


class TestOverlapLongestMatch:
    def test_longer_term_wins_over_shorter(self) -> None:
        # 贵州茅台 (4) overlaps 茅台 (2) -> longest wins at [0,4)
        result = extract("贵州茅台今日大涨")
        companies = [m for m in result.mentions if m.entity_type is EntityType.COMPANY]
        assert [m.surface for m in companies] == ["贵州茅台"]

    def test_same_span_keeps_distinct_types(self) -> None:
        # 600519.SH 同时是 SECURITY（无 COMPANY 同 span），只保留 security。
        result = extract("代码600519.SH有效")
        securities = [m for m in result.mentions if m.entity_type is EntityType.SECURITY]
        assert len(securities) == 1


class TestBareSixDigitsNotSecurity:
    def test_date_not_security(self) -> None:
        result = extract("会议定于20260824召开")
        assert not [m for m in result.mentions if m.entity_type is EntityType.SECURITY]

    def test_amount_not_security(self) -> None:
        result = extract("涉及金额600519元")
        assert not [m for m in result.mentions if m.entity_type is EntityType.SECURITY]

    def test_bare_digits_inside_longer_number_not_security(self) -> None:
        result = extract("编号6005191已处理")
        assert not [m for m in result.mentions if m.entity_type is EntityType.SECURITY]


class TestGenericTermsLowConfidence:
    def test_generic_company_word_not_high_confidence(self) -> None:
        lexicon = EntityLexicon(
            [
                d(
                    "gen-company",
                    "公司",
                    EntityType.COMPANY,
                    confidence_bps=3000,
                )
            ]
        )
        result = extract_entities(
            "该公司发布公告",
            lexicon,
            content_id="c",
            decision_time=T0,
        )
        companies = [m for m in result.mentions if m.entity_type is EntityType.COMPANY]
        assert len(companies) == 1
        assert companies[0].confidence_bps < 6000
        assert companies[0].reason is ExtractionReason.LOW_INFORMATION
        assert not is_eligible(companies[0], ExtractionPolicy())

    def test_low_confidence_mention_not_dropped(self) -> None:
        lexicon = EntityLexicon([d("gen-company", "公司", EntityType.COMPANY, confidence_bps=3000)])
        result = extract_entities("该公司发布公告", lexicon, content_id="c", decision_time=T0)
        assert len(result.mentions) == 1  # kept, not silently dropped


class TestPointInTimeLexicon:
    def test_future_entry_not_visible(self) -> None:
        lexicon = EntityLexicon(
            [
                d(
                    "co-future",
                    "未来公司",
                    EntityType.COMPANY,
                    available_from=datetime(2027, 1, 1, tzinfo=UTC),
                )
            ]
        )
        result = extract_entities("未来公司签约", lexicon, content_id="c", decision_time=T0)
        assert not [m for m in result.mentions if m.entity_type is EntityType.COMPANY]

    def test_expired_entry_not_visible(self) -> None:
        lexicon = EntityLexicon(
            [
                d(
                    "co-expired",
                    "已停用公司",
                    EntityType.COMPANY,
                    available_to=datetime(2020, 1, 1, tzinfo=UTC),
                )
            ]
        )
        result = extract_entities("已停用公司签约", lexicon, content_id="c", decision_time=T0)
        assert not [m for m in result.mentions if m.entity_type is EntityType.COMPANY]

    def test_naive_datetime_rejected_in_entry(self) -> None:
        with pytest.raises(ValueError):
            DictionaryEntry(
                entry_id="x",
                term="测试",
                entity_type=EntityType.COMPANY,
                available_from=datetime(2026, 1, 1),
            )

    def test_naive_decision_time_rejected(self) -> None:
        with pytest.raises(ValueError):
            extract_entities(
                "贵州茅台",
                sample_lexicon(),
                content_id="c",
                decision_time=datetime(2026, 8, 24, 8, 0, 0),
            )


class TestOriginalRunProvenance:
    def test_original_span_attached_when_mapping_provided(self) -> None:
        text = "贵州茅台发布公告"
        result = extract(
            text,
            original_runs={(0, 4): OriginalRun(original_start=11, original_end=15)},
        )
        company = next(m for m in result.mentions if m.entity_type is EntityType.COMPANY)
        assert company.original_start == 11
        assert company.original_end == 15

    def test_no_fabricated_original_span(self) -> None:
        result = extract("贵州茅台发布公告")
        company = next(m for m in result.mentions if m.entity_type is EntityType.COMPANY)
        assert company.original_start is None
        assert company.original_end is None


class TestBuiltinLexicon:
    def test_builtin_has_no_company_or_security(self) -> None:
        lexicon = builtin_lexicon()
        for entry in lexicon.entries:
            assert entry.entity_type not in {
                EntityType.COMPANY,
                EntityType.SECURITY,
            }

    def test_builtin_extracts_generic_entities(self) -> None:
        result = extract_entities(
            "证监会在上海推动全面注册制",
            builtin_lexicon(),
            content_id="c",
            decision_time=T0,
        )
        assert {m.entity_type for m in result.mentions} == {
            EntityType.INSTITUTION,
            EntityType.REGION,
            EntityType.POLICY,
        }


class TestExtractorEvidence:
    def test_evidence_non_empty_and_deterministic(self) -> None:
        r1 = extract("贵州茅台发布公告")
        r2 = extract("贵州茅台发布公告")
        for m in r1.mentions:
            assert m.evidence
        assert [m.evidence for m in r1.mentions] == [m.evidence for m in r2.mentions]

    def test_evidence_binds_content_id_span_and_surface(self) -> None:
        result = extract("贵州茅台发布公告")
        company = next(m for m in result.mentions if m.entity_type is EntityType.COMPANY)
        assert "content-1" in company.evidence
        assert str(company.start_offset) in company.evidence
        assert str(company.end_offset) in company.evidence
        assert "贵州茅台" in company.evidence


class TestExtractorNormalizedSurface:
    def test_normalized_surface_is_own_surface_not_full_text(self) -> None:
        result = extract("贵州茅台与上海签约")
        company = next(m for m in result.mentions if m.entity_type is EntityType.COMPANY)
        assert company.normalized_surface == "贵州茅台"
        assert company.normalized_surface != result.text

    def test_normalized_surface_matches_surface(self) -> None:
        # A lexicon entry with ascii term exercises normalization.
        lexicon = EntityLexicon([d("co-abc", "ABC", EntityType.COMPANY, aliases=("abc",))])
        result2 = extract_entities("ABC公告", lexicon, content_id="c", decision_time=T0)
        m = result2.mentions[0]
        assert m.normalized_surface == "abc"


class TestExtractorMultiCandidate:
    def test_same_span_same_type_keeps_all_candidates(self) -> None:
        lexicon = EntityLexicon(
            [
                d("co-a", "同名公司", EntityType.COMPANY, confidence_bps=8000),
                d("co-b", "同名公司", EntityType.COMPANY, confidence_bps=7000),
            ]
        )
        result = extract_entities("同名公司公告", lexicon, content_id="c", decision_time=T0)
        assert len(result.mentions) == 1
        assert len(result.candidates) == 2
        entry_ids = {c.entry_id for c in result.candidates}
        assert entry_ids == {"co-a", "co-b"}

    def test_candidates_sorted_deterministically(self) -> None:
        lexicon = EntityLexicon(
            [
                d("co-b", "同名公司", EntityType.COMPANY, confidence_bps=7000),
                d("co-a", "同名公司", EntityType.COMPANY, confidence_bps=8000),
            ]
        )
        result = extract_entities("同名公司公告", lexicon, content_id="c", decision_time=T0)
        assert len(result.candidates) == 2
        # higher score first, then entry_id ascending.
        assert [c.score_bps for c in result.candidates] == [8000, 7000]
        assert result.candidates[0].entry_id == "co-a"

    def test_candidates_carry_target_type_reason_source(self) -> None:
        result = extract("贵州茅台发布公告")
        cand = next(c for c in result.candidates if c.entry_id == "co-moutai")
        assert cand.target == "co-moutai"
        assert cand.entity_type is EntityType.COMPANY
        assert cand.surface == "贵州茅台"
        assert cand.score_bps == 8000
        assert cand.reason is ExtractionReason.LEXICON_EXACT
        assert cand.source == "test"
        assert cand.mention_id in {m.mention_id for m in result.mentions}


class TestExtractionIdentityAndUnicode:
    def test_result_records_lexicon_identity_and_decision_time(self) -> None:
        policy = ExtractionPolicy(min_confidence_bps=9000)
        lexicon = EntityLexicon(
            [d("co-low", "低置信公司", EntityType.COMPANY, confidence_bps=8000)]
        )
        result = extract_entities(
            "低置信公司公告",
            lexicon,
            content_id="replay-content",
            decision_time=T0,
            policy=policy,
        )
        assert result.lexicon_fingerprint == lexicon_fingerprint(lexicon)
        assert result.decision_time == T0
        assert result.mentions[0].eligibility_threshold_bps == 9000
        assert result.mentions[0].policy_fingerprint == policy.fingerprint()
        assert not is_eligible(result.mentions[0])

    def test_replay_identity_changes_when_availability_changes(self) -> None:
        base = EntityLexicon([d("co-replay", "回放公司", EntityType.COMPANY)])
        later = EntityLexicon(
            [
                d(
                    "co-replay",
                    "回放公司",
                    EntityType.COMPANY,
                    available_from=datetime(2026, 8, 25, tzinfo=UTC),
                )
            ]
        )
        assert lexicon_fingerprint(base) != lexicon_fingerprint(later)

    def test_alias_order_and_duplicates_do_not_change_lexicon_identity(self) -> None:
        a = EntityLexicon(
            [d("co-alias", "ABC", EntityType.COMPANY, aliases=("abc", "简称", "abc"))]
        )
        b = EntityLexicon([d("co-alias", "ABC", EntityType.COMPANY, aliases=("简称", "abc"))])
        assert lexicon_fingerprint(a) == lexicon_fingerprint(b)

    def test_conflicting_duplicate_entry_id_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            EntityLexicon(
                [
                    d("duplicate", "甲公司", EntityType.COMPANY),
                    d("duplicate", "乙公司", EntityType.COMPANY),
                ]
            )

    def test_ascii_fold_preserves_unicode_offsets_and_does_not_expand_sharp_s(self) -> None:
        lexicon = EntityLexicon(
            [
                d("de", "Straße", EntityType.COMPANY),
                d("abc", "ABC", EntityType.COMPANY),
                d("cn", "中文", EntityType.COMPANY),
            ]
        )
        text = "STRASSE ABC abc 中文 Straße"
        result = extract_entities(text, lexicon, content_id="unicode", decision_time=T0)
        surfaces = [m.surface for m in result.mentions]
        assert "STRASSE" not in surfaces
        assert "Straße" in surfaces
        assert "ABC" in surfaces
        assert "abc" in surfaces
        assert "中文" in surfaces
        for mention in result.mentions:
            assert mention.surface == text[mention.start_offset : mention.end_offset]
