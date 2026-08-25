from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .models import (
    FACTOR_RESEARCH_ALGORITHM_VERSION,
    ChartPoint,
    CorrelationPoint,
    CorrelationStatus,
    DecayResult,
    FactorCorrelationResult,
    FactorFutureDataError,
    FactorObservation,
    FactorResearchInputError,
    FactorResearchResult,
    FactorResearchStatus,
    SampleDropReason,
    StratumPeriodReturn,
    StratumResult,
    TurnoverPolicy,
    TurnoverResult,
    WinsorizationPolicy,
)
from .statistics import average_ranks, mean, pearson, spearman, summarize, winsorize


@dataclass(frozen=True, slots=True)
class _Pair:
    entity_id: str
    decision_time: datetime
    horizon_sessions: int
    factor_value: Decimal
    forward_return: Decimal


def _identity(observations: Sequence[FactorObservation]) -> tuple[str, str]:
    identities = {observation.factor_identity for observation in observations}
    if len(identities) != 1:
        raise FactorResearchInputError("observations must contain one factor identity")
    sample_keys = {
        (observation.decision_time, observation.entity_id) for observation in observations
    }
    if len(sample_keys) != len(observations):
        raise FactorResearchInputError(
            "factor observations must be unique by decision_time and entity_id"
        )
    return next(iter(identities))


def _validate_cutoff(
    observations: Sequence[FactorObservation],
    data_cutoff_time: datetime,
) -> None:
    if any(observation.decision_time > data_cutoff_time for observation in observations):
        raise FactorFutureDataError("factor decision_time exceeds data_cutoff_time")


def _prepare_pairs(
    observations: Sequence[FactorObservation],
    data_cutoff_time: datetime,
) -> tuple[tuple[_Pair, ...], dict[SampleDropReason, int]]:
    drops = {reason: 0 for reason in SampleDropReason}
    pairs: list[_Pair] = []
    for observation in observations:
        for outcome in observation.forward_returns:
            if observation.factor_value is None:
                drops[SampleDropReason.MISSING_FACTOR] += 1
            elif outcome.value is None:
                drops[SampleDropReason.MISSING_RETURN] += 1
            elif outcome.available_time > data_cutoff_time:
                drops[SampleDropReason.OUTCOME_NOT_AVAILABLE] += 1
            else:
                pairs.append(
                    _Pair(
                        entity_id=observation.entity_id,
                        decision_time=observation.decision_time,
                        horizon_sessions=outcome.horizon_sessions,
                        factor_value=observation.factor_value,
                        forward_return=outcome.value,
                    )
                )
    return tuple(pairs), drops


def _correlation_point(
    decision_time: datetime,
    horizon_sessions: int,
    pairs: Sequence[_Pair],
    policy: WinsorizationPolicy | None,
) -> CorrelationPoint:
    factor_values = winsorize(tuple(pair.factor_value for pair in pairs), policy)
    returns = tuple(pair.forward_return for pair in pairs)
    if len(pairs) < 3:
        status = CorrelationStatus.INSUFFICIENT_SAMPLE
        ic = None
        rank_ic = None
    else:
        ic = pearson(factor_values, returns)
        rank_ic = spearman(factor_values, returns)
        status = (
            CorrelationStatus.OK
            if ic is not None and rank_ic is not None
            else CorrelationStatus.CONSTANT_INPUT
        )
    return CorrelationPoint(
        decision_time=decision_time,
        horizon_sessions=horizon_sessions,
        sample_count=len(pairs),
        status=status,
        ic=ic,
        rank_ic=rank_ic,
    )


def _points(
    pairs: Sequence[_Pair],
    policy: WinsorizationPolicy | None,
) -> tuple[CorrelationPoint, ...]:
    grouped: dict[tuple[int, datetime], list[_Pair]] = defaultdict(list)
    for pair in pairs:
        grouped[(pair.horizon_sessions, pair.decision_time)].append(pair)
    return tuple(
        _correlation_point(decision_time, horizon, grouped[(horizon, decision_time)], policy)
        for horizon, decision_time in sorted(grouped)
    )


