"""P1-N07 authoritative full-day calendar resolution contract."""

from __future__ import annotations

import calendar
import traceback
from collections.abc import Iterable, Iterator
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, tzinfo
from uuid import UUID, uuid4

import pytest
from ashare_contracts.calendar_trading_day import Exchange as ContractExchange
from ashare_contracts.calendar_trading_day import Reason as ContractReason
from ashare_contracts.calendar_trading_day import TradingDay
from market_core.calendar.authoritative_snapshot import (
    AuthoritativeCalendarError,
    CalendarAnnualNotice,
    CalendarCoverage,
    CalendarCoverageLevel,
    CalendarDay,
    CalendarDayReason,
    CalendarEvidence,
    CalendarEvidenceKind,
    CalendarResolutionReason,
    CalendarResolutionStatus,
    CalendarRuleCoverage,
    CalendarRuleProfile,
    CalendarScanBundle,
    CalendarScanObservation,
    CalendarScanPage,
    CalendarScope,
    CalendarSnapshot,
    ExchangeCode,
    OfficialAuthority,
    SecondaryCalendarObservation,
    SnapshotTerminal,
    compose_official_calendar,
    resolve,
)

_BASE = datetime(2026, 1, 1, 0, tzinfo=UTC)
_SENTINEL = "untrusted-timezone-secret"


def _assert_fixed_error(error: AuthoritativeCalendarError) -> None:
    rendered = "".join(traceback.format_exception(error))
    assert _SENTINEL not in rendered
    assert error.__context__ is None
    assert error.__cause__ is None


class _ExplodingTimezone(tzinfo):
    def utcoffset(self, _value: datetime | None) -> timedelta:
        raise RuntimeError(_SENTINEL)

    def dst(self, _value: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, _value: datetime | None) -> str:
        return "exploding"


class _ExplodingDays:
    def __iter__(self) -> Iterator[object]:
        raise RuntimeError(_SENTINEL)


class _ExplodingSnapshots:
    def __iter__(self) -> Iterator[CalendarSnapshot]:
        raise RuntimeError(_SENTINEL)


class _ExplodingSecondary:
    def __iter__(self) -> Iterator[SecondaryCalendarObservation]:
        raise RuntimeError(_SENTINEL)


def _digest(number: int) -> str:
    return f"{number:064x}"


def _trusted_evidence(
    number: int,
    kind: CalendarEvidenceKind,
    *,
    exchange: ExchangeCode = "SH",
    year: int = 2026,
    available_at: datetime = _BASE + timedelta(hours=2),
) -> CalendarEvidence:
    authority = {
        "SH": OfficialAuthority.SSE,
        "SZ": OfficialAuthority.SZSE,
        "BJ": OfficialAuthority.BSE,
    }[exchange]
    return CalendarEvidence(
        evidence_id=UUID(int=number),
        artifact_sha256=_digest(number),
        kind=kind,
        authority=authority,
        scope=CalendarScope(exchange=exchange, year=year),
        captured_at=available_at - timedelta(hours=1),
        available_at=available_at,
        source_url=f"https://official.example/{exchange.lower()}/{number}",
        document_id=f"{exchange.lower()}-{year}-{number}",
        title=f"Official {exchange} evidence",
        issuer=authority.value,
        identity_verified=True,
        artifact_id=UUID(int=100_000 + number),
        capture_id=UUID(int=200_000 + number),
    )


def _all_days(
    year: int,
    *,
    exchange: ContractExchange = ContractExchange.sh,
    non_trading: Iterable[date] = (),
) -> list[TradingDay]:
    closed = set(non_trading)
    count = 366 if calendar.isleap(year) else 365
    first_ordinal = date(year, 1, 1).toordinal()
    rows: list[TradingDay] = []
    for offset in range(count):
        current = date.fromordinal(first_ordinal + offset)
        is_trading = current not in closed
        rows.append(
            TradingDay(
                date=current,
                exchange=exchange,
                isTradingDay=is_trading,
                reason=None if is_trading else ContractReason.public_holiday,
            )
        )
    return rows


