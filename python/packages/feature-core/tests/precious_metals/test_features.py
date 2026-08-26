from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from ashare_contracts import BenchmarkSeriesPoint, FundNav
from feature_core.precious_metals import (
    BenchmarkPolicy,
    BenchmarkSeriesPointRecord,
    EvidenceLineage,
    FeatureReason,
    FeatureStatus,
    FundClassificationRecord,
    FundNavRecord,
    PreciousMetalsFeatureInput,
    PreciousMetalsPolicy,
    RawBarRecord,
    calculate_feature,
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
    source: str = "fixture.synthetic",
    raw_object_id: str | None = None,
    payload_digest: str | None = None,
    ingest_time: datetime | None = None,
) -> EvidenceLineage:
    available = available_time or event_time + timedelta(minutes=1)
    return EvidenceLineage(
        source=source,
        source_revision=source_revision or f"revision:{identity}",
        raw_object_id=raw_object_id or f"raw:{identity}",
        payload_digest=payload_digest or _digest(identity),
        event_time=event_time,
        available_time=available,
        processing_time=processing_time or available + timedelta(minutes=1),
        ingest_time=ingest_time,
        source_contract_version="v1",
    )


def _fund(
    *,
    commodity: str = "GOLD",
    confidence: str = "0.95",
    review_status: str = "REVIEWED",
    benchmark_id: str | None = GOLD_ID,
    nav_currency: str = "CNY",
) -> PreciousMetalFund:
    return PreciousMetalFund(
        unified_code="518880.SH",
        exchange="SH",
        asset_type="ETF",
        fund_asset_class="PRECIOUS_METALS",
        underlying_commodity=commodity,
        trading_currency="CNY",
        nav_currency=nav_currency,
        benchmark_or_tracking_index="display text is not an identity",
        benchmark_series_id=benchmark_id,
        management_fee_rate=Decimal("0.005"),
        valid_from="2026-01-01",
        valid_to=None,
        source="fixture.synthetic.fund",
        publish_time=DECISION - timedelta(days=20),
        ingest_time=DECISION - timedelta(days=20),
        available_time=DECISION - timedelta(days=20),
        processing_time=DECISION - timedelta(days=20),
        raw_object_id="fund-classification-v1",
        confidence=Decimal(confidence),
        review_status=review_status,
    )


def _nav(
    *,
    event_time: datetime,
    nav: str = "10.00",
    inav: str | None = "10.00",
    available_time: datetime | None = None,
    raw_object_id: str = "nav-v1",
) -> FundNavRecord:
    available = available_time or event_time + timedelta(minutes=2)
    payload = FundNav(
        unifiedCode="518880.SH",
        date=event_time.date(),
        nav=Decimal(nav),
        inav=Decimal(inav) if inav is not None else None,
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
        lineage=_lineage(
            raw_object_id,
            event_time,
            available_time=available,
            processing_time=available,
            source=payload.source,
            raw_object_id=payload.raw_object_id,
            payload_digest=_digest(raw_object_id),
            ingest_time=payload.ingest_time,
        ),
    )


def _bar(
    index: int,
    *,
    amount: str | None = None,
    suspended: bool = False,
) -> RawBarRecord:
    event_time = datetime(2026, 8, 4 + index, 15, 0, tzinfo=SHANGHAI)
    close = Decimal(200 + 2 * index)
    payload = Bar(
        unified_code="518880.SH",
        exchange="SH",
        date=event_time.date().isoformat(),
        interval="DAILY",
        session="CONTINUOUS",
        timestamp=event_time.isoformat(),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000 + index,
        amount=Decimal(amount or str(100 + index)),
        price_type="RAW",
        suspended=suspended,
    )
    return RawBarRecord(bar=payload, lineage=_lineage(f"bar-{index}", event_time))


