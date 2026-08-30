"""Inspect paper endurance progress and reports without mutating gate state."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from paper_core.endurance_evidence import EvidenceStatus, check_endurance_evidence


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only validation for P6-N12 paper endurance evidence.",
    )
    parser.add_argument("--progress", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--expected-source-version")
    parser.add_argument("--max-progress-age-seconds", type=int, default=180)
    parser.add_argument(
        "--skip-process-check",
        action="store_true",
        help="Do not verify that a RUNNING progress marker's process still exists.",
    )
    return parser.parse_args()


def _load_object(path: Path) -> Mapping[str, object]:
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("evidence JSON must contain an object")
    return cast(Mapping[str, object], payload)


def _invalid(code: str) -> int:
    print(
        json.dumps(
            {
                "completedIterations": None,
                "elapsedWallSeconds": None,
                "errors": [code],
                "evidenceDigest": None,
                "evidenceTarget": None,
                "gateSatisfied": False,
                "sourceVersion": None,
                "status": EvidenceStatus.INVALID.value,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 2


def main() -> int:
    args = _parse_args()
    try:
        progress = _load_object(args.progress)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return _invalid("PROGRESS_FILE_INVALID")

    report: Mapping[str, object] | None = None
    if args.report is not None and args.report.exists():
        try:
            report = _load_object(args.report)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return _invalid("REPORT_FILE_INVALID")

    result = check_endurance_evidence(
        progress,
        report,
        expected_source_version=args.expected_source_version,
        max_progress_age_seconds=args.max_progress_age_seconds,
        check_process=not args.skip_process_check,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=True, sort_keys=True))
    if result.status is EvidenceStatus.QUALIFIED:
        return 0
    if result.status is EvidenceStatus.IN_PROGRESS:
        return 3
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
