"""Immutable prompt, model, profile, and deployment records."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

_COORDINATE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
_VARIABLE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}")
_ENVIRONMENT_REFERENCE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{2,127}")


def _require_text(value: object, field_name: str, *, maximum: int) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    if len(value) > maximum:
        raise ValueError(f"{field_name} must be at most {maximum} characters")
    return value


def _require_coordinate(value: object, field_name: str) -> str:
    text = _require_text(value, field_name, maximum=128)
    if _COORDINATE_PATTERN.fullmatch(text) is None:
        raise ValueError(f"{field_name} must be a version-safe coordinate")
    return text


def _require_aware_utc(value: object, field_name: str) -> datetime:
    if type(value) is not datetime:
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _require_strict_integer(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be a strict integer")
    return value


def _require_basis_points(value: object, field_name: str) -> int:
    result = _require_strict_integer(value, field_name)
    if not 0 <= result <= 10_000:
        raise ValueError(f"{field_name} must be between 0 and 10000")
    return result


def _canonical_fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class DeploymentOperation(str, Enum):
    """Append-only deployment operation."""

    RELEASE = "RELEASE"
    ROLLBACK = "ROLLBACK"


class SelectedVariant(str, Enum):
    """Variant selected by deterministic rollout routing."""

    PRIMARY = "PRIMARY"
    CANDIDATE = "CANDIDATE"


@dataclass(frozen=True, slots=True)
class PromptSpec:
    """One immutable, versioned prompt artifact."""

    prompt_id: str
    version: str
    template: str
    variables: tuple[str, ...]
    output_schema_version: str
    created_at: datetime
    change_note: str = ""
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _require_coordinate(self.prompt_id, "prompt_id")
        _require_coordinate(self.version, "version")
        template = _require_text(self.template, "template", maximum=100_000)
        _require_coordinate(self.output_schema_version, "output_schema_version")
        created_at = _require_aware_utc(self.created_at, "created_at")
        if type(self.variables) is not tuple:
            raise TypeError("variables must be a tuple")
        if len(set(self.variables)) != len(self.variables):
            raise ValueError("variables must not contain duplicates")
        if self.variables != tuple(sorted(self.variables)):
            raise ValueError("variables must be sorted for canonical identity")
        for variable in self.variables:
            if type(variable) is not str or _VARIABLE_PATTERN.fullmatch(variable) is None:
                raise ValueError(f"invalid prompt variable: {variable!r}")
            if "{{" + variable + "}}" not in template:
                raise ValueError(f"template is missing variable placeholder: {variable}")
        if type(self.change_note) is not str:
            raise TypeError("change_note must be a string")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(
            self,
            "fingerprint",
            _canonical_fingerprint(
                {
                    "changeNote": self.change_note,
                    "createdAt": _timestamp(created_at),
                    "outputSchemaVersion": self.output_schema_version,
                    "promptId": self.prompt_id,
                    "template": template,
                    "variables": list(self.variables),
                    "version": self.version,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Reproducible model configuration containing references, never secrets."""

    provider_id: str
    model_id: str
    version: str
    api_variant: str
    credential_env_ref: str
    temperature_milli: int
    max_output_tokens: int
    created_at: datetime
    seed: int | None = None
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _require_coordinate(self.provider_id, "provider_id")
        _require_coordinate(self.model_id, "model_id")
        _require_coordinate(self.version, "version")
        _require_coordinate(self.api_variant, "api_variant")
        credential_ref = _require_text(
            self.credential_env_ref,
            "credential_env_ref",
            maximum=128,
        )
        if _ENVIRONMENT_REFERENCE_PATTERN.fullmatch(credential_ref) is None:
            raise ValueError(
                "credential_env_ref must be an environment-variable name, never a credential value"
            )
        temperature = _require_strict_integer(self.temperature_milli, "temperature_milli")
        if not 0 <= temperature <= 2_000:
            raise ValueError("temperature_milli must be between 0 and 2000")
        max_tokens = _require_strict_integer(self.max_output_tokens, "max_output_tokens")
        if not 1 <= max_tokens <= 1_000_000:
            raise ValueError("max_output_tokens must be between 1 and 1000000")
        if self.seed is not None:
            seed = _require_strict_integer(self.seed, "seed")
            if not 0 <= seed <= 2**63 - 1:
                raise ValueError("seed must be between 0 and 2^63-1")
        created_at = _require_aware_utc(self.created_at, "created_at")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(
            self,
            "fingerprint",
            _canonical_fingerprint(
                {
                    "apiVariant": self.api_variant,
                    "createdAt": _timestamp(created_at),
                    "credentialEnvRef": credential_ref,
                    "maxOutputTokens": max_tokens,
                    "modelId": self.model_id,
                    "providerId": self.provider_id,
                    "seed": self.seed,
                    "temperatureMilli": temperature,
                    "version": self.version,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ExtractionProfile:
    """Versioned binding between a prompt, model, and output contract."""

    profile_id: str
    version: str
    prompt_id: str
    prompt_version: str
    model_provider_id: str
    model_id: str
    model_version: str
    output_schema_version: str
    minimum_confidence_bps: int
    created_at: datetime
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.profile_id, "profile_id"),
            (self.version, "version"),
            (self.prompt_id, "prompt_id"),
            (self.prompt_version, "prompt_version"),
            (self.model_provider_id, "model_provider_id"),
            (self.model_id, "model_id"),
            (self.model_version, "model_version"),
            (self.output_schema_version, "output_schema_version"),
        ):
            _require_coordinate(value, field_name)
        confidence = _require_basis_points(
            self.minimum_confidence_bps,
            "minimum_confidence_bps",
        )
        created_at = _require_aware_utc(self.created_at, "created_at")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(
            self,
            "fingerprint",
            _canonical_fingerprint(
                {
                    "createdAt": _timestamp(created_at),
                    "minimumConfidenceBps": confidence,
                    "modelId": self.model_id,
                    "modelProviderId": self.model_provider_id,
                    "modelVersion": self.model_version,
                    "outputSchemaVersion": self.output_schema_version,
                    "profileId": self.profile_id,
                    "promptId": self.prompt_id,
                    "promptVersion": self.prompt_version,
                    "version": self.version,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class Deployment:
    """One append-only profile release or rollback event."""

    deployment_id: str
    profile_id: str
    primary_profile_version: str
    candidate_profile_version: str | None
    candidate_allocation_bps: int
    operation: DeploymentOperation
    effective_at: datetime
    created_at: datetime
    expected_previous_deployment_id: str | None = None
    rollback_of_deployment_id: str | None = None
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _require_coordinate(self.deployment_id, "deployment_id")
        _require_coordinate(self.profile_id, "profile_id")
        _require_coordinate(self.primary_profile_version, "primary_profile_version")
        if self.candidate_profile_version is not None:
            _require_coordinate(self.candidate_profile_version, "candidate_profile_version")
            if self.candidate_profile_version == self.primary_profile_version:
                raise ValueError("candidate profile version must differ from primary")
        allocation = _require_basis_points(
            self.candidate_allocation_bps,
            "candidate_allocation_bps",
        )
        if self.candidate_profile_version is None and allocation != 0:
            raise ValueError("candidate allocation must be zero without a candidate")
        if self.candidate_profile_version is not None and allocation == 0:
            raise ValueError("candidate allocation must be positive with a candidate")
        if type(self.operation) is not DeploymentOperation:
            raise TypeError("operation must be a DeploymentOperation")
        if self.expected_previous_deployment_id is not None:
            _require_coordinate(
                self.expected_previous_deployment_id,
                "expected_previous_deployment_id",
            )
        if self.rollback_of_deployment_id is not None:
            _require_coordinate(
                self.rollback_of_deployment_id,
                "rollback_of_deployment_id",
            )
        if self.operation is DeploymentOperation.RELEASE:
            if self.rollback_of_deployment_id is not None:
                raise ValueError("release must not set rollback_of_deployment_id")
        else:
            if self.candidate_profile_version is not None or allocation != 0:
                raise ValueError("rollback must select exactly one primary version")
            if self.rollback_of_deployment_id is None:
                raise ValueError("rollback must identify the deployment being rolled back")
            if self.rollback_of_deployment_id != self.expected_previous_deployment_id:
                raise ValueError("rollback target must equal expected previous deployment")
        effective_at = _require_aware_utc(self.effective_at, "effective_at")
        created_at = _require_aware_utc(self.created_at, "created_at")
        if created_at > effective_at:
            raise ValueError("created_at must be <= effective_at")
        object.__setattr__(self, "effective_at", effective_at)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(
            self,
            "fingerprint",
            _canonical_fingerprint(
                {
                    "candidateAllocationBps": allocation,
                    "candidateProfileVersion": self.candidate_profile_version,
                    "createdAt": _timestamp(created_at),
                    "deploymentId": self.deployment_id,
                    "effectiveAt": _timestamp(effective_at),
                    "expectedPreviousDeploymentId": self.expected_previous_deployment_id,
                    "operation": self.operation.value,
                    "primaryProfileVersion": self.primary_profile_version,
                    "profileId": self.profile_id,
                    "rollbackOfDeploymentId": self.rollback_of_deployment_id,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ResolvedProfile:
    """Exact configuration selected for one decision and routing key."""

    profile: ExtractionProfile
    prompt: PromptSpec
    model: ModelSpec
    deployment: Deployment
    selected_variant: SelectedVariant
    routing_bucket: int | None
    decision_time: datetime
    configuration_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.profile) is not ExtractionProfile:
            raise TypeError("profile must be an ExtractionProfile")
        if type(self.prompt) is not PromptSpec:
            raise TypeError("prompt must be a PromptSpec")
        if type(self.model) is not ModelSpec:
            raise TypeError("model must be a ModelSpec")
        if type(self.deployment) is not Deployment:
            raise TypeError("deployment must be a Deployment")
        if type(self.selected_variant) is not SelectedVariant:
            raise TypeError("selected_variant must be a SelectedVariant")
        if self.routing_bucket is not None:
            bucket = _require_strict_integer(self.routing_bucket, "routing_bucket")
            if not 0 <= bucket < 10_000:
                raise ValueError("routing_bucket must be between 0 and 9999")
        decision_time = _require_aware_utc(self.decision_time, "decision_time")
        object.__setattr__(self, "decision_time", decision_time)
        object.__setattr__(
            self,
            "configuration_fingerprint",
            _canonical_fingerprint(
                {
                    "decisionTime": _timestamp(decision_time),
                    "deploymentFingerprint": self.deployment.fingerprint,
                    "modelFingerprint": self.model.fingerprint,
                    "profileFingerprint": self.profile.fingerprint,
                    "promptFingerprint": self.prompt.fingerprint,
                    "routingBucket": self.routing_bucket,
                    "selectedVariant": self.selected_variant.value,
                }
            ),
        )


__all__ = [
    "Deployment",
    "DeploymentOperation",
    "ExtractionProfile",
    "ModelSpec",
    "PromptSpec",
    "ResolvedProfile",
    "SelectedVariant",
]
