from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import feature_core
import pytest
from ashare_contracts import BenchmarkSeriesPoint, FundNav
from feature_core import DatasetManifest, RegisteredFeature
from feature_core.batch import (
    BatchFeatureEngine,
    BatchInputBatch,
    BatchInputLineage,
    BatchInputReference,
    BatchInputRow,
    BatchPartition,
    CalculatorIdentity,
    InMemoryBatchCheckpointStore,
    InMemoryFeaturePartitionStore,
    InputOrigin,
    PartitionInputManifest,
    PartitionReadRequest,
    SourceKind,
)
from feature_core.online import (
    HmacOnlineStateIntegrity,
    InMemoryOnlineStateStore,
    OnlineCalculationResult,
    OnlineCalculatorArtifact,
    OnlineEventSource,
    OnlineFeatureEngine,
    OnlineFeatureEvent,
    OnlineProcessDisposition,
    OnlineWindowPolicy,
    StaticOnlineCalculatorTrust,
)
from feature_core.precious_metals import (
    BatchPreciousMetalsAdapter,
    BenchmarkPolicy,
    BenchmarkSeriesPointRecord,
    EvidenceLineage,
    FeatureReason,
    FeatureStatus,
    FundNavRecord,
    OnlinePreciousMetalsAdapter,
    PreciousMetalsFeatureInput,
    PreciousMetalsPolicy,
    RawBarRecord,
    calculate_feature,
    context_from_batch_rows,
    precious_metals_feature_registry,
    thaw_json_value,
)
from feature_core.precious_metals.specs import precious_metals_feature_specs
from market_core.funds import PreciousMetalFund
from market_core.models import Bar

SHANGHAI = ZoneInfo("Asia/Shanghai")
DECISION = datetime(2026, 8, 24, 15, 0, tzinfo=SHANGHAI)
GOLD_ID = "benchmark:v1:sge:au9999-close-cny"


def _digest(value: str) -> str:
    return f"sha256:{sha256(value.encode()).hexdigest()}"


def _lineage(
    identity: str,
    event_time: datetime,
    *,
    available_time: datetime | None = None,
    processing_time: datetime | None = None,
    source_revision: str | None = None,
) -> EvidenceLineage:
    available = available_time or event_time + timedelta(minutes=1)
    return EvidenceLineage(
        source="fixture.synthetic",
        source_revision=source_revision or f"revision:{identity}",
        raw_object_id=f"raw:{identity}",
        payload_digest=_digest(identity),
        event_time=event_time,
        available_time=available,
        processing_time=processing_time or available + timedelta(minutes=1),
    )


def _fund() -> PreciousMetalFund:
    return PreciousMetalFund(
        unified_code="518880.SH",
        exchange="SH",
        asset_type="ETF",
        fund_asset_class="PRECIOUS_METALS",
        underlying_commodity="GOLD",
        trading_currency="CNY",
        nav_currency="CNY",
        benchmark_or_tracking_index="display-only",
        benchmark_series_id=GOLD_ID,
        management_fee_rate=Decimal("0.005"),
        valid_from="2026-01-01",
        valid_to=None,
        source="fixture.synthetic.fund",
        publish_time=DECISION - timedelta(days=10),
        ingest_time=DECISION - timedelta(days=10),
        available_time=DECISION - timedelta(days=10),
        processing_time=DECISION - timedelta(days=10),
        raw_object_id="fund-v1",
        confidence=Decimal("0.95"),
        review_status="REVIEWED",
        event_time=DECISION - timedelta(days=10),
    )


def _nav(index: int = 0, *, available_time: datetime | None = None) -> FundNavRecord:
    event_time = DECISION - timedelta(days=21 - index, minutes=10)
    available = available_time or event_time + timedelta(minutes=2)
    raw_object_id = f"nav-{index}"
    payload = FundNav(
        unifiedCode="518880.SH",
        date=event_time.date(),
        nav=Decimal("10.00"),
        inav=Decimal("10.00"),
        eventTime=event_time,
        publishTime=event_time,
        ingestTime=event_time + timedelta(minutes=1),
        availableTime=available,
        processingTime=available,
        rawObjectId=raw_object_id,
        source="fixture.synthetic.nav",
    )
    return FundNavRecord(
        nav=payload,
        lineage=EvidenceLineage(
            source=payload.source,
            source_revision=f"revision:{raw_object_id}",
            raw_object_id=payload.raw_object_id,
            payload_digest=_digest(raw_object_id),
            event_time=payload.event_time,
            available_time=payload.available_time,
            processing_time=payload.processing_time,
            ingest_time=payload.ingest_time,
        ),
    )


def _bar(index: int, *, close: str | None = None) -> RawBarRecord:
    event_time = datetime(2026, 8, 3 + index, 15, 0, tzinfo=SHANGHAI)
    payload = Bar(
        unified_code="518880.SH",
        exchange="SH",
        date=event_time.date().isoformat(),
        interval="DAILY",
        session="CONTINUOUS",
        timestamp=event_time.isoformat(),
        open=Decimal(close or str(200 + index)),
        high=Decimal(close or str(200 + index)),
        low=Decimal(close or str(200 + index)),
        close=Decimal(close or str(200 + index)),
        volume=1000,
        amount=Decimal("100"),
        price_type="RAW",
        suspended=False,
    )
    return RawBarRecord(bar=payload, lineage=_lineage(f"bar-{index}", event_time))


