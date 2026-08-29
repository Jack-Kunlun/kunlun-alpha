"""Point-in-time ClickHouse reader for local daily-bar ranking inputs."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import cast
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

RankingBarsTransport = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]
_DATABASE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_INSTRUMENT_ID = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")

RANKING_BARS_PIT_SQL = """
WITH
  parseDateTime64BestEffort({asOf:String}, 3, 'UTC') AS cutoff,
  revision_groups AS (
    SELECT unified_code, interval, event_time, session, price_type, data_version,
      source, source_version, replacement_version,
      any(date) AS revision_date, any(event_time) AS revision_event_time,
      any(high) AS revision_high, any(low) AS revision_low, any(close) AS revision_close,
      any(amount) AS revision_amount, any(available_time) AS revision_available_time,
      any(processing_time) AS revision_processing_time,
      any(revision_fingerprint) AS revision_evidence_id,
      uniqExact(revision_fingerprint) AS revision_count
    FROM bars_daily_v2
    WHERE unified_code = {instrumentId:String}
      AND interval = 'DAILY' AND price_type = 'RAW'
      AND event_time <= cutoff AND available_time <= cutoff AND processing_time <= cutoff
      AND source IN ('tushare-pro', 'akshare-tencent', 'akshare-sina', 'akshare-eastmoney')
    GROUP BY unified_code, interval, event_time, session, price_type, data_version,
      source, source_version, replacement_version
    HAVING throwIf(uniqExact(revision_fingerprint) > 1, 'revision_fingerprint conflict') = 0
  ),
  identity_rows AS (
    SELECT unified_code, interval, event_time, session, price_type, data_version,
      source, source_version,
      argMax(tuple(revision_date, revision_event_time, revision_high, revision_low,
        revision_close, revision_amount, revision_available_time, revision_processing_time,
        revision_evidence_id, data_version, source, source_version), replacement_version)
        AS identity_values,
      max(replacement_version) AS identity_replacement_version,
      argMax(revision_evidence_id, replacement_version) AS identity_revision_fingerprint
    FROM revision_groups
    GROUP BY unified_code, interval, event_time, session, price_type, data_version,
      source, source_version
    HAVING max(revision_count) = 1
  ),
  source_rows AS (
    SELECT *, identity_values.1 AS identity_date,
      multiIf(source = 'tushare-pro', 3, source IN ('akshare-tencent', 'akshare-sina'), 2,
        source = 'akshare-eastmoney', 1, 0) AS source_priority
    FROM identity_rows
  ),
  date_rows AS (
    SELECT unified_code, identity_date AS date,
      argMax(identity_values, tuple(identity_replacement_version, source_priority, source,
        source_version, data_version, interval, session, price_type, identity_values.1,
        identity_values.2, identity_values.3, identity_values.4, identity_values.5,
        identity_values.6, identity_values.7, identity_values.8, identity_values.9,
        identity_values.10, identity_values.11, identity_values.12,
        identity_revision_fingerprint)) AS selected_values
    FROM source_rows
    GROUP BY unified_code, identity_date
  ),
  limited_rows AS (
    SELECT unified_code, date, selected_values
    FROM date_rows
    ORDER BY date DESC
    LIMIT {limit:UInt32}
  )
