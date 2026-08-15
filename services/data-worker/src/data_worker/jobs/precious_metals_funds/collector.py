"""Precious-metal fund NAV collection job.

Collects NAV/iNAV observations from a provider (capability-gated), normalizes
and deduplicates them, validates each observation, and raises alerts for
source conflicts and stale NAV. NAV/iNAV are reference values — never marked
tradeable — and missing fields are never silently inferred.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal, cast
from uuid import uuid4

from ashare_contracts.funds_precious_metal_fund import PreciousMetalFund
from ashare_contracts.providers import Capability
from data_worker.raw import (
    CaptureConflictError,
    RawObjectManifest,
    RawStorage,
    decode_json,
    replay_json,
)
from data_worker.raw.manifest import (
    FUND_ENDPOINT_KINDS,
    SOURCE_REVISION_SENTINEL,
    validate_fund_endpoint_kind,
    validate_identifier,
)
from data_worker.scheduler.scheduler import PermanentError, TransientError
from data_worker.scheduler.store import validate_json_payload
from data_worker.storage.precious_metals import (
    EvidenceEnvelope,
    FundPersistence,
    FundQualityEvent,
    InMemoryFundStorage,
    LeaseContext,
    RejectedObservation,
    controlled_rejection_payload,
    fund_checkpoint_key,
)
from market_core.funds.validation import FundNav
from market_core.providers import (
    Provider,
    ProviderAuthError,
    ProviderDataError,
    ProviderError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RawFundProviderResponse,
)


def map_provider_error(error: BaseException) -> PermanentError | TransientError:
    """Map provider failures to scheduler-safe categories without raw details."""

    if isinstance(error, ProviderTimeoutError):
        return TransientError(category="timeout")
    if isinstance(error, ProviderRateLimitError):
        return TransientError(category="rate_limit")
    if isinstance(error, ProviderUnavailableError):
        return TransientError(category="unavailable")
    if isinstance(error, ProviderAuthError):
        return PermanentError(category="auth")
    if isinstance(error, ProviderNotFoundError):
        return PermanentError(category="not_found")
    if isinstance(error, ProviderDataError):
        return PermanentError(category="data_error")
    if isinstance(error, ProviderError):
        # A future provider subclass must not leak its message into durable
        # task state; unknown taxonomy is conservatively permanent/internal.
        return PermanentError(category="internal")
    return PermanentError(category="internal")


# ---------------------------------------------------------------------------
# Capability-gated raw-to-normalized fund pipeline


@dataclass(frozen=True, slots=True)
class InavObservation:
    """Indicative NAV reference value with an immutable evidence envelope."""

    unified_code: str
    date: str
    inav: Decimal
    evidence: EvidenceEnvelope
    payload: dict[str, object]
    kind: Literal["inav"] = "inav"
    tradeable: bool = False

    @property
    def is_reference_only(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class NavObservation:
    """NAV reference value with an immutable evidence envelope."""

    value: FundNav
    evidence: EvidenceEnvelope
    payload: dict[str, object]
    kind: Literal["nav"] = "nav"
    tradeable: bool = False

    @property
    def unified_code(self) -> str:
        return self.value.unified_code

    @property
    def date(self) -> str:
        return self.value.date

    @property
    def nav(self) -> Decimal:
        return self.value.nav

    @property
    def is_reference_only(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class MetadataObservation:
    """Precious-metals metadata with an immutable evidence envelope."""

    value: PreciousMetalFund
    evidence: EvidenceEnvelope
    payload: dict[str, object]
    kind: Literal["metadata"] = "metadata"
    tradeable: bool = False

    @property
    def unified_code(self) -> str:
        return self.value.unified_code

    @property
    def date(self) -> str:
        return self.value.valid_from.isoformat()

    @property
    def is_reference_only(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class BenchmarkObservation:
    """Benchmark metadata kept independent from full fund classification."""

    unified_code: str
    date: str
    benchmark: str
    evidence: EvidenceEnvelope
    payload: dict[str, object]
    kind: Literal["benchmark"] = "benchmark"
    tradeable: bool = False


@dataclass(frozen=True, slots=True)
class FeeObservation:
    """Decimal fee metadata kept independent from fund classification."""

    unified_code: str
    date: str
    management_fee_rate: Decimal
    evidence: EvidenceEnvelope
    payload: dict[str, object]
    kind: Literal["fees"] = "fees"
    tradeable: bool = False


@dataclass(frozen=True, slots=True)
class FundCollectionResult:
    """Accepted/rejected/quality result for one capability collection."""

    kind: str
    accepted: list[object]
    rejected: list[RejectedObservation]
    quality_events: list[FundQualityEvent]
    checkpoint: dict[str, object]

    @property
    def next_cursor(self) -> str | None:
        # Remote cursors are intentionally never persisted or exposed from a
        # completed collection result.  Restart is at-least-once rescan from
        # the first page; only the irreversible lineage hash is durable.
        return None


class CursorLoopError(ValueError):
    """Provider pagination did not advance monotonically."""


def _json_safe(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _json_safe(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        sequence = cast(tuple[object, ...] | list[object], value)
        return [_json_safe(item) for item in sequence]
    return value


def _json_bytes(value: object) -> bytes:
    encoded = json.dumps(
        _json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return encoded.encode()


def _parse_decimal(value: object, field: str) -> Decimal:
    if isinstance(value, (bool, float)):
        raise TypeError(f"{field} must be supplied as a decimal string")
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} is not a decimal") from exc


def _parse_time(value: object, field: str, *, optional: bool = False) -> datetime | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


@dataclass(frozen=True, slots=True)
class TrustedFundContext:
    """Immutable provenance context built only from a verified raw manifest."""

    source: str
    raw_capture_id: str
    raw_object_id: str
    checksum: str
    ingest_time: datetime
    available_time: datetime
    processing_time: datetime
    endpoint_kind: str
    run_id: str | None
    source_revision: str | None
    schema_version: str
    normalizer_version: str

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("trusted source is required")
        if not self.raw_capture_id.strip() or not self.raw_object_id.strip():
            raise ValueError("trusted raw capture/object identity is required")
        if not self.checksum.strip():
            raise ValueError("trusted checksum is required")
        if self.endpoint_kind not in FUND_ENDPOINT_KINDS:
            raise ValueError("trusted endpoint_kind is invalid")
        for name in ("ingest_time", "available_time", "processing_time"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"trusted {name} must be timezone-aware")

    @classmethod
    def from_manifest(
        cls,
        manifest: RawObjectManifest,
        *,
        processing_time: datetime,
        schema_version: str,
        normalizer_version: str,
    ) -> TrustedFundContext:
        """Create context after the manifest's object bytes have been verified."""

        endpoint_kind = manifest.endpoint_kind
        if endpoint_kind is None:
            raise ValueError("verified manifest is missing endpoint_kind")
        return cls(
            source=manifest.source,
            raw_capture_id=manifest.capture_id,
            raw_object_id=manifest.object_id,
            checksum=manifest.checksum,
            ingest_time=manifest.ingest_time,
            available_time=cast(datetime, manifest.available_time),
            processing_time=processing_time,
            endpoint_kind=endpoint_kind,
            run_id=manifest.run_id,
            source_revision=manifest.source_revision,
            schema_version=schema_version,
            normalizer_version=normalizer_version,
        )


