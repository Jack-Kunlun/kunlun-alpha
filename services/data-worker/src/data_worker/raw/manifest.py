"""Immutable metadata for one captured external response.

Raw bytes are addressed by their SHA-256 checksum, while each response gets a
separate capture manifest.  The latter distinction is important: two requests
may return identical bytes but still have different provenance and retry
semantics.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CHECKSUM_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_LINE_RE = re.compile(r"^(?P<method>[A-Za-z]+)\s+(?P<target>\S+)")
_PATH_HASH_RE = re.compile(r"^path_sha256=(?P<digest>[0-9a-f]{64})$")
_SAFE_QUERY_VALUE_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
_ASCII_DIGITS_RE = re.compile(r"^[0-9]+$")
_CURSOR_HASH_RE = re.compile(r"^sha256-[0-9a-f]{64}$")
_ALLOWED_QUERY_KEYS = frozenset({"exchange", "cursor", "page", "limit", "date", "code"})
_MAX_IDENTIFIER_LENGTH = 48
_MAX_QUERY_VALUE_LENGTH = 128
_MAX_QUERY_FIELDS = 32
_CURSOR_HASH_PREFIX = "sha256-"
FUND_ENDPOINT_KINDS = frozenset({"metadata", "nav", "inav", "benchmark", "fees"})
_MIME_TOKEN_RE = r"[A-Za-z0-9!#$&^_.+-]+"
_MIME_RE = re.compile(
    rf"^(?P<type>{_MIME_TOKEN_RE})/(?P<subtype>{_MIME_TOKEN_RE})(?:;\s*charset=(?P<charset>{_MIME_TOKEN_RE}))?$",
    re.ASCII,
)
_UNSAFE_MIME_MARKERS = ("bearer", "basic", "cookie", "credential", "token", "dsn")
# Providers that do not expose a revision still need a concrete route value.
# This is deliberately a normal identifier (not ``None``/wildcard) so replay
# cannot accidentally mix revisioned and non-revisioned captures.
SOURCE_REVISION_SENTINEL = "source-revision-absent"


def normalize_content_type(value: object) -> str:
    """Return a bounded MIME type without header-derived secret material."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("content_type must be a non-empty string")
    candidate = value.strip()
    if len(candidate) > 128 or not candidate.isascii():
        raise ValueError("content_type is invalid")
    lowered = candidate.lower()
    if any(marker in lowered for marker in _UNSAFE_MIME_MARKERS):
        raise ValueError("content_type contains unsafe material")
    match = _MIME_RE.fullmatch(candidate)
    if match is None:
        raise ValueError("content_type is invalid")
    media_type = f"{match.group('type').lower()}/{match.group('subtype').lower()}"
    charset = match.group("charset")
    return media_type if charset is None else f"{media_type}; charset={charset.lower()}"


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def validate_identifier(
    value: object, field_name: str, *, max_length: int = _MAX_IDENTIFIER_LENGTH
) -> str:
    """Validate a value before it is used as a filesystem path component.

    Deliberately restrict identifiers to portable ASCII names.  This rejects
    path separators, drive prefixes, dot segments, control characters and
    alternate Unicode path tricks before any filesystem access occurs.
    """

    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    if len(value) > max_length:
        raise ValueError(f"{field_name} exceeds the maximum portable length")
    if value.endswith((".", " ")):
        raise ValueError(f"unsafe {field_name}: trailing dot or space")
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"unsafe {field_name}: {value!r}")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"unsafe {field_name}: control character")
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"unsafe {field_name}: {value!r}")
    normalized = value.casefold().split(".", 1)[0]
    if normalized in {"con", "prn", "aux", "nul", "clock$"} or re.fullmatch(
        r"(?:com[1-9]|lpt[1-9])", normalized
    ):
        raise ValueError(f"unsafe {field_name}: reserved Windows device name")
    return value


def validate_date_identifier(value: object) -> str:
    """Validate the collection date used in the landing-zone partition."""

    normalized = validate_identifier(value, "date")
    if not _DATE_RE.fullmatch(normalized):
        raise ValueError(f"date must use YYYY-MM-DD format: {value!r}")
    return normalized


def validate_fund_endpoint_kind(value: object) -> str:
    """Validate the fixed fund endpoint route before capture or replay."""

    if not isinstance(value, str) or value not in FUND_ENDPOINT_KINDS:
        raise ValueError("endpoint_kind must be one of metadata, nav, inav, benchmark, fees")
    return value


