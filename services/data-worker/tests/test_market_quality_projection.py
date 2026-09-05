"""Pure, loss-limited projection of raw market quality evidence."""

from __future__ import annotations

import copy
import hashlib
from datetime import UTC, datetime

import pytest
from data_worker.jobs.market_data.quality_projection import (
    MarketQualityProjectionError,
    project_market_quality_evidence,
)
from data_worker.raw.manifest import RawObjectManifest


def _manifest(*, source: str = "akshare-eastmoney") -> RawObjectManifest:
    digest = hashlib.sha256(b"fixture").hexdigest()
    return RawObjectManifest(
        object_id=digest,
        source=source,
        date="2026-08-27",
        request="GET /provider/market-data?symbol=600000",
        checksum=digest,
        size=7,
        capture_id="capture-fixture-1",
        ingest_time=datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
        available_time=datetime(2026, 8, 27, 4, 1, tzinfo=UTC),
        schema_version="market-bar-v1",
        capture_version="capture-v1",
        api_name="stock_zh_a_hist",
        unified_code="600000.SH",
        interval="DAILY",
        requested_start="2026-08-26",
        requested_end="2026-08-27",
        source_version="provider:v1",
        market_run_id="market-run-fixture",
        capture_ordinal=1,
    )


def _quality(*, source: str = "akshare-eastmoney") -> dict[str, object]:
    return {
        "schemaVersion": "market-data-quality-v1",
        "captureId": "capture-fixture-1",
        "rawObjectId": hashlib.sha256(b"fixture").hexdigest(),
        "rawChecksum": hashlib.sha256(b"fixture").hexdigest(),
        "source": source,
        "status": "REJECTED",
        "reasonCode": "BAR_QUALITY_REJECTED",
        "reasonDetail": "DO NOT EXPOSE reasonDetail secret-token",
        "rejectedRecords": [{"record": {"raw": "secret-payload"}, "reason": "password=secret"}],
        "qualityEvents": [
            {
                "kind": "OUT_OF_ORDER",
                "unifiedCode": "not-a-code",
                "timestamp": "not-a-timestamp",
                "detail": "raw detail secret-token",
            }
        ],
        "recordedAt": "2026-08-27T04:02:00+00:00",
    }


def test_projection_is_bounded_and_does_not_mutate_or_leak_raw_fields() -> None:
    manifest = _manifest()
    quality = _quality()
    original = copy.deepcopy(quality)

    projected = project_market_quality_evidence(quality, manifest)

    assert projected == {
        "evidenceId": projected["evidenceId"],
        "source": "akshare-eastmoney",
        "unifiedCode": "600000.SH",
        "interval": "DAILY",
        "requestedStart": "2026-08-26",
        "requestedEnd": "2026-08-27",
        "status": "REJECTED",
        "reasonCode": "BAR_QUALITY_REJECTED",
        "captureAvailableAt": "2026-08-27T04:01:00Z",
        "qualityRecordedAt": "2026-08-27T04:02:00Z",
        "rejectedRecordCount": 1,
        "qualityEventCount": 1,
        "filteredRecordCount": 0,
        "qualityEvents": [{"kind": "OUT_OF_ORDER", "unifiedCode": None, "timestamp": None}],
        "filteredRecords": [],
    }
    assert quality == original
    serialized = str(projected)
    for forbidden in ("capture-fixture-1", "secret-payload", "secret-token", "reasonDetail"):
        assert forbidden not in serialized
    evidence_id = projected["evidenceId"]
    assert isinstance(evidence_id, str)
    assert evidence_id.startswith("mqe-")
    assert len(evidence_id) == 68


def test_projection_keeps_valid_event_identity_and_maps_invalid_optional_parts_to_null() -> None:
    quality = _quality()
    quality["qualityEvents"] = [
        {
            "kind": "DUPLICATE",
            "unifiedCode": "600000.SH",
            "timestamp": "2026-08-27T01:31:00+08:00",
            "detail": "duplicate raw explanation",
        },
        {
            "kind": "MISSING_FIELD",
            "unifiedCode": "",
            "timestamp": "",
            "detail": "missing raw explanation",
        },
    ]
    projected = project_market_quality_evidence(quality, _manifest())

    assert projected["qualityEvents"] == [
        {
            "kind": "DUPLICATE",
            "unifiedCode": "600000.SH",
            "timestamp": "2026-08-26T17:31:00Z",
        },
        {"kind": "MISSING_FIELD", "unifiedCode": None, "timestamp": None},
    ]


def test_projection_accepts_filtered_evidence_and_preserves_only_safe_fields() -> None:
    quality = _quality(source="akshare-sina")
    quality.update(
        {
            "status": "FILTERED",
            "reasonCode": "SINA_OVERFETCH_OUTSIDE_REQUEST",
            "rejectedRecords": [],
            "qualityEvents": [],
            "filteredRecords": [
                {
                    "rawRowIndex": 3,
                    "timestamp": "2026-08-25T09:31:00+08:00",
                    "requestedStart": "2026-08-26",
                    "requestedEnd": "2026-08-27",
                    "reasonCode": "SINA_OVERFETCH_OUTSIDE_REQUEST",
                    "raw": "secret-payload",
                }
            ],
        }
    )
    quality["rawObjectId"] = quality["rawChecksum"] = hashlib.sha256(b"fixture").hexdigest()

    # The source quality sink never writes the extra raw field; the projection
    # refuses a malformed envelope instead of silently broadening its allowlist.
    with pytest.raises(MarketQualityProjectionError):
        project_market_quality_evidence(quality, _manifest(source="akshare-sina"))

    del quality["filteredRecords"][0]["raw"]  # type: ignore[index]
    projected = project_market_quality_evidence(quality, _manifest(source="akshare-sina"))
    assert projected["status"] == "FILTERED"
    assert projected["filteredRecords"] == [
        {
            "rawRowIndex": 3,
            "timestamp": "2026-08-25T01:31:00Z",
            "requestedStart": "2026-08-26",
            "requestedEnd": "2026-08-27",
            "reasonCode": "SINA_OVERFETCH_OUTSIDE_REQUEST",
        }
    ]


