"""Raw content contract and source policy.

``RawContent`` is the single, immutable, versioned representation of raw text
content ingested from news, announcements, research reports, interactive
platforms and social media. It separates the three time axes that matter for
audit and point-in-time correctness:

* ``publish_time`` — when the content was published;
* ``ingest_time`` — when Kunlun ingested it;
* ``available_time`` — the earliest instant the record may enter research or
  downstream computation (after ingest and boundary validation).

The invariant ``publish_time <= ingest_time <= available_time`` is enforced
fail-closed, and all three are timezone-aware and normalized to UTC.

Immutability and versioning rules:

* raw content is never overwritten in place; an update produces a new
  :class:`RawContent` with a new ``version_id`` whose ``previous_version_id``
  links the superseded version;
* the *content fingerprint* (derived from title + body) may stay equal across a
  metadata-only update, but the *version identity* always changes;
* deletion never physically erases history: :func:`mark_deleted` returns a
  tombstone version that keeps the source, license, evidence and fingerprint;
* an already-deleted record is never implicitly resurrected by an ordinary
  update.

Authorization is fail-closed: :attr:`LicenseMetadata.authorized` has no default
and must be provided explicitly; only ``authorized is True`` with a usable
availability makes content usable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

FINGERPRINT_ALGORITHM_VERSION = "sha256-v1"
VERSION_ALGORITHM = "raw_content_version_v1"

ContentType = Literal["NEWS", "ANNOUNCEMENT", "RESEARCH", "INTERACTION", "SOCIAL"]

_VALID_CONTENT_TYPES = frozenset({"NEWS", "ANNOUNCEMENT", "RESEARCH", "INTERACTION", "SOCIAL"})

_VERSION_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _require_non_empty(value: object, name: str) -> str:
    """Fail closed on a missing or blank provenance string."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")
    return value


def _require_bool(value: object, name: str) -> bool:
    """Fail closed unless ``value`` is a genuine ``bool``.

    ``1``, ``0``, strings and ``None`` are rejected — a boolean authorization
    flag must never be silently coerced.
    """
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a bool")
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