def _snapshot(
    *,
    version: int = 1,
    year: int = 2026,
    exchange: ExchangeCode = "SH",
    authority: OfficialAuthority = OfficialAuthority.SSE,
    available_at: datetime = _BASE + timedelta(hours=2),
    terminal: SnapshotTerminal = SnapshotTerminal.COMPLETE,
    days: Iterable[TradingDay] | None = None,
    supersedes: UUID | None = None,
) -> CalendarSnapshot:
    if type(terminal) is not SnapshotTerminal:
        raise AuthoritativeCalendarError("invalid calendar snapshot")
    rows = (
        list(days)
        if days is not None
        else _all_days(
            year,
            exchange={
                "SH": ContractExchange.sh,
                "SZ": ContractExchange.sz,
                "BJ": ContractExchange.bj,
            }[exchange],
        )
    )
    annual = _trusted_evidence(
        10000 + version,
        CalendarEvidenceKind.ANNUAL_NOTICE,
        exchange=exchange,
        year=year,
        available_at=available_at,
    )
    rule_before = _trusted_evidence(
        11000 + version,
        CalendarEvidenceKind.RULE,
        exchange=exchange,
        year=year,
        available_at=available_at,
    )
    rule_after = _trusted_evidence(
        12000 + version,
        CalendarEvidenceKind.RULE,
        exchange=exchange,
        year=year,
        available_at=available_at,
    )
    scan = _trusted_evidence(
        13000 + version,
        CalendarEvidenceKind.TEMPORARY_SCAN,
        exchange=exchange,
        year=year,
        available_at=available_at,
    )
    assert scan.artifact_id is not None
    assert scan.capture_id is not None
    scan_page = CalendarScanPage(
        ordinal=1,
        evidence=scan,
        cursor_in=None,
        cursor_out=None,
    )
    scan_bundle = CalendarScanBundle(
        bundle_id=UUID(int=14000 + version),
        authority=authority,
        scope=CalendarScope(exchange=exchange, year=year),
        pages=(scan_page,),
        evidence_ids=(scan.evidence_id,),
        artifact_sha256s=(scan.artifact_sha256,),
        window_start=date(year, 1, 1),
        window_end=date(year, 12, 31),
        page_count=1,
        replayable=True,
        continuity_verified=True,
        complete=True,
        covers_full_exchange=True,
        captured_at=available_at - timedelta(hours=1),
        available_at=available_at,
    )
    full_dates = tuple(row.date for row in rows)
    expected_dates = tuple(
        date.fromordinal(date(year, 1, 1).toordinal() + offset)
        for offset in range(366 if calendar.isleap(year) else 365)
    )
    if len(rows) == len(expected_dates) and full_dates == expected_dates:
        closed_dates = tuple(
            row.date for row in rows if not row.is_trading_day or row.date.weekday() >= 5
        )
        annual_notice = CalendarAnnualNotice(
            evidence=annual,
            closed_dates=closed_dates,
        )
        if year == 2026:
            rules = (
                CalendarRuleCoverage(
                    evidence=rule_before,
                    valid_from=date(year, 1, 1),
                    valid_to=date(year, 7, 5),
                    weekdays=(0, 1, 2, 3, 4),
                    closes_legal_holidays=True,
                ),
                CalendarRuleCoverage(
                    evidence=rule_after,
                    valid_from=date(year, 7, 6),
                    valid_to=date(year, 12, 31),
                    weekdays=(0, 1, 2, 3, 4),
                    closes_legal_holidays=True,
                ),
            )
            profile = CalendarRuleProfile(
                scope=CalendarScope(exchange=exchange, year=year),
                required_rule_starts=(date(2026, 7, 6),),
            )
        else:
            rules = (
                CalendarRuleCoverage(
                    evidence=rule_before,
                    valid_from=date(year, 1, 1),
                    valid_to=date(year, 12, 31),
                    weekdays=(0, 1, 2, 3, 4),
                    closes_legal_holidays=True,
                ),
            )
            profile = None
        scan_days = tuple(
            CalendarDay(
                date=current,
                exchange=exchange,
                is_trading_day=current.weekday() < 5 and current not in set(closed_dates),
                reason=(
                    CalendarDayReason.PUBLIC_HOLIDAY
                    if current in set(closed_dates) and current.weekday() < 5
                    else CalendarDayReason.WEEKEND
                    if current.weekday() >= 5
                    else None
                ),
            )
            for current in expected_dates
        )
        scan_observation = CalendarScanObservation(
            bundle=scan_bundle,
            evidence=scan,
            days=scan_days,
        )
        year_end = datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC)
        if available_at >= year_end:
            coverage_level = CalendarCoverageLevel.FINAL_YEAR
            confirmed_through = date(year, 12, 31)
        elif available_at.year == year:
            coverage_level = CalendarCoverageLevel.CONFIRMED_HORIZON
            confirmed_through = available_at.astimezone(UTC).date()
        else:
            coverage_level = CalendarCoverageLevel.INDETERMINATE
            confirmed_through = date(year, 1, 1)
        snapshot = compose_official_calendar(
            snapshot_id=UUID(int=version),
            authority=authority,
            scope=CalendarScope(exchange=exchange, year=year),
            annual_notice=annual_notice,
            rules=rules,
            scan=scan_observation,
            captured_at=available_at - timedelta(hours=1),
            available_at=available_at,
            supersedes=supersedes,
            rule_profile=profile,
            coverage=CalendarCoverage(
                scope=CalendarScope(exchange=exchange, year=year),
                level=coverage_level,
                confirmed_through=confirmed_through,
                publication_cutoff=available_at,
                source_policy_id="test-authoritative-scan-v1",
                source_catalog_sha256=_digest(14000 + version),
                two_pass_verified=True,
                source_policy_verified=True,
            ),
        )
        return snapshot
    return CalendarSnapshot(
        snapshot_id=UUID(int=version),
        artifact_id=scan.artifact_id,
        capture_id=scan.capture_id,
        artifact_sha256=scan.artifact_sha256,
        authority=authority,
        scope=CalendarScope(exchange=exchange, year=year),
        captured_at=available_at - timedelta(hours=1),
        available_at=available_at,
        terminal=terminal,
        days=rows,
        supersedes=supersedes,
        evidence=(annual, rule_before, rule_after, scan),
        scan_bundle=scan_bundle,
    )


