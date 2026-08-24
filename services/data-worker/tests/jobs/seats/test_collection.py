from datetime import UTC, date, datetime
from decimal import Decimal
from inspect import signature
from json import dumps
from threading import Barrier, Thread

import pytest
from data_worker.jobs.seats import (
    BatchConflictError,
    InMemorySeatRepository,
    RawSeatListRecord,
    RevisionConflictError,
    SeatCollectionJob,
    SeatCollectionRequest,
    SeatFetchRequest,
    SeatProviderBatch,
    SeatRepository,
)
from seat_core import Alias, AliasType, SeatKind, SeatProfile
from seat_core.resolution import ResolutionStatus

T0 = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
T1 = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)
T2 = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
TRADE_DATE = date(2026, 8, 21)


def profile(identity_key: str, *, seat_kind: SeatKind = SeatKind.BROKER_BRANCH) -> SeatProfile:
    return SeatProfile.from_identity(
        identity_key,
        canonical_name=identity_key,
        seat_kind=seat_kind,
        valid_from=T0,
        valid_to=None,
        available_time=T0,
        revision_id=f"{identity_key}-profile-v1",
        source="seat-master",
        source_version="2026-08",
        evidence_id=f"profile-evidence-{identity_key}",
    )


def alias(alias_id: str, seat_id: str, name: str, *, available_time: datetime = T0) -> Alias:
    return Alias(
        alias_id=alias_id,
        seat_id=seat_id,
        name=name,
        alias_type=AliasType.SOURCE,
        valid_from=T0,
        valid_to=None,
        available_time=available_time,
        source="seat-alias-source",
        source_version="2026-08",
        evidence_id=f"alias-evidence-{alias_id}",
        revision_id=f"{alias_id}-v1",
    )


