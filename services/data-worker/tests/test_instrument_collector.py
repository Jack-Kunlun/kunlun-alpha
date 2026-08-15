"""Instrument collection job tests.

Covers idempotency (repeated runs produce an empty diff), add/change/delist
auditing, unified_code as the unique key (name changes do not change identity),
and retry behaviour for transient vs permanent provider errors.
"""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest
from ashare_contracts.instrument_instrument import Instrument
from ashare_contracts.providers import Capability, Cursor, Page
from data_worker.jobs.instruments.collector import ActiveRunConflictError, InstrumentCollector
from data_worker.jobs.instruments.repository import (
    InMemoryInstrumentRepository,
    InstrumentCheckpoint,
)
from market_core.providers import (
    ProviderAuthError,
    ProviderDataError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from market_core.providers.interfaces import InstrumentProvider


def _instrument(code: str, name: str, exchange: str = "SH") -> Instrument:
    return Instrument.model_validate(
        {
            "unifiedCode": f"{code}.{exchange}",
            "code": code,
            "exchange": exchange,
            "board": "MAIN",
            "type": "STOCK",
            "name": name,
            "tradingStatus": "LISTED",
            "currency": "CNY",
        }
    )


class FakeInstrumentProvider(InstrumentProvider):
    """Scripted provider: fixed pages, optionally raising transient/permanent errors."""

    def __init__(
        self, instruments: list[Instrument], transient_failures: int = 0, permanent: bool = False
    ) -> None:
        self._instruments = instruments
        self._transient_failures = transient_failures
        self._permanent = permanent
        self.calls = 0

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_INSTRUMENTS})

    def fetch_instruments(self, exchange: str, cursor: Cursor | None = None) -> Page[Instrument]:
        self.calls += 1
        if self._permanent:
            raise ProviderAuthError("bad credentials")
        if self._transient_failures > 0:
            self._transient_failures -= 1
            raise ProviderRateLimitError("throttled")
        return Page(items=list(self._instruments), next_cursor=None)


class PagedInstrumentProvider(InstrumentProvider):
    """Scripted cursor pages with optional failures for restart tests."""

    def __init__(
        self,
        pages: dict[str | None, Page[Instrument]],
        fail_cursors: set[str] | None = None,
    ) -> None:
        self._pages = pages
        self._fail_cursors = set(fail_cursors or set())
        self.calls: list[str | None] = []

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_INSTRUMENTS})

    def fetch_instruments(self, exchange: str, cursor: Cursor | None = None) -> Page[Instrument]:
        self.calls.append(cursor)
        if cursor in self._fail_cursors:
            raise ProviderUnavailableError("simulated page failure")
        return self._pages[cursor]


class InitialCheckpointBarrierRepository(InMemoryInstrumentRepository):
    """Force two initial checkpoint writes to overlap for the race regression."""

    def __init__(self) -> None:
        super().__init__()
        self._initial_save_barrier = threading.Barrier(2)
        self._loser_claimed = threading.Event()

    def save_checkpoint(self, checkpoint: InstrumentCheckpoint) -> None:
        if checkpoint.page_count == 0 and not checkpoint.complete:
            self._initial_save_barrier.wait(timeout=5)
        super().save_checkpoint(checkpoint)

    def claim_run(self, exchange: str, run_id: str) -> InstrumentCheckpoint:
        self._initial_save_barrier.wait(timeout=5)
        try:
            checkpoint = super().claim_run(exchange, run_id)
        except ActiveRunConflictError:
            self._loser_claimed.set()
            raise
        self._loser_claimed.wait(timeout=5)
        return checkpoint


class ClaimSnapshotBarrierRepository(InMemoryInstrumentRepository):
    """Interleave a state write while a run claim is waiting to acquire the lock."""

    def __init__(self) -> None:
        super().__init__()
        self.claim_started = threading.Event()
        self.allow_claim = threading.Event()

    def claim_run(
        self,
        exchange: str,
        run_id: str,
        baseline: tuple[Instrument, ...] | None = None,
    ) -> InstrumentCheckpoint:
        self.claim_started.set()
        if not self.allow_claim.wait(timeout=5):
            raise RuntimeError("claim barrier timed out")
        assert baseline is None, "collector must not capture baseline outside claim"
        return super().claim_run(exchange, run_id)


