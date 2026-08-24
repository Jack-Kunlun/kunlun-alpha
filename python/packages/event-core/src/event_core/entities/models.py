"""Entity extraction domain model (P3-N04).

Pure, deterministic, offline entity candidate extraction. No I/O, no network,
no LLM, no embedding, no database and no service dependency. This package
never imports ``intelligence_engine``; normalized text and P3-N02 span/run
mapping are carried by value into the extraction functions.

Entity kinds (at least): ``COMPANY``, ``SECURITY``, ``INSTITUTION``,
``PERSON``, ``POLICY``, ``REGION``.

Offset semantics (single source of truth):

* all offsets are zero-based, half-open ``[start, end)`` character intervals
  over Python ``str`` code points of the *normalized* input text;
* ``surface`` is the exact slice ``text[start:end]`` of the normalized text;
* ``original_start`` / ``original_end`` (optional) reference the immutable
  original text when a P3-N02 span/run mapping is available; they are
  provenance only and are never fabricated.

``mention_id`` is a stable SHA-256 over the content reference, entity type,
normalized span, surface and extractor identity (see
:func:`compute_mention_id`). Python's built-in ``hash()``, randomness, wall
clock and input ordering are never used for any persisted identity.

The lexicon is injected by the caller (see :mod:`event_core.entities.
dictionary`); this package never hard-codes a production company list.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

ENTITY_EXTRACTION_VERSION = "entities-v1"
"""The only implemented extraction algorithm generation.

Versioned identity prefix shared by every mention id and policy fingerprint in
V1. Bumping this constant is the only sanctioned way to change semantics; a
caller can never stamp a ``entities-v2`` / ``latest`` / arbitrary string onto a
V1 result.
"""


class EntityType(StrEnum):
    """Supported entity kinds for V1 candidate extraction."""

    COMPANY = "company"
    SECURITY = "security"
    INSTITUTION = "institution"
    PERSON = "person"
    POLICY = "policy"
    REGION = "region"


class ExtractionReason(StrEnum):
    """Stable reason codes for an extracted mention."""

    LEXICON_EXACT = "lexicon_exact"
    """A lexicon term (or alias) matched the normalized text exactly."""

    SYMBOL_EXACT = "symbol_exact"
    """A registered canonical symbol matched the normalized text exactly."""

    LOW_INFORMATION = "low_information"
    """Generic/high-frequency term; kept at low confidence, never high."""

    AMBIGUOUS_LEXICON = "ambiguous_lexicon"
    """Multiple lexicon entries share the same normalized span; the mention is
    the text observation only — disambiguation is the resolver's job."""


class EntityPolicyVersionError(ValueError):
    """An unsupported extraction policy version was requested."""


def _require_offsets(start: int, end: int) -> None:
    """Validate offsets without a text: they must be non-negative and ordered.

    ``start_offset`` / ``end_offset`` are document-wide coordinates; the
    mention itself does not carry the full text, so the exact slice check
    happens in :class:`ExtractionResult` where the full text is available.
    """
    if type(start) is not int or type(end) is not int:
        raise TypeError("span offsets must be int")
    if start < 0 or end < start:
        raise ValueError("offsets must satisfy 0 <= start <= end")


def _require_aware(dt: datetime, name: str) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def ascii_fold(value: str) -> str:
    """Lowercase ASCII letters without changing the string's code-point length."""
    return "".join(
        chr(ord(character) + (ord("a") - ord("A"))) if "A" <= character <= "Z" else character
        for character in value
    )


def normalize_surface(surface: str) -> str:
    """Deterministic normalization of an entity's own surface.

    ASCII casefolding plus whitespace collapsing. This is the canonical form
    used for alias/name matching: the surface text is preserved verbatim,
    while ``normalized_surface`` is what downstream matching operates on.
    """
    return ascii_fold(" ".join(surface.split()))


def build_evidence(content_id: str, start_offset: int, end_offset: int, surface: str) -> str:
    """Deterministic, auditable evidence string for an extracted mention.

    Binds the content reference, the document span and the surface text so an
    evidence record can be traced back to the exact source region. The format
    is stable and order-independent by construction.
    """
    if not content_id:
        raise ValueError("content_id must be non-empty")
    if type(start_offset) is not int or type(end_offset) is not int:
        raise TypeError("span offsets must be int")
    if start_offset < 0 or end_offset < start_offset:
        raise ValueError("offsets must satisfy 0 <= start <= end")
    if not surface:
        raise ValueError("surface must be non-empty")
    return f"{content_id}:{start_offset}:{end_offset}:{surface}"


def _require_confidence(confidence_bps: int) -> None:
    if type(confidence_bps) is not int or not 0 <= confidence_bps <= 10000:
        raise ValueError("confidence_bps must be an integer in [0, 10000]")


