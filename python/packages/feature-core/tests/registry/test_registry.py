from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from feature_core.registry import (
    AvailabilityPolicy,
    DuplicateFeatureNameError,
    FeatureDependency,
    FeatureDependencyCycleError,
    FeatureEntity,
    FeatureFrequency,
    FeatureRegistry,
    FeatureRemovalError,
    FeatureSpec,
    FeatureSpecValidationError,
    FeatureValueType,
    FeatureVersionConflictError,
    MissingFeatureDependencyError,
    RegistryLineageConflictError,
    SemanticVersionRequiredError,
    SourceContract,
)


def _spec(
    name: str,
    *,
    version: str = "v1",
    owner: str = "quant-research",
    description: str | None = None,
    dependencies: tuple[FeatureDependency, ...] = (),
    source_contracts: tuple[SourceContract, ...] = (
        SourceContract(name="market.daily_bar", version="v1"),
    ),
) -> FeatureSpec:
    return FeatureSpec(
        name=name,
        version=version,
        entity=FeatureEntity.INSTRUMENT,
        frequency=FeatureFrequency.DAILY,
        value_type=FeatureValueType.DECIMAL,
        owner=owner,
        description=description or f"Point-in-time definition for {name}",
        algorithm_version="v1",
        calculation_definition=f"deterministic calculation for {name}",
        window_definition="POINT_IN_TIME",
        filter_policy_version="v1",
        pit_policy_version="v1",
        event_time_field="trade_date",
        available_time_field="available_time",
        availability_policy=AvailabilityPolicy.MAX_INPUT_AVAILABLE_TIME,
        dependencies=dependencies,
        source_contracts=source_contracts,
    )


def _registry(*specs: FeatureSpec) -> FeatureRegistry:
    registry = FeatureRegistry.empty(namespace_id="kunlun.alpha.features")
    return registry.evolve(
        specs,
        expected_parent_fingerprint=registry.head_fingerprint,
    )


def _evolve(registry: FeatureRegistry, *specs: FeatureSpec) -> FeatureRegistry:
    return registry.evolve(
        specs,
        expected_parent_fingerprint=registry.head_fingerprint,
    )


def test_registry_builds_dependency_graph_in_dependency_first_order() -> None:
    raw = _spec("market.raw_close")
    return_5d = _spec(
        "market.return_5d",
        dependencies=(FeatureDependency(name=raw.name, version=raw.version),),
    )
    signal = _spec(
        "strategy.momentum_signal",
        dependencies=(FeatureDependency(name=return_5d.name, version=return_5d.version),),
    )

    registry = _registry(signal, raw, return_5d)

    assert registry.dependency_graph == {
        "market.raw_close": (),
        "market.return_5d": ("market.raw_close",),
        "strategy.momentum_signal": ("market.return_5d",),
    }
    assert registry.dependency_order() == (
        "market.raw_close",
        "market.return_5d",
        "strategy.momentum_signal",
    )
    assert registry.get("market.return_5d") is return_5d
    assert raw.to_contract()["semanticFingerprint"] == raw.semantic_fingerprint


def test_registry_rejects_duplicate_feature_names() -> None:
    first = _spec("market.raw_close")
    with pytest.raises(DuplicateFeatureNameError, match="market.raw_close"):
        _registry(first, first)


def test_feature_spec_requires_an_owner() -> None:
    with pytest.raises(FeatureSpecValidationError, match="owner"):
        _spec("market.raw_close", owner="  ")


def test_registry_rejects_dependency_cycles() -> None:
    first = _spec(
        "cycle.first",
        dependencies=(FeatureDependency(name="cycle.second", version="v1"),),
    )
    second = _spec(
        "cycle.second",
        dependencies=(FeatureDependency(name="cycle.first", version="v1"),),
    )

    with pytest.raises(FeatureDependencyCycleError, match="cycle.first.*cycle.second"):
        _registry(first, second)


