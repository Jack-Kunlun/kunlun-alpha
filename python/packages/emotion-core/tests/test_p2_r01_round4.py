"""P2-R01 repair round 4 regression tests."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from itertools import permutations
from typing import cast

import pytest
from emotion_core.ladder import LimitUpRecord, compute_board_ladder
from emotion_core.limit_pool import (
    InstrumentContext,
    LimitBarObservation,
    LimitPoolAggregator,
    RevisionConflictError,
    canonicalize_observations,
    compute_limit_facts,
)
from emotion_core.pit import Instant
from market_core.models.validators import Bar, ExchangeId


def _bar(
    code: str,
    timestamp: str,
    close: Decimal,
    *,
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
    timestamp: str,
    close: Decimal,
    *,
    revision: int = 0,
    available_time: str | None = None,
    source: str = "vendor-a",
    source_version: str = "v1",
    evidence_id: str = "ev-1",
    exchange: ExchangeId = "SH",
    date: str = "2026-08-13",
) -> LimitBarObservation:
    return LimitBarObservation(
        bar=_bar(code, timestamp, close, exchange=exchange, date=date),
        event_time=Instant.parse(timestamp),
        available_time=Instant.parse(available_time or timestamp),
        revision=revision,
        source=source,
        source_version=source_version,
        evidence_id=evidence_id,
    )


def _context(code: str, *, board: str = "MAIN") -> InstrumentContext:
    return InstrumentContext(
        unified_code=code,
        prev_close=Decimal("10.00"),
        board=board,
        is_st=False,
    )


def test_lower_revision_conflict_is_ignored_after_winning_revision_is_known() -> None:
    low_a = _obs("600000.SH", "2026-08-13T01:32:00Z", Decimal("11.00"), revision=0)
    low_b = _obs("600000.SH", "2026-08-13T01:32:00Z", Decimal("10.80"), revision=0)
    high = _obs("600000.SH", "2026-08-13T01:32:00Z", Decimal("10.50"), revision=1)

    low_then_high = canonicalize_observations([low_a, low_b, high])
    high_then_low = canonicalize_observations([high, low_a, low_b])

    assert low_then_high == high_then_low == [high]


def test_all_observation_permutations_have_the_same_canonical_result() -> None:
    observations = [
        _obs("600000.SH", "2026-08-13T01:31:00Z", Decimal("10.50")),
        _obs("600000.SH", "2026-08-13T01:32:00Z", Decimal("11.00")),
        _obs("600000.SH", "2026-08-13T01:32:00Z", Decimal("10.80"), revision=1),
    ]

    results = [canonicalize_observations(list(order)) for order in permutations(observations)]

    assert all(result == results[0] for result in results)


def test_highest_revision_conflict_rejects_in_every_arrival_order() -> None:
    low = _obs("600000.SH", "2026-08-13T01:32:00Z", Decimal("10.50"), revision=0)
    high_a = _obs("600000.SH", "2026-08-13T01:32:00Z", Decimal("11.00"), revision=1)
    high_b = _obs("600000.SH", "2026-08-13T01:32:00Z", Decimal("10.80"), revision=1)

    for order in permutations([low, high_a, high_b]):
        with pytest.raises(RevisionConflictError):
            canonicalize_observations(list(order))


def test_same_winning_revision_compares_pit_and_provenance_fields() -> None:
    base = _obs(
        "600000.SH",
        "2026-08-13T01:32:00Z",
        Decimal("11.00"),
        revision=2,
        available_time="2026-08-13T02:00:00Z",
    )
    variants = [
        replace(base, available_time=Instant.parse("2026-08-13T02:01:00Z")),
        replace(base, source="vendor-b"),
        replace(base, source_version="v2"),
        replace(base, evidence_id="ev-2"),
    ]

    for variant in variants:
        with pytest.raises(RevisionConflictError):
            canonicalize_observations([base, variant])


def test_feed_conflict_is_atomic_and_later_revision_recovers() -> None:
    contexts = {"600000.SH": _context("600000.SH")}
    aggregator = LimitPoolAggregator(contexts)
    first = aggregator.feed(_obs("600000.SH", "2026-08-13T01:32:00Z", Decimal("11.00"), revision=0))
    before_events = aggregator.events()

    with pytest.raises(RevisionConflictError):
        aggregator.feed(_obs("600000.SH", "2026-08-13T01:32:00Z", Decimal("10.80"), revision=0))

    assert aggregator.events() == before_events

    recovered = aggregator.feed(
        _obs("600000.SH", "2026-08-13T01:32:00Z", Decimal("10.80"), revision=1)
    )
    assert recovered.revision == first.revision + 1
    assert [event.event_type for event in recovered.retractions] == ["LIMIT_UP"]
    assert aggregator.events() == []


def test_bare_bar_is_rejected_by_public_limit_pool_flows() -> None:
    raw_bar = _bar("600000.SH", "2026-08-13T01:32:00Z", Decimal("11.00"))
    contexts = {"600000.SH": _context("600000.SH")}

    with pytest.raises(TypeError, match="LimitBarObservation"):
        compute_limit_facts([raw_bar], contexts)  # type: ignore[list-item]

    with pytest.raises(TypeError, match="LimitBarObservation"):
        LimitPoolAggregator(contexts).feed(raw_bar)  # type: ignore[arg-type]


def test_pool_facts_use_sh_sz_and_bj_exchange_rules() -> None:
    observations = [
        _obs("600000.SH", "2026-08-13T01:32:00Z", Decimal("11.00"), exchange="SH"),
        _obs("000001.SZ", "2026-08-13T01:32:00Z", Decimal("11.00"), exchange="SZ"),
        _obs(
            "430001.BJ",
            "2026-08-13T01:32:00Z",
            Decimal("11.00"),
            exchange="BJ",
        ),
    ]
    contexts = {
        "600000.SH": _context("600000.SH"),
        "000001.SZ": _context("000001.SZ"),
        "430001.BJ": _context("430001.BJ", board="BSE"),
    }

    events = compute_limit_facts(observations, contexts)

    assert sorted((event.unified_code, event.exchange) for event in events) == [
        ("000001.SZ", "SZ"),
        ("600000.SH", "SH"),
    ]


def test_pool_facts_reject_unknown_exchange() -> None:
    observation = _obs("600000.SH", "2026-08-13T01:32:00Z", Decimal("11.00"))
    object.__setattr__(observation.bar, "exchange", cast(ExchangeId, "XX"))

    with pytest.raises(ValueError, match="unknown exchange"):
        compute_limit_facts([observation], {"600000.SH": _context("600000.SH")})


TRADING_DAYS = ["2026-08-13", "2026-08-14"]
DECISION_TIME = Instant.parse("2026-08-14T09:00:00Z")


def _record(
    day: str,
    *,
    is_limit_up: bool = True,
    available_time: str | None = None,
    source_version: str = "limit-v1",
    evidence_id: str = "limit-ev-1",
) -> LimitUpRecord:
    event_time = Instant.parse(f"{day}T01:00:00Z")
    return LimitUpRecord(
        is_limit_up=is_limit_up,
        event_time=event_time,
        available_time=Instant.parse(available_time or f"{day}T02:00:00Z"),
        source_version=source_version,
        evidence_id=evidence_id,
    )


def test_ladder_excludes_future_available_record_without_treating_it_as_false() -> None:
    history = {
        "A": {
            "2026-08-13": _record("2026-08-13"),
            "2026-08-14": _record(
                "2026-08-14",
                available_time="2026-08-14T12:00:00Z",
                source_version="future-v",
                evidence_id="future-ev",
            ),
        }
    }

    snapshot = compute_board_ladder(
        "2026-08-14",
        TRADING_DAYS,
        history,
        decision_time=DECISION_TIME,
    )

    assert snapshot.boards == {}
    assert any(
        key.startswith("A:") and reason == "not_available_at_decision_time"
        for key, reason in snapshot.provenance.excluded.items()
    )
    assert "future-v" not in snapshot.provenance.source_versions
    assert "future-ev" not in snapshot.provenance.evidence_ids


def test_ladder_advancement_excludes_unavailable_today_from_denominator() -> None:
    history = {
        "A": {
            "2026-08-13": _record("2026-08-13", evidence_id="a-yesterday"),
            "2026-08-14": _record(
                "2026-08-14",
                available_time="2026-08-14T12:00:00Z",
                evidence_id="a-future",
            ),
        },
        "B": {
            "2026-08-13": _record("2026-08-13", evidence_id="b-yesterday"),
            "2026-08-14": _record("2026-08-14", evidence_id="b-today"),
        },
    }

    snapshot = compute_board_ladder(
        "2026-08-14",
        TRADING_DAYS,
        history,
        decision_time=DECISION_TIME,
    )

    assert snapshot.advancement[1] == 1.0
    assert "a-future" not in snapshot.provenance.evidence_ids
    assert "b-today" in snapshot.provenance.evidence_ids


def test_ladder_requires_typed_records_and_decision_time() -> None:
    with pytest.raises(TypeError, match="LimitUpRecord"):
        compute_board_ladder(
            "2026-08-14",
            TRADING_DAYS,
            {"A": {"2026-08-14": True}},  # type: ignore[dict-item]
            decision_time=DECISION_TIME,
        )

    with pytest.raises(TypeError, match="decision_time"):
        compute_board_ladder("2026-08-14", TRADING_DAYS, {}, decision_time=None)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="decision_time"):
        compute_board_ladder("2026-08-14", TRADING_DAYS, {})  # type: ignore[call-arg]


def test_ladder_requires_non_empty_record_provenance_and_valid_event_order() -> None:
    with pytest.raises(ValueError, match="source_version"):
        LimitUpRecord(
            is_limit_up=True,
            event_time=Instant.parse("2026-08-14T01:00:00Z"),
            available_time=Instant.parse("2026-08-14T02:00:00Z"),
            source_version="",
            evidence_id="ev-1",
        )

    with pytest.raises(ValueError, match="event_time"):
        LimitUpRecord(
            is_limit_up=True,
            event_time=Instant.parse("2026-08-14T03:00:00Z"),
            available_time=Instant.parse("2026-08-14T02:00:00Z"),
            source_version="v1",
            evidence_id="ev-1",
        )
