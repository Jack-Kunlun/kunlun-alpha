"""ClickHouse HTTP writer for canonical versioned market bars."""

from __future__ import annotations

import json
import re
import time as time_module
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import cast
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from market_core.storage.storage import StoredBar

HttpTransport = Callable[[str, Mapping[str, str], bytes, float], tuple[int, bytes]]
QueryTransport = Callable[[str, Mapping[str, str], bytes, float], tuple[int, bytes]]
Sleeper = Callable[[float], None]

_DATABASE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TABLES = {
    "DAILY": "bars_daily_v2",
    "MINUTE_1": "bars_minute_v2",
    "MINUTE_5": "bars_minute_v2",
}
_CNY_CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class ClickHouseBarConfig:
    """Connection settings for the canonical Bar tables."""

    url: str
    database: str
    user: str
    password: str | None = field(default=None, repr=False)
    timeout_seconds: float = 5.0
    max_attempts: int = 3
    retry_backoff_seconds: float = 0.25

    def __post_init__(self) -> None:
        url = self.url.strip().rstrip("/")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an HTTP(S) endpoint")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("url must not contain credentials")
        if not _DATABASE_IDENTIFIER.fullmatch(self.database):
            raise ValueError("database must be a safe ClickHouse identifier")
        if not self.user.strip():
            raise ValueError("user must be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
        object.__setattr__(self, "url", url)


def _database_url(config: ClickHouseBarConfig) -> str:
    parsed = urlsplit(config.url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["database"] = config.database
    return urlunsplit(parsed._replace(query=urlencode(query)))


def _stdlib_http_transport(
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    timeout_seconds: float,
) -> tuple[int, bytes]:
    request = Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            return int(response.status), response.read()
    except HTTPError as error:
        return error.code, b""


def _utc_milliseconds(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("ClickHouse timestamps must be timezone-aware")
    utc_value = value.astimezone(UTC)
    return utc_value.strftime("%Y-%m-%d %H:%M:%S.") + f"{utc_value.microsecond // 1000:03d}"


def _cny_amount(value: Decimal) -> str:
    """Render a stored amount explicitly at the ClickHouse CNY-cent scale."""

    return format(value.quantize(_CNY_CENT, rounding=ROUND_HALF_UP), ".2f")


def _row(stored: StoredBar) -> dict[str, object]:
    assert isinstance(stored.event_time, datetime)
    assert isinstance(stored.available_time, datetime)
    assert isinstance(stored.ingest_time, datetime)
    assert isinstance(stored.processing_time, datetime)
    return {
        "unified_code": stored.unified_code,
        "exchange": stored.exchange,
        "interval": stored.interval,
        "event_time": _utc_milliseconds(stored.event_time),
        "session": stored.session,
        "price_type": stored.price_type,
        "data_version": stored.data_version,
        "source": stored.source,
        "source_version": stored.source_version,
        "raw_capture_id": stored.raw_capture_id,
        "available_time": _utc_milliseconds(stored.available_time),
        "ingest_time": _utc_milliseconds(stored.ingest_time),
        "processing_time": _utc_milliseconds(stored.processing_time),
        "replacement_version": stored.replacement_version,
        "date": stored.date,
        "open": str(stored.open),
        "high": str(stored.high),
        "low": str(stored.low),
        "close": str(stored.close),
        "volume": stored.volume,
        "amount": _cny_amount(stored.amount),
        "suspended": 1 if stored.suspended else 0,
    }


def _sql_string(value: str) -> str:
    """Render a bounded SQL string literal without interpolating credentials."""

    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _sql_timestamp(value: str) -> str:
    return f"parseDateTime64BestEffort({_sql_string(value)}, 3, 'UTC')"


def _sql_decimal(value: str, scale: int, precision: int) -> str:
    return f"CAST({_sql_string(value)} AS Decimal({precision}, {scale}))"


def _confirmation_query(table: str, stored: StoredBar) -> bytes:
    """Build an exact-row evidence query for an uncertain INSERT response."""

    row = _row(stored)
    clauses = [
        f"unified_code = {_sql_string(str(row['unified_code']))}",
        f"exchange = {_sql_string(str(row['exchange']))}",
        f"interval = {_sql_string(str(row['interval']))}",
        f"event_time = {_sql_timestamp(str(row['event_time']))}",
        f"session = {_sql_string(str(row['session']))}",
        f"price_type = {_sql_string(str(row['price_type']))}",
        f"data_version = {_sql_string(str(row['data_version']))}",
        f"source = {_sql_string(str(row['source']))}",
        f"source_version = {_sql_string(str(row['source_version']))}",
        f"raw_capture_id = {_sql_string(str(row['raw_capture_id']))}",
        f"available_time = {_sql_timestamp(str(row['available_time']))}",
        f"ingest_time = {_sql_timestamp(str(row['ingest_time']))}",
        f"processing_time = {_sql_timestamp(str(row['processing_time']))}",
        f"replacement_version = {int(cast(int, row['replacement_version']))}",
        f"date = toDate({_sql_string(str(row['date']))})",
        f"open = {_sql_decimal(str(row['open']), 4, 20)}",
        f"high = {_sql_decimal(str(row['high']), 4, 20)}",
        f"low = {_sql_decimal(str(row['low']), 4, 20)}",
        f"close = {_sql_decimal(str(row['close']), 4, 20)}",
        f"volume = {int(cast(int, row['volume']))}",
        f"amount = {_sql_decimal(str(row['amount']), 2, 30)}",
        f"suspended = {int(cast(int, row['suspended']))}",
    ]
    return (
        f"SELECT count() AS row_count, uniqExact(revision_fingerprint) AS fingerprint_count "
        f"FROM {table} WHERE " + " AND ".join(clauses) + " FORMAT JSONEachRow\n"
    ).encode("utf-8")


def _confirmation_result(body: bytes) -> bool:
    rows = [line for line in body.decode("utf-8").splitlines() if line.strip()]
    if len(rows) != 1:
        return False
    try:
        value = json.loads(rows[0])
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(value, dict):
        return False
    payload = cast(dict[str, object], value)
    row_count = payload.get("row_count")
    fingerprint_count = payload.get("fingerprint_count")
    if isinstance(row_count, bool) or isinstance(fingerprint_count, bool):
        return False
    if not isinstance(row_count, (int, str)) or not isinstance(fingerprint_count, (int, str)):
        return False
    try:
        return int(row_count) >= 1 and int(fingerprint_count) == 1
    except (TypeError, ValueError):
        return False


def _retryable_http_status(status: int) -> bool:
    return status in {408, 425, 429} or 500 <= status < 600


def _http_failure(status: int) -> RuntimeError:
    if status in {401, 403}:
        kind = "authorization failed"
    elif status == 429:
        kind = "rate limited"
    elif status in {408, 425} or 500 <= status < 600:
        kind = "transient failure"
    elif 400 <= status < 500:
        kind = "validation failed"
    else:
        kind = "permanent HTTP failure"
    return RuntimeError(f"ClickHouse bar write {kind} ({status})")


class ClickHouseBarWriter:
    """Append exact, provenance-bearing Bar revisions through JSONEachRow."""

    def __init__(
        self,
        config: ClickHouseBarConfig,
        *,
        transport: HttpTransport = _stdlib_http_transport,
        query_transport: QueryTransport = _stdlib_http_transport,
        sleeper: Sleeper = time_module.sleep,
    ) -> None:
        self._config = config
        self._transport = transport
        self._query_transport = query_transport
        self._sleeper = sleeper

    def _confirm_row(
        self,
        table: str,
        stored: StoredBar,
        headers: Mapping[str, str],
    ) -> bool:
        try:
            status, body = self._query_transport(
                _database_url(self._config),
                headers,
                _confirmation_query(table, stored),
                self._config.timeout_seconds,
            )
        except Exception:
            raise RuntimeError("ClickHouse bar write outcome is uncertain") from None
        if not 200 <= status < 300:
            raise RuntimeError("ClickHouse bar write outcome is uncertain")
        return _confirmation_result(body)

    def _confirm_rows(
        self,
        table: str,
        rows: Iterable[StoredBar],
        headers: Mapping[str, str],
    ) -> bool:
        return all(self._confirm_row(table, stored, headers) for stored in rows)

    def _write_rows(
        self,
        table: str,
        rows: list[StoredBar],
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        last_status: int | None = None
        last_outcome_uncertain = False
        for attempt in range(self._config.max_attempts):
            try:
                status, _ = self._transport(
                    _database_url(self._config),
                    headers,
                    body,
                    self._config.timeout_seconds,
                )
            except Exception:
                last_outcome_uncertain = True
            else:
                last_status = status
                last_outcome_uncertain = False
                if 200 <= status < 300:
                    return
                if not _retryable_http_status(status):
                    raise _http_failure(status)

            if self._confirm_rows(table, rows, headers):
                return
            if attempt + 1 < self._config.max_attempts:
                self._sleeper(self._config.retry_backoff_seconds * (2**attempt))
                continue
            if last_outcome_uncertain:
                raise RuntimeError("ClickHouse bar write outcome is uncertain") from None
            if last_status is None:
                raise RuntimeError("ClickHouse bar write outcome is uncertain")
            raise _http_failure(last_status)

        raise RuntimeError("ClickHouse bar write retry loop terminated unexpectedly")

    def write_bars(self, bars: Iterable[StoredBar]) -> int:
        unique: dict[tuple[tuple[str, str, str, str, str, str, str, str], int], StoredBar] = {}
        for candidate in bars:
            key = (candidate.identity, candidate.replacement_version)
            existing = unique.get(key)
            if existing is not None and existing != candidate:
                raise ValueError("conflicting revision for the same identity and version")
            unique[key] = candidate

        grouped: dict[str, list[StoredBar]] = {}
        for stored in unique.values():
            table = _TABLES.get(stored.interval)
            if table is None:
                raise ValueError(f"unsupported Bar interval: {stored.interval}")
            grouped.setdefault(table, []).append(stored)

        headers: dict[str, str] = {
            "content-type": "application/json; charset=utf-8",
            "x-clickhouse-user": self._config.user,
        }
        if self._config.password:
            headers["x-clickhouse-key"] = self._config.password

        for table in sorted(grouped):
            rows = sorted(
                grouped[table],
                key=lambda stored: (stored.identity, stored.replacement_version),
            )
            prefix = f"INSERT INTO {table} FORMAT JSONEachRow\n".encode()
            encoded_rows = b"".join(
                (
                    json.dumps(
                        _row(stored),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8")
                for stored in rows
            )
            self._write_rows(table, rows, headers, prefix + encoded_rows)
        return len(unique)


__all__ = [
    "ClickHouseBarConfig",
    "ClickHouseBarWriter",
    "HttpTransport",
    "QueryTransport",
]
