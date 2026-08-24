"""Near-duplicate detection — status and failure-path tests (P3-N03).

Fourth RED group: not-consumable statuses excluded, unknown status fail-closed
at the boundary, naive datetime rejected, invalid thresholds/negative/oob
rejected, missing content_id/provenance rejected, empty-body and
insufficient-attachment content handled conservatively.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from event_core.dedup import (
    DedupInput,
    DedupPolicy,
    Eligibility,
    cluster_contents,
)

_BASE = datetime(2026, 8, 21, 1, 0, tzinfo=UTC)
_DECISION = datetime(2030, 1, 1, tzinfo=UTC)

_LONG_BODY = "某公司发布重大事项公告，具体内容如下所述，敬请投资者关注相关风险。" * 3


def _input(
    *,
    content_id: str = "c1",
    title: str = "重大事项公告",
    body: str = _LONG_BODY,
    eligibility: Eligibility = Eligibility.ELIGIBLE,
    available_time: datetime = _BASE,
    source_id: str = "src",
) -> DedupInput:
    return DedupInput(
        content_id=content_id,
        record_id=f"rec-{content_id}",
        version_id="d" * 64,
        source_id=source_id,
        source_revision="v1",
        available_time=available_time,
        normalization_version="norm-v1",
        normalization_policy_id="pol-fp-1",
        title=title,
        body=body,
        eligibility=eligibility,
    )


# --- eligibility fail-closed filtering --------------------------------------


def test_not_consumable_excluded_from_clustering() -> None:
    ok = _input(content_id="ok", source_id="a")
    dup = _input(content_id="dup", source_id="b")
    # a rejected/tombstone/quality-review record maps to NOT_CONSUMABLE upstream
    bad = _input(content_id="bad", source_id="c", eligibility=Eligibility.NOT_CONSUMABLE)
    clusters = cluster_contents((ok, dup, bad), policy=DedupPolicy(), decision_time=_DECISION)
    all_members = {m.content_id for cl in clusters for m in cl.members}
    assert "bad" not in all_members
    assert {"ok", "dup"} <= all_members


def test_empty_content_stays_singleton() -> None:
    # EMPTY_BODY / ATTACHMENT_ONLY upstream -> EMPTY_CONTENT: kept but never
    # near-duplicate-merged with anything (no comparable body).
    a = _input(content_id="a", body="", eligibility=Eligibility.EMPTY_CONTENT, source_id="a")
    b = _input(content_id="b", body="", eligibility=Eligibility.EMPTY_CONTENT, source_id="b")
    clusters = cluster_contents((a, b), policy=DedupPolicy(), decision_time=_DECISION)
    assert len(clusters) == 2
    for cluster in clusters:
        assert len(cluster.members) == 1


def test_unknown_eligibility_fails_closed() -> None:
    # a value outside the Eligibility enum must be rejected at the boundary.
    with pytest.raises((TypeError, ValueError)):
        _input(eligibility="mystery_status")  # type: ignore[arg-type]


# --- datetime boundary ------------------------------------------------------


def test_naive_available_time_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        _input(available_time=datetime(2026, 8, 21, 1, 0))  # naive


def test_naive_decision_time_rejected() -> None:
    a = _input(content_id="a")
    with pytest.raises(ValueError, match="timezone"):
        cluster_contents((a,), policy=DedupPolicy(), decision_time=datetime(2026, 8, 21, 2, 0))


# --- policy validation ------------------------------------------------------


def test_negative_threshold_rejected() -> None:
    with pytest.raises((ValueError, TypeError)):
        DedupPolicy(title_similarity_threshold_bps=-1)


def test_out_of_range_threshold_rejected() -> None:
    with pytest.raises(ValueError):
        DedupPolicy(body_similarity_threshold_bps=10001)


def test_zero_ngram_rejected() -> None:
    with pytest.raises(ValueError):
        DedupPolicy(ngram_size=0)


def test_negative_min_chars_rejected() -> None:
    with pytest.raises(ValueError):
        DedupPolicy(min_body_chars=-5)


# --- provenance validation --------------------------------------------------


def test_missing_content_id_rejected() -> None:
    with pytest.raises(ValueError, match="content_id"):
        _input(content_id="   ")


def test_missing_source_id_rejected() -> None:
    with pytest.raises(ValueError, match="source_id"):
        _input(source_id="")
