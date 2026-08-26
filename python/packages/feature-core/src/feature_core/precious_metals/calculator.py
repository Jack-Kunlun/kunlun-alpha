"""The single deterministic Decimal implementation for precious-metal features."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import cast
from zoneinfo import ZoneInfo

from ashare_contracts import is_canonical_benchmark_id
from market_core.funds import PreciousMetalFund, validate_precious_metal_fund

from feature_core.registry import FeatureSpec

from .models import (
    POLICY_VERSION,
    SOURCE_CONTRACT_VERSION,
    BenchmarkSeriesPointRecord,
    EvidenceLineage,
    FeatureReason,
    FeatureResult,
    FeatureStatus,
    PreciousMetalsFeatureInput,
    PreciousMetalsPolicy,
    RawBarRecord,
    quantize_value,
)
from .specs import precious_metals_feature_specs

SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class _Selection[RecordT]:
    records: tuple[RecordT, ...]
    has_future: bool
    conflict: bool


@dataclass(frozen=True, slots=True)
class _Gate:
    fund: PreciousMetalFund
    classification_lineage: EvidenceLineage
    rejection: FeatureResult | None


def _status(reason: FeatureReason) -> FeatureStatus:
    if reason is FeatureReason.PUBLISHED:
        return FeatureStatus.PUBLISHED
    if reason.name.startswith("DEGRADED"):
        return FeatureStatus.DEGRADED
    if reason.name.startswith("REJECTED"):
        return FeatureStatus.REJECTED
    return FeatureStatus.UNAVAILABLE


def _spec(name: str) -> FeatureSpec:
    for spec in precious_metals_feature_specs():
        if spec.name == name:
            return spec
    raise ValueError(f"unknown precious-metals feature: {name}")


def _lineages(*values: EvidenceLineage | Iterable[EvidenceLineage]) -> tuple[EvidenceLineage, ...]:
    flattened: list[EvidenceLineage] = []
    for value in values:
        if isinstance(value, EvidenceLineage):
            flattened.append(value)
        else:
            flattened.extend(value)
    return tuple(set(flattened))


def _failure_lineage(
    context: PreciousMetalsFeatureInput,
    classification_lineage: EvidenceLineage,
    reason: FeatureReason,
) -> tuple[EvidenceLineage, ...]:
    values: list[EvidenceLineage | Iterable[EvidenceLineage]] = [classification_lineage]
    if "NAV" in reason.name or reason is FeatureReason.UNAVAILABLE_NO_VALUATION_REFERENCE:
        values.append(item.lineage for item in context.navs)
    if "BAR" in reason.name or reason is FeatureReason.UNAVAILABLE_NO_MARKET_REFERENCE_PRICE:
        values.append(item.lineage for item in context.bars)
    if "BENCHMARK" in reason.name or reason is FeatureReason.UNAVAILABLE_MISSING_BENCHMARK:
        values.append(item.lineage for item in context.benchmarks)
    return _lineages(*values)


def _result(
    spec: FeatureSpec,
    context: PreciousMetalsFeatureInput,
    reason: FeatureReason,
    *,
    value: Decimal | None,
    lineage: tuple[EvidenceLineage, ...],
) -> FeatureResult:
    ordered = tuple(lineage)
    event_time = max((item.event_time for item in ordered), default=context.decision_time)
    available_time = max((item.available_time for item in ordered), default=context.decision_time)
    return FeatureResult(
        value=None if value is None else quantize_value(value),
        status=_status(reason),
        reason=reason,
        event_time=event_time,
        available_time=available_time,
        spec_version=spec.version,
        semantic_fingerprint=spec.semantic_fingerprint,
        algorithm_version=spec.algorithm_version,
        policy_version=POLICY_VERSION,
        source_contract_version=SOURCE_CONTRACT_VERSION,
        lineage=ordered,
    )


def _select_latest[RecordT](
    records: Iterable[RecordT],
    *,
    identity: Callable[[RecordT], object],
    lineage: Callable[[RecordT], EvidenceLineage],
    decision_time: datetime,
) -> _Selection[RecordT]:
    visible: list[RecordT] = []
    has_future = False
    for record in records:
        evidence = lineage(record)
        if (
            evidence.available_time <= decision_time
            and evidence.event_time <= decision_time
            and evidence.processing_time <= decision_time
        ):
            visible.append(record)
        elif (
            evidence.available_time > decision_time
            or evidence.event_time > decision_time
            or evidence.processing_time > decision_time
        ):
            has_future = True

    grouped: dict[object, list[RecordT]] = {}
    for record in visible:
        grouped.setdefault(identity(record), []).append(record)

    selected: list[RecordT] = []
    conflict = False
    for group in grouped.values():
        latest_bucket = max(
            (lineage(item).available_time, lineage(item).processing_time) for item in group
        )
        bucket = [
            item
            for item in group
            if (lineage(item).available_time, lineage(item).processing_time) == latest_bucket
        ]
        if (
            len({(lineage(item).source_revision, lineage(item).payload_digest) for item in bucket})
            > 1
        ):
            conflict = True
            continue
        selected.append(
            max(
                group,
                key=lambda item: (
                    lineage(item).available_time,
                    lineage(item).processing_time,
                    lineage(item).source_revision,
                    lineage(item).payload_digest,
                ),
            )
        )
    selected.sort(key=lambda item: str(identity(item)))
    return _Selection(tuple(selected), has_future, conflict)


def _classification_gate(
    context: PreciousMetalsFeatureInput,
    spec: FeatureSpec,
    policy: PreciousMetalsPolicy,
) -> _Gate:
    selection = _select_latest(
        (
            item
            for item in context.classification_revisions
            if item.fund.unified_code == context.fund.unified_code
        ),
        identity=lambda item: item.identity,
        lineage=lambda item: item.lineage,
        decision_time=context.decision_time,
    )
    if selection.conflict or not selection.records:
        lineage = _lineages(item.lineage for item in context.classification_revisions)
        return _Gate(
            cast(PreciousMetalFund, context.fund),
            lineage[0],
            _result(
                spec,
                context,
                (
                    FeatureReason.REJECTED_CONFLICTING_CLASSIFICATION
                    if selection.conflict
                    else FeatureReason.REJECTED_CLASSIFICATION
                ),
                value=None,
                lineage=lineage,
            ),
        )
    record = selection.records[-1]
    fund = cast(PreciousMetalFund, record.fund)
    lineage = record.lineage
    try:
        validation = validate_precious_metal_fund(fund, decision_time=context.decision_time)
    except (TypeError, ValueError, AttributeError):
        validation = None
    if fund.underlying_commodity not in {"GOLD", "SILVER"}:
        reason = FeatureReason.REJECTED_UNSUPPORTED_COMMODITY
    elif (
        fund.asset_type not in {"ETF", "LOF", "FUND"}
        or fund.fund_asset_class != "PRECIOUS_METALS"
        or validation is None
        or not validation.valid
    ):
        reason = FeatureReason.REJECTED_CLASSIFICATION
    else:
        try:
            valid_from = datetime.fromisoformat(fund.valid_from).date()
            valid_to = (
                None if fund.valid_to is None else datetime.fromisoformat(fund.valid_to).date()
            )
        except ValueError:
            valid_from = None
            valid_to = None
        decision_date = context.decision_time.astimezone(SHANGHAI).date()
        if (
            valid_from is None
            or decision_date < valid_from
            or (valid_to is not None and decision_date > valid_to)
        ):
            reason = FeatureReason.REJECTED_CLASSIFICATION
        elif fund.review_status != "REVIEWED" or fund.confidence < policy.accepted_confidence:
            reason = FeatureReason.DEGRADED_CLASSIFICATION_UNVERIFIED
        else:
            return _Gate(fund, lineage, None)
    return _Gate(
        fund,
        lineage,
        _result(spec, context, reason, value=None, lineage=(lineage,)),
    )


def _bars(context: PreciousMetalsFeatureInput, fund: PreciousMetalFund) -> _Selection[RawBarRecord]:
    return _select_latest(
        (item for item in context.bars if item.bar.unified_code == fund.unified_code),
        identity=lambda item: item.identity,
        lineage=lambda item: item.lineage,
        decision_time=context.decision_time,
    )


def _market_bars(selection: _Selection[RawBarRecord]) -> tuple[RawBarRecord, ...]:
    return tuple(
        item
        for item in selection.records
        if item.bar.interval == "DAILY"
        and item.bar.price_type == "RAW"
        and not item.bar.suspended
        and item.bar.close > Decimal("0")
    )


def _valuation(
    context: PreciousMetalsFeatureInput,
    fund: PreciousMetalFund,
    policy: PreciousMetalsPolicy,
) -> tuple[Decimal, FeatureReason, EvidenceLineage] | FeatureReason:
    if fund.nav_currency != fund.trading_currency:
        return FeatureReason.UNAVAILABLE_CURRENCY_MISMATCH_NO_FX
    selection = _select_latest(
        (item for item in context.navs if item.nav.unified_code == fund.unified_code),
        identity=lambda item: item.identity,
        lineage=lambda item: item.lineage,
        decision_time=context.decision_time,
    )
    if selection.conflict:
        return FeatureReason.UNAVAILABLE_CONFLICTING_NAV_REVISION
    if not selection.records:
        return (
            FeatureReason.UNAVAILABLE_FUTURE_NAV_REVISION
            if selection.has_future
            else FeatureReason.UNAVAILABLE_NO_VALUATION_REFERENCE
        )
    latest = max(
        selection.records,
        key=lambda item: (
            item.lineage.event_time,
            item.lineage.available_time,
            item.lineage.processing_time,
            item.lineage.source_revision,
            item.lineage.payload_digest,
        ),
    )
    age = context.decision_time - latest.lineage.event_time
    if (
        age >= timedelta(0)
        and age <= policy.inav_max_age
        and latest.nav.inav is not None
        and latest.nav.inav > Decimal("0")
    ):
        return latest.nav.inav, FeatureReason.PUBLISHED, latest.lineage
    if age < timedelta(0) or age > policy.nav_fallback_max_age or latest.nav.nav <= Decimal("0"):
        return FeatureReason.UNAVAILABLE_NO_VALUATION_REFERENCE
    reason = (
        FeatureReason.DEGRADED_STALE_INAV_FALLBACK_NAV
        if latest.nav.inav is not None
        else FeatureReason.DEGRADED_NAV_FALLBACK_NO_INAV
    )
    return latest.nav.nav, reason, latest.lineage


def _premium_discount(
    context: PreciousMetalsFeatureInput,
    fund: PreciousMetalFund,
    spec: FeatureSpec,
    policy: PreciousMetalsPolicy,
    classification_lineage: EvidenceLineage,
) -> FeatureResult:
    bar_selection = _bars(context, fund)
    candidates = _market_bars(bar_selection)
    if bar_selection.conflict:
        return _result(
            spec,
            context,
            FeatureReason.UNAVAILABLE_CONFLICTING_BAR_REVISION,
            value=None,
            lineage=_failure_lineage(
                context,
                classification_lineage,
                FeatureReason.UNAVAILABLE_CONFLICTING_BAR_REVISION,
            ),
        )
    if not candidates:
        return _result(
            spec,
            context,
            (
                FeatureReason.UNAVAILABLE_FUTURE_BAR_REVISION
                if bar_selection.has_future
                else FeatureReason.UNAVAILABLE_NO_MARKET_REFERENCE_PRICE
            ),
            value=None,
            lineage=_failure_lineage(
                context,
                classification_lineage,
                (
                    FeatureReason.UNAVAILABLE_FUTURE_BAR_REVISION
                    if bar_selection.has_future
                    else FeatureReason.UNAVAILABLE_NO_MARKET_REFERENCE_PRICE
                ),
            ),
        )
    market = max(
        candidates, key=lambda item: (item.lineage.event_time, item.lineage.available_time)
    )
    valuation = _valuation(context, fund, policy)
    if isinstance(valuation, FeatureReason):
        return _result(
            spec,
            context,
            valuation,
            value=None,
            lineage=_failure_lineage(context, classification_lineage, valuation),
        )
    reference, reason, valuation_lineage = valuation
    with localcontext() as decimal_context:
        decimal_context.prec = 80
        value = (market.bar.close / reference - Decimal("1")) * Decimal("10000")
    return _result(
        spec,
        context,
        reason,
        value=value,
        lineage=_lineages(classification_lineage, market.lineage, valuation_lineage),
    )


def _benchmark_series(
    context: PreciousMetalsFeatureInput,
    fund: PreciousMetalFund,
    policy: PreciousMetalsPolicy,
) -> tuple[dict[str, BenchmarkSeriesPointRecord], tuple[EvidenceLineage, ...]] | FeatureReason:
    binding = fund.benchmark_series_id
    if binding is None or not is_canonical_benchmark_id(binding):
        return FeatureReason.UNAVAILABLE_MISSING_BENCHMARK
    benchmark_policy = policy.benchmark(binding)
    if benchmark_policy is None:
        return FeatureReason.UNAVAILABLE_MISSING_BENCHMARK
    selection = _select_latest(
        (item for item in context.benchmarks if item.point.benchmark_id == binding),
        identity=lambda item: item.identity,
        lineage=lambda item: item.lineage,
        decision_time=context.decision_time,
    )
    if selection.conflict:
        return FeatureReason.UNAVAILABLE_CONFLICTING_BENCHMARK_REVISION
    if not selection.records and selection.has_future:
        return FeatureReason.UNAVAILABLE_FUTURE_BENCHMARK_REVISION
    currency_mismatch = False
    basis_mismatch = False
    invalid_reference = False
    valid: list[BenchmarkSeriesPointRecord] = []
    for item in selection.records:
        point = item.point
        if point.reference_only is not True or point.reference_value <= Decimal("0"):
            invalid_reference = True
            continue
        if point.currency != benchmark_policy.currency or point.currency != fund.trading_currency:
            currency_mismatch = True
            continue
        if point.price_basis not in benchmark_policy.allowed_price_bases:
            basis_mismatch = True
            continue
        valid.append(item)
    if currency_mismatch:
        return FeatureReason.UNAVAILABLE_CURRENCY_MISMATCH_NO_FX
    if basis_mismatch or invalid_reference or not valid:
        return FeatureReason.UNAVAILABLE_MISSING_BENCHMARK
    bases = {item.point.price_basis for item in valid}
    currencies = {item.point.currency for item in valid}
    if len(bases) != 1:
        return FeatureReason.UNAVAILABLE_MISSING_BENCHMARK
    if currencies != {benchmark_policy.currency}:
        return FeatureReason.UNAVAILABLE_CURRENCY_MISMATCH_NO_FX
    by_date = {
        item.point.event_time.astimezone(SHANGHAI).date().isoformat(): item for item in valid
    }
    return by_date, tuple(item.lineage for item in valid)


def _paired_returns(
    context: PreciousMetalsFeatureInput,
    fund: PreciousMetalFund,
    policy: PreciousMetalsPolicy,
) -> tuple[tuple[Decimal, Decimal, EvidenceLineage, EvidenceLineage], ...] | FeatureReason:
    bar_selection = _bars(context, fund)
    if bar_selection.conflict:
        return FeatureReason.UNAVAILABLE_CONFLICTING_BAR_REVISION
    if not bar_selection.records and bar_selection.has_future:
        return FeatureReason.UNAVAILABLE_FUTURE_BAR_REVISION
    benchmark_data = _benchmark_series(context, fund, policy)
    if isinstance(benchmark_data, FeatureReason):
        return benchmark_data
    benchmark_by_date, _ = benchmark_data
    bars = {
        item.bar.date: item
        for item in _market_bars(bar_selection)
        if item.bar.date in benchmark_by_date
    }
    dates = sorted(set(bars).intersection(benchmark_by_date))
    if len(dates) < 2:
        return FeatureReason.UNAVAILABLE_INSUFFICIENT_SAMPLES
    returns: list[tuple[Decimal, Decimal, EvidenceLineage, EvidenceLineage]] = []
    with localcontext() as decimal_context:
        decimal_context.prec = 80
        for previous, current in zip(dates, dates[1:], strict=False):
            previous_bar = bars[previous]
            current_bar = bars[current]
            previous_benchmark = benchmark_by_date[previous]
            current_benchmark = benchmark_by_date[current]
            if previous_bar.bar.close <= 0 or previous_benchmark.point.reference_value <= 0:
                continue
            fund_return = current_bar.bar.close / previous_bar.bar.close - Decimal("1")
            benchmark_return = (
                current_benchmark.point.reference_value / previous_benchmark.point.reference_value
                - Decimal("1")
            )
            returns.append(
                (
                    fund_return,
                    benchmark_return,
                    current_bar.lineage,
                    current_benchmark.lineage,
                )
            )
    returns = returns[-policy.rolling_window_sessions :]
    if len(returns) < policy.minimum_samples:
        return FeatureReason.UNAVAILABLE_INSUFFICIENT_SAMPLES
    return tuple(returns)


def _tracking_result(
    context: PreciousMetalsFeatureInput,
    fund: PreciousMetalFund,
    spec: FeatureSpec,
    policy: PreciousMetalsPolicy,
    classification_lineage: EvidenceLineage,
    *,
    error: bool,
) -> FeatureResult:
    paired = _paired_returns(context, fund, policy)
    if isinstance(paired, FeatureReason):
        return _result(
            spec,
            context,
            paired,
            value=None,
            lineage=_failure_lineage(context, classification_lineage, paired),
        )
    differences = tuple(
        fund_return - benchmark_return for fund_return, benchmark_return, _, _ in paired
    )
    with localcontext() as decimal_context:
        decimal_context.prec = 80
        mean = sum(differences, Decimal("0")) / Decimal(len(differences))
        if error:
            squared = sum((item - mean) ** 2 for item in differences)
            value = squared / Decimal(len(differences) - 1)
            value = value.sqrt() * Decimal("10000")
        else:
            value = mean * Decimal("10000")
    lineages = _lineages(
        classification_lineage,
        (item[2] for item in paired),
        (item[3] for item in paired),
    )
    return _result(spec, context, FeatureReason.PUBLISHED, value=value, lineage=lineages)


def _liquidity_result(
    context: PreciousMetalsFeatureInput,
    fund: PreciousMetalFund,
    spec: FeatureSpec,
    policy: PreciousMetalsPolicy,
    classification_lineage: EvidenceLineage,
) -> FeatureResult:
    selection = _bars(context, fund)
    bars = tuple(item for item in _market_bars(selection) if item.bar.amount > Decimal("0"))
    bars = bars[-policy.rolling_window_sessions :]
    if selection.conflict:
        return _result(
            spec,
            context,
            FeatureReason.UNAVAILABLE_CONFLICTING_BAR_REVISION,
            value=None,
            lineage=_failure_lineage(
                context,
                classification_lineage,
                FeatureReason.UNAVAILABLE_CONFLICTING_BAR_REVISION,
            ),
        )
    if not bars and selection.has_future:
        return _result(
            spec,
            context,
            FeatureReason.UNAVAILABLE_FUTURE_BAR_REVISION,
            value=None,
            lineage=_failure_lineage(
                context,
                classification_lineage,
                FeatureReason.UNAVAILABLE_FUTURE_BAR_REVISION,
            ),
        )
    if len(bars) < policy.minimum_samples:
        return _result(
            spec,
            context,
            FeatureReason.UNAVAILABLE_INSUFFICIENT_SAMPLES,
            value=None,
            lineage=_failure_lineage(
                context,
                classification_lineage,
                FeatureReason.UNAVAILABLE_INSUFFICIENT_SAMPLES,
            ),
        )
    amounts = sorted(item.bar.amount for item in bars)
    middle = len(amounts) // 2
    with localcontext() as decimal_context:
        decimal_context.prec = 80
        if len(amounts) % 2:
            value = amounts[middle]
        else:
            value = (amounts[middle - 1] + amounts[middle]) / Decimal("2")
    return _result(
        spec,
        context,
        FeatureReason.PUBLISHED,
        value=value,
        lineage=_lineages(classification_lineage, (item.lineage for item in bars)),
    )


def _beta_result(
    context: PreciousMetalsFeatureInput,
    fund: PreciousMetalFund,
    spec: FeatureSpec,
    policy: PreciousMetalsPolicy,
    classification_lineage: EvidenceLineage,
) -> FeatureResult:
    paired = _paired_returns(context, fund, policy)
    if isinstance(paired, FeatureReason):
        return _result(
            spec,
            context,
            paired,
            value=None,
            lineage=_failure_lineage(context, classification_lineage, paired),
        )
    with localcontext() as decimal_context:
        decimal_context.prec = 80
        fund_mean = sum((item[0] for item in paired), Decimal("0")) / Decimal(len(paired))
        benchmark_mean = sum((item[1] for item in paired), Decimal("0")) / Decimal(len(paired))
        covariance_sum = sum(
            (fund_return - fund_mean) * (benchmark_return - benchmark_mean)
            for fund_return, benchmark_return, _, _ in paired
        )
        variance_sum = sum(
            (benchmark_return - benchmark_mean) ** 2 for _, benchmark_return, _, _ in paired
        )
        if variance_sum == Decimal("0"):
            return _result(
                spec,
                context,
                FeatureReason.UNAVAILABLE_ZERO_BENCHMARK_VARIANCE,
                value=None,
                lineage=_failure_lineage(
                    context,
                    classification_lineage,
                    FeatureReason.UNAVAILABLE_ZERO_BENCHMARK_VARIANCE,
                ),
            )
        value = Decimal(str(covariance_sum / variance_sum))
    return _result(
        spec,
        context,
        FeatureReason.PUBLISHED,
        value=value,
        lineage=_lineages(
            classification_lineage,
            (item[2] for item in paired),
            (item[3] for item in paired),
        ),
    )


def calculate_feature(
    feature: str | FeatureSpec,
    context: PreciousMetalsFeatureInput,
    policy: PreciousMetalsPolicy,
) -> FeatureResult:
    """Calculate exactly one feature from a canonical PIT input context."""
    if type(context) is not PreciousMetalsFeatureInput:
        raise TypeError("calculator requires PreciousMetalsFeatureInput")
    if type(policy) is not PreciousMetalsPolicy:
        raise TypeError("calculator requires PreciousMetalsPolicy")
    spec = _spec(feature if isinstance(feature, str) else feature.name)
    gate = _classification_gate(context, spec, policy)
    if gate.rejection is not None:
        return gate.rejection
    if spec.name == "precious_metals_fund.premium_discount_bps":
        return _premium_discount(context, gate.fund, spec, policy, gate.classification_lineage)
    if spec.name == "precious_metals_fund.tracking_difference_bps_20_sessions":
        return _tracking_result(
            context,
            gate.fund,
            spec,
            policy,
            gate.classification_lineage,
            error=False,
        )
    if spec.name == "precious_metals_fund.tracking_error_bps_20_sessions":
        return _tracking_result(
            context,
            gate.fund,
            spec,
            policy,
            gate.classification_lineage,
            error=True,
        )
    if spec.name == "precious_metals_fund.liquidity_median_turnover_cny_20_sessions":
        return _liquidity_result(
            context,
            gate.fund,
            spec,
            policy,
            gate.classification_lineage,
        )
    return _beta_result(context, gate.fund, spec, policy, gate.classification_lineage)


def calculate_features(
    context: PreciousMetalsFeatureInput,
    policy: PreciousMetalsPolicy,
) -> dict[str, FeatureResult]:
    """Calculate the complete v1 bundle using the same pure implementation."""
    return {
        spec.name: calculate_feature(spec, context, policy)
        for spec in precious_metals_feature_specs()
    }


__all__ = ["calculate_feature", "calculate_features"]
