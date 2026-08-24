"""Fail-closed event extraction consumer."""

from __future__ import annotations

import hashlib
import json

from event_core.models import (
    MARKET_EVENT_SCHEMA_VERSION,
    EventEvidence,
    MarketEvent,
    ModelProvenance,
    ProducerType,
)

from intelligence_engine.llm import RegistryError, ResolvedProfile, VersionRegistry
from intelligence_engine.pipelines.events.candidate import (
    EVENT_CANDIDATE_SCHEMA_VERSION,
    CandidateJsonError,
    CandidateValidationError,
    EventCandidate,
    parse_event_candidate,
)
from intelligence_engine.pipelines.events.models import (
    EVENT_EXTRACTION_PIPELINE_VERSION,
    MAX_PROVIDER_OUTPUT_CHARACTERS,
    CommitDisposition,
    ExtractionRequest,
    ExtractionResult,
    ExtractionStatus,
    ExtractionStore,
    ExtractionStoreTransientError,
    FailureReason,
    FailureRecord,
    ModelGateway,
    ModelPermanentError,
    ModelRateLimitError,
    ModelTimeoutError,
    ModelTransientError,
    ProviderInvocation,
    RetryPolicy,
)


def _configuration_fingerprint(resolved: ResolvedProfile) -> str:
    payload = {
        "candidateSchemaVersion": EVENT_CANDIDATE_SCHEMA_VERSION,
        "pipelineVersion": EVENT_EXTRACTION_PIPELINE_VERSION,
        "resolvedConfigurationFingerprint": resolved.configuration_fingerprint,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _evidence_id(
    content_version_id: str,
    start_offset: int,
    end_offset: int,
    excerpt: str,
) -> str:
    identity = f"{content_version_id}\x1f{start_offset}\x1f{end_offset}\x1f{excerpt}"
    return hashlib.sha256(identity.encode()).hexdigest()


class EventExtractionConsumer:
    """Validate provider output before an idempotent fact-layer commit."""

    def __init__(
        self,
        registry: VersionRegistry,
        gateway: ModelGateway,
        store: ExtractionStore,
        *,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        if type(registry) is not VersionRegistry:
            raise TypeError("registry must be a VersionRegistry")
        self._registry = registry
        self._gateway = gateway
        self._store = store
        self._retry_policy = retry_policy or RetryPolicy()

    def handle(self, request: ExtractionRequest) -> ExtractionResult:
        """Handle one queue attempt and return an explicit ack/retry disposition."""
        if type(request) is not ExtractionRequest:
            raise TypeError("request must be an ExtractionRequest")
        try:
            committed = self._store.find_committed(request.idempotency_key)
        except ExtractionStoreTransientError:
            return self._transient(
                request,
                FailureReason.STORE_TRANSIENT,
                "store_lookup_transient",
            )
        if committed is not None:
            return self._duplicate(request, committed)
        if not request.document.is_usable(request.decision_time):
            return self._reject(
                request,
                FailureReason.SOURCE_UNAVAILABLE,
                "source_not_usable_at_decision_time",
            )

        try:
            resolved = self._registry.resolve(
                request.profile_id,
                routing_key=request.routing_key,
                decision_time=request.decision_time,
            )
        except RegistryError:
            return self._reject(
                request,
                FailureReason.CONFIGURATION_ERROR,
                "profile_resolution_failed",
            )
        if resolved.prompt.variables != ("content",):
            return self._reject(
                request,
                FailureReason.CONFIGURATION_ERROR,
                "unsupported_prompt_variables",
                resolved=resolved,
            )
        if resolved.profile.output_schema_version != MARKET_EVENT_SCHEMA_VERSION:
            return self._reject(
                request,
                FailureReason.CONFIGURATION_ERROR,
                "unsupported_final_schema",
                resolved=resolved,
            )

        configuration_fingerprint = _configuration_fingerprint(resolved)
        invocation = ProviderInvocation(
            request_id=request.request_id,
            extraction_run_id=request.extraction_run_id,
            attempt=request.attempt,
            rendered_prompt=resolved.prompt.template.replace(
                "{{content}}",
                request.document.raw_text,
            ),
            model=resolved.model,
            final_output_schema_version=resolved.profile.output_schema_version,
            configuration_fingerprint=configuration_fingerprint,
        )
        try:
            raw_output = self._gateway.generate(invocation)
        except ModelTimeoutError:
            return self._transient(
                request,
                FailureReason.MODEL_TIMEOUT,
                "provider_timeout",
                resolved=resolved,
                configuration_fingerprint=configuration_fingerprint,
            )
        except ModelRateLimitError:
            return self._transient(
                request,
                FailureReason.MODEL_RATE_LIMIT,
                "provider_rate_limit",
                resolved=resolved,
                configuration_fingerprint=configuration_fingerprint,
            )
        except ModelTransientError:
            return self._transient(
                request,
                FailureReason.MODEL_TRANSIENT,
                "provider_transient",
                resolved=resolved,
                configuration_fingerprint=configuration_fingerprint,
            )
        except ModelPermanentError:
            return self._reject(
                request,
                FailureReason.MODEL_PERMANENT,
                "provider_permanent",
                resolved=resolved,
                configuration_fingerprint=configuration_fingerprint,
            )
        except Exception:
            return self._reject(
                request,
                FailureReason.MODEL_PERMANENT,
                "provider_unclassified_exception",
                resolved=resolved,
                configuration_fingerprint=configuration_fingerprint,
            )

        if type(raw_output) is not str:
            return self._reject(
                request,
                FailureReason.INVALID_CANDIDATE,
                "provider_output_not_string",
                resolved=resolved,
                configuration_fingerprint=configuration_fingerprint,
            )
        if len(raw_output) > MAX_PROVIDER_OUTPUT_CHARACTERS:
            return self._reject(
                request,
                FailureReason.RESPONSE_TOO_LARGE,
                "provider_output_too_large",
                raw_output=raw_output,
                resolved=resolved,
                configuration_fingerprint=configuration_fingerprint,
            )
        try:
            candidate = parse_event_candidate(raw_output)
        except CandidateJsonError:
            return self._reject(
                request,
                FailureReason.INVALID_JSON,
                "invalid_provider_json",
                raw_output=raw_output,
                resolved=resolved,
                configuration_fingerprint=configuration_fingerprint,
            )
        except CandidateValidationError:
            return self._reject(
                request,
                FailureReason.INVALID_CANDIDATE,
                "candidate_contract_failed",
                raw_output=raw_output,
                resolved=resolved,
                configuration_fingerprint=configuration_fingerprint,
            )

        if candidate.confidence_bps < resolved.profile.minimum_confidence_bps:
            return self._reject(
                request,
                FailureReason.LOW_CONFIDENCE,
                "below_registered_confidence_threshold",
                raw_output=raw_output,
                resolved=resolved,
                configuration_fingerprint=configuration_fingerprint,
            )
        try:
            event = self._build_event(
                request,
                candidate,
                resolved,
                configuration_fingerprint,
            )
        except IndexError:
            return self._reject(
                request,
                FailureReason.EVIDENCE_MISMATCH,
                "evidence_outside_source",
                raw_output=raw_output,
                resolved=resolved,
                configuration_fingerprint=configuration_fingerprint,
            )
        except LookupError:
            return self._reject(
                request,
                FailureReason.EVIDENCE_MISMATCH,
                "evidence_excerpt_mismatch",
                raw_output=raw_output,
                resolved=resolved,
                configuration_fingerprint=configuration_fingerprint,
            )
        except (TypeError, ValueError):
            return self._reject(
                request,
                FailureReason.EVENT_VALIDATION,
                "market_event_domain_validation_failed",
                raw_output=raw_output,
                resolved=resolved,
                configuration_fingerprint=configuration_fingerprint,
            )

        stored = ExtractionResult(
            status=ExtractionStatus.STORED,
            request_id=request.request_id,
            extraction_run_id=request.extraction_run_id,
            idempotency_key=request.idempotency_key,
            attempt=request.attempt,
            recorded_at=request.processing_time,
            event=event,
            deployment_id=resolved.deployment.deployment_id,
            configuration_fingerprint=configuration_fingerprint,
        )
        try:
            disposition = self._store.commit_validated(
                request.idempotency_key,
                event,
                stored,
            )
        except ExtractionStoreTransientError:
            return self._transient(
                request,
                FailureReason.STORE_TRANSIENT,
                "store_commit_transient",
                raw_output=raw_output,
                resolved=resolved,
                configuration_fingerprint=configuration_fingerprint,
            )
        if disposition is CommitDisposition.COMMITTED:
            return stored
        existing = self._store.find_committed(request.idempotency_key)
        if existing is None:
            return self._transient(
                request,
                FailureReason.STORE_TRANSIENT,
                "store_commit_race_unresolved",
                resolved=resolved,
                configuration_fingerprint=configuration_fingerprint,
            )
        return self._duplicate(
            request,
            existing,
            resolved=resolved,
            configuration_fingerprint=configuration_fingerprint,
        )

    def _build_event(
        self,
        request: ExtractionRequest,
        candidate: EventCandidate,
        resolved: ResolvedProfile,
        configuration_fingerprint: str,
    ) -> MarketEvent:
        evidence: list[EventEvidence] = []
        source = request.document.raw_text
        for span in candidate.evidence_spans:
            if span.end_offset > len(source):
                raise IndexError("evidence span outside source")
            if source[span.start_offset : span.end_offset] != span.excerpt:
                raise LookupError("evidence excerpt mismatch")
            evidence.append(
                EventEvidence(
                    evidence_id=_evidence_id(
                        request.document.content_version_id,
                        span.start_offset,
                        span.end_offset,
                        span.excerpt,
                    ),
                    content_record_id=request.document.content_record_id,
                    content_version_id=request.document.content_version_id,
                    source_id=request.document.source_id,
                    source_version=request.document.source_version,
                    available_time=request.document.available_time,
                    start_offset=span.start_offset,
                    end_offset=span.end_offset,
                    excerpt=span.excerpt,
                )
            )
        return MarketEvent(
            event_type=candidate.event_type,
            headline=candidate.headline,
            summary=candidate.summary,
            occur_time=candidate.occur_time,
            publish_time=request.document.publish_time,
            available_time=max(request.document.available_time, request.processing_time),
            instrument_ids=candidate.instrument_ids,
            sector_ids=candidate.sector_ids,
            evidence=tuple(evidence),
            model_provenance=ModelProvenance(
                producer_type=ProducerType.MODEL,
                provider=resolved.model.provider_id,
                model_id=resolved.model.model_id,
                model_version=resolved.model.version,
                prompt_version=f"{resolved.prompt.prompt_id}@{resolved.prompt.version}",
                output_schema_version=resolved.profile.output_schema_version,
                configuration_fingerprint=configuration_fingerprint,
                extraction_run_id=request.extraction_run_id,
                processing_time=request.processing_time,
            ),
            confidence_bps=candidate.confidence_bps,
        )

    def _duplicate(
        self,
        request: ExtractionRequest,
        event: MarketEvent,
        *,
        resolved: ResolvedProfile | None = None,
        configuration_fingerprint: str | None = None,
    ) -> ExtractionResult:
        result = ExtractionResult(
            status=ExtractionStatus.DUPLICATE,
            request_id=request.request_id,
            extraction_run_id=request.extraction_run_id,
            idempotency_key=request.idempotency_key,
            attempt=request.attempt,
            recorded_at=request.processing_time,
            event=event,
            deployment_id=resolved.deployment.deployment_id if resolved else None,
            configuration_fingerprint=configuration_fingerprint,
        )
        self._store.record_outcome(result)
        return result

    def _reject(
        self,
        request: ExtractionRequest,
        reason: FailureReason,
        detail_code: str,
        *,
        raw_output: str | None = None,
        resolved: ResolvedProfile | None = None,
        configuration_fingerprint: str | None = None,
    ) -> ExtractionResult:
        result = ExtractionResult(
            status=ExtractionStatus.REJECTED,
            request_id=request.request_id,
            extraction_run_id=request.extraction_run_id,
            idempotency_key=request.idempotency_key,
            attempt=request.attempt,
            recorded_at=request.processing_time,
            failure=FailureRecord(reason, detail_code, raw_output),
            deployment_id=resolved.deployment.deployment_id if resolved else None,
            configuration_fingerprint=configuration_fingerprint,
        )
        self._store.record_outcome(result)
        return result

    def _transient(
        self,
        request: ExtractionRequest,
        reason: FailureReason,
        detail_code: str,
        *,
        raw_output: str | None = None,
        resolved: ResolvedProfile | None = None,
        configuration_fingerprint: str | None = None,
    ) -> ExtractionResult:
        if request.attempt >= self._retry_policy.max_attempts:
            return self._reject(
                request,
                FailureReason.RETRY_EXHAUSTED,
                f"{detail_code}_exhausted",
                raw_output=raw_output,
                resolved=resolved,
                configuration_fingerprint=configuration_fingerprint,
            )
        result = ExtractionResult(
            status=ExtractionStatus.RETRY_SCHEDULED,
            request_id=request.request_id,
            extraction_run_id=request.extraction_run_id,
            idempotency_key=request.idempotency_key,
            attempt=request.attempt,
            recorded_at=request.processing_time,
            failure=FailureRecord(reason, detail_code, raw_output),
            retry_at=request.processing_time + self._retry_policy.delay_after(request.attempt),
            deployment_id=resolved.deployment.deployment_id if resolved else None,
            configuration_fingerprint=configuration_fingerprint,
        )
        self._store.record_outcome(result)
        return result


__all__ = ["EventExtractionConsumer"]
