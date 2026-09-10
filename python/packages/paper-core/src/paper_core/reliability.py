"""Recovery and endurance primitives for the simulation-only paper runtime."""

from __future__ import annotations

import json
import time
import tracemalloc
from collections import Counter
from collections.abc import Callable, Generator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from threading import RLock
from typing import Final, Protocol, Self
from uuid import uuid4

GENESIS_DIGEST: Final = "0" * 64
# P6-N12 exit baseline. Live-trading readiness keeps a separate 72-hour hold.
MINIMUM_QUALIFYING_HOURS: Final = 24
MAXIMUM_ENDURANCE_HOURS: Final = 8_760
MAX_APPEND_ATTEMPTS: Final = 2

PayloadScalar = str | int | bool | None


class ReliabilityError(RuntimeError):
    """Base error for recoverable paper-runtime operations."""


class PersistenceUnavailableError(ReliabilityError):
    """Raised before a durable operation when persistence is unavailable."""


class ConcurrentWriteConflictError(ReliabilityError):
    """Raised when a stream head changed before an append was committed."""


class DuplicateEventConflictError(ReliabilityError):
    """Raised when an event identifier is reused with different content."""


class RecoveryInvariantError(ReliabilityError):
    """Raised when a durable event chain cannot be safely replayed."""


class AppendOutcome(StrEnum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"


class FaultScenarioName(StrEnum):
    PROCESS_RESTART = "PROCESS_RESTART"
    DUPLICATE_MESSAGE = "DUPLICATE_MESSAGE"
    DATABASE_OUTAGE = "DATABASE_OUTAGE"
    CACHE_LOSS = "CACHE_LOSS"


class FaultScenarioStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class EnduranceClockMode(StrEnum):
    WALL = "wall"
    VIRTUAL = "virtual"


class EnduranceEvidenceScope(StrEnum):
    TEST_DOUBLE = "TEST_DOUBLE"
    DURABLE_ADAPTER = "DURABLE_ADAPTER"


class EnduranceQualification(StrEnum):
    QUALIFIED = "QUALIFIED"
    ENGINEERING_EVIDENCE_ONLY = "ENGINEERING_EVIDENCE_ONLY"
    FAILED = "FAILED"


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "timestamps must be timezone-aware"
        raise ValueError(msg)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def normalize_payload_items(
    payload: Mapping[str, object],
) -> tuple[tuple[str, PayloadScalar], ...]:
    normalized: list[tuple[str, PayloadScalar]] = []
    for key, value in payload.items():
        if not key:
            msg = "payload keys must not be empty"
            raise ValueError(msg)
        if value is not None and not isinstance(value, (str, int, bool)):
            msg = "payload values must be strings, integers, booleans, or null"
            raise TypeError(msg)
        normalized.append((key, value))
    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True)
class PaperRuntimeEvent:
    """Hash-linked paper event persisted before acknowledgement."""

    stream_id: str
    event_id: str
    event_type: str
    sequence: int
    occurred_at: datetime
    payload_items: tuple[tuple[str, PayloadScalar], ...]
    prior_digest: str
    digest: str

    @classmethod
    def build(
        cls,
        *,
        stream_id: str,
        event_id: str,
        event_type: str,
        sequence: int,
        occurred_at: datetime,
        payload: Mapping[str, PayloadScalar],
        prior_digest: str,
    ) -> Self:
        if not stream_id or not event_id or not event_type:
            msg = "stream_id, event_id, and event_type must not be empty"
            raise ValueError(msg)
        if sequence < 1:
            msg = "sequence must be positive"
            raise ValueError(msg)
        normalized_time = occurred_at.astimezone(UTC)
        items = normalize_payload_items(payload)
        body = {
            "eventId": event_id,
            "eventType": event_type,
            "occurredAt": _timestamp(normalized_time),
            "payload": dict(items),
            "priorDigest": prior_digest,
            "sequence": sequence,
            "streamId": stream_id,
        }
        return cls(
            stream_id=stream_id,
            event_id=event_id,
            event_type=event_type,
            sequence=sequence,
            occurred_at=normalized_time,
            payload_items=items,
            prior_digest=prior_digest,
            digest=_digest(body),
        )

    def canonical_body(self) -> dict[str, object]:
        return {
            "eventId": self.event_id,
            "eventType": self.event_type,
            "occurredAt": _timestamp(self.occurred_at),
            "payload": dict(self.payload_items),
            "priorDigest": self.prior_digest,
            "sequence": self.sequence,
            "streamId": self.stream_id,
        }


