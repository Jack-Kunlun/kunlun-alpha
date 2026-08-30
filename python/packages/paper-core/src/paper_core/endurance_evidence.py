"""Read-only validation for paper-runtime endurance evidence files."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Final, cast

MINIMUM_QUALIFYING_HOURS: Final = 72
MAX_CLOCK_DRIFT_SECONDS: Final = 300.0
SOURCE_VERSION_PATTERN: Final = re.compile(r"^git:[0-9a-f]{40};source-sha256:[0-9a-f]{64}$")
EVIDENCE_TARGET_PATTERN: Final = re.compile(r"^kunlun_paper_endurance_[a-z0-9_]*[0-9a-f]{32}$")
EXPECTED_SCENARIOS: Final = frozenset(
    {"PROCESS_RESTART", "DUPLICATE_MESSAGE", "DATABASE_OUTAGE", "CACHE_LOSS"}
)
EXPECTED_FAULT_INJECTION: Final = "postgresql-database-connectivity-disable-and-backend-termination"


class EvidenceStatus(StrEnum):
    """Outcome of a read-only evidence inspection."""

    IN_PROGRESS = "IN_PROGRESS"
    QUALIFIED = "QUALIFIED"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class EvidenceCheck:
    status: EvidenceStatus
    gate_satisfied: bool
    errors: tuple[str, ...]
    evidence_target: str | None
    source_version: str | None
    completed_iterations: int | None
    elapsed_wall_seconds: float | None
    evidence_digest: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "completedIterations": self.completed_iterations,
            "elapsedWallSeconds": self.elapsed_wall_seconds,
            "errors": list(self.errors),
            "evidenceDigest": self.evidence_digest,
            "evidenceTarget": self.evidence_target,
            "gateSatisfied": self.gate_satisfied,
            "sourceVersion": self.source_version,
            "status": self.status.value,
        }


def evidence_digest(value: object) -> str:
    """Return the canonical SHA-256 used by the endurance report."""

    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _append(errors: list[str], code: str) -> None:
    if code not in errors:
        errors.append(code)


def _string(payload: Mapping[str, object], key: str, errors: list[str]) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        _append(errors, f"INVALID_{key.upper()}")
        return None
    return value


def _integer(payload: Mapping[str, object], key: str, errors: list[str]) -> int | None:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        _append(errors, f"INVALID_{key.upper()}")
        return None
    return value


def _number(payload: Mapping[str, object], key: str, errors: list[str]) -> float | None:
    value = payload.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        _append(errors, f"INVALID_{key.upper()}")
        return None
    number = float(value)
    if not (-float("inf") < number < float("inf")):
        _append(errors, f"INVALID_{key.upper()}")
        return None
    return number


def _timestamp(payload: Mapping[str, object], key: str, errors: list[str]) -> datetime | None:
    value = _string(payload, key, errors)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _append(errors, f"INVALID_{key.upper()}")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _append(errors, f"INVALID_{key.upper()}")
        return None
    return parsed.astimezone(UTC)


def _mapping(value: object, code: str, errors: list[str]) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        _append(errors, code)
        return None
    return cast(Mapping[str, object], value)


def _common_identity(
    payload: Mapping[str, object],
    errors: list[str],
    *,
    expected_source_version: str | None,
) -> tuple[str | None, str | None]:
    if payload.get("clockMode") != "wall":
        _append(errors, "CLOCK_MODE_MISMATCH")
    if payload.get("evidenceScope") != "DURABLE_ADAPTER":
        _append(errors, "EVIDENCE_SCOPE_MISMATCH")
    if payload.get("executionCapability") != "PAPER_ONLY":
        _append(errors, "EXECUTION_CAPABILITY_MISMATCH")
    if payload.get("storageAdapter") != "postgresql":
        _append(errors, "STORAGE_ADAPTER_MISMATCH")

    evidence_target = _string(payload, "evidenceTarget", errors)
    if evidence_target is not None and EVIDENCE_TARGET_PATTERN.fullmatch(evidence_target) is None:
        _append(errors, "UNSAFE_EVIDENCE_TARGET")

    source_version = _string(payload, "sourceVersion", errors)
    if source_version is not None and SOURCE_VERSION_PATTERN.fullmatch(source_version) is None:
        _append(errors, "INVALID_SOURCE_VERSION")
    if expected_source_version is not None and source_version != expected_source_version:
        _append(errors, "SOURCE_VERSION_MISMATCH")
    return evidence_target, source_version


def _completed_progress_identity(
    progress: Mapping[str, object],
    errors: list[str],
    *,
    expected_source_version: str | None,
) -> tuple[str | None, str | None]:
    """Validate the runner's compact COMPLETED marker.

    The authoritative report is separately required to carry and pass the wall-clock
    fields; the runner intentionally omits them from the final progress marker.
    """

    if progress.get("evidenceScope") != "DURABLE_ADAPTER":
        _append(errors, "EVIDENCE_SCOPE_MISMATCH")
    if progress.get("executionCapability") != "PAPER_ONLY":
        _append(errors, "EXECUTION_CAPABILITY_MISMATCH")
    if progress.get("storageAdapter") != "postgresql":
        _append(errors, "STORAGE_ADAPTER_MISMATCH")
    evidence_target = _string(progress, "evidenceTarget", errors)
    if evidence_target is not None and EVIDENCE_TARGET_PATTERN.fullmatch(evidence_target) is None:
        _append(errors, "UNSAFE_EVIDENCE_TARGET")
    source_version = _string(progress, "sourceVersion", errors)
    if source_version is not None and SOURCE_VERSION_PATTERN.fullmatch(source_version) is None:
        _append(errors, "INVALID_SOURCE_VERSION")
    if expected_source_version is not None and source_version != expected_source_version:
        _append(errors, "SOURCE_VERSION_MISMATCH")
    return evidence_target, source_version


def _default_process_is_alive(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _running_check(
    progress: Mapping[str, object],
    errors: list[str],
    *,
    now: datetime,
    max_progress_age_seconds: int,
    check_process: bool,
    process_is_alive: Callable[[int], bool],
) -> tuple[int | None, float | None]:
    requested_hours = _integer(progress, "requestedDurationHours", errors)
    if requested_hours is not None and requested_hours < MINIMUM_QUALIFYING_HOURS:
        _append(errors, "REQUESTED_DURATION_TOO_SHORT")

    completed_iterations = _integer(progress, "completedIterations", errors)
    if completed_iterations is not None and completed_iterations < 1:
        _append(errors, "INVALID_COMPLETED_ITERATIONS")
    elapsed_seconds = _number(progress, "elapsedWallSeconds", errors)
    if elapsed_seconds is not None and elapsed_seconds < 0:
        _append(errors, "INVALID_ELAPSEDWALLSECONDS")

    started_at = _timestamp(progress, "startedAt", errors)
    updated_at = _timestamp(progress, "updatedAt", errors)
    if started_at is not None and updated_at is not None:
        wall_elapsed = (updated_at - started_at).total_seconds()
        if wall_elapsed < 0:
            _append(errors, "TIMESTAMP_ORDER_INVALID")
        if (
            elapsed_seconds is not None
            and abs(wall_elapsed - elapsed_seconds) > MAX_CLOCK_DRIFT_SECONDS
        ):
            _append(errors, "CLOCK_ELAPSED_MISMATCH")
        age = (now - updated_at).total_seconds()
        if age > max_progress_age_seconds:
            _append(errors, "STALE_PROGRESS")
        if age < -MAX_CLOCK_DRIFT_SECONDS:
            _append(errors, "PROGRESS_FROM_FUTURE")

    process_id = _integer(progress, "processId", errors)
    if process_id is not None and process_id < 1:
        _append(errors, "INVALID_PROCESSID")
    if (
        check_process
        and process_id is not None
        and process_id > 0
        and not process_is_alive(process_id)
    ):
        _append(errors, "PROCESS_NOT_RUNNING")
    return completed_iterations, elapsed_seconds


def _validate_scenarios(report: Mapping[str, object], errors: list[str]) -> None:
    raw_scenarios = report.get("scenarios")
    if not isinstance(raw_scenarios, Sequence) or isinstance(raw_scenarios, (str, bytes)):
        _append(errors, "INVALID_SCENARIOS")
        return
    scenario_items = cast(Sequence[object], raw_scenarios)
    names: set[str] = set()
    iterations: set[int] = set()
    for raw_scenario in scenario_items:
        scenario = _mapping(raw_scenario, "INVALID_SCENARIOS", errors)
        if scenario is None:
            continue
        name = scenario.get("name")
        status = scenario.get("status")
        count = scenario.get("iterations")
        if isinstance(name, str):
            names.add(name)
        else:
            _append(errors, "INVALID_SCENARIOS")
        if status != "PASS":
            _append(errors, "SCENARIO_FAILED")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            _append(errors, "INVALID_SCENARIO_ITERATIONS")
        else:
            iterations.add(count)
    if frozenset(names) != EXPECTED_SCENARIOS:
        _append(errors, "SCENARIO_SET_MISMATCH")
    if len(scenario_items) != len(EXPECTED_SCENARIOS):
        _append(errors, "SCENARIO_SET_MISMATCH")
    if len(iterations) > 1:
        _append(errors, "SCENARIO_ITERATION_MISMATCH")


def _completed_check(
    progress: Mapping[str, object],
    report: Mapping[str, object],
    errors: list[str],
    *,
    expected_source_version: str | None,
) -> tuple[float | None, str | None]:
    _common_identity(report, errors, expected_source_version=expected_source_version)
    if report.get("reportVersion") != "paper-endurance-report/v2":
        _append(errors, "REPORT_VERSION_MISMATCH")
    if report.get("qualification") != "QUALIFIED":
        _append(errors, "QUALIFICATION_MISMATCH")
    if report.get("faultInjection") != EXPECTED_FAULT_INJECTION:
        _append(errors, "FAULT_INJECTION_MISMATCH")
    simulated_hours = report.get("simulatedHours")
    if (
        not isinstance(simulated_hours, int)
        or isinstance(simulated_hours, bool)
        or simulated_hours != 0
    ):
        _append(errors, "SIMULATED_HOURS_MISMATCH")

    requested_hours = _integer(report, "requestedDurationHours", errors)
    elapsed_seconds = _number(report, "elapsedWallSeconds", errors)
    if requested_hours is not None and requested_hours < MINIMUM_QUALIFYING_HOURS:
        _append(errors, "REQUESTED_DURATION_TOO_SHORT")
    if (
        requested_hours is not None
        and elapsed_seconds is not None
        and elapsed_seconds < requested_hours * 60 * 60
    ):
        _append(errors, "DURATION_INCOMPLETE")

    started_at = _timestamp(report, "startedAt", errors)
    generated_at = _timestamp(report, "generatedAt", errors)
    if started_at is not None and generated_at is not None and elapsed_seconds is not None:
        timestamp_elapsed = (generated_at - started_at).total_seconds()
        if timestamp_elapsed < 0:
            _append(errors, "TIMESTAMP_ORDER_INVALID")
        if abs(timestamp_elapsed - elapsed_seconds) > MAX_CLOCK_DRIFT_SECONDS:
            _append(errors, "CLOCK_ELAPSED_MISMATCH")

    resources = _mapping(report.get("resourceMetrics"), "INVALID_RESOURCE_METRICS", errors)
    if resources is not None:
        connections_end = resources.get("adapterConnectionsEnd")
        if (
            not isinstance(connections_end, int)
            or isinstance(connections_end, bool)
            or connections_end != 0
        ):
            _append(errors, "ADAPTER_CONNECTION_LEAK")
    _validate_scenarios(report, errors)

    digest = _string(report, "evidenceDigest", errors)
    if digest is not None and re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        _append(errors, "INVALID_EVIDENCE_DIGEST")
    evidence_body = {key: value for key, value in report.items() if key != "evidenceDigest"}
    computed_digest = evidence_digest(evidence_body)
    if digest != computed_digest:
        _append(errors, "EVIDENCE_DIGEST_MISMATCH")

    mirrored_fields = (
        "evidenceDigest",
        "evidenceScope",
        "evidenceTarget",
        "executionCapability",
        "generatedAt",
        "qualification",
        "sourceVersion",
        "storageAdapter",
    )
    if any(progress.get(field) != report.get(field) for field in mirrored_fields):
        _append(errors, "PROGRESS_REPORT_MISMATCH")
    if progress.get("evidenceDigest") != computed_digest:
        _append(errors, "PROGRESS_REPORT_MISMATCH")
    return elapsed_seconds, digest


def check_endurance_evidence(
    progress: Mapping[str, object],
    report: Mapping[str, object] | None,
    *,
    now: datetime | None = None,
    expected_source_version: str | None = None,
    max_progress_age_seconds: int = 180,
    check_process: bool = False,
    process_is_alive: Callable[[int], bool] | None = None,
) -> EvidenceCheck:
    """Validate progress/report payloads without connecting to their evidence store."""

    if max_progress_age_seconds < 1:
        raise ValueError("max_progress_age_seconds must be positive")
    checked_at = datetime.now(UTC) if now is None else now
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    errors: list[str] = []
    status_value = _string(progress, "status", errors)
    if status_value == "COMPLETED":
        evidence_target, source_version = _completed_progress_identity(
            progress,
            errors,
            expected_source_version=expected_source_version,
        )
    else:
        evidence_target, source_version = _common_identity(
            progress,
            errors,
            expected_source_version=expected_source_version,
        )

    completed_iterations: int | None = None
    elapsed_seconds: float | None = None
    digest: str | None = None
    if status_value == "RUNNING":
        if report is not None:
            _append(errors, "REPORT_PRESENT_WHILE_RUNNING")
        completed_iterations, elapsed_seconds = _running_check(
            progress,
            errors,
            now=checked_at.astimezone(UTC),
            max_progress_age_seconds=max_progress_age_seconds,
            check_process=check_process,
            process_is_alive=process_is_alive or _default_process_is_alive,
        )
        result_status = EvidenceStatus.INVALID if errors else EvidenceStatus.IN_PROGRESS
    elif status_value == "COMPLETED":
        if report is None:
            _append(errors, "REPORT_MISSING")
        else:
            elapsed_seconds, digest = _completed_check(
                progress,
                report,
                errors,
                expected_source_version=expected_source_version,
            )
        result_status = EvidenceStatus.INVALID if errors else EvidenceStatus.QUALIFIED
    else:
        _append(errors, "UNSUPPORTED_PROGRESS_STATUS")
        result_status = EvidenceStatus.INVALID

    return EvidenceCheck(
        status=result_status,
        gate_satisfied=result_status is EvidenceStatus.QUALIFIED,
        errors=tuple(errors),
        evidence_target=evidence_target,
        source_version=source_version,
        completed_iterations=completed_iterations,
        elapsed_wall_seconds=elapsed_seconds,
        evidence_digest=digest,
    )
