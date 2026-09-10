"""P1-N06 Tushare instrument-master contract tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from data_worker.jobs.instruments.tushare_master import (
    TUSHARE_COLLECTION_PARTITIONS,
    TUSHARE_FUND_BASIC_FIELDS,
    TUSHARE_INSTRUMENT_PROFILE_VERSION,
    TUSHARE_STOCK_BASIC_FIELDS,
    InstrumentMasterDisposition,
    InstrumentMasterTransportError,
    TushareInstrumentCollector,
    TushareInstrumentConfig,
    TushareInstrumentResponse,
    TushareInstrumentTransport,
    parse_tushare_instrument_page,
    replay_tushare_instrument_master_run,
)
from data_worker.raw.storage import LocalFileStorage
from market_core.instrument import ListingLifecycle, TradingAvailability


def test_operator_source_revision_is_rejected() -> None:
    with pytest.raises(ValueError, match="source revision"):
        TushareInstrumentConfig(token="token", source_revision="operator-asserted")


_OBSERVED = datetime(2026, 9, 8, 1, 0, tzinfo=UTC)


def _envelope(fields: tuple[str, ...], values: dict[str, object]) -> bytes:
    return json.dumps(
        {
            "code": 0,
            "msg": "",
            "data": {
                "fields": list(fields),
                "items": [[values.get(field, "") for field in fields]],
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


def _empty(fields: tuple[str, ...]) -> bytes:
    return json.dumps(
        {"code": 0, "msg": "", "data": {"fields": list(fields), "items": []}},
        separators=(",", ":"),
    ).encode()


def _rows(fields: tuple[str, ...], values: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {
            "code": 0,
            "msg": "",
            "data": {
                "fields": list(fields),
                "items": [[item.get(field, "") for field in fields] for item in values],
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


def _stock(code: str, status: str, name: str = "示例证券") -> bytes:
    return _envelope(
        TUSHARE_STOCK_BASIC_FIELDS,
        {
            "ts_code": f"{code}.SH",
            "symbol": code,
            "name": name,
            "market": "主板",
            "exchange": "SSE",
            "list_status": status,
            "list_date": "20200101",
            "delist_date": "20260101" if status == "D" else "",
        },
    )


def _fund(code: str, status: str) -> bytes:
    return _envelope(
        TUSHARE_FUND_BASIC_FIELDS,
        {
            "ts_code": f"{code}.SH",
            "name": "示例ETF",
            "market": "E",
            "status": status,
            "list_date": "20200101",
            "delist_date": "20260101" if status == "D" else "",
        },
    )


def _pop_transport(
    responses: list[TushareInstrumentResponse],
) -> TushareInstrumentTransport:
    def transport(
        url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> TushareInstrumentResponse:
        del url, headers, body, timeout_seconds
        return responses.pop(0)

    return transport


def test_tushare_config_keeps_token_out_of_repr() -> None:
    config = TushareInstrumentConfig(token="secret-token-for-test")

    assert TUSHARE_INSTRUMENT_PROFILE_VERSION
    assert "secret-token-for-test" not in repr(config)


def test_parser_separates_st_risk_from_listing_and_availability() -> None:
    records = parse_tushare_instrument_page(
        _stock("600000", "L", "*ST示例"),
        api_name="stock_basic",
        status_partition="L",
        market_partition=None,
        observed_at=_OBSERVED,
        available_at=_OBSERVED,
        evidence_ref="page-evidence",
        source_revision="tushare-2026-09-08",
    )

    assert records[0].listing_lifecycle is ListingLifecycle.LISTED
    assert records[0].trading_availability is TradingAvailability.ACTIVE
    assert records[0].risk_tags == ("ST",)
    assert records[0].instrument_id == "600000.SH"


def test_business_fingerprint_ignores_observation_provenance() -> None:
    record = parse_tushare_instrument_page(
        _stock("600000", "L"),
        api_name="stock_basic",
        status_partition="L",
        market_partition=None,
        observed_at=_OBSERVED,
        available_at=_OBSERVED,
        evidence_ref="page-evidence-1",
        source_revision="provider-revision-1",
    )[0]
    repeated_observation = replace(
        record,
        observed_at=_OBSERVED + timedelta(days=1),
        available_at=_OBSERVED + timedelta(days=1),
        source_revision="provider-revision-2",
        evidence_ref="page-evidence-2",
    )

    assert repeated_observation.fingerprint() == record.fingerprint()
    assert replace(record, name="变更名称").fingerprint() != record.fingerprint()


def test_collector_captures_before_parsing_and_replays_without_transport(tmp_path: Path) -> None:
    responses = [
        TushareInstrumentResponse(200, _stock("600000", "L")),
        TushareInstrumentResponse(200, _empty(TUSHARE_STOCK_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_STOCK_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_FUND_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_FUND_BASIC_FIELDS)),
    ]
    calls: list[bytes] = []

    def transport(
        url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> TushareInstrumentResponse:
        assert url == "https://api.tushare.pro"
        assert set(headers) == {"Content-Type"}
        assert timeout_seconds > 0
        calls.append(body)
        return responses.pop(0)

    storage = LocalFileStorage(tmp_path)
    result = TushareInstrumentCollector(
        TushareInstrumentConfig(token="secret-token-for-test"),
        storage,
        transport=transport,
        clock=lambda: _OBSERVED,
        sleeper=lambda _: None,
    ).collect(run_id="00000000-0000-4000-8000-000000000001", manifest_date="2026-09-08")

    assert len(calls) == len(TUSHARE_COLLECTION_PARTITIONS)
    assert json.loads(calls[0].decode())["token"] == "secret-token-for-test"
    assert result.completeness is InstrumentMasterDisposition.COMPLETE
    assert result.records[0].unified_code == "600000.SH"
    assert len(storage.list("tushare-instrument-master", "2026-09-08")) == 11
    assert len(result.checkpoint_capture_ids) == len(TUSHARE_COLLECTION_PARTITIONS)

    replayed = replay_tushare_instrument_master_run(
        storage,
        run_id=result.run_id,
        manifest_date=result.manifest_date,
        manifest_capture_id=result.manifest_capture_id,
    )
    assert replayed.records == result.records
    assert replayed.page_refs == result.page_refs


def test_manifest_digest_proof_can_complete_without_provider_revision(tmp_path: Path) -> None:
    responses = [
        TushareInstrumentResponse(200, _empty(TUSHARE_STOCK_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_STOCK_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_STOCK_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_FUND_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_FUND_BASIC_FIELDS)),
    ]
    result = TushareInstrumentCollector(
        TushareInstrumentConfig(token="token"),
        LocalFileStorage(tmp_path),
        transport=_pop_transport(responses),
        clock=lambda: _OBSERVED,
        sleeper=lambda _: None,
    ).collect("00000000-0000-4000-8000-000000000002", "2026-09-08")

    assert result.terminal.value == "COMPLETE"
    assert result.completeness is InstrumentMasterDisposition.COMPLETE
    assert result.reason_code == "COMPLETE"


def test_full_page_followed_by_short_page_proves_partition_termination(tmp_path: Path) -> None:
    full_page = _rows(
        TUSHARE_STOCK_BASIC_FIELDS,
        [
            {
                "ts_code": "600000.SH",
                "symbol": "600000",
                "name": "示例证券甲",
                "market": "主板",
                "exchange": "SSE",
                "list_status": "L",
                "list_date": "20200101",
            },
            {
                "ts_code": "600001.SH",
                "symbol": "600001",
                "name": "示例证券乙",
                "market": "主板",
                "exchange": "SSE",
                "list_status": "L",
                "list_date": "20200101",
            },
        ],
    )
    responses = [
        TushareInstrumentResponse(200, full_page),
        TushareInstrumentResponse(200, _empty(TUSHARE_STOCK_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_STOCK_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_STOCK_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_FUND_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_FUND_BASIC_FIELDS)),
    ]
    calls = 0

    def transport(
        url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> TushareInstrumentResponse:
        del url, headers, body, timeout_seconds
        nonlocal calls
        calls += 1
        return responses.pop(0)

    result = TushareInstrumentCollector(
        TushareInstrumentConfig(
            token="token",
            page_size=2,
            max_pages=2,
            source_revision=None,
        ),
        LocalFileStorage(tmp_path),
        transport=transport,
        clock=lambda: _OBSERVED,
        sleeper=lambda _: None,
    ).collect("00000000-0000-4000-8000-000000000005", "2026-09-08")

    assert calls == 6
    assert result.terminal.value == "COMPLETE"
    assert result.completeness is InstrumentMasterDisposition.COMPLETE
    assert result.page_refs[0].row_count == 2
    assert result.page_refs[1].offset == 2
    assert result.page_refs[1].row_count == 0
    replayed = replay_tushare_instrument_master_run(
        LocalFileStorage(tmp_path),
        run_id=result.run_id,
        manifest_date=result.manifest_date,
        manifest_capture_id=result.manifest_capture_id,
    )
    assert replayed.page_refs == result.page_refs


def test_page_bound_is_indeterminate_only_when_no_terminal_short_page_arrives(
    tmp_path: Path,
) -> None:
    responses = [
        TushareInstrumentResponse(200, _stock("600000", "L")),
        TushareInstrumentResponse(200, _stock("600001", "P")),
        TushareInstrumentResponse(200, _stock("600002", "D")),
        TushareInstrumentResponse(200, _fund("510000", "L")),
        TushareInstrumentResponse(200, _fund("510001", "D")),
    ]
    result = TushareInstrumentCollector(
        TushareInstrumentConfig(
            token="token",
            page_size=1,
            max_pages=1,
            source_revision=None,
        ),
        LocalFileStorage(tmp_path),
        transport=_pop_transport(responses),
        clock=lambda: _OBSERVED,
        sleeper=lambda _: None,
    ).collect("00000000-0000-4000-8000-000000000006", "2026-09-08")

    assert result.terminal.value == "INDETERMINATE"
    assert result.completeness is InstrumentMasterDisposition.INDETERMINATE
    assert result.reason_code == "PROVIDER_PAGE_CAP_REACHED"


def test_transient_response_is_replayable_as_a_rejected_attempt(tmp_path: Path) -> None:
    """A retried HTTP response remains evidence but is not an accepted page."""

    responses = [
        TushareInstrumentResponse(503, _empty(TUSHARE_STOCK_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_STOCK_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_STOCK_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_STOCK_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_FUND_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_FUND_BASIC_FIELDS)),
    ]
    storage = LocalFileStorage(tmp_path)
    result = TushareInstrumentCollector(
        TushareInstrumentConfig(token="token"),
        storage,
        transport=_pop_transport(responses),
        clock=lambda: _OBSERVED,
        sleeper=lambda _: None,
    ).collect("00000000-0000-4000-8000-000000000003", "2026-09-08")

    assert result.completeness is InstrumentMasterDisposition.COMPLETE
    assert [attempt.state for attempt in result.attempt_refs[:2]] == [
        "REJECTED_RESPONSE",
        "ACCEPTED_RESPONSE",
    ]
    assert result.attempt_refs[0].offset == 0
    assert result.attempt_refs[0].capture_id != result.attempt_refs[1].capture_id
    replayed = replay_tushare_instrument_master_run(
        storage,
        run_id=result.run_id,
        manifest_date=result.manifest_date,
        manifest_capture_id=result.manifest_capture_id,
    )
    assert replayed.attempt_refs == result.attempt_refs


def test_collection_resumes_from_immutable_raw_checkpoint(tmp_path: Path) -> None:
    run_id = "00000000-0000-4000-8000-000000000004"
    storage = LocalFileStorage(tmp_path)
    first_calls = 0

    def interrupted_transport(
        url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> TushareInstrumentResponse:
        del url, headers, body, timeout_seconds
        nonlocal first_calls
        first_calls += 1
        if first_calls == 1:
            return TushareInstrumentResponse(200, _empty(TUSHARE_STOCK_BASIC_FIELDS))
        raise InstrumentMasterTransportError("controlled interruption")

    first = TushareInstrumentCollector(
        TushareInstrumentConfig(token="token", max_attempts=1),
        storage,
        transport=interrupted_transport,
        clock=lambda: _OBSERVED,
        sleeper=lambda _: None,
    ).collect(run_id, "2026-09-08")
    assert first.terminal.value == "FAILED"
    assert len(first.checkpoint_capture_ids) == 1

    remaining = [
        _empty(TUSHARE_STOCK_BASIC_FIELDS),
        _empty(TUSHARE_STOCK_BASIC_FIELDS),
        _empty(TUSHARE_FUND_BASIC_FIELDS),
        _empty(TUSHARE_FUND_BASIC_FIELDS),
    ]
    calls = 0

    def resumed_transport(
        url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> TushareInstrumentResponse:
        del url, headers, body, timeout_seconds
        nonlocal calls
        calls += 1
        return TushareInstrumentResponse(200, remaining.pop(0))

    resumed = TushareInstrumentCollector(
        TushareInstrumentConfig(token="token", max_attempts=1),
        storage,
        transport=resumed_transport,
        clock=lambda: _OBSERVED,
        sleeper=lambda _: None,
    ).collect(run_id, "2026-09-08")
    assert resumed.terminal.value == "COMPLETE"
    assert calls == 4
    assert resumed.manifest_capture_id != first.manifest_capture_id
    replayed = replay_tushare_instrument_master_run(
        storage,
        run_id=run_id,
        manifest_date="2026-09-08",
        manifest_capture_id=resumed.manifest_capture_id,
    )
    assert replayed.records == resumed.records


def test_parser_rejects_field_drift_and_bad_identity() -> None:
    body = json.loads(_stock("600000", "L"))
    body["data"]["fields"][-1] = "unexpected"
    with pytest.raises(ValueError, match="fields drifted"):
        parse_tushare_instrument_page(
            json.dumps(body).encode(),
            api_name="stock_basic",
            status_partition="L",
            market_partition=None,
            observed_at=_OBSERVED,
            available_at=_OBSERVED,
            evidence_ref="page-evidence",
        )

    with pytest.raises(ValueError, match="identity"):
        parse_tushare_instrument_page(
            _envelope(
                TUSHARE_STOCK_BASIC_FIELDS,
                {
                    "ts_code": "000001.SH",
                    "name": "bad exchange fixture",
                    "list_status": "L",
                },
            ),
            api_name="stock_basic",
            status_partition="L",
            market_partition=None,
            observed_at=_OBSERVED,
            available_at=_OBSERVED,
            evidence_ref="page-evidence",
        )
