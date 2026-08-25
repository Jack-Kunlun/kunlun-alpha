from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, getcontext, localcontext

from .models import (
    ClusteredMeanSummary,
    ClusteredObservation,
    ClusterInferenceStatus,
)


def mean(values: tuple[Decimal, ...]) -> Decimal:
    return sum(values, start=Decimal(0)) / Decimal(len(values))


def clustered_mean(
    observations: tuple[ClusteredObservation, ...],
) -> ClusteredMeanSummary:
    sample_count = len(observations)
    clusters = {observation.cluster_id for observation in observations}
    cluster_count = len(clusters)
    if sample_count == 0:
        return ClusteredMeanSummary(
            sample_count=0,
            cluster_count=0,
            mean=None,
            standard_error=None,
            degrees_of_freedom=None,
            finite_sample_correction=None,
            inference_status=ClusterInferenceStatus.NO_VALID_SAMPLES,
        )
    mean_value = mean(tuple(observation.value for observation in observations))
    if sample_count < 2:
        return ClusteredMeanSummary(
            sample_count=sample_count,
            cluster_count=cluster_count,
            mean=mean_value,
            standard_error=None,
            degrees_of_freedom=None,
            finite_sample_correction=None,
            inference_status=ClusterInferenceStatus.INSUFFICIENT_EVENT_SAMPLES,
        )
    if cluster_count < 2:
        return ClusteredMeanSummary(
            sample_count=sample_count,
            cluster_count=cluster_count,
            mean=mean_value,
            standard_error=None,
            degrees_of_freedom=None,
            finite_sample_correction=None,
            inference_status=ClusterInferenceStatus.INSUFFICIENT_CLUSTERS,
        )
    residual_sums: dict[str, Decimal] = defaultdict(Decimal)
    for observation in observations:
        residual_sums[observation.cluster_id] += observation.value - mean_value
    correction = Decimal(cluster_count) / Decimal(cluster_count - 1)
    variance = (
        correction
        * sum(
            (residual_sum * residual_sum for residual_sum in residual_sums.values()),
            start=Decimal(0),
        )
        / Decimal(sample_count * sample_count)
    )
    if variance == 0:
        standard_error = Decimal(0)
        inference_status = ClusterInferenceStatus.ZERO_CLUSTER_VARIATION
    else:
        with localcontext() as context:
            context.prec = max(getcontext().prec, 50)
            high_precision_error = variance.sqrt()
        standard_error = +high_precision_error
        inference_status = (
            ClusterInferenceStatus.SMALL_CLUSTER_COUNT
            if cluster_count < 30
            else ClusterInferenceStatus.OK
        )
    return ClusteredMeanSummary(
        sample_count=sample_count,
        cluster_count=cluster_count,
        mean=mean_value,
        standard_error=standard_error,
        degrees_of_freedom=cluster_count - 1,
        finite_sample_correction=correction,
        inference_status=inference_status,
    )
