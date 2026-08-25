"""PIT-gated fake-LLM claim extraction consumer."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Protocol

from kol_core.extraction import ClaimExtractionCandidate

from .candidate import parse_claim_extraction_response
from .models import (
    ClaimAuditRecord,
    ClaimExtractionPolicy,
    ClaimExtractionRequest,
    ClaimFailureReason,
    ClaimProcessResult,
    ClaimProcessStatus,
    ClaimRateLimitError,
    ClaimStoreTransientError,
    ClaimTemporaryUnavailableError,
    ClaimTimeoutError,
)


class ClaimExtractor(Protocol):
    def extract(self, request: ClaimExtractionRequest) -> object: ...


class ClaimCandidateStore(Protocol):
    def find_committed(self, key: str) -> ClaimExtractionCandidate | None: ...
    def claim(self, key: str) -> ClaimProcessStatus: ...
    def append(
        self, key: str, candidate: ClaimExtractionCandidate, expected_previous: str | None
    ) -> ClaimProcessStatus: ...
    def latest(self, candidate_id: str) -> ClaimExtractionCandidate | None: ...
    def as_of(
        self, candidate_id: str, decision_time: datetime
    ) -> ClaimExtractionCandidate | None: ...
    def release(self, key: str) -> None: ...

    def append_source_tombstone(
        self,
        source_kind: str,
        source_id: str,
        source_revision_id: str,
        effective_time: datetime,
        reason: str,
    ) -> tuple[ClaimExtractionCandidate, ...]: ...


class ClaimAuditSink(Protocol):
    def append(self, record: ClaimAuditRecord) -> ClaimAuditRecord: ...


def _audit_id(
    request: ClaimExtractionRequest, policy: ClaimExtractionPolicy, status: str, reason: str
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "key": request.effective_idempotency_key(policy.fingerprint),
                "policy": policy.fingerprint,
                "reason": reason,
                "status": status,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class ClaimExtractionConsumer:
    def __init__(
        self,
        extractor: ClaimExtractor,
        store: ClaimCandidateStore,
        policy: ClaimExtractionPolicy | None = None,
        audit_sink: ClaimAuditSink | None = None,
    ) -> None:
        self.extractor = extractor
        self.store = store
        self.policy = ClaimExtractionPolicy() if policy is None else policy
        self.audit_sink = audit_sink

    def handle(self, request: ClaimExtractionRequest) -> ClaimProcessResult:
        key = request.effective_idempotency_key(self.policy.fingerprint)
        existing = self.store.find_committed(key)
        if existing is not None:
            return ClaimProcessResult(
                ClaimProcessStatus.ALREADY_COMMITTED,
                key,
                existing,
                audit=self._audit(request, "ALREADY_COMMITTED", "already_committed"),
            )
        claim = self.store.claim(key)
        if claim is ClaimProcessStatus.ALREADY_COMMITTED:
            existing = self.store.find_committed(key)
            return ClaimProcessResult(
                ClaimProcessStatus.ALREADY_COMMITTED,
                key,
                existing,
                audit=self._audit(request, "ALREADY_COMMITTED", "already_committed"),
            )
        if claim is ClaimProcessStatus.IN_PROGRESS:
            return ClaimProcessResult(
                ClaimProcessStatus.IN_PROGRESS,
                key,
                audit=self._audit(request, "IN_PROGRESS", "request_in_progress"),
            )
        unavailable = [
            item
            for item in request.sources
            if item.deleted or not item.authorized or item.available_time > request.decision_time
        ]
        if unavailable:
            self.store.release(key)
            return ClaimProcessResult(
                ClaimProcessStatus.REJECTED,
                key,
                failure=ClaimFailureReason.SOURCE_UNAVAILABLE,
                audit=self._audit(request, "REJECTED", "source_unavailable"),
            )
        try:
            raw = self.extractor.extract(request)
        except ClaimTimeoutError:
            return self._retry(request, key, ClaimFailureReason.MODEL_TIMEOUT, "model_timeout")
        except ClaimRateLimitError:
            return self._retry(
                request, key, ClaimFailureReason.MODEL_RATE_LIMIT, "model_rate_limit"
            )
        except ClaimTemporaryUnavailableError:
            return self._retry(
                request, key, ClaimFailureReason.MODEL_UNAVAILABLE, "model_unavailable"
            )
        except Exception:
            self.store.release(key)
            return ClaimProcessResult(
                ClaimProcessStatus.REJECTED,
                key,
                failure=ClaimFailureReason.EXTRACTOR_FAILURE,
                audit=self._audit(request, "REJECTED", "extractor_permanent_failure"),
            )
        try:
            candidate = parse_claim_extraction_response(raw, request, self.policy)
        except (TypeError, ValueError):
            self.store.release(key)
            return ClaimProcessResult(
                ClaimProcessStatus.REJECTED,
                key,
                failure=ClaimFailureReason.INVALID_CANDIDATE,
                audit=self._audit(request, "REJECTED", "invalid_candidate"),
            )
        if candidate.confidence_bps < self.policy.minimum_confidence_bps:
            self.store.release(key)
            return ClaimProcessResult(
                ClaimProcessStatus.REJECTED,
                key,
                failure=ClaimFailureReason.LOW_CONFIDENCE,
                audit=self._audit(request, "REJECTED", "low_confidence"),
            )
        try:
            previous = self.store.latest(candidate.candidate_id)
            status = self.store.append(
                key, candidate, None if previous is None else previous.revision_id
            )
        except ClaimStoreTransientError:
            self.store.release(key)
            return self._retry(request, key, ClaimFailureReason.STORE_TRANSIENT, "store_transient")
        except ValueError:
            self.store.release(key)
            return ClaimProcessResult(
                ClaimProcessStatus.REJECTED,
                key,
                failure=ClaimFailureReason.CONFLICT,
                audit=self._audit(request, "REJECTED", "conflict"),
            )
        if status is ClaimProcessStatus.ALREADY_COMMITTED:
            return ClaimProcessResult(
                status,
                key,
                self.store.find_committed(key),
                audit=self._audit(request, "ALREADY_COMMITTED", "already_committed"),
            )
        committed = self.store.find_committed(key)
        return ClaimProcessResult(
            ClaimProcessStatus.COMMITTED,
            key,
            committed,
            audit=self._audit(request, "COMMITTED", "committed"),
        )

    def _retry(
        self, request: ClaimExtractionRequest, key: str, reason: ClaimFailureReason, code: str
    ) -> ClaimProcessResult:
        self.store.release(key)
        status = (
            ClaimProcessStatus.RETRY_SCHEDULED
            if request.attempt < self.policy.max_attempts
            else ClaimProcessStatus.REJECTED
        )
        failure = (
            reason
            if status is ClaimProcessStatus.RETRY_SCHEDULED
            else ClaimFailureReason.RETRY_EXHAUSTED
        )
        return ClaimProcessResult(
            status,
            key,
            failure=failure,
            audit=self._audit(
                request,
                status.value,
                code if status is ClaimProcessStatus.RETRY_SCHEDULED else "retry_exhausted",
            ),
        )

    def _audit(
        self, request: ClaimExtractionRequest, status: str, reason: str
    ) -> ClaimAuditRecord | None:
        if self.audit_sink is None:
            return None
        record = ClaimAuditRecord(
            _audit_id(request, self.policy, status, reason),
            status,
            reason,
            request.effective_idempotency_key(self.policy.fingerprint),
            self.policy.fingerprint,
            request.resolved_profile.configuration_fingerprint,
            request.extraction_run_id,
            request.processing_time,
        )
        return self.audit_sink.append(record)


__all__ = ["ClaimAuditSink", "ClaimCandidateStore", "ClaimExtractor", "ClaimExtractionConsumer"]
