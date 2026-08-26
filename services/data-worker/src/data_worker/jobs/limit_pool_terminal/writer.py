"""Production writer for canonical P6-N03 terminal snapshots."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from emotion_core.limit_pool import TerminalSnapshotProjection

HttpTransport = Callable[[str, Mapping[str, str], bytes, float], tuple[int, bytes]]
_DATABASE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_INSERT_PREFIX = b"INSERT INTO limit_pool_terminal_snapshots_v2 FORMAT JSONEachRow\n"


class LimitPoolTerminalWriter(Protocol):
    """Persistence boundary for a canonical terminal projection."""

    def write(self, projection: TerminalSnapshotProjection) -> TerminalSnapshotProjection: ...


@dataclass(frozen=True)
class ClickHouseTerminalConfig:
    url: str
    database: str
    user: str
    password: str | None = None
    timeout_seconds: float = 4.0

    def __post_init__(self) -> None:
        if not self.url.strip():
            raise ValueError("url must be non-empty")
        if not _DATABASE_IDENTIFIER.fullmatch(self.database):
            raise ValueError("database must be a safe ClickHouse identifier")
        if not self.user.strip():
            raise ValueError("user must be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


def _database_url(config: ClickHouseTerminalConfig) -> str:
    parsed = urlsplit(config.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an HTTP(S) endpoint")
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
        with urlopen(request, timeout=timeout_seconds) as response:
            return int(response.status), response.read()
    except HTTPError as error:
        return error.code, b""


class ClickHouseLimitPoolTerminalWriter:
    """Persist a materialized projection through ClickHouse HTTP."""

    def __init__(
        self,
        config: ClickHouseTerminalConfig,
        *,
        transport: HttpTransport = _stdlib_http_transport,
    ) -> None:
        self._config = config
        self._transport = transport

    def write(self, projection: TerminalSnapshotProjection) -> TerminalSnapshotProjection:
        row = projection.clickhouse_row()
        body = _INSERT_PREFIX + (
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        headers: dict[str, str] = {
            "content-type": "application/json; charset=utf-8",
            "x-clickhouse-user": self._config.user,
        }
        if self._config.password:
            headers["x-clickhouse-key"] = self._config.password
        try:
            status, _ = self._transport(
                _database_url(self._config),
                headers,
                body,
                self._config.timeout_seconds,
            )
        except Exception:
            raise RuntimeError("ClickHouse terminal write failed") from None
        if not 200 <= status < 300:
            raise RuntimeError(f"ClickHouse terminal write failed ({status})")
        return projection
