from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import cast

from quant_core.strategy import (
    STRATEGY_SDK_VERSION,
    StrategyDescriptor,
    StrategyInputError,
    StrategyParameters,
    StrategyParameterSpec,
    validate_parameters,
)

from .models import (
    ScheduledDecisionEvent,
    require_aware,
    require_hex_digest,
    require_non_empty,
    revalidate_scheduled_decision_event,
)

BACKTEST_ENGINE_VERSION = "1.0.0"
MANIFEST_SCHEMA_VERSION = "1.0.0"
EVENT_ORDERING_VERSION = "1.0.0"
RNG_ALGORITHM = "sha256-counter-v2"
_NAMESPACED_DATASET_DIGEST = re.compile(r"^[A-Za-z0-9_.-]+:[^\s]+$")


def _revalidate_descriptor(value: object) -> StrategyDescriptor:
    if not isinstance(value, StrategyDescriptor):
        raise StrategyInputError("strategy_descriptor must be a StrategyDescriptor")
    try:
        StrategyDescriptor.__post_init__(value)
        if value.schema_version != "strategy-descriptor-v1":
            raise StrategyInputError("strategy_descriptor schema_version is not supported")
        if value.lifecycle_hooks != ("initialize", "onDecision", "finalize"):
            raise StrategyInputError("strategy_descriptor lifecycle_hooks are not canonical")
        if value.signal_schema_version != "signal-v1":
            raise StrategyInputError("strategy_descriptor signal_schema_version is not supported")
        if getattr(value, "exec" + "ution_capability") != "NONE":
            raise StrategyInputError("strategy_descriptor capability must be NONE")
        if value.sdk_version != STRATEGY_SDK_VERSION:
            raise StrategyInputError("strategy_descriptor sdk_version is not supported")
        for index, spec in enumerate(value.parameter_specs):
            if not isinstance(spec, StrategyParameterSpec):  # pyright: ignore[reportUnnecessaryIsInstance]
                raise StrategyInputError(
                    f"strategy_descriptor.parameter_specs[{index}] must be a StrategyParameterSpec"
                )
            StrategyParameterSpec.__post_init__(spec)
    except (AttributeError, TypeError) as error:
        raise StrategyInputError("strategy_descriptor contains a forged value") from error
    return value


def _revalidate_parameters(value: object) -> StrategyParameters:
    if not isinstance(value, StrategyParameters):
        raise StrategyInputError("strategy_parameters must be StrategyParameters")
    try:
        StrategyParameters.__post_init__(value)
    except (AttributeError, TypeError) as error:
        raise StrategyInputError("strategy_parameters contains a forged value") from error
    return value


def _validate_strategy_parameters(
    descriptor: StrategyDescriptor, parameters: StrategyParameters
) -> None:
    try:
        canonical_parameters = validate_parameters(descriptor, parameters.as_dict())
    except (AttributeError, TypeError, StrategyInputError) as error:
        raise StrategyInputError(
            f"strategy_parameters violate strategy_descriptor parameter_specs: {error}"
        ) from error
    if canonical_parameters != parameters:
        raise StrategyInputError(
            "strategy_parameters must equal the canonical descriptor parameter snapshot"
        )


def _require_dataset_digest(value: object) -> str:
    if not isinstance(value, str):
        raise StrategyInputError("dataset_digest must be a string")
    if _NAMESPACED_DATASET_DIGEST.fullmatch(value) is not None:
        return value
    try:
        return require_hex_digest(value, "dataset_digest")
    except StrategyInputError as error:
        raise StrategyInputError(
            "dataset_digest must be a 64-character lowercase hex digest "
            "or a namespaced external digest"
        ) from error


