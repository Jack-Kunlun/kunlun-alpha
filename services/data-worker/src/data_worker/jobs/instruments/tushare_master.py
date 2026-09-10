"""Raw-first Tushare Pro security-master collection and replay.

This adapter deliberately does not import the Tushare SDK.  The provider
response is captured before it is parsed, request identities contain no token,
and the replay path only reads the immutable raw landing zone.
"""

from __future__ import annotations

import json
import re
import time as time_module
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from email.message import Message
from enum import StrEnum
from typing import IO, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from data_worker.raw.manifest import (
    RawObjectManifest,
    normalize_content_type,
    sanitize_request_identity,
    utc_now,
)
from data_worker.raw.storage import RawIntegrityError, RawStorage
from market_core.instrument import (
    InstrumentMasterRecord,
    ListingLifecycle,
    TradingAvailability,
)
from market_core.instrument.code_parser import parse_instrument_code

TUSHARE_INSTRUMENT_SOURCE = "tushare-instrument-master"
TUSHARE_INSTRUMENT_PROFILE_VERSION = "tushare-instrument-profile-v1"
TUSHARE_INSTRUMENT_SCHEMA_VERSION = "tushare-instrument-raw-v1"
TUSHARE_INSTRUMENT_PARSER_VERSION = "tushare-instrument-parser-v1"
TUSHARE_INSTRUMENT_CAPTURE_VERSION = "tushare-instrument-capture-v1"
TUSHARE_API_ENDPOINT = "https://api.tushare.pro"
TUSHARE_COLLECTION_PARTITIONS: tuple[tuple[str, str, str | None], ...] = (
    ("stock_basic", "L", None),
    ("stock_basic", "P", None),
    ("stock_basic", "D", None),
    ("fund_basic", "L", "E"),
    ("fund_basic", "D", "E"),
)
TUSHARE_STOCK_BASIC_FIELDS: tuple[str, ...] = (
    "ts_code",
    "symbol",
    "name",
    "area",
    "industry",
    "fullname",
    "enname",
    "cnspell",
    "market",
    "exchange",
    "curr_type",
    "list_status",
    "list_date",
    "delist_date",
    "is_hs",
    "act_name",
    "act_ent_type",
)
TUSHARE_FUND_BASIC_FIELDS: tuple[str, ...] = (
    "ts_code",
    "name",
    "management",
    "custodian",
    "fund_type",
    "found_date",
    "due_date",
    "list_date",
    "issue_date",
    "delist_date",
    "issue_amount",
    "m_fee",
    "c_fee",
    "duration_year",
    "p_value",
    "min_amount",
    "exp_return",
    "benchmark",
    "status",
    "invest_type",
    "type",
    "trustee",
    "purc_startdate",
    "redm_startdate",
    "market",
)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DATE8_RE = re.compile(r"^(?:19|20)\d{6}$")
_SUPPORTED_EXCHANGES = frozenset({"SH", "SZ", "BJ"})
_TRANSIENT_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_PAGE_REF_KEYS = frozenset(
    {
        "ordinal",
        "api_name",
        "status_partition",
        "market_partition",
        "offset",
        "row_count",
        "capture_id",
        "object_id",
        "checksum",
        "size",
        "request",
        "status_code",
        "content_type",
        "observed_at",
        "available_at",
        "source_revision",
    }
)
_ATTEMPT_REF_KEYS = frozenset(
    {
        "ordinal",
        "partition",
        "offset",
        "attempt",
        "capture_id",
        "object_id",
        "status_code",
        "state",
        "request",
        "checksum",
        "size",
        "content_type",
        "observed_at",
        "available_at",
        "source_revision",
    }
)
_CHECKPOINT_KEYS = frozenset(
    {
        "capture_schema",
        "kind",
        "source",
        "profile_version",
        "schema_version",
        "parser_version",
        "source_revision",
        "run_id",
        "manifest_date",
        "checkpoint_ordinal",
        "next_partition_ordinal",
        "next_offset",
        "page_refs",
        "attempt_refs",
        "records",
    }
)


class InstrumentMasterError(ValueError):
    """Base class for fixed, non-sensitive collector failures."""


class InstrumentMasterTransportError(InstrumentMasterError):
    """The provider could not be reached within its bounded retry budget."""


class InstrumentMasterDataError(InstrumentMasterError):
    """The provider response did not match the pinned raw contract."""


class _InstrumentMasterFetchError(InstrumentMasterError):
    """A page failed after its attempt evidence was durably captured."""

    def __init__(
        self,
        message: str,
        attempts: tuple[InstrumentAttemptRef, ...],
        *,
        transport: bool,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.transport = transport


class InstrumentMasterDisposition(StrEnum):
    COMPLETE = "COMPLETE"
    INDETERMINATE = "INDETERMINATE"
    REJECTED = "REJECTED"


class InstrumentMasterTerminal(StrEnum):
    COMPLETE = "COMPLETE"
    INDETERMINATE = "INDETERMINATE"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class TushareInstrumentConfig:
    """Fixed connection/profile settings; ``token`` never appears in repr."""

    token: str = field(repr=False)
    endpoint: str = TUSHARE_API_ENDPOINT
    timeout_seconds: float = 8.0
    max_attempts: int = 3
    retry_backoff_seconds: float = 0.5
    page_size: int = 5000
    max_pages: int = 100
    source_revision: str | None = None

    def __post_init__(self) -> None:
        if type(self.token) is not str or not self.token.strip():
            raise ValueError("Tushare token is required")
        endpoint = self.endpoint.strip().rstrip("/")
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "api.tushare.pro"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Tushare endpoint must be the fixed HTTPS API endpoint")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            raise ValueError("timeout_seconds is outside the supported bound")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 5:
            raise ValueError("max_attempts is outside the supported bound")
        if self.retry_backoff_seconds < 0 or self.retry_backoff_seconds > 30:
            raise ValueError("retry_backoff_seconds is outside the supported bound")
        if type(self.page_size) is not int or not 1 <= self.page_size <= 5000:
            raise ValueError("page_size is outside the supported bound")
        if type(self.max_pages) is not int or not 1 <= self.max_pages <= 1000:
            raise ValueError("max_pages is outside the supported bound")
        if self.source_revision is not None:
            raise ValueError("operator source revision is not accepted")
        object.__setattr__(self, "token", self.token.strip())
        object.__setattr__(self, "endpoint", endpoint)


@dataclass(frozen=True, slots=True)
class TushareInstrumentResponse:
    """Transport result with only bounded response metadata."""

    status_code: int
    body: bytes
    content_type: str = "application/json; charset=utf-8"
    redirected: bool = False

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise ValueError("status_code is invalid")
        if type(self.body) is not bytes or len(self.body) > _MAX_RESPONSE_BYTES:
            raise ValueError("provider response exceeds the bounded size")
        object.__setattr__(self, "content_type", normalize_content_type(self.content_type))
        if type(self.redirected) is not bool:
            raise ValueError("redirected is invalid")


class TushareInstrumentTransport(Protocol):
    def __call__(
        self,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> TushareInstrumentResponse | tuple[int, bytes]: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> Request | None:
        del req, fp, code, msg, headers, newurl
        return None


def _stdlib_http_transport(
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    timeout_seconds: float,
) -> TushareInstrumentResponse:
    request = Request(url, data=body, headers=dict(headers), method="POST")
    opener = build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout_seconds) as response:  # noqa: S310
            response_body = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(response_body) > _MAX_RESPONSE_BYTES:
                raise InstrumentMasterTransportError("provider response exceeds the bounded size")
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "application/json")
            return TushareInstrumentResponse(
                status_code=int(response.status),
                body=response_body,
                content_type=content_type,
                redirected=final_url != url,
            )
    except HTTPError as error:
        response_body = error.read(_MAX_RESPONSE_BYTES + 1)
        if len(response_body) > _MAX_RESPONSE_BYTES:
            response_body = b""
        content_type = error.headers.get("Content-Type", "application/json")
        return TushareInstrumentResponse(
            status_code=int(error.code),
            body=response_body,
            content_type=content_type,
            redirected=300 <= int(error.code) < 400,
        )
    except TimeoutError as error:
        raise InstrumentMasterTransportError("provider request timed out") from error
    except URLError as error:
        raise InstrumentMasterTransportError("provider request was unavailable") from error
    except OSError as error:
        raise InstrumentMasterTransportError("provider request was unavailable") from error


@dataclass(frozen=True, slots=True)
class InstrumentPageRef:
    """Manifest-level evidence for one successfully captured page."""

    ordinal: int
    api_name: str
    status_partition: str
    market_partition: str | None
    offset: int
    row_count: int
    capture_id: str
    object_id: str
    checksum: str
    size: int
    request: str
    status_code: int
    content_type: str
    observed_at: datetime
    available_at: datetime
    source_revision: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "api_name": self.api_name,
            "status_partition": self.status_partition,
            "market_partition": self.market_partition,
            "offset": self.offset,
            "row_count": self.row_count,
            "capture_id": self.capture_id,
            "object_id": self.object_id,
            "checksum": self.checksum,
            "size": self.size,
            "request": self.request,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "observed_at": self.observed_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "source_revision": self.source_revision,
        }


