from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from feature_core.batch import CalculatorIdentity, RegisteredFeature, canonical_checksum
from feature_core.online import (
    HmacOnlineStateIntegrity,
    InMemoryOnlineStateStore,
    OnlineCalculatorArtifact,
    OnlineCasResult,
    OnlineCasStatus,
    OnlineConflictError,
    OnlineEventDisposition,
    OnlineEventReceipt,
    OnlineEventSource,
    OnlineFeatureEngine,
    OnlineFeatureEvent,
    OnlineFreshness,
    OnlineIntegrityError,
    OnlineProcessDisposition,
    OnlineValidationError,
    OnlineWindowPolicy,
    StaticOnlineCalculatorTrust,
)
from feature_core.registry import (
    AvailabilityPolicy,
    FeatureEntity,
    FeatureFrequency,
    FeatureRegistry,
    FeatureSpec,
    FeatureValueType,
    SourceContract,
)

T0 = datetime(2026, 8, 24, 10, tzinfo=UTC)
TEST_HMAC_KEY = b"p5-n03-test-integrity-key-32-bytes-minimum"


def _feature(
    *,
    contract_name: str = "market.flow_event",
    window_definition: str = "EVENT_TIME_TUMBLING:PT1H",
    availability_policy: AvailabilityPolicy = AvailabilityPolicy.MAX_INPUT_AVAILABLE_TIME,
) -> RegisteredFeature:
    spec = FeatureSpec(
        name="market.online_flow",
        version="v1",
        entity=FeatureEntity.INSTRUMENT,
        frequency=FeatureFrequency.MINUTE,
        value_type=FeatureValueType.DECIMAL,
        owner="quant-research",
        description="Event-time online flow",
        algorithm_version="v1",
        calculation_definition="sum(value)",
        window_definition=window_definition,
        filter_policy_version="v1",
        pit_policy_version="v1",
        event_time_field="event_time",
        available_time_field="available_time",
        availability_policy=availability_policy,
        source_contracts=(SourceContract(name=contract_name, version="v1"),),
    )
    genesis = FeatureRegistry.empty(namespace_id="tests.online")
    registry = genesis.evolve((spec,), expected_parent_fingerprint=genesis.head_fingerprint)
    return RegisteredFeature.from_registry(registry, spec.name)


def _policy(
    *,
    size: timedelta = timedelta(hours=1),
    allowed_lateness: timedelta = timedelta(minutes=30),
    stale_after: timedelta = timedelta(minutes=10),
    ttl: timedelta = timedelta(hours=1),
    replay_horizon: timedelta = timedelta(hours=2),
) -> OnlineWindowPolicy:
    return OnlineWindowPolicy(
        size=size,
        allowed_lateness=allowed_lateness,
        stale_after=stale_after,
        ttl=ttl,
        replay_horizon=replay_horizon,
    )


def _event(
    event_id: str,
    minute: int,
    value: str = "1",
    *,
    source: OnlineEventSource = OnlineEventSource.MARKET,
    contract_name: str = "market.flow_event",
) -> OnlineFeatureEvent:
    event_time = T0 + timedelta(minutes=minute)
    available_time = event_time + timedelta(minutes=1)
    return OnlineFeatureEvent(
        event_id=event_id,
        entity_id="600519.SH",
        source=source,
        contract_name=contract_name,
        contract_version="v1",
        source_revision=f"source-{event_id}",
        event_time=event_time,
        available_time=available_time,
        ingest_time=available_time + timedelta(minutes=1),
        payload={"value": value},
    )


class _SumCalculator:
    identity = CalculatorIdentity(
        algorithm_version="v1",
        implementation_fingerprint=canonical_checksum(
            {"artifact": "tests.online.sum", "build": "v1"},
        ),
    )

    def __call__(
        self,
        _spec: FeatureSpec,
        _window: object,
        events: tuple[OnlineFeatureEvent, ...],
    ) -> str:
        return str(sum(Decimal(str(event.payload["value"])) for event in events))


