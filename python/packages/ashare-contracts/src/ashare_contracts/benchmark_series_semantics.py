"""Semantic validation shared by the generated benchmark-series DTO."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Final

_TIME_FIELDS: Final[tuple[str, ...]] = (
    "eventTime",
    "ingestTime",
    "availableTime",
    "processingTime",
)
_CANONICAL_BENCHMARK_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^benchmark:v1:[a-z0-9][a-z0-9._-]{0,31}:[a-z0-9][a-z0-9._-]{0,127}$"
)
_BENCHMARK_ID_MAX_LENGTH: Final = 174
_CURRENCY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Z]{3}$")
_PRICE_BASIS_MAX_LENGTH: Final = 64
_REFERENCE_VALUE_MAX_LENGTH: Final = 64
_PROVENANCE_STRING_MAX_LENGTH: Final = 256
_CANONICAL_DECIMAL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:0\.[0-9]*[1-9][0-9]*|[1-9][0-9]*(?:\.[0-9]+)?)$"
)
_PAYLOAD_DIGEST_PATTERN: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCHEMA_VERSION: Final = "benchmark-series-point-v1"
_STRICT_RFC3339_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:"
    r"[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?"
    r"(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


def is_canonical_benchmark_id(value: object) -> bool:
    """Return whether a value is an exact lowercase ASCII benchmark identity."""
    return (
        isinstance(value, str)
        and len(value) <= _BENCHMARK_ID_MAX_LENGTH
        and _CANONICAL_BENCHMARK_ID_PATTERN.fullmatch(value) is not None
    )


def validate_benchmark_series_point(payload: dict[str, object]) -> None:
    """Validate canonical identity, decimal wire form and point-in-time ordering."""
    if payload.get("schemaVersion") != _SCHEMA_VERSION:
        raise ValueError("schemaVersion must be benchmark-series-point-v1")
    if not is_canonical_benchmark_id(payload.get("benchmarkId")):
        raise ValueError("benchmarkId must use canonical benchmark:v1 identity")
    currency = payload.get("currency")
    if not isinstance(currency, str) or _CURRENCY_PATTERN.fullmatch(currency) is None:
        raise ValueError("currency must be an ISO 4217 currency code")

    price_basis = payload.get("priceBasis")
    if not _is_non_empty_bounded_string(price_basis, _PRICE_BASIS_MAX_LENGTH):
        raise ValueError("priceBasis must be non-empty and no longer than 64 characters")

    for field in ("source", "sourceRevision", "rawObjectId"):
        value = payload.get(field)
        if not _is_non_empty_bounded_string(value, _PROVENANCE_STRING_MAX_LENGTH):
            raise ValueError(f"{field} must be non-empty and no longer than 256 characters")

    reference_value = payload.get("referenceValue")
    if (
        not isinstance(reference_value, str)
        or len(reference_value) > _REFERENCE_VALUE_MAX_LENGTH
        or _CANONICAL_DECIMAL_PATTERN.fullmatch(reference_value) is None
    ):
        raise ValueError("referenceValue must be a canonical positive fixed-point decimal string")

    if payload.get("referenceOnly") is not True:
        raise ValueError("referenceOnly must be true")
    payload_digest = payload.get("payloadDigest")
    if not isinstance(payload_digest, str) or (
        _PAYLOAD_DIGEST_PATTERN.fullmatch(payload_digest) is None
    ):
        raise ValueError("payloadDigest must be a sha256 digest")

    timestamps = tuple(_parse_aware_datetime(payload[field], field) for field in _TIME_FIELDS)
    if any(left > right for left, right in zip(timestamps, timestamps[1:], strict=False)):
        raise ValueError("event/ingest/available/processing order invalid")


def _is_non_empty_bounded_string(value: object, max_length: int) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= max_length and value.strip() != ""


def _parse_aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str) or _STRICT_RFC3339_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be a timezone-aware datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return parsed
