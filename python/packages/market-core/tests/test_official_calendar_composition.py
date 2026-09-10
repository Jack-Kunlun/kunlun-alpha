"""P1-N07-C1 official calendar composition tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from market_core.calendar.official_calendar_composition import (
    AuthoritativeCalendarError,
    CalendarAnnualNotice,
    CalendarCompositionReceipt,
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
    CalendarTemporaryClosureDelta,
    ExchangeCode,
    OfficialAuthority,
    SnapshotTerminal,
    apply_temporary_closure,
    build_authoritative_snapshot,
    compose_official_calendar,
    expected_calendar_dates,
    resolve,
)

_BASE = datetime(2026, 1, 1, 0, tzinfo=UTC)
_HOLIDAYS_2026 = (
    date(2026, 1, 1),
    date(2026, 1, 2),
    date(2026, 2, 16),
    date(2026, 2, 17),
    date(2026, 2, 18),
    date(2026, 2, 19),
    date(2026, 2, 20),
    date(2026, 2, 23),
    date(2026, 4, 6),
    date(2026, 5, 1),
    date(2026, 5, 4),
    date(2026, 5, 5),
    date(2026, 6, 19),
    date(2026, 9, 25),
    date(2026, 10, 1),
    date(2026, 10, 2),
    date(2026, 10, 5),
    date(2026, 10, 6),
    date(2026, 10, 7),
)


class _HostileEvidence:
    @property
    def identity_verified(self) -> bool:
        raise RuntimeError("untrusted-calendar-sentinel")


def _digest(number: int) -> str:
    return f"{number:064x}"


def _authority(exchange: ExchangeCode) -> OfficialAuthority:
    return {
        "SH": OfficialAuthority.SSE,
        "SZ": OfficialAuthority.SZSE,
        "BJ": OfficialAuthority.BSE,
    }[exchange]


def _evidence(
    number: int,
    kind: CalendarEvidenceKind,
    *,
    exchange: ExchangeCode = "SH",
    year: int = 2026,
    available_at: datetime = _BASE,
    covers_full_exchange: bool = False,
    covers_full_day: bool = False,
) -> CalendarEvidence:
    return CalendarEvidence(
        evidence_id=UUID(int=number),
        artifact_sha256=_digest(number),
        kind=kind,
        authority=_authority(exchange),
        scope=CalendarScope(exchange, year),
        captured_at=_BASE,
        available_at=available_at,
        source_url=f"https://official.example/{exchange.lower()}/{number}",
        document_id=f"{exchange.lower()}-{year}-{number}",
        title=f"Official {exchange} calendar evidence",
        issuer=_authority(exchange).value,
        identity_verified=True,
        covers_full_exchange=covers_full_exchange,
        covers_full_day=covers_full_day,
        artifact_id=UUID(int=100_000 + number),
        capture_id=UUID(int=200_000 + number),
    )


def _annual(
    exchange: ExchangeCode = "SH", year: int = 2026, number: int = 1
) -> CalendarAnnualNotice:
    return CalendarAnnualNotice(
        evidence=_evidence(
            number, CalendarEvidenceKind.ANNUAL_NOTICE, exchange=exchange, year=year
        ),
        closed_dates=_HOLIDAYS_2026 if year == 2026 else (),
    )


def _rules(exchange: ExchangeCode = "SH", year: int = 2026) -> tuple[CalendarRuleCoverage, ...]:
    return (
        CalendarRuleCoverage(
            evidence=_evidence(2, CalendarEvidenceKind.RULE, exchange=exchange, year=year),
            valid_from=date(year, 1, 1),
            valid_to=date(year, 7, 5),
            weekdays=(0, 1, 2, 3, 4),
            closes_legal_holidays=True,
        ),
        CalendarRuleCoverage(
            evidence=_evidence(3, CalendarEvidenceKind.RULE, exchange=exchange, year=year),
            valid_from=date(year, 7, 6),
            valid_to=date(year, 12, 31),
            weekdays=(0, 1, 2, 3, 4),
            closes_legal_holidays=True,
        ),
    )


def _scan_days(exchange: ExchangeCode = "SH", year: int = 2026) -> tuple[CalendarDay, ...]:
    closures = set(_HOLIDAYS_2026 if year == 2026 else ())
    return tuple(
        CalendarDay(
            date=current,
            exchange=exchange,
            is_trading_day=current.weekday() < 5 and current not in closures,
            reason=(
                CalendarDayReason.PUBLIC_HOLIDAY
                if current in closures
                else CalendarDayReason.WEEKEND
                if current.weekday() >= 5
                else None
            ),
        )
        for current in expected_calendar_dates(year)
    )


def _scan(
    exchange: ExchangeCode = "SH",
    year: int = 2026,
    number: int = 4,
    *,
    complete: bool = True,
    days: tuple[CalendarDay, ...] | None = None,
    delta_evidence: CalendarEvidence | None = None,
    available_at: datetime = _BASE,
    deltas: tuple[CalendarTemporaryClosureDelta, ...] = (),
) -> CalendarScanObservation:
    scope = CalendarScope(exchange, year)
    page_evidence = tuple(
        _evidence(
            number if ordinal == 1 else number * 1000 + ordinal,
            CalendarEvidenceKind.TEMPORARY_SCAN,
            exchange=exchange,
            year=year,
            available_at=available_at,
        )
        for ordinal in range(1, 13)
    )
    pages = tuple(
        CalendarScanPage(
            ordinal=ordinal,
            evidence=evidence,
            cursor_in=None if ordinal == 1 else f"cursor-{ordinal - 1}",
            cursor_out=None if ordinal == 12 else f"cursor-{ordinal}",
        )
        for ordinal, evidence in enumerate(page_evidence, start=1)
    )
    bundle = CalendarScanBundle(
        bundle_id=UUID(int=number),
        authority=_authority(exchange),
        scope=scope,
        pages=pages,
        evidence_ids=tuple(item.evidence_id for item in page_evidence),
        artifact_sha256s=tuple(item.artifact_sha256 for item in page_evidence),
        window_start=date(year, 1, 1),
        window_end=date(year, 12, 31),
        page_count=12,
        replayable=complete,
        continuity_verified=complete,
        complete=complete,
        covers_full_exchange=True,
        captured_at=_BASE,
        available_at=available_at,
    )
    return CalendarScanObservation(
        bundle=bundle,
        evidence=page_evidence[0],
        days=_scan_days(exchange, year) if days is None else days,
        delta_evidence=delta_evidence,
        deltas=deltas,
    )


def _complete_snapshot(
    *, exchange: ExchangeCode = "SH", year: int = 2026, version: int = 1
) -> CalendarSnapshot:
    scope = CalendarScope(exchange, year)
    final_available = max(
        _BASE,
        datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC) + timedelta(hours=1),
    )
    profile = (
        CalendarRuleProfile(
            scope=scope,
            required_rule_starts=(date(2026, 7, 6),),
        )
        if year == 2026
        else None
    )
    return compose_official_calendar(
        snapshot_id=UUID(int=version),
        authority=_authority(exchange),
        scope=scope,
        annual_notice=_annual(exchange, year, 10 + version),
        rules=_rules(exchange, year),
        scan=_scan(exchange, year, 40 + version, available_at=final_available),
        captured_at=_BASE,
        available_at=final_available,
        rule_profile=profile,
        coverage=CalendarCoverage(
            scope=scope,
            level=CalendarCoverageLevel.FINAL_YEAR,
            confirmed_through=date(year, 12, 31),
            publication_cutoff=datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC),
            source_policy_id="official-calendar-scan-v1",
            source_catalog_sha256=_digest(900 + version),
            two_pass_verified=True,
            source_policy_verified=True,
        ),
    )


def test_three_exchanges_have_unique_365_dates_and_242_ordinary_trading_days() -> None:
    for exchange in cast(tuple[ExchangeCode, ...], ("SH", "SZ", "BJ")):
        snapshot = _complete_snapshot(exchange=exchange)
        assert snapshot.terminal is SnapshotTerminal.INDETERMINATE
        assert len(snapshot.days) == 365
        assert {day.date for day in snapshot.days} == set(expected_calendar_dates(2026))
        assert sum(day.is_trading_day for day in snapshot.days) == 242
        assert sum(day.reason is CalendarDayReason.PUBLIC_HOLIDAY for day in snapshot.days) == 19
        assert all(day.exchange == exchange for day in snapshot.days)
        assert snapshot.scan_bundle is not None
        assert snapshot.scan_bundle.page_count == 12
        page_ids = {page.evidence.evidence_id for page in snapshot.scan_bundle.pages}
        assert page_ids.issubset({item.evidence_id for item in snapshot.evidence})
        first_page = snapshot.scan_bundle.pages[0].evidence
        assert snapshot.artifact_id == first_page.artifact_id
        assert snapshot.capture_id == first_page.capture_id
        assert snapshot.artifact_sha256 == first_page.artifact_sha256


def test_legacy_composer_is_candidate_only_for_positive_resolution() -> None:
    snapshot = _complete_snapshot(exchange="SH")

    assert snapshot.terminal is SnapshotTerminal.INDETERMINATE
    result = resolve("SH", date(2026, 9, 4), snapshot.available_at, [snapshot])
    assert result.status is CalendarResolutionStatus.INDETERMINATE
    assert result.reason is CalendarResolutionReason.OFFICIAL_INCOMPLETE


def test_leap_year_path_has_366_days() -> None:
    snapshot = _complete_snapshot(exchange="SZ", year=2024)
    assert len(snapshot.days) == 366
    assert snapshot.days[-1].date == date(2024, 12, 31)


def test_complete_requires_replayable_continuous_scan_even_for_full_projection() -> None:
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        CalendarSnapshot(
            snapshot_id=UUID(int=100),
            artifact_id=UUID(int=101),
            capture_id=UUID(int=102),
            artifact_sha256=_digest(100),
            authority=OfficialAuthority.SSE,
            scope=CalendarScope("SH", 2026),
            captured_at=_BASE,
            available_at=_BASE + timedelta(hours=8),
            terminal=SnapshotTerminal.COMPLETE,
            days=_scan_days(),
            evidence=(
                _evidence(1, CalendarEvidenceKind.ANNUAL_NOTICE),
                _evidence(2, CalendarEvidenceKind.RULE),
                _evidence(3, CalendarEvidenceKind.RULE),
            ),
        )


def test_direct_complete_rejects_unverified_evidence() -> None:
    source = _complete_snapshot()
    unverified = replace(source.evidence[0], identity_verified=False)
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        CalendarSnapshot(
            snapshot_id=UUID(int=110),
            artifact_id=source.artifact_id,
            capture_id=source.capture_id,
            artifact_sha256=source.artifact_sha256,
            authority=source.authority,
            scope=source.scope,
            captured_at=source.captured_at,
            available_at=source.available_at,
            terminal=SnapshotTerminal.COMPLETE,
            days=source.days,
            evidence=(unverified, *source.evidence[1:]),
            scan_bundle=source.scan_bundle,
        )


def test_builder_rejects_unverified_evidence_instead_of_deriving_complete() -> None:
    source = _complete_snapshot()
    unverified = replace(source.evidence[0], identity_verified=False)
    result = build_authoritative_snapshot(
        snapshot_id=UUID(int=112),
        artifact_id=source.artifact_id,
        capture_id=source.capture_id,
        artifact_sha256=source.artifact_sha256,
        authority=source.authority,
        scope=source.scope,
        captured_at=source.captured_at,
        available_at=source.available_at,
        days=source.days,
        evidence=(unverified, *source.evidence[1:]),
        scan_bundle=source.scan_bundle,
    )
    assert result.terminal is SnapshotTerminal.INDETERMINATE


def test_direct_complete_rejects_bundle_receipt_that_is_not_temporary_scan() -> None:
    source = _complete_snapshot()
    annual = source.evidence[0]
    assert source.scan_bundle is not None
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        replace(
            source.scan_bundle,
            evidence_ids=(annual.evidence_id,),
            artifact_sha256s=(annual.artifact_sha256,),
        )


def test_missing_or_non_continuous_scan_is_indeterminate() -> None:
    snapshot = compose_official_calendar(
        snapshot_id=UUID(int=200),
        authority=OfficialAuthority.SSE,
        scope=CalendarScope("SH", 2026),
        annual_notice=_annual(),
        rules=_rules(),
        scan=_scan(complete=False),
        captured_at=_BASE,
        available_at=_BASE + timedelta(hours=8),
    )
    assert snapshot.terminal is SnapshotTerminal.INDETERMINATE


def test_weekend_makeup_dates_remain_closed() -> None:
    snapshot = _complete_snapshot()
    assert all(
        day.reason is CalendarDayReason.WEEKEND
        for day in snapshot.days
        if day.date.weekday() >= 5 and day.date not in _HOLIDAYS_2026
    )
    assert all(day.date.weekday() < 5 for day in snapshot.days if day.is_trading_day)


def test_temporary_full_market_delta_supersedes_without_mutating_parent() -> None:
    parent = _complete_snapshot()
    delta = _evidence(
        500,
        CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE,
        covers_full_exchange=True,
        covers_full_day=True,
    )
    successor_days: tuple[CalendarDay, ...] = tuple(
        CalendarDay(
            date=day.date,
            exchange=cast(ExchangeCode, day.exchange),
            is_trading_day=False,
            reason=CalendarDayReason.TEMPORARY_CLOSURE,
        )
        if day.date == date(2026, 3, 16)
        else CalendarDay(
            date=day.date,
            exchange=cast(ExchangeCode, day.exchange),
            is_trading_day=day.is_trading_day,
            reason=cast(CalendarDayReason | None, day.reason),
        )
        for day in parent.days
    )
    successor_scan = _scan(
        number=600,
        days=successor_days,
        delta_evidence=delta,
        available_at=parent.available_at,
    )
    child = apply_temporary_closure(
        parent,
        snapshot_id=UUID(int=501),
        evidence=delta,
        closure_date=date(2026, 3, 16),
        captured_at=parent.available_at + timedelta(days=1),
        available_at=parent.available_at + timedelta(days=1, hours=1),
        successor_scan=successor_scan,
    )
    assert child.terminal is SnapshotTerminal.INDETERMINATE
    assert child.supersedes == parent.snapshot_id
    child_evidence_ids = {item.evidence_id for item in child.evidence}
    assert delta.evidence_id in child_evidence_ids
    assert {item.evidence_id for item in successor_scan.page_evidence}.issubset(child_evidence_ids)
    assert child.artifact_id == delta.artifact_id
    assert child.capture_id == delta.capture_id
    assert child.artifact_sha256 == delta.artifact_sha256
    assert next(day for day in parent.days if day.date == date(2026, 3, 16)).is_trading_day
    changed = next(day for day in child.days if day.date == date(2026, 3, 16))
    assert changed.is_trading_day is False
    assert changed.reason is CalendarDayReason.TEMPORARY_CLOSURE


@pytest.mark.parametrize(
    "identity_verified,covers_full_day",
    [(False, True), (True, False)],
    ids=["unverified", "not-full-day"],
)
def test_temporary_delta_requires_verified_full_day_evidence(
    identity_verified: bool, covers_full_day: bool
) -> None:
    parent = _complete_snapshot()
    delta = _evidence(
        510,
        CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE,
        covers_full_exchange=True,
        covers_full_day=covers_full_day,
    )
    delta = replace(delta, identity_verified=identity_verified)
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        apply_temporary_closure(
            parent,
            snapshot_id=UUID(int=511),
            evidence=delta,
            closure_date=date(2026, 3, 16),
            captured_at=_BASE,
            available_at=_BASE,
            successor_scan=None,
        )


def test_temporary_delta_without_successor_scan_is_indeterminate_child() -> None:
    parent = _complete_snapshot()
    delta = _evidence(
        520,
        CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE,
        covers_full_exchange=True,
        covers_full_day=True,
    )
    child = apply_temporary_closure(
        parent,
        snapshot_id=UUID(int=521),
        evidence=delta,
        closure_date=date(2026, 3, 16),
        captured_at=parent.available_at + timedelta(days=1),
        available_at=parent.available_at + timedelta(days=1, hours=1),
        successor_scan=None,
    )
    assert child.terminal is SnapshotTerminal.INDETERMINATE
    assert child.supersedes == parent.snapshot_id


def test_future_evidence_and_rule_gap_fail_closed() -> None:
    future_scan = _scan(number=601)
    future_evidence = _evidence(
        601,
        CalendarEvidenceKind.TEMPORARY_SCAN,
        available_at=_BASE + timedelta(days=2),
    )
    future_page = CalendarScanPage(
        ordinal=1,
        evidence=future_evidence,
        cursor_in=None,
        cursor_out=None,
    )
    future_scan = CalendarScanObservation(
        bundle=CalendarScanBundle(
            bundle_id=future_scan.bundle.bundle_id,
            authority=future_scan.bundle.authority,
            scope=future_scan.bundle.scope,
            pages=(future_page,),
            evidence_ids=(future_evidence.evidence_id,),
            artifact_sha256s=(future_evidence.artifact_sha256,),
            window_start=date(2026, 1, 1),
            window_end=date(2026, 12, 31),
            page_count=1,
            replayable=True,
            continuity_verified=True,
            complete=True,
            covers_full_exchange=True,
            captured_at=_BASE,
            available_at=future_evidence.available_at,
        ),
        evidence=future_evidence,
        days=future_scan.days,
    )
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        compose_official_calendar(
            snapshot_id=UUID(int=602),
            authority=OfficialAuthority.SSE,
            scope=CalendarScope("SH", 2026),
            annual_notice=_annual(),
            rules=_rules(),
            scan=future_scan,
            captured_at=_BASE,
            available_at=_BASE,
        )

    gap_rules = (
        CalendarRuleCoverage(
            evidence=_evidence(701, CalendarEvidenceKind.RULE),
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 7, 4),
            weekdays=(0, 1, 2, 3, 4),
            closes_legal_holidays=True,
        ),
        CalendarRuleCoverage(
            evidence=_evidence(702, CalendarEvidenceKind.RULE),
            valid_from=date(2026, 7, 6),
            valid_to=date(2026, 12, 31),
            weekdays=(0, 1, 2, 3, 4),
            closes_legal_holidays=True,
        ),
    )
    gap_snapshot = compose_official_calendar(
        snapshot_id=UUID(int=703),
        authority=OfficialAuthority.SSE,
        scope=CalendarScope("SH", 2026),
        annual_notice=_annual(),
        rules=gap_rules,
        scan=_scan(),
        captured_at=_BASE,
        available_at=_BASE + timedelta(hours=8),
    )
    assert gap_snapshot.terminal is SnapshotTerminal.INDETERMINATE


def test_calendar_day_count_uses_calendar_module_for_regression() -> None:
    assert len(expected_calendar_dates(2024)) == 366
    assert len(expected_calendar_dates(2026)) == 365


def test_scan_bundle_rejects_page_count_and_receipt_mismatch() -> None:
    evidence = _evidence(800, CalendarEvidenceKind.TEMPORARY_SCAN)
    page = CalendarScanPage(ordinal=1, evidence=evidence, cursor_in=None, cursor_out=None)
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        CalendarScanBundle(
            bundle_id=UUID(int=801),
            authority=OfficialAuthority.SSE,
            scope=CalendarScope("SH", 2026),
            pages=(page,),
            evidence_ids=(evidence.evidence_id,),
            artifact_sha256s=(evidence.artifact_sha256,),
            window_start=date(2026, 1, 1),
            window_end=date(2026, 12, 31),
            page_count=12,
            replayable=True,
            continuity_verified=True,
            complete=True,
            captured_at=_BASE,
            available_at=_BASE,
            covers_full_exchange=True,
        )


def test_scan_bundle_rejects_ordinal_cursor_gap_and_open_terminal_cursor() -> None:
    first = _evidence(810, CalendarEvidenceKind.TEMPORARY_SCAN)
    second = _evidence(811, CalendarEvidenceKind.TEMPORARY_SCAN)
    pages = (
        CalendarScanPage(ordinal=1, evidence=first, cursor_in=None, cursor_out="a"),
        CalendarScanPage(ordinal=3, evidence=second, cursor_in="b", cursor_out="tail"),
    )
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        CalendarScanBundle(
            bundle_id=UUID(int=812),
            authority=OfficialAuthority.SSE,
            scope=CalendarScope("SH", 2026),
            pages=pages,
            evidence_ids=(first.evidence_id, second.evidence_id),
            artifact_sha256s=(first.artifact_sha256, second.artifact_sha256),
            window_start=date(2026, 1, 1),
            window_end=date(2026, 12, 31),
            page_count=2,
            replayable=True,
            continuity_verified=True,
            complete=True,
            captured_at=_BASE,
            available_at=_BASE,
            covers_full_exchange=True,
        )


def test_generic_single_rule_covers_a_leap_year() -> None:
    year = 2024
    scope = CalendarScope("SH", year)
    annual = _annual(year=year)
    rule = CalendarRuleCoverage(
        evidence=_evidence(820, CalendarEvidenceKind.RULE, year=year),
        valid_from=date(year, 1, 1),
        valid_to=date(year, 12, 31),
        weekdays=(0, 1, 2, 3, 4),
        closes_legal_holidays=True,
    )
    snapshot = compose_official_calendar(
        snapshot_id=UUID(int=821),
        authority=OfficialAuthority.SSE,
        scope=scope,
        annual_notice=annual,
        rules=(rule,),
        scan=_scan(year=year, number=822),
        captured_at=_BASE,
        available_at=_BASE + timedelta(hours=8),
        coverage=_coverage(
            scope,
            level=CalendarCoverageLevel.FINAL_YEAR,
            confirmed_through=date(year, 12, 31),
            publication_cutoff=datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC),
        ),
    )
    assert snapshot.terminal is SnapshotTerminal.INDETERMINATE
    assert len(snapshot.days) == 366


def test_2026_profile_requires_the_july_six_rule_boundary() -> None:
    year = 2026
    scope = CalendarScope("SH", year)
    annual = _annual(year=year)
    rule = CalendarRuleCoverage(
        evidence=_evidence(830, CalendarEvidenceKind.RULE, year=year),
        valid_from=date(year, 1, 1),
        valid_to=date(year, 12, 31),
        weekdays=(0, 1, 2, 3, 4),
        closes_legal_holidays=True,
    )
    profile = CalendarRuleProfile(scope=scope, required_rule_starts=(date(2026, 7, 6),))
    snapshot = compose_official_calendar(
        snapshot_id=UUID(int=831),
        authority=OfficialAuthority.SSE,
        scope=scope,
        annual_notice=annual,
        rules=(rule,),
        rule_profile=profile,
        scan=_scan(number=832),
        captured_at=_BASE,
        available_at=_BASE + timedelta(hours=8),
    )
    assert snapshot.terminal is SnapshotTerminal.INDETERMINATE


def test_snapshot_rejects_provenance_receipt_mismatch() -> None:
    source = _complete_snapshot()
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        CalendarSnapshot(
            snapshot_id=UUID(int=840),
            artifact_id=UUID(int=841),
            capture_id=UUID(int=842),
            artifact_sha256=_digest(843),
            authority=source.authority,
            scope=source.scope,
            captured_at=source.captured_at,
            available_at=source.available_at,
            terminal=SnapshotTerminal.COMPLETE,
            days=source.days,
            evidence=source.evidence,
            scan_bundle=source.scan_bundle,
        )


def test_builder_normalizes_hostile_evidence_to_fixed_domain_error() -> None:
    source = _complete_snapshot()
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        build_authoritative_snapshot(
            snapshot_id=UUID(int=850),
            artifact_id=source.artifact_id,
            capture_id=source.capture_id,
            artifact_sha256=source.artifact_sha256,
            authority=source.authority,
            scope=source.scope,
            captured_at=source.captured_at,
            available_at=source.available_at,
            days=source.days,
            evidence=(_HostileEvidence(), *source.evidence[1:]),  # type: ignore[arg-type]
            scan_bundle=source.scan_bundle,
        )


def test_direct_verified_evidence_and_arbitrary_days_cannot_claim_complete() -> None:
    source = _complete_snapshot()
    arbitrary_days = tuple(
        CalendarDay(date=day.date, exchange="SH", is_trading_day=True) for day in source.days
    )
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        CalendarSnapshot(
            snapshot_id=UUID(int=860),
            artifact_id=source.artifact_id,
            capture_id=source.capture_id,
            artifact_sha256=source.artifact_sha256,
            authority=source.authority,
            scope=source.scope,
            captured_at=source.captured_at,
            available_at=source.available_at,
            terminal=SnapshotTerminal.COMPLETE,
            days=arbitrary_days,
            evidence=source.evidence,
            scan_bundle=source.scan_bundle,
        )


def _coverage(
    scope: CalendarScope,
    *,
    level: CalendarCoverageLevel,
    confirmed_through: date,
    publication_cutoff: datetime,
    two_pass_verified: bool = True,
) -> CalendarCoverage:
    return CalendarCoverage(
        scope=scope,
        level=level,
        confirmed_through=confirmed_through,
        publication_cutoff=publication_cutoff,
        source_policy_id="official-calendar-scan-v1",
        source_catalog_sha256=_digest(861),
        two_pass_verified=two_pass_verified,
        source_policy_verified=True,
    )


def test_horizon_resolves_confirmed_dates_but_not_future_dates() -> None:
    scope = CalendarScope("SH", 2026)
    horizon_at = datetime(2026, 9, 6, 23, 59, tzinfo=UTC)
    horizon = compose_official_calendar(
        snapshot_id=UUID(int=862),
        authority=OfficialAuthority.SSE,
        scope=scope,
        annual_notice=_annual(),
        rules=_rules(),
        scan=_scan(number=863, available_at=horizon_at),
        captured_at=_BASE,
        available_at=horizon_at,
        rule_profile=CalendarRuleProfile(scope=scope, required_rule_starts=(date(2026, 7, 6),)),
        coverage=_coverage(
            scope,
            level=CalendarCoverageLevel.CONFIRMED_HORIZON,
            confirmed_through=date(2026, 9, 6),
            publication_cutoff=horizon_at,
        ),
    )
    assert horizon.terminal is SnapshotTerminal.INDETERMINATE
    as_of = datetime(2026, 9, 6, 23, 59, tzinfo=UTC)
    confirmed = resolve("SH", date(2026, 9, 4), as_of, [horizon])
    future = resolve("SH", date(2026, 12, 31), as_of, [horizon])
    assert confirmed.status is CalendarResolutionStatus.INDETERMINATE
    assert confirmed.reason is CalendarResolutionReason.OFFICIAL_INCOMPLETE
    assert future.status is CalendarResolutionStatus.INDETERMINATE
    assert future.reason is CalendarResolutionReason.OFFICIAL_INCOMPLETE


def test_confirmed_horizon_cannot_extend_past_publication_date() -> None:
    scope = CalendarScope("SH", 2026)
    publication = _BASE
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        compose_official_calendar(
            snapshot_id=UUID(int=8630),
            authority=OfficialAuthority.SSE,
            scope=scope,
            annual_notice=_annual(),
            rules=_rules(),
            scan=_scan(number=8631, available_at=publication),
            captured_at=_BASE,
            available_at=publication,
            rule_profile=CalendarRuleProfile(scope=scope, required_rule_starts=(date(2026, 7, 6),)),
            coverage=_coverage(
                scope,
                level=CalendarCoverageLevel.CONFIRMED_HORIZON,
                confirmed_through=date(2026, 12, 31),
                publication_cutoff=publication,
            ),
        )


def test_final_year_requires_year_end_publication_watermark() -> None:
    scope = CalendarScope("SH", 2026)
    early = compose_official_calendar(
        snapshot_id=UUID(int=864),
        authority=OfficialAuthority.SSE,
        scope=scope,
        annual_notice=_annual(),
        rules=_rules(),
        scan=_scan(number=865),
        captured_at=_BASE,
        available_at=_BASE + timedelta(hours=8),
        rule_profile=CalendarRuleProfile(scope=scope, required_rule_starts=(date(2026, 7, 6),)),
        coverage=_coverage(
            scope,
            level=CalendarCoverageLevel.FINAL_YEAR,
            confirmed_through=date(2026, 12, 31),
            publication_cutoff=_BASE,
        ),
    )
    assert early.terminal is SnapshotTerminal.INDETERMINATE
    early_result = resolve(
        "SH",
        date(2026, 12, 31),
        _BASE + timedelta(days=1),
        [early],
    )
    assert early_result.status is CalendarResolutionStatus.INDETERMINATE

    year_end = datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)
    final = compose_official_calendar(
        snapshot_id=UUID(int=866),
        authority=OfficialAuthority.SSE,
        scope=scope,
        annual_notice=_annual(number=867),
        rules=_rules(),
        scan=_scan(number=868, available_at=year_end),
        captured_at=_BASE,
        available_at=year_end + timedelta(hours=1),
        rule_profile=CalendarRuleProfile(scope=scope, required_rule_starts=(date(2026, 7, 6),)),
        coverage=_coverage(
            scope,
            level=CalendarCoverageLevel.FINAL_YEAR,
            confirmed_through=date(2026, 12, 31),
            publication_cutoff=year_end,
        ),
    )
    assert final.terminal is SnapshotTerminal.INDETERMINATE


def test_multi_page_scan_with_all_none_cursors_is_rejected() -> None:
    source = _scan(number=869)
    assert source.bundle.pages[1].cursor_in is not None
    pages = tuple(
        CalendarScanPage(
            ordinal=page.ordinal,
            evidence=page.evidence,
            cursor_in=None,
            cursor_out=None,
        )
        for page in source.bundle.pages
    )
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        replace(
            source.bundle,
            pages=pages,
            evidence_ids=tuple(page.evidence.evidence_id for page in pages),
            artifact_sha256s=tuple(page.evidence.artifact_sha256 for page in pages),
            continuity_verified=True,
            complete=True,
        )


def test_multi_page_scan_rejects_repeated_cursor_tokens() -> None:
    source = _scan(number=8690)
    pages = tuple(
        CalendarScanPage(
            ordinal=page.ordinal,
            evidence=page.evidence,
            cursor_in=None if page.ordinal == 1 else "repeated",
            cursor_out=None if page.ordinal == source.bundle.page_count else "repeated",
        )
        for page in source.bundle.pages
    )

    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        replace(
            source.bundle,
            pages=pages,
            evidence_ids=tuple(page.evidence.evidence_id for page in pages),
            artifact_sha256s=tuple(page.evidence.artifact_sha256 for page in pages),
            continuity_verified=True,
            complete=True,
        )


def test_unstable_scan_policy_stays_indeterminate() -> None:
    scope = CalendarScope("SH", 2026)
    snapshot = compose_official_calendar(
        snapshot_id=UUID(int=870),
        authority=OfficialAuthority.SSE,
        scope=scope,
        annual_notice=_annual(),
        rules=_rules(),
        scan=_scan(number=871),
        captured_at=_BASE,
        available_at=_BASE + timedelta(hours=8),
        rule_profile=CalendarRuleProfile(scope=scope, required_rule_starts=(date(2026, 7, 6),)),
        coverage=_coverage(
            scope,
            level=CalendarCoverageLevel.FINAL_YEAR,
            confirmed_through=date(2026, 12, 31),
            publication_cutoff=datetime(2026, 12, 31, 23, 59, tzinfo=UTC),
            two_pass_verified=False,
        ),
    )
    assert snapshot.terminal is SnapshotTerminal.INDETERMINATE


def test_primary_provenance_must_match_composition_receipt() -> None:
    source = _complete_snapshot()
    assert source.composition_receipt is not None
    annual = source.composition_receipt.annual_notice.evidence
    assert annual.artifact_id is not None
    assert annual.capture_id is not None
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        CalendarSnapshot(
            snapshot_id=UUID(int=872),
            artifact_id=annual.artifact_id,
            capture_id=annual.capture_id,
            artifact_sha256=annual.artifact_sha256,
            authority=source.authority,
            scope=source.scope,
            captured_at=source.captured_at,
            available_at=source.available_at,
            terminal=source.terminal,
            days=source.days,
            evidence=source.evidence,
            scan_bundle=source.scan_bundle,
            composition_receipt=source.composition_receipt,
        )


def test_2026_complete_requires_an_explicit_rule_profile() -> None:
    scope = CalendarScope("SH", 2026)
    year_end = datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)
    snapshot = compose_official_calendar(
        snapshot_id=UUID(int=8730),
        authority=OfficialAuthority.SSE,
        scope=scope,
        annual_notice=_annual(),
        rules=_rules(),
        scan=_scan(number=8731, available_at=year_end),
        captured_at=_BASE,
        available_at=year_end + timedelta(hours=1),
        coverage=_coverage(
            scope,
            level=CalendarCoverageLevel.FINAL_YEAR,
            confirmed_through=date(2026, 12, 31),
            publication_cutoff=year_end,
        ),
    )

    assert snapshot.terminal is SnapshotTerminal.INDETERMINATE


def test_baseline_plus_ordered_temporary_deltas_recomputes_rows() -> None:
    scope = CalendarScope("SH", 2026)
    closure = date(2026, 3, 16)
    delta_evidence = _evidence(
        873,
        CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE,
        covers_full_exchange=True,
        covers_full_day=True,
    )
    delta = CalendarTemporaryClosureDelta(evidence=delta_evidence, closure_date=closure)
    second_closure = date(2026, 3, 17)
    second_delta_evidence = _evidence(
        876,
        CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE,
        covers_full_exchange=True,
        covers_full_day=True,
    )
    second_delta = CalendarTemporaryClosureDelta(
        evidence=second_delta_evidence,
        closure_date=second_closure,
    )
    days = tuple(
        CalendarDay(
            date=day.date,
            exchange="SH",
            is_trading_day=False,
            reason=CalendarDayReason.TEMPORARY_CLOSURE,
        )
        if day.date in {closure, second_closure}
        else day
        for day in _scan_days()
    )
    snapshot = compose_official_calendar(
        snapshot_id=UUID(int=874),
        authority=OfficialAuthority.SSE,
        scope=scope,
        annual_notice=_annual(),
        rules=_rules(),
        scan=_scan(
            number=875,
            days=days,
            delta_evidence=delta_evidence,
            deltas=(delta, second_delta),
        ),
        deltas=(delta, second_delta),
        captured_at=_BASE,
        available_at=_BASE + timedelta(hours=8),
        rule_profile=CalendarRuleProfile(scope=scope, required_rule_starts=(date(2026, 7, 6),)),
        coverage=_coverage(
            scope,
            level=CalendarCoverageLevel.CONFIRMED_HORIZON,
            confirmed_through=date(2026, 1, 1),
            publication_cutoff=_BASE,
        ),
    )
    assert snapshot.terminal is SnapshotTerminal.INDETERMINATE
    assert snapshot.days[closure.toordinal() - date(2026, 1, 1).toordinal()].reason is (
        CalendarDayReason.TEMPORARY_CLOSURE
    )
    assert snapshot.days[second_closure.toordinal() - date(2026, 1, 1).toordinal()].reason is (
        CalendarDayReason.TEMPORARY_CLOSURE
    )


def test_composition_receipt_rejects_scan_delta_set_mismatch() -> None:
    source = _complete_snapshot()
    assert source.composition_receipt is not None
    first_evidence = _evidence(
        8740,
        CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE,
        covers_full_exchange=True,
        covers_full_day=True,
    )
    second_evidence = _evidence(
        8741,
        CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE,
        covers_full_exchange=True,
        covers_full_day=True,
    )
    first = CalendarTemporaryClosureDelta(evidence=first_evidence, closure_date=date(2026, 3, 16))
    second = CalendarTemporaryClosureDelta(evidence=second_evidence, closure_date=date(2026, 3, 17))
    scan = _scan(
        number=8742,
        days=cast(tuple[CalendarDay, ...], source.days),
        delta_evidence=first_evidence,
        deltas=(first, second),
        available_at=source.available_at,
    )
    receipt = source.composition_receipt

    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        CalendarCompositionReceipt(
            authority=source.authority,
            scope=source.scope,
            annual_notice=receipt.annual_notice,
            rules=receipt.rules,
            rule_profile=receipt.rule_profile,
            scan=scan,
            deltas=(first,),
            primary_evidence=scan.evidence,
            coverage=receipt.coverage,
            scan_watermark=source.available_at,
        )


def test_delta_before_child_visibility_is_rejected_and_parent_is_unchanged() -> None:
    parent = compose_official_calendar(
        snapshot_id=UUID(int=876),
        authority=OfficialAuthority.SSE,
        scope=CalendarScope("SH", 2026),
        annual_notice=_annual(),
        rules=_rules(),
        scan=_scan(number=877),
        captured_at=_BASE,
        available_at=_BASE + timedelta(hours=8),
        rule_profile=CalendarRuleProfile(
            scope=CalendarScope("SH", 2026), required_rule_starts=(date(2026, 7, 6),)
        ),
        coverage=_coverage(
            CalendarScope("SH", 2026),
            level=CalendarCoverageLevel.CONFIRMED_HORIZON,
            confirmed_through=date(2026, 1, 1),
            publication_cutoff=_BASE,
        ),
    )
    delta = _evidence(
        878,
        CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE,
        available_at=_BASE + timedelta(days=2),
        covers_full_exchange=True,
        covers_full_day=True,
    )
    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        apply_temporary_closure(
            parent,
            snapshot_id=UUID(int=879),
            evidence=delta,
            closure_date=date(2026, 3, 16),
            captured_at=_BASE,
            available_at=_BASE + timedelta(days=1),
        )
    assert parent.snapshot_id == UUID(int=876)


def test_temporary_delta_supports_horizon_parent_without_promoting_terminal() -> None:
    scope = CalendarScope("SH", 2026)
    horizon_at = datetime(2026, 9, 6, 23, 59, tzinfo=UTC)
    parent = compose_official_calendar(
        snapshot_id=UUID(int=880),
        authority=OfficialAuthority.SSE,
        scope=scope,
        annual_notice=_annual(),
        rules=_rules(),
        scan=_scan(number=881, available_at=horizon_at),
        captured_at=_BASE,
        available_at=horizon_at,
        rule_profile=CalendarRuleProfile(scope=scope, required_rule_starts=(date(2026, 7, 6),)),
        coverage=_coverage(
            scope,
            level=CalendarCoverageLevel.CONFIRMED_HORIZON,
            confirmed_through=date(2026, 9, 6),
            publication_cutoff=horizon_at,
        ),
    )
    closure = date(2026, 9, 4)
    delta = _evidence(
        882,
        CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE,
        available_at=horizon_at + timedelta(hours=1),
        covers_full_exchange=True,
        covers_full_day=True,
    )
    successor_days = tuple(
        replace(day, is_trading_day=False, reason=CalendarDayReason.TEMPORARY_CLOSURE)
        if day.date == closure
        else day
        for day in _scan_days()
    )
    successor = _scan(
        number=883,
        days=successor_days,
        delta_evidence=delta,
        available_at=horizon_at + timedelta(hours=2),
    )
    child = apply_temporary_closure(
        parent,
        snapshot_id=UUID(int=884),
        evidence=delta,
        closure_date=closure,
        captured_at=horizon_at + timedelta(hours=1),
        available_at=horizon_at + timedelta(hours=3),
        successor_scan=successor,
    )
    assert child.terminal is SnapshotTerminal.INDETERMINATE
    assert child.composition_receipt is not None
    assert child.supersedes == parent.snapshot_id
    before = resolve("SH", closure, horizon_at, [parent, child])
    after = resolve("SH", closure, child.available_at, [parent, child])
    assert before.status is CalendarResolutionStatus.INDETERMINATE
    assert before.reason is CalendarResolutionReason.OFFICIAL_INCOMPLETE
    assert after.status is CalendarResolutionStatus.INDETERMINATE
    assert after.reason is CalendarResolutionReason.OFFICIAL_INCOMPLETE


def test_successor_scan_rejects_delta_set_not_reflected_in_rows() -> None:
    parent = _complete_snapshot()
    first_evidence = _evidence(
        8750,
        CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE,
        covers_full_exchange=True,
        covers_full_day=True,
    )
    second_evidence = _evidence(
        8751,
        CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE,
        covers_full_exchange=True,
        covers_full_day=True,
    )
    first = CalendarTemporaryClosureDelta(evidence=first_evidence, closure_date=date(2026, 3, 16))
    second = CalendarTemporaryClosureDelta(evidence=second_evidence, closure_date=date(2026, 3, 17))
    successor_days = tuple(
        CalendarDay(
            date=day.date,
            exchange="SH",
            is_trading_day=False,
            reason=CalendarDayReason.TEMPORARY_CLOSURE,
        )
        if day.date == first.closure_date
        else CalendarDay(
            date=day.date,
            exchange="SH",
            is_trading_day=day.is_trading_day,
            reason=cast(CalendarDayReason | None, day.reason),
        )
        for day in parent.days
    )
    successor = _scan(
        number=8752,
        days=successor_days,
        available_at=parent.available_at,
        delta_evidence=first_evidence,
        deltas=(first, second),
    )

    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        apply_temporary_closure(
            parent,
            snapshot_id=UUID(int=8753),
            evidence=first_evidence,
            closure_date=first.closure_date,
            captured_at=parent.available_at + timedelta(days=1),
            available_at=parent.available_at + timedelta(days=1, hours=1),
            successor_scan=successor,
        )


def test_successor_scan_pages_must_not_predate_delta_notice() -> None:
    parent = _complete_snapshot()
    delta = _evidence(
        8760,
        CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE,
        available_at=_BASE + timedelta(days=2),
        covers_full_exchange=True,
        covers_full_day=True,
    )
    closure = date(2026, 3, 16)
    successor_days = tuple(
        CalendarDay(
            date=day.date,
            exchange="SH",
            is_trading_day=False,
            reason=CalendarDayReason.TEMPORARY_CLOSURE,
        )
        if day.date == closure
        else CalendarDay(
            date=day.date,
            exchange="SH",
            is_trading_day=day.is_trading_day,
            reason=cast(CalendarDayReason | None, day.reason),
        )
        for day in parent.days
    )
    successor = _scan(
        number=8761,
        days=successor_days,
        available_at=_BASE,
        delta_evidence=delta,
    )

    with pytest.raises(AuthoritativeCalendarError, match="invalid calendar snapshot"):
        apply_temporary_closure(
            parent,
            snapshot_id=UUID(int=8762),
            evidence=delta,
            closure_date=closure,
            captured_at=parent.available_at + timedelta(days=1),
            available_at=parent.available_at + timedelta(days=3),
            successor_scan=successor,
        )


@pytest.mark.parametrize("use_legacy_delta_alias", [False, True])
def test_direct_compose_rejects_stale_delta_scan_pages(
    use_legacy_delta_alias: bool,
) -> None:
    scope = CalendarScope("SH", 2026)
    year_end = datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)
    delta = _evidence(
        8770 if not use_legacy_delta_alias else 8771,
        CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE,
        available_at=_BASE + timedelta(days=2),
        covers_full_exchange=True,
        covers_full_day=True,
    )
    closure = date(2026, 3, 16)
    stale_days = tuple(
        CalendarDay(
            date=day.date,
            exchange="SH",
            is_trading_day=False,
            reason=CalendarDayReason.TEMPORARY_CLOSURE,
        )
        if day.date == closure
        else day
        for day in _scan_days()
    )
    scan = _scan(
        number=8772 if not use_legacy_delta_alias else 8773,
        days=stale_days,
        available_at=_BASE,
        delta_evidence=delta if use_legacy_delta_alias else None,
        deltas=()
        if use_legacy_delta_alias
        else (CalendarTemporaryClosureDelta(evidence=delta, closure_date=closure),),
    )
    typed_delta = CalendarTemporaryClosureDelta(evidence=delta, closure_date=closure)
    snapshot = compose_official_calendar(
        snapshot_id=UUID(int=8774 if not use_legacy_delta_alias else 8775),
        authority=OfficialAuthority.SSE,
        scope=scope,
        annual_notice=_annual(),
        rules=_rules(),
        scan=scan,
        deltas=(typed_delta,),
        captured_at=_BASE,
        available_at=year_end + timedelta(hours=1),
        rule_profile=CalendarRuleProfile(scope=scope, required_rule_starts=(date(2026, 7, 6),)),
        coverage=_coverage(
            scope,
            level=CalendarCoverageLevel.FINAL_YEAR,
            confirmed_through=date(2026, 12, 31),
            publication_cutoff=year_end,
        ),
    )

    assert snapshot.terminal is SnapshotTerminal.INDETERMINATE
    assert snapshot.composition_receipt is None


def test_confirmed_horizon_uses_shanghai_publication_date() -> None:
    scope = CalendarScope("SH", 2026)
    publication_cutoff = datetime(2026, 9, 6, 0, 1, tzinfo=ZoneInfo("Asia/Shanghai"))

    coverage = _coverage(
        scope,
        level=CalendarCoverageLevel.CONFIRMED_HORIZON,
        confirmed_through=date(2026, 9, 6),
        publication_cutoff=publication_cutoff,
    )

    assert coverage.confirmed_through == date(2026, 9, 6)
