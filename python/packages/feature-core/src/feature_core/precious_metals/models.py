"""Immutable inputs, policy, lineage, and result models for precious-metal funds."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum
from typing import Final, cast

from ashare_contracts import (
    BenchmarkSeriesPoint,
    FundNav,
    is_canonical_benchmark_id,
)
from ashare_contracts import (
    PreciousMetalFund as ContractPreciousMetalFund,
)
from market_core.funds import PreciousMetalFund, fund_from_dict
from market_core.models import Bar

POLICY_VERSION: Final = "v1"
ALGORITHM_VERSION: Final = "v1"
SOURCE_CONTRACT_VERSION: Final = "v1"
OUTPUT_QUANTUM: Final = Decimal("0.000001")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _decimal(value: object, field_name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, (bool, float)):
        raise TypeError(f"{field_name} must not be a float or boolean")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field_name} must be a Decimal-compatible value") from error
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError(f"{field_name} must be finite" + (" and positive" if positive else ""))
    return result


def quantize_value(value: Decimal) -> Decimal:
    """Return the stable fixed-point representation used by all v1 outputs."""
    with localcontext() as context:
        context.prec = 80
        return value.quantize(OUTPUT_QUANTUM)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")
    )
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


FundLike = PreciousMetalFund | ContractPreciousMetalFund


def _canonical_fund(value: FundLike) -> PreciousMetalFund:
    if type(value) is PreciousMetalFund:
        return value
    if type(value) is ContractPreciousMetalFund:
        return fund_from_dict(value.model_dump(by_alias=True, mode="json"))
    raise TypeError("fund must be a public precious-metal fund contract")


@dataclass(frozen=True, slots=True)
class EvidenceLineage:
    """PIT evidence retained with every published or degraded feature."""

    source: str
    source_revision: str
    raw_object_id: str
    payload_digest: str
    event_time: datetime
    available_time: datetime
    processing_time: datetime
    source_contract_version: str = SOURCE_CONTRACT_VERSION
    ingest_time: datetime | None = None

    def __post_init__(self) -> None:
        _text(self.source, "lineage.source")
        _text(self.source_revision, "lineage.source_revision")
        _text(self.raw_object_id, "lineage.raw_object_id")
        if type(self.payload_digest) is not str or _DIGEST.fullmatch(self.payload_digest) is None:
            raise ValueError("lineage.payload_digest must be a sha256 fingerprint")
        _aware(self.event_time, "lineage.event_time")
        _aware(self.available_time, "lineage.available_time")
        _aware(self.processing_time, "lineage.processing_time")
        if self.ingest_time is not None:
            _aware(self.ingest_time, "lineage.ingest_time")
        if (
            self.event_time > self.available_time
            or self.available_time > self.processing_time
            or (
                self.ingest_time is not None
                and not self.event_time <= self.ingest_time <= self.available_time
            )
        ):
            raise ValueError("lineage timestamps must be event <= available <= processing")
        _text(self.source_contract_version, "lineage.source_contract_version")

    def to_contract(self) -> dict[str, str]:
        payload = {
            "source": self.source,
            "sourceRevision": self.source_revision,
            "rawObjectId": self.raw_object_id,
            "payloadDigest": self.payload_digest,
            "eventTime": self.event_time.isoformat(),
            "availableTime": self.available_time.isoformat(),
            "processingTime": self.processing_time.isoformat(),
            "sourceContractVersion": self.source_contract_version,
        }
        if self.ingest_time is not None:
            payload["ingestTime"] = self.ingest_time.isoformat()
        return payload

    @property
    def source_ingest_time(self) -> datetime | None:
        """Source-record ingest time; distinct from OnlineFeatureEvent arrival_time."""
        return self.ingest_time


def _merge_payload_lineage(
    lineage: EvidenceLineage,
    *,
    source: str | None = None,
    source_revision: str | None = None,
    raw_object_id: str | None = None,
    payload_digest: str | None = None,
    event_time: datetime | None = None,
    ingest_time: datetime | None = None,
    available_time: datetime | None = None,
    processing_time: datetime | None = None,
) -> EvidenceLineage:
    expected = (
        ("source", source),
        ("source_revision", source_revision),
        ("raw_object_id", raw_object_id),
        ("payload_digest", payload_digest),
        ("event_time", event_time),
        ("ingest_time", ingest_time),
        ("available_time", available_time),
        ("processing_time", processing_time),
    )
    for field_name, value in expected:
        if (
            value is not None
            and not (field_name == "ingest_time" and lineage.ingest_time is None)
            and getattr(lineage, field_name) != value
        ):
            raise ValueError(f"lineage.{field_name} conflicts with public payload")
    if ingest_time is not None and lineage.ingest_time is None:
        return replace(lineage, ingest_time=ingest_time)
    return lineage


def _bar_event_time(bar: Bar) -> datetime:
    try:
        parsed = datetime.fromisoformat(bar.timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("bar.timestamp must be an ISO timestamp") from error
    return _aware(parsed, "bar.timestamp")


@dataclass(frozen=True, slots=True)
class FundClassificationRecord:
    fund: FundLike
    lineage: EvidenceLineage
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        fund = _canonical_fund(self.fund)
        object.__setattr__(self, "fund", fund)
        if type(self.lineage) is not EvidenceLineage:
            raise TypeError("classification lineage type is invalid")
        object.__setattr__(
            self,
            "lineage",
            _merge_payload_lineage(
                self.lineage,
                source=fund.source,
                raw_object_id=fund.raw_object_id,
                event_time=fund.event_time,
                ingest_time=fund.ingest_time,
                available_time=fund.available_time,
                processing_time=fund.processing_time,
            ),
        )
        object.__setattr__(self, "identity", self.fund.unified_code)


@dataclass(frozen=True, slots=True)
class FundNavRecord:
    nav: FundNav
    lineage: EvidenceLineage
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.nav) is not FundNav:
            raise TypeError("fund NAV record requires ashare_contracts.FundNav")
        if type(self.lineage) is not EvidenceLineage:
            raise TypeError("NAV lineage type is invalid")
        object.__setattr__(
            self,
            "lineage",
            _merge_payload_lineage(
                self.lineage,
                source=self.nav.source,
                raw_object_id=self.nav.raw_object_id,
                event_time=self.nav.event_time,
                ingest_time=self.nav.ingest_time,
                available_time=self.nav.available_time,
                processing_time=self.nav.processing_time,
            ),
        )
        object.__setattr__(self, "identity", f"{self.nav.unified_code}:{self.nav.date.isoformat()}")


@dataclass(frozen=True, slots=True)
class RawBarRecord:
    bar: Bar
    lineage: EvidenceLineage
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.bar) is not Bar:
            raise TypeError("raw bar record requires market_core.models.Bar")
        if type(self.lineage) is not EvidenceLineage:
            raise TypeError("bar lineage type is invalid")
        object.__setattr__(
            self,
            "lineage",
            _merge_payload_lineage(self.lineage, event_time=_bar_event_time(self.bar)),
        )
        object.__setattr__(self, "identity", f"{self.bar.unified_code}:{self.bar.date}")


@dataclass(frozen=True, slots=True)
class BenchmarkSeriesPointRecord:
    point: BenchmarkSeriesPoint
    lineage: EvidenceLineage
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.point) is not BenchmarkSeriesPoint:
            raise TypeError("benchmark record requires ashare_contracts.BenchmarkSeriesPoint")
        if type(self.lineage) is not EvidenceLineage:
            raise TypeError("benchmark lineage type is invalid")
        object.__setattr__(
            self,
            "lineage",
            _merge_payload_lineage(
                self.lineage,
                source=self.point.source,
                source_revision=self.point.source_revision,
                raw_object_id=self.point.raw_object_id,
                payload_digest=self.point.payload_digest,
                event_time=self.point.event_time,
                ingest_time=self.point.ingest_time,
                available_time=self.point.available_time,
                processing_time=self.point.processing_time,
            ),
        )
        object.__setattr__(
            self,
            "identity",
            f"{self.point.benchmark_id}:{self.point.event_time.isoformat()}",
        )


# Descriptive aliases make the revision boundary explicit to callers.
FundClassificationRevision = FundClassificationRecord
FundNavRevision = FundNavRecord
RawBarRevision = RawBarRecord
BenchmarkSeriesPointRevision = BenchmarkSeriesPointRecord


@dataclass(frozen=True, slots=True)
class BenchmarkPolicy:
    benchmark_series_id: str
    allowed_price_bases: tuple[str, ...]
    currency: str

    def __post_init__(self) -> None:
        if not is_canonical_benchmark_id(self.benchmark_series_id):
            raise ValueError("benchmark_series_id must be a canonical benchmark:v1 identity")
        bases = tuple(self.allowed_price_bases)
        if not bases or any(type(item) is not str or not item.strip() for item in bases):
            raise ValueError("allowed_price_bases must be non-empty strings")
        if len(set(bases)) != len(bases):
            raise ValueError("allowed_price_bases must be unique")
        object.__setattr__(self, "allowed_price_bases", tuple(sorted(bases)))
        if type(self.currency) is not str or re.fullmatch(r"[A-Z]{3}", self.currency) is None:
            raise ValueError("benchmark currency must be an ISO 4217 code")


@dataclass(frozen=True, slots=True)
class PreciousMetalsPolicy:
    """Immutable v1 policy; benchmark bindings are always explicitly supplied."""

    policy_version: str = POLICY_VERSION
    inav_max_age: timedelta = timedelta(minutes=5)
    nav_fallback_max_age: timedelta = timedelta(days=7)
    rolling_window_sessions: int = 20
    minimum_samples: int = 10
    accepted_confidence: Decimal = Decimal("0.80")
    benchmarks: tuple[BenchmarkPolicy, ...] = ()
    source_contract_version: str = SOURCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.policy_version != POLICY_VERSION:
            raise ValueError("only policy v1 is implemented")
        if self.inav_max_age <= timedelta(0) or self.nav_fallback_max_age <= timedelta(0):
            raise ValueError("valuation age limits must be positive")
        if type(self.rolling_window_sessions) is not int or self.rolling_window_sessions <= 0:
            raise ValueError("rolling_window_sessions must be positive")
        if (
            type(self.minimum_samples) is not int
            or not 1 <= self.minimum_samples <= self.rolling_window_sessions
        ):
            raise ValueError("minimum_samples must be within the rolling window")
        confidence = _decimal(self.accepted_confidence, "accepted_confidence")
        if confidence < Decimal("0") or confidence > Decimal("1"):
            raise ValueError("accepted_confidence must be between zero and one")
        object.__setattr__(self, "accepted_confidence", confidence)
        policies = tuple(self.benchmarks)
        if any(type(item) is not BenchmarkPolicy for item in policies):
            raise TypeError("benchmarks must contain BenchmarkPolicy values")
        if len({item.benchmark_series_id for item in policies}) != len(policies):
            raise ValueError("benchmark policies must have unique canonical identities")
        object.__setattr__(
            self,
            "benchmarks",
            tuple(sorted(policies, key=lambda item: item.benchmark_series_id)),
        )
        _text(self.source_contract_version, "source_contract_version")

    def benchmark(self, benchmark_series_id: str) -> BenchmarkPolicy | None:
        return next(
            (item for item in self.benchmarks if item.benchmark_series_id == benchmark_series_id),
            None,
        )


class FeatureStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    REJECTED = "REJECTED"


class FeatureReason(StrEnum):
    PUBLISHED = "PUBLISHED"
    DEGRADED_STALE_INAV_FALLBACK_NAV = "DEGRADED_STALE_INAV_FALLBACK_NAV"
    DEGRADED_NAV_FALLBACK_NO_INAV = "DEGRADED_NAV_FALLBACK_NO_INAV"
    UNAVAILABLE_FUTURE_NAV_REVISION = "UNAVAILABLE_FUTURE_NAV_REVISION"
    UNAVAILABLE_FUTURE_BAR_REVISION = "UNAVAILABLE_FUTURE_BAR_REVISION"
    UNAVAILABLE_FUTURE_BENCHMARK_REVISION = "UNAVAILABLE_FUTURE_BENCHMARK_REVISION"
    UNAVAILABLE_CONFLICTING_NAV_REVISION = "UNAVAILABLE_CONFLICTING_NAV_REVISION"
    UNAVAILABLE_CONFLICTING_BAR_REVISION = "UNAVAILABLE_CONFLICTING_BAR_REVISION"
    UNAVAILABLE_CONFLICTING_BENCHMARK_REVISION = "UNAVAILABLE_CONFLICTING_BENCHMARK_REVISION"
    UNAVAILABLE_NO_VALUATION_REFERENCE = "UNAVAILABLE_NO_VALUATION_REFERENCE"
    UNAVAILABLE_CURRENCY_MISMATCH_NO_FX = "UNAVAILABLE_CURRENCY_MISMATCH_NO_FX"
    UNAVAILABLE_NO_MARKET_REFERENCE_PRICE = "UNAVAILABLE_NO_MARKET_REFERENCE_PRICE"
    UNAVAILABLE_MISSING_BENCHMARK = "UNAVAILABLE_MISSING_BENCHMARK"
    UNAVAILABLE_INSUFFICIENT_SAMPLES = "UNAVAILABLE_INSUFFICIENT_SAMPLES"
    UNAVAILABLE_ZERO_BENCHMARK_VARIANCE = "UNAVAILABLE_ZERO_BENCHMARK_VARIANCE"
    REJECTED_UNSUPPORTED_COMMODITY = "REJECTED_UNSUPPORTED_COMMODITY"
    REJECTED_CLASSIFICATION = "REJECTED_CLASSIFICATION"
    REJECTED_CONFLICTING_CLASSIFICATION = "REJECTED_CONFLICTING_CLASSIFICATION"
    DEGRADED_CLASSIFICATION_UNVERIFIED = "DEGRADED_CLASSIFICATION_UNVERIFIED"


_REASON_STATUS: dict[FeatureReason, FeatureStatus] = {
    FeatureReason.PUBLISHED: FeatureStatus.PUBLISHED,
    FeatureReason.DEGRADED_STALE_INAV_FALLBACK_NAV: FeatureStatus.DEGRADED,
    FeatureReason.DEGRADED_NAV_FALLBACK_NO_INAV: FeatureStatus.DEGRADED,
    FeatureReason.DEGRADED_CLASSIFICATION_UNVERIFIED: FeatureStatus.DEGRADED,
    FeatureReason.REJECTED_UNSUPPORTED_COMMODITY: FeatureStatus.REJECTED,
    FeatureReason.REJECTED_CLASSIFICATION: FeatureStatus.REJECTED,
    FeatureReason.REJECTED_CONFLICTING_CLASSIFICATION: FeatureStatus.REJECTED,
    FeatureReason.UNAVAILABLE_FUTURE_NAV_REVISION: FeatureStatus.UNAVAILABLE,
    FeatureReason.UNAVAILABLE_FUTURE_BAR_REVISION: FeatureStatus.UNAVAILABLE,
    FeatureReason.UNAVAILABLE_FUTURE_BENCHMARK_REVISION: FeatureStatus.UNAVAILABLE,
    FeatureReason.UNAVAILABLE_CONFLICTING_NAV_REVISION: FeatureStatus.UNAVAILABLE,
    FeatureReason.UNAVAILABLE_CONFLICTING_BAR_REVISION: FeatureStatus.UNAVAILABLE,
    FeatureReason.UNAVAILABLE_CONFLICTING_BENCHMARK_REVISION: FeatureStatus.UNAVAILABLE,
    FeatureReason.UNAVAILABLE_NO_VALUATION_REFERENCE: FeatureStatus.UNAVAILABLE,
    FeatureReason.UNAVAILABLE_CURRENCY_MISMATCH_NO_FX: FeatureStatus.UNAVAILABLE,
    FeatureReason.UNAVAILABLE_NO_MARKET_REFERENCE_PRICE: FeatureStatus.UNAVAILABLE,
    FeatureReason.UNAVAILABLE_MISSING_BENCHMARK: FeatureStatus.UNAVAILABLE,
    FeatureReason.UNAVAILABLE_INSUFFICIENT_SAMPLES: FeatureStatus.UNAVAILABLE,
    FeatureReason.UNAVAILABLE_ZERO_BENCHMARK_VARIANCE: FeatureStatus.UNAVAILABLE,
}


@dataclass(frozen=True, slots=True)
class FeatureResult:
    value: Decimal | None
    status: FeatureStatus
    reason: FeatureReason
    event_time: datetime
    available_time: datetime
    spec_version: str
    semantic_fingerprint: str
    algorithm_version: str
    policy_version: str
    source_contract_version: str
    lineage: tuple[EvidenceLineage, ...]

    def __post_init__(self) -> None:
        if type(self.status) is not FeatureStatus or type(self.reason) is not FeatureReason:
            raise TypeError("feature status and reason must use typed enums")
        if _REASON_STATUS[self.reason] is not self.status:
            raise ValueError("feature status does not match reason")
        _aware(self.event_time, "feature.event_time")
        _aware(self.available_time, "feature.available_time")
        if self.value is not None and type(cast(object, self.value)) is float:
            raise TypeError("feature values must not be floats")
        if self.value is not None:
            object.__setattr__(self, "value", quantize_value(_decimal(self.value, "feature.value")))
        if (
            self.value is None
            and self.status in {FeatureStatus.PUBLISHED, FeatureStatus.DEGRADED}
            and self.reason
            in {
                FeatureReason.PUBLISHED,
                FeatureReason.DEGRADED_STALE_INAV_FALLBACK_NAV,
                FeatureReason.DEGRADED_NAV_FALLBACK_NO_INAV,
            }
        ):
            raise ValueError("published valuation features require a numeric value")
        if type(self.lineage) is not tuple or any(
            type(item) is not EvidenceLineage for item in self.lineage
        ):
            raise TypeError("feature lineage must contain EvidenceLineage values")
        ordered = tuple(
            sorted(
                set(self.lineage),
                key=lambda item: (
                    item.event_time,
                    item.available_time,
                    item.source_revision,
                    item.raw_object_id,
                    item.payload_digest,
                ),
            )
        )
        object.__setattr__(self, "lineage", ordered)

    @property
    def canonical_value(self) -> str | None:
        if self.value is None:
            return None
        normalized = format(self.value, "f").rstrip("0").rstrip(".")
        return "0" if normalized in {"", "-0"} else normalized

    @property
    def state(self) -> FeatureReason:
        return self.reason

    @property
    def canonical_payload(self) -> dict[str, object]:
        return {
            "value": self.canonical_value,
            "status": self.status.value,
            "reason": self.reason.value,
            "eventTime": self.event_time.isoformat(),
            "availableTime": self.available_time.isoformat(),
            "specVersion": self.spec_version,
            "semanticFingerprint": self.semantic_fingerprint,
            "algorithmVersion": self.algorithm_version,
            "policyVersion": self.policy_version,
            "sourceContractVersion": self.source_contract_version,
            "lineage": tuple(item.to_contract() for item in self.lineage),
        }

    @property
    def canonical_json(self) -> str:
        return json.dumps(
            self.canonical_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class PreciousMetalsFeatureInput:
    fund: FundLike
    decision_time: datetime
    navs: tuple[FundNavRecord, ...] = ()
    bars: tuple[RawBarRecord, ...] = ()
    benchmarks: tuple[BenchmarkSeriesPointRecord, ...] = ()
    classification_revisions: tuple[FundClassificationRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "fund", _canonical_fund(self.fund))
        _aware(self.decision_time, "decision_time")
        for field_name, expected_type in (
            ("navs", FundNavRecord),
            ("bars", RawBarRecord),
            ("benchmarks", BenchmarkSeriesPointRecord),
            ("classification_revisions", FundClassificationRecord),
        ):
            values = tuple(getattr(self, field_name))
            if any(type(item) is not expected_type for item in values):
                raise TypeError(f"{field_name} contains an invalid revision record")
            object.__setattr__(self, field_name, values)
        if not self.classification_revisions:
            event_time = self.fund.event_time or self.fund.available_time
            fallback = EvidenceLineage(
                source=self.fund.source,
                source_revision=self.fund.raw_object_id,
                raw_object_id=self.fund.raw_object_id,
                payload_digest=_digest(
                    {
                        "unifiedCode": self.fund.unified_code,
                        "validFrom": self.fund.valid_from,
                        "validTo": self.fund.valid_to,
                        "benchmarkSeriesId": self.fund.benchmark_series_id,
                    }
                ),
                event_time=event_time,
                available_time=self.fund.available_time,
                processing_time=self.fund.processing_time,
                ingest_time=self.fund.ingest_time,
            )
            object.__setattr__(
                self,
                "classification_revisions",
                (FundClassificationRecord(fund=self.fund, lineage=fallback),),
            )


# A compatibility name for callers that prefer the shorter input terminology.
FeatureInput = PreciousMetalsFeatureInput
