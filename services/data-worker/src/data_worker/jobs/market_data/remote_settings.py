"""Read-only, fail-closed loading of managed market-data settings."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from http.client import HTTPMessage
from typing import IO, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import SplitResult, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

MAX_REMOTE_SETTINGS_RESPONSE_BYTES = 8 * 1024
REMOTE_SETTINGS_TIMEOUT_SECONDS = 5.0
REMOTE_SETTINGS_PATH = "/api/v1/internal/market-data/settings"
WORKER_TOKEN_MIN_LENGTH = 32
WORKER_TOKEN_MAX_LENGTH = 512
MAX_SAFE_INTEGER = 2**53 - 1

_ALLOWED_PROVIDERS = frozenset({"akshare", "tushare"})
_LOCAL_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class RemoteMarketDataSettingsError(RuntimeError):
    """Managed settings could not be loaded or did not pass validation."""


class _HttpResponse(Protocol):
    status: int

    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...


RemoteSettingsTransport = Callable[[Request, float], _HttpResponse]


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent an internal settings request from following a redirect."""

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


@dataclass(frozen=True, slots=True)
class RemoteMarketDataSettings:
    """Validated provider settings returned by the internal control-plane route."""

    provider: str
    revision: int
    token: str | None = field(repr=False)

    def __post_init__(self) -> None:
        if self.provider not in _ALLOWED_PROVIDERS:
            raise ValueError("managed market-data provider is invalid")
        if type(self.revision) is not int or not 0 <= self.revision <= MAX_SAFE_INTEGER:
            raise ValueError("managed market-data revision is invalid")
        _validate_provider_token(self.provider, self.token)


@dataclass(frozen=True, slots=True)
class RemoteMarketDataSettingsSource:
    """Validated endpoint credentials; the worker credential is never represented."""

    url: str
    worker_token: str = field(repr=False)
    allow_local_http: bool = False


def _invalid(
    message: str = "managed market-data settings are invalid",
) -> RemoteMarketDataSettingsError:
    return RemoteMarketDataSettingsError(message)


def _validate_provider_token(provider: str, token: object) -> str | None:
    if token is None:
        if provider == "tushare":
            raise ValueError("managed market-data token is required")
        return None
    if not isinstance(token, str) or not 1 <= len(token) <= 256:
        raise ValueError("managed market-data token is invalid")
    if any(not 0x21 <= ord(character) <= 0x7E for character in token):
        raise ValueError("managed market-data token is invalid")
    if provider == "akshare":
        raise ValueError("managed market-data token is invalid")
    return token


def _validate_worker_token(worker_token: str) -> str:
    if not WORKER_TOKEN_MIN_LENGTH <= len(worker_token) <= WORKER_TOKEN_MAX_LENGTH:
        raise _invalid("managed market-data worker credential is invalid")
    if any(not 0x21 <= ord(character) <= 0x7E for character in worker_token):
        raise _invalid("managed market-data worker credential is invalid")
    return worker_token


def validate_remote_settings_worker_token(worker_token: str) -> str:
    """Validate the credential used to authenticate managed settings reads."""

    return _validate_worker_token(worker_token)