def _benchmark(
    index: int,
    *,
    value: str | None = None,
    revision: str | None = None,
    available_time: datetime | None = None,
    processing_time: datetime | None = None,
) -> BenchmarkSeriesPointRecord:
    event_time = datetime(2026, 8, 3 + index, 15, 0, tzinfo=SHANGHAI)
    revision_id = revision or f"benchmark-revision-{index}"
    raw_id = f"benchmark-raw-{index}-{revision_id}"
    digest = _digest(raw_id)
    payload_available_time = available_time or (event_time + timedelta(minutes=2))
    payload_processing_time = processing_time or (event_time + timedelta(minutes=3))
    payload = BenchmarkSeriesPoint.model_validate(
        {
            "schemaVersion": "benchmark-series-point-v1",
            "benchmarkId": GOLD_ID,
            "currency": "CNY",
            "priceBasis": "CLOSE",
            "referenceValue": value or str(100 + index),
            "eventTime": event_time.isoformat(),
            "ingestTime": (event_time + timedelta(minutes=1)).isoformat(),
            "availableTime": payload_available_time.isoformat(),
            "processingTime": payload_processing_time.isoformat(),
            "source": "fixture.synthetic.benchmark",
            "sourceRevision": revision_id,
            "rawObjectId": raw_id,
            "payloadDigest": digest,
            "referenceOnly": True,
        }
    )
    return BenchmarkSeriesPointRecord(
        point=payload,
        lineage=EvidenceLineage(
            source=payload.source,
            source_revision=payload.source_revision,
            raw_object_id=payload.raw_object_id,
            payload_digest=payload.payload_digest,
            event_time=payload.event_time,
            available_time=payload.available_time,
            processing_time=payload.processing_time,
            ingest_time=payload.ingest_time,
        ),
    )


def _policy() -> PreciousMetalsPolicy:
    return PreciousMetalsPolicy(
        benchmarks=(
            BenchmarkPolicy(
                benchmark_series_id=GOLD_ID,
                allowed_price_bases=("CLOSE",),
                currency="CNY",
            ),
        ),
    )


def _context(
    *,
    bars: tuple[RawBarRecord, ...] | None = None,
    benchmarks: tuple[BenchmarkSeriesPointRecord, ...] | None = None,
) -> PreciousMetalsFeatureInput:
    return PreciousMetalsFeatureInput(
        fund=_fund(),
        decision_time=DECISION,
        navs=(_nav(21),),
        bars=bars if bars is not None else tuple(_bar(index) for index in range(21)),
        benchmarks=(
            benchmarks
            if benchmarks is not None
            else tuple(_benchmark(index) for index in range(21))
        ),
    )


def test_default_public_registry_uses_legal_namespace_from_both_exports() -> None:
    root = feature_core.precious_metals_feature_registry()
    package = precious_metals_feature_registry()
    assert root.namespace_id == "precious_metals.funds"
    assert package.namespace_id == root.namespace_id
    assert len(root) == 5
    names = tuple(spec.name for spec in precious_metals_feature_specs())
    assert tuple(root.get(name).semantic_fingerprint for name in names) == tuple(
        package.get(name).semantic_fingerprint for name in names
    )


def test_each_spec_declares_only_its_minimal_raw_source_contracts() -> None:
    specs = {spec.name: spec for spec in precious_metals_feature_specs()}
    assert {
        (item.name, item.version)
        for item in specs["precious_metals_fund.premium_discount_bps"].source_contracts
    } == {
        ("domain.fund_nav", "v1"),
        ("domain.precious_metal_fund", "v1"),
        ("market.daily_bar", "v1"),
    }
    for name in (
        "precious_metals_fund.tracking_difference_bps_20_sessions",
        "precious_metals_fund.tracking_error_bps_20_sessions",
        "precious_metals_fund.benchmark_beta_20_sessions",
    ):
        assert {(item.name, item.version) for item in specs[name].source_contracts} == {
            ("domain.precious_metal_fund", "v1"),
            ("market.benchmark_series_point", "v1"),
            ("market.daily_bar", "v1"),
        }
    assert {
        (item.name, item.version)
        for item in specs[
            "precious_metals_fund.liquidity_median_turnover_cny_20_sessions"
        ].source_contracts
    } == {
        ("domain.precious_metal_fund", "v1"),
        ("market.daily_bar", "v1"),
    }
    assert all(not spec.dependencies for spec in specs.values())


