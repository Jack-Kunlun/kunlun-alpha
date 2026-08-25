from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal

from .models import (
    InferenceAssumption,
    MetricSummary,
    SignTestResult,
    WinsorizationPolicy,
)

MIN_CORRELATION_SAMPLE = 3


def mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / Decimal(len(values))


def median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _quantile(values: Sequence[Decimal], quantile: Decimal) -> Decimal:
    ordered = sorted(values)
    position = Decimal(len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def winsorize(
    values: tuple[Decimal, ...],
    policy: WinsorizationPolicy | None,
) -> tuple[Decimal, ...]:
    if policy is None or not values:
        return values
    lower = _quantile(values, policy.lower_quantile)
    upper = _quantile(values, policy.upper_quantile)
    return tuple(min(max(value, lower), upper) for value in values)


def pearson(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal | None:
    if len(left) != len(right) or len(left) < MIN_CORRELATION_SAMPLE:
        return None
    left_mean = mean(left)
    right_mean = mean(right)
    left_centered = tuple(value - left_mean for value in left)
    right_centered = tuple(value - right_mean for value in right)
    left_ss = sum((value * value for value in left_centered), Decimal(0))
    right_ss = sum((value * value for value in right_centered), Decimal(0))
    if left_ss == 0 or right_ss == 0:
        return None
    covariance = sum(
        (x_value * y_value for x_value, y_value in zip(left_centered, right_centered, strict=True)),
        Decimal(0),
    )
    result = covariance / (left_ss * right_ss).sqrt()
    return min(max(result, Decimal(-1)), Decimal(1))


def average_ranks(values: Sequence[Decimal]) -> tuple[Decimal, ...]:
    indexed = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [Decimal(0)] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        average = (Decimal(start + 1) + Decimal(end)) / Decimal(2)
        for index, _ in indexed[start:end]:
            ranks[index] = average
        start = end
    return tuple(ranks)


def spearman(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal | None:
    if len(left) != len(right):
        return None
    return pearson(average_ranks(left), average_ranks(right))


def summarize(values: Sequence[Decimal]) -> MetricSummary:
    sample_count = len(values)
    if sample_count:
        result_mean = mean(values)
        result_median = median(values)
    else:
        result_mean = None
        result_median = None
    standard_error: Decimal | None = None
    if sample_count >= 2 and result_mean is not None:
        variance = sum(
            ((value - result_mean) ** 2 for value in values),
            Decimal(0),
        ) / Decimal(sample_count - 1)
        standard_error = (variance / Decimal(sample_count)).sqrt()
    positive = sum(value > 0 for value in values)
    negative = sum(value < 0 for value in values)
    zero = sample_count - positive - negative
    nonzero = positive + negative
    p_value: Decimal | None = None
    if nonzero:
        tail = min(positive, negative)
        numerator = sum(math.comb(nonzero, index) for index in range(tail + 1)) * 2
        p_value = min(Decimal(1), Decimal(numerator) / Decimal(2**nonzero))
    return MetricSummary(
        sample_count=sample_count,
        mean=result_mean,
        median=result_median,
        standard_error=standard_error,
        sign_test=SignTestResult(
            positive_count=positive,
            negative_count=negative,
            zero_count=zero,
            two_sided_p_value=p_value,
        ),
        inference_assumption=InferenceAssumption.IID_DESCRIPTIVE_UNADJUSTED,
    )
