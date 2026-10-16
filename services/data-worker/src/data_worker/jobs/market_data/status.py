"""Atomic, secret-free publication of one market-data sync status document."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from ashare_contracts.data_quality_market_data_sync_status import MarketDataSyncStatus
from pydantic import ValidationError

STATUS_FILENAME = "market-data-sync-status.json"
WorkerStatusErrorCode = Literal["SOURCE_ERROR", "VALIDATION_ERROR", "SYNC_ERROR"]
Clock = Callable[[], datetime]


class MarketDataSyncStatusError(RuntimeError):
    """The optional public status document is unsafe or unavailable."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MarketDataSyncStatusPublisher:
    """Publish validated status JSON without changing raw or checkpoint state."""

    def __init__(
        self,
        public_root: Path,
        *,
        provider: str,
        symbols: Sequence[str],
        clock: Clock = _utc_now,
    ) -> None:
        self._root = Path(public_root)
        self._path = self._root / STATUS_FILENAME
        self._provider = provider
        self._symbols = tuple(symbols)
        if not 1 <= len(self._symbols) <= 100 or len(self._symbols) != len(set(self._symbols)):
            raise MarketDataSyncStatusError(
                "market-data sync status scope must include between 1 and 100 unique symbols"
            )
        self._clock = clock
        self._attempt_at: str | None = None

    def _timestamp(self) -> str:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise MarketDataSyncStatusError("market-data status clock must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _ensure_not_before(value: str, *boundaries: object) -> None:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        for boundary in boundaries:
            if type(boundary) is not str:
                continue
            previous = datetime.fromisoformat(boundary.replace("Z", "+00:00")).astimezone(UTC)
            if observed < previous:
                raise MarketDataSyncStatusError("market-data status clock moved backwards")

    def _validate(self, payload: Mapping[str, object]) -> MarketDataSyncStatus:
        symbols = payload.get("symbols")
        if not isinstance(symbols, list):
            raise MarketDataSyncStatusError("market-data sync status is invalid")
        symbol_objects = cast(list[object], symbols)
        if any(type(symbol) is not str for symbol in symbol_objects):
            raise MarketDataSyncStatusError("market-data sync status is invalid")
        symbol_values = cast(list[str], symbol_objects)
        if len(symbol_values) != len(set(symbol_values)):
            raise MarketDataSyncStatusError("market-data sync status is invalid")
        try:
            return MarketDataSyncStatus.model_validate(payload)
        except (ValidationError, TypeError, ValueError):
            raise MarketDataSyncStatusError("market-data sync status is invalid") from None

    def _prepare_root(self) -> None:
        try:
            if self._root.is_symlink():
                raise MarketDataSyncStatusError("market-data sync status path is unsafe")
            self._root.mkdir(parents=True, exist_ok=True, mode=0o755)
            if self._root.is_symlink() or not self._root.is_dir():
                raise MarketDataSyncStatusError("market-data sync status path is unsafe")
            if os.name != "nt":
                os.chmod(self._root, 0o755)
            if self._path.is_symlink():
                raise MarketDataSyncStatusError("market-data sync status path is unsafe")
            if self._path.exists() and not self._path.is_file():
                raise MarketDataSyncStatusError("market-data sync status path is unsafe")
        except MarketDataSyncStatusError:
            raise
        except OSError:
            raise MarketDataSyncStatusError("market-data sync status path is unavailable") from None

    def _load(self) -> MarketDataSyncStatus | None:
        self._prepare_root()
        try:
            descriptor = os.open(
                self._path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
            )
        except FileNotFoundError:
            return None
        except OSError:
            if self._path.is_symlink():
                raise MarketDataSyncStatusError("market-data sync status path is unsafe") from None
            raise MarketDataSyncStatusError("market-data sync status is unavailable") from None
        try:
            with os.fdopen(descriptor, "r", encoding="utf-8") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise MarketDataSyncStatusError("market-data sync status path is unsafe")
                content = source.read()
        except MarketDataSyncStatusError:
            raise
        except (OSError, UnicodeDecodeError):
            raise MarketDataSyncStatusError("market-data sync status is unavailable") from None
        try:
            raw = json.loads(content)
        except json.JSONDecodeError:
            raise MarketDataSyncStatusError("market-data sync status is corrupt") from None
        if not isinstance(raw, dict):
            raise MarketDataSyncStatusError("market-data sync status is corrupt")
        return self._validate(cast(dict[str, object], raw))

    def _same_scope(self, current: MarketDataSyncStatus) -> bool:
        return current.provider.value == self._provider and {
            symbol.root for symbol in current.symbols
        } == set(self._symbols)

    def _base_payload(self) -> dict[str, object]:
        current = self._load()
        if current is not None and self._same_scope(current):
            payload = cast(dict[str, object], current.model_dump(mode="json", by_alias=True))
            payload["provider"] = self._provider
            payload["symbols"] = list(self._symbols)
            return payload
        return {
            "schemaVersion": "market-data-sync-status-v1",
            "status": "UNKNOWN",
            "provider": self._provider,
            "symbols": list(self._symbols),
            "lastAttemptAt": None,
            "lastFinishedAt": None,
            "lastSuccessAt": None,
            "lastSuccessResult": None,
            "errorCode": None,
        }

    def _write(self, payload: Mapping[str, object]) -> None:
        model = self._validate(payload)
        document = json.dumps(
            model.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        self._prepare_root()
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".market-data-sync-status-",
                suffix=".tmp",
                dir=self._root,
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as temporary:
                if os.name != "nt":
                    os.fchmod(temporary.fileno(), 0o644)
                temporary.write(document)
                temporary.flush()
                os.fsync(temporary.fileno())
            if self._path.is_symlink():
                raise MarketDataSyncStatusError("market-data sync status path is unsafe")
            os.replace(temporary_path, self._path)
            if os.name != "nt":
                with suppress(OSError):
                    directory = os.open(self._root, os.O_RDONLY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
        except MarketDataSyncStatusError:
            raise
        except OSError:
            raise MarketDataSyncStatusError("unable to publish market-data sync status") from None
        finally:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink()

    def publish_running(self) -> None:
        payload = self._base_payload()
        self._attempt_at = self._timestamp()
        self._ensure_not_before(
            self._attempt_at,
            payload.get("lastAttemptAt"),
            payload.get("lastFinishedAt"),
            payload.get("lastSuccessAt"),
        )
        payload.update(
            {
                "status": "RUNNING",
                "lastAttemptAt": self._attempt_at,
                "lastFinishedAt": None,
                "errorCode": None,
            }
        )
        self._write(payload)

    def publish_succeeded(
        self,
        *,
        requests: int,
        received_bars: int,
        written_bars: int,
        daily_refreshed: bool,
    ) -> None:
        payload = self._base_payload()
        now = self._timestamp()
        self._ensure_not_before(
            now,
            payload.get("lastAttemptAt"),
            payload.get("lastFinishedAt"),
            payload.get("lastSuccessAt"),
            self._attempt_at,
        )
        payload.update(
            {
                "status": "SUCCEEDED",
                "lastAttemptAt": payload.get("lastAttemptAt") or self._attempt_at or now,
                "lastFinishedAt": now,
                "lastSuccessAt": now,
                "lastSuccessResult": {
                    "requests": requests,
                    "receivedBars": received_bars,
                    "writtenBars": written_bars,
                    "dailyRefreshed": daily_refreshed,
                },
                "errorCode": None,
            }
        )
        self._write(payload)

    def publish_failed(self, error_code: WorkerStatusErrorCode) -> None:
        payload = self._base_payload()
        now = self._timestamp()
        self._ensure_not_before(
            now,
            payload.get("lastAttemptAt"),
            payload.get("lastFinishedAt"),
            payload.get("lastSuccessAt"),
            self._attempt_at,
        )
        payload.update(
            {
                "status": "FAILED",
                "lastAttemptAt": payload.get("lastAttemptAt") or self._attempt_at or now,
                "lastFinishedAt": now,
                "errorCode": error_code,
            }
        )
        self._write(payload)


__all__ = [
    "MarketDataSyncStatusError",
    "MarketDataSyncStatusPublisher",
    "STATUS_FILENAME",
    "WorkerStatusErrorCode",
]
