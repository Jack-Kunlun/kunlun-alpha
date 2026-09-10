"""Raw-first, offline-replayable SZSE direct-daily calendar collection.

This module is intentionally narrower than a general provider framework.  It
only accepts the fixed SZSE calendar page, its raw ``szsePath.js`` and
``concatversion.js`` identity assets, the derived versioned JavaScript asset,
and the fixed monthly JSON endpoint.  A response is captured in
:class:`RawStorage` before it is decoded or validated.  The resulting typed
scan proof is still a provider boundary: raw-byte authenticity is established
by the adapter's allowlist and replay checks, not by the market-core domain
types alone.
"""

from __future__ import annotations

import calendar
import hashlib
import hmac
import json
import re
import ssl
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from email.message import Message
from http.client import HTTPMessage
from types import MappingProxyType
from typing import IO, Final, NoReturn, Protocol, cast
from urllib.error import HTTPError
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from data_worker.raw import CaptureConflictError, RawObjectManifest, RawStorage
from data_worker.raw.manifest import (
    normalize_content_type,
    sanitize_request_identity,
    validate_date_identifier,
    validate_identifier,
)
from market_core.calendar.scan_run import (
    SZSE_DIRECT_DAILY_POLICY_ID,
    CalendarScanRunCatalogReceipt,
    CalendarScanRunDay,
    CalendarScanRunManifestReceipt,
    CalendarScanRunPage,
    CalendarScanRunPassReceipt,
    CalendarScanRunReceipt,
    calendar_scan_run_catalog_digest,
    calendar_scan_run_manifest_member_digest,
    calendar_scan_run_pass_id,
    calendar_scan_run_pass_member_digest,
    calendar_scan_run_payload_digest,
    calendar_scan_run_resource_id,
)

SZSE_CALENDAR_SOURCE: Final = "szse-calendar"
SZSE_CAPTURE_STATE_SOURCE: Final = "szse-calendar-state"
SZSE_CATALOG_SOURCE: Final = "szse-calendar-catalog"
SZSE_MANIFEST_SOURCE: Final = "szse-calendar-manifest"
SZSE_CALENDAR_ROOT_URL: Final = "https://www.szse.cn/aboutus/calendar/index.html"
SZSE_CALENDAR_PATH_URL_TEMPLATE: Final = "https://www.szse.cn/szsePath.js?random={random_ms}"
SZSE_CALENDAR_CONCATVERSION_URL_TEMPLATE: Final = (
    "https://res.szse.cn/common/js/concatversion.js?random={random_ms}"
)
# Retained as a non-routable compatibility label for callers that only display
# the asset name.  Collection and replay always require the versioned URL
# generated from the root observation timestamp.
SZSE_CALENDAR_CONCATVERSION_URL: Final = "https://res.szse.cn/common/js/concatversion.js"
SZSE_CALENDAR_JS_URL: Final = (
    "https://res.static.szse.cn/modules/tradeCalendar/js/tradeCanledar_new.min.js?version=1.2.221"
)
SZSE_CALENDAR_SCRIPT_PATH: Final = "/modules/tradeCalendar/js/tradeCanledar_new.js"
SZSE_CALENDAR_PATH_SCRIPT_PATH: Final = "/szsePath.js"
SZSE_CALENDAR_CONCATVERSION_PATH: Final = "/common/js/concatversion.js"
SZSE_CALENDAR_PATH_HOST: Final = "www.szse.cn"
SZSE_CALENDAR_CONCATVERSION_HOST: Final = "res.szse.cn"
SZSE_CALENDAR_STATIC_HOST: Final = "res.static.szse.cn"
SZSE_DIRECT_DAILY_URL_TEMPLATE: Final = "https://www.szse.cn/api/report/exchange/onepersistenthour/monthList?month={year:04d}-{month:02d}"
SZSE_PARSER_VERSION: Final = "szse-direct-daily-v4"
SZSE_CONTRACT_VERSION: Final = "calendar-scan-run-v4"
SZSE_MANIFEST_VERSION: Final = "szse-calendar-run-manifest-v4"
SZSE_CAPTURE_STATE_VERSION: Final = "szse-calendar-capture-state-v4"
SZSE_CATALOG_VERSION: Final = "szse-calendar-catalog-v4"
SZSE_IDENTITY_POLICY_VERSION: Final = "szse-calendar-source-identity-v4"
_IDENTITY_SOURCE_SHA256: Final = MappingProxyType(
    {
        "root": "c172b73cf8301d68b194464a6efca3a719f04274d9b22d6df680c69460eddad9",
        "path": "83fd11aea1932b7e705760071eb04d978495bca96a7c573014f4b5fb181d5882",
        "concat": "eebde357d093a18f59506deab8d0cc93c0899df45000f5bfd4eab3c54fced0f0",
        "js": "98bd59154008ff9f4039ad4b65efaa17c5d7630d317b7d6c30800caac8588e40",
    }
)
SZSE_RUN_LEDGER_SOURCE: Final = "szse-calendar-run-ledger"
SZSE_RUN_LEDGER_DATE: Final = "2000-01-01"
SZSE_RUN_LEDGER_VERSION: Final = "szse-calendar-run-ledger-v4"
SZSE_TIMEOUT_SECONDS: Final = 10.0
SZSE_MAX_RESPONSE_BYTES: Final = 512 * 1024
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_SUPPORTED_YEAR = 2026
_ROOT_HTML_MARKERS = ("深圳证券交易所", "changeVertion")
_JS_MARKERS = (
    "/api/report/exchange/onepersistenthour/monthList?month=",
    "onepersistenthour",
)
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_JS_TYPES = frozenset({"application/javascript", "text/javascript", "application/x-javascript"})
_JSON_TYPES = frozenset({"application/json", "text/json"})
_IDENTITY_KINDS = ("root", "path", "concat", "js")
_SCRIPT_TAG_RE = re.compile(
    r"<script\b(?P<attributes>[^>]*)>(?P<body>.*?)</script\s*>",
    re.IGNORECASE | re.DOTALL,
)
_SCRIPT_SRC_RE = re.compile(
    r"(?<![A-Za-z0-9_-])src\s*=\s*(?P<quote>['\"])(?P<value>[^'\"]+)(?P=quote)",
    re.IGNORECASE,
)
_ROOT_DYNAMIC_PATH_RE = re.compile(r"/szsePath\.js\?random=(?P<random>[0-9]+)$", re.ASCII)
_ROOT_DYNAMIC_CONCAT_RE = re.compile(
    r"/common/js/concatversion\.js\?random=(?P<random>[0-9]+)$", re.ASCII
)
_ROOT_VERSION_DATE_RE = re.compile(
    r"\bvar\s+_versionDate\s*=\s*new\s+Date\s*\(\s*\)\s*\.\s*"
    r"getTime\s*\(\s*\)\s*;",
    re.ASCII,
)
_ROOT_VERSION_DATE_ANY_ASSIGNMENT_RE = re.compile(r"\b_versionDate\s*=", re.ASCII)
_ROOT_PATH_HTTPS_BRANCH_RE = re.compile(
    r"\bif\s*\(\s*location\s*\.\s*protocol\s*==\s*(['\"])https:\1\s*\)\s*\{\s*"
    r"var\s+_path\s*=\s*(['\"])https://res\.szse\.cn\2\s*;\s*\}",
    re.ASCII | re.DOTALL,
)
_ROOT_PATH_HTTP_ASSIGNMENT_RE = re.compile(
    r"\bvar\s+_path\s*=\s*(['\"])http://res\.static\.szse\.cn\1\s*;", re.ASCII
)
_ROOT_PATH_HTTPS_ASSIGNMENT_RE = re.compile(
    r"\b_path\s*=\s*(['\"])https://res\.szse\.cn\1\s*;", re.ASCII
)
_ROOT_HOST_HTTPS_BRANCH_RE = re.compile(
    r"\bif\s*\(\s*location\s*\.\s*protocol\s*==\s*(['\"])https:\1\s*\)\s*\{\s*"
    r"_host\s*=\s*(['\"])https://www\.szse\.cn\2\s*;\s*\}",
    re.ASCII | re.DOTALL,
)
_ROOT_HOST_HTTP_ASSIGNMENT_RE = re.compile(
    r"\bvar\s+_host\s*=\s*(['\"])http://www\.szse\.cn\1\s*;", re.ASCII
)
_ROOT_HOST_HTTPS_ASSIGNMENT_RE = re.compile(
    r"\b_host\s*=\s*(['\"])https://www\.szse\.cn\1\s*;", re.ASCII
)
_ROOT_PATH_REPLACE_RE = re.compile(
    r"\b_path\s*=\s*_path\s*\.\s*replace\s*\(\s*"
    r"(['\"])\.static\.\1\s*,\s*(['\"])\.\2\s*\)\s*;",
    re.ASCII,
)
_VERSION_ASSIGNMENT_RE = re.compile(
    r"\bsjsVersion\s*=\s*(?P<quote>['\"])(?P<version>[^'\"]+)(?P=quote)\s*;",
    re.ASCII,
)
_VERSION_ANY_ASSIGNMENT_RE = re.compile(r"\bsjsVersion\s*=", re.ASCII)
_VERSION_QUERY_RE = re.compile(r"(['\"])\?version=\1\s*\+\s*sjsVersion\b", re.ASCII)
_FINAL_JS_PATH = SZSE_CALENDAR_SCRIPT_PATH.replace(".js", ".min.js")
_PATH_MAIN_ASSIGNMENT_RE = re.compile(
    r"\bdomainMainHttps\s*=\s*(['\"])https://www\.szse\.cn\1\s*;", re.ASCII
)
_PATH_MAIN_ANY_ASSIGNMENT_RE = re.compile(r"\bdomainMainHttps\s*=", re.ASCII)
_PATH_STATIC_ASSIGNMENT_RE = re.compile(
    r"\bdomainResStaticHttps\s*=\s*(['\"])https://res\.static\.szse\.cn\1\s*;",
    re.ASCII,
)
_PATH_STATIC_ANY_ASSIGNMENT_RE = re.compile(r"\bdomainResStaticHttps\s*=", re.ASCII)
_CONCAT_FUNCTION_RE = re.compile(
    r"\bfunction\s+changeVertion\s*\(\s*"
    r"(?P<url>[A-Za-z_$][A-Za-z0-9_$]*)\s*,\s*"
    r"(?P<type>[A-Za-z_$][A-Za-z0-9_$]*)\s*\)",
    re.ASCII,
)
_CONCAT_SWITCH_RE = re.compile(r"\bswitch\s*\(\s*(?P<type>[A-Za-z_$][A-Za-z0-9_$]*)\s*\)", re.ASCII)
_CONCAT_CASE_JS_RE = re.compile(r"\bcase\s*(['\"])js\1\s*:", re.ASCII)
_CONCAT_DEV_ASSIGNMENT_RE = re.compile(r"\bisDevModel\s*=\s*false\s*;", re.ASCII)
_CONCAT_DEV_ANY_ASSIGNMENT_RE = re.compile(r"\bisDevModel\s*=", re.ASCII)
_CONCAT_DOMAIN_MAPPING_KEY_RE = re.compile(r"(['\"])resStaticHttps\1\s*:", re.ASCII)
_CONCAT_DOMAIN_MAPPING_RE = re.compile(
    r"(['\"])resStaticHttps\1\s*:\s*\[\s*"
    r"domainResStaticHttps\s*,\s*backDomainResStaticHttps\s*\]",
    re.ASCII,
)
_CONCAT_DOMAIN_MAP_ASSIGNMENT_RE = re.compile(r"\bvar\s+szseDomainMap\s*=", re.ASCII)
_CONCAT_PATH_OBJECT_ASSIGNMENT_RE = re.compile(r"\bvar\s+pathObj\s*=", re.ASCII)
_CONCAT_HTTPS_FILE_PROPERTY_RE = re.compile(
    r"\bhttps_file_path\s*:\s*domainBackSwitch\s*\(\s*"
    r"(['\"])resStaticHttps\1\s*\)\s*[,;}]",
    re.ASCII,
)
_CONCAT_REPORT_PROPERTY_RE = re.compile(
    r"\breport_path\s*:\s*(['\"])\/api\/report\1\s*[,;}]", re.ASCII
)
_CONCAT_HTTPS_FILE_BRANCH_RE = re.compile(
    r"\bif\s*\(\s*isNotHttps\s*\(\s*\)\s*\)\s*\{\s*"
    r"filePath\s*=\s*pathObj\s*\.\s*https_file_path\s*;\s*\}\s*"
    r"else\s*\{\s*filePath\s*=\s*pathObj\s*\.\s*file_path\s*;\s*\}",
    re.ASCII | re.DOTALL,
)
_CONCAT_NONDEV_IF_RE = re.compile(r"\bif\s*\(\s*!\s*isDevModel\s*\)\s*\{", re.ASCII)
_CONCAT_GENERALIZED_RE = re.compile(
    r"\b(?P<url>[A-Za-z_$][A-Za-z0-9_$]*)\s*\.\s*replace\s*"
    r"\(\s*(?P<left_quote>['\"])\.\s*(?P=left_quote)\s*\+\s*"
    r"(?P<type>[A-Za-z_$][A-Za-z0-9_$]*)\s*,\s*"
    r"(?P<right_quote>['\"])\.min\.\s*(?P=right_quote)\s*\+\s*"
    r"(?P=type)\s*\)",
    re.ASCII,
)
_REPORT_ENDPOINT_RE = re.compile(
    r"\bpathObj\s*\.\s*report_path\s*\+\s*"
    r"(['\"])\/exchange\/onepersistenthour\/monthList\?month=\1",
    re.ASCII,
)
_FAILURE_CODES = frozenset(
    {
        "transport",
        "status",
        "redirect",
        "content_type",
        "size",
        "identity",
        "schema",
        "month_days",
        "nowdate",
        "raw",
        "integrity",
        "unstable",
    }
)
_ENDPOINT_KINDS = frozenset({"root", "path", "concat", "js", "catalog", "page", "manifest", "run"})
_CATALOG_ENTRY_KEYS = frozenset(
    {
        "run_id",
        "year",
        "month",
        "catalog_id",
        "resource_id",
        "raw_evidence_id",
        "raw_artifact_sha256",
        "identity_verified",
        "replay_verified",
        "url",
        "raw_ref",
    }
)
_PAGE_ENTRY_KEYS = frozenset(
    {
        "run_id",
        "pass_number",
        "pass_id",
        "month",
        "year",
        "page_id",
        "catalog_id",
        "resource_id",
        "raw_evidence_id",
        "raw_artifact_sha256",
        "canonical_payload_sha256",
        "artifact_id",
        "capture_id",
        "opened_at",
        "observed_at",
        "available_at",
        "source_nowdate",
        "identity_verified",
        "replay_verified",
        "days",
        "raw_ref",
        "state_ref",
    }
)
_DAY_ENTRY_KEYS = frozenset({"date", "is_trading_day"})
_PASS_ENTRY_KEYS = frozenset(
    {"run_id", "pass_number", "pass_id", "opened_at", "finished_at", "page_refs", "member_digest"}
)

_SCOPE_ERROR = "official SZSE calendar scope is unsupported"
_RESPONSE_ERROR = "official SZSE calendar response is unusable"
_IDENTITY_ERROR = "official SZSE calendar source identity is invalid"
_DATA_ERROR = "official SZSE calendar data is invalid"
_NOWDATE_ERROR = "official SZSE calendar nowdate is invalid"
_RAW_ERROR = "official SZSE calendar raw capture failed"
_INTEGRITY_ERROR = "official SZSE calendar capture integrity failed"
_UNSTABLE_ERROR = "official SZSE calendar scan is unstable"
_REPLAY_ERROR = "official SZSE calendar replay is invalid"
_TIME_ERROR = "official SZSE calendar observation time is invalid"
_LEDGER_CONFLICT_ERROR = "official SZSE calendar run is already claimed"
_LEDGER_ERROR = "official SZSE calendar run ledger is invalid"


class OfficialSzseCalendarError(ValueError):
    """A fixed, non-sensitive failure from the SZSE calendar collector."""


class SzseFailureCode(str):
    """Fixed error-code namespace persisted in capture-state records."""

    TRANSPORT = "transport"
    STATUS = "status"
    REDIRECT = "redirect"
    CONTENT_TYPE = "content_type"
    SIZE = "size"
    IDENTITY = "identity"
    SCHEMA = "schema"
    MONTH_DAYS = "month_days"
    NOWDATE = "nowdate"
    RAW = "raw"
    INTEGRITY = "integrity"
    UNSTABLE = "unstable"


def _raise(message: str) -> NoReturn:
    raise OfficialSzseCalendarError(message) from None


class _CollectionFailureError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fail(code: str) -> NoReturn:
    if code not in _FAILURE_CODES:
        code = SzseFailureCode.INTEGRITY
    raise _CollectionFailureError(code)


def _safe_call[T](action: Callable[[], T]) -> tuple[T | None, bool]:
    try:
        return action(), False
    except Exception:
        return None, True


def _strict_uuid(value: object) -> UUID:
    if type(value) is not UUID:
        _fail(SzseFailureCode.INTEGRITY)
    return value


def _strict_sha256(value: object) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(SzseFailureCode.INTEGRITY)
    return value


def _route_parts(route: object) -> tuple[str, str]:
    if type(route) is not str:
        _fail(SzseFailureCode.INTEGRITY)
    parts = route.split(" ", 1)
    if len(parts) != 2 or parts[0] not in {"GET", "PUT"} or not parts[1]:
        _fail(SzseFailureCode.INTEGRITY)
    target = parts[1]
    if any(ord(char) < 32 or ord(char) == 127 for char in target):
        _fail(SzseFailureCode.INTEGRITY)
    return parts[0], target


def _route_digest(route: str) -> str:
    method, target = _route_parts(route)
    return hashlib.sha256(f"{method} {target}".encode()).hexdigest()


def _route_request_identity(route: str) -> str:
    method, _ = _route_parts(route)
    return sanitize_request_identity(f"{method} path_sha256={_route_digest(route)}")


def _validate_reference_route(reference: SzseRawReference, route: str) -> None:
    if reference.route_digest != _route_digest(route):
        _fail(SzseFailureCode.INTEGRITY)
    if reference.request_identity != _route_request_identity(route):
        _fail(SzseFailureCode.INTEGRITY)


def _catalog_route(year: int, month: int) -> str:
    return f"PUT /szse-calendar/catalog/{year:04d}-{month:02d}"


def _state_route(attempt_id: str) -> str:
    return f"PUT /szse-calendar/capture-state/{attempt_id}"


def _attempt_route(attempt_id: str) -> str:
    return f"PUT /szse-calendar/attempt/{attempt_id}"


def _manifest_route() -> str:
    return "PUT /szse-calendar/run-manifest"


def _ledger_route(kind: str) -> str:
    if kind not in {"claim", "final"}:
        _fail(SzseFailureCode.INTEGRITY)
    return f"PUT /szse-calendar/ledger/{kind}"


def _strict_datetime(value: object) -> datetime:
    if type(value) is not datetime:
        _fail(SzseFailureCode.INTEGRITY)
    try:
        if value.tzinfo is None or value.utcoffset() is None:
            _fail(SzseFailureCode.INTEGRITY)
        return value.astimezone(UTC)
    except _CollectionFailureError:
        raise
    except Exception:
        _fail(SzseFailureCode.INTEGRITY)


def _validate_scope(exchange: object, year: object) -> None:
    if (
        type(exchange) is not str
        or exchange != "SZ"
        or type(year) is not int
        or year != _SUPPORTED_YEAR
    ):
        _raise(_SCOPE_ERROR)