def _snapshot_with_days_object(days: object) -> CalendarSnapshot:
    return CalendarSnapshot(
        snapshot_id=UUID(int=901),
        artifact_id=UUID(int=1901),
        capture_id=UUID(int=2901),
        artifact_sha256=_digest(901),
        authority=OfficialAuthority.SSE,
        scope=CalendarScope(exchange="SH", year=2026),
        captured_at=_BASE,
        available_at=_BASE + timedelta(hours=1),
        terminal=SnapshotTerminal.INDETERMINATE,
        days=days,  # type: ignore[arg-type]
    )


def _secondary(
    *,
    number: int,
    day: date = date(2026, 1, 2),
    is_trading_day: bool,
    available_at: datetime = _BASE + timedelta(hours=2),
    exchange: ExchangeCode = "SH",
    year: int = 2026,
) -> SecondaryCalendarObservation:
    return SecondaryCalendarObservation(
        evidence_id=UUID(int=3000 + number),
        artifact_sha256=_digest(3000 + number),
        scope=CalendarScope(exchange=exchange, year=year),
        date=day,
        is_trading_day=is_trading_day,
        available_at=available_at,
    )


def test_complete_snapshot_accepts_365_and_366_day_years() -> None:
    normal = _snapshot(year=2026)
    leap = _snapshot(version=2, year=2024, available_at=_BASE)

    assert normal.terminal is SnapshotTerminal.INDETERMINATE
    assert len(normal.days) == 365
    assert len(leap.days) == 366
    assert isinstance(normal.days, tuple)
    result = resolve("SH", date(2026, 1, 1), _BASE + timedelta(days=1), [normal])
    assert result.status is CalendarResolutionStatus.INDETERMINATE
    assert result.reason is CalendarResolutionReason.OFFICIAL_INCOMPLETE


