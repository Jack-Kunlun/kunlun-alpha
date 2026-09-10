"""P1-N07 direct-daily scan-run proof tests."""

from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from market_core.calendar.authoritative_snapshot import (
    AuthoritativeCalendarError,
    CalendarDay,
    CalendarResolutionReason,
    CalendarResolutionStatus,
    SnapshotTerminal,
    resolve,
)
from market_core.calendar.official_calendar_composition import compose_direct_daily_snapshot
from market_core.calendar.scan_run import (
    SZSE_DIRECT_DAILY_POLICY_ID,
    CalendarScanRunCatalogReceipt,
    CalendarScanRunDay,
    CalendarScanRunError,
    CalendarScanRunManifestReceipt,
    CalendarScanRunPage,
    CalendarScanRunPassReceipt,
    CalendarScanRunReceipt,
    ScanRunCoverageLevel,
    calendar_scan_run_catalog_digest,
    calendar_scan_run_manifest_member_digest,
    calendar_scan_run_pass_id,
    calendar_scan_run_pass_member_digest,
    calendar_scan_run_payload_digest,
    calendar_scan_run_resource_id,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_YEAR = 2026
_RUN_ID = UUID(int=1)
_OPENED = datetime(2026, 9, 6, 8, 0, tzinfo=_SHANGHAI)
_CUTOFF = datetime(2026, 9, 6, 18, 0, tzinfo=_SHANGHAI)


def _digest(number: int) -> str:
    return f"{number:064x}"


def _catalog(month: int, *, run_id: UUID = _RUN_ID) -> CalendarScanRunCatalogReceipt:
    return CalendarScanRunCatalogReceipt(
        run_id=run_id,
        year=_YEAR,
        month=month,
        catalog_id=UUID(int=10_000 + month),
        resource_id=calendar_scan_run_resource_id(_YEAR, month),
        raw_evidence_id=UUID(int=20_000 + month),
        raw_artifact_sha256=_digest(20_000 + month),
        identity_verified=True,
        replay_verified=True,
    )


def _month_days(month: int, *, flip: bool = False) -> tuple[CalendarScanRunDay, ...]:
    count = calendar.monthrange(_YEAR, month)[1]
    return tuple(
        CalendarScanRunDay(
            date=date(_YEAR, month, day),
            is_trading_day=(date(_YEAR, month, day).weekday() < 5) != flip,
        )
        for day in range(1, count + 1)
    )


def _page(
    *,
    pass_number: int,
    month: int,
    run_id: UUID = _RUN_ID,
    source_nowdate: date = date(2026, 9, 6),
    opened_at: datetime = _OPENED,
    observed_at: datetime | None = None,
    available_at: datetime | None = None,
    catalog_id: UUID | None = None,
    days: tuple[CalendarScanRunDay, ...] | None = None,
) -> CalendarScanRunPage:
    page_id = UUID(int=100_000 + (pass_number - 1) * 100 + month)
    page_offset = 1 + (pass_number - 1) * 31
    observed = observed_at or opened_at + timedelta(minutes=page_offset)
    available = available_at or opened_at + timedelta(minutes=page_offset + 1)
    page_days = _month_days(month) if days is None else days
    return CalendarScanRunPage(
        run_id=run_id,
        pass_number=pass_number,
        pass_id=calendar_scan_run_pass_id(run_id, pass_number),
        month=month,
        year=_YEAR,
        page_id=page_id,
        catalog_id=UUID(int=10_000 + month) if catalog_id is None else catalog_id,
        resource_id=calendar_scan_run_resource_id(_YEAR, month),
        raw_evidence_id=UUID(int=200_000 + page_id.int),
        raw_artifact_sha256=_digest(200_000 + page_id.int),
        canonical_payload_sha256=calendar_scan_run_payload_digest(page_days),
        artifact_id=UUID(int=300_000 + page_id.int),
        capture_id=UUID(int=400_000 + page_id.int),
        opened_at=opened_at,
        observed_at=observed,
        available_at=available,
        source_nowdate=source_nowdate,
        identity_verified=True,
        replay_verified=True,
        days=page_days,
    )


def _receipt(
    *,
    source_nowdate: date = date(2026, 9, 6),
    cutoff_at: datetime = _CUTOFF,
    pages: tuple[CalendarScanRunPage, ...] | None = None,
    catalogs: tuple[CalendarScanRunCatalogReceipt, ...] | None = None,
    passes: tuple[CalendarScanRunPassReceipt, ...] | None = None,
    manifest: CalendarScanRunManifestReceipt | None = None,
) -> CalendarScanRunReceipt:
    opened_at = _OPENED
    if source_nowdate.year != _YEAR:
        opened_at = datetime(
            source_nowdate.year,
            source_nowdate.month,
            source_nowdate.day,
            8,
            tzinfo=_SHANGHAI,
        )
    page_values = (
        pages
        if pages is not None
        else tuple(
            _page(
                pass_number=pass_number,
                month=month,
                source_nowdate=source_nowdate,
                opened_at=opened_at,
            )
            for pass_number in (1, 2)
            for month in range(1, 13)
        )
    )
    catalog_values = (
        catalogs if catalogs is not None else tuple(_catalog(month) for month in range(1, 13))
    )
    pass_values = (
        passes
        if passes is not None
        else (
            CalendarScanRunPassReceipt(
                run_id=_RUN_ID,
                pass_number=1,
                pass_id=calendar_scan_run_pass_id(_RUN_ID, 1),
                opened_at=opened_at,
                finished_at=opened_at + timedelta(minutes=30),
                page_refs=tuple(page.page_id for page in page_values[:12]),
                member_digest=calendar_scan_run_pass_member_digest(page_values[:12]),
            ),
            CalendarScanRunPassReceipt(
                run_id=_RUN_ID,
                pass_number=2,
                pass_id=calendar_scan_run_pass_id(_RUN_ID, 2),
                opened_at=opened_at + timedelta(minutes=31),
                finished_at=opened_at + timedelta(minutes=60),
                page_refs=tuple(page.page_id for page in page_values[12:]),
                member_digest=calendar_scan_run_pass_member_digest(page_values[12:]),
            ),
        )
    )
    manifest_digest = calendar_scan_run_manifest_member_digest(
        catalog_values, pass_values, page_values
    )
    return CalendarScanRunReceipt(
        run_id=_RUN_ID,
        authority="SZSE",
        exchange="SZ",
        year=_YEAR,
        parser_version="szse-direct-daily-parser-v1",
        contract_version="calendar-scan-run-v1",
        policy_id=SZSE_DIRECT_DAILY_POLICY_ID,
        compiled_catalog_sha256=calendar_scan_run_catalog_digest(catalog_values),
        opened_at=opened_at,
        cutoff_at=cutoff_at,
        catalog_receipts=catalog_values,
        pass_receipts=pass_values,
        pages=page_values,
        manifest=manifest
        if manifest is not None
        else CalendarScanRunManifestReceipt(
            run_id=_RUN_ID,
            raw_evidence_id=UUID(int=900_000),
            artifact_id=UUID(int=900_001),
            capture_id=UUID(int=900_002),
            raw_artifact_sha256=_digest(900_003),
            canonical_member_digest=manifest_digest,
            finalized_at=cutoff_at,
        ),
    )


def test_valid_two_pass_run_derives_horizon_and_resolves_only_within_it() -> None:
    receipt = _receipt()

    assert receipt.coverage.level is ScanRunCoverageLevel.CONFIRMED_HORIZON
    assert receipt.coverage.confirmed_through == date(2026, 9, 5)
    snapshot = compose_direct_daily_snapshot(snapshot_id=UUID(int=5000), run_receipt=receipt)
    assert snapshot.terminal is SnapshotTerminal.INDETERMINATE
    confirmed = resolve("SZ", date(2026, 9, 4), _CUTOFF, [snapshot])
    future = resolve("SZ", date(2026, 12, 31), _CUTOFF, [snapshot])
    assert confirmed.status is CalendarResolutionStatus.TRADING
    assert future.status is CalendarResolutionStatus.INDETERMINATE
    assert future.reason is CalendarResolutionReason.OFFICIAL_HORIZON_UNCONFIRMED


def test_final_year_requires_post_year_source_nowdate_and_cutoff() -> None:
    cutoff = datetime(2027, 1, 2, 9, 0, tzinfo=_SHANGHAI)
    receipt = _receipt(source_nowdate=date(2027, 1, 2), cutoff_at=cutoff)

    assert receipt.coverage.level is ScanRunCoverageLevel.FINAL_YEAR
    assert receipt.coverage.confirmed_through == date(2026, 12, 31)
    snapshot = compose_direct_daily_snapshot(snapshot_id=UUID(int=5001), run_receipt=receipt)
    assert snapshot.terminal is SnapshotTerminal.COMPLETE


def test_wrong_run_pass_and_identity_are_rejected() -> None:
    pages = list(_receipt().pages)
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        pages[0] = replace(pages[0], run_id=UUID(int=7000))

    bad_catalog = replace(_catalog(1), identity_verified=False)
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        _receipt(catalogs=(bad_catalog,))


@pytest.mark.parametrize("bad_month", [0, 13])
def test_month_out_of_range_is_rejected(bad_month: int) -> None:
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        _page(pass_number=1, month=bad_month, days=_month_days(1))


def test_missing_duplicate_cross_month_and_pass_digest_mismatch_are_rejected() -> None:
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        _page(pass_number=1, month=2, days=_month_days(1))

    pages = list(_receipt().pages)
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        pages[1] = replace(pages[1], month=1)

    pages = list(_receipt().pages)
    flipped = _month_days(1, flip=True)
    pages[12] = _page(pass_number=2, month=1, days=flipped)
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        _receipt(pages=tuple(pages))


def test_source_nowdate_page_time_manifest_and_proof_digest_mismatches_fail_closed() -> None:
    pages = list(_receipt().pages)
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        pages[3] = replace(pages[3], source_nowdate=date(2026, 9, 7))

    pages = list(_receipt().pages)
    pages[4] = replace(pages[4], available_at=_CUTOFF + timedelta(minutes=1))
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        _receipt(pages=tuple(pages))

    pages = list(_receipt().pages)
    pages[5] = replace(pages[5], opened_at=_OPENED - timedelta(minutes=1))
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        _receipt(pages=tuple(pages))

    source = _receipt()
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        replace(
            source,
            manifest=replace(source.manifest, canonical_member_digest=_digest(9998)),
        )

    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        replace(source, proof_digest=_digest(9999))


def test_scan_run_is_not_available_for_sh_or_bj_positive_proof() -> None:
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        replace(_receipt(), authority="SSE", exchange="SH")
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        replace(_receipt(), authority="BSE", exchange="BJ")


def test_direct_snapshot_cannot_claim_complete_with_arbitrary_days() -> None:
    receipt = _receipt()
    snapshot = compose_direct_daily_snapshot(snapshot_id=UUID(int=5002), run_receipt=receipt)
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        replace(
            snapshot,
            terminal=SnapshotTerminal.COMPLETE,
            days=tuple(
                replace(day, is_trading_day=True, reason=None)
                for day in cast(tuple[CalendarDay, ...], snapshot.days)
            ),
        )


def test_snapshot_is_not_visible_before_run_cutoff() -> None:
    receipt = _receipt()
    snapshot = compose_direct_daily_snapshot(snapshot_id=UUID(int=5003), run_receipt=receipt)
    before = resolve("SZ", date(2026, 9, 4), _CUTOFF - timedelta(minutes=1), [snapshot])
    after = resolve("SZ", date(2026, 9, 4), _CUTOFF, [snapshot])
    assert before.reason is CalendarResolutionReason.NO_VISIBLE_OFFICIAL
    assert after.status is CalendarResolutionStatus.TRADING


def test_scan_run_requires_fixed_month_catalogs_and_independent_pass_manifest() -> None:
    """Red contract: legacy one-catalog/one-primary-page receipts are invalid."""

    assert calendar_scan_run_resource_id(_YEAR, 1).endswith("-01")
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        CalendarScanRunPassReceipt(  # type: ignore[call-arg]
            run_id=_RUN_ID,
            pass_number=1,
            pass_id=calendar_scan_run_pass_id(_RUN_ID, 1),
            opened_at=_OPENED,
            finished_at=_OPENED + timedelta(minutes=1),
            page_refs=(),
            member_digest=_digest(1),
        )
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        CalendarScanRunManifestReceipt(  # type: ignore[call-arg]
            run_id=_RUN_ID,
            raw_evidence_id=UUID(int=1),
            artifact_id=UUID(int=1),
            capture_id=UUID(int=3),
            raw_artifact_sha256=_digest(1),
            canonical_member_digest=_digest(2),
            finalized_at=_CUTOFF,
        )


def test_catalog_digest_and_resource_mapping_are_recomputed() -> None:
    source = _receipt()
    catalogs = list(source.catalog_receipts)
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        replace(catalogs[1], resource_id=calendar_scan_run_resource_id(_YEAR, 1))
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        _receipt(catalogs=(catalogs[0],))
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        replace(source, compiled_catalog_sha256=_digest(9910))


def test_old_pages_with_a_future_cutoff_remain_horizon_only() -> None:
    future_cutoff = datetime(2027, 1, 2, 18, 0, tzinfo=_SHANGHAI)
    source = _receipt(cutoff_at=future_cutoff)

    assert source.coverage.level is ScanRunCoverageLevel.CONFIRMED_HORIZON
    assert source.coverage.confirmed_through == date(2026, 9, 5)
    assert (
        compose_direct_daily_snapshot(snapshot_id=UUID(int=5004), run_receipt=source).terminal
        is SnapshotTerminal.INDETERMINATE
    )


def test_page_identity_is_unique_across_both_passes() -> None:
    source = _receipt()
    pages = list(source.pages)
    pages[12] = replace(pages[12], artifact_id=pages[0].artifact_id)
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        _receipt(pages=tuple(pages))

    pages = list(source.pages)
    pages[12] = replace(pages[12], capture_id=pages[0].capture_id)
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        _receipt(pages=tuple(pages))


def test_pass_receipts_bind_order_window_and_member_digest() -> None:
    source = _receipt()
    passes = list(source.pass_receipts)
    passes[0] = replace(passes[0], member_digest=_digest(9920))
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        _receipt(passes=tuple(passes))

    passes = list(source.pass_receipts)
    passes[1] = replace(passes[1], page_refs=tuple(reversed(passes[1].page_refs)))
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        _receipt(passes=tuple(passes))

    passes = list(source.pass_receipts)
    passes[0] = replace(passes[0], finished_at=passes[1].opened_at)
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        _receipt(passes=tuple(passes))


def test_manifest_is_the_only_primary_provenance_anchor() -> None:
    source = _receipt()
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        _receipt(
            manifest=replace(
                source.manifest,
                raw_evidence_id=source.pages[0].raw_evidence_id,
            )
        )
    with pytest.raises(CalendarScanRunError, match="invalid calendar scan run"):
        _receipt(
            manifest=replace(
                source.manifest,
                artifact_id=source.pages[0].artifact_id,
            )
        )


def test_snapshot_terminal_must_match_run_coverage() -> None:
    horizon = compose_direct_daily_snapshot(snapshot_id=UUID(int=5005), run_receipt=_receipt())
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        replace(horizon, terminal=SnapshotTerminal.COMPLETE)

    final = compose_direct_daily_snapshot(
        snapshot_id=UUID(int=5006),
        run_receipt=_receipt(
            source_nowdate=date(2027, 1, 2),
            cutoff_at=datetime(2027, 1, 2, 9, 0, tzinfo=_SHANGHAI),
        ),
    )
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        replace(final, terminal=SnapshotTerminal.INDETERMINATE)
