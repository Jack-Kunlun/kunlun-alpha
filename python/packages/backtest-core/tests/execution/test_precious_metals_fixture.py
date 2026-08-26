from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from ashare_contracts import BenchmarkSeriesPoint, FundNav
from backtest_core.engine import BacktestOrderIntent, IntentSide
from backtest_core.execution import (
    EXECUTION_SCHEMA_VERSION,
    ExecutableLiquidityLevel,
    ExecutionProvenance,
    ExecutionValidationError,
    FeeComponent,
    FeeSchedule,
    FeeScope,
    InstrumentExecutionRules,
    InstrumentKind,
    LimitLockState,
    MarketExecutionSnapshot,
    OddLotSellPolicy,
    OrderType,
    PriceBand,
    PriceSource,
    RoundingMode,
    SameDaySellPolicy,
    SessionKind,
    SimulationOrder,
    SlippageModel,
    TradeStatus,
    match_orders,
)
from feature_core import (
    DatasetExporter,
    DatasetManifest,
    FeatureHistoryRepository,
    InMemoryFeatureHistoryBackend,
)
from feature_core.precious_metals import (
    BenchmarkSeriesPointRecord,
    EvidenceLineage,
    FundClassificationRecord,
    FundNavRecord,
    PreciousMetalsFeatureInput,
    RawBarRecord,
)
from market_core.funds import fund_from_dict
from market_core.models import bar_from_dict

SHANGHAI = ZoneInfo("Asia/Shanghai")
MATCH_TIME = datetime(2026, 8, 24, 15, 0, tzinfo=SHANGHAI)
ROOT = Path(__file__).parents[1] / "fixtures/precious-metals"


def _fixture(name: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads((ROOT / name).read_text(encoding="utf-8")))


def _provenance(record_id: str, digest: str) -> ExecutionProvenance:
    return ExecutionProvenance(
        source_id="fixture.synthetic.execution",
        source_version="v1",
        record_id=record_id,
        digest=digest,
        available_time=MATCH_TIME - timedelta(minutes=2),
    )


def _snapshot(*, ask_levels: tuple[ExecutableLiquidityLevel, ...] = ()) -> MarketExecutionSnapshot:
    return MarketExecutionSnapshot(
        schema_version=EXECUTION_SCHEMA_VERSION,
        snapshot_id="fixture-empty-quote",
        instrument_code="518880.SH",
        match_time=MATCH_TIME,
        observed_time=MATCH_TIME - timedelta(seconds=30),
        available_time=MATCH_TIME - timedelta(seconds=20),
        processing_time=MATCH_TIME - timedelta(seconds=10),
        trading_date=MATCH_TIME.date().isoformat(),
        is_trading_day=True,
        calendar_id="fixture.calendar",
        calendar_version="v1",
        calendar_digest="a" * 64,
        session=SessionKind.CONTINUOUS,
        trade_status=TradeStatus.OPEN,
        price_band=PriceBand(
            daily_lower=Decimal("1"),
            daily_upper=Decimal("20"),
            dynamic_valid_lower=Decimal("1"),
            dynamic_valid_upper=Decimal("20"),
        ),
        bid_levels=(),
        ask_levels=ask_levels,
        lock_state=LimitLockState.NONE,
        source=_provenance("snapshot", "b" * 64),
    )


def _rules(instrument_code: str = "518880.SH") -> InstrumentExecutionRules:
    return InstrumentExecutionRules(
        rule_set_id="fixture.rules",
        rule_set_version="v1",
        instrument_code=instrument_code,
        instrument_kind=InstrumentKind.EXCHANGE_LISTED_FUND,
        effective_from=MATCH_TIME - timedelta(days=1),
        effective_to=MATCH_TIME + timedelta(days=1),
        available_time=MATCH_TIME - timedelta(minutes=5),
        lot_size=100,
        tick_size=Decimal("0.01"),
        buy_min_quantity=100,
        buy_increment=100,
        max_order_quantity=1000,
        odd_lot_sell_policy=OddLotSellPolicy.DISALLOW,
        same_day_sell_policy=SameDaySellPolicy.T_PLUS_1,
        supported_order_types=(OrderType.LIMIT_IOC,),
        source=_provenance("rules", "c" * 64),
    )


