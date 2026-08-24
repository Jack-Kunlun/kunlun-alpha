"""Near-duplicate detection — threshold evaluation-set tests (P3-N03).

Sixth RED group: a small, sanitized, labeled evaluation set produces a stable
confusion matrix; precision/recall are computed correctly; zero-denominator
behavior is explicit; different companies' template announcements never become
a false positive; the evaluation result is bound to the correct policy
fingerprint.

The labeled set is synthetic (no production news, cookies, accounts or private
raw data). Every case has a stable id and a duplicate/non-duplicate label and
covers: exact duplicate, light title rewrite, small body edit, cross-source
repost, template announcement, different-company same-type announcement, short
text, empty text, and a threshold boundary case.
"""

from __future__ import annotations

from datetime import UTC, datetime

from event_core.dedup import (
    DecisionReason,
    DedupInput,
    DedupPolicy,
    Eligibility,
    build_evaluation_set,
    decide_pair,
    evaluate_labeled_set,
)
from event_core.dedup.evaluation import (
    EVALUATION_SET_VERSION,
    evaluation_set_fingerprint,
)

_BASE = datetime(2026, 8, 21, 1, 0, tzinfo=UTC)

# A shared body whose engineered similarity to its edited variant is a fixed,
# known basis-points value, so a boundary policy can pin the threshold exactly.
_CORE = "某公司发布重大合同公告内容详实并请广大投资者注意投资风险以及后续相关安排事宜的具体说明"
_BODY_A = _CORE
_BODY_B = _CORE + "甲乙丙"
_BODY_BPS = 9318  # body_similarity_bps(_BODY_A, _BODY_B, 3)
# Two high-information (congruent) titles with a fixed similarity.
_TITLE_A = "重大资产收购进展公告"
_TITLE_B = "重大资产收购进展事项"
_TITLE_BPS = 6000  # title_similarity_bps(_TITLE_A, _TITLE_B, 3)


def _pair(title_a: str, body_a: str, title_b: str, body_b: str) -> tuple[DedupInput, DedupInput]:
    def mk(cid: str, title: str, body: str, src: str) -> DedupInput:
        return DedupInput(
            content_id=cid,
            record_id=f"rec-{cid}",
            version_id="f" * 64,
            source_id=src,
            source_revision="v1",
            available_time=_BASE,
            normalization_version="norm-v1",
            normalization_policy_id="pol-fp-1",
            title=title,
            body=body,
            eligibility=Eligibility.ELIGIBLE,
        )

    return mk("a", title_a, body_a, "cninfo"), mk("b", title_b, body_b, "sina")


def test_evaluation_set_has_stable_ids_and_labels() -> None:
    cases = build_evaluation_set()
    assert len(cases) >= 9
    ids = [case.case_id for case in cases]
    assert len(ids) == len(set(ids))  # unique stable ids
    for case in cases:
        assert isinstance(case.expected_duplicate, bool)


def test_evaluation_produces_confusion_matrix() -> None:
    result = evaluate_labeled_set(build_evaluation_set(), policy=DedupPolicy())
    assert result.true_positives >= 0
    assert result.false_positives >= 0
    assert result.true_negatives >= 0
    assert result.false_negatives >= 0
    total = (
        result.true_positives
        + result.false_positives
        + result.true_negatives
        + result.false_negatives
    )
    assert total == len(build_evaluation_set())


def test_evaluation_is_deterministic() -> None:
    a = evaluate_labeled_set(build_evaluation_set(), policy=DedupPolicy())
    b = evaluate_labeled_set(build_evaluation_set(), policy=DedupPolicy())
    assert a == b


def test_precision_recall_computed_correctly() -> None:
    result = evaluate_labeled_set(build_evaluation_set(), policy=DedupPolicy())
    # precision = TP / (TP + FP); recall = TP / (TP + FN), quantized to bps
    tp, fp, fn = result.true_positives, result.false_positives, result.false_negatives
    if tp + fp == 0:
        assert result.precision_bps == 0
    else:
        assert result.precision_bps == round(10000 * tp / (tp + fp))
    if tp + fn == 0:
        assert result.recall_bps == 0
    else:
        assert result.recall_bps == round(10000 * tp / (tp + fn))


def test_zero_denominator_is_explicit() -> None:
    # an all-negative labeled set has no positives -> recall denominator is 0.
    all_negatives = tuple(c for c in build_evaluation_set() if not c.expected_duplicate)
    result = evaluate_labeled_set(all_negatives, policy=DedupPolicy())
    assert result.true_positives == 0
    assert result.false_negatives == 0
    assert result.recall_bps == 0  # explicit zero, not a crash


def test_different_company_announcements_never_false_positive() -> None:
    result = evaluate_labeled_set(build_evaluation_set(), policy=DedupPolicy())
    # strict gate: no different-company same-type announcement may merge.
    assert result.false_positives == 0


def test_evaluation_bound_to_policy_fingerprint() -> None:
    policy = DedupPolicy()
    result = evaluate_labeled_set(build_evaluation_set(), policy=policy)
    assert result.policy_fingerprint == policy.fingerprint()