def _engine(
    store: object | None = None,
    *,
    feature: RegisteredFeature | None = None,
    policy: OnlineWindowPolicy | None = None,
    trusted_calculator: object | None = None,
) -> tuple[OnlineFeatureEngine, InMemoryOnlineStateStore]:
    resolved_feature = feature or _feature()
    resolved_store = store or InMemoryOnlineStateStore()
    calculator = trusted_calculator or _SumCalculator()
    identity = calculator.identity
    return (
        OnlineFeatureEngine(
            store=resolved_store,
            integrity=HmacOnlineStateIntegrity(TEST_HMAC_KEY),
            calculator_trust=StaticOnlineCalculatorTrust(
                {
                    resolved_feature.spec.semantic_fingerprint: OnlineCalculatorArtifact(
                        identity=identity,
                        calculator=calculator,
                    ),
                },
            ),
            policy=policy or _policy(),
        ),
        resolved_store,
    )


def _process(
    engine: OnlineFeatureEngine,
    event: OnlineFeatureEvent,
    *,
    feature: RegisteredFeature | None = None,
    processing_time: datetime | None = None,
):
    return engine.process(
        feature or _feature(),
        event,
        processing_time=processing_time or event.ingest_time,
    )


def test_window_membership_uses_event_time_not_processing_time() -> None:
    engine, _ = _engine(policy=_policy(ttl=timedelta(hours=8), replay_horizon=timedelta(hours=9)))
    event = _event("event-time", 15)
    result = _process(engine, event, processing_time=T0 + timedelta(hours=3))

    assert result.value is not None
    assert result.value.window.start == T0
    assert result.value.window.end == T0 + timedelta(hours=1)
    assert result.state.watermark == event.event_time - timedelta(minutes=30)


def test_out_of_order_event_inside_allowed_lateness_recomputes_window() -> None:
    engine, _ = _engine()
    first = _process(engine, _event("newer", 50, "2"))
    second = _process(
        engine,
        _event("older", 30, "1"),
        processing_time=T0 + timedelta(minutes=53),
    )

    assert first.value is not None
    assert second.disposition is OnlineProcessDisposition.COMMITTED
    assert second.value is not None
    assert second.value.value == "3"
    assert second.value.event_ids == ("older", "newer")
    assert second.state.max_event_time == T0 + timedelta(minutes=50)


def test_processing_time_cannot_move_backward_during_recomputation() -> None:
    engine, _ = _engine()
    _process(engine, _event("newer", 50, "2"))

    with pytest.raises(OnlineIntegrityError, match="cannot move backward"):
        _process(engine, _event("older", 30, "1"))


def test_duplicate_is_idempotent_and_conflicting_duplicate_fails() -> None:
    engine, _ = _engine()
    event = _event("duplicate", 20)
    first = _process(engine, event)
    duplicate = _process(engine, event)

    assert duplicate.disposition is OnlineProcessDisposition.DUPLICATE
    assert duplicate.state.revision == first.state.revision

    conflicting = replace(
        event,
        source_revision="different-revision",
        payload={"value": "99"},
    )
    with pytest.raises(OnlineConflictError, match="different content"):
        _process(engine, conflicting)


def test_event_older_than_watermark_is_rejected_with_audit() -> None:
    engine, _ = _engine()
    accepted = _process(engine, _event("newer", 50, "2"))
    late = _process(
        engine,
        _event("late", 10, "100"),
        processing_time=T0 + timedelta(minutes=53),
    )

    assert late.disposition is OnlineProcessDisposition.REJECTED_LATE
    assert late.rejection is not None
    assert late.rejection.observed_watermark == T0 + timedelta(minutes=20)
    assert late.value == accepted.value
    assert all(event.event_id != "late" for event in late.state.events)


