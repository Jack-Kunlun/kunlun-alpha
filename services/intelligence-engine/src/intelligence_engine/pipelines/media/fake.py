"""Deterministic in-memory ports used by the P4-N07 tests."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime

from intelligence_engine.llm.models import (
    Deployment,
    DeploymentOperation,
    ExtractionProfile,
    ModelSpec,
    PromptSpec,
    ResolvedProfile,
    SelectedVariant,
)

from .models import (
    MediaAuditRecord,
    MediaCheckpoint,
    MediaChunk,
    MediaClaimStatus,
    MediaFailureReason,
    MediaManifest,
    MediaProcessingRequest,
    MediaStoreClaim,
    MediaStreamMetadata,
    MediaTextEvidence,
)


class FakeMediaObjectReader:
    def __init__(
        self,
        objects: Mapping[tuple[str, str], bytes],
        *,
        chunk_specs: Mapping[tuple[str, str], Sequence[MediaChunk]] | None = None,
    ) -> None:
        self._objects = dict(objects)
        self._chunk_specs = {} if chunk_specs is None else dict(chunk_specs)
        self.reads: list[tuple[str, str]] = []
        self.iteration_indexes: list[int] = []

    def _chunks(self, manifest: MediaManifest, chunk_size_bytes: int) -> Iterator[MediaChunk]:
        key = (manifest.media_id, manifest.media_version)
        raw = self._objects.get(key)
        if raw is None:
            raise ValueError("media object not found")
        supplied = self._chunk_specs.get(key)
        if supplied is not None:
            supplied_chunks: list[MediaChunk] = []
            for index, supplied_chunk in enumerate(supplied):
                if type(supplied_chunk) is not MediaChunk or supplied_chunk.index != index:
                    raise ValueError("fake chunk layout is invalid")
                supplied_chunks.append(replace(supplied_chunk, index=index))
            if sum(len(chunk.data) for chunk in supplied_chunks) != len(raw):
                raise ValueError("fake chunk layout does not match raw media")
            offset = 0
            for chunk in supplied_chunks:
                if raw[offset : offset + len(chunk.data)] != chunk.data:
                    raise ValueError("fake chunk layout does not match raw media")
                offset += len(chunk.data)
                yield chunk
            return
        else:
            count = (len(raw) + chunk_size_bytes - 1) // chunk_size_bytes
            for index, offset in enumerate(range(0, len(raw), chunk_size_bytes)):
                data = raw[offset : offset + chunk_size_bytes]
                if manifest.duration_ms is None:
                    start_ms = end_ms = None
                else:
                    start_ms = (manifest.duration_ms * index) // count
                    end_ms = (manifest.duration_ms * (index + 1)) // count
                yield MediaChunk(
                    index=index,
                    data=data,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    width=manifest.width,
                    height=manifest.height,
                )

    def preflight(self, manifest: MediaManifest, chunk_size_bytes: int) -> MediaStreamMetadata:
        self.reads.append((manifest.media_id, manifest.media_version))
        byte_size = 0
        chunk_count = 0
        content_hasher = hashlib.sha256()
        layout_hasher = hashlib.sha256()
        prefix_hasher = hashlib.sha256()
        prefix_count = 0
        prefix_counts: list[int] = []
        prefix_digests: list[str] = []
        for chunk in self._chunks(manifest, chunk_size_bytes):
            prefix_hasher.update(chunk.data)
            prefix_count += len(chunk.data)
            byte_size += len(chunk.data)
            content_hasher.update(chunk.data)
            layout_hasher.update(chunk.chunk_identity.encode("ascii"))
            layout_hasher.update(b"\n")
            prefix_counts.append(prefix_count)
            prefix_digests.append(prefix_hasher.hexdigest())
            chunk_count += 1
        if chunk_count == 0:
            raise ValueError("media object is empty")
        return MediaStreamMetadata(
            byte_size=byte_size,
            chunk_count=chunk_count,
            duration_ms=manifest.duration_ms,
            layout_fingerprint=layout_hasher.hexdigest(),
            content_sha256=content_hasher.hexdigest(),
            prefix_byte_counts=tuple(prefix_counts),
            prefix_sha256s=tuple(prefix_digests),
        )

    def iter_chunks(
        self,
        manifest: MediaManifest,
        chunk_size_bytes: int,
        start_index: int = 0,
    ) -> Iterable[MediaChunk]:
        self.reads.append((manifest.media_id, manifest.media_version))
        prefix_count = 0
        prefix_hasher = hashlib.sha256()
        for chunk in self._chunks(manifest, chunk_size_bytes):
            prefix_hasher.update(chunk.data)
            prefix_count += len(chunk.data)
            chunk = replace(
                chunk,
                prefix_byte_count=prefix_count,
                prefix_sha256=prefix_hasher.hexdigest(),
            )
            if chunk.index < start_index:
                continue
            self.iteration_indexes.append(chunk.index)
            yield chunk

    def read(self, manifest: MediaManifest) -> bytes:
        self.reads.append((manifest.media_id, manifest.media_version))
        try:
            return self._objects[(manifest.media_id, manifest.media_version)]
        except KeyError as error:
            raise ValueError("media object not found") from error


class FakeMediaRecognizer:
    def __init__(self, responses: Sequence[object]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, int, str]] = []

    def recognize(self, chunk: MediaChunk, request: MediaProcessingRequest) -> object:
        self.calls.append((chunk.digest, chunk.index, request.request_id))
        if not self._responses:
            raise ValueError("fake recognizer has no response")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class InMemoryMediaEvidenceStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._request_records: dict[str, tuple[str, MediaTextEvidence]] = {}
        self._claims: dict[str, str] = {}
        self._checkpoints: dict[str, MediaCheckpoint] = {}
        self._evidence: dict[str, list[MediaTextEvidence]] = {}

    def find_committed(
        self, request: MediaProcessingRequest, idempotency_key: str
    ) -> MediaTextEvidence | None:
        with self._lock:
            existing = self._request_records.get(request.request_id)
            if existing is None:
                return None
            fingerprint, evidence = existing
            if fingerprint != idempotency_key:
                raise ValueError("media request conflict")
            return evidence

    def claim(
        self, request: MediaProcessingRequest, idempotency_key: str, owner_id: str
    ) -> MediaStoreClaim:
        with self._lock:
            existing = self._request_records.get(request.request_id)
            if existing is not None:
                fingerprint, evidence = existing
                if fingerprint != idempotency_key:
                    return MediaStoreClaim(MediaClaimStatus.CONFLICT, owner_id)
                return MediaStoreClaim(MediaClaimStatus.EXISTING, owner_id, evidence)
            claimed_by = self._claims.get(idempotency_key)
            if claimed_by is None or claimed_by == owner_id:
                self._claims[idempotency_key] = owner_id
                return MediaStoreClaim(MediaClaimStatus.CLAIMED, owner_id)
            return MediaStoreClaim(MediaClaimStatus.IN_PROGRESS, owner_id)

    def load_checkpoint(
        self, request: MediaProcessingRequest, idempotency_key: str
    ) -> MediaCheckpoint | None:
        with self._lock:
            return self._checkpoints.get(idempotency_key)

    def save_checkpoint(
        self,
        request: MediaProcessingRequest,
        idempotency_key: str,
        checkpoint: MediaCheckpoint,
        expected: MediaCheckpoint | None,
    ) -> MediaCheckpoint:
        with self._lock:
            current = self._checkpoints.get(idempotency_key)
            if current != expected:
                raise ValueError("checkpoint conflict")
            self._checkpoints[idempotency_key] = checkpoint
            return checkpoint

    def latest_evidence(self, evidence_id: str) -> MediaTextEvidence | None:
        with self._lock:
            revisions = self._evidence.get(evidence_id)
            return None if not revisions else revisions[-1]

    def compare_and_append(
        self,
        request: MediaProcessingRequest,
        evidence: MediaTextEvidence,
        expected_previous_revision_id: str | None,
        idempotency_key: str,
    ) -> MediaTextEvidence:
        with self._lock:
            request_existing = self._request_records.get(request.request_id)
            if request_existing is not None:
                if request_existing[0] != idempotency_key:
                    raise ValueError("media request conflict")
                if request_existing[1].fingerprint == evidence.fingerprint:
                    return request_existing[1]
                raise ValueError("media request conflict")
            revisions = self._evidence.setdefault(evidence.evidence_id, [])
            latest = revisions[-1] if revisions else None
            current_revision = None if latest is None else latest.revision_id
            if current_revision != expected_previous_revision_id:
                raise ValueError("evidence revision conflict")
            if latest is not None and evidence.previous_revision_id != latest.revision_id:
                raise ValueError("evidence predecessor conflict")
            for existing in revisions:
                if existing.revision_id == evidence.revision_id:
                    if existing.fingerprint == evidence.fingerprint:
                        return existing
                    raise ValueError("evidence revision conflict")
            if latest is not None and evidence.available_time <= latest.available_time:
                raise ValueError("evidence available_time must increase")
            revisions.append(evidence)
            self._request_records[request.request_id] = (idempotency_key, evidence)
            self._claims.pop(idempotency_key, None)
            return evidence

    def as_of(self, evidence_id: str, decision_time: datetime) -> MediaTextEvidence | None:
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            raise ValueError("decision_time must be timezone-aware")
        moment = decision_time.astimezone(UTC)
        with self._lock:
            visible = [
                item
                for item in self._evidence.get(evidence_id, ())
                if item.available_time <= moment
            ]
            return (
                None
                if not visible
                else max(visible, key=lambda item: (item.available_time, item.revision_id))
            )

    def release(self, request: MediaProcessingRequest, idempotency_key: str, owner_id: str) -> None:
        with self._lock:
            if self._claims.get(idempotency_key) == owner_id:
                self._claims.pop(idempotency_key, None)

    def fail(
        self, request: MediaProcessingRequest, idempotency_key: str, reason: MediaFailureReason
    ) -> None:
        if reason not in (
            MediaFailureReason.TIMEOUT,
            MediaFailureReason.RATE_LIMIT,
            MediaFailureReason.TEMPORARY_UNAVAILABLE,
            MediaFailureReason.STORE_TRANSIENT,
        ):
            with self._lock:
                self._claims.pop(idempotency_key, None)

    # Compatibility methods keep the old fake useful to callers, while the
    # consumer only uses the CAS methods above.
    def find(self, request_id: str, request_fingerprint: str) -> MediaTextEvidence | None:
        with self._lock:
            existing = self._request_records.get(request_id)
            if existing is None:
                return None
            if existing[0] != request_fingerprint:
                raise ValueError("media request conflict")
            return existing[1]

    def commit(
        self, request: MediaProcessingRequest, evidence: MediaTextEvidence
    ) -> MediaTextEvidence:
        result = self.compare_and_append(request, evidence, None, request.request_fingerprint)
        return result


class InMemoryMediaAuditSink:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: list[MediaAuditRecord] = []
        self._by_id: dict[str, MediaAuditRecord] = {}

    @property
    def records(self) -> tuple[MediaAuditRecord, ...]:
        with self._lock:
            return tuple(self._records)

    def append(self, record: MediaAuditRecord) -> MediaAuditRecord:
        with self._lock:
            existing = self._by_id.get(record.audit_id)
            if existing is not None:
                if existing != record:
                    raise ValueError("audit conflict")
                return existing
            self._records.append(record)
            self._by_id[record.audit_id] = record
            return record


def fake_media_profile(
    decision_time: datetime,
    *,
    model_id: str = "fake-media-model",
) -> ResolvedProfile:
    """Build a VersionRegistry-shaped profile without a provider or credential."""
    moment = decision_time.astimezone(UTC)
    prompt = PromptSpec(
        prompt_id="media-fake-prompt",
        version="v1",
        template="media candidate",
        variables=(),
        output_schema_version="media-recognition-candidate-v1",
        created_at=moment,
    )
    model = ModelSpec(
        provider_id="fake-media-provider",
        model_id=model_id,
        version="v1",
        api_variant="offline",
        credential_env_ref="MEDIA_FAKE_CREDENTIAL",
        temperature_milli=0,
        max_output_tokens=4096,
        created_at=moment,
        seed=0,
    )
    profile = ExtractionProfile(
        profile_id="media-fake-profile",
        version="v1",
        prompt_id=prompt.prompt_id,
        prompt_version=prompt.version,
        model_provider_id=model.provider_id,
        model_id=model.model_id,
        model_version=model.version,
        output_schema_version="kol-media-text-evidence-v1",
        minimum_confidence_bps=0,
        created_at=moment,
    )
    deployment = Deployment(
        deployment_id="media-fake-deployment",
        profile_id=profile.profile_id,
        primary_profile_version=profile.version,
        candidate_profile_version=None,
        candidate_allocation_bps=0,
        operation=DeploymentOperation.RELEASE,
        effective_at=moment,
        created_at=moment,
    )
    return ResolvedProfile(
        profile=profile,
        prompt=prompt,
        model=model,
        deployment=deployment,
        selected_variant=SelectedVariant.PRIMARY,
        routing_bucket=None,
        decision_time=moment,
    )


__all__ = [
    "FakeMediaObjectReader",
    "FakeMediaRecognizer",
    "InMemoryMediaAuditSink",
    "InMemoryMediaEvidenceStore",
    "fake_media_profile",
]
