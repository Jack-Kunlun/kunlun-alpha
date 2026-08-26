"""Run the simulation-only paper-runtime endurance gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from paper_core.reliability import (
    EnduranceClockMode,
    EnduranceQualification,
    run_paper_endurance,
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
        "--allow-engineering-evidence",
        action="store_true",
        help="Return success for a non-qualifying virtual engineering run.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    clock_mode = EnduranceClockMode(args.clock_mode)
    report = run_paper_endurance(
        duration_hours=args.duration_hours,
        clock_mode=clock_mode,
        tick_seconds=args.tick_seconds,
    )
    output: Path = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(
        json.dumps(report.to_dict(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)

    print(
        json.dumps(
            {
                "evidenceDigest": report.evidence_digest,
                "evidenceScope": report.evidence_scope.value,
                "output": str(output),
                "qualification": report.qualification.value,
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
