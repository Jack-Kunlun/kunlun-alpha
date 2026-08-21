"""Board ladder tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from emotion_core.ladder import (
    LADDER_VERSION,
    LimitUpRecord,
    compute_board_ladder,
    consecutive_boards,
)
from emotion_core.pit import Instant

TRADING_DAYS = [
    "2026-08-10",
    "2026-08-11",
    "2026-08-12",
    "2026-08-13",
    "2026-08-14",
]
DECISION_TIME = Instant.parse("2026-08-14T09:00:00Z")


def _rec(
    day: str,
    *,
    is_limit_up: bool = True,
    source_version: str = "limit_v1",
    evidence_id: str = "ev-1",
    available_time: str | None = None,
) -> LimitUpRecord:
    return LimitUpRecord(
        is_limit_up=is_limit_up,
        event_time=Instant.parse(f"{day}T01:00:00Z"),
        available_time=Instant.parse(available_time or f"{day}T07:00:00Z"),
        source_version=source_version,
        evidence_id=evidence_id,
    )


def test_consecutive_boards_across_weekend() -> None:
    history = {
        "A": {
            "2026-08-13": _rec("2026-08-13"),
            "2026-08-14": _rec("2026-08-14"),
        }
    }
    assert (
        consecutive_boards("A", "2026-08-14", TRADING_DAYS, history, decision_time=DECISION_TIME)
        == 2
    )


def test_suspended_day_does_not_break_streak() -> None:
    history = {
        "A": {
            "2026-08-12": _rec("2026-08-12"),
            "2026-08-14": _rec("2026-08-14"),
        }
    }
    suspended = {"A": {"2026-08-13"}}
    assert (
        consecutive_boards(
            "A",
            "2026-08-14",
            TRADING_DAYS,
            history,
            suspended,
            decision_time=DECISION_TIME,
        )
        == 2
    )


def test_broken_board_ends_streak() -> None:
    history = {
        "A": {
            "2026-08-13": _rec("2026-08-13", is_limit_up=False),
            "2026-08-14": _rec("2026-08-14"),
        }
    }
    assert (
        consecutive_boards("A", "2026-08-14", TRADING_DAYS, history, decision_time=DECISION_TIME)
        == 1
    )


def test_new_stock_starts_at_one_board() -> None:
    history = {"A": {"2026-08-14": _rec("2026-08-14")}}
    assert (
        consecutive_boards("A", "2026-08-14", TRADING_DAYS, history, decision_time=DECISION_TIME)
        == 1
    )


def test_ladder_distribution_and_advancement() -> None:
    history = {
        "A": {
            "2026-08-12": _rec("2026-08-12"),
            "2026-08-13": _rec("2026-08-13"),
            "2026-08-14": _rec("2026-08-14"),
        },
        "B": {
            "2026-08-13": _rec("2026-08-13"),
            "2026-08-14": _rec("2026-08-14", is_limit_up=False),
        },
        "C": {
            "2026-08-13": _rec("2026-08-13"),
            "2026-08-14": _rec("2026-08-14"),
        },
        "D": {"2026-08-14": _rec("2026-08-14")},
    }
    snapshot = compute_board_ladder(
        "2026-08-14", TRADING_DAYS, history, decision_time=DECISION_TIME
    )

    assert snapshot.boards[3] == ["A"]
    assert snapshot.boards[2] == ["C"]
    assert snapshot.boards[1] == ["D"]
    assert abs(snapshot.advancement[2] - 1.0) < 1e-9
    assert abs(snapshot.advancement[1] - 0.5) < 1e-9


def test_ladder_snapshot_carries_version() -> None:
    history = {"A": {"2026-08-14": _rec("2026-08-14")}}
    snapshot = compute_board_ladder(
        "2026-08-14", TRADING_DAYS, history, decision_time=DECISION_TIME
    )
    assert LADDER_VERSION == "board_ladder_v2"
    assert snapshot.version == LADDER_VERSION


def test_advancement_records_zero_when_today_is_explicit_false() -> None:
    history = {
        "A": {
            "2026-08-13": _rec("2026-08-13"),
            "2026-08-14": _rec("2026-08-14", is_limit_up=False),
        }
    }

    snapshot = compute_board_ladder(
        "2026-08-14", TRADING_DAYS, history, decision_time=DECISION_TIME
    )

    assert snapshot.advancement[1] == 0.0


def test_explicit_false_advancement_record_enters_provenance() -> None:
    history = {
        "A": {
            "2026-08-13": _rec(
                "2026-08-13",
                source_version="yesterday-v1",
                evidence_id="yesterday-ev",
            ),
            "2026-08-14": _rec(
                "2026-08-14",
                is_limit_up=False,
                source_version="today-false-v2",
                evidence_id="today-false-ev",
            ),
        }
    }

    snapshot = compute_board_ladder(
        "2026-08-14", TRADING_DAYS, history, decision_time=DECISION_TIME
    )

    assert "today-false-v2" in snapshot.provenance.source_versions
    assert "today-false-ev" in snapshot.provenance.evidence_ids


def test_missing_today_record_is_excluded_from_advancement_denominator() -> None:
    history = {
        "A": {"2026-08-13": _rec("2026-08-13")},
        "B": {
            "2026-08-13": _rec("2026-08-13"),
            "2026-08-14": _rec("2026-08-14"),
        },
    }

    snapshot = compute_board_ladder(
        "2026-08-14", TRADING_DAYS, history, decision_time=DECISION_TIME
    )

    assert snapshot.advancement[1] == 1.0
    assert snapshot.provenance.excluded["A:2026-08-14"] == "missing_at_decision_time"


def test_missing_historical_gap_is_recorded_and_stops_the_streak() -> None:
    history = {
        "A": {
            "2026-08-11": _rec("2026-08-11", evidence_id="before-gap"),
            "2026-08-13": _rec("2026-08-13", evidence_id="near"),
            "2026-08-14": _rec("2026-08-14", evidence_id="today"),
        }
    }

    snapshot = compute_board_ladder(
        "2026-08-14", TRADING_DAYS, history, decision_time=DECISION_TIME
    )

    assert snapshot.boards == {2: ["A"]}
    assert snapshot.provenance.excluded["A:2026-08-12"] == "missing_at_decision_time"
    assert "before-gap" not in snapshot.provenance.evidence_ids
    assert snapshot.provenance.evidence_ids == ("near", "today")


def test_future_event_is_excluded_from_boards_and_provenance() -> None:
    future = LimitUpRecord(
        is_limit_up=True,
        event_time=Instant.parse("2026-08-14T10:00:00Z"),
        available_time=Instant.parse("2026-08-14T10:01:00Z"),
        source_version="future-v",
        evidence_id="future-ev",
    )
    history = {
        "A": {
            "2026-08-13": _rec("2026-08-13"),
            "2026-08-14": future,
        }
    }

    snapshot = compute_board_ladder(
        "2026-08-14", TRADING_DAYS, history, decision_time=DECISION_TIME
    )

    assert snapshot.boards == {}
    assert snapshot.provenance.excluded["A:2026-08-14"] == "event_after_decision_time"
    assert "future-v" not in snapshot.provenance.source_versions
    assert "future-ev" not in snapshot.provenance.evidence_ids


def test_suspended_codes_recorded_as_exclusions() -> None:
    history = {
        "A": {
            "2026-08-13": _rec("2026-08-13"),
            "2026-08-14": _rec("2026-08-14"),
        }
    }
    suspended = {"A": {"2026-08-13"}}
    snapshot = compute_board_ladder(
        "2026-08-14", TRADING_DAYS, history, suspended, decision_time=DECISION_TIME
    )
    assert snapshot.exclusions.get("A") == ("2026-08-13",)


def test_ladder_carries_structured_provenance() -> None:
    history = {
        "A": {
            "2026-08-13": _rec("2026-08-13", evidence_id="a-1"),
            "2026-08-14": _rec("2026-08-14", evidence_id="a-2"),
        },
        "B": {"2026-08-14": _rec("2026-08-14", is_limit_up=False)},
    }
    snapshot = compute_board_ladder(
        "2026-08-14", TRADING_DAYS, history, decision_time=DECISION_TIME
    )

    prov = snapshot.provenance
    assert prov.algorithm_version == LADDER_VERSION
    assert prov.as_of == DECISION_TIME.isoformat()
    assert prov.included == ("A",)
    assert prov.sample_size == 1
    assert prov.excluded["B"] == "not_on_ladder"
    assert prov.evidence_ids == ("a-1", "a-2", "ev-1")


def test_ladder_provenance_records_suspension_exclusion_reason() -> None:
    history = {"A": {"2026-08-14": _rec("2026-08-14", is_limit_up=False)}}
    suspended = {"A": {"2026-08-13"}}
    snapshot = compute_board_ladder(
        "2026-08-14", TRADING_DAYS, history, suspended, decision_time=DECISION_TIME
    )
    assert "A" in snapshot.provenance.excluded


def test_typed_limit_up_history_counts_boards() -> None:
    history = {
        "A": {
            "2026-08-13": _rec("2026-08-13"),
            "2026-08-14": _rec("2026-08-14"),
        }
    }
    assert (
        consecutive_boards("A", "2026-08-14", TRADING_DAYS, history, decision_time=DECISION_TIME)
        == 2
    )


def test_ladder_provenance_aggregates_source_versions_and_evidence() -> None:
    history = {
        "A": {
            "2026-08-13": _rec("2026-08-13", source_version="limit_v1", evidence_id="ev-a1"),
            "2026-08-14": _rec("2026-08-14", source_version="limit_v2", evidence_id="ev-a2"),
        }
    }
    snapshot = compute_board_ladder(
        "2026-08-14", TRADING_DAYS, history, decision_time=DECISION_TIME
    )
    prov = snapshot.provenance
    assert prov.source_versions == ("limit_v1", "limit_v2")
    assert prov.evidence_ids == ("ev-a1", "ev-a2")


def test_bool_history_is_rejected() -> None:
    history = cast(
        Mapping[str, Mapping[str, LimitUpRecord]],
        {"A": {"2026-08-14": True}},
    )
    try:
        compute_board_ladder("2026-08-14", TRADING_DAYS, history, decision_time=DECISION_TIME)
    except TypeError as exc:
        assert "LimitUpRecord" in str(exc)
    else:
        raise AssertionError("bool history must be rejected")
