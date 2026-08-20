"""Point-in-time value-object tests.

``Instant`` normalizes timezone-aware datetimes to a canonical UTC instant so
that equivalent representations of the same moment sort, compare and dedupe
identically, and rejects naive or malformed timestamps at the domain boundary.
``PriceObservation`` binds a :class:`~decimal.Decimal` value to its event and
availability instants plus source/version/evidence provenance so downstream
consumers never mix an observed value with a leaked or unattributed one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from emotion_core.pit import Instant, PriceObservation


def test_equivalent_timezone_representations_normalize_equal() -> None:
    # 06:30 at -05:00 is the same instant as 11:30Z.
    a = Instant.parse("2026-08-14T06:30:00.000-05:00")
    b = Instant.parse("2026-08-14T11:30:00.000Z")
    assert a == b
    assert hash(a) == hash(b)
    assert a.as_utc() == datetime(2026, 8, 14, 11, 30, tzinfo=UTC)


def test_offset_minus_five_does_not_leak_future_data() -> None:
    # A value available at 01:30-05:00 (== 06:30Z) is NOT yet available at a
    # decision made at 05:00Z; naive string ordering would wrongly pass it.
    available = Instant.parse("2026-08-14T01:30:00.000-05:00")  # 06:30Z
    decision = Instant.parse("2026-08-14T05:00:00.000Z")
    assert available > decision
    assert not (available <= decision)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        Instant.parse("2026-08-14T01:30:00.000")


def test_malformed_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError):
        Instant.parse("not-a-timestamp")


def test_none_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError):
        Instant.parse(None)  # type: ignore[arg-type]


def test_sorting_uses_canonical_instant_across_timezones() -> None:
    # Given three equivalent-or-ordered instants in mixed offsets, sorting by
    # the canonical UTC instant yields a stable deterministic order.
    raw = [
        "2026-08-14T11:30:00.000Z",  # 11:30Z
        "2026-08-14T06:30:00.000-05:00",  # 11:30Z (tie)
        "2026-08-14T12:00:00.000+00:00",  # 12:00Z
        "2026-08-14T07:00:00.000-05:00",  # 12:00Z (tie)
    ]
    instants = [Instant.parse(value) for value in raw]
    ordered = sorted(instants)
    assert ordered[0].as_utc() == datetime(2026, 8, 14, 11, 30, tzinfo=UTC)
    assert ordered[-1].as_utc() == datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def test_dedup_by_canonical_instant() -> None:
    a = Instant.parse("2026-08-14T06:30:00.000-05:00")
    b = Instant.parse("2026-08-14T11:30:00.000Z")
    assert len({a, b}) == 1


def test_price_observation_carries_decimal_and_provenance() -> None:
    obs = PriceObservation(
        value=Decimal("11.05"),
        event_time=Instant.parse("2026-08-14T07:00:00.000Z"),
        available_time=Instant.parse("2026-08-14T07:05:00.000Z"),
        source="vendor-a",
        source_version="quote_v2",
        evidence_id="evt-123",
    )
    assert obs.value == Decimal("11.05")
    assert isinstance(obs.value, Decimal)
    assert obs.source == "vendor-a"
    assert obs.evidence_id == "evt-123"


def test_price_observation_rejects_binary_float_value() -> None:
    with pytest.raises((TypeError, ValueError)):
        PriceObservation(
            value=11.05,  # type: ignore[arg-type]
            event_time=Instant.parse("2026-08-14T07:00:00.000Z"),
            available_time=Instant.parse("2026-08-14T07:05:00.000Z"),
            source="vendor-a",
            source_version="quote_v2",
            evidence_id="evt-123",
        )


def test_price_observation_available_at() -> None:
    decision = Instant.parse("2026-08-14T07:05:00.000Z")
    obs = PriceObservation(
        value=Decimal("11.05"),
        event_time=Instant.parse("2026-08-14T07:00:00.000Z"),
        available_time=Instant.parse("2026-08-14T07:05:00.000Z"),  # == decision
        source="vendor-a",
        source_version="quote_v2",
        evidence_id="evt-123",
    )
    # available_time == decision_time boundary is inclusive.
    assert obs.available_at(decision) is True

    later_decision = Instant.parse("2026-08-14T07:04:59.000Z")
    assert obs.available_at(later_decision) is False


def test_price_observation_missing_provenance_is_rejected() -> None:
    with pytest.raises(ValueError):
        PriceObservation(
            value=Decimal("11.05"),
            event_time=Instant.parse("2026-08-14T07:00:00.000Z"),
            available_time=Instant.parse("2026-08-14T07:05:00.000Z"),
            source="",  # missing provenance
            source_version="quote_v2",
            evidence_id="evt-123",
        )


# --- Round 3: stronger time invariants --------------------------------------


def test_event_time_after_available_time_is_rejected() -> None:
    # A value cannot become available before the event it refers to.
    with pytest.raises(ValueError, match="event_time"):
        PriceObservation(
            value=Decimal("11.05"),
            event_time=Instant.parse("2026-08-14T07:10:00.000Z"),
            available_time=Instant.parse("2026-08-14T07:05:00.000Z"),  # earlier
            source="vendor-a",
            source_version="quote_v2",
            evidence_id="evt-123",
        )


def test_event_time_not_instant_is_rejected() -> None:
    with pytest.raises(TypeError):
        PriceObservation(
            value=Decimal("11.05"),
            event_time="2026-08-14T07:00:00.000Z",  # type: ignore[arg-type]
            available_time=Instant.parse("2026-08-14T07:05:00.000Z"),
            source="vendor-a",
            source_version="quote_v2",
            evidence_id="evt-123",
        )


def test_available_time_not_instant_is_rejected() -> None:
    with pytest.raises(TypeError):
        PriceObservation(
            value=Decimal("11.05"),
            event_time=Instant.parse("2026-08-14T07:00:00.000Z"),
            available_time="2026-08-14T07:05:00.000Z",  # type: ignore[arg-type]
            source="vendor-a",
            source_version="quote_v2",
            evidence_id="evt-123",
        )


def test_available_at_requires_instant_decision_time() -> None:
    obs = PriceObservation(
        value=Decimal("11.05"),
        event_time=Instant.parse("2026-08-14T07:00:00.000Z"),
        available_time=Instant.parse("2026-08-14T07:05:00.000Z"),
        source="vendor-a",
        source_version="quote_v2",
        evidence_id="evt-123",
    )
    with pytest.raises(TypeError):
        obs.available_at("2026-08-14T07:05:00.000Z")  # type: ignore[arg-type]


def test_available_at_requires_event_time_before_decision() -> None:
    # An observation whose *event* is in the future of the decision must not be
    # usable, even if its availability instant is already at or before it.
    obs = PriceObservation(
        value=Decimal("11.05"),
        event_time=Instant.parse("2026-08-14T07:00:00.000Z"),
        available_time=Instant.parse("2026-08-14T07:00:00.000Z"),
        source="vendor-a",
        source_version="quote_v2",
        evidence_id="evt-123",
    )
    # Decision is before the event -> not usable (future event).
    assert obs.available_at(Instant.parse("2026-08-14T06:59:59.000Z")) is False
    # Decision at the event instant -> usable.
    assert obs.available_at(Instant.parse("2026-08-14T07:00:00.000Z")) is True