def _decay(
    pairs: Sequence[_Pair],
    points: Sequence[CorrelationPoint],
) -> tuple[DecayResult, ...]:
    horizons = sorted({pair.horizon_sessions for pair in pairs})
    return tuple(
        DecayResult(
            horizon_sessions=horizon,
            valid_pair_count=sum(pair.horizon_sessions == horizon for pair in pairs),
            period_count=sum(
                point.horizon_sessions == horizon and point.status is CorrelationStatus.OK
                for point in points
            ),
            ic=summarize(
                tuple(
                    point.ic
                    for point in points
                    if point.horizon_sessions == horizon and point.ic is not None
                )
            ),
            rank_ic=summarize(
                tuple(
                    point.rank_ic
                    for point in points
                    if point.horizon_sessions == horizon and point.rank_ic is not None
                )
            ),
        )
        for horizon in horizons
    )


def _strata_and_turnover(
    pairs: Sequence[_Pair],
    primary_horizon: int,
    bucket_count: int,
    policy: WinsorizationPolicy | None,
    turnover_policy: TurnoverPolicy | None,
) -> tuple[tuple[StratumResult, ...], tuple[TurnoverResult, ...]]:
    by_time: dict[datetime, list[_Pair]] = defaultdict(list)
    for pair in pairs:
        if pair.horizon_sessions == primary_horizon:
            by_time[pair.decision_time].append(pair)
    period_returns: dict[int, list[StratumPeriodReturn]] = defaultdict(list)
    memberships: dict[int, list[tuple[datetime, set[str] | None]]] = defaultdict(list)
    for decision_time in sorted(by_time):
        period_pairs = sorted(by_time[decision_time], key=lambda pair: pair.entity_id)
        factor_values = winsorize(tuple(pair.factor_value for pair in period_pairs), policy)
        if len(set(factor_values)) <= 1:
            for bucket in range(bucket_count):
                memberships[bucket].append((decision_time, None))
            continue
        ranks = average_ranks(factor_values)
        entities: dict[int, set[str]] = defaultdict(set)
        bucket_returns: dict[int, list[Decimal]] = defaultdict(list)
        for pair, rank in zip(period_pairs, ranks, strict=True):
            bucket = min(
                bucket_count - 1,
                int(((rank - Decimal(1)) * Decimal(bucket_count)) / Decimal(len(period_pairs))),
            )
            bucket_returns[bucket].append(pair.forward_return)
            entities[bucket].add(pair.entity_id)
        for bucket in range(bucket_count):
            entity_ids = entities.get(bucket, set())
            memberships[bucket].append((decision_time, entity_ids))
            values = bucket_returns.get(bucket, [])
            if values:
                period_returns[bucket].append(
                    StratumPeriodReturn(
                        decision_time=decision_time,
                        stratum=bucket,
                        constituent_count=len(values),
                        entity_ids=tuple(sorted(entity_ids)),
                        return_value=mean(values),
                    )
                )
    strata = tuple(
        StratumResult(
            stratum=bucket,
            sample_count=sum(point.constituent_count for point in period_returns[bucket]),
            period_count=len(period_returns[bucket]),
            return_summary=summarize(tuple(point.return_value for point in period_returns[bucket])),
            period_returns=tuple(period_returns[bucket]),
        )
        for bucket in range(bucket_count)
    )
    turnover: list[TurnoverResult] = []
    for bucket in range(bucket_count):
        values: list[Decimal] = []
        excluded = 0
        ordered = memberships[bucket]
        for (prior_time, prior), (current_time, current) in zip(ordered, ordered[1:], strict=False):
            if (
                turnover_policy is None
                or not turnover_policy.is_adjacent(prior_time, current_time)
                or prior is None
                or current is None
                or (not prior and not current)
            ):
                excluded += 1
                continue
            union = prior | current
            values.append(Decimal(1) - Decimal(len(prior & current)) / Decimal(len(union)))
        turnover.append(
            TurnoverResult(
                stratum=bucket,
                transition_count=len(values),
                excluded_transition_count=excluded,
                turnover_summary=summarize(tuple(values)),
            )
        )
    return strata, tuple(turnover)


