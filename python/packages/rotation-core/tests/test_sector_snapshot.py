from __future__ import annotations

from decimal import Decimal

import pytest
from market_core.models.validators import Bar
from rotation_core.snapshot import (
    SectorBarObservation,
    SnapshotAggregator,
    SnapshotRevisionConflictError,
    compute_snapshot,
)
from rotation_core.taxonomy import Sector, SectorMembership, SectorTaxonomy

_DATE = "2026-08-13"
_DECISION = "2026-08-13T02:02:00Z"


def _taxonomy(codes: list[str]) -> SectorTaxonomy:
    return SectorTaxonomy(
        [
            Sector(
                "s1",
                "测试板块",
                None,
                "INDUSTRY",
                "taxonomy",
                "2020-01-01",
                None,
                "taxonomy-v1",
                "2020-01-01T00:00:00Z",
                "sector-s1",
            )
        ],
        [
            SectorMembership(
                code,
                "s1",
                "2020-01-01",
                None,
                "taxonomy",
                "membership-v1",
                "2020-01-01T00:00:00Z",
                f"membership-{code}",
            )
            for code in codes
        ],
        ["taxonomy"],
    )


def _observation(
    code: str,
    close: str,
    amount: str,
    minute: int,
    *,
    available_minute: int | None = None,
    revision: int = 0,
    evidence_id: str | None = None,
) -> SectorBarObservation:
    event_time = f"{_DATE}T02:{minute:02d}:00Z"
    available = available_minute if available_minute is not None else minute
    bar = Bar(
        unified_code=code,
        exchange="SH",
        date=_DATE,
        interval="MINUTE_1",
        session="CONTINUOUS",
        timestamp=event_time,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=1000,
        amount=Decimal(amount),
        price_type="RAW",
    )
    return SectorBarObservation(
        bar,
        Decimal("10"),
        f"{_DATE}T02:{available:02d}:00Z",
        "bars",
        "bars-v1",
        evidence_id or f"bar-{code}-{minute}-r{revision}",
        revision,
    )


def test_snapshot_contains_speed_freshness_sample_and_evidence() -> None:
    taxonomy = _taxonomy(["600000.SH", "600001.SH", "600002.SH"])
    observations = [
        _observation("600000.SH", "10.0", "500", 0),
        _observation("600000.SH", "11.0", "1000", 1),
        _observation("600001.SH", "10.5", "2000", 1),
    ]
    snapshot = compute_snapshot("s1", _DATE, _DECISION, taxonomy, observations)
    assert snapshot.average_change == 0.075
    assert snapshot.speed == 0.1
    assert snapshot.turnover == Decimal("3000")
    assert snapshot.breadth == 1.0
    assert snapshot.leader == "600000.SH"
    assert snapshot.sample_size == 2
    assert snapshot.member_count == 3
    assert snapshot.freshness_seconds == 60
    assert snapshot.confidence == pytest.approx(2 / 3, abs=1e-6)
    assert snapshot.excluded["600002.SH"] == "missing_or_unavailable_bar"
    assert snapshot.version == "sector_snapshot_v2"
    assert len(snapshot.evidence) == 2


def test_future_or_unavailable_bar_is_excluded() -> None:
    taxonomy = _taxonomy(["600000.SH", "600001.SH"])
    observations = [
        _observation("600000.SH", "11", "1000", 3),
        _observation("600001.SH", "11", "1000", 1, available_minute=3),
    ]
    snapshot = compute_snapshot("s1", _DATE, _DECISION, taxonomy, observations)
    assert snapshot.sample_size == 0
    assert snapshot.leader is None
    assert snapshot.excluded == {
        "600000.SH": "missing_or_unavailable_bar",
        "600001.SH": "missing_or_unavailable_bar",
    }


def test_batch_and_reverse_arrival_stream_are_identical() -> None:
    taxonomy = _taxonomy(["600000.SH", "600001.SH"])
    observations = [
        _observation("600000.SH", "10", "500", 0),
        _observation("600000.SH", "11", "1000", 1),
        _observation("600001.SH", "10.5", "2000", 1),
    ]
    batch = compute_snapshot("s1", _DATE, _DECISION, taxonomy, observations)
    aggregator = SnapshotAggregator("s1", _DATE, taxonomy)
    for observation in reversed(observations):
        aggregator.feed(observation)
    assert aggregator.snapshot(_DECISION) == batch


def test_higher_revision_correction_replaces_earlier_payload() -> None:
    taxonomy = _taxonomy(["600000.SH"])
    original = _observation("600000.SH", "11", "1000", 1, revision=0)
    corrected = _observation("600000.SH", "9", "900", 1, revision=1)
    aggregator = SnapshotAggregator("s1", _DATE, taxonomy)
    aggregator.feed(original)
    aggregator.feed(corrected)
    snapshot = aggregator.snapshot(_DECISION)
    assert snapshot.average_change == -0.1
    assert snapshot.turnover == Decimal("900")


def test_same_revision_conflict_fails_closed_without_poisoning_aggregator() -> None:
    taxonomy = _taxonomy(["600000.SH"])
    first = _observation("600000.SH", "11", "1000", 1, evidence_id="same", revision=0)
    conflict = _observation("600000.SH", "9", "900", 1, evidence_id="same", revision=0)
    aggregator = SnapshotAggregator("s1", _DATE, taxonomy)
    aggregator.feed(first)
    with pytest.raises(SnapshotRevisionConflictError):
        aggregator.feed(conflict)
    assert aggregator.snapshot(_DECISION).average_change == 0.1