def _payload_digest(record: Mapping[str, object]) -> str:
    return hashlib.sha256(_json_bytes(record)).hexdigest()


_SEMANTIC_PAYLOAD_EXCLUDED_FIELDS = frozenset(
    {
        "source",
        "rawObjectId",
        "rawEvidenceId",
        "raw_object_id",
        "raw_evidence_id",
        "eventTime",
        "publishTime",
        "ingestTime",
        "availableTime",
        "processingTime",
        "event_time",
        "publish_time",
        "ingest_time",
        "available_time",
        "processing_time",
        "captureId",
        "capture_id",
        "checksum",
        "endpointKind",
        "endpoint_kind",
        "runId",
        "run_id",
        "sourceRevision",
        "source_revision",
        "schemaVersion",
        "schema_version",
        "normalizerVersion",
        "normalizer_version",
    }
)


def _effective_available_time(
    record: Mapping[str, object], context: TrustedFundContext
) -> datetime:
    payload_available = _parse_time(record.get("availableTime"), "availableTime", optional=True)
    if payload_available is None:
        return context.available_time
    return max(payload_available, context.available_time)


def _trusted_record(
    record: Mapping[str, object], context: TrustedFundContext
) -> tuple[dict[str, object], datetime]:
    payload_object_id = record.get("rawObjectId")
    if payload_object_id is not None and payload_object_id != context.raw_object_id:
        raise ValueError("rawObjectId does not match the verified manifest")

    available_time = _effective_available_time(record, context)
    trusted: dict[str, object] = dict(record)
    trusted.update(
        {
            "source": context.source,
            "ingestTime": context.ingest_time.isoformat(),
            "availableTime": available_time.isoformat(),
            "processingTime": context.processing_time.isoformat(),
        }
    )
    for field_name in (
        "captureId",
        "checksum",
        "endpointKind",
        "runId",
        "sourceRevision",
        "schemaVersion",
        "normalizerVersion",
        "capture_id",
        "endpoint_kind",
        "run_id",
        "source_revision",
        "schema_version",
        "normalizer_version",
    ):
        trusted.pop(field_name, None)
    return trusted, available_time


