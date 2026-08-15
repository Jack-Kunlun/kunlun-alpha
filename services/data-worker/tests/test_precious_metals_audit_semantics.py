"""Qualified RED coverage for independent benchmark/fee semantics."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

import pytest
from ashare_contracts.providers import Capability
from data_worker.jobs.precious_metals_funds import FundCollector
from data_worker.jobs.precious_metals_funds.collector import (
    BenchmarkObservation,
    FeeObservation,
)
from data_worker.raw import LocalFileStorage
from data_worker.storage import EvidenceEnvelope, InMemoryFundStorage, RejectedObservation
from market_core.providers import RawFundProviderResponse
from market_core.providers.base import Provider

_EVENT = datetime(2026, 8, 13, 1, tzinfo=UTC)
_PUBLISH = _EVENT + timedelta(hours=1)
_INGEST = _EVENT + timedelta(hours=2)
_AVAILABLE = _EVENT + timedelta(hours=3)
_PROCESSING = _EVENT + timedelta(hours=4)


def _response(
    kind: str,
    item: dict[str, object],
    *,
    next_cursor: str | None = None,
) -> RawFundProviderResponse:
    body = json.dumps(
        {"items": [item], "nextCursor": next_cursor},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return RawFundProviderResponse(
        body=body,
        source="provider-x",
        request=f"GET /funds/{kind}?exchange=SH",
        content_type="application/json",
        ingest_time=_INGEST,
        available_time=_AVAILABLE,
        endpoint_kind=kind,
        run_id="run-1",
        source_revision="revision-1",
    )


def _times(item: dict[str, object]) -> dict[str, object]:
    item.update(
        {
            "unifiedCode": "518880.SH",
            "date": "2026-08-13",
            "eventTime": _EVENT.isoformat(),
            "publishTime": _PUBLISH.isoformat(),
            "ingestTime": _INGEST.isoformat(),
            "availableTime": _AVAILABLE.isoformat(),
            "processingTime": _PROCESSING.isoformat(),
            "source": "provider-x",
        }
    )
    return item


class EndpointProvider(Provider):
    def __init__(self, responses: dict[str, RawFundProviderResponse]) -> None:
        self._responses = responses

    def capabilities(self) -> frozenset[Capability]:
        return frozenset(
            {
                {
                    "benchmark": Capability.FETCH_FUND_BENCHMARK,
                    "fees": Capability.FETCH_FUND_FEES,
                }[kind]
                for kind in self._responses
            }
        )

    def fetch_fund_benchmark(
        self, exchange: str, cursor: str | None = None
    ) -> RawFundProviderResponse:
        return self._responses["benchmark"]

    def fetch_fund_fees(self, exchange: str, cursor: str | None = None) -> RawFundProviderResponse:
        return self._responses["fees"]


class SequencedEndpointProvider(Provider):
    def __init__(
        self,
        responses: dict[str, tuple[RawFundProviderResponse, RawFundProviderResponse]],
    ) -> None:
        self._responses = responses

    def capabilities(self) -> frozenset[Capability]:
        capabilities = {
            "benchmark": Capability.FETCH_FUND_BENCHMARK,
            "fees": Capability.FETCH_FUND_FEES,
        }
        return frozenset(capabilities[kind] for kind in self._responses)

    def _page(self, kind: str, cursor: str | None) -> RawFundProviderResponse:
        pages = self._responses[kind]
        return pages[0] if cursor is None else pages[1]

    def fetch_fund_benchmark(
        self, exchange: str, cursor: str | None = None
    ) -> RawFundProviderResponse:
        return self._page("benchmark", cursor)

    def fetch_fund_fees(self, exchange: str, cursor: str | None = None) -> RawFundProviderResponse:
        return self._page("fees", cursor)


class RejectionProvider(Provider):
    """Provider fixture that drives the collector's real rejection path."""

    def __init__(self, items: list[object]) -> None:
        self._response = RawFundProviderResponse(
            body=json.dumps(
                {"items": items, "nextCursor": None},
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
            source="provider-x",
            request="GET /funds/metadata?exchange=SH",
            content_type="application/json",
            ingest_time=_INGEST,
            available_time=_AVAILABLE,
            endpoint_kind="metadata",
            run_id="run-rejection",
            source_revision="revision-rejection",
        )

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_FUND_METADATA})

    def fetch_fund_metadata(
        self, exchange: str, cursor: str | None = None
    ) -> RawFundProviderResponse:
        return self._response


