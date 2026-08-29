"""Restart-safe replay tests for market capture manifests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from ashare_contracts.market_data_bar import Bar
from data_worker.providers.akshare import AKShareBarCapture, AKShareMarketDataProvider
from data_worker.raw import LocalFileStorage, RawIntegrityError
from data_worker.raw.replay import replay_market_capture
from market_core.providers import ProviderDataError
from market_core.providers.tushare import (
    TushareBarCapture,
    TushareConfig,
    TushareMarketDataProvider,
)


def _akshare_body() -> bytes:
    return json.dumps(
        [
            {
                "日期": "2026-08-26",
                "股票代码": "600000",
                "开盘": "10.01",
                "收盘": "10.06",
                "最高": "10.08",
                "最低": "9.99",
                "成交量": "12.34",
                "成交额": "1234.50",
            }
        ],
        ensure_ascii=False,
    ).encode("utf-8")


def _akshare_minute_body() -> bytes:
    return json.dumps(
        [
            {
                "day": "2026-08-26 09:31:00",
                "股票代码": "600000",
                "开盘": "10.01",
                "收盘": "10.06",
                "最高": "10.08",
                "最低": "9.99",
                "成交量": "1234",
                "成交额": "1234.50",
            }
        ],
        ensure_ascii=False,
    ).encode("utf-8")


class CapturingBarParser:
    def __init__(self) -> None:
        self.capture: object | None = None

    def parse_bars(self, capture: object) -> list[Bar]:
        self.capture = capture
        return []


def _put_market_capture(
    storage: LocalFileStorage,
    *,
    source: str,
    body: bytes,
    api_name: str,
    unified_code: str = "600000.SH",
    interval: str = "DAILY",
    capture_id: str = "market-replay-1",
    source_version: str | None = None,
):
    received_at = datetime(2026, 8, 27, 4, 0, 5, tzinfo=UTC)
    return storage.put(
        source,
        "2026-08-27",
        f"GET /{source}/{api_name}?code={unified_code[:6]}",
        body,
        content_type="application/json; charset=utf-8",
        capture_id=capture_id,
        ingest_time=received_at,
        available_time=received_at,
        schema_version="market-bar-v1",
        capture_version="capture-v1",
        api_name=api_name,
        unified_code=unified_code,
        interval=interval,
        requested_start="2026-08-26",
        requested_end="2026-08-26",
        source_version=source_version
        or (
            f"akshare:1.18.94:{api_name}:{'v1' if source == 'akshare-eastmoney' else 'v2'}"
            if source in {"akshare-eastmoney", "akshare-tencent", "akshare-sina"}
            else f"tushare:{api_name}:v1"
        ),
        market_run_id="market-run-replay",
        capture_ordinal=1,
    )


def test_market_replay_rebuilds_akshare_capture_after_storage_restart(
    tmp_path: Path,
) -> None:
    body = _akshare_body()
    storage = LocalFileStorage(tmp_path)
    manifest = _put_market_capture(
        storage,
        source="akshare-eastmoney",
        body=body,
        api_name="stock_zh_a_hist",
    )
    original_capture = AKShareBarCapture(
        body=body,
        api_name="stock_zh_a_hist",
        request=manifest.request,
        unified_code="600000.SH",
        interval="DAILY",
        start_date="2026-08-26",
        end_date="2026-08-26",
        received_at=manifest.received_at,
        source=manifest.source,
        source_version=manifest.source_version or "",
        content_type=manifest.content_type,
    )
    parser = AKShareMarketDataProvider()
    expected = parser.parse_bars(original_capture)

    restarted = LocalFileStorage(tmp_path)
    loaded_manifest = restarted.list("akshare-eastmoney", "2026-08-27")[0]
    replayed = replay_market_capture(restarted, loaded_manifest, AKShareMarketDataProvider())

    assert replayed == expected
    assert replayed[0].close == Decimal("10.06")


def test_market_replay_routes_tushare_capture_by_source(tmp_path: Path) -> None:
    body = json.dumps(
        {
            "code": 0,
            "data": {
                "fields": [
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "vol",
                    "amount",
                ],
                "items": [["600000.SH", "20260826", 10.01, 10.08, 9.99, 10.06, 12.34, 1234.50]],
            },
        }
    ).encode("utf-8")
    storage = LocalFileStorage(tmp_path)
    manifest = _put_market_capture(
        storage,
        source="tushare-pro",
        body=body,
        api_name="daily",
    )
    parser = TushareMarketDataProvider(TushareConfig(token="test-token"))
    original_capture = TushareBarCapture(
        body=body,
        api_name="daily",
        request=manifest.request,
        unified_code="600000.SH",
        interval="DAILY",
        start_date="2026-08-26",
        end_date="2026-08-26",
        received_at=manifest.received_at,
        source=manifest.source,
        source_version=manifest.source_version or "",
        content_type=manifest.content_type,
    )

    assert replay_market_capture(storage, manifest, parser) == parser.parse_bars(original_capture)


@pytest.mark.parametrize(
    ("source", "api_name", "interval", "body"),
    [
        ("akshare-tencent", "stock_zh_a_hist_tx", "DAILY", _akshare_body()),
        ("akshare-sina", "stock_zh_a_minute", "MINUTE_1", _akshare_minute_body()),
    ],
)
def test_market_replay_routes_akshare_sources_to_capture_envelope(
    tmp_path: Path,
    source: str,
    api_name: str,
    interval: str,
    body: bytes,
) -> None:
    storage = LocalFileStorage(tmp_path)
    manifest = _put_market_capture(
        storage,
        source=source,
        body=body,
        api_name=api_name,
        interval=interval,
        capture_id=f"market-replay-{source}",
    )
    parser = CapturingBarParser()

    assert replay_market_capture(storage, manifest, parser) == []
    assert isinstance(parser.capture, AKShareBarCapture)
    assert parser.capture.source == source
    assert parser.capture.api_name == api_name
    assert parser.capture.interval == interval
    assert parser.capture.source_version == manifest.source_version


def test_market_replay_rejects_tampered_body_before_provider_parse(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    manifest = _put_market_capture(
        storage,
        source="akshare-eastmoney",
        body=_akshare_body(),
        api_name="stock_zh_a_hist",
    )
    (tmp_path / "objects" / manifest.object_id).write_bytes(b"tampered")

    with pytest.raises(RawIntegrityError, match="checksum|size"):
        replay_market_capture(storage, manifest, AKShareMarketDataProvider())


def test_market_replay_preserves_ambiguous_legacy_index_minute_raw_but_rejects_parse(
    tmp_path: Path,
) -> None:
    body = _akshare_minute_body()
    storage = LocalFileStorage(tmp_path)
    manifest = _put_market_capture(
        storage,
        source="akshare-eastmoney",
        body=body,
        api_name="index_zh_a_hist_min_em",
        unified_code="000001.SH",
        interval="MINUTE_5",
        capture_id="market-replay-ambiguous-index-minute",
    )

    with pytest.raises(ProviderDataError, match="unsupported|ambiguous.*price semantics"):
        replay_market_capture(storage, manifest, AKShareMarketDataProvider())

    assert storage.get(manifest.object_id, checksum=manifest.checksum, size=manifest.size) == body
    assert manifest.source == "akshare-eastmoney"
    assert manifest.api_name == "index_zh_a_hist_min_em"
    assert manifest.interval == "MINUTE_5"


@pytest.mark.parametrize(
    ("source", "api_name", "interval", "source_version"),
    [
        (
            "akshare-sina",
            "stock_zh_a_hist_tx",
            "DAILY",
            "akshare:99.0.0:other_endpoint:v99",
        ),
        (
            "akshare-tencent",
            "stock_zh_a_hist",
            "DAILY",
            "akshare:1.18.94:stock_zh_a_hist:v1",
        ),
        (
            "akshare-sina",
            "stock_zh_a_minute",
            "DAILY",
            "akshare:1.18.94:stock_zh_a_minute:v2",
        ),
        (
            "akshare-sina",
            "stock_zh_a_minute",
            "MINUTE_1",
            "akshare:99.0.0:stock_zh_a_minute:v99",
        ),
    ],
)
def test_market_replay_rejects_akshare_profile_mismatch_before_parser(
    tmp_path: Path,
    source: str,
    api_name: str,
    interval: str,
    source_version: str,
) -> None:
    body = _akshare_body() if interval == "DAILY" else _akshare_minute_body()
    storage = LocalFileStorage(tmp_path)
    manifest = _put_market_capture(
        storage,
        source=source,
        body=body,
        api_name=api_name,
        interval=interval,
        source_version=source_version,
        capture_id="market-replay-bad-profile",
    )
    parser = CapturingBarParser()

    with pytest.raises(ProviderDataError, match="unsupported.*capture profile"):
        replay_market_capture(storage, manifest, parser)

    assert parser.capture is None
    assert storage.get(manifest.object_id, checksum=manifest.checksum, size=manifest.size) == body


def test_market_replay_rejects_unknown_source(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    manifest = _put_market_capture(
        storage,
        source="unknown-provider",
        body=b"[]",
        api_name="unknown_api",
        capture_id="market-unknown-source",
    )

    parser = CapturingBarParser()
    with pytest.raises(ValueError, match="unknown source"):
        replay_market_capture(storage, manifest, parser)

    assert parser.capture is None
    assert storage.get(manifest.object_id, checksum=manifest.checksum, size=manifest.size) == b"[]"


@pytest.mark.parametrize(
    ("api_name", "interval", "source_version"),
    [
        ("fund_daily", "DAILY", "tushare:fund_daily:v1"),
        ("daily", "MINUTE_1", "tushare:daily:v1"),
        ("daily", "DAILY", "tushare:daily:v2"),
    ],
)
def test_market_replay_rejects_tushare_profile_mismatch_before_parser(
    tmp_path: Path,
    api_name: str,
    interval: str,
    source_version: str,
) -> None:
    body = b"replay-body-secret"
    storage = LocalFileStorage(tmp_path)
    manifest = _put_market_capture(
        storage,
        source="tushare-pro",
        body=body,
        api_name=api_name,
        interval=interval,
        source_version=source_version,
        capture_id="market-replay-bad-tushare-profile",
    )
    parser = CapturingBarParser()

    with pytest.raises(ProviderDataError, match="unsupported.*capture profile"):
        replay_market_capture(storage, manifest, parser)

    assert parser.capture is None
    assert storage.get(manifest.object_id, checksum=manifest.checksum, size=manifest.size) == body


@pytest.mark.parametrize("unified_code", ["000001.SH", "518880.SH"])
def test_market_replay_rejects_legacy_stock_daily_profile_for_non_stock_before_parser(
    tmp_path: Path,
    unified_code: str,
) -> None:
    body = _akshare_body()
    storage = LocalFileStorage(tmp_path)
    manifest = _put_market_capture(
        storage,
        source="akshare-eastmoney",
        body=body,
        api_name="stock_zh_a_hist",
        unified_code=unified_code,
        interval="DAILY",
        capture_id=f"market-replay-legacy-stock-{unified_code}",
    )
    parser = CapturingBarParser()

    with pytest.raises(ProviderDataError, match="unsupported.*capture profile"):
        replay_market_capture(storage, manifest, parser)

    assert parser.capture is None
    assert storage.get(manifest.object_id, checksum=manifest.checksum, size=manifest.size) == body


def test_market_replay_rejects_incomplete_manifest_route(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    manifest = _put_market_capture(
        storage,
        source="akshare-eastmoney",
        body=_akshare_body(),
        api_name="stock_zh_a_hist",
        capture_id="market-incomplete-route",
    )
    object.__setattr__(manifest, "api_name", None)

    with pytest.raises(ValueError, match="incomplete"):
        replay_market_capture(storage, manifest, AKShareMarketDataProvider())


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("schema_version", "market-bar-v2"), ("capture_version", "capture-v2")],
)
def test_market_replay_rejects_unknown_capture_versions(
    tmp_path: Path, field_name: str, value: str
) -> None:
    storage = LocalFileStorage(tmp_path)
    manifest = _put_market_capture(
        storage,
        source="akshare-eastmoney",
        body=_akshare_body(),
        api_name="stock_zh_a_hist",
        capture_id=f"market-replay-unknown-{field_name}",
    )
    object.__setattr__(manifest, field_name, value)

    with pytest.raises(ValueError, match="version"):
        replay_market_capture(storage, manifest, AKShareMarketDataProvider())


def test_market_replay_rejects_tampered_manifest_binding(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    _put_market_capture(
        storage,
        source="akshare-eastmoney",
        body=_akshare_body(),
        api_name="stock_zh_a_hist",
        capture_id="market-tampered-manifest",
    )
    manifest_path = next(
        (tmp_path / "index" / "akshare-eastmoney" / "2026-08-27").glob(
            "market-tampered-manifest.*.json"
        )
    )
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["unified_code"] = "600001.SH"
    manifest_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(RawIntegrityError, match="manifest|digest"):
        LocalFileStorage(tmp_path).list("akshare-eastmoney", "2026-08-27")