def _evidence(
    record: Mapping[str, object],
    *,
    context: TrustedFundContext,
    item_ordinal: int,
    payload_digest: str | None,
) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        raw_capture_id=context.raw_capture_id,
        raw_object_id=context.raw_object_id,
        checksum=context.checksum,
        source=context.source,
        source_revision=context.source_revision,
        schema_version=context.schema_version,
        normalizer_version=context.normalizer_version,
        payload_digest=payload_digest or _payload_digest(record),
        item_ordinal=item_ordinal,
        event_time=_parse_time(record.get("eventTime"), "eventTime", optional=True),
        publish_time=_parse_time(record.get("publishTime"), "publishTime", optional=True),
        ingest_time=context.ingest_time,
        available_time=_effective_available_time(record, context),
        processing_time=context.processing_time,
    )


def normalize_fund_observation(
    kind: Literal["metadata", "nav", "inav", "benchmark", "fees"],
    record: Mapping[str, object],
    *,
    trusted_context: TrustedFundContext | None,
    item_ordinal: int = 0,
    payload_digest: str | None = None,
) -> MetadataObservation | NavObservation | InavObservation | BenchmarkObservation | FeeObservation:
    """Normalize one raw item only after its response has been captured."""
    if kind not in FUND_ENDPOINT_KINDS:
        raise ValueError("kind must be one of metadata, nav, inav, benchmark, fees")
    if trusted_context is None:
        raise ValueError("trusted_context is required")
    context = trusted_context
    if context.endpoint_kind != kind:
        raise ValueError("trusted endpoint_kind does not match normalization kind")
    evidence = _evidence(
        record,
        context=context,
        item_ordinal=item_ordinal,
        payload_digest=payload_digest,
    )
    trusted_record, _ = _trusted_record(record, context)
    semantic_record = {
        key: value
        for key, value in trusted_record.items()
        if key not in _SEMANTIC_PAYLOAD_EXCLUDED_FIELDS
    }
    payload = cast(dict[str, object], _json_safe(semantic_record))
    model_record = dict(trusted_record)
    model_record["rawObjectId"] = context.raw_object_id
    for field_name in (
        "captureId",
        "checksum",
        "endpointKind",
        "runId",
        "sourceRevision",
        "schemaVersion",
        "normalizerVersion",
    ):
        model_record.pop(field_name, None)
    if kind == "benchmark":
        required = record.get("benchmarkOrTrackingIndex")
        if not isinstance(required, str) or not required.strip():
            raise ValueError("benchmarkOrTrackingIndex is required")
        return BenchmarkObservation(
            unified_code=str(record.get("unifiedCode", "")),
            date=str(record.get("date", "")),
            benchmark=required,
            evidence=evidence,
            payload=payload,
        )
    if kind == "fees":
        fee = _parse_decimal(record.get("managementFeeRate"), "managementFeeRate")
        if fee < 0:
            raise ValueError("managementFeeRate must be >= 0")
        return FeeObservation(
            unified_code=str(record.get("unifiedCode", "")),
            date=str(record.get("date", "")),
            management_fee_rate=fee,
            evidence=evidence,
            payload=payload,
        )
    if kind == "metadata":
        value = PreciousMetalFund.model_validate(model_record)
        if value.valid_to is not None and value.valid_to < value.valid_from:
            raise ValueError("valid_to cannot precede valid_from")
        return MetadataObservation(value=value, evidence=evidence, payload=payload)

    required_times = (
        evidence.event_time,
        evidence.publish_time,
        evidence.ingest_time,
        evidence.available_time,
        evidence.processing_time,
    )
    if any(value is None for value in required_times):
        raise ValueError("NAV/iNAV requires event/publish/ingest/available/processing times")
    code = str(trusted_record.get("unifiedCode", ""))
    nav_date = str(trusted_record.get("date", ""))
    if kind == "nav":
        value = FundNav(
            unified_code=code,
            date=nav_date,
            nav=_parse_decimal(trusted_record.get("nav"), "nav"),
            inav=None,
            event_time=cast(datetime, evidence.event_time),
            publish_time=cast(datetime, evidence.publish_time),
            ingest_time=cast(datetime, evidence.ingest_time),
            available_time=cast(datetime, evidence.available_time),
            processing_time=cast(datetime, evidence.processing_time),
            raw_object_id=context.raw_object_id,
            source=context.source,
        )
        return NavObservation(value=value, evidence=evidence, payload=payload)

    inav = _parse_decimal(trusted_record.get("inav"), "inav")
    return InavObservation(
        unified_code=code,
        date=nav_date,
        inav=inav,
        evidence=evidence,
        payload=payload,
    )