def test_restart_recovers_watermark_receipts_and_window_inputs() -> None:
    store = InMemoryOnlineStateStore()
    first_engine, _ = _engine(store)
    first = _process(first_engine, _event("before-restart", 40, "1"))

    restarted, _ = _engine(store)
    duplicate = _process(restarted, _event("before-restart", 40, "1"))
    after = _process(
        restarted,
        _event("after-restart", 30, "2"),
        processing_time=T0 + timedelta(minutes=43),
    )

    assert duplicate.disposition is OnlineProcessDisposition.DUPLICATE
    assert after.value is not None
    assert after.value.value == "3"
    assert after.state.revision == first.state.revision + 1


def test_ttl_read_has_future_fresh_degraded_and_expired_states() -> None:
    engine, _ = _engine()
    event = _event("ttl", 5)
    result = _process(engine, event)
    assert result.value is not None

    future = engine.read(
        _feature(),
        event.entity_id,
        as_of=event.available_time - timedelta(microseconds=1),
    )
    fresh = engine.read(
        _feature(),
        event.entity_id,
        as_of=event.available_time + timedelta(minutes=5),
    )
    stale = engine.read(
        _feature(),
        event.entity_id,
        as_of=event.available_time + timedelta(minutes=20),
    )
    expired = engine.read(
        _feature(),
        event.entity_id,
        as_of=event.available_time + timedelta(hours=1),
    )

    assert future.freshness is OnlineFreshness.MISSING
    assert fresh.freshness is OnlineFreshness.FRESH
    assert stale.freshness is OnlineFreshness.DEGRADED_STALE
    assert stale.value == result.value
    assert expired.freshness is OnlineFreshness.EXPIRED
    assert expired.value is None


def test_expired_on_arrival_is_rejected_without_calculation() -> None:
    engine, _ = _engine()
    event = _event("expired", 5)
    result = _process(
        engine,
        event,
        processing_time=event.available_time + timedelta(hours=1),
    )

    assert result.disposition is OnlineProcessDisposition.REJECTED_EXPIRED
    assert result.value is None
    assert result.state.events == ()


def test_future_availability_is_rejected_before_state_write() -> None:
    engine, store = _engine()
    event = _event("future", 20)
    with pytest.raises(OnlineValidationError, match="not available"):
        _process(
            engine,
            event,
            processing_time=event.available_time - timedelta(seconds=1),
        )
    assert store.envelopes == ()


def test_nondeterministic_calculator_fails_before_state_write() -> None:
    class CounterCalculator:
        identity = _SumCalculator.identity

        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, _spec: object, _window: object, _events: object) -> str:
            self.calls += 1
            return str(self.calls)

    calculator = CounterCalculator()
    engine, store = _engine(trusted_calculator=calculator)
    with pytest.raises(OnlineIntegrityError, match="non-deterministic"):
        _process(engine, _event("nondeterministic", 20))
    assert store.envelopes == ()


def test_cas_must_be_durable_and_read_back() -> None:
    class PhantomStore:
        def load(self, _stream_key: str):
            return None

        def compare_and_set(
            self,
            *,
            expected_revision: int | None,
            candidate,
        ):
            assert expected_revision is None
            return OnlineCasResult(OnlineCasStatus.CREATED, candidate)

    engine, _ = _engine(PhantomStore())
    with pytest.raises(OnlineIntegrityError, match="envelope"):
        _process(engine, _event("phantom", 20))


