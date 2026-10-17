"""Database-owned watchlist universe; isolated raw-first daily synchronization.

No private names/owners are logged or copied into the public sample universe.
A per-code PostgreSQL session lock fences competing workers, while the existing
raw/checkpoint writer makes crash recovery idempotent. Failures retry at most
three times per Shanghai date, no more frequently than hourly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import psycopg
from data_worker.jobs.market_data.runtime import (
    MarketDataSyncSettings,
    MarketDataSyncSummary,
    build_market_data_runner,
    load_market_data_settings,
)
from market_core.instrument.code_parser import ExchangeCode, is_market_data_code_for_exchange
from market_core.providers import (
    ProviderDataError,
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def supported_code(code: str) -> bool:
    parts = code.rsplit(".", 1)
    return (
        len(parts) == 2
        and parts[1] in {"SH", "SZ", "BJ"}
        and is_market_data_code_for_exchange(code, cast(ExchangeCode, parts[1]))
    )


def due_for_sync(
    status: str | None,
    attempt_date: date | None,
    last_attempt: datetime | None,
    attempts: int,
    now: datetime,
) -> bool:
    local = now.astimezone(_SHANGHAI)
    if status == "UNSUPPORTED":
        return False
    if status is None:
        return True
    if attempt_date != local.date():
        return local.hour >= 9
    if status in {"SUCCEEDED", "EMPTY"} or attempts >= 3:
        return False
    return last_attempt is None or now - last_attempt >= timedelta(hours=1)


def has_daily_bars(settings: MarketDataSyncSettings, code: str) -> bool:
    """Recover a committed checkpoint without treating an empty capture as success."""
    if not supported_code(code):
        return False
    query = urlencode({"database": settings.clickhouse_database, "param_code": code})
    headers = {"X-ClickHouse-User": settings.clickhouse_user}
    if settings.clickhouse_password is not None:
        headers["X-ClickHouse-Key"] = settings.clickhouse_password
    request = Request(
        settings.clickhouse_url.rstrip("/") + "/?" + query,
        data=(
            b"SELECT count() FROM bars_daily_v2 WHERE unified_code={code:String} "
            b"AND interval='DAILY' AND price_type='RAW'"
        ),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=settings.clickhouse_timeout_seconds) as response:
        return int(response.read(128).decode().strip()) > 0


Runner = Callable[[MarketDataSyncSettings], MarketDataSyncSummary]


def collect_code(settings: MarketDataSyncSettings) -> MarketDataSyncSummary:
    """Kill a hung SDK/storage operation, including SDK calls with no timeout."""
    environment = {
        **os.environ,
        "MARKET_DATA_SYMBOLS": ",".join(settings.symbols),
        "MARKET_DATA_PROVIDER": "akshare",
        "MARKET_DATA_RUN_MODE": "once",
        "MARKET_DATA_MINUTE_SYMBOLS": "",
        "MARKET_DATA_SETTINGS_URL": "",
        "MARKET_DATA_QUALITY_PUBLIC_ROOT": "",
        "MARKET_DATA_STATUS_PUBLIC_ROOT": "",
        "MARKET_DATA_RAW_ROOT": str(settings.raw_root),
        "MARKET_DATA_DAILY_LOOKBACK_DAYS": str(settings.daily_lookback_days),
        "CLICKHOUSE_URL": settings.clickhouse_url,
        "CLICKHOUSE_DATABASE": settings.clickhouse_database,
        "CLICKHOUSE_USER": settings.clickhouse_user,
        "CLICKHOUSE_PASSWORD": settings.clickhouse_password or "",
        "CLICKHOUSE_TIMEOUT_SECONDS": str(settings.clickhouse_timeout_seconds),
        "TUSHARE_TOKEN": "",
    }
    try:
        child = subprocess.run(
            [sys.executable, "-m", __name__, "--collect-one"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ProviderTimeoutError("watchlist source deadline exceeded") from None
    try:
        payload = cast(dict[str, object], json.loads(child.stdout.splitlines()[-1]))
        if child.returncode != 0:
            if payload.get("errorCode") == "VALIDATION_ERROR":
                raise ProviderDataError("watchlist source validation failed")
            raise ProviderUnavailableError("watchlist source unavailable")
        captures = payload["rawCaptureIds"]
        if not isinstance(captures, list) or not all(
            isinstance(x, str) for x in cast(list[object], captures)
        ):
            raise ValueError("invalid capture ids")
        return MarketDataSyncSummary(
            trading_date=str(payload["tradingDate"]),
            requests=int(cast(int, payload["requests"])),
            received_bars=int(cast(int, payload["receivedBars"])),
            written_bars=int(cast(int, payload["writtenBars"])),
            daily_refreshed=bool(payload["dailyRefreshed"]),
            raw_capture_ids=tuple(cast(list[str], captures)),
        )
    except (ValueError, KeyError, IndexError, TypeError):
        raise RuntimeError("watchlist child returned invalid result") from None


def sync_watchlist(
    dsn: str,
    settings: MarketDataSyncSettings,
    *,
    runner: Runner = collect_code,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, int]:
    counts = {
        "processed": 0,
        "succeeded": 0,
        "empty": 0,
        "failed": 0,
        "unsupported": 0,
        "writtenBars": 0,
    }
    with psycopg.connect(dsn, autocommit=True) as connection:
        codes = connection.execute(
            "SELECT DISTINCT code FROM personal_watchlist_items ORDER BY code"
        ).fetchall()
        for (code_value,) in codes:
            code = str(code_value)
            lock = "personal-watchlist-market:" + code
            locked = connection.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s,0))", (lock,)
            ).fetchone()
            if locked is None or not locked[0]:
                continue
            try:
                row = connection.execute(
                    "SELECT status,attempt_date,last_attempt_at,attempt_count "
                    "FROM personal_watchlist_market_state WHERE code=%s",
                    (code,),
                ).fetchone()
                now = clock()
                if row is not None and not due_for_sync(
                    str(row[0]),
                    cast(date | None, row[1]),
                    cast(datetime | None, row[2]),
                    int(row[3]),
                    now,
                ):
                    continue
                connection.execute(
                    """INSERT INTO personal_watchlist_market_state
                    (code,status,last_attempt_at,attempt_date,attempt_count)
                    VALUES(%s,'RUNNING',%s,%s,1) ON CONFLICT(code) DO UPDATE SET
                    status='RUNNING', last_attempt_at=EXCLUDED.last_attempt_at, error_code=NULL,
                    attempt_count=CASE
                    WHEN personal_watchlist_market_state.attempt_date=EXCLUDED.attempt_date
                    THEN personal_watchlist_market_state.attempt_count+1 ELSE 1 END,
                    attempt_date=EXCLUDED.attempt_date""",
                    (code, now, now.astimezone(_SHANGHAI).date()),
                )
                counts["processed"] += 1
                status, error = "UNSUPPORTED", "UNSUPPORTED_MARKET"
                if supported_code(code):
                    try:
                        result = runner(
                            replace(
                                settings,
                                symbols=(code,),
                                minute_symbols=(),
                                quality_public_root=None,
                                status_public_root=None,
                                daily_at=None,
                                continuous=False,
                            )
                        )
                        # A zero-request result means the durable checkpoint already
                        # committed this date (e.g. crash before the status update).
                        status = (
                            "SUCCEEDED"
                            if result.received_bars > 0
                            or (result.requests == 0 and has_daily_bars(settings, code))
                            else "EMPTY"
                        )
                        error = None
                        counts["writtenBars"] += result.written_bars
                    except ProviderDataError:
                        status, error = "FAILED", "VALIDATION_ERROR"
                    except ProviderError:
                        status, error = "FAILED", "SOURCE_ERROR"
                    except (RuntimeError, OSError, ValueError):
                        status, error = "FAILED", "SYNC_ERROR"
                connection.execute(
                    """UPDATE personal_watchlist_market_state SET status=%s,error_code=%s,
                    last_success_at=CASE WHEN %s='SUCCEEDED' THEN %s ELSE last_success_at END
                    WHERE code=%s""",
                    (status, error, status, clock(), code),
                )
                counts[status.lower()] += 1
                # Aggregate progress only: useful for long backfills without
                # disclosing a user's symbols or names in container logs.
                print(json.dumps({"event": "watchlist_sync_progress", **counts}), flush=True)
            finally:
                connection.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (lock,))
    return counts


def main() -> None:
    dsn = os.environ.get("KUNLUN_POSTGRES_DSN", "").strip()
    if not dsn:
        raise SystemExit("KUNLUN_POSTGRES_DSN is required")
    settings = load_market_data_settings(
        {
            **os.environ,
            "MARKET_DATA_PROVIDER": "akshare",
            "MARKET_DATA_RUN_MODE": "once",
            "MARKET_DATA_SYMBOLS": "600519.SH",
            "MARKET_DATA_MINUTE_SYMBOLS": "",
            "MARKET_DATA_SETTINGS_URL": "",
            "TUSHARE_TOKEN": "",
        }
    )
    if sys.argv[1:] == ["--collect-one"]:
        try:
            # The parent sets one validated code and a bounded deadline.
            child_settings = replace(
                settings, symbols=tuple(os.environ["MARKET_DATA_SYMBOLS"].split(","))
            )
            summary = build_market_data_runner(
                child_settings,
                checkpoint_root=settings.raw_root
                / "watchlist-checkpoints"
                / child_settings.symbols[0],
            ).run_cycle()
            print(json.dumps(summary.to_dict()), flush=True)
        except ProviderDataError:
            print(json.dumps({"errorCode": "VALIDATION_ERROR"}), flush=True)
            raise SystemExit(1) from None
        except (ProviderError, RuntimeError, OSError, ValueError):
            print(json.dumps({"errorCode": "SOURCE_ERROR"}), flush=True)
            raise SystemExit(1) from None
        return
    once = os.environ.get("WATCHLIST_SYNC_RUN_MODE", "continuous") == "once"
    while True:
        try:
            print(
                json.dumps({"event": "watchlist_sync_completed", **sync_watchlist(dsn, settings)}),
                flush=True,
            )
        except psycopg.Error:
            # Avoid leaking connection strings or SQL parameter values.
            print(json.dumps({"event": "watchlist_sync_database_unavailable"}), flush=True)
            if once:
                raise SystemExit(1) from None
        if once:
            return
        time.sleep(60)


if __name__ == "__main__":
    main()
