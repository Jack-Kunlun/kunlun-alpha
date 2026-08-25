"""Strict, cross-platform canonical JSON for regression artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import cast


class RegressionCanonicalizationError(ValueError):
    """Raised when a value cannot be represented by the regression format."""


_DECIMAL_RE = re.compile(
    r"^(?:0|-?(?:0\.[0-9]*[1-9]|[1-9][0-9]*(?:\.[0-9]*[1-9])?))$"
)
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def decimal_string(value: Decimal | str, field_name: str = "Decimal") -> str:
    """Return one finite, fixed-point, non-negative-zero Decimal spelling."""

    if isinstance(value, str):
        if _DECIMAL_RE.fullmatch(value) is None:
            raise RegressionCanonicalizationError(
                f"{field_name} must be a canonical Decimal string without exponent"
            )
        try:
            decimal = Decimal(value)
        except ArithmeticError as error:
            raise RegressionCanonicalizationError(f"{field_name} is not a Decimal") from error
    elif type(value) is Decimal:
        decimal = value
    else:
        raise RegressionCanonicalizationError(f"{field_name} must be Decimal or string")

    if not decimal.is_finite():
        raise RegressionCanonicalizationError(f"{field_name} must be finite")
    if decimal.is_zero() and decimal.as_tuple().sign:
        raise RegressionCanonicalizationError(f"{field_name} must not be negative zero")
    fixed = format(decimal, "f")
    if "." in fixed:
        fixed = fixed.rstrip("0").rstrip(".")
    if fixed in ("", "-0"):
        fixed = "0"
    if fixed.startswith("+") or "e" in fixed.lower():
        raise RegressionCanonicalizationError(f"{field_name} has non-canonical spelling")
    if fixed == "-0":
        raise RegressionCanonicalizationError(f"{field_name} must not be negative zero")
    if isinstance(value, str):
        return value
    return fixed


def timestamp_string(value: object, field_name: str = "timestamp") -> str:
    """Serialize an aware datetime as UTC RFC3339 with exactly six decimals."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RegressionCanonicalizationError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def require_timestamp(value: object, field_name: str = "timestamp") -> str:
    if not isinstance(value, str) or _TIMESTAMP_RE.fullmatch(value) is None:
        raise RegressionCanonicalizationError(
            f"{field_name} must be UTC RFC3339 with six fractional digits"
        )
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise RegressionCanonicalizationError(f"{field_name} is not a valid timestamp") from error
    return value


def _canonical_value(value: object, field_name: str = "value") -> object:
    if value is None or type(value) is bool or type(value) is int:
        return value
    if type(value) is float:
        raise RegressionCanonicalizationError(f"{field_name} must not contain a float")
    if type(value) is Decimal:
        return decimal_string(value, field_name)
    if isinstance(value, datetime):
        return timestamp_string(value, field_name)
    if isinstance(value, Enum):
        return _canonical_value(value.value, field_name)
    if isinstance(value, str):
        if "\r" in value:
            raise RegressionCanonicalizationError(f"{field_name} must not contain CR")
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        items = cast(Mapping[object, object], value).items()
        for key, item in items:
            if not isinstance(key, str):
                raise RegressionCanonicalizationError(f"{field_name} mapping keys must be strings")
            if any(ord(character) > 0x7F for character in key):
                raise RegressionCanonicalizationError(
                    f"{field_name} mapping keys must be ASCII"
                )
            result[key] = _canonical_value(item, f"{field_name}.{key}")
        return result
    if isinstance(value, (tuple, list)):
        return [
            _canonical_value(item, f"{field_name}[{index}]")
            for index, item in enumerate(cast(Sequence[object], value))
        ]
    raise RegressionCanonicalizationError(
        f"{field_name} contains unsupported type {type(value).__name__}"
    )


def canonicalize(value: object) -> object:
    """Convert supported values without sorting or changing array order."""

    return _canonical_value(value)


def canonical_json(value: object) -> str:
    """Return UTF-8-ready compact JSON with sorted keys and one terminal LF."""

    normalized = canonicalize(value)
    return (
        json.dumps(
            normalized,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def canonical_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _reject_constant(value: str) -> object:
    raise RegressionCanonicalizationError(f"JSON constant {value} is not supported")


def parse_canonical_json(raw: bytes, *, field_name: str = "JSON") -> dict[str, object]:
    """Parse and byte-compare canonical JSON, rejecting duplicate keys."""

    if raw.startswith(b"\xef\xbb\xbf"):
        raise RegressionCanonicalizationError(f"{field_name} must not contain a BOM")
    if b"\r" in raw:
        raise RegressionCanonicalizationError(f"{field_name} must not contain CR")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RegressionCanonicalizationError(f"{field_name} is not valid UTF-8") from error

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        seen: set[str] = set()
        for key, value in pairs:
            if key in seen:
                raise RegressionCanonicalizationError(f"{field_name} contains duplicate key {key}")
            seen.add(key)
            result[key] = value
        return result

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_float=lambda value: (_ for _ in ()).throw(
                RegressionCanonicalizationError(
                    f"{field_name} must not contain JSON floats: {value}"
                )
            ),
            parse_constant=_reject_constant,
        )
    except RegressionCanonicalizationError:
        raise
    except (json.JSONDecodeError, TypeError) as error:
        raise RegressionCanonicalizationError(f"{field_name} is malformed JSON") from error
    if not isinstance(parsed, dict):
        raise RegressionCanonicalizationError(f"{field_name} root must be an object")
    parsed_object = cast(dict[str, object], parsed)
    try:
        expected = canonical_json(parsed_object)
    except RegressionCanonicalizationError:
        raise
    if expected.encode("utf-8") != raw:
        raise RegressionCanonicalizationError(f"{field_name} is not canonical JSON")
    return parsed_object


def require_sha256(value: object, field_name: str = "sha256") -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise RegressionCanonicalizationError(f"{field_name} must be lowercase SHA-256")
    return value


__all__ = [
    "RegressionCanonicalizationError",
    "canonical_bytes",
    "canonical_json",
    "canonical_sha256",
    "canonicalize",
    "decimal_string",
    "parse_canonical_json",
    "require_sha256",
    "require_timestamp",
    "timestamp_string",
]
