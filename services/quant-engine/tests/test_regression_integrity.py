from __future__ import annotations

import copy
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from quant_engine.regression import (
    ArtifactConflictError,
    ArtifactCorruptionError,
    FileRunArtifactRepository,
    RegressionCanonicalizationError,
    RegressionValidationError,
    canonical_json,
    load_baseline,
    run_smoke_chain,
)
from quant_engine.regression.artifact import RegressionRunArtifact, compute_artifact_sha256
from quant_engine.regression.canonical import (
    canonical_bytes,
    decimal_string,
    parse_canonical_json,
    timestamp_string,
)
from quant_engine.regression.diff import compare_artifacts, parse_backtest_regression_comparison


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _candidate(
    artifact: RegressionRunArtifact,
    mutate: Callable[[dict[str, object]], None],
) -> RegressionRunArtifact:
    payload = copy.deepcopy(artifact.to_dict())
    mutate(payload)
    payload["artifactSha256"] = compute_artifact_sha256(payload)
    return RegressionRunArtifact.from_dict(payload)


def test_canonical_rejects_float_duplicate_key_bom_and_noncanonical_bytes() -> None:
    assert canonical_json({"b": "1", "a": ["2"]}) == '{"a":["2"],"b":"1"}\n'
    for invalid in ("1.00", "1e0", "+1", "-0"):
        with pytest.raises(RegressionCanonicalizationError):
            decimal_string(invalid)
    assert decimal_string("-0.5") == "-0.5"
    assert decimal_string("0.5") == "0.5"
    with pytest.raises(RegressionCanonicalizationError):
        canonical_json({"value": 1.0})
    with pytest.raises(RegressionCanonicalizationError):
        parse_canonical_json(b'{"a":1,"a":2}\n')
    with pytest.raises(RegressionCanonicalizationError):
        parse_canonical_json(b"\xef\xbb\xbf{}\n")
    with pytest.raises(RegressionCanonicalizationError):
        parse_canonical_json(b'{ "a": 1 }\n')


def test_timestamp_and_trust_schema_are_strict() -> None:
    assert timestamp_string(datetime(2026, 5, 29, tzinfo=UTC)) == "2026-05-29T00:00:00.000000Z"
    artifact = run_smoke_chain()
    payload = copy.deepcopy(artifact.to_dict())
    _object(payload["trust"])["mode"] = "INVESTMENT_CONFIDENCE"
    payload["artifactSha256"] = compute_artifact_sha256(payload)
    with pytest.raises(RegressionValidationError):
        RegressionRunArtifact.from_dict(payload)


def test_baseline_chain_rejects_tampering_and_missing_file(tmp_path: Path) -> None:
    baseline_path = Path("services/quant-engine/fixtures/regression/p5-core-chain.baseline.json")
    baseline = load_baseline(baseline_path)
    assert baseline.artifact.artifact_sha256 == baseline.payload["expectedArtifactSha256"]

    payload = copy.deepcopy(baseline.payload)
    _object(payload["approval"])["reviewedArtifactSha256"] = "0" * 64
    tampered = tmp_path / "tampered-baseline.json"
    tampered.write_bytes(canonical_bytes(payload))
    with pytest.raises(RegressionValidationError):
        load_baseline(tampered)
    with pytest.raises(RegressionValidationError):
        load_baseline(tmp_path / "missing-baseline.json")


def test_repository_conflict_corruption_traversal_and_symlink_fail_closed(tmp_path: Path) -> None:
    artifact = run_smoke_chain()
    repository = FileRunArtifactRepository(tmp_path / "objects")
    assert repository.append(artifact) == artifact.artifact_sha256

    changed = _candidate(
        artifact,
        lambda payload: _object(_object(payload["results"])["counts"]).__setitem__("orders", 3),
    )
    with pytest.raises(ArtifactConflictError):
        repository.append(changed)
    with pytest.raises(RegressionValidationError):
        repository.get("../escape", artifact.run_id)

    object_path = (
        tmp_path
        / "objects"
        / "objects"
        / "sha256"
        / artifact.artifact_sha256[:2]
        / f"{artifact.artifact_sha256}.json"
    )
    object_path.write_bytes(b"{}\n")
    with pytest.raises(ArtifactCorruptionError):
        repository.get(artifact.suite_id, artifact.run_id)

    if hasattr(os, "symlink") and os.name != "nt":
        second_root = tmp_path / "symlink-store"
        second = FileRunArtifactRepository(second_root)
        second.append(artifact)
        ref = second_root / "identities" / artifact.suite_id / f"{artifact.run_id}.ref.json"
        target = (
            second_root
            / "objects"
            / "sha256"
            / artifact.artifact_sha256[:2]
            / f"{artifact.artifact_sha256}.json"
        )
        ref.unlink()
        ref.symlink_to(target)
        with pytest.raises(ArtifactCorruptionError):
            second.get(artifact.suite_id, artifact.run_id)