def _identity_random_ms(observed_at: object) -> int:
    """Derive the only accepted cache-busting token from a root timestamp."""

    normalized = _strict_datetime(observed_at)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = normalized - epoch
    random_ms = delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000
    if random_ms < 0:
        _fail(SzseFailureCode.IDENTITY)
    return random_ms


def _identity_urls(random_ms: object) -> tuple[str, str]:
    """Return the dynamic path and concatversion URLs for one root capture."""

    if type(random_ms) is not int or random_ms < 0:
        _fail(SzseFailureCode.IDENTITY)
    return (
        SZSE_CALENDAR_PATH_URL_TEMPLATE.format(random_ms=random_ms),
        SZSE_CALENDAR_CONCATVERSION_URL_TEMPLATE.format(random_ms=random_ms),
    )


def _validated_dynamic_identity_url(url: object, *, kind: str) -> int:
    """Validate a dynamic identity URL and return its numeric random token."""

    if type(url) is not str:
        _fail(SzseFailureCode.IDENTITY)
    if kind == "path":
        pattern = re.compile(
            rf"^https://{re.escape(SZSE_CALENDAR_PATH_HOST)}"
            rf"{re.escape(SZSE_CALENDAR_PATH_SCRIPT_PATH)}\?random=(?P<random>[0-9]+)$",
            re.ASCII,
        )
    elif kind == "concat":
        pattern = re.compile(
            rf"^https://{re.escape(SZSE_CALENDAR_CONCATVERSION_HOST)}"
            rf"{re.escape(SZSE_CALENDAR_CONCATVERSION_PATH)}\?random=(?P<random>[0-9]+)$",
            re.ASCII,
        )
    else:
        _fail(SzseFailureCode.IDENTITY)
    match = pattern.fullmatch(url)
    if match is None:
        _fail(SzseFailureCode.IDENTITY)
    try:
        return int(match.group("random"))
    except Exception:
        _fail(SzseFailureCode.IDENTITY)


def szse_direct_daily_url(year: int, month: int) -> str:
    """Build a URL only from the fixed SZSE allowlist and validated month."""

    if type(year) is not int or year != _SUPPORTED_YEAR:
        _raise(_SCOPE_ERROR)
    if type(month) is not int or not 1 <= month <= 12:
        _raise(_SCOPE_ERROR)
    month_value = month
    return SZSE_DIRECT_DAILY_URL_TEMPLATE.format(year=year, month=month_value)


def _capture_id(run_id: UUID, label: str) -> str:
    _strict_uuid(run_id)
    if type(label) is not str or not label or "\x00" in label:
        _fail(SzseFailureCode.INTEGRITY)
    value = f"capture-{uuid5(run_id, label).hex}"
    try:
        return validate_identifier(value, "capture_id", max_length=48)
    except Exception:
        _fail(SzseFailureCode.INTEGRITY)


def _state_capture_id(run_id: UUID, attempt_id: str) -> str:
    return _capture_id(run_id, f"state:{attempt_id}")


def _domain_id(run_id: UUID, label: str) -> UUID:
    _strict_uuid(run_id)
    if type(label) is not str or not label or "\x00" in label:
        _fail(SzseFailureCode.INTEGRITY)
    return uuid5(run_id, label)


def _manifest_domain(
    run_id: UUID,
    *,
    canonical_member_digest: str,
    finalized_at: datetime,
) -> dict[str, str]:
    """Return the only manifest identity tuple accepted for one run."""

    return {
        "raw_evidence_id": str(_domain_id(run_id, "manifest-evidence")),
        "artifact_id": str(_domain_id(run_id, "manifest-artifact")),
        "capture_id": str(_domain_id(run_id, "manifest-capture")),
        "canonical_member_digest": canonical_member_digest,
        "finalized_at": finalized_at.isoformat(),
    }


def _expected_response_attempts(
    run_id: UUID,
) -> tuple[tuple[str, str, str, int | None, int | None], ...]:
    """Return the fixed response-attempt order for one successful run."""

    values: list[tuple[str, str, str, int | None, int | None]] = [
        (
            _capture_id(run_id, "attempt:root"),
            _capture_id(run_id, "capture:root"),
            "root",
            None,
            None,
        ),
        (
            _capture_id(run_id, "attempt:path"),
            _capture_id(run_id, "capture:path"),
            "path",
            None,
            None,
        ),
        (
            _capture_id(run_id, "attempt:concat"),
            _capture_id(run_id, "capture:concat"),
            "concat",
            None,
            None,
        ),
        (
            _capture_id(run_id, "attempt:js"),
            _capture_id(run_id, "capture:js"),
            "js",
            None,
            None,
        ),
    ]
    values.extend(
        (
            _capture_id(run_id, f"attempt:page:{pass_number}:{month}"),
            _capture_id(run_id, f"capture:page:{pass_number}:{month}"),
            "page",
            pass_number,
            month,
        )
        for pass_number in (1, 2)
        for month in range(1, 13)
    )
    return tuple(values)


@dataclass(frozen=True, slots=True)
class OfficialSzseResponse:
    """Bounded response returned by an injected or stdlib transport."""

    status_code: int
    content_type: str
    body: bytes
    redirected: bool = False


class OfficialSzseTransport(Protocol):
    """Transport boundary for fixed allowlisted SZSE URLs."""

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> OfficialSzseResponse: ...


@dataclass(frozen=True, slots=True)
class SzseRawReference:
    """Safe reference to one stored raw capture, without source URL/body."""

    kind: str
    capture_id: str
    object_id: str
    checksum: str
    size: int
    raw_date: str
    content_type: str
    route_digest: str
    request_identity: str
    observed_at: datetime
    available_at: datetime

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in _ENDPOINT_KINDS:
            _fail(SzseFailureCode.INTEGRITY)
        try:
            validate_identifier(self.capture_id, "capture_id", max_length=48)
            validate_identifier(self.object_id, "object_id", max_length=64)
            validate_date_identifier(self.raw_date)
        except Exception:
            _fail(SzseFailureCode.INTEGRITY)
        _strict_sha256(self.object_id)
        _strict_sha256(self.checksum)
        _strict_sha256(self.route_digest)
        if self.object_id != self.checksum:
            _fail(SzseFailureCode.INTEGRITY)
        if type(self.size) is not int or self.size < 0:
            _fail(SzseFailureCode.INTEGRITY)
        if type(self.content_type) is not str or not self.content_type:
            _fail(SzseFailureCode.INTEGRITY)
        if type(self.request_identity) is not str:
            _fail(SzseFailureCode.INTEGRITY)
        try:
            method, target = _route_parts(self.request_identity)
        except _CollectionFailureError:
            raise
        except Exception:
            _fail(SzseFailureCode.INTEGRITY)
        if target != f"path_sha256={self.route_digest}":
            _fail(SzseFailureCode.INTEGRITY)
        if method not in {"GET", "PUT"}:
            _fail(SzseFailureCode.INTEGRITY)
        observed_at = _strict_datetime(self.observed_at)
        available_at = _strict_datetime(self.available_at)
        if available_at < observed_at:
            _fail(SzseFailureCode.INTEGRITY)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "available_at", available_at)

    @property
    def raw_object_id(self) -> str:
        return self.object_id

    @property
    def raw_checksum(self) -> str:
        return self.checksum


@dataclass(frozen=True, slots=True)
class SzseCaptureAttempt:
    """Immutable success/failure state for one response or run operation."""

    attempt_id: str
    capture_id: str
    endpoint_kind: str
    pass_number: int | None
    month: int | None
    status_code: int | None
    error_code: str | None
    raw_ref: SzseRawReference | None
    state_ref: SzseRawReference | None
    observed_at: datetime
    available_at: datetime
    replay_allowed: bool

    def __post_init__(self) -> None:
        try:
            validate_identifier(self.attempt_id, "attempt_id", max_length=48)
            validate_identifier(self.capture_id, "capture_id", max_length=48)
        except Exception:
            _fail(SzseFailureCode.INTEGRITY)
        if self.endpoint_kind not in _ENDPOINT_KINDS:
            _fail(SzseFailureCode.INTEGRITY)
        if self.pass_number is not None and self.pass_number not in (1, 2):
            _fail(SzseFailureCode.INTEGRITY)
        if self.month is not None and not 1 <= self.month <= 12:
            _fail(SzseFailureCode.INTEGRITY)
        if self.status_code is not None and (
            type(self.status_code) is not int or not 100 <= self.status_code <= 599
        ):
            _fail(SzseFailureCode.INTEGRITY)
        if self.error_code is not None and self.error_code not in _FAILURE_CODES:
            _fail(SzseFailureCode.INTEGRITY)
        if type(self.replay_allowed) is not bool:
            _fail(SzseFailureCode.INTEGRITY)
        if self.replay_allowed and (self.error_code is not None or self.raw_ref is None):
            _fail(SzseFailureCode.INTEGRITY)
        observed_at = _strict_datetime(self.observed_at)
        available_at = _strict_datetime(self.available_at)
        if available_at < observed_at:
            _fail(SzseFailureCode.INTEGRITY)
        if self.raw_ref is not None and self.raw_ref.capture_id != self.capture_id:
            _fail(SzseFailureCode.INTEGRITY)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "available_at", available_at)

    @property
    def error(self) -> str | None:
        return self.error_code


@dataclass(frozen=True, slots=True)
class SzseOfficialDailyResult:
    """Public result containing proof, manifest reference, and attempts."""

    exchange: str
    year: int
    run_id: UUID
    proof: CalendarScanRunReceipt
    raw_manifest_ref: SzseRawReference
    identity_assets: tuple[SzseRawReference, ...]
    catalog_refs: tuple[SzseRawReference, ...]
    attempts: tuple[SzseCaptureAttempt, ...]

    def __post_init__(self) -> None:
        _validate_official_daily_result(self)

    @property
    def manifest(self) -> SzseRawReference:
        return self.raw_manifest_ref


def _validate_official_daily_result(result: SzseOfficialDailyResult) -> None:
    """Validate the complete public result/provenance contract in one place.

    Raw-backed replay performs byte-level checks before constructing this
    result.  This validator is the final immutable boundary, so callers cannot
    use direct construction or ``dataclasses.replace`` to detach the proof,
    attempts, and point-in-time evidence from one another.
    """

    if type(result) is not SzseOfficialDailyResult:
        _fail(SzseFailureCode.INTEGRITY)
    if (
        type(result.exchange) is not str
        or result.exchange != "SZ"
        or type(result.year) is not int
        or result.year != _SUPPORTED_YEAR
    ):
        _fail(SzseFailureCode.INTEGRITY)
    run_id = _strict_uuid(result.run_id)
    proof = result.proof
    if type(proof) is not CalendarScanRunReceipt or proof.run_id != run_id:
        _fail(SzseFailureCode.INTEGRITY)
    reconstructed_proof = CalendarScanRunReceipt(
        run_id=proof.run_id,
        authority=proof.authority,
        exchange=proof.exchange,
        year=proof.year,
        parser_version=proof.parser_version,
        contract_version=proof.contract_version,
        policy_id=proof.policy_id,
        compiled_catalog_sha256=proof.compiled_catalog_sha256,
        opened_at=proof.opened_at,
        cutoff_at=proof.cutoff_at,
        catalog_receipts=proof.catalog_receipts,
        pass_receipts=proof.pass_receipts,
        pages=proof.pages,
        manifest=proof.manifest,
        proof_digest=proof.proof_digest,
    )
    if reconstructed_proof.proof_digest != proof.proof_digest:
        _fail(SzseFailureCode.INTEGRITY)
    if type(proof.coverage) is not type(reconstructed_proof.coverage):
        _fail(SzseFailureCode.INTEGRITY)
    if (
        reconstructed_proof.coverage != proof.coverage
        or reconstructed_proof.final_year_eligible != proof.final_year_eligible
        or reconstructed_proof.daily_days != proof.daily_days
        or reconstructed_proof.primary_provenance != proof.primary_provenance
        or reconstructed_proof.manifest_member_digest != proof.manifest_member_digest
        or reconstructed_proof.page_count != proof.page_count
    ):
        _fail(SzseFailureCode.INTEGRITY)
    proof_manifest = proof.manifest
    if type(proof_manifest) is not CalendarScanRunManifestReceipt:
        _fail(SzseFailureCode.INTEGRITY)
    proof_catalogs = proof.catalog_receipts
    if type(proof_catalogs) is not tuple or len(proof_catalogs) != 12:
        _fail(SzseFailureCode.INTEGRITY)
    if any(type(catalog) is not CalendarScanRunCatalogReceipt for catalog in proof_catalogs):
        _fail(SzseFailureCode.INTEGRITY)

    manifest_reference = result.raw_manifest_ref
    if type(manifest_reference) is not SzseRawReference:
        _fail(SzseFailureCode.INTEGRITY)
    if (
        manifest_reference.kind != "manifest"
        or manifest_reference.capture_id != _capture_id(run_id, "capture:manifest")
        or manifest_reference.checksum != proof_manifest.raw_artifact_sha256
        or manifest_reference.observed_at != proof.cutoff_at
        or manifest_reference.available_at != proof.cutoff_at
        or manifest_reference.raw_date != _raw_date(proof.cutoff_at)
        or not _mime_is(manifest_reference.content_type, _JSON_TYPES)
    ):
        _fail(SzseFailureCode.INTEGRITY)
    _validate_reference_route(manifest_reference, _manifest_route())

    identity_assets = result.identity_assets
    catalog_refs = result.catalog_refs
    attempts = result.attempts
    if type(identity_assets) is not tuple or len(identity_assets) != len(_IDENTITY_KINDS):
        _fail(SzseFailureCode.INTEGRITY)
    if any(type(reference) is not SzseRawReference for reference in identity_assets):
        _fail(SzseFailureCode.INTEGRITY)
    if type(catalog_refs) is not tuple or len(catalog_refs) != 12:
        _fail(SzseFailureCode.INTEGRITY)
    if any(type(reference) is not SzseRawReference for reference in catalog_refs):
        _fail(SzseFailureCode.INTEGRITY)
    if type(attempts) is not tuple or len(attempts) != 28:
        _fail(SzseFailureCode.INTEGRITY)
    if any(type(attempt) is not SzseCaptureAttempt for attempt in attempts):
        _fail(SzseFailureCode.INTEGRITY)

    expected_attempts = _expected_response_attempts(run_id)
    if not attempts or attempts[0].endpoint_kind != "root":
        _fail(SzseFailureCode.INTEGRITY)
    path_url, concat_url = _identity_urls(_identity_random_ms(attempts[0].observed_at))
    for attempt, (attempt_id, capture_id, endpoint_kind, pass_number, month) in zip(
        attempts, expected_attempts, strict=True
    ):
        raw_reference = attempt.raw_ref
        state_reference = attempt.state_ref
        if (
            attempt.attempt_id != attempt_id
            or attempt.capture_id != capture_id
            or attempt.endpoint_kind != endpoint_kind
            or attempt.pass_number != pass_number
            or attempt.month != month
            or attempt.status_code != 200
            or attempt.error_code is not None
            or not attempt.replay_allowed
            or type(raw_reference) is not SzseRawReference
            or type(state_reference) is not SzseRawReference
            or raw_reference.kind != endpoint_kind
            or raw_reference.capture_id != capture_id
            or state_reference.kind != "run"
            or state_reference.capture_id != _state_capture_id(run_id, attempt_id)
            or attempt.observed_at != raw_reference.observed_at
            or attempt.available_at != raw_reference.available_at
            or state_reference.observed_at != attempt.available_at
            or state_reference.available_at != attempt.available_at
            or raw_reference.raw_date != _raw_date(raw_reference.observed_at)
            or state_reference.raw_date != _raw_date(state_reference.observed_at)
            or attempt.observed_at < proof.opened_at
            or attempt.available_at > proof.cutoff_at
        ):
            _fail(SzseFailureCode.INTEGRITY)

        if endpoint_kind == "root":
            expected_route = f"GET {SZSE_CALENDAR_ROOT_URL}"
            expected_types = _HTML_TYPES
        elif endpoint_kind == "path":
            expected_route = f"GET {path_url}"
            expected_types = _JS_TYPES
        elif endpoint_kind == "concat":
            expected_route = f"GET {concat_url}"
            expected_types = _JS_TYPES
        elif endpoint_kind == "js":
            expected_route = f"GET {SZSE_CALENDAR_JS_URL}"
            expected_types = _JS_TYPES
        else:
            if type(month) is not int:
                _fail(SzseFailureCode.INTEGRITY)
            expected_route = f"GET {szse_direct_daily_url(_SUPPORTED_YEAR, month)}"
            expected_types = _JSON_TYPES
        if not _mime_is(raw_reference.content_type, expected_types):
            _fail(SzseFailureCode.INTEGRITY)
        if not _mime_is(state_reference.content_type, _JSON_TYPES):
            _fail(SzseFailureCode.INTEGRITY)
        _validate_reference_route(raw_reference, expected_route)
        _validate_reference_route(state_reference, _state_route(attempt_id))

    for reference, attempt, endpoint_kind in zip(
        identity_assets, attempts[: len(_IDENTITY_KINDS)], _IDENTITY_KINDS, strict=True
    ):
        if attempt.raw_ref is None or reference != attempt.raw_ref:
            _fail(SzseFailureCode.INTEGRITY)
        if reference.raw_date != _raw_date(reference.observed_at) or not _mime_is(
            reference.content_type, _HTML_TYPES if endpoint_kind == "root" else _JS_TYPES
        ):
            _fail(SzseFailureCode.INTEGRITY)

    for month, reference, catalog in zip(range(1, 13), catalog_refs, proof_catalogs, strict=True):
        if (
            reference.kind != "catalog"
            or reference.capture_id != _capture_id(run_id, f"capture:catalog:{month}")
            or reference.checksum != catalog.raw_artifact_sha256
            or reference.raw_date != _raw_date(reference.observed_at)
            or not _mime_is(reference.content_type, _JSON_TYPES)
        ):
            _fail(SzseFailureCode.INTEGRITY)
        _validate_reference_route(reference, _catalog_route(_SUPPORTED_YEAR, month))

    pages = proof.pages
    if type(pages) is not tuple or len(pages) != 24:
        _fail(SzseFailureCode.INTEGRITY)
    for page, attempt in zip(pages, attempts[len(_IDENTITY_KINDS) :], strict=True):
        raw_reference = attempt.raw_ref
        state_reference = attempt.state_ref
        if (
            type(page) is not CalendarScanRunPage
            or type(raw_reference) is not SzseRawReference
            or type(state_reference) is not SzseRawReference
            or page.run_id != run_id
            or page.year != _SUPPORTED_YEAR
            or page.pass_number != attempt.pass_number
            or page.month != attempt.month
            or page.raw_artifact_sha256 != raw_reference.checksum
            or page.raw_artifact_sha256 == "0" * 64
            or page.observed_at != raw_reference.observed_at
            or page.available_at != raw_reference.available_at
            or page.opened_at != proof.opened_at
            or page.available_at > proof.cutoff_at
            or page.capture_id
            != _domain_id(run_id, f"page-capture:{page.pass_number}:{page.month}")
            or page.page_id != _domain_id(run_id, f"page:{page.pass_number}:{page.month}")
            or page.raw_evidence_id
            != _domain_id(run_id, f"page-evidence:{page.pass_number}:{page.month}")
            or page.artifact_id
            != _domain_id(run_id, f"page-artifact:{page.pass_number}:{page.month}")
            or state_reference.observed_at != page.available_at
            or state_reference.available_at != page.available_at
        ):
            _fail(SzseFailureCode.INTEGRITY)

    public_references: list[SzseRawReference] = []
    for identity_reference, attempt in zip(
        identity_assets, attempts[: len(_IDENTITY_KINDS)], strict=True
    ):
        if attempt.state_ref is None:
            _fail(SzseFailureCode.INTEGRITY)
        public_references.extend((identity_reference, attempt.state_ref))
    public_references.extend(catalog_refs)
    for attempt in attempts[len(_IDENTITY_KINDS) :]:
        if attempt.raw_ref is None or attempt.state_ref is None:
            _fail(SzseFailureCode.INTEGRITY)
        public_references.extend((attempt.raw_ref, attempt.state_ref))
    public_references.append(manifest_reference)
    _validate_evidence_timeline(
        tuple(public_references), opened_at=proof.opened_at, cutoff_at=proof.cutoff_at
    )


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except Exception:
        _fail(SzseFailureCode.INTEGRITY)