def _parsed_url(url: str, *, allow_local_http: bool) -> SplitResult:
    if (
        not url
        or url != url.strip()
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in url)
    ):
        raise _invalid("managed market-data settings endpoint is invalid")
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except Exception:
        raise _invalid("managed market-data settings endpoint is invalid") from None
    if (
        parsed.scheme not in {"http", "https"}
        or hostname is None
        or not parsed.netloc
        or parsed.path != REMOTE_SETTINGS_PATH
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise _invalid("managed market-data settings endpoint is invalid")
    if port is not None and not 1 <= port <= 65535:
        raise _invalid("managed market-data settings endpoint is invalid")
    if parsed.scheme == "http":
        normalized_host = hostname.lower()
        loopback = normalized_host in _LOCAL_HTTP_HOSTS
        compose_origin = normalized_host == "server" and port == 3002
        if not loopback and not (allow_local_http and compose_origin):
            raise _invalid("managed market-data settings endpoint is invalid")
    return parsed


def validate_remote_settings_url(url: str, *, allow_local_http: bool = False) -> str:
    """Validate and return an internal settings endpoint without exposing it in errors."""

    _parsed_url(url, allow_local_http=allow_local_http)
    return url


def _source_from_environment(environ: Mapping[str, str]) -> RemoteMarketDataSettingsSource | None:
    url_value = environ.get("MARKET_DATA_SETTINGS_URL")
    worker_token_value = environ.get("MARKET_DATA_SETTINGS_WORKER_TOKEN")
    allow_raw = environ.get("MARKET_DATA_SETTINGS_ALLOW_LOCAL_HTTP")
    url = url_value if url_value is not None else ""
    worker_token = worker_token_value if worker_token_value is not None else ""

    if not url and not worker_token:
        if allow_raw is not None and allow_raw.strip() not in {"", "false"}:
            raise _invalid("managed market-data settings environment is incomplete")
        return None
    if not url or not worker_token:
        raise _invalid("managed market-data settings environment is incomplete")
    if allow_raw is None or not allow_raw.strip():
        allow_local_http = False
    elif allow_raw.strip() == "true":
        allow_local_http = True
    elif allow_raw.strip() == "false":
        allow_local_http = False
    else:
        raise _invalid("managed market-data settings environment is invalid")
    validate_remote_settings_url(url, allow_local_http=allow_local_http)
    _validate_worker_token(worker_token)
    return RemoteMarketDataSettingsSource(
        url=url,
        worker_token=worker_token,
        allow_local_http=allow_local_http,
    )


def _stdlib_transport(request: Request, timeout_seconds: float) -> _HttpResponse:
    """Open a request with proxies and redirects disabled."""

    opener = build_opener(ProxyHandler({}), _NoRedirectHandler())
    return cast(_HttpResponse, opener.open(request, timeout=timeout_seconds))


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _decode_response(body: bytes) -> RemoteMarketDataSettings:
    try:
        value: object = json.loads(body.decode("utf-8"), object_pairs_hook=_object_pairs)
    except (UnicodeDecodeError, ValueError):
        raise _invalid() from None
    if not isinstance(value, dict):
        raise _invalid()
    payload = cast(dict[object, object], value)
    expected = {"schemaVersion", "provider", "revision", "token"}
    if set(payload) != expected:
        raise _invalid()
    if payload.get("schemaVersion") != "market-data-worker-settings-v1":
        raise _invalid()
    provider = payload.get("provider")
    revision = payload.get("revision")
    token = payload.get("token")
    if not isinstance(provider, str) or provider not in _ALLOWED_PROVIDERS:
        raise _invalid()
    if type(revision) is not int or not 0 <= revision <= MAX_SAFE_INTEGER:
        raise _invalid()
    try:
        checked_token = _validate_provider_token(provider, token)
        return RemoteMarketDataSettings(provider, revision, checked_token)
    except (TypeError, ValueError):
        raise _invalid() from None


def fetch_remote_market_data_settings(
    url: str,
    worker_token: str,
    *,
    allow_local_http: bool = False,
    timeout_seconds: float = REMOTE_SETTINGS_TIMEOUT_SECONDS,
    transport: RemoteSettingsTransport | None = None,
) -> RemoteMarketDataSettings:
    """Fetch one exact settings response using a read-only authenticated GET."""

    validate_remote_settings_url(url, allow_local_http=allow_local_http)
    _validate_worker_token(worker_token)
    if not 0 < timeout_seconds <= 30:
        raise _invalid("managed market-data settings timeout is invalid")
    try:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {worker_token}",
                "Cache-Control": "no-store",
            },
            method="GET",
        )
    except Exception:
        raise _invalid("managed market-data settings endpoint is invalid") from None
    opener = transport or _stdlib_transport
    response: _HttpResponse | None = None
    try:
        response = opener(request, timeout_seconds)
        try:
            status = response.status
            body = response.read(MAX_REMOTE_SETTINGS_RESPONSE_BYTES + 1)
        except Exception:
            raise _invalid("managed market-data settings request failed") from None
    except HTTPError as error:
        with suppress(Exception):
            error.close()
        raise _invalid("managed market-data settings request failed") from None
    except (URLError, TimeoutError, OSError):
        raise _invalid("managed market-data settings request failed") from None
    except Exception:
        raise _invalid("managed market-data settings request failed") from None
    finally:
        if response is not None:
            with suppress(Exception):
                response.close()
    if type(status) is not int or status != 200:
        raise _invalid("managed market-data settings request failed")
    if len(body) > MAX_REMOTE_SETTINGS_RESPONSE_BYTES:
        raise _invalid()
    return _decode_response(body)


def load_remote_market_data_settings(
    environ: Mapping[str, str],
    *,
    transport: RemoteSettingsTransport | None = None,
) -> RemoteMarketDataSettings | None:
    """Load managed settings when the complete remote-mode environment is configured."""

    source = _source_from_environment(environ)
    if source is None:
        return None
    return fetch_remote_market_data_settings(
        source.url,
        source.worker_token,
        allow_local_http=source.allow_local_http,
        transport=transport,
    )


def remote_market_data_settings_source(
    environ: Mapping[str, str],
) -> RemoteMarketDataSettingsSource | None:
    """Return validated remote source metadata without making a network request."""

    return _source_from_environment(environ)


__all__ = [
    "MAX_REMOTE_SETTINGS_RESPONSE_BYTES",
    "REMOTE_SETTINGS_PATH",
    "REMOTE_SETTINGS_TIMEOUT_SECONDS",
    "RemoteMarketDataSettings",
    "RemoteMarketDataSettingsError",
    "RemoteMarketDataSettingsSource",
    "RemoteSettingsTransport",
    "fetch_remote_market_data_settings",
    "load_remote_market_data_settings",
    "remote_market_data_settings_source",
    "validate_remote_settings_worker_token",
    "validate_remote_settings_url",
]
