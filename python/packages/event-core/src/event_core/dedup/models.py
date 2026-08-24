"""Immutable domain models for near-duplicate detection (P3-N03).

This module defines the *only* inputs and outputs of the deduplication domain.
It is pure: no I/O, no network, no LLM, no database, no service dependency, and
it never imports ``intelligence_engine`` (the dependency direction is
service → domain, never the reverse). Normalized text and provenance are
carried *by value* into :class:`DedupInput`; the caller (a normalization
service or an assembler) is responsible for projecting a normalized result
into this input, including a fail-closed ``eligibility`` decision.

Identity and offset conventions follow the rest of the repository: stable,
cross-process, cross-platform SHA-256 with an explicit versioned prefix; the
built-in ``hash()`` is never used for a persisted identity. All timestamps are
timezone-aware and normalized to UTC; naive datetimes are rejected at the
boundary.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

# Algorithm version for every persisted dedup identity (policy fingerprint,
# content hash, cluster id). Bumping this string is the *only* sanctioned way to
# change dedup semantics; historical identities keep their old meaning.
DEDUP_ALGORITHM_VERSION = "neardup-v1"

# Similarity scores are quantized to integer basis points in [0, 10000] to make
# threshold comparisons deterministic across platforms (no float epsilon drift
# at a boundary). 10000 bps == 1.0 == identical.
BASIS_POINTS_SCALE = 10000


def _require_non_empty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")
    return value


def _require_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a bool")
    return value


def _require_aware_utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"timezone required: naive datetime is rejected ({name})")
    return value.astimezone(UTC)


def _require_basis_points(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int in basis points")
    if not (0 <= value <= BASIS_POINTS_SCALE):
        raise ValueError(f"{name} must be within [0, {BASIS_POINTS_SCALE}]")
    return value


class Eligibility(StrEnum):
    """Minimal, fail-closed consumability boundary for a dedup input.

    The dedup domain does *not* re-implement the P3-N02 normalization state
    machine. The caller collapses the normalization status into exactly one of
    these values. Only :attr:`ELIGIBLE` may enter ordinary automatic
    clustering; every other value (including any unknown/未来 status the caller
    could not map) keeps the record out, fail-closed.
    """

    ELIGIBLE = "eligible"
    # Body is empty but the record is otherwise consumable (EMPTY_BODY /
    # ATTACHMENT_ONLY upstream). It is kept as its own singleton and never
    # near-duplicate-merged, because there is no comparable body content.
    EMPTY_CONTENT = "empty_content"
    # Not consumable at all (REJECTED / TOMBSTONE / QUALITY_REVIEW_REQUIRED
    # upstream, or unauthorized / not-yet-available / deleted). Excluded.
    NOT_CONSUMABLE = "not_consumable"


class DecisionReason(StrEnum):
    """Stable, auditable reason code for a pair decision.

    Never a free-text string, so downstream and evaluation code can branch on a
    stable enum.
    """

    EXACT_CONTENT_MATCH = "exact_content_match"
    STRONG_TITLE_AND_BODY = "strong_title_and_body"
    SUBJECT_KEY_CONFLICT = "subject_key_conflict"
    BELOW_THRESHOLD = "below_threshold"
    TITLE_ONLY_INSUFFICIENT = "title_only_insufficient"
    BODY_TEMPLATE_INSUFFICIENT = "body_template_insufficient"
    LOW_INFORMATION_TITLE = "low_information_title"
    CONTENT_TOO_SHORT = "content_too_short"
    NOT_CONSUMABLE = "not_consumable"


class MasterReason(StrEnum):
    """Why a member was chosen as the cluster's master record."""

    EARLIEST_AVAILABLE_TIME = "earliest_available_time"
    CONTENT_ID_TIE_BREAK = "content_id_tie_break"
    SOLE_MEMBER = "sole_member"


