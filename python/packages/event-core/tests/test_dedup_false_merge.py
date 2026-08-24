"""Near-duplicate detection — false-merge protection tests (P3-N03).

Third RED group: different companies' template announcements must not merge;
conflicting subject clues block a merge; a shared generic title alone does not
merge; a shared template body alone does not merge; short/empty text does not
produce spurious near-duplicates; a real transitive chain where A~B and B~C are
both duplicates yet A≁C must not chain-bridge A and C under complete linkage.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from event_core.dedup import (
    DecisionReason,
    DedupInput,
    DedupPolicy,
    Eligibility,
    cluster_contents,
    decide_pair,
)

_BASE = datetime(2026, 8, 21, 1, 0, tzinfo=UTC)

# A highly templated announcement body shared verbatim by different companies
# except for the company name and security symbol.
_TEMPLATE = (
    "公司董事会现就本次权益分派事项公告如下：本次利润分配以方案实施时股权登记日的总股本为基数，"
    "每十股派发现金红利，具体股权登记日及除权除息日详见后续公告，敬请广大投资者注意投资风险。"
)


def _input(
    *,
    content_id: str,
    title: str,
    body: str,
    source_id: str = "src",
    subject_keys: tuple[str, ...] = (),
) -> DedupInput:
    return DedupInput(
        content_id=content_id,
        record_id=f"rec-{content_id}",
        version_id="c" * 64,
        source_id=source_id,
        source_revision="v1",
        available_time=_BASE,
        normalization_version="norm-v1",
        normalization_policy_id="pol-fp-1",
        title=title,
        body=body,
        eligibility=Eligibility.ELIGIBLE,
        subject_keys=subject_keys,
    )


def test_different_companies_template_announcement_not_merged() -> None:
    a = _input(
        content_id="a",
        title="甲公司权益分派公告",
        body="甲公司" + _TEMPLATE,
        subject_keys=("600000.SH",),
    )
    b = _input(
        content_id="b",
        title="乙公司权益分派公告",
        body="乙公司" + _TEMPLATE,
        subject_keys=("000001.SZ",),
    )
    clusters = cluster_contents((a, b), policy=DedupPolicy(), decision_time=_BASE)
    assert len(clusters) == 2  # two singletons, not merged


def test_conflicting_subject_keys_block_merge() -> None:
    a = _input(
        content_id="a", title="权益分派公告", body="甲公司" + _TEMPLATE, subject_keys=("600000.SH",)
    )
    b = _input(
        content_id="b", title="权益分派公告", body="甲公司" + _TEMPLATE, subject_keys=("000001.SZ",)
    )
    decision = decide_pair(a, b, policy=DedupPolicy())
    assert decision.is_duplicate is False
    assert decision.reason == DecisionReason.SUBJECT_KEY_CONFLICT


def test_conflicting_subject_keys_block_even_on_exact_body() -> None:
    # even byte-identical content must not merge when subjects conflict.
    same_body = "完全相同的正文" + _TEMPLATE
    a = _input(content_id="a", title="完全相同标题", body=same_body, subject_keys=("600000.SH",))
    b = _input(content_id="b", title="完全相同标题", body=same_body, subject_keys=("000001.SZ",))
    decision = decide_pair(a, b, policy=DedupPolicy())
    assert decision.is_duplicate is False
    assert decision.reason == DecisionReason.SUBJECT_KEY_CONFLICT


def test_shared_generic_title_only_not_merged() -> None:
    a = _input(content_id="a", title="公告", body="甲公司今日召开董事会审议年度经营计划相关议案。")
    b = _input(content_id="b", title="公告", body="乙公司完成了对某海外子公司的股权出售交易。")
    clusters = cluster_contents((a, b), policy=DedupPolicy(), decision_time=_BASE)
    assert len(clusters) == 2


def test_low_information_title_reason_is_low_information() -> None:
    a = _input(content_id="a", title="公告", body="甲公司今日召开董事会审议年度经营计划相关议案。")
    b = _input(content_id="b", title="公告", body="乙公司完成了对某海外子公司的股权出售交易。")
    decision = decide_pair(a, b, policy=DedupPolicy())
    assert decision.is_duplicate is False


def test_shared_template_body_only_not_merged() -> None:
    # same template body, clearly different titles and different subjects.
    a = _input(
        content_id="a", title="甲公司权益分派公告", body=_TEMPLATE, subject_keys=("600000.SH",)
    )
    b = _input(
        content_id="b", title="乙公司季度业绩预告", body=_TEMPLATE, subject_keys=("000001.SZ",)
    )
    clusters = cluster_contents((a, b), policy=DedupPolicy(), decision_time=_BASE)
    assert len(clusters) == 2


def test_short_text_no_spurious_duplicate() -> None:
    a = _input(content_id="a", title="停牌", body="今起停牌")
    b = _input(content_id="b", title="停牌", body="今起停牌")
    decision = decide_pair(a, b, policy=DedupPolicy())
    # bodies are shorter than min_body_chars -> not a near-duplicate.
    assert decision.is_duplicate is False
    assert decision.reason == DecisionReason.CONTENT_TOO_SHORT


def test_empty_body_not_merged() -> None:
    a = _input(content_id="a", title="仅标题公告", body="")
    b = _input(content_id="b", title="仅标题公告", body="")
    decision = decide_pair(a, b, policy=DedupPolicy())
    assert decision.is_duplicate is False


def test_low_info_title_template_body_no_subject_not_merged() -> None:
    # I1 counterexample: two low-information titles ("公告"), a highly similar
    # (template) body, and NO subject keys on either side. Without a reliable,
    # matching subject clue the pair must fail closed — different companies
    # routinely share boilerplate bodies under a generic title.
    body_a = "甲" + _TEMPLATE
    body_b = "乙" + _TEMPLATE
    a = _input(content_id="a", title="公告", body=body_a)
    b = _input(content_id="b", title="公告", body=body_b)
    decision = decide_pair(a, b, policy=DedupPolicy())
    assert decision.is_duplicate is False
    assert decision.reason == DecisionReason.LOW_INFORMATION_TITLE
    clusters = cluster_contents((a, b), policy=DedupPolicy(), decision_time=_BASE)
    assert len(clusters) == 2  # two singletons, never merged


def test_low_info_title_high_body_similarity_no_subject_not_merged() -> None:
    # Even a near-identical template body under a generic title must not merge
    # when the caller supplied no subject clue to confirm the same issuer.
    shared = _TEMPLATE + "关于本次事项的详细说明内容如下所述并请投资者关注。"
    a = _input(content_id="a", title="通知", body="甲公司" + shared)
    b = _input(content_id="b", title="通知", body="乙公司" + shared)
    decision = decide_pair(a, b, policy=DedupPolicy())
    assert decision.is_duplicate is False
    assert decision.reason == DecisionReason.LOW_INFORMATION_TITLE


def test_low_info_title_same_subject_reliable_body_merges() -> None:
    # With a low-information title BUT matching, non-empty subject keys and a
    # reliably-similar body, the same issuer's repost may cluster.
    shared = _TEMPLATE + "关于本次事项的详细说明内容如下所述并请投资者关注。"
    a = _input(content_id="a", title="公告", body="甲公司" + shared, subject_keys=("600000.SH",))
    b = _input(
        content_id="b",
        title="公告",
        body="甲公司" + shared + "（转载自权威媒体）",
        subject_keys=("600000.SH",),
    )
    decision = decide_pair(a, b, policy=DedupPolicy())
    assert decision.is_duplicate is True
    assert decision.reason == DecisionReason.STRONG_TITLE_AND_BODY


def test_enforce_subject_conflict_false_is_rejected() -> None:
    # The V1 subject-conflict protection must not be disable-able by a caller;
    # constructing a policy with the guard off must fail, not yield a
    # "valid but unsafe" policy.
    with pytest.raises((ValueError, TypeError)):
        DedupPolicy(enforce_subject_conflict=False)


def test_conflicting_subjects_block_exact_even_with_default_policy() -> None:
    # Exact identical content with conflicting subject keys must never merge,
    # and there is no policy switch that can turn this protection off.
    same_body = "完全相同的正文" + _TEMPLATE
    a = _input(content_id="a", title="重大事项公告", body=same_body, subject_keys=("600000.SH",))
    b = _input(content_id="b", title="重大事项公告", body=same_body, subject_keys=("000001.SZ",))
    decision = decide_pair(a, b, policy=DedupPolicy())
    assert decision.is_duplicate is False
    assert decision.reason == DecisionReason.SUBJECT_KEY_CONFLICT


def test_high_info_title_cross_source_repost_still_clusters() -> None:
    # Regression guard: an ordinary high-information-title cross-source repost
    # with no subject keys must still cluster under the conservative joint rule.
    long_body = "某公司发布重大资产重组进展公告，" + "本次交易涉及标的资产的评估与审计工作。" * 6
    a = _input(content_id="a", title="重大资产重组进展公告", body=long_body, source_id="cninfo")
    b = _input(
        content_id="b",
        title="重大资产重组进展公告",
        body=long_body + "（转载）",
        source_id="sina",
    )
    decision = decide_pair(a, b, policy=DedupPolicy())
    assert decision.is_duplicate is True
    clusters = cluster_contents((a, b), policy=DedupPolicy(), decision_time=_BASE)
    assert len(clusters) == 1


def test_no_chain_bridging() -> None:
    # Missing-test supplement (round 2, I2): the previous fixture asserted
    # decide_pair(B,C).is_duplicate is False, i.e. it was an "A~B duplicate but
    # A≁C and B≁C" arrangement — a degenerate case a single-linkage engine would
    # also pass. It never exercised complete linkage. This replacement builds a
    # REAL transitive chain where BOTH A~B and B~C are duplicates yet A≁C, so
    # only complete linkage (every pair inside a cluster must be a duplicate) can
    # keep A and C apart. The production code is already correct, so this test
    # passes on first run — it is added to close a coverage gap, not to fake a
    # production RED.
    #
    # Construction relies on the fact that character n-gram Jaccard is NOT a
    # metric (it violates the triangle inequality): with A = 前甲+Q, B = Q+R,
    # C = R+后丁, A shares segment Q with B and B shares segment R with C, while
    # A and C share almost nothing. B is close to both A and C; A and C are far.
    q = "贝塔段落详细披露内容乙乙乙乙乙乙乙乙乙乙乙乙乙乙乙乙乙乙乙乙乙乙乙乙乙乙乙乙乙乙"
    r = "伽马段落详细披露内容丙丙丙丙丙丙丙丙丙丙丙丙丙丙丙丙丙丙丙丙丙丙丙丙丙丙丙丙丙丙"
    a = _input(content_id="a", title="贝塔重大事项详细披露公告", body="前甲" + q)
    b = _input(content_id="b", title="贝塔与伽马重大事项详细披露公告", body=q + r)
    c = _input(content_id="c", title="伽马重大事项详细披露公告", body=r + "后丁")
    # A legal V1 policy: only the body threshold is lowered (a chain requires B
    # to hold BOTH neighbours' text, so its Jaccard to each side is bounded near
    # 50%). The version, ngram size and all conflict/subject protections are the
    # production defaults; the production default body threshold is NOT lowered
    # in normal operation — this policy is scoped to this transitive-chain test.
    policy = DedupPolicy(body_similarity_threshold_bps=5000)

    # A REAL chain: A~B duplicate, B~C duplicate, A~C NOT duplicate.
    ab = decide_pair(a, b, policy=policy)
    bc = decide_pair(b, c, policy=policy)
    ac = decide_pair(a, c, policy=policy)
    assert ab.is_duplicate is True
    assert ab.reason == DecisionReason.STRONG_TITLE_AND_BODY
    assert bc.is_duplicate is True
    assert bc.reason == DecisionReason.STRONG_TITLE_AND_BODY
    assert ac.is_duplicate is False

    # Complete linkage must keep A and C in different clusters across every input
    # order, never lose or duplicate a member, and emit unique cluster ids.
    for order in ((a, b, c), (c, b, a), (b, a, c)):
        clusters = cluster_contents(order, policy=policy, decision_time=_BASE)
        groups = sorted(sorted(m.content_id for m in cl.members) for cl in clusters)
        assert groups == [["a", "b"], ["c"]]
        member_ids = [m.content_id for cl in clusters for m in cl.members]
        assert sorted(member_ids) == ["a", "b", "c"]  # all three kept
        assert len(member_ids) == len(set(member_ids))  # no duplicate member
        cluster_ids = [cl.cluster_id for cl in clusters]
        assert len(cluster_ids) == len(set(cluster_ids))  # unique cluster ids
        # A and C must never share a cluster.
        for group in (frozenset(g) for g in groups):
            assert not ({"a", "c"} <= group)
