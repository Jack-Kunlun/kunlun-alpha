"""P6-N03 canonical limit-pool terminal materializer tests."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from emotion_core.ladder import LADDER_VERSION, BoardLadderSnapshot
from emotion_core.limit_pool import (
    TERMINAL_MATERIALIZER_VERSION,
    TerminalInstrumentEvidence,
    materialize_terminal_snapshot,
)
from emotion_core.models import (
    LIMIT_POOL_ALGORITHM_VERSION,
    LIMIT_RULE_VERSION,
    LimitPoolSnapshot,
    SnapshotObservationProvenance,
)
from emotion_core.pit import Instant
from emotion_core.provenance import SampleProvenance

AS_OF = Instant.parse("2026-08-25T06:42:00Z")


def _pool() -> LimitPoolSnapshot:
    return LimitPoolSnapshot(
        date="2026-08-25",
        timestamp=AS_OF.isoformat(),
        limit_up_count=1,
        limit_down_count=0,
        sealed_count=1,
        limit_up_instruments=("600000.SH",),
        total_open_count=0,
        provenance=(
            SnapshotObservationProvenance(
                unified_code="600000.SH",
                event_time="2026-08-25T01:31:00Z",
                available_time="2026-08-25T01:31:01Z",
                revision=1,
                source="vendor-a",
                source_version="vendor-a:v7",
                evidence_id="limit-600000-1",
            ),
        ),
        algorithm_version=LIMIT_POOL_ALGORITHM_VERSION,
        limit_rule_version=LIMIT_RULE_VERSION,
    )


def _ladder() -> BoardLadderSnapshot:
    return BoardLadderSnapshot(
        date="2026-08-25",
        boards={2: ["600000.SH"]},
        advancement={1: 0.5},
        provenance=SampleProvenance(
            algorithm_version=LADDER_VERSION,
            as_of=AS_OF.isoformat(),
            included=("600000.SH",),
            source_versions=("vendor-a:v7",),
            evidence_ids=("limit-600000-1",),
        ),
    )


def _entry(*, available_time: str = "2026-08-25T01:31:01Z") -> TerminalInstrumentEvidence:
    return TerminalInstrumentEvidence(
        instrument_id="600000.SH",
        name="浦发银行",
        exchange="SH",
        listing_board="MAIN",
        is_st=False,
        side="LIMIT_UP",
        state="SEALED",
        streak_days=2,
        previous_streak_days=1,
        open_count=0,
        price_cny=Decimal("11.00"),
        previous_close_cny=Decimal("10.00"),
        first_seal_time=Instant.parse("2026-08-25T01:31:00Z"),
        last_seal_time=Instant.parse("2026-08-25T01:31:00Z"),
        event_time=Instant.parse("2026-08-25T01:31:00Z"),
        available_time=Instant.parse(available_time),
        revision=1,
        source_version="vendor-a:v7",
        evidence_id="limit-600000-1",
    )


def test_materializer_maps_pool_ladder_and_rules_to_a_version_vector() -> None:
    projection = materialize_terminal_snapshot(
        pool_snapshot=_pool(),
        ladder_snapshot=_ladder(),
        entries=[_entry()],
        previous_day_eligible_counts={1: 2},
        available_time=AS_OF,
        processing_time=Instant.parse("2026-08-25T06:42:01Z"),
        revision=1,
    )

    assert projection.pool_algorithm_version == LIMIT_POOL_ALGORITHM_VERSION
    assert projection.limit_rule_version == LIMIT_RULE_VERSION
    assert projection.ladder_algorithm_version == LADDER_VERSION
    assert projection.materializer_version == TERMINAL_MATERIALIZER_VERSION
    assert projection.payload["ladder"] == [
        {
            "streakDays": 2,
            "count": 1,
            "previousDayEligibleCount": 2,
            "promotedCount": 1,
        }
    ]
    assert projection.clickhouse_row()["payload_digest"] == projection.payload_digest
    assert projection.clickhouse_row()["processing_time"] == "2026-08-25 06:42:01.000"


def test_materializer_rejects_future_instrument_evidence() -> None:
    with pytest.raises(ValueError, match="point-in-time eligible"):
        materialize_terminal_snapshot(
            pool_snapshot=_pool(),
            ladder_snapshot=_ladder(),
            entries=[_entry(available_time="2026-08-25T07:00:00Z")],
            previous_day_eligible_counts={1: 2},
            available_time=AS_OF,
            processing_time=Instant.parse("2026-08-25T06:42:01Z"),
            revision=1,
        )


def test_materializer_requires_partial_reasons() -> None:
    with pytest.raises(ValueError, match="missing_reasons"):
        materialize_terminal_snapshot(
            pool_snapshot=_pool(),
            ladder_snapshot=_ladder(),
            entries=[_entry()],
            previous_day_eligible_counts={1: 2},
            available_time=AS_OF,
            processing_time=Instant.parse("2026-08-25T06:42:01Z"),
            revision=1,
            completeness="PARTIAL",
        )


def test_materializer_digest_binds_the_complete_version_vector() -> None:
    base = materialize_terminal_snapshot(
        pool_snapshot=_pool(),
        ladder_snapshot=_ladder(),
        entries=[_entry()],
        previous_day_eligible_counts={1: 2},
        available_time=AS_OF,
        processing_time=Instant.parse("2026-08-25T06:42:01Z"),
        revision=1,
    )
    different_rule = replace(_pool(), limit_rule_version="limit_rules_v2")
    changed = materialize_terminal_snapshot(
        pool_snapshot=different_rule,
        ladder_snapshot=_ladder(),
        entries=[_entry()],
        previous_day_eligible_counts={1: 2},
        available_time=AS_OF,
        processing_time=Instant.parse("2026-08-25T06:42:01Z"),
        revision=1,
    )
    assert changed.payload == base.payload
    assert changed.payload_digest != base.payload_digest


def test_materializer_digest_binds_availability_and_provenance() -> None:
    base = materialize_terminal_snapshot(
        pool_snapshot=_pool(),
        ladder_snapshot=_ladder(),
        entries=[_entry()],
        previous_day_eligible_counts={1: 2},
        available_time=AS_OF,
        processing_time=Instant.parse("2026-08-25T06:42:01Z"),
        revision=1,
    )
    later = materialize_terminal_snapshot(
        pool_snapshot=_pool(),
        ladder_snapshot=_ladder(),
        entries=[_entry()],
        previous_day_eligible_counts={1: 2},
        available_time=Instant.parse("2026-08-25T06:42:30Z"),
        processing_time=Instant.parse("2026-08-25T06:42:31Z"),
        revision=1,
    )
    extra_provenance = replace(
        _ladder().provenance,
        source_versions=("vendor-z:v1", "vendor-a:v7"),
        evidence_ids=("limit-z-1", "limit-600000-1"),
    )
    changed_provenance = materialize_terminal_snapshot(
        pool_snapshot=_pool(),
        ladder_snapshot=replace(_ladder(), provenance=extra_provenance),
        entries=[_entry()],
        previous_day_eligible_counts={1: 2},
        available_time=AS_OF,
        processing_time=Instant.parse("2026-08-25T06:42:01Z"),
        revision=1,
    )

    assert later.payload == base.payload
    assert later.payload_digest != base.payload_digest
    assert later.snapshot_id != base.snapshot_id
    assert changed_provenance.payload == base.payload
    assert changed_provenance.source_versions == ("vendor-a:v7", "vendor-z:v1")
    assert changed_provenance.payload_digest != base.payload_digest
    assert changed_provenance.snapshot_id != base.snapshot_id


@pytest.mark.parametrize("price", ["NaN", "Infinity", "-Infinity", "-1", "0"])
def test_terminal_evidence_rejects_non_finite_or_non_positive_prices(price: str) -> None:
    with pytest.raises(ValueError, match="price"):
        replace(_entry(), price_cny=Decimal(price))
    with pytest.raises(ValueError, match="previous_close"):
        replace(_entry(), previous_close_cny=Decimal(price))


def test_materializer_rejects_non_finite_advancement() -> None:
    with pytest.raises(ValueError, match="advancement"):
        materialize_terminal_snapshot(
            pool_snapshot=_pool(),
            ladder_snapshot=replace(_ladder(), advancement={1: float("nan")}),
            entries=[_entry()],
            previous_day_eligible_counts={1: 2},
            available_time=AS_OF,
            processing_time=Instant.parse("2026-08-25T06:42:01Z"),
            revision=1,
        )


@pytest.mark.parametrize(
    "bad_counts",
    (
        {1: True},
        {True: 2},
        {99: -1},
    ),
)
def test_materializer_rejects_invalid_or_unused_previous_day_counts(
    bad_counts: dict[int, int],
) -> None:
    with pytest.raises(ValueError, match="previous-day eligible"):
        materialize_terminal_snapshot(
            pool_snapshot=_pool(),
            ladder_snapshot=_ladder(),
            entries=[_entry()],
            previous_day_eligible_counts=bad_counts,
            available_time=AS_OF,
            processing_time=Instant.parse("2026-08-25T06:42:01Z"),
            revision=1,
        )


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), True])
def test_materializer_rejects_invalid_unused_advancement(invalid: float) -> None:
    with pytest.raises(ValueError, match="advancement"):
        materialize_terminal_snapshot(
            pool_snapshot=_pool(),
            ladder_snapshot=replace(_ladder(), advancement={1: 0.5, 99: invalid}),
            entries=[_entry()],
            previous_day_eligible_counts={1: 2},
            available_time=AS_OF,
            processing_time=Instant.parse("2026-08-25T06:42:01Z"),
            revision=1,
        )


def test_terminal_evidence_rejects_boolean_integer_fields() -> None:
    for field in ("streak_days", "previous_streak_days", "open_count", "revision"):
        with pytest.raises(ValueError, match="integer"):
            replace(_entry(), **{field: True})