def test_parallel_events_retry_cas_without_losing_window_input() -> None:
    store = InMemoryOnlineStateStore()
    engine, _ = _engine(store)
    events = (_event("parallel-a", 20, "1"), _event("parallel-b", 21, "2"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(
            pool.map(
                lambda event: _process(
                    engine,
                    event,
                    processing_time=T0 + timedelta(minutes=23),
                ),
                events,
            ),
        )

    assert all(result.disposition is OnlineProcessDisposition.COMMITTED for result in results)
    latest = engine.read(_feature(), "600519.SH", as_of=T0 + timedelta(minutes=25))
    assert latest.value is not None
    assert latest.value.value == "3"


def test_feature_spec_window_definition_must_match_online_policy() -> None:
    feature = _feature(window_definition="EVENT_TIME_TUMBLING:P1D")
    engine, _ = _engine(feature=feature)

    with pytest.raises(OnlineValidationError, match="does not match"):
        _process(engine, _event("wrong-window", 20), feature=feature)


def test_availability_policies_are_enforced() -> None:
    materialized = _feature(
        availability_policy=AvailabilityPolicy.MATERIALIZATION_TIME,
    )
    materialized_engine, _ = _engine(feature=materialized)
    event = _event("materialized", 20)
    processing_time = event.ingest_time + timedelta(minutes=5)
    result = _process(
        materialized_engine,
        event,
        feature=materialized,
        processing_time=processing_time,
    )
    assert result.value is not None
    assert result.value.available_time == processing_time

    source = _feature(
        availability_policy=AvailabilityPolicy.SOURCE_AVAILABLE_TIME,
    )
    source_engine, _ = _engine(feature=source)
    _process(source_engine, _event("source-one", 20), feature=source)
    with pytest.raises(OnlineIntegrityError, match="exactly one"):
        _process(
            source_engine,
            _event("source-two", 21),
            feature=source,
            processing_time=T0 + timedelta(minutes=23),
        )


def test_calculator_behavior_drift_under_same_artifact_is_rejected() -> None:
    class MutableCalculator(_SumCalculator):
        def __init__(self) -> None:
            self.override: str | None = None

        def __call__(
            self,
            spec: FeatureSpec,
            window: object,
            events: tuple[OnlineFeatureEvent, ...],
        ) -> str:
            if self.override is not None:
                return self.override
            return super().__call__(spec, window, events)

    calculator = MutableCalculator()
    engine, _ = _engine(trusted_calculator=calculator)
    _process(engine, _event("artifact-before", 20))
    calculator.override = "999"

    with pytest.raises(OnlineIntegrityError, match="trusted calculator output"):
        _process(
            engine,
            _event("artifact-after", 21),
            processing_time=T0 + timedelta(minutes=23),
        )


def test_hmac_detects_tampered_online_value() -> None:
    engine, store = _engine()
    result = _process(engine, _event("tamper", 20))
    envelope = store.envelopes[0]
    assert result.value is not None
    changed_value = replace(result.value, value="999")
    tampered = replace(
        envelope,
        state=replace(envelope.state, values=(changed_value,)),
    )

    class TamperedStore:
        def load(self, _stream_key: str):
            return tampered

    tampered_engine, _ = _engine(TamperedStore())
    with pytest.raises(OnlineIntegrityError, match="integrity verification"):
        tampered_engine.read(_feature(), "600519.SH", as_of=T0 + timedelta(minutes=25))


def test_signed_isolated_receipt_cannot_suppress_event() -> None:
    engine, store = _engine()
    _process(engine, _event("real", 20))
    envelope = store.envelopes[0]
    integrity = HmacOnlineStateIntegrity(TEST_HMAC_KEY)
    forged_state = replace(
        envelope.state,
        receipts=(
            *envelope.state.receipts,
            OnlineEventReceipt(
                event_id="forged",
                content_checksum=canonical_checksum("forged"),
                disposition=OnlineEventDisposition.ACCEPTED,
                retain_until=T0 + timedelta(hours=3),
            ),
        ),
    )
    forged = integrity.seal(
        forged_state,
        retain_until=T0 + timedelta(hours=3),
    )

    class ForgedStore:
        def load(self, _stream_key: str):
            return forged

    forged_engine, _ = _engine(ForgedStore())
    with pytest.raises(OnlineIntegrityError, match="lacks matching"):
        forged_engine.read(_feature(), "600519.SH", as_of=T0 + timedelta(minutes=25))


def test_replay_horizon_outlives_value_ttl_for_deduplication() -> None:
    engine, store = _engine()
    event = _event("retained-duplicate", 20)
    result = _process(engine, event)
    assert result.value is not None
    assert store.expire(trusted_now=result.value.expires_at) == 0

    duplicate = _process(
        engine,
        event,
        processing_time=result.value.expires_at,
    )
    assert duplicate.disposition is OnlineProcessDisposition.DUPLICATE

    retain_until = result.state.receipts[0].retain_until
    assert store.expire(trusted_now=retain_until) == 1


def test_event_source_must_match_contract_namespace() -> None:
    engine, _ = _engine()
    with pytest.raises(OnlineValidationError, match="source"):
        _process(
            engine,
            _event("wrong-source", 20, source=OnlineEventSource.DOMAIN),
        )

    domain_feature = _feature(contract_name="domain.signal_event")
    domain_engine, _ = _engine(feature=domain_feature)
    result = _process(
        domain_engine,
        _event(
            "domain-event",
            25,
            source=OnlineEventSource.DOMAIN,
            contract_name="domain.signal_event",
        ),
        feature=domain_feature,
    )
    assert result.disposition is OnlineProcessDisposition.COMMITTED


def test_signed_canonical_value_must_match_trusted_calculator() -> None:
    engine, store = _engine()
    result = _process(engine, _event("signed-tamper", 20))
    envelope = store.envelopes[0]
    assert result.value is not None
    changed_value = replace(result.value, value="999")
    changed_state = replace(envelope.state, values=(changed_value,))
    integrity = HmacOnlineStateIntegrity(TEST_HMAC_KEY)
    signed = integrity.seal(changed_state, retain_until=envelope.retain_until)

    class SignedTamperedStore:
        def load(self, _stream_key: str):
            return signed

    signed_engine, _ = _engine(SignedTamperedStore())
    with pytest.raises(OnlineIntegrityError, match="trusted calculator output"):
        signed_engine.read(_feature(), "600519.SH", as_of=T0 + timedelta(minutes=25))


def test_later_duplicate_advances_monotonic_processing_clock() -> None:
    engine, _ = _engine()
    event = _event("clock-duplicate", 20)
    _process(engine, event)
    duplicate = _process(
        engine,
        event,
        processing_time=T0 + timedelta(hours=2),
    )
    assert duplicate.disposition is OnlineProcessDisposition.DUPLICATE
    assert duplicate.state.last_processing_time == T0 + timedelta(hours=2)

    with pytest.raises(OnlineIntegrityError, match="cannot move backward"):
        _process(
            engine,
            _event("clock-after", 61),
            processing_time=T0 + timedelta(hours=1, minutes=3),
        )


def test_closed_window_keeps_accepted_evidence_until_receipt_horizon() -> None:
    engine, _ = _engine()
    _process(engine, _event("old-window", 20, "1"))
    rollover = _process(
        engine,
        _event("new-window", 90, "2"),
        processing_time=T0 + timedelta(minutes=92),
    )

    assert rollover.disposition is OnlineProcessDisposition.COMMITTED
    assert any(event.event_id == "old-window" for event in rollover.state.accepted_evidence)
    assert all(event.event_id != "old-window" for event in rollover.state.events)


def test_future_as_of_read_cannot_physically_delete_replay_state() -> None:
    engine, store = _engine()
    event = _event("future-query", 20)
    _process(engine, event)

    future = engine.read(
        _feature(),
        event.entity_id,
        as_of=T0 + timedelta(days=30),
    )
    assert future.freshness is OnlineFreshness.EXPIRED
    assert len(store.envelopes) == 1

    duplicate = _process(engine, event)
    assert duplicate.disposition is OnlineProcessDisposition.DUPLICATE
