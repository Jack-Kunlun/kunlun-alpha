from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import cast, overload

STRATEGY_SDK_VERSION = "1.0.0"
_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")

type ScalarValue = bool | int | Decimal | str
type NumericBound = int | Decimal


class StrategyError(Exception):
    """Base error for the research-only strategy SDK."""


class StrategyInputError(StrategyError, ValueError):
    """Raised when a strategy boundary receives invalid input."""


class StrategyFutureDataError(StrategyInputError):
    """Raised when data was not available at the point-in-time cutoff."""


class ParameterType(str, Enum):
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    BOOLEAN = "BOOLEAN"
    STRING = "STRING"


class SignalDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


def _require_non_empty(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StrategyInputError(f"{field_name} must be a non-empty string")
    return value


def _require_version(value: object, field_name: str) -> str:
    version = _require_non_empty(value, field_name)
    if _VERSION_PATTERN.fullmatch(version) is None:
        raise StrategyInputError(f"{field_name} must be a semantic version")
    return version


def _require_aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise StrategyInputError(f"{field_name} must be timezone-aware")
    return value


@overload
def _require_tuple[T](value: tuple[T, ...], field_name: str) -> tuple[T, ...]: ...


@overload
def _require_tuple(value: object, field_name: str) -> tuple[object, ...]: ...


def _require_tuple(value: object, field_name: str) -> tuple[object, ...]:
    if type(value) is not tuple:
        raise StrategyInputError(f"{field_name} must be a tuple")
    return cast(tuple[object, ...], value)


def _require_instance[T](value: object, expected_type: type[T], field_name: str) -> T:
    if not isinstance(value, expected_type):
        raise StrategyInputError(f"{field_name} must be a {expected_type.__name__}")
    return value


def _require_mapping(value: object, field_name: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise StrategyInputError(f"{field_name} must be a mapping")
    return cast(Mapping[object, object], value)


def _require_scalar(value: object, field_name: str) -> ScalarValue:
    if type(value) in (bool, int, str):
        return cast(ScalarValue, value)
    if isinstance(value, Decimal) and value.is_finite():
        return value
    raise StrategyInputError(
        f"{field_name} must be bool, int, finite Decimal, or string; float is forbidden"
    )


def _require_sorted_unique_strings(values: object, field_name: str) -> tuple[str, ...]:
    items = _require_tuple(values, field_name)
    typed = tuple(_require_non_empty(item, field_name) for item in items)
    if len(set(typed)) != len(typed):
        raise StrategyInputError(f"{field_name} must not contain duplicates")
    if typed != tuple(sorted(typed)):
        raise StrategyInputError(f"{field_name} must be deterministically sorted")
    return typed


def _require_name_value_pair(value: object, field_name: str) -> tuple[str, ScalarValue]:
    pair = _require_tuple(value, field_name)
    if len(pair) != 2:
        raise StrategyInputError(f"{field_name} must contain (name, value) tuples")
    name = _require_non_empty(pair[0], f"{field_name} name")
    scalar = _require_scalar(pair[1], f"{field_name} {name}")
    return name, scalar


@dataclass(frozen=True, slots=True)
class FeatureValue:
    entity_id: str
    feature_name: str
    feature_version: str
    value: ScalarValue
    event_time: datetime
    available_time: datetime
    processing_time: datetime
    source_snapshot_id: str
    source_snapshot_version: str

    def __post_init__(self) -> None:
        _require_non_empty(self.entity_id, "entity_id")
        _require_non_empty(self.feature_name, "feature_name")
        _require_version(self.feature_version, "feature_version")
        _require_scalar(self.value, "value")
        event_time = _require_aware(self.event_time, "event_time")
        available_time = _require_aware(self.available_time, "available_time")
        processing_time = _require_aware(self.processing_time, "processing_time")
        if event_time > available_time or available_time > processing_time:
            raise StrategyInputError(
                "feature times must satisfy event_time <= available_time <= processing_time"
            )
        _require_non_empty(self.source_snapshot_id, "source_snapshot_id")
        _require_version(self.source_snapshot_version, "source_snapshot_version")


@dataclass(frozen=True, slots=True)
class UniverseSnapshot:
    snapshot_id: str
    snapshot_version: str
    as_of_time: datetime
    available_time: datetime
    processing_time: datetime
    entity_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_non_empty(self.snapshot_id, "snapshot_id")
        _require_version(self.snapshot_version, "snapshot_version")
        as_of_time = _require_aware(self.as_of_time, "as_of_time")
        available_time = _require_aware(self.available_time, "available_time")
        processing_time = _require_aware(self.processing_time, "processing_time")
        if as_of_time > available_time or available_time > processing_time:
            raise StrategyInputError(
                "universe times must satisfy as_of_time <= available_time <= processing_time"
            )
        entity_ids = _require_sorted_unique_strings(self.entity_ids, "entity_ids")
        if not entity_ids:
            raise StrategyInputError("entity_ids must not be empty")


@dataclass(frozen=True, slots=True)
class StrategyContext:
    decision_time: datetime
    data_cutoff_time: datetime
    snapshot_id: str
    snapshot_version: str
    universe: UniverseSnapshot
    features: tuple[FeatureValue, ...]

    def __post_init__(self) -> None:
        decision_time = _require_aware(self.decision_time, "decision_time")
        cutoff = _require_aware(self.data_cutoff_time, "data_cutoff_time")
        if cutoff > decision_time:
            raise StrategyFutureDataError("data_cutoff_time must not exceed decision_time")
        _require_non_empty(self.snapshot_id, "snapshot_id")
        _require_version(self.snapshot_version, "snapshot_version")
        universe = _require_instance(self.universe, UniverseSnapshot, "universe")
        if (
            universe.as_of_time > cutoff
            or universe.available_time > cutoff
            or universe.processing_time > cutoff
        ):
            raise StrategyFutureDataError("universe exceeds data cutoff")

        raw_features = _require_tuple(self.features, "features")
        features = tuple(_require_instance(item, FeatureValue, "feature") for item in raw_features)
        feature_keys = tuple((item.entity_id, item.feature_name) for item in features)
        if len(set(feature_keys)) != len(feature_keys):
            raise StrategyInputError("features must not contain duplicate entity/name pairs")
        if feature_keys != tuple(sorted(feature_keys)):
            raise StrategyInputError("features must be deterministically sorted")
        universe_entities = set(universe.entity_ids)
        for item in features:
            if item.entity_id not in universe_entities:
                raise StrategyInputError(
                    f"feature entity {item.entity_id!r} is outside historical universe"
                )
            if item.available_time > cutoff or item.processing_time > cutoff:
                raise StrategyFutureDataError("feature exceeds data cutoff")

    @property
    def entity_ids(self) -> tuple[str, ...]:
        return self.universe.entity_ids

    def get_feature(self, entity_id: str, feature_name: str) -> FeatureValue | None:
        return next(
            (
                item
                for item in self.features
                if item.entity_id == entity_id and item.feature_name == feature_name
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class StrategyParameterSpec:
    name: str
    value_type: ParameterType
    required: bool
    description: str
    default_value: ScalarValue | None = None
    minimum: NumericBound | None = None
    maximum: NumericBound | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.name, "parameter name")
        _require_instance(self.value_type, ParameterType, f"{self.name} value_type")
        if type(self.required) is not bool:
            raise StrategyInputError(f"{self.name} required must be boolean")
        _require_non_empty(self.description, f"{self.name} description")

        if self.value_type is ParameterType.INTEGER:
            if any(
                bound is not None and type(bound) is not int
                for bound in (self.minimum, self.maximum)
            ):
                raise StrategyInputError(f"{self.name} INTEGER bounds must be exact integers")
        elif self.value_type is ParameterType.DECIMAL:
            if any(
                bound is not None and (not isinstance(bound, Decimal) or not bound.is_finite())
                for bound in (self.minimum, self.maximum)
            ):
                raise StrategyInputError(
                    f"{self.name} DECIMAL bounds must be finite Decimal values"
                )
        elif self.minimum is not None or self.maximum is not None:
            raise StrategyInputError(
                f"{self.name} {self.value_type.value} parameters cannot have bounds"
            )

        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise StrategyInputError(f"{self.name} minimum must not exceed maximum")
        if self.default_value is not None:
            _validate_parameter_value(self, self.default_value, "default")


@dataclass(frozen=True, slots=True)
class StrategyDescriptor:
    strategy_id: str
    strategy_version: str
    algorithm_version: str
    sdk_version: str
    lifecycle_version: str
    description: str
    required_features: tuple[str, ...]
    parameter_specs: tuple[StrategyParameterSpec, ...]
    schema_version: str = field(default="strategy-descriptor-v1", init=False)
    lifecycle_hooks: tuple[str, ...] = field(
        default=("initialize", "onDecision", "finalize"), init=False
    )
    signal_schema_version: str = field(default="signal-v1", init=False)
    execution_capability: str = field(default="NONE", init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.strategy_id, "strategy_id")
        _require_version(self.strategy_version, "strategy_version")
        _require_version(self.algorithm_version, "algorithm_version")
        _require_version(self.sdk_version, "sdk_version")
        _require_version(self.lifecycle_version, "lifecycle_version")
        _require_non_empty(self.description, "description")
        required_features = _require_sorted_unique_strings(
            self.required_features, "required_features"
        )
        if not required_features:
            raise StrategyInputError("required_features must not be empty")
        raw_specs = _require_tuple(self.parameter_specs, "parameter_specs")
        if not raw_specs:
            raise StrategyInputError("parameter_specs must not be empty")
        specs = tuple(
            _require_instance(item, StrategyParameterSpec, "parameter spec") for item in raw_specs
        )
        names = tuple(item.name for item in specs)
        if len(set(names)) != len(names):
            raise StrategyInputError("parameter_specs must not contain duplicate names")
        if names != tuple(sorted(names)):
            raise StrategyInputError("parameter_specs must be deterministically sorted")


@dataclass(frozen=True, slots=True)
class StrategyParameters:
    descriptor_version: str
    values: tuple[tuple[str, ScalarValue], ...]

    def __post_init__(self) -> None:
        _require_version(self.descriptor_version, "descriptor_version")
        raw_values = _require_tuple(self.values, "values")
        names: list[str] = []
        for item in raw_values:
            name, _ = _require_name_value_pair(item, "parameter value")
            names.append(name)
        if len(set(names)) != len(names):
            raise StrategyInputError("values must not contain duplicate parameter names")
        if names != sorted(names):
            raise StrategyInputError("values must be deterministically sorted")

    def get(self, name: str) -> ScalarValue | None:
        return next((value for key, value in self.values if key == name), None)

    def as_dict(self) -> dict[str, ScalarValue]:
        return dict(self.values)


@dataclass(frozen=True, slots=True)
class StrategyState:
    state_version: str
    values: tuple[tuple[str, ScalarValue], ...]

    def __post_init__(self) -> None:
        _require_version(self.state_version, "state_version")
        raw_values = _require_tuple(self.values, "values")
        names: list[str] = []
        for item in raw_values:
            name, _ = _require_name_value_pair(item, "state value")
            names.append(name)
        if len(set(names)) != len(names):
            raise StrategyInputError("values must not contain duplicate state names")
        if names != sorted(names):
            raise StrategyInputError("values must be deterministically sorted")

    def get(self, name: str) -> ScalarValue | None:
        return next((value for key, value in self.values if key == name), None)


@dataclass(frozen=True, slots=True)
class Signal:
    signal_id: str
    schema_version: str
    strategy_id: str
    strategy_version: str
    algorithm_version: str
    entity_id: str
    decision_time: datetime
    data_cutoff_time: datetime
    direction: SignalDirection
    score: Decimal
    confidence: Decimal
    horizon_sessions: int
    rationale: str
    input_snapshot_id: str
    input_snapshot_version: str
    evidence_ids: tuple[str, ...]
    is_executable: bool = field(default=False, init=False)
    execution_capability: str = field(default="NONE", init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.signal_id, "signal_id")
        if self.schema_version != "signal-v1":
            raise StrategyInputError("schema_version must be signal-v1")
        _require_non_empty(self.strategy_id, "strategy_id")
        _require_version(self.strategy_version, "strategy_version")
        _require_version(self.algorithm_version, "algorithm_version")
        _require_non_empty(self.entity_id, "entity_id")
        decision_time = _require_aware(self.decision_time, "decision_time")
        cutoff = _require_aware(self.data_cutoff_time, "data_cutoff_time")
        if cutoff > decision_time:
            raise StrategyFutureDataError("data_cutoff_time must not exceed decision_time")
        _require_instance(self.direction, SignalDirection, "direction")
        score = _require_instance(self.score, Decimal, "score")
        if not score.is_finite():
            raise StrategyInputError("score must be a finite Decimal")
        if score < Decimal("-1") or score > Decimal("1"):
            raise StrategyInputError("score must be between -1 and 1")
        confidence = _require_instance(self.confidence, Decimal, "confidence")
        if not confidence.is_finite():
            raise StrategyInputError("confidence must be a finite Decimal")
        if confidence < Decimal(0) or confidence > Decimal(1):
            raise StrategyInputError("confidence must be between 0 and 1")
        if type(self.horizon_sessions) is not int or not 1 <= self.horizon_sessions <= 10_000:
            raise StrategyInputError("horizon_sessions must be an integer between 1 and 10000")
        _require_non_empty(self.rationale, "rationale")
        _require_non_empty(self.input_snapshot_id, "input_snapshot_id")
        _require_version(self.input_snapshot_version, "input_snapshot_version")
        evidence_ids = _require_sorted_unique_strings(self.evidence_ids, "evidence_ids")
        if not evidence_ids:
            raise StrategyInputError("evidence_ids must not be empty")


@dataclass(frozen=True, slots=True)
class StrategyResult:
    signals: tuple[Signal, ...]
    next_state: StrategyState
    diagnostics: tuple[str, ...]

    def __post_init__(self) -> None:
        raw_signals = _require_tuple(self.signals, "signals")
        for item in raw_signals:
            _require_instance(item, Signal, "signal")
        signal_ids = tuple(item.signal_id for item in raw_signals)
        if len(set(signal_ids)) != len(signal_ids):
            raise StrategyInputError("signals must not contain duplicate signal_id values")
        _require_instance(self.next_state, StrategyState, "next_state")
        diagnostics = _require_tuple(self.diagnostics, "diagnostics")
        for item in diagnostics:
            _require_non_empty(item, "diagnostic")


def _validate_parameter_value(
    spec: StrategyParameterSpec, value: object, source: str = "value"
) -> ScalarValue:
    if spec.value_type is ParameterType.INTEGER:
        if type(value) is not int:
            raise StrategyInputError(f"{spec.name} {source} must be an INTEGER")
    elif spec.value_type is ParameterType.DECIMAL:
        if not isinstance(value, Decimal) or not value.is_finite():
            raise StrategyInputError(f"{spec.name} {source} must be a finite DECIMAL")
    elif spec.value_type is ParameterType.BOOLEAN:
        if type(value) is not bool:
            raise StrategyInputError(f"{spec.name} {source} must be a BOOLEAN")
    elif spec.value_type is ParameterType.STRING:
        if not isinstance(value, str):
            raise StrategyInputError(f"{spec.name} {source} must be a STRING")
    else:  # pragma: no cover - guarded by StrategyParameterSpec
        raise StrategyInputError(f"{spec.name} has an unsupported parameter type")

    typed_value = _require_scalar(value, f"{spec.name} {source}")
    if spec.minimum is not None and typed_value < spec.minimum:  # type: ignore[operator]
        raise StrategyInputError(f"{spec.name} {source} is below minimum")
    if spec.maximum is not None and typed_value > spec.maximum:  # type: ignore[operator]
        raise StrategyInputError(f"{spec.name} {source} exceeds maximum")
    return typed_value


def validate_parameters(
    descriptor: StrategyDescriptor, supplied: Mapping[str, object]
) -> StrategyParameters:
    descriptor = _require_instance(descriptor, StrategyDescriptor, "descriptor")
    supplied_mapping = _require_mapping(supplied, "supplied parameters")
    supplied_values = {
        _require_non_empty(key, "parameter name"): value for key, value in supplied_mapping.items()
    }

    specs = {spec.name: spec for spec in descriptor.parameter_specs}
    unknown = sorted(set(supplied_values) - set(specs))
    if unknown:
        raise StrategyInputError(f"unknown parameter: {unknown[0]}")

    values: list[tuple[str, ScalarValue]] = []
    for name in sorted(specs):
        spec = specs[name]
        if name in supplied_values:
            values.append((name, _validate_parameter_value(spec, supplied_values[name])))
        elif spec.default_value is not None:
            values.append((name, spec.default_value))
        elif spec.required:
            raise StrategyInputError(f"missing required parameter: {name}")
    return StrategyParameters(
        descriptor_version=descriptor.strategy_version,
        values=tuple(values),
    )