def _benchmark(
    index: int,
    *,
    benchmark_id: str = GOLD_ID,
    currency: str = "CNY",
    price_basis: str = "CLOSE",
    reference_value: str | None = None,
) -> BenchmarkSeriesPointRecord:
    event_time = datetime(2026, 8, 4 + index, 15, 0, tzinfo=SHANGHAI)
    payload = BenchmarkSeriesPoint.model_validate(
        {
            "schemaVersion": "benchmark-series-point-v1",
            "benchmarkId": benchmark_id,
            "currency": currency,
            "priceBasis": price_basis,
            "referenceValue": reference_value or str(100 + index),
            "eventTime": event_time.isoformat(),
            "ingestTime": (event_time + timedelta(minutes=1)).isoformat(),
            "availableTime": (event_time + timedelta(minutes=2)).isoformat(),
            "processingTime": (event_time + timedelta(minutes=3)).isoformat(),
            "source": "fixture.synthetic.benchmark",
            "sourceRevision": f"benchmark-revision-{index}",
            "rawObjectId": f"benchmark-raw-{index}",
            "payloadDigest": _digest(f"benchmark-{index}"),
            "referenceOnly": True,
        }
    )
    return BenchmarkSeriesPointRecord(
        point=payload,
        lineage=_lineage(
            f"benchmark-{index}",
            event_time,
            available_time=payload.available_time,
            processing_time=payload.processing_time,
            source=payload.source,
            source_revision=payload.source_revision,
            raw_object_id=payload.raw_object_id,
            payload_digest=payload.payload_digest,
            ingest_time=payload.ingest_time,
        ),
    )


def _policy(benchmark_id: str = GOLD_ID) -> PreciousMetalsPolicy:
    return PreciousMetalsPolicy(
        benchmarks=(
            BenchmarkPolicy(
                benchmark_series_id=benchmark_id,
                allowed_price_bases=("CLOSE",),
                currency="CNY",
            ),
        ),
    )


def _input(
    *,
    fund: PreciousMetalFund | None = None,
    navs: tuple[FundNavRecord, ...] | None = None,
    bars: tuple[RawBarRecord, ...] | None = None,
    benchmarks: tuple[BenchmarkSeriesPointRecord, ...] | None = None,
) -> PreciousMetalsFeatureInput:
    return PreciousMetalsFeatureInput(
        fund=fund or _fund(),
        decision_time=DECISION,
        navs=navs or (_nav(event_time=DECISION - timedelta(minutes=2)),),
        bars=bars if bars is not None else tuple(_bar(index) for index in range(21)),
        benchmarks=(
            benchmarks
            if benchmarks is not None
            else tuple(_benchmark(index) for index in range(21))
        ),
    )


def test_v1_specs_are_registered_and_versioned() -> None:
    specs = precious_metals_feature_specs()
    assert len(specs) == 5
    assert {spec.entity.value for spec in specs} == {"PRECIOUS_METALS_FUND"}
    assert {spec.value_type.value for spec in specs} == {"DECIMAL"}
    assert {spec.availability_policy.value for spec in specs} == {"MAX_INPUT_AVAILABLE_TIME"}
    assert all(spec.version == "v1" for spec in specs)
    assert all(spec.algorithm_version == "v1" for spec in specs)
    assert all(spec.semantic_fingerprint.startswith("sha256:") for spec in specs)


def test_valid_gold_uses_exact_decimal_features() -> None:
    context = _input()
    premium = calculate_feature("precious_metals_fund.premium_discount_bps", context, _policy())
    tracking = calculate_feature(
        "precious_metals_fund.tracking_difference_bps_20_sessions", context, _policy()
    )
    error = calculate_feature(
        "precious_metals_fund.tracking_error_bps_20_sessions", context, _policy()
    )
    liquidity = calculate_feature(
        "precious_metals_fund.liquidity_median_turnover_cny_20_sessions", context, _policy()
    )
    beta = calculate_feature("precious_metals_fund.benchmark_beta_20_sessions", context, _policy())

    assert premium.status is FeatureStatus.PUBLISHED
    assert premium.reason is FeatureReason.PUBLISHED
    assert premium.value == Decimal("228000.000000")
    assert premium.canonical_value == "228000"
    assert tracking.value == Decimal("0.000000")
    assert error.value == Decimal("0.000000")
    assert liquidity.value == Decimal("109.500000")
    assert beta.value == Decimal("1.000000")
    assert all(item.policy_version == "v1" for item in (premium, tracking, error, liquidity, beta))