@pytest.mark.parametrize(
    "feature_name",
    [
        "precious_metals_fund.tracking_difference_bps_20_sessions",
        "precious_metals_fund.tracking_error_bps_20_sessions",
        "precious_metals_fund.benchmark_beta_20_sessions",
        "precious_metals_fund.liquidity_median_turnover_cny_20_sessions",
    ],
)
def test_latest_visible_bar_conflict_fails_closed_for_all_dependent_features(
    feature_name: str,
) -> None:
    left = _bar(10)
    right = replace(
        _bar(10, close="999"),
        lineage=_lineage(
            "bar-conflict",
            left.lineage.event_time,
            available_time=left.lineage.available_time,
            processing_time=left.lineage.processing_time,
        ),
    )
    result = calculate_feature(
        feature_name,
        _context(bars=tuple(_bar(index) for index in range(21)) + (right,)),
        _policy(),
    )
    assert result.value is None
    assert result.reason is FeatureReason.UNAVAILABLE_CONFLICTING_BAR_REVISION
    assert {item.raw_object_id for item in result.lineage} >= {
        "raw:bar-10",
        "raw:bar-conflict",
    }


@pytest.mark.parametrize(
    "feature_name",
    [
        "precious_metals_fund.tracking_difference_bps_20_sessions",
        "precious_metals_fund.tracking_error_bps_20_sessions",
        "precious_metals_fund.benchmark_beta_20_sessions",
    ],
)
def test_latest_visible_benchmark_conflict_fails_closed(feature_name: str) -> None:
    left = _benchmark(10)
    right = _benchmark(10, value="999", revision="benchmark-conflict")
    right = replace(
        right,
        lineage=replace(
            right.lineage,
            available_time=left.lineage.available_time,
            processing_time=left.lineage.processing_time,
        ),
    )
    result = calculate_feature(
        feature_name,
        _context(benchmarks=tuple(_benchmark(index) for index in range(21)) + (right,)),
        _policy(),
    )
    assert result.value is None
    assert result.reason is FeatureReason.UNAVAILABLE_CONFLICTING_BENCHMARK_REVISION
    assert {item.raw_object_id for item in result.lineage} >= {
        "benchmark-raw-10-benchmark-revision-10",
        "benchmark-raw-10-benchmark-conflict",
    }


def test_future_bar_and_benchmark_revisions_have_typed_unavailable_reasons() -> None:
    future_bar = replace(
        _bar(1),
        lineage=replace(
            _bar(1).lineage,
            available_time=DECISION + timedelta(minutes=1),
            processing_time=DECISION + timedelta(minutes=2),
        ),
    )
    bar_result = calculate_feature(
        "precious_metals_fund.premium_discount_bps",
        _context(bars=(future_bar,)),
        _policy(),
    )
    assert bar_result.value is None
    assert bar_result.reason is FeatureReason.UNAVAILABLE_FUTURE_BAR_REVISION

    future_benchmark = _benchmark(
        1,
        available_time=DECISION + timedelta(minutes=1),
        processing_time=DECISION + timedelta(minutes=2),
    )
    benchmark_result = calculate_feature(
        "precious_metals_fund.tracking_difference_bps_20_sessions",
        _context(benchmarks=(future_benchmark,)),
        _policy(),
    )
    assert benchmark_result.value is None
    assert benchmark_result.reason is FeatureReason.UNAVAILABLE_FUTURE_BENCHMARK_REVISION


def test_future_processing_time_cannot_be_hidden_by_past_availability() -> None:
    future_bar = replace(
        _bar(1),
        lineage=replace(_bar(1).lineage, processing_time=DECISION + timedelta(minutes=1)),
    )
    bar_result = calculate_feature(
        "precious_metals_fund.premium_discount_bps",
        _context(bars=(future_bar,)),
        _policy(),
    )
    assert bar_result.value is None
    assert bar_result.reason is FeatureReason.UNAVAILABLE_FUTURE_BAR_REVISION

    future_benchmark = _benchmark(
        1,
        processing_time=DECISION + timedelta(minutes=1),
    )
    benchmark_result = calculate_feature(
        "precious_metals_fund.tracking_difference_bps_20_sessions",
        _context(benchmarks=(future_benchmark,)),
        _policy(),
    )
    assert benchmark_result.value is None
    assert benchmark_result.reason is FeatureReason.UNAVAILABLE_FUTURE_BENCHMARK_REVISION


def test_adapters_implement_the_public_engine_callable_boundaries() -> None:
    batch = BatchPreciousMetalsAdapter(_policy())
    online = OnlinePreciousMetalsAdapter(_policy())
    assert callable(batch)
    assert callable(online)
    artifact = OnlineCalculatorArtifact(
        identity=CalculatorIdentity(
            algorithm_version="v1",
            implementation_fingerprint=_digest("adapter"),
        ),
        calculator=online,
    )
    assert callable(artifact.calculator)


