"""Point-in-time snapshot tests (P2-R01 R3-4, blocking #2).

A snapshot at ``as_of`` must satisfy *both* the event-time and the
availability-time constraint: only observations for the matching
``trading_date`` whose ``event_time <= as_of`` AND ``available_time <= as_of``
are considered. Among the candidates for one identity the highest revision that
is already available at ``as_of`` wins — so a later correction that is not yet
available never rewrites an earlier historical snapshot. The snapshot records
the provenance (revision / source version / evidence id) of every observation
it actually used.
"""

from __future__ import annotations

from decimal import Decimal

from emotion_core.limit_pool import (
    InstrumentContext,
    LimitBarObservation,
    LimitPoolAggregator,
)
from emotion_core.pit import Instant
from market_core.models.validators import Bar, ExchangeId


def _bar(
    code: str,
    timestamp: str,
    close: Decimal,
    exchange: ExchangeId = "SH",
    date: str = "2026-08-13",
) -> Bar:
    return Bar(
        unified_code=code,
        exchange=exchange,
        date=date,
        interval="MINUTE_1",
        session="CONTINUOUS",
        timestamp=timestamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        amount=close * Decimal("1000"),
        price_type="RAW",
    )


def _obs(
    code: str,
    event_time: str,
    close: Decimal,
    *,
    available_time: str,
    revision: int = 0,
    source: str = "vendor-a",
    source_version: str = "v1",
    evidence_id: str = "ev-1",
    exchange: ExchangeId = "SH",
    date: str = "2026-08-13",
) -> LimitBarObservation:
    return LimitBarObservation(
        bar=_bar(code, event_time, close, exchange=exchange, date=date),
        event_time=Instant.parse(event_time),
        available_time=Instant.parse(available_time),
        revision=revision,
        source=source,
        source_version=source_version,
        evidence_id=evidence_id,
    )


def _context(
    code: str, prev_close: Decimal = Decimal("10.00"), board: str = "MAIN", is_st: bool = False
) -> InstrumentContext:
    return InstrumentContext(unified_code=code, prev_close=prev_close, board=board, is_st=is_st)


def test_snapshot_excludes_not_yet_available_observation() -> None:
    # event_time is at 01:32 but the observation only became available at 15:00.
    # A snapshot at 11:00 must NOT see it, even though its event_time <= as_of.
    aggregator = LimitPoolAggregator({"600000.SH": _context("600000.SH")})
    aggregator.feed(
        _obs(
            "600000.SH",
            "2026-08-13T01:32:00.000Z",
            Decimal("11.00"),
            available_time="2026-08-13T07:00:00.000Z",  # 15:00 CST
        )
    )
    snap = aggregator.snapshot(as_of="2026-08-13T03:00:00.000Z", trading_date="2026-08-13")
    assert snap.limit_up_count == 0  # not available yet at 11:00 CST


def test_snapshot_uses_revision_available_at_as_of() -> None:
    # revision 1 available at 02:00Z (10:00 CST), revision 2 available at
    # 07:00Z (15:00 CST). A snapshot at 03:00Z (11:00 CST) must use revision 1;
    # a snapshot at 08:00Z (16:00 CST) must use revision 2.
    aggregator = LimitPoolAggregator({"600000.SH": _context("600000.SH")})
    aggregator.feed(
        _obs(
            "600000.SH",
            "2026-08-13T01:32:00.000Z",
            Decimal("11.00"),  # revision 1: a limit-up seal
            available_time="2026-08-13T02:00:00.000Z",
            revision=1,
            source_version="v1",
            evidence_id="ev-r1",
        )
    )
    aggregator.feed(
        _obs(
            "600000.SH",
            "2026-08-13T01:32:00.000Z",
            Decimal("10.80"),  # revision 2: corrected, not a limit-up
            available_time="2026-08-13T07:00:00.000Z",
            revision=2,
            source_version="v2",
            evidence_id="ev-r2",
        )
    )

    early = aggregator.snapshot(as_of="2026-08-13T03:00:00.000Z", trading_date="2026-08-13")
    assert early.limit_up_count == 1  # revision 2 not available yet -> use rev 1

    late = aggregator.snapshot(as_of="2026-08-13T08:00:00.000Z", trading_date="2026-08-13")
    assert late.limit_up_count == 0  # revision 2 now available -> correction wins


def test_snapshot_records_provenance_of_used_observations() -> None:
    aggregator = LimitPoolAggregator({"600000.SH": _context("600000.SH")})
    aggregator.feed(
        _obs(
            "600000.SH",
            "2026-08-13T01:32:00.000Z",
            Decimal("11.00"),
            available_time="2026-08-13T01:32:00.000Z",
            revision=3,
            source="vendor-a",
            source_version="v7",
            evidence_id="ev-42",
        )
    )
    snap = aggregator.snapshot(as_of="2026-08-13T03:00:00.000Z", trading_date="2026-08-13")
    assert snap.limit_up_count == 1
    prov = snap.provenance
    assert len(prov) == 1
    entry = prov[0]
    assert entry.unified_code == "600000.SH"
    assert entry.revision == 3
    assert entry.source == "vendor-a"
    assert entry.source_version == "v7"
    assert entry.evidence_id == "ev-42"


def test_later_correction_does_not_rewrite_earlier_snapshot() -> None:
    # A snapshot taken at an early as_of must be stable even after a later,
    # not-yet-available correction is fed.
    aggregator = LimitPoolAggregator({"600000.SH": _context("600000.SH")})
    aggregator.feed(
        _obs(
            "600000.SH",
            "2026-08-13T01:32:00.000Z",
            Decimal("11.00"),
            available_time="2026-08-13T02:00:00.000Z",
            revision=1,
        )
    )
    before = aggregator.snapshot(as_of="2026-08-13T03:00:00.000Z", trading_date="2026-08-13")
    assert before.limit_up_count == 1

    # Feed a correction that only becomes available much later.
    aggregator.feed(
        _obs(
            "600000.SH",
            "2026-08-13T01:32:00.000Z",
            Decimal("10.80"),
            available_time="2026-08-13T07:00:00.000Z",
            revision=2,
        )
    )
    after = aggregator.snapshot(as_of="2026-08-13T03:00:00.000Z", trading_date="2026-08-13")
    assert after.limit_up_count == 1  # unchanged: correction not available at 11:00
    assert after == before
