"""Entity lexicon (P3-N04).

A caller-injected, point-in-time aware dictionary used by the extractor. The
package ships only a *generic* builtin (regions, institutions and policy
terms of common public knowledge) — never a production company list. Company
and security lexicons are supplied by the caller so that the extractor stays
deterministic and offline.

Timestamps:

* ``available_from`` / ``available_to`` bound when a term is *known/usable*;
  they must be timezone-aware (naive datetimes are rejected) so that
  point-in-time decisions never mix zones.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from event_core.entities.models import EntityType, ascii_fold

BUILTIN_LEXICON_SOURCE = "builtin-generic-v1"
"""Source tag for the generic builtin lexicon.

The builtin is intentionally *generic*: it contains no production company or
security list. Callers must inject their own company/security lexicon.
"""


def _require_aware(dt: datetime, name: str) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class DictionaryEntry:
    """One normalized term (plus aliases) for one entity kind."""

    entry_id: str
    term: str
    entity_type: EntityType
    aliases: tuple[str, ...] = ()
    confidence_bps: int = 8000
    available_from: datetime | None = None
    available_to: datetime | None = None
    source: str = "manual"

    def __post_init__(self) -> None:
        if not self.entry_id:
            raise ValueError("entry_id must be non-empty")
        if not self.term.strip():
            raise ValueError("term must be non-empty")
        for alias in self.aliases:
            if not alias.strip():
                raise ValueError("aliases must be non-empty")
        if type(self.confidence_bps) is not int or not 0 <= self.confidence_bps <= 10000:
            raise ValueError("confidence_bps must be an integer in [0, 10000]")
        if self.available_from is not None:
            _require_aware(self.available_from, "available_from")
        if self.available_to is not None:
            _require_aware(self.available_to, "available_to")
        if (
            self.available_from is not None
            and self.available_to is not None
            and self.available_from > self.available_to
        ):
            raise ValueError("available_from must not be after available_to")

    def visible_at(self, decision_time: datetime) -> bool:
        """Whether the entry is usable at ``decision_time`` (point-in-time)."""
        _require_aware(decision_time, "decision_time")
        if self.available_from is not None and decision_time < self.available_from:
            return False
        return not (self.available_to is not None and decision_time > self.available_to)


class EntityLexicon:
    """Deterministic, immutable-after-validation lexicon.

    Terms are matched on exact code-point equality (the input is already
    normalized by the P3-N02 text pipeline). Matching is case-insensitive for
    ASCII by lowering both sides at build time — Chinese terms are unaffected.
    """

    def __init__(self, entries: Iterable[DictionaryEntry]) -> None:
        by_id: dict[str, DictionaryEntry] = {}
        for entry in entries:
            previous = by_id.get(entry.entry_id)
            if previous is None:
                by_id[entry.entry_id] = entry
                continue
            if _entry_semantic_key(previous) != _entry_semantic_key(entry):
                raise ValueError(f"conflicting duplicate entry_id: {entry.entry_id!r}")
        self._entries = tuple(sorted(by_id.values(), key=_entry_semantic_key))
        self._by_term: dict[str, list[DictionaryEntry]] = {}
        for entry in self._entries:
            terms = {entry.term, *entry.aliases}
            for term in terms:
                key = self._key(term)
                self._by_term.setdefault(key, []).append(entry)
        for key, grouped in self._by_term.items():
            self._by_term[key] = sorted(grouped, key=lambda e: e.entry_id)
        # Terms sorted longest-first for deterministic longest-match scanning.
        self._terms: tuple[str, ...] = tuple(
            sorted(
                {t for e in self._entries for t in {e.term, *e.aliases}},
                key=lambda t: (-len(t), t),
            )
        )

    @staticmethod
    def _key(term: str) -> str:
        return ascii_fold(term)

    @property
    def entries(self) -> tuple[DictionaryEntry, ...]:
        return self._entries

    @property
    def terms(self) -> tuple[str, ...]:
        """All terms (term + aliases), longest-first, deterministic order."""
        return self._terms

    def lookup(self, term: str) -> tuple[DictionaryEntry, ...]:
        """All entries whose term/alias equals ``term``, ordered by entry_id."""
        return tuple(self._by_term.get(self._key(term), ()))


def builtin_lexicon() -> EntityLexicon:
    """Generic builtin: regions, institutions and policy terms only.

    Explicitly excludes company and security terms. Callers inject their own
    company/security lexicons; this function is provided for smoke tests and
    generic text (a stock mention without any injected lexicon must not be
    produced by the builtin).
    """
    entries = [
        DictionaryEntry(
            entry_id="builtin-region-beijing",
            term="北京",
            entity_type=EntityType.REGION,
            source=BUILTIN_LEXICON_SOURCE,
        ),
        DictionaryEntry(
            entry_id="builtin-region-shanghai",
            term="上海",
            entity_type=EntityType.REGION,
            source=BUILTIN_LEXICON_SOURCE,
        ),
        DictionaryEntry(
            entry_id="builtin-region-shenzhen",
            term="深圳",
            entity_type=EntityType.REGION,
            source=BUILTIN_LEXICON_SOURCE,
        ),
        DictionaryEntry(
            entry_id="builtin-institution-csrc",
            term="证监会",
            entity_type=EntityType.INSTITUTION,
            source=BUILTIN_LEXICON_SOURCE,
        ),
        DictionaryEntry(
            entry_id="builtin-institution-csrc-full",
            term="中国证券监督管理委员会",
            entity_type=EntityType.INSTITUTION,
            aliases=("证监会",),
            source=BUILTIN_LEXICON_SOURCE,
        ),
        DictionaryEntry(
            entry_id="builtin-institution-pboc",
            term="中国人民银行",
            entity_type=EntityType.INSTITUTION,
            aliases=("央行",),
            source=BUILTIN_LEXICON_SOURCE,
        ),
        DictionaryEntry(
            entry_id="builtin-institution-sse",
            term="上海证券交易所",
            entity_type=EntityType.INSTITUTION,
            aliases=("上交所",),
            source=BUILTIN_LEXICON_SOURCE,
        ),
        DictionaryEntry(
            entry_id="builtin-institution-szse",
            term="深圳证券交易所",
            entity_type=EntityType.INSTITUTION,
            aliases=("深交所",),
            source=BUILTIN_LEXICON_SOURCE,
        ),
        DictionaryEntry(
            entry_id="builtin-policy-registration",
            term="全面注册制",
            entity_type=EntityType.POLICY,
            source=BUILTIN_LEXICON_SOURCE,
        ),
        DictionaryEntry(
            entry_id="builtin-policy-new-guojiutiao",
            term="新国九条",
            entity_type=EntityType.POLICY,
            source=BUILTIN_LEXICON_SOURCE,
        ),
    ]
    return EntityLexicon(entries)


def lexicon_fingerprint(lexicon: EntityLexicon) -> str:
    """Deterministic SHA-256 over the whole lexicon.

    Binds every result-affecting field — entry_id, term, aliases, type,
    confidence, source and the availability window. Availability changes
    (including visibility-window changes) therefore change the fingerprint.
    All timestamps are normalized to an explicit UTC representation, so the
    fingerprint is independent of input order and timezone spelling.
    """
    import hashlib

    def _utc_iso(dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return dt.astimezone(UTC).isoformat()

    payload = [
        (
            e.entry_id,
            e.term,
            e.entity_type.value,
            tuple(sorted(set(e.aliases))),
            str(e.confidence_bps),
            e.source,
            _utc_iso(e.available_from),
            _utc_iso(e.available_to),
        )
        for e in lexicon.entries
    ]
    payload.sort(key=lambda item: (item[0], json.dumps(item, ensure_ascii=False)))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _entry_semantic_key(
    entry: DictionaryEntry,
) -> tuple[str, str, str, tuple[str, ...], str, str, str | None, str | None]:
    def _utc_iso(dt: datetime | None) -> str | None:
        return None if dt is None else dt.astimezone(UTC).isoformat()

    return (
        entry.entry_id,
        entry.term,
        entry.entity_type.value,
        tuple(sorted(set(entry.aliases))),
        str(entry.confidence_bps),
        entry.source,
        _utc_iso(entry.available_from),
        _utc_iso(entry.available_to),
    )


__all__ = [
    "BUILTIN_LEXICON_SOURCE",
    "DictionaryEntry",
    "EntityLexicon",
    "builtin_lexicon",
    "lexicon_fingerprint",
]
