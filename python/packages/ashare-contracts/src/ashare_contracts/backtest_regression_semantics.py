"""Trusted semantic validation for backtest regression comparisons.

This module is intentionally dependency-free so generated Pydantic models,
Python consumers, and the quant engine can share the same rules.
"""

from __future__ import annotations

import hashlib
import json
import math
from functools import cmp_to_key
from typing import Any

DIFF_CATEGORIES = (
    "SCHEMA",
    "MANIFEST_INPUT",
    "ALGORITHM_CONFIG",
    "DEPENDENCY_TOOLCHAIN",
    "RESULT",
)
DIFF_STATUSES = ("ADDED", "REMOVED", "REPLACED")
ROOT_PYPROJECT_ENTRY = "root-pyproject.toml"
SERVICE_PYPROJECT_ENTRY = "quant-engine-pyproject.toml"
UV_LOCK_ENTRY = "uv.lock"


def compare_ascii(left: str, right: str) -> int:
    """Compare ASCII strings by code point without locale dependence."""

    for left_code, right_code in zip(map(ord, left), map(ord, right)):
        if left_code != right_code:
            return -1 if left_code < right_code else 1
    return (len(left) > len(right)) - (len(left) < len(right))


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def _is_json_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_value(item)
            for key, item in value.items()
        )
    return False


def _valid_pointer(pointer: object) -> bool:
    if not isinstance(pointer, str) or not pointer or not pointer.startswith("/"):
        return False
    if any(ord(character) > 127 for character in pointer):
        return False
    index = 0
    while index < len(pointer):
        if pointer[index] == "~":
            if index + 1 >= len(pointer) or pointer[index + 1] not in "01":
                return False
            index += 2
            continue
        index += 1
    return True


def _compare_diff(left: dict[str, Any], right: dict[str, Any]) -> int:
    category_result = DIFF_CATEGORIES.index(left["category"]) - DIFF_CATEGORIES.index(
        right["category"]
    )
    if category_result:
        return -1 if category_result < 0 else 1
    return compare_ascii(left["pointer"], right["pointer"])


def format_diff_line(diff: dict[str, Any]) -> str:
    return f'{diff["category"]} {diff["status"]} {diff["pointer"]}'


def toolchain_evidence_sha256(toolchain: dict[str, str]) -> str:
    payload = {
        "hatchling": toolchain["hatchling"],
        "python": toolchain["python"],
        "rootPyprojectSha256": toolchain["rootPyprojectSha256"],
        "servicePyprojectSha256": toolchain["servicePyprojectSha256"],
        "uv": toolchain["uv"],
        "uvLockSha256": toolchain["uvLockSha256"],
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_exact_keys(value: dict[str, Any], expected: set[str], context: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{context} must contain exactly {sorted(expected)}")


def _validate_counts(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("categoryCounts must be an object")
    if set(value) != set(DIFF_CATEGORIES):
        raise ValueError("categoryCounts must contain exactly the five diff categories")
    counts: dict[str, int] = {}
    for category in DIFF_CATEGORIES:
        count = value[category]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"categoryCounts.{category} must be a non-negative integer")
        counts[category] = count
    return counts


def validate_backtest_regression_comparison(value: object) -> dict[str, Any]:
    """Validate and return a canonical comparison payload.

    JSON Schema validates field shapes; this function validates all cross-field
    invariants and is the sole trusted semantic boundary for consumers.
    """

    if not isinstance(value, dict):
        raise ValueError("comparison must be an object")
    expected_keys = {
        "baselineSha256",
        "candidateSha256",
        "categoryCounts",
        "diffLines",
        "diffs",
        "status",
    }
    _require_exact_keys(value, expected_keys, "comparison")
    for field in ("baselineSha256", "candidateSha256"):
        digest = value[field]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    status = value["status"]
    if status not in ("MATCHED", "DRIFTED"):
        raise ValueError("comparison.status is invalid")
    counts = _validate_counts(value["categoryCounts"])
    raw_diffs = value["diffs"]
    if not isinstance(raw_diffs, list):
        raise ValueError("diffs must be an array")
    diffs: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for raw_diff in raw_diffs:
        if not isinstance(raw_diff, dict):
            raise ValueError("each diff must be an object")
        _require_exact_keys(
            raw_diff,
            {
                "baselineValue",
                "candidateValue",
                "category",
                "pointer",
                "status",
            },
            "diff",
        )
        category = raw_diff["category"]
        diff_status = raw_diff["status"]
        pointer = raw_diff["pointer"]
        if category not in DIFF_CATEGORIES:
            raise ValueError("diff category is invalid")
        if diff_status not in DIFF_STATUSES:
            raise ValueError("diff status is invalid")
        if not _valid_pointer(pointer):
            raise ValueError("diff pointer is not a valid ASCII RFC 6901 pointer")
        identity = (category, pointer)
        if identity in identities:
            raise ValueError("duplicate diff category and pointer")
        identities.add(identity)
        baseline = raw_diff["baselineValue"]
        candidate = raw_diff["candidateValue"]
        if not _is_json_value(baseline) or not _is_json_value(candidate):
            raise ValueError("diff values must be JSON values")
        if diff_status == "ADDED" and (baseline is not None or candidate is None):
            raise ValueError("ADDED diff must have only a candidate value")
        if diff_status == "REMOVED" and (baseline is None or candidate is not None):
            raise ValueError("REMOVED diff must have only a baseline value")
        if diff_status == "REPLACED" and (baseline is None or candidate is None):
            raise ValueError("REPLACED diff must have both values")
        diffs.append(
            {
                "baselineValue": baseline,
                "candidateValue": candidate,
                "category": category,
                "pointer": pointer,
                "status": diff_status,
            }
        )
    sorted_diffs = sorted(diffs, key=cmp_to_key(_compare_diff))
    if diffs != sorted_diffs:
        raise ValueError("diffs must be sorted by category and ASCII pointer")
    expected_counts = {category: 0 for category in DIFF_CATEGORIES}
    for diff in diffs:
        expected_counts[diff["category"]] += 1
    if counts != expected_counts:
        raise ValueError("categoryCounts does not match diffs")
    raw_lines = value["diffLines"]
    if not isinstance(raw_lines, list) or not all(isinstance(line, str) for line in raw_lines):
        raise ValueError("diffLines must be an array of strings")
    expected_lines = [format_diff_line(diff) for diff in diffs]
    if raw_lines != expected_lines:
        raise ValueError("diffLines does not match canonical diffs")
    if status == "MATCHED":
        if diffs or raw_lines or any(counts.values()):
            raise ValueError("MATCHED comparison must have no diffs or diff lines")
    elif not diffs:
        raise ValueError("DRIFTED comparison must have at least one diff")
    return {
        "baselineSha256": value["baselineSha256"],
        "candidateSha256": value["candidateSha256"],
        "categoryCounts": counts,
        "diffLines": raw_lines,
        "diffs": diffs,
        "status": status,
    }
