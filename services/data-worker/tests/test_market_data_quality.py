"""Durable market-data rejection evidence tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from data_worker.jobs.market_data.quality import (
    MarketDataQualitySink,
    QualityEvidenceConflictError,
    QualitySinkError,
)
from data_worker.raw import LocalFileStorage
from data_worker.raw.manifest import RawObjectManifest


def _manifest(
    tmp_path: Path,
    *,
    source: str = "akshare-eastmoney",
    api_name: str = "stock_zh_a_hist",
    source_version: str = "akshare:1.18.94:stock_zh_a_hist:v1",
) -> RawObjectManifest:
    return LocalFileStorage(tmp_path / "raw").put(
        source,
        "2026-08-27",
        f"GET /akshare/{api_name}?code=600000&token=secret",
        b"[]",
        content_type="application/json; charset=utf-8",
        capture_id="quality-capture-1",
        ingest_time=datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
        available_time=datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
        schema_version="market-bar-v1",
        capture_version="capture-v1",
        api_name=api_name,
        unified_code="600000.SH",
        interval="DAILY",
        requested_start="2026-08-26",
        requested_end="2026-08-26",
        source_version=source_version,
        market_run_id="market-run-1",
        capture_ordinal=1,
    )


def _record(
    sink: MarketDataQualitySink,
    manifest: RawObjectManifest,
    *,
    recorded_at: datetime,
) -> Path:
    return sink.record(
        manifest,
        reason_code="BAR_QUALITY_REJECTED",
        reason_detail="one or more bars failed quality validation",
        rejected_records=[
            {
                "record": {"unifiedCode": "600000.SH", "timestamp": "2026-08-27T01:31:00Z"},
                "reason": "sequence: out-of-order timestamp",
            }
        ],
        quality_events=[
            {
                "kind": "OUT_OF_ORDER",
                "unifiedCode": "600000.SH",
                "timestamp": "2026-08-27T01:31:00Z",
                "detail": "out-of-order timestamp",
            }
        ],
        recorded_at=recorded_at,
    )


def test_quality_sink_writes_controlled_evidence_in_sibling_tree(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    sink = MarketDataQualitySink(tmp_path / "raw" / "market-quality")

    path = _record(sink, manifest, recorded_at=datetime(2026, 8, 27, 4, 1, tzinfo=UTC))
    evidence = json.loads(path.read_text(encoding="utf-8"))

    assert evidence["schemaVersion"] == "market-data-quality-v1"
    assert evidence["captureId"] == manifest.capture_id
    assert evidence["rawObjectId"] == manifest.object_id
    assert evidence["rawChecksum"] == manifest.checksum
    assert evidence["source"] == "akshare-eastmoney"
    assert evidence["status"] == "REJECTED"
    assert evidence["reasonCode"] == "BAR_QUALITY_REJECTED"
    assert evidence["rejectedRecords"][0]["reason"]
    assert evidence["qualityEvents"][0]["kind"] == "OUT_OF_ORDER"
    assert "secret" not in json.dumps(evidence)
    assert path.parent == tmp_path / "raw" / "market-quality"
    assert (tmp_path / "raw" / "objects" / manifest.object_id).exists()
    assert list((tmp_path / "raw" / "index").rglob("*.json"))


def test_quality_sink_persists_filtered_overfetch_evidence(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        source="akshare-sina",
        api_name="stock_zh_a_minute",
        source_version="akshare:1.18.94:stock_zh_a_minute:v2",
    )
    sink = MarketDataQualitySink(tmp_path / "raw" / "market-quality")

    path = sink.record(
        manifest,
        status="FILTERED",
        reason_code="SINA_OVERFETCH_OUTSIDE_REQUEST",
        reason_detail="Sina minute payload included rows outside the requested window",
        rejected_records=[],
        quality_events=[],
        filtered_records=[
            {
                "rawRowIndex": 0,
                "timestamp": "2026-08-26T01:31:00+00:00",
                "requestedStart": "2026-08-27",
                "requestedEnd": "2026-08-27",
                "reasonCode": "SINA_OVERFETCH_OUTSIDE_REQUEST",
            }
        ],
        recorded_at=datetime(2026, 8, 27, 4, 1, tzinfo=UTC),
    )

    evidence = json.loads(path.read_text(encoding="utf-8"))
    assert evidence["status"] == "FILTERED"
    assert evidence["reasonCode"] == "SINA_OVERFETCH_OUTSIDE_REQUEST"
    assert evidence["filteredRecords"] == [
        {
            "rawRowIndex": 0,
            "timestamp": "2026-08-26T01:31:00+00:00",
            "requestedStart": "2026-08-27",
            "requestedEnd": "2026-08-27",
            "reasonCode": "SINA_OVERFETCH_OUTSIDE_REQUEST",
        }
    ]


def test_quality_sink_is_idempotent_and_keeps_first_recorded_at(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    sink = MarketDataQualitySink(tmp_path / "raw" / "market-quality")
    first_time = datetime(2026, 8, 27, 4, 1, tzinfo=UTC)
    second_time = datetime(2026, 8, 27, 4, 2, tzinfo=UTC)

    first = _record(sink, manifest, recorded_at=first_time)
    second = _record(sink, manifest, recorded_at=second_time)

    assert second == first
    evidence = json.loads(first.read_text(encoding="utf-8"))
    assert evidence["recordedAt"] == first_time.isoformat()
    assert len(list((tmp_path / "raw" / "market-quality").glob("*.json"))) == 1


def test_quality_sink_retries_public_publish_on_idempotent_capture(tmp_path: Path) -> None:
    class Publisher:
        def __init__(self) -> None:
            self.calls = 0

        def publish_capture(self) -> object:
            self.calls += 1
            return None

    publisher = Publisher()
    manifest = _manifest(tmp_path)
    sink = MarketDataQualitySink(tmp_path / "raw" / "market-quality", publisher=publisher)
    first_time = datetime(2026, 8, 27, 4, 1, tzinfo=UTC)

    _record(sink, manifest, recorded_at=first_time)
    _record(sink, manifest, recorded_at=datetime(2026, 8, 27, 4, 2, tzinfo=UTC))

    assert publisher.calls == 2


def test_quality_sink_keeps_raw_evidence_when_public_publish_fails(tmp_path: Path) -> None:
    class FailingPublisher:
        def publish_capture(self) -> object:
            raise RuntimeError("untrusted publisher detail")

    manifest = _manifest(tmp_path)
    quality_root = tmp_path / "raw" / "market-quality"
    sink = MarketDataQualitySink(quality_root, publisher=FailingPublisher())

    with pytest.raises(QualitySinkError, match="public publish") as error:
        _record(sink, manifest, recorded_at=datetime(2026, 8, 27, 4, 1, tzinfo=UTC))

    assert "untrusted publisher detail" not in str(error.value)
    assert (quality_root / f"{manifest.capture_id}.json").exists()


def test_quality_sink_rejects_conflicting_semantics_for_same_capture(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    sink = MarketDataQualitySink(tmp_path / "raw" / "market-quality")
    _record(sink, manifest, recorded_at=datetime(2026, 8, 27, 4, 1, tzinfo=UTC))

    with pytest.raises(QualityEvidenceConflictError):
        sink.record(
            manifest,
            reason_code="PROVIDER_PARSE_ERROR",
            reason_detail="provider parse failed",
            rejected_records=[],
            quality_events=[],
            recorded_at=datetime(2026, 8, 27, 4, 2, tzinfo=UTC),
        )


def test_quality_sink_atomic_publish_failure_leaves_no_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    quality_root = tmp_path / "raw" / "market-quality"
    sink = MarketDataQualitySink(quality_root)

    def fail_replace(_source: str | bytes | Path, _destination: str | bytes | Path) -> None:
        raise OSError("simulated publish failure")

    monkeypatch.setattr("data_worker.jobs.market_data.quality.os.replace", fail_replace)

    with pytest.raises(QualitySinkError, match="publish"):
        _record(sink, manifest, recorded_at=datetime(2026, 8, 27, 4, 1, tzinfo=UTC))

    assert not (quality_root / f"{manifest.capture_id}.json").exists()
    assert list(quality_root.glob("*.tmp")) == []