@dataclass(frozen=True)
class DedupInput:
    """One immutable near-duplicate candidate, carried entirely by value.

    It holds only what deduplication needs: a stable ``content_id``, the
    provenance needed to trace a member back to its raw record without a
    reverse dependency (``record_id`` / ``version_id`` / ``source_id`` /
    ``source_revision``), the point-in-time axis (``available_time``), the
    normalization identity (``normalization_version`` /
    ``normalization_policy_id``), the normalized ``title`` / ``body`` to compare,
    a fail-closed ``eligibility`` decision, and optional caller-supplied
    ``subject_keys`` (stable subject clues such as security symbols or a source
    subject key). The dedup node does *not* derive subject identity itself
    (that is P3-N04); it only *uses* conflicting clues defensively.

    A whole service object is never copied in, so the domain never gains a
    reverse dependency on a service.
    """

    content_id: str
    record_id: str
    version_id: str
    source_id: str
    source_revision: str
    available_time: datetime
    normalization_version: str
    normalization_policy_id: str
    title: str
    body: str
    eligibility: Eligibility
    subject_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty(self.content_id, "content_id")
        _require_non_empty(self.record_id, "record_id")
        _require_non_empty(self.version_id, "version_id")
        _require_non_empty(self.source_id, "source_id")
        _require_non_empty(self.source_revision, "source_revision")
        _require_non_empty(self.normalization_version, "normalization_version")
        _require_non_empty(self.normalization_policy_id, "normalization_policy_id")
        if type(self.title) is not str:
            raise TypeError("title must be a str")
        if type(self.body) is not str:
            raise TypeError("body must be a str")
        if type(self.eligibility) is not Eligibility:
            raise TypeError("eligibility must be an Eligibility")
        object.__setattr__(
            self, "available_time", _require_aware_utc(self.available_time, "available_time")
        )
        if type(self.subject_keys) is not tuple:
            raise TypeError("subject_keys must be a tuple")
        cleaned: list[str] = []
        seen: set[str] = set()
        for key in self.subject_keys:
            token = _require_non_empty(key, "subject_key").strip()
            if token not in seen:
                seen.add(token)
                cleaned.append(token)
        object.__setattr__(self, "subject_keys", tuple(cleaned))


@dataclass(frozen=True)
class DedupPolicy:
    """Immutable, versioned deduplication policy.

    Every parameter that can change a decision lives here, so a
    :meth:`fingerprint` uniquely and reproducibly identifies the configuration.
    Thresholds are integer basis points (see :data:`BASIS_POINTS_SCALE`) to make
    boundary comparisons deterministic. No floating ``latest``, no implicit
    global config and no wall-clock time participates in the fingerprint.
    """

    version: str = DEDUP_ALGORITHM_VERSION
    # Character n-gram width used by both title and body similarity (shingles).
    ngram_size: int = 3
    # A duplicate needs a strong body at/above ``body_similarity_threshold_bps``
    # AND a title that is at least *congruent* (>= title_congruence_floor_bps),
    # unless an exact content hash match short-circuits. The high title
    # threshold marks a title that is strong on its own; between the floor and
    # the high threshold a title only *supports* an already-strong body (the
    # real repost signal), while a title below the floor means the two are about
    # different things and must not merge even if the body template matches.
    title_similarity_threshold_bps: int = 7500
    title_congruence_floor_bps: int = 3000
    body_similarity_threshold_bps: int = 8000
    # Minimum normalized-character length for a body to be comparable; shorter
    # bodies are treated as too-short and never near-duplicate-merged.
    min_body_chars: int = 40
    # Minimum normalized-character length for a title to contribute on its own.
    min_title_chars: int = 6
    # Low-information titles that must never drive clustering by themselves.
    low_information_titles: tuple[str, ...] = (
        "公告",
        "通知",
        "重要提示",
        "澄清公告",
        "风险提示",
        "提示性公告",
        "补充公告",
        "更正公告",
    )
    # In V1 the subject-conflict protection is always on and cannot be turned
    # off by a caller: constructing a policy with it disabled is rejected (no
    # "valid but unsafe" policy). The field is kept only so the fingerprint
    # material is explicit and stable; any value other than True is refused.
    enforce_subject_conflict: bool = True

    def __post_init__(self) -> None:
        _require_non_empty(self.version, "version")
        # V1 implements exactly one algorithm generation. A policy claiming a
        # different version would emit that version in its fingerprint while
        # content_hash and cluster_identity still run V1 — an inconsistent,
        # unmigrateable identity. Reject any version other than the one this
        # code actually implements (bumping DEDUP_ALGORITHM_VERSION is the only
        # sanctioned way to change semantics).
        if self.version != DEDUP_ALGORITHM_VERSION:
            raise ValueError(
                f"unsupported dedup version {self.version!r}: "
                f"only {DEDUP_ALGORITHM_VERSION!r} is implemented"
            )
        if type(self.ngram_size) is not int:
            raise TypeError("ngram_size must be an int")
        if self.ngram_size < 1:
            raise ValueError("ngram_size must be >= 1")
        _require_basis_points(self.title_similarity_threshold_bps, "title_similarity_threshold_bps")
        _require_basis_points(self.title_congruence_floor_bps, "title_congruence_floor_bps")
        _require_basis_points(self.body_similarity_threshold_bps, "body_similarity_threshold_bps")
        if self.title_congruence_floor_bps > self.title_similarity_threshold_bps:
            raise ValueError("title_congruence_floor_bps must be <= title_similarity_threshold_bps")
        if type(self.min_body_chars) is not int:
            raise TypeError("min_body_chars must be an int")
        if self.min_body_chars < 0:
            raise ValueError("min_body_chars must be >= 0")
        if type(self.min_title_chars) is not int:
            raise TypeError("min_title_chars must be an int")
        if self.min_title_chars < 0:
            raise ValueError("min_title_chars must be >= 0")
        if type(self.low_information_titles) is not tuple:
            raise TypeError("low_information_titles must be a tuple")
        normalized_low_info: list[str] = []
        for title in self.low_information_titles:
            normalized_low_info.append(_require_non_empty(title, "low_information_title"))
        object.__setattr__(self, "low_information_titles", tuple(normalized_low_info))
        if _require_bool(self.enforce_subject_conflict, "enforce_subject_conflict") is not True:
            raise ValueError(
                "enforce_subject_conflict must stay True in V1: "
                "the subject-conflict protection cannot be disabled"
            )

    def fingerprint(self) -> str:
        """Deterministic 64-hex SHA-256 identity over every decision parameter.

        Canonical JSON (sorted keys, fixed separators, UTF-8, non-ASCII
        preserved) hashed with SHA-256, prefixed with the algorithm version so
        two different algorithm generations can never collide. The built-in
        ``hash()`` is never used.
        """
        material = {
            "version": self.version,
            "ngram_size": self.ngram_size,
            "title_similarity_threshold_bps": self.title_similarity_threshold_bps,
            "title_congruence_floor_bps": self.title_congruence_floor_bps,
            "body_similarity_threshold_bps": self.body_similarity_threshold_bps,
            "min_body_chars": self.min_body_chars,
            "min_title_chars": self.min_title_chars,
            "low_information_titles": list(self.low_information_titles),
            "enforce_subject_conflict": self.enforce_subject_conflict,
        }
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"{self.version}:{digest}"


