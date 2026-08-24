"""Deterministic entity candidate extraction (P3-N04).

Algorithm (documented, deterministic, offline):

1.  Lexicon visibility filtering — only entries whose availability window
    contains ``decision_time`` are eligible (point-in-time).
2.  Exact code-point term matching over the normalized text. ASCII matching is
    case-insensitive (the lexicon lower-cases both sides); Chinese terms need
    no word boundary. For ASCII terms a boundary guard rejects partial tokens
    (e.g. ``600519`` must not match inside ``6005191``).
3.  Six-digit bare numbers are **never** auto-recognized as securities:
    dates, amounts and counters must not be bound. A ``SECURITY`` mention is
    produced only when a registered canonical symbol (e.g. ``600519.SH``) is
    in the lexicon.
4.  Longest-match overlapping resolution — when two candidate spans overlap,
    the longer span wins; on exact equal spans, every distinct entity type is
    kept (one mention per (span, type)); every visible lexicon entry of that
    (span, type) is delivered as an ``EntityCandidate`` (deterministic
    entry_id order) so same-name entities survive for downstream
    disambiguation.
5.  Low-information generic terms are kept at low confidence with a
    ``LOW_INFORMATION`` reason; the raw observation is never dropped.

The extraction itself is pure: ``decision_time`` is supplied by the caller and
used only to filter lexicon visibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from event_core.entities.dictionary import DictionaryEntry, EntityLexicon, lexicon_fingerprint
from event_core.entities.models import (
    ENTITY_EXTRACTION_VERSION,
    EntityCandidate,
    EntityMention,
    EntityPolicyVersionError,
    EntityType,
    ExtractionPolicy,
    ExtractionReason,
    ExtractionResult,
    ascii_fold,
    build_evidence,
    compute_mention_id,
    normalize_surface,
)

_ASCII_TAIL = re.compile(r"[A-Za-z0-9]")
_BARE_SIX_DIGITS = re.compile(r"(?<!\d)\d{6}(?!\d)")


@dataclass(frozen=True)
class OriginalRun:
    """Minimal P3-N02 run mapping carried by value (optional provenance).

    ``original_start``/``original_end`` reference the immutable original text;
    the extractor never fabricates them.
    """

    original_start: int
    original_end: int


def _require_aware(dt: datetime, name: str) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _ascii_boundary_ok(text: str, start: int, end: int) -> bool:
    if start > 0 and text[start - 1].isascii() and text[start - 1].isalnum():
        return False
    return not (end < len(text) and text[end].isascii() and text[end].isalnum())


def extract_entities(
    text: str,
    lexicon: EntityLexicon,
    *,
    content_id: str,
    decision_time: datetime,
    policy: ExtractionPolicy | None = None,
    original_runs: dict[tuple[int, int], OriginalRun] | None = None,
) -> ExtractionResult:
    """Extract candidate entity mentions from normalized ``text``.

    ``original_runs`` maps normalized spans to original-text runs (provenance
    only, never fabricated). Returns all observations, including low-confidence
    ones (callers use ``is_eligible`` for the high-confidence view).
    """
    if not text:
        raise ValueError("text must be a non-empty str")
    if not content_id:
        raise ValueError("content_id must be non-empty")
    _require_aware(decision_time, "decision_time")
    policy = policy or ExtractionPolicy()
    if policy.version != ENTITY_EXTRACTION_VERSION:
        raise EntityPolicyVersionError(f"unsupported policy version: {policy.version!r}")
    fingerprint = policy.fingerprint()

    mentions: list[EntityMention] = []
    candidates: list[EntityCandidate] = []

    # Longest-match scan: iterate terms longest-first, then resolve overlaps.
    raw_hits: list[tuple[int, int, str]] = []
    folded_text = ascii_fold(text)
    for term in lexicon.terms:
        folded_term = ascii_fold(term)
        start = folded_text.find(folded_term)
        while start != -1:
            end = start + len(term)
            if _ascii_boundary_ok(text, start, end):
                raw_hits.append((start, end, term))
            start = folded_text.find(folded_term, start + 1)

    # Group every visible lexicon entry by normalized span. All entries of the
    # same (span, type) are kept as candidates (deterministic entry_id order);
    # a single mention is emitted per (span, type) from the first entry.
    span_entries: dict[tuple[int, int], list[DictionaryEntry]] = {}
    for start, end, term in raw_hits:
        for entry in lexicon.lookup(term):
            if not entry.visible_at(decision_time):
                continue
            bucket = span_entries.setdefault((start, end), [])
            if all(e.entry_id != entry.entry_id for e in bucket):
                bucket.append(entry)

    for span in span_entries:
        span_entries[span].sort(key=lambda e: (e.entry_id, e.entity_type.value))

    accepted: list[tuple[int, int, str]] = []
    seen_span_type: set[tuple[int, int, str]] = set()
    for (start, end), entries in sorted(
        span_entries.items(), key=lambda kv: (kv[0][1] - kv[0][0], kv[0][0]), reverse=True
    ):
        for entry in entries:
            span_key = (start, end)
            if any(_overlaps(span_key, (s, e)) and (s, e) != span_key for s, e, _t in accepted):
                continue
            if (start, end, entry.entity_type.value) in seen_span_type:
                continue
            accepted.append((start, end, entry.entity_type.value))
            seen_span_type.add((start, end, entry.entity_type.value))
            typed_entries = tuple(e for e in entries if e.entity_type is entry.entity_type)
            representative = min(
                typed_entries,
                key=lambda e: (-e.confidence_bps, e.entry_id),
            )
            surface = text[start:end]
            reason = (
                ExtractionReason.AMBIGUOUS_LEXICON
                if len(typed_entries) > 1
                else _reason_for(representative, policy)
            )
            run = original_runs.get((start, end)) if original_runs else None
            mention_id = compute_mention_id(
                content_id=content_id,
                entity_type=representative.entity_type,
                start_offset=start,
                end_offset=end,
                surface=surface,
                policy=policy,
            )
            mentions.append(
                EntityMention(
                    mention_id=mention_id,
                    content_id=content_id,
                    entity_type=representative.entity_type,
                    surface=surface,
                    normalized_surface=normalize_surface(surface),
                    start_offset=start,
                    end_offset=end,
                    extractor_version=ENTITY_EXTRACTION_VERSION,
                    policy_fingerprint=fingerprint,
                    confidence_bps=representative.confidence_bps,
                    eligibility_threshold_bps=policy.min_confidence_bps,
                    reason=reason,
                    evidence=build_evidence(content_id, start, end, surface),
                    original_start=run.original_start if run else None,
                    original_end=run.original_end if run else None,
                )
            )
            # Deliver every candidate for this (span, type): same-name
            # entities must survive for downstream disambiguation.
            for cand_entry in typed_entries:
                candidates.append(
                    EntityCandidate(
                        mention_id=mention_id,
                        entry_id=cand_entry.entry_id,
                        target=cand_entry.entry_id,
                        entity_type=cand_entry.entity_type,
                        surface=surface,
                        start_offset=start,
                        end_offset=end,
                        score_bps=cand_entry.confidence_bps,
                        reason=_reason_for(cand_entry, policy),
                        source=cand_entry.source,
                    )
                )

    mentions.sort(key=lambda m: (m.start_offset, m.end_offset, m.entity_type.value))
    candidates.sort(
        key=lambda c: (
            c.start_offset,
            c.end_offset,
            c.entity_type.value,
            c.entry_id,
        )
    )
    return ExtractionResult(
        text=text,
        mentions=tuple(mentions),
        extractor_version=ENTITY_EXTRACTION_VERSION,
        policy_fingerprint=fingerprint,
        lexicon_fingerprint=lexicon_fingerprint(lexicon),
        decision_time=decision_time,
        candidates=tuple(candidates),
    )


def _reason_for(entry: DictionaryEntry, policy: ExtractionPolicy) -> ExtractionReason:
    if entry.entity_type is EntityType.SECURITY:
        return ExtractionReason.SYMBOL_EXACT
    if entry.confidence_bps < policy.min_confidence_bps:
        return ExtractionReason.LOW_INFORMATION
    return ExtractionReason.LEXICON_EXACT


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


__all__ = ["OriginalRun", "extract_entities"]
