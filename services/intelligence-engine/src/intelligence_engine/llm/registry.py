"""Append-only, point-in-time prompt and model configuration registry."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from intelligence_engine.llm.models import (
    Deployment,
    DeploymentOperation,
    ExtractionProfile,
    ModelSpec,
    PromptSpec,
    ResolvedProfile,
    SelectedVariant,
)


class RegistryError(ValueError):
    """Base registry consistency error."""


class DuplicateVersionError(RegistryError):
    """An immutable coordinate already exists."""


class MissingReferenceError(RegistryError):
    """A profile or deployment references an unregistered artifact."""


class DeploymentConflictError(RegistryError):
    """A deployment failed append-order or compare-and-set validation."""


class NoActiveDeploymentError(RegistryError):
    """No deployment was effective at the requested decision time."""


def _aware_utc(value: object, field_name: str) -> datetime:
    if type(value) is not datetime:
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _routing_bucket(profile_id: str, deployment_id: str, routing_key: str) -> int:
    identity = f"{profile_id}\x1f{deployment_id}\x1f{routing_key}".encode()
    return int.from_bytes(hashlib.sha256(identity).digest()[:8], "big") % 10_000


def _registry_fingerprint(
    prompts: tuple[PromptSpec, ...],
    models: tuple[ModelSpec, ...],
    profiles: tuple[ExtractionProfile, ...],
    deployments: tuple[Deployment, ...],
) -> str:
    payload = {
        "deployments": sorted(item.fingerprint for item in deployments),
        "models": sorted(item.fingerprint for item in models),
        "profiles": sorted(item.fingerprint for item in profiles),
        "prompts": sorted(item.fingerprint for item in prompts),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class VersionRegistry:
    """Immutable registry; every write returns a separately validated snapshot."""

    prompts: tuple[PromptSpec, ...] = ()
    models: tuple[ModelSpec, ...] = ()
    profiles: tuple[ExtractionProfile, ...] = ()
    deployments: tuple[Deployment, ...] = ()
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        for values, expected_type, field_name in (
            (self.prompts, PromptSpec, "prompts"),
            (self.models, ModelSpec, "models"),
            (self.profiles, ExtractionProfile, "profiles"),
            (self.deployments, Deployment, "deployments"),
        ):
            if type(values) is not tuple:
                raise TypeError(f"{field_name} must be a tuple")
            if any(type(item) is not expected_type for item in values):
                raise TypeError(f"{field_name} contains an invalid record type")

        prompt_by_key: dict[tuple[str, str], PromptSpec] = {}
        for prompt in self.prompts:
            key = (prompt.prompt_id, prompt.version)
            if key in prompt_by_key:
                raise DuplicateVersionError(f"duplicate prompt coordinate: {key!r}")
            prompt_by_key[key] = prompt

        model_by_key: dict[tuple[str, str, str], ModelSpec] = {}
        for model in self.models:
            key = (model.provider_id, model.model_id, model.version)
            if key in model_by_key:
                raise DuplicateVersionError(f"duplicate model coordinate: {key!r}")
            model_by_key[key] = model

        profile_by_key: dict[tuple[str, str], ExtractionProfile] = {}
        for profile in self.profiles:
            key = (profile.profile_id, profile.version)
            if key in profile_by_key:
                raise DuplicateVersionError(f"duplicate profile coordinate: {key!r}")
            prompt = prompt_by_key.get((profile.prompt_id, profile.prompt_version))
            if prompt is None:
                raise MissingReferenceError("profile references an unregistered prompt version")
            model = model_by_key.get(
                (profile.model_provider_id, profile.model_id, profile.model_version)
            )
            if model is None:
                raise MissingReferenceError("profile references an unregistered model version")
            if prompt.output_schema_version != profile.output_schema_version:
                raise MissingReferenceError("profile and prompt output schema versions differ")
            if profile.created_at < max(prompt.created_at, model.created_at):
                raise MissingReferenceError("profile cannot predate its prompt or model")
            profile_by_key[key] = profile

        deployment_ids: set[str] = set()
        last_by_profile: dict[str, Deployment] = {}
        for deployment in self.deployments:
            if deployment.deployment_id in deployment_ids:
                raise DuplicateVersionError(
                    f"duplicate deployment id: {deployment.deployment_id!r}"
                )
            deployment_ids.add(deployment.deployment_id)
            primary = profile_by_key.get(
                (deployment.profile_id, deployment.primary_profile_version)
            )
            if primary is None:
                raise MissingReferenceError("deployment references an unregistered primary profile")
            referenced_profiles = [primary]
            if deployment.candidate_profile_version is not None:
                candidate = profile_by_key.get(
                    (deployment.profile_id, deployment.candidate_profile_version)
                )
                if candidate is None:
                    raise MissingReferenceError(
                        "deployment references an unregistered candidate profile"
                    )
                referenced_profiles.append(candidate)
            if any(
                deployment.created_at < profile.created_at
                or deployment.effective_at < profile.created_at
                for profile in referenced_profiles
            ):
                raise MissingReferenceError("deployment cannot predate a referenced profile")

            previous = last_by_profile.get(deployment.profile_id)
            if previous is None:
                if deployment.expected_previous_deployment_id is not None:
                    raise DeploymentConflictError(
                        "initial deployment must not expect a previous deployment"
                    )
                if deployment.operation is DeploymentOperation.ROLLBACK:
                    raise DeploymentConflictError("initial deployment cannot be a rollback")
            else:
                if deployment.effective_at <= previous.effective_at:
                    raise DeploymentConflictError(
                        "deployment effective times must increase per profile"
                    )
                if deployment.expected_previous_deployment_id != previous.deployment_id:
                    raise DeploymentConflictError(
                        "expected previous deployment does not match the append head"
                    )
                if (
                    deployment.operation is DeploymentOperation.ROLLBACK
                    and deployment.rollback_of_deployment_id != previous.deployment_id
                ):
                    raise DeploymentConflictError("rollback must target the append head")
            last_by_profile[deployment.profile_id] = deployment

        object.__setattr__(
            self,
            "fingerprint",
            _registry_fingerprint(
                self.prompts,
                self.models,
                self.profiles,
                self.deployments,
            ),
        )

    def register_prompt(self, prompt: PromptSpec) -> VersionRegistry:
        """Append a prompt version; coordinates can never be overwritten."""
        return replace(self, prompts=(*self.prompts, prompt))

    def register_model(self, model: ModelSpec) -> VersionRegistry:
        """Append a model version; coordinates can never be overwritten."""
        return replace(self, models=(*self.models, model))

    def register_profile(self, profile: ExtractionProfile) -> VersionRegistry:
        """Append a fully referenced extraction profile."""
        return replace(self, profiles=(*self.profiles, profile))

    def register_deployment(self, deployment: Deployment) -> VersionRegistry:
        """Append a release or rollback after full reference and CAS validation."""
        return replace(self, deployments=(*self.deployments, deployment))

    def latest_configured_deployment(self, profile_id: str) -> Deployment:
        """Return the append head, including future scheduled deployments."""
        matches = [item for item in self.deployments if item.profile_id == profile_id]
        if not matches:
            raise NoActiveDeploymentError(f"profile has no deployment: {profile_id!r}")
        return matches[-1]

    def rollback(
        self,
        *,
        deployment_id: str,
        profile_id: str,
        target_profile_version: str,
        effective_at: datetime,
        created_at: datetime,
        expected_current_deployment_id: str,
    ) -> VersionRegistry:
        """Append a guarded rollback without mutating historical releases."""
        current = self.latest_configured_deployment(profile_id)
        if current.deployment_id != expected_current_deployment_id:
            raise DeploymentConflictError(
                "expected current deployment does not match the append head"
            )
        return self.register_deployment(
            Deployment(
                deployment_id=deployment_id,
                profile_id=profile_id,
                primary_profile_version=target_profile_version,
                candidate_profile_version=None,
                candidate_allocation_bps=0,
                operation=DeploymentOperation.ROLLBACK,
                effective_at=effective_at,
                created_at=created_at,
                expected_previous_deployment_id=current.deployment_id,
                rollback_of_deployment_id=current.deployment_id,
            )
        )

    def resolve(
        self,
        profile_id: str,
        *,
        routing_key: str,
        decision_time: datetime,
    ) -> ResolvedProfile:
        """Resolve only configuration available at the supplied decision time."""
        if type(profile_id) is not str or not profile_id:
            raise TypeError("profile_id must be a non-empty string")
        if type(routing_key) is not str or not routing_key:
            raise TypeError("routing_key must be a non-empty string")
        moment = _aware_utc(decision_time, "decision_time")
        eligible = [
            item
            for item in self.deployments
            if item.profile_id == profile_id and item.effective_at <= moment
        ]
        if not eligible:
            raise NoActiveDeploymentError(
                f"profile has no deployment at decision time: {profile_id!r}"
            )
        deployment = eligible[-1]
        selected_version = deployment.primary_profile_version
        selected_variant = SelectedVariant.PRIMARY
        routing_bucket: int | None = None
        if deployment.candidate_profile_version is not None:
            routing_bucket = _routing_bucket(profile_id, deployment.deployment_id, routing_key)
            if routing_bucket < deployment.candidate_allocation_bps:
                selected_version = deployment.candidate_profile_version
                selected_variant = SelectedVariant.CANDIDATE

        profile = self._profile(profile_id, selected_version)
        prompt = self._prompt(profile.prompt_id, profile.prompt_version)
        model = self._model(
            profile.model_provider_id,
            profile.model_id,
            profile.model_version,
        )
        return ResolvedProfile(
            profile=profile,
            prompt=prompt,
            model=model,
            deployment=deployment,
            selected_variant=selected_variant,
            routing_bucket=routing_bucket,
            decision_time=moment,
        )

    def _prompt(self, prompt_id: str, version: str) -> PromptSpec:
        for prompt in self.prompts:
            if (prompt.prompt_id, prompt.version) == (prompt_id, version):
                return prompt
        raise MissingReferenceError("registered profile lost its prompt reference")

    def _model(self, provider_id: str, model_id: str, version: str) -> ModelSpec:
        for model in self.models:
            if (model.provider_id, model.model_id, model.version) == (
                provider_id,
                model_id,
                version,
            ):
                return model
        raise MissingReferenceError("registered profile lost its model reference")

    def _profile(self, profile_id: str, version: str) -> ExtractionProfile:
        for profile in self.profiles:
            if (profile.profile_id, profile.version) == (profile_id, version):
                return profile
        raise MissingReferenceError("deployment lost its profile reference")


__all__ = [
    "DeploymentConflictError",
    "DuplicateVersionError",
    "MissingReferenceError",
    "NoActiveDeploymentError",
    "RegistryError",
    "VersionRegistry",
]
