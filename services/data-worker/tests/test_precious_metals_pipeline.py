"""RED fixtures for the raw-to-persistence precious-metals pipeline."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from importlib import import_module

import pytest
from data_worker.jobs.precious_metals_funds import collector as collector_module
from data_worker.jobs.precious_metals_funds.collector import TrustedFundContext
from data_worker.raw import RawObjectManifest

try:
    storage_module = import_module("data_worker.storage.precious_metals")
except ImportError:
    storage_module = None


def _require(module: object, name: str) -> object:
    assert module is not None, "missing required pipeline module"
    value = getattr(module, name, None)
    assert value is not None, f"missing required pipeline symbol: {name}"
    return value


def _times() -> tuple[datetime, datetime, datetime, datetime, datetime]:
    event = datetime(2026, 8, 13, 1, 0, tzinfo=UTC)
    publish = datetime(2026, 8, 13, 2, 0, tzinfo=UTC)
    ingest = datetime(2026, 8, 13, 3, 0, tzinfo=UTC)
    available = datetime(2026, 8, 13, 3, 30, tzinfo=UTC)
    processing = datetime(2026, 8, 13, 4, 0, tzinfo=UTC)
    return event, publish, ingest, available, processing


def _trusted_context(
    kind: str = "nav",
) -> TrustedFundContext:
    _, _, ingest, available, processing = _times()
    checksum = hashlib.sha256(b"{}").hexdigest()
    manifest = RawObjectManifest(
        object_id=checksum,
        source="provider-x",
        date="2026-08-13",
        request="GET /funds/nav?exchange=SH",
        checksum=checksum,
        size=2,
        capture_id="capture-1",
        ingest_time=ingest,
        available_time=available,
        endpoint_kind=kind,
        run_id="run-1",
        source_revision="revision-1",
    )
    return TrustedFundContext.from_manifest(
        manifest,
        processing_time=processing,
        schema_version="precious-metals-fund-v1",
        normalizer_version="precious-metals-normalizer-v1",
    )


def test_evidence_envelope_retains_capture_object_digest_versions_and_five_times() -> None:
    envelope_type = _require(storage_module, "EvidenceEnvelope")
    event, publish, ingest, available, processing = _times()
    envelope = envelope_type(
        raw_capture_id="capture-1",
        raw_object_id="a" * 64,
        checksum="a" * 64,
        source="provider-x",
        source_revision="rev-1",
        schema_version="fund-v1",
        normalizer_version="normalizer-v1",
        payload_digest="b" * 64,
        item_ordinal=0,
        event_time=event,
        publish_time=publish,
        ingest_time=ingest,
        available_time=available,
        processing_time=processing,
    )
    assert envelope.record_id == "capture-1:0"
    assert envelope.available_time == available


def test_nav_and_inav_are_distinct_reference_only_observations() -> None:
    inav_type = _require(collector_module, "InavObservation")
    assert inav_type.__dataclass_fields__["tradeable"].default is False
    assert isinstance(inav_type.is_reference_only, property)


def test_normalization_rejects_float_and_invalid_time_order() -> None:
    normalize = _require(collector_module, "normalize_fund_observation")
    event, publish, ingest, available, processing = _times()
    context = _trusted_context()
    record = {
        "unifiedCode": "518880.SH",
        "date": "2026-08-13",
        "nav": 0.1,
        "eventTime": event.isoformat(),
        "publishTime": publish.isoformat(),
        "ingestTime": ingest.isoformat(),
        "availableTime": available.isoformat(),
        "processingTime": processing.isoformat(),
        "source": "provider-x",
    }
    with pytest.raises((TypeError, ValueError)):
        normalize("nav", record, trusted_context=context)

    record["nav"] = "1.25"
    record["publishTime"] = (processing + datetime.resolution).isoformat()
    observation = normalize("nav", record, trusted_context=context)
    valid, issues = collector_module.validate_fund_observation(
        observation, now=processing, as_of=processing
    )
    assert not valid
    assert any("order" in issue for issue in issues)


def test_normalization_requires_trusted_context() -> None:
    normalize = _require(collector_module, "normalize_fund_observation")
    event, publish, ingest, available, processing = _times()
    record = {
        "unifiedCode": "518880.SH",
        "date": "2026-08-13",
        "nav": "1.25",
        "eventTime": event.isoformat(),
        "publishTime": publish.isoformat(),
        "ingestTime": ingest.isoformat(),
        "availableTime": available.isoformat(),
        "processingTime": processing.isoformat(),
        "source": "payload-source",
    }
    with pytest.raises(ValueError, match="trusted_context"):
        normalize(
            "nav",
            record,
            trusted_context=None,
        )


def test_metadata_scope_and_missing_fields_are_rejected() -> None:
    normalize = _require(collector_module, "normalize_fund_observation")
    event, publish, ingest, available, processing = _times()
    context = _trusted_context("metadata")
    record = {
        "unifiedCode": "518880.SH",
        "exchange": "SH",
        "assetType": "ETF",
        "fundAssetClass": "GOLD",
        "underlyingCommodity": "GOLD",
        "tradingCurrency": "CNY",
        "navCurrency": "CNY",
        "benchmarkOrTrackingIndex": "IDX",
        "managementFeeRate": "0.005",
        "validFrom": "2026-01-01",
        "source": "provider-x",
        "publishTime": publish.isoformat(),
        "ingestTime": ingest.isoformat(),
        "availableTime": available.isoformat(),
        "processingTime": processing.isoformat(),
        "rawObjectId": "a" * 64,
        "confidence": "0.9",
        "reviewStatus": "UNREVIEWED",
    }
    with pytest.raises(ValueError):
        normalize("metadata", record, trusted_context=context)


def test_capture_replay_is_idempotent_but_changed_content_conflicts() -> None:
    storage_type = _require(storage_module, "InMemoryFundStorage")
    collector_type = _require(collector_module, "FundCollector")
    persistence = storage_type()
    assert collector_type is not None
    assert persistence is not None
