"""Versioned KOL attention, consensus, and Claim score features."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from kol_core import ClaimDirection, KolClaim, ReviewStatus
from kol_core.performance import (
    ClaimPerformancePolicy,
    ClaimPerformanceResult,
    ClaimPerformanceSample,
    ClaimPerformanceStatus,
    TradablePriceObservation,
    TradingCalendarSnapshot,
    compute_claim_performance,
    select_active_claims,
)

KOL_FEATURE_SCHEMA_VERSION = "kol-feature-value-v1"
KOL_FEATURE_ALGORITHM_VERSION = "kol-feature-algorithm-v1"
KOL_FEATURE_POLICY_VERSION = "kol-feature-policy-v1"


def _aware(value: datetime, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _integer_bps(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_HALF_EVEN))


def _duration_micros(value: timedelta) -> int:
    return ((value.days * 86_400 + value.seconds) * 1_000_000) + value.microseconds


class KolFeatureName(StrEnum):
    KOL_ATTENTION_SCORE = "kol_attention_score"
    CONSENSUS_SCORE = "consensus_score"
    CLAIM_SCORE = "claim_score"


class FeatureStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    INSUFFICIENT_SAMPLES = "INSUFFICIENT_SAMPLES"
    NO_SAMPLES = "NO_SAMPLES"


class KolFeatureInputError(ValueError):
    """Fail-closed error for ambiguous feature aggregation inputs."""


@dataclass(frozen=True, slots=True)
class ClaimRevisionReference:
    source: str
    claim_id: str
    revision_id: str
    content_id: str
    content_version: str
    kol_id: str
    instrument_id: str
    direction: ClaimDirection
    confidence_bps: int
    review_status: ReviewStatus
    publish_time: datetime
    available_time: datetime
    statement_fingerprint: str
    active_at_decision: bool
    withdrawn_at: datetime | None
    evidence_revision_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PriceRevisionReference:
    source: str
    source_version: str
    data_version: str
    raw_capture_id: str
    revision_id: str
    replacement_version: int
    instrument_id: str
    trade_date: date
    event_time: datetime
    available_time: datetime
    price: Decimal
    suspended: bool


@dataclass(frozen=True, slots=True)
class KolFeaturePolicy:
    attention_lookback_days: int = 30
    attention_saturation: Decimal = Decimal("5")
    minimum_consensus_kols: int = 2
    high_grade_confidence_bps: int = 7000
    performance_policy: ClaimPerformancePolicy = field(default_factory=ClaimPerformancePolicy)
    algorithm_version: str = KOL_FEATURE_ALGORITHM_VERSION
    policy_version: str = KOL_FEATURE_POLICY_VERSION

    def __post_init__(self) -> None:
        if type(self.attention_lookback_days) is not int or self.attention_lookback_days < 1:
            raise ValueError("attention_lookback_days must be a positive integer")
        if (
            type(self.attention_saturation) is not Decimal
            or not self.attention_saturation.is_finite()
            or self.attention_saturation <= 0
        ):
            raise ValueError("attention_saturation must be a positive Decimal")
        if type(self.minimum_consensus_kols) is not int or self.minimum_consensus_kols < 1:
            raise ValueError("minimum_consensus_kols must be a positive integer")
        if (
            type(self.high_grade_confidence_bps) is not int
            or not 0 <= self.high_grade_confidence_bps <= 10_000
        ):
            raise ValueError("high_grade_confidence_bps must be in [0, 10000]")
        if type(self.performance_policy) is not ClaimPerformancePolicy:
            raise TypeError("performance_policy must be ClaimPerformancePolicy")
        if not self.algorithm_version or not self.policy_version:
            raise ValueError("feature versions must be non-empty")

    @property
    def fingerprint(self) -> str:
        payload = {
            "algorithmVersion": self.algorithm_version,
            "attentionLookbackDays": self.attention_lookback_days,
            "attentionSaturation": format(self.attention_saturation, "f"),
            "highGradeConfidenceBps": self.high_grade_confidence_bps,
            "minimumConsensusKols": self.minimum_consensus_kols,
            "performancePolicyFingerprint": self.performance_policy.fingerprint,
            "policyVersion": self.policy_version,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


_DEFAULT_KOL_FEATURE_POLICY = KolFeaturePolicy()


@dataclass(frozen=True, slots=True)
class KolFeatureValue:
    schema_version: str
    feature_name: KolFeatureName
    entity_id: str
    value_bps: int | None
    status: FeatureStatus
    sample_count: int
    decision_time: datetime
    data_cutoff_time: datetime | None
    input_claims: tuple[ClaimRevisionReference, ...]
    input_prices: tuple[PriceRevisionReference, ...]
    input_calendars: tuple[TradingCalendarSnapshot, ...]
    input_fingerprint: str
    high_grade: bool
    algorithm_version: str
    policy_version: str
    policy_fingerprint: str


@dataclass(frozen=True, slots=True)
class KolFeatureBundle:
    decision_time: datetime
    features: tuple[KolFeatureValue, ...]
    performance: ClaimPerformanceResult
    data_cutoff_time: datetime | None
    algorithm_version: str
    policy_version: str
    policy_fingerprint: str


def _statement_fingerprint(claim: KolClaim) -> str:
    payload = {
        "attribution": claim.attribution.value,
        "confidenceBps": claim.confidence_bps,
        "direction": claim.direction.value,
        "instrumentId": claim.instrument_id,
        "statement": claim.statement,
        "statementKind": claim.statement_kind.value,
        "uncertainty": claim.uncertainty.value,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(encoded.encode()).hexdigest()}"


def _claim_reference(claim: KolClaim) -> ClaimRevisionReference:
    return ClaimRevisionReference(
        source=claim.source,
        claim_id=claim.claim_id,
        revision_id=claim.revision_id,
        content_id=claim.content_id,
        content_version=claim.content_version,
        kol_id=claim.kol_id,
        instrument_id=claim.instrument_id,
        direction=claim.direction,
        confidence_bps=claim.confidence_bps,
        review_status=claim.review_status,
        publish_time=claim.publish_time,
        available_time=claim.available_time,
        statement_fingerprint=_statement_fingerprint(claim),
        active_at_decision=True,
        withdrawn_at=None,
        evidence_revision_ids=tuple(sorted(item.evidence_revision_id for item in claim.evidence)),
    )


def _sample_claim_reference(sample: ClaimPerformanceSample) -> ClaimRevisionReference:
    return ClaimRevisionReference(
        source=sample.source,
        claim_id=sample.claim_id,
        revision_id=sample.claim_revision_id,
        content_id=sample.content_id,
        content_version=sample.content_version,
        kol_id=sample.kol_id,
        instrument_id=sample.instrument_id,
        direction=sample.direction,
        confidence_bps=sample.confidence_bps,
        review_status=sample.review_status,
        publish_time=sample.publish_time,
        available_time=sample.claim_available_time,
        statement_fingerprint=sample.statement_fingerprint,
        active_at_decision=sample.active_at_decision,
        withdrawn_at=sample.withdrawn_at,
        evidence_revision_ids=sample.evidence_revision_ids,
    )


def _price_reference(observation: TradablePriceObservation) -> PriceRevisionReference:
    return PriceRevisionReference(
        source=observation.source,
        source_version=observation.source_version,
        data_version=observation.data_version,
        raw_capture_id=observation.raw_capture_id,
        revision_id=observation.revision_id,
        replacement_version=observation.replacement_version,
        instrument_id=observation.instrument_id,
        trade_date=observation.trade_date,
        event_time=observation.event_time,
        available_time=observation.available_time,
        price=observation.price,
        suspended=observation.suspended,
    )


def _claim_sort_key(reference: ClaimRevisionReference) -> tuple[str, str, str]:
    return (reference.source, reference.claim_id, reference.revision_id)


def _price_sort_key(reference: PriceRevisionReference) -> tuple[datetime, str, str]:
    return (reference.event_time, reference.source, reference.revision_id)


def _calendar_sort_key(
    snapshot: TradingCalendarSnapshot,
) -> tuple[str, str, int, str]:
    return (
        snapshot.market,
        snapshot.source,
        snapshot.replacement_version,
        snapshot.snapshot_id,
    )


def _input_fingerprint(
    claims: tuple[ClaimRevisionReference, ...],
    prices: tuple[PriceRevisionReference, ...],
    calendars: tuple[TradingCalendarSnapshot, ...],
) -> str:
    payload = {
        "calendars": [
            {
                "fingerprint": item.fingerprint,
                "market": item.market,
                "replacementVersion": item.replacement_version,
                "snapshotId": item.snapshot_id,
                "source": item.source,
                "sourceVersion": item.source_version,
            }
            for item in calendars
        ],
        "claims": [
            {
                "activeAtDecision": item.active_at_decision,
                "availableTime": item.available_time.isoformat(),
                "claimId": item.claim_id,
                "confidenceBps": item.confidence_bps,
                "contentId": item.content_id,
                "contentVersion": item.content_version,
                "direction": item.direction.value,
                "evidenceRevisionIds": list(item.evidence_revision_ids),
                "instrumentId": item.instrument_id,
                "kolId": item.kol_id,
                "publishTime": item.publish_time.isoformat(),
                "reviewStatus": item.review_status.value,
                "revisionId": item.revision_id,
                "source": item.source,
                "statementFingerprint": item.statement_fingerprint,
                "withdrawnAt": (
                    item.withdrawn_at.isoformat() if item.withdrawn_at is not None else None
                ),
            }
            for item in claims
        ],
        "prices": [
            {
                "availableTime": item.available_time.isoformat(),
                "dataVersion": item.data_version,
                "eventTime": item.event_time.isoformat(),
                "instrumentId": item.instrument_id,
                "price": format(item.price, "f"),
                "rawCaptureId": item.raw_capture_id,
                "replacementVersion": item.replacement_version,
                "revisionId": item.revision_id,
                "source": item.source,
                "sourceVersion": item.source_version,
                "suspended": item.suspended,
                "tradeDate": item.trade_date.isoformat(),
            }
            for item in prices
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _feature(
    policy: KolFeaturePolicy,
    decision_time: datetime,
    *,
    name: KolFeatureName,
    entity_id: str,
    value_bps: int | None,
    status: FeatureStatus,
    sample_count: int,
    cutoff: datetime | None,
    claims: tuple[ClaimRevisionReference, ...],
    prices: tuple[PriceRevisionReference, ...] = (),
    calendars: tuple[TradingCalendarSnapshot, ...] = (),
    high_grade: bool,
) -> KolFeatureValue:
    ordered_claims = tuple(sorted(claims, key=_claim_sort_key))
    ordered_prices = tuple(sorted(prices, key=_price_sort_key))
    ordered_calendars = tuple(sorted(calendars, key=_calendar_sort_key))
    return KolFeatureValue(
        schema_version=KOL_FEATURE_SCHEMA_VERSION,
        feature_name=name,
        entity_id=entity_id,
        value_bps=value_bps,
        status=status,
        sample_count=sample_count,
        decision_time=decision_time,
        data_cutoff_time=cutoff,
        input_claims=ordered_claims,
        input_prices=ordered_prices,
        input_calendars=ordered_calendars,
        input_fingerprint=_input_fingerprint(
            ordered_claims,
            ordered_prices,
            ordered_calendars,
        ),
        high_grade=high_grade,
        algorithm_version=policy.algorithm_version,
        policy_version=policy.policy_version,
        policy_fingerprint=policy.fingerprint,
    )


def _attention_features(
    active_claims: tuple[KolClaim, ...],
    decision_time: datetime,
    policy: KolFeaturePolicy,
) -> list[KolFeatureValue]:
    window = timedelta(days=policy.attention_lookback_days)
    window_start = decision_time - window
    window_micros = Decimal(_duration_micros(window))
    grouped: dict[str, list[KolClaim]] = {}
    for claim in active_claims:
        if claim.review_status is ReviewStatus.APPROVED and claim.available_time >= window_start:
            grouped.setdefault(claim.kol_id, []).append(claim)

    features: list[KolFeatureValue] = []
    for kol_id, claims in sorted(grouped.items()):
        weighted_count = Decimal("0")
        for claim in claims:
            age = decision_time - claim.available_time
            recency = Decimal(_duration_micros(window - age)) / window_micros
            weighted_count += (Decimal(claim.confidence_bps) / Decimal("10000")) * recency
        value = min(
            Decimal("10000"),
            weighted_count / policy.attention_saturation * Decimal("10000"),
        )
        features.append(
            _feature(
                policy,
                decision_time,
                name=KolFeatureName.KOL_ATTENTION_SCORE,
                entity_id=kol_id,
                value_bps=_integer_bps(value),
                status=FeatureStatus.PUBLISHED,
                sample_count=len(claims),
                cutoff=max(item.available_time for item in claims),
                claims=tuple(_claim_reference(item) for item in claims),
                high_grade=False,
            )
        )
    return features


def _consensus_features(
    active_claims: tuple[KolClaim, ...],
    decision_time: datetime,
    policy: KolFeaturePolicy,
) -> list[KolFeatureValue]:
    latest_by_kol: dict[tuple[str, str], KolClaim] = {}
    for claim in active_claims:
        if (
            claim.review_status is not ReviewStatus.APPROVED
            or claim.confidence_bps < policy.high_grade_confidence_bps
        ):
            continue
        key = (claim.instrument_id, claim.kol_id)
        current = latest_by_kol.get(key)
        if current is not None and claim.available_time == current.available_time:
            raise KolFeatureInputError(
                "simultaneous Claims for one KOL and instrument are ambiguous"
            )
        if current is None or claim.available_time > current.available_time:
            latest_by_kol[key] = claim
    grouped: dict[str, list[KolClaim]] = {}
    for (instrument_id, _), claim in latest_by_kol.items():
        grouped.setdefault(instrument_id, []).append(claim)

    features: list[KolFeatureValue] = []
    for instrument_id, claims in sorted(grouped.items()):
        claims.sort(key=lambda item: (item.kol_id, item.revision_id))
        numerator = Decimal("0")
        denominator = Decimal("0")
        for claim in claims:
            weight = Decimal(claim.confidence_bps)
            denominator += weight
            if claim.direction is ClaimDirection.BULLISH:
                numerator += weight
            elif claim.direction is ClaimDirection.BEARISH:
                numerator -= weight
        sufficient = len(claims) >= policy.minimum_consensus_kols and denominator > 0
        value = None if not sufficient else _integer_bps(numerator / denominator * Decimal("10000"))
        features.append(
            _feature(
                policy,
                decision_time,
                name=KolFeatureName.CONSENSUS_SCORE,
                entity_id=instrument_id,
                value_bps=value,
                status=(
                    FeatureStatus.PUBLISHED if sufficient else FeatureStatus.INSUFFICIENT_SAMPLES
                ),
                sample_count=len(claims),
                cutoff=max(item.available_time for item in claims),
                claims=tuple(_claim_reference(item) for item in claims),
                high_grade=sufficient,
            )
        )
    return features


def _claim_score_features(
    performance: ClaimPerformanceResult,
    policy: KolFeaturePolicy,
) -> list[KolFeatureValue]:
    features: list[KolFeatureValue] = []
    calendars_by_market = {item.market: item for item in performance.calendar_snapshots}
    for sample in performance.samples:
        mature = sample.status is ClaimPerformanceStatus.MATURE
        value: int | None = None
        if mature:
            average_signed_return = sum(
                (item.signed_return for item in sample.horizon_returns),
                start=Decimal("0"),
            ) / Decimal(len(sample.horizon_returns))
            capped = max(
                -policy.performance_policy.return_cap,
                min(policy.performance_policy.return_cap, average_signed_return),
            )
            outcome_bps = Decimal("5000") + (
                capped / policy.performance_policy.return_cap * Decimal("5000")
            )
            value = _integer_bps((Decimal(sample.confidence_bps) + outcome_bps) / Decimal("2"))
        entity_id = f"{sample.source}:{sample.claim_id}:{sample.claim_revision_id}"
        input_calendars: tuple[TradingCalendarSnapshot, ...] = ()
        if sample.calendar_snapshot_id is not None:
            market = sample.instrument_id.rsplit(".", maxsplit=1)[1]
            calendar = calendars_by_market.get(market)
            if calendar is None or calendar.snapshot_id != sample.calendar_snapshot_id:
                raise KolFeatureInputError("performance calendar provenance is incomplete")
            input_calendars = (calendar,)
        features.append(
            _feature(
                policy,
                performance.decision_time,
                name=KolFeatureName.CLAIM_SCORE,
                entity_id=entity_id,
                value_bps=value,
                status=(
                    FeatureStatus.PUBLISHED
                    if mature
                    else FeatureStatus.INSUFFICIENT_SAMPLES
                    if sample.status is ClaimPerformanceStatus.PENDING
                    else FeatureStatus.NO_SAMPLES
                ),
                sample_count=len(sample.horizon_returns),
                cutoff=sample.logical_available_time,
                claims=(_sample_claim_reference(sample),),
                prices=tuple(_price_reference(item) for item in sample.observed_price_path),
                calendars=input_calendars,
                high_grade=(
                    mature
                    and sample.confidence_bps >= policy.high_grade_confidence_bps
                    and sample.review_status is ReviewStatus.APPROVED
                ),
            )
        )
    return features


def compute_kol_features(
    claims: Iterable[KolClaim],
    prices: Iterable[TradablePriceObservation],
    trading_calendars: Iterable[TradingCalendarSnapshot],
    decision_time: datetime,
    policy: KolFeaturePolicy = _DEFAULT_KOL_FEATURE_POLICY,
) -> KolFeatureBundle:
    decision = _aware(decision_time, "decision_time")
    if type(policy) is not KolFeaturePolicy:
        raise TypeError("policy must be KolFeaturePolicy")
    claim_values = tuple(claims)
    price_values = tuple(prices)
    calendar_values = tuple(trading_calendars)
    performance = compute_claim_performance(
        claim_values,
        price_values,
        calendar_values,
        decision,
        policy.performance_policy,
    )
    active_claims = select_active_claims(claim_values, decision)
    features = [
        *_attention_features(active_claims, decision, policy),
        *_consensus_features(active_claims, decision, policy),
        *_claim_score_features(performance, policy),
    ]
    ordered = tuple(sorted(features, key=lambda item: (item.feature_name.value, item.entity_id)))
    cutoff_candidates = [
        item.data_cutoff_time for item in ordered if item.data_cutoff_time is not None
    ]
    if performance.data_cutoff_time is not None:
        cutoff_candidates.append(performance.data_cutoff_time)
    cutoff = max(cutoff_candidates, default=None)
    return KolFeatureBundle(
        decision_time=decision,
        features=ordered,
        performance=performance,
        data_cutoff_time=cutoff,
        algorithm_version=policy.algorithm_version,
        policy_version=policy.policy_version,
        policy_fingerprint=policy.fingerprint,
    )


__all__ = [
    "KOL_FEATURE_ALGORITHM_VERSION",
    "KOL_FEATURE_POLICY_VERSION",
    "KOL_FEATURE_SCHEMA_VERSION",
    "ClaimRevisionReference",
    "FeatureStatus",
    "KolFeatureBundle",
    "KolFeatureInputError",
    "KolFeatureName",
    "KolFeaturePolicy",
    "KolFeatureValue",
    "PriceRevisionReference",
    "compute_kol_features",
]