def _identity_policy_pins() -> dict[str, str]:
    """Return the immutable source-policy pins in deterministic endpoint order."""

    if set(_IDENTITY_SOURCE_SHA256) != set(_IDENTITY_KINDS):
        _fail(SzseFailureCode.IDENTITY)
    pins: dict[str, str] = {}
    for endpoint_kind in _IDENTITY_KINDS:
        pin = _IDENTITY_SOURCE_SHA256.get(endpoint_kind)
        if type(pin) is not str:
            _fail(SzseFailureCode.IDENTITY)
        _strict_sha256(pin)
        pins[endpoint_kind] = pin
    return pins


def _identity_policy_payload() -> dict[str, object]:
    return {
        "version": SZSE_IDENTITY_POLICY_VERSION,
        "sha256": _identity_policy_pins(),
    }


def _identity_policy_digest() -> str:
    return hashlib.sha256(_canonical_json(_identity_policy_payload())).hexdigest()


def _verify_identity_source_pin(body: bytes, endpoint_kind: object) -> None:
    """Verify the source bytes against the fixed policy before parsing them."""

    if type(endpoint_kind) is not str or endpoint_kind not in _IDENTITY_KINDS:
        _fail(SzseFailureCode.IDENTITY)
    if type(body) is not bytes:
        _fail(SzseFailureCode.IDENTITY)
    pin = _identity_policy_pins().get(endpoint_kind)
    if type(pin) is not str:
        _fail(SzseFailureCode.IDENTITY)
    actual = hashlib.sha256(body).hexdigest()
    if not hmac.compare_digest(actual, pin):
        _fail(SzseFailureCode.IDENTITY)


def _canonical_content_type(value: object) -> str | None:
    normalized, failed = _safe_call(lambda: normalize_content_type(value))
    return None if failed or type(normalized) is not str else normalized


def _mime_is(value: object, allowed: frozenset[str]) -> bool:
    normalized = _canonical_content_type(value)
    return normalized is not None and normalized.split(";", 1)[0] in allowed


def _observation_time(clock: Callable[[], datetime]) -> datetime:
    value, failed = _safe_call(clock)
    if failed:
        _raise(_TIME_ERROR)
    normalized: datetime | None = None
    with suppress(_CollectionFailureError):
        normalized = _strict_datetime(value)
    if normalized is None:
        _raise(_TIME_ERROR)
    return normalized


def _raw_date(timestamp: datetime) -> str:
    try:
        return timestamp.astimezone(_SHANGHAI_TZ).date().isoformat()
    except Exception:
        _fail(SzseFailureCode.INTEGRITY)


def _reference_from_manifest(
    manifest: RawObjectManifest,
    kind: str,
    *,
    route_digest: str | None = None,
    request_identity: str | None = None,
) -> SzseRawReference:
    if type(manifest) is not RawObjectManifest:
        _fail(SzseFailureCode.RAW)
    available = manifest.available_time
    if available is None:
        _fail(SzseFailureCode.RAW)
    if route_digest is None or request_identity is None:
        _fail(SzseFailureCode.INTEGRITY)
    return SzseRawReference(
        kind=kind,
        capture_id=manifest.capture_id,
        object_id=manifest.object_id,
        checksum=manifest.checksum,
        size=manifest.size,
        raw_date=manifest.date,
        content_type=manifest.content_type,
        route_digest=route_digest,
        request_identity=request_identity,
        observed_at=manifest.ingest_time,
        available_at=available,
    )


def _store_raw(
    raw_storage: RawStorage,
    *,
    source: str,
    capture_id: str,
    route: str,
    content: bytes,
    content_type: str,
    observed_at: datetime,
    kind: str,
) -> tuple[SzseRawReference, bytes]:
    if type(content) is not bytes:
        _fail(SzseFailureCode.RAW)
    route_digest = _route_digest(route)
    request_identity = _route_request_identity(route)
    raw_date = _raw_date(observed_at)
    manifest, failed = _safe_call(
        lambda: raw_storage.put(
            source=source,
            date=raw_date,
            request=request_identity,
            content=content,
            content_type=content_type,
            capture_id=capture_id,
            ingest_time=observed_at,
            available_time=observed_at,
        )
    )
    if failed or type(manifest) is not RawObjectManifest:
        _fail(SzseFailureCode.RAW)
    expected_checksum = hashlib.sha256(content).hexdigest()
    if (
        manifest.source != source
        or manifest.date != raw_date
        or manifest.capture_id != capture_id
        or manifest.object_id != expected_checksum
        or manifest.size != len(content)
        or manifest.checksum != expected_checksum
        or manifest.content_type != normalize_content_type(content_type)
        or manifest.request != request_identity
        or manifest.ingest_time != observed_at
        or manifest.available_time != observed_at
    ):
        _fail(SzseFailureCode.INTEGRITY)
    replayed, get_failed = _safe_call(
        lambda: raw_storage.get(
            manifest.object_id,
            checksum=manifest.checksum,
            size=manifest.size,
        )
    )
    if get_failed or type(replayed) is not bytes or replayed != content:
        _fail(SzseFailureCode.INTEGRITY)
    return (
        _reference_from_manifest(
            manifest,
            kind,
            route_digest=route_digest,
            request_identity=request_identity,
        ),
        replayed,
    )


def _attempt_payload(attempt: SzseCaptureAttempt) -> dict[str, object]:
    if type(attempt) is not SzseCaptureAttempt:
        _fail(SzseFailureCode.INTEGRITY)
    return {
        "attempt_id": attempt.attempt_id,
        "capture_id": attempt.capture_id,
        "endpoint_kind": attempt.endpoint_kind,
        "pass_number": attempt.pass_number,
        "month": attempt.month,
        "status_code": attempt.status_code,
        "error_code": attempt.error_code,
        "raw_ref": None if attempt.raw_ref is None else _raw_ref_payload(attempt.raw_ref),
        "state_ref": None if attempt.state_ref is None else _raw_ref_payload(attempt.state_ref),
        "observed_at": attempt.observed_at.isoformat(),
        "available_at": attempt.available_at.isoformat(),
        "replay_allowed": attempt.replay_allowed,
    }


def _raw_ref_payload(reference: SzseRawReference) -> dict[str, object]:
    if type(reference) is not SzseRawReference:
        _fail(SzseFailureCode.INTEGRITY)
    return {
        "kind": reference.kind,
        "capture_id": reference.capture_id,
        "object_id": reference.object_id,
        "checksum": reference.checksum,
        "size": reference.size,
        "raw_date": reference.raw_date,
        "content_type": reference.content_type,
        "route_digest": reference.route_digest,
        "request_identity": reference.request_identity,
        "observed_at": reference.observed_at.isoformat(),
        "available_at": reference.available_at.isoformat(),
    }


def _state_payload(attempt: SzseCaptureAttempt) -> dict[str, object]:
    return {
        "version": SZSE_CAPTURE_STATE_VERSION,
        "attempt_id": attempt.attempt_id,
        "capture_id": attempt.capture_id,
        "endpoint_kind": attempt.endpoint_kind,
        "pass_number": attempt.pass_number,
        "month": attempt.month,
        "status_code": attempt.status_code,
        "error_code": attempt.error_code,
        "raw_ref": None if attempt.raw_ref is None else _raw_ref_payload(attempt.raw_ref),
        "observed_at": attempt.observed_at.isoformat(),
        "available_at": attempt.available_at.isoformat(),
        "replay_allowed": attempt.replay_allowed,
    }


def _attempt_marker_bytes(run_id: UUID, attempt_id: str, code: str) -> bytes:
    return _canonical_json(
        {
            "kind": "attempt",
            "run_id": str(run_id),
            "attempt_id": attempt_id,
            "error_code": code if code in _FAILURE_CODES else SzseFailureCode.INTEGRITY,
        }
    )


def _parse_iso_datetime(value: object) -> datetime:
    if type(value) is not str:
        _fail(SzseFailureCode.INTEGRITY)
    try:
        parsed = datetime.fromisoformat(value)
    except Exception:
        _fail(SzseFailureCode.INTEGRITY)
    return _strict_datetime(parsed)


def _parse_raw_ref(value: object, *, expected_kind: str | None = None) -> SzseRawReference:
    if type(value) is not dict:
        _fail(SzseFailureCode.INTEGRITY)
    payload = cast(dict[str, object], value)
    allowed = {
        "kind",
        "capture_id",
        "object_id",
        "checksum",
        "size",
        "raw_date",
        "content_type",
        "route_digest",
        "request_identity",
        "observed_at",
        "available_at",
    }
    if set(payload) != allowed:
        _fail(SzseFailureCode.INTEGRITY)
    kind = payload.get("kind")
    if expected_kind is not None and kind != expected_kind:
        _fail(SzseFailureCode.INTEGRITY)
    return SzseRawReference(
        kind=cast(str, kind),
        capture_id=cast(str, payload.get("capture_id")),
        object_id=cast(str, payload.get("object_id")),
        checksum=cast(str, payload.get("checksum")),
        size=cast(int, payload.get("size")),
        raw_date=cast(str, payload.get("raw_date")),
        content_type=cast(str, payload.get("content_type")),
        route_digest=cast(str, payload.get("route_digest")),
        request_identity=cast(str, payload.get("request_identity")),
        observed_at=_parse_iso_datetime(payload.get("observed_at")),
        available_at=_parse_iso_datetime(payload.get("available_at")),
    )


def _load_raw_reference(
    raw_storage: RawStorage,
    reference: SzseRawReference,
    *,
    source: str,
    expected_route: str | None = None,
) -> bytes:
    if expected_route is not None:
        try:
            _validate_reference_route(reference, expected_route)
        except _CollectionFailureError:
            raise
        except Exception:
            _fail(SzseFailureCode.INTEGRITY)
    manifests, failed = _safe_call(lambda: raw_storage.list(source, reference.raw_date))
    if failed or type(manifests) is not list:
        _fail(SzseFailureCode.INTEGRITY)
    matches = [
        manifest
        for manifest in manifests
        if type(manifest) is RawObjectManifest and manifest.capture_id == reference.capture_id
    ]
    if len(matches) != 1:
        _fail(SzseFailureCode.INTEGRITY)
    manifest = matches[0]
    if (
        manifest.source != source
        or manifest.date != reference.raw_date
        or manifest.capture_id != reference.capture_id
        or manifest.object_id != reference.object_id
        or manifest.checksum != reference.checksum
        or manifest.size != reference.size
        or manifest.content_type != reference.content_type
        or manifest.request != reference.request_identity
        or manifest.ingest_time != reference.observed_at
        or manifest.available_time != reference.available_at
    ):
        _fail(SzseFailureCode.INTEGRITY)
    content, get_failed = _safe_call(
        lambda: raw_storage.get(
            manifest.object_id,
            checksum=manifest.checksum,
            size=manifest.size,
        )
    )
    if (
        get_failed
        or type(content) is not bytes
        or len(content) != reference.size
        or hashlib.sha256(content).hexdigest() != reference.checksum
    ):
        _fail(SzseFailureCode.INTEGRITY)
    return content


def _ledger_capture_id(run_id: UUID, kind: str) -> str:
    return _capture_id(run_id, f"ledger:{kind}")


def _ledger_payload(
    *,
    run_id: UUID,
    kind: str,
    claim_nonce: str,
    manifest_date: str | None = None,
    manifest_capture_id: str | None = None,
    proof_digest: str | None = None,
) -> bytes:
    if type(claim_nonce) is not str or re.fullmatch(r"[0-9a-f]{32}", claim_nonce) is None:
        _fail(SzseFailureCode.INTEGRITY)
    if kind == "claim":
        payload: dict[str, object] = {
            "version": SZSE_RUN_LEDGER_VERSION,
            "kind": "claim",
            "run_id": str(run_id),
            "status": "CLAIMED",
            "claim_nonce": claim_nonce,
            "identity_policy_version": SZSE_IDENTITY_POLICY_VERSION,
            "identity_policy_digest": _identity_policy_digest(),
        }
    elif kind == "final":
        if manifest_date is None or manifest_capture_id is None or proof_digest is None:
            _fail(SzseFailureCode.INTEGRITY)
        payload = {
            "version": SZSE_RUN_LEDGER_VERSION,
            "kind": "final",
            "run_id": str(run_id),
            "status": "FINAL",
            "claim_nonce": claim_nonce,
            "identity_policy_version": SZSE_IDENTITY_POLICY_VERSION,
            "manifest_date": manifest_date,
            "manifest_capture_id": manifest_capture_id,
            "proof_digest": proof_digest,
            "identity_policy_digest": _identity_policy_digest(),
        }
    else:
        _fail(SzseFailureCode.INTEGRITY)
    return _canonical_json(payload)


def _store_ledger_entry(
    raw_storage: RawStorage,
    *,
    run_id: UUID,
    kind: str,
    content: bytes,
    at: datetime,
) -> SzseRawReference:
    _strict_uuid(run_id)
    if type(content) is not bytes:
        _fail(SzseFailureCode.RAW)
    capture_id = _ledger_capture_id(run_id, kind)
    route = _ledger_route(kind)
    route_digest = _route_digest(route)
    request_identity = _route_request_identity(route)
    expected_checksum = hashlib.sha256(content).hexdigest()
    try:
        manifest = raw_storage.put(
            source=SZSE_RUN_LEDGER_SOURCE,
            date=SZSE_RUN_LEDGER_DATE,
            request=request_identity,
            content=content,
            content_type="application/json",
            capture_id=capture_id,
            ingest_time=at,
            available_time=at,
        )
    except CaptureConflictError:
        _raise(_LEDGER_CONFLICT_ERROR)
    except Exception:
        _raise(_LEDGER_ERROR)
    if type(manifest) is not RawObjectManifest:
        _raise(_LEDGER_ERROR)
    if (
        manifest.source != SZSE_RUN_LEDGER_SOURCE
        or manifest.date != SZSE_RUN_LEDGER_DATE
        or manifest.request != request_identity
        or manifest.capture_id != capture_id
        or manifest.object_id != expected_checksum
        or manifest.checksum != expected_checksum
        or manifest.size != len(content)
        or manifest.content_type != "application/json"
        or manifest.ingest_time != at
        or manifest.available_time != at
    ):
        _raise(_LEDGER_ERROR)
    replayed, failed = _safe_call(
        lambda: raw_storage.get(
            manifest.object_id,
            checksum=manifest.checksum,
            size=manifest.size,
        )
    )
    if failed or type(replayed) is not bytes or replayed != content:
        _raise(_LEDGER_ERROR)
    try:
        return _reference_from_manifest(
            manifest,
            "run",
            route_digest=route_digest,
            request_identity=request_identity,
        )
    except _CollectionFailureError:
        _raise(_LEDGER_ERROR)


def _read_ledger_entry(
    raw_storage: RawStorage,
    *,
    run_id: UUID,
    kind: str,
    manifest: RawObjectManifest,
) -> tuple[SzseRawReference, dict[str, object]]:
    capture_id = _ledger_capture_id(run_id, kind)
    route = _ledger_route(kind)
    if manifest.capture_id != capture_id:
        _raise(_LEDGER_ERROR)
    reference: SzseRawReference | None = None
    content: bytes | None = None
    failed = False
    try:
        reference = _reference_from_manifest(
            manifest,
            "run",
            route_digest=_route_digest(route),
            request_identity=_route_request_identity(route),
        )
        content = _load_raw_reference(
            raw_storage,
            reference,
            source=SZSE_RUN_LEDGER_SOURCE,
            expected_route=route,
        )
    except Exception:
        failed = True
    if failed or reference is None or content is None:
        _raise(_LEDGER_ERROR)
    try:
        payload = _parse_json_object(content)
    except Exception:
        _raise(_LEDGER_ERROR)
    return reference, payload


def _validate_ledger_claim(payload: Mapping[str, object], run_id: UUID) -> None:
    if set(payload) != {
        "version",
        "kind",
        "run_id",
        "status",
        "claim_nonce",
        "identity_policy_version",
        "identity_policy_digest",
    }:
        _raise(_LEDGER_ERROR)
    nonce = payload.get("claim_nonce")
    if (
        payload.get("version") != SZSE_RUN_LEDGER_VERSION
        or payload.get("kind") != "claim"
        or payload.get("run_id") != str(run_id)
        or payload.get("status") != "CLAIMED"
        or type(nonce) is not str
        or re.fullmatch(r"[0-9a-f]{32}", nonce) is None
        or payload.get("identity_policy_version") != SZSE_IDENTITY_POLICY_VERSION
        or payload.get("identity_policy_digest") != _identity_policy_digest()
    ):
        _raise(_LEDGER_ERROR)


def _validate_ledger_final(payload: Mapping[str, object], run_id: UUID) -> None:
    if set(payload) != {
        "version",
        "kind",
        "run_id",
        "status",
        "claim_nonce",
        "manifest_date",
        "manifest_capture_id",
        "proof_digest",
        "identity_policy_version",
        "identity_policy_digest",
    }:
        _raise(_LEDGER_ERROR)
    try:
        validate_date_identifier(payload.get("manifest_date"))
        validate_identifier(payload.get("manifest_capture_id"), "capture_id", max_length=48)
    except Exception:
        _raise(_LEDGER_ERROR)
    if (
        payload.get("version") != SZSE_RUN_LEDGER_VERSION
        or payload.get("kind") != "final"
        or payload.get("run_id") != str(run_id)
        or payload.get("status") != "FINAL"
        or type(payload.get("claim_nonce")) is not str
        or re.fullmatch(r"[0-9a-f]{32}", cast(str, payload.get("claim_nonce"))) is None
        or type(payload.get("proof_digest")) is not str
        or _SHA256_RE.fullmatch(cast(str, payload.get("proof_digest"))) is None
        or payload.get("identity_policy_version") != SZSE_IDENTITY_POLICY_VERSION
        or payload.get("identity_policy_digest") != _identity_policy_digest()
    ):
        _raise(_LEDGER_ERROR)


