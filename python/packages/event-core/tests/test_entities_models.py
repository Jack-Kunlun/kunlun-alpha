"""Entity model tests (P3-N04)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from event_core.entities.models import (
    ENTITY_EXTRACTION_VERSION,
    EntityMention,
    EntityPolicyVersionError,
    EntityType,
    ExtractionPolicy,
    ExtractionResult,
    build_evidence,
    compute_mention_id,
    is_eligible,
    normalize_surface,
)

T0 = datetime(2026, 8, 24, 8, 0, 0, tzinfo=UTC)


def make_policy(**overrides: Any) -> ExtractionPolicy:
    return ExtractionPolicy(**overrides)


def make_mention(
    text: str = "示例酒业",
    start: Any = 0,
    end: int | None = None,
    entity_type: EntityType = EntityType.COMPANY,
    confidence_bps: Any = 8000,
    **overrides: Any,
) -> EntityMention:
    end = len(text) if end is None else end
    surface = text[start:end]
    fields: dict[str, Any] = {
        "content_id": "content-1",
        "entity_type": entity_type,
        "surface": surface,
        "normalized_surface": normalize_surface(surface),
        "start_offset": start,
        "end_offset": end,
        "extractor_version": ENTITY_EXTRACTION_VERSION,
        "policy_fingerprint": make_policy().fingerprint(),
        "confidence_bps": confidence_bps,
        "eligibility_threshold_bps": make_policy().min_confidence_bps,
        "reason": "lexicon_exact",
    }
    fields.update(overrides)
    if "evidence" not in fields:
        fields["evidence"] = build_evidence(
            fields["content_id"],
            fields["start_offset"],
            fields["end_offset"],
            fields["surface"],
        )
    if "mention_id" not in fields:
        identity_policy = ExtractionPolicy(
            version=fields["extractor_version"],
            min_confidence_bps=fields["eligibility_threshold_bps"],
        )
        fields["mention_id"] = compute_mention_id(
            content_id=fields["content_id"],
            entity_type=fields["entity_type"],
            start_offset=fields["start_offset"],
            end_offset=fields["end_offset"],
            surface=fields["surface"],
            policy=identity_policy,
        )
    return EntityMention(**fields)


class TestEntityTypes:
    def test_six_kinds_present(self) -> None:
        assert set(EntityType) == {
            EntityType.COMPANY,
            EntityType.SECURITY,
            EntityType.INSTITUTION,
            EntityType.PERSON,
            EntityType.POLICY,
            EntityType.REGION,
        }

    def test_values_are_stable_lowercase(self) -> None:
        assert EntityType.COMPANY.value == "company"
        assert EntityType.SECURITY.value == "security"
        assert EntityType.INSTITUTION.value == "institution"
        assert EntityType.PERSON.value == "person"
        assert EntityType.POLICY.value == "policy"
        assert EntityType.REGION.value == "region"


class TestMentionSpan:
    def test_surface_is_exact_text_slice(self) -> None:
        m = make_mention("中国平安", start=0, end=2)
        assert m.surface == "中国"
        assert m.start_offset == 0
        assert m.end_offset == 2

    def test_normalized_surface_is_surface_not_full_text(self) -> None:
        m = make_mention("中国平安", start=0, end=2)
        # normalized_surface is the entity's own normalized surface, not the
        # whole document text.
        assert m.normalized_surface == normalize_surface("中国")
        assert m.normalized_surface != "中国平安"

    def test_normalized_surface_is_ascii_casefolded(self) -> None:
        m = make_mention("ABC股份", start=0, end=3)
        assert m.normalized_surface == "abc"

    def test_offset_semantics_are_code_point_based(self) -> None:
        # 4-byte emoji counts as one code point; offsets are Unicode-aware.
        text = "🚀中国平安"
        m = make_mention(text, start=1, end=5)
        assert m.surface == "中国平安"

    def test_rejects_bad_span(self) -> None:
        with pytest.raises(ValueError):
            make_mention("示例酒业", start=-1, end=2)
        with pytest.raises(ValueError):
            make_mention("示例酒业", start=3, end=2)

    def test_full_text_bound_is_checked_by_extraction_result(self) -> None:
        # A mention alone cannot validate document bounds: start/end are
        # document-wide coordinates and the mention does not carry the full
        # text. The exact slice check happens in ExtractionResult (see
        # extractor tests: test_span_is_exact_slice).
        m = make_mention("示例酒业", start=0, end=99)
        assert m.surface == "示例酒业"
        assert m.normalized_surface == normalize_surface("示例酒业")

    def test_rejects_float_offsets(self) -> None:
        with pytest.raises(TypeError):
            make_mention("示例酒业", start=0.0, end=2)

    def test_original_span_must_be_pair(self) -> None:
        with pytest.raises(ValueError):
            make_mention("示例酒业", original_start=0)
        with pytest.raises(ValueError):
            make_mention("示例酒业", original_end=2)
        with pytest.raises(ValueError):
            make_mention("示例酒业", original_start=5, original_end=2)

    def test_original_span_pair_is_allowed(self) -> None:
        m = make_mention("示例酒业", original_start=10, original_end=14)
        assert m.original_start == 10
        assert m.original_end == 14


class TestMentionIdentity:
    def test_mention_id_is_sha256_with_prefix(self) -> None:
        m = make_mention()
        assert m.mention_id.startswith("mention:")
        digest = m.mention_id.removeprefix("mention:")
        assert len(digest) == 64
        # deterministic: same inputs -> same id
        assert make_mention().mention_id == m.mention_id

    def test_mention_id_binds_span_and_surface(self) -> None:
        a = make_mention("中国平安", start=0, end=2)
        b = make_mention("中国平安", start=0, end=4)
        assert a.mention_id != b.mention_id

    def test_mention_id_binds_content_and_type(self) -> None:
        base = make_mention()
        assert make_mention(content_id="other").mention_id != base.mention_id
        assert make_mention(entity_type=EntityType.SECURITY).mention_id != base.mention_id

    def test_compute_mention_id_matches_constructor(self) -> None:
        text = "示例酒业"
        manual = compute_mention_id(
            content_id="content-1",
            entity_type=EntityType.COMPANY,
            start_offset=0,
            end_offset=len(text),
            surface=text,
            policy=make_policy(),
        )
        m = make_mention(text, start=0, end=len(text))
        assert m.mention_id == manual

    def test_compute_mention_id_is_not_plain_concatenation(self) -> None:
        # Field boundaries are explicit: ("a"+"bc") must not collide with
        # ("ab"+"c") style ambiguity. Use distinct id/span combos and require
        # the digest to be a real SHA-256 of the framed material.
        a = compute_mention_id(
            content_id="ab",
            entity_type=EntityType.COMPANY,
            start_offset=0,
            end_offset=1,
            surface="中国",
            policy=make_policy(),
        )
        b = compute_mention_id(
            content_id="a",
            entity_type=EntityType.COMPANY,
            start_offset=0,
            end_offset=1,
            surface="b中国",
            policy=make_policy(),
        )
        assert a != b

    def test_compute_mention_id_rejects_raw_policy_identity(self) -> None:
        unsafe_compute: Any = compute_mention_id
        with pytest.raises(TypeError):
            unsafe_compute(
                content_id="content-1",
                entity_type=EntityType.COMPANY,
                start_offset=0,
                end_offset=4,
                surface="示例酒业",
                extractor_version=ENTITY_EXTRACTION_VERSION,
                policy_fingerprint=make_policy().fingerprint(),
            )

    def test_compute_mention_id_rejects_policy_lookalike(self) -> None:
        class PolicyLookalike:
            version = ENTITY_EXTRACTION_VERSION

            def fingerprint(self) -> str:
                return make_policy().fingerprint()

        unsafe_compute: Any = compute_mention_id
        with pytest.raises(TypeError, match="validated ExtractionPolicy"):
            unsafe_compute(
                content_id="content-1",
                entity_type=EntityType.COMPANY,
                start_offset=0,
                end_offset=4,
                surface="示例酒业",
                policy=PolicyLookalike(),
            )


class TestExtractionPolicy:
    def test_default_fingerprint_is_stable_sha256(self) -> None:
        fp = make_policy().fingerprint()
        assert len(fp) == 64
        assert fp == make_policy().fingerprint()

    def test_fingerprint_binds_parameters(self) -> None:
        assert (
            make_policy(min_confidence_bps=5000).fingerprint()
            != make_policy(min_confidence_bps=6000).fingerprint()
        )

    def test_version_is_rejected(self) -> None:
        with pytest.raises(EntityPolicyVersionError):
            ExtractionPolicy(version="entities-v2")
        with pytest.raises(EntityPolicyVersionError):
            ExtractionPolicy(version="latest")

    def test_mention_rejects_unknown_extractor_version(self) -> None:
        with pytest.raises(EntityPolicyVersionError):
            make_mention(extractor_version="entities-v2")

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValueError):
            ExtractionPolicy(min_confidence_bps=10001)
        with pytest.raises(ValueError):
            ExtractionPolicy(min_confidence_bps=-1)
        with pytest.raises(ValueError):
            ExtractionPolicy(min_confidence_bps=7000.5)  # type: ignore[arg-type]


class TestMentionValidation:
    def test_confidence_must_be_int_in_range(self) -> None:
        with pytest.raises(ValueError):
            make_mention(confidence_bps=-1)
        with pytest.raises(ValueError):
            make_mention(confidence_bps=10001)
        with pytest.raises(ValueError):
            make_mention(confidence_bps=8000.0)

    def test_empty_fields_rejected(self) -> None:
        with pytest.raises(ValueError):
            make_mention(mention_id="")
        with pytest.raises(ValueError):
            make_mention(content_id="")

    def test_extraction_result_rejects_foreign_text(self) -> None:
        m = make_mention()
        with pytest.raises(ValueError):
            ExtractionResult(
                text="别的文本",
                mentions=(m,),
                extractor_version=ENTITY_EXTRACTION_VERSION,
                policy_fingerprint=m.policy_fingerprint,
                lexicon_fingerprint="lexicon-test",
                decision_time=T0,
            )

    def test_extraction_result_version_checked(self) -> None:
        m = make_mention()
        with pytest.raises(EntityPolicyVersionError):
            ExtractionResult(
                text=m.normalized_surface,
                mentions=(m,),
                extractor_version="entities-v2",
                policy_fingerprint=m.policy_fingerprint,
                lexicon_fingerprint="lexicon-test",
                decision_time=T0,
            )


class TestEligibility:
    def test_eligible_at_or_above_threshold(self) -> None:
        policy = make_policy(min_confidence_bps=6000)
        assert is_eligible(make_mention(confidence_bps=6000), policy)
        assert is_eligible(make_mention(confidence_bps=8000), policy)
        assert not is_eligible(make_mention(confidence_bps=5999), policy)

    def test_mismatched_policy_cannot_override_bound_threshold(self) -> None:
        mention = make_mention(
            confidence_bps=8000,
            eligibility_threshold_bps=9000,
            policy_fingerprint=make_policy(min_confidence_bps=9000).fingerprint(),
        )
        with pytest.raises(ValueError, match="policy fingerprint"):
            is_eligible(mention, make_policy(min_confidence_bps=0))


class TestNormalizeSurface:
    def test_casefolds_ascii_and_collapses_whitespace(self) -> None:
        assert normalize_surface("  ABC  股份 ") == "abc 股份"
        assert normalize_surface("贵州茅台") == "贵州茅台"
        assert normalize_surface("600519.SH") == "600519.sh"

    def test_mention_rejects_normalized_mismatch(self) -> None:
        with pytest.raises(ValueError):
            make_mention("中国平安", start=0, end=2, normalized_surface="中国平安")

    def test_mention_rejects_empty_normalized(self) -> None:
        with pytest.raises(ValueError):
            make_mention(normalized_surface="")


class TestEvidence:
    def test_mention_evidence_non_empty(self) -> None:
        m = make_mention()
        assert m.evidence
        assert "content-1" in m.evidence
        assert "0" in m.evidence
        assert "4" in m.evidence
        assert "示例酒业" in m.evidence

    def test_mention_rejects_empty_evidence(self) -> None:
        with pytest.raises(ValueError):
            make_mention(evidence="")

    @pytest.mark.parametrize(
        "evidence",
        [
            "other-content:0:4:示例酒业",
            "content-1:1:4:示例酒业",
            "content-1:0:4:错误表面",
        ],
    )
    def test_mention_rejects_evidence_not_bound_to_mention(self, evidence: str) -> None:
        with pytest.raises(ValueError):
            make_mention(evidence=evidence)

    def test_mention_accepts_exact_deterministic_evidence(self) -> None:
        m = make_mention()
        assert m.evidence == build_evidence("content-1", 0, 4, "示例酒业")

    def test_threshold_is_bound_to_policy_fingerprint(self) -> None:
        policy = make_policy(min_confidence_bps=9000)
        m = make_mention(
            confidence_bps=8000,
            eligibility_threshold_bps=policy.min_confidence_bps,
            policy_fingerprint=policy.fingerprint(),
        )
        assert not is_eligible(m)
        assert m.eligibility_threshold_bps == 9000

    def test_threshold_and_policy_fingerprint_must_match(self) -> None:
        with pytest.raises(ValueError):
            make_mention(
                eligibility_threshold_bps=9000,
                policy_fingerprint=make_policy(min_confidence_bps=6000).fingerprint(),
            )


class TestExtractionResultCandidates:
    def test_candidates_default_empty(self) -> None:
        m = make_mention()
        result = ExtractionResult(
            text=m.surface,
            mentions=(m,),
            extractor_version=ENTITY_EXTRACTION_VERSION,
            policy_fingerprint=m.policy_fingerprint,
            lexicon_fingerprint="lexicon-test",
            decision_time=T0,
        )
        assert result.candidates == ()

    def test_result_validates_surface_against_text_span(self) -> None:
        m = make_mention("示例酒业", start=0, end=2)
        # surface "示例" must equal text[0:2]; a mismatched text fails.
        with pytest.raises(ValueError):
            ExtractionResult(
                text="别的文本",
                mentions=(m,),
                extractor_version=ENTITY_EXTRACTION_VERSION,
                policy_fingerprint=m.policy_fingerprint,
                lexicon_fingerprint="lexicon-test",
                decision_time=T0,
            )

    def test_result_keeps_candidates(self) -> None:
        from event_core.entities.models import (
            EntityCandidate,
            ExtractionReason,
        )

        m = make_mention("示例酒业")
        cand = EntityCandidate(
            mention_id=m.mention_id,
            entry_id="co-example",
            target="co-example",
            entity_type=EntityType.COMPANY,
            surface=m.surface,
            start_offset=0,
            end_offset=4,
            score_bps=8000,
            reason=ExtractionReason.LEXICON_EXACT,
            source="test",
        )
        result = ExtractionResult(
            text=m.surface,
            mentions=(m,),
            candidates=(cand,),
            extractor_version=ENTITY_EXTRACTION_VERSION,
            policy_fingerprint=m.policy_fingerprint,
            lexicon_fingerprint="lexicon-test",
            decision_time=T0,
        )
        assert result.candidates == (cand,)

    def test_result_rejects_orphan_candidate_mention(self) -> None:
        from event_core.entities.models import (
            EntityCandidate,
            ExtractionReason,
        )

        m = make_mention("示例酒业")
        cand = EntityCandidate(
            mention_id="mention:missing",
            entry_id="co-example",
            target="co-example",
            entity_type=EntityType.COMPANY,
            surface=m.surface,
            start_offset=0,
            end_offset=4,
            score_bps=8000,
            reason=ExtractionReason.LEXICON_EXACT,
            source="test",
        )
        with pytest.raises(ValueError):
            ExtractionResult(
                text=m.surface,
                mentions=(m,),
                candidates=(cand,),
                extractor_version=ENTITY_EXTRACTION_VERSION,
                policy_fingerprint=m.policy_fingerprint,
                lexicon_fingerprint="lexicon-test",
                decision_time=T0,
            )

    def test_result_requires_aware_decision_time_and_lexicon_identity(self) -> None:
        m = make_mention()
        with pytest.raises(ValueError):
            ExtractionResult(
                text=m.surface,
                mentions=(m,),
                extractor_version=ENTITY_EXTRACTION_VERSION,
                policy_fingerprint=m.policy_fingerprint,
                lexicon_fingerprint="",
                decision_time=datetime(2026, 8, 24, 8, 0, 0),
            )

    def test_result_rejects_mention_with_different_policy_fingerprint(self) -> None:
        m = make_mention()
        with pytest.raises(ValueError):
            ExtractionResult(
                text=m.surface,
                mentions=(m,),
                extractor_version=ENTITY_EXTRACTION_VERSION,
                policy_fingerprint="f" * 64,
                lexicon_fingerprint="lexicon-test",
                decision_time=T0,
            )
