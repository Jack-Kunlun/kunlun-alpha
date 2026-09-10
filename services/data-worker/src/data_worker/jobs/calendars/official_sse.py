"""Narrow raw-first ingestion of the SSE 2026 SH holiday announcement.

This module deliberately handles one published artifact only.  It is not a
general calendar provider and it does not claim that the sparse holiday rows
form a complete trading calendar.  The response capture is persisted before
parsing or PostgreSQL work so that a failed parse or later persistence step
can be recovered from the original bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from http.client import HTTPMessage
from typing import IO, Literal, NoReturn, Protocol, cast
from urllib.error import HTTPError
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)
from uuid import uuid4

from ashare_contracts.calendar_holiday import Exchange as HolidayExchange
from ashare_contracts.calendar_holiday import Holiday
from ashare_contracts.calendar_holiday import Reason as HolidayReason
from data_worker.jobs.calendars.repository import CalendarRepository
from data_worker.raw import RawObjectManifest, RawStorage
from data_worker.raw.manifest import (
    normalize_content_type,
    validate_date_identifier,
    validate_identifier,
)

SSE_CALENDAR_SOURCE = "sse-calendar-announcement"
SSE_RECEIPT_SOURCE = "sse-calendar-receipt"
SSE_CAPTURE_STATE_SOURCE = "sse-calendar-capture-state"
SSE_2026_ANNOUNCEMENT_URL = (
    "https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml"
)
SSE_PARSER_VERSION = "sse-calendar-2026-v1"
SSE_TIMEOUT_SECONDS = 10.0
SSE_MAX_RESPONSE_BYTES = 512 * 1024
SSE_COVERAGE_STATUS: Literal["UNKNOWN"] = "UNKNOWN"

_SCOPE_ERROR = "official SSE calendar scope is unsupported"
_ANNOUNCEMENT_ERROR = "official SSE calendar announcement is invalid"
_RESPONSE_ERROR = "official SSE calendar response is unusable"
_REQUEST_ERROR = "official SSE calendar request failed"
_RAW_ERROR = "official SSE calendar raw capture failed"
_PERSISTENCE_ERROR = "official SSE calendar persistence failed"
_RECEIPT_ERROR = "official SSE calendar receipt failed"
_CAPTURE_ERROR = "official SSE calendar capture is unavailable"
_CAPTURE_INTEGRITY_ERROR = "official SSE calendar capture integrity failed"
_TIME_ERROR = "official SSE calendar observation time is invalid"

_TITLE = "关于上海证券交易所2026年部分节假日休市安排的通知"
_ANNOUNCEMENT_NUMBER = "上证公告〔2025〕45号"
_ANNOUNCEMENT_DATE = "2025-12-22"
_ISSUER = "上海证券交易所"
_RECEIPT_REQUEST = "PUT https://www.sse.com.cn/disclosure/announcement/general/c/receipt"
_CAPTURE_STATE_REQUEST = (
    "PUT https://www.sse.com.cn/disclosure/announcement/general/c/capture-state"
)

_EXPECTED_RANGES: tuple[tuple[str, tuple[tuple[int, int], tuple[int, int]]], ...] = (
    ("元旦", ((1, 1), (1, 3))),
    ("春节", ((2, 15), (2, 23))),
    ("清明", ((4, 4), (4, 6))),
    ("劳动节", ((5, 1), (5, 5))),
    ("端午", ((6, 19), (6, 21))),
    ("中秋", ((9, 25), (9, 27))),
    ("国庆", ((10, 1), (10, 7))),
)
_EXPECTED_SECTION_NUMBERS = ("一", "二", "三", "四", "五", "六", "七")
_OFFICIAL_SECTION_LABELS = ("元旦", "春节", "清明节", "劳动节", "端午节", "中秋节", "国庆节")
_EXPECTED_TOP_LEVEL_NUMBERS = ("一", "二", "三")
_EXPECTED_TOP_LEVEL_PREFIXES = ("休市安排", "有关清算事宜", "有关春节、国庆节测试事宜")
_DATE_TOKEN_RE = re.compile(
    r"(?:(?P<year>20\d{2})\s*年\s*)?"
    r"(?P<month>0?[1-9]|1[0-2])\s*月\s*"
    r"(?P<day>0?[1-9]|[12]\d|3[01])\s*日"
)
_CHILD_SECTION_RE = re.compile(
    r"（(?P<number>[一二三四五六七八九十]+)）\s*"
    r"(?P<label>[^：:\n]{1,32}?)\s*[：:]"
)
_TOP_LEVEL_SECTION_RE = re.compile(
    r"(?P<number>[一二三四五六七八九十]+)\s*、\s*(?P<body>.*?)(?=(?:[一二三四五六七八九十]+)\s*、|$)"
)
_VERSION_RE = re.compile(
    r"(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"|(?:sse-calendar-announcement:2026:v[1-9][0-9]*)"
)
_HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_RECEIPT_FIELDS = frozenset(
    {
        "capture_id",
        "raw_object_id",
        "raw_checksum",
        "raw_size",
        "raw_date",
        "exchange",
        "year",
        "parser_version",
        "observed_at",
        "available_at",
        "coverage_status",
        "calendar_version_id",
    }
)
_CAPTURE_STATE_FIELDS = frozenset(
    {
        "capture_id",
        "raw_object_id",
        "raw_checksum",
        "raw_size",
        "raw_date",
        "exchange",
        "year",
        "status_code",
        "redirected",
        "content_type",
        "replay_allowed",
    }
)
_ATTEMPT_ERROR_CODES = frozenset({"NETWORK_FAILURE", "MALFORMED_RESPONSE", "RESPONSE_TOO_LARGE"})


class OfficialSseCalendarError(ValueError):
    """A fixed, non-sensitive failure from the narrow SSE collector."""


@dataclass(frozen=True, slots=True)
class OfficialSseResponse:
    """Bounded response data returned by an injected or stdlib transport."""

    status_code: int
    content_type: str
    body: bytes
    redirected: bool = False


class OfficialSseTransport(Protocol):
    """Transport boundary for the fixed SSE URL."""

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> OfficialSseResponse: ...


class _HttpResponse(Protocol):
    status: int
    headers: HTTPMessage

    def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True, slots=True)
class SseOfficialCalendarResult:
    """Safe result metadata; no source HTML or free-form provider text."""

    exchange: Literal["SH"]
    year: Literal[2026]
    capture_id: str
    raw_object_id: str
    raw_checksum: str
    raw_date: str
    parser_version: str
    observed_at: datetime
    available_at: datetime
    operation_id: str
    version_id: str
    receipt_id: str
    holiday_count: int
    coverage_status: Literal["UNKNOWN"] = SSE_COVERAGE_STATUS


class _VisibleTextParser(HTMLParser):
    """Collect visible text while retaining block boundaries."""

    _BLOCK_TAGS = frozenset({"body", "br", "div", "h1", "head", "li", "p", "title", "tr"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self._ignored_depth += 1
        if tag in self._BLOCK_TAGS and self._ignored_depth == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK_TAGS and self._ignored_depth == 0:
            self.parts.append("\n")
        if tag in {"script", "style"} and self._ignored_depth > 0:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


def _safe_call[T](action: Callable[[], T]) -> tuple[T | None, bool]:
    """Run untrusted-boundary code and return a flag instead of its exception."""

    try:
        return action(), False
    except Exception:
        return None, True


def _scope_is_supported(exchange: object, year: object) -> bool:
    return type(exchange) is str and exchange == "SH" and type(year) is int and year == 2026


def _raise(message: str) -> NoReturn:
    """Raise only from a non-except scope so exception context stays empty."""

    raise OfficialSseCalendarError(message)


def _capture_id(value: str | None) -> str:
    if value is None:
        return f"capture-{uuid4().hex}"
    candidate, failed = _safe_call(lambda: validate_identifier(value, "capture_id", max_length=48))
    if failed or not isinstance(candidate, str):
        _raise(_SCOPE_ERROR)
    return candidate


def _receipt_id(capture_id: str) -> str:
    digest = hashlib.sha256(capture_id.encode("utf-8")).hexdigest()[:32]
    return f"receipt-{digest}"


def _observation_time(clock: Callable[[], datetime]) -> datetime:
    value, failed = _safe_call(clock)
    if failed or type(value) is not datetime:
        _raise(_TIME_ERROR)
    normalized: datetime | None = None
    conversion_failed = False
    try:
        if value.tzinfo is None or value.utcoffset() is None:
            conversion_failed = True
        else:
            normalized = value.astimezone(UTC)
    except Exception:
        conversion_failed = True
    if conversion_failed or type(normalized) is not datetime:
        _raise(_TIME_ERROR)
    return normalized


def _canonical_response_content_type(value: object) -> str | None:
    normalized, failed = _safe_call(lambda: normalize_content_type(value))
    if failed or not isinstance(normalized, str):
        return None
    return normalized


def _is_html_content_type(value: object) -> bool:
    normalized = _canonical_response_content_type(value)
    return normalized is not None and normalized.split(";", 1)[0] in _HTML_CONTENT_TYPES


def _safe_version_id(value: object) -> str | None:
    if type(value) is not str or not _VERSION_RE.fullmatch(value):
        return None
    return value


def _attempt_bytes(capture_id: str, exchange: str, year: int, error_code: str) -> bytes:
    if error_code not in _ATTEMPT_ERROR_CODES:
        error_code = "MALFORMED_RESPONSE"
    payload = {
        "capture_id": capture_id,
        "error_code": error_code,
        "exchange": exchange,
        "kind": "attempt",
        "source": SSE_CALENDAR_SOURCE,
        "year": year,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _put_raw(
    raw_storage: RawStorage,
    *,
    source: str,
    date: str,
    request: str,
    content: bytes,
    content_type: str,
    capture_id: str,
    observed_at: datetime,
) -> RawObjectManifest | None:
    manifest, failed = _safe_call(
        lambda: raw_storage.put(
            source=source,
            date=date,
            request=request,
            content=content,
            content_type=content_type,
            capture_id=capture_id,
            ingest_time=observed_at,
            available_time=observed_at,
        )
    )
    if failed or not isinstance(manifest, RawObjectManifest):
        return None
    valid_manifest, manifest_failed = _safe_call(
        lambda: (
            manifest.source == source
            and manifest.date == date
            and manifest.capture_id == capture_id
            and manifest.size == len(content)
            and manifest.checksum == hashlib.sha256(content).hexdigest()
        )
    )
    if manifest_failed or valid_manifest is not True:
        return None
    return manifest


def _put_attempt(
    raw_storage: RawStorage,
    *,
    date: str,
    capture_id: str,
    exchange: str,
    year: int,
    observed_at: datetime,
    error_code: str,
) -> bool:
    manifest = _put_raw(
        raw_storage,
        source=SSE_CALENDAR_SOURCE,
        date=date,
        request=f"GET {SSE_2026_ANNOUNCEMENT_URL}",
        content=_attempt_bytes(capture_id, exchange, year, error_code),
        content_type="application/json",
        capture_id=capture_id,
        observed_at=observed_at,
    )
    return manifest is not None


def _capture_state_payload(
    manifest: RawObjectManifest,
    *,
    status_code: int,
    redirected: bool,
) -> dict[str, object]:
    if type(status_code) is not int or not 100 <= status_code <= 599:
        raise ValueError
    if type(redirected) is not bool:
        raise ValueError
    content_type = manifest.content_type
    if (
        type(content_type) is not str
        or _canonical_response_content_type(content_type) != content_type
    ):
        raise ValueError
    return {
        "capture_id": manifest.capture_id,
        "raw_object_id": manifest.object_id,
        "raw_checksum": manifest.checksum,
        "raw_size": manifest.size,
        "raw_date": manifest.date,
        "exchange": "SH",
        "year": 2026,
        "status_code": status_code,
        "redirected": redirected,
        "content_type": content_type,
        "replay_allowed": status_code == 200
        and not redirected
        and _is_html_content_type(content_type),
    }


def _put_capture_state(
    raw_storage: RawStorage,
    manifest: RawObjectManifest,
    *,
    status_code: int,
    redirected: bool,
) -> bool:
    content, build_failed = _safe_call(
        lambda: json.dumps(
            _capture_state_payload(
                manifest,
                status_code=status_code,
                redirected=redirected,
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if build_failed or not isinstance(content, bytes):
        return False
    inputs, input_failed = _safe_call(
        lambda: (manifest.date, manifest.capture_id, manifest.ingest_time)
    )
    if input_failed or not isinstance(inputs, tuple) or len(inputs) != 3:
        return False
    raw_date, capture_id, observed_at = inputs
    if (
        type(raw_date) is not str
        or type(capture_id) is not str
        or type(observed_at) is not datetime
    ):
        return False
    state_manifest = _put_raw(
        raw_storage,
        source=SSE_CAPTURE_STATE_SOURCE,
        date=raw_date,
        request=_CAPTURE_STATE_REQUEST,
        content=content,
        content_type="application/json",
        capture_id=capture_id,
        observed_at=observed_at,
    )
    return state_manifest is not None


def _capture_state_matches(
    payload: Mapping[str, object],
    manifest: RawObjectManifest,
) -> bool:
    if frozenset(payload) != _CAPTURE_STATE_FIELDS:
        return False
    if any(
        payload[field_name] != expected
        for field_name, expected in (
            ("capture_id", manifest.capture_id),
            ("raw_object_id", manifest.object_id),
            ("raw_checksum", manifest.checksum),
            ("raw_size", manifest.size),
            ("raw_date", manifest.date),
            ("exchange", "SH"),
            ("year", 2026),
        )
    ):
        return False
    status_code = payload["status_code"]
    redirected = payload["redirected"]
    content_type = payload["content_type"]
    replay_allowed = payload["replay_allowed"]
    if (
        type(status_code) is not int
        or not 100 <= status_code <= 599
        or type(redirected) is not bool
        or type(content_type) is not str
        or _canonical_response_content_type(content_type) != content_type
        or content_type != manifest.content_type
        or type(replay_allowed) is not bool
    ):
        return False
    return replay_allowed is (
        status_code == 200 and not redirected and _is_html_content_type(content_type)
    )


def _visible_text(body: bytes) -> str:
    parser = _VisibleTextParser()
    parser.feed(body.decode("utf-8"))
    parser.close()
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _section_region(text: str) -> tuple[str, list[tuple[int, int]]]:
    top_level_matches = list(_TOP_LEVEL_SECTION_RE.finditer(text))
    if len(top_level_matches) != len(_EXPECTED_TOP_LEVEL_NUMBERS):
        raise ValueError
    top_level_keys = tuple(match.group("number") for match in top_level_matches)
    if top_level_keys != _EXPECTED_TOP_LEVEL_NUMBERS or any(
        not _top_level_prefix_matches(match.group("body"), prefix)
        for match, prefix in zip(top_level_matches, _EXPECTED_TOP_LEVEL_PREFIXES, strict=True)
    ):
        raise ValueError
    region_start = top_level_matches[0].start()
    region_end = top_level_matches[1].start()
    region = text[region_start:region_end]
    official_matches = list(_CHILD_SECTION_RE.finditer(region))
    official_keys = tuple(
        (match.group("number"), match.group("label").strip()) for match in official_matches
    )
    expected_keys = tuple(zip(_EXPECTED_SECTION_NUMBERS, _OFFICIAL_SECTION_LABELS, strict=True))
    if official_keys != expected_keys:
        raise ValueError
    return region, [(match.start(), match.end()) for match in official_matches]


def _top_level_prefix_matches(body: str, prefix: str) -> bool:
    normalized = body.strip()
    if not normalized.startswith(prefix):
        return False
    remainder = normalized[len(prefix) :]
    return not remainder or remainder[0] in " \t\n，。；：（("


def _parse_announcement(body: bytes) -> list[Holiday]:
    if type(body) is not bytes or len(body) > SSE_MAX_RESPONSE_BYTES:
        raise ValueError
    text = _visible_text(body)
    if not all(
        anchor in text for anchor in (_TITLE, _ANNOUNCEMENT_NUMBER, _ANNOUNCEMENT_DATE, _ISSUER)
    ):
        raise ValueError
    region, section_spans = _section_region(text)

    holidays: list[Holiday] = []
    for index, (_label, expected) in enumerate(_EXPECTED_RANGES):
        start_position = section_spans[index][0]
        end_position = (
            len(region) if index == len(section_spans) - 1 else section_spans[index + 1][0]
        )
        section = region[start_position:end_position]
        close_position = section.find("休市")
        if close_position < 0:
            raise ValueError
        range_text = section[: close_position + len("休市")]
        tokens = list(_DATE_TOKEN_RE.finditer(range_text))
        if len(tokens) != 2:
            raise ValueError
        parsed_dates: list[date] = []
        for token in tokens:
            token_year = token.group("year")
            if token_year is not None and token_year != "2026":
                raise ValueError
            parsed_dates.append(date(2026, int(token.group("month")), int(token.group("day"))))
        expected_start = date(2026, expected[0][0], expected[0][1])
        expected_end = date(2026, expected[1][0], expected[1][1])
        if tuple(parsed_dates) != (expected_start, expected_end):
            raise ValueError
        current = expected_start
        while current <= expected_end:
            if current.weekday() < 5:
                holidays.append(
                    Holiday(
                        date=current,
                        exchange=HolidayExchange.sh,
                        reason=HolidayReason.public_holiday,
                        note=None,
                    )
                )
            current = date.fromordinal(current.toordinal() + 1)

    if len(holidays) != 19:
        raise ValueError
    return holidays


def parse_sse_2026_announcement(body: bytes) -> list[Holiday]:
    """Strictly parse the fixed 2026 SSE announcement into sparse holidays."""

    holidays, failed = _safe_call(lambda: _parse_announcement(body))
    if failed or not isinstance(holidays, list):
        _raise(_ANNOUNCEMENT_ERROR)
    return holidays


def _receipt_payload(manifest: RawObjectManifest, version_id: str) -> dict[str, object]:
    return {
        "capture_id": manifest.capture_id,
        "raw_object_id": manifest.object_id,
        "raw_checksum": manifest.checksum,
        "raw_size": manifest.size,
        "raw_date": manifest.date,
        "exchange": "SH",
        "year": 2026,
        "parser_version": SSE_PARSER_VERSION,
        "observed_at": manifest.ingest_time.isoformat(),
        "available_at": manifest.available_time.isoformat()
        if manifest.available_time is not None
        else manifest.ingest_time.isoformat(),
        "coverage_status": SSE_COVERAGE_STATUS,
        "calendar_version_id": version_id,
    }


def _receipt_bytes(manifest: RawObjectManifest, version_id: str) -> bytes:
    return json.dumps(
        _receipt_payload(manifest, version_id),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _put_receipt(
    raw_storage: RawStorage,
    manifest: RawObjectManifest,
    version_id: str,
) -> str | None:
    receipt_id = _receipt_id(manifest.capture_id)
    content, build_failed = _safe_call(lambda: _receipt_bytes(manifest, version_id))
    if build_failed or not isinstance(content, bytes):
        return None
    receipt_manifest = _put_raw(
        raw_storage,
        source=SSE_RECEIPT_SOURCE,
        date=manifest.date,
        request=_RECEIPT_REQUEST,
        content=content,
        content_type="application/json",
        capture_id=receipt_id,
        observed_at=manifest.available_time or manifest.ingest_time,
    )
    return None if receipt_manifest is None else receipt_manifest.capture_id


def _validate_replay_date(value: str) -> str:
    candidate, failed = _safe_call(lambda: validate_date_identifier(value))
    if failed or not isinstance(candidate, str):
        _raise(_CAPTURE_ERROR)
    parsed, parse_failed = _safe_call(lambda: date.fromisoformat(candidate))
    if parse_failed or not isinstance(parsed, date) or parsed.isoformat() != candidate:
        _raise(_CAPTURE_ERROR)
    return candidate


def _load_capture(
    raw_storage: RawStorage,
    *,
    capture_id: str,
    date: str,
) -> RawObjectManifest | None:
    manifests, failed = _safe_call(lambda: raw_storage.list(SSE_CALENDAR_SOURCE, date))
    if failed or not isinstance(manifests, list):
        return None
    candidates = cast(list[object], manifests)
    matches = [
        manifest
        for manifest in candidates
        if isinstance(manifest, RawObjectManifest) and _manifest_has_capture(manifest, capture_id)
    ]
    return matches[0] if len(matches) == 1 else None


def _manifest_has_capture(manifest: RawObjectManifest, capture_id: str) -> bool:
    value, failed = _safe_call(lambda: manifest.capture_id == capture_id)
    return not failed and value is True


def _load_capture_state(
    raw_storage: RawStorage,
    *,
    manifest: RawObjectManifest,
) -> Mapping[str, object] | None:
    raw_date, date_failed = _safe_call(lambda: manifest.date)
    if date_failed or not isinstance(raw_date, str):
        _raise(_CAPTURE_INTEGRITY_ERROR)
    manifests, failed = _safe_call(lambda: raw_storage.list(SSE_CAPTURE_STATE_SOURCE, raw_date))
    if failed or not isinstance(manifests, list):
        _raise(_CAPTURE_INTEGRITY_ERROR)
    candidates = cast(list[object], manifests)
    matches = [
        state_manifest
        for state_manifest in candidates
        if isinstance(state_manifest, RawObjectManifest)
        and _manifest_has_capture(state_manifest, manifest.capture_id)
    ]
    if not matches:
        return None
    if len(matches) != 1:
        _raise(_CAPTURE_INTEGRITY_ERROR)
    state_manifest = matches[0]
    content, get_failed = _safe_call(
        lambda: raw_storage.get(
            state_manifest.object_id,
            checksum=state_manifest.checksum,
            size=state_manifest.size,
        )
    )
    if get_failed or not isinstance(content, bytes):
        _raise(_CAPTURE_INTEGRITY_ERROR)
    decoded, decode_failed = _safe_call(lambda: json.loads(content.decode("utf-8")))
    if decode_failed or not isinstance(decoded, dict):
        _raise(_CAPTURE_INTEGRITY_ERROR)
    payload = cast(dict[str, object], decoded)
    valid, validation_failed = _safe_call(lambda: _capture_state_matches(payload, manifest))
    if validation_failed or valid is not True:
        _raise(_CAPTURE_INTEGRITY_ERROR)
    return payload


def _load_receipt_payload(
    raw_storage: RawStorage,
    *,
    capture_id: str,
    date: str,
) -> Mapping[str, object] | None:
    receipt_id = _receipt_id(capture_id)
    manifests, failed = _safe_call(lambda: raw_storage.list(SSE_RECEIPT_SOURCE, date))
    if failed or not isinstance(manifests, list):
        _raise(_CAPTURE_INTEGRITY_ERROR)
    candidates = cast(list[object], manifests)
    matches = [
        manifest
        for manifest in candidates
        if isinstance(manifest, RawObjectManifest) and _manifest_has_capture(manifest, receipt_id)
    ]
    if not matches:
        return None
    if len(matches) != 1:
        _raise(_CAPTURE_INTEGRITY_ERROR)
    content, get_failed = _safe_call(
        lambda: raw_storage.get(
            matches[0].object_id,
            checksum=matches[0].checksum,
            size=matches[0].size,
        )
    )
    if get_failed or not isinstance(content, bytes):
        _raise(_CAPTURE_INTEGRITY_ERROR)
    decoded, decode_failed = _safe_call(lambda: json.loads(content.decode("utf-8")))
    if decode_failed or not isinstance(decoded, dict):
        _raise(_CAPTURE_INTEGRITY_ERROR)
    payload = cast(dict[str, object], decoded)
    if frozenset(payload) != _RECEIPT_FIELDS:
        _raise(_CAPTURE_INTEGRITY_ERROR)
    return payload


def _validate_existing_receipt(
    payload: Mapping[str, object], manifest: RawObjectManifest
) -> str | None:
    expected, build_failed = _safe_call(lambda: _receipt_payload(manifest, ""))
    if build_failed or not isinstance(expected, dict):
        _raise(_CAPTURE_INTEGRITY_ERROR)
    for field_name in _RECEIPT_FIELDS - {"calendar_version_id"}:
        if payload.get(field_name) != expected[field_name]:
            _raise(_CAPTURE_INTEGRITY_ERROR)
    version_id = _safe_version_id(payload.get("calendar_version_id"))
    if version_id is None:
        _raise(_CAPTURE_INTEGRITY_ERROR)
    return version_id


def _find_receipt_operation_version(
    repository: CalendarRepository,
    manifest: RawObjectManifest,
    holidays: list[Holiday],
    operation_id: str,
    receipt_version_id: str,
) -> str:
    version_id_raw, lookup_failed = _safe_call(
        lambda: repository.find_operation_version(
            SSE_CALENDAR_SOURCE,
            2026,
            holidays,
            exchange="SH",
            operation_id=operation_id,
        )
    )
    version_id = _safe_version_id(version_id_raw)
    if lookup_failed or (version_id_raw is not None and version_id is None):
        _raise(_PERSISTENCE_ERROR)
    if version_id is None or version_id != receipt_version_id:
        _raise(_CAPTURE_INTEGRITY_ERROR)
    return version_id


class SseOfficialCalendarCollector:
    """Collect, persist and receipt one fixed SSE SH/2026 artifact."""

    def __init__(
        self,
        raw_storage: RawStorage,
        repository: CalendarRepository,
        *,
        transport: OfficialSseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        timeout_seconds: float = SSE_TIMEOUT_SECONDS,
        max_bytes: int = SSE_MAX_RESPONSE_BYTES,
    ) -> None:
        self._raw_storage = raw_storage
        self._repository = repository
        self._transport = UrllibSseTransport() if transport is None else transport
        self._clock = _utc_now if clock is None else clock
        if type(timeout_seconds) is not float or not 0.0 < timeout_seconds <= 60.0:
            _raise(_REQUEST_ERROR)
        if type(max_bytes) is not int or max_bytes < 1024 or max_bytes > 8 * 1024 * 1024:
            _raise(_REQUEST_ERROR)
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes

    def _capture_response(
        self,
        *,
        capture_id: str,
        exchange: str,
        year: int,
    ) -> RawObjectManifest:
        response, request_failed = _safe_call(
            lambda: self._transport.fetch(
                SSE_2026_ANNOUNCEMENT_URL,
                timeout_seconds=self._timeout_seconds,
                max_bytes=self._max_bytes,
            )
        )
        observed_at = _observation_time(self._clock)
        if request_failed or not isinstance(response, OfficialSseResponse):
            if not _put_attempt(
                self._raw_storage,
                date=observed_at.date().isoformat(),
                capture_id=capture_id,
                exchange=exchange,
                year=year,
                observed_at=observed_at,
                error_code="NETWORK_FAILURE",
            ):
                _raise(_RAW_ERROR)
            _raise(_REQUEST_ERROR)

        valid_shape = False
        status_code: int | None = None
        body: bytes | None = None
        content_type: object = None
        redirected = False
        shape_failed = False
        try:
            status_code = response.status_code
            body = response.body
            content_type = response.content_type
            redirected = response.redirected
            valid_shape = (
                type(status_code) is int
                and type(body) is bytes
                and type(content_type) is str
                and type(redirected) is bool
            )
        except Exception:
            shape_failed = True
        if shape_failed or not valid_shape or body is None or status_code is None:
            if not _put_attempt(
                self._raw_storage,
                date=observed_at.date().isoformat(),
                capture_id=capture_id,
                exchange=exchange,
                year=year,
                observed_at=observed_at,
                error_code="MALFORMED_RESPONSE",
            ):
                _raise(_RAW_ERROR)
            _raise(_RESPONSE_ERROR)

        if len(body) > self._max_bytes:
            if not _put_attempt(
                self._raw_storage,
                date=observed_at.date().isoformat(),
                capture_id=capture_id,
                exchange=exchange,
                year=year,
                observed_at=observed_at,
                error_code="RESPONSE_TOO_LARGE",
            ):
                _raise(_RAW_ERROR)
            _raise(_RESPONSE_ERROR)

        raw_content_type = (
            _canonical_response_content_type(content_type) or "application/octet-stream"
        )
        manifest = _put_raw(
            self._raw_storage,
            source=SSE_CALENDAR_SOURCE,
            date=observed_at.date().isoformat(),
            request=f"GET {SSE_2026_ANNOUNCEMENT_URL}",
            content=body,
            content_type=raw_content_type,
            capture_id=capture_id,
            observed_at=observed_at,
        )
        if manifest is None:
            _raise(_RAW_ERROR)
        if not _put_capture_state(
            self._raw_storage,
            manifest,
            status_code=status_code,
            redirected=redirected,
        ):
            _raise(_RAW_ERROR)
        if redirected or status_code != 200 or not _is_html_content_type(content_type):
            _raise(_RESPONSE_ERROR)
        return manifest

    def collect(
        self,
        exchange: str = "SH",
        year: int = 2026,
        *,
        capture_id: str | None = None,
    ) -> SseOfficialCalendarResult:
        """Fetch the fixed announcement and save a sparse SH holiday version."""

        if not _scope_is_supported(exchange, year):
            _raise(_SCOPE_ERROR)
        resolved_capture_id = _capture_id(capture_id)
        manifest = self._capture_response(
            capture_id=resolved_capture_id,
            exchange=exchange,
            year=year,
        )
        body, get_failed = _safe_call(
            lambda: self._raw_storage.get(
                manifest.object_id,
                checksum=manifest.checksum,
                size=manifest.size,
            )
        )
        if get_failed or not isinstance(body, bytes):
            _raise(_CAPTURE_INTEGRITY_ERROR)
        holidays = parse_sse_2026_announcement(body)
        operation_id = f"{manifest.capture_id}:{SSE_PARSER_VERSION}:{manifest.checksum}"
        existing_payload = _load_receipt_payload(
            self._raw_storage,
            capture_id=manifest.capture_id,
            date=manifest.date,
        )
        expected_receipt_version = (
            None
            if existing_payload is None
            else _validate_existing_receipt(existing_payload, manifest)
        )
        if expected_receipt_version is not None:
            version_id = _find_receipt_operation_version(
                self._repository,
                manifest,
                holidays,
                operation_id,
                expected_receipt_version,
            )
        else:
            version_id_raw, save_failed = _safe_call(
                lambda: self._repository.save_version(
                    SSE_CALENDAR_SOURCE,
                    2026,
                    holidays,
                    exchange="SH",
                    operation_id=operation_id,
                )
            )
            version_id = _safe_version_id(version_id_raw)
            if save_failed or version_id is None:
                _raise(_PERSISTENCE_ERROR)
        receipt_id = _put_receipt(self._raw_storage, manifest, version_id)
        if receipt_id is None:
            _raise(_RECEIPT_ERROR)
        assert manifest.available_time is not None
        return SseOfficialCalendarResult(
            exchange="SH",
            year=2026,
            capture_id=manifest.capture_id,
            raw_object_id=manifest.object_id,
            raw_checksum=manifest.checksum,
            raw_date=manifest.date,
            parser_version=SSE_PARSER_VERSION,
            observed_at=manifest.ingest_time,
            available_at=manifest.available_time,
            operation_id=operation_id,
            version_id=version_id,
            receipt_id=receipt_id,
            holiday_count=len(holidays),
        )


def replay_sse_calendar(
    raw_storage: RawStorage,
    repository: CalendarRepository,
    *,
    capture_id: str,
    date: str,
    exchange: str = "SH",
    year: int = 2026,
) -> SseOfficialCalendarResult:
    """Replay one stored capture without creating an HTTP request."""

    if not _scope_is_supported(exchange, year):
        _raise(_SCOPE_ERROR)
    resolved_capture_id = _capture_id(capture_id)
    resolved_date = _validate_replay_date(date)
    manifest = _load_capture(
        raw_storage,
        capture_id=resolved_capture_id,
        date=resolved_date,
    )
    if manifest is None:
        _raise(_CAPTURE_ERROR)
    capture_state = _load_capture_state(raw_storage, manifest=manifest)
    if capture_state is None or capture_state.get("replay_allowed") is not True:
        _raise(_CAPTURE_INTEGRITY_ERROR)
    content, get_failed = _safe_call(
        lambda: raw_storage.get(
            manifest.object_id,
            checksum=manifest.checksum,
            size=manifest.size,
        )
    )
    if get_failed or not isinstance(content, bytes) or len(content) > SSE_MAX_RESPONSE_BYTES:
        _raise(_CAPTURE_INTEGRITY_ERROR)
    if not _is_html_content_type(manifest.content_type):
        _raise(_CAPTURE_INTEGRITY_ERROR)
    holidays = parse_sse_2026_announcement(content)
    operation_id = f"{manifest.capture_id}:{SSE_PARSER_VERSION}:{manifest.checksum}"
    existing_payload = _load_receipt_payload(
        raw_storage,
        capture_id=manifest.capture_id,
        date=manifest.date,
    )
    expected_receipt_version = (
        None if existing_payload is None else _validate_existing_receipt(existing_payload, manifest)
    )
    if expected_receipt_version is not None:
        version_id = _find_receipt_operation_version(
            repository,
            manifest,
            holidays,
            operation_id,
            expected_receipt_version,
        )
    else:
        version_id_raw, save_failed = _safe_call(
            lambda: repository.save_version(
                SSE_CALENDAR_SOURCE,
                2026,
                holidays,
                exchange="SH",
                operation_id=operation_id,
            )
        )
        version_id = _safe_version_id(version_id_raw)
        if save_failed or version_id is None:
            _raise(_PERSISTENCE_ERROR)
    receipt_id = _put_receipt(raw_storage, manifest, version_id)
    if receipt_id is None:
        _raise(_RECEIPT_ERROR)
    assert manifest.available_time is not None
    return SseOfficialCalendarResult(
        exchange="SH",
        year=2026,
        capture_id=manifest.capture_id,
        raw_object_id=manifest.object_id,
        raw_checksum=manifest.checksum,
        raw_date=manifest.date,
        parser_version=SSE_PARSER_VERSION,
        observed_at=manifest.ingest_time,
        available_at=manifest.available_time,
        operation_id=operation_id,
        version_id=version_id,
        receipt_id=receipt_id,
        holiday_count=len(holidays),
    )


class _NoRedirectHandler(HTTPRedirectHandler):
    """Reject redirects so the fixed host/path cannot be changed."""

    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        del req, fp, code, msg, headers, newurl
        return None


def _header_content_type(headers: object) -> str:
    value: object = None
    try:
        if isinstance(headers, HTTPMessage):
            value = headers.get("Content-Type")
    except Exception:
        value = None
    normalized = _canonical_response_content_type(value)
    return normalized or "application/octet-stream"


def _read_http_response(response: object, max_bytes: int) -> OfficialSseResponse | None:
    status_code: object = None
    content_type = "application/octet-stream"
    body: object = None
    try:
        http_response = cast(_HttpResponse, response)
        status_code = http_response.status
        content_type = _header_content_type(http_response.headers)
        body = http_response.read(max_bytes + 1)
    except Exception:
        return None
    if type(status_code) is not int or type(body) is not bytes:
        return None
    return OfficialSseResponse(
        status_code=status_code,
        content_type=content_type,
        body=body,
        redirected=status_code in {301, 302, 303, 307, 308},
    )


class UrllibSseTransport:
    """Bounded HTTPS transport for the one allowlisted SSE page."""

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> OfficialSseResponse:
        if url != SSE_2026_ANNOUNCEMENT_URL:
            _raise(_REQUEST_ERROR)
        if type(timeout_seconds) is not float or not 0.0 < timeout_seconds <= 60.0:
            _raise(_REQUEST_ERROR)
        if type(max_bytes) is not int or max_bytes < 1024 or max_bytes > 8 * 1024 * 1024:
            _raise(_REQUEST_ERROR)

        request = Request(
            SSE_2026_ANNOUNCEMENT_URL,
            method="GET",
            headers={"Accept": "text/html"},
        )
        opener = build_opener(
            ProxyHandler({}),
            HTTPSHandler(context=ssl.create_default_context()),
            _NoRedirectHandler(),
        )
        result: OfficialSseResponse | None = None
        failed = False
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                result = _read_http_response(response, max_bytes)
                failed = result is None
        except HTTPError as response_error:
            result = _read_http_response(response_error, max_bytes)
            failed = result is None
        except Exception:
            failed = True
        if failed or result is None:
            _raise(_REQUEST_ERROR)
        return result


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "OfficialSseCalendarError",
    "OfficialSseResponse",
    "OfficialSseTransport",
    "SSE_2026_ANNOUNCEMENT_URL",
    "SSE_CALENDAR_SOURCE",
    "SSE_CAPTURE_STATE_SOURCE",
    "SSE_COVERAGE_STATUS",
    "SSE_MAX_RESPONSE_BYTES",
    "SSE_PARSER_VERSION",
    "SSE_RECEIPT_SOURCE",
    "SSE_TIMEOUT_SECONDS",
    "SseOfficialCalendarCollector",
    "SseOfficialCalendarResult",
    "UrllibSseTransport",
    "parse_sse_2026_announcement",
    "replay_sse_calendar",
]