@dataclass(frozen=True, slots=True)
class InstrumentAttemptRef:
    """Durable state for every response/transport attempt."""

    ordinal: int
    partition: str
    offset: int
    attempt: int
    capture_id: str
    object_id: str
    status_code: int
    state: str
    # The attempt is an evidence edge in its own right.  Keep the exact raw
    # manifest metadata here so the database adapter never has to invent
    # request/timeline/MIME values while rebuilding the graph.
    request: str = ""
    checksum: str = ""
    size: int = 0
    content_type: str = "application/json; charset=utf-8"
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    available_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    source_revision: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "partition": self.partition,
            "offset": self.offset,
            "attempt": self.attempt,
            "capture_id": self.capture_id,
            "object_id": self.object_id,
            "status_code": self.status_code,
            "state": self.state,
            "request": self.request,
            "checksum": self.checksum,
            "size": self.size,
            "content_type": self.content_type,
            "observed_at": self.observed_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "source_revision": self.source_revision,
        }


@dataclass(frozen=True, slots=True)
class InstrumentMasterRunResult:
    """Stable collection/replay result; raw evidence is referenced by id."""

    run_id: str
    manifest_date: str
    manifest_capture_id: str
    records: tuple[InstrumentMasterRecord, ...]
    page_refs: tuple[InstrumentPageRef, ...]
    attempt_refs: tuple[InstrumentAttemptRef, ...]
    terminal: InstrumentMasterTerminal
    completeness: InstrumentMasterDisposition
    reason_code: str
    source_revision: str | None = None
    checkpoint_capture_ids: tuple[str, ...] = ()
    manifest_history: tuple[str, ...] = ()

    @property
    def disposition(self) -> InstrumentMasterDisposition:
        return self.completeness

    @property
    def run_disposition(self) -> str:
        return (
            "SNAPSHOT_CANDIDATE"
            if self.completeness is InstrumentMasterDisposition.COMPLETE
            else "NO_HEAD_CHANGE"
        )

    @property
    def manifest_date_value(self) -> date:
        return date.fromisoformat(self.manifest_date)


