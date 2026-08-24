"""Near-duplicate detection — point-in-time tests (P3-N03).

Fifth RED group: content whose available_time is later than decision_time is
invisible; early publish_time cannot leak a late available_time record into a
historical cluster; replaying an earlier decision_time after a new repost keeps
the original historical result; the same instant expressed in different
timezones yields the same result.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from event_core.dedup import (
    DedupInput,
    DedupPolicy,
    Eligibility,
    cluster_contents,
)

_LONG_BODY = (
    "某上市公司发布重大合同公告，公司近日与客户签订了金额较大的销售合同，"
    "预计对本年度经营业绩产生积极影响，敬请广大投资者理性投资注意风险。"
)

_T0 = datetime(2026, 8, 21, 1, 0, tzinfo=UTC)
_T_LATER = datetime(2026, 8, 21, 5, 0, tzinfo=UTC)


def _input(
    *,
    content_id: str,
    source_id: str,
    available_time: datetime,
    title: str = "重大合同公告",
    body: str = _LONG_BODY,
) -> DedupInput:
    return DedupInput(
        content_id=content_id,
        record_id=f"rec-{content_id}",
        version_id="e" * 64,
        source_id=source_id,
        source_revision="v1",
        available_time=available_time,
        normalization_version="norm-v1",
        normalization_policy_id="pol-fp-1",
        title=title,
        body=body,
        eligibility=Eligibility.ELIGIBLE,
    )


def test_future_available_time_is_invisible() -> None:
    visible = _input(content_id="a", source_id="cninfo", available_time=_T0)
    future = _input(content_id="b", source_id="sina", available_time=_T_LATER)
    clusters = cluster_contents(
        (visible, future), policy=DedupPolicy(), decision_time=_T0 + timedelta(hours=1)
    )
    members = {m.content_id for cl in clusters for m in cl.members}
    assert "a" in members
    assert "b" not in members  # available_time later than decision_time


def test_available_time_controls_visibility_not_publish_time() -> None:
    # a repost that becomes available late must not enter an earlier cluster,
    # even though its (source) publish could be early — only available_time
    # governs point-in-time visibility here.
    original = _input(content_id="a", source_id="cninfo", available_time=_T0)
    late_repost = _input(content_id="b", source_id="sina", available_time=_T_LATER)
    at_t0 = cluster_contents((original, late_repost), policy=DedupPolicy(), decision_time=_T0)
    members = {m.content_id for cl in at_t0 for m in cl.members}
    assert members == {"a"}


def test_replay_earlier_decision_time_is_stable_after_new_repost() -> None:
    original = _input(content_id="a", source_id="cninfo", available_time=_T0)
    late_repost = _input(content_id="b", source_id="sina", available_time=_T_LATER)
    # historical replay at _T0 must not see the later repost
    historical = cluster_contents((original, late_repost), policy=DedupPolicy(), decision_time=_T0)
    historical_members = {m.content_id for cl in historical for m in cl.members}
    assert historical_members == {"a"}
    # and running again yields the identical historical result
    again = cluster_contents((original, late_repost), policy=DedupPolicy(), decision_time=_T0)
    assert historical == again


def test_same_instant_different_timezone_same_result() -> None:
    cst = timezone(timedelta(hours=8))
    a_utc = _input(content_id="a", source_id="cninfo", available_time=_T0)
    b_utc = _input(content_id="b", source_id="sina", available_time=_T0)
    # same instants expressed in +08:00
    a_cst = _input(content_id="a", source_id="cninfo", available_time=_T0.astimezone(cst))
    b_cst = _input(content_id="b", source_id="sina", available_time=_T0.astimezone(cst))
    utc_clusters = cluster_contents((a_utc, b_utc), policy=DedupPolicy(), decision_time=_T_LATER)
    cst_clusters = cluster_contents(
        (a_cst, b_cst), policy=DedupPolicy(), decision_time=_T_LATER.astimezone(cst)
    )
    assert utc_clusters == cst_clusters


def test_omitting_decision_time_is_rejected() -> None:
    # I2: a pure domain function has no trustworthy "now"; a caller that omits
    # decision_time must fail loudly rather than silently clustering *all* data
    # (which would leak future-available content into a historical decision).
    a = _input(content_id="a", source_id="cninfo", available_time=_T0)
    with pytest.raises(TypeError):
        cluster_contents((a,), policy=DedupPolicy())  # type: ignore[call-arg]


def test_available_time_equal_to_decision_time_is_visible() -> None:
    a = _input(content_id="a", source_id="cninfo", available_time=_T0)
    b = _input(content_id="b", source_id="sina", available_time=_T0)
    clusters = cluster_contents((a, b), policy=DedupPolicy(), decision_time=_T0)
    members = {m.content_id for cl in clusters for m in cl.members}
    assert members == {"a", "b"}  # available_time == decision_time is visible