@pytest.mark.parametrize(
    ("fixture_name", "commodity"),
    (
        ("gold-etf-backtest-v1.json", "GOLD"),
        ("silver-lof-backtest-v1.json", "SILVER"),
    ),
)
def test_online_fixture_payload_keeps_source_ingest_and_thaws_frozen_json(
    fixture_name: str,
    commodity: str,
) -> None:
    fixture_root = Path(__file__).parents[3] / "backtest-core/tests/fixtures/precious-metals"
    fixture = cast(
        dict[str, object],
        json.loads((fixture_root / fixture_name).read_text(encoding="utf-8")),
    )
    reference = cast(dict[str, object], fixture["referenceEvidence"])
    fund = cast(dict[str, object], reference["fund"])
    assert fund["underlyingCommodity"] == commodity
    event_time = datetime.fromisoformat(str(fund["eventTime"]))
    available_time = datetime.fromisoformat(str(fund["availableTime"]))
    source_ingest_time = datetime.fromisoformat(str(fund["ingestTime"]))
    payload = {
        "recordType": "fund",
        "data": fund,
        "eventTime": fund["eventTime"],
        "availableTime": fund["availableTime"],
        "ingestTime": fund["ingestTime"],
        "processingTime": fund["processingTime"],
        "source": fund["source"],
        "rawObjectId": fund["rawObjectId"],
        "payloadDigest": reference["classificationPayloadDigest"],
    }
    online_arrival_time = available_time + timedelta(minutes=5)
    event = OnlineFeatureEvent(
        event_id=f"{commodity.lower()}-fund-event",
        entity_id=str(fund["unifiedCode"]),
        source=OnlineEventSource.DOMAIN,
        contract_name="domain.precious_metal_fund",
        contract_version="v1",
        source_revision="classification-v1",
        event_time=event_time,
        available_time=available_time,
        ingest_time=online_arrival_time,
        payload=payload,
    )

    context = OnlinePreciousMetalsAdapter(_policy()).context((event,), DECISION)
    lineage = context.classification_revisions[0].lineage

    assert lineage.ingest_time == source_ingest_time
    assert event.ingest_time == online_arrival_time
    assert lineage.ingest_time != event.ingest_time
    assert context.fund.recurring_fees == ()


def test_payload_future_revision_cannot_be_hidden_by_past_outer_lineage() -> None:
    rows = list(_engine_payload_rows())
    nav_index = next(
        index for index, row in enumerate(rows) if row.contract_name == "domain.fund_nav"
    )
    original = rows[nav_index]
    payload = dict(original.payload)
    data = dict(cast(Mapping[str, object], payload["data"]))
    data["availableTime"] = (DECISION + timedelta(minutes=1)).isoformat()
    payload["data"] = data
    rows[nav_index] = replace(original, payload=payload)
    with pytest.raises(ValueError, match="available_time|payload"):
        context_from_batch_rows(tuple(rows), DECISION)


def test_dataset_fixture_uses_the_public_dataset_manifest_schema() -> None:
    path = (
        Path(__file__).parents[3]
        / "backtest-core/tests/fixtures/precious-metals/dataset/dataset-manifest.json"
    )
    manifest = DatasetManifest.from_json(path.read_text(encoding="utf-8"))
    assert manifest.schema_version == "1.0.0"
    assert len(manifest.partitions) == 2


def test_thaw_json_value_rejects_unknown_nested_leaf_without_mutation() -> None:
    unknown = object()
    source: dict[str, object] = {"nested": ({"value": unknown},)}

    with pytest.raises(ValueError, match="unsupported leaf type"):
        thaw_json_value(source)

    nested = cast(tuple[dict[str, object], ...], source["nested"])
    assert nested[0]["value"] is unknown


def _engine_payload_rows() -> tuple[BatchInputRow, ...]:
    event_time = DECISION - timedelta(minutes=10)
    available_time = DECISION - timedelta(minutes=5)
    fund = _fund()
    nav = _nav(21).nav
    bar = _bar(21).bar
    records = (
        (
            "fund",
            "domain.precious_metal_fund",
            {
                "unifiedCode": fund.unified_code,
                "exchange": fund.exchange,
                "assetType": fund.asset_type,
                "fundAssetClass": fund.fund_asset_class,
                "underlyingCommodity": fund.underlying_commodity,
                "tradingCurrency": fund.trading_currency,
                "navCurrency": fund.nav_currency,
                "benchmarkOrTrackingIndex": fund.benchmark_or_tracking_index,
                "benchmarkSeriesId": fund.benchmark_series_id,
                "managementFeeRate": "0.005",
                "validFrom": fund.valid_from,
                "validTo": fund.valid_to,
                "source": fund.source,
                "publishTime": event_time.isoformat(),
                "ingestTime": available_time.isoformat(),
                "availableTime": available_time.isoformat(),
                "processingTime": (event_time + timedelta(minutes=7)).isoformat(),
                "rawObjectId": fund.raw_object_id,
                "confidence": "0.95",
                "reviewStatus": fund.review_status,
                "eventTime": event_time.isoformat(),
            },
        ),
        (
            "nav",
            "domain.fund_nav",
            {
                "unifiedCode": nav.unified_code,
                "date": nav.date.isoformat(),
                "nav": "10.00",
                "inav": "10.00",
                "eventTime": event_time.isoformat(),
                "publishTime": event_time.isoformat(),
                "ingestTime": available_time.isoformat(),
                "availableTime": available_time.isoformat(),
                "processingTime": (event_time + timedelta(minutes=7)).isoformat(),
                "rawObjectId": "nav-engine",
                "source": nav.source,
            },
        ),
        (
            "bar",
            "market.daily_bar",
            {
                "unifiedCode": bar.unified_code,
                "exchange": bar.exchange,
                "date": event_time.date().isoformat(),
                "interval": "DAILY",
                "session": "CONTINUOUS",
                "timestamp": event_time.isoformat(),
                "open": "200",
                "high": "200",
                "low": "200",
                "close": "200",
                "volume": 1000,
                "amount": "100",
                "priceType": "RAW",
                "suspended": False,
            },
        ),
    )
    rows: list[BatchInputRow] = []
    for record_type, contract_name, data in records:
        identity = f"engine-{record_type}"
        payload = {
            "recordType": record_type,
            "data": data,
            "eventTime": event_time.isoformat(),
            "availableTime": available_time.isoformat(),
            "ingestTime": available_time.isoformat(),
            "processingTime": (event_time + timedelta(minutes=7)).isoformat(),
            "source": data.get("source", "fixture.synthetic.bar"),
            "rawObjectId": data.get("rawObjectId", identity),
            "payloadDigest": _digest(identity),
        }
        rows.append(
            BatchInputRow(
                row_id=identity,
                entity_id="518880.SH",
                event_time=event_time,
                available_time=available_time,
                lineage=BatchInputLineage(
                    reference=BatchInputReference(
                        origin=InputOrigin.SOURCE_CONTRACT,
                        name=contract_name,
                        version="v1",
                    ),
                    source_revision=f"revision:{identity}",
                ),
                payload=payload,
            )
        )
    return tuple(rows)


