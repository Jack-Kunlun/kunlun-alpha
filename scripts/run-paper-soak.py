"""Run the simulation-only paper-runtime endurance gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from paper_core.postgres_reliability import (
    PostgresPaperFaultHarness,
)
from paper_core.reliability import (
    EnduranceClockMode,
    EnduranceQualification,
    InMemoryPaperFaultHarness,
    PaperEnduranceProgress,
    PaperFaultHarness,
    run_paper_endurance,
)

POSTGRES_ADMIN_DSN_ENV = "KUNLUN_PAPER_ENDURANCE_ADMIN_DSN"
SOURCE_FILES = (
    "python/packages/paper-core/pyproject.toml",
    "python/packages/paper-core/src/paper_core/postgres_reliability.py",
    "python/packages/paper-core/src/paper_core/reliability.py",
    "scripts/run-paper-soak.py",
    "uv.lock",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run paper-runtime recovery faults over an endurance window.",
    )
    parser.add_argument("--duration-hours", type=int, default=72)
    parser.add_argument(
        "--clock-mode",
        choices=[mode.value for mode in EnduranceClockMode],
        default=EnduranceClockMode.WALL.value,
    )
    parser.add_argument("--tick-seconds", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--progress-output",
        type=Path,
        help="Atomically update a separate JSON progress file after every iteration.",
    )
    parser.add_argument(
        "--store",
        choices=("test-double", "postgres"),
        default="test-double",
        help="Use the engineering test double or an isolated PostgreSQL database.",
    )
    parser.add_argument(
        "--postgres-database",
        default=None,
        help=(
            "Optional UUID-suffixed isolated database name. "
            "If omitted, the PostgreSQL harness generates a fresh name."
        ),
    )
    parser.add_argument(
        "--allow-engineering-evidence",
        action="store_true",
        help="Return success for a non-qualifying virtual engineering run.",
    )
    return parser.parse_args()


def _build_harness(args: argparse.Namespace) -> PaperFaultHarness:
    if args.store == "test-double":
        return InMemoryPaperFaultHarness()
    admin_dsn = os.environ.get(POSTGRES_ADMIN_DSN_ENV)
    if admin_dsn is None:
        raise SystemExit(f"{POSTGRES_ADMIN_DSN_ENV} must be set for --store postgres")
    harness = PostgresPaperFaultHarness(
        admin_dsn=admin_dsn,
        database_name=args.postgres_database,
    )
    harness.prepare_database()
    return harness


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _source_version() -> str:
    repository_root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for relative_path in SOURCE_FILES:
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update((repository_root / relative_path).read_bytes())
        digest.update(b"\0")
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unknown"
    return f"git:{revision};source-sha256:{digest.hexdigest()}"


def main() -> int:
    args = _parse_args()
    clock_mode = EnduranceClockMode(args.clock_mode)
    harness = _build_harness(args)
    source_version = _source_version()
    output: Path = args.output.resolve()
    progress_output: Path | None = (
        args.progress_output.resolve() if args.progress_output is not None else None
    )
    if progress_output is not None:
        _write_json_atomic(
            progress_output,
            {
                "evidenceScope": harness.evidence_scope.value,
                "evidenceTarget": harness.evidence_target,
                "executionCapability": "PAPER_ONLY",
                "processId": os.getpid(),
                "status": "STARTING",
                "storageAdapter": harness.storage_adapter,
                "sourceVersion": source_version,
            },
        )

    def record_progress(progress: PaperEnduranceProgress) -> None:
        if progress_output is not None:
            payload = progress.to_dict()
            payload.update(
                {
                    "evidenceTarget": harness.evidence_target,
                    "processId": os.getpid(),
                    "storageAdapter": harness.storage_adapter,
                }
            )
            _write_json_atomic(progress_output, payload)

    report = run_paper_endurance(
        duration_hours=args.duration_hours,
        clock_mode=clock_mode,
        tick_seconds=args.tick_seconds,
        harness=harness,
        progress_callback=record_progress,
        source_version=source_version,
    )
    _write_json_atomic(output, report.to_dict())
    if progress_output is not None:
        completed_progress = {
            "evidenceDigest": report.evidence_digest,
            "evidenceScope": report.evidence_scope.value,
            "evidenceTarget": report.evidence_target,
            "executionCapability": report.execution_capability,
            "generatedAt": report.to_dict()["generatedAt"],
            "processId": os.getpid(),
            "qualification": report.qualification.value,
            "sourceVersion": report.source_version,
            "status": "COMPLETED",
            "storageAdapter": report.storage_adapter,
        }
        _write_json_atomic(progress_output, completed_progress)

    print(
        json.dumps(
            {
                "evidenceDigest": report.evidence_digest,
                "evidenceScope": report.evidence_scope.value,
                "output": str(output),
                "qualification": report.qualification.value,
                "store": args.store,
            },
            ensure_ascii=True,
        )
    )
    if report.qualification is EnduranceQualification.QUALIFIED:
        return 0
    if (
        report.qualification is EnduranceQualification.ENGINEERING_EVIDENCE_ONLY
        and args.allow_engineering_evidence
        and clock_mode is EnduranceClockMode.VIRTUAL
    ):
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
