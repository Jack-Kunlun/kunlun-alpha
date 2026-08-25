"""Read-only regression comparison CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .artifact import RegressionValidationError, parse_artifact_bytes
from .baseline import load_baseline
from .canonical import canonical_json
from .diff import compare_artifacts
from .smoke import run_smoke_chain


def _read_artifact(path: Path):
    try:
        return parse_artifact_bytes(path.read_bytes())
    except OSError as error:
        raise RegressionValidationError(f"candidate artifact is unavailable: {path}") from error


def _check(args: argparse.Namespace) -> int:
    baseline = load_baseline(Path(args.baseline))
    candidate = run_smoke_chain()
    if candidate.suite_id != baseline.suite_id:
        raise RegressionValidationError("candidate suiteId does not match baseline")
    comparison = compare_artifacts(baseline.artifact, candidate)
    print(canonical_json(comparison.to_dict()), end="")
    return 0 if comparison.is_match else 2


def _compare(args: argparse.Namespace) -> int:
    baseline = load_baseline(Path(args.baseline))
    candidate = _read_artifact(Path(args.candidate))
    comparison = compare_artifacts(baseline.artifact, candidate)
    print(canonical_json(comparison.to_dict()), end="")
    return 0 if comparison.is_match else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only backtest regression comparison")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="run the fixed smoke chain against a baseline")
    check.add_argument("--baseline", required=True, help="checked-in baseline JSON")
    check.set_defaults(handler=_check)
    compare = commands.add_parser("compare", help="compare a candidate artifact with a baseline")
    compare.add_argument("--baseline", required=True, help="checked-in baseline JSON")
    compare.add_argument("--candidate", required=True, help="read-only candidate artifact JSON")
    compare.set_defaults(handler=_compare)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (RegressionValidationError, ValueError, OSError) as error:
        print(f"backtest regression check failed: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
