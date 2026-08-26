"""Public benchmark-series contract and explicit fund binding tests."""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from ashare_contracts import BenchmarkSeriesPoint, is_canonical_benchmark_id
from market_core.funds import (
    benchmark_series_matches,
    fund_from_dict,
    validate_precious_metal_fund,
)


def _point_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": "benchmark-series-point-v1",
        "benchmarkId": "benchmark:v1:gold:gold_cny",
        "currency": "CNY",
        "priceBasis": "PRICE_RETURN",
        "referenceValue": "123.4500",
        "eventTime": "2026-08-13T09:00:00Z",
        "ingestTime": "2026-08-13T09:01:00Z",
        "availableTime": "2026-08-13T09:02:00Z",
        "processingTime": "2026-08-13T09:03:00Z",
        "source": "provider-x",
        "sourceRevision": "2026-08-13-1",
        "rawObjectId": "raw-benchmark-1",
        "payloadDigest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "referenceOnly": True,
    }
    payload.update(overrides)
    return payload


_BENCHMARK_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[4]
        / "packages"
        / "contracts"
        / "schemas"
        / "funds"
        / "benchmark-series-point.json"
    ).read_text(encoding="utf-8")
)
_BENCHMARK_PROPERTIES = _BENCHMARK_SCHEMA["properties"]


def _fund_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "unifiedCode": "518880.SH",
        "exchange": "SH",
        "assetType": "ETF",
        "fundAssetClass": "PRECIOUS_METALS",
        "underlyingCommodity": "GOLD",
        "tradingCurrency": "CNY",
        "navCurrency": "CNY",
        "benchmarkOrTrackingIndex": "Gold display label",
        "managementFeeRate": "0.005",
        "validFrom": "2020-01-01",
        "validTo": None,
        "source": "provider-x",
        "publishTime": "2026-08-13T09:00:00Z",
        "ingestTime": "2026-08-13T09:01:00Z",
        "availableTime": "2026-08-13T09:02:00Z",
        "processingTime": "2026-08-13T09:03:00Z",
        "rawObjectId": "raw-fund-1",
        "confidence": "0.95",
        "reviewStatus": "REVIEWED",
    }
    payload.update(overrides)
    return payload


def test_benchmark_series_point_is_public_and_exact() -> None:
    point = BenchmarkSeriesPoint.model_validate(_point_payload())
    assert point.benchmark_id == "benchmark:v1:gold:gold_cny"
    assert point.reference_value == Decimal("123.4500")
    assert point.reference_only is True