@dataclass(frozen=True)
class SimilaritySignals:
    """Per-pair similarity evidence, all quantized and auditable.

    ``exact_match`` is the versioned content-hash equality; the two similarity
    scores are integer basis points (see :data:`BASIS_POINTS_SCALE`).
    """

    exact_match: bool
    title_similarity_bps: int
    body_similarity_bps: int

    def __post_init__(self) -> None:
        _require_bool(self.exact_match, "exact_match")
        _require_basis_points(self.title_similarity_bps, "title_similarity_bps")
        _require_basis_points(self.body_similarity_bps, "body_similarity_bps")


@dataclass(frozen=True)
class PairDecision:
    """The explainable result of comparing two candidates.

    Carries both signal scores, the final boolean, a stable
    :class:`DecisionReason` and the policy fingerprint that produced it.
    """

    left_content_id: str
    right_content_id: str
    is_duplicate: bool
    signals: SimilaritySignals
    reason: DecisionReason
    policy_fingerprint: str

    def __post_init__(self) -> None:
        _require_non_empty(self.left_content_id, "left_content_id")
        _require_non_empty(self.right_content_id, "right_content_id")
        _require_bool(self.is_duplicate, "is_duplicate")
        if type(self.signals) is not SimilaritySignals:
            raise TypeError("signals must be a SimilaritySignals")
        if type(self.reason) is not DecisionReason:
            raise TypeError("reason must be a DecisionReason")
        _require_non_empty(self.policy_fingerprint, "policy_fingerprint")


@dataclass(frozen=True)
class ClusterMember:
    """One member of a cluster with its own preserved identity and evidence.

    A member is never physically merged: it keeps its own ``content_id`` and
    full provenance (``record_id`` / ``version_id`` / ``source_id`` /
    ``source_revision`` / ``available_time``). ``similarity_to_master`` and
    ``join_reason`` record why it joined (the master itself has an exact-match
    self signal and ``SOLE_MEMBER``/master reason recorded on the cluster).
    """

    content_id: str
    record_id: str
    version_id: str
    source_id: str
    source_revision: str
    available_time: datetime
    is_master: bool
    similarity_to_master: SimilaritySignals
    join_reason: DecisionReason

    def __post_init__(self) -> None:
        _require_non_empty(self.content_id, "content_id")
        _require_non_empty(self.record_id, "record_id")
        _require_non_empty(self.version_id, "version_id")
        _require_non_empty(self.source_id, "source_id")
        _require_non_empty(self.source_revision, "source_revision")
        object.__setattr__(
            self, "available_time", _require_aware_utc(self.available_time, "available_time")
        )
        _require_bool(self.is_master, "is_master")
        if type(self.similarity_to_master) is not SimilaritySignals:
            raise TypeError("similarity_to_master must be a SimilaritySignals")
        if type(self.join_reason) is not DecisionReason:
            raise TypeError("join_reason must be a DecisionReason")


