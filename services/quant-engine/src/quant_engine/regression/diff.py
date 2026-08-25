"""Deterministic RFC6901 tree comparison for regression artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cmp_to_key
from typing import cast

from ashare_contracts.backtest_regression_semantics import (
    compare_ascii,
    validate_backtest_regression_comparison,
)

from .artifact import RegressionRunArtifact, RegressionValidationError

DIFF_CATEGORIES = (
    "SCHEMA",
    "MANIFEST_INPUT",
    "ALGORITHM_CONFIG",
    "DEPENDENCY_TOOLCHAIN",
    "RESULT",
)
_CATEGORY_ORDER = {value: index for index, value in enumerate(DIFF_CATEGORIES)}


def json_pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _compare_diff(left: RegressionDiff, right: RegressionDiff) -> int:
    category_result = _CATEGORY_ORDER[left.category] - _CATEGORY_ORDER[right.category]
    if category_result:
        return -1 if category_result < 0 else 1
    return compare_ascii(left.pointer, right.pointer)


def parse_backtest_regression_comparison(value: object) -> dict[str, object]:
    try:
        return validate_backtest_regression_comparison(value)
    except ValueError as error:
        raise RegressionValidationError(str(error)) from error


def _category(pointer: str) -> str:
    first = pointer.split("/", 2)[1] if pointer.startswith("/") else ""
    if first in {"schemaVersion", "canonicalizationVersion"}:
        return "SCHEMA"
    if first in {"manifest", "inputs", "suiteId", "runId", "fixtureId"}:
        return "MANIFEST_INPUT"
    if first == "provenance":
        second = pointer.split("/", 3)[2] if pointer.count("/") >= 2 else ""
        if second in {"dependencies", "toolchain"}:
            return "DEPENDENCY_TOOLCHAIN"
        return "ALGORITHM_CONFIG"
    if first == "versions" or first == "trust":
        return "ALGORITHM_CONFIG"
    if first == "results":
        return "RESULT"
    return "SCHEMA"


def _diff_tree(baseline: object, candidate: object, pointer: str = "") -> list[dict[str, object]]:
    if isinstance(baseline, dict) and isinstance(candidate, dict):
        baseline_object = cast(dict[str, object], baseline)
        candidate_object = cast(dict[str, object], candidate)
        keys: list[str] = sorted(set(baseline_object) | set(candidate_object))
        result: list[dict[str, object]] = []
        for key in keys:
            if pointer == "" and key == "artifactSha256":
                continue
            child = f"{pointer}/{json_pointer_segment(key)}"
            if key not in baseline_object:
                result.append(
                    {
                        "category": _category(child),
                        "pointer": child,
                        "status": "ADDED",
                        "baselineValue": None,
                        "candidateValue": candidate_object[key],
                    }
                )
            elif key not in candidate_object:
                result.append(
                    {
                        "category": _category(child),
                        "pointer": child,
                        "status": "REMOVED",
                        "baselineValue": baseline_object[key],
                        "candidateValue": None,
                    }
                )
            else:
                result.extend(_diff_tree(baseline_object[key], candidate_object[key], child))
        return result
    if isinstance(baseline, list) and isinstance(candidate, list):
        baseline_list = cast(list[object], baseline)
        candidate_list = cast(list[object], candidate)
        result = []
        for index in range(max(len(baseline_list), len(candidate_list))):
            child = f"{pointer}/{index}"
            if index >= len(baseline_list):
                result.append(
                    {
                        "category": _category(child),
                        "pointer": child,
                        "status": "ADDED",
                        "baselineValue": None,
                        "candidateValue": candidate_list[index],
                    }
                )
            elif index >= len(candidate_list):
                result.append(
                    {
                        "category": _category(child),
                        "pointer": child,
                        "status": "REMOVED",
                        "baselineValue": baseline_list[index],
                        "candidateValue": None,
                    }
                )
            else:
                result.extend(_diff_tree(baseline_list[index], candidate_list[index], child))
        return result
    if baseline != candidate:
        return [
            {
                "category": _category(pointer),
                "pointer": pointer or "/",
                "status": "REPLACED",
                "baselineValue": baseline,
                "candidateValue": candidate,
            }
        ]
    return []


@dataclass(frozen=True, slots=True)
class RegressionDiff:
    category: str
    pointer: str
    status: str
    baseline_value: object
    candidate_value: object

    def __post_init__(self) -> None:
        if self.category not in DIFF_CATEGORIES:
            raise ValueError("unsupported regression diff category")
        if self.status not in {"ADDED", "REMOVED", "REPLACED"}:
            raise ValueError("unsupported regression diff status")

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "pointer": self.pointer,
            "status": self.status,
            "baselineValue": self.baseline_value,
            "candidateValue": self.candidate_value,
        }


@dataclass(frozen=True, slots=True)
class RegressionComparison:
    baseline_sha256: str
    candidate_sha256: str
    status: str
    diffs: tuple[RegressionDiff, ...]

    @property
    def is_match(self) -> bool:
        return self.status == "MATCHED"

    @property
    def category_counts(self) -> dict[str, int]:
        counts = {category: 0 for category in DIFF_CATEGORIES}
        for diff in self.diffs:
            counts[diff.category] += 1
        return counts

    @property
    def diff_lines(self) -> tuple[str, ...]:
        return tuple(f"{diff.category} {diff.status} {diff.pointer}" for diff in self.diffs)

    def to_dict(self) -> dict[str, object]:
        return {
            "baselineSha256": self.baseline_sha256,
            "candidateSha256": self.candidate_sha256,
            "status": self.status,
            "categoryCounts": self.category_counts,
            "diffs": [diff.to_dict() for diff in self.diffs],
            "diffLines": list(self.diff_lines),
        }


def _artifact(value: RegressionRunArtifact | object) -> RegressionRunArtifact:
    return (
        value
        if isinstance(value, RegressionRunArtifact)
        else RegressionRunArtifact.from_dict(value)
    )


def compare_artifacts(
    baseline: RegressionRunArtifact | object,
    candidate: RegressionRunArtifact | object,
) -> RegressionComparison:
    baseline_artifact = _artifact(baseline)
    candidate_artifact = _artifact(candidate)
    raw_diffs = _diff_tree(baseline_artifact.payload, candidate_artifact.payload)
    diffs = tuple(
        RegressionDiff(
            category=cast(str, item["category"]),
            pointer=cast(str, item["pointer"]),
            status=cast(str, item["status"]),
            baseline_value=item["baselineValue"],
            candidate_value=item["candidateValue"],
        )
        for item in raw_diffs
    )
    ordered = tuple(
        sorted(diffs, key=cmp_to_key(_compare_diff))
    )
    comparison = RegressionComparison(
        baseline_sha256=baseline_artifact.artifact_sha256,
        candidate_sha256=candidate_artifact.artifact_sha256,
        status="MATCHED" if not ordered else "DRIFTED",
        diffs=ordered,
    )
    parse_backtest_regression_comparison(comparison.to_dict())
    return comparison


__all__ = [
    "DIFF_CATEGORIES",
    "RegressionComparison",
    "RegressionDiff",
    "compare_artifacts",
    "json_pointer_segment",
]