def sanitize_request_identity(request: object) -> str:
    """Return an allowlisted, stable request identity.

    Only the first request line is parsed.  Headers and bodies are discarded
    completely; the target path is represented by a SHA-256 digest so account
    ids and path credentials never enter the manifest.  A small allowlist of
    non-sensitive query keys is retained in sorted order, while every unknown
    key/value is dropped.
    """

    if not isinstance(request, str) or not request.strip():
        raise ValueError("request must be a non-empty string")
    if "\x00" in request or any(ord(char) < 32 and char not in "\t\r\n" for char in request):
        raise ValueError("request contains an unsafe control character")

    first_line = request.splitlines()[0].strip()
    request_match = _REQUEST_LINE_RE.match(first_line)
    if request_match is None:
        method = "UNKNOWN"
        target = first_line
    else:
        method = request_match.group("method").upper()
        target = request_match.group("target")

    try:
        parsed_target = urlsplit(target)
    except ValueError:
        parsed_target = None

    if parsed_target is None:
        path_digest = hashlib.sha256(target.encode("utf-8")).hexdigest()
        query = ""
    else:
        path_marker = _PATH_HASH_RE.fullmatch(parsed_target.path)
        path_digest = (
            path_marker.group("digest")
            if path_marker is not None
            else hashlib.sha256(parsed_target.path.encode("utf-8")).hexdigest()
        )
        try:
            query_pairs = parse_qsl(
                parsed_target.query,
                keep_blank_values=True,
                max_num_fields=_MAX_QUERY_FIELDS,
            )
        except ValueError:
            query_pairs = []
        allowed_pairs: list[tuple[str, str]] = []
        for key, value in query_pairs:
            normalized_key = key.casefold()
            if normalized_key not in _ALLOWED_QUERY_KEYS:
                continue
            if normalized_key == "cursor":
                if _CURSOR_HASH_RE.fullmatch(value) is None and (
                    len(value) > _MAX_QUERY_VALUE_LENGTH
                    or _ASCII_DIGITS_RE.fullmatch(value) is None
                ):
                    value = _CURSOR_HASH_PREFIX + hashlib.sha256(value.encode("utf-8")).hexdigest()
            elif (
                len(value) > _MAX_QUERY_VALUE_LENGTH
                or _SAFE_QUERY_VALUE_RE.fullmatch(value) is None
            ):
                continue
            allowed_pairs.append((normalized_key, value))
        allowed_pairs.sort()
        query = urlencode(allowed_pairs)

    identity = f"{method} path_sha256={path_digest}"
    return f"{identity}?{query}" if query else identity


