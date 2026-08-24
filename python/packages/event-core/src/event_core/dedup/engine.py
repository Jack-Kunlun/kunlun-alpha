"""Deterministic near-duplicate decision, clustering and master selection.

Pure domain logic: given immutable :class:`DedupInput` candidates and a
versioned :class:`DedupPolicy`, produce explainable pair decisions and
deterministic, conservative clusters. No I/O, no randomness, no wall-clock
time; the only time input is an explicit ``decision_time`` for point-in-time
visibility.

Conservatism / fail-closed principles:

* not-consumable inputs never cluster; empty-content inputs stay singletons;
* conflicting non-empty subject clues block a merge even on an exact content
  hash match (different companies' template announcements must not merge);
* a duplicate requires *both* title and body similarity at/above threshold on
  non-exact content — a shared generic title alone or a shared template body
  alone is never enough;
* clustering uses complete linkage (every pair inside a cluster must be a
  duplicate), so an A~B, B~C but A≁C chain can never bridge A and C;
* master selection is deterministic: earliest ``available_time`` then smallest
  ``content_id``; it never depends on input order, wall-clock time or randomness
  and never overwrites a member's own evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime

from event_core.dedup.models import (
    ClusterMember,
    ContentCluster,
    DecisionReason,
    DedupInput,
    DedupPolicy,
    Eligibility,
    MasterReason,
    PairDecision,
    SimilaritySignals,
    cluster_identity,
    content_hash,
)
from event_core.dedup.similarity import body_similarity_bps, title_similarity_bps


def _require_aware_utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"timezone required: naive datetime is rejected ({name})")
    return value.astimezone(UTC)


def _normalized_char_len(text: str) -> int:
    """Length of the whitespace-collapsed text (comparable-content length)."""
    return len("".join(text.split()))


def _subject_conflict(left: DedupInput, right: DedupInput) -> bool:
    """True when both carry non-empty subject clues that do not overlap.

    Missing subject clues on either side are *not* a conflict (the dedup node
    does not invent subject identity — that is P3-N04); only an explicit,
    non-empty, disjoint pair of clue sets is a conflict.
    """
    left_keys = set(left.subject_keys)
    right_keys = set(right.subject_keys)
    if not left_keys or not right_keys:
        return False
    return left_keys.isdisjoint(right_keys)


def _subject_reliably_same(left: DedupInput, right: DedupInput) -> bool:
    """True only when both sides carry non-empty, intersecting subject clues.

    This is the *positive* confirmation that two records concern the same
    subject. A missing clue on either side is never treated as a confirmation
    (fail-closed): the dedup node does not guess a subject (that is P3-N04). It
    is used to gate low-information-title merges, where a shared boilerplate
    body alone (common across different issuers) must not drive a merge.
    """
    left_keys = set(left.subject_keys)
    right_keys = set(right.subject_keys)
    if not left_keys or not right_keys:
        return False
    return not left_keys.isdisjoint(right_keys)


def _is_low_information_title(title: str, policy: DedupPolicy) -> bool:
    collapsed = "".join(title.split())
    if collapsed in policy.low_information_titles:
        return True
    return len(collapsed) < policy.min_title_chars


def _signals(left: DedupInput, right: DedupInput, policy: DedupPolicy) -> SimilaritySignals:
    exact = content_hash(left.title, left.body) == content_hash(right.title, right.body)
    return SimilaritySignals(
        exact_match=exact,
        title_similarity_bps=title_similarity_bps(left.title, right.title, policy.ngram_size),
        body_similarity_bps=body_similarity_bps(left.body, right.body, policy.ngram_size),
    )


def decide_pair(left: DedupInput, right: DedupInput, *, policy: DedupPolicy) -> PairDecision:
    """Compare two candidates and return an explainable, fail-closed decision.

    Precedence of reasons (first match wins):

    1. either side not consumable / empty content → not duplicate;
    2. conflicting non-empty subject clues → not duplicate (even on exact hash);
    3. either body shorter than ``min_body_chars`` → not duplicate (too short);
    4. exact versioned content hash match → duplicate;
    5. a low-information title on either side without a strong body → not
       duplicate (a generic title must not drive a merge);
    6. both title and body at/above threshold → duplicate;
    7. otherwise → not duplicate, with the weaker signal named.
    """
    signals = _signals(left, right, policy)
    fingerprint = policy.fingerprint()

    def build(is_duplicate: bool, reason: DecisionReason) -> PairDecision:
        return PairDecision(
            left_content_id=left.content_id,
            right_content_id=right.content_id,
            is_duplicate=is_duplicate,
            signals=signals,
            reason=reason,
            policy_fingerprint=fingerprint,
        )

    if left.eligibility != Eligibility.ELIGIBLE or right.eligibility != Eligibility.ELIGIBLE:
        return build(False, DecisionReason.NOT_CONSUMABLE)

    if policy.enforce_subject_conflict and _subject_conflict(left, right):
        return build(False, DecisionReason.SUBJECT_KEY_CONFLICT)

    if (
        _normalized_char_len(left.body) < policy.min_body_chars
        or _normalized_char_len(right.body) < policy.min_body_chars
    ):
        return build(False, DecisionReason.CONTENT_TOO_SHORT)

    title_bps = signals.title_similarity_bps
    body_ok = signals.body_similarity_bps >= policy.body_similarity_threshold_bps
    title_strong = title_bps >= policy.title_similarity_threshold_bps
    title_congruent = title_bps >= policy.title_congruence_floor_bps

    if signals.exact_match:
        return build(True, DecisionReason.EXACT_CONTENT_MATCH)

    low_info = _is_low_information_title(left.title, policy) or _is_low_information_title(
        right.title, policy
    )
    if low_info:
        # A generic/low-information title must never drive clustering by
        # itself, and a shared template body under a generic title is NOT
        # enough — different issuers routinely reuse boilerplate. Only a
        # reliable, matching subject clue on BOTH sides (fail-closed when
        # missing) may confirm the same subject and allow a strong-body merge.
        if body_ok and _subject_reliably_same(left, right):
            return build(True, DecisionReason.STRONG_TITLE_AND_BODY)
        return build(False, DecisionReason.LOW_INFORMATION_TITLE)

    # A merge on non-exact content requires a strong body (the authoritative
    # repost signal) AND a title that is at least congruent — so a shared
    # template body with unrelated titles (title below the floor) never merges,
    # and a strong title with a weak body never merges either.
    if body_ok and title_congruent:
        return build(True, DecisionReason.STRONG_TITLE_AND_BODY)
    if body_ok and not title_congruent:
        return build(False, DecisionReason.BODY_TEMPLATE_INSUFFICIENT)
    if title_strong and not body_ok:
        return build(False, DecisionReason.TITLE_ONLY_INSUFFICIENT)
    return build(False, DecisionReason.BELOW_THRESHOLD)


def select_master(members: tuple[DedupInput, ...]) -> tuple[str, MasterReason]:
    """Pick a deterministic master: earliest available_time, then content_id.

    Never depends on input order, wall-clock time or randomness. Returns the
    chosen ``content_id`` and the reason. A tie on ``available_time`` is broken
    by the smallest ``content_id`` (a stable, cross-platform ordinal).
    """
    if not members:
        raise ValueError("cannot select a master from an empty member set")
    if len(members) == 1:
        return members[0].content_id, MasterReason.SOLE_MEMBER
    ordered = sorted(members, key=lambda m: (m.available_time, m.content_id))
    best = ordered[0]
    earliest = [m for m in ordered if m.available_time == best.available_time]
    reason = (
        MasterReason.EARLIEST_AVAILABLE_TIME
        if len(earliest) == 1
        else MasterReason.CONTENT_ID_TIE_BREAK
    )
    return best.content_id, reason


def _self_signals() -> SimilaritySignals:
    return SimilaritySignals(
        exact_match=True,
        title_similarity_bps=10000,
        body_similarity_bps=10000,
    )


def _build_cluster(
    group: tuple[DedupInput, ...],
    pair_reason: dict[frozenset[str], DecisionReason],
    policy: DedupPolicy,
) -> ContentCluster:
    fingerprint = policy.fingerprint()
    master_id, master_reason = select_master(group)
    master_input = next(m for m in group if m.content_id == master_id)
    members: list[ClusterMember] = []
    for candidate in sorted(group, key=lambda m: m.content_id):
        if candidate.content_id == master_id:
            similarity = _self_signals()
            join_reason = DecisionReason.EXACT_CONTENT_MATCH
        else:
            similarity = _signals(master_input, candidate, policy)
            key = frozenset({master_id, candidate.content_id})
            join_reason = pair_reason.get(key, DecisionReason.STRONG_TITLE_AND_BODY)
        members.append(
            ClusterMember(
                content_id=candidate.content_id,
                record_id=candidate.record_id,
                version_id=candidate.version_id,
                source_id=candidate.source_id,
                source_revision=candidate.source_revision,
                available_time=candidate.available_time,
                is_master=candidate.content_id == master_id,
                similarity_to_master=similarity,
                join_reason=join_reason,
            )
        )
    cluster_id = cluster_identity(tuple(m.content_id for m in members), policy=policy)
    return ContentCluster(
        cluster_id=cluster_id,
        master_content_id=master_id,
        master_reason=master_reason,
        members=tuple(members),
        policy_fingerprint=fingerprint,
    )


def _reject_duplicate_content_ids(inputs: tuple[DedupInput, ...]) -> None:
    """Fail-closed if any ``content_id`` appears more than once in this call.

    ``content_id`` is the stable, persistent identity of a normalized record and
    the key downstream consumers use to attach evidence. Two inputs sharing a
    ``content_id`` — even the very same object passed twice, or a collision where
    one side would later be dropped by point-in-time or eligibility filtering —
    make cluster identity and master selection ambiguous and would silently drop
    or overwrite evidence downstream. This runs *before* any decision_time
    filtering, eligibility filtering, pair-cache construction or clustering, so a
    would-be-filtered duplicate can never mask the collision. The error message
    names every duplicate id in a stable, sorted order for a deterministic,
    cross-platform diagnostic.
    """
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in inputs:
        if item.content_id in seen:
            duplicates.add(item.content_id)
        else:
            seen.add(item.content_id)
    if duplicates:
        listed = ", ".join(sorted(duplicates))
        raise ValueError(f"duplicate content_id in a single cluster_contents call: {listed}")


def cluster_contents(
    inputs: tuple[DedupInput, ...],
    *,
    policy: DedupPolicy,
    decision_time: datetime,
) -> tuple[ContentCluster, ...]:
    """Cluster near-duplicate content deterministically and conservatively.

    Identity: every input's ``content_id`` must be unique within a single call.
    A repeated ``content_id`` — including the same object passed twice, and even
    when one of the colliding inputs would later be filtered out by
    point-in-time or eligibility — is rejected fail-closed *before* any filtering
    or clustering, because it makes cluster identity, master selection and
    downstream evidence attribution ambiguous.

    Point-in-time: ``decision_time`` is **required** — a pure domain function
    has no trustworthy wall clock, so the caller must state the instant the
    decision is made. Only inputs whose ``available_time`` is not later than
    ``decision_time`` participate; a record that becomes available later can
    never leak into an earlier decision. ``decision_time`` must be
    timezone-aware (naive is rejected); the same instant in any timezone yields
    the same result. There is no implicit "cluster everything" path.

    Eligibility: ``NOT_CONSUMABLE`` inputs are dropped; ``EMPTY_CONTENT`` inputs
    are kept but always form their own singleton (no comparable body).

    Linkage: complete linkage — a candidate joins an existing cluster only if it
    is a duplicate of *every* current member, so an A~B, B~C, A≁C chain never
    bridges A and C. Candidates are processed in a stable ``content_id`` order,
    and both cluster membership and cluster ids are order-independent.
    """
    _reject_duplicate_content_ids(inputs)
    decision = _require_aware_utc(decision_time, "decision_time")

    eligible: list[DedupInput] = []
    singletons: list[DedupInput] = []
    for item in inputs:
        if item.available_time > decision:
            continue  # not yet available at the decision time
        if item.eligibility == Eligibility.NOT_CONSUMABLE:
            continue
        if item.eligibility == Eligibility.EMPTY_CONTENT:
            singletons.append(item)
            continue
        eligible.append(item)

    # deterministic processing order
    eligible.sort(key=lambda m: m.content_id)

    # precompute pair decisions (also used for join-reason provenance)
    pair_duplicate: dict[frozenset[str], bool] = {}
    pair_reason: dict[frozenset[str], DecisionReason] = {}
    for i in range(len(eligible)):
        for j in range(i + 1, len(eligible)):
            decision_pair = decide_pair(eligible[i], eligible[j], policy=policy)
            key = frozenset({eligible[i].content_id, eligible[j].content_id})
            pair_duplicate[key] = decision_pair.is_duplicate
            pair_reason[key] = decision_pair.reason

    # complete-linkage grouping
    groups: list[list[DedupInput]] = []
    for item in eligible:
        placed = False
        for group in groups:
            if all(
                pair_duplicate.get(frozenset({item.content_id, member.content_id}), False)
                for member in group
            ):
                group.append(item)
                placed = True
                break
        if not placed:
            groups.append([item])

    clusters = [_build_cluster(tuple(group), pair_reason, policy) for group in groups]
    clusters.extend(_build_cluster((item,), pair_reason, policy) for item in singletons)
    # stable output order by cluster master content id
    clusters.sort(key=lambda c: c.master_content_id)
    return tuple(clusters)