@dataclass(frozen=True, slots=True)
class PaperRuntimeProjection:
    stream_id: str
    event_count: int
    event_ids: tuple[str, ...]
    event_type_counts: tuple[tuple[str, int], ...]
    head_digest: str
    rebuilt_at: datetime


@dataclass(frozen=True, slots=True)
class AppendReceipt:
    outcome: AppendOutcome
    event: PaperRuntimeEvent
    projection: PaperRuntimeProjection


class PaperDurableEventStore(Protocol):
    def read_stream(self, stream_id: str) -> tuple[PaperRuntimeEvent, ...]: ...

    def append_event(
        self,
        event: PaperRuntimeEvent,
        *,
        expected_head_digest: str,
    ) -> tuple[AppendOutcome, tuple[PaperRuntimeEvent, ...]]: ...


class PaperFaultHarness(Protocol):
    """Provide isolated stores and a real or simulated persistence outage."""

    evidence_scope: EnduranceEvidenceScope
    evidence_target: str
    fault_injection: str
    storage_adapter: str

    def new_store(self) -> PaperDurableEventStore: ...

    def database_outage(self) -> AbstractContextManager[None]: ...

    def active_connection_count(self) -> int | None: ...


class FaultInjectablePaperStore:
    """Thread-safe persistence test double with compare-and-swap appends."""

    def __init__(self) -> None:
        self._available = True
        self._streams: dict[str, tuple[PaperRuntimeEvent, ...]] = {}
        self._lock = RLock()

    def set_available(self, available: bool) -> None:
        with self._lock:
            self._available = available

    def read_stream(self, stream_id: str) -> tuple[PaperRuntimeEvent, ...]:
        with self._lock:
            self._require_available()
            return self._streams.get(stream_id, ())

    def append_event(
        self,
        event: PaperRuntimeEvent,
        *,
        expected_head_digest: str,
    ) -> tuple[AppendOutcome, tuple[PaperRuntimeEvent, ...]]:
        with self._lock:
            self._require_available()
            current = self._streams.get(event.stream_id, ())
            for persisted in current:
                if persisted.event_id != event.event_id:
                    continue
                if (
                    persisted.event_type == event.event_type
                    and persisted.payload_items == event.payload_items
                ):
                    return AppendOutcome.DUPLICATE, current
                msg = f"event_id {event.event_id!r} was reused with different content"
                raise DuplicateEventConflictError(msg)

            current_head = current[-1].digest if current else GENESIS_DIGEST
            if current_head != expected_head_digest:
                msg = "durable stream head changed before append"
                raise ConcurrentWriteConflictError(msg)
            if event.sequence != len(current) + 1:
                msg = "event sequence is not contiguous"
                raise RecoveryInvariantError(msg)
            if event.prior_digest != current_head:
                msg = "event prior digest does not match the durable stream head"
                raise RecoveryInvariantError(msg)

            updated = (*current, event)
            self._streams[event.stream_id] = updated
            return AppendOutcome.APPLIED, updated

    def _require_available(self) -> None:
        if not self._available:
            msg = "paper persistence is unavailable; operation failed closed"
            raise PersistenceUnavailableError(msg)


class InMemoryPaperFaultHarness:
    """Fault harness for fast engineering checks using one in-memory store."""

    evidence_scope = EnduranceEvidenceScope.TEST_DOUBLE
    evidence_target = "ephemeral-test-double"
    fault_injection = "in-process-availability-toggle"
    storage_adapter = "in-memory-test-double"

    def __init__(self) -> None:
        self._store = FaultInjectablePaperStore()

    def new_store(self) -> PaperDurableEventStore:
        return self._store

    def active_connection_count(self) -> None:
        return None

    @contextmanager
    def database_outage(self) -> Generator[None, None, None]:
        self._store.set_available(False)
        try:
            yield
        finally:
            self._store.set_available(True)