def raw_record(
    revision_id: str,
    *,
    previous_revision_id: str | None = None,
    raw_seat_name: str = "Alpha Securities营业部",
    raw_instrument_id: str = "SH.600519",
    buy_amount: str = "100.00",
    sell_amount: str = "40.00",
    vendor_net_amount: str = "60.00",
    available_time: datetime = T1,
    payload_suffix: str = "base",
    seat_kind_hint: SeatKind | None = SeatKind.BROKER_BRANCH,
    source: str = "dragon-tiger-fake",
    source_version: str = "2026-08",
) -> RawSeatListRecord:
    payload = dumps(
        {
            "seat": raw_seat_name,
            "instrument": raw_instrument_id,
            "buy": buy_amount,
            "sell": sell_amount,
            "net": vendor_net_amount,
            "suffix": payload_suffix,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return RawSeatListRecord.from_provider(
        source=source,
        source_version=source_version,
        trade_date=TRADE_DATE,
        event_time=T0,
        publish_time=T0,
        ingest_time=T1,
        available_time=available_time,
        raw_seat_name=raw_seat_name,
        listing_reason="连续三个交易日内收盘价格涨幅偏离值累计达到20%",
        raw_instrument_id=raw_instrument_id,
        buy_amount=buy_amount,
        sell_amount=sell_amount,
        vendor_net_amount=vendor_net_amount,
        raw_payload=payload,
        revision_id=revision_id,
        previous_revision_id=previous_revision_id,
        seat_kind_hint=seat_kind_hint,
    )


class FakeProvider:
    def __init__(
        self, batch: SeatProviderBatch | None = None, error: Exception | None = None
    ) -> None:
        self.batch = batch
        self.error = error
        self.calls = 0

    def fetch(self, request: SeatFetchRequest) -> SeatProviderBatch:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.batch is not None
        assert self.batch.batch_id == request.batch_id
        return self.batch


def make_job(
    provider: FakeProvider,
    repository: InMemorySeatRepository | None = None,
    *,
    profiles: tuple[SeatProfile, ...] | None = None,
    aliases: tuple[Alias, ...] | None = None,
) -> tuple[SeatCollectionJob, InMemorySeatRepository]:
    repo = repository or InMemorySeatRepository()
    profile_value = profiles or (profile("broker:alpha-001"),)
    alias_value = aliases or (alias("alpha-1", profile_value[0].seat_id, "Alpha Securities营业部"),)
    return SeatCollectionJob(provider, repo, profile_value, alias_value), repo


def request(
    batch_id: str,
    *,
    decision_time: datetime = T1,
    source: str = "dragon-tiger-fake",
    source_version: str = "2026-08",
    expected_previous_checkpoint: str | None = None,
) -> SeatCollectionRequest:
    return SeatCollectionRequest(
        batch_id=batch_id,
        trade_date=TRADE_DATE,
        decision_time=decision_time,
        source=source,
        source_version=source_version,
        expected_previous_checkpoint=expected_previous_checkpoint,
    )


def batch(
    batch_id: str,
    *records: RawSeatListRecord,
    checkpoint: str | None = "cp-1",
    source: str = "dragon-tiger-fake",
    source_version: str = "2026-08",
) -> SeatProviderBatch:
    return SeatProviderBatch(
        batch_id=batch_id,
        source=source,
        source_version=source_version,
        records=records,
        checkpoint_token=checkpoint,
    )


def test_collects_normalized_trade_with_raw_and_source_evidence() -> None:
    record = raw_record("rev-1")
    provider = FakeProvider(batch("batch-1", record))
    job, repository = make_job(provider)

    result = job.run(request("batch-1"))

    assert len(result.raw_records) == 1
    assert len(result.normalized_trades) == 1
    normalized = result.normalized_trades[0]
    assert normalized.trade.instrument_id == "600519.SH"
    assert normalized.trade.buy_amount == Decimal("100.00")
    assert normalized.trade.sell_amount == Decimal("40.00")
    assert normalized.trade.net_amount == Decimal("60.00")
    assert normalized.trade.raw_record_id == record.raw_record_id
    assert normalized.listing_reason == record.listing_reason
    assert normalized.provider_evidence_id == record.evidence_id
    assert normalized.seat_evidence_ids == ("alias-evidence-alpha-1",)
    assert repository.checkpoint(request("batch-1").checkpoint_route) == "cp-1"


def test_exact_duplicate_retry_is_idempotent_after_refetch() -> None:
    record = raw_record("rev-1")
    provider = FakeProvider(batch("batch-1", record))
    job, _ = make_job(provider)

    first = job.run(request("batch-1"))
    second = job.run(request("batch-1"))

    assert second == first
    assert provider.calls == 2


def test_checkpoint_fence_rejects_stale_expected_previous_checkpoint() -> None:
    repository = InMemorySeatRepository()
    first_job, _ = make_job(
        FakeProvider(batch("batch-fence-1", raw_record("rev-fence-1"))), repository
    )
    first_job.run(request("batch-fence-1"))

    second_job, _ = make_job(
        FakeProvider(batch("batch-fence-2", raw_record("rev-fence-2"))), repository
    )
    with pytest.raises(BatchConflictError, match="checkpoint"):
        second_job.run(request("batch-fence-2", expected_previous_checkpoint="stale-checkpoint"))
    assert repository.checkpoint(request("batch-fence-2").checkpoint_route) == "cp-1"
    assert len(repository.raw_records) == 1
    assert len(repository.normalized_trades) == 1


def test_exact_duplicate_record_in_a_new_batch_does_not_duplicate_or_downgrade() -> None:
    record = raw_record("rev-1")
    repository = InMemorySeatRepository()
    first_job, _ = make_job(FakeProvider(batch("batch-1", record)), repository)
    first = first_job.run(request("batch-1"))

    duplicate_job, _ = make_job(
        FakeProvider(batch("batch-duplicate", record, checkpoint="cp-duplicate")),
        repository,
    )
    duplicate = duplicate_job.run(request("batch-duplicate", expected_previous_checkpoint="cp-1"))

    assert duplicate.normalized_trades == first.normalized_trades
    assert duplicate.rejected_records == ()
    assert len(repository.raw_records) == 1
    assert len(repository.normalized_trades) == 1
    assert repository.checkpoint(request("batch-duplicate").checkpoint_route) == "cp-duplicate"


def test_request_and_batch_fingerprints_cover_pit_and_immutable_provider_content() -> None:
    record = raw_record("rev-fingerprint")
    provider_batch = batch("batch-fingerprint", record)
    changed_request = request("batch-fingerprint", decision_time=T0)
    changed_source = request("batch-fingerprint", source="other-provider")
    changed_batch = batch(
        "batch-fingerprint",
        raw_record("rev-fingerprint", payload_suffix="changed"),
        checkpoint="cp-2",
    )

    assert request("batch-fingerprint").request_fingerprint != changed_request.request_fingerprint
    assert request("batch-fingerprint").request_fingerprint != changed_source.request_fingerprint
    assert provider_batch.batch_fingerprint != changed_batch.batch_fingerprint


def test_collector_fetches_before_batch_id_idempotency_and_rejects_pit_or_content_conflicts() -> (
    None
):
    record = raw_record("rev-pit")
    provider = FakeProvider(batch("batch-pit", record))
    job, repository = make_job(provider)

    first = job.run(request("batch-pit"))
    assert first.request_fingerprint == request("batch-pit").request_fingerprint
    provider_batch = provider.batch
    assert provider_batch is not None
    assert first.batch_fingerprint == provider_batch.batch_fingerprint

    with pytest.raises(BatchConflictError):
        job.run(request("batch-pit", decision_time=T0))
    assert provider.calls == 2

    provider.batch = batch(
        "batch-pit",
        raw_record("rev-pit", payload_suffix="changed"),
        checkpoint="cp-changed",
    )
    with pytest.raises(BatchConflictError):
        job.run(request("batch-pit"))
    assert provider.calls == 3
    assert repository.checkpoint(request("batch-pit").checkpoint_route) == "cp-1"


def test_provider_batch_deduplicates_exact_records_and_rejects_conflicting_duplicates() -> None:
    record = raw_record("rev-duplicate")
    duplicate = batch("batch-duplicate-input", record, record)
    assert duplicate.records == (record,)

    with pytest.raises(RevisionConflictError):
        batch(
            "batch-conflicting-input",
            record,
            raw_record("rev-duplicate", payload_suffix="different"),
        )


def test_batch_result_rejects_duplicate_outputs_and_job_uses_repository_protocol() -> None:
    repository_annotation = (
        signature(SeatCollectionJob.__init__).parameters["repository"].annotation
    )
    assert "SeatRepository" in str(repository_annotation)
    assert SeatRepository is not InMemorySeatRepository

    record = raw_record("rev-output")
    job, _ = make_job(FakeProvider(batch("batch-output", record)))
    result = job.run(request("batch-output"))
    with pytest.raises(ValueError, match="duplicate"):
        result.__class__(
            batch_id=result.batch_id,
            raw_records=(record, record),
            normalized_trades=result.normalized_trades,
            rejected_records=result.rejected_records,
            checkpoint_token=result.checkpoint_token,
            request_fingerprint=result.request_fingerprint,
            batch_fingerprint=result.batch_fingerprint,
            route_key=result.route_key,
        )


def test_same_revision_different_payload_conflicts_without_overwriting_history() -> None:
    repository = InMemorySeatRepository()
    first_provider = FakeProvider(batch("batch-1", raw_record("rev-1")))
    first_job, _ = make_job(first_provider, repository)
    first_job.run(request("batch-1"))

    conflicting = raw_record(
        "rev-1", buy_amount="101.00", vendor_net_amount="61.00", payload_suffix="changed"
    )
    second_provider = FakeProvider(batch("batch-2", conflicting, checkpoint="cp-2"))
    second_job, _ = make_job(second_provider, repository)

    with pytest.raises(RevisionConflictError):
        second_job.run(request("batch-2", expected_previous_checkpoint="cp-1"))

    assert repository.raw_records[0].buy_amount == Decimal("100.00")
    assert repository.checkpoint(request("batch-2").checkpoint_route) == "cp-1"


def test_valid_revision_is_appended_and_missing_or_out_of_order_predecessor_is_quarantined() -> (
    None
):
    repository = InMemorySeatRepository()
    base_job, _ = make_job(FakeProvider(batch("batch-1", raw_record("rev-1"))), repository)
    base_job.run(request("batch-1"))

    corrected = raw_record(
        "rev-2",
        previous_revision_id="rev-1",
        buy_amount="110.00",
        vendor_net_amount="70.00",
        payload_suffix="revision",
    )
    correction_job, _ = make_job(
        FakeProvider(batch("batch-2", corrected, checkpoint="cp-2")), repository
    )
    correction_result = correction_job.run(request("batch-2", expected_previous_checkpoint="cp-1"))
    assert len(repository.raw_records) == 2
    assert len(correction_result.normalized_trades) == 1

    fork = raw_record(
        "rev-fork",
        previous_revision_id="rev-1",
        buy_amount="120.00",
        vendor_net_amount="80.00",
        payload_suffix="stale-fork",
    )
    fork_job, _ = make_job(
        FakeProvider(batch("batch-fork", fork, checkpoint="cp-fork")), repository
    )
    fork_result = fork_job.run(request("batch-fork", expected_previous_checkpoint="cp-2"))
    assert fork_result.normalized_trades == ()
    assert fork_result.rejected_records[0].reason == "stale_previous_revision"

    missing = raw_record(
        "rev-missing", previous_revision_id="not-present", payload_suffix="missing"
    )
    missing_job, _ = make_job(
        FakeProvider(batch("batch-3", missing, checkpoint="cp-3")), repository
    )
    missing_result = missing_job.run(request("batch-3", expected_previous_checkpoint="cp-fork"))
    assert missing_result.rejected_records[0].reason == "missing_previous_revision"
    assert repository.checkpoint(request("batch-3").checkpoint_route) == "cp-3"

    parent = raw_record("rev-4", previous_revision_id="rev-2", payload_suffix="parent")
    child = raw_record("rev-5", previous_revision_id="rev-4", payload_suffix="child")
    ordered_job, _ = make_job(
        FakeProvider(batch("batch-4", child, parent, checkpoint="cp-4")), repository
    )
    ordered_result = ordered_job.run(request("batch-4", expected_previous_checkpoint="cp-3"))
    assert any(item.reason == "out_of_order_revision" for item in ordered_result.rejected_records)
    assert any(item.trade.revision_id == "rev-4" for item in ordered_result.normalized_trades)


def test_revision_identity_is_scoped_by_provider_source() -> None:
    repository = InMemorySeatRepository()
    first_record = raw_record("rev-shared", source="provider-a")
    first_job, _ = make_job(
        FakeProvider(batch("batch-source-a", first_record, source="provider-a")), repository
    )
    first_job.run(request("batch-source-a", source="provider-a"))

    second_record = raw_record("rev-shared", source="provider-b")
    second_job, _ = make_job(
        FakeProvider(batch("batch-source-b", second_record, source="provider-b")), repository
    )
    second_result = second_job.run(request("batch-source-b", source="provider-b"))

    assert len(second_result.normalized_trades) == 1
    assert len(repository.raw_records) == 2


def test_commit_revalidates_revision_chain_after_concurrent_prechecks() -> None:
    barrier = Barrier(2)

    class CoordinatedRepository(InMemorySeatRepository):
        synchronize = False

        def revision_rejections(
            self,
            records: tuple[RawSeatListRecord, ...],
            *,
            route_key: str | None = None,
        ) -> dict[str, str]:
            result = super().revision_rejections(records, route_key=route_key)
            if self.synchronize:
                barrier.wait(timeout=2)
            return result

    repository = CoordinatedRepository()
    base = raw_record("rev-concurrent-base")
    base_job, _ = make_job(FakeProvider(batch("batch-concurrent-base", base)), repository)
    base_job.run(request("batch-concurrent-base"))
    repository.synchronize = True

    left = raw_record("rev-concurrent-left", previous_revision_id="rev-concurrent-base")
    right = raw_record("rev-concurrent-right", previous_revision_id="rev-concurrent-base")
    left_job, _ = make_job(FakeProvider(batch("batch-concurrent-left", left)), repository)
    right_job, _ = make_job(FakeProvider(batch("batch-concurrent-right", right)), repository)
    failures: list[BaseException] = []

    def run(job: SeatCollectionJob, batch_id: str) -> None:
        try:
            job.run(request(batch_id, expected_previous_checkpoint="cp-1"))
        except BaseException as error:
            failures.append(error)

    threads = (
        Thread(target=run, args=(left_job, "batch-concurrent-left")),
        Thread(target=run, args=(right_job, "batch-concurrent-right")),
    )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert len(failures) == 1
    assert isinstance(failures[0], BatchConflictError)
    assert str(failures[0]) == "revision chain changed before atomic commit"
    assert len(repository.raw_records) == 2
    assert repository.checkpoint(request("batch-concurrent-base").checkpoint_route) == "cp-1"


def test_amount_reconciliation_and_negative_values_are_quarantined_without_silent_fix() -> None:
    mismatch = raw_record("rev-bad-net", vendor_net_amount="61.00", payload_suffix="bad-net")
    negative = raw_record(
        "rev-negative",
        buy_amount="-1.00",
        sell_amount="0.00",
        vendor_net_amount="-1.00",
        raw_instrument_id="SZ.000001",
        payload_suffix="negative",
    )
    provider = FakeProvider(batch("batch-amounts", mismatch, negative))
    job, repository = make_job(provider)

    result = job.run(request("batch-amounts"))

    assert result.normalized_trades == ()
    assert {item.reason for item in result.rejected_records} == {
        "vendor_net_mismatch",
        "negative_amount",
    }
    assert len(repository.raw_records) == 2
    assert repository.checkpoint(request("batch-amounts").checkpoint_route) == "cp-1"


def test_review_reject_and_future_alias_never_create_trade() -> None:
    alpha = profile("broker:alpha-001")
    beta = profile("broker:beta-002")
    shared_aliases = (
        alias("shared-alpha", alpha.seat_id, "Shared Securities营业部"),
        alias("shared-beta", beta.seat_id, "Shared Securities营业部"),
    )
    review_record = raw_record("rev-review", raw_seat_name="Shared Securities营业部")
    review_job, _ = make_job(
        FakeProvider(batch("batch-review", review_record)),
        profiles=(alpha, beta),
        aliases=shared_aliases,
    )
    review_result = review_job.run(request("batch-review"))
    assert review_result.normalized_trades == ()
    assert review_result.rejected_records[0].reason == "seat_resolution_review"
    assert review_result.rejected_records[0].resolution_status is ResolutionStatus.REVIEW
    assert len(review_result.rejected_records[0].candidate_seat_ids) == 2

    future_alias = alias(
        "future-alpha", alpha.seat_id, "Future Securities营业部", available_time=T2
    )
    future_record = raw_record(
        "rev-future",
        raw_seat_name="Future Securities营业部",
        available_time=T1,
    )
    future_job, _ = make_job(
        FakeProvider(batch("batch-future", future_record)),
        profiles=(alpha,),
        aliases=(future_alias,),
    )
    future_result = future_job.run(request("batch-future", decision_time=T1))
    assert future_result.normalized_trades == ()
    assert future_result.rejected_records[0].reason == "seat_resolution_reject"
    assert future_result.rejected_records[0].candidate_seat_ids == ()


def test_provider_or_atomic_batch_conflict_does_not_commit_partial_records() -> None:
    repository = InMemorySeatRepository()
    provider = FakeProvider(error=RuntimeError("provider unavailable"))
    job, _ = make_job(provider, repository)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        job.run(request("batch-failed"))
    assert repository.raw_records == ()
    assert repository.normalized_trades == ()
    assert repository.checkpoint(request("batch-failed").checkpoint_route) is None

    first = raw_record("rev-atomic-1", payload_suffix="one")
    base_job, _ = make_job(FakeProvider(batch("batch-atomic-base", first)), repository)
    base_job.run(request("batch-atomic-base"))
    conflicting = raw_record(
        "rev-atomic-1", buy_amount="101.00", vendor_net_amount="61.00", payload_suffix="two"
    )
    new_record = raw_record("rev-atomic-2", payload_suffix="new")
    conflict_job, _ = make_job(
        FakeProvider(batch("batch-conflict", conflicting, new_record, checkpoint="cp-conflict")),
        repository,
    )
    with pytest.raises(RevisionConflictError):
        conflict_job.run(request("batch-conflict", expected_previous_checkpoint="cp-1"))
    assert repository.raw_records == (first,)
    assert repository.raw_records[0].buy_amount == Decimal("100.00")
    assert all(record.raw_record_id != "rev-atomic-2" for record in repository.raw_records)
    assert repository.checkpoint(request("batch-conflict").checkpoint_route) == "cp-1"


def test_raw_record_requires_timezone_aware_times() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        raw_record("rev-naive", available_time=datetime(2026, 8, 25, 8, 0))
