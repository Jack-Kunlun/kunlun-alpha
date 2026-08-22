"""Normalization model: operations, edit records, span runs, policy, audit.

Offset semantics (single source of truth, repeated in the package README):

* all offsets are zero-based, half-open ``[start, end)`` character intervals
  over Python ``str`` code points;
* ``original_*`` offsets refer to the immutable original RawContent text;
* ``normalized_*`` offsets refer to the final normalized text;
* zero-width spans (``start == end``) are legal and mark insert/delete points.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

NORMALIZATION_VERSION = "normalize-v1"


class Operation(StrEnum):
    REMOVE_BOM = "remove_bom"
    NEWLINE_LF = "newline_lf"
    UNICODE_NFC = "unicode_nfc"
    MOJIBAKE_RECOVER = "mojibake_recover"
    REMOVE_CONTROL = "remove_control"
    HTML_TAG_STRIP = "html_tag_strip"
    HTML_ENTITY = "html_entity"
    HTML_INVISIBLE_STRIP = "html_invisible_strip"
    WHITESPACE_COLLAPSE = "whitespace_collapse"
    TRUNCATE = "truncate"


class Reason(StrEnum):
    UTF8_BOM_PREFIX = "utf8_bom_prefix"
    CRLF_NEWLINE = "crlf_newline"
    CR_NEWLINE = "cr_newline"
    UNICODE_NFC_COMPOSITION = "unicode_nfc_composition"
    MOJIBAKE_LATIN1_UTF8_ROUNDTRIP = "mojibake_latin1_utf8_roundtrip"
    CONTROL_CHARACTER_REMOVED = "control_character_removed"
    HTML_TAG_REMOVED = "html_tag_removed"
    HTML_LINE_BREAK = "html_line_break"
    HTML_ENTITY_DECODED = "html_entity_decoded"
    HTML_INVISIBLE_CONTENT_REMOVED = "html_invisible_content_removed"
    HTML_COMMENT_REMOVED = "html_comment_removed"
    WHITESPACE_COLLAPSED = "whitespace_collapsed"
    WHITESPACE_TRIMMED = "whitespace_trimmed"
    CONTENT_TRUNCATED = "content_truncated"


class UnsupportedNormalizationVersionError(ValueError):
    """The requested normalization strategy version is not supported."""


class UnrecoverableTextError(ValueError):
    """The text contains damage (e.g. U+FFFD) that cannot be safely repaired."""


class NormalizationAuditError(ValueError):
    """A normalization result failed its reversibility/consistency audit."""


class NormalizationStatus(StrEnum):
    OK = "ok"
    EMPTY_BODY = "empty_body"
    ATTACHMENT_ONLY = "attachment_only"
    QUALITY_REVIEW_REQUIRED = "quality_review_required"
    TOMBSTONE = "tombstone"
    REJECTED = "rejected"


class EmptyBodyReason(StrEnum):
    EMPTY = "empty"
    WHITESPACE_ONLY = "whitespace_only"
    CONTROL_CHARS_ONLY = "control_chars_only"
    HTML_INVISIBLE_ONLY = "html_invisible_only"


class RejectionReason(StrEnum):
    MOJIBAKE_UNRECOVERABLE = "mojibake_unrecoverable"


class QualityReviewReason(StrEnum):
    SUSPECTED_MOJIBAKE = "suspected_mojibake"
    PARTIAL_MOJIBAKE_SUSPECTED = "partial_mojibake_suspected"


def _require_span(start: int, end: int, name: str) -> None:
    if type(start) is not int or type(end) is not int:
        raise TypeError(f"{name} offsets must be int")
    if start < 0 or end < 0:
        raise ValueError(f"{name} offsets must be non-negative")
    if start > end:
        raise ValueError(f"{name}_start must be <= {name}_end")


@dataclass(frozen=True)
class EditRecord:
    """One reversible cleaning operation over an original text.

    ``original_fragment`` is the exact slice of the original text at
    ``[original_start, original_end)``; ``replacement_fragment`` is what the
    operation put in its place at creation time. The final
    ``[normalized_start, normalized_end)`` span locates the surviving part of
    the replacement in the final normalized text; it may be zero-width when a
    later stage consumed the replacement (e.g. an entity-decoded space later
    removed by whitespace collapse).
    """

    operation: Operation
    original_start: int
    original_end: int
    normalized_start: int
    normalized_end: int
    original_fragment: str
    replacement_fragment: str
    reason: Reason
    normalization_version: str

    def __post_init__(self) -> None:
        _require_span(self.original_start, self.original_end, "original")
        _require_span(self.normalized_start, self.normalized_end, "normalized")
        if len(self.original_fragment) != self.original_end - self.original_start:
            raise ValueError("original_fragment length must match original span")
        if self.normalization_version != NORMALIZATION_VERSION:
            raise UnsupportedNormalizationVersionError(
                f"unsupported normalization version: {self.normalization_version!r}"
            )


@dataclass(frozen=True)
class SpanRun:
    """A run of normalized positions sharing the same original span.

    ``normalized_fragment`` is the authoritative normalized text this run
    contributes, recorded at finalization from the edit lineage (for edited
    runs) or from the surviving identity characters (for 1:1 runs). It is the
    ground truth the audit compares ``NormalizedText.text`` against, so a
    tampered ``text`` (e.g. a swapped NFC-composed or entity-decoded character)
    is detected even though the original span is unchanged.
    """

    normalized_start: int
    normalized_end: int
    original_start: int
    original_end: int
    normalized_fragment: str

    def __post_init__(self) -> None:
        _require_span(self.normalized_start, self.normalized_end, "normalized")
        _require_span(self.original_start, self.original_end, "original")
        if len(self.normalized_fragment) != self.normalized_end - self.normalized_start:
            raise ValueError("normalized_fragment length must match normalized span")


@dataclass(frozen=True)
class NormalizedText:
    """A normalized text with its edit history and original-span mapping.

    ``runs`` partitions ``[0, len(text))`` into monotonic runs; each run states
    which original character range its normalized characters came from.
    """

    text: str
    runs: tuple[SpanRun, ...]
    edits: tuple[EditRecord, ...]

    def original_range(self, start: int, end: int) -> tuple[int, int]:
        """Map a normalized ``[start, end)`` range back to the original text.

        Returns the covering original range (``original_start`` of the first
        overlapping run, ``original_end`` of the last). For an empty range the
        position is anchored to the following run (or ``(0, 0)`` when empty).
        """
        if type(start) is not int or type(end) is not int:
            raise TypeError("range bounds must be int")
        if start < 0 or end < start or end > len(self.text):
            raise ValueError("invalid normalized range")
        first_start: int | None = None
        last_end = 0
        for run in self.runs:
            if run.normalized_start >= end:
                break
            if run.normalized_end > start:
                if first_start is None:
                    first_start = run.original_start
                last_end = run.original_end
        if first_start is not None:
            return (first_start, last_end)
        for run in self.runs:
            if run.normalized_start >= start:
                return (run.original_start, run.original_start)
        if self.runs:
            anchor = self.runs[-1].original_end
            return (anchor, anchor)
        return (0, 0)


@dataclass(frozen=True)
class NormalizationPolicy:
    """Versioned, deterministic normalization strategy parameters."""

    version: str = NORMALIZATION_VERSION
    max_title_length: int = 1000
    max_body_length: int = 100_000
    strip_html: bool = False
    recover_mojibake: bool = True
    author_separators: tuple[str, ...] = (",", ";", "，", "；", "、", "/", "|")

    def __post_init__(self) -> None:
        if self.version != NORMALIZATION_VERSION:
            raise UnsupportedNormalizationVersionError(
                f"unsupported normalization version: {self.version!r} "
                f"(supported: {NORMALIZATION_VERSION!r})"
            )
        if self.max_title_length <= 0:
            raise ValueError("max_title_length must be positive")
        if self.max_body_length <= 0:
            raise ValueError("max_body_length must be positive")
        for separator in self.author_separators:
            if type(separator) is not str or not separator:
                raise ValueError("author_separators must be non-empty strings")

    def fingerprint(self) -> str:
        """Deterministic 64-hex SHA-256 identity over every result-affecting param.

        Two policies with the same ``normalization_version`` but different
        parameters (limits, ``strip_html``, ``recover_mojibake``, separators)
        produce different results, so they must have different identities to be
        reproducible. The identity is a canonical-JSON (sorted keys, fixed
        separators, UTF-8, non-ASCII preserved) SHA-256 — stable and
        cross-platform. Python's built-in ``hash()`` is never used.
        """
        material = {
            "version": self.version,
            "max_title_length": self.max_title_length,
            "max_body_length": self.max_body_length,
            "strip_html": self.strip_html,
            "recover_mojibake": self.recover_mojibake,
            "author_separators": list(self.author_separators),
        }
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def restore_original(normalized: NormalizedText, original_length: int) -> str:
    """Reconstruct the original text from the public normalization result.

    Every original position is resolved from (in priority order): an edit
    record's original fragment (authoritative evidence, since it equals the
    original slice by contract) or a surviving identity character (singleton
    run not claimed by any edit). Positions that cannot be resolved mean
    content was silently lost or fabricated and raise
    :class:`NormalizationAuditError`.
    """
    resolved: dict[int, str] = {}
    for edit in normalized.edits:
        for offset, character in enumerate(edit.original_fragment):
            resolved[edit.original_start + offset] = character
    for run in normalized.runs:
        if (
            run.normalized_end - run.normalized_start == 1
            and run.original_end - run.original_start == 1
        ):
            position = run.original_start
            if position not in resolved:
                resolved[position] = normalized.text[run.normalized_start]
    parts: list[str] = []
    for position in range(original_length):
        character = resolved.get(position)
        if character is None:
            raise NormalizationAuditError(f"original position {position} is uncovered")
        parts.append(character)
    return "".join(parts)


def audit_normalization(original: str, normalized: NormalizedText) -> None:
    """Full-lineage audit: prove the normalized result is faithful and traceable.

    Verifies, fail-closed:

    * ``runs`` cover ``[0, len(text))`` contiguously and are monotonic in
      original offsets;
    * every run's authoritative ``normalized_fragment`` matches the actual
      slice of ``normalized.text`` (so tampering a *transformed* character —
      NFC, entity, CRLF, mojibake, collapsed space — is caught, not just the
      untouched 1:1 characters);
    * every edit's ``original_fragment`` is the exact original slice at its
      span (authoritative original evidence);
    * the original text reconstructs exactly from the public result.

    Because each run carries its authoritative ``normalized_fragment``, a
    tampered ``text`` is caught even when it swaps a *transformed* character
    (NFC, entity, CRLF, mojibake, collapsed space) whose original span is
    unchanged. Raises :class:`NormalizationAuditError` on any violation.
    """
    position = 0
    previous_start = 0
    previous_end = 0
    for run in normalized.runs:
        if run.normalized_start != position:
            raise NormalizationAuditError(
                f"runs must cover [0, len(text)) contiguously at normalized offset {position}"
            )
        if run.original_start < previous_start or run.original_end < previous_end:
            raise NormalizationAuditError("runs must be monotonic in original offsets")
        if normalized.text[run.normalized_start : run.normalized_end] != run.normalized_fragment:
            raise NormalizationAuditError(
                f"normalized text does not match run lineage at "
                f"[{run.normalized_start}, {run.normalized_end})"
            )
        previous_start = run.original_start
        previous_end = run.original_end
        position = run.normalized_end
    if position != len(normalized.text):
        raise NormalizationAuditError("runs must cover [0, len(text)) contiguously")
    for edit in normalized.edits:
        expected = original[edit.original_start : edit.original_end]
        if expected != edit.original_fragment:
            raise NormalizationAuditError(
                f"edit fragment mismatch at original span "
                f"[{edit.original_start}, {edit.original_end})"
            )
    if restore_original(normalized, len(original)) != original:
        raise NormalizationAuditError("reconstruction does not match the original text")