def validate_fund_observation(
    observation: MetadataObservation
    | NavObservation
    | InavObservation
    | BenchmarkObservation
    | FeeObservation,
    *,
    now: datetime,
    as_of: datetime | None = None,
    stale_after: timedelta = timedelta(days=7),
) -> tuple[bool, tuple[str, ...]]:
    """Apply point-in-time, non-negative and stale-value validation."""
    now_value = _parse_time(now.isoformat(), "now")
    assert now_value is not None
    cutoff = now_value if as_of is None else _parse_time(as_of.isoformat(), "as_of")
    assert cutoff is not None
    evidence = observation.evidence
    times = (
        evidence.event_time,
        evidence.publish_time,
        evidence.ingest_time,
        evidence.available_time,
        evidence.processing_time,
    )
    issues: list[str] = []
    if any(value is None for value in times) and observation.kind in {"nav", "inav"}:
        issues.append("missing timestamp")
    ordered = tuple(value for value in times if value is not None)
    if any(left > right for left, right in zip(ordered, ordered[1:], strict=False)):
        issues.append("timestamp order invalid")
    if evidence.available_time is not None and evidence.available_time > cutoff:
        issues.append("available time is after as-of")
    if observation.kind == "nav":
        if observation.value.nav < 0:
            issues.append("nav must be >= 0")
        try:
            nav_date = date.fromisoformat(observation.value.date)
            if (now_value.date() - nav_date) > stale_after:
                issues.append("nav is stale")
        except ValueError:
            issues.append("date is invalid")
    elif observation.kind == "inav" and observation.inav < 0:
        issues.append("inav must be >= 0")
    elif observation.kind == "fees" and observation.management_fee_rate < 0:
        issues.append("management fee must be >= 0")
    return not issues, tuple(issues)


def _semantic_key(observation: object) -> str:
    stored_key = getattr(observation, "semantic_key", None)
    if isinstance(stored_key, str) and stored_key:
        return stored_key
    code = str(getattr(observation, "unified_code", ""))
    value_date = str(getattr(observation, "date", ""))
    return f"{getattr(observation, 'kind', '')}:{code}:{value_date}"


def _semantic_value(observation: object) -> object:
    kind = getattr(observation, "kind", "")
    payload = getattr(observation, "payload", {})
    if isinstance(payload, dict):
        payload_dict = cast(dict[str, object], payload)
        if kind == "metadata":
            return tuple(sorted((str(key), str(item)) for key, item in payload_dict.items()))
        canonical_fields = {
            "nav": "nav",
            "inav": "inav",
            "benchmark": "benchmarkOrTrackingIndex",
            "fees": "managementFeeRate",
        }
        field = canonical_fields.get(kind)
        if field is not None:
            value = payload_dict.get(field)
            if value is None:
                value = payload_dict.get(
                    {
                        "benchmarkOrTrackingIndex": "benchmark",
                        "managementFeeRate": "management_fee_rate",
                    }.get(field, field)
                )
            return None if value is None else str(value)
    return repr(observation)


def _validated_checkpoint(persistence: FundPersistence, task_id: str) -> dict[str, object]:
    """Load and validate a bounded checkpoint before starting a rescan."""

    raw = persistence.get_checkpoint(task_id)
    if raw is None:
        return {}
    validated = validate_json_payload(raw, "checkpoint")
    checkpoint = cast(dict[str, object], validated)
    if "next_cursor" in checkpoint or "consumed_cursors" in checkpoint:
        raise ValueError("checkpoint contains a plaintext remote cursor")
    attempt_id = checkpoint.get("attempt_id")
    if attempt_id is not None:
        validate_identifier(attempt_id, "attempt_id", max_length=64)
    committed_page_count = checkpoint.get("committed_page_count")
    if committed_page_count is not None and (
        type(committed_page_count) is not int or committed_page_count < 0
    ):
        raise ValueError("checkpoint committed_page_count must be non-negative")
    return checkpoint


def _cursor_lineage_hash(previous: str, cursor: str | None) -> str:
    """Extend an irreversible cursor lineage digest without persisting cursor text."""

    marker = "<end>" if cursor is None else cursor
    digest = hashlib.sha256(f"{previous}|{marker}".encode()).hexdigest()
    return f"sha256-{digest}"


