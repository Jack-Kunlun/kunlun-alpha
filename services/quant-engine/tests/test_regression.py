from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from quant_engine.regression import (
    FileRunArtifactRepository,
    RegressionCanonicalizationError,
    canonical_json,
    compare_artifacts,
    run_smoke_chain,
)


def test_canonicalization_rejects_float_and_normalizes_decimal() -> None:
    assert canonical_json({"value": Decimal("1.00")}) == '{"value":"1"}\n'
    with pytest.raises(RegressionCanonicalizationError):
        canonical_json({"value": 1.0})


def test_public_smoke_chain_is_deterministic_and_has_two_orders() -> None:
    first = run_smoke_chain()
    second = run_smoke_chain()

    assert first.artifact_sha256 == second.artifact_sha256
    results = cast(dict[str, object], first.payload["results"])
    counts = cast(dict[str, object], results["counts"])
    trust = cast(dict[str, object], first.payload["trust"])
    assert counts["orders"] == 2
    assert trust["mode"] == "FIXTURE_SELF_CONTAINED"


def test_file_repository_is_append_only_and_supports_idempotent_reads(tmp_path: Path) -> None:
    artifact = run_smoke_chain()
    repository = FileRunArtifactRepository(tmp_path)

    repository.append(artifact)
    repository.append(artifact)

    loaded = repository.get(artifact.suite_id, artifact.run_id)
    assert loaded.artifact_sha256 == artifact.artifact_sha256


def test_comparison_reports_result_drift_without_ignoring_artifact_digest() -> None:
    artifact = run_smoke_chain()
    candidate = artifact.to_dict()
    results = cast(dict[str, object], candidate["results"])
    counts = cast(dict[str, object], results["counts"])
    counts["orders"] = 3
    candidate["artifactSha256"] = artifact.compute_sha256(candidate)

    comparison = compare_artifacts(artifact, candidate)

    assert comparison.is_match is False
    assert comparison.category_counts["RESULT"] == 1
    assert comparison.baseline_sha256 == artifact.artifact_sha256
