"""Idempotent HTTP publisher for immutable ranking snapshots."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

RankingPublishTransport = Callable[
    [str, str, dict[str, str], bytes | None, float], tuple[int, bytes]
]
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class RankingPublishError(RuntimeError):
    """The immutable ranking snapshot could not be published safely."""


@dataclass(frozen=True, slots=True)
class RankingPublishResult:
    published: bool
    payload: dict[str, object]


def _transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout_seconds: float,
) -> tuple[int, bytes]:
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return int(response.status), response.read()
    except HTTPError as error:
        return error.code, error.read()


def _object(body: bytes) -> dict[str, object]:
    try:
        value: object = json.loads(body)
    except (UnicodeDecodeError, ValueError) as error:
        raise RankingPublishError("quant-engine returned invalid JSON") from error
    if not isinstance(value, dict):
        raise RankingPublishError("quant-engine returned a non-object response")
    raw = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        raise RankingPublishError("quant-engine returned non-string keys")
    return cast(dict[str, object], raw)


class RankingSnapshotPublisher:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 5.0,
        transport: RankingPublishTransport = _transport,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an HTTP(S) endpoint")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def publish(self, payload: dict[str, object]) -> RankingPublishResult:
        snapshot_id = payload.get("snapshotId")
        as_of = payload.get("asOf")
        if not isinstance(snapshot_id, str) or _DIGEST.fullmatch(snapshot_id) is None:
            raise RankingPublishError("snapshotId must be a SHA-256 digest")
        if not isinstance(as_of, str) or not as_of.strip():
            raise RankingPublishError("asOf is required")

        existing = self._latest(as_of)
        if existing is not None and existing.get("snapshotId") == snapshot_id:
            return RankingPublishResult(published=False, payload=existing)

        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
        status, response = self._request(
            "POST",
            urljoin(self._base_url, "v1/ranking/snapshots"),
            {"content-type": "application/json; charset=utf-8"},
            body,
        )
        if status == 409:
            raced = self._latest(as_of)
            if raced is not None and raced.get("snapshotId") == snapshot_id:
                return RankingPublishResult(published=False, payload=raced)
        if status != 200:
            raise RankingPublishError(f"quant-engine ranking publish failed ({status})")
        result = _object(response)
        if result.get("snapshotId") != snapshot_id:
            raise RankingPublishError("quant-engine returned a different snapshotId")
        return RankingPublishResult(published=True, payload=result)

    def _latest(self, as_of: str) -> dict[str, object] | None:
        endpoint = urljoin(self._base_url, "v1/ranking/snapshots/latest")
        status, body = self._request(
            "GET",
            f"{endpoint}?{urlencode({'asOf': as_of})}",
            {},
            None,
        )
        if status == 404:
            return None
        if status != 200:
            raise RankingPublishError(f"quant-engine ranking lookup failed ({status})")
        return _object(body)

    def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> tuple[int, bytes]:
        try:
            return self._transport(method, url, headers, body, self._timeout_seconds)
        except Exception:
            raise RankingPublishError("quant-engine ranking request failed") from None
