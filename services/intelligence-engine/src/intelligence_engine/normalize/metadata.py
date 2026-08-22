"""Metadata normalization: times, authors and attachments.

All functions are pure and deterministic: no network, no I/O, no guessing of
identity or authority. Author normalization only cleans whitespace and
separators; attachment normalization only touches metadata — it never
downloads, parses or converts attachment content (that belongs to later
nodes).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import urlparse

_SUPPORTED_URI_SCHEMES = frozenset({"http", "https", "ftp", "ftps", "file"})


class AttachmentStatus(StrEnum):
    """Typed outcome of attachment metadata normalization."""

    OK = "ok"
    DUPLICATE = "duplicate"
    INVALID_URI = "invalid_uri"
    MISSING_METADATA = "missing_metadata"
    UNSUPPORTED_SCHEME = "unsupported_scheme"


@dataclass(frozen=True)
class AuthorInput:
    """An author as declared by the source (no identity resolution here)."""

    name: str


@dataclass(frozen=True)
class NormalizedAuthor:
    """One deduplicated author: the raw fragment plus its cleaned name."""

    original_name: str
    normalized_name: str


@dataclass(frozen=True)
class NormalizedAuthors:
    """Author normalization result preserving the original input texts."""

    original_authors: tuple[str, ...]
    normalized: tuple[NormalizedAuthor, ...]


@dataclass(frozen=True)
class AttachmentInput:
    """An attachment as declared by the source."""

    uri: str
    filename: str | None = None
    mime_type: str | None = None
    position: int | None = None


@dataclass(frozen=True)
class NormalizedAttachment:
    """Deterministic attachment metadata with the originals preserved."""

    original_uri: str
    original_filename: str | None
    declared_mime_type: str | None
    original_position: int | None
    normalized_uri: str
    normalized_filename: str | None
    normalized_mime_type: str | None
    attachment_id: str
    status: AttachmentStatus


@dataclass(frozen=True)
class NormalizedTimes:
    """The three audit time axes, timezone-aware and normalized to UTC."""

    publish_time: datetime
    ingest_time: datetime
    available_time: datetime


def _require_aware_utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"timezone required: naive datetime is rejected ({name})")
    return value.astimezone(UTC)


def normalize_times(
    publish_time: datetime, ingest_time: datetime, available_time: datetime
) -> NormalizedTimes:
    """Normalize the three time axes to UTC without changing any instant.

    Naive datetimes are rejected fail-closed; the ordering
    ``publish_time <= ingest_time <= available_time`` is enforced. The current
    time is never used to fill a missing business time.
    """
    publish = _require_aware_utc(publish_time, "publish_time")
    ingest = _require_aware_utc(ingest_time, "ingest_time")
    available = _require_aware_utc(available_time, "available_time")
    if publish > ingest:
        raise ValueError("publish_time must be <= ingest_time")
    if ingest > available:
        raise ValueError("ingest_time must be <= available_time")
    return NormalizedTimes(publish_time=publish, ingest_time=ingest, available_time=available)


def normalize_authors(
    authors: Sequence[str | AuthorInput | None], separators: Sequence[str]
) -> NormalizedAuthors:
    """Clean author names deterministically, preserving the original texts.

    Each input is split on the configured separators; fragments are
    whitespace-collapsed, empty fragments are dropped and duplicates (by
    normalized name) keep only their first occurrence. Order is stable and no
    identity/organization guessing happens here.
    """
    for separator in separators:
        if type(separator) is not str or not separator:
            raise ValueError("separators must be non-empty strings")
    pattern = re.compile("|".join(re.escape(separator) for separator in separators))
    original_authors: list[str] = []
    candidates: list[tuple[str, str]] = []
    for entry in authors:
        if entry is None:
            continue
        name = entry.name if isinstance(entry, AuthorInput) else entry
        if type(name) is not str:
            raise TypeError("author entries must be str or AuthorInput")
        original_authors.append(name)
        for fragment in pattern.split(name):
            normalized_name = " ".join(fragment.split())
            if normalized_name:
                candidates.append((fragment, normalized_name))
    seen: set[str] = set()
    normalized: list[NormalizedAuthor] = []
    for fragment, normalized_name in candidates:
        if normalized_name in seen:
            continue
        seen.add(normalized_name)
        normalized.append(NormalizedAuthor(original_name=fragment, normalized_name=normalized_name))
    return NormalizedAuthors(original_authors=tuple(original_authors), normalized=tuple(normalized))


def _clean_optional(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str or None")
    return value.strip()


def normalize_attachments(
    attachments: Sequence[AttachmentInput],
) -> tuple[NormalizedAttachment, ...]:
    """Normalize attachment metadata deterministically.

    The original URI, filename, declared MIME type and position are preserved
    verbatim; normalized copies are stripped (and lowercased for MIME). Every
    attachment receives a typed status: ``INVALID_URI`` (blank URI) takes
    precedence, then ``DUPLICATE`` (same normalized URI as an earlier
    attachment), then ``UNSUPPORTED_SCHEME`` (scheme outside the supported
    set), then ``MISSING_METADATA`` (no filename or MIME declared).
    """
    results: list[NormalizedAttachment] = []
    seen: set[str] = set()
    for attachment in attachments:
        if type(attachment) is not AttachmentInput:
            raise TypeError("attachments must be AttachmentInput instances")
        if type(attachment.uri) is not str:
            raise TypeError("attachment uri must be a str")
        original_filename = attachment.filename
        original_mime = attachment.mime_type
        if original_filename is not None and type(original_filename) is not str:
            raise TypeError("attachment filename must be a str or None")
        if original_mime is not None and type(original_mime) is not str:
            raise TypeError("attachment mime_type must be a str or None")
        normalized_uri = attachment.uri.strip()
        normalized_filename = _clean_optional(attachment.filename, "attachment filename")
        normalized_mime_value = _clean_optional(attachment.mime_type, "attachment mime_type")
        normalized_mime = (
            normalized_mime_value.lower() if normalized_mime_value is not None else None
        )
        if not normalized_uri:
            status = AttachmentStatus.INVALID_URI
        elif normalized_uri in seen:
            status = AttachmentStatus.DUPLICATE
        else:
            scheme = urlparse(normalized_uri).scheme.lower()
            if scheme and scheme not in _SUPPORTED_URI_SCHEMES:
                status = AttachmentStatus.UNSUPPORTED_SCHEME
            elif normalized_filename is None or normalized_mime is None:
                status = AttachmentStatus.MISSING_METADATA
            else:
                status = AttachmentStatus.OK
        if normalized_uri:
            seen.add(normalized_uri)
        attachment_id = (
            hashlib.sha256(normalized_uri.encode("utf-8")).hexdigest() if normalized_uri else ""
        )
        results.append(
            NormalizedAttachment(
                original_uri=attachment.uri,
                original_filename=original_filename,
                declared_mime_type=original_mime,
                original_position=attachment.position,
                normalized_uri=normalized_uri,
                normalized_filename=normalized_filename,
                normalized_mime_type=normalized_mime,
                attachment_id=attachment_id,
                status=status,
            )
        )
    return tuple(results)


def has_usable_attachment(attachments: Sequence[NormalizedAttachment]) -> bool:
    """Whether at least one attachment is usable (``AttachmentStatus.OK``).

    Only an OK attachment (valid supported URI, not a duplicate, with the
    required metadata) counts as usable content. INVALID_URI, DUPLICATE,
    UNSUPPORTED_SCHEME and MISSING_METADATA attachments never upgrade an empty
    body into consumable content.
    """
    return any(attachment.status == AttachmentStatus.OK for attachment in attachments)