class FundCollector:
    """Capability-gated collector that captures before normalization."""

    _CAPABILITIES = {
        "metadata": Capability.FETCH_FUND_METADATA,
        "nav": Capability.FETCH_FUND_NAV,
        "inav": Capability.FETCH_FUND_INAV,
        "benchmark": Capability.FETCH_FUND_BENCHMARK,
        "fees": Capability.FETCH_FUND_FEES,
    }

    def __init__(
        self,
        provider: Provider,
        raw_storage: RawStorage,
        persistence: FundPersistence | None = None,
        *,
        now: datetime | None = None,
        as_of: datetime | None = None,
        schema_version: str = "precious-metals-fund-v1",
        normalizer_version: str = "precious-metals-normalizer-v1",
    ) -> None:
        self._provider = provider
        self._raw_storage = raw_storage
        self._persistence: FundPersistence = (
            persistence if persistence is not None else InMemoryFundStorage()
        )
        self._now = now or datetime.now(UTC)
        self._as_of = as_of
        self._schema_version = schema_version
        self._normalizer_version = normalizer_version

    def collect(
        self,
        kind: Literal["metadata", "nav", "inav", "benchmark", "fees"],
        exchange: str,
        *,
        context: LeaseContext | None = None,
        collection_date: str | None = None,
        run_id: str | None = None,
        source_revision: str | None = None,
        attempt_id: str | None = None,
    ) -> FundCollectionResult:
        validate_fund_endpoint_kind(kind)
        if source_revision == SOURCE_REVISION_SENTINEL:
            raise ValueError("source_revision sentinel is reserved for provider absence")
        capability = self._CAPABILITIES[kind]
        self._provider.require(capability)
        date_value = collection_date or self._now.date().isoformat()
        task_id = context.task_id if context is not None else "default"
        checkpoint_key = fund_checkpoint_key(task_id, kind, exchange)
        prior_checkpoint = _validated_checkpoint(self._persistence, checkpoint_key)
        for field_name, expected in (
            ("kind", kind),
            ("exchange", exchange),
            ("date", date_value),
        ):
            prior_value = prior_checkpoint.get(field_name)
            if prior_value is not None and prior_value != expected:
                raise ValueError(f"checkpoint {field_name} does not match collection route")
        stored_run_id = prior_checkpoint.get("run_id")
        if stored_run_id is not None and not isinstance(stored_run_id, str):
            raise ValueError("checkpoint run_id must be a string")
        active_run_id = run_id or stored_run_id
        active_attempt_id = attempt_id or uuid4().hex
        validate_identifier(active_attempt_id, "attempt_id", max_length=64)
        # Every invocation is a fresh at-least-once rescan attempt.  A
        # checkpoint is evidence of the prior attempt, never a cursor resume
        # instruction for the new one.
        committed_page_count = 0
        lineage_hash = "sha256-" + "0" * 64
        prior_lineage_hash = prior_checkpoint.get("cursor_lineage_hash")
        if prior_lineage_hash is not None and (
            not isinstance(prior_lineage_hash, str) or not prior_lineage_hash.startswith("sha256-")
        ):
            raise ValueError("checkpoint cursor lineage hash is invalid")
        if source_revision is not None:
            validate_identifier(source_revision, "source_revision", max_length=64)
        active_source_revision = source_revision
        stored_source_revision = prior_checkpoint.get("source_revision")
        if stored_source_revision is not None:
            if not isinstance(stored_source_revision, str):
                raise ValueError("checkpoint source_revision must be a string")
            if (
                active_source_revision is not None
                and active_source_revision != stored_source_revision
            ):
                raise ValueError("checkpoint source_revision does not match collection route")
            if active_source_revision is None:
                active_source_revision = stored_source_revision
        cursor: str | None = None
        consumed: set[str] = set()
        accepted: list[object] = []
        rejected: list[RejectedObservation] = []
        quality_events: list[FundQualityEvent] = []
        semantic_values: dict[str, tuple[object, str]] = {}
        normalized_kind = kind
        for prior in self._persistence.observations(normalized_kind):
            prior_key = _semantic_key(prior)
            prior_evidence = getattr(prior, "evidence", None)
            prior_record_id = getattr(prior_evidence, "record_id", None)
            if isinstance(prior_record_id, str):
                semantic_values[prior_key] = (_semantic_value(prior), prior_record_id)
        while True:
            response = self._fetch_page(kind, exchange, cursor)
            response_run_id = response.run_id
            if (
                active_run_id is not None
                and response_run_id is not None
                and response_run_id != active_run_id
            ):
                raise ValueError("provider response run_id does not match collection route")
            active_run_id = active_run_id or response_run_id or uuid4().hex
            response_source_revision = (
                response.source_revision
                if response.source_revision is not None
                else SOURCE_REVISION_SENTINEL
            )
            if response.source_revision == SOURCE_REVISION_SENTINEL:
                raise ValueError("provider response source_revision uses reserved sentinel")
            if (
                active_source_revision is not None
                and response_source_revision != active_source_revision
            ):
                raise ValueError(
                    "provider response source_revision does not match collection route"
                )
            active_source_revision = active_source_revision or response_source_revision
            response_endpoint_kind = response.endpoint_kind or kind
            if response_endpoint_kind not in FUND_ENDPOINT_KINDS:
                raise ValueError("provider response endpoint_kind is invalid")
            if response_endpoint_kind != kind:
                raise ValueError("provider response endpoint_kind does not match collection kind")
            if cursor is not None:
                if cursor in consumed:
                    raise CursorLoopError("provider cursor was already consumed")
                consumed.add(cursor)
            captured_ingest = response.ingest_time or self._now
            captured_available = response.available_time or captured_ingest
            manifest = self._raw_storage.put(
                response.source,
                date_value,
                response.request,
                response.body,
                response.content_type,
                capture_id=response.capture_id,
                ingest_time=captured_ingest,
                available_time=captured_available,
                endpoint_kind=kind,
                run_id=active_run_id,
                source_revision=(
                    None if response.source_revision is None else active_source_revision
                ),
                source_revision_absent=response.source_revision is None,
                attempt_id=active_attempt_id,
                page_ordinal=committed_page_count,
            )
            if (
                manifest.endpoint_kind != kind
                or manifest.run_id != active_run_id
                or manifest.source_revision != active_source_revision
                or manifest.attempt_id != active_attempt_id
                or manifest.page_ordinal != committed_page_count
            ):
                raise CaptureConflictError(
                    "raw capture manifest lineage does not match active collection attempt"
                )
            payload = self._raw_storage.get(
                manifest.object_id,
                checksum=manifest.checksum,
                size=manifest.size,
            )
            decoded = decode_json(payload)
            if not isinstance(decoded, Mapping):
                raise ValueError("raw fund response must decode to an object")
            trusted_context = TrustedFundContext.from_manifest(
                manifest,
                processing_time=self._now,
                schema_version=self._schema_version,
                normalizer_version=self._normalizer_version,
            )
            decoded_map = cast(Mapping[str, object], decoded)
            raw_items_value = decoded_map.get("items")
            if not isinstance(raw_items_value, list):
                raise ValueError("raw fund response items must be a list")
            raw_items = cast(list[object], raw_items_value)
            raw_next_cursor = decoded_map.get("nextCursor")
            if raw_next_cursor is not None and not isinstance(raw_next_cursor, str):
                raise ValueError("raw fund response nextCursor must be a string or null")
            next_cursor = raw_next_cursor
            if next_cursor is not None and (next_cursor == cursor or next_cursor in consumed):
                raise CursorLoopError("provider returned a repeated pagination cursor")
            lineage_hash = _cursor_lineage_hash(lineage_hash, next_cursor)
            for ordinal, item in enumerate(raw_items):
                if not isinstance(item, Mapping):
                    envelope = EvidenceEnvelope(
                        raw_capture_id=trusted_context.raw_capture_id,
                        raw_object_id=trusted_context.raw_object_id,
                        checksum=trusted_context.checksum,
                        source=trusted_context.source,
                        source_revision=trusted_context.source_revision,
                        schema_version=trusted_context.schema_version,
                        normalizer_version=trusted_context.normalizer_version,
                        payload_digest=hashlib.sha256(_json_bytes(item)).hexdigest(),
                        item_ordinal=ordinal,
                        ingest_time=trusted_context.ingest_time,
                        available_time=trusted_context.available_time,
                        processing_time=trusted_context.processing_time,
                    )
                    rejected.append(
                        RejectedObservation(
                            record_id=envelope.record_id,
                            kind=kind,
                            payload=controlled_rejection_payload(
                                item, digest=envelope.payload_digest
                            ),
                            reason="item_not_mapping",
                            evidence=envelope,
                        )
                    )
                    continue
                item_record = cast(Mapping[str, object], item)
                try:
                    normalized = normalize_fund_observation(
                        normalized_kind,
                        item_record,
                        trusted_context=trusted_context,
                        item_ordinal=ordinal,
                        payload_digest=hashlib.sha256(_json_bytes(item_record)).hexdigest(),
                    )
                    valid, issues = validate_fund_observation(
                        normalized,
                        now=self._now,
                        as_of=self._as_of,
                    )
                    if not valid:
                        raise ValueError("; ".join(issues))
                except (TypeError, ValueError, KeyError):
                    # Build a valid envelope after normalization failed so the
                    # rejection remains replayable and evidence-linked.
                    envelope = EvidenceEnvelope(
                        raw_capture_id=trusted_context.raw_capture_id,
                        raw_object_id=trusted_context.raw_object_id,
                        checksum=trusted_context.checksum,
                        source=trusted_context.source,
                        source_revision=trusted_context.source_revision,
                        schema_version=trusted_context.schema_version,
                        normalizer_version=trusted_context.normalizer_version,
                        payload_digest=hashlib.sha256(_json_bytes(item_record)).hexdigest(),
                        item_ordinal=ordinal,
                        ingest_time=trusted_context.ingest_time,
                        available_time=trusted_context.available_time,
                        processing_time=trusted_context.processing_time,
                    )
                    rejected.append(
                        RejectedObservation(
                            record_id=envelope.record_id,
                            kind=kind,
                            payload=controlled_rejection_payload(
                                item_record, digest=envelope.payload_digest
                            ),
                            reason="normalization_error",
                            evidence=envelope,
                        )
                    )
                    continue
                accepted.append(normalized)
                semantic_key = _semantic_key(normalized)
                semantic_value = _semantic_value(normalized)
                prior = semantic_values.get(semantic_key)
                if prior is not None and prior[0] != semantic_value:
                    quality_events.append(
                        _conflict_event(
                            semantic_key,
                            (prior[1], normalized.evidence.record_id),
                            self._now,
                        )
                    )
                else:
                    semantic_values[semantic_key] = (
                        semantic_value,
                        normalized.evidence.record_id,
                    )

            committed_page_count += 1
            checkpoint: dict[str, object] = {
                "kind": kind,
                "exchange": exchange,
                "date": date_value,
                "run_id": active_run_id,
                "source_revision": active_source_revision,
                "attempt_id": active_attempt_id,
                "committed_page_count": committed_page_count,
                "last_capture_id": manifest.capture_id,
                "cursor_lineage_hash": lineage_hash,
                "complete": next_cursor is None,
            }
            validated_checkpoint = validate_json_payload(checkpoint, "checkpoint")
            if not isinstance(validated_checkpoint, dict):
                raise ValueError("checkpoint must be a JSON object")
            checkpoint = cast(dict[str, object], validated_checkpoint)
            # A committed page and its checkpoint are one persistence action.
            self._persistence.commit_page(
                accepted=tuple(accepted),
                rejected=tuple(rejected),
                quality_events=tuple(quality_events),
                checkpoint=checkpoint,
                context=context,
                checkpoint_key=checkpoint_key,
            )
            if next_cursor is None:
                return FundCollectionResult(
                    kind=kind,
                    accepted=accepted,
                    rejected=rejected,
                    quality_events=quality_events,
                    checkpoint=checkpoint,
                )
            cursor = next_cursor

    def _fetch_page(
        self,
        kind: str,
        exchange: str,
        cursor: str | None,
    ) -> RawFundProviderResponse:
        method_names = {
            "metadata": ("fetch_fund_metadata",),
            "nav": ("fetch_fund_nav", "fetch_navs"),
            "inav": ("fetch_fund_inav", "fetch_inavs"),
            "benchmark": ("fetch_fund_benchmark", "fetch_benchmark_metadata"),
            "fees": ("fetch_fund_fees", "fetch_fee_metadata"),
        }[kind]
        method = next(
            (
                getattr(self._provider, name, None)
                for name in method_names
                if hasattr(self._provider, name)
            ),
            None,
        )
        if not callable(method):
            raise NotImplementedError(f"provider does not expose {kind} endpoint")
        try:
            result = method(exchange, cursor)
        except ProviderError as error:
            # Translate only the provider taxonomy at the transport boundary.
            # Non-provider/runtime failures remain opaque to the collector and
            # are recorded as ``internal`` by TaskScheduler without persisting
            # their message.
            raise map_provider_error(error) from None
        if isinstance(result, RawFundProviderResponse):
            return result
        raise TypeError("fund provider must return RawFundProviderResponse")

    def replay_raw(
        self,
        source: str,
        collection_date: str,
        handler: Callable[[RawObjectManifest, object], None],
    ) -> int:
        return replay_json(self._raw_storage, source, collection_date, handler)

    def replay_captures(
        self,
        kind: Literal["metadata", "nav", "inav", "benchmark", "fees"],
        source: str,
        collection_date: str,
        *,
        context: LeaseContext | None = None,
        exchange: str = "SH",
        run_id: str | None = None,
        source_revision: str | None = None,
        attempt_id: str | None = None,
    ) -> FundCollectionResult:
        """Replay one complete route through the normal collector path.

        Raw bytes are read and verified before a replay provider is built.  The
        original capture identity and bytes are passed back to ``RawStorage``;
        idempotent manifests therefore do not create duplicate observations.
        """
        validate_fund_endpoint_kind(kind)
        if not run_id or not source_revision or not attempt_id:
            raise ValueError("replay requires run_id, source_revision, and attempt_id route")
        validate_identifier(run_id, "run_id", max_length=64)
        validate_identifier(source_revision, "source_revision", max_length=64)
        validate_identifier(attempt_id, "attempt_id", max_length=64)
        manifests = self._raw_storage.list(source, collection_date)
        selected: list[RawObjectManifest] = []
        for manifest in manifests:
            route = RawObjectManifest.route_identity(manifest.to_dict())
            if route is None:
                raise ValueError("legacy capture is missing replay route identity")
            endpoint_kind, manifest_run_id, manifest_revision, manifest_attempt, _page_ordinal = (
                route
            )
            if endpoint_kind != kind:
                continue
            if (
                manifest_run_id != run_id
                or manifest_revision != source_revision
                or manifest_attempt != attempt_id
            ):
                continue
            selected.append(manifest)
        if not selected:
            raise ValueError("no captures found for replay attempt")
        selected.sort(key=lambda item: cast(int, item.page_ordinal))
        ordinals = [cast(int, item.page_ordinal) for item in selected]
        if len(set(ordinals)) != len(ordinals):
            raise ValueError("replay attempt contains duplicate page ordinal")
        if ordinals != list(range(len(ordinals))):
            raise ValueError("replay attempt page ordinals must be zero-based and contiguous")
        pages: list[RawFundProviderResponse] = []
        for manifest in selected:
            content = self._raw_storage.get(
                manifest.object_id,
                checksum=manifest.checksum,
                size=manifest.size,
            )
            decoded = decode_json(content)
            if not isinstance(decoded, dict):
                raise ValueError("replay capture must decode to an object")
            decoded_map = cast(dict[str, object], decoded)
            if not isinstance(decoded_map.get("items"), list):
                raise ValueError("replay capture items must be a list")
            pages.append(
                RawFundProviderResponse(
                    body=content,
                    source=manifest.source,
                    request=manifest.request_identity,
                    content_type=manifest.content_type,
                    capture_id=manifest.capture_id,
                    ingest_time=manifest.ingest_time,
                    available_time=manifest.available_time,
                    endpoint_kind=manifest.endpoint_kind,
                    run_id=manifest.run_id,
                    source_revision=(
                        None
                        if manifest.source_revision == SOURCE_REVISION_SENTINEL
                        else manifest.source_revision
                    ),
                )
            )
        replay_provider = _ReplayProvider(kind, pages)
        replay_collector = FundCollector(
            replay_provider,
            self._raw_storage,
            self._persistence,
            now=self._now,
            as_of=self._as_of,
            schema_version=self._schema_version,
            normalizer_version=self._normalizer_version,
        )
        return replay_collector.collect(
            kind,
            exchange,
            context=context,
            collection_date=collection_date,
            run_id=run_id,
            source_revision=(
                None if source_revision == SOURCE_REVISION_SENTINEL else source_revision
            ),
            attempt_id=attempt_id,
        )