def _load_ledger_state(
    raw_storage: RawStorage,
    *,
    run_id: UUID,
) -> dict[str, object] | None:
    try:
        manifests = raw_storage.list(SZSE_RUN_LEDGER_SOURCE, SZSE_RUN_LEDGER_DATE)
    except Exception:
        _raise(_LEDGER_ERROR)
    if type(manifests) is not list:
        _raise(_LEDGER_ERROR)
    claim_matches: list[RawObjectManifest] = []
    final_matches: list[RawObjectManifest] = []
    claim_id = _ledger_capture_id(run_id, "claim")
    final_id = _ledger_capture_id(run_id, "final")
    for manifest in manifests:
        if type(manifest) is not RawObjectManifest:
            _raise(_LEDGER_ERROR)
        if manifest.capture_id == claim_id:
            claim_matches.append(manifest)
        elif manifest.capture_id == final_id:
            final_matches.append(manifest)
    if len(claim_matches) > 1 or len(final_matches) > 1:
        _raise(_LEDGER_ERROR)
    if not claim_matches and not final_matches:
        return None
    if not claim_matches:
        _raise(_LEDGER_ERROR)
    claim_reference, claim_payload = _read_ledger_entry(
        raw_storage,
        run_id=run_id,
        kind="claim",
        manifest=claim_matches[0],
    )
    _validate_ledger_claim(claim_payload, run_id)
    if not final_matches:
        _raise(_LEDGER_CONFLICT_ERROR)
    final_reference, final_payload = _read_ledger_entry(
        raw_storage,
        run_id=run_id,
        kind="final",
        manifest=final_matches[0],
    )
    _validate_ledger_final(final_payload, run_id)
    if claim_reference.available_at > final_reference.observed_at or claim_payload.get(
        "claim_nonce"
    ) != final_payload.get("claim_nonce"):
        _raise(_LEDGER_ERROR)
    return final_payload


def _validate_evidence_timeline(
    references: tuple[SzseRawReference, ...],
    *,
    opened_at: datetime,
    cutoff_at: datetime,
) -> None:
    """Require every persisted evidence reference to fit the run window/order."""

    previous = opened_at
    for reference in references:
        if (
            type(reference) is not SzseRawReference
            or reference.observed_at < opened_at
            or reference.available_at > cutoff_at
            or reference.observed_at < previous
            or reference.available_at < reference.observed_at
        ):
            _fail(SzseFailureCode.INTEGRITY)
        previous = reference.available_at


def _store_attempt_state(
    raw_storage: RawStorage,
    run_id: UUID,
    attempt: SzseCaptureAttempt,
) -> SzseCaptureAttempt:
    state_capture_id = _state_capture_id(run_id, attempt.attempt_id)
    content = _canonical_json(_state_payload(attempt))
    try:
        state_ref, _ = _store_raw(
            raw_storage,
            source=SZSE_CAPTURE_STATE_SOURCE,
            capture_id=state_capture_id,
            route=_state_route(attempt.attempt_id),
            content=content,
            content_type="application/json",
            observed_at=attempt.available_at,
            kind="run",
        )
    except _CollectionFailureError:
        raise
    except Exception:
        _fail(SzseFailureCode.RAW)
    return replace(attempt, state_ref=state_ref)


@dataclass(frozen=True, slots=True)
class _Captured:
    attempt_id: str
    capture_id: str
    endpoint_kind: str
    pass_number: int | None
    month: int | None
    status_code: int | None
    content_type: str
    redirected: bool
    reference: SzseRawReference
    body: bytes


def _parse_date(value: object) -> date:
    if type(value) is not str or _DATE_RE.fullmatch(value) is None:
        _fail(SzseFailureCode.SCHEMA)
    try:
        parsed = date.fromisoformat(value)
    except Exception:
        _fail(SzseFailureCode.SCHEMA)
    if parsed.isoformat() != value:
        _fail(SzseFailureCode.SCHEMA)
    return parsed


def _parse_json_object(body: bytes) -> dict[str, object]:
    try:
        decoded = json.loads(body.decode("utf-8"))
    except Exception:
        _fail(SzseFailureCode.SCHEMA)
    if type(decoded) is not dict:
        _fail(SzseFailureCode.SCHEMA)
    return cast(dict[str, object], decoded)


def _parse_json_list(value: object) -> list[object]:
    if type(value) is not list:
        _fail(SzseFailureCode.SCHEMA)
    return cast(list[object], value)


def _json_object(value: object) -> dict[str, object]:
    if type(value) is not dict:
        _fail(SzseFailureCode.INTEGRITY)
    return cast(dict[str, object], value)


def _parse_month_body(
    body: bytes,
    *,
    year: int,
    month: int,
) -> tuple[date, tuple[CalendarScanRunDay, ...]]:
    payload = _parse_json_object(body)
    if set(payload) != {"data", "nowdate"}:
        _fail(SzseFailureCode.SCHEMA)
    nowdate = _parse_date(payload.get("nowdate"))
    rows = _parse_json_list(payload.get("data"))
    expected_dates = tuple(
        date(year, month, day) for day in range(1, calendar.monthrange(year, month)[1] + 1)
    )
    parsed: list[CalendarScanRunDay] = []
    for row_value in rows:
        row = _json_object(row_value)
        if set(row) != {"jyrq", "jybz", "zrxh"}:
            _fail(SzseFailureCode.SCHEMA)
        row_date = _parse_date(row.get("jyrq"))
        status = row.get("jybz")
        if type(status) is not str or status not in {"0", "1"}:
            _fail(SzseFailureCode.SCHEMA)
        weekday = row.get("zrxh")
        if type(weekday) is not int or not 1 <= weekday <= 7:
            _fail(SzseFailureCode.SCHEMA)
        expected_weekday = (row_date.weekday() + 1) % 7 + 1
        if weekday != expected_weekday:
            _fail(SzseFailureCode.SCHEMA)
        parsed.append(CalendarScanRunDay(date=row_date, is_trading_day=status == "1"))
    if len(parsed) != len(expected_dates) or tuple(day.date for day in parsed) != expected_dates:
        _fail(SzseFailureCode.MONTH_DAYS)
    return nowdate, tuple(parsed)


def _decode_identity_text(body: bytes) -> str:
    if type(body) is not bytes:
        _fail(SzseFailureCode.IDENTITY)
    try:
        text = body.decode("utf-8")
    except Exception:
        _fail(SzseFailureCode.IDENTITY)
    if "\x00" in text:
        _fail(SzseFailureCode.IDENTITY)
    return text


def _strip_javascript_comments(text: str) -> str:
    """Remove JavaScript comments without interpreting or executing code."""

    def can_start_regex(position: int) -> bool:
        cursor = position - 1
        while cursor >= 0 and text[cursor].isspace():
            cursor -= 1
        if cursor < 0 or text[cursor] in "([{=,:;!&|?":
            return True
        end = cursor + 1
        while cursor >= 0 and (text[cursor].isalnum() or text[cursor] in {"_", "$"}):
            cursor -= 1
        previous_word = text[cursor + 1 : end]
        return previous_word in {
            "case",
            "delete",
            "else",
            "in",
            "of",
            "return",
            "throw",
            "typeof",
            "void",
        }

    output: list[str] = []
    index = 0
    quote: str | None = None
    escaped = False
    while index < len(text):
        character = text[index]
        if quote is not None:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"', "`"}:
            quote = character
            output.append(character)
            index += 1
            continue
        if character == "/" and index + 1 < len(text):
            next_character = text[index + 1]
            if next_character == "/":
                index += 2
                while index < len(text) and text[index] not in {"\r", "\n"}:
                    index += 1
                continue
            if next_character == "*":
                index += 2
                while index + 1 < len(text) and text[index : index + 2] != "*/":
                    index += 1
                if index + 1 >= len(text):
                    _fail(SzseFailureCode.IDENTITY)
                index += 2
                continue
            if can_start_regex(index):
                regex_start = index
                index += 1
                regex_escaped = False
                in_character_class = False
                while index < len(text):
                    regex_character = text[index]
                    if regex_escaped:
                        regex_escaped = False
                    elif regex_character == "\\":
                        regex_escaped = True
                    elif regex_character == "[":
                        in_character_class = True
                    elif regex_character == "]":
                        in_character_class = False
                    elif regex_character == "/" and not in_character_class:
                        index += 1
                        while index < len(text) and text[index].isalpha():
                            index += 1
                        output.append(text[regex_start:index])
                        break
                    elif regex_character in {"\r", "\n"}:
                        break
                    index += 1
                else:
                    index = regex_start
                if index != regex_start:
                    continue
        output.append(character)
        index += 1
    if quote is not None:
        _fail(SzseFailureCode.IDENTITY)
    return "".join(output)


def _javascript_string_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Return string-literal spans for the small identity grammar."""

    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character not in {"'", '"', "`"}:
            index += 1
            continue
        quote = character
        start = index
        index += 1
        escaped = False
        while index < len(text):
            character = text[index]
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                spans.append((start, index + 1))
                index += 1
                break
            index += 1
        else:
            _fail(SzseFailureCode.IDENTITY)
    return tuple(spans)


def _match_outside_strings(match: re.Match[str], spans: tuple[tuple[int, int], ...]) -> bool:
    return not any(start <= match.start() < end for start, end in spans)


def _match_at_string_start(match: re.Match[str], spans: tuple[tuple[int, int], ...]) -> bool:
    return any(match.start() == start for start, _end in spans)


@dataclass(frozen=True, slots=True)
class _JavascriptToken:
    kind: str
    value: str
    brace_depth: int
    paren_depth: int
    bracket_depth: int


@dataclass(frozen=True, slots=True)
class _RootChangeVersionCall:
    first_literal: str | None
    second_literal: str | None
    top_level: bool
    guarded: bool
    valid_arguments: bool


def _javascript_tokens(text: str) -> tuple[_JavascriptToken, ...]:
    """Tokenize only the syntax needed for the root call grammar."""

    text_without_comments = _strip_javascript_comments(text)
    tokens: list[_JavascriptToken] = []
    index = 0
    brace_depth = 0
    paren_depth = 0
    bracket_depth = 0
    while index < len(text_without_comments):
        character = text_without_comments[index]
        if character.isspace():
            index += 1
            continue
        if character in {"'", '"', "`"}:
            quote = character
            start = index
            index += 1
            escaped = False
            while index < len(text_without_comments):
                character = text_without_comments[index]
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == quote:
                    tokens.append(
                        _JavascriptToken(
                            "string",
                            text_without_comments[start + 1 : index],
                            brace_depth,
                            paren_depth,
                            bracket_depth,
                        )
                    )
                    index += 1
                    break
                index += 1
            else:
                _fail(SzseFailureCode.IDENTITY)
            continue
        if character.isalpha() or character in {"_", "$"}:
            start = index
            index += 1
            while index < len(text_without_comments) and (
                text_without_comments[index].isalnum() or text_without_comments[index] in {"_", "$"}
            ):
                index += 1
            tokens.append(
                _JavascriptToken(
                    "identifier",
                    text_without_comments[start:index],
                    brace_depth,
                    paren_depth,
                    bracket_depth,
                )
            )
            continue
        if character.isdigit():
            start = index
            index += 1
            while index < len(text_without_comments) and (
                text_without_comments[index].isalnum() or text_without_comments[index] in {".", "_"}
            ):
                index += 1
            tokens.append(
                _JavascriptToken(
                    "number",
                    text_without_comments[start:index],
                    brace_depth,
                    paren_depth,
                    bracket_depth,
                )
            )
            continue
        token_value = character
        for width in (3, 2):
            candidate = text_without_comments[index : index + width]
            if candidate in {"===", "!==", "==", "!=", "&&", "||", "++", "--"}:
                token_value = candidate
                index += width
                break
        else:
            index += 1
        tokens.append(
            _JavascriptToken(
                "symbol",
                token_value,
                brace_depth,
                paren_depth,
                bracket_depth,
            )
        )
        if token_value == "{":
            brace_depth += 1
        elif token_value == "}":
            brace_depth -= 1
            if brace_depth < 0:
                _fail(SzseFailureCode.IDENTITY)
        elif token_value == "(":
            paren_depth += 1
        elif token_value == ")":
            paren_depth -= 1
            if paren_depth < 0:
                _fail(SzseFailureCode.IDENTITY)
        elif token_value == "[":
            bracket_depth += 1
        elif token_value == "]":
            bracket_depth -= 1
            if bracket_depth < 0:
                _fail(SzseFailureCode.IDENTITY)
    if brace_depth or paren_depth or bracket_depth:
        _fail(SzseFailureCode.IDENTITY)
    return tuple(tokens)


def _root_call_is_guarded(tokens: tuple[_JavascriptToken, ...], index: int) -> bool:
    """Reject target calls under top-level control-flow statements."""

    current_depth = tokens[index].brace_depth
    start = index - 1
    while start >= 0:
        token = tokens[start]
        if token.brace_depth < current_depth or (
            token.brace_depth == current_depth and token.value in {";", "{"}
        ):
            break
        start -= 1
    return any(
        token.kind == "identifier"
        and token.value in {"if", "else", "for", "while", "switch", "case", "do"}
        for token in tokens[start + 1 : index]
    )


def _root_change_version_calls(text: str) -> tuple[_RootChangeVersionCall, ...]:
    tokens = _javascript_tokens(text)
    calls: list[_RootChangeVersionCall] = []
    for index, token in enumerate(tokens[:-1]):
        if token.kind != "identifier" or token.value != "changeVertion":
            continue
        opening_index = index + 1
        if tokens[opening_index].value != "(":
            continue
        depth = 1
        closing_index: int | None = None
        cursor = opening_index + 1
        while cursor < len(tokens):
            value = tokens[cursor].value
            if value == "(":
                depth += 1
            elif value == ")":
                depth -= 1
                if depth == 0:
                    closing_index = cursor
                    break
            cursor += 1
        if closing_index is None:
            _fail(SzseFailureCode.IDENTITY)
        arguments = tokens[opening_index + 1 : closing_index]
        valid_arguments = (
            len(arguments) == 3
            and arguments[0].kind == "string"
            and arguments[1].value == ","
            and arguments[2].kind == "string"
        )
        first_literal = arguments[0].value if arguments and arguments[0].kind == "string" else None
        second_literal = (
            arguments[2].value if len(arguments) >= 3 and arguments[2].kind == "string" else None
        )
        direct_call = index == 0 or tokens[index - 1].value != "."
        top_level = (
            direct_call
            and token.brace_depth == 0
            and token.paren_depth == 0
            and token.bracket_depth == 0
        )
        calls.append(
            _RootChangeVersionCall(
                first_literal=first_literal,
                second_literal=second_literal,
                top_level=top_level,
                guarded=_root_call_is_guarded(tokens, index),
                valid_arguments=valid_arguments,
            )
        )
    return tuple(calls)


