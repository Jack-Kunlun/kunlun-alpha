"""Replay sanitized provider-shaped captures without network or database access."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

from data_worker.jobs.local_reference import load_local_reference_catalog
from data_worker.providers.akshare import AKShareMarketDataProvider
from data_worker.raw import LocalFileStorage
from data_worker.raw.replay import replay_market_capture

type FixtureRow = dict[str, str]

_SCHEMA_VERSION = "offline-market-replay-fixture-v1"
_DATA_MEANING = "SANITIZED_OFFLINE_FIXTURE_NO_MARKET_CLAIM"
_FIXTURE_VERSION = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[1-9][0-9]*$")
_CAPTURE_PROFILES = {
    (
        "akshare-tencent",
        "stock_zh_a_hist_tx",
        "DAILY",
        "akshare:1.18.94:stock_zh_a_hist_tx:v2",
    ),
    (
        "akshare-sina",
        "stock_zh_a_minute",
        "MINUTE_1",
        "akshare:1.18.94:stock_zh_a_minute:v2",
    ),
}


class OfflineReplayFixtureError(ValueError):
    """The checked-in offline replay fixture is unsafe or malformed."""


@dataclass(frozen=True, slots=True)
class OfflineReplayCapture:
    capture_id: str
    source: str
    api_name: str
    source_version: str
    unified_code: str
    interval: str
    requested_start: date
    requested_end: date
    received_at: datetime
    rows: tuple[FixtureRow, ...]


@dataclass(frozen=True, slots=True)
class OfflineReplayBundle:
    fixture_version: str
    data_meaning: str
    captures: tuple[OfflineReplayCapture, ...]


@dataclass(frozen=True, slots=True)
class OfflineMarketReplaySummary:
    fixture_version: str
    catalog_version: str
    data_meaning: str
    capture_count: int
    bar_count: int
    instrument_ids: tuple[str, ...]
    board_coverage: tuple[str, ...]
    exchange_coverage: tuple[str, ...]
    interval_coverage: tuple[str, ...]
    source_profiles: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        """Return a stable JSON-facing summary without fixture price values."""

        return {
            "fixtureVersion": self.fixture_version,
            "catalogVersion": self.catalog_version,
            "dataMeaning": self.data_meaning,
            "captureCount": self.capture_count,
            "barCount": self.bar_count,
            "instrumentIds": list(self.instrument_ids),
            "boardCoverage": list(self.board_coverage),
            "exchangeCoverage": list(self.exchange_coverage),
            "intervalCoverage": list(self.interval_coverage),
            "sourceProfiles": list(self.source_profiles),
        }


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise OfflineReplayFixtureError(f"{field} must be an object")
    raw = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw):
        raise OfflineReplayFixtureError(f"{field} must be an object")
    return cast(dict[str, object], raw)


def _exact_keys(value: dict[str, object], expected: frozenset[str], field: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise OfflineReplayFixtureError(
            f"{field} fields differ: missing={sorted(expected - actual)} "
            f"extra={sorted(actual - expected)}"
        )


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise OfflineReplayFixtureError(f"{field} must be non-empty canonical text")
    return value


def _date(value: object, field: str) -> date:
    raw = _text(value, field)
    try:
        return date.fromisoformat(raw)
    except ValueError as error:
        raise OfflineReplayFixtureError(f"{field} must be an ISO date") from error


def _instant(value: object, field: str) -> datetime:
    raw = _text(value, field)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise OfflineReplayFixtureError(f"{field} must be RFC3339") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OfflineReplayFixtureError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _rows(value: object, field: str) -> tuple[FixtureRow, ...]:
    if not isinstance(value, list) or not value:
        raise OfflineReplayFixtureError(f"{field} must be a non-empty array")
    rows: list[FixtureRow] = []
    for index, item in enumerate(cast(list[object], value)):
        raw = _object(item, f"{field}[{index}]")
        if not raw or not all(isinstance(item_value, str) for item_value in raw.values()):
            raise OfflineReplayFixtureError(f"{field}[{index}] must contain string values")
        rows.append(cast(FixtureRow, raw))
    return tuple(rows)


def _capture(value: object, ordinal: int) -> OfflineReplayCapture:
    field = f"captures[{ordinal}]"
    raw = _object(value, field)
    _exact_keys(
        raw,
        frozenset(
            {
                "captureId",
                "source",
                "apiName",
                "sourceVersion",
                "unifiedCode",
                "interval",
                "requestedStart",
                "requestedEnd",
                "receivedAt",
                "rows",
            }
        ),
        field,
    )
    source = _text(raw["source"], f"{field}.source")
    api_name = _text(raw["apiName"], f"{field}.apiName")
    interval = _text(raw["interval"], f"{field}.interval")
    source_version = _text(raw["sourceVersion"], f"{field}.sourceVersion")
    if (source, api_name, interval, source_version) not in _CAPTURE_PROFILES:
        raise OfflineReplayFixtureError(f"{field} uses an unsupported parser profile")
    requested_start = _date(raw["requestedStart"], f"{field}.requestedStart")
    requested_end = _date(raw["requestedEnd"], f"{field}.requestedEnd")
    if requested_end < requested_start:
        raise OfflineReplayFixtureError(f"{field} requestedEnd precedes requestedStart")
    return OfflineReplayCapture(
        capture_id=_text(raw["captureId"], f"{field}.captureId"),
        source=source,
        api_name=api_name,
        source_version=source_version,
        unified_code=_text(raw["unifiedCode"], f"{field}.unifiedCode"),
        interval=interval,
        requested_start=requested_start,
        requested_end=requested_end,
        received_at=_instant(raw["receivedAt"], f"{field}.receivedAt"),
        rows=_rows(raw["rows"], f"{field}.rows"),
    )


def load_offline_replay_bundle(path: Path) -> OfflineReplayBundle:
    """Load a strict fixture that cannot claim real-market provenance."""

    try:
        decoded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise OfflineReplayFixtureError(
            f"offline replay fixture cannot be read: {error}"
        ) from error
    raw = _object(decoded, "fixture")
    _exact_keys(
        raw,
        frozenset({"schemaVersion", "fixtureVersion", "dataMeaning", "captures"}),
        "fixture",
    )
    if raw["schemaVersion"] != _SCHEMA_VERSION:
        raise OfflineReplayFixtureError("unsupported schemaVersion")
    fixture_version = _text(raw["fixtureVersion"], "fixtureVersion")
    if _FIXTURE_VERSION.fullmatch(fixture_version) is None:
        raise OfflineReplayFixtureError("fixtureVersion must use YYYY.MM.DD.REVISION")
    data_meaning = _text(raw["dataMeaning"], "dataMeaning")
    if data_meaning != _DATA_MEANING:
        raise OfflineReplayFixtureError(
            f"dataMeaning must be {_DATA_MEANING}; offline fixtures cannot claim market truth"
        )
    raw_captures = raw["captures"]
    if not isinstance(raw_captures, list) or not raw_captures:
        raise OfflineReplayFixtureError("captures must be a non-empty array")
    captures = tuple(
        _capture(item, index) for index, item in enumerate(cast(list[object], raw_captures))
    )
    capture_ids = [item.capture_id for item in captures]
    if len(capture_ids) != len(set(capture_ids)):
        raise OfflineReplayFixtureError("captures contain duplicate captureId values")
    return OfflineReplayBundle(
        fixture_version=fixture_version,
        data_meaning=data_meaning,
        captures=captures,
    )


def _run_in_temporary_storage(
    bundle: OfflineReplayBundle,
    storage_root: Path,
) -> int:
    storage = LocalFileStorage(storage_root)
    parser = AKShareMarketDataProvider()
    manifests: list[tuple[OfflineReplayCapture, str]] = []
    run_id = f"offline-replay-{bundle.fixture_version}"
    for ordinal, capture in enumerate(bundle.captures, start=1):
        partition = capture.received_at.date().isoformat()
        body = json.dumps(
            capture.rows,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        storage.put(
            capture.source,
            partition,
            f"GET /offline-market-replay/{capture.api_name}?code={capture.unified_code[:6]}",
            body,
            content_type="application/json; charset=utf-8",
            capture_id=capture.capture_id,
            ingest_time=capture.received_at,
            available_time=capture.received_at,
            schema_version="market-bar-v1",
            capture_version="capture-v1",
            api_name=capture.api_name,
            unified_code=capture.unified_code,
            interval=capture.interval,
            requested_start=capture.requested_start.isoformat(),
            requested_end=capture.requested_end.isoformat(),
            source_version=capture.source_version,
            market_run_id=run_id,
            capture_ordinal=ordinal,
        )
        manifests.append((capture, partition))

    replayed_bars = 0
    restarted = LocalFileStorage(storage_root)
    for capture, partition in manifests:
        loaded = {
            manifest.capture_id: manifest for manifest in restarted.list(capture.source, partition)
        }.get(capture.capture_id)
        if loaded is None:
            raise OfflineReplayFixtureError(
                f"capture {capture.capture_id} was not recoverable after storage restart"
            )
        bars = replay_market_capture(restarted, loaded, parser)
        if len(bars) != len(capture.rows):
            raise OfflineReplayFixtureError(
                f"capture {capture.capture_id} replayed an unexpected number of bars"
            )
        if any(
            bar.unified_code != capture.unified_code or bar.interval.value != capture.interval
            for bar in bars
        ):
            raise OfflineReplayFixtureError(
                f"capture {capture.capture_id} changed its instrument or interval identity"
            )
        replayed_bars += len(bars)
    return replayed_bars


def run_offline_replay_check(
    *,
    fixture_path: Path,
    catalog_path: Path,
) -> OfflineMarketReplaySummary:
    """Validate and replay the checked-in bundle in an ephemeral directory only."""

    bundle = load_offline_replay_bundle(fixture_path)
    catalog = load_local_reference_catalog(catalog_path)
    by_instrument = {item.instrument_id: item for item in catalog.instruments}
    instrument_ids = tuple(sorted({capture.unified_code for capture in bundle.captures}))
    unknown = sorted(set(instrument_ids) - set(by_instrument))
    if unknown:
        raise OfflineReplayFixtureError(
            f"offline replay instruments are absent from the curated catalog: {unknown}"
        )
    with tempfile.TemporaryDirectory(prefix="kunlun-offline-market-replay-") as directory:
        bar_count = _run_in_temporary_storage(bundle, Path(directory))
    boards = tuple(sorted({by_instrument[item].board for item in instrument_ids}))
    exchanges = tuple(sorted({item.rsplit(".", maxsplit=1)[1] for item in instrument_ids}))
    return OfflineMarketReplaySummary(
        fixture_version=bundle.fixture_version,
        catalog_version=catalog.catalog_version,
        data_meaning=bundle.data_meaning,
        capture_count=len(bundle.captures),
        bar_count=bar_count,
        instrument_ids=instrument_ids,
        board_coverage=boards,
        exchange_coverage=exchanges,
        interval_coverage=tuple(sorted({item.interval for item in bundle.captures})),
        source_profiles=tuple(sorted({item.source for item in bundle.captures})),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate sanitized market captures through the real raw replay parser",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("data/fixtures/offline-market-replay-v1.json"),
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("data/reference/local-terminal-instruments-v1.json"),
    )
    arguments = parser.parse_args()
    summary = run_offline_replay_check(
        fixture_path=arguments.fixture,
        catalog_path=arguments.catalog,
    )
    print(json.dumps(summary.to_payload(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