@pytest.mark.parametrize(
    "days",
    [
        _all_days(2026)[:-1],
        _all_days(2026) + [_all_days(2026)[0]],
        _all_days(2026)[:-1]
        + [
            TradingDay(
                date=date(2025, 12, 31),
                exchange=ContractExchange.sh,
                isTradingDay=True,
            )
        ],
    ],
    ids=["missing", "duplicate", "wrong-year"],
)
def test_complete_snapshot_requires_each_date_exactly_once(days: list[TradingDay]) -> None:
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        _snapshot(days=days)


def test_incomplete_snapshot_preserves_valid_partial_days_but_never_resolves_positive() -> None:
    snapshot = _snapshot(
        terminal=SnapshotTerminal.INDETERMINATE,
        days=_all_days(2026)[:2],
    )

    result = resolve("SH", date(2026, 1, 2), _BASE + timedelta(days=1), [snapshot])

    assert result.status is CalendarResolutionStatus.INDETERMINATE
    assert result.reason is CalendarResolutionReason.OFFICIAL_INCOMPLETE
    assert result.selected_version == snapshot.snapshot_id
    assert len(snapshot.days) == 2


def test_scope_day_exchange_and_bool_types_are_strict() -> None:
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar scope"):
        CalendarScope(exchange="SH", year=True)  # type: ignore[arg-type]

    forged = TradingDay.model_construct(
        date=date(2026, 1, 1),
        exchange=ContractExchange.sh,
        is_trading_day=1,
        reason=None,
        note=None,
    )
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar day"):
        _snapshot(terminal=SnapshotTerminal.INDETERMINATE, days=[forged])

    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        _snapshot(terminal=True)  # type: ignore[arg-type]


def test_datetime_is_not_accepted_as_a_calendar_date() -> None:
    forged = TradingDay.model_construct(
        date=datetime(2026, 1, 1),
        exchange=ContractExchange.sh,
        is_trading_day=True,
        reason=None,
        note=None,
    )
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar day"):
        _snapshot(terminal=SnapshotTerminal.INDETERMINATE, days=[forged])

    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar scope"):
        resolve("SH", datetime(2026, 1, 2), _BASE, [])  # type: ignore[arg-type]

    with pytest.raises(AuthoritativeCalendarError, match="invalid secondary calendar observation"):
        _secondary(number=9, day=datetime(2026, 1, 2), is_trading_day=True)  # type: ignore[arg-type]


def test_trading_day_cannot_carry_a_non_trading_reason() -> None:
    forged = TradingDay.model_construct(
        date=date(2026, 1, 1),
        exchange=ContractExchange.sh,
        is_trading_day=True,
        reason=ContractReason.weekend,
        note=None,
    )

    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar day"):
        _snapshot(terminal=SnapshotTerminal.INDETERMINATE, days=[forged])


def test_year_9999_complete_snapshot_does_not_overflow_next_year() -> None:
    year_end = datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)
    snapshot = _snapshot(version=90, year=9999, available_at=year_end)

    result = resolve("SH", date(9999, 12, 31), year_end, [snapshot])

    assert len(snapshot.days) == 365
    assert result.status is CalendarResolutionStatus.INDETERMINATE
    assert result.reason is CalendarResolutionReason.OFFICIAL_INCOMPLETE


def test_naive_and_reversed_snapshot_times_are_rejected() -> None:
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        _snapshot(available_at=datetime(2026, 1, 1, 2))

    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        CalendarSnapshot(
            snapshot_id=UUID(int=10),
            artifact_id=UUID(int=1010),
            capture_id=UUID(int=2010),
            artifact_sha256=_digest(10),
            authority=OfficialAuthority.SSE,
            scope=CalendarScope("SH", 2026),
            captured_at=_BASE + timedelta(hours=2),
            available_at=_BASE + timedelta(hours=1),
            terminal=SnapshotTerminal.INDETERMINATE,
            days=(),
        )


def test_untrusted_timezone_exception_does_not_survive_as_context() -> None:
    exploding = datetime(2026, 1, 1, 2, tzinfo=_ExplodingTimezone())

    with pytest.raises(AuthoritativeCalendarError) as caught:
        _snapshot(available_at=exploding)

    _assert_fixed_error(caught.value)


