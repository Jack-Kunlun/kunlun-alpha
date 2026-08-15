"""RED tests for scheduler lease context and fenced page writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from ashare_contracts.providers import Capability
from data_worker.jobs.precious_metals_funds import FundCollector
from data_worker.raw import LocalFileStorage
from data_worker.scheduler import InMemoryTaskStore, TaskScheduler
from data_worker.storage import InMemoryFundStorage, LeaseFenceError
from data_worker.storage.precious_metals import LeaseContext
from market_core.providers import RawFundProviderResponse


@dataclass
class Clock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def test_scheduler_passes_active_lease_context_to_backward_compatible_job() -> None:
    clock = Clock(datetime(2026, 8, 13, tzinfo=UTC))
    store = InMemoryTaskStore(now=clock.now)
    scheduler = TaskScheduler(store, now=clock.now)
    seen: list[object] = []

    result = scheduler.run("fund-task", lambda context: seen.append(context))

    assert result == "SUCCEEDED"
    assert len(seen) == 1
    context = seen[0]
    assert getattr(context, "task_id", None) == "fund-task"
    assert getattr(context, "lease_token", None)


def test_expired_or_taken_over_worker_writes_zero_rows(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 8, 13, tzinfo=UTC))
    scheduler_store = InMemoryTaskStore(now=clock.now)
    first_token = scheduler_store.acquire_lease("fund-task", lease_seconds=1)
    assert first_token is not None
    first_record = scheduler_store.get("fund-task")
    old_context = LeaseContext(
        task_id="fund-task",
        lease_token=first_token,
        lease_expires_at=first_record.lease_expires_at,
    )

    clock.value += timedelta(seconds=2)
    successor = scheduler_store.acquire_lease("fund-task", lease_seconds=30)
    assert successor is not None

    class Provider:
        def capabilities(self) -> frozenset[Capability]:
            return frozenset({Capability.FETCH_FUND_NAV})

        def require(self, capability: Capability) -> None:
            if capability not in self.capabilities():
                raise NotImplementedError

        def fetch_fund_nav(
            self, exchange: str, cursor: str | None = None
        ) -> RawFundProviderResponse:
            return RawFundProviderResponse(
                body=b'{"items":[],"nextCursor":null}',
                request="GET /funds/nav?exchange=SH",
                source="provider-x",
                endpoint_kind="nav",
                run_id="run-lease",
                source_revision="rev-1",
            )

    persistence = InMemoryFundStorage(lease_store=scheduler_store, now=clock.now)
    collector = FundCollector(
        Provider(),
        LocalFileStorage(tmp_path),
        persistence,
        now=clock.now(),
    )

    with pytest.raises(LeaseFenceError):
        collector.collect("nav", "SH", context=old_context)
    assert persistence.observations() == []
    assert persistence.rejections() == []
    assert persistence.quality_events() == []
    assert persistence.get_checkpoint("fund-task") is None