def _canonical_value(value: object) -> object:
    if value is None or type(value) is bool or type(value) is int or isinstance(value, str):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise StrategyInputError("canonical payload cannot contain a non-finite Decimal")
        return {"__decimal__": str(value)}
    if isinstance(value, datetime):
        aware = require_aware(value, "canonical datetime")
        utc_value = aware.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        return {"__datetime__": utc_value}
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    if is_dataclass(value):
        result: dict[str, object] = {}
        for field_info in fields(value):
            if field_info.name != "result_digest":
                field_value = cast(object, getattr(value, field_info.name))
                result[field_info.name] = _canonical_value(field_value)
        return result
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        items: dict[str, object] = {}
        mapping_items: tuple[tuple[object, object], ...] = tuple(mapping.items())
        for key, item in mapping_items:
            if not isinstance(key, str):
                raise StrategyInputError("canonical mappings require string keys")
            items[key] = _canonical_value(item)
        return {key: items[key] for key in sorted(items)}
    if isinstance(value, (tuple, list)):
        sequence_items = cast(Sequence[object], value)
        return [_canonical_value(item) for item in sequence_items]
    raise StrategyInputError(f"unsupported canonical value type: {type(value).__name__}")


def canonical_json(value: object) -> str:
    """Serialize a supported value without process-local or wall-clock data."""

    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def event_sort_key(event: ScheduledDecisionEvent) -> tuple[datetime, int, str, int, str]:
    return (
        event.logical_time.astimezone(UTC),
        event.phase,
        event.source_id,
        event.source_sequence,
        event.event_id,
    )


def _manifest_payload(manifest: BacktestRunManifest) -> dict[str, object]:
    return {
        "schema_version": manifest.schema_version,
        "engine_version": manifest.engine_version,
        "strategy_descriptor": manifest.strategy_descriptor,
        "strategy_parameters": manifest.strategy_parameters,
        "strategy_implementation_fingerprint": manifest.strategy_implementation_fingerprint,
        "policy_id": manifest.policy_id,
        "policy_version": manifest.policy_version,
        "policy_implementation_fingerprint": manifest.policy_implementation_fingerprint,
        "dataset_id": manifest.dataset_id,
        "dataset_version": manifest.dataset_version,
        "dataset_digest": manifest.dataset_digest,
        "code_version": manifest.code_version,
        "config_version": manifest.config_version,
        "event_ordering_version": manifest.event_ordering_version,
        "rng_algorithm": manifest.rng_algorithm,
        "rng_seed": manifest.rng_seed,
        "start_time": manifest.start_time,
        "end_time": manifest.end_time,
        "events": manifest.events,
    }


def _validate_manifest_metadata(manifest: BacktestRunManifest) -> tuple[datetime, datetime]:
    for field_name in (
        "schema_version",
        "engine_version",
        "strategy_implementation_fingerprint",
        "policy_id",
        "policy_version",
        "policy_implementation_fingerprint",
        "dataset_id",
        "dataset_version",
        "dataset_digest",
        "code_version",
        "config_version",
        "event_ordering_version",
        "rng_algorithm",
    ):
        require_non_empty(getattr(manifest, field_name), field_name)
    _require_dataset_digest(manifest.dataset_digest)
    descriptor = _revalidate_descriptor(manifest.strategy_descriptor)
    parameters = _revalidate_parameters(manifest.strategy_parameters)
    _validate_strategy_parameters(descriptor, parameters)
    if manifest.schema_version != MANIFEST_SCHEMA_VERSION:
        raise StrategyInputError("schema_version is not supported")
    if manifest.engine_version != BACKTEST_ENGINE_VERSION:
        raise StrategyInputError("engine_version is not supported")
    if manifest.event_ordering_version != EVENT_ORDERING_VERSION:
        raise StrategyInputError("event_ordering_version is not supported")
    if manifest.rng_algorithm != RNG_ALGORITHM:
        raise StrategyInputError("rng_algorithm is not supported")
    if type(manifest.rng_seed) not in (str, int):
        raise StrategyInputError("rng_seed must be a string or integer")
    if isinstance(manifest.rng_seed, str):
        require_non_empty(manifest.rng_seed, "rng_seed")
    start_time = require_aware(manifest.start_time, "start_time")
    end_time = require_aware(manifest.end_time, "end_time")
    if start_time > end_time:
        raise StrategyInputError("start_time must not exceed end_time")
    return start_time, end_time


