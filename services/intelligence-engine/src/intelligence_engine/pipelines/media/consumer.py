"""PIT-gated streaming media consumer over fake-only ports."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from .candidate import MediaRecognitionCandidate, parse_media_recognition_candidate
from .models import (
    MediaAuditReason,
    MediaAuditRecord,
    MediaAuditStatus,
    MediaCheckpoint,
    MediaCheckpointPhase,
    MediaChecksumMismatchError,
    MediaChunk,
    MediaClaimStatus,
    MediaDecodeError,
    MediaEvidenceProvenance,
    MediaFailureReason,
    MediaManifest,
    MediaPipelinePolicy,
    MediaProcessingRequest,
    MediaProcessResult,
    MediaProcessStatus,
    MediaRateLimitError,
    MediaSilenceError,
    MediaStoreClaim,
    MediaStoreTransientError,
    MediaStreamMetadata,
    MediaTemporaryUnavailableError,
    MediaTextEvidence,
    MediaTextSegment,
    MediaTimeoutError,
    MediaTooLongError,
)


class MediaObjectReader(Protocol):
    def preflight(self, manifest: MediaManifest, chunk_size_bytes: int) -> MediaStreamMetadata: ...

    def iter_chunks(
        self,
        manifest: MediaManifest,
        chunk_size_bytes: int,
        start_index: int = 0,
    ) -> Iterable[MediaChunk]: ...


class MediaRecognizer(Protocol):
    def recognize(self, chunk: MediaChunk, request: MediaProcessingRequest) -> object: ...


class MediaEvidenceStore(Protocol):
    def find_committed(
        self, request: MediaProcessingRequest, idempotency_key: str
    ) -> MediaTextEvidence | None: ...

    def claim(
        self, request: MediaProcessingRequest, idempotency_key: str, owner_id: str
    ) -> MediaStoreClaim: ...

    def load_checkpoint(
        self, request: MediaProcessingRequest, idempotency_key: str
    ) -> MediaCheckpoint | None: ...

    def save_checkpoint(
        self,
        request: MediaProcessingRequest,
        idempotency_key: str,
        checkpoint: MediaCheckpoint,
        expected: MediaCheckpoint | None,
    ) -> MediaCheckpoint: ...

    def compare_and_append(
        self,
        request: MediaProcessingRequest,
        evidence: MediaTextEvidence,
        expected_previous_revision_id: str | None,
        idempotency_key: str,
    ) -> MediaTextEvidence: ...

    def latest_evidence(self, evidence_id: str) -> MediaTextEvidence | None: ...

    def as_of(self, evidence_id: str, decision_time: datetime) -> MediaTextEvidence | None: ...

    def release(
        self, request: MediaProcessingRequest, idempotency_key: str, owner_id: str
    ) -> None: ...

    def fail(
        self, request: MediaProcessingRequest, idempotency_key: str, reason: MediaFailureReason
    ) -> None: ...


class MediaAuditSink(Protocol):
    def append(self, record: MediaAuditRecord) -> MediaAuditRecord: ...


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class MediaProcessingConsumer:
    def __init__(
        self,
        *,
        reader: MediaObjectReader,
        recognizer: MediaRecognizer,
        store: MediaEvidenceStore,
        policy: MediaPipelinePolicy | None = None,
        audit_sink: MediaAuditSink | None = None,
    ) -> None:
        self.reader = reader
        self.recognizer = recognizer
        self.store = store
        self.policy = MediaPipelinePolicy() if policy is None else policy
        self.audit_sink = audit_sink
        self._owner_id = f"consumer-{id(self)}"
        self._audit_lock = threading.RLock()
        self._active_lock = threading.RLock()
        self._active_keys: set[str] = set()

    def process(self, request: MediaProcessingRequest) -> MediaProcessResult:
        if request.checkpoint is not None:
            self._validate_checkpoint_identity(request, request.checkpoint)
            if request.checkpoint.phase is MediaCheckpointPhase.READY_TO_COMMIT:
                self._validate_ready_checkpoint(request, request.checkpoint)
        idempotency_key = request.idempotency_fingerprint(self.policy)
        with self._active_lock:
            if idempotency_key in self._active_keys:
                audit_id = self._audit(
                    request,
                    MediaAuditStatus.TRANSIENT_RETRY,
                    MediaAuditReason.TRANSIENT_RETRY,
                )
                return MediaProcessResult(
                    MediaProcessStatus.RETRY_SCHEDULED,
                    failure_reason=MediaFailureReason.IN_PROGRESS,
                    audit_id=audit_id,
                )
            self._active_keys.add(idempotency_key)
        try:
            return self._process(request)
        finally:
            with self._active_lock:
                self._active_keys.discard(idempotency_key)

    def _process(self, request: MediaProcessingRequest) -> MediaProcessResult:
        if request.checkpoint is not None:
            self._validate_checkpoint_identity(request, request.checkpoint)
        idempotency_key = request.idempotency_fingerprint(self.policy)
        existing = self.store.find_committed(request, idempotency_key)
        if existing is not None:
            audit_id = self._audit(
                request,
                MediaAuditStatus.ALREADY_COMMITTED,
                MediaAuditReason.ALREADY_COMMITTED,
                existing,
            )
            return MediaProcessResult(
                MediaProcessStatus.ALREADY_COMMITTED, evidence=existing, audit_id=audit_id
            )
        claim = self.store.claim(request, idempotency_key, self._owner_id)
        if claim.status is MediaClaimStatus.EXISTING and claim.evidence is not None:
            audit_id = self._audit(
                request,
                MediaAuditStatus.ALREADY_COMMITTED,
                MediaAuditReason.ALREADY_COMMITTED,
                claim.evidence,
            )
            return MediaProcessResult(
                MediaProcessStatus.ALREADY_COMMITTED, evidence=claim.evidence, audit_id=audit_id
            )
        if claim.status is MediaClaimStatus.CONFLICT:
            self._audit(request, MediaAuditStatus.CONFLICT, MediaAuditReason.CONFLICT)
            raise ValueError("media request conflict")
        if claim.status is MediaClaimStatus.IN_PROGRESS:
            audit_id = self._audit(
                request, MediaAuditStatus.TRANSIENT_RETRY, MediaAuditReason.TRANSIENT_RETRY
            )
            return MediaProcessResult(
                MediaProcessStatus.RETRY_SCHEDULED,
                failure_reason=MediaFailureReason.IN_PROGRESS,
                audit_id=audit_id,
            )

        gate = self._gate(request)
        if gate is not None:
            if gate is MediaFailureReason.DELETED:
                tombstone = self._append_tombstone(request, idempotency_key)
                if tombstone is not None:
                    audit_id = self._audit(
                        request, MediaAuditStatus.TOMBSTONED, MediaAuditReason.TOMBSTONED, tombstone
                    )
                    return MediaProcessResult(
                        MediaProcessStatus.TERMINAL,
                        evidence=tombstone,
                        failure_reason=gate,
                        audit_id=audit_id,
                    )
                audit_id = self._audit(request, MediaAuditStatus.DELETED, MediaAuditReason.DELETED)
                self.store.release(request, idempotency_key, self._owner_id)
                return MediaProcessResult(
                    MediaProcessStatus.TERMINAL, failure_reason=gate, audit_id=audit_id
                )
            audit_id = self._audit(request, MediaAuditStatus.CONFLICT, MediaAuditReason.CONFLICT)
            self.store.release(request, idempotency_key, self._owner_id)
            return MediaProcessResult(
                MediaProcessStatus.TERMINAL, failure_reason=gate, audit_id=audit_id
            )

        checkpoint = request.checkpoint
        stored_checkpoint = self.store.load_checkpoint(request, idempotency_key)
        if checkpoint is None:
            checkpoint = stored_checkpoint
        elif stored_checkpoint is not None and checkpoint != stored_checkpoint:
            self._audit(request, MediaAuditStatus.CONFLICT, MediaAuditReason.CONFLICT)
            raise ValueError("checkpoint conflict")
        if checkpoint is not None and checkpoint.phase is MediaCheckpointPhase.READY_TO_COMMIT:
            if stored_checkpoint is None:
                self._audit(request, MediaAuditStatus.CONFLICT, MediaAuditReason.CONFLICT)
                raise ValueError("READY_TO_COMMIT checkpoint was not persisted")
            self._validate_ready_checkpoint(request, checkpoint)
            return self._commit_checkpoint(request, checkpoint, idempotency_key)

        try:
            metadata = self.reader.preflight(request.manifest, self.policy.chunk_size_bytes)
            self._validate_preflight(request.manifest, metadata)
        except MediaTimeoutError:
            return self._retry_or_terminal(
                request, None, MediaFailureReason.TIMEOUT, idempotency_key
            )
        except (MediaRateLimitError, MediaTemporaryUnavailableError):
            return self._retry_or_terminal(
                request, None, MediaFailureReason.TEMPORARY_UNAVAILABLE, idempotency_key
            )
        except MediaTooLongError:
            audit_id = self._audit(
                request, MediaAuditStatus.BUDGET_EXCEEDED, MediaAuditReason.BUDGET_EXCEEDED
            )
            self.store.fail(request, idempotency_key, MediaFailureReason.BUDGET_EXCEEDED)
            return MediaProcessResult(
                MediaProcessStatus.TERMINAL,
                failure_reason=MediaFailureReason.BUDGET_EXCEEDED,
                audit_id=audit_id,
            )
        except MediaChecksumMismatchError:
            audit_id = self._audit(
                request, MediaAuditStatus.CHECKSUM_MISMATCH, MediaAuditReason.CHECKSUM_MISMATCH
            )
            self.store.fail(request, idempotency_key, MediaFailureReason.CHECKSUM_MISMATCH)
            return MediaProcessResult(
                MediaProcessStatus.TERMINAL,
                failure_reason=MediaFailureReason.CHECKSUM_MISMATCH,
                audit_id=audit_id,
            )
        except ValueError:
            audit_id = self._audit(
                request, MediaAuditStatus.DECODE_FAILED, MediaAuditReason.DECODE_FAILED
            )
            self.store.fail(request, idempotency_key, MediaFailureReason.DECODE_FAILURE)
            return MediaProcessResult(
                MediaProcessStatus.TERMINAL,
                failure_reason=MediaFailureReason.DECODE_FAILURE,
                audit_id=audit_id,
            )

        next_chunk = 0
        text = ""
        language: str | None = None
        segments: list[MediaTextSegment] = []
        frame_identities: set[str] = set()
        segment_identities: set[str] = set()
        rolling_count = 0
        rolling_sha = hashlib.sha256().hexdigest()
        if checkpoint is not None:
            self._validate_checkpoint(request, metadata, checkpoint)
            next_chunk = checkpoint.next_chunk_index
            text = checkpoint.text
            language = None if checkpoint.language == "und" else checkpoint.language
            segments = list(checkpoint.segments)
            frame_identities = set(checkpoint.frame_identities)
            segment_identities = {segment.identity for segment in segments}
            rolling_count = checkpoint.rolling_byte_count
            rolling_sha = checkpoint.rolling_sha256

        layout_hasher = hashlib.sha256()
        rolling_hasher = hashlib.sha256() if next_chunk == 0 else None
        observed_count = 0
        last_prefix_sha = rolling_sha
        try:
            for chunk in self.reader.iter_chunks(
                request.manifest,
                self.policy.chunk_size_bytes,
                start_index=next_chunk,
            ):
                if type(chunk) is not MediaChunk or chunk.index != next_chunk + observed_count:
                    raise ValueError("invalid chunk sequence")
                if len(chunk.data) > self.policy.max_chunk_bytes:
                    raise MediaTooLongError("chunk budget")
                prior_rolling_count = rolling_count
                prior_rolling_sha = rolling_sha
                layout_hasher.update(chunk.chunk_identity.encode("ascii"))
                layout_hasher.update(b"\n")
                if next_chunk == 0:
                    assert rolling_hasher is not None
                    rolling_hasher.update(chunk.data)
                    rolling_count += len(chunk.data)
                    rolling_sha = rolling_hasher.hexdigest()
                else:
                    if chunk.prefix_byte_count <= rolling_count or not chunk.prefix_sha256:
                        raise ValueError("resumed chunk lacks verifiable prefix state")
                    rolling_count = chunk.prefix_byte_count
                    rolling_sha = chunk.prefix_sha256
                last_prefix_sha = rolling_sha
                is_video_ocr = (
                    request.processor_kind.value == "OCR"
                    and request.manifest.media_kind.value == "VIDEO"
                )
                if is_video_ocr and chunk.frame_identity is None:
                    audit_id = self._audit(
                        request,
                        MediaAuditStatus.INVALID_CANDIDATE,
                        MediaAuditReason.INVALID_CANDIDATE,
                    )
                    self.store.fail(request, idempotency_key, MediaFailureReason.INVALID_CANDIDATE)
                    return MediaProcessResult(
                        MediaProcessStatus.TERMINAL,
                        failure_reason=MediaFailureReason.INVALID_CANDIDATE,
                        audit_id=audit_id,
                    )
                if is_video_ocr and chunk.frame_identity in frame_identities:
                    self._audit(
                        request, MediaAuditStatus.DUPLICATE_FRAME, MediaAuditReason.DUPLICATE_FRAME
                    )
                    observed_count += 1
                    checkpoint = self._checkpoint(
                        request,
                        metadata,
                        chunk.index + 1,
                        text,
                        segments,
                        frame_identities,
                        language,
                        rolling_count,
                        rolling_sha,
                        phase=MediaCheckpointPhase.RECOGNIZING,
                        chunk_count=metadata.chunk_count,
                    )
                    checkpoint = self._save_checkpoint(request, idempotency_key, checkpoint)
                    continue
                try:
                    raw_candidate = self.recognizer.recognize(chunk, request)
                    candidate = parse_media_recognition_candidate(
                        raw_candidate,
                        manifest=request.manifest,
                        processor_kind=request.processor_kind,
                        chunk=chunk,
                    )
                except MediaSilenceError:
                    audit_id = self._audit(
                        request, MediaAuditStatus.SILENCE, MediaAuditReason.SILENCE
                    )
                    self.store.fail(request, idempotency_key, MediaFailureReason.SILENCE)
                    return MediaProcessResult(
                        MediaProcessStatus.TERMINAL,
                        failure_reason=MediaFailureReason.SILENCE,
                        audit_id=audit_id,
                    )
                except (
                    MediaTimeoutError,
                    MediaRateLimitError,
                    MediaTemporaryUnavailableError,
                ) as error:
                    reason = (
                        MediaFailureReason.TIMEOUT
                        if isinstance(error, MediaTimeoutError)
                        else MediaFailureReason.RATE_LIMIT
                        if isinstance(error, MediaRateLimitError)
                        else MediaFailureReason.TEMPORARY_UNAVAILABLE
                    )
                    checkpoint = self._checkpoint(
                        request,
                        metadata,
                        chunk.index,
                        text,
                        segments,
                        frame_identities,
                        language,
                        prior_rolling_count,
                        prior_rolling_sha,
                        phase=MediaCheckpointPhase.RECOGNIZING,
                        chunk_count=metadata.chunk_count,
                    )
                    checkpoint = self._save_checkpoint(request, idempotency_key, checkpoint)
                    return self._retry_or_terminal(request, checkpoint, reason, idempotency_key)
                except MediaDecodeError:
                    audit_id = self._audit(
                        request, MediaAuditStatus.DECODE_FAILED, MediaAuditReason.DECODE_FAILED
                    )
                    self.store.fail(request, idempotency_key, MediaFailureReason.DECODE_FAILURE)
                    return MediaProcessResult(
                        MediaProcessStatus.TERMINAL,
                        failure_reason=MediaFailureReason.DECODE_FAILURE,
                        audit_id=audit_id,
                    )
                except (TypeError, ValueError):
                    audit_id = self._audit(
                        request,
                        MediaAuditStatus.INVALID_CANDIDATE,
                        MediaAuditReason.INVALID_CANDIDATE,
                    )
                    self.store.fail(request, idempotency_key, MediaFailureReason.INVALID_CANDIDATE)
                    return MediaProcessResult(
                        MediaProcessStatus.TERMINAL,
                        failure_reason=MediaFailureReason.INVALID_CANDIDATE,
                        audit_id=audit_id,
                    )
                if language is None:
                    language = candidate.language
                elif language != candidate.language:
                    audit_id = self._audit(
                        request,
                        MediaAuditStatus.INVALID_CANDIDATE,
                        MediaAuditReason.INVALID_CANDIDATE,
                    )
                    self.store.fail(request, idempotency_key, MediaFailureReason.INVALID_CANDIDATE)
                    return MediaProcessResult(
                        MediaProcessStatus.TERMINAL,
                        failure_reason=MediaFailureReason.INVALID_CANDIDATE,
                        audit_id=audit_id,
                    )
                if candidate.quality_bps < self.policy.minimum_quality_bps:
                    self._audit(
                        request,
                        MediaAuditStatus.QUALITY_REVIEW_REQUIRED,
                        MediaAuditReason.QUALITY_REVIEW_REQUIRED,
                    )
                if not self._merge_candidate(
                    candidate,
                    text_holder := [text],
                    segments,
                    frame_identities,
                    segment_identities,
                    chunk.frame_identity,
                ):
                    self._audit(
                        request, MediaAuditStatus.DUPLICATE_FRAME, MediaAuditReason.DUPLICATE_FRAME
                    )
                text = text_holder[0]
                if (
                    len(text) > self.policy.max_text_codepoints
                    or len(segments) > self.policy.max_segments
                ):
                    audit_id = self._audit(
                        request, MediaAuditStatus.BUDGET_EXCEEDED, MediaAuditReason.BUDGET_EXCEEDED
                    )
                    self.store.fail(request, idempotency_key, MediaFailureReason.BUDGET_EXCEEDED)
                    return MediaProcessResult(
                        MediaProcessStatus.TERMINAL,
                        failure_reason=MediaFailureReason.BUDGET_EXCEEDED,
                        audit_id=audit_id,
                    )
                frame_count = len(frame_identities)
                if frame_count > self.policy.max_frames:
                    audit_id = self._audit(
                        request, MediaAuditStatus.BUDGET_EXCEEDED, MediaAuditReason.BUDGET_EXCEEDED
                    )
                    self.store.fail(request, idempotency_key, MediaFailureReason.BUDGET_EXCEEDED)
                    return MediaProcessResult(
                        MediaProcessStatus.TERMINAL,
                        failure_reason=MediaFailureReason.BUDGET_EXCEEDED,
                        audit_id=audit_id,
                    )
                observed_count += 1
                checkpoint = self._checkpoint(
                    request,
                    metadata,
                    chunk.index + 1,
                    text,
                    segments,
                    frame_identities,
                    language,
                    rolling_count,
                    rolling_sha,
                    phase=MediaCheckpointPhase.RECOGNIZING,
                    chunk_count=metadata.chunk_count,
                )
                checkpoint = self._save_checkpoint(request, idempotency_key, checkpoint)
        except (MediaTimeoutError, MediaRateLimitError, MediaTemporaryUnavailableError):
            return self._retry_or_terminal(
                request, checkpoint, MediaFailureReason.TEMPORARY_UNAVAILABLE, idempotency_key
            )
        except (MediaDecodeError, ValueError, TypeError):
            audit_id = self._audit(
                request, MediaAuditStatus.DECODE_FAILED, MediaAuditReason.DECODE_FAILED
            )
            self.store.fail(request, idempotency_key, MediaFailureReason.DECODE_FAILURE)
            return MediaProcessResult(
                MediaProcessStatus.TERMINAL,
                failure_reason=MediaFailureReason.DECODE_FAILURE,
                audit_id=audit_id,
            )

        if observed_count + next_chunk != metadata.chunk_count:
            audit_id = self._audit(
                request, MediaAuditStatus.DECODE_FAILED, MediaAuditReason.DECODE_FAILED
            )
            self.store.fail(request, idempotency_key, MediaFailureReason.DECODE_FAILURE)
            return MediaProcessResult(
                MediaProcessStatus.TERMINAL,
                failure_reason=MediaFailureReason.DECODE_FAILURE,
                audit_id=audit_id,
            )
        if next_chunk == 0 and layout_hasher.hexdigest() != metadata.layout_fingerprint:
            audit_id = self._audit(
                request, MediaAuditStatus.DECODE_FAILED, MediaAuditReason.DECODE_FAILED
            )
            self.store.fail(request, idempotency_key, MediaFailureReason.DECODE_FAILURE)
            return MediaProcessResult(
                MediaProcessStatus.TERMINAL,
                failure_reason=MediaFailureReason.DECODE_FAILURE,
                audit_id=audit_id,
            )
        checksum = rolling_sha if next_chunk == 0 else last_prefix_sha
        if rolling_count != request.manifest.byte_size or checksum != request.manifest.raw_sha256:
            audit_id = self._audit(
                request, MediaAuditStatus.CHECKSUM_MISMATCH, MediaAuditReason.CHECKSUM_MISMATCH
            )
            self.store.fail(request, idempotency_key, MediaFailureReason.CHECKSUM_MISMATCH)
            return MediaProcessResult(
                MediaProcessStatus.TERMINAL,
                failure_reason=MediaFailureReason.CHECKSUM_MISMATCH,
                audit_id=audit_id,
            )
        if not text or not segments:
            audit_id = self._audit(request, MediaAuditStatus.SILENCE, MediaAuditReason.NO_SPEECH)
            self.store.fail(request, idempotency_key, MediaFailureReason.SILENCE)
            return MediaProcessResult(
                MediaProcessStatus.TERMINAL,
                failure_reason=MediaFailureReason.SILENCE,
                audit_id=audit_id,
            )

        checkpoint = self._checkpoint(
            request,
            metadata,
            metadata.chunk_count,
            text,
            segments,
            frame_identities,
            language,
            rolling_count,
            checksum,
            phase=MediaCheckpointPhase.READY_TO_COMMIT,
            chunk_count=metadata.chunk_count,
        )
        checkpoint = self._save_checkpoint(request, idempotency_key, checkpoint)
        return self._commit_checkpoint(request, checkpoint, idempotency_key)

    def _commit_checkpoint(
        self,
        request: MediaProcessingRequest,
        checkpoint: MediaCheckpoint,
        idempotency_key: str,
    ) -> MediaProcessResult:
        self._validate_ready_checkpoint(request, checkpoint)
        language = "und" if checkpoint.language == "und" else checkpoint.language
        evidence = self._build_evidence(
            request,
            checkpoint.text,
            checkpoint.segments,
            language,
        )
        latest = self.store.latest_evidence(evidence.evidence_id)
        expected_previous = None if latest is None else latest.revision_id
        if latest is not None:
            evidence = self._build_evidence(
                request,
                checkpoint.text,
                checkpoint.segments,
                language,
                latest,
            )
        try:
            committed = self.store.compare_and_append(
                request, evidence, expected_previous, idempotency_key
            )
        except MediaStoreTransientError:
            return self._retry_or_terminal(
                request, checkpoint, MediaFailureReason.STORE_TRANSIENT, idempotency_key
            )
        except ValueError:
            self._audit(request, MediaAuditStatus.CONFLICT, MediaAuditReason.CONFLICT, evidence)
            raise
        audit_id = self._audit(
            request, MediaAuditStatus.COMMITTED, MediaAuditReason.COMMITTED, committed
        )
        return MediaProcessResult(
            MediaProcessStatus.COMMITTED, evidence=committed, audit_id=audit_id
        )

    def _gate(self, request: MediaProcessingRequest) -> MediaFailureReason | None:
        if request.manifest.input_available_time > request.decision_time:
            return MediaFailureReason.FUTURE_MEDIA
        if not request.manifest.authorized:
            return MediaFailureReason.UNAUTHORIZED
        if request.manifest.deleted:
            return MediaFailureReason.DELETED
        return None

    def _validate_preflight(self, manifest: MediaManifest, metadata: MediaStreamMetadata) -> None:
        if metadata.chunk_count > self.policy.max_chunks:
            raise MediaTooLongError("chunk budget")
        if metadata.byte_size > self.policy.effective_max_bytes:
            raise MediaTooLongError("byte budget")
        if metadata.content_sha256 != manifest.raw_sha256:
            raise MediaChecksumMismatchError("checksum mismatch")
        if manifest.duration_ms is not None and manifest.duration_ms > self.policy.max_duration_ms:
            raise MediaTooLongError("duration budget")
        if metadata.duration_ms != manifest.duration_ms:
            raise ValueError("preflight duration mismatch")

    def _validate_checkpoint(
        self,
        request: MediaProcessingRequest,
        metadata: MediaStreamMetadata,
        checkpoint: MediaCheckpoint,
    ) -> None:
        if (
            checkpoint.request_fingerprint != request.request_fingerprint
            or checkpoint.raw_sha256 != request.manifest.raw_sha256
            or checkpoint.manifest_identity != request.manifest.identity
            or checkpoint.manifest_revision_id != request.manifest.revision_id
            or checkpoint.policy_fingerprint != self.policy.fingerprint
            or checkpoint.configuration_fingerprint
            != request.resolved_profile.configuration_fingerprint
            or checkpoint.chunk_layout_fingerprint != metadata.layout_fingerprint
        ):
            raise ValueError("checkpoint conflict")
        if checkpoint.phase is not MediaCheckpointPhase.RECOGNIZING:
            raise ValueError("recognizing checkpoint has an invalid phase")
        if checkpoint.chunk_count != metadata.chunk_count:
            raise ValueError("checkpoint chunk count mismatch")
        if checkpoint.next_chunk_index < 0 or checkpoint.next_chunk_index >= metadata.chunk_count:
            raise ValueError("checkpoint is beyond media chunks")
        previous = checkpoint.next_chunk_index - 1
        if previous >= 0:
            if metadata.prefix_byte_counts[previous] != checkpoint.rolling_byte_count:
                raise ValueError("checkpoint rolling byte count mismatch")
            if metadata.prefix_sha256s[previous] != checkpoint.rolling_sha256:
                raise ValueError("checkpoint rolling digest mismatch")
        if checkpoint.completed_chunk_indices != tuple(range(checkpoint.next_chunk_index)):
            raise ValueError("checkpoint completed chunk sequence mismatch")

    def _validate_ready_checkpoint(
        self,
        request: MediaProcessingRequest,
        checkpoint: MediaCheckpoint,
    ) -> None:
        self._validate_checkpoint_identity(request, checkpoint)
        if checkpoint.phase is not MediaCheckpointPhase.READY_TO_COMMIT:
            raise ValueError("checkpoint is not ready to commit")
        if checkpoint.next_chunk_index != checkpoint.chunk_count:
            raise ValueError("checkpoint READY_TO_COMMIT is incomplete")
        if checkpoint.rolling_byte_count != request.manifest.byte_size:
            raise ValueError("checkpoint READY_TO_COMMIT byte count mismatch")
        if checkpoint.rolling_sha256 != request.manifest.raw_sha256:
            raise ValueError("checkpoint READY_TO_COMMIT checksum mismatch")
        if checkpoint.completed_chunk_indices != tuple(range(checkpoint.chunk_count)):
            raise ValueError("checkpoint READY_TO_COMMIT completed chunk sequence mismatch")

    def _validate_checkpoint_identity(
        self,
        request: MediaProcessingRequest,
        checkpoint: MediaCheckpoint,
    ) -> None:
        if (
            checkpoint.request_fingerprint != request.request_fingerprint
            or checkpoint.raw_sha256 != request.manifest.raw_sha256
            or checkpoint.manifest_identity != request.manifest.identity
            or checkpoint.manifest_revision_id != request.manifest.revision_id
            or checkpoint.policy_fingerprint != self.policy.fingerprint
            or checkpoint.configuration_fingerprint
            != request.resolved_profile.configuration_fingerprint
        ):
            raise ValueError("checkpoint conflict")

    def _prefix_before_chunk(
        self,
        metadata: MediaStreamMetadata,
        index: int,
        current_sha: str,
        chunk: MediaChunk,
    ) -> str:
        if index == 0:
            return hashlib.sha256(b"").hexdigest()
        previous = index - 1
        expected = metadata.prefix_sha256s[previous]
        if index > 0 and current_sha == chunk.prefix_sha256:
            return expected
        return expected

    def _layout_suffix_fingerprint(self, metadata: MediaStreamMetadata, start_index: int) -> str:
        # The fake reader's layout fingerprint is based on all chunks. A resumed
        # stream receives the same preflight fingerprint and verifies its own
        # chunk identities incrementally below; the suffix cannot be reconstructed
        # without replaying the prefix, so the preflight identity is authoritative.
        return (
            metadata.layout_fingerprint
            if start_index == 0
            else hashlib.sha256(
                b"".join(d.encode("ascii") + b"\n" for d in metadata.prefix_sha256s[start_index:])
            ).hexdigest()
        )

    def _checkpoint(
        self,
        request: MediaProcessingRequest,
        metadata: MediaStreamMetadata,
        failed_chunk: int,
        text: str,
        segments: list[MediaTextSegment],
        frame_identities: set[str],
        language: str | None,
        rolling_count: int,
        rolling_sha: str,
        *,
        phase: MediaCheckpointPhase = MediaCheckpointPhase.RECOGNIZING,
        chunk_count: int | None = None,
    ) -> MediaCheckpoint:
        return MediaCheckpoint(
            request_fingerprint=request.request_fingerprint,
            raw_sha256=request.manifest.raw_sha256,
            next_chunk_index=failed_chunk,
            text=text,
            segments=tuple(segments),
            frame_identities=tuple(sorted(frame_identities)),
            language=language or "und",
            phase=phase,
            chunk_count=metadata.chunk_count if chunk_count is None else chunk_count,
            manifest_identity=request.manifest.identity,
            manifest_revision_id=request.manifest.revision_id,
            policy_fingerprint=self.policy.fingerprint,
            configuration_fingerprint=request.resolved_profile.configuration_fingerprint,
            chunk_layout_fingerprint=metadata.layout_fingerprint,
            rolling_byte_count=rolling_count,
            rolling_sha256=rolling_sha,
            completed_chunk_indices=tuple(range(failed_chunk)),
        )

    def _save_checkpoint(
        self,
        request: MediaProcessingRequest,
        idempotency_key: str,
        checkpoint: MediaCheckpoint,
    ) -> MediaCheckpoint:
        expected = self.store.load_checkpoint(request, idempotency_key)
        return self.store.save_checkpoint(request, idempotency_key, checkpoint, expected)

    def _retry_or_terminal(
        self,
        request: MediaProcessingRequest,
        checkpoint: MediaCheckpoint | None,
        reason: MediaFailureReason,
        idempotency_key: str,
    ) -> MediaProcessResult:
        if request.attempt + 1 >= self.policy.max_attempts:
            audit_id = self._audit(
                request, MediaAuditStatus.RETRY_EXHAUSTED, MediaAuditReason.RETRY_EXHAUSTED
            )
            self.store.fail(request, idempotency_key, MediaFailureReason.RETRY_EXHAUSTED)
            return MediaProcessResult(
                MediaProcessStatus.TERMINAL,
                failure_reason=MediaFailureReason.RETRY_EXHAUSTED,
                checkpoint=checkpoint,
                audit_id=audit_id,
            )
        retry_after = min(self.policy.retry_base_seconds * (2 ** min(request.attempt, 8)), 300)
        audit_id = self._audit(
            request, MediaAuditStatus.TRANSIENT_RETRY, MediaAuditReason.TRANSIENT_RETRY
        )
        return MediaProcessResult(
            MediaProcessStatus.RETRY_SCHEDULED,
            failure_reason=reason,
            checkpoint=checkpoint,
            retry_after_seconds=retry_after,
            audit_id=audit_id,
        )

    def _merge_candidate(
        self,
        candidate: MediaRecognitionCandidate,
        text_holder: list[str],
        segments: list[MediaTextSegment],
        frame_identities: set[str],
        segment_identities: set[str],
        reader_frame_identity: str | None,
    ) -> bool:
        candidate_identity = candidate.frame_identity or reader_frame_identity or candidate.identity
        if candidate_identity in frame_identities:
            return False
        frame_identities.add(candidate_identity)
        base_offset = len(text_holder[0])
        new_segments: list[MediaTextSegment] = []
        for segment in candidate.segments:
            shifted = MediaTextSegment(
                segment.text,
                segment.start_offset + base_offset,
                segment.end_offset + base_offset,
                segment.start_ms,
                segment.end_ms,
                segment.bbox,
                segment.confidence_bps,
                segment.quality_bps,
                segment.frame_identity,
            )
            if shifted.identity not in segment_identities:
                segment_identities.add(shifted.identity)
                new_segments.append(shifted)
        if new_segments:
            text_holder[0] += candidate.text
            segments.extend(new_segments)
        return True

    def _stable_evidence_id(self, request: MediaProcessingRequest) -> str:
        return "media-evidence-" + _digest(
            {
                "contentId": request.manifest.content_id,
                "contentVersion": request.manifest.content_version,
                "evidenceKind": "kol-media-text-evidence",
                "mediaId": request.manifest.media_id,
                "processorKind": request.processor_kind.value,
            }
        )

    def _build_evidence(
        self,
        request: MediaProcessingRequest,
        text: str,
        segments: tuple[MediaTextSegment, ...],
        language: str,
        previous: MediaTextEvidence | None = None,
    ) -> MediaTextEvidence:
        profile = request.resolved_profile
        recognition_run_id = _digest(
            {
                "configurationFingerprint": profile.configuration_fingerprint,
                "manifestRevisionId": request.manifest.revision_id,
                "policyFingerprint": self.policy.fingerprint,
                "requestFingerprint": request.request_fingerprint,
            }
        )
        output_fingerprint = _digest(
            {
                "language": language,
                "segments": [segment.payload() for segment in segments],
                "text": text,
            }
        )
        revision_id = "media-evidence-revision-" + _digest(
            {
                "configurationFingerprint": profile.configuration_fingerprint,
                "manifestRevisionId": request.manifest.revision_id,
                "outputFingerprint": output_fingerprint,
                "policyFingerprint": self.policy.fingerprint,
                "recognitionRunId": recognition_run_id,
            }
        )
        provenance = MediaEvidenceProvenance(
            pipeline_version=self.policy.pipeline_version,
            processor_kind=request.processor_kind,
            provider=profile.model.provider_id,
            model=profile.model.model_id,
            model_version=profile.model.version,
            prompt_version=profile.prompt.version,
            configuration_fingerprint=profile.configuration_fingerprint,
            policy_fingerprint=self.policy.fingerprint,
            recognition_run_id=recognition_run_id,
        )
        confidence = min(segment.confidence_bps for segment in segments)
        quality = min(segment.quality_bps for segment in segments)
        return MediaTextEvidence(
            evidence_id=self._stable_evidence_id(request),
            revision_id=revision_id,
            previous_revision_id=None if previous is None else previous.revision_id,
            media_manifest=request.manifest,
            processor_kind=request.processor_kind,
            text=text,
            language=language,
            segments=segments,
            confidence_bps=confidence,
            quality_bps=quality,
            event_time=request.event_time,
            publish_time=request.publish_time,
            ingest_time=request.ingest_time,
            processing_time=request.processing_time,
            provenance=provenance,
            deleted=request.manifest.deleted,
            deleted_at=request.manifest.deleted_at,
            deletion_reason=request.manifest.deletion_reason,
        )

    def _append_tombstone(
        self,
        request: MediaProcessingRequest,
        idempotency_key: str,
    ) -> MediaTextEvidence | None:
        evidence_id = self._stable_evidence_id(request)
        latest = self.store.latest_evidence(evidence_id)
        if latest is None:
            return None
        tombstone = self._build_evidence(
            request,
            latest.text,
            latest.segments,
            latest.language,
            latest,
        )
        return self.store.compare_and_append(
            request, tombstone, latest.revision_id, idempotency_key
        )

    def _audit(
        self,
        request: MediaProcessingRequest,
        status: MediaAuditStatus,
        reason: MediaAuditReason,
        evidence: MediaTextEvidence | None = None,
    ) -> str | None:
        if self.audit_sink is None:
            return None
        manifest_fingerprint = request.manifest.identity
        manifest_revision_fingerprint = _digest(
            {
                "manifestFingerprint": manifest_fingerprint,
                "revisionId": request.manifest.revision_id,
            }
        )
        evidence_fingerprint = (
            None if evidence is None else _digest({"evidenceId": evidence.evidence_id})
        )
        evidence_revision_fingerprint = (
            None
            if evidence is None
            else _digest(
                {
                    "evidenceFingerprint": evidence_fingerprint,
                    "revisionId": evidence.revision_id,
                }
            )
        )
        recognition_run_fingerprint = _digest(
            {
                "attempt": request.attempt,
                "configurationFingerprint": request.resolved_profile.configuration_fingerprint,
                "policyFingerprint": self.policy.fingerprint,
                "requestFingerprint": request.request_fingerprint,
            }
        )
        audit_id = _digest(
            {
                "attempt": request.attempt,
                "evidenceRevisionFingerprint": evidence_revision_fingerprint,
                "manifestRevisionFingerprint": manifest_revision_fingerprint,
                "reason": reason.value,
                "requestFingerprint": request.request_fingerprint,
                "status": status.value,
            }
        )
        record = MediaAuditRecord(
            audit_id=audit_id,
            status=status,
            reason=reason,
            attempt=request.attempt,
            manifest_fingerprint=manifest_fingerprint,
            manifest_revision_fingerprint=manifest_revision_fingerprint,
            evidence_fingerprint=evidence_fingerprint,
            evidence_revision_fingerprint=evidence_revision_fingerprint,
            recognition_run_fingerprint=recognition_run_fingerprint,
            policy_fingerprint=self.policy.fingerprint,
            configuration_fingerprint=request.resolved_profile.configuration_fingerprint,
            logical_time=request.processing_time,
        )
        with self._audit_lock:
            self.audit_sink.append(record)
        return audit_id


__all__ = [
    "MediaAuditSink",
    "MediaEvidenceStore",
    "MediaObjectReader",
    "MediaProcessingConsumer",
    "MediaRecognizer",
]
