"""Raw-first collection tests for real market bars."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from ashare_contracts.market_data_bar import Bar
from data_worker.jobs.market_data.collector import MarketDataCollector, RawBarCapture
from data_worker.jobs.market_data.quality import MarketDataQualitySink, QualitySinkError
from data_worker.providers.akshare import AKShareBarCapture, AKShareMarketDataProvider
from data_worker.raw.storage import LocalFileStorage
from market_core.providers import ProviderDataError
from market_core.providers.tushare import TushareBarCapture
from market_core.storage import StoredBar


class FakeProvider:
    def __init__(self, *, fail_parse: bool = False) -> None:
        self.fail_parse = fail_parse
        self.fetch_calls = 0

    def fetch_raw_bars(
        self,
        unified_code: str,
        interval: str,
        start_date: str,
        end_date: str,
        cursor: str | None = None,
    ) -> RawBarCapture:
        assert cursor is None
        self.fetch_calls += 1
        return TushareBarCapture(
            body=json.dumps({"real": True}).encode("utf-8"),
            api_name="rt_min_daily",
            request="POST /?code=600000.SH&date=2026-08-27",
            unified_code=unified_code,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            received_at=datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
        )

    def parse_bars(self, capture: RawBarCapture) -> list[Bar]:
        del capture
        if self.fail_parse:
            raise ProviderDataError("invalid row")
        return [
            Bar.model_validate(
                {
                    "unifiedCode": "600000.SH",
                    "exchange": "SH",
                    "date": "2026-08-27",
                    "interval": "MINUTE_1",
                    "session": "CONTINUOUS",
                    "timestamp": "2026-08-27T01:31:00.000Z",
                    "open": Decimal("10.01"),
                    "high": Decimal("10.08"),
                    "low": Decimal("9.99"),
                    "close": Decimal("10.06"),
                    "volume": 1200,
                    "amount": Decimal("12072.5"),
                    "priceType": "RAW",
                }
            )
        ]


class RecordingWriter:
    def __init__(self) -> None:
        self.rows: list[StoredBar] = []

    def write_bars(self, bars: Iterable[StoredBar]) -> int:
        collected = list(bars)
        self.rows.extend(collected)
        return len(collected)


def test_retry_replays_persisted_raw_capture_without_fetching_new_payload(
    tmp_path: Path,
) -> None:
    provider = FakeProvider()
    raw = LocalFileStorage(tmp_path / "raw")
    writer = RecordingWriter()
    collector = MarketDataCollector(
        provider,
        raw,
        writer,
        quality_sink=MarketDataQualitySink(tmp_path / "market-quality"),
    )

    first = collector.collect(
        "600000.SH",
        "MINUTE_1",
        "2026-08-27",
        "2026-08-27",
        run_id="restartable-run",
        capture_ordinal=1,
        processing_time=datetime(2026, 8, 27, 5, 0, tzinfo=UTC),
    )
    second = collector.collect(
        "600000.SH",
        "MINUTE_1",
        "2026-08-27",
        "2026-08-27",
        run_id="restartable-run",
        capture_ordinal=1,
        processing_time=datetime(2026, 8, 27, 5, 0, tzinfo=UTC),
    )

    assert second.raw_capture_id == first.raw_capture_id
    assert provider.fetch_calls == 1
    assert len(raw.list("tushare-pro", "2026-08-27")) == 1
    assert writer.rows[0] == writer.rows[1]


class DuplicateBarsProvider(FakeProvider):
    def parse_bars(self, capture: RawBarCapture) -> list[Bar]:
        bar = super().parse_bars(capture)[0]
        return [bar, bar.model_copy(deep=True)]


class OutOfOrderBarsProvider(FakeProvider):
    def parse_bars(self, capture: RawBarCapture) -> list[Bar]:
        bar = super().parse_bars(capture)[0]
        return [
            bar.model_copy(update={"timestamp": datetime(2026, 8, 27, 1, 32, tzinfo=UTC)}),
            bar.model_copy(update={"timestamp": datetime(2026, 8, 27, 1, 31, tzinfo=UTC)}),
        ]


class FailingQualitySink:
    def record(self, *_args: object, **_kwargs: object) -> None:
        raise QualitySinkError("quality evidence publish failed")


def _sina_row(day: str, *, close: str = "10.06") -> dict[str, object]:
    return {
        "day": day,
        "股票代码": "600000",
        "开盘": "10.01",
        "收盘": close,
        "最高": "10.08",
        "最低": "9.99",
        "成交量": "1234",
        "成交额": "1234.50",
    }


class SinaEvidenceProvider:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._delegate = AKShareMarketDataProvider()
        self._capture = AKShareBarCapture(
            body=json.dumps(rows, ensure_ascii=False).encode("utf-8"),
            api_name="stock_zh_a_minute",
            request="GET /akshare/stock_zh_a_minute?code=600000",
            unified_code="600000.SH",
            interval="MINUTE_1",
            start_date="2026-08-27",
            end_date="2026-08-27",
            received_at=datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
            source="akshare-sina",
            source_version="akshare:1.18.94:stock_zh_a_minute:v2",
        )

    def fetch_raw_bars(
        self,
        unified_code: str,
        interval: str,
        start_date: str,
        end_date: str,
        cursor: str | None = None,
    ) -> AKShareBarCapture:
        del unified_code, interval, start_date, end_date, cursor
        return self._capture

    def parse_bars(self, capture: RawBarCapture) -> list[Bar]:
        return self._delegate.parse_bars(capture)

    def parse_bars_with_evidence(self, capture: RawBarCapture) -> object:
        return self._delegate.parse_bars_with_evidence(capture)


def _quality_evidence(root: Path) -> dict[str, object]:
    paths = list(root.glob("*.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text(encoding="utf-8"))


def test_sina_overfetch_writes_only_in_window_and_persists_filter_evidence(
    tmp_path: Path,
) -> None:
    raw = LocalFileStorage(tmp_path / "raw")
    writer = RecordingWriter()
    quality_root = tmp_path / "market-quality"
    collector = MarketDataCollector(
        SinaEvidenceProvider(
            [
                _sina_row("2026-08-26 09:31:00"),
                _sina_row("2026-08-27 09:31:00"),
            ]
        ),
        raw,
        writer,
        quality_sink=MarketDataQualitySink(quality_root),
    )

    result = collector.collect(
        "600000.SH",
        "MINUTE_1",
        "2026-08-27",
        "2026-08-27",
        run_id="run-sina-filtered",
        capture_ordinal=1,
    )

    manifest = raw.list("akshare-sina", "2026-08-27")[0]
    assert (
        len(json.loads(raw.get(manifest.object_id, checksum=manifest.checksum, size=manifest.size)))
        == 2
    )
    assert result.received_bars == 1
    assert result.written_bars == 1
    assert len(writer.rows) == 1
    evidence = _quality_evidence(quality_root)
    assert evidence["status"] == "FILTERED"
    assert evidence["reasonCode"] == "SINA_OVERFETCH_OUTSIDE_REQUEST"
    assert evidence["captureId"] == manifest.capture_id
    assert evidence["rawObjectId"] == manifest.object_id
    assert evidence["rawChecksum"] == manifest.checksum
    assert evidence["filteredRecords"] == [
        {
            "rawRowIndex": 0,
            "timestamp": "2026-08-26T01:31:00+00:00",
            "requestedStart": "2026-08-27",
            "requestedEnd": "2026-08-27",
            "reasonCode": "SINA_OVERFETCH_OUTSIDE_REQUEST",
        }
    ]


def test_filtered_quality_public_publish_failure_stops_bar_write(tmp_path: Path) -> None:
    class FailingPublisher:
        def publish_capture(self) -> object:
            raise RuntimeError("public evidence unavailable")

    raw = LocalFileStorage(tmp_path / "raw")
    writer = RecordingWriter()
    collector = MarketDataCollector(
        SinaEvidenceProvider(
            [
                _sina_row("2026-08-26 09:31:00"),
                _sina_row("2026-08-27 09:31:00"),
            ]
        ),
        raw,
        writer,
        quality_sink=MarketDataQualitySink(
            tmp_path / "market-quality", publisher=FailingPublisher()
        ),
    )

    with pytest.raises(QualitySinkError, match="public publish"):
        collector.collect(
            "600000.SH",
            "MINUTE_1",
            "2026-08-27",
            "2026-08-27",
            run_id="run-sina-public-publish-failure",
            capture_ordinal=1,
        )

    assert len(raw.list("akshare-sina", "2026-08-27")) == 1
    assert writer.rows == []


def test_sina_filter_evidence_failure_stops_writer_after_raw_capture(tmp_path: Path) -> None:
    raw = LocalFileStorage(tmp_path / "raw")
    writer = RecordingWriter()
    collector = MarketDataCollector(
        SinaEvidenceProvider(
            [
                _sina_row("2026-08-26 09:31:00"),
                _sina_row("2026-08-27 09:31:00"),
            ]
        ),
        raw,
        writer,
        quality_sink=FailingQualitySink(),
    )

    with pytest.raises(QualitySinkError, match="publish"):
        collector.collect(
            "600000.SH",
            "MINUTE_1",
            "2026-08-27",
            "2026-08-27",
            run_id="run-sina-filter-failure",
            capture_ordinal=1,
        )

    assert len(raw.list("akshare-sina", "2026-08-27")) == 1
    assert writer.rows == []


@pytest.mark.parametrize(
    ("in_window_rows", "event_kind"),
    [
        (
            [
                _sina_row("2026-08-27 09:32:00"),
                _sina_row("2026-08-27 09:31:00"),
            ],
            "OUT_OF_ORDER",
        ),
        (
            [
                _sina_row("2026-08-27 09:31:00"),
                _sina_row("2026-08-27 09:31:00"),
            ],
            "DUPLICATE",
        ),
    ],
)
def test_sina_filter_and_pipeline_rejection_publish_one_final_evidence(
    tmp_path: Path,
    in_window_rows: list[dict[str, object]],
    event_kind: str,
) -> None:
    raw = LocalFileStorage(tmp_path / "raw")
    writer = RecordingWriter()
    quality_root = tmp_path / "market-quality"
    collector = MarketDataCollector(
        SinaEvidenceProvider([_sina_row("2026-08-26 09:31:00"), *in_window_rows]),
        raw,
        writer,
        quality_sink=MarketDataQualitySink(quality_root),
    )

    with pytest.raises(ProviderDataError, match="quality rejection"):
        collector.collect(
            "600000.SH",
            "MINUTE_1",
            "2026-08-27",
            "2026-08-27",
            run_id=f"run-sina-{event_kind.lower()}",
            capture_ordinal=1,
        )

    assert writer.rows == []
    evidence = _quality_evidence(quality_root)
    assert evidence["status"] == "REJECTED"
    assert evidence["reasonCode"] == "BAR_QUALITY_REJECTED"
    assert evidence["filteredRecords"]
    raw_quality_events = evidence["qualityEvents"]
    assert isinstance(raw_quality_events, list)
    quality_events = cast(list[object], raw_quality_events)
    assert len(quality_events) == 1
    first_event = quality_events[0]
    assert isinstance(first_event, dict)
    assert first_event["kind"] == event_kind


def test_collector_persists_raw_before_versioned_bars(tmp_path: Path) -> None:
    raw = LocalFileStorage(tmp_path)
    writer = RecordingWriter()
    quality = MarketDataQualitySink(tmp_path / "market-quality")
    collector = MarketDataCollector(
        FakeProvider(),
        raw,
        writer,
        quality_sink=quality,
        clock=lambda: datetime(2026, 8, 27, 4, 0, 5, tzinfo=UTC),
    )

    result = collector.collect(
        "600000.SH",
        "MINUTE_1",
        "2026-08-27",
        "2026-08-27",
        run_id="run-20260827-0001",
        capture_ordinal=1,
    )

    manifests = raw.list("tushare-pro", "2026-08-27")
    assert result.raw_capture_id == manifests[0].capture_id
    assert result.written_bars == 1
    stored = writer.rows[0]
    assert stored.raw_capture_id == manifests[0].capture_id
    assert stored.source == "tushare-pro"
    assert stored.source_version == "tushare:rt_min_daily:v1"
    assert stored.available_time == datetime(2026, 8, 27, 4, 0, tzinfo=UTC)
    assert stored.processing_time == datetime(2026, 8, 27, 4, 0, 5, tzinfo=UTC)
    assert manifests[0].schema_version == "market-bar-v1"
    assert manifests[0].capture_version == "capture-v1"
    assert manifests[0].api_name == "rt_min_daily"
    assert manifests[0].unified_code == "600000.SH"
    assert manifests[0].interval == "MINUTE_1"
    assert manifests[0].requested_start == "2026-08-27"
    assert manifests[0].requested_end == "2026-08-27"
    assert manifests[0].source_version == "tushare:rt_min_daily:v1"
    assert manifests[0].market_run_id == "run-20260827-0001"
    assert manifests[0].capture_ordinal == 1
    assert list((tmp_path / "market-quality").glob("*.json")) == []


def test_parse_failure_keeps_raw_evidence_and_writes_nothing(tmp_path: Path) -> None:
    raw = LocalFileStorage(tmp_path)
    writer = RecordingWriter()
    quality = MarketDataQualitySink(tmp_path / "market-quality")
    collector = MarketDataCollector(
        FakeProvider(fail_parse=True), raw, writer, quality_sink=quality
    )

    with pytest.raises(ProviderDataError, match="captureId") as exc_info:
        collector.collect(
            "600000.SH",
            "MINUTE_1",
            "2026-08-27",
            "2026-08-27",
            run_id="run-20260827-0002",
            capture_ordinal=1,
        )

    assert len(raw.list("tushare-pro", "2026-08-27")) == 1
    assert writer.rows == []
    assert "market-" in str(exc_info.value)
    evidence = json.loads(
        next((tmp_path / "market-quality").glob("*.json")).read_text(encoding="utf-8")
    )
    assert evidence["status"] == "REJECTED"
    assert evidence["reasonCode"] == "PROVIDER_PARSE_ERROR"
    assert evidence["captureId"] == raw.list("tushare-pro", "2026-08-27")[0].capture_id
    assert evidence["rejectedRecords"] == [
        {
            "record": {
                "apiName": "rt_min_daily",
                "unifiedCode": "600000.SH",
                "interval": "MINUTE_1",
                "requestedStart": "2026-08-27",
                "requestedEnd": "2026-08-27",
            },
            "reason": "provider_parse_error",
        }
    ]
    rejected_record = evidence["rejectedRecords"][0]["record"]
    assert "request" not in rejected_record
    assert "invalid row" not in json.dumps(evidence, ensure_ascii=False)


def test_duplicate_bars_keep_raw_evidence_and_write_nothing(tmp_path: Path) -> None:
    raw = LocalFileStorage(tmp_path)
    writer = RecordingWriter()
    quality = MarketDataQualitySink(tmp_path / "market-quality")
    collector = MarketDataCollector(DuplicateBarsProvider(), raw, writer, quality_sink=quality)

    with pytest.raises(ProviderDataError, match="captureId"):
        collector.collect(
            "600000.SH",
            "MINUTE_1",
            "2026-08-27",
            "2026-08-27",
            run_id="run-20260827-duplicate",
            capture_ordinal=1,
        )

    assert len(raw.list("tushare-pro", "2026-08-27")) == 1
    assert writer.rows == []
    evidence = json.loads(
        next((tmp_path / "market-quality").glob("*.json")).read_text(encoding="utf-8")
    )
    assert any(event["kind"] == "DUPLICATE" for event in evidence["qualityEvents"])
    assert evidence["rejectedRecords"]


def test_out_of_order_bars_keep_raw_quality_evidence_and_write_nothing(tmp_path: Path) -> None:
    raw = LocalFileStorage(tmp_path)
    writer = RecordingWriter()
    quality = MarketDataQualitySink(tmp_path / "market-quality")
    collector = MarketDataCollector(OutOfOrderBarsProvider(), raw, writer, quality_sink=quality)

    with pytest.raises(ProviderDataError, match="captureId"):
        collector.collect(
            "600000.SH",
            "MINUTE_1",
            "2026-08-27",
            "2026-08-27",
            run_id="run-20260827-out-of-order",
            capture_ordinal=1,
        )

    assert len(raw.list("tushare-pro", "2026-08-27")) == 1
    assert writer.rows == []
    evidence = json.loads(
        next((tmp_path / "market-quality").glob("*.json")).read_text(encoding="utf-8")
    )
    assert any(event["kind"] == "OUT_OF_ORDER" for event in evidence["qualityEvents"])
    assert evidence["rejectedRecords"]


def test_quality_sink_failure_stops_writer_after_raw_capture(tmp_path: Path) -> None:
    raw = LocalFileStorage(tmp_path)
    writer = RecordingWriter()
    collector = MarketDataCollector(
        DuplicateBarsProvider(), raw, writer, quality_sink=FailingQualitySink()
    )

    with pytest.raises(QualitySinkError, match="publish"):
        collector.collect(
            "600000.SH",
            "MINUTE_1",
            "2026-08-27",
            "2026-08-27",
            run_id="run-20260827-quality-failure",
            capture_ordinal=1,
        )

    assert len(raw.list("tushare-pro", "2026-08-27")) == 1
    assert writer.rows == []


class AKShareProvenanceProvider(FakeProvider):
    def fetch_raw_bars(
        self,
        unified_code: str,
        interval: str,
        start_date: str,
        end_date: str,
        cursor: str | None = None,
    ) -> AKShareBarCapture:
        del cursor
        return AKShareBarCapture(
            body=b'{"columns":[],"data":[]}',
            api_name="stock_zh_a_hist_min_em",
            request="GET /akshare/stock_zh_a_hist_min_em?code=600000&date=2026-08-27",
            unified_code=unified_code,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            received_at=datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
            source="akshare-eastmoney",
            source_version="akshare:1.18.94:stock_zh_a_hist_min_em:v1",
            content_type="application/json; charset=utf-8",
        )


def test_collector_uses_capture_provenance_without_provider_type_branching(tmp_path: Path) -> None:
    raw = LocalFileStorage(tmp_path)
    writer = RecordingWriter()
    collector = MarketDataCollector(
        AKShareProvenanceProvider(),
        raw,
        writer,
        quality_sink=MarketDataQualitySink(tmp_path / "market-quality"),
        clock=lambda: datetime(2026, 8, 27, 4, 0, 5, tzinfo=UTC),
    )

    result = collector.collect(
        "600000.SH",
        "MINUTE_1",
        "2026-08-27",
        "2026-08-27",
        run_id="run-akshare-1",
        capture_ordinal=1,
    )

    manifests = raw.list("akshare-eastmoney", "2026-08-27")
    assert result.raw_capture_id == manifests[0].capture_id
    assert manifests[0].content_type == "application/json; charset=utf-8"
    assert writer.rows[0].source == "akshare-eastmoney"
    assert writer.rows[0].source_version == "akshare:1.18.94:stock_zh_a_hist_min_em:v1"