@dataclass(frozen=True)
class EntityMention:
    """A text observation of a candidate entity.

    A mention is a *fact* about the text (span + surface), not a binding: it
    carries no resolved security. Entity candidates and security resolution are
    downstream (P3-N04 ``market-core/resolver``).
    """

    mention_id: str
    content_id: str
    entity_type: EntityType
    surface: str
    normalized_surface: str
    start_offset: int
    end_offset: int
    extractor_version: str
    policy_fingerprint: str
    confidence_bps: int
    eligibility_threshold_bps: int
    reason: ExtractionReason
    evidence: str
    original_start: int | None = None
    original_end: int | None = None

    def __post_init__(self) -> None:
        if not self.mention_id:
            raise ValueError("mention_id must be non-empty")
        if not self.content_id:
            raise ValueError("content_id must be non-empty")
        if not self.surface:
            raise ValueError("surface must be non-empty")
        if not self.normalized_surface:
            raise ValueError("normalized_surface must be non-empty")
        if not self.policy_fingerprint:
            raise ValueError("policy_fingerprint must be non-empty")
        if self.extractor_version != ENTITY_EXTRACTION_VERSION:
            raise EntityPolicyVersionError(
                f"unsupported extractor version: {self.extractor_version!r}"
            )
        # start/end are document-wide offsets; they are validated structurally
        # here and exactly (surface == text[start:end]) in ExtractionResult.
        _require_offsets(self.start_offset, self.end_offset)
        if normalize_surface(self.surface) != self.normalized_surface:
            raise ValueError(
                "normalized_surface must equal normalize_surface(surface) "
                "(the entity's own surface, not the document text)"
            )
        _require_confidence(self.confidence_bps)
        _require_confidence(self.eligibility_threshold_bps)
        expected_policy_fingerprint = ExtractionPolicy(
            version=self.extractor_version,
            min_confidence_bps=self.eligibility_threshold_bps,
        ).fingerprint()
        if self.policy_fingerprint != expected_policy_fingerprint:
            raise ValueError(
                "policy_fingerprint must match extractor_version and eligibility_threshold_bps"
            )
        expected_evidence = build_evidence(
            self.content_id,
            self.start_offset,
            self.end_offset,
            self.surface,
        )
        if self.evidence != expected_evidence:
            raise ValueError("evidence must equal build_evidence(content_id, span, surface)")
        if self.original_start is not None or self.original_end is not None:
            if self.original_start is None or self.original_end is None:
                raise ValueError("original_start and original_end must be set together")
            if self.original_start < 0 or self.original_end < self.original_start:
                raise ValueError("original span must satisfy 0 <= start <= end")


@dataclass(frozen=True)
class EntityCandidate:
    """A candidate entity produced for a mention.

    Kept for evaluation/audit purposes: one mention can map to several lexicon
    candidates (same name, different companies). No candidate is ever selected
    by this package. Candidates are deterministically sorted and carry the
    lexicon entry/target, type, confidence, reason and source so downstream
    resolution can disambiguate same-name entities.
    """

    mention_id: str
    entry_id: str
    target: str
    entity_type: EntityType
    surface: str
    start_offset: int
    end_offset: int
    score_bps: int
    reason: ExtractionReason
    source: str

    def __post_init__(self) -> None:
        if not self.mention_id:
            raise ValueError("mention_id must be non-empty")
        if not self.entry_id:
            raise ValueError("entry_id must be non-empty")
        if not self.target:
            raise ValueError("target must be non-empty")
        if not self.surface:
            raise ValueError("surface must be non-empty")
        _require_offsets(self.start_offset, self.end_offset)
        _require_confidence(self.score_bps)
        if not self.source:
            raise ValueError("source must be non-empty")

    @property
    def candidate_key(self) -> str:
        return f"{self.mention_id}:{self.entry_id}"


@dataclass(frozen=True)
class ExtractionResult:
    """Deterministic output of a single extraction run."""

    text: str
    mentions: tuple[EntityMention, ...]
    extractor_version: str
    policy_fingerprint: str
    lexicon_fingerprint: str
    decision_time: datetime
    candidates: tuple[EntityCandidate, ...] = ()

    def __post_init__(self) -> None:
        if self.extractor_version != ENTITY_EXTRACTION_VERSION:
            raise EntityPolicyVersionError(
                f"unsupported extractor version: {self.extractor_version!r}"
            )
        if not self.policy_fingerprint:
            raise ValueError("policy_fingerprint must be non-empty")
        if not self.lexicon_fingerprint:
            raise ValueError("lexicon_fingerprint must be non-empty")
        _require_aware(self.decision_time, "decision_time")
        mention_ids: set[str] = set()
        for mention in self.mentions:
            if mention.extractor_version != self.extractor_version:
                raise ValueError("mention.extractor_version must equal result.extractor_version")
            if mention.policy_fingerprint != self.policy_fingerprint:
                raise ValueError("mention.policy_fingerprint must equal result.policy_fingerprint")
            if mention.surface != self.text[mention.start_offset : mention.end_offset]:
                raise ValueError("mention.surface must equal text[start_offset:end_offset]")
            if normalize_surface(mention.surface) != mention.normalized_surface:
                raise ValueError(
                    "mention.normalized_surface must equal normalize_surface(mention.surface)"
                )
            mention_ids.add(mention.mention_id)
        for candidate in self.candidates:
            if candidate.mention_id not in mention_ids:
                raise ValueError("candidate.mention_id must reference a mention in this result")
            mention = next(m for m in self.mentions if m.mention_id == candidate.mention_id)
            if candidate.surface != mention.surface:
                raise ValueError("candidate.surface must equal its mention surface")
            if (candidate.start_offset, candidate.end_offset) != (
                mention.start_offset,
                mention.end_offset,
            ):
                raise ValueError("candidate span must equal its mention span")


