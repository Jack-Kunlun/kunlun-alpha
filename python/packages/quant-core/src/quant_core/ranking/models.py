from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

RANKING_ALGORITHM_VERSION = "intelligence-ranking-v1"

_SEMANTIC_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_INSTRUMENT_ID = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")


class RankingInputError(ValueError):
    """Raised when ranking input cannot produce a reproducible snapshot."""


class RankingDirection(StrEnum):
    HIGHER_IS_BETTER = "HIGHER_IS_BETTER"
    LOWER_IS_BETTER = "LOWER_IS_BETTER"


class MissingFeaturePolicy(StrEnum):
    EXCLUDE = "EXCLUDE"
    ZERO = "ZERO"
    RENORMALIZE = "RENORMALIZE"


class RankingRowStatus(StrEnum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"


def _is_runtime_instance(value: object, expected: type[object]) -> bool:
    return isinstance(value, expected)


def canonical_instant(value: datetime, *, field_name: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RankingInputError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class RankingFeatureSpec:
    key: str
    label: str
    weight_bps: int
    direction: RankingDirection
    missing_policy: MissingFeaturePolicy = MissingFeaturePolicy.RENORMALIZE

    def __post_init__(self) -> None:
        if not _is_runtime_instance(self.direction, RankingDirection):
            raise RankingInputError("feature direction must be a RankingDirection")
        if not _is_runtime_instance(self.missing_policy, MissingFeaturePolicy):
            raise RankingInputError("feature missing_policy must be a MissingFeaturePolicy")
        if type(self.weight_bps) is not int:
            raise RankingInputError("feature weight_bps must be an integer")
        if not self.key or self.key != self.key.strip():
            raise RankingInputError("feature key must be a non-empty canonical value")
        if not self.label.strip():
            raise RankingInputError(f"feature {self.key} requires a label")
        if not 1 <= self.weight_bps <= 10_000:
            raise RankingInputError(f"feature {self.key} weight_bps must be in [1, 10000]")


@dataclass(frozen=True, slots=True)
class RankingSpec:
    spec_id: str
    version: str
    features: tuple[RankingFeatureSpec, ...]
    minimum_coverage_bps: int = 5_000
    algorithm_version: str = RANKING_ALGORITHM_VERSION

    def __post_init__(self) -> None:
        if type(self.minimum_coverage_bps) is not int:
            raise RankingInputError("minimum_coverage_bps must be an integer")
        if not self.spec_id or self.spec_id != self.spec_id.strip():
            raise RankingInputError("spec_id must be a non-empty canonical value")
        if _SEMANTIC_VERSION.fullmatch(self.version) is None:
            raise RankingInputError("ranking spec version must use MAJOR.MINOR.PATCH")
        if not self.features:
            raise RankingInputError("ranking spec requires at least one feature")
        keys = [feature.key for feature in self.features]
        if len(keys) != len(set(keys)):
            raise RankingInputError("ranking feature keys must be unique")
        if sum(feature.weight_bps for feature in self.features) != 10_000:
            raise RankingInputError("ranking feature weights must total 10000 bps")
        if not 0 <= self.minimum_coverage_bps <= 10_000:
            raise RankingInputError("minimum_coverage_bps must be in [0, 10000]")
        if not self.algorithm_version.strip():
            raise RankingInputError("algorithm_version is required")

    @property
    def fingerprint(self) -> str:
        payload = {
            "algorithmVersion": self.algorithm_version,
            "features": [
                {
                    "direction": feature.direction.value,
                    "key": feature.key,
                    "label": feature.label,
                    "missingPolicy": feature.missing_policy.value,
                    "ordinal": ordinal,
                    "weightBps": feature.weight_bps,
                }
                for ordinal, feature in enumerate(self.features)
            ],
            "minimumCoverageBps": self.minimum_coverage_bps,
            "specId": self.spec_id,
            "version": self.version,
        }
        encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FeatureObservation:
    feature_key: str
    value: Decimal | None
    available_time: datetime | None = None
    source: str | None = None
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.feature_key or self.feature_key != self.feature_key.strip():
            raise RankingInputError("observation feature_key must be canonical")
        if self.value is None:
            if not isinstance(self.missing_reason, str) or not self.missing_reason.strip():
                raise RankingInputError(f"missing feature {self.feature_key} requires a reason")
            if self.available_time is not None:
                canonical_instant(self.available_time, field_name="available_time")
            return
        if not self.value.is_finite():
            raise RankingInputError(f"feature {self.feature_key} must be finite")
        if self.available_time is None:
            raise RankingInputError(f"feature {self.feature_key} requires available_time")
        canonical_instant(self.available_time, field_name="available_time")
        if not self.source or not self.source.strip():
            raise RankingInputError(f"feature {self.feature_key} requires source provenance")
        if self.missing_reason is not None:
            raise RankingInputError(
                f"available feature {self.feature_key} cannot have missing_reason"
            )


@dataclass(frozen=True, slots=True)
class InstrumentFeatureSnapshot:
    instrument_id: str
    instrument_name: str
    sector: str
    observations: tuple[FeatureObservation, ...]

    def __post_init__(self) -> None:
        if _INSTRUMENT_ID.fullmatch(self.instrument_id) is None:
            raise RankingInputError(f"invalid canonical instrument_id: {self.instrument_id}")
        if not self.instrument_name.strip():
            raise RankingInputError(f"instrument {self.instrument_id} requires a name")
        if not self.sector.strip():
            raise RankingInputError(f"instrument {self.instrument_id} requires a sector")
        keys = [observation.feature_key for observation in self.observations]
        if len(keys) != len(set(keys)):
            raise RankingInputError(f"instrument {self.instrument_id} has duplicate features")


@dataclass(frozen=True, slots=True)
class RankingContribution:
    feature_key: str
    label: str
    direction: RankingDirection
    raw_value: Decimal | None
    normalized_score_bps: int | None
    configured_weight_bps: int
    effective_weight_bps: int
    contribution_bps: int
    missing_reason: str | None
    available_time: datetime | None
    source: str | None


@dataclass(frozen=True, slots=True)
class RankingRow:
    instrument_id: str
    instrument_name: str
    sector: str
    status: RankingRowStatus
    rank: int | None
    score_bps: int | None
    coverage_bps: int
    contributions: tuple[RankingContribution, ...]
    exclusion_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RankingSnapshot:
    snapshot_id: str
    as_of: datetime
    generated_at: datetime
    spec: RankingSpec
    input_fingerprint: str
    rows: tuple[RankingRow, ...]

    def __post_init__(self) -> None:
        canonical_instant(self.as_of, field_name="as_of")
        canonical_instant(self.generated_at, field_name="generated_at")
        if self.generated_at < self.as_of:
            raise RankingInputError("generated_at must not be earlier than as_of")


@dataclass(frozen=True, slots=True)
class RankingFilter:
    query: str = ""
    sectors: frozenset[str] = frozenset()
    minimum_score_bps: int | None = None
    include_excluded: bool = False

    def __post_init__(self) -> None:
        if self.minimum_score_bps is not None and not 0 <= self.minimum_score_bps <= 10_000:
            raise RankingInputError("minimum_score_bps must be in [0, 10000]")