def test_stale_inav_falls_back_to_nav_without_numeric_leakage() -> None:
    context = _input(
        navs=(_nav(event_time=DECISION - timedelta(minutes=6), nav="10.00", inav="10.20"),),
    )
    result = calculate_feature("precious_metals_fund.premium_discount_bps", context, _policy())
    assert result.status is FeatureStatus.DEGRADED
    assert result.reason is FeatureReason.DEGRADED_STALE_INAV_FALLBACK_NAV
    assert result.value == Decimal("228000.000000")


def test_missing_inav_uses_nav_with_explicit_degraded_state() -> None:
    context = _input(navs=(_nav(event_time=DECISION - timedelta(days=1), inav=None),))
    result = calculate_feature("precious_metals_fund.premium_discount_bps", context, _policy())
    assert result.reason is FeatureReason.DEGRADED_NAV_FALLBACK_NO_INAV
    assert result.value == Decimal("228000.000000")


def test_future_nav_revision_is_excluded_at_earlier_decision_time() -> None:
    old = _nav(
        event_time=DECISION - timedelta(days=1),
        nav="10.00",
        inav=None,
        available_time=DECISION - timedelta(hours=1),
        raw_object_id="nav-old",
    )
    future = _nav(
        event_time=DECISION - timedelta(days=1),
        nav="8.00",
        inav=None,
        available_time=DECISION + timedelta(minutes=1),
        raw_object_id="nav-future",
    )
    early = calculate_feature(
        "precious_metals_fund.premium_discount_bps",
        _input(navs=(old, future)),
        _policy(),
    )
    late_context = replace(_input(navs=(old, future)), decision_time=DECISION + timedelta(hours=1))
    late = calculate_feature("precious_metals_fund.premium_discount_bps", late_context, _policy())
    assert early.value == Decimal("228000.000000")
    assert late.value == Decimal("290000.000000")


def test_missing_benchmark_fails_closed_and_display_text_is_not_a_fallback() -> None:
    context = _input(fund=_fund(benchmark_id=None), benchmarks=())
    result = calculate_feature(
        "precious_metals_fund.tracking_difference_bps_20_sessions", context, _policy()
    )
    assert result.status is FeatureStatus.UNAVAILABLE
    assert result.reason is FeatureReason.UNAVAILABLE_MISSING_BENCHMARK
    assert result.value is None


def test_missing_raw_market_reference_fails_closed() -> None:
    context = _input(bars=())
    result = calculate_feature("precious_metals_fund.premium_discount_bps", context, _policy())
    assert result.reason is FeatureReason.UNAVAILABLE_NO_MARKET_REFERENCE_PRICE
    assert result.value is None


def test_other_and_unverified_classifications_have_no_numeric_release() -> None:
    other = calculate_feature(
        "precious_metals_fund.premium_discount_bps",
        _input(fund=_fund(commodity="OTHER")),
        _policy(),
    )
    low_confidence = calculate_feature(
        "precious_metals_fund.premium_discount_bps",
        _input(fund=_fund(confidence="0.79")),
        _policy(),
    )
    assert other.status is FeatureStatus.REJECTED
    assert other.reason is FeatureReason.REJECTED_UNSUPPORTED_COMMODITY
    assert other.value is None
    assert low_confidence.status is FeatureStatus.DEGRADED
    assert low_confidence.reason is FeatureReason.DEGRADED_CLASSIFICATION_UNVERIFIED
    assert low_confidence.value is None


def test_exact_decision_time_availability_is_visible() -> None:
    exact = _nav(
        event_time=DECISION - timedelta(days=1),
        inav=None,
        available_time=DECISION,
        raw_object_id="nav-exact",
    )
    result = calculate_feature(
        "precious_metals_fund.premium_discount_bps", _input(navs=(exact,)), _policy()
    )
    assert result.value == Decimal("228000.000000")