def _chart_data(
    points: Iterable[CorrelationPoint],
    strata: Iterable[StratumResult],
) -> tuple[ChartPoint, ...]:
    result: list[ChartPoint] = []
    for point in points:
        x = f"{point.decision_time.isoformat()}|{point.horizon_sessions}"
        if point.ic is not None:
            result.append(ChartPoint("ic", x, point.ic, point.sample_count))
        if point.rank_ic is not None:
            result.append(ChartPoint("rank_ic", x, point.rank_ic, point.sample_count))
    for stratum in strata:
        for period_return in stratum.period_returns:
            result.append(
                ChartPoint(
                    "stratum_return",
                    f"{period_return.decision_time.isoformat()}|{stratum.stratum}",
                    period_return.return_value,
                    period_return.constituent_count,
                )
            )
    return tuple(result)


def analyze_factor(
    observations: Sequence[FactorObservation],
    *,
    data_cutoff_time: datetime,
    bucket_count: int = 5,
    winsorization: WinsorizationPolicy | None = None,
    turnover_policy: TurnoverPolicy | None = None,
) -> FactorResearchResult:
    if data_cutoff_time.tzinfo is None:
        raise FactorResearchInputError("data_cutoff_time must be timezone-aware")
    if not observations:
        raise FactorResearchInputError("factor research requires observations")
    if type(bucket_count) is not int or not 2 <= bucket_count <= 20:
        raise FactorResearchInputError("bucket_count must be between 2 and 20")
    _validate_cutoff(observations, data_cutoff_time)
    factor_name, factor_version = _identity(observations)
    pairs, drops = _prepare_pairs(observations, data_cutoff_time)
    points = _points(pairs, winsorization)
    decay = _decay(pairs, points)
    primary_horizon = min((pair.horizon_sessions for pair in pairs), default=None)
    primary_points = tuple(
        point
        for point in points
        if point.horizon_sessions == primary_horizon and point.status is CorrelationStatus.OK
    )
    ic = summarize(tuple(point.ic for point in primary_points if point.ic is not None))
    rank_ic = summarize(
        tuple(point.rank_ic for point in primary_points if point.rank_ic is not None)
    )
    if not pairs:
        status = FactorResearchStatus.NO_VALID_SAMPLES
    elif primary_points:
        status = FactorResearchStatus.OK
    elif any(point.status is CorrelationStatus.CONSTANT_INPUT for point in points):
        status = FactorResearchStatus.CONSTANT_INPUT
    else:
        status = FactorResearchStatus.INSUFFICIENT_SAMPLE
    if primary_horizon is None:
        strata: tuple[StratumResult, ...] = ()
        turnover: tuple[TurnoverResult, ...] = ()
    else:
        strata, turnover = _strata_and_turnover(
            pairs,
            primary_horizon,
            bucket_count,
            winsorization,
            turnover_policy,
        )
        if status is FactorResearchStatus.CONSTANT_INPUT:
            strata = ()
            turnover = ()
    return FactorResearchResult(
        factor_name=factor_name,
        factor_version=factor_version,
        algorithm_version=FACTOR_RESEARCH_ALGORITHM_VERSION,
        data_cutoff_time=data_cutoff_time,
        status=status,
        input_observation_count=len(observations),
        valid_pair_count=len(pairs),
        primary_valid_pair_count=sum(pair.horizon_sessions == primary_horizon for pair in pairs),
        valid_period_count=len(primary_points),
        primary_horizon_sessions=primary_horizon,
        ic=ic,
        rank_ic=rank_ic,
        correlation_points=points,
        decay=decay,
        strata=strata,
        turnover=turnover,
        turnover_policy=turnover_policy,
        drop_counts=tuple((reason, drops[reason]) for reason in SampleDropReason),
        winsorization=winsorization,
        chart_data=_chart_data(points, strata),
    )