def _order(instrument_code: str = "518880.SH") -> SimulationOrder:
    intent = BacktestOrderIntent(
        intent_id="intent:fixture",
        source_signal_id="signal:fixture",
        entity_id=instrument_code,
        logical_time=MATCH_TIME - timedelta(minutes=1),
        side=IntentSide.BUY,
        policy_id="fixture.policy",
        policy_version="v1",
        policy_fingerprint="d" * 64,
        manifest_digest="e" * 64,
    )
    return SimulationOrder(
        order_id="order:fixture",
        source_intent=intent,
        instrument_code=instrument_code,
        side=IntentSide.BUY,
        manifest_digest="e" * 64,
        submitted_at=MATCH_TIME - timedelta(seconds=30),
        submission_sequence=1,
        quantity=100,
        order_type=OrderType.LIMIT_IOC,
        limit_price=Decimal("10.20"),
        protection_price=None,
    )


def _fees() -> FeeSchedule:
    component = FeeComponent(
        code="commission",
        applies_sides=(IntentSide.BUY, IntentSide.SELL),
        instrument_kinds=(InstrumentKind.EXCHANGE_LISTED_FUND,),
        rate=Decimal("0.001"),
        minimum=Decimal("0"),
        maximum=None,
        rounding_quantum=Decimal("0.01"),
        rounding_mode=RoundingMode.HALF_UP,
        scope=FeeScope.PER_FILL,
        effective_from=MATCH_TIME - timedelta(days=1),
        effective_to=MATCH_TIME + timedelta(days=1),
        available_time=MATCH_TIME - timedelta(minutes=5),
        source=_provenance("fee", "f" * 64),
    )
    return FeeSchedule(
        schedule_id="fixture.fees",
        schedule_version="v1",
        effective_from=MATCH_TIME - timedelta(days=1),
        effective_to=MATCH_TIME + timedelta(days=1),
        available_time=MATCH_TIME - timedelta(minutes=5),
        components=(component,),
        source=_provenance("fee-schedule", "1" * 64),
    )


def _slippage() -> SlippageModel:
    return SlippageModel(
        model_id="fixture.slippage",
        model_version="v1",
        effective_from=MATCH_TIME - timedelta(days=1),
        effective_to=MATCH_TIME + timedelta(days=1),
        available_time=MATCH_TIME - timedelta(minutes=5),
        max_level_participation=None,
        adverse_level_offset=0,
        skip_level_ids=(),
        source=_provenance("slippage", "2" * 64),
    )


def test_fixture_evidence_and_execution_snapshot_are_separate() -> None:
    for name, commodity in (
        ("gold-etf-backtest-v1.json", "GOLD"),
        ("silver-lof-backtest-v1.json", "SILVER"),
        ("other-commodity-v1.json", "OTHER"),
    ):
        payload = _fixture(name)
        reference = cast(dict[str, object], payload["referenceEvidence"])
        snapshot = cast(dict[str, object], payload["executionSnapshot"])
        assert reference["underlyingCommodity"] == commodity
        assert "executionSnapshot" in payload
        levels = cast(list[dict[str, object]], snapshot["askLevels"])
        assert all(level["priceSource"] == "EXECUTABLE_QUOTE" for level in levels)
        assert reference["rawBars"]
        assert reference["benchmarkSeries"]


def test_fixture_index_and_dataset_partition_digests_match_actual_files() -> None:
    index = _fixture("fixture-index-v1.json")
    entries = cast(list[object], index["fixtures"])
    manifest = DatasetManifest.from_json(
        (ROOT / "dataset/dataset-manifest.json").read_text(encoding="utf-8")
    )
    parquet_record_counts = {
        (Path("dataset") / artifact.relative_path).as_posix(): artifact.row_count
        for artifact in manifest.partitions
    }
    expected_files = {
        "gold-etf-backtest-v1.json",
        "silver-lof-backtest-v1.json",
        "other-commodity-v1.json",
        "dataset/dataset-manifest.json",
        "dataset/rebuild-command.json",
        "dataset/partitions/train/train.parquet",
        "dataset/partitions/evaluation/evaluation.parquet",
    }
    assert {str(cast(dict[str, object], item)["file"]) for item in entries} == expected_files
    assert "fixture-index-v1.json" not in expected_files
    for item in entries:
        entry = cast(dict[str, object], item)
        path = ROOT / str(entry["file"])
        assert "sha256:" + sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        assert entry["sizeBytes"] == path.stat().st_size
        record_count = parquet_record_counts.get(str(entry["file"]), 1)
        assert entry["recordCount"] == record_count

    for artifact in manifest.partitions:
        path = ROOT / "dataset" / artifact.relative_path
        assert "sha256:" + sha256(path.read_bytes()).hexdigest() == artifact.file_checksum


