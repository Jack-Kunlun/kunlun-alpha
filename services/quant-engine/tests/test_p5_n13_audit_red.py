"""Regression tests added from the P5-N13 independent audit findings."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
import quant_engine.regression.smoke as smoke
from ashare_contracts.backtest_regression import Observation
from ashare_contracts.backtest_regression_semantics import toolchain_evidence_sha256
from backtest_core.engine import BacktestEngine
from backtest_core.portfolio import PortfolioState
from quant_engine.regression.artifact import (
    RegressionRunArtifact,
    RegressionValidationError,
    compute_artifact_sha256,
)
from quant_engine.regression.canonical import (
    RegressionCanonicalizationError,
    canonical_json,
    parse_canonical_json,
)
from quant_engine.regression.diff import compare_artifacts
from quant_engine.regression.repository import (
    ArtifactCorruptionError,
    FileRunArtifactRepository,
)
from quant_engine.regression.smoke import (
    _execution_inputs,  # pyright: ignore[reportPrivateUsage]
    _manifest,  # pyright: ignore[reportPrivateUsage]
    _portfolio_and_valuations,  # pyright: ignore[reportPrivateUsage]
    _RegressionProgram,  # pyright: ignore[reportPrivateUsage]
    run_smoke_chain,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


@pytest.mark.parametrize("key", ["\ue000", "\U00010000"])
def test_canonical_json_rejects_non_ascii_object_keys_recursively(key: str) -> None:
    with pytest.raises(RegressionCanonicalizationError):
        canonical_json({"outer": {key: 1}})

    payload = json.dumps({"outer": {key: 1}}, ensure_ascii=False, separators=(",", ":")) + "\n"
    with pytest.raises(RegressionCanonicalizationError):
        parse_canonical_json(payload.encode("utf-8"))


def _copy_provenance_fixture(destination: Path) -> Path:
    for relative in (
        "services/quant-engine/src",
        "services/quant-engine/pyproject.toml",
        "python/packages/backtest-core/src",
        "python/packages/backtest-core/pyproject.toml",
        "python/packages/quant-core/src",
        "python/packages/quant-core/pyproject.toml",
        "python/packages/ashare-contracts/src",
        "python/packages/ashare-contracts/pyproject.toml",
        "pyproject.toml",
        ".python-version",
        "uv.lock",
    ):
        source = REPO_ROOT / relative
        target = destination / relative
        if source.is_dir():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return destination


def test_source_and_lock_mutations_change_provenance_and_candidate_digest(tmp_path: Path) -> None:
    fixture = _copy_provenance_fixture(tmp_path / "repo")
    original = run_smoke_chain(repo_root=fixture).payload

    source_file = next((fixture / "python/packages/backtest-core/src/backtest_core").rglob("*.py"))
    source_file.write_text(
        source_file.read_text(encoding="utf-8") + "\n# source drift\n",
        encoding="utf-8",
    )
    source_drift = run_smoke_chain(repo_root=fixture).payload

    assert source_drift["artifactSha256"] != original["artifactSha256"]
    assert _object(_object(source_drift["provenance"])["code"])["treeSha256"] != _object(
        _object(original["provenance"])["code"]
    )["treeSha256"]

    lock_file = fixture / "uv.lock"
    lock_file.write_text(
        lock_file.read_text(encoding="utf-8") + "\n# lock drift\n",
        encoding="utf-8",
    )
    lock_drift = run_smoke_chain(repo_root=fixture).payload
    assert lock_drift["artifactSha256"] != source_drift["artifactSha256"]
    assert _object(_object(lock_drift["provenance"])["toolchain"])["uvLockSha256"] != _object(
        _object(source_drift["provenance"])["toolchain"]
    )["uvLockSha256"]


def test_cli_reports_dependency_drift_with_nonzero_exit(tmp_path: Path) -> None:
    fixture = _copy_provenance_fixture(tmp_path / "repo")
    baseline_source = (
        REPO_ROOT / "services/quant-engine/fixtures/regression/p5-core-chain.baseline.json"
    )
    baseline = fixture / "services/quant-engine/fixtures/regression/p5-core-chain.baseline.json"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(baseline_source, baseline)
    lock_file = fixture / "uv.lock"
    lock_file.write_text(
        lock_file.read_text(encoding="utf-8") + "\n# dependency drift\n",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "KUNLUN_REPO_ROOT": str(fixture),
        "PYTHONPATH": os.pathsep.join(
            str(fixture / relative)
            for relative in (
                "services/quant-engine/src",
                "python/packages/ashare-contracts/src",
                "python/packages/backtest-core/src",
                "python/packages/quant-core/src",
            )
        ),
    }

    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "quant_engine.regression",
            "check",
            "--baseline",
            str(baseline),
        ],
        cwd=fixture,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2, result.stdout + result.stderr


def test_smoke_chain_contains_real_t_plus_one_lineage() -> None:
    artifact = _object(run_smoke_chain().payload)
    results = _object(artifact["results"])
    t_plus_one = _object(results["tPlusOne"])
    same_day = _object(t_plus_one["sameDay"])
    next_day = _object(t_plus_one["nextDay"])
    counts = _object(results["counts"])

    assert same_day["status"] == "REJECTED"
    assert same_day["rejectReason"] == "T_PLUS_ONE_NOT_SELLABLE"
    assert same_day["fillCount"] == 0
    assert next_day["status"] == "FILLED"
    assert next_day["fillCount"] == 1
    assert counts["tPlusOneRejected"] == 1
    assert counts["nextDaySellFills"] == 1
    inputs = _object(artifact["inputs"])
    t_plus_one_inputs = _object(inputs["tPlusOne"])
    assert t_plus_one_inputs["sameDayBatchDigest"]
    assert t_plus_one_inputs["nextDayBatchDigest"]


def test_smoke_chain_keeps_the_public_exported_same_day_snapshot_not_sellable() -> None:
    manifest = _manifest()
    run = BacktestEngine().run(manifest, _RegressionProgram())
    intents = tuple(intent for trace in run.trace for intent in trace.intents)
    plan = _execution_inputs(manifest, intents)
    _state, _valuations, _nav, _risk_free, evidence = _portfolio_and_valuations(plan)

    assert len(evidence.same_day_sellability.lots) == 1
    lot = evidence.same_day_sellability.lots[0]
    assert lot.quantity > 0
    assert lot.sellable_quantity == 0
    assert lot.acquisition_trade_date == evidence.same_day_inputs.snapshot.trading_date


def test_valuations_use_point_in_time_portfolio_states() -> None:
    manifest = _manifest()
    run = BacktestEngine().run(manifest, _RegressionProgram())
    intents = tuple(intent for trace in run.trace for intent in trace.intents)
    plan = _execution_inputs(manifest, intents)
    value_portfolio_spy = Mock(wraps=smoke.value_portfolio)

    original_value_portfolio = smoke.value_portfolio
    smoke.value_portfolio = value_portfolio_spy  # pyright: ignore[reportAttributeAccessIssue]
    try:
        final_state, valuations, nav, risk_free, _evidence = _portfolio_and_valuations(plan)
    finally:
        smoke.value_portfolio = original_value_portfolio

    assert len(value_portfolio_spy.call_args_list) == len(valuations) == 4
    valuation_states = tuple(
        cast(PortfolioState, call.args[0]) for call in value_portfolio_spy.call_args_list
    )
    for state, (valuation, mark) in zip(valuation_states, valuations, strict=True):
        assert state.last_ordering_key is not None
        assert state.last_ordering_key[0] <= valuation.cutoff_time
        assert mark.available_time <= valuation.cutoff_time
        assert valuation.state_digest == state.state_digest

    assert valuation_states[0] == valuation_states[1] == valuation_states[2]
    assert valuation_states[0].open_lots
    assert valuation_states[3].last_ordering_key is not None
    assert valuation_states[3].last_ordering_key[0] == valuations[3][0].cutoff_time
    assert not valuation_states[3].open_lots
    assert valuation_states[3].state_digest == final_state.state_digest
    assert all(item.available_time <= item.observation_time for item in nav)
    assert all(item.available_time <= item.observation_time for item in risk_free)


def _rehashed_payload(mutate: Callable[[dict[str, object]], None]) -> dict[str, object]:
    artifact = run_smoke_chain()
    payload = copy.deepcopy(artifact.payload)
    mutate(payload)
    payload["artifactSha256"] = compute_artifact_sha256(payload)
    return payload


def test_toolchain_parser_rejects_forged_uv_lock_binding() -> None:
    def forge(payload: dict[str, object]) -> None:
        provenance = _object(payload["provenance"])
        toolchain = _object(provenance["toolchain"])
        toolchain["uvLockSha256"] = "b" * 64

    with pytest.raises(RegressionValidationError):
        RegressionRunArtifact.from_dict(_rehashed_payload(forge))


def test_toolchain_parser_rejects_forged_evidence_and_missing_binding() -> None:
    def forge(payload: dict[str, object]) -> None:
        provenance = _object(payload["provenance"])
        toolchain = _object(provenance["toolchain"])
        toolchain["evidenceSha256"] = "c" * 64
        config = cast(list[object], provenance["config"])
        assert isinstance(config, list)
        config[:] = [entry for entry in config if _object(entry)["name"] != "root-pyproject.toml"]

    with pytest.raises(RegressionValidationError):
        RegressionRunArtifact.from_dict(_rehashed_payload(forge))


@pytest.mark.parametrize("drift", ["source", "uv-lock", "result"])
def test_induced_source_uv_lock_and_result_drift_is_nonzero(drift: str) -> None:
    baseline = run_smoke_chain()
    payload = copy.deepcopy(baseline.payload)
    provenance = _object(payload["provenance"])
    if drift == "source":
        allowlist = cast(list[object], _object(provenance["code"])["allowlist"])
        _object(allowlist[0])["sha256"] = "c" * 64
    elif drift == "uv-lock":
        dependencies = cast(list[object], provenance["dependencies"])
        lock = next(
            _object(entry)
            for entry in dependencies
            if _object(entry)["name"] == "uv.lock"
        )
        lock["sha256"] = "d" * 64
        toolchain = _object(provenance["toolchain"])
        toolchain["uvLockSha256"] = "d" * 64
        toolchain["evidenceSha256"] = toolchain_evidence_sha256(
            {
                "python": cast(str, toolchain["python"]),
                "uv": cast(str, toolchain["uv"]),
                "hatchling": cast(str, toolchain["hatchling"]),
                "rootPyprojectSha256": cast(str, toolchain["rootPyprojectSha256"]),
                "servicePyprojectSha256": cast(
                    str, toolchain["servicePyprojectSha256"]
                ),
                "uvLockSha256": "d" * 64,
            }
        )
    else:
        metrics = _object(_object(payload["results"])["metrics"])
        cumulative_return = _object(metrics["cumulativeChainedReturn"])
        cumulative_return["value"] = "0.5"
    payload["artifactSha256"] = compute_artifact_sha256(payload)
    candidate = RegressionRunArtifact.from_dict(payload)
    comparison = compare_artifacts(baseline, candidate)
    assert comparison.status == "DRIFTED"
    assert comparison.diffs


@pytest.mark.parametrize("value", ["-0", "1.00", "0.0", "1e0", "+1", "01"])
def test_generated_pydantic_decimal_schema_rejects_noncanonical_values(value: str) -> None:
    with pytest.raises(ValueError):
        Observation.model_validate(
            {
                "observationTime": "2026-05-29T01:00:00.000000Z",
                "nav": value,
                "provenanceDigest": "a" * 64,
            }
        )


def test_generated_pydantic_comparison_semantics_are_trusted_boundary() -> None:
    from ashare_contracts.backtest_regression import BacktestRegressionComparison

    payload: dict[str, object] = {
        "baselineSha256": "a" * 64,
        "candidateSha256": "b" * 64,
        "status": "MATCHED",
        "categoryCounts": {
            "SCHEMA": 0,
            "MANIFEST_INPUT": 0,
            "ALGORITHM_CONFIG": 0,
            "DEPENDENCY_TOOLCHAIN": 0,
            "RESULT": 0,
        },
        "diffs": [],
        "diffLines": [],
    }
    BacktestRegressionComparison.model_validate(payload)
    payload["diffs"] = [
        {
            "category": "RESULT",
            "pointer": "/results/x",
            "status": "REPLACED",
            "baselineValue": 1,
            "candidateValue": 2,
        }
    ]
    payload["categoryCounts"] = {
        "SCHEMA": 0,
        "MANIFEST_INPUT": 0,
        "ALGORITHM_CONFIG": 0,
        "DEPENDENCY_TOOLCHAIN": 1,
        "RESULT": 0,
    }
    payload["diffLines"] = ["RESULT REPLACED /results/x"]
    with pytest.raises(ValueError):
        BacktestRegressionComparison.model_validate(payload)


def test_repository_rejects_digest_traversal_before_path_construction(tmp_path: Path) -> None:
    repository = FileRunArtifactRepository(tmp_path / "root")

    with pytest.raises(RegressionValidationError):
        repository.get("../escape", "run")


def test_repository_rejects_internal_ancestor_symlink(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "objects").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ArtifactCorruptionError):
        FileRunArtifactRepository(root)


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink permission is environment-dependent")
def test_repository_rejects_root_and_final_object_symlink(tmp_path: Path) -> None:
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    root_link = tmp_path / "root-link"
    root_link.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(ArtifactCorruptionError):
        FileRunArtifactRepository(root_link)

    repository = FileRunArtifactRepository(tmp_path / "store")
    artifact = run_smoke_chain()
    repository.append(artifact)
    object_path = (
        tmp_path
        / "store"
        / "objects"
        / "sha256"
        / artifact.artifact_sha256[:2]
        / f"{artifact.artifact_sha256}.json"
    )
    outside_object = tmp_path / "outside-object.json"
    outside_object.write_bytes(object_path.read_bytes())
    object_path.unlink()
    object_path.symlink_to(outside_object)
    with pytest.raises(ArtifactCorruptionError):
        repository.get(artifact.suite_id, artifact.run_id)


def _snapshot_tree(root: Path) -> dict[str, tuple[str, bytes | str | None]]:
    snapshot: dict[str, tuple[str, bytes | str | None]] = {}
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in (*directories, *files):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                snapshot[relative] = ("symlink", os.readlink(path))
            elif path.is_file():
                snapshot[relative] = ("file", path.read_bytes())
    return snapshot


def test_public_regression_cli_is_zero_write_with_isolated_cache(tmp_path: Path) -> None:
    fixture = _copy_provenance_fixture(tmp_path / "repo")
    baseline_source = (
        REPO_ROOT / "services/quant-engine/fixtures/regression/p5-core-chain.baseline.json"
    )
    baseline = fixture / "services/quant-engine/fixtures/regression/p5-core-chain.baseline.json"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(baseline_source, baseline)
    before = _snapshot_tree(fixture)
    baseline_before = baseline.read_bytes()
    result = subprocess.run(
        [
            "node",
            str(REPO_ROOT / "scripts/ci/backtest-regression-no-write.mjs"),
            "--root",
            str(fixture),
            "--baseline",
            str(baseline),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    after = _snapshot_tree(fixture)

    assert result.returncode == 0, result.stdout + result.stderr
    assert after == before
    assert baseline.read_bytes() == baseline_before


def test_wrapper_fails_when_child_mutates_any_isolated_subtree(tmp_path: Path) -> None:
    fixture = _copy_provenance_fixture(tmp_path / "repo")
    baseline_source = (
        REPO_ROOT / "services/quant-engine/fixtures/regression/p5-core-chain.baseline.json"
    )
    baseline = fixture / "services/quant-engine/fixtures/regression/p5-core-chain.baseline.json"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(baseline_source, baseline)

    result = subprocess.run(
        [
            "node",
            str(REPO_ROOT / "scripts/ci/backtest-regression-no-write.mjs"),
            "--root",
            str(fixture),
            "--baseline",
            str(baseline),
            "--test-child-write",
            "infra/docker/data/child-mutation.txt",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "tree changed" in result.stderr