def test_missing_pydantic_row_field_does_not_survive_as_context() -> None:
    missing = TradingDay.model_construct(
        date=date(2026, 1, 1),
        exchange=ContractExchange.sh,
        reason=None,
        note=None,
    )

    with pytest.raises(AuthoritativeCalendarError) as caught:
        _snapshot(terminal=SnapshotTerminal.INDETERMINATE, days=[missing])

    _assert_fixed_error(caught.value)


def test_days_iterator_exception_does_not_survive_as_context() -> None:
    with pytest.raises(AuthoritativeCalendarError) as caught:
        _snapshot_with_days_object(_ExplodingDays())

    _assert_fixed_error(caught.value)


def test_snapshot_iterator_exception_does_not_survive_as_context() -> None:
    with pytest.raises(AuthoritativeCalendarError) as caught:
        resolve("SH", date(2026, 1, 2), _BASE, _ExplodingSnapshots())

    _assert_fixed_error(caught.value)


def test_secondary_iterator_exception_does_not_survive_as_context() -> None:
    official = _snapshot()
    with pytest.raises(AuthoritativeCalendarError) as caught:
        resolve(
            "SH",
            date(2026, 1, 2),
            _BASE + timedelta(days=1),
            [official],
            secondary=_ExplodingSecondary(),
        )

    _assert_fixed_error(caught.value)


def test_snapshot_copies_and_converts_pydantic_rows_to_frozen_internal_rows() -> None:
    row = TradingDay(
        date=date(2026, 1, 1),
        exchange=ContractExchange.sh,
        isTradingDay=True,
    )
    rows = [row]
    snapshot = _snapshot(terminal=SnapshotTerminal.INDETERMINATE, days=rows)
    rows.clear()
    row.date = date(2026, 1, 2)

    assert len(snapshot.days) == 1
    assert snapshot.days[0].date == date(2026, 1, 1)
    with pytest.raises(FrozenInstanceError):
        snapshot.days[0].is_trading_day = False  # type: ignore[misc]


def test_future_or_missing_official_input_is_indeterminate() -> None:
    future = _snapshot(available_at=_BASE + timedelta(days=2))

    future_result = resolve("SH", date(2026, 1, 2), _BASE + timedelta(days=1), [future])
    empty_result = resolve("SH", date(2026, 1, 2), _BASE + timedelta(days=1), [])

    assert future_result.status is CalendarResolutionStatus.INDETERMINATE
    assert future_result.reason is CalendarResolutionReason.NO_VISIBLE_OFFICIAL
    assert empty_result.status is CalendarResolutionStatus.INDETERMINATE
    assert empty_result.reason is CalendarResolutionReason.NO_VISIBLE_OFFICIAL


def test_future_invalid_lineage_does_not_change_an_earlier_result() -> None:
    current = _snapshot(version=19, available_at=_BASE + timedelta(hours=2))
    future_dangling = _snapshot(
        version=95,
        available_at=_BASE + timedelta(days=2),
        supersedes=uuid4(),
    )

    result = resolve("SH", date(2026, 1, 1), _BASE + timedelta(days=1), [current, future_dangling])

    assert result.status is CalendarResolutionStatus.INDETERMINATE
    assert result.reason is CalendarResolutionReason.OFFICIAL_INCOMPLETE
    assert result.selected_version == current.snapshot_id


def test_revision_is_selected_by_available_time_and_as_of_boundary() -> None:
    old = _snapshot(version=20, available_at=_BASE + timedelta(hours=2))
    new = _snapshot(
        version=21,
        available_at=_BASE + timedelta(hours=4),
        terminal=SnapshotTerminal.INDETERMINATE,
        days=_all_days(2026, non_trading={date(2026, 1, 1)}),
        supersedes=old.snapshot_id,
    )

    before = resolve("SH", date(2026, 1, 1), _BASE + timedelta(hours=3), [old, new])
    at_boundary = resolve("SH", date(2026, 1, 1), _BASE + timedelta(hours=4), [old, new])

    assert before.status is CalendarResolutionStatus.INDETERMINATE
    assert before.reason is CalendarResolutionReason.OFFICIAL_INCOMPLETE
    assert before.selected_version == old.snapshot_id
    assert at_boundary.status is CalendarResolutionStatus.INDETERMINATE
    assert at_boundary.reason is CalendarResolutionReason.OFFICIAL_INCOMPLETE
    assert at_boundary.selected_version == new.snapshot_id
    assert at_boundary.selected_available_at == new.available_at


