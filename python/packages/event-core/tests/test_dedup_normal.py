"""Near-duplicate detection — normal near-duplicate tests (P3-N03).

Second RED group: identical content from different sources clusters; a repost
with a lightly changed title and highly similar body clusters; each member
keeps its own content_id and provenance; master selection is deterministic and
auditable; policy version and per-signal evidence are preserved.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from event_core.dedup import (
    DecisionReason,
    DedupInput,
    DedupPolicy,
    Eligibility,
    cluster_contents,
    decide_pair,
)

_BASE = datetime(2026, 8, 21, 1, 0, tzinfo=UTC)
_DECISION = datetime(2030, 1, 1, tzinfo=UTC)

_LONG_BODY = (
    "某上市公司发布公告，宣布拟以现金方式收购目标资产，"
    "交易金额约为人民币十亿元，本次交易尚需通过股东大会审议以及监管机构批准。"
    "公司表示本次收购有助于完善产业链布局，提升核心竞争力与持续盈利能力。"
)


def _input(
    *,
    content_id: str,
    title: str,
    body: str,
    source_id: str,
    available_time: datetime = _BASE,
    subject_keys: tuple[str, ...] = (),
) -> DedupInput:
    return DedupInput(
        content_id=content_id,
        record_id=f"rec-{content_id}",
        version_id="b" * 64,
        source_id=source_id,
        source_revision="v1",
        available_time=available_time,
        normalization_version="norm-v1",
        normalization_policy_id="pol-fp-1",
        title=title,
        body=body,
        eligibility=Eligibility.ELIGIBLE,
        subject_keys=subject_keys,
    )


def test_identical_content_different_sources_clusters() -> None:
    a = _input(content_id="a", title="重大资产收购公告", body=_LONG_BODY, source_id="cninfo")
    b = _input(content_id="b", title="重大资产收购公告", body=_LONG_BODY, source_id="sina")
    clusters = cluster_contents((a, b), policy=DedupPolicy(), decision_time=_DECISION)
    assert len(clusters) == 1
    assert {m.content_id for m in clusters[0].members} == {"a", "b"}


def test_exact_pair_decision_is_exact_match() -> None:
    a = _input(content_id="a", title="重大资产收购公告", body=_LONG_BODY, source_id="cninfo")
    b = _input(content_id="b", title="重大资产收购公告", body=_LONG_BODY, source_id="sina")
    decision = decide_pair(a, b, policy=DedupPolicy())
    assert decision.is_duplicate is True
    assert decision.signals.exact_match is True
    assert decision.reason == DecisionReason.EXACT_CONTENT_MATCH


def test_light_title_rewrite_high_body_similarity_clusters() -> None:
    body_repost = _LONG_BODY + "（转载自权威媒体）"
    a = _input(content_id="a", title="某公司重大资产收购公告", body=_LONG_BODY, source_id="cninfo")
    b = _input(
        content_id="b", title="某公司重大资产收购事项公告", body=body_repost, source_id="sina"
    )
    clusters = cluster_contents((a, b), policy=DedupPolicy(), decision_time=_DECISION)
    assert len(clusters) == 1
    assert {m.content_id for m in clusters[0].members} == {"a", "b"}


def test_repost_pair_reason_is_strong_title_and_body() -> None:
    body_repost = _LONG_BODY + "（转载自权威媒体）"
    a = _input(content_id="a", title="某公司重大资产收购公告", body=_LONG_BODY, source_id="cninfo")
    b = _input(
        content_id="b", title="某公司重大资产收购事项公告", body=body_repost, source_id="sina"
    )
    decision = decide_pair(a, b, policy=DedupPolicy())
    assert decision.is_duplicate is True
    assert decision.reason == DecisionReason.STRONG_TITLE_AND_BODY
    # per-signal evidence is preserved and quantized
    assert 0 <= decision.signals.title_similarity_bps <= 10000
    assert 0 <= decision.signals.body_similarity_bps <= 10000


def test_members_keep_own_identity_and_provenance() -> None:
    a = _input(content_id="a", title="重大资产收购公告", body=_LONG_BODY, source_id="cninfo")
    b = _input(content_id="b", title="重大资产收购公告", body=_LONG_BODY, source_id="sina")
    clusters = cluster_contents((a, b), policy=DedupPolicy(), decision_time=_DECISION)
    by_id = {m.content_id: m for m in clusters[0].members}
    assert by_id["a"].source_id == "cninfo"
    assert by_id["b"].source_id == "sina"
    assert by_id["a"].record_id == "rec-a"
    assert by_id["b"].record_id == "rec-b"


def test_master_is_earliest_available_time() -> None:
    early = _input(
        content_id="a",
        title="重大资产收购公告",
        body=_LONG_BODY,
        source_id="cninfo",
        available_time=_BASE,
    )
    late = _input(
        content_id="b",
        title="重大资产收购公告",
        body=_LONG_BODY,
        source_id="sina",
        available_time=_BASE + timedelta(hours=2),
    )
    clusters = cluster_contents((early, late), policy=DedupPolicy(), decision_time=_DECISION)
    assert clusters[0].master_content_id == "a"


def test_master_tie_break_uses_content_id() -> None:
    a = _input(content_id="zzz", title="重大资产收购公告", body=_LONG_BODY, source_id="cninfo")
    b = _input(content_id="aaa", title="重大资产收购公告", body=_LONG_BODY, source_id="sina")
    clusters = cluster_contents((a, b), policy=DedupPolicy(), decision_time=_DECISION)
    # same available_time -> smallest content_id wins
    assert clusters[0].master_content_id == "aaa"


def test_output_carries_policy_fingerprint() -> None:
    a = _input(content_id="a", title="重大资产收购公告", body=_LONG_BODY, source_id="cninfo")
    b = _input(content_id="b", title="重大资产收购公告", body=_LONG_BODY, source_id="sina")
    policy = DedupPolicy()
    clusters = cluster_contents((a, b), policy=policy, decision_time=_DECISION)
    assert clusters[0].policy_fingerprint == policy.fingerprint()
