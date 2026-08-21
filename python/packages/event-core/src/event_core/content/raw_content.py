"""Raw content contract and source policy.

``RawContent`` is the single, immutable, versioned representation of raw text
content ingested from news, announcements, research reports, interactive
platforms and social media. It separates the two time axes that matter for
audit and point-in-time correctness — ``publish_time`` (when the content was
published) and ``ingest_time`` (when Kunlun ingested it) — and carries a
deterministic, algorithm-versioned content fingerprint so the same raw content
can always be recognized without trusting an external identifier.

Immutability rules:

* raw content is never overwritten in place; an update produces a new
  :class:`RawContent` whose ``previous_fingerprint`` links the superseded
  version;
* deletion never physically erases history: :func:`mark_deleted` returns a new
  record that keeps the source, license, evidence and fingerprint and only
  adds the deletion status and time;
* a repost keeps both the current source and the original source, so the
  attribution chain is never lost.

The source policy is expressed by :class:`ContentSource` (source id / version /
evidence id) and :class:`LicenseMetadata` (license id / usage restriction /
authorization), both of which fail closed on empty provenance rather than
fabricating it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

FINGERPRINT_ALGORITHM_VERSION = "raw_content_sha256_v1"

ContentType = Literal["NEWS", "ANNOUNCEMENT", "RESEARCH", "INTERACTION", "SOCIAL"]

_VALID_CONTENT_TYPES = frozenset({"NEWS", "ANNOUNCEMENT", "RESEARCH", "INTERACTION", "SOCIAL"})


def _require_non_empty(value: object, name: str) -> str:
    """Fail closed on a missing or blank provenance string."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")
    return value


def _require_aware_datetime(value: object, name: str) -> datetime:
    """Fail closed unless ``value`` is a timezone-aware :class:`datetime`.

    Naive datetimes are rejected because an availability or ordering decision
    must never rely on an ambiguous local time. The check is runtime-enforced
    and does not depend on the static annotation.
    """
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"timezone required: naive datetime is rejected ({name})")
    return value


def _require_content_type(value: object) -> str:
    """Fail closed on an unknown content category."""
    if not isinstance(value, str) or value not in _VALID_CONTENT_TYPES:
        raise ValueError(f"invalid content_type: {value!r}")
    return value


@dataclass(frozen=True)
class ContentSource:
    """Attribution of a piece of content to its source.

    ``source_id`` identifies the provider or platform; ``source_version`` is the
    provider's data/API version; ``evidence_id`` is an immutable identifier of
    the raw evidence this content was derived from. All three are required so
    the source policy never produces unattributed content.
    """

    source_id: str
    source_version: str
    evidence_id: str

    def __post_init__(self) -> None:
        _require_non_empty(self.source_id, "source_id")
        _require_non_empty(self.source_version, "source_version")
        _require_non_empty(self.evidence_id, "evidence_id")


@dataclass(frozen=True)
class LicenseMetadata:
    """License, authorization and usage-restriction metadata.

    ``license_id`` names the license or right grant; ``usage_restriction``
    records any restriction on use; ``authorized`` states whether use is
    permitted. License and restriction are required non-empty strings — an
    empty license string must never stand in for "no restriction".
    """

    license_id: str
    usage_restriction: str
    authorized: bool = True

    def __post_init__(self) -> None:
        _require_non_empty(self.license_id, "license_id")
        _require_non_empty(self.usage_restriction, "usage_restriction")


def content_fingerprint(title: str, body: str) -> str:
    """Deterministic content fingerprint over the raw title and body.

    SHA-256 over ``title`` + NUL + ``body`` (UTF-8), hex-encoded. The same raw
    content always produces the same fingerprint, and the algorithm is versioned
    by :data:`FINGERPRINT_ALGORITHM_VERSION` so a future algorithm change never
    silently reinterprets an old fingerprint.
    """
    payload = title.encode("utf-8") + b"\x00" + body.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class RawContent:
    """An immutable, versioned raw content record.

    ``publish_time`` and ``ingest_time`` are distinct: the former is when the
    content was published, the latter when Kunlun ingested it. ``publish_time``
    must never be later than ``ingest_time``. ``fingerprint`` and
    ``fingerprint_algorithm_version`` are derived from the raw title and body
    and are not caller-supplied, so a fingerprint can never be forged.

    ``original_source`` is set only for reposts; ``previous_fingerprint`` links
    an update to the version it supersedes; ``deleted`` / ``deleted_at`` mark a
    deletion without erasing the underlying content.
    """

    content_type: ContentType
    source: ContentSource
    url: str
    title: str
    body: str
    publish_time: datetime
    ingest_time: datetime
    license: LicenseMetadata
    original_source: ContentSource | None = None
    previous_fingerprint: str | None = None
    deleted: bool = False
    deleted_at: datetime | None = None
    fingerprint: str = field(init=False, default="")
    fingerprint_algorithm_version: str = field(init=False, default=FINGERPRINT_ALGORITHM_VERSION)

    def __post_init__(self) -> None:
        object.__setattr__(self, "content_type", _require_content_type(self.content_type))
        publish = _require_aware_datetime(self.publish_time, "publish_time")
        ingest = _require_aware_datetime(self.ingest_time, "ingest_time")
        object.__setattr__(self, "publish_time", publish)
        object.__setattr__(self, "ingest_time", ingest)
        if publish > ingest:
            raise ValueError("publish_time must be <= ingest_time")
        _require_non_empty(self.url, "url")
        if self.deleted:
            if self.deleted_at is None:
                raise ValueError("deleted content must have deleted_at")
            object.__setattr__(
                self, "deleted_at", _require_aware_datetime(self.deleted_at, "deleted_at")
            )
        elif self.deleted_at is not None:
            raise ValueError("non-deleted content must not have deleted_at")
        object.__setattr__(self, "fingerprint", content_fingerprint(self.title, self.body))


def updated_content(
    old: RawContent,
    *,
    title: str,
    body: str,
    publish_time: datetime,
    ingest_time: datetime,
) -> RawContent:
    """Produce a new version of ``old`` without overwriting it.

    The new record keeps the source, url, license and repost provenance of the
    original and links back through ``previous_fingerprint``. ``old`` remains
    untouched (immutable), so history is never lost.
    """
    return RawContent(
        content_type=old.content_type,
        source=old.source,
        url=old.url,
        title=title,
        body=body,
        publish_time=publish_time,
        ingest_time=ingest_time,
        license=old.license,
        original_source=old.original_source,
        previous_fingerprint=old.fingerprint,
    )


def mark_deleted(old: RawContent, *, deleted_at: datetime) -> RawContent:
    """Mark ``old`` as deleted while preserving all evidence.

    Returns a new record that keeps the source, license, fingerprint and url and
    adds ``deleted=True`` with the deletion time. Nothing is physically erased,
    so the audit trail survives deletion.
    """
    return RawContent(
        content_type=old.content_type,
        source=old.source,
        url=old.url,
        title=old.title,
        body=old.body,
        publish_time=old.publish_time,
        ingest_time=old.ingest_time,
        license=old.license,
        original_source=old.original_source,
        previous_fingerprint=old.fingerprint,
        deleted=True,
        deleted_at=deleted_at,
    )