def _parse_timestamp(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    else:
        raise ValueError(f"{field_name} must be a datetime or ISO-8601 string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


@dataclass(frozen=True, slots=True)
class RawObjectManifest:
    """Audit metadata for one immutable response capture."""

    # Keep the original field order for callers of the P1-N05 API.  New
    # capture/provenance fields use defaults so old positional construction is
    # still readable while storage always supplies explicit values.
    object_id: str
    source: str
    date: str
    request: str
    checksum: str
    size: int
    content_type: str = "application/octet-stream"
    capture_id: str = ""
    ingest_time: datetime = field(default_factory=utc_now)
    available_time: datetime | None = None
    endpoint_kind: str | None = None
    run_id: str | None = None
    source_revision: str | None = None
    attempt_id: str | None = None
    page_ordinal: int | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.source, "source")
        validate_date_identifier(self.date)
        validate_identifier(self.object_id, "object_id", max_length=64)
        if not _CHECKSUM_RE.fullmatch(self.object_id):
            raise ValueError("object_id must be a lowercase SHA-256 hex digest")
        if not _CHECKSUM_RE.fullmatch(self.checksum):
            raise ValueError("checksum must be a lowercase SHA-256 hex digest")
        if self.object_id != self.checksum:
            raise ValueError("object_id and checksum must match")
        if type(self.size) is bool or type(self.size) is not int or self.size < 0:
            raise ValueError("size must be a non-negative integer")
        object.__setattr__(self, "content_type", normalize_content_type(self.content_type))

        capture_id = self.capture_id or f"legacy-object-{self.object_id[:32]}"
        validate_identifier(capture_id, "capture_id")
        object.__setattr__(self, "capture_id", capture_id)

        ingest_time = _parse_timestamp(self.ingest_time, "ingest_time")
        available_time = (
            ingest_time
            if self.available_time is None
            else _parse_timestamp(self.available_time, "available_time")
        )
        if available_time < ingest_time:
            raise ValueError("available_time cannot precede ingest_time")
        object.__setattr__(self, "ingest_time", ingest_time)
        object.__setattr__(self, "available_time", available_time)
        object.__setattr__(self, "request", sanitize_request_identity(self.request))
        for field_name, value in (
            ("endpoint_kind", self.endpoint_kind),
            ("run_id", self.run_id),
            ("source_revision", self.source_revision),
        ):
            if value is not None:
                if field_name == "endpoint_kind":
                    validate_fund_endpoint_kind(value)
                else:
                    validate_identifier(value, field_name, max_length=64)
        if (self.attempt_id is None) != (self.page_ordinal is None):
            raise ValueError("attempt_id and page_ordinal must be provided together")
        if self.attempt_id is not None:
            validate_identifier(self.attempt_id, "attempt_id", max_length=64)
        if self.page_ordinal is not None and (
            type(self.page_ordinal) is not int or self.page_ordinal < 0
        ):
            raise ValueError("page_ordinal must be a non-negative integer")

    @staticmethod
    def route_identity(
        raw: Mapping[str, object],
    ) -> tuple[str, str, str, str, int] | None:
        """Return the complete replay route, or ``None`` for legacy data."""

        values = tuple(raw.get(name) for name in ("endpoint_kind", "run_id", "source_revision"))
        if all(value is None for value in values):
            if raw.get("attempt_id") is not None or raw.get("page_ordinal") is not None:
                raise ValueError("manifest route identity is incomplete")
            return None
        if any(value is None for value in values):
            raise ValueError("manifest route identity is incomplete")
        endpoint_kind, run_id, source_revision = values
        validated_endpoint_kind = validate_fund_endpoint_kind(endpoint_kind)
        attempt_id = raw.get("attempt_id")
        page_ordinal = raw.get("page_ordinal")
        if attempt_id is None or page_ordinal is None:
            raise ValueError("manifest replay route is missing attempt lineage")
        if type(page_ordinal) is not int or page_ordinal < 0:
            raise ValueError("manifest page_ordinal must be a non-negative integer")
        return (
            validated_endpoint_kind,
            validate_identifier(run_id, "run_id", max_length=64),
            validate_identifier(source_revision, "source_revision", max_length=64),
            validate_identifier(attempt_id, "attempt_id", max_length=64),
            page_ordinal,
        )

    @property
    def request_identity(self) -> str:
        """Alias naming the sanitized request identity explicitly."""

        return self.request

    def to_dict(self) -> dict[str, object]:
        """Serialize the manifest using JSON-compatible primitive values."""

        assert self.available_time is not None
        payload: dict[str, object] = {
            "capture_id": self.capture_id,
            "object_id": self.object_id,
            "source": self.source,
            "date": self.date,
            "request": self.request,
            "request_identity": self.request,
            "checksum": self.checksum,
            "size": self.size,
            "content_type": self.content_type,
            "ingest_time": self.ingest_time.isoformat(),
            "available_time": self.available_time.isoformat(),
        }
        for field_name in ("endpoint_kind", "run_id", "source_revision"):
            value = getattr(self, field_name)
            if value is not None:
                payload[field_name] = value
        for field_name in ("attempt_id", "page_ordinal"):
            value = getattr(self, field_name)
            if value is not None:
                payload[field_name] = value
        return payload

    def canonical_bytes(self) -> bytes:
        """Return canonical bytes used to bind a manifest filename."""

        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    def content_digest(self) -> str:
        """Return the SHA-256 digest binding this manifest to its filename."""

        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> RawObjectManifest:
        """Parse and validate a manifest loaded from disk."""

        object_id = str(raw["object_id"])
        request_value = raw.get("request_identity", raw.get("request"))
        if request_value is None:
            raise ValueError("manifest is missing request identity")
        ingest_value = raw.get("ingest_time")
        if ingest_value is None:
            raise ValueError("manifest is missing ingest_time")
        available_value = raw.get("available_time", ingest_value)
        size = raw["size"]
        if isinstance(size, bool) or not isinstance(size, int):
            raise ValueError("manifest size must be an integer")
        raw_page_ordinal = raw.get("page_ordinal")
        if raw_page_ordinal is not None and (
            type(raw_page_ordinal) is not int or raw_page_ordinal < 0
        ):
            raise ValueError("manifest page_ordinal must be a non-negative integer")
        return cls(
            object_id=object_id,
            source=str(raw["source"]),
            date=str(raw["date"]),
            request=str(request_value),
            checksum=str(raw["checksum"]),
            size=size,
            content_type=str(raw.get("content_type", "application/octet-stream")),
            capture_id=str(raw.get("capture_id", "")),
            ingest_time=_parse_timestamp(ingest_value, "ingest_time"),
            available_time=_parse_timestamp(available_value, "available_time"),
            endpoint_kind=(None if raw.get("endpoint_kind") is None else str(raw["endpoint_kind"])),
            run_id=None if raw.get("run_id") is None else str(raw["run_id"]),
            source_revision=(
                None if raw.get("source_revision") is None else str(raw["source_revision"])
            ),
            attempt_id=None if raw.get("attempt_id") is None else str(raw["attempt_id"]),
            page_ordinal=raw_page_ordinal,
        )


ManifestData = dict[str, object]


def manifest_from_json_data(raw: object) -> RawObjectManifest:
    """Type-safe adapter for JSON decoders returning ``object``."""

    if not isinstance(raw, dict):
        raise ValueError("manifest JSON must be an object")
    return RawObjectManifest.from_dict(cast(Mapping[str, object], raw))