SELECT toString(date) AS date,
  formatDateTime(selected_values.2, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS event_time,
  toString(selected_values.3) AS high, toString(selected_values.4) AS low,
  toString(selected_values.5) AS close, toString(selected_values.6) AS amount,
  formatDateTime(selected_values.7, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS available_time,
  formatDateTime(selected_values.8, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS processing_time,
  selected_values.11 AS source, selected_values.12 AS source_version,
  toString(selected_values.9) AS evidence_id
FROM limited_rows
ORDER BY date ASC
FORMAT JSONEachRow
""".strip()


class RankingBarsReadError(RuntimeError):
    """The point-in-time bar input could not be read or validated."""


@dataclass(frozen=True, slots=True)
class DailyRankingBar:
    instrument_id: str
    date: date
    event_time: datetime
    high: Decimal
    low: Decimal
    close: Decimal
    amount: Decimal
    available_time: datetime
    processing_time: datetime
    source: str
    source_version: str
    evidence_id: str

    def __post_init__(self) -> None:
        if _INSTRUMENT_ID.fullmatch(self.instrument_id) is None:
            raise ValueError("instrument_id must be canonical")
        if any(value.tzinfo is None or value.utcoffset() is None for value in self.instants):
            raise ValueError("bar timestamps must be timezone-aware")
        if not all(value.is_finite() for value in (self.high, self.low, self.close, self.amount)):
            raise ValueError("bar decimal values must be finite")
        if self.low <= 0 or self.close <= 0 or self.high <= 0 or self.amount < 0:
            raise ValueError("bar prices must be positive and amount must be non-negative")
        if not self.low <= self.close <= self.high:
            raise ValueError("bar OHLC ordering is invalid")
        if self.available_time > self.processing_time:
            raise ValueError("bar available_time must not exceed processing_time")
        if (
            not self.source.strip()
            or not self.source_version.strip()
            or not self.evidence_id.strip()
        ):
            raise ValueError("bar provenance is required")

    @property
    def instants(self) -> tuple[datetime, datetime, datetime]:
        return (self.event_time, self.available_time, self.processing_time)


@dataclass(frozen=True, slots=True)
class ClickHouseRankingConfig:
    url: str
    database: str
    user: str
    password: str | None = field(default=None, repr=False)
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an HTTP(S) endpoint")
        if _DATABASE_IDENTIFIER.fullmatch(self.database) is None:
            raise ValueError("database must be a safe ClickHouse identifier")
        if not self.user.strip():
            raise ValueError("user must be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


def _transport(
    url: str,
    headers: dict[str, str],
    body: bytes,
    timeout_seconds: float,
) -> tuple[int, bytes]:
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return int(response.status), response.read()
    except HTTPError as error:
        return error.code, error.read()


def _canonical_instant(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _instant(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise RankingBarsReadError(f"invalid ClickHouse field: {field_name}")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RankingBarsReadError(f"invalid ClickHouse field: {field_name}") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise RankingBarsReadError(f"invalid ClickHouse field: {field_name}")
    return result.astimezone(UTC)


def _decimal(value: object, field_name: str, *, positive: bool) -> Decimal:
    if not isinstance(value, str):
        raise RankingBarsReadError(f"invalid ClickHouse field: {field_name}")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise RankingBarsReadError(f"invalid ClickHouse field: {field_name}") from error
    if not result.is_finite() or (result <= 0 if positive else result < 0):
        raise RankingBarsReadError(f"invalid ClickHouse field: {field_name}")
    return result


def _text(record: dict[str, object], field_name: str) -> str:
    value = record.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise RankingBarsReadError(f"invalid ClickHouse field: {field_name}")
    return value


def _row(instrument_id: str, value: object) -> DailyRankingBar:
    if not isinstance(value, dict):
        raise RankingBarsReadError("ClickHouse ranking row must be an object")
    raw = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        raise RankingBarsReadError("ClickHouse ranking row keys must be strings")
    record = cast(dict[str, object], raw)
    try:
        trading_date = date.fromisoformat(_text(record, "date"))
    except ValueError as error:
        raise RankingBarsReadError("invalid ClickHouse field: date") from error
    return DailyRankingBar(
        instrument_id=instrument_id,
        date=trading_date,
        event_time=_instant(record.get("event_time"), "event_time"),
        high=_decimal(record.get("high"), "high", positive=True),
        low=_decimal(record.get("low"), "low", positive=True),
        close=_decimal(record.get("close"), "close", positive=True),
        amount=_decimal(record.get("amount"), "amount", positive=False),
        available_time=_instant(record.get("available_time"), "available_time"),
        processing_time=_instant(record.get("processing_time"), "processing_time"),
        source=_text(record, "source"),
        source_version=_text(record, "source_version"),
        evidence_id=_text(record, "evidence_id"),
    )


class ClickHouseRankingBarsReader:
    def __init__(
        self,
        config: ClickHouseRankingConfig,
        *,
        transport: RankingBarsTransport = _transport,
    ) -> None:
        self._config = config
        self._transport = transport

    def read(
        self,
        instrument_id: str,
        as_of: datetime,
        *,
        limit: int,
    ) -> tuple[DailyRankingBar, ...]:
        if _INSTRUMENT_ID.fullmatch(instrument_id) is None:
            raise ValueError("instrument_id must be canonical")
        if not 2 <= limit <= 500:
            raise ValueError("limit must be in [2, 500]")
        parsed = urlsplit(self._config.url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.update(
            {
                "database": self._config.database,
                "param_instrumentId": instrument_id,
                "param_asOf": _canonical_instant(as_of),
                "param_limit": str(limit),
            }
        )
        url = urlunsplit(parsed._replace(query=urlencode(query)))
        headers = {
            "content-type": "text/plain; charset=utf-8",
            "x-clickhouse-user": self._config.user,
        }
        if self._config.password:
            headers["x-clickhouse-key"] = self._config.password
        try:
            status, body = self._transport(
                url,
                headers,
                RANKING_BARS_PIT_SQL.encode(),
                self._config.timeout_seconds,
            )
        except Exception:
            raise RankingBarsReadError("ClickHouse ranking read failed") from None
        if status != 200:
            raise RankingBarsReadError(f"ClickHouse ranking read failed ({status})")
        try:
            values = [json.loads(line) for line in body.splitlines() if line.strip()]
        except (UnicodeDecodeError, ValueError) as error:
            raise RankingBarsReadError("ClickHouse ranking response is invalid JSON") from error
        rows = tuple(_row(instrument_id, value) for value in values)
        if [item.date for item in rows] != sorted(item.date for item in rows):
            raise RankingBarsReadError("ClickHouse ranking rows are not ordered by date")
        if len({item.date for item in rows}) != len(rows):
            raise RankingBarsReadError("ClickHouse ranking rows contain duplicate dates")
        return rows