def _online_event_from_row(row: BatchInputRow) -> OnlineFeatureEvent:
    return OnlineFeatureEvent(
        event_id=row.row_id,
        entity_id=row.entity_id,
        source=(
            OnlineEventSource.DOMAIN
            if row.contract_name.startswith("domain.")
            else OnlineEventSource.MARKET
        ),
        contract_name=row.contract_name,
        contract_version=row.contract_version,
        source_revision=row.source_revision or "missing-source-revision",
        event_time=row.event_time,
        available_time=row.available_time,
        ingest_time=row.available_time + timedelta(minutes=1),
        payload=row.payload,
    )


def test_online_engine_exposes_unsupported_commodity_as_terminal() -> None:
    registry = precious_metals_feature_registry()
    feature = RegisteredFeature.from_registry(
        registry,
        "precious_metals_fund.premium_discount_bps",
    )
    rows = list(_engine_payload_rows())
    fund_payload = dict(rows[0].payload)
    fund_data = dict(cast(Mapping[str, object], fund_payload["data"]))
    fund_data["underlyingCommodity"] = "OTHER"
    fund_payload["data"] = fund_data
    fund_payload["payloadDigest"] = _digest("engine-fund-other")
    rows[0] = replace(rows[0], payload=fund_payload)
    events = tuple(_online_event_from_row(row) for row in rows)
    policy = OnlineWindowPolicy(
        size=timedelta(days=1),
        allowed_lateness=timedelta(minutes=30),
        stale_after=timedelta(minutes=10),
        ttl=timedelta(hours=1),
        replay_horizon=timedelta(hours=2),
    )
    adapter = OnlinePreciousMetalsAdapter(_policy())
    engine = OnlineFeatureEngine(
        store=InMemoryOnlineStateStore(),
        integrity=HmacOnlineStateIntegrity(b"p5-n14-online-engine-integrity-key-32-bytes"),
        calculator_trust=StaticOnlineCalculatorTrust(
            {feature.snapshot_ref.feature_fingerprint: adapter.artifact}
        ),
        policy=policy,
    )

    results = tuple(
        engine.process(
            feature,
            event,
            processing_time=DECISION - timedelta(minutes=3),
        )
        for event in events
    )

    assert results[0].disposition is OnlineProcessDisposition.PENDING
    assert results[1].disposition is OnlineProcessDisposition.PENDING
    assert results[2].disposition is OnlineProcessDisposition.TERMINAL
    assert results[2].terminal_status == FeatureStatus.REJECTED.value
    assert results[2].terminal_reason == FeatureReason.REJECTED_UNSUPPORTED_COMMODITY.value
    assert results[2].value is None
    assert results[2].state.values == ()
    assert len(results[2].state.accepted_evidence) == 3