@pytest.mark.parametrize(
    "field",
    [
        "schemaVersion",
        "benchmarkId",
        "currency",
        "priceBasis",
        "referenceValue",
        "eventTime",
        "ingestTime",
        "availableTime",
        "processingTime",
        "source",
        "sourceRevision",
        "rawObjectId",
        "payloadDigest",
    ],
)
def test_benchmark_series_point_rejects_bytes_for_every_string_wire_field(field: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        BenchmarkSeriesPoint.model_validate(_point_payload(**{field: b"not-json-string"}))


def test_benchmark_series_schema_declares_version_and_reference_only_constants() -> None:
    assert _BENCHMARK_PROPERTIES["schemaVersion"]["const"] == "benchmark-series-point-v1"
    assert _BENCHMARK_PROPERTIES["referenceOnly"]["const"] is True


def test_benchmark_series_point_enforces_schema_version_constant() -> None:
    point = BenchmarkSeriesPoint.model_validate(
        _point_payload(schemaVersion="benchmark-series-point-v1")
    )
    assert point.schema_version == "benchmark-series-point-v1"
    for value in ["other-v1", None, True]:
        with pytest.raises((TypeError, ValueError)):
            BenchmarkSeriesPoint.model_validate(_point_payload(schemaVersion=value))


@pytest.mark.parametrize("field", ["priceBasis", "source", "sourceRevision", "rawObjectId"])
def test_benchmark_series_point_enforces_string_min_max_boundaries(field: str) -> None:
    property_schema = _BENCHMARK_PROPERTIES[field]
    min_length = int(property_schema["minLength"])
    max_length = int(property_schema["maxLength"])
    for value in ["x" * min_length, "x" * max_length]:
        BenchmarkSeriesPoint.model_validate(_point_payload(**{field: value}))
    with pytest.raises((TypeError, ValueError)):
        BenchmarkSeriesPoint.model_validate(_point_payload(**{field: "x" * (max_length + 1)}))
    with pytest.raises((TypeError, ValueError)):
        BenchmarkSeriesPoint.model_validate(_point_payload(**{field: ""}))


def test_benchmark_series_point_enforces_benchmark_id_and_reference_value_max_boundaries() -> None:
    benchmark_id_at_limit = f"benchmark:v1:{'n' * 32}:{'k' * 128}"
    benchmark_id_over_limit = f"benchmark:v1:{'n' * 32}:{'k' * 129}"
    assert len(benchmark_id_at_limit) == _BENCHMARK_PROPERTIES["benchmarkId"]["maxLength"]
    assert len(benchmark_id_over_limit) == len(benchmark_id_at_limit) + 1
    BenchmarkSeriesPoint.model_validate(_point_payload(benchmarkId=benchmark_id_at_limit))
    with pytest.raises((TypeError, ValueError)):
        BenchmarkSeriesPoint.model_validate(_point_payload(benchmarkId=benchmark_id_over_limit))

    max_length = int(_BENCHMARK_PROPERTIES["referenceValue"]["maxLength"])
    reference_value_at_limit = f"1.{'0' * (max_length - 2)}"
    reference_value_over_limit = f"1.{'0' * (max_length - 1)}"
    assert len(reference_value_at_limit) == max_length
    BenchmarkSeriesPoint.model_validate(_point_payload(referenceValue=reference_value_at_limit))
    with pytest.raises((TypeError, ValueError)):
        BenchmarkSeriesPoint.model_validate(
            _point_payload(referenceValue=reference_value_over_limit)
        )


def test_benchmark_series_point_enforces_currency_and_payload_digest_patterns() -> None:
    BenchmarkSeriesPoint.model_validate(_point_payload(currency="USD"))
    for currency in ["US", "USDA", "usd"]:
        with pytest.raises((TypeError, ValueError)):
            BenchmarkSeriesPoint.model_validate(_point_payload(currency=currency))
    for payload_digest in [
        f"sha256:{'a' * 63}",
        f"sha256:{'a' * 65}",
        f"sha256:{'A' * 64}",
    ]:
        with pytest.raises((TypeError, ValueError)):
            BenchmarkSeriesPoint.model_validate(_point_payload(payloadDigest=payload_digest))


def test_canonical_benchmark_id_predicate_is_public_api() -> None:
    assert is_canonical_benchmark_id("benchmark:v1:gold:gold_cny") is True
    assert is_canonical_benchmark_id("Gold display label") is False


@pytest.mark.parametrize(
    "value",
    [
        0,
        -1,
        0.1,
        True,
        Decimal("123.45"),
        "0",
        "0.0",
        "-1",
        "+1",
        " 1",
        "1 ",
        "1e3",
        "01.0",
        "NaN",
        "Infinity",
    ],
)
def test_benchmark_series_point_rejects_non_canonical_reference_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        BenchmarkSeriesPoint.model_validate(_point_payload(referenceValue=value))


@pytest.mark.parametrize("value", ["0.1", "0.10", "1", "1.2300"])
def test_benchmark_series_point_accepts_canonical_reference_values(value: str) -> None:
    point = BenchmarkSeriesPoint.model_validate(_point_payload(referenceValue=value))
    assert point.reference_value == Decimal(value)


@pytest.mark.parametrize(
    "value",
    [
        "benchmark:gold-cny",
        "Gold display label",
        " benchmark:v1:gold:key",
        "benchmark:v1:gold:key ",
        "benchmark:v1:Gold:key",
        "benchmark:v1:金:key",
        "benchmark:v1:-gold:key",
        "benchmark:v1:gold:-key",
    ],
)
def test_benchmark_series_point_rejects_non_canonical_benchmark_id(value: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        BenchmarkSeriesPoint.model_validate(_point_payload(benchmarkId=value))


@pytest.mark.parametrize("value", [1, 0, "true", False])
def test_benchmark_series_point_rejects_non_literal_reference_only(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        BenchmarkSeriesPoint.model_validate(_point_payload(referenceOnly=value))


def test_benchmark_series_point_rejects_missing_provenance() -> None:
    for field, value in (
        ("sourceRevision", ""),
        ("rawObjectId", ""),
        ("payloadDigest", "not-a-digest"),
    ):
        with pytest.raises((TypeError, ValueError)):
            BenchmarkSeriesPoint.model_validate(_point_payload(**{field: value}))


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-13 09:00:00Z",
        "2026-08-13T09:00:00.1234567Z",
        "2026-08-13T09:00:00",
        "2026-02-29T09:00:00Z",
        "2026-08-13T24:00:00Z",
        "2026-08-13T09:00:00+24:00",
    ],
)
def test_benchmark_series_point_rejects_non_strict_rfc3339(value: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        BenchmarkSeriesPoint.model_validate(_point_payload(eventTime=value))


def test_benchmark_series_point_rejects_year_zero_and_accepts_year_one() -> None:
    with pytest.raises((TypeError, ValueError)):
        BenchmarkSeriesPoint.model_validate(_point_payload(eventTime="0000-01-01T00:00:00Z"))
    BenchmarkSeriesPoint.model_validate(_point_payload(eventTime="0001-01-01T00:00:00Z"))


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-13T09:00:00Z",
        "2026-08-13T09:00:00.1+08:00",
        "2026-08-13T03:00:00.123456-05:30",
    ],
)
def test_benchmark_series_point_accepts_strict_rfc3339(value: str) -> None:
    BenchmarkSeriesPoint.model_validate(_point_payload(eventTime=value))