def test_committed_fixture_uses_the_public_dataset_verifier() -> None:
    exporter = DatasetExporter(FeatureHistoryRepository(InMemoryFeatureHistoryBackend()))
    manifest = exporter.verify(ROOT / "dataset")
    assert manifest.dataset_name == "precious-metals-fixture"


def test_fixture_reference_evidence_uses_public_feature_input_constructors() -> None:
    for name in (
        "gold-etf-backtest-v1.json",
        "silver-lof-backtest-v1.json",
        "other-commodity-v1.json",
    ):
        payload = _fixture(name)
        reference = cast(dict[str, object], payload["referenceEvidence"])
        fund = fund_from_dict(cast(dict[str, object], reference["fund"]))

        def _nav_record(item: object) -> FundNavRecord:
            raw = cast(dict[str, object], item)
            public_payload = {key: value for key, value in raw.items() if key != "payloadDigest"}
            parsed = FundNav.model_validate(public_payload)
            return FundNavRecord(
                nav=parsed,
                lineage=EvidenceLineage(
                    source="fixture.synthetic.nav",
                    source_revision=str(raw["rawObjectId"]),
                    raw_object_id=str(raw["rawObjectId"]),
                    payload_digest=str(raw["payloadDigest"]),
                    event_time=parsed.event_time,
                    available_time=parsed.available_time,
                    processing_time=parsed.processing_time,
                    ingest_time=parsed.ingest_time,
                ),
            )

        navs = tuple(_nav_record(item) for item in cast(list[object], reference["navs"]))
        bars = tuple(
            RawBarRecord(
                bar=bar_from_dict(cast(dict[str, object], cast(dict[str, object], item)["bar"])),
                lineage=EvidenceLineage(
                    source="fixture.synthetic.bar",
                    source_revision=str(cast(dict[str, object], item)["sourceRevision"]),
                    raw_object_id=str(cast(dict[str, object], item)["rawObjectId"]),
                    payload_digest=str(cast(dict[str, object], item)["payloadDigest"]),
                    event_time=datetime.fromisoformat(
                        str(cast(dict[str, object], item)["eventTime"])
                    ),
                    available_time=datetime.fromisoformat(
                        str(cast(dict[str, object], item)["availableTime"])
                    ),
                    processing_time=datetime.fromisoformat(
                        str(cast(dict[str, object], item)["processingTime"])
                    ),
                    ingest_time=datetime.fromisoformat(
                        str(cast(dict[str, object], item)["ingestTime"])
                    ),
                ),
            )
            for item in cast(list[object], reference["bars"])
        )
        benchmarks = tuple(
            BenchmarkSeriesPointRecord(
                point=BenchmarkSeriesPoint.model_validate(cast(dict[str, object], item)),
                lineage=EvidenceLineage(
                    source=str(cast(dict[str, object], item)["source"]),
                    source_revision=str(cast(dict[str, object], item)["sourceRevision"]),
                    raw_object_id=str(cast(dict[str, object], item)["rawObjectId"]),
                    payload_digest=str(cast(dict[str, object], item)["payloadDigest"]),
                    event_time=BenchmarkSeriesPoint.model_validate(
                        cast(dict[str, object], item)
                    ).event_time,
                    available_time=BenchmarkSeriesPoint.model_validate(
                        cast(dict[str, object], item)
                    ).available_time,
                    processing_time=BenchmarkSeriesPoint.model_validate(
                        cast(dict[str, object], item)
                    ).processing_time,
                    ingest_time=BenchmarkSeriesPoint.model_validate(
                        cast(dict[str, object], item)
                    ).ingest_time,
                ),
            )
            for item in cast(list[object], reference["benchmarks"])
        )
        classification = FundClassificationRecord(
            fund=fund,
            lineage=EvidenceLineage(
                source=fund.source,
                source_revision=fund.raw_object_id,
                raw_object_id=fund.raw_object_id,
                payload_digest=str(reference["classificationPayloadDigest"]),
                event_time=fund.event_time or fund.available_time,
                available_time=fund.available_time,
                processing_time=fund.processing_time,
                ingest_time=fund.ingest_time,
            ),
        )
        context = PreciousMetalsFeatureInput(
            fund=fund,
            decision_time=MATCH_TIME,
            navs=navs,
            bars=bars,
            benchmarks=benchmarks,
            classification_revisions=(classification,),
        )
        assert context.fund.unified_code == payload["unifiedCode"]