def test_registry_rejects_missing_and_version_conflicting_dependencies() -> None:
    missing = _spec(
        "strategy.missing_input",
        dependencies=(FeatureDependency(name="market.unknown", version="v1"),),
    )
    with pytest.raises(MissingFeatureDependencyError, match="market.unknown"):
        _registry(missing)

    raw = _spec("market.raw_close", version="v1")
    mismatch = _spec(
        "strategy.version_mismatch",
        dependencies=(FeatureDependency(name=raw.name, version="v2"),),
    )
    with pytest.raises(FeatureVersionConflictError, match="expected v2.*registered v1"):
        _registry(raw, mismatch)


def test_semantic_change_requires_a_strict_version_increase() -> None:
    previous = _spec("market.raw_close", description="Unadjusted daily close")
    changed_without_bump = replace(previous, description="Forward-adjusted daily close")
    registry = _registry(previous)

    with pytest.raises(SemanticVersionRequiredError, match="market.raw_close"):
        _evolve(registry, changed_without_bump)

    changed_with_bump = replace(changed_without_bump, version="v2")
    registry = _evolve(registry, changed_with_bump)
    assert registry.get("market.raw_close").version == "v2"
    assert tuple(item.version for item in registry.lineage("market.raw_close")) == ("v1", "v2")


def test_registry_rejects_version_regression_but_allows_owner_handoff() -> None:
    previous = _spec("market.raw_close", version="v2")
    regressed = replace(previous, version="v1")
    registry = _registry(previous)
    with pytest.raises(FeatureVersionConflictError, match="regressed"):
        _evolve(registry, regressed)

    handed_off = replace(previous, owner="market-data")
    registry = _evolve(registry, handed_off)
    assert registry.get("market.raw_close").owner == "market-data"
    assert tuple(item.owner for item in registry.lineage("market.raw_close")) == (
        "quant-research",
        "market-data",
    )


def test_registry_evolution_is_append_only() -> None:
    registry = _registry(_spec("market.raw_close"))

    with pytest.raises(FeatureRemovalError, match="market.raw_close"):
        _evolve(registry)


def test_registry_evolution_requires_the_trusted_parent_head() -> None:
    spec = _spec("market.raw_close")
    registry = _registry(spec)

    with pytest.raises(RegistryLineageConflictError, match="parent fingerprint"):
        registry.evolve(
            (spec,),
            expected_parent_fingerprint=f"sha256:{'0' * 64}",
        )


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("algorithm_version", "v2"),
        ("calculation_definition", "a different deterministic formula"),
        ("window_definition", "TRADING_SESSIONS:5"),
        ("filter_policy_version", "v2"),
        ("pit_policy_version", "v2"),
        ("source_contracts", (SourceContract(name="market.daily_bar", version="v2"),)),
    ],
)
def test_each_execution_semantic_change_requires_version_bump(
    field_name: str,
    replacement: object,
) -> None:
    previous = _spec("market.raw_close")
    changed = replace(previous, **{field_name: replacement})
    registry = _registry(previous)

    with pytest.raises(SemanticVersionRequiredError, match="market.raw_close"):
        _evolve(registry, changed)


def test_contract_adapter_recomputes_fingerprint_and_matches_shared_vector() -> None:
    fixture_path = (
        Path(__file__).parents[5] / "packages/contracts/fixtures/feature/feature-spec-v1.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    spec = FeatureSpec.from_contract(payload)
    assert spec.semantic_fingerprint == payload["semanticFingerprint"]
    assert spec.to_contract() == payload

    payload["semanticFingerprint"] = f"sha256:{'0' * 64}"
    with pytest.raises(FeatureSpecValidationError, match="semanticFingerprint"):
        FeatureSpec.from_contract(payload)

    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    payload["description"] = f" {payload['description']} "
    with pytest.raises(FeatureSpecValidationError, match="outer whitespace"):
        FeatureSpec.from_contract(payload)


@pytest.mark.parametrize("version", ["", "1", "v0", "v01", "V1", "v1.0"])
def test_feature_spec_rejects_invalid_versions(version: str) -> None:
    with pytest.raises(FeatureSpecValidationError, match="version"):
        _spec("market.raw_close", version=version)
