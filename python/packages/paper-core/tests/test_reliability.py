from datetime import UTC, datetime

import pytest
from paper_core.reliability import (
    AppendOutcome,
    DuplicateEventConflictError,
    EnduranceClockMode,
    EnduranceQualification,
    FaultInjectablePaperStore,
    FaultScenarioStatus,
    PaperProjectionCache,
    PersistenceUnavailableError,
    RecoverablePaperRuntime,
    classify_endurance_qualification,
    run_fault_matrix,
    run_paper_endurance,
)

NOW = datetime(2026, 8, 26, 1, 2, 3, tzinfo=UTC)


def test_restart_and_cache_loss_rebuild_the_durable_projection() -> None:
    store = FaultInjectablePaperStore()
    cache = PaperProjectionCache()
    runtime = RecoverablePaperRuntime(store, cache)
    runtime.append_message(
        stream_id="account-1",
        event_id="deposit-1",
        event_type="CASH_DEPOSITED",
        payload={"amount": "100000.00", "currency": "CNY"},
        occurred_at=NOW,
    )
    runtime.append_message(
        stream_id="account-1",
        event_id="reserve-1",
        event_type="ORDER_RESERVED",
        payload={"amount": "1000.00"},
        occurred_at=NOW,
    )
    before = runtime.projection("account-1")

    cache.clear()
    after_cache_loss = runtime.projection("account-1")
    after_restart = RecoverablePaperRuntime(store).recover("account-1")

    assert after_cache_loss.event_ids == before.event_ids
    assert after_restart.event_ids == before.event_ids
    assert after_restart.head_digest == before.head_digest
    assert after_restart.event_count == 2


def test_duplicate_delivery_is_idempotent_and_conflicts_are_rejected() -> None:
    runtime = RecoverablePaperRuntime(FaultInjectablePaperStore())
    first = runtime.append_message(
        stream_id="execution-1",
        event_id="fill-1",
        event_type="ORDER_FILLED",
        payload={"fillId": "fill-1", "quantity": 100},
        occurred_at=NOW,
    )
    duplicate = runtime.append_message(
        stream_id="execution-1",
        event_id="fill-1",
        event_type="ORDER_FILLED",
        payload={"fillId": "fill-1", "quantity": 100},
        occurred_at=NOW,
    )

    assert first.outcome is AppendOutcome.APPLIED
    assert duplicate.outcome is AppendOutcome.DUPLICATE
    assert duplicate.projection.event_count == 1

    with pytest.raises(DuplicateEventConflictError):
        runtime.append_message(
            stream_id="execution-1",
            event_id="fill-1",
            event_type="ORDER_FILLED",
            payload={"fillId": "fill-1", "quantity": 200},
            occurred_at=NOW,
        )


def test_persistence_outage_fails_closed_before_mutation() -> None:
    store = FaultInjectablePaperStore()
    runtime = RecoverablePaperRuntime(store)
    store.set_available(False)

    with pytest.raises(PersistenceUnavailableError):
        runtime.append_message(
            stream_id="account-1",
            event_id="reserve-1",
            event_type="ORDER_RESERVED",
            payload={"amount": "1000.00"},
            occurred_at=NOW,
        )

    store.set_available(True)
    assert runtime.projection("account-1").event_count == 0


def test_fault_matrix_covers_all_required_recovery_scenarios() -> None:
    results = run_fault_matrix(now=NOW)

    assert len(results) == 4
    assert all(result.status is FaultScenarioStatus.PASS for result in results)


def test_virtual_72_hour_run_is_never_formal_qualification() -> None:
    report = run_paper_endurance(
        duration_hours=72,
        clock_mode=EnduranceClockMode.VIRTUAL,
    )

    assert report.qualification is EnduranceQualification.ENGINEERING_EVIDENCE_ONLY
    assert report.simulated_hours == 72
    assert report.execution_capability == "PAPER_ONLY"
    assert all(result.iterations == 72 for result in report.scenarios)
    assert len(report.evidence_digest) == 64


def test_only_a_complete_wall_clock_run_can_qualify() -> None:
    scenarios = run_fault_matrix(now=NOW)

    assert (
        classify_endurance_qualification(
            clock_mode=EnduranceClockMode.WALL,
            requested_duration_hours=72,
            elapsed_wall_seconds=(72 * 60 * 60) - 0.001,
            scenarios=scenarios,
        )
        is EnduranceQualification.ENGINEERING_EVIDENCE_ONLY
    )
    assert (
        classify_endurance_qualification(
            clock_mode=EnduranceClockMode.WALL,
            requested_duration_hours=72,
            elapsed_wall_seconds=72 * 60 * 60,
            scenarios=scenarios,
        )
        is EnduranceQualification.QUALIFIED
    )
    assert (
        classify_endurance_qualification(
            clock_mode=EnduranceClockMode.WALL,
            requested_duration_hours=71,
            elapsed_wall_seconds=71 * 60 * 60,
            scenarios=scenarios,
        )
        is EnduranceQualification.ENGINEERING_EVIDENCE_ONLY
    )
