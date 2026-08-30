import json
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from paper_core.endurance_evidence import (
    EvidenceStatus,
    check_endurance_evidence,
    evidence_digest,
)

NOW = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
SOURCE_VERSION = f"git:{'a' * 40};source-sha256:{'b' * 64}"
EVIDENCE_TARGET = f"kunlun_paper_endurance_test_{'c' * 32}"
SCENARIO_NAMES = (
    "PROCESS_RESTART",
    "DUPLICATE_MESSAGE",
    "DATABASE_OUTAGE",
    "CACHE_LOSS",
)


def running_progress() -> dict[str, object]:
    return {
        "clockMode": "wall",
        "completedIterations": 1_880,
        "elapsedWallSeconds": 113_685.0,
        "evidenceScope": "DURABLE_ADAPTER",
        "executionCapability": "PAPER_ONLY",
        "requestedDurationHours": 72,
        "sourceVersion": SOURCE_VERSION,
        "startedAt": (NOW - timedelta(seconds=113_685)).isoformat().replace("+00:00", "Z"),
        "status": "RUNNING",
        "updatedAt": NOW.isoformat().replace("+00:00", "Z"),
        "evidenceTarget": EVIDENCE_TARGET,
        "processId": 44352,
        "storageAdapter": "postgresql",
    }


def completed_report() -> dict[str, object]:
    body: dict[str, object] = {
        "clockMode": "wall",
        "elapsedWallSeconds": 72 * 60 * 60,
        "evidenceScope": "DURABLE_ADAPTER",
        "evidenceTarget": EVIDENCE_TARGET,
        "executionCapability": "PAPER_ONLY",
        "faultInjection": "postgresql-database-connectivity-disable-and-backend-termination",
        "generatedAt": NOW.isoformat().replace("+00:00", "Z"),
        "qualification": "QUALIFIED",
        "reportVersion": "paper-endurance-report/v2",
        "requestedDurationHours": 72,
        "resourceMetrics": {
            "adapterConnectionsEnd": 0,
            "adapterConnectionsStart": 0,
            "pythonHeapEndBytes": 120,
            "pythonHeapGrowthBytes": 20,
            "pythonHeapPeakBytes": 140,
            "pythonHeapStartBytes": 100,
        },
        "scenarios": [
            {
                "details": "4320/4320 iterations passed",
                "iterations": 4320,
                "name": name,
                "status": "PASS",
            }
            for name in SCENARIO_NAMES
        ],
        "simulatedHours": 0,
        "startedAt": (NOW - timedelta(hours=72)).isoformat().replace("+00:00", "Z"),
        "storageAdapter": "postgresql",
        "sourceVersion": SOURCE_VERSION,
    }
    return {**body, "evidenceDigest": evidence_digest(body)}


def completed_progress(report: dict[str, object]) -> dict[str, object]:
    return {
        "evidenceDigest": report["evidenceDigest"],
        "evidenceScope": report["evidenceScope"],
        "evidenceTarget": report["evidenceTarget"],
        "executionCapability": report["executionCapability"],
        "generatedAt": report["generatedAt"],
        "processId": 44352,
        "qualification": report["qualification"],
        "sourceVersion": report["sourceVersion"],
        "status": "COMPLETED",
        "storageAdapter": report["storageAdapter"],
    }


def test_valid_running_evidence_is_explicitly_not_a_pass() -> None:
    result = check_endurance_evidence(
        running_progress(),
        None,
        now=NOW,
        expected_source_version=SOURCE_VERSION,
        check_process=True,
        process_is_alive=lambda process_id: process_id == 44352,
    )

    assert result.status is EvidenceStatus.IN_PROGRESS
    assert result.gate_satisfied is False
    assert result.errors == ()
    assert result.completed_iterations == 1_880
    assert result.elapsed_wall_seconds == 113_685.0


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("evidenceTarget", "kunlun_paper_endurance_p6n12_r2", "UNSAFE_EVIDENCE_TARGET"),
        ("clockMode", "virtual", "CLOCK_MODE_MISMATCH"),
        ("evidenceScope", "TEST_DOUBLE", "EVIDENCE_SCOPE_MISMATCH"),
        ("executionCapability", "LIVE", "EXECUTION_CAPABILITY_MISMATCH"),
        ("storageAdapter", "in-memory-test-double", "STORAGE_ADAPTER_MISMATCH"),
    ],
)
def test_running_evidence_fails_closed_on_nonqualifying_identity(
    field: str,
    value: object,
    code: str,
) -> None:
    progress = running_progress()
    progress[field] = value

    result = check_endurance_evidence(progress, None, now=NOW)

    assert result.status is EvidenceStatus.INVALID
    assert code in result.errors