def _require_version_id(value: object, name: str) -> str:
    """Fail closed unless ``value`` is a 64-hex lowercase version identifier."""
    if not isinstance(value, str) or not _VERSION_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a 64-hex lowercase string")
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

    ``authorized`` has no default: it must be supplied explicitly. An
    unauthorized record can still be saved for audit, but content use decisions
    fail closed — only an explicit ``authorized is True`` grants use.
    """

    license_id: str
    usage_restriction: str
    authorized: bool

    def __post_init__(self) -> None:
        _require_non_empty(self.license_id, "license_id")
        _require_non_empty(self.usage_restriction, "usage_restriction")
        object.__setattr__(self, "authorized", _require_bool(self.authorized, "authorized"))


def content_fingerprint(title: str, body: str) -> str:
    """Deterministic 64-hex lowercase SHA-256 fingerprint over title + body."""
    payload = title.encode("utf-8") + b"\x00" + body.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _source_material(source: ContentSource) -> dict[str, str]:
    return {
        "source_id": source.source_id,
        "source_version": source.source_version,
        "evidence_id": source.evidence_id,
    }


def _derive_version_id(material: dict[str, object]) -> str:
    """Derive the version identity from the full canonical immutable material.

    The material is serialized as canonical JSON (UTF-8, sorted keys, fixed
    separators, ``None`` preserved, times as canonical UTC ISO 8601, enums as
    their stable string values) and hashed with SHA-256. Any change to any
    immutable wire field — source, license, authorization, url, content type,
    times, original source, previous version id, deleted state or deletion time
    — changes the version identity. ``version_id`` itself is not part of the
    material, so there is no recursion.
    """
    canonical = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RawContent:
    """An immutable, versioned raw content record.

    ``record_id`` is the stable lineage identifier shared by every version of
    the same content; ``version_id`` (derived) uniquely identifies the current
    immutable version; ``previous_version_id`` links the direct predecessor.
    ``fingerprint`` (derived) is the content fingerprint and is never trusted
    from the caller — it is recomputed from title + body.

    ``publish_time <= ingest_time <= available_time`` is enforced. ``deleted``
    records require a ``deleted_at`` not earlier than ``available_time``.
    """

    content_type: ContentType
    source: ContentSource
    url: str
    title: str
    body: str
    publish_time: datetime
    ingest_time: datetime
    available_time: datetime
    license: LicenseMetadata
    record_id: str
    original_source: ContentSource | None = None
    previous_version_id: str | None = None
    deleted: bool = False
    deleted_at: datetime | None = None
    fingerprint: str = field(init=False, default="")
    fingerprint_algorithm_version: str = field(init=False, default=FINGERPRINT_ALGORITHM_VERSION)
    version_id: str = field(init=False, default="")

    def __post_init__(self) -> None:
        object.__setattr__(self, "content_type", _require_content_type(self.content_type))
        publish = _require_aware_datetime(self.publish_time, "publish_time").astimezone(UTC)
        ingest = _require_aware_datetime(self.ingest_time, "ingest_time").astimezone(UTC)
        available = _require_aware_datetime(self.available_time, "available_time").astimezone(UTC)
        object.__setattr__(self, "publish_time", publish)
        object.__setattr__(self, "ingest_time", ingest)
        object.__setattr__(self, "available_time", available)
        if publish > ingest:
            raise ValueError("publish_time must be <= ingest_time")
        if ingest > available:
            raise ValueError("ingest_time must be <= available_time")
        _require_non_empty(self.url, "url")
        _require_non_empty(self.record_id, "record_id")
        object.__setattr__(self, "deleted", _require_bool(self.deleted, "deleted"))
        if self.deleted:
            if self.deleted_at is None:
                raise ValueError("deleted content must have deleted_at")
            deleted_at = _require_aware_datetime(self.deleted_at, "deleted_at").astimezone(UTC)
            object.__setattr__(self, "deleted_at", deleted_at)
            if deleted_at < available:
                raise ValueError("deleted_at must be >= available_time")
        elif self.deleted_at is not None:
            raise ValueError("non-deleted content must not have deleted_at")
        if self.previous_version_id is not None:
            object.__setattr__(
                self,
                "previous_version_id",
                _require_version_id(self.previous_version_id, "previous_version_id"),
            )

        fingerprint = content_fingerprint(self.title, self.body)
        object.__setattr__(self, "fingerprint", fingerprint)
        material: dict[str, object] = {
            "algorithm": VERSION_ALGORITHM,
            "record_id": self.record_id,
            "previous_version_id": self.previous_version_id,
            "content_type": self.content_type,
            "url": self.url,
            "title": self.title,
            "body": self.body,
            "publish_time": publish.isoformat(),
            "ingest_time": ingest.isoformat(),
            "available_time": available.isoformat(),
            "fingerprint": fingerprint,
            "fingerprint_algorithm_version": FINGERPRINT_ALGORITHM_VERSION,
            "source": _source_material(self.source),
            "license": {
                "license_id": self.license.license_id,
                "usage_restriction": self.license.usage_restriction,
                "authorized": self.license.authorized,
            },
            "original_source": (
                _source_material(self.original_source) if self.original_source is not None else None
            ),
            "deleted": self.deleted,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at is not None else None,
        }
        version_id = _derive_version_id(material)
        object.__setattr__(self, "version_id", version_id)
        if self.previous_version_id is not None and self.previous_version_id == version_id:
            raise ValueError("previous_version_id must not equal version_id (self-reference)")

    def available_at(self, decision_time: datetime) -> bool:
        """Whether this record may be used at ``decision_time`` (inclusive).

        ``decision_time`` must be a timezone-aware instant; the record is
        available only when ``available_time <= decision_time``.
        """
        decision = _require_aware_datetime(decision_time, "decision_time").astimezone(UTC)
        return self.available_time <= decision

    def is_usable(self, decision_time: datetime) -> bool:
        """Whether this content may be used at ``decision_time`` (fail-closed).

        A tombstone (``deleted is True``) is never usable, regardless of
        authorization or decision time — it only serves audit and replay.
        Otherwise usable only when already available *and* explicitly
        authorized.
        """
        if self.deleted:
            return False
        return self.available_at(decision_time) and self.license.authorized


def updated_content(
    old: RawContent,
    *,
    title: str,
    body: str,
    publish_time: datetime,
    ingest_time: datetime,
    available_time: datetime,
) -> RawContent:
    """Produce a new version of ``old`` without overwriting it.

    The new record keeps the ``record_id``, source, url, license and repost
    provenance and links back through ``previous_version_id``. The version chain
    is monotonic on every time axis: ``publish_time`` and ``available_time``
    must not go backwards and ``ingest_time`` must strictly advance. An
    already-deleted record is never implicitly resurrected.
    """
    if old.deleted:
        raise ValueError("cannot update a deleted record")
    publish = _require_aware_datetime(publish_time, "publish_time").astimezone(UTC)
    ingest = _require_aware_datetime(ingest_time, "ingest_time").astimezone(UTC)
    available = _require_aware_datetime(available_time, "available_time").astimezone(UTC)
    if publish < old.publish_time:
        raise ValueError("updated publish_time must be >= previous version")
    if ingest <= old.ingest_time:
        raise ValueError("updated ingest_time must be later than the previous version")
    if available < old.available_time:
        raise ValueError("updated available_time must be >= previous version")
    return RawContent(
        content_type=old.content_type,
        source=old.source,
        url=old.url,
        title=title,
        body=body,
        publish_time=publish,
        ingest_time=ingest,
        available_time=available,
        license=old.license,
        record_id=old.record_id,
        original_source=old.original_source,
        previous_version_id=old.version_id,
    )


def mark_deleted(old: RawContent, *, deleted_at: datetime) -> RawContent:
    """Mark ``old`` as deleted by creating a tombstone version.

    The tombstone keeps the source, license, fingerprint, url and repost
    provenance, points ``previous_version_id`` at the deleted version, and adds
    ``deleted=True`` with the deletion time. Nothing is physically erased.
    """
    if old.deleted:
        raise ValueError("record is already deleted")
    return RawContent(
        content_type=old.content_type,
        source=old.source,
        url=old.url,
        title=old.title,
        body=old.body,
        publish_time=old.publish_time,
        ingest_time=old.ingest_time,
        available_time=old.available_time,
        license=old.license,
        record_id=old.record_id,
        original_source=old.original_source,
        previous_version_id=old.version_id,
        deleted=True,
        deleted_at=deleted_at,
    )
