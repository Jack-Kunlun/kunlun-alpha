"""Prompt/model version registry acceptance tests (P3-N06)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest
from intelligence_engine.llm import (
    Deployment,
    DeploymentConflictError,
    DeploymentOperation,
    DuplicateVersionError,
    ExtractionProfile,
    MissingReferenceError,
    ModelSpec,
    NoActiveDeploymentError,
    PromptSpec,
    SelectedVariant,
    VersionRegistry,
)

CREATED = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)


def moment(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 24, hour, minute, tzinfo=UTC)


def prompt(
    *,
    version: str = "v1",
    template: str = "Extract market facts from {{content}} as strict JSON.",
    output_schema_version: str = "market-event-v1",
) -> PromptSpec:
    return PromptSpec(
        prompt_id="event-extraction",
        version=version,
        template=template,
        variables=("content",),
        output_schema_version=output_schema_version,
        created_at=CREATED,
        change_note="initial evidence-bound extraction prompt",
    )


def model(*, version: str = "2026-08-01") -> ModelSpec:
    return ModelSpec(
        provider_id="provider-a",
        model_id="event-extractor",
        version=version,
        api_variant="structured-output",
        credential_env_ref="KUNLUN_LLM_API_KEY",
        temperature_milli=0,
        max_output_tokens=4096,
        seed=7,
        created_at=CREATED,
    )


def profile(
    *,
    version: str = "v1",
    output_schema_version: str = "market-event-v1",
) -> ExtractionProfile:
    return ExtractionProfile(
        profile_id="market-event-extraction",
        version=version,
        prompt_id="event-extraction",
        prompt_version="v1",
        model_provider_id="provider-a",
        model_id="event-extractor",
        model_version="2026-08-01",
        output_schema_version=output_schema_version,
        minimum_confidence_bps=7000,
        created_at=CREATED,
    )


def registry_with_profiles() -> VersionRegistry:
    return (
        VersionRegistry()
        .register_prompt(prompt())
        .register_model(model())
        .register_profile(profile(version="v1"))
        .register_profile(profile(version="v2"))
    )


def release(
    *,
    deployment_id: str = "release-1",
    primary: str = "v1",
    candidate: str | None = None,
    allocation_bps: int = 0,
    effective_at: datetime | None = None,
    expected_previous: str | None = None,
) -> Deployment:
    effective = moment(4) if effective_at is None else effective_at
    return Deployment(
        deployment_id=deployment_id,
        profile_id="market-event-extraction",
        primary_profile_version=primary,
        candidate_profile_version=candidate,
        candidate_allocation_bps=allocation_bps,
        operation=DeploymentOperation.RELEASE,
        effective_at=effective,
        created_at=effective,
        expected_previous_deployment_id=expected_previous,
    )


def test_artifacts_are_immutable_and_content_addressed() -> None:
    artifact = prompt()
    assert len(artifact.fingerprint) == 64
    assert artifact.fingerprint == prompt().fingerprint
    assert artifact.fingerprint != prompt(template="Changed {{content}}").fingerprint
    with pytest.raises(dataclasses.FrozenInstanceError):
        artifact.template = "tampered"  # type: ignore[misc]


def test_strict_types_time_and_credential_reference_are_enforced() -> None:
    with pytest.raises(TypeError, match="strict integer"):
        dataclasses.replace(model(), temperature_milli=True)
    with pytest.raises(ValueError, match="environment-variable"):
        dataclasses.replace(model(), credential_env_ref="sk-live-secret-value")
    with pytest.raises(ValueError, match="timezone-aware"):
        dataclasses.replace(prompt(), created_at=datetime(2026, 8, 24, 1, 0))


def test_prompt_variables_must_be_declared_in_template() -> None:
    with pytest.raises(ValueError, match="placeholder"):
        dataclasses.replace(prompt(), template="No source placeholder")


def test_immutable_coordinates_cannot_be_overwritten() -> None:
    registry = VersionRegistry().register_prompt(prompt())
    with pytest.raises(DuplicateVersionError, match="duplicate prompt"):
        registry.register_prompt(prompt(template="Different {{content}}"))


def test_profile_requires_registered_matching_artifacts() -> None:
    with pytest.raises(MissingReferenceError, match="prompt"):
        VersionRegistry().register_profile(profile())

    registry = VersionRegistry().register_prompt(prompt()).register_model(model())
    with pytest.raises(MissingReferenceError, match="schema"):
        registry.register_profile(profile(output_schema_version="market-event-v2"))


def test_deployment_is_invisible_before_effective_time() -> None:
    registry = registry_with_profiles().register_deployment(release())
    with pytest.raises(NoActiveDeploymentError, match="decision time"):
        registry.resolve(
            "market-event-extraction",
            routing_key="raw-version-1",
            decision_time=moment(3, 59),
        )
    resolved = registry.resolve(
        "market-event-extraction",
        routing_key="raw-version-1",
        decision_time=moment(4),
    )
    assert resolved.profile.version == "v1"
    assert resolved.decision_time == moment(4)


def test_gray_routing_is_stable_and_matches_integer_bucket() -> None:
    registry = registry_with_profiles().register_deployment(
        release(candidate="v2", allocation_bps=5000)
    )
    first = registry.resolve(
        "market-event-extraction",
        routing_key="raw-version-42",
        decision_time=moment(4),
    )
    second = registry.resolve(
        "market-event-extraction",
        routing_key="raw-version-42",
        decision_time=moment(4),
    )
    assert first == second
    assert first.routing_bucket is not None
    expected = SelectedVariant.CANDIDATE if first.routing_bucket < 5000 else SelectedVariant.PRIMARY
    assert first.selected_variant is expected
    assert first.profile.version == ("v2" if expected is SelectedVariant.CANDIDATE else "v1")


def test_append_guard_rejects_stale_or_backdated_deployments() -> None:
    registry = registry_with_profiles().register_deployment(release())
    with pytest.raises(DeploymentConflictError, match="append head"):
        registry.register_deployment(
            release(
                deployment_id="release-2",
                effective_at=moment(5),
                expected_previous="stale-release",
            )
        )
    with pytest.raises(DeploymentConflictError, match="effective times"):
        registry.register_deployment(
            release(
                deployment_id="release-2",
                effective_at=moment(3),
                expected_previous="release-1",
            )
        )


def test_rollback_is_append_only_and_preserves_historical_resolution() -> None:
    released = registry_with_profiles().register_deployment(
        release(candidate="v2", allocation_bps=10_000)
    )
    rolled_back = released.rollback(
        deployment_id="rollback-1",
        profile_id="market-event-extraction",
        target_profile_version="v1",
        effective_at=moment(5),
        created_at=moment(4, 30),
        expected_current_deployment_id="release-1",
    )
    historical = rolled_back.resolve(
        "market-event-extraction",
        routing_key="raw-version-1",
        decision_time=moment(4, 59),
    )
    current = rolled_back.resolve(
        "market-event-extraction",
        routing_key="raw-version-1",
        decision_time=moment(5),
    )
    assert len(released.deployments) == 1
    assert len(rolled_back.deployments) == 2
    assert historical.profile.version == "v2"
    assert current.profile.version == "v1"
    assert current.deployment.operation is DeploymentOperation.ROLLBACK
    assert current.deployment.rollback_of_deployment_id == "release-1"


def test_rollback_requires_expected_current_deployment() -> None:
    registry = registry_with_profiles().register_deployment(release())
    with pytest.raises(DeploymentConflictError, match="append head"):
        registry.rollback(
            deployment_id="rollback-1",
            profile_id="market-event-extraction",
            target_profile_version="v1",
            effective_at=moment(5),
            created_at=moment(4, 30),
            expected_current_deployment_id="stale-release",
        )


def test_resolution_exposes_exact_reproducibility_provenance() -> None:
    registry = registry_with_profiles().register_deployment(release())
    resolved = registry.resolve(
        "market-event-extraction",
        routing_key="raw-version-1",
        decision_time=moment(4),
    )
    assert resolved.prompt.version == "v1"
    assert resolved.model.version == "2026-08-01"
    assert resolved.profile.output_schema_version == "market-event-v1"
    assert resolved.deployment.deployment_id == "release-1"
    assert len(resolved.prompt.fingerprint) == 64
    assert len(resolved.model.fingerprint) == 64
    assert len(resolved.profile.fingerprint) == 64
    assert len(resolved.configuration_fingerprint) == 64