class PaperProjectionCache:
    """Volatile cache whose complete loss is always recoverable."""

    def __init__(self) -> None:
        self._projections: dict[str, PaperRuntimeProjection] = {}
        self._lock = RLock()

    def get(self, stream_id: str) -> PaperRuntimeProjection | None:
        with self._lock:
            return self._projections.get(stream_id)

    def put(self, projection: PaperRuntimeProjection) -> None:
        with self._lock:
            self._projections[projection.stream_id] = projection

    def clear(self) -> None:
        with self._lock:
            self._projections.clear()


def _project(
    stream_id: str,
    events: tuple[PaperRuntimeEvent, ...],
    *,
    rebuilt_at: datetime,
) -> PaperRuntimeProjection:
    prior_digest = GENESIS_DIGEST
    event_ids: set[str] = set()
    counts: Counter[str] = Counter()
    for expected_sequence, event in enumerate(events, start=1):
        if event.stream_id != stream_id:
            msg = "durable stream contains an event for a different stream"
            raise RecoveryInvariantError(msg)
        if event.sequence != expected_sequence:
            msg = "durable stream sequence is not contiguous"
            raise RecoveryInvariantError(msg)
        if event.prior_digest != prior_digest:
            msg = "durable stream digest chain is broken"
            raise RecoveryInvariantError(msg)
        if event.digest != _digest(event.canonical_body()):
            msg = "durable event digest verification failed"
            raise RecoveryInvariantError(msg)
        if event.event_id in event_ids:
            msg = "durable stream contains a duplicate event identifier"
            raise RecoveryInvariantError(msg)
        event_ids.add(event.event_id)
        counts[event.event_type] += 1
        prior_digest = event.digest

    return PaperRuntimeProjection(
        stream_id=stream_id,
        event_count=len(events),
        event_ids=tuple(event.event_id for event in events),
        event_type_counts=tuple(sorted(counts.items())),
        head_digest=prior_digest,
        rebuilt_at=rebuilt_at.astimezone(UTC),
    )


class RecoverablePaperRuntime:
    """Simulation-only runtime that acknowledges only durable appends."""

    def __init__(
        self,
        store: PaperDurableEventStore,
        cache: PaperProjectionCache | None = None,
    ) -> None:
        self._store = store
        self._cache = cache if cache is not None else PaperProjectionCache()

    def append_message(
        self,
        *,
        stream_id: str,
        event_id: str,
        event_type: str,
        payload: Mapping[str, PayloadScalar],
        occurred_at: datetime | None = None,
    ) -> AppendReceipt:
        event_time = occurred_at if occurred_at is not None else datetime.now(UTC)
        for attempt in range(MAX_APPEND_ATTEMPTS):
            events = self._store.read_stream(stream_id)
            for persisted in events:
                if persisted.event_id != event_id:
                    continue
                if (
                    persisted.event_type != event_type
                    or persisted.payload_items != normalize_payload_items(payload)
                ):
                    msg = f"event_id {event_id!r} was reused with different content"
                    raise DuplicateEventConflictError(msg)
                projection = _project(
                    stream_id,
                    events,
                    rebuilt_at=datetime.now(UTC),
                )
                self._cache.put(projection)
                return AppendReceipt(AppendOutcome.DUPLICATE, persisted, projection)

            head_digest = events[-1].digest if events else GENESIS_DIGEST
            event = PaperRuntimeEvent.build(
                stream_id=stream_id,
                event_id=event_id,
                event_type=event_type,
                sequence=len(events) + 1,
                occurred_at=event_time,
                payload=payload,
                prior_digest=head_digest,
            )
            try:
                outcome, updated = self._store.append_event(
                    event,
                    expected_head_digest=head_digest,
                )
            except ConcurrentWriteConflictError:
                if attempt + 1 == MAX_APPEND_ATTEMPTS:
                    raise
                continue
            persisted = next(item for item in updated if item.event_id == event_id)
            projection = _project(
                stream_id,
                updated,
                rebuilt_at=datetime.now(UTC),
            )
            self._cache.put(projection)
            return AppendReceipt(outcome, persisted, projection)

        msg = "bounded append retry was exhausted"
        raise ConcurrentWriteConflictError(msg)

    def projection(self, stream_id: str) -> PaperRuntimeProjection:
        events = self._store.read_stream(stream_id)
        durable_head = events[-1].digest if events else GENESIS_DIGEST
        cached = self._cache.get(stream_id)
        if cached is not None and cached.head_digest == durable_head:
            return cached
        return self.recover(stream_id, events=events)

    def recover(
        self,
        stream_id: str,
        *,
        events: tuple[PaperRuntimeEvent, ...] | None = None,
    ) -> PaperRuntimeProjection:
        durable_events = events if events is not None else self._store.read_stream(stream_id)
        projection = _project(
            stream_id,
            durable_events,
            rebuilt_at=datetime.now(UTC),
        )
        self._cache.put(projection)
        return projection


