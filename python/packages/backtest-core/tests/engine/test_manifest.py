from __future__ import annotations

from collections import deque
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from backtest_core.engine.manifest import (
    BACKTEST_ENGINE_VERSION,
    EVENT_ORDERING_VERSION,
    MANIFEST_SCHEMA_VERSION,
    RNG_ALGORITHM,
    BacktestRunManifest,
)
from backtest_core.engine.models import ScheduledDecisionEvent
from quant_core.strategy import (
    STRATEGY_SDK_VERSION,
    FeatureValue,
    ParameterType,
    StrategyContext,
    StrategyDescriptor,
    StrategyInputError,
    StrategyParameters,
    StrategyParameterSpec,
    UniverseSnapshot,
)

START = datetime(2026, 6, 1, 7, tzinfo=UTC)


def _descriptor() -> StrategyDescriptor:
    return StrategyDescriptor(
        strategy_id="momentum.research",
        strategy_version="1.0.0",
        algorithm_version="1.0.0",
        sdk_version=STRATEGY_SDK_VERSION,
        lifecycle_version="1.0.0",
        description="Deterministic test strategy",
        required_features=("momentum.window_20d",),
        parameter_specs=(
            StrategyParameterSpec(
                name="lookback",
                value_type=ParameterType.INTEGER,
                required=True,
                description="Lookback sessions",
                minimum=1,
                maximum=250,
            ),
        ),
    )


PARAMETERS = StrategyParameters(descriptor_version="1.0.0", values=(("lookback", 20),))


def _context(at: datetime, snapshot_id: str = "context:one") -> StrategyContext:
    cutoff = at - timedelta(minutes=1)
    universe = UniverseSnapshot(
        snapshot_id="universe:one",
        snapshot_version="1.0.0",
        as_of_time=cutoff - timedelta(minutes=1),
        available_time=cutoff - timedelta(seconds=2),
        processing_time=cutoff - timedelta(seconds=1),
        entity_ids=("600001.SH",),
    )
    feature = FeatureValue(
        entity_id="600001.SH",
        feature_name="momentum.window_20d",
        feature_version="1.0.0",
        value=Decimal("0.5"),
        event_time=at - timedelta(days=1),
        available_time=cutoff - timedelta(seconds=2),
        processing_time=cutoff - timedelta(seconds=1),
        source_snapshot_id="features:one",
        source_snapshot_version="1.0.0",
    )
    return StrategyContext(
        decision_time=at,
        data_cutoff_time=cutoff,
        snapshot_id=snapshot_id,
        snapshot_version="1.0.0",
        universe=universe,
        features=(feature,),
    )


def _event(
    event_id: str,
    at: datetime,
    sequence: int,
    *,
    source_id: str = "market",
    available_time: datetime | None = None,
    context: StrategyContext | None = None,
) -> ScheduledDecisionEvent:
    return ScheduledDecisionEvent(
        event_id=event_id,
        source_id=source_id,
        source_sequence=sequence,
        logical_time=at,
        available_time=available_time or at - timedelta(minutes=2),
        context=context or _context(at, f"context:{event_id}"),
    )


def _manifest(
    events: object,
    *,
    schema_version: str = MANIFEST_SCHEMA_VERSION,
    engine_version: str = BACKTEST_ENGINE_VERSION,
    event_ordering_version: str = EVENT_ORDERING_VERSION,
    rng_algorithm: str = RNG_ALGORITHM,
    dataset_digest: str = "dataset:external-digest:v1",
) -> BacktestRunManifest:
    return BacktestRunManifest(
        schema_version=schema_version,
        engine_version=engine_version,
        strategy_descriptor=_descriptor(),
        strategy_parameters=PARAMETERS,
        policy_id="test.policy",
        policy_version="1.0.0",
        strategy_implementation_fingerprint="strategy:fingerprint:v1",
        policy_implementation_fingerprint="policy:fingerprint:v1",
        dataset_id="dataset:test",
        dataset_version="1.0.0",
        dataset_digest=dataset_digest,
        code_version="code:v1",
        config_version="config:v1",
        event_ordering_version=event_ordering_version,
        rng_algorithm=rng_algorithm,
        rng_seed="seed:test",
        start_time=START,
        end_time=START + timedelta(hours=1),
        events=events,  # type: ignore[arg-type]
    )


def test_manifest_is_canonical_and_order_independent() -> None:
    first = _event("event-b", START + timedelta(minutes=2), 2)
    second = _event("event-a", START + timedelta(minutes=1), 1)
    left = _manifest((first, second))
    right = _manifest((second, first))

    assert left.events == (second, first)
    assert left.events == right.events
    assert left.manifest_digest == right.manifest_digest
    assert isinstance(left.events, tuple)
    assert len(left.manifest_digest) == 64
    assert left.manifest_digest == left.manifest_digest.lower()
    with pytest.raises(FrozenInstanceError):
        left.engine_version = "2.0.0"  # type: ignore[misc]


def test_manifest_rejects_duplicate_ids_sequences_sort_keys_and_out_of_range_events() -> None:
    event = _event("event-a", START + timedelta(minutes=1), 1)
    with pytest.raises(StrategyInputError, match="event_id"):
        _manifest((event, _event("event-a", START + timedelta(minutes=2), 2)))
    with pytest.raises(StrategyInputError, match="source_sequence"):
        _manifest((event, _event("event-b", START + timedelta(minutes=2), 1)))
    with pytest.raises(StrategyInputError, match="range"):
        _manifest((_event("event-out", START - timedelta(seconds=1), 1),))
    with pytest.raises(StrategyInputError, match="logical_time"):
        _event(
            "event-mismatch",
            START + timedelta(minutes=1),
            1,
            context=_context(START + timedelta(minutes=2)),
        )
    with pytest.raises(StrategyInputError, match="available_time"):
        _event(
            "event-future",
            START + timedelta(minutes=1),
            1,
            available_time=START + timedelta(minutes=1),
        )


def test_manifest_copies_mutable_event_input_and_rejects_naive_times() -> None:
    event = _event("event-a", START + timedelta(minutes=1), 1)
    with pytest.raises(StrategyInputError, match="tuple"):
        _manifest([event])
    with pytest.raises(StrategyInputError, match="tuple"):
        _manifest({"event": event})
    with pytest.raises(StrategyInputError, match="tuple"):
        _manifest(deque((event,)))

    with pytest.raises(StrategyInputError, match="timezone-aware"):
        _manifest((_event("event-naive", START.replace(tzinfo=None), 1),))


def test_manifest_pins_versions_and_rng_algorithm_at_construction() -> None:
    event = _event("event-version", START + timedelta(minutes=1), 1)
    for field_name in ("schema_version", "engine_version", "event_ordering_version"):
        with pytest.raises(StrategyInputError, match="version"):
            _manifest((event,), **{field_name: "9.0.0"})
    with pytest.raises(StrategyInputError, match="rng_algorithm"):
        _manifest((event,), rng_algorithm="unsupported-rng")


def test_decision_event_phase_is_fixed_and_not_caller_controlled() -> None:
    event = _event("event-phase", START + timedelta(minutes=1), 1)
    assert event.phase == 0
    with pytest.raises(ValueError, match="phase"):
        replace(event, phase=1)
    with pytest.raises(TypeError, match="phase"):
        ScheduledDecisionEvent(
            event_id="event-phase-forged",
            source_id="market",
            source_sequence=2,
            logical_time=event.logical_time,
            available_time=event.available_time,
            context=event.context,
            phase=1,  # type: ignore[call-arg]
        )
