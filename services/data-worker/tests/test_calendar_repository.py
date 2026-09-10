"""Calendar repository scope, version, and correction isolation tests."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import cast

import pytest
from ashare_contracts.calendar_holiday import Exchange, Holiday, Reason
from data_worker.jobs.calendars.repository import (
    CalendarOperationConflictError,
    CalendarScopeAmbiguityError,
    CalendarScopeError,
    InMemoryCalendarRepository,
)


def test_in_memory_operation_id_is_idempotent_and_conflict_safe() -> None:
    repository = InMemoryCalendarRepository()
    first_rows = [_holiday("2026-01-01")]
    second_rows = [_holiday("2026-02-17")]

    first = repository.save_version(
        "source-a", 2026, first_rows, exchange="SH", operation_id="operation-1"
    )
    assert (
        repository.save_version(
            "source-a", 2026, first_rows, exchange="SH", operation_id="operation-1"
        )
        == first
    )
    with pytest.raises(CalendarOperationConflictError):
        repository.save_version(
            "source-a", 2026, second_rows, exchange="SH", operation_id="operation-1"
        )
    assert repository.latest_version_id("source-a", "SH", 2026) == first


def test_in_memory_find_operation_version_is_read_only_and_conflict_safe() -> None:
    repository = InMemoryCalendarRepository()
    rows = [_holiday("2026-01-01")]
    other_rows = [_holiday("2026-02-17")]
    version_id = repository.save_version(
        "source-a", 2026, rows, exchange="SH", operation_id="operation-lookup"
    )
    before_audit = repository.audit_log()

    assert (
        repository.find_operation_version(
            "source-a",
            2026,
            rows,
            exchange="SH",
            operation_id="operation-lookup",
        )
        == version_id
    )
    assert (
        repository.find_operation_version(
            "source-a",
            2026,
            rows,
            exchange="SH",
            operation_id="missing-operation",
        )
        is None
    )
    with pytest.raises(CalendarOperationConflictError):
        repository.find_operation_version(
            "source-a",
            2026,
            [],
            exchange="SZ",
            operation_id="operation-lookup",
        )
    with pytest.raises(CalendarOperationConflictError):
        repository.find_operation_version(
            "source-a",
            2026,
            other_rows,
            exchange="SH",
            operation_id="operation-lookup",
        )

    assert repository.audit_log() == before_audit
    assert repository.latest_version_id("source-a", "SH", 2026) == version_id


def _holiday(
    value: str,
    *,
    exchange: str = "SH",
    note: str | None = None,
) -> Holiday:
    return Holiday.model_validate(
        {
            "date": value,
            "exchange": exchange,
            "reason": "PUBLIC_HOLIDAY",
            "note": note,
        }
    )


def test_compound_scope_tracks_empty_and_repeated_latest_independently() -> None:
    repository = InMemoryCalendarRepository()
    sh_2026 = repository.save_version("source-a", 2026, [_holiday("2026-01-01")], exchange="SH")
    sz_2026 = repository.save_version("source-a", 2026, [], exchange="SZ")
    sh_2027 = repository.save_version("source-a", 2027, [_holiday("2027-01-01")], exchange="SH")

    assert repository.latest_version_id("source-a", "SH", 2026) == sh_2026
    assert repository.latest_version_id("source-a", "SZ", 2026) == sz_2026
    assert repository.latest_version_id("source-a", "SH", 2027) == sh_2027
    assert repository.source_holidays("source-a", exchange="SH", year=2026) == [
        _holiday("2026-01-01")
    ]
    assert repository.source_holidays("source-a", exchange="SZ", year=2026) == []
    assert repository.source_holidays("source-a", exchange="SH", year=2027) == [
        _holiday("2027-01-01")
    ]


def test_recollecting_one_scope_keeps_other_histories_and_versions_unchanged() -> None:
    repository = InMemoryCalendarRepository()
    old_sh_2026 = repository.save_version("source-a", 2026, [_holiday("2026-01-01")], exchange="SH")
    sz_2026 = repository.save_version("source-a", 2026, [], exchange="SZ")
    sh_2027 = repository.save_version("source-a", 2027, [_holiday("2027-01-01")], exchange="SH")
    replacement_sh_2026 = repository.save_version(
        "source-a", 2026, [_holiday("2026-02-17")], exchange="SH"
    )

    assert repository.latest_version_id("source-a", "SH", 2026) == replacement_sh_2026
    assert repository.get_version(old_sh_2026) == [_holiday("2026-01-01")]
    assert repository.latest_version_id("source-a", "SZ", 2026) == sz_2026
    assert repository.latest_version_id("source-a", "SH", 2027) == sh_2027
    with pytest.raises(CalendarScopeAmbiguityError, match="calendar scope is ambiguous"):
        repository.source_holidays("source-a")


def test_source_and_scope_unknown_are_distinct_from_explicit_empty_snapshot() -> None:
    repository = InMemoryCalendarRepository()

    assert repository.source_holidays("missing-source") == []
    assert repository.latest_version_id("missing-source", "SH", 2026) is None

    empty_version = repository.save_version("source-a", 2026, [], exchange="SH")

    assert empty_version
    assert repository.latest_version_id("source-a", "SH", 2026) == empty_version
    assert repository.source_holidays("source-a") == []
    assert repository.source_holidays("source-a", exchange="SH", year=2026) == []


def test_legacy_three_argument_save_derives_one_homogeneous_scope() -> None:
    repository = InMemoryCalendarRepository()

    version_id = repository.save_version("source-a", 2026, [_holiday("2026-01-01")])

    assert repository.latest_version_id("source-a", "SH", 2026) == version_id
    assert repository.source_holidays("source-a") == [_holiday("2026-01-01")]


def test_legacy_three_argument_empty_save_is_rejected_without_counter_or_state_change() -> None:
    repository = InMemoryCalendarRepository()

    with pytest.raises(CalendarScopeError, match="calendar scope is invalid"):
        repository.save_version("source-a", 2026, [])

    assert repository.audit_log() == []
    version_id = repository.save_version("source-a", 2026, [_holiday("2026-01-01")])
    assert version_id == "source-a:2026:v1"


def test_source_only_reads_require_one_distinct_scope_and_explicit_scope_is_paired() -> None:
    repository = InMemoryCalendarRepository()
    repository.save_version("source-a", 2026, [_holiday("2026-01-01")], exchange="SH")

    with pytest.raises(
        CalendarScopeError, match="calendar exchange and year must be provided together"
    ):
        repository.source_holidays("source-a", exchange="SH")
    with pytest.raises(
        CalendarScopeError, match="calendar exchange and year must be provided together"
    ):
        repository.source_holidays("source-a", year=2026)

    repository.save_version("source-a", 2026, [], exchange="SZ")
    with pytest.raises(CalendarScopeAmbiguityError, match="calendar scope is ambiguous"):
        repository.source_holidays("source-a")


@pytest.mark.parametrize(
    ("source", "year", "exchange"),
    [
        ("", 2026, "SH"),
        ("source-a", True, "SH"),
        ("source-a", 0, "SH"),
        ("source-a", 10000, "SH"),
        ("source-a", 2026, "sh"),
        ("source-a", 2026, "SSE"),
        ("source-a", 2026, ""),
        ("source-a", 2026, None),
    ],
)
def test_invalid_explicit_scope_is_rejected_before_state_change(
    source: object, year: object, exchange: object
) -> None:
    repository = InMemoryCalendarRepository()
    before_audit = repository.audit_log()

    with pytest.raises(CalendarScopeError, match="calendar scope is invalid"):
        repository.save_version(
            cast(str, source),
            cast(int, year),
            [],
            exchange=cast(str | None, exchange),
        )

    assert repository.audit_log() == before_audit == []
    version_id = repository.save_version("source-a", 2026, [], exchange="SH")
    assert version_id == "source-a:2026:v1"


def test_mixed_exchange_or_year_rows_are_rejected_before_counter_and_versions_change() -> None:
    repository = InMemoryCalendarRepository()
    mixed_exchange = [_holiday("2026-01-01"), _holiday("2026-02-17", exchange="SZ")]
    mixed_year = [_holiday("2026-01-01"), _holiday("2025-12-31")]

    for rows in (mixed_exchange, mixed_year):
        with pytest.raises(CalendarScopeError, match="calendar scope is invalid"):
            repository.save_version("source-a", 2026, rows)
        assert repository.audit_log() == []

    version_id = repository.save_version("source-a", 2026, [], exchange="SH")
    assert version_id == "source-a:2026:v1"


def test_invalid_row_type_is_rejected_without_persisting_partial_input() -> None:
    repository = InMemoryCalendarRepository()

    with pytest.raises(CalendarScopeError, match="calendar scope is invalid"):
        repository.save_version("source-a", 2026, cast(list[Holiday], [_holiday("2026-01-01"), {}]))

    assert repository.audit_log() == []
    assert repository.latest_version_id("source-a", "SH", 2026) is None


def test_legacy_scope_inference_revalidates_the_derived_exchange_value() -> None:
    repository = InMemoryCalendarRepository()
    row = _holiday("2026-01-01")
    object.__setattr__(row, "exchange", SimpleNamespace(value="XX"))

    with pytest.raises(CalendarScopeError, match="calendar scope is invalid"):
        repository.save_version("source-a", 2026, [row])

    assert repository.audit_log() == []
    assert repository.latest_version_id("source-a", "SH", 2026) is None


@pytest.mark.parametrize(
    ("fake_field", "explicit_exchange"),
    [
        ("exchange", None),
        ("exchange", "SH"),
        ("date", None),
        ("date", "SH"),
        ("reason", None),
        ("reason", "SH"),
        ("note", None),
        ("note", "SH"),
        ("missing_reason", "SH"),
        ("missing_note", "SH"),
    ],
)
def test_save_rejects_fake_or_missing_fields_before_mutating_scope_state(
    fake_field: str, explicit_exchange: str | None
) -> None:
    repository = InMemoryCalendarRepository()
    initial_version = repository.save_version("source-a", 2026, [], exchange="SH")
    before_audit = repository.audit_log()
    row = _holiday("2026-01-01")
    if fake_field == "exchange":
        object.__setattr__(row, "exchange", SimpleNamespace(value="SH"))
    elif fake_field == "date":
        object.__setattr__(row, "date", SimpleNamespace(year=2026))
    elif fake_field == "reason":
        object.__setattr__(row, "reason", "PUBLIC_HOLIDAY")
    elif fake_field == "note":
        object.__setattr__(row, "note", SimpleNamespace(value="not-text"))
    elif fake_field == "missing_reason":
        row = Holiday.model_construct(date=date(2026, 1, 1), exchange=Exchange.sh)
    else:
        row = Holiday.model_construct(
            date=date(2026, 1, 1), exchange=Exchange.sh, reason=Reason.public_holiday
        )
        object.__delattr__(row, "note")

    with pytest.raises(CalendarScopeError, match="calendar scope is invalid"):
        repository.save_version("source-a", 2026, [row], exchange=explicit_exchange)

    assert repository.audit_log() == before_audit
    assert repository.latest_version_id("source-a", "SH", 2026) == initial_version
    assert repository.get_version(initial_version) == []
    next_version = repository.save_version(
        "source-a", 2026, [_holiday("2026-02-17")], exchange="SH"
    )
    assert next_version == "source-a:2026:v2"


@pytest.mark.parametrize("missing_field", ["exchange", "date"])
def test_save_rejects_missing_identity_fields_with_controlled_scope_error(
    missing_field: str,
) -> None:
    repository = InMemoryCalendarRepository()
    if missing_field == "exchange":
        row = Holiday.model_construct(date=date(2026, 1, 1), reason=Reason.public_holiday)
    else:
        row = Holiday.model_construct(exchange=Exchange.sh, reason=Reason.public_holiday)

    with pytest.raises(CalendarScopeError, match="calendar scope is invalid"):
        repository.save_version("source-a", 2026, [row], exchange="SH")

    assert repository.audit_log() == []
    assert repository.latest_version_id("source-a", "SH", 2026) is None


def test_save_and_reads_are_deep_copied() -> None:
    repository = InMemoryCalendarRepository()
    original = _holiday("2026-01-01", note="original")
    rows = [original]
    repository.save_version("source-a", 2026, rows, exchange="SH")

    original.note = "mutated input"
    rows.append(_holiday("2026-02-17"))
    loaded = repository.source_holidays("source-a", exchange="SH", year=2026)
    loaded[0].note = "mutated output"

    assert repository.source_holidays("source-a", exchange="SH", year=2026) == [
        _holiday("2026-01-01", note="original")
    ]


def test_single_version_implicit_correction_is_bound_to_that_version() -> None:
    repository = InMemoryCalendarRepository()
    version_id = repository.save_version("source-a", 2026, [_holiday("2026-01-01")], exchange="SH")
    before_source = repository.get_version(version_id)

    repository.apply_correction("2026-01-02", "TEMPORARY_CLOSURE", "manual", "ops")

    corrections = repository.correction_overlay()
    assert len(corrections) == 1
    assert corrections[0].version_id == version_id
    assert repository.corrections() == corrections
    assert repository.get_version(version_id) == before_source


def test_no_version_implicit_correction_and_overlay_are_empty_or_rejected_safely() -> None:
    repository = InMemoryCalendarRepository()

    assert repository.correction_overlay() == []
    with pytest.raises(CalendarScopeError, match="calendar scope is invalid"):
        repository.apply_correction("2026-01-01", "PUBLIC_HOLIDAY", "manual", "ops")
    assert repository.audit_log() == []


def test_implicit_correction_and_overlay_reject_multiple_versions_even_same_scope() -> None:
    repository = InMemoryCalendarRepository()
    first = repository.save_version("source-a", 2026, [], exchange="SH")
    repository.save_version("source-a", 2026, [_holiday("2026-02-17")], exchange="SH")
    before_audit = repository.audit_log()

    with pytest.raises(CalendarScopeAmbiguityError, match="calendar scope is ambiguous"):
        repository.apply_correction("2026-01-02", "TEMPORARY_CLOSURE", "manual", "ops")
    with pytest.raises(CalendarScopeAmbiguityError, match="calendar scope is ambiguous"):
        repository.correction_overlay()

    assert repository.audit_log() == before_audit
    assert repository.get_version(first) == []


def test_explicit_correction_is_isolated_to_exact_version() -> None:
    repository = InMemoryCalendarRepository()
    sh_version = repository.save_version("source-a", 2026, [_holiday("2026-01-01")], exchange="SH")
    sz_version = repository.save_version("source-a", 2026, [], exchange="SZ")
    before_sh = repository.get_version(sh_version)
    before_sz = repository.get_version(sz_version)

    repository.apply_correction(
        "2026-01-02", "TEMPORARY_CLOSURE", "manual", "ops", version_id=sh_version
    )

    assert [item.version_id for item in repository.correction_overlay(sh_version)] == [sh_version]
    assert repository.correction_overlay(sz_version) == []
    assert repository.get_version(sh_version) == before_sh
    assert repository.get_version(sz_version) == before_sz


@pytest.mark.parametrize("invalid_date", ["2025-01-02", "2026-1-2", "2026-02-30", None])
def test_correction_date_must_be_canonical_and_match_target_year(invalid_date: object) -> None:
    repository = InMemoryCalendarRepository()
    version_id = repository.save_version("source-a", 2026, [], exchange="SH")
    before_audit = repository.audit_log()

    with pytest.raises(CalendarScopeError, match="calendar scope is invalid"):
        repository.apply_correction(
            cast(str, invalid_date), "TEMPORARY_CLOSURE", "manual", "ops", version_id
        )

    assert repository.audit_log() == before_audit
    assert repository.correction_overlay(version_id) == []


def test_unknown_version_ids_use_controlled_errors_and_do_not_change_snapshots() -> None:
    repository = InMemoryCalendarRepository()
    version_id = repository.save_version("source-a", 2026, [], exchange="SH")
    before_audit = repository.audit_log()

    for operation in (
        lambda: repository.get_version("sensitive-version-marker"),
        lambda: repository.correction_overlay("sensitive-version-marker"),
        lambda: repository.apply_correction(
            "2026-01-02",
            "TEMPORARY_CLOSURE",
            "manual",
            "ops",
            "sensitive-version-marker",
        ),
    ):
        with pytest.raises(KeyError, match="unknown calendar version"):
            operation()

    assert repository.audit_log() == before_audit
    assert repository.get_version(version_id) == []


def test_explicit_scope_empty_snapshot_is_visible_only_in_that_scope() -> None:
    repository = InMemoryCalendarRepository()
    repository.save_version("source-a", 2026, [], exchange="SZ")
    repository.save_version("source-b", 2026, [_holiday("2026-01-01")], exchange="SH")

    assert repository.source_holidays("source-a", exchange="SZ", year=2026) == []
    assert repository.source_holidays("source-a", exchange="SH", year=2026) == []
    assert repository.source_holidays("source-b", exchange="SH", year=2026) == [
        _holiday("2026-01-01")
    ]