def test_visible_child_with_future_parent_cannot_be_selected() -> None:
    parent = _snapshot(version=91, available_at=_BASE + timedelta(hours=7))
    child = _snapshot(
        version=92,
        available_at=_BASE + timedelta(hours=6),
        supersedes=parent.snapshot_id,
    )

    result = resolve(
        "SH",
        date(2026, 1, 1),
        _BASE + timedelta(hours=6),
        [child, parent],
    )

    assert result.status is CalendarResolutionStatus.INDETERMINATE
    assert result.reason is CalendarResolutionReason.OFFICIAL_LINEAGE_UNAVAILABLE
    assert result.selected_version is None

    late_result = resolve(
        "SH",
        date(2026, 1, 2),
        _BASE + timedelta(hours=8),
        [child, parent],
    )
    assert late_result.status is CalendarResolutionStatus.INDETERMINATE
    assert late_result.reason is CalendarResolutionReason.OFFICIAL_LINEAGE_UNAVAILABLE
    assert late_result.selected_version is None


def test_reordering_snapshot_inputs_does_not_change_resolution() -> None:
    old = _snapshot(version=93, available_at=_BASE + timedelta(hours=2))
    new = _snapshot(
        version=94,
        available_at=_BASE + timedelta(hours=4),
        days=_all_days(2026, non_trading={date(2026, 1, 2)}),
        supersedes=old.snapshot_id,
    )

    forward = resolve("SH", date(2026, 1, 2), _BASE + timedelta(hours=4), [old, new])
    reverse = resolve("SH", date(2026, 1, 2), _BASE + timedelta(hours=4), [new, old])

    assert forward == reverse


