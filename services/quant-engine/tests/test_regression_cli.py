from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

from quant_engine.regression import run_smoke_chain
from quant_engine.regression.artifact import compute_artifact_sha256
from quant_engine.regression.canonical import canonical_bytes

ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / "services/quant-engine/fixtures/regression/p5-core-chain.baseline.json"


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "services/quant-engine/src")
    return subprocess.run(
        [sys.executable, "-m", "quant_engine.regression", *args],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_check_and_help_are_read_only() -> None:
    before = BASELINE.read_bytes()
    checked = _cli("check", "--baseline", str(BASELINE))
    assert checked.returncode == 0, checked.stderr
    help_result = _cli("--help")
    assert help_result.returncode == 0
    assert "update" not in help_result.stdout.lower()
    assert "accept" not in help_result.stdout.lower()
    assert "overwrite" not in help_result.stdout.lower()
    assert BASELINE.read_bytes() == before


def test_cli_compare_returns_nonzero_for_result_drift_without_writing(tmp_path: Path) -> None:
    artifact = run_smoke_chain()
    candidate = copy.deepcopy(artifact.to_dict())
    results = cast(dict[str, object], candidate["results"])
    counts = cast(dict[str, object], results["counts"])
    counts["orders"] = 3
    candidate["artifactSha256"] = compute_artifact_sha256(candidate)
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_bytes(canonical_bytes(candidate))
    before = BASELINE.read_bytes()

    compared = _cli(
        "compare",
        "--baseline",
        str(BASELINE),
        "--candidate",
        str(candidate_path),
    )

    assert compared.returncode == 2
    assert '"status":"DRIFTED"' in compared.stdout
    assert BASELINE.read_bytes() == before