def test_terminal_outcome_survives_duplicate_restart_and_later_materialization() -> None:
    feature = RegisteredFeature.from_registry(
        precious_metals_feature_registry(),
        "precious_metals_fund.premium_discount_bps",
    )
    identity = CalculatorIdentity(
        algorithm_version=feature.spec.algorithm_version,
        implementation_fingerprint=_digest("generic-terminal-calculator"),
    )

    def calculator(
        _feature: object,
        _window: object,
        events: tuple[OnlineFeatureEvent, ...],
    ) -> object:
        if events[-1].payload["result"] == "terminal":
            return OnlineCalculationResult.terminal(
                status="UNAVAILABLE",
                reason="UNAVAILABLE_TEST_PROBE",
            )
        return "1"

    artifact = OnlineCalculatorArtifact(identity=identity, calculator=calculator)
    policy = OnlineWindowPolicy(
        size=timedelta(days=1),
        allowed_lateness=timedelta(minutes=30),
        stale_after=timedelta(minutes=10),
        ttl=timedelta(hours=1),
        replay_horizon=timedelta(hours=2),
    )
    integrity = HmacOnlineStateIntegrity(b"p5-n14-terminal-state-integrity-key-32-bytes")
    store = InMemoryOnlineStateStore()

    def engine() -> OnlineFeatureEngine:
        return OnlineFeatureEngine(
            store=store,
            integrity=integrity,
            calculator_trust=StaticOnlineCalculatorTrust(
                {feature.snapshot_ref.feature_fingerprint: artifact}
            ),
            policy=policy,
        )

    event_time = DECISION - timedelta(minutes=10)
    available_time = DECISION - timedelta(minutes=5)

    def event(event_id: str, result: str, sequence: int) -> OnlineFeatureEvent:
        return OnlineFeatureEvent(
            event_id=event_id,
            entity_id="518880.SH",
            source=OnlineEventSource.DOMAIN,
            contract_name="domain.precious_metal_fund",
            contract_version="v1",
            source_revision=f"revision:{event_id}",
            event_time=event_time + timedelta(seconds=sequence),
            available_time=available_time + timedelta(seconds=sequence),
            ingest_time=available_time + timedelta(minutes=1, seconds=sequence),
            payload={"result": result},
        )

    online = engine()
    materialized = event("generic-materialized", "materialized", 0)
    terminal = event("generic-terminal", "terminal", 1)
    recovered = event("generic-recovered", "materialized", 2)
    processing_time = DECISION - timedelta(minutes=3)

    first = online.process(feature, materialized, processing_time=processing_time)
    assert first.disposition is OnlineProcessDisposition.COMMITTED
    assert len(first.state.values) == 1

    terminal_result = online.process(
        feature,
        terminal,
        processing_time=processing_time + timedelta(seconds=1),
    )
    assert terminal_result.disposition is OnlineProcessDisposition.TERMINAL
    assert terminal_result.terminal_status == "UNAVAILABLE"
    assert terminal_result.terminal_reason == "UNAVAILABLE_TEST_PROBE"
    assert terminal_result.state.values == ()
    assert len(terminal_result.state.terminal_outcomes) == 1
    outcome = terminal_result.state.terminal_outcomes[0]
    outcome_event_ids = {item.event_id for item in outcome.input_lineage}
    assert all(
        receipt.retain_until >= outcome.retain_until
        for receipt in terminal_result.state.receipts
        if receipt.event_id in outcome_event_ids
    )

    envelope = store.envelopes[0]

    class FixedEnvelopeStore:
        def __init__(self, fixed: feature_core.OnlineStateEnvelope) -> None:
            self.fixed = fixed

        def load(
            self,
            stream_key: str,
        ) -> feature_core.OnlineStateEnvelope | None:
            del stream_key
            return self.fixed

        def compare_and_set(
            self,
            *,
            expected_revision: int | None,
            candidate: feature_core.OnlineStateEnvelope,
        ) -> feature_core.OnlineCasResult:
            del expected_revision, candidate
            raise AssertionError("tampered state must fail before CAS")

    def assert_signed_state_rejected(
        state: feature_core.OnlineStreamState,
        match: str,
    ) -> None:
        signed = integrity.seal(state, retain_until=envelope.retain_until)
        tampered_engine = OnlineFeatureEngine(
            store=FixedEnvelopeStore(signed),
            integrity=integrity,
            calculator_trust=StaticOnlineCalculatorTrust(
                {feature.snapshot_ref.feature_fingerprint: artifact}
            ),
            policy=policy,
        )
        with pytest.raises(feature_core.OnlineIntegrityError, match=match):
            tampered_engine.read(feature, "518880.SH", as_of=processing_time)

    shifted_window = replace(
        outcome.window,
        start=outcome.window.start + timedelta(days=1),
        end=outcome.window.end + timedelta(days=1),
    )
    assert_signed_state_rejected(
        replace(
            terminal_result.state,
            terminal_outcomes=(replace(outcome, window=shifted_window),),
        ),
        "window is not canonical",
    )

    assert_signed_state_rejected(
        replace(
            terminal_result.state,
            terminal_outcomes=(
                replace(
                    outcome,
                    retain_until=outcome.computed_at + timedelta(minutes=1),
                ),
            ),
        ),
        "retain_until is inconsistent",
    )

    incomplete_lineage = outcome.input_lineage[1:]
    assert_signed_state_rejected(
        replace(
            terminal_result.state,
            terminal_outcomes=(
                replace(
                    outcome,
                    input_lineage=incomplete_lineage,
                    input_checksum=feature_core.canonical_checksum(incomplete_lineage),
                ),
            ),
        ),
        "lineage is not transition-complete",
    )

    trigger = next(
        item
        for item in terminal_result.state.accepted_evidence
        if item.event_id == outcome.event_id
    )
    future_trigger = replace(
        trigger,
        ingest_time=outcome.computed_at + timedelta(seconds=1),
    )
    future_lineage = tuple(
        feature_core.OnlineInputLineage.from_event(future_trigger)
        if item.event_id == future_trigger.event_id
        else item
        for item in outcome.input_lineage
    )
    future_state = replace(
        terminal_result.state,
        watermark_anchor=(
            future_trigger
            if terminal_result.state.watermark_anchor == trigger
            else terminal_result.state.watermark_anchor
        ),
        events=tuple(
            future_trigger if item.event_id == future_trigger.event_id else item
            for item in terminal_result.state.events
        ),
        accepted_evidence=tuple(
            future_trigger if item.event_id == future_trigger.event_id else item
            for item in terminal_result.state.accepted_evidence
        ),
        receipts=tuple(
            replace(receipt, content_checksum=future_trigger.content_checksum)
            if receipt.event_id == future_trigger.event_id
            else receipt
            for receipt in terminal_result.state.receipts
        ),
        terminal_outcomes=(
            replace(
                outcome,
                input_lineage=future_lineage,
                input_checksum=feature_core.canonical_checksum(future_lineage),
            ),
        ),
    )
    assert_signed_state_rejected(future_state, "before ingest_time")

    immediate_duplicate = online.process(
        feature,
        terminal,
        processing_time=processing_time + timedelta(seconds=1),
    )
    assert immediate_duplicate.disposition is OnlineProcessDisposition.DUPLICATE
    assert immediate_duplicate.terminal_reason == "UNAVAILABLE_TEST_PROBE"

    restarted = engine()
    restarted_duplicate = restarted.process(
        feature,
        terminal,
        processing_time=processing_time + timedelta(seconds=2),
    )
    assert restarted_duplicate.disposition is OnlineProcessDisposition.DUPLICATE
    assert restarted_duplicate.terminal_status == "UNAVAILABLE"
    assert restarted_duplicate.terminal_reason == "UNAVAILABLE_TEST_PROBE"

    recovered_result = restarted.process(
        feature,
        recovered,
        processing_time=processing_time + timedelta(seconds=3),
    )
    assert recovered_result.disposition is OnlineProcessDisposition.COMMITTED
    assert len(recovered_result.state.values) == 1
    assert len(recovered_result.state.terminal_outcomes) == 1

    replayed_terminal = restarted.process(
        feature,
        terminal,
        processing_time=processing_time + timedelta(seconds=4),
    )
    assert replayed_terminal.disposition is OnlineProcessDisposition.DUPLICATE
    assert replayed_terminal.terminal_reason == "UNAVAILABLE_TEST_PROBE"


