"""Conflict-preserving, replay and cursor recovery tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from ashare_contracts.providers import Capability
from data_worker.jobs.precious_metals_funds import FundCollector
from data_worker.jobs.precious_metals_funds.collector import NavObservation
from data_worker.raw import CaptureConflictError, LocalFileStorage
from data_worker.storage import InMemoryFundStorage, fund_checkpoint_key
from market_core.providers import RawFundProviderResponse
from market_core.providers.base import Provider

_EVENT = "2026-08-13T01:00:00+00:00"
_PUBLISH = "2026-08-13T02:00:00+00:00"
_INGEST = "2026-08-13T03:00:00+00:00"
_AVAILABLE = "2026-08-13T03:30:00+00:00"
_PROCESSING = "2026-08-13T04:00:00+00:00"


def _item(value: str, source: str = "provider-x") -> dict[str, object]:
    return {
        "unifiedCode": "518880.SH",
        "date": "2026-08-13",
        "nav": value,
        "eventTime": _EVENT,
        "publishTime": _PUBLISH,
        "ingestTime": _INGEST,
        "availableTime": _AVAILABLE,
        "processingTime": _PROCESSING,
        "source": source,
    }


class ScriptedProvider(Provider):
    source = "provider-x"

    def __init__(self, pages: list[RawFundProviderResponse]) -> None:
        self.pages = pages

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_FUND_NAV})

    def fetch_fund_nav(self, exchange: str, cursor: str | None = None) -> RawFundProviderResponse:
        return self.pages[0] if cursor is None else self.pages[1]


def _page(
    capture_id: str | None, item: dict[str, object], next_cursor: str | None
) -> RawFundProviderResponse:
    body = json.dumps(
        {"items": [item], "nextCursor": next_cursor},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return RawFundProviderResponse(
        body=body,
        request="GET /funds/nav?exchange=SH",
        capture_id=capture_id,
        source="provider-x",
        endpoint_kind="nav",
        run_id="run-1",
        source_revision="rev-1",
        ingest_time=datetime(2026, 8, 13, 3, 0, tzinfo=UTC),
        available_time=datetime(2026, 8, 13, 3, 30, tzinfo=UTC),
    )


def _collector(
    tmp_path: Path, pages: list[RawFundProviderResponse]
) -> tuple[FundCollector, InMemoryFundStorage]:
    persistence = InMemoryFundStorage()
    collector = FundCollector(
        ScriptedProvider(pages),
        LocalFileStorage(tmp_path),
        persistence,
        now=datetime(2026, 8, 13, 5, 0, tzinfo=UTC),
    )
    return collector, persistence


def test_equal_payloads_from_separate_captures_preserve_two_evidence_links(
    tmp_path: Path,
) -> None:
    item = _item("1.2500")
    collector, persistence = _collector(
        tmp_path,
        [_page("capture-a", item, "page-2"), _page("capture-b", item, None)],
    )

    result = collector.collect("nav", "SH")

    assert len(result.accepted) == 2
    evidence = persistence.evidence()
    assert {entry.raw_capture_id for entry in evidence} == {"capture-a", "capture-b"}
    assert len(persistence.observations("nav")) == 1


def test_conflicting_values_are_both_persisted_with_quality_event(tmp_path: Path) -> None:
    collector, persistence = _collector(
        tmp_path,
        [
            _page("capture-a", _item("1.2500", "provider-a"), "page-2"),
            _page("capture-b", _item("1.2600", "provider-b"), None),
        ],
    )

    result = collector.collect("nav", "SH")

    assert len(result.accepted) == 2
    observations = [cast(NavObservation, item) for item in persistence.observations("nav")]
    assert {item.value.nav for item in observations} == {
        Decimal("1.2500"),
        Decimal("1.2600"),
    }
    conflicts = [event for event in persistence.quality_events() if event.kind == "SOURCE_CONFLICT"]
    assert len(conflicts) == 1
    assert len(conflicts[0].evidence_ids) == 2


def test_exact_capture_replay_is_idempotent_and_changed_payload_conflicts(tmp_path: Path) -> None:
    item = _item("1.2500")
    collector, persistence = _collector(tmp_path, [_page("capture-a", item, None)])

    first = collector.collect("nav", "SH")
    first_attempt = cast(str, first.checkpoint["attempt_id"])
    collector.replay_captures(
        "nav",
        "provider-x",
        "2026-08-13",
        exchange="SH",
        run_id="run-1",
        source_revision="rev-1",
        attempt_id=first_attempt,
    )
    assert len(persistence.observations("nav")) == 1
    assert persistence.get_checkpoint(fund_checkpoint_key("default", "nav", "SH")) is not None

    changed, _ = _collector(tmp_path, [_page("capture-a", _item("1.2700"), None)])
    with pytest.raises(CaptureConflictError):
        changed.collect("nav", "SH")


def test_cursor_loop_is_rejected_and_final_cursor_none_is_checkpointed(tmp_path: Path) -> None:
    looping = _page("capture-loop", _item("1.2500"), "loop")
    repeated = _page("capture-loop-next", _item("1.2500"), "loop")
    collector, persistence = _collector(tmp_path, [looping, repeated])
    with pytest.raises(ValueError, match="cursor"):
        collector.collect("nav", "SH")
    checkpoint = persistence.get_checkpoint(fund_checkpoint_key("default", "nav", "SH"))
    assert checkpoint is not None
    assert checkpoint["complete"] is False
    assert checkpoint["committed_page_count"] == 1


def test_cursor_tokens_are_hashed_before_raw_capture_identifier_use(tmp_path: Path) -> None:
    collector, persistence = _collector(
        tmp_path,
        [
            _page("capture-a", _item("1.2500"), "provider/cursor"),
            _page(None, _item("1.2500"), None),
        ],
    )

    result = collector.collect("nav", "SH")

    assert len(result.accepted) == 2
    assert all("/" not in evidence.raw_capture_id for evidence in persistence.evidence())