def _safe_id(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_ID_RE.fullmatch(value) is None:
        raise InstrumentMasterError(f"{field_name} is invalid")
    return value


def _validate_date(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise InstrumentMasterError(f"{field_name} is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise InstrumentMasterError(f"{field_name} is invalid") from error
    return parsed.isoformat()


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InstrumentMasterError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _uuid_text(value: str | uuid.UUID | None) -> str:
    if value is None:
        return str(uuid.uuid4())
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, AttributeError) as error:
        raise InstrumentMasterError("run_id is invalid") from error
    return str(parsed)


def _no_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InstrumentMasterDataError("provider JSON contains duplicate keys")
        result[key] = value
    return result


def _decode_json(body: bytes) -> dict[str, object]:
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=_no_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, InstrumentMasterDataError) as error:
        raise InstrumentMasterDataError("provider response is not valid JSON") from error
    if not isinstance(value, dict):
        raise InstrumentMasterDataError("provider response must be an object")
    return cast(dict[str, object], value)


def _field_tuple(value: object, expected: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise InstrumentMasterDataError("provider response fields drifted")
    values = cast(list[object], value)
    if tuple(values) != expected:
        raise InstrumentMasterDataError("provider response fields drifted")
    if not all(isinstance(item, str) for item in values):
        raise InstrumentMasterDataError("provider response fields are invalid")
    return expected


def _text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise InstrumentMasterDataError(f"provider field {field_name} is invalid")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise InstrumentMasterDataError(f"provider field {field_name} is empty")
    if len(normalized) > 256 or any(ord(char) < 32 for char in normalized):
        raise InstrumentMasterDataError(f"provider field {field_name} is invalid")
    return normalized


def _date8(value: object, field_name: str, *, required: bool = False) -> date | None:
    text = _text(value, field_name, allow_empty=True)
    if not text:
        if required:
            raise InstrumentMasterDataError(f"provider field {field_name} is required")
        return None
    if _DATE8_RE.fullmatch(text) is None:
        raise InstrumentMasterDataError(f"provider field {field_name} is invalid")
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError as error:
        raise InstrumentMasterDataError(f"provider field {field_name} is invalid") from error


def _canonical_code(value: object, security_type: str) -> tuple[str, str, str, str]:
    raw = _text(value, "ts_code")
    if "." not in raw:
        raise InstrumentMasterDataError("provider ts_code must use code.exchange")
    code, exchange = raw.rsplit(".", 1)
    if exchange not in _SUPPORTED_EXCHANGES:
        raise InstrumentMasterDataError("provider ts_code exchange is unsupported")
    parsed = parse_instrument_code(code)
    if parsed is None or parsed.exchange != exchange:
        raise InstrumentMasterDataError("provider ts_code is not a supported identity")
    if parsed.type != security_type and not (
        security_type == "FUND" and parsed.type in {"ETF", "LOF", "FUND"}
    ):
        raise InstrumentMasterDataError("provider security type conflicts with code prefix")
    return raw, code, exchange, parsed.board


def _record_from_row(
    row: Mapping[str, object],
    *,
    api_name: str,
    status_partition: str,
    market_partition: str | None,
    observed_at: datetime,
    available_at: datetime,
    evidence_ref: str,
    source_revision: str | None,
) -> InstrumentMasterRecord:
    if api_name == "stock_basic":
        expected_status = _text(row.get("list_status"), "list_status")
        if expected_status != status_partition:
            raise InstrumentMasterDataError("stock list_status conflicts with partition")
        security_type = "STOCK"
        unified_code, code, exchange, board = _canonical_code(row.get("ts_code"), security_type)
        if _text(row.get("symbol"), "symbol") != code:
            raise InstrumentMasterDataError("provider symbol conflicts with ts_code")
        expected_exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[exchange]
        if _text(row.get("exchange"), "exchange") != expected_exchange:
            raise InstrumentMasterDataError("provider exchange conflicts with ts_code")
        list_date = _date8(row.get("list_date"), "list_date")
        delist_date = _date8(row.get("delist_date"), "delist_date")
        lifecycle = (
            ListingLifecycle.DELISTED if status_partition == "D" else ListingLifecycle.LISTED
        )
        availability = (
            TradingAvailability.ACTIVE
            if status_partition == "L"
            else TradingAvailability.SUSPENDED_FULL_DAY
            if status_partition == "P"
            else TradingAvailability.UNKNOWN
        )
        name = _text(row.get("name"), "name")
        tags: list[str] = []
        if name.upper().startswith("*ST") or name.upper().startswith("ST"):
            tags.append("ST")
        market = _text(row.get("market"), "market", allow_empty=True)
        if market and market not in {"主板", "创业板", "科创板", "北交所"}:
            tags.append(f"MARKET_{re.sub(r'[^A-Z0-9]+', '_', market.upper()).strip('_')}")
    else:
        if market_partition != "E":
            raise InstrumentMasterDataError("fund partition must use market E")
        expected_status = _text(row.get("status"), "status")
        if expected_status != status_partition:
            raise InstrumentMasterDataError("fund status conflicts with partition")
        unified_code, code, exchange, board = _canonical_code(row.get("ts_code"), "FUND")
        list_date = _date8(row.get("list_date"), "list_date")
        delist_date = _date8(row.get("delist_date"), "delist_date")
        lifecycle = (
            ListingLifecycle.DELISTED if status_partition == "D" else ListingLifecycle.LISTED
        )
        availability = (
            TradingAvailability.ACTIVE if status_partition == "L" else TradingAvailability.UNKNOWN
        )
        name = _text(row.get("name"), "name")
        tags = []
        security_type = parse_instrument_code(code)
        if security_type is None:
            raise InstrumentMasterDataError("fund code is unsupported")
        actual_type = security_type.type
        if actual_type not in {"ETF", "LOF", "FUND"}:
            raise InstrumentMasterDataError("fund code is not an exchange-listed fund")
        security_type = actual_type

    return InstrumentMasterRecord(
        unified_code=unified_code,
        code=code,
        exchange=exchange,
        board=board,
        security_type=security_type,
        name=name,
        listing_lifecycle=lifecycle,
        trading_availability=availability,
        risk_tags=tuple(tags),
        list_date=list_date,
        delist_date=delist_date,
        observed_at=observed_at,
        available_at=available_at,
        source=TUSHARE_INSTRUMENT_SOURCE,
        source_revision=source_revision,
        evidence_ref=evidence_ref,
    )


def parse_tushare_instrument_page(
    body: bytes,
    *,
    api_name: str,
    status_partition: str,
    market_partition: str | None,
    observed_at: datetime,
    available_at: datetime,
    evidence_ref: str,
    source_revision: str | None = None,
) -> tuple[InstrumentMasterRecord, ...]:
    """Strictly parse one captured ``stock_basic`` or ``fund_basic`` page."""

    if api_name not in {"stock_basic", "fund_basic"}:
        raise InstrumentMasterDataError("provider API is unsupported")
    if status_partition not in {"L", "P", "D"}:
        raise InstrumentMasterDataError("provider status partition is unsupported")
    if api_name == "fund_basic" and status_partition not in {"L", "D"}:
        raise InstrumentMasterDataError("provider fund status partition is unsupported")
    observed = _aware(observed_at, "observed_at")
    available = _aware(available_at, "available_at")
    if available < observed:
        raise InstrumentMasterDataError("available_at precedes observed_at")
    root = _decode_json(body)
    if set(root) != {"code", "msg", "data"}:
        raise InstrumentMasterDataError("provider response envelope drifted")
    if type(root["code"]) is not int:
        raise InstrumentMasterDataError("provider response code is invalid")
    if root["code"] != 0:
        raise InstrumentMasterDataError("provider rejected the request")
    _text(root["msg"], "msg", allow_empty=True)
    data_value = root["data"]
    if not isinstance(data_value, dict):
        raise InstrumentMasterDataError("provider response data drifted")
    data = cast(dict[str, object], data_value)
    if set(data) != {"fields", "items"}:
        raise InstrumentMasterDataError("provider response data drifted")
    expected_fields = (
        TUSHARE_STOCK_BASIC_FIELDS if api_name == "stock_basic" else TUSHARE_FUND_BASIC_FIELDS
    )
    fields = _field_tuple(data["fields"], expected_fields)
    items_value = data["items"]
    if not isinstance(items_value, list):
        raise InstrumentMasterDataError("provider response items are invalid")
    items = cast(list[object], items_value)
    records: list[InstrumentMasterRecord] = []
    for row_index, item in enumerate(items):
        if not isinstance(item, list):
            raise InstrumentMasterDataError(f"provider row {row_index} does not match fields")
        row_values = cast(list[object], item)
        if len(row_values) != len(fields):
            raise InstrumentMasterDataError(f"provider row {row_index} does not match fields")
        if any(isinstance(value, (dict, list, tuple, set, float, bool)) for value in row_values):
            raise InstrumentMasterDataError(f"provider row {row_index} has unsupported value type")
        row: dict[str, object] = dict(zip(fields, row_values, strict=True))
        try:
            records.append(
                _record_from_row(
                    row,
                    api_name=api_name,
                    status_partition=status_partition,
                    market_partition=market_partition,
                    observed_at=observed,
                    available_at=available,
                    evidence_ref=evidence_ref,
                    source_revision=source_revision,
                )
            )
        except (KeyError, TypeError) as error:
            raise InstrumentMasterDataError(f"provider row {row_index} is invalid") from error
    return tuple(records)


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _coerce_response(value: object) -> TushareInstrumentResponse:
    if isinstance(value, TushareInstrumentResponse):
        return value
    if isinstance(value, tuple):
        values = cast(tuple[object, ...], value)
        if len(values) != 2:
            raise InstrumentMasterTransportError("transport response type is invalid")
        status, body = values
        if type(status) is int and isinstance(body, bytes):
            return TushareInstrumentResponse(status, body)
    raise InstrumentMasterTransportError("transport response type is invalid")


def _request_path(
    api_name: str,
    status_partition: str,
    market_partition: str | None,
    offset: int,
) -> str:
    market = "E" if market_partition is not None else "ALL"
    return f"POST /tushare/{api_name}/{status_partition}/{market}/offset/{offset}"


def _manifest_capture_id(run_id: str, generation: int = 0) -> str:
    return f"manifest-{uuid.UUID(run_id).hex}-{generation}"


def _checkpoint_capture_id(run_id: str, ordinal: int) -> str:
    return f"checkpoint-{uuid.UUID(run_id).hex}-{ordinal}"


def _page_capture_id(
    run_id: str,
    api_name: str,
    status_partition: str,
    market_partition: str | None,
    offset: int,
    attempt: int,
) -> str:
    market = "E" if market_partition is not None else "A"
    return (
        f"page-{uuid.UUID(run_id).hex}-{api_name[:2]}-{status_partition}-"
        f"{market}-{offset}-{attempt}"
    )


def _attempt_capture_id(run_id: str, partition_ordinal: int, offset: int, attempt: int) -> str:
    """Return a collision-free identity for one partition/offset attempt."""

    return f"attempt-{uuid.UUID(run_id).hex}-{partition_ordinal}-{offset}-{attempt}"


def _state_bytes(state: Mapping[str, object]) -> bytes:
    return _canonical_json({"capture_schema": TUSHARE_INSTRUMENT_CAPTURE_VERSION, **state})


def _strict_int(value: object, field_name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise InstrumentMasterDataError(f"{field_name} is invalid")
    return value


def _page_ref_from_dict(raw: Mapping[str, object], ordinal: int) -> InstrumentPageRef:
    if set(raw) != set(_PAGE_REF_KEYS):
        raise InstrumentMasterDataError("checkpoint page ref schema drifted")
    if raw.get("ordinal") != ordinal:
        raise InstrumentMasterDataError("checkpoint page order drifted")
    source_revision = raw.get("source_revision")
    if source_revision is not None:
        _safe_id(source_revision, "source_revision")
    market = raw.get("market_partition")
    if market is not None and not isinstance(market, str):
        raise InstrumentMasterDataError("checkpoint page market is invalid")
    capture_id = raw.get("capture_id")
    object_id = raw.get("object_id")
    checksum = raw.get("checksum")
    request = raw.get("request")
    if not all(isinstance(value, str) for value in (capture_id, object_id, checksum, request)):
        raise InstrumentMasterDataError("checkpoint page identity is invalid")
    capture_text = cast(str, capture_id)
    object_text = cast(str, object_id)
    checksum_text = cast(str, checksum)
    request_text = cast(str, request)
    source_revision_text = source_revision if isinstance(source_revision, str) else None
    return InstrumentPageRef(
        ordinal=ordinal,
        api_name=str(raw.get("api_name")),
        status_partition=str(raw.get("status_partition")),
        market_partition=market,
        offset=_strict_int(raw.get("offset"), "checkpoint page offset"),
        row_count=_strict_int(raw.get("row_count"), "checkpoint page row_count"),
        capture_id=capture_text,
        object_id=object_text,
        checksum=checksum_text,
        size=_strict_int(raw.get("size"), "checkpoint page size"),
        request=request_text,
        status_code=_strict_int(raw.get("status_code"), "checkpoint page status", minimum=100),
        content_type=str(raw.get("content_type")),
        observed_at=_parse_manifest_datetime(raw.get("observed_at"), "checkpoint.observed_at"),
        available_at=_parse_manifest_datetime(raw.get("available_at"), "checkpoint.available_at"),
        source_revision=source_revision_text,
    )


def _attempt_ref_from_dict(raw: Mapping[str, object], ordinal: int) -> InstrumentAttemptRef:
    if set(raw) != set(_ATTEMPT_REF_KEYS):
        raise InstrumentMasterDataError("checkpoint attempt ref schema drifted")
    if raw.get("ordinal") != ordinal:
        raise InstrumentMasterDataError("checkpoint attempt order drifted")
    values = tuple(raw.get(key) for key in ("capture_id", "object_id", "request", "checksum"))
    if not all(isinstance(value, str) and value for value in values):
        raise InstrumentMasterDataError("checkpoint attempt identity is invalid")
    source_revision = raw.get("source_revision")
    if source_revision is not None:
        _safe_id(source_revision, "source_revision")
    state = raw.get("state")
    if state not in {"ACCEPTED_RESPONSE", "REJECTED_RESPONSE", "TRANSPORT_ERROR"}:
        raise InstrumentMasterDataError("checkpoint attempt state is invalid")
    state_text = cast(str, state)
    source_revision_text = source_revision if isinstance(source_revision, str) else None
    return InstrumentAttemptRef(
        ordinal=ordinal,
        partition=str(raw.get("partition")),
        offset=_strict_int(raw.get("offset"), "checkpoint attempt offset"),
        attempt=_strict_int(raw.get("attempt"), "checkpoint attempt number", minimum=1),
        capture_id=cast(str, raw["capture_id"]),
        object_id=cast(str, raw["object_id"]),
        status_code=_strict_int(raw.get("status_code"), "checkpoint attempt status"),
        state=state_text,
        request=cast(str, raw["request"]),
        checksum=cast(str, raw["checksum"]),
        size=_strict_int(raw.get("size"), "checkpoint attempt size"),
        content_type=str(raw.get("content_type")),
        observed_at=_parse_manifest_datetime(raw.get("observed_at"), "checkpoint.observed_at"),
        available_at=_parse_manifest_datetime(raw.get("available_at"), "checkpoint.available_at"),
        source_revision=source_revision_text,
    )


class TushareInstrumentCollector:
    """Collect all fixed provider partitions into immutable raw storage."""

    def __init__(
        self,
        config: TushareInstrumentConfig,
        raw_storage: RawStorage,
        *,
        transport: TushareInstrumentTransport = _stdlib_http_transport,
        clock: Callable[[], datetime] = utc_now,
        sleeper: Callable[[float], None] = time_module.sleep,
    ) -> None:
        self._config = config
        self._raw = raw_storage
        self._transport = transport
        self._clock = clock
        self._sleeper = sleeper

    def _restore_checkpoint(
        self,
        run_id: str,
        collection_date: str,
    ) -> tuple[
        list[InstrumentPageRef],
        list[InstrumentAttemptRef],
        list[InstrumentMasterRecord],
        int,
        int,
        list[str],
        list[str],
    ]:
        """Restore the latest raw checkpoint before opening a provider call."""

        manifests = self._raw.list(TUSHARE_INSTRUMENT_SOURCE, collection_date)
        prefix = f"checkpoint-{uuid.UUID(run_id).hex}-"
        checkpoint_manifests: list[tuple[int, RawObjectManifest]] = []
        for item in manifests:
            if not item.capture_id.startswith(prefix) or item.run_id != run_id:
                continue
            suffix = item.capture_id[len(prefix) :]
            if not suffix.isdigit():
                raise InstrumentMasterDataError("checkpoint capture identity is invalid")
            checkpoint_manifests.append((int(suffix), item))
        checkpoint_manifests.sort(key=lambda pair: pair[0])
        if not checkpoint_manifests:
            return (
                [],
                [],
                [],
                0,
                0,
                [],
                [
                    item.capture_id
                    for item in manifests
                    if item.run_id == run_id and item.capture_id.startswith("manifest-")
                ],
            )
        if [ordinal for ordinal, _ in checkpoint_manifests] != list(
            range(len(checkpoint_manifests))
        ):
            raise InstrumentMasterDataError("checkpoint sequence is incomplete")
        latest_ordinal, latest_manifest = checkpoint_manifests[-1]
        body = self._raw.get(
            latest_manifest.object_id,
            checksum=latest_manifest.checksum,
            size=latest_manifest.size,
        )
        payload = _decode_json(body)
        if set(payload) != set(_CHECKPOINT_KEYS) or payload.get("kind") != "CHECKPOINT":
            raise InstrumentMasterDataError("checkpoint schema drifted")
        if (
            payload.get("capture_schema") != TUSHARE_INSTRUMENT_CAPTURE_VERSION
            or payload.get("source") != TUSHARE_INSTRUMENT_SOURCE
            or payload.get("profile_version") != TUSHARE_INSTRUMENT_PROFILE_VERSION
            or payload.get("schema_version") != TUSHARE_INSTRUMENT_SCHEMA_VERSION
            or payload.get("parser_version") != TUSHARE_INSTRUMENT_PARSER_VERSION
            or payload.get("run_id") != run_id
            or payload.get("manifest_date") != collection_date
            or payload.get("checkpoint_ordinal") != latest_ordinal
            or payload.get("source_revision") != self._config.source_revision
        ):
            raise InstrumentMasterDataError("checkpoint provenance drifted")
        next_partition = _strict_int(
            payload.get("next_partition_ordinal"), "checkpoint next partition"
        )
        next_offset = _strict_int(payload.get("next_offset"), "checkpoint next offset")
        if next_partition > len(TUSHARE_COLLECTION_PARTITIONS):
            raise InstrumentMasterDataError("checkpoint next partition is invalid")
        if next_partition == len(TUSHARE_COLLECTION_PARTITIONS) and next_offset != 0:
            raise InstrumentMasterDataError("complete checkpoint offset is invalid")
        raw_pages = payload.get("page_refs")
        raw_attempts = payload.get("attempt_refs")
        raw_records = payload.get("records")
        if not all(isinstance(value, list) for value in (raw_pages, raw_attempts, raw_records)):
            raise InstrumentMasterDataError("checkpoint refs are invalid")
        pages = [
            _page_ref_from_dict(cast(Mapping[str, object], value), index)
            for index, value in enumerate(cast(list[object], raw_pages))
            if isinstance(value, dict)
        ]
        if len(pages) != len(cast(list[object], raw_pages)):
            raise InstrumentMasterDataError("checkpoint page ref is invalid")
        attempts = [
            _attempt_ref_from_dict(cast(Mapping[str, object], value), index)
            for index, value in enumerate(cast(list[object], raw_attempts))
            if isinstance(value, dict)
        ]
        if len(attempts) != len(cast(list[object], raw_attempts)):
            raise InstrumentMasterDataError("checkpoint attempt ref is invalid")
        records: list[InstrumentMasterRecord] = []
        for value in cast(list[object], raw_records):
            if not isinstance(value, dict):
                raise InstrumentMasterDataError("checkpoint record is invalid")
            try:
                records.append(InstrumentMasterRecord.from_dict(cast(Mapping[str, object], value)))
            except (KeyError, TypeError, ValueError) as error:
                raise InstrumentMasterDataError("checkpoint record is invalid") from error
        by_capture = {item.capture_id: item for item in manifests}
        for page in pages:
            capture = by_capture.get(page.capture_id)
            if (
                capture is None
                or capture.run_id != run_id
                or capture.object_id != page.object_id
                or capture.checksum != page.checksum
                or capture.size != page.size
            ):
                raise InstrumentMasterDataError("checkpoint page provenance drifted")
            page_body = self._raw.get(
                capture.object_id, checksum=capture.checksum, size=capture.size
            )
            parsed = parse_tushare_instrument_page(
                page_body,
                api_name=page.api_name,
                status_partition=page.status_partition,
                market_partition=page.market_partition,
                observed_at=page.observed_at,
                available_at=page.available_at,
                evidence_ref=page.capture_id,
                source_revision=page.source_revision,
            )
            if len(parsed) != page.row_count:
                raise InstrumentMasterDataError("checkpoint page row count drifted")
        known_attempt_captures = {attempt.capture_id for attempt in attempts}
        historical_attempts: list[InstrumentAttemptRef] = []
        history_ids = [
            item.capture_id
            for item in manifests
            if item.run_id == run_id and item.capture_id.startswith("manifest-")
        ]
        for history_id in history_ids:
            history_manifest = by_capture[history_id]
            history_body = self._raw.get(
                history_manifest.object_id,
                checksum=history_manifest.checksum,
                size=history_manifest.size,
            )
            history_payload = _decode_json(history_body)
            raw_history_attempts = history_payload.get("attempt_refs")
            if not isinstance(raw_history_attempts, list):
                raise InstrumentMasterDataError("manifest history attempts are invalid")
            for index, value in enumerate(cast(list[object], raw_history_attempts)):
                if not isinstance(value, dict):
                    raise InstrumentMasterDataError("manifest history attempt is invalid")
                historical_attempt = _attempt_ref_from_dict(
                    cast(Mapping[str, object], value), index
                )
                if historical_attempt.capture_id not in known_attempt_captures:
                    known_attempt_captures.add(historical_attempt.capture_id)
                    historical_attempts.append(historical_attempt)
        attempts.extend(historical_attempts)
        attempts[:] = [replace(attempt, ordinal=index) for index, attempt in enumerate(attempts)]
        return (
            pages,
            attempts,
            records,
            next_partition,
            next_offset,
            [item.capture_id for _, item in checkpoint_manifests],
            [
                item.capture_id
                for item in manifests
                if item.run_id == run_id and item.capture_id.startswith("manifest-")
            ],
        )

    def _write_checkpoint(
        self,
        run_id: str,
        collection_date: str,
        ordinal: int,
        next_partition: int,
        next_offset: int,
        page_refs: list[InstrumentPageRef],
        attempt_refs: list[InstrumentAttemptRef],
        records: list[InstrumentMasterRecord],
    ) -> RawObjectManifest:
        payload = {
            "kind": "CHECKPOINT",
            "source": TUSHARE_INSTRUMENT_SOURCE,
            "profile_version": TUSHARE_INSTRUMENT_PROFILE_VERSION,
            "schema_version": TUSHARE_INSTRUMENT_SCHEMA_VERSION,
            "parser_version": TUSHARE_INSTRUMENT_PARSER_VERSION,
            "source_revision": self._config.source_revision,
            "run_id": run_id,
            "manifest_date": collection_date,
            "checkpoint_ordinal": ordinal,
            "next_partition_ordinal": next_partition,
            "next_offset": next_offset,
            "page_refs": [ref.to_dict() for ref in page_refs],
            "attempt_refs": [ref.to_dict() for ref in attempt_refs],
            "records": [record.to_dict() for record in records],
        }
        return self._raw.put(
            TUSHARE_INSTRUMENT_SOURCE,
            collection_date,
            f"PUT /tushare/runs/{run_id}/checkpoint/{ordinal}",
            _state_bytes(payload),
            "application/json; charset=utf-8",
            capture_id=_checkpoint_capture_id(run_id, ordinal),
            run_id=run_id,
            source_revision=self._config.source_revision,
            ingest_time=_aware(self._clock(), "collector clock"),
        )

    def collect(
        self,
        run_id: str | uuid.UUID | None = None,
        manifest_date: str | None = None,
    ) -> InstrumentMasterRunResult:
        run_text = _uuid_text(None if run_id is None else str(run_id))
        observed = _aware(self._clock(), "collector clock")
        collection_date = (
            observed.date().isoformat()
            if manifest_date is None
            else _validate_date(manifest_date, "manifest_date")
        )
        page_refs: list[InstrumentPageRef] = []
        attempt_refs: list[InstrumentAttemptRef] = []
        records: list[InstrumentMasterRecord] = []
        start_partition = 0
        start_offset = 0
        checkpoint_capture_ids: list[str] = []
        manifest_history: list[str] = []
        seen_codes: set[str] = set()
        reason_code = "COMPLETE"
        terminal = InstrumentMasterTerminal.COMPLETE
        try:
            (
                page_refs,
                attempt_refs,
                records,
                start_partition,
                start_offset,
                checkpoint_capture_ids,
                manifest_history,
            ) = self._restore_checkpoint(run_text, collection_date)
            seen_codes = {record.unified_code for record in records}
            for partition_ordinal, (api_name, status, market) in enumerate(
                TUSHARE_COLLECTION_PARTITIONS
            ):
                if partition_ordinal < start_partition:
                    continue
                offset = start_offset if partition_ordinal == start_partition else 0
                page_count = sum(
                    1
                    for page_ref in page_refs
                    if page_ref.api_name == api_name
                    and page_ref.status_partition == status
                    and page_ref.market_partition == market
                )
                partition_terminal = False
                while not partition_terminal:
                    if page_count >= self._config.max_pages:
                        # A page exactly at ``page_size`` is not itself a
                        # failure: the next offset can still provide the
                        # short page that proves partition termination.  The
                        # bound is only indeterminate when it is reached
                        # before such a terminal page arrives.
                        reason_code = "PROVIDER_PAGE_CAP_REACHED"
                        terminal = InstrumentMasterTerminal.INDETERMINATE
                        partition_terminal = True
                        continue
                    partition_name = f"{api_name}:{status}:{market or 'ALL'}"
                    previous_attempt = max(
                        (
                            attempt.attempt
                            for attempt in attempt_refs
                            if attempt.partition == partition_name and attempt.offset == offset
                        ),
                        default=0,
                    )
                    page, attempts = self._fetch_page(
                        run_text,
                        collection_date,
                        partition_ordinal,
                        api_name,
                        status,
                        market,
                        offset,
                        observed,
                        attempt_start=previous_attempt + 1,
                    )
                    attempt_base_ordinal = len(attempt_refs)
                    attempt_refs.extend(
                        replace(attempt, ordinal=attempt_base_ordinal + index)
                        for index, attempt in enumerate(attempts)
                    )
                    response, manifest, page_records = page
                    page_refs.append(
                        InstrumentPageRef(
                            ordinal=len(page_refs),
                            api_name=api_name,
                            status_partition=status,
                            market_partition=market,
                            offset=offset,
                            row_count=len(page_records),
                            capture_id=manifest.capture_id,
                            object_id=manifest.object_id,
                            checksum=manifest.checksum,
                            size=manifest.size,
                            request=manifest.request,
                            status_code=response.status_code,
                            content_type=manifest.content_type,
                            observed_at=manifest.ingest_time,
                            available_at=manifest.available_time or manifest.ingest_time,
                            source_revision=self._config.source_revision,
                        )
                    )
                    for record in page_records:
                        if record.unified_code in seen_codes:
                            raise InstrumentMasterDataError(
                                "duplicate instrument identity across partitions"
                            )
                        seen_codes.add(record.unified_code)
                        records.append(record)
                    page_count += 1
                    if len(page_records) < self._config.page_size:
                        partition_terminal = True
                        checkpoint_next_partition = partition_ordinal + 1
                        checkpoint_next_offset = 0
                    else:
                        # Continue to the next offset.  A full page is normal
                        # for a provider that paginates by ``limit``; only the
                        # configured page bound above prevents proving the
                        # partition's terminal page.
                        offset += self._config.page_size
                        checkpoint_next_partition = partition_ordinal
                        checkpoint_next_offset = offset
                    checkpoint = self._write_checkpoint(
                        run_text,
                        collection_date,
                        len(checkpoint_capture_ids),
                        checkpoint_next_partition,
                        checkpoint_next_offset,
                        page_refs,
                        attempt_refs,
                        records,
                    )
                    checkpoint_capture_ids.append(checkpoint.capture_id)
        except InstrumentMasterError as error:
            failed_attempts = getattr(error, "attempts", ())
            if failed_attempts:
                attempt_base_ordinal = len(attempt_refs)
                attempt_refs.extend(
                    replace(attempt, ordinal=attempt_base_ordinal + index)
                    for index, attempt in enumerate(failed_attempts)
                )
            reason_code = _reason_code(error)
            terminal = InstrumentMasterTerminal.FAILED

        completeness = (
            InstrumentMasterDisposition.COMPLETE
            if terminal is InstrumentMasterTerminal.COMPLETE and reason_code == "COMPLETE"
            else InstrumentMasterDisposition.INDETERMINATE
            if terminal is not InstrumentMasterTerminal.FAILED
            else InstrumentMasterDisposition.REJECTED
        )
        manifest_capture_id = _manifest_capture_id(run_text, len(manifest_history))
        manifest_payload = {
            "schema_version": TUSHARE_INSTRUMENT_SCHEMA_VERSION,
            "capture_version": TUSHARE_INSTRUMENT_CAPTURE_VERSION,
            "parser_version": TUSHARE_INSTRUMENT_PARSER_VERSION,
            "profile_version": TUSHARE_INSTRUMENT_PROFILE_VERSION,
            "source": TUSHARE_INSTRUMENT_SOURCE,
            "source_revision": self._config.source_revision,
            "run_id": run_text,
            "manifest_date": collection_date,
            "page_size": self._config.page_size,
            "max_pages": self._config.max_pages,
            "terminal": terminal.value,
            "completeness": completeness.value,
            "reason_code": reason_code,
            "partitions": [
                {
                    "ordinal": index,
                    "api_name": api_name,
                    "status_partition": status,
                    "market_partition": market,
                }
                for index, (api_name, status, market) in enumerate(TUSHARE_COLLECTION_PARTITIONS)
            ],
            "page_refs": [ref.to_dict() for ref in page_refs],
            "attempt_refs": [ref.to_dict() for ref in attempt_refs],
            "record_count": len(records),
            "checkpoint_refs": checkpoint_capture_ids,
            "manifest_history": manifest_history,
        }
        manifest = self._raw.put(
            TUSHARE_INSTRUMENT_SOURCE,
            collection_date,
            f"PUT /tushare/runs/{run_text}/manifest",
            _canonical_json(manifest_payload),
            "application/json; charset=utf-8",
            capture_id=manifest_capture_id,
            run_id=run_text,
            source_revision=self._config.source_revision,
            ingest_time=_aware(self._clock(), "collector clock"),
        )
        if manifest.capture_id != manifest_capture_id:
            raise RawIntegrityError("manifest capture identity drifted")
        return InstrumentMasterRunResult(
            run_id=run_text,
            manifest_date=collection_date,
            manifest_capture_id=manifest.capture_id,
            records=tuple(sorted(records, key=lambda record: record.unified_code)),
            page_refs=tuple(page_refs),
            attempt_refs=tuple(attempt_refs),
            terminal=terminal,
            completeness=completeness,
            reason_code=reason_code,
            source_revision=self._config.source_revision,
            checkpoint_capture_ids=tuple(checkpoint_capture_ids),
            manifest_history=tuple(manifest_history),
        )

    def _fetch_page(
        self,
        run_id: str,
        collection_date: str,
        partition_ordinal: int,
        api_name: str,
        status: str,
        market: str | None,
        offset: int,
        observed: datetime,
        attempt_start: int = 1,
    ) -> tuple[
        tuple[
            TushareInstrumentResponse,
            RawObjectManifest,
            tuple[InstrumentMasterRecord, ...],
        ],
        list[InstrumentAttemptRef],
    ]:
        attempts: list[InstrumentAttemptRef] = []
        request_path = _request_path(api_name, status, market, offset)
        payload = {
            "api_name": api_name,
            "token": self._config.token,
            "params": {
                "list_status" if api_name == "stock_basic" else "status": status,
                "offset": offset,
                "limit": self._config.page_size,
                **({"market": market} if market is not None else {}),
            },
            "fields": ",".join(
                TUSHARE_STOCK_BASIC_FIELDS
                if api_name == "stock_basic"
                else TUSHARE_FUND_BASIC_FIELDS
            ),
        }
        body = _canonical_json(payload)
        if type(attempt_start) is not int or attempt_start < 1:
            raise InstrumentMasterDataError("attempt start is invalid")
        for retry_index in range(self._config.max_attempts):
            attempt = attempt_start + retry_index
            capture_id = _page_capture_id(run_id, api_name, status, market, offset, attempt)
            attempt_number = len(attempts)
            try:
                response_value = self._transport(
                    self._config.endpoint,
                    {"Content-Type": "application/json; charset=utf-8"},
                    body,
                    self._config.timeout_seconds,
                )
                response = _coerce_response(response_value)
            except Exception as error:
                state = _state_bytes(
                    {
                        "run_id": run_id,
                        "partition": f"{api_name}:{status}:{market or 'ALL'}",
                        "offset": offset,
                        "attempt": attempt,
                        "state": "TRANSPORT_ERROR",
                    }
                )
                state_manifest = self._raw.put(
                    TUSHARE_INSTRUMENT_SOURCE,
                    collection_date,
                    request_path,
                    state,
                    "application/json; charset=utf-8",
                    capture_id=_attempt_capture_id(run_id, partition_ordinal, offset, attempt),
                    run_id=run_id,
                    source_revision=self._config.source_revision,
                    ingest_time=observed,
                )
                attempts.append(
                    InstrumentAttemptRef(
                        ordinal=attempt_number,
                        partition=f"{api_name}:{status}:{market or 'ALL'}",
                        offset=offset,
                        attempt=attempt,
                        capture_id=state_manifest.capture_id,
                        object_id=state_manifest.object_id,
                        status_code=0,
                        state="TRANSPORT_ERROR",
                        request=state_manifest.request,
                        checksum=state_manifest.checksum,
                        size=state_manifest.size,
                        content_type=state_manifest.content_type,
                        observed_at=state_manifest.ingest_time,
                        available_at=state_manifest.received_at,
                        source_revision=state_manifest.source_revision,
                    )
                )
                if attempt >= self._config.max_attempts:
                    raise _InstrumentMasterFetchError(
                        "provider request failed", tuple(attempts), transport=True
                    ) from error
                self._sleeper(self._config.retry_backoff_seconds * (2**retry_index))
                continue

            response_manifest = self._raw.put(
                TUSHARE_INSTRUMENT_SOURCE,
                collection_date,
                request_path,
                response.body,
                response.content_type,
                capture_id=capture_id,
                run_id=run_id,
                source_revision=self._config.source_revision,
                ingest_time=observed,
            )
            attempts.append(
                InstrumentAttemptRef(
                    ordinal=attempt_number,
                    partition=f"{api_name}:{status}:{market or 'ALL'}",
                    offset=offset,
                    attempt=attempt,
                    capture_id=response_manifest.capture_id,
                    object_id=response_manifest.object_id,
                    status_code=response.status_code,
                    state="REJECTED_RESPONSE",
                    request=response_manifest.request,
                    checksum=response_manifest.checksum,
                    size=response_manifest.size,
                    content_type=response_manifest.content_type,
                    observed_at=response_manifest.ingest_time,
                    available_at=response_manifest.received_at,
                    source_revision=response_manifest.source_revision,
                )
            )
            if response.redirected or not 200 <= response.status_code < 300:
                if (
                    response.status_code in _TRANSIENT_HTTP_STATUS
                    and attempt < self._config.max_attempts
                ):
                    self._sleeper(self._config.retry_backoff_seconds * (2**retry_index))
                    continue
                raise _InstrumentMasterFetchError(
                    "provider HTTP response was not accepted", tuple(attempts), transport=True
                )
            if response_manifest.content_type.split(";", 1)[0] != "application/json":
                raise _InstrumentMasterFetchError(
                    "provider response MIME type is invalid", tuple(attempts), transport=False
                )
            try:
                page_records = parse_tushare_instrument_page(
                    response.body,
                    api_name=api_name,
                    status_partition=status,
                    market_partition=market,
                    observed_at=response_manifest.ingest_time,
                    available_at=response_manifest.available_time or response_manifest.ingest_time,
                    evidence_ref=response_manifest.capture_id,
                    source_revision=self._config.source_revision,
                )
            except InstrumentMasterError as error:
                raise _InstrumentMasterFetchError(
                    str(error), tuple(attempts), transport=False
                ) from error
            attempts[-1] = replace(attempts[-1], state="ACCEPTED_RESPONSE")
            return (response, response_manifest, page_records), attempts
        raise _InstrumentMasterFetchError(
            "provider retry budget exhausted", tuple(attempts), transport=True
        )


# The shorter name is useful to callers that treat the provider as an
# instrument-master collector, while the explicit name remains canonical.
InstrumentMasterCollector = TushareInstrumentCollector


def _reason_code(error: BaseException) -> str:
    if isinstance(error, _InstrumentMasterFetchError):
        return "TRANSPORT_FAILED" if error.transport else "DATA_REJECTED"
    if isinstance(error, InstrumentMasterDataError):
        message = str(error)
        if "duplicate" in message:
            return "IDENTITY_CONFLICT"
        if "page bound" in message:
            return "PAGE_BOUND_REACHED"
        if "provider" in message and "drift" in message:
            return "SCHEMA_DRIFT"
        return "DATA_REJECTED"
    if isinstance(error, InstrumentMasterTransportError):
        return "TRANSPORT_FAILED"
    return "COLLECTION_FAILED"


def _result_from_manifest(
    raw_storage: RawStorage,
    manifest: RawObjectManifest,
    payload: Mapping[str, object],
) -> InstrumentMasterRunResult:
    expected_keys = {
        "schema_version",
        "capture_version",
        "parser_version",
        "profile_version",
        "source",
        "source_revision",
        "run_id",
        "manifest_date",
        "page_size",
        "max_pages",
        "terminal",
        "completeness",
        "reason_code",
        "partitions",
        "page_refs",
        "attempt_refs",
        "record_count",
        "checkpoint_refs",
        "manifest_history",
    }
    if set(payload) != expected_keys:
        raise InstrumentMasterDataError("run manifest schema drifted")
    if (
        payload["schema_version"] != TUSHARE_INSTRUMENT_SCHEMA_VERSION
        or payload["capture_version"] != TUSHARE_INSTRUMENT_CAPTURE_VERSION
    ):
        raise InstrumentMasterDataError("run manifest version is unsupported")
    if (
        payload["parser_version"] != TUSHARE_INSTRUMENT_PARSER_VERSION
        or payload["profile_version"] != TUSHARE_INSTRUMENT_PROFILE_VERSION
    ):
        raise InstrumentMasterDataError("run manifest contract version is unsupported")
    run_id = _uuid_text(str(payload["run_id"]))
    if manifest.run_id != run_id:
        raise InstrumentMasterDataError("run manifest identity drifted")
    manifest_date = _validate_date(payload["manifest_date"], "manifest_date")
    if manifest.date != manifest_date or payload["source"] != TUSHARE_INSTRUMENT_SOURCE:
        raise InstrumentMasterDataError("run manifest partition drifted")
    page_size = payload["page_size"]
    max_pages = payload["max_pages"]
    if type(page_size) is not int or not 1 <= page_size <= 5000:
        raise InstrumentMasterDataError("run manifest page size is invalid")
    if type(max_pages) is not int or not 1 <= max_pages <= 1000:
        raise InstrumentMasterDataError("run manifest page bound is invalid")
    source_revision_value = payload["source_revision"]
    if source_revision_value is not None and not isinstance(source_revision_value, str):
        raise InstrumentMasterDataError("run manifest source revision is invalid")
    source_revision = source_revision_value
    if source_revision is not None:
        _safe_id(source_revision, "source_revision")
    if manifest.source_revision != source_revision:
        raise InstrumentMasterDataError("run manifest source revision drifted")
    if manifest.content_type.split(";", 1)[0] != "application/json":
        raise InstrumentMasterDataError("run manifest MIME type is invalid")
    expected_manifest_request = sanitize_request_identity(f"PUT /tushare/runs/{run_id}/manifest")
    if manifest.request != expected_manifest_request:
        raise InstrumentMasterDataError("run manifest request identity drifted")
    partitions = payload["partitions"]
    expected_partitions = [
        {
            "ordinal": index,
            "api_name": api_name,
            "status_partition": status,
            "market_partition": market,
        }
        for index, (api_name, status, market) in enumerate(TUSHARE_COLLECTION_PARTITIONS)
    ]
    if partitions != expected_partitions:
        raise InstrumentMasterDataError("run manifest partition order drifted")
    raw_page_refs = payload["page_refs"]
    raw_attempt_refs = payload["attempt_refs"]
    raw_checkpoint_refs = payload["checkpoint_refs"]
    raw_manifest_history = payload["manifest_history"]
    if not all(
        isinstance(value, list)
        for value in (raw_page_refs, raw_attempt_refs, raw_checkpoint_refs, raw_manifest_history)
    ):
        raise InstrumentMasterDataError("run manifest refs are invalid")
    listed = raw_storage.list(TUSHARE_INSTRUMENT_SOURCE, manifest_date)
    by_capture = {item.capture_id: item for item in listed}
    pages: list[InstrumentPageRef] = []
    records: list[InstrumentMasterRecord] = []
    seen_codes: set[str] = set()
    last_partition: tuple[str, str, str | None] | None = None
    last_offset = -1
    last_row_count = 0
    expected_partition_index = -1
    seen_partitions: set[tuple[str, str, str | None]] = set()
    partition_last_row_counts: dict[tuple[str, str, str | None], int] = {}
    history_ids: list[str] = []
    for value in cast(list[object], raw_manifest_history):
        if not isinstance(value, str) or not value.startswith("manifest-"):
            raise InstrumentMasterDataError("run manifest history is invalid")
        if value == manifest.capture_id or value in history_ids or value not in by_capture:
            raise InstrumentMasterDataError("run manifest history is invalid")
        if by_capture[value].run_id != run_id:
            raise InstrumentMasterDataError("run manifest history provenance drifted")
        history_ids.append(value)
    checkpoint_ids: list[str] = []
    for value in cast(list[object], raw_checkpoint_refs):
        if not isinstance(value, str) or not value.startswith("checkpoint-"):
            raise InstrumentMasterDataError("run manifest checkpoint refs are invalid")
        if value in checkpoint_ids or value not in by_capture:
            raise InstrumentMasterDataError("run manifest checkpoint ref is missing")
        checkpoint_manifest = by_capture[value]
        if checkpoint_manifest.run_id != run_id:
            raise InstrumentMasterDataError("run manifest checkpoint provenance drifted")
        checkpoint_body = raw_storage.get(
            checkpoint_manifest.object_id,
            checksum=checkpoint_manifest.checksum,
            size=checkpoint_manifest.size,
        )
        checkpoint_payload = _decode_json(checkpoint_body)
        if (
            checkpoint_payload.get("capture_schema") != TUSHARE_INSTRUMENT_CAPTURE_VERSION
            or checkpoint_payload.get("kind") != "CHECKPOINT"
            or checkpoint_payload.get("run_id") != run_id
            or checkpoint_payload.get("manifest_date") != manifest_date
        ):
            raise InstrumentMasterDataError("run manifest checkpoint is invalid")
        checkpoint_ids.append(value)
    referenced_capture_ids: set[str] = {
        manifest.capture_id,
        *history_ids,
        *checkpoint_ids,
    }
    page_capture_ids: set[str] = set()
    page_ref_values = cast(list[object], raw_page_refs)
    for ref_index, raw_ref in enumerate(page_ref_values):
        if not isinstance(raw_ref, dict):
            raise InstrumentMasterDataError("run manifest page ref is invalid")
        raw_ref = cast(dict[str, object], raw_ref)
        if set(raw_ref) != set(_PAGE_REF_KEYS):
            raise InstrumentMasterDataError("run manifest page ref schema drifted")
        if raw_ref.get("ordinal") != ref_index:
            raise InstrumentMasterDataError("run manifest page order drifted")
        api_name = raw_ref.get("api_name")
        status = raw_ref.get("status_partition")
        market = raw_ref.get("market_partition")
        if not isinstance(api_name, str) or not isinstance(status, str):
            raise InstrumentMasterDataError("run manifest page partition is invalid")
        if market is not None and not isinstance(market, str):
            raise InstrumentMasterDataError("run manifest page partition is invalid")
        partition = (api_name, status, market)
        if partition != last_partition:
            try:
                partition_index = TUSHARE_COLLECTION_PARTITIONS.index((api_name, status, market))
            except ValueError as error:
                raise InstrumentMasterDataError("run manifest page partition is invalid") from error
            if partition_index <= expected_partition_index:
                raise InstrumentMasterDataError("run manifest partition order drifted")
            expected_partition_index = partition_index
            last_partition = partition
            seen_partitions.add(last_partition)
            last_offset = -1
            last_row_count = 0
        offset = raw_ref.get("offset")
        if not isinstance(offset, int) or offset < 0 or offset <= last_offset:
            raise InstrumentMasterDataError("run manifest offsets are not monotonic")
        if last_offset >= 0:
            if last_row_count < page_size or offset != last_offset + page_size:
                raise InstrumentMasterDataError("run manifest page sequence is invalid")
        elif offset != 0:
            raise InstrumentMasterDataError("run manifest partition must start at offset zero")
        last_offset = offset
        capture_id = raw_ref.get("capture_id")
        if not isinstance(capture_id, str) or capture_id not in by_capture:
            raise InstrumentMasterDataError("run manifest page capture is missing")
        if capture_id in referenced_capture_ids:
            raise InstrumentMasterDataError("run manifest capture is duplicated")
        referenced_capture_ids.add(capture_id)
        page_capture_ids.add(capture_id)
        page_manifest = by_capture[capture_id]
        if page_manifest.run_id != run_id or page_manifest.source_revision != source_revision:
            raise InstrumentMasterDataError("page capture provenance drifted")
        if (
            page_manifest.object_id != raw_ref.get("object_id")
            or page_manifest.size != raw_ref.get("size")
            or page_manifest.checksum != raw_ref.get("checksum")
            or page_manifest.request != raw_ref.get("request")
        ):
            raise InstrumentMasterDataError("page capture checksum or size drifted")
        body = raw_storage.get(
            page_manifest.object_id,
            checksum=page_manifest.checksum,
            size=page_manifest.size,
        )
        observed = _parse_manifest_datetime(raw_ref.get("observed_at"), "observed_at")
        available = _parse_manifest_datetime(raw_ref.get("available_at"), "available_at")
        if available < observed:
            raise InstrumentMasterDataError("page capture timeline is invalid")
        if page_manifest.ingest_time != observed or page_manifest.available_time != available:
            raise InstrumentMasterDataError("page capture timeline drifted")
        if page_manifest.content_type != str(raw_ref.get("content_type")):
            raise InstrumentMasterDataError("page capture MIME drifted")
        expected_page_request = sanitize_request_identity(
            _request_path(api_name, status, market, offset)
        )
        if page_manifest.request != expected_page_request:
            raise InstrumentMasterDataError("page request identity drifted")
        partition_page_count = sum(
            1
            for existing_page in pages
            if (
                existing_page.api_name,
                existing_page.status_partition,
                existing_page.market_partition,
            )
            == (
                api_name,
                status,
                market,
            )
        )
        if partition_page_count >= max_pages:
            raise InstrumentMasterDataError("run manifest page bound reached")
        page_records = parse_tushare_instrument_page(
            body,
            api_name=api_name,
            status_partition=status,
            market_partition=market,
            observed_at=observed,
            available_at=available,
            evidence_ref=capture_id,
            source_revision=source_revision,
        )
        raw_status_code = raw_ref.get("status_code")
        if type(raw_status_code) is not int or raw_status_code != 200:
            raise InstrumentMasterDataError("page response status is invalid")
        raw_row_count = raw_ref.get("row_count")
        if type(raw_row_count) is not int or raw_row_count != len(page_records):
            raise InstrumentMasterDataError("page row count drifted")
        last_row_count = len(page_records)
        partition_last_row_counts[partition] = last_row_count
        for record in page_records:
            if record.unified_code in seen_codes:
                raise InstrumentMasterDataError("duplicate instrument identity across replay pages")
            seen_codes.add(record.unified_code)
            records.append(record)
        pages.append(
            InstrumentPageRef(
                ordinal=ref_index,
                api_name=api_name,
                status_partition=status,
                market_partition=market,
                offset=offset,
                row_count=len(page_records),
                capture_id=capture_id,
                object_id=page_manifest.object_id,
                checksum=page_manifest.checksum,
                size=page_manifest.size,
                request=page_manifest.request,
                status_code=raw_status_code,
                content_type=page_manifest.content_type,
                observed_at=observed,
                available_at=available,
                source_revision=source_revision,
            )
        )
    raw_record_count = payload["record_count"]
    if type(raw_record_count) is not int or raw_record_count != len(records):
        raise InstrumentMasterDataError("run manifest record count drifted")
    attempts: list[InstrumentAttemptRef] = []
    attempt_capture_ids: set[str] = set()
    attempt_ref_values = cast(list[object], raw_attempt_refs)
    for attempt_index, raw_attempt in enumerate(attempt_ref_values):
        if not isinstance(raw_attempt, dict):
            raise InstrumentMasterDataError("run manifest attempt ref is invalid")
        raw_attempt = cast(dict[str, object], raw_attempt)
        if set(raw_attempt) != set(_ATTEMPT_REF_KEYS):
            raise InstrumentMasterDataError("run manifest attempt ref schema drifted")
        if raw_attempt.get("ordinal") != attempt_index:
            raise InstrumentMasterDataError("run manifest attempt order drifted")
        capture_id = raw_attempt.get("capture_id")
        if not isinstance(capture_id, str) or capture_id not in by_capture:
            raise InstrumentMasterDataError("run manifest attempt capture is missing")
        if capture_id in attempt_capture_ids:
            raise InstrumentMasterDataError("run manifest capture is duplicated")
        attempt_capture_ids.add(capture_id)
        attempt_manifest = by_capture[capture_id]
        raw_attempt_body = raw_storage.get(
            attempt_manifest.object_id,
            checksum=attempt_manifest.checksum,
            size=attempt_manifest.size,
        )
        if attempt_manifest.run_id != run_id:
            raise InstrumentMasterDataError("attempt capture provenance drifted")
        attempt_state = raw_attempt.get("state")
        if attempt_state not in {
            "ACCEPTED_RESPONSE",
            "REJECTED_RESPONSE",
            "TRANSPORT_ERROR",
        }:
            raise InstrumentMasterDataError("run manifest attempt state is invalid")
        attempt_state_text = cast(str, attempt_state)
        if (
            attempt_manifest.object_id != raw_attempt.get("object_id")
            or attempt_manifest.checksum != raw_attempt.get("checksum")
            or attempt_manifest.size != raw_attempt.get("size")
            or attempt_manifest.request != raw_attempt.get("request")
            or attempt_manifest.content_type != raw_attempt.get("content_type")
            or attempt_manifest.source_revision != source_revision
        ):
            raise InstrumentMasterDataError("attempt capture metadata drifted")
        observed = _parse_manifest_datetime(raw_attempt.get("observed_at"), "observed_at")
        available = _parse_manifest_datetime(raw_attempt.get("available_at"), "available_at")
        if attempt_manifest.ingest_time != observed or attempt_manifest.available_time != available:
            raise InstrumentMasterDataError("attempt capture timeline drifted")
        if available < observed:
            raise InstrumentMasterDataError("attempt capture timeline is invalid")
        if attempt_state == "TRANSPORT_ERROR":
            decoded = _decode_json(raw_attempt_body)
            if decoded.get("state") != "TRANSPORT_ERROR":
                raise InstrumentMasterDataError("attempt state drifted")
        partition_text = raw_attempt.get("partition")
        if not isinstance(partition_text, str):
            raise InstrumentMasterDataError("run manifest attempt partition is invalid")
        partition_parts = partition_text.split(":")
        if len(partition_parts) != 3 or partition_parts[0] not in {"stock_basic", "fund_basic"}:
            raise InstrumentMasterDataError("run manifest attempt partition is invalid")
        market_value = None if partition_parts[2] == "ALL" else partition_parts[2]
        if (
            partition_parts[0],
            partition_parts[1],
            market_value,
        ) not in TUSHARE_COLLECTION_PARTITIONS:
            raise InstrumentMasterDataError("run manifest attempt partition is invalid")
        raw_offset = raw_attempt.get("offset")
        raw_attempt_number = raw_attempt.get("attempt")
        if (
            type(raw_offset) is not int
            or raw_offset < 0
            or type(raw_attempt_number) is not int
            or raw_attempt_number < 1
        ):
            raise InstrumentMasterDataError("run manifest attempt coordinates are invalid")
        try:
            expected_request = _request_path(
                partition_parts[0], partition_parts[1], market_value, raw_offset
            )
        except (TypeError, ValueError) as error:
            raise InstrumentMasterDataError("run manifest attempt route is invalid") from error
        if attempt_manifest.request != sanitize_request_identity(expected_request):
            raise InstrumentMasterDataError("attempt request identity drifted")
        raw_status_code = raw_attempt.get("status_code")
        if type(raw_status_code) is not int or not 0 <= raw_status_code <= 599:
            raise InstrumentMasterDataError("run manifest attempt status is invalid")
        if attempt_state == "TRANSPORT_ERROR" and (
            raw_status_code != 0
            or capture_id
            != _attempt_capture_id(
                run_id,
                TUSHARE_COLLECTION_PARTITIONS.index(
                    (partition_parts[0], partition_parts[1], market_value)
                ),
                raw_offset,
                raw_attempt_number,
            )
        ):
            raise InstrumentMasterDataError("transport attempt identity is invalid")
        attempts.append(
            InstrumentAttemptRef(
                ordinal=attempt_index,
                partition=partition_text,
                offset=raw_offset,
                attempt=raw_attempt_number,
                capture_id=capture_id,
                object_id=attempt_manifest.object_id,
                status_code=raw_status_code,
                state=attempt_state_text,
                request=attempt_manifest.request,
                checksum=attempt_manifest.checksum,
                size=attempt_manifest.size,
                content_type=attempt_manifest.content_type,
                observed_at=observed,
                available_at=available,
                source_revision=attempt_manifest.source_revision,
            )
        )
    run_captures = {item.capture_id for item in listed if item.run_id == run_id}
    if run_captures != referenced_capture_ids | attempt_capture_ids:
        raise InstrumentMasterDataError("run manifest does not cover every capture")
    response_attempt_ids = {
        item.capture_id for item in attempts if item.state == "ACCEPTED_RESPONSE"
    }
    if page_capture_ids != response_attempt_ids:
        raise InstrumentMasterDataError("run manifest page attempts are incomplete")
    page_by_key = {
        (page.api_name, page.status_partition, page.market_partition, page.offset): page
        for page in pages
    }
    attempts_by_key: dict[tuple[str, str, str | None, int], list[InstrumentAttemptRef]] = {}
    for attempt in attempts:
        partition_parts = attempt.partition.split(":")
        market_value = None if partition_parts[2] == "ALL" else partition_parts[2]
        key = (partition_parts[0], partition_parts[1], market_value, attempt.offset)
        attempts_by_key.setdefault(key, []).append(attempt)
        if attempt.state == "ACCEPTED_RESPONSE":
            page = page_by_key.get(key)
            if (
                page is None
                or page.capture_id != attempt.capture_id
                or page.object_id != attempt.object_id
                or page.checksum != attempt.checksum
                or page.size != attempt.size
                or page.request != attempt.request
                or page.status_code != attempt.status_code
                or page.content_type != attempt.content_type
                or page.observed_at != attempt.observed_at
                or page.available_at != attempt.available_at
                or page.source_revision != attempt.source_revision
            ):
                raise InstrumentMasterDataError("accepted attempt does not bind to page")
            if attempt.capture_id != _page_capture_id(
                run_id,
                partition_parts[0],
                partition_parts[1],
                market_value,
                attempt.offset,
                attempt.attempt,
            ):
                raise InstrumentMasterDataError("accepted attempt identity is invalid")
    for grouped_attempts in attempts_by_key.values():
        ordered = sorted(grouped_attempts, key=lambda item: item.attempt)
        if [item.attempt for item in ordered] != list(range(1, ordered[-1].attempt + 1)):
            raise InstrumentMasterDataError("run manifest attempt sequence is incomplete")
        accepted_count = sum(item.state == "ACCEPTED_RESPONSE" for item in ordered)
        if accepted_count:
            if accepted_count != 1 or ordered[-1].state != "ACCEPTED_RESPONSE":
                raise InstrumentMasterDataError("run manifest accepted attempt is invalid")
            if any(item.state == "ACCEPTED_RESPONSE" for item in ordered[:-1]):
                raise InstrumentMasterDataError("run manifest has attempts after acceptance")
    try:
        terminal = InstrumentMasterTerminal(str(payload["terminal"]))
        completeness = InstrumentMasterDisposition(str(payload["completeness"]))
    except ValueError as error:
        raise InstrumentMasterDataError("run manifest disposition is invalid") from error
    if terminal is InstrumentMasterTerminal.COMPLETE:
        if set(attempts_by_key) != set(page_by_key):
            raise InstrumentMasterDataError("complete run attempt/page graph is incomplete")
        if (
            completeness is not InstrumentMasterDisposition.COMPLETE
            or str(payload["reason_code"]) != "COMPLETE"
        ):
            raise InstrumentMasterDataError("complete terminal state is inconsistent")
        if expected_partition_index != len(TUSHARE_COLLECTION_PARTITIONS) - 1:
            raise InstrumentMasterDataError("complete run is missing a fixed partition")
        if seen_partitions != set(TUSHARE_COLLECTION_PARTITIONS):
            raise InstrumentMasterDataError("complete run is missing a partition page")
        if any(
            partition_last_row_counts.get(partition, page_size) >= page_size
            for partition in TUSHARE_COLLECTION_PARTITIONS
        ):
            raise InstrumentMasterDataError("complete run is missing a terminal short page")
    elif terminal is InstrumentMasterTerminal.INDETERMINATE:
        if completeness is not InstrumentMasterDisposition.INDETERMINATE:
            raise InstrumentMasterDataError("indeterminate terminal state is inconsistent")
    elif completeness is not InstrumentMasterDisposition.REJECTED:
        raise InstrumentMasterDataError("failed terminal state is inconsistent")
    return InstrumentMasterRunResult(
        run_id=run_id,
        manifest_date=manifest_date,
        manifest_capture_id=manifest.capture_id,
        records=tuple(sorted(records, key=lambda record: record.unified_code)),
        page_refs=tuple(pages),
        attempt_refs=tuple(attempts),
        terminal=terminal,
        completeness=completeness,
        reason_code=str(payload["reason_code"]),
        source_revision=source_revision,
        checkpoint_capture_ids=tuple(checkpoint_ids),
        manifest_history=tuple(history_ids),
    )


def _parse_manifest_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise InstrumentMasterDataError(f"manifest {field_name} is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise InstrumentMasterDataError(f"manifest {field_name} is invalid") from error
    return _aware(parsed, field_name)


def replay_tushare_instrument_master_run(
    raw_storage: RawStorage,
    *,
    run_id: str | uuid.UUID,
    manifest_date: str,
    manifest_capture_id: str,
) -> InstrumentMasterRunResult:
    """Reconstruct a run without creating a transport or reading credentials."""

    run_text = _uuid_text(str(run_id))
    capture_id = _safe_id(manifest_capture_id, "manifest_capture_id")
    date_text = _validate_date(manifest_date, "manifest_date")
    manifests = raw_storage.list(TUSHARE_INSTRUMENT_SOURCE, date_text)
    manifest = next((item for item in manifests if item.capture_id == capture_id), None)
    if manifest is None:
        raise InstrumentMasterDataError("run manifest was not found")
    if manifest.run_id != run_text:
        raise InstrumentMasterDataError("run manifest run_id does not match")
    raw_bytes = raw_storage.get(manifest.object_id, checksum=manifest.checksum, size=manifest.size)
    payload = _decode_json(raw_bytes)
    return _result_from_manifest(raw_storage, manifest, payload)


def replay_instrument_master_run(
    raw_storage: RawStorage,
    run_id: str | uuid.UUID,
    manifest_date: str,
    manifest_capture_id: str,
) -> InstrumentMasterRunResult:
    """Positional compatibility alias for repository/runtime callers."""

    return replay_tushare_instrument_master_run(
        raw_storage,
        run_id=run_id,
        manifest_date=manifest_date,
        manifest_capture_id=manifest_capture_id,
    )


__all__ = [
    "InstrumentAttemptRef",
    "InstrumentMasterCollector",
    "InstrumentMasterDataError",
    "InstrumentMasterDisposition",
    "InstrumentMasterError",
    "InstrumentMasterRunResult",
    "InstrumentMasterTerminal",
    "InstrumentMasterTransportError",
    "InstrumentPageRef",
    "TUSHARE_API_ENDPOINT",
    "TUSHARE_COLLECTION_PARTITIONS",
    "TUSHARE_FUND_BASIC_FIELDS",
    "TUSHARE_INSTRUMENT_CAPTURE_VERSION",
    "TUSHARE_INSTRUMENT_PARSER_VERSION",
    "TUSHARE_INSTRUMENT_PROFILE_VERSION",
    "TUSHARE_INSTRUMENT_SCHEMA_VERSION",
    "TUSHARE_INSTRUMENT_SOURCE",
    "TUSHARE_STOCK_BASIC_FIELDS",
    "TushareInstrumentCollector",
    "TushareInstrumentConfig",
    "TushareInstrumentResponse",
    "TushareInstrumentTransport",
    "parse_tushare_instrument_page",
    "parse_instrument_page",
    "replay_instrument_master_run",
    "replay_tushare_instrument_master",
    "replay_tushare_instrument_master_run",
]


parse_instrument_page = parse_tushare_instrument_page
replay_tushare_instrument_master = replay_tushare_instrument_master_run