def test_online_adapter_rejects_contract_and_record_type_mismatch_before_commit() -> None:
    feature = RegisteredFeature.from_registry(
        precious_metals_feature_registry(),
        "precious_metals_fund.premium_discount_bps",
    )
    adapter = OnlinePreciousMetalsAdapter(_policy())
    store = InMemoryOnlineStateStore()
    engine = OnlineFeatureEngine(
        store=store,
        integrity=HmacOnlineStateIntegrity(b"p5-n14-contract-binding-integrity-key-32-bytes"),
        calculator_trust=StaticOnlineCalculatorTrust(
            {feature.snapshot_ref.feature_fingerprint: adapter.artifact}
        ),
        policy=OnlineWindowPolicy(
            size=timedelta(days=1),
            allowed_lateness=timedelta(minutes=30),
            stale_after=timedelta(minutes=10),
            ttl=timedelta(hours=1),
            replay_horizon=timedelta(hours=2),
        ),
    )
    mislabeled = replace(
        _online_event_from_row(_engine_payload_rows()[0]),
        source=OnlineEventSource.MARKET,
        contract_name="market.daily_bar",
    )

    with pytest.raises(ValueError, match="requires recordType bar"):
        engine.process(
            feature,
            mislabeled,
            processing_time=DECISION - timedelta(minutes=3),
        )

    assert store.envelopes == ()


class _EngineSource:
    def __init__(self, rows: tuple[BatchInputRow, ...]) -> None:
        self.rows = rows

    def read_partition(self, request: PartitionReadRequest) -> BatchInputBatch:
        del request
        return BatchInputBatch(
            source_kind=SourceKind.PARQUET,
            snapshot_version="precious-metals-p5-n14-v1",
            rows=self.rows,
            manifest=PartitionInputManifest.from_rows(self.rows),
        )


def test_real_batch_engine_materializes_the_registered_feature() -> None:
    registry = precious_metals_feature_registry()
    feature = RegisteredFeature.from_registry(
        registry,
        "precious_metals_fund.premium_discount_bps",
    )
    rows = _engine_payload_rows()
    engine = BatchFeatureEngine(
        source=_EngineSource(rows),
        output_store=InMemoryFeaturePartitionStore(),
        checkpoint_store=InMemoryBatchCheckpointStore(),
    )
    execution = engine.run(
        feature,
        BatchPartition(
            key="2026-08-24",
            start=DECISION - timedelta(hours=1),
            end=DECISION,
            decision_time=DECISION,
        ),
        BatchPreciousMetalsAdapter(_policy()),
    )
    assert len(execution.result.rows) == 1
    assert execution.result.rows[0].value == "190000"
    assert execution.result.rows[0].available_time == DECISION - timedelta(minutes=5)