@dataclass(frozen=True, slots=True)
class FaultScenarioResult:
    name: FaultScenarioName
    status: FaultScenarioStatus
    iterations: int
    details: str

    def to_dict(self) -> dict[str, object]:
        return {
            "details": self.details,
            "iterations": self.iterations,
            "name": self.name.value,
            "status": self.status.value,
        }


def _run_scenario(
    name: FaultScenarioName,
    scenario: Callable[[], str],
) -> FaultScenarioResult:
    try:
        details = scenario()
    except Exception as exc:  # noqa: BLE001 - a fault report must retain all failures.
        return FaultScenarioResult(
            name=name,
            status=FaultScenarioStatus.FAIL,
            iterations=1,
            details=f"{type(exc).__name__}: {exc}",
        )
    return FaultScenarioResult(
        name=name,
        status=FaultScenarioStatus.PASS,
        iterations=1,
        details=details,
    )


def run_fault_matrix(
    *,
    now: datetime | None = None,
    harness: PaperFaultHarness | None = None,
) -> tuple[FaultScenarioResult, ...]:
    """Exercise restart, duplicate, persistence-outage, and cache-loss recovery."""

    event_time = now if now is not None else datetime.now(UTC)
    selected_harness = harness if harness is not None else InMemoryPaperFaultHarness()
    stream_prefix = f"paper-endurance-{uuid4().hex}"

    def process_restart() -> str:
        runtime = RecoverablePaperRuntime(selected_harness.new_store())
        runtime.append_message(
            stream_id=f"{stream_prefix}-restart",
            event_id="restart-1",
            event_type="CASH_DEPOSITED",
            payload={"amount": "100000.00", "currency": "CNY"},
            occurred_at=event_time,
        )
        restarted = RecoverablePaperRuntime(selected_harness.new_store())
        recovered = restarted.recover(f"{stream_prefix}-restart")
        if recovered.event_count != 1 or recovered.event_ids != ("restart-1",):
            msg = "process restart did not recover the durable projection"
            raise RecoveryInvariantError(msg)
        return "replayed one durable event after a fresh runtime start"

    def duplicate_message() -> str:
        runtime = RecoverablePaperRuntime(selected_harness.new_store())
        runtime.append_message(
            stream_id=f"{stream_prefix}-duplicate",
            event_id="fill-1",
            event_type="ORDER_FILLED",
            payload={"fillId": "fill-1", "quantity": 100},
            occurred_at=event_time,
        )
        duplicate = runtime.append_message(
            stream_id=f"{stream_prefix}-duplicate",
            event_id="fill-1",
            event_type="ORDER_FILLED",
            payload={"fillId": "fill-1", "quantity": 100},
            occurred_at=event_time,
        )
        if duplicate.outcome is not AppendOutcome.DUPLICATE:
            msg = "duplicate message was not classified as idempotent"
            raise RecoveryInvariantError(msg)
        if duplicate.projection.event_count != 1:
            msg = "duplicate message changed the durable projection"
            raise RecoveryInvariantError(msg)
        return "replayed duplicate event_id without a second durable mutation"

    def database_outage() -> str:
        runtime = RecoverablePaperRuntime(selected_harness.new_store())
        stream_id = f"{stream_prefix}-outage"
        with selected_harness.database_outage():
            try:
                runtime.append_message(
                    stream_id=stream_id,
                    event_id="outage-1",
                    event_type="ORDER_RESERVED",
                    payload={"amount": "1000.00"},
                    occurred_at=event_time,
                )
            except PersistenceUnavailableError:
                pass
            else:
                msg = "persistence outage did not fail closed"
                raise RecoveryInvariantError(msg)

        if runtime.projection(stream_id).event_count != 0:
            msg = "failed persistence operation mutated the durable stream"
            raise RecoveryInvariantError(msg)
        applied = runtime.append_message(
            stream_id=stream_id,
            event_id="outage-1",
            event_type="ORDER_RESERVED",
            payload={"amount": "1000.00"},
            occurred_at=event_time,
        )
        duplicate = runtime.append_message(
            stream_id=stream_id,
            event_id="outage-1",
            event_type="ORDER_RESERVED",
            payload={"amount": "1000.00"},
            occurred_at=event_time,
        )
        if applied.outcome is not AppendOutcome.APPLIED:
            msg = "message was not applied after persistence recovery"
            raise RecoveryInvariantError(msg)
        if duplicate.projection.event_count != 1:
            msg = "outage retry was not idempotent"
            raise RecoveryInvariantError(msg)
        return "failed closed during outage and applied one idempotent retry"

    def cache_loss() -> str:
        cache = PaperProjectionCache()
        runtime = RecoverablePaperRuntime(selected_harness.new_store(), cache)
        stream_id = f"{stream_prefix}-cache"
        for sequence in (1, 2):
            runtime.append_message(
                stream_id=stream_id,
                event_id=f"cache-{sequence}",
                event_type="POSITION_CHANGED",
                payload={"quantity": sequence * 100, "symbol": "600519.SH"},
                occurred_at=event_time,
            )
        before = runtime.projection(stream_id)
        cache.clear()
        after = runtime.projection(stream_id)
        if (
            after.event_ids != before.event_ids
            or after.head_digest != before.head_digest
            or after.event_count != 2
        ):
            msg = "cache loss did not rebuild the same durable projection"
            raise RecoveryInvariantError(msg)
        return "rebuilt the projection from two hash-verified durable events"

    return (
        _run_scenario(FaultScenarioName.PROCESS_RESTART, process_restart),
        _run_scenario(FaultScenarioName.DUPLICATE_MESSAGE, duplicate_message),
        _run_scenario(FaultScenarioName.DATABASE_OUTAGE, database_outage),
        _run_scenario(FaultScenarioName.CACHE_LOSS, cache_loss),
    )