def test_fixture_execution_snapshots_use_real_market_execution_constructors() -> None:
    for name in (
        "gold-etf-backtest-v1.json",
        "silver-lof-backtest-v1.json",
        "other-commodity-v1.json",
    ):
        snapshot = _fixture(name)["executionSnapshot"]
        data = cast(dict[str, object], snapshot)
        provenance = ExecutionProvenance(
            source_id=str(cast(dict[str, object], data["source"])["sourceId"]),
            source_version=str(cast(dict[str, object], data["source"])["sourceVersion"]),
            record_id=str(cast(dict[str, object], data["source"])["recordId"]),
            digest=str(cast(dict[str, object], data["source"])["digest"]),
            available_time=datetime.fromisoformat(
                str(cast(dict[str, object], data["source"])["availableTime"])
            ),
        )
        levels = tuple(
            ExecutableLiquidityLevel(
                level_id=str(cast(dict[str, object], item)["levelId"]),
                side=IntentSide(str(cast(dict[str, object], item)["side"])),
                price=Decimal(str(cast(dict[str, object], item)["price"])),
                quantity=int(str(cast(dict[str, object], item)["quantity"])),
                available_time=datetime.fromisoformat(
                    str(cast(dict[str, object], item)["availableTime"])
                ),
                price_source=PriceSource(str(cast(dict[str, object], item)["priceSource"])),
                source=provenance,
            )
            for item in cast(list[object], data["askLevels"])
        )
        price_band = cast(dict[str, object], data["priceBand"])
        real_snapshot = MarketExecutionSnapshot(
            schema_version=str(data["schemaVersion"]),
            snapshot_id=str(data["snapshotId"]),
            instrument_code=str(data["instrumentCode"]),
            match_time=datetime.fromisoformat(str(data["matchTime"])),
            observed_time=datetime.fromisoformat(str(data["observedTime"])),
            available_time=datetime.fromisoformat(str(data["availableTime"])),
            processing_time=datetime.fromisoformat(str(data["processingTime"])),
            trading_date=str(data["tradingDate"]),
            is_trading_day=bool(data["isTradingDay"]),
            calendar_id=str(data["calendarId"]),
            calendar_version=str(data["calendarVersion"]),
            calendar_digest=str(data["calendarDigest"]),
            session=SessionKind(str(data["session"])),
            trade_status=TradeStatus(str(data["tradeStatus"])),
            price_band=PriceBand(
                daily_lower=Decimal(str(price_band["dailyLower"])),
                daily_upper=Decimal(str(price_band["dailyUpper"])),
                dynamic_valid_lower=Decimal(str(price_band["dynamicValidLower"])),
                dynamic_valid_upper=Decimal(str(price_band["dynamicValidUpper"])),
            ),
            bid_levels=(),
            ask_levels=levels,
            lock_state=LimitLockState(str(data["lockState"])),
            source=provenance,
        )
        assert real_snapshot.instrument_code == str(_fixture(name)["unifiedCode"])
        if not levels:
            execution = match_orders(
                (_order(real_snapshot.instrument_code),),
                real_snapshot,
                _rules(real_snapshot.instrument_code),
                None,
                _fees(),
                _slippage(),
            )
            assert execution.results[0].status.value == "UNFILLED"
            assert execution.results[0].reject_reason is not None
            assert execution.results[0].reject_reason.value == ("MISSING_EXECUTABLE_LIQUIDITY")


def test_missing_executable_quote_is_unfilled() -> None:
    result = match_orders(
        (_order(),),
        _snapshot(),
        _rules(),
        None,
        _fees(),
        _slippage(),
    )
    match = result.results[0]
    assert match.status.value == "UNFILLED"
    assert match.reject_reason is not None
    assert match.reject_reason.value == "MISSING_EXECUTABLE_LIQUIDITY"


@pytest.mark.parametrize(
    "price_source",
    [PriceSource.NAV, PriceSource.INAV, PriceSource.BAR_RAW, PriceSource.BAR_ADJUSTED],
)
def test_reference_evidence_cannot_be_injected_as_execution_liquidity(
    price_source: PriceSource,
) -> None:
    with pytest.raises(ExecutionValidationError, match="EXECUTABLE_QUOTE"):
        ExecutableLiquidityLevel(
            level_id="invalid-reference-level",
            side=IntentSide.SELL,
            price=Decimal("10.20"),
            quantity=100,
            available_time=MATCH_TIME - timedelta(minutes=1),
            price_source=price_source,
            source=_provenance("invalid-level", "3" * 64),
        )
