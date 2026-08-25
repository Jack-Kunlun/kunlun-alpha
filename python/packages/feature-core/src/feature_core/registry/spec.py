"""Immutable feature specifications and point-in-time semantics."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, cast

FEATURE_SPEC_SCHEMA_VERSION: Final = "feature-spec-v1"

_FEATURE_NAME = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_FEATURE_VERSION = re.compile(r"^v[1-9][0-9]*$")
_FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_SEMANTIC_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")

_FEATURE_SPEC_CONTRACT_KEYS = frozenset(
    {
        "schemaVersion",
        "name",
        "version",
        "entity",
        "frequency",
        "valueType",
        "owner",
        "description",
        "algorithmVersion",
        "calculationDefinition",
        "windowDefinition",
        "filterPolicyVersion",
        "pitPolicyVersion",
        "eventTimeField",
        "availableTimeField",
        "availabilityPolicy",
        "dependencies",
        "sourceContracts",
        "semanticFingerprint",
    }
)


class FeatureSpecValidationError(ValueError):
    """Raised when a feature specification is malformed."""


class FeatureEntity(StrEnum):
    INSTRUMENT = "INSTRUMENT"
    SECTOR = "SECTOR"
    MARKET = "MARKET"
    EVENT = "EVENT"
    SEAT = "SEAT"
    KOL = "KOL"
    PRECIOUS_METALS_FUND = "PRECIOUS_METALS_FUND"


class FeatureFrequency(StrEnum):
    TICK = "TICK"
    MINUTE = "MINUTE"
    DAILY = "DAILY"
    EVENT = "EVENT"
    SNAPSHOT = "SNAPSHOT"


class FeatureValueType(StrEnum):
    BOOLEAN = "BOOLEAN"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    STRING = "STRING"
    CATEGORY = "CATEGORY"
    VECTOR = "VECTOR"


class AvailabilityPolicy(StrEnum):
    SOURCE_AVAILABLE_TIME = "SOURCE_AVAILABLE_TIME"
    MAX_INPUT_AVAILABLE_TIME = "MAX_INPUT_AVAILABLE_TIME"
    MATERIALIZATION_TIME = "MATERIALIZATION_TIME"


def _required_text(value: object, field_name: str, *, maximum: int) -> str:
    if type(value) is not str:
        raise FeatureSpecValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise FeatureSpecValidationError(f"{field_name} must not be empty")
    if normalized != value:
        raise FeatureSpecValidationError(f"{field_name} must not contain outer whitespace")
    if len(normalized) > maximum:
        raise FeatureSpecValidationError(f"{field_name} must be at most {maximum} characters")
    return normalized


def _feature_name(value: object, field_name: str = "name") -> str:
    normalized = _required_text(value, field_name, maximum=128)
    if _FEATURE_NAME.fullmatch(normalized) is None:
        raise FeatureSpecValidationError(
            f"{field_name} must be a lowercase dotted feature name",
        )
    return normalized


def _feature_version(value: object, field_name: str = "version") -> str:
    normalized = _required_text(value, field_name, maximum=16)
    if _FEATURE_VERSION.fullmatch(normalized) is None:
        raise FeatureSpecValidationError(f"{field_name} must match vN with N >= 1")
    return normalized


def _field_name(value: object, field_name: str) -> str:
    normalized = _required_text(value, field_name, maximum=64)
    if _FIELD_NAME.fullmatch(normalized) is None:
        raise FeatureSpecValidationError(f"{field_name} must be a snake_case field name")
    return normalized


def _enum_value[T: StrEnum](value: object, enum_type: type[T], field_name: str) -> T:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        allowed = ", ".join(item.value for item in enum_type)
        raise FeatureSpecValidationError(f"{field_name} must be one of: {allowed}") from error


@dataclass(frozen=True, slots=True)
class FeatureDependency:
    """An exact dependency on another feature version."""

    name: str
    version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _feature_name(self.name, "dependency name"))
        object.__setattr__(self, "version", _feature_version(self.version, "dependency version"))

    def to_contract(self) -> dict[str, str]:
        return {"name": self.name, "version": self.version}


@dataclass(frozen=True, slots=True)
class SourceContract:
    """An exact raw-input or provider contract required by a feature."""

    name: str
    version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _feature_name(self.name, "source contract name"))
        object.__setattr__(
            self,
            "version",
            _feature_version(self.version, "source contract version"),
        )

    def to_contract(self) -> dict[str, str]:
        return {"name": self.name, "version": self.version}


def _validated_dependencies(values: Iterable[object]) -> tuple[FeatureDependency, ...]:
    dependencies: list[FeatureDependency] = []
    seen: set[str] = set()
    for dependency in values:
        if not isinstance(dependency, FeatureDependency):
            raise FeatureSpecValidationError(
                "dependencies must contain FeatureDependency values",
            )
        if dependency.name in seen:
            raise FeatureSpecValidationError(
                f"duplicate dependency name: {dependency.name}",
            )
        seen.add(dependency.name)
        dependencies.append(dependency)
    return tuple(dependencies)


def _validated_source_contracts(values: Iterable[object]) -> tuple[SourceContract, ...]:
    source_contracts: list[SourceContract] = []
    seen: set[str] = set()
    for source_contract in values:
        if not isinstance(source_contract, SourceContract):
            raise FeatureSpecValidationError(
                "source_contracts must contain SourceContract values",
            )
        if source_contract.name in seen:
            raise FeatureSpecValidationError(
                f"duplicate source contract name: {source_contract.name}",
            )
        seen.add(source_contract.name)
        source_contracts.append(source_contract)
    return tuple(source_contracts)


def _contract_versions(value: object, field_name: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        raise FeatureSpecValidationError(f"{field_name} must be an object")
    items: list[tuple[str, str]] = []
    mapping = cast(Mapping[object, object], value)
    for raw_name, raw_version in mapping.items():
        items.append(
            (
                _feature_name(raw_name, f"{field_name} name"),
                _feature_version(raw_version, f"{field_name} version"),
            )
        )
    return tuple(sorted(items))


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """Canonical, versioned semantics for one point-in-time feature."""

    name: str
    version: str
    entity: FeatureEntity
    frequency: FeatureFrequency
    value_type: FeatureValueType
    owner: str
    description: str
    algorithm_version: str
    calculation_definition: str
    window_definition: str
    filter_policy_version: str
    pit_policy_version: str
    event_time_field: str
    available_time_field: str
    availability_policy: AvailabilityPolicy
    dependencies: tuple[FeatureDependency, ...] = ()
    source_contracts: tuple[SourceContract, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _feature_name(self.name))
        object.__setattr__(self, "version", _feature_version(self.version))
        object.__setattr__(self, "entity", _enum_value(self.entity, FeatureEntity, "entity"))
        object.__setattr__(
            self,
            "frequency",
            _enum_value(self.frequency, FeatureFrequency, "frequency"),
        )
        object.__setattr__(
            self,
            "value_type",
            _enum_value(self.value_type, FeatureValueType, "value_type"),
        )
        object.__setattr__(self, "owner", _required_text(self.owner, "owner", maximum=128))
        object.__setattr__(
            self,
            "description",
            _required_text(self.description, "description", maximum=2_000),
        )
        object.__setattr__(
            self,
            "algorithm_version",
            _feature_version(self.algorithm_version, "algorithm_version"),
        )
        object.__setattr__(
            self,
            "calculation_definition",
            _required_text(
                self.calculation_definition,
                "calculation_definition",
                maximum=4_000,
            ),
        )
        object.__setattr__(
            self,
            "window_definition",
            _required_text(self.window_definition, "window_definition", maximum=256),
        )
        object.__setattr__(
            self,
            "filter_policy_version",
            _feature_version(self.filter_policy_version, "filter_policy_version"),
        )
        object.__setattr__(
            self,
            "pit_policy_version",
            _feature_version(self.pit_policy_version, "pit_policy_version"),
        )
        object.__setattr__(
            self,
            "event_time_field",
            _field_name(self.event_time_field, "event_time_field"),
        )
        object.__setattr__(
            self,
            "available_time_field",
            _field_name(self.available_time_field, "available_time_field"),
        )
        object.__setattr__(
            self,
            "availability_policy",
            _enum_value(
                self.availability_policy,
                AvailabilityPolicy,
                "availability_policy",
            ),
        )

        object.__setattr__(
            self,
            "dependencies",
            _validated_dependencies(self.dependencies),
        )
        object.__setattr__(
            self,
            "source_contracts",
            _validated_source_contracts(self.source_contracts),
        )

    @property
    def version_number(self) -> int:
        return int(self.version[1:])

    @property
    def semantic_fingerprint(self) -> str:
        payload = {
            "algorithmVersion": self.algorithm_version,
            "availabilityPolicy": self.availability_policy.value,
            "availableTimeField": self.available_time_field,
            "calculationDefinition": self.calculation_definition,
            "dependencies": {
                dependency.name: dependency.version
                for dependency in sorted(
                    self.dependencies,
                    key=lambda item: (item.name, item.version),
                )
            },
            "description": self.description,
            "entity": self.entity.value,
            "eventTimeField": self.event_time_field,
            "filterPolicyVersion": self.filter_policy_version,
            "frequency": self.frequency.value,
            "name": self.name,
            "pitPolicyVersion": self.pit_policy_version,
            "sourceContracts": {
                source_contract.name: source_contract.version
                for source_contract in sorted(
                    self.source_contracts,
                    key=lambda item: (item.name, item.version),
                )
            },
            "valueType": self.value_type.value,
            "windowDefinition": self.window_definition,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    @classmethod
    def from_contract(cls, payload: Mapping[str, object]) -> FeatureSpec:
        payload_keys = frozenset(payload)
        if payload_keys != _FEATURE_SPEC_CONTRACT_KEYS:
            missing = sorted(_FEATURE_SPEC_CONTRACT_KEYS - payload_keys)
            extra = sorted(payload_keys - _FEATURE_SPEC_CONTRACT_KEYS)
            raise FeatureSpecValidationError(
                f"FeatureSpec contract keys mismatch; missing={missing}, extra={extra}",
            )
        if payload["schemaVersion"] != FEATURE_SPEC_SCHEMA_VERSION:
            raise FeatureSpecValidationError("unsupported FeatureSpec schemaVersion")

        dependencies = tuple(
            FeatureDependency(name=name, version=version)
            for name, version in _contract_versions(payload["dependencies"], "dependencies")
        )
        source_contracts = tuple(
            SourceContract(name=name, version=version)
            for name, version in _contract_versions(
                payload["sourceContracts"],
                "sourceContracts",
            )
        )
        spec = cls(
            name=_feature_name(payload["name"]),
            version=_feature_version(payload["version"]),
            entity=_enum_value(payload["entity"], FeatureEntity, "entity"),
            frequency=_enum_value(payload["frequency"], FeatureFrequency, "frequency"),
            value_type=_enum_value(payload["valueType"], FeatureValueType, "valueType"),
            owner=_required_text(payload["owner"], "owner", maximum=128),
            description=_required_text(payload["description"], "description", maximum=2_000),
            algorithm_version=_feature_version(
                payload["algorithmVersion"],
                "algorithmVersion",
            ),
            calculation_definition=_required_text(
                payload["calculationDefinition"],
                "calculationDefinition",
                maximum=4_000,
            ),
            window_definition=_required_text(
                payload["windowDefinition"],
                "windowDefinition",
                maximum=256,
            ),
            filter_policy_version=_feature_version(
                payload["filterPolicyVersion"],
                "filterPolicyVersion",
            ),
            pit_policy_version=_feature_version(
                payload["pitPolicyVersion"],
                "pitPolicyVersion",
            ),
            event_time_field=_field_name(payload["eventTimeField"], "eventTimeField"),
            available_time_field=_field_name(
                payload["availableTimeField"],
                "availableTimeField",
            ),
            availability_policy=_enum_value(
                payload["availabilityPolicy"],
                AvailabilityPolicy,
                "availabilityPolicy",
            ),
            dependencies=dependencies,
            source_contracts=source_contracts,
        )
        supplied_fingerprint = _required_text(
            payload["semanticFingerprint"],
            "semanticFingerprint",
            maximum=71,
        )
        if _SEMANTIC_FINGERPRINT.fullmatch(supplied_fingerprint) is None or not hmac.compare_digest(
            supplied_fingerprint,
            spec.semantic_fingerprint,
        ):
            raise FeatureSpecValidationError(
                "semanticFingerprint does not match normalized FeatureSpec semantics",
            )
        return spec

    def to_contract(self) -> dict[str, object]:
        return {
            "schemaVersion": FEATURE_SPEC_SCHEMA_VERSION,
            "name": self.name,
            "version": self.version,
            "entity": self.entity.value,
            "frequency": self.frequency.value,
            "valueType": self.value_type.value,
            "owner": self.owner,
            "description": self.description,
            "algorithmVersion": self.algorithm_version,
            "calculationDefinition": self.calculation_definition,
            "windowDefinition": self.window_definition,
            "filterPolicyVersion": self.filter_policy_version,
            "pitPolicyVersion": self.pit_policy_version,
            "eventTimeField": self.event_time_field,
            "availableTimeField": self.available_time_field,
            "availabilityPolicy": self.availability_policy.value,
            "dependencies": {
                dependency.name: dependency.version
                for dependency in sorted(
                    self.dependencies,
                    key=lambda item: (item.name, item.version),
                )
            },
            "sourceContracts": {
                source_contract.name: source_contract.version
                for source_contract in sorted(
                    self.source_contracts,
                    key=lambda item: (item.name, item.version),
                )
            },
            "semanticFingerprint": self.semantic_fingerprint,
        }