def test_running_evidence_rejects_stale_progress_and_dead_process() -> None:
    progress = running_progress()
    progress["updatedAt"] = (NOW - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")

    result = check_endurance_evidence(
        progress,
        None,
        now=NOW,
        max_progress_age_seconds=180,
        check_process=True,
        process_is_alive=lambda _process_id: False,
    )

    assert result.status is EvidenceStatus.INVALID
    assert "STALE_PROGRESS" in result.errors
    assert "PROCESS_NOT_RUNNING" in result.errors


def test_complete_report_requires_all_formal_evidence_and_matching_progress() -> None:
    report = completed_report()

    result = check_endurance_evidence(
        completed_progress(report),
        report,
        now=NOW,
        expected_source_version=SOURCE_VERSION,
    )

    assert result.status is EvidenceStatus.QUALIFIED
    assert result.gate_satisfied is True
    assert result.errors == ()
    assert result.evidence_digest == report["evidenceDigest"]


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("qualification", "FAILED", "QUALIFICATION_MISMATCH"),
        ("elapsedWallSeconds", 259_199.0, "DURATION_INCOMPLETE"),
        ("clockMode", "virtual", "CLOCK_MODE_MISMATCH"),
        ("evidenceScope", "TEST_DOUBLE", "EVIDENCE_SCOPE_MISMATCH"),
        ("executionCapability", "LIVE", "EXECUTION_CAPABILITY_MISMATCH"),
        ("evidenceTarget", "kunlun_paper_endurance_p6n12_r2", "UNSAFE_EVIDENCE_TARGET"),
    ],
)
def test_complete_report_fails_closed_when_formal_evidence_is_invalid(
    field: str,
    value: object,
    code: str,
) -> None:
    report = completed_report()
    report[field] = value
    report["evidenceDigest"] = evidence_digest(
        {key: value for key, value in report.items() if key != "evidenceDigest"}
    )

    result = check_endurance_evidence(completed_progress(report), report, now=NOW)

    assert result.status is EvidenceStatus.INVALID
    assert code in result.errors


def test_complete_report_rejects_adapter_connection_leaks() -> None:
    report = completed_report()
    resources = cast(dict[str, object], report["resourceMetrics"])
    resources["adapterConnectionsEnd"] = 1
    report["evidenceDigest"] = evidence_digest(
        {key: value for key, value in report.items() if key != "evidenceDigest"}
    )

    result = check_endurance_evidence(completed_progress(report), report, now=NOW)

    assert result.status is EvidenceStatus.INVALID
    assert "ADAPTER_CONNECTION_LEAK" in result.errors


def test_complete_report_rejects_failed_scenarios() -> None:
    report = completed_report()
    scenarios = cast(list[dict[str, object]], report["scenarios"])
    scenarios[0]["status"] = "FAIL"
    report["evidenceDigest"] = evidence_digest(
        {key: value for key, value in report.items() if key != "evidenceDigest"}
    )

    result = check_endurance_evidence(completed_progress(report), report, now=NOW)

    assert result.status is EvidenceStatus.INVALID
    assert "SCENARIO_FAILED" in result.errors


def test_complete_report_rejects_duplicate_scenario_rows() -> None:
    report = completed_report()
    scenarios = cast(list[dict[str, object]], report["scenarios"])
    scenarios.append(deepcopy(scenarios[0]))
    report["evidenceDigest"] = evidence_digest(
        {key: value for key, value in report.items() if key != "evidenceDigest"}
    )

    result = check_endurance_evidence(completed_progress(report), report, now=NOW)

    assert result.status is EvidenceStatus.INVALID
    assert "SCENARIO_SET_MISMATCH" in result.errors


def test_complete_report_rejects_digest_tampering() -> None:
    report = completed_report()
    tampered = deepcopy(report)
    tampered["simulatedHours"] = 99

    result = check_endurance_evidence(completed_progress(report), tampered, now=NOW)

    assert result.status is EvidenceStatus.INVALID
    assert "EVIDENCE_DIGEST_MISMATCH" in result.errors
    assert "PROGRESS_REPORT_MISMATCH" in result.errors


def test_cli_reads_progress_without_modifying_evidence(tmp_path: Path) -> None:
    progress_path = tmp_path / "progress.json"
    progress_path.write_text(json.dumps(running_progress()), encoding="utf-8")
    before = progress_path.read_bytes()
    repository_root = Path(__file__).resolve().parents[4]

    completed = subprocess.run(
        [
            sys.executable,
            str(repository_root / "scripts/check-paper-soak-evidence.py"),
            "--progress",
            str(progress_path),
            "--expected-source-version",
            SOURCE_VERSION,
            "--max-progress-age-seconds",
            "3600",
            "--skip-process-check",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 3
    assert json.loads(completed.stdout)["status"] == "IN_PROGRESS"
    assert completed.stderr == ""
    assert progress_path.read_bytes() == before