def test_lineage_dangling_cycle_and_cross_scope_inputs_fail_closed() -> None:
    dangling = _snapshot(version=30, supersedes=uuid4())
    dangling_result = resolve("SH", date(2026, 1, 2), _BASE + timedelta(days=1), [dangling])
    assert dangling_result.status is CalendarResolutionStatus.INDETERMINATE
    assert dangling_result.reason is CalendarResolutionReason.OFFICIAL_LINEAGE_UNAVAILABLE

    first_id = UUID(int=31)
    second_id = UUID(int=32)
    lineage_available = _BASE
    first_annual = _trusted_evidence(
        20031, CalendarEvidenceKind.ANNUAL_NOTICE, available_at=lineage_available
    )
    first_rule_before = _trusted_evidence(
        20032, CalendarEvidenceKind.RULE, available_at=lineage_available
    )
    first_rule_after = _trusted_evidence(
        20033, CalendarEvidenceKind.RULE, available_at=lineage_available
    )
    first_scan = _trusted_evidence(
        20034, CalendarEvidenceKind.TEMPORARY_SCAN, available_at=lineage_available
    )
    assert first_scan.artifact_id is not None
    assert first_scan.capture_id is not None
    first_scan_page = CalendarScanPage(
        ordinal=1, evidence=first_scan, cursor_in=None, cursor_out=None
    )
    second_annual = _trusted_evidence(
        20035, CalendarEvidenceKind.ANNUAL_NOTICE, available_at=lineage_available
    )
    second_rule_before = _trusted_evidence(
        20036, CalendarEvidenceKind.RULE, available_at=lineage_available
    )
    second_rule_after = _trusted_evidence(
        20037, CalendarEvidenceKind.RULE, available_at=lineage_available
    )
    second_scan = _trusted_evidence(
        20038, CalendarEvidenceKind.TEMPORARY_SCAN, available_at=lineage_available
    )
    assert second_scan.artifact_id is not None
    assert second_scan.capture_id is not None
    second_scan_page = CalendarScanPage(
        ordinal=1, evidence=second_scan, cursor_in=None, cursor_out=None
    )
    first = CalendarSnapshot(
        snapshot_id=first_id,
        artifact_id=first_scan.artifact_id,
        capture_id=first_scan.capture_id,
        artifact_sha256=first_scan.artifact_sha256,
        authority=OfficialAuthority.SSE,
        scope=CalendarScope("SH", 2026),
        captured_at=_BASE,
        available_at=_BASE + timedelta(hours=1),
        terminal=SnapshotTerminal.INDETERMINATE,
        days=_all_days(2026),
        supersedes=second_id,
        evidence=(first_annual, first_rule_before, first_rule_after, first_scan),
        scan_bundle=CalendarScanBundle(
            bundle_id=UUID(int=21031),
            authority=OfficialAuthority.SSE,
            scope=CalendarScope("SH", 2026),
            pages=(first_scan_page,),
            evidence_ids=(first_scan.evidence_id,),
            artifact_sha256s=(first_scan.artifact_sha256,),
            window_start=date(2026, 1, 1),
            window_end=date(2026, 12, 31),
            page_count=1,
            replayable=True,
            continuity_verified=True,
            complete=True,
            covers_full_exchange=True,
            captured_at=_BASE - timedelta(hours=1),
            available_at=_BASE,
        ),
    )
    second = CalendarSnapshot(
        snapshot_id=second_id,
        artifact_id=second_scan.artifact_id,
        capture_id=second_scan.capture_id,
        artifact_sha256=second_scan.artifact_sha256,
        authority=OfficialAuthority.SSE,
        scope=CalendarScope("SH", 2026),
        captured_at=_BASE,
        available_at=_BASE + timedelta(hours=1),
        terminal=SnapshotTerminal.INDETERMINATE,
        days=_all_days(2026),
        supersedes=first_id,
        evidence=(second_annual, second_rule_before, second_rule_after, second_scan),
        scan_bundle=CalendarScanBundle(
            bundle_id=UUID(int=21032),
            authority=OfficialAuthority.SSE,
            scope=CalendarScope("SH", 2026),
            pages=(second_scan_page,),
            evidence_ids=(second_scan.evidence_id,),
            artifact_sha256s=(second_scan.artifact_sha256,),
            window_start=date(2026, 1, 1),
            window_end=date(2026, 12, 31),
            page_count=1,
            replayable=True,
            continuity_verified=True,
            complete=True,
            covers_full_exchange=True,
            captured_at=_BASE - timedelta(hours=1),
            available_at=_BASE,
        ),
    )
    cycle_result = resolve("SH", date(2026, 1, 2), _BASE + timedelta(days=1), [first, second])
    assert cycle_result.status is CalendarResolutionStatus.INDETERMINATE
    assert cycle_result.reason is CalendarResolutionReason.OFFICIAL_LINEAGE_UNAVAILABLE

    other_scope = _snapshot(version=33, exchange="SZ", authority=OfficialAuthority.SZSE)
    cross_scope_child = _snapshot(version=34, supersedes=other_scope.snapshot_id)
    cross_scope_result = resolve(
        "SH",
        date(2026, 1, 2),
        _BASE + timedelta(days=1),
        [cross_scope_child, other_scope],
    )
    assert cross_scope_result.status is CalendarResolutionStatus.INDETERMINATE
    assert cross_scope_result.reason is CalendarResolutionReason.OFFICIAL_LINEAGE_UNAVAILABLE


def test_unlinked_heads_cannot_be_selected_by_order_or_content() -> None:
    first = _snapshot(version=40)
    second = _snapshot(
        version=41,
        days=_all_days(2026, non_trading={date(2026, 1, 2)}),
    )

    result = resolve("SH", date(2026, 1, 2), _BASE + timedelta(days=1), [second, first])

    assert result.status is CalendarResolutionStatus.INDETERMINATE
    assert result.reason is CalendarResolutionReason.OFFICIAL_CONFLICT
    assert result.selected_version is None