def _rejection_strings(rejected: list[RejectedObservation]) -> str:
    return json.dumps(
        [
            {
                "payload": item.payload,
                "reason": item.reason,
            }
            for item in rejected
        ],
        sort_keys=True,
        default=str,
    )


def test_benchmark_and_fee_are_independent_partial_observations(tmp_path: Path) -> None:
    benchmark = _times({"benchmarkOrTrackingIndex": "IDX-GOLD"})
    fee = _times({"managementFeeRate": "0.005000000001"})
    persistence = InMemoryFundStorage()
    provider = EndpointProvider(
        {
            "benchmark": _response("benchmark", benchmark),
            "fees": _response("fees", fee),
        }
    )
    collector = FundCollector(provider, LocalFileStorage(tmp_path), persistence, now=_PROCESSING)

    benchmark_result = collector.collect("benchmark", "SH", collection_date="2026-08-13")
    fee_result = collector.collect("fees", "SH", collection_date="2026-08-13")

    assert benchmark_result.accepted
    assert fee_result.accepted
    benchmark_observation = cast(BenchmarkObservation, benchmark_result.accepted[0])
    fee_observation = cast(FeeObservation, fee_result.accepted[0])
    assert benchmark_observation.kind == "benchmark"
    assert fee_observation.kind == "fees"
    benchmark_persisted = cast(BenchmarkObservation, persistence.observations("benchmark")[0])
    fee_persisted = cast(FeeObservation, persistence.observations("fees")[0])
    assert benchmark_persisted.payload["benchmarkOrTrackingIndex"] == "IDX-GOLD"
    assert fee_persisted.payload["managementFeeRate"] == "0.005000000001"


@pytest.mark.parametrize(
    ("kind", "first", "second"),
    [
        (
            "benchmark",
            {"benchmarkOrTrackingIndex": "IDX-GOLD"},
            {"benchmarkOrTrackingIndex": "IDX-SILVER"},
        ),
        ("fees", {"managementFeeRate": "0.005"}, {"managementFeeRate": "0.006"}),
    ],
)
def test_benchmark_and_fee_value_changes_emit_source_conflict(
    tmp_path: Path,
    kind: str,
    first: dict[str, object],
    second: dict[str, object],
) -> None:
    route_kind = cast(Literal["benchmark", "fees"], kind)
    first_response = _response(route_kind, _times(first), next_cursor="page-2")
    second_response = _response(route_kind, _times(second))
    persistence = InMemoryFundStorage()
    provider = SequencedEndpointProvider({route_kind: (first_response, second_response)})
    collector = FundCollector(provider, LocalFileStorage(tmp_path), persistence, now=_PROCESSING)

    result = collector.collect(route_kind, "SH", collection_date="2026-08-13")

    assert len(result.accepted) == 2
    conflicts = [event for event in persistence.quality_events() if event.kind == "SOURCE_CONFLICT"]
    assert len(conflicts) == 1
    assert len(conflicts[0].evidence_ids) == 2


def test_collector_rejection_diagnostics_never_persist_provider_values(
    tmp_path: Path,
) -> None:
    bearer = "task2-nested-bearer-value"
    basic = "task2-nested-basic-value"
    dsn_password = "task2-dsn-userinfo-password"
    cookie = "task2-cookie-value"
    api_key = "task2-api-key-value"
    access_token = "task2-access-token-value"
    dsn = f"postgresql://collector:{dsn_password}@db.example.test:5432/funds"
    non_mapping = f"Bearer {bearer}; Basic {basic}; {dsn}; Cookie {cookie}"
    invalid_mapping = {
        "details": {
            "Authorization": f"Bearer {bearer}",
            "proxy": f"Basic {basic}",
            "dsn": dsn,
            "CookieHeader": cookie,
            "API_KEY": api_key,
            "access-token": access_token,
        },
        "validFrom": f"invalid-date-{dsn_password}",
    }
    persistence = InMemoryFundStorage()
    collector = FundCollector(
        RejectionProvider([non_mapping, invalid_mapping]),
        LocalFileStorage(tmp_path),
        persistence,
        now=_PROCESSING,
    )

    result = collector.collect("metadata", "SH", collection_date="2026-08-13")

    assert len(result.rejected) == 2
    persisted = persistence.rejections()
    assert len(persisted) == 2
    serialized = _rejection_strings(result.rejected) + _rejection_strings(persisted)
    for secret in (bearer, basic, dsn_password, dsn, cookie, api_key, access_token):
        assert secret not in serialized
    assert {item.reason for item in persisted} <= {
        "item_not_mapping",
        "normalization_error",
    }
    for item in persisted:
        assert set(item.payload) == {"item_digest", "field_names"}
        digest = item.payload["item_digest"]
        assert isinstance(digest, str) and len(digest) == 64
        fields_value = item.payload["field_names"]
        assert isinstance(fields_value, list)
        fields = cast(list[object], fields_value)
        assert len(fields) <= 32
        for field in fields:
            assert isinstance(field, str)
            assert len(field) <= 64
            assert field.isascii()
            assert all(character.isalnum() or character in "_.-" for character in field)