def test_inav_exact_five_minute_boundary_publishes_and_older_inav_falls_back() -> None:
    visible_bars = tuple(_bar(index) for index in range(20))
    exact = calculate_feature(
        "precious_metals_fund.premium_discount_bps",
        _input(
            navs=(_nav(event_time=DECISION - timedelta(minutes=5), inav="10.20"),),
            bars=visible_bars,
        ),
        _policy(),
    )
    expected = ((Decimal("238") / Decimal("10.20") - Decimal("1")) * Decimal("10000")).quantize(
        Decimal("0.000001")
    )
    assert exact.status is FeatureStatus.PUBLISHED
    assert exact.reason is FeatureReason.PUBLISHED
    assert exact.value == expected

    stale = calculate_feature(
        "precious_metals_fund.premium_discount_bps",
        _input(
            navs=(_nav(event_time=DECISION - timedelta(minutes=6), inav="10.20"),),
            bars=visible_bars,
        ),
        _policy(),
    )
    assert stale.reason is FeatureReason.DEGRADED_STALE_INAV_FALLBACK_NAV
    assert stale.value == Decimal("228000.000000")


def test_nav_exact_seven_day_boundary_falls_back_and_older_nav_is_unavailable() -> None:
    exact = calculate_feature(
        "precious_metals_fund.premium_discount_bps",
        _input(
            navs=(
                _nav(
                    event_time=DECISION - timedelta(days=7),
                    inav=None,
                    available_time=DECISION - timedelta(hours=1),
                ),
            ),
        ),
        _policy(),
    )
    assert exact.reason is FeatureReason.DEGRADED_NAV_FALLBACK_NO_INAV
    assert exact.value == Decimal("228000.000000")

    expired = calculate_feature(
        "precious_metals_fund.premium_discount_bps",
        _input(
            navs=(
                _nav(
                    event_time=DECISION - timedelta(days=7, seconds=1),
                    inav=None,
                    available_time=DECISION - timedelta(hours=1),
                ),
            ),
        ),
        _policy(),
    )
    assert expired.reason is FeatureReason.UNAVAILABLE_NO_VALUATION_REFERENCE
    assert expired.value is None


@pytest.mark.parametrize(
    "feature_name",
    [
        "precious_metals_fund.tracking_difference_bps_20_sessions",
        "precious_metals_fund.tracking_error_bps_20_sessions",
        "precious_metals_fund.benchmark_beta_20_sessions",
    ],
)
def test_price_basis_and_currency_mismatch_fail_closed(feature_name: str) -> None:
    basis_mismatch = calculate_feature(
        feature_name,
        _input(benchmarks=tuple(_benchmark(index, price_basis="OPEN") for index in range(21))),
        _policy(),
    )
    assert basis_mismatch.value is None
    assert basis_mismatch.reason is FeatureReason.UNAVAILABLE_MISSING_BENCHMARK

    currency_mismatch = calculate_feature(
        feature_name,
        _input(benchmarks=tuple(_benchmark(index, currency="USD") for index in range(21))),
        _policy(),
    )
    assert currency_mismatch.value is None
    assert currency_mismatch.reason is FeatureReason.UNAVAILABLE_CURRENCY_MISMATCH_NO_FX

    nav_currency_mismatch = calculate_feature(
        "precious_metals_fund.premium_discount_bps",
        _input(fund=_fund(nav_currency="USD")),
        _policy(),
    )
    assert nav_currency_mismatch.value is None
    assert nav_currency_mismatch.reason is FeatureReason.UNAVAILABLE_CURRENCY_MISMATCH_NO_FX


def test_zero_benchmark_variance_fails_closed_for_beta() -> None:
    result = calculate_feature(
        "precious_metals_fund.benchmark_beta_20_sessions",
        _input(
            benchmarks=tuple(_benchmark(index, reference_value="100") for index in range(21)),
        ),
        _policy(),
    )
    assert result.value is None
    assert result.reason is FeatureReason.UNAVAILABLE_ZERO_BENCHMARK_VARIANCE