def test_new_incomplete_revision_blocks_complete_parent_fallback() -> None:
    old = _snapshot(version=50)
    new = _snapshot(
        version=51,
        terminal=SnapshotTerminal.INDETERMINATE,
        days=_all_days(2026)[:4],
        supersedes=old.snapshot_id,
        available_at=_BASE + timedelta(hours=4),
    )

    result = resolve("SH", date(2026, 1, 2), _BASE + timedelta(hours=4), [old, new])

    assert result.status is CalendarResolutionStatus.INDETERMINATE
    assert result.reason is CalendarResolutionReason.OFFICIAL_INCOMPLETE
    assert result.selected_version == new.snapshot_id


def test_secondary_cannot_override_official_and_conflict_evidence_is_redacted() -> None:
    official = _snapshot(version=60)
    secondary = _secondary(number=1, day=date(2026, 1, 1), is_trading_day=False)
    competing_secondary = _secondary(number=9, day=date(2026, 1, 1), is_trading_day=True)

    result = resolve(
        "SH",
        date(2026, 1, 1),
        _BASE + timedelta(days=1),
        [official],
        secondary=[secondary, competing_secondary],
    )

    assert result.status is CalendarResolutionStatus.INDETERMINATE
    assert result.secondary_conflict is not None
    evidence = result.secondary_conflict
    assert evidence.evidence_ids == tuple(
        sorted(
            (secondary.evidence_id, competing_secondary.evidence_id), key=lambda item: item.bytes
        )
    )
    assert set(evidence.artifact_digests) == {
        secondary.artifact_sha256,
        competing_secondary.artifact_sha256,
    }
    assert not hasattr(evidence, "note")
    assert not hasattr(evidence, "url")
    with pytest.raises(FrozenInstanceError):
        evidence.evidence_ids += (uuid4(),)  # type: ignore[misc]


def test_secondary_conflicts_are_compared_only_at_visible_matching_scope_and_date() -> None:
    official = _snapshot(version=70)
    visible_non_trading = _secondary(number=2, day=date(2026, 1, 1), is_trading_day=False)
    visible_trading = _secondary(number=3, day=date(2026, 1, 1), is_trading_day=True)
    future = _secondary(
        number=4,
        is_trading_day=False,
        available_at=_BASE + timedelta(days=4),
    )
    other_date = _secondary(number=5, day=date(2026, 1, 3), is_trading_day=False)
    other_scope = _secondary(
        number=6,
        is_trading_day=False,
        exchange="SZ",
    )

    result = resolve(
        "SH",
        date(2026, 1, 1),
        _BASE + timedelta(days=1),
        [official],
        secondary=[visible_non_trading, visible_trading, future, other_date, other_scope],
    )

    assert result.status is CalendarResolutionStatus.INDETERMINATE
    assert result.secondary_conflict is not None
    assert future.evidence_id not in result.secondary_conflict.evidence_ids
    assert other_date.evidence_id not in result.secondary_conflict.evidence_ids
    assert other_scope.evidence_id not in result.secondary_conflict.evidence_ids


def test_secondary_only_or_future_secondary_never_creates_positive_result() -> None:
    secondary = _secondary(number=7, is_trading_day=True)
    future = _secondary(
        number=8,
        is_trading_day=True,
        available_at=_BASE + timedelta(days=5),
    )

    result = resolve(
        "SH",
        date(2026, 1, 2),
        _BASE + timedelta(days=1),
        [],
        secondary=[secondary, future],
    )

    assert result.status is CalendarResolutionStatus.INDETERMINATE
    assert result.reason is CalendarResolutionReason.NO_VISIBLE_OFFICIAL
    assert result.secondary_conflict is None


def test_resolution_has_no_free_text_metadata_or_raw_input() -> None:
    official = _snapshot(version=80)
    result = resolve("SH", date(2026, 1, 1), _BASE + timedelta(days=1), [official])

    assert not hasattr(result, "note")
    assert not hasattr(result, "url")
    assert not hasattr(result, "source")
    assert result.selected_version == official.snapshot_id