@pytest.mark.parametrize(
    "overrides",
    [
        {"eventTime": "2026-08-13T09:01:00Z", "ingestTime": "2026-08-13T09:00:00Z"},
        {"ingestTime": "2026-08-13T09:03:00Z", "availableTime": "2026-08-13T09:02:00Z"},
        {"availableTime": "2026-08-13T09:04:00Z", "processingTime": "2026-08-13T09:03:00Z"},
    ],
)
def test_benchmark_series_point_rejects_timestamp_order(overrides: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="event/ingest/available/processing order invalid"):
        BenchmarkSeriesPoint.model_validate(_point_payload(**overrides))


def test_explicit_binding_matches_canonical_id_and_legacy_missing_binding_fails_closed() -> None:
    point = BenchmarkSeriesPoint.model_validate(_point_payload())
    legacy = fund_from_dict(_fund_payload())
    assert validate_precious_metal_fund(legacy).valid is True
    assert legacy.benchmark_series_id is None
    assert benchmark_series_matches(legacy, point) is False

    null_binding = fund_from_dict(_fund_payload(benchmarkSeriesId=None))
    assert benchmark_series_matches(null_binding, point) is False

    bound = fund_from_dict(_fund_payload(benchmarkSeriesId="benchmark:v1:gold:gold_cny"))
    assert validate_precious_metal_fund(bound).valid is True
    assert benchmark_series_matches(bound, point) is True

    other = BenchmarkSeriesPoint.model_validate(
        _point_payload(benchmarkId="benchmark:v1:gold:other")
    )
    assert benchmark_series_matches(bound, other) is False

    display_text_only = fund_from_dict(
        _fund_payload(benchmarkOrTrackingIndex="benchmark:v1:gold:gold_cny"),
    )
    assert benchmark_series_matches(display_text_only, point) is False


@pytest.mark.parametrize(
    "value",
    [
        True,
        1,
        {},
        [],
    ],
)
def test_fund_from_dict_rejects_non_string_optional_benchmark_binding(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        fund_from_dict(_fund_payload(benchmarkSeriesId=value))


@pytest.mark.parametrize(
    "value",
    [
        "benchmark:gold-cny",
        "Gold display label",
        " benchmark:v1:gold:key",
        "benchmark:v1:gold:key ",
        "benchmark:v1:Gold:key",
        "benchmark:v1:金:key",
    ],
)
def test_fund_validation_rejects_non_canonical_optional_benchmark_binding(value: str) -> None:
    fund = fund_from_dict(_fund_payload(benchmarkSeriesId=value))
    point = BenchmarkSeriesPoint.model_validate(_point_payload())
    assert validate_precious_metal_fund(fund).valid is False
    assert benchmark_series_matches(fund, point) is False


def test_old_fund_payload_does_not_require_binding() -> None:
    old_payload = deepcopy(_fund_payload())
    assert "benchmarkSeriesId" not in old_payload
    assert validate_precious_metal_fund(fund_from_dict(old_payload)).valid is True


def test_type_surface_accepts_only_contract_objects() -> None:
    payload: dict[str, Any] = _point_payload()
    assert payload["referenceOnly"] is True
