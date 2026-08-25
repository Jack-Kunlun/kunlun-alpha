"""Checked-in, manually approved regression baseline validation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .artifact import (
    RegressionRunArtifact,
    RegressionValidationError,
    _digest_reference,  # pyright: ignore[reportPrivateUsage]
    _exact,  # pyright: ignore[reportPrivateUsage]
    _list,  # pyright: ignore[reportPrivateUsage]
    _text,  # pyright: ignore[reportPrivateUsage]
    safe_id,
)
from .canonical import canonical_json, parse_canonical_json, require_timestamp

BASELINE_SCHEMA_VERSION = "backtest-regression-baseline-v1"


@dataclass(frozen=True, slots=True)
class BacktestRegressionBaseline:
    payload: dict[str, object]
    artifact: RegressionRunArtifact

    def __post_init__(self) -> None:
        normalized = deepcopy(self.payload)
        required = {
            "schemaVersion",
            "baselineId",
            "suiteId",
            "expectedArtifact",
            "expectedArtifactSha256",
            "approval",
        }
        _exact(normalized, required, "baseline")
        if normalized["schemaVersion"] != BASELINE_SCHEMA_VERSION:
            raise RegressionValidationError("baseline schemaVersion is unsupported")
        safe_id(normalized["baselineId"], "baseline.baselineId")
        safe_id(normalized["suiteId"], "baseline.suiteId")
        artifact = RegressionRunArtifact.from_dict(normalized["expectedArtifact"])
        if artifact.suite_id != normalized["suiteId"]:
            raise RegressionValidationError("baseline suiteId does not match expected artifact")
        if artifact.artifact_sha256 != normalized["expectedArtifactSha256"]:
            raise RegressionValidationError(
                "baseline expectedArtifactSha256 does not match artifact"
            )
        approval = _exact(
            normalized["approval"],
            {
                "approvalId",
                "reviewedBy",
                "reviewedAt",
                "reviewedArtifactSha256",
                "changeReference",
                "reason",
                "evidenceRefs",
            },
            "baseline.approval",
        )
        safe_id(approval["approvalId"], "baseline.approval.approvalId")
        _text(approval["reviewedBy"], "baseline.approval.reviewedBy")
        try:
            require_timestamp(approval["reviewedAt"], "baseline.approval.reviewedAt")
        except ValueError as error:
            raise RegressionValidationError(str(error)) from error
        if approval["reviewedArtifactSha256"] != artifact.artifact_sha256:
            raise RegressionValidationError("baseline approval digest does not match artifact")
        _digest_reference(approval["changeReference"], "baseline.approval.changeReference")
        if cast(dict[str, object], approval["changeReference"])["kind"] != "OPAQUE_EXTERNAL":
            raise RegressionValidationError("baseline changeReference must be opaque")
        _text(approval["reason"], "baseline.approval.reason")
        refs = _list(approval["evidenceRefs"], "baseline.approval.evidenceRefs")
        rendered: list[str] = []
        for index, ref in enumerate(refs):
            _digest_reference(ref, f"baseline.approval.evidenceRefs[{index}]")
            rendered.append(canonical_json(ref))
        if tuple(rendered) != tuple(sorted(rendered)):
            raise RegressionValidationError("baseline approval evidenceRefs must be ordered")
        object.__setattr__(self, "payload", normalized)
        object.__setattr__(self, "artifact", artifact)

    @classmethod
    def from_dict(cls, payload: object) -> BacktestRegressionBaseline:
        if not isinstance(payload, dict):
            raise RegressionValidationError("baseline must be an object")
        return cls(
            cast(dict[str, object], payload),
            RegressionRunArtifact.from_dict(cast(object, payload["expectedArtifact"])),
        )

    @property
    def baseline_id(self) -> str:
        return cast(str, self.payload["baselineId"])

    @property
    def suite_id(self) -> str:
        return cast(str, self.payload["suiteId"])


def load_baseline(path: Path) -> BacktestRegressionBaseline:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise RegressionValidationError(f"baseline is unavailable: {path}") from error
    return BacktestRegressionBaseline.from_dict(parse_canonical_json(raw, field_name="baseline"))


__all__ = ["BASELINE_SCHEMA_VERSION", "BacktestRegressionBaseline", "load_baseline"]