class OwnerLossBeforeReconcileRepository(InMemoryInstrumentRepository):
    """Transfer ownership immediately before a final reconcile attempt."""

    def __init__(self, replacement: Instrument) -> None:
        super().__init__()
        self._replacement = replacement
        self._owner_lost = False

    def _lose_owner(self) -> None:
        if self._owner_lost:
            return
        self._owner_lost = True
        self.clear_checkpoint("SH", "run-old")
        super().claim_run("SH", "run-new")
        self.upsert(self._replacement)

    def remove(self, unified_code: str) -> None:
        self._lose_owner()
        super().remove(unified_code)

    def reconcile_and_complete(
        self, checkpoint: InstrumentCheckpoint, delisted_codes: tuple[str, ...]
    ) -> InstrumentCheckpoint:
        self._lose_owner()
        return super().reconcile_and_complete(checkpoint, delisted_codes)


class FailingCommitRepository(InMemoryInstrumentRepository):
    """Inject a page-commit failure before any page state is published."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_next_commit = True

    def commit_page(
        self,
        checkpoint: InstrumentCheckpoint,
        instruments: tuple[Instrument, ...],
        next_cursor: Cursor | None,
    ) -> InstrumentCheckpoint:
        if self.fail_next_commit:
            self.fail_next_commit = False
            raise RuntimeError("injected page commit failure")
        return super().commit_page(checkpoint, instruments, next_cursor)


def test_first_run_adds_everything() -> None:
    provider = FakeInstrumentProvider(
        [_instrument("600000", "浦发银行"), _instrument("600001", "邯郸钢铁")]
    )
    repo = InMemoryInstrumentRepository()
    collector = InstrumentCollector(provider, repo)

    result = collector.collect("SH")

    assert len(result.added) == 2
    assert result.changed == []
    assert result.delisted == []
    assert len(repo.get_all("SH")) == 2


def test_repeated_run_is_idempotent() -> None:
    instruments = [_instrument("600000", "浦发银行")]
    provider = FakeInstrumentProvider(instruments)
    repo = InMemoryInstrumentRepository()
    collector = InstrumentCollector(provider, repo)

    collector.collect("SH")
    second = collector.collect("SH")

    assert second.is_empty()
    assert len(repo.get_all("SH")) == 1


def test_change_and_delist_are_audited() -> None:
    repo = InMemoryInstrumentRepository()
    provider_a = FakeInstrumentProvider(
        [_instrument("600000", "浦发银行"), _instrument("600001", "邯郸钢铁")]
    )
    InstrumentCollector(provider_a, repo).collect("SH")

    # Second run: 600000 renamed, 600001 delisted, 600002 added.
    provider_b = FakeInstrumentProvider(
        [_instrument("600000", "浦发银行(更名)"), _instrument("600002", "新增")]
    )
    result = InstrumentCollector(provider_b, repo).collect("SH")

    assert [c.unified_code for c in result.changed] == ["600000.SH"]
    assert [c.unified_code for c in result.delisted] == ["600001.SH"]
    assert [a.unified_code for a in result.added] == ["600002.SH"]

    audit = repo.audit_log()
    assert any("UPSERT 600000.SH" in line for line in audit)
    assert any("DELIST 600001.SH" in line for line in audit)


def test_unified_code_is_unique_key_not_name() -> None:
    repo = InMemoryInstrumentRepository()
    provider_a = FakeInstrumentProvider([_instrument("600000", "浦发银行")])
    InstrumentCollector(provider_a, repo).collect("SH")

    provider_b = FakeInstrumentProvider([_instrument("600000", "完全不同的名字")])
    result = InstrumentCollector(provider_b, repo).collect("SH")

    # Same unified code -> a change, not a delist + add.
    assert [c.unified_code for c in result.changed] == ["600000.SH"]
    assert result.delisted == []
    assert result.added == []


def test_transient_error_is_retried() -> None:
    provider = FakeInstrumentProvider([_instrument("600000", "浦发银行")], transient_failures=2)
    repo = InMemoryInstrumentRepository()
    result = InstrumentCollector(provider, repo).collect("SH")

    assert len(result.added) == 1
    assert provider.calls == 3  # 2 failures + 1 success


def test_permanent_error_fails_fast() -> None:
    provider = FakeInstrumentProvider([_instrument("600000", "浦发银行")], permanent=True)
    repo = InMemoryInstrumentRepository()

    with pytest.raises(ProviderAuthError):
        InstrumentCollector(provider, repo).collect("SH")
    assert provider.calls == 1


def test_checkpoint_is_saved_after_each_page_and_restart_resumes_cursor() -> None:
    first = _instrument("600000", "娴﹀彂閾惰")
    second = _instrument("600001", "閭兏閽㈤搧")
    existing = _instrument("600002", "鏃у凡閫€甯傝")
    repo = InMemoryInstrumentRepository()
    repo.upsert(existing)

    failing_provider = PagedInstrumentProvider(
        {
            None: Page(items=[first], next_cursor="page-2"),
            "page-2": Page(items=[second], next_cursor=None),
        },
        fail_cursors={"page-2"},
    )
    with pytest.raises(ProviderUnavailableError):
        InstrumentCollector(failing_provider, repo, max_retries=1).collect("SH", run_id="run-1")

    checkpoint = repo.load_checkpoint("SH", "run-1")
    assert checkpoint is not None
    assert checkpoint.exchange == "SH"
    assert checkpoint.run_id == "run-1"
    assert checkpoint.next_cursor == "page-2"
    assert checkpoint.accepted_codes == frozenset({"600000.SH"})
    assert checkpoint.page_count == 1
    assert checkpoint.complete is False
    assert "600002.SH" in repo.get_all("SH")
    assert not any("DELIST 600002.SH" in line for line in repo.audit_log())

    resumed_provider = PagedInstrumentProvider({"page-2": Page(items=[second], next_cursor=None)})
    result = InstrumentCollector(resumed_provider, repo).collect("SH", run_id="run-1")

    assert resumed_provider.calls == ["page-2"]
    assert [item.unified_code for item in result.delisted] == ["600002.SH"]
    completed = repo.load_checkpoint("SH", "run-1")
    assert completed is not None
    assert completed.complete is True
    assert completed.reconciled is True


def test_replayed_instrument_page_is_idempotent() -> None:
    first = _instrument("600000", "娴﹀彂閾惰")
    pages = {None: Page(items=[first], next_cursor=None)}
    repo = InMemoryInstrumentRepository()

    InstrumentCollector(PagedInstrumentProvider(pages), repo).collect("SH")
    InstrumentCollector(PagedInstrumentProvider(pages), repo).collect("SH")

    assert repo.audit_log().count("UPSERT 600000.SH") == 1


def test_resume_diff_uses_run_start_baseline_for_accepted_pages() -> None:
    baseline = _instrument("600000", "旧名称")
    changed = _instrument("600000", "新名称")
    added = _instrument("600003", "首批新增")
    tail = _instrument("600001", "后续记录")
    stale = _instrument("600002", "快照外记录")
    repo = InMemoryInstrumentRepository()
    repo.upsert(baseline)
    repo.upsert(stale)

    failing_provider = PagedInstrumentProvider(
        {
            None: Page(items=[changed, added], next_cursor="page-2"),
            "page-2": Page(items=[tail], next_cursor=None),
        },
        fail_cursors={"page-2"},
    )
    with pytest.raises(ProviderUnavailableError):
        InstrumentCollector(failing_provider, repo, max_retries=1).collect(
            "SH", run_id="run-baseline"
        )

    resumed_provider = PagedInstrumentProvider({"page-2": Page(items=[tail], next_cursor=None)})
    result = InstrumentCollector(resumed_provider, repo).collect("SH", run_id="run-baseline")

    assert [item.unified_code for item in result.added] == ["600001.SH", "600003.SH"]
    assert [item.unified_code for item in result.changed] == ["600000.SH"]
    assert [item.unified_code for item in result.delisted] == ["600002.SH"]


def test_checkpoint_baseline_is_deep_copied_and_run_scoped() -> None:
    sh_baseline = _instrument("600000", "基准名称")
    sz_baseline = _instrument("000001", "深市基准", exchange="SZ")
    repo = InMemoryInstrumentRepository()
    repo.save_checkpoint(
        InstrumentCheckpoint(
            exchange="SH",
            run_id="run-1",
            next_cursor="page-2",
            accepted_codes=frozenset(),
            baseline=(sh_baseline,),
        )
    )
    repo.save_checkpoint(
        InstrumentCheckpoint(
            exchange="SZ",
            run_id="run-1",
            next_cursor="page-sz-2",
            accepted_codes=frozenset(),
            baseline=(sz_baseline,),
        )
    )

    sh_baseline.name = "外部修改"
    stored_sh = repo.load_checkpoint("SH", "run-1")
    stored_sz = repo.load_checkpoint("SZ", "run-1")

    assert stored_sh is not None
    assert stored_sz is not None
    assert stored_sh.baseline[0].name == "基准名称"
    assert stored_sz.baseline[0].name == "深市基准"


def test_resume_rejects_cursor_cycle_to_consumed_token() -> None:
    first = _instrument("600000", "第一页")
    second = _instrument("600001", "第二页")
    third = _instrument("600003", "第三页")
    repo = InMemoryInstrumentRepository()
    failing_provider = PagedInstrumentProvider(
        {
            None: Page(items=[first], next_cursor="page-2"),
            "page-2": Page(items=[second], next_cursor="page-3"),
            "page-3": Page(items=[third], next_cursor=None),
        },
        fail_cursors={"page-3"},
    )

    with pytest.raises(ProviderUnavailableError):
        InstrumentCollector(failing_provider, repo, max_retries=1).collect("SH", run_id="run-cycle")

    checkpoint = repo.load_checkpoint("SH", "run-cycle")
    assert checkpoint is not None
    assert checkpoint.next_cursor == "page-3"
    assert checkpoint.consumed_cursors == ("page-2",)

    resumed_provider = PagedInstrumentProvider(
        {"page-3": Page(items=[third], next_cursor="page-2")}
    )
    with pytest.raises(ProviderDataError):
        InstrumentCollector(resumed_provider, repo, max_retries=1).collect("SH", run_id="run-cycle")
    assert resumed_provider.calls == ["page-3"]


def test_active_exchange_run_rejects_different_run_id() -> None:
    first = _instrument("600000", "第一页")
    repo = InMemoryInstrumentRepository()
    failing_provider = PagedInstrumentProvider(
        {None: Page(items=[first], next_cursor="page-2")}, fail_cursors={"page-2"}
    )

    with pytest.raises(ProviderUnavailableError):
        InstrumentCollector(failing_provider, repo, max_retries=1).collect(
            "SH", run_id="run-active"
        )

    conflict_provider = PagedInstrumentProvider({})
    with pytest.raises(ActiveRunConflictError):
        InstrumentCollector(conflict_provider, repo).collect("SH", run_id="run-other")

    assert conflict_provider.calls == []
    assert repo.load_checkpoint("SH", "run-other") is None


def test_completed_run_retry_is_empty_and_does_not_duplicate_audit() -> None:
    current = _instrument("600000", "当前记录")
    stale = _instrument("600001", "应退市")
    repo = InMemoryInstrumentRepository()
    repo.upsert(stale)
    first_provider = PagedInstrumentProvider({None: Page(items=[current], next_cursor=None)})

    first = InstrumentCollector(first_provider, repo).collect("SH", run_id="run-complete")
    audit_after_first = repo.audit_log()
    retry_provider = PagedInstrumentProvider({})
    second = InstrumentCollector(retry_provider, repo).collect("SH", run_id="run-complete")

    assert first.delisted[0].unified_code == "600001.SH"
    assert second.is_empty()
    assert retry_provider.calls == []
    assert repo.audit_log() == audit_after_first


def test_concurrent_run_claim_allows_one_owner_only() -> None:
    repo = InitialCheckpointBarrierRepository()
    providers = {
        run_id: PagedInstrumentProvider(
            {None: Page(items=[_instrument("600000", run_id)], next_cursor=None)}
        )
        for run_id in ("run-a", "run-b")
    }
    outcomes: dict[str, object] = {}

    def execute(run_id: str) -> None:
        try:
            outcomes[run_id] = InstrumentCollector(providers[run_id], repo).collect(
                "SH", run_id=run_id
            )
        except BaseException as exc:  # capture thread failures for assertions
            outcomes[run_id] = exc

    threads = [threading.Thread(target=execute, args=(run_id,)) for run_id in providers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert sum(isinstance(outcome, ActiveRunConflictError) for outcome in outcomes.values()) == 1
    assert sum(not isinstance(outcome, BaseException) for outcome in outcomes.values()) == 1
    failed_run = next(
        run_id for run_id, outcome in outcomes.items() if isinstance(outcome, BaseException)
    )
    assert providers[failed_run].calls == []
    assert repo.load_checkpoint("SH", failed_run) is None


def test_claim_baseline_matches_state_at_atomic_owner_claim() -> None:
    before = _instrument("600000", "鎴戠殑鏃х姸鎬?")
    concurrent = _instrument("600001", "骞惰鏇存柊")
    repo = ClaimSnapshotBarrierRepository()
    repo.upsert(before)
    provider = PagedInstrumentProvider({None: Page(items=[], next_cursor=None)})
    outcomes: list[BaseException] = []

    def execute() -> None:
        try:
            InstrumentCollector(provider, repo).collect("SH", run_id="run-atomic")
        except BaseException as exc:  # capture thread failures for assertions
            outcomes.append(exc)

    thread = threading.Thread(target=execute)
    thread.start()
    assert repo.claim_started.wait(timeout=5)
    repo.upsert(concurrent)
    repo.allow_claim.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert outcomes == []
    checkpoint = repo.load_checkpoint("SH", "run-atomic")
    assert checkpoint is not None
    assert {item.unified_code for item in checkpoint.baseline} == {
        "600000.SH",
        "600001.SH",
    }


def test_reconcile_owner_loss_does_not_delete_new_owner_data() -> None:
    stale = _instrument("600001", "搴旈€€甯傚満")
    replacement = _instrument("600001", "鏂颁富浜烘暟鎹?")
    repo = OwnerLossBeforeReconcileRepository(replacement)
    repo.upsert(stale)
    provider = PagedInstrumentProvider({None: Page(items=[], next_cursor=None)})

    with pytest.raises(ActiveRunConflictError):
        InstrumentCollector(provider, repo).collect("SH", run_id="run-old")

    records = repo.get_all("SH")
    assert records[replacement.unified_code] == replacement
    assert not any("DELIST 600001.SH" in entry for entry in repo.audit_log())


def test_page_commit_failure_does_not_publish_orphan_records() -> None:
    instrument = _instrument("600000", "原子提交")
    repo = FailingCommitRepository()
    provider = PagedInstrumentProvider({None: Page(items=[instrument], next_cursor=None)})

    with pytest.raises(RuntimeError, match="injected page commit failure"):
        InstrumentCollector(provider, repo).collect("SH", run_id="run-commit")

    checkpoint_after_failure = repo.load_checkpoint("SH", "run-commit")
    assert checkpoint_after_failure is not None
    assert checkpoint_after_failure.page_count == 0
    assert checkpoint_after_failure.accepted_codes == frozenset()
    assert checkpoint_after_failure.next_cursor is None
    assert repo.get_all("SH") == {}
    assert repo.audit_log() == []

    result = InstrumentCollector(provider, repo).collect("SH", run_id="run-commit")

    assert [item.unified_code for item in result.added] == ["600000.SH"]
    assert list(repo.get_all("SH")) == ["600000.SH"]
    assert repo.audit_log().count("UPSERT 600000.SH") == 1


def test_stale_or_released_owner_cannot_publish_checkpoint() -> None:
    instrument = _instrument("600000", "鎵€鏈夋潈鍥炴敹")
    repo = InMemoryInstrumentRepository()
    claimed = repo.claim_run("SH", "run-owner")

    committed = repo.commit_page(claimed, (instrument,), None)

    with pytest.raises(ActiveRunConflictError):
        repo.commit_page(claimed, (instrument,), None)

    repo.save_checkpoint(replace(committed, reconciled=True))
    with pytest.raises(ActiveRunConflictError):
        repo.save_checkpoint(replace(committed, reconciled=False))

    assert repo.load_checkpoint("SH", "run-owner") is not None
    repo.clear_checkpoint("SH", "run-owner")
    with pytest.raises(ActiveRunConflictError):
        repo.save_checkpoint(committed)