class _ReplayProvider(Provider):
    """Cursor adapter over verified raw captures used only during replay."""

    def __init__(self, kind: str, pages: list[RawFundProviderResponse]) -> None:
        if not pages:
            raise ValueError("replay requires at least one captured page")
        self.source = pages[0].source if pages else "replay"
        self._kind = kind
        self._pages = pages
        self._cursor_index: dict[str, int] = {}
        for index, page in enumerate(pages[:-1]):
            decoded = decode_json(page.body)
            if not isinstance(decoded, Mapping):
                raise ValueError("replay capture must decode to an object")
            decoded_mapping = cast(Mapping[str, object], decoded)
            next_cursor = decoded_mapping.get("nextCursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                raise ValueError("replay capture page is missing a next cursor")
            if next_cursor in self._cursor_index:
                raise ValueError("replay capture contains duplicate cursors")
            self._cursor_index[next_cursor] = index + 1
        final_decoded = decode_json(pages[-1].body)
        if not isinstance(final_decoded, Mapping):
            raise ValueError("replay capture must decode to an object")
        final_next_cursor = cast(Mapping[str, object], final_decoded).get("nextCursor")
        if final_next_cursor is not None:
            raise ValueError("replay attempt is incomplete: final page has a next cursor")

    def capabilities(self) -> frozenset[Capability]:
        capability = {
            "metadata": Capability.FETCH_FUND_METADATA,
            "nav": Capability.FETCH_FUND_NAV,
            "inav": Capability.FETCH_FUND_INAV,
            "benchmark": Capability.FETCH_FUND_BENCHMARK,
            "fees": Capability.FETCH_FUND_FEES,
        }[self._kind]
        return frozenset({capability})

    def _page(self, cursor: str | None) -> RawFundProviderResponse:
        if cursor is None:
            index = 0
        else:
            index = self._cursor_index.get(cursor)
            if index is None:
                raise ValueError("replay cursor is unknown")
        if index >= len(self._pages):
            raise ValueError("replay cursor points beyond captured pages")
        return self._pages[index]

    def fetch_fund_metadata(
        self, exchange: str, cursor: str | None = None
    ) -> RawFundProviderResponse:
        return self._page(cursor)

    def fetch_fund_nav(self, exchange: str, cursor: str | None = None) -> RawFundProviderResponse:
        return self._page(cursor)

    def fetch_fund_inav(self, exchange: str, cursor: str | None = None) -> RawFundProviderResponse:
        return self._page(cursor)

    def fetch_fund_benchmark(
        self, exchange: str, cursor: str | None = None
    ) -> RawFundProviderResponse:
        return self._page(cursor)

    def fetch_fund_fees(self, exchange: str, cursor: str | None = None) -> RawFundProviderResponse:
        return self._page(cursor)


PreciousMetalsFundCollector = FundCollector
FundMetadataCollector = FundCollector


def _conflict_event(
    semantic_key: str, evidence_ids: tuple[str, ...], created_at: datetime
) -> FundQualityEvent:
    event_id = (
        "fund-conflict-"
        + hashlib.sha256(f"{semantic_key}|{'|'.join(evidence_ids)}".encode()).hexdigest()
    )
    return FundQualityEvent(
        event_id=event_id,
        kind="SOURCE_CONFLICT",
        semantic_key=semantic_key,
        detail="multiple source observations disagree; no canonical value selected",
        evidence_ids=evidence_ids,
        created_at=created_at,
    )