def _aggregate_fault_results(
    results: list[FaultScenarioResult],
) -> tuple[FaultScenarioResult, ...]:
    aggregated: list[FaultScenarioResult] = []
    for name in FaultScenarioName:
        matching = [result for result in results if result.name is name]
        failures = [result for result in matching if result.status is FaultScenarioStatus.FAIL]
        if failures:
            details = "; ".join(result.details for result in failures[:3])
            aggregated.append(
                FaultScenarioResult(
                    name=name,
                    status=FaultScenarioStatus.FAIL,
                    iterations=len(matching),
                    details=details,
                )
            )
        else:
            aggregated.append(
                FaultScenarioResult(
                    name=name,
                    status=FaultScenarioStatus.PASS,
                    iterations=len(matching),
                    details=f"{len(matching)}/{len(matching)} iterations passed",
                )
            )
    return tuple(aggregated)


def classify_endurance_qualification(
    *,
    clock_mode: EnduranceClockMode,
    evidence_scope: EnduranceEvidenceScope,
    requested_duration_hours: int,
    elapsed_wall_seconds: float,
    scenarios: tuple[FaultScenarioResult, ...],
) -> EnduranceQualification:
    if not scenarios or any(scenario.status is FaultScenarioStatus.FAIL for scenario in scenarios):
        return EnduranceQualification.FAILED
    requested_seconds = requested_duration_hours * 60 * 60
    if (
        clock_mode is EnduranceClockMode.WALL
        and evidence_scope is EnduranceEvidenceScope.DURABLE_ADAPTER
        and requested_duration_hours >= MINIMUM_QUALIFYING_HOURS
        and elapsed_wall_seconds >= requested_seconds
    ):
        return EnduranceQualification.QUALIFIED
    return EnduranceQualification.ENGINEERING_EVIDENCE_ONLY


