from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from datetime import datetime
from threading import Lock
from types import MappingProxyType

from feature_core.batch.models import RegistrySnapshotRef, canonical_checksum

from .models import (
    OnlineCasResult,
    OnlineCasStatus,
    OnlineIntegrityError,
    OnlineStateEnvelope,
    OnlineStreamState,
)
from .ports import OnlineCalculatorArtifact


class HmacOnlineStateIntegrity:
    def __init__(self, key: bytes) -> None:
        if type(key) is not bytes or len(key) < 32:
            raise OnlineIntegrityError("online state HMAC key must contain at least 32 bytes")
        self._key = key

    def _tag(self, state: OnlineStreamState, retain_until: datetime) -> str:
        payload = canonical_checksum(
            {
                "state": state,
                "retain_until": retain_until,
            },
        ).encode("ascii")
        digest = hmac.new(self._key, payload, hashlib.sha256).hexdigest()
        return f"hmac-sha256:{digest}"

    def seal(
        self,
        state: OnlineStreamState,
        *,
        retain_until: datetime,
    ) -> OnlineStateEnvelope:
        return OnlineStateEnvelope(
            state=state,
            retain_until=retain_until,
            integrity_tag=self._tag(state, retain_until),
        )

    def verify(self, envelope: OnlineStateEnvelope) -> bool:
        if type(envelope) is not OnlineStateEnvelope:
            return False
        expected = self._tag(envelope.state, envelope.retain_until)
        return hmac.compare_digest(expected, envelope.integrity_tag)


class StaticOnlineCalculatorTrust:
    def __init__(
        self,
        artifacts: Mapping[str, OnlineCalculatorArtifact],
    ) -> None:
        self._artifacts = MappingProxyType(dict(artifacts))

    def resolve(
        self,
        registry_ref: RegistrySnapshotRef,
    ) -> OnlineCalculatorArtifact | None:
        return self._artifacts.get(registry_ref.feature_fingerprint)


class InMemoryOnlineStateStore:
    def __init__(self) -> None:
        self._envelopes: dict[str, OnlineStateEnvelope] = {}
        self._lock = Lock()

    def load(self, stream_key: str) -> OnlineStateEnvelope | None:
        with self._lock:
            return self._envelopes.get(stream_key)

    def compare_and_set(
        self,
        *,
        expected_revision: int | None,
        candidate: OnlineStateEnvelope,
    ) -> OnlineCasResult:
        with self._lock:
            stream_key = candidate.state.stream_key
            existing = self._envelopes.get(stream_key)
            actual_revision = None if existing is None else existing.state.revision
            if actual_revision != expected_revision:
                return OnlineCasResult(OnlineCasStatus.CONFLICT, existing)
            if existing == candidate:
                return OnlineCasResult(OnlineCasStatus.EXISTING_SAME, existing)
            expected_candidate_revision = 1 if existing is None else existing.state.revision + 1
            if candidate.state.revision != expected_candidate_revision:
                return OnlineCasResult(OnlineCasStatus.CONFLICT, existing)
            self._envelopes[stream_key] = candidate
            status = OnlineCasStatus.CREATED if existing is None else OnlineCasStatus.UPDATED
            return OnlineCasResult(status, candidate)

    def expire(self, *, trusted_now: datetime) -> int:
        with self._lock:
            expired = [
                key
                for key, envelope in self._envelopes.items()
                if envelope.retain_until <= trusted_now
            ]
            for key in expired:
                del self._envelopes[key]
            return len(expired)

    @property
    def envelopes(self) -> tuple[OnlineStateEnvelope, ...]:
        with self._lock:
            return tuple(self._envelopes[key] for key in sorted(self._envelopes))