def test_diff_categories_are_deterministic_and_dependencies_are_not_ignored() -> None:
    artifact = run_smoke_chain()

    def manifest_drift(payload: dict[str, object]) -> None:
        payload["suiteId"] = "p5-core-chain-alt"

    def algorithm_drift(payload: dict[str, object]) -> None:
        _object(payload["versions"])["strategy"] = "2.0.0"

    def dependency_drift(payload: dict[str, object]) -> None:
        dependencies = _object(payload["provenance"])["dependencies"]
        assert isinstance(dependencies, list)
        _object(cast(list[object], dependencies)[0])["version"] = "2.0.0"

    def result_drift(payload: dict[str, object]) -> None:
        _object(_object(payload["results"])["counts"])["fills"] = 3

    candidates = (
        _candidate(artifact, manifest_drift),
        _candidate(artifact, algorithm_drift),
        _candidate(artifact, dependency_drift),
        _candidate(artifact, result_drift),
    )
    categories = [
        compare_artifacts(artifact, candidate).diffs[0].category for candidate in candidates
    ]
    assert categories == ["MANIFEST_INPUT", "ALGORITHM_CONFIG", "DEPENDENCY_TOOLCHAIN", "RESULT"]
    comparison = compare_artifacts(artifact, candidates[-1])
    assert comparison.status == "DRIFTED"
    assert comparison.diff_lines == tuple(
        sorted(comparison.diff_lines, key=lambda line: (line.split(" ", 1)[0], line))
    )


def test_comparison_parser_rejects_semantic_drift() -> None:
    valid = {
        "baselineSha256": "a" * 64,
        "candidateSha256": "b" * 64,
        "status": "DRIFTED",
        "categoryCounts": {
            "SCHEMA": 0,
            "MANIFEST_INPUT": 0,
            "ALGORITHM_CONFIG": 0,
            "DEPENDENCY_TOOLCHAIN": 0,
            "RESULT": 1,
        },
        "diffs": [
            {
                "category": "RESULT",
                "pointer": "/results/x",
                "status": "REPLACED",
                "baselineValue": 1,
                "candidateValue": 2,
            }
        ],
        "diffLines": ["RESULT REPLACED /results/x"],
    }
    assert parse_backtest_regression_comparison(valid)["status"] == "DRIFTED"
    mutations: tuple[dict[str, object], ...] = (
        cast(dict[str, object], {"status": "MATCHED"}),
        cast(dict[str, object], {"diffLines": ["untrusted text"]}),
        cast(
            dict[str, object],
            {"categoryCounts": {**cast(dict[str, object], valid["categoryCounts"]), "RESULT": 0}},
        ),
        cast(
            dict[str, object],
            {
                "diffs": [
                    {
                        **_object(cast(list[object], valid["diffs"])[0]),
                        "pointer": "/results/~2",
                    }
                ]
            },
        ),
    )
    for mutation in mutations:
        candidate = cast(dict[str, object], copy.deepcopy(valid))
        candidate.update(mutation)
        with pytest.raises(RegressionValidationError):
            parse_backtest_regression_comparison(candidate)


def test_comparison_parity_fixture_matches_canonical_order_and_artifact_binding() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    baseline = load_baseline(
        repo_root / "services/quant-engine/fixtures/regression/p5-core-chain.baseline.json"
    )
    assert baseline.artifact.artifact_sha256 == baseline.payload["expectedArtifactSha256"]
    fixture = json.loads(
        (
            repo_root
            / "packages/contracts/fixtures/backtest-regression-comparison-parity.json"
        ).read_text(encoding="utf-8")
    )
    parsed = parse_backtest_regression_comparison(fixture)
    assert parsed["diffLines"] == fixture["diffLines"]
    assert parsed["categoryCounts"] == fixture["categoryCounts"]