def test_real_online_engine_uses_the_same_registered_feature_and_adapter() -> None:
    registry = precious_metals_feature_registry()
    feature = RegisteredFeature.from_registry(
        registry,
        "precious_metals_fund.premium_discount_bps",
    )
    rows = _engine_payload_rows()

    events = tuple(_online_event_from_row(row) for row in rows)
    policy = OnlineWindowPolicy(
        size=timedelta(days=1),
        allowed_lateness=timedelta(minutes=30),
        stale_after=timedelta(minutes=10),
        ttl=timedelta(hours=1),
        replay_horizon=timedelta(hours=2),
    )
    adapter = OnlinePreciousMetalsAdapter(_policy())
    integrity = HmacOnlineStateIntegrity(b"p5-n14-online-engine-integrity-key-32-bytes")
    store = InMemoryOnlineStateStore()
    processing_time = DECISION - timedelta(minutes=3)
    engine = OnlineFeatureEngine(
        store=store,
        integrity=integrity,
        calculator_trust=StaticOnlineCalculatorTrust(
            {feature.snapshot_ref.feature_fingerprint: adapter.artifact}
        ),
        policy=policy,
    )

    online_steps = tuple(
        engine.process(feature, event, processing_time=processing_time) for event in events
    )
    fund_step, nav_step, online = online_steps
    direct = calculate_feature(
        feature.name,
        adapter.context(events, DECISION),
        _policy(),
    )
    online_direct = adapter.calculate(feature.name, events, DECISION)

    assert fund_step.disposition is OnlineProcessDisposition.PENDING
    assert fund_step.value is None
    assert fund_step.state.values == ()
    assert nav_step.disposition is OnlineProcessDisposition.PENDING
    assert nav_step.value is None
    assert nav_step.state.values == ()
    assert online.disposition is OnlineProcessDisposition.COMMITTED
    assert online.value is not None
    assert online.value.value == "190000"
    assert len(online.state.accepted_evidence) == 3
    assert len(online.state.values) == 1
    assert events[0].ingest_time != datetime.fromisoformat(str(events[0].payload["ingestTime"]))
    duplicate = engine.process(feature, events[0], processing_time=processing_time)
    assert duplicate.disposition is OnlineProcessDisposition.DUPLICATE
    assert online_direct.status is direct.status
    assert online_direct.reason is direct.reason
    assert online_direct.lineage == direct.lineage
    assert online_direct.available_time == direct.available_time
    assert isinstance(online.value.value, str)
    assert Decimal(online.value.value) == Decimal(direct.canonical_value or "0")
    assert online.value.available_time == direct.available_time == DECISION - timedelta(minutes=5)
    assert tuple(sorted(item.event_id for item in online.value.input_lineage)) == tuple(
        sorted(event.event_id for event in events)
    )


def test_real_online_engine_uses_trusted_processing_time_for_future_payload_probe() -> None:
    registry = precious_metals_feature_registry()
    feature = RegisteredFeature.from_registry(
        registry,
        "precious_metals_fund.premium_discount_bps",
    )
    rows = list(_engine_payload_rows())
    bar_index = next(
        index for index, row in enumerate(rows) if row.contract_name == "market.daily_bar"
    )
    future_payload = dict(rows[bar_index].payload)
    future_payload["processingTime"] = (DECISION + timedelta(minutes=10)).isoformat()
    rows[bar_index] = replace(rows[bar_index], payload=future_payload)

    events = tuple(_online_event_from_row(row) for row in rows)
    policy = OnlineWindowPolicy(
        size=timedelta(days=1),
        allowed_lateness=timedelta(minutes=30),
        stale_after=timedelta(minutes=10),
        ttl=timedelta(hours=1),
        replay_horizon=timedelta(hours=2),
    )
    adapter = OnlinePreciousMetalsAdapter(_policy())
    engine = OnlineFeatureEngine(
        store=InMemoryOnlineStateStore(),
        integrity=HmacOnlineStateIntegrity(b"p5-n14-online-engine-integrity-key-32-bytes"),
        calculator_trust=StaticOnlineCalculatorTrust(
            {feature.snapshot_ref.feature_fingerprint: adapter.artifact}
        ),
        policy=policy,
    )

    results = tuple(
        engine.process(feature, event, processing_time=DECISION - timedelta(minutes=3))
        for event in events
    )

    assert results[-1].disposition is OnlineProcessDisposition.TERMINAL
    assert results[-1].value is None
    assert results[-1].terminal_status == FeatureStatus.UNAVAILABLE.value
    assert results[-1].terminal_reason == FeatureReason.UNAVAILABLE_FUTURE_BAR_REVISION.value
    assert results[-1].state.values == ()
    assert results[-1].state.accepted_evidence[-1].event_id == "engine-bar"


def test_decimal_quantization_is_fixed_internally_but_wire_is_normalized() -> None:
    rows = _engine_payload_rows()
    policy = _policy()
    result = calculate_feature(
        "precious_metals_fund.premium_discount_bps",
        BatchPreciousMetalsAdapter(policy).context(rows, DECISION),
        policy,
    )
    assert result.value == Decimal("190000.000000")
    assert result.canonical_value == "190000"
