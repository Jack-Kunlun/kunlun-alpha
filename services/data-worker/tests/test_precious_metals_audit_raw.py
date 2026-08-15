"""Qualified RED coverage for the P1-R07 raw-first audit contract."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

import pytest
from ashare_contracts.providers import Capability
from data_worker.jobs.precious_metals_funds import FundCollector, NavObservation
from data_worker.jobs.precious_metals_funds import collector as collector_module
from data_worker.raw import LocalFileStorage, RawObjectManifest
from data_worker.raw import manifest as manifest_module
from data_worker.storage import InMemoryFundStorage
from market_core import providers as provider_module
from market_core.providers import RawFundProviderResponse
from market_core.providers.base import Provider

_EVENT = datetime(2026, 8, 13, 1, tzinfo=UTC)
_PUBLISH = _EVENT + timedelta(hours=1)
_INGEST = _EVENT + timedelta(hours=2)
_AVAILABLE = _EVENT + timedelta(hours=3)
_PROCESSING = _EVENT + timedelta(hours=4)


def _nav_body(value: str = "1.250000000001") -> bytes:
    return json.dumps(
        {
            "items": [
                {
                    "unifiedCode": "518880.SH",
                    "date": "2026-08-13",
                    "nav": value,
                    "eventTime": _EVENT.isoformat(),
                    "publishTime": _PUBLISH.isoformat(),
                    "ingestTime": _INGEST.isoformat(),
                    "availableTime": _AVAILABLE.isoformat(),
                    "processingTime": _PROCESSING.isoformat(),
                    "source": "provider-x",
                }
            ],
            "nextCursor": None,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _nav_body_with_untrusted_provenance() -> bytes:
    payload = cast(dict[str, object], json.loads(_nav_body()))
    items = cast(list[object], payload["items"])
    item = cast(dict[str, object], items[0])
    item.update(
        {
            "source": "payload-source",
            "ingestTime": _PUBLISH.isoformat(),
            "availableTime": _PUBLISH.isoformat(),
            "processingTime": _PUBLISH.isoformat(),
        }
    )
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _raw_response(body: bytes, *, run_id: str = "run-1") -> RawFundProviderResponse:
    response_type = getattr(provider_module, "RawFundProviderResponse", None)
    assert response_type is not None, "missing raw transport response contract"
    return RawFundProviderResponse(
        body=body,
        source="provider-x",
        request="GET /funds/nav?exchange=SH",
        content_type="application/json",
        ingest_time=_INGEST,
        available_time=_AVAILABLE,
        endpoint_kind="nav",
        run_id=run_id,
        source_revision="revision-1",
    )


class RawProvider(Provider):
    def __init__(self, body: bytes) -> None:
        self.body = body

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_FUND_NAV})

    def fetch_fund_nav(self, exchange: str, cursor: str | None = None) -> RawFundProviderResponse:
        return _raw_response(self.body)


def test_provider_contract_is_bytes_transport_without_page_items() -> None:
    response_type = getattr(provider_module, "RawFundProviderResponse", None)
    assert response_type is not None
    response = _raw_response(_nav_body())
    assert isinstance(response.body, bytes)
    assert response.content_type == "application/json"
    assert not hasattr(response, "items")
    assert not hasattr(response, "next_cursor")


@pytest.mark.parametrize(
    "content_type",
    [
        "Bearer secret",
        "application/json; bearer=secret",
        "application/json; token=secret",
        "application/json; credential=secret",
        "application/json; dsn=postgresql://user:secret@db/funds",
    ],
)
def test_raw_provider_response_rejects_secret_derived_content_type(
    content_type: str,
) -> None:
    with pytest.raises(ValueError, match="content_type"):
        RawFundProviderResponse(
            body=b"{}",
            source="provider-x",
            request="GET /funds/nav?exchange=SH",
            content_type=content_type,
        )


def test_raw_provider_response_normalizes_safe_mime_content_type() -> None:
    response = RawFundProviderResponse(
        body=b"{}",
        source="provider-x",
        request="GET /funds/nav?exchange=SH",
        content_type="Application/JSON; charset=UTF-8",
    )
    assert response.content_type == "application/json; charset=utf-8"


@pytest.mark.parametrize(
    "content_type",
    [
        "Basic secret",
        "application/json; cookie=secret",
        "application/json; credential=secret",
        "application/json; token=secret",
        "application/json; dsn=postgresql://user:secret@db/funds",
    ],
)
def test_manifest_rejects_secret_derived_content_type_before_storage(
    tmp_path: Path,
    content_type: str,
) -> None:
    checksum = hashlib.sha256(b"{}").hexdigest()
    with pytest.raises(ValueError, match="content_type"):
        RawObjectManifest(
            object_id=checksum,
            source="provider-x",
            date="2026-08-13",
            request="GET /funds/nav?exchange=SH",
            checksum=checksum,
            size=2,
            content_type=content_type,
            capture_id="capture-mime",
            ingest_time=_INGEST,
            available_time=_AVAILABLE,
            endpoint_kind="nav",
            run_id="run-1",
            source_revision="revision-1",
        )
    storage = LocalFileStorage(tmp_path)
    with pytest.raises(ValueError, match="content_type"):
        storage.put(
            "provider-x",
            "2026-08-13",
            "GET /funds/nav?exchange=SH",
            b"{}",
            content_type=content_type,
            capture_id="capture-mime",
            endpoint_kind="nav",
            run_id="run-1",
            source_revision="revision-1",
            attempt_id="attempt-mime",
            page_ordinal=0,
        )
    assert not (tmp_path / "objects").exists()


def test_collector_decodes_bytes_read_back_from_raw_manifest(tmp_path: Path) -> None:
    persistence = InMemoryFundStorage()
    collector = FundCollector(
        RawProvider(_nav_body()),
        LocalFileStorage(tmp_path),
        persistence,
        now=_PROCESSING,
    )

    result = collector.collect("nav", "SH", collection_date="2026-08-13")

    assert len(result.accepted) == 1
    observation = cast(NavObservation, result.accepted[0])
    stored = cast(NavObservation, persistence.observations("nav")[0])
    assert stored.value.nav == observation.value.nav


def test_collector_uses_verified_manifest_and_processing_clock_for_provenance(
    tmp_path: Path,
) -> None:
    persistence = InMemoryFundStorage()
    storage = LocalFileStorage(tmp_path)
    collector = FundCollector(
        RawProvider(_nav_body_with_untrusted_provenance()),
        storage,
        persistence,
        now=_PROCESSING,
    )

    result = collector.collect("nav", "SH", collection_date="2026-08-13")

    assert len(result.accepted) == 1
    observation = cast(NavObservation, result.accepted[0])
    manifest = storage.list("provider-x", "2026-08-13")[0]
    assert manifest.available_time is not None
    evidence = observation.evidence
    assert evidence.source == manifest.source
    assert evidence.raw_capture_id == manifest.capture_id
    assert evidence.raw_object_id == manifest.object_id
    assert evidence.checksum == manifest.checksum
    assert evidence.source_revision == manifest.source_revision
    assert evidence.ingest_time == manifest.ingest_time
    assert evidence.available_time == manifest.available_time
    assert evidence.processing_time == _PROCESSING
    assert observation.value.source == manifest.source
    assert observation.value.raw_object_id == manifest.object_id
    for provenance_field in (
        "source",
        "rawObjectId",
        "eventTime",
        "publishTime",
        "ingestTime",
        "availableTime",
        "processingTime",
    ):
        assert provenance_field not in observation.payload


def test_collector_rejects_payload_raw_object_id_mismatch(tmp_path: Path) -> None:
    payload = cast(dict[str, object], json.loads(_nav_body()))
    items = cast(list[object], payload["items"])
    item = cast(dict[str, object], items[0])
    item["rawObjectId"] = "forged-object-id"
    persistence = InMemoryFundStorage()
    collector = FundCollector(
        RawProvider(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()),
        LocalFileStorage(tmp_path),
        persistence,
        now=_PROCESSING,
    )

    result = collector.collect("nav", "SH", collection_date="2026-08-13")

    assert result.accepted == []
    assert len(result.rejected) == 1


def test_raw_storage_rejects_unknown_endpoint_kind_before_capture(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)

    with pytest.raises(ValueError, match="endpoint_kind"):
        storage.put(
            "provider-x",
            "2026-08-13",
            "GET /funds/nav?exchange=SH",
            _nav_body(),
            content_type="application/json",
            endpoint_kind="unknown",
            run_id="run-1",
            source_revision="revision-1",
        )

    assert not (tmp_path / "objects").exists()
    assert not (tmp_path / "index").exists()


def test_equal_raw_bytes_from_two_requests_receive_two_captures_one_logical_observation(
    tmp_path: Path,
) -> None:
    body = _nav_body()
    persistence = InMemoryFundStorage()
    collector = FundCollector(
        RawProvider(body),
        LocalFileStorage(tmp_path),
        persistence,
        now=_PROCESSING,
    )

    collector.collect("nav", "SH", collection_date="2026-08-13")
    collector.collect("nav", "SH", collection_date="2026-08-13")

    assert len(persistence.observations("nav")) == 1
    assert len(persistence.evidence()) == 2
    assert persistence.evidence()[0].raw_capture_id != persistence.evidence()[1].raw_capture_id


def test_provenance_time_changes_do_not_create_duplicate_logical_observations(
    tmp_path: Path,
) -> None:
    class TimeVaryingProvider(RawProvider):
        def __init__(self, body: bytes) -> None:
            super().__init__(body)
            self.calls = 0

        def fetch_fund_nav(
            self, exchange: str, cursor: str | None = None
        ) -> RawFundProviderResponse:
            self.calls += 1
            return RawFundProviderResponse(
                body=self.body,
                source="provider-x",
                request="GET /funds/nav?exchange=SH",
                content_type="application/json",
                ingest_time=_INGEST + timedelta(minutes=self.calls),
                available_time=_AVAILABLE + timedelta(minutes=self.calls),
                endpoint_kind="nav",
                run_id="run-1",
                source_revision="revision-1",
            )

    persistence = InMemoryFundStorage()
    collector = FundCollector(
        TimeVaryingProvider(_nav_body()),
        LocalFileStorage(tmp_path),
        persistence,
        now=_PROCESSING + timedelta(hours=1),
    )

    collector.collect("nav", "SH", collection_date="2026-08-13")
    collector.collect("nav", "SH", collection_date="2026-08-13")

    assert len(persistence.observations("nav")) == 1
    assert len(persistence.evidence()) == 2


def test_manifest_route_fields_are_optional_and_bound_in_new_canonical_digest() -> None:
    manifest_type = getattr(manifest_module, "RawObjectManifest", None)
    assert manifest_type is not None
    parameters = inspect.signature(manifest_type).parameters
    for field_name in ("endpoint_kind", "run_id", "source_revision"):
        assert field_name in parameters, f"manifest missing route field: {field_name}"

    payload = b"{}"
    checksum = hashlib.sha256(payload).hexdigest()
    manifest = manifest_type(
        object_id=checksum,
        source="provider-x",
        date="2026-08-13",
        request="GET /funds/nav?exchange=SH",
        checksum=checksum,
        size=len(payload),
        capture_id="capture-route",
        ingest_time=_INGEST,
        available_time=_AVAILABLE,
        endpoint_kind="nav",
        run_id="run-1",
        source_revision="revision-1",
    )
    encoded = manifest.to_dict()
    assert encoded["endpoint_kind"] == "nav"
    assert encoded["run_id"] == "run-1"
    assert manifest_type.from_dict(encoded).content_digest() == manifest.content_digest()


def test_manifest_route_replay_rejects_legacy_capture_without_route_fields() -> None:
    manifest_type = getattr(manifest_module, "RawObjectManifest", None)
    assert manifest_type is not None
    assert hasattr(manifest_type, "route_identity")
    assert (
        manifest_type.route_identity(
            {"source": "provider-x", "date": "2026-08-13", "capture_id": "legacy"}
        )
        is None
    )


def test_manifest_route_rejects_unknown_endpoint_kind() -> None:
    manifest_type = getattr(manifest_module, "RawObjectManifest", None)
    assert manifest_type is not None
    with pytest.raises(ValueError, match="endpoint_kind"):
        manifest_type.route_identity(
            {
                "endpoint_kind": "unknown",
                "run_id": "run-1",
                "source_revision": "revision-1",
            }
        )


def test_replay_rejects_unknown_endpoint_kind_before_route_selection(tmp_path: Path) -> None:
    collector = FundCollector(
        RawProvider(_nav_body()),
        LocalFileStorage(tmp_path),
        now=_PROCESSING,
    )

    with pytest.raises(ValueError, match="endpoint_kind|kind"):
        collector.replay_captures(
            cast(Literal["metadata", "nav", "inav", "benchmark", "fees"], "unknown"),
            "provider-x",
            "2026-08-13",
            run_id="run-1",
            source_revision="revision-1",
        )


@pytest.mark.parametrize(
    ("kind", "capability", "method_name"),
    [
        ("metadata", Capability.FETCH_FUND_METADATA, "fetch_fund_metadata"),
        ("nav", Capability.FETCH_FUND_NAV, "fetch_fund_nav"),
        ("inav", Capability.FETCH_FUND_INAV, "fetch_fund_inav"),
        ("benchmark", Capability.FETCH_FUND_BENCHMARK, "fetch_fund_benchmark"),
        ("fees", Capability.FETCH_FUND_FEES, "fetch_fund_fees"),
    ],
)
def test_replay_provider_dispatches_all_fund_endpoint_kinds(
    kind: str, capability: Capability, method_name: str
) -> None:
    replay_type = getattr(collector_module, "_ReplayProvider", None)
    assert replay_type is not None
    page = replace(_raw_response(b'{"items": [], "nextCursor": null}'), endpoint_kind=kind)
    provider = replay_type(kind, [page])

    assert provider.supports(capability)
    assert getattr(provider, method_name)("SH").body == page.body