# --- evaluation-set identity (I4) -------------------------------------------


def test_result_carries_evaluation_set_identity() -> None:
    result = evaluate_labeled_set(build_evaluation_set(), policy=DedupPolicy())
    assert result.evaluation_set_version == EVALUATION_SET_VERSION
    assert result.evaluation_set_fingerprint == evaluation_set_fingerprint(build_evaluation_set())
    # version-prefixed SHA-256, not a Python hash()
    prefix, _, digest = result.evaluation_set_fingerprint.partition(":")
    assert prefix == EVALUATION_SET_VERSION
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_evaluation_set_fingerprint_is_stable() -> None:
    assert evaluation_set_fingerprint(build_evaluation_set()) == evaluation_set_fingerprint(
        build_evaluation_set()
    )


def test_changing_a_label_changes_fingerprint() -> None:
    cases = list(build_evaluation_set())
    original = evaluation_set_fingerprint(tuple(cases))
    flipped = cases[0].__class__(
        case_id=cases[0].case_id,
        left=cases[0].left,
        right=cases[0].right,
        expected_duplicate=not cases[0].expected_duplicate,
    )
    mutated = tuple([flipped, *cases[1:]])
    assert evaluation_set_fingerprint(mutated) != original


def test_changing_a_case_input_changes_fingerprint() -> None:
    cases = list(build_evaluation_set())
    original = evaluation_set_fingerprint(tuple(cases))
    left = cases[0].left
    new_left = DedupInput(
        content_id=left.content_id,
        record_id=left.record_id,
        version_id=left.version_id,
        source_id=left.source_id,
        source_revision=left.source_revision,
        available_time=left.available_time,
        normalization_version=left.normalization_version,
        normalization_policy_id=left.normalization_policy_id,
        title=left.title + "（修改）",
        body=left.body,
        eligibility=left.eligibility,
        subject_keys=left.subject_keys,
    )
    changed = cases[0].__class__(
        case_id=cases[0].case_id,
        left=new_left,
        right=cases[0].right,
        expected_duplicate=cases[0].expected_duplicate,
    )
    mutated = tuple([changed, *cases[1:]])
    assert evaluation_set_fingerprint(mutated) != original


# --- threshold boundary cases (I4) ------------------------------------------


def test_body_similarity_equal_to_threshold_merges() -> None:
    a, b = _pair(_TITLE_A, _BODY_A, _TITLE_B, _BODY_B)
    policy = DedupPolicy(body_similarity_threshold_bps=_BODY_BPS)
    decision = decide_pair(a, b, policy=policy)
    assert decision.signals.body_similarity_bps == _BODY_BPS
    assert decision.is_duplicate is True  # >= threshold is inclusive


def test_body_similarity_just_below_threshold_not_merged() -> None:
    a, b = _pair(_TITLE_A, _BODY_A, _TITLE_B, _BODY_B)
    policy = DedupPolicy(body_similarity_threshold_bps=_BODY_BPS + 1)
    decision = decide_pair(a, b, policy=policy)
    assert decision.is_duplicate is False
    # title is congruent but the body fell just under threshold -> below.
    assert decision.reason == DecisionReason.BELOW_THRESHOLD


def test_body_similarity_just_above_threshold_merges() -> None:
    a, b = _pair(_TITLE_A, _BODY_A, _TITLE_B, _BODY_B)
    policy = DedupPolicy(body_similarity_threshold_bps=_BODY_BPS - 1)
    decision = decide_pair(a, b, policy=policy)
    assert decision.is_duplicate is True


def test_title_similarity_equal_to_congruence_floor_merges() -> None:
    a, b = _pair(_TITLE_A, _BODY_A, _TITLE_B, _BODY_B)
    policy = DedupPolicy(
        body_similarity_threshold_bps=_BODY_BPS,
        title_congruence_floor_bps=_TITLE_BPS,
    )
    decision = decide_pair(a, b, policy=policy)
    assert decision.signals.title_similarity_bps == _TITLE_BPS
    assert decision.is_duplicate is True  # title == floor is inclusive


def test_title_similarity_just_below_congruence_floor_not_merged() -> None:
    a, b = _pair(_TITLE_A, _BODY_A, _TITLE_B, _BODY_B)
    policy = DedupPolicy(
        body_similarity_threshold_bps=_BODY_BPS,
        title_congruence_floor_bps=_TITLE_BPS + 1,
    )
    decision = decide_pair(a, b, policy=policy)
    assert decision.is_duplicate is False
    assert decision.reason == DecisionReason.BODY_TEMPLATE_INSUFFICIENT


# --- locked confusion matrix (I4) -------------------------------------------


def test_default_evaluation_confusion_matrix_is_locked() -> None:
    result = evaluate_labeled_set(build_evaluation_set(), policy=DedupPolicy())
    assert result.true_positives == 5
    assert result.false_positives == 0
    assert result.true_negatives == 7
    assert result.false_negatives == 0
    assert result.precision_bps == 10000
    assert result.recall_bps == 10000