@dataclass(frozen=True, slots=True)
class PaperEnduranceProgress:
    started_at: datetime
    updated_at: datetime
    requested_duration_hours: int
    elapsed_wall_seconds: float
    completed_iterations: int
    clock_mode: EnduranceClockMode
    evidence_scope: EnduranceEvidenceScope
    execution_capability: str
    source_version: str

    def to_dict(self) -> dict[str, object]:
        return {
            "clockMode": self.clock_mode.value,
            "completedIterations": self.completed_iterations,
            "elapsedWallSeconds": round(self.elapsed_wall_seconds, 3),
            "evidenceScope": self.evidence_scope.value,
            "executionCapability": self.execution_capability,
            "requestedDurationHours": self.requested_duration_hours,
            "sourceVersion": self.source_version,
            "startedAt": _timestamp(self.started_at),
            "status": "RUNNING",
            "updatedAt": _timestamp(self.updated_at),
        }


@dataclass(frozen=True, slots=True)
class EnduranceResourceMetrics:
    python_heap_start_bytes: int
    python_heap_end_bytes: int
    python_heap_peak_bytes: int
    adapter_connections_start: int | None
    adapter_connections_end: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "adapterConnectionsEnd": self.adapter_connections_end,
            "adapterConnectionsStart": self.adapter_connections_start,
            "pythonHeapEndBytes": self.python_heap_end_bytes,
            "pythonHeapGrowthBytes": (self.python_heap_end_bytes - self.python_heap_start_bytes),
            "pythonHeapPeakBytes": self.python_heap_peak_bytes,
            "pythonHeapStartBytes": self.python_heap_start_bytes,
        }


@dataclass(frozen=True, slots=True)
class PaperEnduranceReport:
    report_version: str
    started_at: datetime
    generated_at: datetime
    requested_duration_hours: int
    elapsed_wall_seconds: float
    simulated_hours: int
    clock_mode: EnduranceClockMode
    evidence_scope: EnduranceEvidenceScope
    evidence_target: str
    fault_injection: str
    qualification: EnduranceQualification
    execution_capability: str
    storage_adapter: str
    source_version: str
    resource_metrics: EnduranceResourceMetrics
    scenarios: tuple[FaultScenarioResult, ...]
    evidence_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "clockMode": self.clock_mode.value,
            "elapsedWallSeconds": round(self.elapsed_wall_seconds, 3),
            "evidenceDigest": self.evidence_digest,
            "evidenceScope": self.evidence_scope.value,
            "evidenceTarget": self.evidence_target,
            "executionCapability": self.execution_capability,
            "faultInjection": self.fault_injection,
            "generatedAt": _timestamp(self.generated_at),
            "qualification": self.qualification.value,
            "reportVersion": self.report_version,
            "requestedDurationHours": self.requested_duration_hours,
            "resourceMetrics": self.resource_metrics.to_dict(),
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
            "simulatedHours": self.simulated_hours,
            "startedAt": _timestamp(self.started_at),
            "storageAdapter": self.storage_adapter,
            "sourceVersion": self.source_version,
        }


