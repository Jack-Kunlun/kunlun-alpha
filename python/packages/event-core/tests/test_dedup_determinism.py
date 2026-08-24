"""Near-duplicate detection — determinism and fingerprint tests (P3-N03).

First RED group: stable content hash, no concatenation ambiguity, input-order
independence, deterministic policy fingerprint, fingerprint sensitivity, and
stable cluster id / member order / master.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from event_core.dedup import (
    DEDUP_ALGORITHM_VERSION,
    DedupInput,
    DedupPolicy,
    Eligibility,
    cluster_contents,
    cluster_identity,
    content_hash,
)

_BASE = datetime(2026, 8, 21, 1, 0, tzinfo=UTC)
_DECISION = datetime(2030, 1, 1, tzinfo=UTC)


def _input(
    *,
    content_id: str,
    title: str = "同一事件标题",
    body: str = "这是一段足够长的正文内容用于近重复检测的确定性测试。" * 3,
    source_id: str = "src-a",
    source_revision: str = "v1",
    record_id: str | None = None,
    version_id: str | None = None,
    available_time: datetime = _BASE,
    eligibility: Eligibility = Eligibility.ELIGIBLE,
    subject_keys: tuple[str, ...] = (),
) -> DedupInput:
    return DedupInput(
        content_id=content_id,
        record_id=record_id or f"rec-{content_id}",
        version_id=version_id or ("a" * 64),
        source_id=source_id,
        source_revision=source_revision,
        available_time=available_time,
        normalization_version="norm-v1",
        normalization_policy_id="pol-fp-1",
        title=title,
        body=body,
        eligibility=eligibility,
        subject_keys=subject_keys,
    )


# --- stable content hash ----------------------------------------------------


def test_content_hash_is_deterministic() -> None:
    a = content_hash("标题", "正文内容")
    b = content_hash("标题", "正文内容")
    assert a == b


def test_content_hash_is_version_prefixed_sha256() -> None:
    value = content_hash("标题", "正文内容")
    prefix, _, digest = value.partition(":")
    assert prefix == "neardup-v1"
    assert len(digest) == 64
    assert digest == digest.lower()
    assert all(c in "0123456789abcdef" for c in digest)


def test_content_hash_no_concatenation_ambiguity() -> None:
    # title "ab" + body "c" must never collide with title "a" + body "bc".
    assert content_hash("ab", "c") != content_hash("a", "bc")


def test_content_hash_changes_with_content() -> None:
    assert content_hash("标题", "正文一") != content_hash("标题", "正文二")


# --- policy fingerprint -----------------------------------------------------


def test_same_policy_same_fingerprint() -> None:
    assert DedupPolicy().fingerprint() == DedupPolicy().fingerprint()


def test_fingerprint_is_version_prefixed() -> None:
    fp = DedupPolicy().fingerprint()
    assert fp.startswith("neardup-v1:")


def test_threshold_change_changes_fingerprint() -> None:
    a = DedupPolicy().fingerprint()
    b = DedupPolicy(body_similarity_threshold_bps=9000).fingerprint()
    assert a != b


def test_ngram_change_changes_fingerprint() -> None:
    a = DedupPolicy().fingerprint()
    b = DedupPolicy(ngram_size=4).fingerprint()
    assert a != b


def test_low_information_titles_change_changes_fingerprint() -> None:
    a = DedupPolicy().fingerprint()
    b = DedupPolicy(low_information_titles=("公告",)).fingerprint()
    assert a != b


# --- cluster identity -------------------------------------------------------


def test_cluster_identity_is_order_independent() -> None:
    policy = DedupPolicy()
    assert cluster_identity(("c1", "c2", "c3"), policy=policy) == cluster_identity(
        ("c3", "c1", "c2"), policy=policy
    )


# --- version namespace consistency (I3) -------------------------------------


def test_unsupported_policy_version_is_rejected() -> None:
    # V1 only implements neardup-v1; a policy claiming another version would
    # produce a neardup-v2 policy fingerprint but a neardup-v1 cluster id — an
    # inconsistent, unmigrateable identity. Reject it instead.
    with pytest.raises(ValueError):
        DedupPolicy(version="neardup-v2")


def test_default_policy_version_matches_algorithm_version() -> None:
    assert DedupPolicy().version == DEDUP_ALGORITHM_VERSION


# --- public identity helpers cannot forge an algorithm version (I round 3) --
#
# content_hash and cluster_identity are exported helpers that mint persistent
# identity. The version prefix is NOT caller-supplied metadata: V1 only
# implements neardup-v1, so a caller must not be able to stamp a "neardup-v2"
# (or "latest", or any custom) prefix onto what is really the V1 algorithm, nor
# feed cluster_identity a forged bare fingerprint that never came from a
# validated DedupPolicy. Both would create records whose declared identity
# disagrees with the algorithm that produced them.


def test_content_hash_rejects_forged_version() -> None:
    # V1 removes the version parameter entirely: a caller may not claim another
    # algorithm version. Passing one must fail loudly (TypeError), never return
    # a forged neardup-v2 prefix over the V1 digest.
    with pytest.raises(TypeError):
        content_hash("标题", "正文", version="neardup-v2")  # type: ignore[call-arg]


def test_content_hash_rejects_latest_version() -> None:
    with pytest.raises(TypeError):
        content_hash("标题", "正文", version="latest")  # type: ignore[call-arg]


def test_content_hash_rejects_empty_version() -> None:
    with pytest.raises(TypeError):
        content_hash("标题", "正文", version="")  # type: ignore[call-arg]


def test_content_hash_rejects_case_variant_version() -> None:
    with pytest.raises(TypeError):
        content_hash("标题", "正文", version="NEARDUP-V1")  # type: ignore[call-arg]


def test_content_hash_default_v1_is_stable_and_prefixed() -> None:
    value = content_hash("标题", "正文")
    assert value.startswith(f"{DEDUP_ALGORITHM_VERSION}:")
    # stable across calls
    assert value == content_hash("标题", "正文")


def test_cluster_identity_rejects_bare_forged_fingerprint() -> None:
    # A bare fingerprint string is no longer trusted: the caller could forge a
    # "neardup-v2:forged" (or a valid-looking neardup-v1: + 64 hex) fingerprint
    # that never came from a validated DedupPolicy. The helper must require a
    # DedupPolicy and derive the fingerprint itself.
    with pytest.raises(TypeError):
        cluster_identity(("a", "b"), "neardup-v2:forged")  # type: ignore[arg-type]


def test_cluster_identity_rejects_valid_looking_bare_fingerprint() -> None:
    # A syntactically valid-looking neardup-v1 prefix + 64 hex digest is still
    # a bare string, not a validated policy, and must be rejected too.
    forged = "neardup-v1:" + "0" * 64
    with pytest.raises(TypeError):
        cluster_identity(("a", "b"), forged)  # type: ignore[arg-type]


def test_cluster_identity_accepts_validated_policy() -> None:
    policy = DedupPolicy()
    cid = cluster_identity(("a", "b"), policy=policy)
    assert cid.startswith(f"{DEDUP_ALGORITHM_VERSION}:")


def test_cluster_identity_binds_policy_fingerprint() -> None:
    # The cluster id must be built from the policy's own fingerprint, so two
    # policies with different parameters yield different cluster ids for the
    # same members.
    a = cluster_identity(("c1", "c2"), policy=DedupPolicy())
    b = cluster_identity(("c1", "c2"), policy=DedupPolicy(body_similarity_threshold_bps=9000))
    assert a != b


def test_content_hash_policy_fingerprint_cluster_id_share_version_prefix() -> None:
    policy = DedupPolicy()
    prefix = f"{DEDUP_ALGORITHM_VERSION}:"
    ch = content_hash("标题", "正文内容")
    fp = policy.fingerprint()
    cid = cluster_identity(("c1", "c2"), policy=policy)
    assert ch.startswith(prefix)
    assert fp.startswith(prefix)
    assert cid.startswith(prefix)


def test_cluster_id_binds_policy_and_is_order_stable_via_engine() -> None:
    a = _input(content_id="c1", source_id="src-a")
    b = _input(content_id="c2", source_id="src-b")
    policy = DedupPolicy()
    forward = cluster_contents((a, b), policy=policy, decision_time=_DECISION)
    reverse = cluster_contents((b, a), policy=policy, decision_time=_DECISION)
    assert [cl.cluster_id for cl in forward] == [cl.cluster_id for cl in reverse]
    # every emitted cluster id carries the algorithm version prefix
    for cl in forward:
        assert cl.cluster_id.startswith(f"{DEDUP_ALGORITHM_VERSION}:")


# --- deterministic clustering (order-independence) --------------------------


def test_clustering_is_input_order_independent() -> None:
    a = _input(content_id="c1", source_id="src-a")
    b = _input(content_id="c2", source_id="src-b")
    c = _input(content_id="c3", source_id="src-c")
    forward = cluster_contents((a, b, c), policy=DedupPolicy(), decision_time=_DECISION)
    reverse = cluster_contents((c, b, a), policy=DedupPolicy(), decision_time=_DECISION)
    # same cluster ids, same member order, same masters
    assert [cl.cluster_id for cl in forward] == [cl.cluster_id for cl in reverse]
    assert [cl.master_content_id for cl in forward] == [cl.master_content_id for cl in reverse]
    for cluster in forward:
        assert [m.content_id for m in cluster.members] == sorted(
            m.content_id for m in cluster.members
        )


def test_clustering_is_deterministic_across_runs() -> None:
    a = _input(content_id="c1", source_id="src-a")
    b = _input(content_id="c2", source_id="src-b")
    first = cluster_contents((a, b), policy=DedupPolicy(), decision_time=_DECISION)
    second = cluster_contents((a, b), policy=DedupPolicy(), decision_time=_DECISION)
    assert first == second


# --- duplicate content_id rejection at the entrypoint (I2 round 2) ----------
#
# ``content_id`` is the stable, persistent identity of a normalized content
# record and the key that carries evidence downstream. Two inputs sharing a
# ``content_id`` within one call violate that identity contract: the resulting
# cluster ids and master selection would depend on which duplicate happened to
# win, and downstream consumers that key on ``content_id`` would silently drop
# or overwrite evidence. ``cluster_contents`` must fail-closed at the
# entrypoint — before any decision_time filtering, eligibility filtering, pair
# cache construction or clustering — with a clear, stable error that names the
# duplicate content_id(s). It must never silently keep, de-duplicate or reorder
# its way around the collision.


def _dup_error_message(exc: pytest.ExceptionInfo[ValueError]) -> str:
    return str(exc.value)


def test_duplicate_content_id_same_payload_is_rejected() -> None:
    a = _input(content_id="dupe", source_id="src-a")
    b = _input(content_id="dupe", source_id="src-a")  # identical payload, same id
    with pytest.raises(ValueError) as exc:
        cluster_contents((a, b), policy=DedupPolicy(), decision_time=_DECISION)
    message = _dup_error_message(exc)
    assert "duplicate content_id" in message
    assert "dupe" in message


def test_duplicate_content_id_different_payload_is_rejected() -> None:
    a = _input(content_id="dupe", title="标题甲", body="正文甲" * 20, source_id="src-a")
    b = _input(content_id="dupe", title="标题乙", body="正文乙" * 20, source_id="src-b")
    with pytest.raises(ValueError) as exc:
        cluster_contents((a, b), policy=DedupPolicy(), decision_time=_DECISION)
    message = _dup_error_message(exc)
    assert "duplicate content_id" in message
    assert "dupe" in message


def test_same_object_passed_twice_is_rejected() -> None:
    a = _input(content_id="dupe", source_id="src-a")
    with pytest.raises(ValueError) as exc:
        cluster_contents((a, a), policy=DedupPolicy(), decision_time=_DECISION)
    assert "duplicate content_id" in _dup_error_message(exc)


def test_duplicate_content_id_reports_ids_deterministically() -> None:
    # two distinct collisions; the error must name every duplicate id and do so
    # in a stable, sorted order regardless of input order.
    a1 = _input(content_id="alpha", source_id="src-a")
    a2 = _input(content_id="alpha", source_id="src-b")
    b1 = _input(content_id="beta", source_id="src-c")
    b2 = _input(content_id="beta", source_id="src-d")
    unique = _input(content_id="gamma", source_id="src-e")
    forward = pytest.raises(ValueError)
    with forward as exc_fwd:
        cluster_contents((a1, b1, unique, a2, b2), policy=DedupPolicy(), decision_time=_DECISION)
    with pytest.raises(ValueError) as exc_rev:
        cluster_contents((b2, a2, unique, b1, a1), policy=DedupPolicy(), decision_time=_DECISION)
    msg_fwd = _dup_error_message(exc_fwd)
    msg_rev = _dup_error_message(exc_rev)
    assert msg_fwd == msg_rev  # order-independent, deterministic message
    assert "alpha" in msg_fwd
    assert "beta" in msg_fwd
    assert "gamma" not in msg_fwd  # the unique id is not a duplicate
    assert msg_fwd.index("alpha") < msg_fwd.index("beta")  # sorted


def test_duplicate_rejected_even_when_one_is_after_decision_time() -> None:
    # A duplicate content_id must be rejected wholesale even if one of the
    # colliding inputs would have been filtered out by point-in-time; the
    # collision is an identity error, not something PIT filtering may mask.
    early = _input(content_id="dupe", available_time=_BASE, source_id="src-a")
    late = _input(
        content_id="dupe",
        available_time=datetime(2031, 1, 1, tzinfo=UTC),
        source_id="src-b",
    )
    with pytest.raises(ValueError) as exc:
        cluster_contents((early, late), policy=DedupPolicy(), decision_time=_DECISION)
    assert "duplicate content_id" in _dup_error_message(exc)


def test_duplicate_rejected_even_when_one_is_not_consumable() -> None:
    # Likewise a NOT_CONSUMABLE input that would be dropped by eligibility must
    # not let its content_id collision slip past.
    kept = _input(content_id="dupe", eligibility=Eligibility.ELIGIBLE, source_id="src-a")
    dropped = _input(
        content_id="dupe",
        eligibility=Eligibility.NOT_CONSUMABLE,
        source_id="src-b",
    )
    with pytest.raises(ValueError) as exc:
        cluster_contents((kept, dropped), policy=DedupPolicy(), decision_time=_DECISION)
    assert "duplicate content_id" in _dup_error_message(exc)


def test_unique_content_ids_are_unaffected() -> None:
    # The uniqueness gate must not change behaviour for well-formed input.
    a = _input(content_id="c1", source_id="src-a")
    b = _input(content_id="c2", source_id="src-b")
    clusters = cluster_contents((a, b), policy=DedupPolicy(), decision_time=_DECISION)
    ids = sorted(m.content_id for cl in clusters for m in cl.members)
    assert ids == ["c1", "c2"]


def test_empty_input_contract_is_unchanged() -> None:
    assert cluster_contents((), policy=DedupPolicy(), decision_time=_DECISION) == ()
