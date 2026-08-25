"""Deterministic in-memory fake ports for claim extraction."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

from kol_core.extraction import (
    ClaimExtractionCandidate,
    MediaExactAnchor,
    claim_extraction_candidate_payload,
    compute_candidate_revision_id_from_payload,
    deterministic_fingerprint,
)

from .models import ClaimAuditRecord, ClaimExtractionRequest, ClaimProcessStatus


class FakeClaimExtractor:
    def __init__(self, responses: Sequence[object]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    def extract(self, request: ClaimExtractionRequest) -> object:
        self.calls.append(request.request_id)
        if not self.responses:
            raise ValueError("fake extractor has no response")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class InMemoryClaimCandidateStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._requests: dict[str, tuple[str, ClaimExtractionCandidate]] = {}
        self._claims: dict[str, list[ClaimExtractionCandidate]] = {}
        self._in_progress: set[str] = set()
        self._source_index: dict[tuple[str, str, str], set[str]] = {}

    @staticmethod
    def _head(chain: list[ClaimExtractionCandidate]) -> ClaimExtractionCandidate | None:
        if not chain:
            return None
        child_revisions = {
            item.previous_revision_id for item in chain if item.previous_revision_id is not None
        }
        heads = [item for item in chain if item.revision_id not in child_revisions]
        if len(heads) != 1:
            raise ValueError("candidate revision graph has no unique head")
        return heads[0]

    @staticmethod
    def _source_keys(candidate: ClaimExtractionCandidate) -> set[tuple[str, str, str]]:
        keys: set[tuple[str, str, str]] = set()
        for anchor in candidate.anchors:
            keys.add(("content", anchor.content_id, anchor.content_revision_id))
            if isinstance(anchor, MediaExactAnchor):
                keys.add(("evidence", anchor.evidence_id, anchor.evidence_revision_id))
        return keys

    def _index(self, candidate: ClaimExtractionCandidate) -> None:
        for key in self._source_keys(candidate):
            self._source_index.setdefault(key, set()).add(candidate.candidate_id)

    def find_committed(self, key: str) -> ClaimExtractionCandidate | None:
        with self._lock:
            item = self._requests.get(key)
            return None if item is None else item[1]

    def claim(self, key: str) -> ClaimProcessStatus:
        with self._lock:
            if key in self._requests:
                return ClaimProcessStatus.ALREADY_COMMITTED
            if key in self._in_progress:
                return ClaimProcessStatus.IN_PROGRESS
            self._in_progress.add(key)
            return ClaimProcessStatus.COMMITTED

    def release(self, key: str) -> None:
        with self._lock:
            self._in_progress.discard(key)

    def append(
        self, key: str, candidate: ClaimExtractionCandidate, expected_previous: str | None
    ) -> ClaimProcessStatus:
        with self._lock:
            existing = self._requests.get(key)
            if existing is not None:
                if existing[1] != candidate:
                    raise ValueError("request conflict")
                self._in_progress.discard(key)
                return ClaimProcessStatus.ALREADY_COMMITTED
            chain = self._claims.setdefault(candidate.candidate_id, [])
            latest_candidate = self._head(chain)
            latest = None if latest_candidate is None else latest_candidate.revision_id
            if latest != expected_previous:
                raise ValueError("candidate revision predecessor conflict")
            if candidate.previous_revision_id not in (None, expected_previous):
                raise ValueError("candidate revision predecessor is not the latest")
            if any(item.revision_id == candidate.revision_id for item in chain):
                raise ValueError("candidate revision is duplicated")
            if (
                latest_candidate is not None
                and candidate.available_time <= latest_candidate.available_time
            ):
                raise ValueError("candidate available_time must increase along revisions")
            stored = replace(candidate, previous_revision_id=expected_previous)
            chain.append(stored)
            self._index(stored)
            self._requests[key] = (key, stored)
            self._in_progress.discard(key)
            return ClaimProcessStatus.COMMITTED

    def latest(self, candidate_id: str) -> ClaimExtractionCandidate | None:
        with self._lock:
            return self._head(self._claims.get(candidate_id, []))

    def as_of(self, candidate_id: str, decision_time: datetime) -> ClaimExtractionCandidate | None:
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            raise ValueError("decision_time must be timezone-aware")
        with self._lock:
            visible = [
                item
                for item in self._claims.get(candidate_id, [])
                if item.effective_time <= decision_time.astimezone(UTC)
            ]
            head = self._head(visible)
            if head is None or head.deleted:
                return None
            return head if head.visible_at(decision_time) else None

    def append_source_tombstone(
        self,
        source_kind: str,
        source_id: str,
        source_revision_id: str,
        effective_time: datetime,
        reason: str,
    ) -> tuple[ClaimExtractionCandidate, ...]:
        if source_kind not in {"content", "evidence"}:
            raise ValueError("unsupported source kind")
        if effective_time.tzinfo is None or effective_time.utcoffset() is None:
            raise ValueError("effective_time must be timezone-aware")
        if not reason.strip():
            raise ValueError("reason must be non-empty")
        source_key = (source_kind, source_id, source_revision_id)
        with self._lock:
            candidates: list[tuple[ClaimExtractionCandidate, ClaimExtractionCandidate, str]] = []
            for candidate_id in sorted(self._source_index.get(source_key, set())):
                head = self._head(self._claims.get(candidate_id, []))
                if head is None or head.deleted:
                    continue
                available = effective_time.astimezone(UTC)
                if available <= head.available_time:
                    raise ValueError("source lifecycle event is not after candidate head")
                tombstone = replace(
                    head,
                    revision_id="pending-revision",
                    previous_revision_id=head.revision_id,
                    available_time=available,
                    deleted=True,
                    deleted_at=available,
                    deletion_reason=reason,
                )
                tombstone_payload = claim_extraction_candidate_payload(tombstone)
                tombstone = replace(
                    tombstone,
                    revision_id=compute_candidate_revision_id_from_payload(tombstone_payload),
                )
                lifecycle_key = deterministic_fingerprint(
                    {
                        "candidateId": head.candidate_id,
                        "sourceKind": source_kind,
                        "sourceId": source_id,
                        "sourceRevisionId": source_revision_id,
                        "effectiveTime": available.isoformat(),
                        "reason": reason,
                    }
                )
                candidates.append((head, tombstone, lifecycle_key))
            committed: list[ClaimExtractionCandidate] = []
            for head, tombstone, lifecycle_key in candidates:
                self.append(lifecycle_key, tombstone, head.revision_id)
                latest = self._head(self._claims[tombstone.candidate_id])
                if latest is not None:
                    committed.append(latest)
            return tuple(committed)


class InMemoryClaimAuditSink:
    def __init__(self) -> None:
        self.records: list[ClaimAuditRecord] = []

    def append(self, record: ClaimAuditRecord) -> ClaimAuditRecord:
        self.records.append(record)
        return record


__all__ = ["FakeClaimExtractor", "InMemoryClaimAuditSink", "InMemoryClaimCandidateStore"]