def test_collector_rejection_ignores_forged_canonical_digest(tmp_path: Path) -> None:
    forged_digest = "f" * 64
    item = {"item_digest": forged_digest, "field_names": ["validFrom"]}
    persistence = InMemoryFundStorage()
    collector = FundCollector(
        RejectionProvider([item]),
        LocalFileStorage(tmp_path),
        persistence,
        now=_PROCESSING,
    )

    result = collector.collect("metadata", "SH", collection_date="2026-08-13")

    assert len(result.rejected) == 1
    rejection = result.rejected[0]
    expected_digest = rejection.evidence.payload_digest
    assert expected_digest != forged_digest
    assert rejection.payload["item_digest"] == expected_digest
    assert persistence.rejections()[0].payload["item_digest"] == expected_digest


def test_inmemory_rejection_boundary_drops_untrusted_field_names() -> None:
    evidence = EvidenceEnvelope(
        raw_capture_id="capture-field-boundary",
        raw_object_id="a" * 64,
        checksum="a" * 64,
        source="provider-x",
        source_revision=None,
        schema_version="schema-v1",
        normalizer_version="normalizer-v1",
        payload_digest="b" * 64,
        item_ordinal=0,
        ingest_time=_INGEST,
        available_time=_AVAILABLE,
        processing_time=_PROCESSING,
    )
    rejected = RejectedObservation(
        record_id=evidence.record_id,
        kind="metadata",
        payload={
            "item_digest": "f" * 64,
            "field_names": ["validFrom", "T" * 64],
        },
        reason="normalization_error",
        evidence=evidence,
    )
    persistence = InMemoryFundStorage()

    persistence.commit_page(
        accepted=(),
        rejected=(rejected,),
        quality_events=(),
        checkpoint={},
    )

    stored = persistence.rejections()[0]
    assert stored.payload == {"item_digest": evidence.payload_digest, "field_names": []}


def test_evidence_rejects_non_hex_payload_digest() -> None:
    with pytest.raises(ValueError, match="payload_digest"):
        EvidenceEnvelope(
            raw_capture_id="capture-invalid-digest",
            raw_object_id="a" * 64,
            checksum="a" * 64,
            source="provider-x",
            source_revision=None,
            schema_version="schema-v1",
            normalizer_version="normalizer-v1",
            payload_digest="Bearer test-value",
            item_ordinal=0,
            ingest_time=_INGEST,
            available_time=_AVAILABLE,
            processing_time=_PROCESSING,
        )


def test_inmemory_rejection_invalid_evidence_digest_fails_closed() -> None:
    evidence = EvidenceEnvelope(
        raw_capture_id="capture-invalid-inmemory",
        raw_object_id="a" * 64,
        checksum="a" * 64,
        source="provider-x",
        source_revision=None,
        schema_version="schema-v1",
        normalizer_version="normalizer-v1",
        payload_digest="b" * 64,
        item_ordinal=0,
        ingest_time=_INGEST,
        available_time=_AVAILABLE,
        processing_time=_PROCESSING,
    )
    object.__setattr__(evidence, "payload_digest", "Bearer test-value")
    rejected = RejectedObservation(
        record_id=evidence.record_id,
        kind="metadata",
        payload={"item_digest": "f" * 64, "field_names": []},
        reason="normalization_error",
        evidence=evidence,
    )
    persistence = InMemoryFundStorage()

    with pytest.raises(ValueError, match="payload_digest"):
        persistence.commit_page(
            accepted=(),
            rejected=(rejected,),
            quality_events=(),
            checkpoint={},
        )
    assert persistence.rejections() == []