def test_filtered_projection_requires_manifest_window_and_excludes_requested_shanghai_dates() -> (
    None
):
    quality = _quality(source="akshare-sina")
    quality.update(
        {
            "status": "FILTERED",
            "reasonCode": "SINA_OVERFETCH_OUTSIDE_REQUEST",
            "rejectedRecords": [],
            "qualityEvents": [],
            "filteredRecords": [
                {
                    "rawRowIndex": 3,
                    "timestamp": "2026-08-25T16:00:00Z",
                    "requestedStart": "2026-08-26",
                    "requestedEnd": "2026-08-27",
                    "reasonCode": "SINA_OVERFETCH_OUTSIDE_REQUEST",
                }
            ],
        }
    )
    manifest = _manifest(source="akshare-sina")

    with pytest.raises(MarketQualityProjectionError):
        project_market_quality_evidence(quality, manifest)

    quality["filteredRecords"] = [
        {
            "rawRowIndex": 3,
            "timestamp": "2026-08-26T01:00:00Z",
            "requestedStart": "2026-08-26",
            "requestedEnd": "2026-08-27",
            "reasonCode": "SINA_OVERFETCH_OUTSIDE_REQUEST",
        }
    ]
    with pytest.raises(MarketQualityProjectionError):
        project_market_quality_evidence(quality, manifest)


def test_filtered_projection_rejects_duplicate_or_unsafe_row_indices() -> None:
    quality = _quality(source="akshare-sina")
    quality.update(
        {
            "status": "FILTERED",
            "reasonCode": "SINA_OVERFETCH_OUTSIDE_REQUEST",
            "rejectedRecords": [],
            "qualityEvents": [],
            "filteredRecords": [
                {
                    "rawRowIndex": 3,
                    "timestamp": "2026-08-25T16:00:00Z",
                    "requestedStart": "2026-08-26",
                    "requestedEnd": "2026-08-27",
                    "reasonCode": "SINA_OVERFETCH_OUTSIDE_REQUEST",
                },
                {
                    "rawRowIndex": 3,
                    "timestamp": "2026-08-28T16:00:00Z",
                    "requestedStart": "2026-08-26",
                    "requestedEnd": "2026-08-27",
                    "reasonCode": "SINA_OVERFETCH_OUTSIDE_REQUEST",
                },
            ],
        }
    )
    with pytest.raises(MarketQualityProjectionError):
        project_market_quality_evidence(quality, _manifest(source="akshare-sina"))


def test_filtered_projection_requires_sina_source() -> None:
    quality = _quality()
    quality.update(
        {
            "status": "FILTERED",
            "reasonCode": "SINA_OVERFETCH_OUTSIDE_REQUEST",
            "rejectedRecords": [],
            "qualityEvents": [],
            "filteredRecords": [
                {
                    "rawRowIndex": 3,
                    "timestamp": "2026-08-25T16:00:00Z",
                    "requestedStart": "2026-08-26",
                    "requestedEnd": "2026-08-27",
                    "reasonCode": "SINA_OVERFETCH_OUTSIDE_REQUEST",
                }
            ],
        }
    )
    with pytest.raises(MarketQualityProjectionError):
        project_market_quality_evidence(quality, _manifest())

    quality["filteredRecords"] = [
        {
            "rawRowIndex": 2**53,
            "timestamp": "2026-08-25T16:00:00Z",
            "requestedStart": "2026-08-26",
            "requestedEnd": "2026-08-27",
            "reasonCode": "SINA_OVERFETCH_OUTSIDE_REQUEST",
        }
    ]
    with pytest.raises(MarketQualityProjectionError):
        project_market_quality_evidence(quality, _manifest(source="akshare-sina"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schemaVersion", "unknown"),
        ("status", "UNKNOWN"),
        ("reasonCode", "UNKNOWN"),
        ("source", "unknown-source"),
        ("captureId", "other-capture"),
        ("rawObjectId", "f" * 64),
        ("rawChecksum", "f" * 64),
    ],
)
def test_projection_rejects_unknown_or_mismatched_identity(field: str, value: object) -> None:
    quality = _quality()
    quality[field] = value

    with pytest.raises(MarketQualityProjectionError):
        project_market_quality_evidence(quality, _manifest())


def test_projection_rejects_unknown_kind_and_time_order_or_future_evidence() -> None:
    quality = _quality()
    quality["qualityEvents"] = [
        {
            "kind": "NEW_UNKNOWN_KIND",
            "unifiedCode": None,
            "timestamp": None,
            "detail": "hidden",
        }
    ]
    with pytest.raises(MarketQualityProjectionError):
        project_market_quality_evidence(quality, _manifest())

    quality = _quality()
    quality["recordedAt"] = "2026-08-27T04:00:00+00:00"
    with pytest.raises(MarketQualityProjectionError):
        project_market_quality_evidence(quality, _manifest())

    quality = _quality()
    quality["recordedAt"] = "2099-08-27T04:02:00+00:00"
    project_market_quality_evidence(quality, _manifest())
    with pytest.raises(MarketQualityProjectionError):
        project_market_quality_evidence(
            quality,
            _manifest(),
            published_at=datetime(2026, 8, 27, 4, 3, tzinfo=UTC),
        )