def _balanced_javascript_block(text: str, opening: int) -> tuple[str, int]:
    """Return a brace-delimited body and its closing-brace offset."""

    if opening < 0 or opening >= len(text) or text[opening] != "{":
        _fail(SzseFailureCode.IDENTITY)
    depth = 0
    index = opening
    quote: str | None = None
    escaped = False
    while index < len(text):
        character = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"', "`"}:
            quote = character
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index], index
        index += 1
    _fail(SzseFailureCode.IDENTITY)


def _change_version_function_body(text: str, function_match: re.Match[str]) -> str:
    """Return the balanced changeVertion body for grammar-only validation."""

    opening = text.find("{", function_match.end())
    body, _closing = _balanced_javascript_block(text, opening)
    return _strip_javascript_comments(body)


def _parse_root_dynamic_urls(
    script_tokens: tuple[tuple[_JavascriptToken, ...], ...], *, random_ms: int
) -> tuple[str, str]:
    """Validate the exact variable-based dynamic identity writer in the root."""

    expected_arguments = (
        ("string", " <script src='"),
        ("symbol", "+"),
        ("identifier", "_host"),
        ("symbol", "+"),
        ("string", "/szsePath.js?random="),
        ("symbol", "+"),
        ("identifier", "_versionDate"),
        ("symbol", "+"),
        ("string", "'> <\\/script> "),
        ("symbol", "+"),
        ("string", " <script src='"),
        ("symbol", "+"),
        ("identifier", "_path"),
        ("symbol", "+"),
        ("string", "/common/js/concatversion.js?random="),
        ("symbol", "+"),
        ("identifier", "_versionDate"),
        ("symbol", "+"),
        ("string", "'> <\\/script> "),
    )
    relevant_calls: list[tuple[_JavascriptToken, ...]] = []
    for tokens in script_tokens:
        for index, token in enumerate(tokens):
            if (
                token.kind != "identifier"
                or token.value != "document"
                or index + 3 >= len(tokens)
                or tokens[index + 1].value != "."
                or tokens[index + 2].kind != "identifier"
                or tokens[index + 2].value != "write"
                or tokens[index + 3].value != "("
            ):
                continue
            depth = 1
            cursor = index + 4
            while cursor < len(tokens) and depth:
                if tokens[cursor].value == "(":
                    depth += 1
                elif tokens[cursor].value == ")":
                    depth -= 1
                cursor += 1
            if depth:
                _fail(SzseFailureCode.IDENTITY)
            arguments = tokens[index + 4 : cursor - 1]
            if any(
                token.kind == "string"
                and ("szsePath.js" in token.value or "concatversion.js" in token.value)
                for token in arguments
            ):
                relevant_calls.append(arguments)
    if len(relevant_calls) != 1:
        _fail(SzseFailureCode.IDENTITY)
    actual_arguments = tuple((token.kind, token.value) for token in relevant_calls[0])
    if actual_arguments != expected_arguments:
        _fail(SzseFailureCode.IDENTITY)
    path_url, concat_url = _identity_urls(random_ms)
    _validated_dynamic_identity_url(path_url, kind="path")
    _validated_dynamic_identity_url(concat_url, kind="concat")
    return path_url, concat_url


def _parse_root_identity(body: bytes, *, random_ms: int) -> tuple[str, str]:
    """Parse root identity resources and the unique top-level calendar call."""

    text = _decode_identity_text(body)
    if "深圳证券交易所" not in text:
        _fail(SzseFailureCode.IDENTITY)
    scripts = tuple(_SCRIPT_TAG_RE.finditer(text))
    if not scripts:
        _fail(SzseFailureCode.IDENTITY)
    script_texts: list[str] = []
    script_tokens: list[tuple[_JavascriptToken, ...]] = []
    calls: list[_RootChangeVersionCall] = []
    for script in scripts:
        attributes = script.group("attributes")
        sources = tuple(match.group("value") for match in _SCRIPT_SRC_RE.finditer(attributes))
        if len(sources) > 1:
            _fail(SzseFailureCode.IDENTITY)
        if sources:
            source = sources[0]
            if (
                source in {SZSE_CALENDAR_JS_URL, SZSE_CALENDAR_SCRIPT_PATH}
                or "szsePath.js" in source
                or "concatversion.js" in source
                or "tradeCalendar/js/tradeCanledar_new" in source
            ):
                _fail(SzseFailureCode.IDENTITY)
        script_body = script.group("body")
        script_texts.append(_strip_javascript_comments(script_body))
        tokens = _javascript_tokens(script_body)
        script_tokens.append(tokens)
        calls.extend(_root_change_version_calls(script_body))
    identity_text = "\n".join(script_texts)
    identity_spans = _javascript_string_spans(identity_text)

    def outside(pattern: re.Pattern[str]) -> tuple[re.Match[str], ...]:
        return tuple(
            match
            for match in pattern.finditer(identity_text)
            if _match_outside_strings(match, identity_spans)
        )

    if (
        len(outside(_ROOT_VERSION_DATE_RE)) != 1
        or len(outside(_ROOT_VERSION_DATE_ANY_ASSIGNMENT_RE)) != 1
        or len(outside(_ROOT_PATH_HTTPS_BRANCH_RE)) != 1
        or len(outside(_ROOT_PATH_HTTP_ASSIGNMENT_RE)) != 1
        or len(outside(_ROOT_PATH_HTTPS_ASSIGNMENT_RE)) != 1
        or len(outside(_ROOT_HOST_HTTPS_BRANCH_RE)) != 1
        or len(outside(_ROOT_HOST_HTTP_ASSIGNMENT_RE)) != 1
        or len(outside(_ROOT_HOST_HTTPS_ASSIGNMENT_RE)) != 1
        or len(outside(_ROOT_PATH_REPLACE_RE)) != 1
    ):
        _fail(SzseFailureCode.IDENTITY)
    path_url, concat_url = _parse_root_dynamic_urls(tuple(script_tokens), random_ms=random_ms)
    target_calls = [call for call in calls if call.first_literal == SZSE_CALENDAR_SCRIPT_PATH]
    if len(target_calls) != 1:
        _fail(SzseFailureCode.IDENTITY)
    target = target_calls[0]
    if (
        not target.valid_arguments
        or target.second_literal != "js"
        or not target.top_level
        or target.guarded
    ):
        _fail(SzseFailureCode.IDENTITY)
    if any(not call.valid_arguments for call in calls):
        _fail(SzseFailureCode.IDENTITY)
    return path_url, concat_url


def _parse_path_identity(body: bytes) -> tuple[str, str]:
    """Parse only the canonical domain declarations from ``szsePath.js``."""

    text = _strip_javascript_comments(_decode_identity_text(body))
    string_spans = _javascript_string_spans(text)

    def outside(pattern: re.Pattern[str]) -> tuple[re.Match[str], ...]:
        return tuple(
            match for match in pattern.finditer(text) if _match_outside_strings(match, string_spans)
        )

    main_assignments = outside(_PATH_MAIN_ASSIGNMENT_RE)
    main_any_assignments = outside(_PATH_MAIN_ANY_ASSIGNMENT_RE)
    static_assignments = outside(_PATH_STATIC_ASSIGNMENT_RE)
    static_any_assignments = outside(_PATH_STATIC_ANY_ASSIGNMENT_RE)
    if (
        len(main_assignments) != 1
        or len(main_any_assignments) != 1
        or len(static_assignments) != 1
        or len(static_any_assignments) != 1
    ):
        _fail(SzseFailureCode.IDENTITY)
    return f"https://{SZSE_CALENDAR_STATIC_HOST}", "/api/report"


def _parse_concatversion_identity(body: bytes, *, path_identity: tuple[str, str]) -> str:
    """Parse the live concatversion grammar and derive the final JS URL."""

    text = _strip_javascript_comments(_decode_identity_text(body))
    string_spans = _javascript_string_spans(text)

    def outside(pattern: re.Pattern[str]) -> tuple[re.Match[str], ...]:
        return tuple(
            match for match in pattern.finditer(text) if _match_outside_strings(match, string_spans)
        )

    domain_maps = outside(_CONCAT_DOMAIN_MAP_ASSIGNMENT_RE)
    path_objects = outside(_CONCAT_PATH_OBJECT_ASSIGNMENT_RE)
    if len(domain_maps) != 1 or len(path_objects) != 1:
        _fail(SzseFailureCode.IDENTITY)
    domain_opening = text.find("{", domain_maps[0].end())
    domain_body, _domain_closing = _balanced_javascript_block(text, domain_opening)
    domain_text = domain_body + "}"
    domain_spans = _javascript_string_spans(domain_text)
    mapping_keys = tuple(
        match
        for match in _CONCAT_DOMAIN_MAPPING_KEY_RE.finditer(domain_text)
        if _match_at_string_start(match, domain_spans)
    )
    mappings = tuple(
        match
        for match in _CONCAT_DOMAIN_MAPPING_RE.finditer(domain_text)
        if _match_at_string_start(match, domain_spans)
    )
    if len(mapping_keys) != 1 or len(mappings) != 1:
        _fail(SzseFailureCode.IDENTITY)
    object_opening = text.find("{", path_objects[0].end())
    object_body, _object_closing = _balanced_javascript_block(text, object_opening)
    object_text = object_body + "}"
    object_spans = _javascript_string_spans(object_text)
    file_properties = tuple(
        match
        for match in _CONCAT_HTTPS_FILE_PROPERTY_RE.finditer(object_text)
        if _match_outside_strings(match, object_spans)
    )
    file_property_names = tuple(
        match
        for match in re.finditer(r"\bhttps_file_path\s*:", object_text, re.ASCII)
        if _match_outside_strings(match, object_spans)
    )
    report_properties = tuple(
        match
        for match in _CONCAT_REPORT_PROPERTY_RE.finditer(object_text)
        if _match_outside_strings(match, object_spans)
    )
    report_property_names = tuple(
        match
        for match in re.finditer(r"\breport_path\s*:", object_text, re.ASCII)
        if _match_outside_strings(match, object_spans)
    )
    if (
        len(file_properties) != 1
        or len(file_property_names) != 1
        or len(report_properties) != 1
        or len(report_property_names) != 1
    ):
        _fail(SzseFailureCode.IDENTITY)

    functions = tuple(
        match
        for match in _CONCAT_FUNCTION_RE.finditer(text)
        if _match_outside_strings(match, string_spans)
    )
    if len(functions) != 1:
        _fail(SzseFailureCode.IDENTITY)
    function = functions[0]
    url_parameter = function.group("url")
    type_parameter = function.group("type")
    function_body = _change_version_function_body(text, function)
    assignments = outside(_VERSION_ASSIGNMENT_RE)
    any_assignments = outside(_VERSION_ANY_ASSIGNMENT_RE)
    dev_assignments = outside(_CONCAT_DEV_ASSIGNMENT_RE)
    dev_any_assignments = outside(_CONCAT_DEV_ANY_ASSIGNMENT_RE)
    if (
        len(assignments) != 1
        or assignments[0].group("version") != "1.2.221"
        or len(any_assignments) != 1
        or len(dev_assignments) != 1
        or len(dev_any_assignments) != 1
    ):
        _fail(SzseFailureCode.IDENTITY)

    function_string_spans = _javascript_string_spans(function_body)
    file_branches = tuple(
        match
        for match in _CONCAT_HTTPS_FILE_BRANCH_RE.finditer(function_body)
        if _match_outside_strings(match, function_string_spans)
    )
    nondev_ifs = tuple(
        match
        for match in _CONCAT_NONDEV_IF_RE.finditer(function_body)
        if _match_outside_strings(match, function_string_spans)
    )
    replace_matches = tuple(
        match
        for match in _CONCAT_GENERALIZED_RE.finditer(function_body)
        if _match_outside_strings(match, function_string_spans)
        and match.group("url") == url_parameter
        and match.group("type") == type_parameter
    )
    switches = tuple(
        match
        for match in _CONCAT_SWITCH_RE.finditer(function_body)
        if _match_outside_strings(match, function_string_spans)
        and match.group("type") == type_parameter
    )
    if len(file_branches) != 1 or len(nondev_ifs) != 1 or len(replace_matches) != 1:
        _fail(SzseFailureCode.IDENTITY)
    if len(switches) != 1:
        _fail(SzseFailureCode.IDENTITY)
    switch = switches[0]
    replace_match = replace_matches[0]
    nondev_opening = nondev_ifs[0].end() - 1
    _nondev_body, nondev_closing = _balanced_javascript_block(function_body, nondev_opening)
    if not (
        nondev_ifs[0].start() < replace_match.start() < nondev_closing
        and replace_match.end() < switch.start()
        and file_branches[0].start() < switch.start()
    ):
        _fail(SzseFailureCode.IDENTITY)

    switch_opening = function_body.find("{", switch.end())
    switch_body, _switch_closing = _balanced_javascript_block(function_body, switch_opening)
    switch_string_spans = _javascript_string_spans(switch_body)
    case_matches = tuple(
        match
        for match in _CONCAT_CASE_JS_RE.finditer(switch_body)
        if _match_outside_strings(match, switch_string_spans)
    )
    if len(case_matches) != 1:
        _fail(SzseFailureCode.IDENTITY)
    js_case = case_matches[0]
    js_case_body = switch_body[js_case.end() :]
    js_case_spans = _javascript_string_spans(js_case_body)
    jshref_assignments = tuple(
        match
        for match in re.finditer(r"\bvar\s+jshref\s*=", js_case_body, re.ASCII)
        if _match_outside_strings(match, js_case_spans)
    )
    jshref_writes = tuple(
        match
        for match in re.finditer(
            r"\bdocument\s*\.\s*write\s*\(\s*jshref\s*\)", js_case_body, re.ASCII
        )
        if _match_outside_strings(match, js_case_spans)
    )
    composition_pattern = re.compile(
        rf"\bfilePath\s*\+\s*{re.escape(url_parameter)}\s*\+\s*"
        r"(['\"])\?version=\1\s*\+\s*sjsVersion\b",
        re.ASCII,
    )
    compositions = tuple(
        match
        for match in composition_pattern.finditer(js_case_body)
        if _match_outside_strings(match, js_case_spans)
    )
    if len(jshref_assignments) != 1 or len(jshref_writes) != 1 or len(compositions) != 1:
        _fail(SzseFailureCode.IDENTITY)

    static_host, report_path = path_identity
    if static_host != f"https://{SZSE_CALENDAR_STATIC_HOST}" or report_path != "/api/report":
        _fail(SzseFailureCode.IDENTITY)
    version = assignments[0].group("version")
    derived_url = f"{static_host}{_FINAL_JS_PATH}?version={version}"
    if derived_url != SZSE_CALENDAR_JS_URL:
        _fail(SzseFailureCode.IDENTITY)
    return derived_url


def _parse_final_js_identity(body: bytes, *, report_path: str) -> None:
    """Parse only the scoped monthly endpoint composition in final JS."""

    text = _strip_javascript_comments(_decode_identity_text(body))
    string_spans = _javascript_string_spans(text)
    matches = tuple(
        match
        for match in _REPORT_ENDPOINT_RE.finditer(text)
        if _match_outside_strings(match, string_spans)
    )
    if report_path != "/api/report" or len(matches) != 1:
        _fail(SzseFailureCode.IDENTITY)


def _parse_identity(
    body: bytes,
    *,
    endpoint_kind: str,
    random_ms: int | None = None,
    path_identity: tuple[str, str] | None = None,
) -> tuple[str, str] | str | None:
    _verify_identity_source_pin(body, endpoint_kind)
    if endpoint_kind == "root":
        if random_ms is None:
            _fail(SzseFailureCode.IDENTITY)
        return _parse_root_identity(body, random_ms=random_ms)
    if endpoint_kind == "path":
        return _parse_path_identity(body)
    if endpoint_kind == "concat":
        if path_identity is None:
            _fail(SzseFailureCode.IDENTITY)
        return _parse_concatversion_identity(body, path_identity=path_identity)
    if endpoint_kind == "js":
        if path_identity is None:
            _fail(SzseFailureCode.IDENTITY)
        _parse_final_js_identity(body, report_path=path_identity[1])
        return None
    _fail(SzseFailureCode.IDENTITY)


def _raw_ref_payloads(references: tuple[SzseRawReference, ...]) -> tuple[dict[str, object], ...]:
    return tuple(_raw_ref_payload(reference) for reference in references)


def _catalog_manifest_payload(
    catalog: CalendarScanRunCatalogReceipt,
    reference: SzseRawReference,
    url: str,
) -> dict[str, object]:
    return {
        "run_id": str(catalog.run_id),
        "year": catalog.year,
        "month": catalog.month,
        "catalog_id": str(catalog.catalog_id),
        "resource_id": catalog.resource_id,
        "raw_evidence_id": str(catalog.raw_evidence_id),
        "raw_artifact_sha256": catalog.raw_artifact_sha256,
        "identity_verified": catalog.identity_verified,
        "replay_verified": catalog.replay_verified,
        "url": url,
        "raw_ref": _raw_ref_payload(reference),
    }


def _day_manifest_payload(day: CalendarScanRunDay) -> dict[str, object]:
    return {
        "date": day.date.isoformat(),
        "is_trading_day": day.is_trading_day,
    }


def _page_manifest_payload(
    page: CalendarScanRunPage,
    reference: SzseRawReference,
    state_ref: SzseRawReference,
) -> dict[str, object]:
    return {
        "run_id": str(page.run_id),
        "pass_number": page.pass_number,
        "pass_id": str(page.pass_id),
        "month": page.month,
        "year": page.year,
        "page_id": str(page.page_id),
        "catalog_id": str(page.catalog_id),
        "resource_id": page.resource_id,
        "raw_evidence_id": str(page.raw_evidence_id),
        "raw_artifact_sha256": page.raw_artifact_sha256,
        "canonical_payload_sha256": page.canonical_payload_sha256,
        "artifact_id": str(page.artifact_id),
        "capture_id": str(page.capture_id),
        "opened_at": page.opened_at.isoformat(),
        "observed_at": page.observed_at.isoformat(),
        "available_at": page.available_at.isoformat(),
        "source_nowdate": page.source_nowdate.isoformat(),
        "identity_verified": page.identity_verified,
        "replay_verified": page.replay_verified,
        "days": tuple(_day_manifest_payload(day) for day in page.days),
        "raw_ref": _raw_ref_payload(reference),
        "state_ref": _raw_ref_payload(state_ref),
    }


def _pass_manifest_payload(receipt: CalendarScanRunPassReceipt) -> dict[str, object]:
    return {
        "run_id": str(receipt.run_id),
        "pass_number": receipt.pass_number,
        "pass_id": str(receipt.pass_id),
        "opened_at": receipt.opened_at.isoformat(),
        "finished_at": receipt.finished_at.isoformat(),
        "page_refs": tuple(str(item) for item in receipt.page_refs),
        "member_digest": receipt.member_digest,
    }


def _parse_manifest_datetime(value: object) -> datetime:
    return _parse_iso_datetime(value)


def _manifest_payload(
    *,
    run_receipt: CalendarScanRunReceipt,
    identity_assets: tuple[SzseRawReference, ...],
    catalog_entries: tuple[dict[str, object], ...],
    pass_receipts: tuple[CalendarScanRunPassReceipt, ...],
    page_entries: tuple[dict[str, object], ...],
    attempts: tuple[SzseCaptureAttempt, ...],
    manifest_domain: Mapping[str, object],
) -> bytes:
    payload = {
        "version": SZSE_MANIFEST_VERSION,
        "run_id": str(run_receipt.run_id),
        "authority": run_receipt.authority,
        "exchange": run_receipt.exchange,
        "year": run_receipt.year,
        "parser_version": run_receipt.parser_version,
        "contract_version": run_receipt.contract_version,
        "policy_id": run_receipt.policy_id,
        "identity_policy": _identity_policy_payload(),
        "identity_policy_digest": _identity_policy_digest(),
        "compiled_catalog_sha256": run_receipt.compiled_catalog_sha256,
        "opened_at": run_receipt.opened_at.isoformat(),
        "cutoff_at": run_receipt.cutoff_at.isoformat(),
        "manifest_capture_id": _capture_id(run_receipt.run_id, "capture:manifest"),
        "identity_assets": _raw_ref_payloads(identity_assets),
        "catalogs": catalog_entries,
        "passes": tuple(_pass_manifest_payload(receipt) for receipt in pass_receipts),
        "pages": page_entries,
        "attempts": tuple(_attempt_payload(attempt) for attempt in attempts),
        "manifest_domain": manifest_domain,
    }
    return _canonical_json(payload)


def _map_collection_error(code: str) -> str:
    if code in {SzseFailureCode.TRANSPORT}:
        return _RESPONSE_ERROR
    if code in {SzseFailureCode.STATUS, SzseFailureCode.REDIRECT, SzseFailureCode.CONTENT_TYPE}:
        return _RESPONSE_ERROR
    if code in {SzseFailureCode.SIZE, SzseFailureCode.SCHEMA, SzseFailureCode.MONTH_DAYS}:
        return _DATA_ERROR
    if code == SzseFailureCode.IDENTITY:
        return _IDENTITY_ERROR
    if code == SzseFailureCode.NOWDATE:
        return _NOWDATE_ERROR
    if code == SzseFailureCode.UNSTABLE:
        return _UNSTABLE_ERROR
    if code == SzseFailureCode.RAW:
        return _RAW_ERROR
    return _INTEGRITY_ERROR


class SzseOfficialCalendarCollector:
    """Collect a fixed SZSE 2026 run without network or persistence side effects beyond raw."""

    def __init__(
        self,
        raw_storage: RawStorage,
        *,
        transport: OfficialSzseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        run_id: UUID | None = None,
        timeout_seconds: float = SZSE_TIMEOUT_SECONDS,
        max_bytes: int = SZSE_MAX_RESPONSE_BYTES,
    ) -> None:
        if type(timeout_seconds) is not float or not 0.0 < timeout_seconds <= 60.0:
            _raise(_RESPONSE_ERROR)
        if type(max_bytes) is not int or max_bytes < 1024 or max_bytes > 8 * 1024 * 1024:
            _raise(_RESPONSE_ERROR)
        if run_id is not None:
            try:
                _strict_uuid(run_id)
            except _CollectionFailureError:
                _raise(_INTEGRITY_ERROR)
        self._raw_storage = raw_storage
        self._transport = _UrllibSzseTransport() if transport is None else transport
        self._clock = (lambda: datetime.now(UTC)) if clock is None else clock
        self._run_id = uuid4() if run_id is None else run_id
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes
        self._attempts: list[SzseCaptureAttempt] = []
        self._last_evidence_at: datetime | None = None

    @property
    def attempts(self) -> tuple[SzseCaptureAttempt, ...]:
        """Return immutable state for the latest collection attempt."""

        return tuple(self._attempts)

    @property
    def run_id(self) -> UUID:
        return self._run_id

    def _next_time(self) -> datetime:
        observed_at = _observation_time(self._clock)
        if self._last_evidence_at is not None and observed_at < self._last_evidence_at:
            _fail(SzseFailureCode.UNSTABLE)
        self._last_evidence_at = observed_at
        return observed_at

    def _append_attempt(
        self,
        *,
        attempt_id: str,
        capture_id: str,
        endpoint_kind: str,
        pass_number: int | None,
        month: int | None,
        status_code: int | None,
        error_code: str | None,
        raw_ref: SzseRawReference | None,
        observed_at: datetime,
        available_at: datetime,
        replay_allowed: bool,
    ) -> SzseCaptureAttempt:
        attempt = SzseCaptureAttempt(
            attempt_id=attempt_id,
            capture_id=capture_id,
            endpoint_kind=endpoint_kind,
            pass_number=pass_number,
            month=month,
            status_code=status_code,
            error_code=error_code,
            raw_ref=raw_ref,
            state_ref=None,
            observed_at=observed_at,
            available_at=available_at,
            replay_allowed=replay_allowed,
        )
        stateful = _store_attempt_state(self._raw_storage, self._run_id, attempt)
        self._attempts.append(stateful)
        return stateful

    def _marker_failure(
        self,
        *,
        endpoint_kind: str,
        label: str,
        pass_number: int | None,
        month: int | None,
        code: str,
        at: datetime,
        status_code: int | None = None,
    ) -> NoReturn:
        attempt_id = _capture_id(self._run_id, f"attempt:{label}")
        capture_id = _capture_id(self._run_id, f"capture:{label}")
        raw_ref: SzseRawReference | None = None
        try:
            raw_ref, _ = _store_raw(
                self._raw_storage,
                source=SZSE_CALENDAR_SOURCE,
                capture_id=capture_id,
                route=_attempt_route(attempt_id),
                content=_attempt_marker_bytes(self._run_id, attempt_id, code),
                content_type="application/json",
                observed_at=at,
                kind=endpoint_kind,
            )
        except _CollectionFailureError:
            raw_ref = None
        try:
            self._append_attempt(
                attempt_id=attempt_id,
                capture_id=capture_id,
                endpoint_kind=endpoint_kind,
                pass_number=pass_number,
                month=month,
                status_code=status_code,
                error_code=code,
                raw_ref=raw_ref,
                observed_at=at,
                available_at=at,
                replay_allowed=False,
            )
        except _CollectionFailureError:
            # The in-memory state is still represented if the state store is unavailable.
            self._attempts.append(
                SzseCaptureAttempt(
                    attempt_id=attempt_id,
                    capture_id=capture_id,
                    endpoint_kind=endpoint_kind,
                    pass_number=pass_number,
                    month=month,
                    status_code=status_code,
                    error_code=code,
                    raw_ref=raw_ref,
                    state_ref=None,
                    observed_at=at,
                    available_at=at,
                    replay_allowed=False,
                )
            )
        _fail(code)

    def _capture_response(
        self,
        *,
        endpoint_kind: str,
        url: str,
        label: str,
        pass_number: int | None,
        month: int | None,
        expected_types: frozenset[str],
        run_opened: datetime,
    ) -> _Captured:
        capture_id = _capture_id(self._run_id, f"capture:{label}")
        attempt_id = _capture_id(self._run_id, f"attempt:{label}")
        response, transport_failed = _safe_call(
            lambda: self._transport.fetch(
                url,
                timeout_seconds=self._timeout_seconds,
                max_bytes=self._max_bytes,
            )
        )
        try:
            observed_at = self._next_time()
        except _CollectionFailureError as failure:
            observed_at = self._last_evidence_at or run_opened
            self._marker_failure(
                endpoint_kind=endpoint_kind,
                label=label,
                pass_number=pass_number,
                month=month,
                code=failure.code,
                at=observed_at,
            )
        except OfficialSzseCalendarError:
            observed_at = self._last_evidence_at or run_opened
            self._marker_failure(
                endpoint_kind=endpoint_kind,
                label=label,
                pass_number=pass_number,
                month=month,
                code=SzseFailureCode.INTEGRITY,
                at=observed_at,
            )
        if transport_failed or type(response) is not OfficialSzseResponse:
            self._marker_failure(
                endpoint_kind=endpoint_kind,
                label=label,
                pass_number=pass_number,
                month=month,
                code=SzseFailureCode.TRANSPORT,
                at=observed_at,
            )
        try:
            status_code = response.status_code
            content_type = response.content_type
            body = response.body
            redirected = response.redirected
        except Exception:
            self._marker_failure(
                endpoint_kind=endpoint_kind,
                label=label,
                pass_number=pass_number,
                month=month,
                code=SzseFailureCode.SCHEMA,
                at=observed_at,
            )
        if (
            type(status_code) is not int
            or type(content_type) is not str
            or type(body) is not bytes
            or type(redirected) is not bool
        ):
            self._marker_failure(
                endpoint_kind=endpoint_kind,
                label=label,
                pass_number=pass_number,
                month=month,
                code=SzseFailureCode.SCHEMA,
                at=observed_at,
                status_code=status_code if type(status_code) is int else None,
            )
        if len(body) > self._max_bytes:
            self._marker_failure(
                endpoint_kind=endpoint_kind,
                label=label,
                pass_number=pass_number,
                month=month,
                code=SzseFailureCode.SIZE,
                at=observed_at,
                status_code=status_code,
            )
        normalized_content_type = _canonical_content_type(content_type)
        store_type = normalized_content_type or "application/octet-stream"
        try:
            reference, replayed = _store_raw(
                self._raw_storage,
                source=SZSE_CALENDAR_SOURCE,
                capture_id=capture_id,
                route=f"GET {url}",
                content=body,
                content_type=store_type,
                observed_at=observed_at,
                kind=endpoint_kind,
            )
        except _CollectionFailureError as failure:
            with suppress(_CollectionFailureError):
                self._append_attempt(
                    attempt_id=attempt_id,
                    capture_id=capture_id,
                    endpoint_kind=endpoint_kind,
                    pass_number=pass_number,
                    month=month,
                    status_code=status_code,
                    error_code=failure.args[0] if failure.args else SzseFailureCode.RAW,
                    raw_ref=None,
                    observed_at=observed_at,
                    available_at=observed_at,
                    replay_allowed=False,
                )
            raise
        if redirected:
            self._finish(
                attempt_id=attempt_id,
                capture_id=capture_id,
                endpoint_kind=endpoint_kind,
                pass_number=pass_number,
                month=month,
                status_code=status_code,
                reference=reference,
                error_code=SzseFailureCode.REDIRECT,
            )
            _fail(SzseFailureCode.REDIRECT)
        if status_code != 200:
            self._finish(
                attempt_id=attempt_id,
                capture_id=capture_id,
                endpoint_kind=endpoint_kind,
                pass_number=pass_number,
                month=month,
                status_code=status_code,
                reference=reference,
                error_code=SzseFailureCode.STATUS,
            )
            _fail(SzseFailureCode.STATUS)
        if (
            normalized_content_type is None
            or normalized_content_type.split(";", 1)[0] not in expected_types
        ):
            self._finish(
                attempt_id=attempt_id,
                capture_id=capture_id,
                endpoint_kind=endpoint_kind,
                pass_number=pass_number,
                month=month,
                status_code=status_code,
                reference=reference,
                error_code=SzseFailureCode.CONTENT_TYPE,
            )
            _fail(SzseFailureCode.CONTENT_TYPE)
        if replayed != body:
            _fail(SzseFailureCode.INTEGRITY)
        return _Captured(
            attempt_id=attempt_id,
            capture_id=capture_id,
            endpoint_kind=endpoint_kind,
            pass_number=pass_number,
            month=month,
            status_code=status_code,
            content_type=normalized_content_type,
            redirected=redirected,
            reference=reference,
            body=replayed,
        )

    def _capture_bytes(
        self,
        *,
        endpoint_kind: str,
        label: str,
        source: str,
        route: str,
        content: bytes,
        content_type: str,
        at: datetime,
        pass_number: int | None = None,
        month: int | None = None,
    ) -> _Captured:
        capture_id = _capture_id(self._run_id, f"capture:{label}")
        attempt_id = _capture_id(self._run_id, f"attempt:{label}")
        reference, replayed = _store_raw(
            self._raw_storage,
            source=source,
            capture_id=capture_id,
            route=route,
            content=content,
            content_type=content_type,
            observed_at=at,
            kind=endpoint_kind,
        )
        return _Captured(
            attempt_id=attempt_id,
            capture_id=capture_id,
            endpoint_kind=endpoint_kind,
            pass_number=pass_number,
            month=month,
            status_code=200,
            content_type=content_type,
            redirected=False,
            reference=reference,
            body=replayed,
        )

    def _finish(
        self,
        *,
        attempt_id: str,
        capture_id: str,
        endpoint_kind: str,
        pass_number: int | None,
        month: int | None,
        status_code: int | None,
        reference: SzseRawReference,
        error_code: str | None,
    ) -> SzseCaptureAttempt:
        return self._append_attempt(
            attempt_id=attempt_id,
            capture_id=capture_id,
            endpoint_kind=endpoint_kind,
            pass_number=pass_number,
            month=month,
            status_code=status_code,
            error_code=error_code,
            raw_ref=reference,
            observed_at=reference.observed_at,
            available_at=reference.available_at,
            replay_allowed=error_code is None,
        )

    def _success(self, captured: _Captured) -> SzseCaptureAttempt:
        return self._finish(
            attempt_id=captured.attempt_id,
            capture_id=captured.capture_id,
            endpoint_kind=captured.endpoint_kind,
            pass_number=captured.pass_number,
            month=captured.month,
            status_code=captured.status_code,
            reference=captured.reference,
            error_code=None,
        )

    def collect(self, exchange: str = "SZ", year: int = _SUPPORTED_YEAR) -> SzseOfficialDailyResult:
        """Capture identity assets and two fixed monthly passes, then build a domain proof."""

        _validate_scope(exchange, year)
        self._attempts = []
        self._last_evidence_at = None
        existing_final = _load_ledger_state(self._raw_storage, run_id=self._run_id)
        if existing_final is not None:
            try:
                replayed = _replay_szse_daily_run_core(
                    self._raw_storage,
                    run_id=self._run_id,
                    manifest_date=cast(str, existing_final.get("manifest_date")),
                    manifest_capture_id=cast(str, existing_final.get("manifest_capture_id")),
                )
            except OfficialSzseCalendarError:
                raise
            except Exception:
                _raise(_LEDGER_ERROR)
            if replayed.proof.proof_digest != existing_final.get("proof_digest"):
                _raise(_LEDGER_ERROR)
            self._attempts = list(replayed.attempts)
            return replayed
        try:
            run_opened = self._next_time()
            claim_nonce = uuid4().hex
            _store_ledger_entry(
                self._raw_storage,
                run_id=self._run_id,
                kind="claim",
                content=_ledger_payload(run_id=self._run_id, kind="claim", claim_nonce=claim_nonce),
                at=run_opened,
            )
            identity_assets: list[SzseRawReference] = []
            root = self._capture_response(
                endpoint_kind="root",
                url=SZSE_CALENDAR_ROOT_URL,
                label="root",
                pass_number=None,
                month=None,
                expected_types=_HTML_TYPES,
                run_opened=run_opened,
            )
            try:
                random_ms = _identity_random_ms(root.reference.observed_at)
                path_url, concat_url = cast(
                    tuple[str, str],
                    _parse_identity(root.body, endpoint_kind="root", random_ms=random_ms),
                )
            except _CollectionFailureError:
                self._finish(
                    attempt_id=root.attempt_id,
                    capture_id=root.capture_id,
                    endpoint_kind=root.endpoint_kind,
                    pass_number=None,
                    month=None,
                    status_code=root.status_code,
                    reference=root.reference,
                    error_code=SzseFailureCode.IDENTITY,
                )
                raise
            self._success(root)
            identity_assets.append(root.reference)

            path = self._capture_response(
                endpoint_kind="path",
                url=path_url,
                label="path",
                pass_number=None,
                month=None,
                expected_types=_JS_TYPES,
                run_opened=run_opened,
            )
            try:
                path_identity = cast(
                    tuple[str, str], _parse_identity(path.body, endpoint_kind="path")
                )
            except _CollectionFailureError:
                self._finish(
                    attempt_id=path.attempt_id,
                    capture_id=path.capture_id,
                    endpoint_kind=path.endpoint_kind,
                    pass_number=None,
                    month=None,
                    status_code=path.status_code,
                    reference=path.reference,
                    error_code=SzseFailureCode.IDENTITY,
                )
                raise
            self._success(path)
            identity_assets.append(path.reference)

            concat = self._capture_response(
                endpoint_kind="concat",
                url=concat_url,
                label="concat",
                pass_number=None,
                month=None,
                expected_types=_JS_TYPES,
                run_opened=run_opened,
            )
            try:
                derived_js_url = cast(
                    str,
                    _parse_identity(
                        concat.body,
                        endpoint_kind="concat",
                        path_identity=path_identity,
                    ),
                )
            except _CollectionFailureError:
                self._finish(
                    attempt_id=concat.attempt_id,
                    capture_id=concat.capture_id,
                    endpoint_kind=concat.endpoint_kind,
                    pass_number=None,
                    month=None,
                    status_code=concat.status_code,
                    reference=concat.reference,
                    error_code=SzseFailureCode.IDENTITY,
                )
                raise
            self._success(concat)
            identity_assets.append(concat.reference)

            js = self._capture_response(
                endpoint_kind="js",
                url=derived_js_url,
                label="js",
                pass_number=None,
                month=None,
                expected_types=_JS_TYPES,
                run_opened=run_opened,
            )
            try:
                _parse_identity(js.body, endpoint_kind="js", path_identity=path_identity)
            except _CollectionFailureError:
                self._finish(
                    attempt_id=js.attempt_id,
                    capture_id=js.capture_id,
                    endpoint_kind=js.endpoint_kind,
                    pass_number=None,
                    month=None,
                    status_code=js.status_code,
                    reference=js.reference,
                    error_code=SzseFailureCode.IDENTITY,
                )
                raise
            self._success(js)
            identity_assets.append(js.reference)

            catalogs: list[CalendarScanRunCatalogReceipt] = []
            catalog_refs: list[SzseRawReference] = []
            catalog_urls: list[str] = []
            for month in range(1, 13):
                url = szse_direct_daily_url(year, month)
                try:
                    at = self._next_time()
                except _CollectionFailureError as failure:
                    self._marker_failure(
                        endpoint_kind="catalog",
                        label=f"catalog:{month}",
                        pass_number=None,
                        month=month,
                        code=failure.code,
                        at=self._last_evidence_at or run_opened,
                    )
                catalog_body = _canonical_json(
                    {
                        "version": SZSE_CATALOG_VERSION,
                        "authority": "SZSE",
                        "exchange": "SZ",
                        "year": year,
                        "month": month,
                        "resource_id": calendar_scan_run_resource_id(year, month),
                        "url": url,
                    }
                )
                captured = self._capture_bytes(
                    endpoint_kind="catalog",
                    label=f"catalog:{month}",
                    source=SZSE_CATALOG_SOURCE,
                    route=_catalog_route(year, month),
                    content=catalog_body,
                    content_type="application/json",
                    at=at,
                    month=month,
                )
                catalog_refs.append(captured.reference)
                catalog_urls.append(url)
                catalogs.append(
                    CalendarScanRunCatalogReceipt(
                        run_id=self._run_id,
                        year=year,
                        month=month,
                        catalog_id=_domain_id(self._run_id, f"catalog:{month}"),
                        resource_id=calendar_scan_run_resource_id(year, month),
                        raw_evidence_id=_domain_id(self._run_id, f"catalog-evidence:{month}"),
                        raw_artifact_sha256=captured.reference.checksum,
                        identity_verified=True,
                        replay_verified=True,
                    )
                )
            catalog_values = tuple(catalogs)
            catalog_digest = calendar_scan_run_catalog_digest(catalog_values)

            pages: list[CalendarScanRunPage] = []
            page_refs: list[SzseRawReference] = []
            page_state_refs: list[SzseRawReference] = []
            source_dates: set[date] = set()
            for pass_number in (1, 2):
                for month in range(1, 13):
                    url = szse_direct_daily_url(year, month)
                    captured = self._capture_response(
                        endpoint_kind="page",
                        url=url,
                        label=f"page:{pass_number}:{month}",
                        pass_number=pass_number,
                        month=month,
                        expected_types=_JSON_TYPES,
                        run_opened=run_opened,
                    )
                    try:
                        source_nowdate, days = _parse_month_body(
                            captured.body,
                            year=year,
                            month=month,
                        )
                    except _CollectionFailureError as failure:
                        code = failure.args[0] if failure.args else SzseFailureCode.SCHEMA
                        self._finish(
                            attempt_id=captured.attempt_id,
                            capture_id=captured.capture_id,
                            endpoint_kind=captured.endpoint_kind,
                            pass_number=pass_number,
                            month=month,
                            status_code=captured.status_code,
                            reference=captured.reference,
                            error_code=code,
                        )
                        raise
                    observed_local_date = captured.reference.observed_at.astimezone(
                        _SHANGHAI_TZ
                    ).date()
                    if source_nowdate != observed_local_date:
                        self._finish(
                            attempt_id=captured.attempt_id,
                            capture_id=captured.capture_id,
                            endpoint_kind=captured.endpoint_kind,
                            pass_number=pass_number,
                            month=month,
                            status_code=captured.status_code,
                            reference=captured.reference,
                            error_code=SzseFailureCode.NOWDATE,
                        )
                        _fail(SzseFailureCode.NOWDATE)
                    source_dates.add(source_nowdate)
                    stateful = self._success(captured)
                    if stateful.state_ref is None:
                        _fail(SzseFailureCode.RAW)
                    catalog = catalog_values[month - 1]
                    page = CalendarScanRunPage(
                        run_id=self._run_id,
                        pass_number=pass_number,
                        pass_id=calendar_scan_run_pass_id(self._run_id, pass_number),
                        month=month,
                        year=year,
                        page_id=_domain_id(self._run_id, f"page:{pass_number}:{month}"),
                        catalog_id=catalog.catalog_id,
                        resource_id=catalog.resource_id,
                        raw_evidence_id=_domain_id(
                            self._run_id, f"page-evidence:{pass_number}:{month}"
                        ),
                        raw_artifact_sha256=captured.reference.checksum,
                        canonical_payload_sha256=calendar_scan_run_payload_digest(days),
                        artifact_id=_domain_id(
                            self._run_id, f"page-artifact:{pass_number}:{month}"
                        ),
                        capture_id=_domain_id(self._run_id, f"page-capture:{pass_number}:{month}"),
                        opened_at=run_opened,
                        observed_at=captured.reference.observed_at,
                        available_at=captured.reference.available_at,
                        source_nowdate=source_nowdate,
                        identity_verified=True,
                        replay_verified=True,
                        days=days,
                    )
                    pages.append(page)
                    page_refs.append(captured.reference)
                    page_state_refs.append(stateful.state_ref)
            if len(source_dates) != 1:
                self._marker_failure(
                    endpoint_kind="run",
                    label="unstable-nowdate",
                    pass_number=None,
                    month=None,
                    code=SzseFailureCode.NOWDATE,
                    at=pages[-1].available_at,
                )
            page_values = tuple(pages)
            pass_values = (
                CalendarScanRunPassReceipt(
                    run_id=self._run_id,
                    pass_number=1,
                    pass_id=calendar_scan_run_pass_id(self._run_id, 1),
                    opened_at=run_opened,
                    finished_at=max(page.available_at for page in page_values[:12])
                    + timedelta(microseconds=1),
                    page_refs=tuple(page.page_id for page in page_values[:12]),
                    member_digest=calendar_scan_run_pass_member_digest(page_values[:12]),
                ),
                CalendarScanRunPassReceipt(
                    run_id=self._run_id,
                    pass_number=2,
                    pass_id=calendar_scan_run_pass_id(self._run_id, 2),
                    opened_at=page_values[12].observed_at,
                    finished_at=max(page.available_at for page in page_values[12:])
                    + timedelta(microseconds=1),
                    page_refs=tuple(page.page_id for page in page_values[12:]),
                    member_digest=calendar_scan_run_pass_member_digest(page_values[12:]),
                ),
            )
            if not pass_values[0].finished_at < pass_values[1].opened_at:
                self._marker_failure(
                    endpoint_kind="run",
                    label="pass-window",
                    pass_number=None,
                    month=None,
                    code=SzseFailureCode.UNSTABLE,
                    at=max(page.available_at for page in page_values),
                )
            try:
                cutoff_at = self._next_time()
            except _CollectionFailureError as failure:
                self._marker_failure(
                    endpoint_kind="run",
                    label="cutoff-window",
                    pass_number=None,
                    month=None,
                    code=failure.code,
                    at=self._last_evidence_at or run_opened,
                )
            if cutoff_at < pass_values[1].finished_at:
                self._marker_failure(
                    endpoint_kind="run",
                    label="cutoff-window",
                    pass_number=None,
                    month=None,
                    code=SzseFailureCode.UNSTABLE,
                    at=pass_values[1].finished_at,
                )
            manifest_domain = _manifest_domain(
                self._run_id,
                canonical_member_digest=calendar_scan_run_manifest_member_digest(
                    catalog_values, pass_values, page_values
                ),
                finalized_at=cutoff_at,
            )
            catalog_entries = tuple(
                _catalog_manifest_payload(catalog, reference, url)
                for catalog, reference, url in zip(
                    catalog_values, catalog_refs, catalog_urls, strict=True
                )
            )
            page_entries = tuple(
                _page_manifest_payload(page, reference, state_ref)
                for page, reference, state_ref in zip(
                    page_values, page_refs, page_state_refs, strict=True
                )
            )
            # The manifest itself is deliberately not included in this list of
            # response attempts; it is the immutable run-manifest anchor.
            manifest_body = _manifest_payload(
                run_receipt=CalendarScanRunReceipt(
                    run_id=self._run_id,
                    authority="SZSE",
                    exchange="SZ",
                    year=year,
                    parser_version=SZSE_PARSER_VERSION,
                    contract_version=SZSE_CONTRACT_VERSION,
                    policy_id=SZSE_DIRECT_DAILY_POLICY_ID,
                    compiled_catalog_sha256=catalog_digest,
                    opened_at=run_opened,
                    cutoff_at=cutoff_at,
                    catalog_receipts=catalog_values,
                    pass_receipts=pass_values,
                    pages=page_values,
                    manifest=CalendarScanRunManifestReceipt(
                        run_id=self._run_id,
                        raw_evidence_id=UUID(manifest_domain["raw_evidence_id"]),
                        artifact_id=UUID(manifest_domain["artifact_id"]),
                        capture_id=UUID(manifest_domain["capture_id"]),
                        raw_artifact_sha256="0" * 64,
                        canonical_member_digest=manifest_domain["canonical_member_digest"],
                        finalized_at=cutoff_at,
                    ),
                ),
                identity_assets=tuple(identity_assets),
                catalog_entries=catalog_entries,
                pass_receipts=pass_values,
                page_entries=page_entries,
                attempts=tuple(self._attempts),
                manifest_domain=manifest_domain,
            )
            # Constructing the temporary receipt above only computes canonical
            # member/proof inputs; the raw manifest checksum is bound below.
            manifest_capture_id = _capture_id(self._run_id, "capture:manifest")
            manifest_captured = self._capture_bytes(
                endpoint_kind="manifest",
                label="manifest",
                source=SZSE_MANIFEST_SOURCE,
                route=_manifest_route(),
                content=manifest_body,
                content_type="application/json",
                at=cutoff_at,
            )
            if manifest_captured.capture_id != manifest_capture_id:
                _fail(SzseFailureCode.INTEGRITY)
            manifest = CalendarScanRunManifestReceipt(
                run_id=self._run_id,
                raw_evidence_id=UUID(manifest_domain["raw_evidence_id"]),
                artifact_id=UUID(manifest_domain["artifact_id"]),
                capture_id=UUID(manifest_domain["capture_id"]),
                raw_artifact_sha256=manifest_captured.reference.checksum,
                canonical_member_digest=manifest_domain["canonical_member_digest"],
                finalized_at=cutoff_at,
            )
            ordered_evidence: list[SzseRawReference] = []
            for attempt in self._attempts[: len(_IDENTITY_KINDS)]:
                if attempt.raw_ref is None or attempt.state_ref is None:
                    _fail(SzseFailureCode.INTEGRITY)
                ordered_evidence.extend((attempt.raw_ref, attempt.state_ref))
            ordered_evidence.extend(catalog_refs)
            for attempt in self._attempts[len(_IDENTITY_KINDS) :]:
                if attempt.raw_ref is None or attempt.state_ref is None:
                    _fail(SzseFailureCode.INTEGRITY)
                ordered_evidence.extend((attempt.raw_ref, attempt.state_ref))
            ordered_evidence.append(manifest_captured.reference)
            _validate_evidence_timeline(
                tuple(ordered_evidence),
                opened_at=run_opened,
                cutoff_at=cutoff_at,
            )
            proof = CalendarScanRunReceipt(
                run_id=self._run_id,
                authority="SZSE",
                exchange="SZ",
                year=year,
                parser_version=SZSE_PARSER_VERSION,
                contract_version=SZSE_CONTRACT_VERSION,
                policy_id=SZSE_DIRECT_DAILY_POLICY_ID,
                compiled_catalog_sha256=catalog_digest,
                opened_at=run_opened,
                cutoff_at=cutoff_at,
                catalog_receipts=catalog_values,
                pass_receipts=pass_values,
                pages=page_values,
                manifest=manifest,
            )
            # The manifest payload cannot include its own checksum without a
            # circular rewrite; replay derives it from the stored manifest.
            result = SzseOfficialDailyResult(
                exchange="SZ",
                year=year,
                run_id=self._run_id,
                proof=proof,
                raw_manifest_ref=manifest_captured.reference,
                identity_assets=tuple(identity_assets),
                catalog_refs=tuple(catalog_refs),
                attempts=tuple(self._attempts),
            )
            _store_ledger_entry(
                self._raw_storage,
                run_id=self._run_id,
                kind="final",
                content=_ledger_payload(
                    run_id=self._run_id,
                    kind="final",
                    claim_nonce=claim_nonce,
                    manifest_date=result.raw_manifest_ref.raw_date,
                    manifest_capture_id=result.raw_manifest_ref.capture_id,
                    proof_digest=result.proof.proof_digest,
                ),
                at=cutoff_at,
            )
            return result
        except _CollectionFailureError as failure:
            code = failure.args[0] if failure.args else SzseFailureCode.INTEGRITY
            error_message = _map_collection_error(code)
        except OfficialSzseCalendarError:
            raise
        except Exception:
            error_message = _INTEGRITY_ERROR
        _raise(error_message)


def _manifest_for_replay(
    raw_storage: RawStorage,
    *,
    run_id: UUID,
    manifest_date: str,
    manifest_capture_id: str,
) -> tuple[RawObjectManifest, bytes]:
    _strict_uuid(run_id)
    try:
        validate_date_identifier(manifest_date)
        validate_identifier(manifest_capture_id, "capture_id", max_length=48)
    except Exception:
        _raise(_REPLAY_ERROR)
    manifests, failed = _safe_call(lambda: raw_storage.list(SZSE_MANIFEST_SOURCE, manifest_date))
    if failed or type(manifests) is not list:
        _raise(_REPLAY_ERROR)
    matches = [
        item
        for item in manifests
        if type(item) is RawObjectManifest and item.capture_id == manifest_capture_id
    ]
    if len(matches) != 1:
        _raise(_REPLAY_ERROR)
    manifest = matches[0]
    if (
        manifest.source != SZSE_MANIFEST_SOURCE
        or manifest.date != manifest_date
        or manifest.request != _route_request_identity(_manifest_route())
    ):
        _raise(_REPLAY_ERROR)
    content, get_failed = _safe_call(
        lambda: raw_storage.get(manifest.object_id, checksum=manifest.checksum, size=manifest.size)
    )
    if (
        get_failed
        or type(content) is not bytes
        or len(content) != manifest.size
        or hashlib.sha256(content).hexdigest() != manifest.checksum
    ):
        _raise(_REPLAY_ERROR)
    return manifest, content


def _replay_attempts(
    raw_storage: RawStorage,
    *,
    run_id: UUID,
    payload: Mapping[str, object],
) -> tuple[SzseCaptureAttempt, ...]:
    values = payload.get("attempts")
    if type(values) is not list:
        _raise(_REPLAY_ERROR)
    attempt_values = cast(list[object], values)
    if not attempt_values or type(attempt_values[0]) is not dict:
        _raise(_REPLAY_ERROR)
    first_attempt = cast(dict[str, object], attempt_values[0])
    first_raw_ref_value = first_attempt.get("raw_ref")
    if first_raw_ref_value is None:
        _raise(_REPLAY_ERROR)
    first_raw_ref = _parse_raw_ref(first_raw_ref_value, expected_kind="root")
    if first_raw_ref.capture_id != _capture_id(run_id, "capture:root"):
        _raise(_REPLAY_ERROR)
    path_url, concat_url = _identity_urls(_identity_random_ms(first_raw_ref.observed_at))
    attempts: list[SzseCaptureAttempt] = []
    for raw_attempt_value in attempt_values:
        if type(raw_attempt_value) is not dict:
            _raise(_REPLAY_ERROR)
        raw_attempt = cast(dict[str, object], raw_attempt_value)
        allowed = {
            "attempt_id",
            "capture_id",
            "endpoint_kind",
            "pass_number",
            "month",
            "status_code",
            "error_code",
            "raw_ref",
            "state_ref",
            "observed_at",
            "available_at",
            "replay_allowed",
        }
        if set(raw_attempt) != allowed:
            _raise(_REPLAY_ERROR)
        raw_ref_value = raw_attempt.get("raw_ref")
        state_ref_value = raw_attempt.get("state_ref")
        raw_ref = None if raw_ref_value is None else _parse_raw_ref(raw_ref_value)
        state_ref = (
            None
            if state_ref_value is None
            else _parse_raw_ref(state_ref_value, expected_kind="run")
        )
        if raw_ref is not None:
            if raw_ref.kind == "root":
                expected_route = f"GET {SZSE_CALENDAR_ROOT_URL}"
            elif raw_ref.kind == "path":
                expected_route = f"GET {path_url}"
            elif raw_ref.kind == "concat":
                expected_route = f"GET {concat_url}"
            elif raw_ref.kind == "js":
                expected_route = f"GET {SZSE_CALENDAR_JS_URL}"
            elif raw_ref.kind == "page":
                raw_pass = raw_attempt.get("pass_number")
                raw_month = raw_attempt.get("month")
                if type(raw_pass) is not int or type(raw_month) is not int:
                    _raise(_REPLAY_ERROR)
                expected_route = f"GET {szse_direct_daily_url(2026, raw_month)}"
            else:
                _raise(_REPLAY_ERROR)
            _load_raw_reference(
                raw_storage,
                raw_ref,
                source=SZSE_CALENDAR_SOURCE,
                expected_route=expected_route,
            )
        if state_ref is None:
            _raise(_REPLAY_ERROR)
        state_content = _load_raw_reference(
            raw_storage,
            state_ref,
            source=SZSE_CAPTURE_STATE_SOURCE,
            expected_route=_state_route(cast(str, raw_attempt.get("attempt_id"))),
        )
        state_payload = _parse_json_object(state_content)
        if state_payload.get("version") != SZSE_CAPTURE_STATE_VERSION:
            _raise(_REPLAY_ERROR)
        expected_state = dict(state_payload)
        expected_state.pop("version", None)
        actual_state = {
            key: raw_attempt.get(key)
            for key in (
                "attempt_id",
                "capture_id",
                "endpoint_kind",
                "pass_number",
                "month",
                "status_code",
                "error_code",
                "raw_ref",
                "observed_at",
                "available_at",
                "replay_allowed",
            )
        }
        if expected_state != actual_state or raw_attempt.get("replay_allowed") is not True:
            _raise(_REPLAY_ERROR)
        observed_at = _parse_iso_datetime(raw_attempt.get("observed_at"))
        available_at = _parse_iso_datetime(raw_attempt.get("available_at"))
        if (
            raw_ref is None
            or raw_ref.observed_at != observed_at
            or raw_ref.available_at != available_at
        ):
            _raise(_REPLAY_ERROR)
        if state_ref.observed_at != available_at or state_ref.available_at != available_at:
            _raise(_REPLAY_ERROR)
        attempts.append(
            SzseCaptureAttempt(
                attempt_id=cast(str, raw_attempt.get("attempt_id")),
                capture_id=cast(str, raw_attempt.get("capture_id")),
                endpoint_kind=cast(str, raw_attempt.get("endpoint_kind")),
                pass_number=cast(int | None, raw_attempt.get("pass_number")),
                month=cast(int | None, raw_attempt.get("month")),
                status_code=cast(int | None, raw_attempt.get("status_code")),
                error_code=cast(str | None, raw_attempt.get("error_code")),
                raw_ref=raw_ref,
                state_ref=state_ref,
                observed_at=observed_at,
                available_at=available_at,
                replay_allowed=True,
            )
        )
    values = tuple(attempts)
    expected = _expected_response_attempts(run_id)
    if len(values) != len(expected):
        _raise(_REPLAY_ERROR)
    for attempt, (attempt_id, capture_id, endpoint_kind, pass_number, month) in zip(
        values, expected, strict=True
    ):
        if (
            attempt.attempt_id != attempt_id
            or attempt.capture_id != capture_id
            or attempt.endpoint_kind != endpoint_kind
            or attempt.pass_number != pass_number
            or attempt.month != month
            or attempt.status_code != 200
            or attempt.error_code is not None
            or not attempt.replay_allowed
            or attempt.raw_ref is None
            or attempt.raw_ref.kind != endpoint_kind
            or attempt.raw_ref.capture_id != capture_id
            or attempt.state_ref is None
            or attempt.state_ref.capture_id != _state_capture_id(run_id, attempt_id)
        ):
            _raise(_REPLAY_ERROR)
    return values


def _validate_manifest_payload(
    payload: dict[str, object],
    *,
    run_id: UUID,
    manifest_storage: RawObjectManifest,
) -> None:
    required = {
        "version",
        "run_id",
        "authority",
        "exchange",
        "year",
        "parser_version",
        "contract_version",
        "policy_id",
        "identity_policy",
        "identity_policy_digest",
        "compiled_catalog_sha256",
        "opened_at",
        "cutoff_at",
        "manifest_capture_id",
        "identity_assets",
        "catalogs",
        "passes",
        "pages",
        "attempts",
        "manifest_domain",
    }
    if set(payload) != required or payload.get("version") != SZSE_MANIFEST_VERSION:
        _fail(SzseFailureCode.INTEGRITY)
    expected_capture_id = _capture_id(run_id, "capture:manifest")
    if (
        payload.get("run_id") != str(run_id)
        or payload.get("authority") != "SZSE"
        or payload.get("exchange") != "SZ"
        or payload.get("year") != 2026
        or payload.get("parser_version") != SZSE_PARSER_VERSION
        or payload.get("contract_version") != SZSE_CONTRACT_VERSION
        or payload.get("policy_id") != SZSE_DIRECT_DAILY_POLICY_ID
        or payload.get("identity_policy") != _identity_policy_payload()
        or payload.get("identity_policy_digest") != _identity_policy_digest()
        or payload.get("manifest_capture_id") != expected_capture_id
        or manifest_storage.capture_id != expected_capture_id
        or manifest_storage.content_type != "application/json"
    ):
        _fail(SzseFailureCode.INTEGRITY)


def _replay_identity_assets(
    raw_storage: RawStorage,
    *,
    run_id: UUID,
    payload: Mapping[str, object],
) -> tuple[SzseRawReference, ...]:
    values = payload.get("identity_assets")
    if type(values) is not list:
        _fail(SzseFailureCode.INTEGRITY)
    identity_values = cast(list[object], values)
    if len(identity_values) != len(_IDENTITY_KINDS):
        _fail(SzseFailureCode.INTEGRITY)
    identity_assets = tuple(_parse_raw_ref(item) for item in identity_values)
    expected_types = (_HTML_TYPES, _JS_TYPES, _JS_TYPES, _JS_TYPES)
    for reference, endpoint_kind, content_types in zip(
        identity_assets, _IDENTITY_KINDS, expected_types, strict=True
    ):
        if reference.kind != endpoint_kind or reference.capture_id != _capture_id(
            run_id, f"capture:{endpoint_kind}"
        ):
            _fail(SzseFailureCode.INTEGRITY)
        if not _mime_is(reference.content_type, content_types):
            _fail(SzseFailureCode.INTEGRITY)

    root_reference, path_reference, concat_reference, js_reference = identity_assets
    root_body = _load_raw_reference(
        raw_storage,
        root_reference,
        source=SZSE_CALENDAR_SOURCE,
        expected_route=f"GET {SZSE_CALENDAR_ROOT_URL}",
    )
    random_ms = _identity_random_ms(root_reference.observed_at)
    path_url, concat_url = cast(
        tuple[str, str], _parse_identity(root_body, endpoint_kind="root", random_ms=random_ms)
    )
    path_body = _load_raw_reference(
        raw_storage,
        path_reference,
        source=SZSE_CALENDAR_SOURCE,
        expected_route=f"GET {path_url}",
    )
    path_identity = cast(tuple[str, str], _parse_identity(path_body, endpoint_kind="path"))
    concat_body = _load_raw_reference(
        raw_storage,
        concat_reference,
        source=SZSE_CALENDAR_SOURCE,
        expected_route=f"GET {concat_url}",
    )
    derived_js_url = cast(
        str,
        _parse_identity(
            concat_body,
            endpoint_kind="concat",
            path_identity=path_identity,
        ),
    )
    js_body = _load_raw_reference(
        raw_storage,
        js_reference,
        source=SZSE_CALENDAR_SOURCE,
        expected_route=f"GET {derived_js_url}",
    )
    _parse_identity(js_body, endpoint_kind="js", path_identity=path_identity)
    return identity_assets


def _replay_catalogs(
    raw_storage: RawStorage,
    *,
    run_id: UUID,
    payload: Mapping[str, object],
) -> tuple[CalendarScanRunCatalogReceipt, ...]:
    values = payload.get("catalogs")
    if type(values) is not list:
        _fail(SzseFailureCode.INTEGRITY)
    catalog_values = cast(list[object], values)
    if len(catalog_values) != 12:
        _fail(SzseFailureCode.INTEGRITY)
    catalogs: list[CalendarScanRunCatalogReceipt] = []
    for index, value in enumerate(catalog_values, start=1):
        raw_catalog = _json_object(value)
        if set(raw_catalog) != set(_CATALOG_ENTRY_KEYS):
            _fail(SzseFailureCode.INTEGRITY)
        raw_ref = _parse_raw_ref(raw_catalog.get("raw_ref"), expected_kind="catalog")
        body = _load_raw_reference(
            raw_storage,
            raw_ref,
            source=SZSE_CATALOG_SOURCE,
            expected_route=_catalog_route(2026, index),
        )
        expected_url = szse_direct_daily_url(2026, index)
        expected_catalog = {
            "version": SZSE_CATALOG_VERSION,
            "authority": "SZSE",
            "exchange": "SZ",
            "year": 2026,
            "month": index,
            "resource_id": calendar_scan_run_resource_id(2026, index),
            "url": expected_url,
        }
        if _parse_json_object(body) != expected_catalog:
            _fail(SzseFailureCode.INTEGRITY)
        expected_catalog_id = _domain_id(run_id, f"catalog:{index}")
        expected_evidence_id = _domain_id(run_id, f"catalog-evidence:{index}")
        if (
            raw_catalog.get("run_id") != str(run_id)
            or raw_catalog.get("year") != 2026
            or raw_catalog.get("month") != index
            or raw_catalog.get("catalog_id") != str(expected_catalog_id)
            or raw_catalog.get("resource_id") != calendar_scan_run_resource_id(2026, index)
            or raw_catalog.get("raw_evidence_id") != str(expected_evidence_id)
            or raw_catalog.get("raw_artifact_sha256") != raw_ref.checksum
            or raw_catalog.get("identity_verified") is not True
            or raw_catalog.get("replay_verified") is not True
            or raw_catalog.get("url") != expected_url
            or raw_ref.capture_id != _capture_id(run_id, f"capture:catalog:{index}")
        ):
            _fail(SzseFailureCode.INTEGRITY)
        try:
            catalogs.append(
                CalendarScanRunCatalogReceipt(
                    run_id=UUID(cast(str, raw_catalog.get("run_id"))),
                    year=cast(int, raw_catalog.get("year")),
                    month=cast(int, raw_catalog.get("month")),
                    catalog_id=UUID(cast(str, raw_catalog.get("catalog_id"))),
                    resource_id=cast(str, raw_catalog.get("resource_id")),
                    raw_evidence_id=UUID(cast(str, raw_catalog.get("raw_evidence_id"))),
                    raw_artifact_sha256=cast(str, raw_catalog.get("raw_artifact_sha256")),
                    identity_verified=cast(bool, raw_catalog.get("identity_verified")),
                    replay_verified=cast(bool, raw_catalog.get("replay_verified")),
                )
            )
        except Exception:
            _fail(SzseFailureCode.INTEGRITY)
    return tuple(catalogs)


def _replay_pages(
    raw_storage: RawStorage,
    *,
    run_id: UUID,
    payload: Mapping[str, object],
) -> tuple[CalendarScanRunPage, ...]:
    values = payload.get("pages")
    if type(values) is not list:
        _fail(SzseFailureCode.INTEGRITY)
    page_values = cast(list[object], values)
    if len(page_values) != 24:
        _fail(SzseFailureCode.INTEGRITY)
    pages: list[CalendarScanRunPage] = []
    for index, value in enumerate(page_values):
        raw_page = _json_object(value)
        if set(raw_page) != set(_PAGE_ENTRY_KEYS):
            _fail(SzseFailureCode.INTEGRITY)
        pass_number = 1 if index < 12 else 2
        month = index % 12 + 1
        raw_ref = _parse_raw_ref(raw_page.get("raw_ref"), expected_kind="page")
        state_ref = _parse_raw_ref(raw_page.get("state_ref"), expected_kind="run")
        body = _load_raw_reference(
            raw_storage,
            raw_ref,
            source=SZSE_CALENDAR_SOURCE,
            expected_route=f"GET {szse_direct_daily_url(2026, month)}",
        )
        if not _mime_is(raw_ref.content_type, _JSON_TYPES):
            _fail(SzseFailureCode.INTEGRITY)
        source_nowdate, days = _parse_month_body(body, year=2026, month=month)
        if source_nowdate != raw_ref.observed_at.astimezone(_SHANGHAI_TZ).date():
            _fail(SzseFailureCode.INTEGRITY)
        raw_days = _parse_json_list(raw_page.get("days"))
        if tuple(_parse_date(_json_object(item).get("date")) for item in raw_days) != tuple(
            day.date for day in days
        ):
            _fail(SzseFailureCode.INTEGRITY)
        for raw_day_value, expected_day in zip(raw_days, days, strict=True):
            raw_day = _json_object(raw_day_value)
            if (
                set(raw_day) != set(_DAY_ENTRY_KEYS)
                or raw_day.get("date") != expected_day.date.isoformat()
                or raw_day.get("is_trading_day") is not expected_day.is_trading_day
            ):
                _fail(SzseFailureCode.INTEGRITY)
        expected_pass_id = calendar_scan_run_pass_id(run_id, pass_number)
        expected_page_id = _domain_id(run_id, f"page:{pass_number}:{month}")
        expected_catalog_id = _domain_id(run_id, f"catalog:{month}")
        expected_evidence_id = _domain_id(run_id, f"page-evidence:{pass_number}:{month}")
        expected_artifact_id = _domain_id(run_id, f"page-artifact:{pass_number}:{month}")
        expected_domain_capture_id = _domain_id(run_id, f"page-capture:{pass_number}:{month}")
        expected_attempt_id = _capture_id(run_id, f"attempt:page:{pass_number}:{month}")
        opened_at = _parse_iso_datetime(raw_page.get("opened_at"))
        if (
            raw_page.get("run_id") != str(run_id)
            or raw_page.get("pass_number") != pass_number
            or raw_page.get("pass_id") != str(expected_pass_id)
            or raw_page.get("month") != month
            or raw_page.get("year") != 2026
            or raw_page.get("page_id") != str(expected_page_id)
            or raw_page.get("catalog_id") != str(expected_catalog_id)
            or raw_page.get("resource_id") != calendar_scan_run_resource_id(2026, month)
            or raw_page.get("raw_evidence_id") != str(expected_evidence_id)
            or raw_page.get("raw_artifact_sha256") != raw_ref.checksum
            or raw_page.get("canonical_payload_sha256") != calendar_scan_run_payload_digest(days)
            or raw_page.get("artifact_id") != str(expected_artifact_id)
            or raw_page.get("capture_id") != str(expected_domain_capture_id)
            or raw_page.get("opened_at") != opened_at.isoformat()
            or raw_page.get("observed_at") != raw_ref.observed_at.isoformat()
            or raw_page.get("available_at") != raw_ref.available_at.isoformat()
            or raw_page.get("source_nowdate") != source_nowdate.isoformat()
            or raw_page.get("identity_verified") is not True
            or raw_page.get("replay_verified") is not True
            or raw_ref.capture_id != _capture_id(run_id, f"capture:page:{pass_number}:{month}")
            or state_ref.capture_id != _state_capture_id(run_id, expected_attempt_id)
        ):
            _fail(SzseFailureCode.INTEGRITY)
        try:
            pages.append(
                CalendarScanRunPage(
                    run_id=run_id,
                    pass_number=pass_number,
                    pass_id=expected_pass_id,
                    month=month,
                    year=2026,
                    page_id=expected_page_id,
                    catalog_id=expected_catalog_id,
                    resource_id=calendar_scan_run_resource_id(2026, month),
                    raw_evidence_id=expected_evidence_id,
                    raw_artifact_sha256=raw_ref.checksum,
                    canonical_payload_sha256=calendar_scan_run_payload_digest(days),
                    artifact_id=expected_artifact_id,
                    capture_id=expected_domain_capture_id,
                    opened_at=opened_at,
                    observed_at=raw_ref.observed_at,
                    available_at=raw_ref.available_at,
                    source_nowdate=source_nowdate,
                    identity_verified=True,
                    replay_verified=True,
                    days=days,
                )
            )
        except Exception:
            _fail(SzseFailureCode.INTEGRITY)
    return tuple(pages)


def _replay_passes(
    *, run_id: UUID, payload: Mapping[str, object], pages: tuple[CalendarScanRunPage, ...]
) -> tuple[CalendarScanRunPassReceipt, ...]:
    values = payload.get("passes")
    if type(values) is not list:
        _fail(SzseFailureCode.INTEGRITY)
    pass_values = cast(list[object], values)
    if len(pass_values) != 2:
        _fail(SzseFailureCode.INTEGRITY)
    receipts: list[CalendarScanRunPassReceipt] = []
    for index, value in enumerate(pass_values, start=1):
        raw_pass = _json_object(value)
        if set(raw_pass) != set(_PASS_ENTRY_KEYS):
            _fail(SzseFailureCode.INTEGRITY)
        page_refs = _parse_json_list(raw_pass.get("page_refs"))
        pages_for_pass = pages[:12] if index == 1 else pages[12:]
        expected_page_refs = tuple(str(page.page_id) for page in pages_for_pass)
        expected_pass_id = calendar_scan_run_pass_id(run_id, index)
        if (
            raw_pass.get("run_id") != str(run_id)
            or raw_pass.get("pass_number") != index
            or raw_pass.get("pass_id") != str(expected_pass_id)
            or tuple(page_refs) != expected_page_refs
            or raw_pass.get("member_digest") != calendar_scan_run_pass_member_digest(pages_for_pass)
        ):
            _fail(SzseFailureCode.INTEGRITY)
        try:
            receipts.append(
                CalendarScanRunPassReceipt(
                    run_id=run_id,
                    pass_number=index,
                    pass_id=expected_pass_id,
                    opened_at=_parse_iso_datetime(raw_pass.get("opened_at")),
                    finished_at=_parse_iso_datetime(raw_pass.get("finished_at")),
                    page_refs=tuple(UUID(cast(str, value)) for value in page_refs),
                    member_digest=cast(str, raw_pass.get("member_digest")),
                )
            )
        except Exception:
            _fail(SzseFailureCode.INTEGRITY)
    result = tuple(receipts)
    if tuple(receipt.page_refs for receipt in result) != (
        tuple(page.page_id for page in pages[:12]),
        tuple(page.page_id for page in pages[12:]),
    ):
        _fail(SzseFailureCode.INTEGRITY)
    return result


def _replay_manifest(
    *,
    run_id: UUID,
    payload: Mapping[str, object],
    manifest_storage: RawObjectManifest,
) -> tuple[CalendarScanRunManifestReceipt, datetime]:
    manifest_domain = _json_object(payload.get("manifest_domain"))
    if set(manifest_domain) != {
        "raw_evidence_id",
        "artifact_id",
        "capture_id",
        "canonical_member_digest",
        "finalized_at",
    }:
        _fail(SzseFailureCode.INTEGRITY)
    cutoff_at = _parse_manifest_datetime(payload.get("cutoff_at"))
    if manifest_storage.ingest_time != cutoff_at or manifest_storage.available_time != cutoff_at:
        _fail(SzseFailureCode.INTEGRITY)
    expected_domain = _manifest_domain(
        run_id,
        canonical_member_digest=cast(str, manifest_domain.get("canonical_member_digest")),
        finalized_at=cutoff_at,
    )
    if manifest_domain != expected_domain:
        _fail(SzseFailureCode.INTEGRITY)
    try:
        manifest = CalendarScanRunManifestReceipt(
            run_id=run_id,
            raw_evidence_id=UUID(cast(str, manifest_domain.get("raw_evidence_id"))),
            artifact_id=UUID(cast(str, manifest_domain.get("artifact_id"))),
            capture_id=UUID(cast(str, manifest_domain.get("capture_id"))),
            raw_artifact_sha256=manifest_storage.checksum,
            canonical_member_digest=cast(str, manifest_domain.get("canonical_member_digest")),
            finalized_at=cutoff_at,
        )
    except Exception:
        _fail(SzseFailureCode.INTEGRITY)
    return manifest, cutoff_at


def _replay_szse_daily_run_core(
    raw_storage: RawStorage,
    *,
    run_id: UUID,
    manifest_date: str,
    manifest_capture_id: str,
) -> SzseOfficialDailyResult:
    """Rebuild one ledger-authorized run using only raw/state/manifest reads.

    This function has no transport parameter and never calls ``RawStorage.put``.
    """

    try:
        _strict_uuid(run_id)
        manifest_storage, manifest_body = _manifest_for_replay(
            raw_storage,
            run_id=run_id,
            manifest_date=manifest_date,
            manifest_capture_id=manifest_capture_id,
        )
        payload = _parse_json_object(manifest_body)
        _validate_manifest_payload(payload, run_id=run_id, manifest_storage=manifest_storage)
        identity_assets = _replay_identity_assets(raw_storage, run_id=run_id, payload=payload)
        catalogs = _replay_catalogs(raw_storage, run_id=run_id, payload=payload)
        pages = _replay_pages(raw_storage, run_id=run_id, payload=payload)
        passes = _replay_passes(run_id=run_id, payload=payload, pages=pages)
        attempts = _replay_attempts(raw_storage, run_id=run_id, payload=payload)
        for identity_reference, attempt in zip(
            identity_assets, attempts[: len(_IDENTITY_KINDS)], strict=True
        ):
            if (
                attempt.raw_ref is None
                or attempt.state_ref is None
                or identity_reference != attempt.raw_ref
            ):
                _fail(SzseFailureCode.INTEGRITY)
        raw_page_values = cast(list[object], payload.get("pages"))
        for page, attempt, raw_page_value in zip(
            pages, attempts[len(_IDENTITY_KINDS) :], raw_page_values, strict=True
        ):
            raw_page = _json_object(raw_page_value)
            page_raw_ref = _parse_raw_ref(raw_page.get("raw_ref"), expected_kind="page")
            page_state_ref = _parse_raw_ref(raw_page.get("state_ref"), expected_kind="run")
            if (
                attempt.raw_ref is None
                or attempt.state_ref is None
                or page_raw_ref != attempt.raw_ref
                or page_state_ref != attempt.state_ref
                or attempt.raw_ref.capture_id
                != _capture_id(run_id, f"capture:page:{page.pass_number}:{page.month}")
                or attempt.raw_ref.checksum != page.raw_artifact_sha256
                or attempt.raw_ref.observed_at != page.observed_at
                or attempt.raw_ref.available_at != page.available_at
            ):
                _fail(SzseFailureCode.INTEGRITY)
        manifest, cutoff_at = _replay_manifest(
            run_id=run_id, payload=payload, manifest_storage=manifest_storage
        )
        opened_at = _parse_iso_datetime(payload.get("opened_at"))
        catalog_refs = tuple(
            _parse_raw_ref(_json_object(item).get("raw_ref"), expected_kind="catalog")
            for item in cast(list[object], payload.get("catalogs"))
        )
        identity_attempt_references = tuple(
            reference
            for identity_reference, attempt in zip(
                identity_assets, attempts[: len(_IDENTITY_KINDS)], strict=True
            )
            for reference in (identity_reference, attempt.state_ref)
            if reference is not None
        )
        page_attempt_references = tuple(
            reference
            for attempt in attempts[len(_IDENTITY_KINDS) :]
            for reference in (attempt.raw_ref, attempt.state_ref)
            if reference is not None
        )
        manifest_reference = _reference_from_manifest(
            manifest_storage,
            "manifest",
            route_digest=_route_digest(_manifest_route()),
            request_identity=_route_request_identity(_manifest_route()),
        )
        _validate_evidence_timeline(
            identity_attempt_references
            + catalog_refs
            + page_attempt_references
            + (manifest_reference,),
            opened_at=opened_at,
            cutoff_at=cutoff_at,
        )
        if manifest.canonical_member_digest != calendar_scan_run_manifest_member_digest(
            catalogs, passes, pages
        ):
            _fail(SzseFailureCode.INTEGRITY)
        proof = CalendarScanRunReceipt(
            run_id=run_id,
            authority=cast(str, payload.get("authority")),
            exchange=cast(str, payload.get("exchange")),
            year=cast(int, payload.get("year")),
            parser_version=cast(str, payload.get("parser_version")),
            contract_version=cast(str, payload.get("contract_version")),
            policy_id=cast(str, payload.get("policy_id")),
            compiled_catalog_sha256=cast(str, payload.get("compiled_catalog_sha256")),
            opened_at=opened_at,
            cutoff_at=cutoff_at,
            catalog_receipts=catalogs,
            pass_receipts=passes,
            pages=pages,
            manifest=manifest,
        )
        return SzseOfficialDailyResult(
            exchange="SZ",
            year=2026,
            run_id=run_id,
            proof=proof,
            raw_manifest_ref=manifest_reference,
            identity_assets=identity_assets,
            catalog_refs=catalog_refs,
            attempts=attempts,
        )
    except OfficialSzseCalendarError:
        raise
    except _CollectionFailureError:
        error_message = _REPLAY_ERROR
    except Exception:
        error_message = _REPLAY_ERROR
    _raise(error_message)


def replay_szse_daily_run(
    raw_storage: RawStorage,
    *,
    run_id: UUID,
    manifest_date: str,
    manifest_capture_id: str,
) -> SzseOfficialDailyResult:
    """Replay only a run with a durable claim and final ledger pointer."""

    try:
        _strict_uuid(run_id)
        final_payload = _load_ledger_state(raw_storage, run_id=run_id)
    except Exception:
        final_payload = None
    if final_payload is None:
        _raise(_REPLAY_ERROR)
    if (
        final_payload.get("manifest_date") != manifest_date
        or final_payload.get("manifest_capture_id") != manifest_capture_id
    ):
        _raise(_REPLAY_ERROR)
    try:
        result = _replay_szse_daily_run_core(
            raw_storage,
            run_id=run_id,
            manifest_date=manifest_date,
            manifest_capture_id=manifest_capture_id,
        )
    except OfficialSzseCalendarError:
        raise
    except Exception:
        result = None
    if result is None:
        _raise(_REPLAY_ERROR)
    if result.proof.proof_digest != final_payload.get("proof_digest"):
        _raise(_REPLAY_ERROR)
    return result


class _NoRedirectHandler(HTTPRedirectHandler):
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


class _UrllibSzseTransport:
    """Bounded HTTPS transport that rejects redirects and unknown URLs."""

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> OfficialSzseResponse:
        allowed_dynamic = False
        for kind in ("path", "concat"):
            try:
                _validated_dynamic_identity_url(url, kind=kind)
            except _CollectionFailureError:
                continue
            allowed_dynamic = True
            break
        if not (
            allowed_dynamic
            or url
            in {
                SZSE_CALENDAR_ROOT_URL,
                SZSE_CALENDAR_JS_URL,
                *(szse_direct_daily_url(_SUPPORTED_YEAR, month) for month in range(1, 13)),
            }
        ):
            _raise(_RESPONSE_ERROR)
        if type(timeout_seconds) is not float or not 0.0 < timeout_seconds <= 60.0:
            _raise(_RESPONSE_ERROR)
        if type(max_bytes) is not int or max_bytes < 1024 or max_bytes > 8 * 1024 * 1024:
            _raise(_RESPONSE_ERROR)
        request = Request(url, method="GET", headers={"Accept": "application/json, text/html, */*"})
        opener = build_opener(
            ProxyHandler({}),
            HTTPSHandler(context=ssl.create_default_context()),
            _NoRedirectHandler(),
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                return _read_http_response(response, max_bytes)
        except HTTPError as response_error:
            return _read_http_response(response_error, max_bytes)
        except Exception:
            _raise(_RESPONSE_ERROR)


class _HttpResponse(Protocol):
    status: int
    headers: Message

    def read(self, size: int = -1) -> bytes: ...


def _read_http_response(response: object, max_bytes: int) -> OfficialSzseResponse:
    try:
        http_response = cast(_HttpResponse, response)
        status_code = http_response.status
        headers = http_response.headers
        content_type = headers.get("Content-Type")
        body = http_response.read(max_bytes + 1)
    except Exception:
        _raise(_RESPONSE_ERROR)
    if type(status_code) is not int or type(body) is not bytes:
        _raise(_RESPONSE_ERROR)
    normalized = _canonical_content_type(content_type) or "application/octet-stream"
    return OfficialSzseResponse(
        status_code=status_code,
        content_type=normalized,
        body=body,
        redirected=status_code in {301, 302, 303, 307, 308},
    )


OfficialSzseCalendarCollector = SzseOfficialCalendarCollector
SzseOfficialDailyCollector = SzseOfficialCalendarCollector
OfficialSzseDailyCollector = SzseOfficialCalendarCollector


__all__ = [
    "SZSE_CALENDAR_CONCATVERSION_PATH",
    "SZSE_CALENDAR_CONCATVERSION_HOST",
    "SZSE_CALENDAR_CONCATVERSION_URL",
    "SZSE_CALENDAR_CONCATVERSION_URL_TEMPLATE",
    "SZSE_CALENDAR_JS_URL",
    "SZSE_CALENDAR_PATH_HOST",
    "SZSE_CALENDAR_PATH_SCRIPT_PATH",
    "SZSE_CALENDAR_PATH_URL_TEMPLATE",
    "SZSE_CALENDAR_ROOT_URL",
    "SZSE_CALENDAR_SCRIPT_PATH",
    "SZSE_CALENDAR_STATIC_HOST",
    "SZSE_CALENDAR_SOURCE",
    "SZSE_CAPTURE_STATE_SOURCE",
    "SZSE_CATALOG_SOURCE",
    "SZSE_CONTRACT_VERSION",
    "SZSE_DIRECT_DAILY_URL_TEMPLATE",
    "SZSE_IDENTITY_POLICY_VERSION",
    "SZSE_MANIFEST_SOURCE",
    "SZSE_MAX_RESPONSE_BYTES",
    "SZSE_PARSER_VERSION",
    "SZSE_RUN_LEDGER_DATE",
    "SZSE_RUN_LEDGER_SOURCE",
    "SZSE_RUN_LEDGER_VERSION",
    "SZSE_TIMEOUT_SECONDS",
    "OfficialSzseCalendarCollector",
    "OfficialSzseCalendarError",
    "OfficialSzseDailyCollector",
    "OfficialSzseResponse",
    "OfficialSzseTransport",
    "SzseCaptureAttempt",
    "SzseFailureCode",
    "SzseOfficialCalendarCollector",
    "SzseOfficialDailyCollector",
    "SzseOfficialDailyResult",
    "SzseRawReference",
    "replay_szse_daily_run",
    "szse_direct_daily_url",
]