def run_paper_endurance(
    *,
    duration_hours: int = MINIMUM_QUALIFYING_HOURS,
    clock_mode: EnduranceClockMode = EnduranceClockMode.WALL,
    tick_seconds: int = 60,
    harness: PaperFaultHarness | None = None,
    progress_callback: Callable[[PaperEnduranceProgress], None] | None = None,
    source_version: str = "unversioned",
) -> PaperEnduranceReport:
    """Run the fault matrix under a virtual or real wall-clock endurance window."""

    if not 1 <= duration_hours <= MAXIMUM_ENDURANCE_HOURS:
        msg = f"duration_hours must be between 1 and {MAXIMUM_ENDURANCE_HOURS}"
        raise ValueError(msg)
    if tick_seconds < 1:
        msg = "tick_seconds must be positive"
        raise ValueError(msg)
    if not source_version:
        msg = "source_version must not be empty"
        raise ValueError(msg)

    started_at = datetime.now(UTC)
    started_monotonic = time.monotonic()
    collected: list[FaultScenarioResult] = []
    simulated_hours = 0
    selected_harness = harness if harness is not None else InMemoryPaperFaultHarness()
    owns_tracing = not tracemalloc.is_tracing()
    if owns_tracing:
        tracemalloc.start()
    heap_start, _ = tracemalloc.get_traced_memory()
    connections_start = selected_harness.active_connection_count()
    completed_iterations = 0

    def report_progress(elapsed: float) -> None:
        if progress_callback is None:
            return
        progress_callback(
            PaperEnduranceProgress(
                started_at=started_at,
                updated_at=datetime.now(UTC),
                requested_duration_hours=duration_hours,
                elapsed_wall_seconds=elapsed,
                completed_iterations=completed_iterations,
                clock_mode=clock_mode,
                evidence_scope=selected_harness.evidence_scope,
                execution_capability="PAPER_ONLY",
                source_version=source_version,
            )
        )

    try:
        if clock_mode is EnduranceClockMode.VIRTUAL:
            for hour in range(duration_hours):
                collected.extend(run_fault_matrix(now=started_at, harness=selected_harness))
                simulated_hours = hour + 1
                completed_iterations += 1
                report_progress(time.monotonic() - started_monotonic)
        else:
            requested_seconds = duration_hours * 60 * 60
            while True:
                collected.extend(run_fault_matrix(harness=selected_harness))
                completed_iterations += 1
                elapsed = time.monotonic() - started_monotonic
                report_progress(elapsed)
                if elapsed >= requested_seconds:
                    break
                time.sleep(min(float(tick_seconds), requested_seconds - elapsed))

        elapsed_wall_seconds = time.monotonic() - started_monotonic
        heap_end, heap_peak = tracemalloc.get_traced_memory()
        resource_metrics = EnduranceResourceMetrics(
            python_heap_start_bytes=heap_start,
            python_heap_end_bytes=heap_end,
            python_heap_peak_bytes=heap_peak,
            adapter_connections_start=connections_start,
            adapter_connections_end=selected_harness.active_connection_count(),
        )
        scenarios = _aggregate_fault_results(collected)
        evidence_scope = selected_harness.evidence_scope
        qualification = classify_endurance_qualification(
            clock_mode=clock_mode,
            evidence_scope=evidence_scope,
            requested_duration_hours=duration_hours,
            elapsed_wall_seconds=elapsed_wall_seconds,
            scenarios=scenarios,
        )
        if (
            qualification is EnduranceQualification.QUALIFIED
            and resource_metrics.adapter_connections_end != 0
        ):
            qualification = EnduranceQualification.FAILED
        generated_at = datetime.now(UTC)
        evidence_body = {
            "clockMode": clock_mode.value,
            "elapsedWallSeconds": round(elapsed_wall_seconds, 3),
            "evidenceScope": evidence_scope.value,
            "evidenceTarget": selected_harness.evidence_target,
            "executionCapability": "PAPER_ONLY",
            "faultInjection": selected_harness.fault_injection,
            "generatedAt": _timestamp(generated_at),
            "qualification": qualification.value,
            "reportVersion": "paper-endurance-report/v2",
            "requestedDurationHours": duration_hours,
            "resourceMetrics": resource_metrics.to_dict(),
            "scenarios": [scenario.to_dict() for scenario in scenarios],
            "simulatedHours": simulated_hours,
            "startedAt": _timestamp(started_at),
            "storageAdapter": selected_harness.storage_adapter,
            "sourceVersion": source_version,
        }
        return PaperEnduranceReport(
            report_version="paper-endurance-report/v2",
            started_at=started_at,
            generated_at=generated_at,
            requested_duration_hours=duration_hours,
            elapsed_wall_seconds=elapsed_wall_seconds,
            simulated_hours=simulated_hours,
            clock_mode=clock_mode,
            evidence_scope=evidence_scope,
            evidence_target=selected_harness.evidence_target,
            fault_injection=selected_harness.fault_injection,
            qualification=qualification,
            execution_capability="PAPER_ONLY",
            storage_adapter=selected_harness.storage_adapter,
            source_version=source_version,
            resource_metrics=resource_metrics,
            scenarios=scenarios,
            evidence_digest=_digest(evidence_body),
        )
    finally:
        if owns_tracing:
            tracemalloc.stop()