def test_liquidity_excludes_suspended_and_zero_amount_and_requires_ten_rows() -> None:
    invalid = tuple(_bar(index) for index in range(9)) + (
        _bar(9, amount="0"),
        _bar(10, amount="1000", suspended=True),
    )
    insufficient = calculate_feature(
        "precious_metals_fund.liquidity_median_turnover_cny_20_sessions",
        _input(bars=invalid),
        _policy(),
    )
    assert insufficient.value is None
    assert insufficient.reason is FeatureReason.UNAVAILABLE_INSUFFICIENT_SAMPLES

    ten_rows = calculate_feature(
        "precious_metals_fund.liquidity_median_turnover_cny_20_sessions",
        _input(bars=tuple(_bar(index) for index in range(10))),
        _policy(),
    )
    assert ten_rows.reason is FeatureReason.PUBLISHED
    assert ten_rows.value == Decimal("104.500000")


def test_classification_revision_conflict_rejects_all_numeric_release() -> None:
    first = _fund()
    second = replace(first, raw_object_id="fund-classification-v2")
    context = replace(
        _input(),
        classification_revisions=(
            FundClassificationRecord(
                fund=first,
                lineage=_lineage(
                    "classification-v1",
                    first.available_time,
                    available_time=first.available_time,
                    processing_time=first.processing_time,
                    source=first.source,
                    raw_object_id=first.raw_object_id,
                    ingest_time=first.ingest_time,
                ),
            ),
            FundClassificationRecord(
                fund=second,
                lineage=_lineage(
                    "classification-v2",
                    second.available_time,
                    available_time=second.available_time,
                    processing_time=second.processing_time,
                    source=second.source,
                    raw_object_id=second.raw_object_id,
                    ingest_time=second.ingest_time,
                ),
            ),
        ),
    )
    result = calculate_feature("precious_metals_fund.premium_discount_bps", context, _policy())
    assert result.value is None
    assert result.reason is FeatureReason.REJECTED_CONFLICTING_CLASSIFICATION
    assert {item.raw_object_id for item in result.lineage} == {
        "fund-classification-v1",
        "fund-classification-v2",
    }


def test_silver_classification_has_positive_numeric_output() -> None:
    result = calculate_feature(
        "precious_metals_fund.premium_discount_bps",
        _input(fund=_fund(commodity="SILVER")),
        _policy(),
    )
    assert result.value is not None
    assert result.value > Decimal("0")


def test_float_boundaries_are_rejected_by_public_contracts() -> None:
    with pytest.raises(TypeError):
        FundNav(
            unifiedCode="518880.SH",
            date=DECISION.date(),
            nav=cast(Decimal, 1.0),
            inav=None,
            eventTime=DECISION,
            publishTime=DECISION,
            ingestTime=DECISION,
            availableTime=DECISION,
            processingTime=DECISION,
            rawObjectId="float",
            source="fixture",
        )


def test_same_latest_revision_bucket_fails_closed() -> None:
    left = _nav(
        event_time=DECISION - timedelta(days=1),
        inav=None,
        available_time=DECISION - timedelta(hours=1),
        raw_object_id="conflict-left",
    )
    right = _nav(
        event_time=DECISION - timedelta(days=1),
        nav="11.00",
        inav=None,
        available_time=DECISION - timedelta(hours=1),
        raw_object_id="conflict-right",
    )
    result = calculate_feature(
        "precious_metals_fund.premium_discount_bps", _input(navs=(left, right)), _policy()
    )
    assert result.reason is FeatureReason.UNAVAILABLE_CONFLICTING_NAV_REVISION


def test_fixture_index_has_only_sanitized_content() -> None:
    path = (
        Path(__file__).parents[3]
        / "backtest-core/tests/fixtures/precious-metals/dataset/dataset-manifest.json"
    )
    payload = path.read_text(encoding="utf-8")
    assert "password" not in payload.lower()
    assert "token" not in payload.lower()
    assert "prod" not in payload.lower()