@dataclass(frozen=True)
class ContentCluster:
    """An immutable, deterministic near-duplicate cluster.

    ``cluster_id`` is a stable, version-prefixed SHA-256 over the sorted member
    content ids, so the same member set and policy always yield the same id,
    order and master regardless of input order. Members preserve their own
    identity and provenance; nothing is deleted or physically merged.
    """

    cluster_id: str
    master_content_id: str
    master_reason: MasterReason
    members: tuple[ClusterMember, ...]
    policy_fingerprint: str

    def __post_init__(self) -> None:
        _require_non_empty(self.cluster_id, "cluster_id")
        _require_non_empty(self.master_content_id, "master_content_id")
        if type(self.master_reason) is not MasterReason:
            raise TypeError("master_reason must be a MasterReason")
        if type(self.members) is not tuple or not self.members:
            raise ValueError("members must be a non-empty tuple")
        for member in self.members:
            if type(member) is not ClusterMember:
                raise TypeError("members must be ClusterMember instances")
        _require_non_empty(self.policy_fingerprint, "policy_fingerprint")
        masters = [m for m in self.members if m.is_master]
        if len(masters) != 1:
            raise ValueError("a cluster must have exactly one master member")
        if masters[0].content_id != self.master_content_id:
            raise ValueError("master_content_id must match the master member")


def cluster_identity(member_content_ids: tuple[str, ...], *, policy: DedupPolicy) -> str:
    """Deterministic, version-prefixed cluster id over a member set.

    Takes a **validated** :class:`DedupPolicy` — never a bare fingerprint
    string — so a caller cannot forge a version or inject a fingerprint that did
    not come from a policy whose version passed the V1 gate. The fingerprint is
    derived here via ``policy.fingerprint()`` and the version prefix comes from
    ``policy.version`` (already constrained to :data:`DEDUP_ALGORITHM_VERSION`).

    The member ids are sorted so that input order never changes the identity;
    the policy fingerprint is included so two different policies produce
    different cluster ids for the same members. Built-in ``hash()`` is never
    used.
    """
    if type(policy) is not DedupPolicy:
        raise TypeError("cluster_identity requires a validated DedupPolicy")
    fingerprint = policy.fingerprint()
    material = {
        "version": policy.version,
        "members": sorted(member_content_ids),
        "policy_fingerprint": fingerprint,
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{policy.version}:{digest}"


def content_hash(title: str, body: str) -> str:
    """Stable V1 content hash over normalized title + body.

    The version prefix is **not** caller-supplied metadata: V1 only implements
    ``neardup-v1`` and the prefix is always :data:`DEDUP_ALGORITHM_VERSION`.
    There is deliberately no ``version`` parameter — a caller must not be able
    to stamp another algorithm's version onto what is really the V1 digest. A
    future V2 requires a real implementation / explicit version dispatch, not a
    string argument.

    Field boundaries are unambiguous: title and body are length-prefixed and
    NUL-separated so that no concatenation collision is possible (e.g. title
    ``"ab"`` + body ``"c"`` can never hash-collide with title ``"a"`` + body
    ``"bc"``). Source id, url and ingest/scrape time are deliberately *not*
    mixed in — content similarity must depend only on content — while those
    remain preserved as provenance elsewhere. The result is version-prefixed so
    a future serialization change cannot silently reuse an old identity.
    """
    if type(title) is not str or type(body) is not str:
        raise TypeError("title and body must be str")
    title_bytes = title.encode("utf-8")
    body_bytes = body.encode("utf-8")
    payload = b"".join(
        (
            str(len(title_bytes)).encode("ascii"),
            b":",
            title_bytes,
            b"\x00",
            str(len(body_bytes)).encode("ascii"),
            b":",
            body_bytes,
        )
    )
    digest = hashlib.sha256(payload).hexdigest()
    return f"{DEDUP_ALGORITHM_VERSION}:{digest}"