def _validate_events(
    manifest: BacktestRunManifest,
    *,
    require_canonical_order: bool,
) -> tuple[ScheduledDecisionEvent, ...]:
    raw_events: object = cast(object, manifest.events)
    if type(raw_events) is not tuple:
        raise StrategyInputError("events must be an exact tuple")
    raw_event_values = cast(tuple[object, ...], raw_events)
    if not raw_event_values:
        raise StrategyInputError("events must not be empty")
    normalized_events = tuple(
        revalidate_scheduled_decision_event(event_value, f"events[{index}]")
        for index, event_value in enumerate(raw_event_values)
    )
    ordered_events = tuple(sorted(normalized_events, key=event_sort_key))
    if require_canonical_order and ordered_events != normalized_events:
        raise StrategyInputError("events must already be in canonical order")
    seen_event_ids: set[str] = set()
    seen_source_sequences: set[tuple[str, int]] = set()
    seen_sort_keys: set[tuple[datetime, int, str, int, str]] = set()
    for event in ordered_events:
        if event.event_id in seen_event_ids:
            raise StrategyInputError("event_id values must be unique")
        seen_event_ids.add(event.event_id)
        source_sequence = (event.source_id, event.source_sequence)
        if source_sequence in seen_source_sequences:
            raise StrategyInputError("source_sequence values must be unique per source")
        seen_source_sequences.add(source_sequence)
        sort_key = event_sort_key(event)
        if sort_key in seen_sort_keys:
            raise StrategyInputError("event ordering sort key conflict")
        seen_sort_keys.add(sort_key)
        if not manifest.start_time <= event.logical_time <= manifest.end_time:
            raise StrategyInputError("event logical_time must be within manifest range")
    return ordered_events


@dataclass(frozen=True, slots=True)
class BacktestRunManifest:
    """Frozen, canonical run inputs and their content digest."""

    schema_version: str
    engine_version: str
    strategy_descriptor: StrategyDescriptor
    strategy_parameters: StrategyParameters
    strategy_implementation_fingerprint: str
    policy_id: str
    policy_version: str
    policy_implementation_fingerprint: str
    dataset_id: str
    dataset_version: str
    dataset_digest: str
    code_version: str
    config_version: str
    event_ordering_version: str
    rng_algorithm: str
    rng_seed: str | int
    start_time: datetime
    end_time: datetime
    events: tuple[ScheduledDecisionEvent, ...]
    manifest_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_manifest_metadata(self)
        ordered_events = _validate_events(self, require_canonical_order=False)
        object.__setattr__(self, "events", ordered_events)
        object.__setattr__(self, "manifest_digest", canonical_digest(_manifest_payload(self)))

    def validate_integrity(self) -> None:
        """Revalidate current fields without sorting or repairing this manifest."""

        _validate_manifest_metadata(self)
        _validate_events(self, require_canonical_order=True)
        require_hex_digest(self.manifest_digest, "manifest_digest")
        expected_digest = canonical_digest(_manifest_payload(self))
        if self.manifest_digest != expected_digest:
            raise StrategyInputError("manifest_digest does not match current canonical payload")

    @property
    def descriptor(self) -> StrategyDescriptor:
        return self.strategy_descriptor

    @property
    def parameters(self) -> StrategyParameters:
        return self.strategy_parameters

    @property
    def digest(self) -> str:
        return self.manifest_digest

    def to_canonical_json(self) -> str:
        return canonical_json(_manifest_payload(self))


__all__ = [
    "BACKTEST_ENGINE_VERSION",
    "BacktestRunManifest",
    "EVENT_ORDERING_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "RNG_ALGORITHM",
    "canonical_digest",
    "canonical_json",
]
