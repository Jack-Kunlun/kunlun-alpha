"""Contract tests for the P1-N07 calendar quality projection."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from data_worker.jobs.calendars.calendar_quality import (
    CalendarClosureEvidence,
    CalendarQualityDay,
    CalendarQualityEvidenceLink,
    CalendarQualityOverlay,
    CalendarQualitySource,
    QualityAssessmentStatus,
    assess_calendar_quality,
)
from data_worker.jobs.calendars.calendar_quality_repository import (
    CalendarQualityOperationConflictError,
    CalendarQualityOverlayConflictError,
    InMemoryCalendarQualityRepository,
    PostgresCalendarQualityRepository,
)
from data_worker.storage import migrations as worker_migrations

_AVAILABLE = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)


def _source(
    *,
    source_id: UUID,
    source_kind: str,
    exchange: str,
    coverage_level: str,
    confirmed_through: date | None,
    days: tuple[CalendarQualityDay, ...] = (),
    closures: tuple[CalendarClosureEvidence, ...] = (),
) -> CalendarQualitySource:
    return CalendarQualitySource(
        source_id=source_id,
        source_kind=source_kind,
        source_name=f"{source_kind.lower()}-fixture",
        exchange=exchange,
        year=2026,
        captured_at=_AVAILABLE,
        available_at=_AVAILABLE,
        coverage_level=coverage_level,
        confirmed_through=confirmed_through,
        source_fingerprint="b" * 64,
        days=days,
        evidence_links=(
            CalendarQualityEvidenceLink(
                source_id=source_id,
                evidence_ref=f"evidence-{source_id.hex}",
                artifact_sha256="a" * 64,
            ),
        ),
        closures=closures,
    )


def test_sparse_sse_snapshot_never_infers_missing_dates() -> None:
    source = _source(
        source_id=uuid4(),
        source_kind="SPARSE",
        exchange="SH",
        coverage_level="UNKNOWN",
        confirmed_through=None,
        days=(
            CalendarQualityDay(
                calendar_date=date(2026, 1, 1),
                is_trading_day=False,
                reason="PUBLIC_HOLIDAY",
            ),
        ),
    )

    assessment = assess_calendar_quality(
        operation_id="sse-sparse-2026",
        exchange="SH",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(source,),
    )

    assert assessment.status is QualityAssessmentStatus.INDETERMINATE
    assert assessment.missing_dates == ()
    assert len(assessment.alerts) == 1
    assert assessment.alerts[0].kind == "MISSING_COVERAGE"
    assert assessment.alerts[0].calendar_date is None
    assert assessment.alerts[0].detail_code == "DATE_NOT_CONFIRMED"


def test_delayed_assessment_uses_detection_time_for_visibility() -> None:
    source = _source(
        source_id=uuid4(),
        source_kind="OFFICIAL",
        exchange="SZ",
        coverage_level="CONFIRMED_HORIZON",
        confirmed_through=date(2026, 9, 7),
        days=(CalendarQualityDay(calendar_date=date(2026, 9, 7), is_trading_day=True),),
    )
    source = replace(
        source,
        captured_at=_AVAILABLE - timedelta(minutes=2),
        available_at=_AVAILABLE - timedelta(minutes=1),
    )

    assessment = assess_calendar_quality(
        operation_id="delayed-assessment-2026",
        exchange="SZ",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(source,),
    )

    assert assessment.available_at == _AVAILABLE
    assert all(alert.available_at == _AVAILABLE for alert in assessment.alerts)


def test_complementary_official_horizons_aggregate_without_false_gaps() -> None:
    first = _source(
        source_id=uuid4(),
        source_kind="OFFICIAL",
        exchange="SZ",
        coverage_level="CONFIRMED_HORIZON",
        confirmed_through=date(2026, 1, 2),
        days=(CalendarQualityDay(calendar_date=date(2026, 1, 1), is_trading_day=True),),
    )
    second = _source(
        source_id=uuid4(),
        source_kind="OFFICIAL",
        exchange="SZ",
        coverage_level="CONFIRMED_HORIZON",
        confirmed_through=date(2026, 1, 3),
        days=(
            CalendarQualityDay(calendar_date=date(2026, 1, 2), is_trading_day=True),
            CalendarQualityDay(calendar_date=date(2026, 1, 3), is_trading_day=True),
        ),
    )

    assessment = assess_calendar_quality(
        operation_id="complementary-official-2026",
        exchange="SZ",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(first, second),
    )

    assert assessment.missing_dates == ()
    assert tuple(day.calendar_date for day in assessment.confirmed_days) == (
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
    )


def test_conflicting_official_observations_are_not_selected_or_marked_missing() -> None:
    first = _source(
        source_id=uuid4(),
        source_kind="OFFICIAL",
        exchange="SZ",
        coverage_level="CONFIRMED_HORIZON",
        confirmed_through=date(2026, 1, 2),
        days=(
            CalendarQualityDay(calendar_date=date(2026, 1, 1), is_trading_day=True),
            CalendarQualityDay(calendar_date=date(2026, 1, 2), is_trading_day=True),
        ),
    )
    second = _source(
        source_id=uuid4(),
        source_kind="OFFICIAL",
        exchange="SZ",
        coverage_level="CONFIRMED_HORIZON",
        confirmed_through=date(2026, 1, 2),
        days=(
            CalendarQualityDay(
                calendar_date=date(2026, 1, 1), is_trading_day=False, reason="SPECIAL"
            ),
            CalendarQualityDay(calendar_date=date(2026, 1, 2), is_trading_day=True),
        ),
    )

    assessment = assess_calendar_quality(
        operation_id="conflicting-official-2026",
        exchange="SZ",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(first, second),
    )

    assert date(2026, 1, 1) not in assessment.missing_dates
    assert date(2026, 1, 1) not in tuple(day.calendar_date for day in assessment.confirmed_days)
    assert any(
        alert.kind == "SOURCE_CONFLICT" and alert.calendar_date == date(2026, 1, 1)
        for alert in assessment.alerts
    )


def test_overlay_canonical_fingerprint_rejects_delimiter_collision() -> None:
    source_id = uuid4()
    source = _source(
        source_id=source_id,
        source_kind="SPARSE",
        exchange="SH",
        coverage_level="UNKNOWN",
        confirmed_through=None,
    )
    assessment = assess_calendar_quality(
        operation_id="overlay-delimiter-assessment",
        exchange="SH",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(source,),
    )
    repository = InMemoryCalendarQualityRepository()
    repository.persist_assessment(assessment)
    first = CalendarQualityOverlay(
        overlay_id=uuid4(),
        operation_id="overlay-delimiter-collision",
        assessment_id=assessment.assessment_id,
        source_id=source_id,
        calendar_date=date(2026, 1, 1),
        decision="NON_TRADING",
        reason_code="REVIEW",
        note="A:B",
        author="C",
        available_at=_AVAILABLE,
    )
    second = replace(first, overlay_id=uuid4(), note="A", author="B:C")

    assert repository.persist_manual_overlay(first).disposition == "CREATED"
    with pytest.raises(CalendarQualityOverlayConflictError):
        repository.persist_manual_overlay(second)


def test_szse_horizon_creates_missing_coverage_without_guessing_day_status() -> None:
    source = _source(
        source_id=uuid4(),
        source_kind="OFFICIAL",
        exchange="SZ",
        coverage_level="CONFIRMED_HORIZON",
        confirmed_through=date(2026, 9, 7),
        days=(
            CalendarQualityDay(
                calendar_date=date(2026, 9, 7),
                is_trading_day=True,
            ),
        ),
    )

    assessment = assess_calendar_quality(
        operation_id="szse-horizon-2026",
        exchange="SZ",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(source,),
    )

    assert assessment.status is QualityAssessmentStatus.MISSING_COVERAGE
    assert date(2026, 1, 1) in assessment.missing_dates
    assert date(2026, 9, 8) not in assessment.missing_dates
    assert date(2026, 12, 31) not in assessment.missing_dates
    assert all(day not in assessment.confirmed_days for day in assessment.missing_dates)


def test_horizon_missing_dates_use_each_source_horizon() -> None:
    first = _source(
        source_id=uuid4(),
        source_kind="OFFICIAL",
        exchange="SZ",
        coverage_level="CONFIRMED_HORIZON",
        confirmed_through=date(2026, 9, 7),
        days=(CalendarQualityDay(calendar_date=date(2026, 9, 7), is_trading_day=True),),
    )
    second = _source(
        source_id=uuid4(),
        source_kind="OFFICIAL",
        exchange="SZ",
        coverage_level="CONFIRMED_HORIZON",
        confirmed_through=date(2026, 9, 5),
        days=(
            # A row outside this source's declared horizon must not fill a
            # hole in the accepted aggregate horizon.
            CalendarQualityDay(calendar_date=date(2026, 9, 6), is_trading_day=True),
        ),
    )

    assessment = assess_calendar_quality(
        operation_id="szse-source-horizons-2026",
        exchange="SZ",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(first, second),
    )

    assert date(2026, 9, 6) in assessment.missing_dates


def test_in_memory_repository_rejects_forged_projection() -> None:
    source = _source(
        source_id=uuid4(),
        source_kind="SPARSE",
        exchange="SH",
        coverage_level="UNKNOWN",
        confirmed_through=None,
    )
    assessment = assess_calendar_quality(
        operation_id="sh-forged-2026",
        exchange="SH",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(source,),
    )
    forged = replace(assessment, status="MISSING_COVERAGE")

    with pytest.raises(Exception, match="persistence failed"):
        InMemoryCalendarQualityRepository().persist_assessment(forged)


def test_evidence_link_rejects_non_opaque_reference() -> None:
    source_id = uuid4()
    with pytest.raises(ValueError):
        CalendarQualityEvidenceLink(source_id, "https://example.invalid/raw", "a" * 64)
    with pytest.raises(ValueError):
        CalendarQualityEvidenceLink(source_id, "path/to/raw", "a" * 64)
    with pytest.raises(ValueError):
        CalendarQualityEvidenceLink(source_id, "raw evidence", "a" * 64)


def test_same_date_conflict_and_temporary_closure_retain_evidence() -> None:
    first_id = uuid4()
    second_id = uuid4()
    first = _source(
        source_id=first_id,
        source_kind="OFFICIAL",
        exchange="SZ",
        coverage_level="CONFIRMED_HORIZON",
        confirmed_through=date(2026, 8, 7),
        days=(
            CalendarQualityDay(
                calendar_date=date(2026, 8, 7),
                is_trading_day=True,
            ),
        ),
    )
    second = _source(
        source_id=second_id,
        source_kind="SECONDARY",
        exchange="SZ",
        coverage_level="CONFIRMED_HORIZON",
        confirmed_through=date(2026, 8, 7),
        days=(
            CalendarQualityDay(
                calendar_date=date(2026, 8, 7),
                is_trading_day=False,
                reason="TEMPORARY_CLOSURE",
            ),
        ),
        closures=(
            CalendarClosureEvidence(
                source_id=second_id,
                closure_date=date(2026, 8, 7),
                evidence_ref=f"closure-{second_id.hex}",
                artifact_sha256="a" * 64,
                captured_at=_AVAILABLE,
                available_at=_AVAILABLE,
            ),
        ),
    )

    assessment = assess_calendar_quality(
        operation_id="conflict-2026",
        exchange="SZ",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(first, second),
    )

    assert assessment.status is QualityAssessmentStatus.CONFLICT
    assert any(alert.kind == "SOURCE_CONFLICT" for alert in assessment.alerts)
    assert any(alert.kind == "TEMPORARY_CLOSURE" for alert in assessment.alerts)
    assert {first_id, second_id}.issubset(
        {source_id for alert in assessment.alerts for source_id in alert.source_ids}
    )


def test_missing_source_is_indeterminate_and_repository_is_operation_idempotent() -> None:
    assessment = assess_calendar_quality(
        operation_id="bj-missing-2026",
        exchange="BJ",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(),
    )
    assert assessment.status is QualityAssessmentStatus.MISSING_COVERAGE
    assert assessment.missing_dates == ()
    assert len(assessment.alerts) == 1
    assert assessment.alerts[0].calendar_date is None
    assert not assessment.alerts[0].source_ids

    repository = InMemoryCalendarQualityRepository()
    created = repository.persist_assessment(assessment)
    duplicate = repository.persist_assessment(assessment)
    assert created.disposition == "CREATED"
    assert duplicate.disposition == "DUPLICATE"
    assert duplicate.assessment_id == created.assessment_id

    changed = assess_calendar_quality(
        operation_id="bj-missing-2026",
        exchange="BJ",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(
            _source(
                source_id=uuid4(),
                source_kind="SPARSE",
                exchange="BJ",
                coverage_level="UNKNOWN",
                confirmed_through=None,
            ),
        ),
    )
    try:
        repository.persist_assessment(changed)
    except CalendarQualityOperationConflictError:
        pass
    else:
        raise AssertionError("same operation with different evidence must conflict")


def test_same_operation_with_different_detection_time_conflicts() -> None:
    source = _source(
        source_id=uuid4(),
        source_kind="SPARSE",
        exchange="SH",
        coverage_level="UNKNOWN",
        confirmed_through=None,
    )
    first = assess_calendar_quality(
        operation_id="same-operation-different-time",
        exchange="SH",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(source,),
    )
    second = assess_calendar_quality(
        operation_id="same-operation-different-time",
        exchange="SH",
        year=2026,
        detected_at=_AVAILABLE + timedelta(seconds=1),
        sources=(source,),
    )
    assert first.content_fingerprint != second.content_fingerprint

    repository = InMemoryCalendarQualityRepository()
    assert repository.persist_assessment(first).disposition == "CREATED"
    with pytest.raises(CalendarQualityOperationConflictError):
        repository.persist_assessment(second)


def test_postgres_persist_inserts_assessment_before_children() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def execute(self, query: str, _params: object = ()) -> None:
            self.queries.append(query)

        def fetchone(self) -> None:
            return None

    assessment = assess_calendar_quality(
        operation_id="bj-persist-2026",
        exchange="BJ",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(),
    )
    cursor = Cursor()

    repository = PostgresCalendarQualityRepository.__new__(PostgresCalendarQualityRepository)
    persist_method_name = "_persist"
    persist = getattr(repository, persist_method_name)
    result = persist(cursor, assessment)

    assert result.disposition == "CREATED"
    assessment_insert = next(
        index
        for index, query in enumerate(cursor.queries)
        if "INSERT INTO calendar_quality_assessments" in query
    )
    child_insert = next(
        index
        for index, query in enumerate(cursor.queries)
        if "INSERT INTO calendar_quality_alerts" in query
    )
    assert assessment_insert < child_insert


def test_quality_confirmed_constraint_tracks_all_referenced_columns() -> None:
    constraint_name = "calendar_quality_assessments_confirmed_ck"
    expected_constraints_name = "_CALENDAR_QUALITY_EXPECTED_CONSTRAINTS"
    expected_constraints = getattr(worker_migrations, expected_constraints_name)
    expected_spec = next(spec for spec in expected_constraints if spec.name == constraint_name)
    actual_expression = (
        "((coverage_level = ANY (ARRAY['UNKNOWN'::text, 'INDETERMINATE'::text])) "
        "AND confirmed_through IS NULL OR coverage_level = 'CONFIRMED_HORIZON'::text "
        "AND confirmed_through >= make_date(calendar_year, 1, 1) "
        "AND confirmed_through <= make_date(calendar_year, 12, 31) "
        "OR coverage_level = 'FINAL_YEAR'::text "
        "AND confirmed_through = make_date(calendar_year, 12, 31))"
    )

    class Cursor:
        def __init__(self) -> None:
            self._fetchall_calls = 0

        def execute(self, query: str, _params: object = ()) -> None:
            self._query = query

        def fetchall(self) -> list[tuple[object, ...]]:
            self._fetchall_calls += 1
            if "FROM pg_constraint" in self._query:
                return [
                    (
                        "calendar_quality_assessments",
                        constraint_name,
                        "c",
                        [8, 9, 6],
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        False,
                        False,
                        True,
                        False,
                        actual_expression,
                    )
                ]
            return [
                ("calendar_quality_assessments", 6, "calendar_year"),
                ("calendar_quality_assessments", 8, "coverage_level"),
                ("calendar_quality_assessments", 9, "confirmed_through"),
            ]

        def fetchone(self) -> tuple[str]:
            return ("quality_fixture",)

    verifier_name = "_verify_constraint_specs"
    verifier = getattr(worker_migrations, verifier_name)
    verifier(
        Cursor(),
        ("calendar_quality_assessments",),
        (expected_spec,),
        normalize_expressions=True,
    )


def test_manual_overlay_is_source_bound_append_only_and_point_in_time_filtered() -> None:
    source_id = uuid4()
    source = _source(
        source_id=source_id,
        source_kind="SPARSE",
        exchange="SH",
        coverage_level="UNKNOWN",
        confirmed_through=None,
        days=(
            CalendarQualityDay(
                calendar_date=date(2026, 1, 1),
                is_trading_day=False,
                reason="PUBLIC_HOLIDAY",
            ),
        ),
    )
    assessment = assess_calendar_quality(
        operation_id="sh-overlay-2026",
        exchange="SH",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(source,),
    )
    repository = InMemoryCalendarQualityRepository()
    repository.persist_assessment(assessment)
    overlay = CalendarQualityOverlay(
        overlay_id=uuid4(),
        operation_id="overlay-1",
        assessment_id=assessment.assessment_id,
        source_id=source_id,
        calendar_date=date(2026, 1, 1),
        decision="NON_TRADING",
        reason_code="OPERATOR_REVIEW",
        note="",
        author="operator",
        available_at=_AVAILABLE + timedelta(minutes=1),
    )
    assert repository.persist_manual_overlay(overlay).disposition == "CREATED"
    assert repository.persist_manual_overlay(overlay).disposition == "DUPLICATE"
    assert repository.list_manual_overlays(assessment.assessment_id, _AVAILABLE) == ()
    assert repository.list_manual_overlays(
        assessment.assessment_id, _AVAILABLE + timedelta(minutes=1)
    ) == (overlay,)

    changed = CalendarQualityOverlay(
        overlay_id=overlay.overlay_id,
        operation_id=overlay.operation_id,
        assessment_id=overlay.assessment_id,
        source_id=overlay.source_id,
        calendar_date=overlay.calendar_date,
        decision="REVIEW",
        reason_code=overlay.reason_code,
        note=overlay.note,
        author=overlay.author,
        available_at=overlay.available_at,
    )
    try:
        repository.persist_manual_overlay(changed)
    except CalendarQualityOverlayConflictError:
        pass
    else:
        raise AssertionError("same overlay operation with changed content must conflict")