def analyze_factor_correlation(
    left: Sequence[FactorObservation],
    right: Sequence[FactorObservation],
    *,
    data_cutoff_time: datetime,
    winsorization: WinsorizationPolicy | None = None,
) -> FactorCorrelationResult:
    if data_cutoff_time.tzinfo is None:
        raise FactorResearchInputError("data_cutoff_time must be timezone-aware")
    if not left or not right:
        raise FactorResearchInputError("factor correlation requires both factor series")
    _validate_cutoff(left, data_cutoff_time)
    _validate_cutoff(right, data_cutoff_time)
    left_name, left_version = _identity(left)
    right_name, right_version = _identity(right)
    if (left_name, left_version) == (right_name, right_version):
        raise FactorResearchInputError("factor correlation requires distinct identities")
    left_values = {
        (item.decision_time, item.entity_id): item.factor_value
        for item in left
        if item.factor_value is not None and item.factor_available_time <= data_cutoff_time
    }
    right_values = {
        (item.decision_time, item.entity_id): item.factor_value
        for item in right
        if item.factor_value is not None and item.factor_available_time <= data_cutoff_time
    }
    common = sorted(left_values.keys() & right_values.keys())
    grouped: dict[datetime, list[tuple[Decimal, Decimal]]] = defaultdict(list)
    for decision_time, entity_id in common:
        grouped[decision_time].append(
            (left_values[(decision_time, entity_id)], right_values[(decision_time, entity_id)])
        )
    points: list[CorrelationPoint] = []
    for decision_time in sorted(grouped):
        pairs = grouped[decision_time]
        left_period = winsorize(tuple(pair[0] for pair in pairs), winsorization)
        right_period = winsorize(tuple(pair[1] for pair in pairs), winsorization)
        value = pearson(left_period, right_period)
        rank_value = spearman(left_period, right_period)
        if len(pairs) < 3:
            status = CorrelationStatus.INSUFFICIENT_SAMPLE
        elif value is None or rank_value is None:
            status = CorrelationStatus.CONSTANT_INPUT
        else:
            status = CorrelationStatus.OK
        points.append(
            CorrelationPoint(
                decision_time=decision_time,
                horizon_sessions=0,
                sample_count=len(pairs),
                status=status,
                ic=value,
                rank_ic=rank_value,
            )
        )
    valid = tuple(point for point in points if point.status is CorrelationStatus.OK)
    return FactorCorrelationResult(
        left_factor_name=left_name,
        left_factor_version=left_version,
        right_factor_name=right_name,
        right_factor_version=right_version,
        algorithm_version=FACTOR_RESEARCH_ALGORITHM_VERSION,
        data_cutoff_time=data_cutoff_time,
        aligned_sample_count=len(common),
        valid_period_count=len(valid),
        correlation=summarize(tuple(point.ic for point in valid if point.ic is not None)),
        rank_correlation=summarize(
            tuple(point.rank_ic for point in valid if point.rank_ic is not None)
        ),
        points=tuple(points),
        chart_data=tuple(
            chart_point
            for point in valid
            for chart_point in (
                ChartPoint(
                    "factor_correlation",
                    point.decision_time.isoformat(),
                    point.ic,
                    point.sample_count,
                )
                if point.ic is not None
                else None,
                ChartPoint(
                    "factor_rank_correlation",
                    point.decision_time.isoformat(),
                    point.rank_ic,
                    point.sample_count,
                )
                if point.rank_ic is not None
                else None,
            )
            if chart_point is not None
        ),
    )