@dataclass(frozen=True)
class ExtractionPolicy:
    """Versioned, deterministic extraction parameters.

    ``min_confidence_bps`` only affects the *eligible* view: mentions below it
    are still returned (low-information mentions must not be silently
    dropped), but they are marked with a low-confidence reason and are not
    eligible for high-confidence use. The raw observation is never discarded.
    """

    version: str = ENTITY_EXTRACTION_VERSION
    min_confidence_bps: int = 6000

    def __post_init__(self) -> None:
        if self.version != ENTITY_EXTRACTION_VERSION:
            raise EntityPolicyVersionError(
                f"unsupported version: {self.version!r} (supported: {ENTITY_EXTRACTION_VERSION!r})"
            )
        _require_confidence(self.min_confidence_bps)

    def fingerprint(self) -> str:
        """Deterministic 64-hex SHA-256 over every result-affecting parameter.

        Canonical JSON (sorted keys, fixed separators, UTF-8, non-ASCII
        preserved) — stable and cross-platform. Never the built-in ``hash()``.
        """
        material = {
            "version": self.version,
            "min_confidence_bps": self.min_confidence_bps,
        }
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_mention_id(
    *,
    content_id: str,
    entity_type: EntityType,
    start_offset: int,
    end_offset: int,
    surface: str,
    policy: ExtractionPolicy,
) -> str:
    """Stable SHA-256 mention identity with explicit field boundaries.

    Field boundaries are unambiguous: each field is length-prefixed and
    NUL-separated, so no concatenation collision is possible. The identity
    binds content, type, span, surface and extractor identity; it never uses
    ``hash()``, randomness, wall clock or input ordering.
    """
    if not content_id:
        raise ValueError("content_id must be non-empty")
    if type(start_offset) is not int or type(end_offset) is not int:
        raise TypeError("span offsets must be int")
    if start_offset < 0 or end_offset < start_offset:
        raise ValueError("span must satisfy 0 <= start <= end")
    if not surface:
        raise ValueError("surface must be non-empty")
    extractor_version = policy.version
    policy_fingerprint = policy.fingerprint()
    material = (
        f"{len(content_id)}:{content_id}\x00"
        f"{len(entity_type.value)}:{entity_type.value}\x00"
        f"{start_offset}\x00{end_offset}\x00"
        f"{len(surface)}:{surface}\x00"
        f"{len(extractor_version)}:{extractor_version}\x00"
        f"{len(policy_fingerprint)}:{policy_fingerprint}"
    )
    return "mention:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def is_eligible(mention: EntityMention, policy: ExtractionPolicy | None = None) -> bool:
    """Whether a mention meets the policy's confidence bar.

    Mentions below the bar are still part of the extraction result — this
    predicate is the explicit gate a caller must use before treating a mention
    as a high-confidence observation.
    """
    if policy is not None and policy.fingerprint() != mention.policy_fingerprint:
        raise ValueError("policy fingerprint must match mention.policy_fingerprint")
    return mention.confidence_bps >= mention.eligibility_threshold_bps


def utc_now() -> datetime:
    """Explicit timezone-aware ``now`` used only for *recorded* provenance.

    Extraction itself is pure: the caller supplies ``decision_time`` and the
    lexicon is filtered by it, so a future lexicon entry can never leak into a
    historical decision. This helper is provided for callers that build
    provenance records (not for the extraction algorithm).
    """
    return datetime.now(UTC)


__all__ = [
    "ENTITY_EXTRACTION_VERSION",
    "EntityCandidate",
    "EntityMention",
    "EntityPolicyVersionError",
    "EntityType",
    "ExtractionPolicy",
    "ExtractionReason",
    "ExtractionResult",
    "ascii_fold",
    "build_evidence",
    "compute_mention_id",
    "is_eligible",
    "normalize_surface",
    "utc_now",
]
