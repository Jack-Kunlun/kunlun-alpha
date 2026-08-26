"""Adapters for the public batch and online feature-engine boundaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import cast

from ashare_contracts import BenchmarkSeriesPoint, FundNav
from market_core.funds import fund_from_dict
from market_core.models import bar_from_dict

from feature_core.batch import (
    BatchInputRow,
    BatchPartition,
    CalculatedFeature,
    CalculatorIdentity,
    canonical_checksum,
)
from feature_core.online import (
    EventTimeWindow,
    OnlineCalculationResult,
    OnlineCalculatorArtifact,
    OnlineFeatureEvent,
)
from feature_core.registry import FeatureSpec

from .calculator import calculate_feature
from .models import (
    ALGORITHM_VERSION,
    BenchmarkSeriesPointRecord,
    EvidenceLineage,
    FeatureResult,
    FundClassificationRecord,
    FundNavRecord,
    PreciousMetalsFeatureInput,
    PreciousMetalsPolicy,
    RawBarRecord,
)

CALCULATOR_IDENTITY = CalculatorIdentity(
    algorithm_version=ALGORITHM_VERSION,
    implementation_fingerprint=canonical_checksum(
        {"calculator": "feature_core.precious_metals.calculator", "version": ALGORITHM_VERSION}
    ),
)

_Record = FundClassificationRecord | FundNavRecord | RawBarRecord | BenchmarkSeriesPointRecord

_RECORD_TYPE_BY_CONTRACT = {
    ("domain.precious_metal_fund", "v1"): "fund",
    ("domain.fund_nav", "v1"): "nav",
    ("market.daily_bar", "v1"): "bar",
    ("market.benchmark_series_point", "v1"): "benchmark",
}


class FeatureMaterializationUnavailableError(RuntimeError):
    """A typed calculator result cannot be represented as a numeric materialized value."""

    def __init__(self, result: FeatureResult) -> None:
        self.result = result
        super().__init__(f"{result.status.value}/{result.reason.value} has no numeric value")


def _timestamp(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif type(value) is str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{field_name} must be an ISO timestamp string") from error
    else:
        raise ValueError(f"{field_name} must be a timezone-aware timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return cast(Mapping[str, object], value)


def _validate_contract_record_type(
    payload: Mapping[str, object],
    contract_name: str,
    contract_version: str,
) -> None:
    expected = _RECORD_TYPE_BY_CONTRACT.get((contract_name, contract_version))
    if expected is None:
        raise ValueError(f"unsupported precious-metals contract {contract_name}@{contract_version}")
    if payload.get("recordType") != expected:
        raise ValueError(f"{contract_name}@{contract_version} requires recordType {expected}")


def thaw_json_value(value: object) -> object:
    """Convert frozen canonical JSON containers to ordinary JSON containers."""
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        if any(type(key) is not str for key in mapping):
            raise ValueError("canonical JSON object keys must be strings")
        return {key: thaw_json_value(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        items = cast(Sequence[object], value)
        return [thaw_json_value(item) for item in items]
    if value is None or type(value) in (bool, int, str):
        return value
    raise ValueError("canonical JSON contains an unsupported leaf type")


def _coalesced(
    payload: Mapping[str, object],
    data: Mapping[str, object],
    key: str,
    *,
    parse: bool = False,
) -> object | None:
    values: list[object] = []
    for mapping in (payload, data):
        if key in mapping:
            values.append(mapping[key])
    if not values:
        return None
    normalized = [_timestamp(item, key) if parse else item for item in values]
    if len(set(normalized)) != 1:
        raise ValueError(f"payload {key} values conflict")
    return normalized[0]


def _same_or_missing(
    field_name: str,
    payload_value: object | None,
    expected: object | None,
) -> object | None:
    if payload_value is not None and expected is not None and payload_value != expected:
        raise ValueError(f"payload {field_name} conflicts with outer lineage")
    return expected if expected is not None else payload_value


def _record_lineage(
    payload: Mapping[str, object],
    data: Mapping[str, object],
    record: _Record,
    *,
    outer_event_time: datetime,
    outer_available_time: datetime,
    source_revision: str | None,
    source_contract_version: str,
) -> EvidenceLineage:
    payload_event = _coalesced(payload, data, "eventTime", parse=True)
    payload_available = _coalesced(payload, data, "availableTime", parse=True)
    payload_ingest = _coalesced(payload, data, "ingestTime", parse=True)
    payload_processing = _coalesced(payload, data, "processingTime", parse=True)
    payload_source = _coalesced(payload, data, "source")
    payload_raw_object_id = _coalesced(payload, data, "rawObjectId")
    payload_source_revision = _coalesced(payload, data, "sourceRevision")
    payload_digest = _coalesced(payload, data, "payloadDigest")
    payload_contract_version = _coalesced(payload, data, "sourceContractVersion")

    model_event: datetime | None = None
    model_ingest: datetime | None = None
    model_available: datetime | None = None
    model_processing: datetime | None = None
    model_source: str | None = None
    model_raw_object_id: str | None = None
    model_source_revision: str | None = None
    model_payload_digest: str | None = None
    if isinstance(record, FundClassificationRecord):
        model_event = record.fund.event_time
        model_ingest = record.fund.ingest_time
        model_available = record.fund.available_time
        model_processing = record.fund.processing_time
        model_source = record.fund.source
        model_raw_object_id = record.fund.raw_object_id
    elif isinstance(record, FundNavRecord):
        model_event = record.nav.event_time
        model_ingest = record.nav.ingest_time
        model_available = record.nav.available_time
        model_processing = record.nav.processing_time
        model_source = record.nav.source
        model_raw_object_id = record.nav.raw_object_id
    elif isinstance(record, RawBarRecord):
        model_event = _timestamp(record.bar.timestamp, "bar.timestamp")
    else:
        model_event = record.point.event_time
        model_ingest = record.point.ingest_time
        model_available = record.point.available_time
        model_processing = record.point.processing_time
        model_source = record.point.source
        model_raw_object_id = record.point.raw_object_id
        model_source_revision = record.point.source_revision
        model_payload_digest = record.point.payload_digest

    event_time = _same_or_missing("eventTime", cast(datetime | None, payload_event), model_event)
    event_time = _same_or_missing("eventTime", event_time, outer_event_time)
    if event_time is None:
        raise ValueError("payload must provide eventTime or a public model event time")
    available_time = _same_or_missing(
        "availableTime", cast(datetime | None, payload_available), model_available
    )
    available_time = _same_or_missing("availableTime", available_time, outer_available_time)
    if available_time is None:
        raise ValueError("payload must provide availableTime")
    ingest_time = _same_or_missing(
        "ingestTime", cast(datetime | None, payload_ingest), model_ingest
    )
    processing_time = _same_or_missing(
        "processingTime", cast(datetime | None, payload_processing), model_processing
    )
    if processing_time is None:
        raise ValueError("payload must provide processingTime")
    source = _same_or_missing("source", cast(str | None, payload_source), model_source)
    raw_object_id = _same_or_missing(
        "rawObjectId", cast(str | None, payload_raw_object_id), model_raw_object_id
    )
    if type(source) is not str or not source:
        raise ValueError("payload must provide source")
    if type(raw_object_id) is not str or not raw_object_id:
        raise ValueError("payload must provide rawObjectId")
    resolved_source_revision = _same_or_missing(
        "sourceRevision", cast(str | None, payload_source_revision), model_source_revision
    )
    resolved_source_revision = _same_or_missing(
        "sourceRevision", resolved_source_revision, source_revision
    )
    if type(resolved_source_revision) is not str or not resolved_source_revision:
        raise ValueError("payload or explicit lineage must provide sourceRevision")
    resolved_digest = _same_or_missing(
        "payloadDigest", cast(str | None, payload_digest), model_payload_digest
    )
    if resolved_digest is None:
        resolved_digest = canonical_checksum(payload)
    if type(resolved_digest) is not str:
        raise ValueError("payloadDigest must be a string")
    if payload_contract_version is not None and payload_contract_version != source_contract_version:
        raise ValueError("sourceContractVersion conflicts with the declared contract")
    return EvidenceLineage(
        source=source,
        source_revision=resolved_source_revision,
        raw_object_id=raw_object_id,
        payload_digest=resolved_digest,
        event_time=cast(datetime, event_time),
        available_time=cast(datetime, available_time),
        processing_time=cast(datetime, processing_time),
        source_contract_version=source_contract_version,
        ingest_time=cast(datetime | None, ingest_time),
    )


def _initial_lineage(
    payload: Mapping[str, object],
    data: Mapping[str, object],
    *,
    outer_event_time: datetime,
    outer_available_time: datetime,
    source_revision: str | None,
) -> EvidenceLineage:
    processing = payload.get("processingTime", data.get("processingTime"))
    if processing is None:
        raise ValueError("payload must provide processingTime")
    return EvidenceLineage(
        source=str(data.get("source", payload.get("source", "missing-source"))),
        source_revision=source_revision or str(data.get("sourceRevision", "missing-revision")),
        raw_object_id=str(data.get("rawObjectId", payload.get("rawObjectId", "missing-raw"))),
        payload_digest=cast(str, payload.get("payloadDigest", canonical_checksum(payload))),
        event_time=outer_event_time,
        available_time=outer_available_time,
        processing_time=_timestamp(processing, "processingTime"),
    )


def _record(
    payload: Mapping[str, object],
    *,
    contract_name: str,
    outer_event_time: datetime,
    outer_available_time: datetime,
    source_revision: str | None,
    source_contract_version: str,
) -> _Record:
    thawed_payload = _mapping(thaw_json_value(payload), "payload")
    _validate_contract_record_type(
        thawed_payload,
        contract_name,
        source_contract_version,
    )
    record_type = thawed_payload.get("recordType")
    data = _mapping(thawed_payload.get("data"), "data")
    initial = _initial_lineage(
        thawed_payload,
        data,
        outer_event_time=outer_event_time,
        outer_available_time=outer_available_time,
        source_revision=source_revision,
    )
    if record_type == "fund":
        parsed: _Record = FundClassificationRecord(
            fund=fund_from_dict(dict(data)),
            lineage=initial,
        )
    elif record_type == "nav":
        parsed = FundNavRecord(nav=FundNav.model_validate(dict(data)), lineage=initial)
    elif record_type == "bar":
        parsed = RawBarRecord(bar=bar_from_dict(dict(data)), lineage=initial)
    elif record_type == "benchmark":
        parsed = BenchmarkSeriesPointRecord(
            point=BenchmarkSeriesPoint.model_validate(dict(data)),
            lineage=initial,
        )
    else:
        raise ValueError("recordType must be fund, nav, bar, or benchmark")
    lineage = _record_lineage(
        thawed_payload,
        data,
        parsed,
        outer_event_time=outer_event_time,
        outer_available_time=outer_available_time,
        source_revision=source_revision,
        source_contract_version=source_contract_version,
    )
    if isinstance(parsed, FundClassificationRecord):
        return FundClassificationRecord(fund=parsed.fund, lineage=lineage)
    if isinstance(parsed, FundNavRecord):
        return FundNavRecord(nav=parsed.nav, lineage=lineage)
    if isinstance(parsed, RawBarRecord):
        return RawBarRecord(bar=parsed.bar, lineage=lineage)
    return BenchmarkSeriesPointRecord(point=parsed.point, lineage=lineage)


def _context(records: Sequence[_Record], decision_time: datetime) -> PreciousMetalsFeatureInput:
    classifications = tuple(item for item in records if type(item) is FundClassificationRecord)
    if not classifications:
        raise ValueError("engine input must contain a fund classification record")
    fund = classifications[0].fund
    return PreciousMetalsFeatureInput(
        fund=fund,
        decision_time=decision_time,
        navs=tuple(item for item in records if type(item) is FundNavRecord),
        bars=tuple(item for item in records if type(item) is RawBarRecord),
        benchmarks=tuple(item for item in records if type(item) is BenchmarkSeriesPointRecord),
        classification_revisions=classifications,
    )


def context_from_batch_rows(
    rows: Sequence[BatchInputRow],
    decision_time: datetime,
) -> PreciousMetalsFeatureInput:
    records = tuple(
        _record(
            row.payload,
            contract_name=row.contract_name,
            outer_event_time=row.event_time,
            outer_available_time=row.available_time,
            source_revision=row.source_revision,
            source_contract_version=row.contract_version,
        )
        for row in rows
    )
    return _context(records, decision_time)


def context_from_online_events(
    events: Sequence[OnlineFeatureEvent],
    decision_time: datetime,
) -> PreciousMetalsFeatureInput:
    records = tuple(
        _record(
            event.payload,
            contract_name=event.contract_name,
            outer_event_time=event.event_time,
            outer_available_time=event.available_time,
            source_revision=event.source_revision,
            source_contract_version=event.contract_version,
        )
        for event in events
    )
    return _context(records, decision_time)


def _online_decision_time(
    events: Sequence[OnlineFeatureEvent],
    window: EventTimeWindow,
) -> datetime:
    return max((event.arrival_time for event in events), default=window.end)


def _numeric_result(
    result: FeatureResult,
    *,
    entity_id: str,
    event_time: datetime,
    input_row_ids: tuple[str, ...],
) -> CalculatedFeature:
    if result.canonical_value is None:
        raise FeatureMaterializationUnavailableError(result)
    return CalculatedFeature(
        entity_id=entity_id,
        event_time=event_time,
        value=result.canonical_value,
        input_row_ids=input_row_ids,
    )


class BatchPreciousMetalsAdapter:
    """A callable BatchCalculator plus a compatibility calculation helper."""

    identity = CALCULATOR_IDENTITY

    def __init__(self, policy: PreciousMetalsPolicy) -> None:
        self.policy = policy

    def __call__(
        self,
        feature: FeatureSpec,
        partition: BatchPartition,
        rows: tuple[BatchInputRow, ...],
    ) -> tuple[CalculatedFeature, ...]:
        context = context_from_batch_rows(rows, partition.decision_time)
        result = calculate_feature(feature, context, self.policy)
        return (
            _numeric_result(
                result,
                entity_id=context.fund.unified_code,
                event_time=result.event_time,
                input_row_ids=tuple(row.row_id for row in rows),
            ),
        )

    def context(
        self,
        rows: Sequence[BatchInputRow],
        decision_time: datetime,
    ) -> PreciousMetalsFeatureInput:
        return context_from_batch_rows(rows, decision_time)

    def calculate(
        self,
        feature: str,
        rows: Sequence[BatchInputRow],
        decision_time: datetime,
    ) -> FeatureResult:
        return calculate_feature(feature, self.context(rows, decision_time), self.policy)


class OnlinePreciousMetalsAdapter:
    """A callable OnlineCalculator plus a compatibility calculation helper."""

    identity = CALCULATOR_IDENTITY

    def __init__(self, policy: PreciousMetalsPolicy) -> None:
        self.policy = policy

    @property
    def artifact(self) -> OnlineCalculatorArtifact:
        return OnlineCalculatorArtifact(
            identity=self.identity,
            calculator=self,
            contextual_calculator=self._calculate_with_processing_time,
        )

    def _calculate_with_processing_time(
        self,
        feature: FeatureSpec,
        _window: EventTimeWindow,
        events: tuple[OnlineFeatureEvent, ...],
        processing_time: datetime,
    ) -> OnlineCalculationResult:
        return self._online_result(feature, events, processing_time)

    def __call__(
        self,
        feature: FeatureSpec,
        window: EventTimeWindow,
        events: tuple[OnlineFeatureEvent, ...],
    ) -> OnlineCalculationResult:
        decision_time = _online_decision_time(events, window)
        return self._online_result(feature, events, decision_time)

    def _online_result(
        self,
        feature: FeatureSpec,
        events: Sequence[OnlineFeatureEvent],
        decision_time: datetime,
    ) -> OnlineCalculationResult:
        for event in events:
            _validate_contract_record_type(
                event.payload,
                event.contract_name,
                event.contract_version,
            )
        required_contracts = {
            (contract.name, contract.version) for contract in feature.source_contracts
        }
        present_contracts = {(event.contract_name, event.contract_version) for event in events}
        if not required_contracts.issubset(present_contracts):
            return OnlineCalculationResult.pending()
        result = calculate_feature(
            feature.name,
            context_from_online_events(events, decision_time),
            self.policy,
        )
        if result.canonical_value is not None:
            return OnlineCalculationResult.materialized(result.canonical_value)
        return OnlineCalculationResult.terminal(
            status=result.status.value,
            reason=result.reason.value,
        )

    def context(
        self,
        events: Sequence[OnlineFeatureEvent],
        decision_time: datetime,
    ) -> PreciousMetalsFeatureInput:
        return context_from_online_events(events, decision_time)

    def calculate(
        self,
        feature: str,
        events: Sequence[OnlineFeatureEvent],
        decision_time: datetime,
    ) -> FeatureResult:
        return calculate_feature(feature, self.context(events, decision_time), self.policy)


__all__ = [
    "CALCULATOR_IDENTITY",
    "BatchPreciousMetalsAdapter",
    "FeatureMaterializationUnavailableError",
    "OnlinePreciousMetalsAdapter",
    "context_from_batch_rows",
    "context_from_online_events",
    "thaw_json_value",
]
