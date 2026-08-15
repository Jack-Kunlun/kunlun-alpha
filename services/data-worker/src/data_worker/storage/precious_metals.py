"""Persistence ports/adapters for precious-metals fund observations.

The in-memory adapter is a deterministic contract fake.  The PostgreSQL
adapter uses one transaction per page and fences every write with the active
scheduler lease token.  Both adapters use the same record/evidence identity
rules so raw replay is safe after a process crash.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from psycopg import Connection


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_SENSITIVE_KEYS = frozenset(
    {
        "accesskeyid",
        "password",
        "passwd",
        "secret",
        "credential",
        "credentials",
        "dsn",
        "connectionstring",
        "databaseurl",
        "token",
        "apikey",
        "accesstoken",
        "accesskey",
        "privatekey",
        "authorization",
        "proxyauthorization",
        "bearer",
        "basic",
        "cookie",
        "setcookie",
        "cookieheader",
    }
)

_REJECTION_REASON_CODES = frozenset({"item_not_mapping", "normalization_error"})
_MAX_REJECTION_FIELDS = 32
_MAX_REJECTION_FIELD_LENGTH = 64


def _safe_rejection_field_names(value: object) -> list[str]:
    """Return bounded, non-sensitive field names without any field values."""

    if not isinstance(value, Mapping):
        return []
    mapping = cast(Mapping[object, object], value)
    names: set[str] = set()
    for key in mapping:
        if not isinstance(key, str):
            continue
        name = key.strip()
        if not name or len(name) > _MAX_REJECTION_FIELD_LENGTH or not name.isascii():
            continue
        if not all(character.isalnum() or character in "_.-" for character in name):
            continue
        normalized = "".join(character for character in name.lower() if character.isalnum())
        if normalized in _SENSITIVE_KEYS:
            continue
        names.add(name)
    return sorted(names)[:_MAX_REJECTION_FIELDS]


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _safe_rejection_field_names_from_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    fields = cast(list[object], value)
    if not all(isinstance(field, str) for field in fields):
        return []
    return _safe_rejection_field_names({field: None for field in cast(list[str], fields)})


def controlled_rejection_payload(
    item: object,
    *,
    digest: str | None = None,
    field_names: object | None = None,
) -> dict[str, object]:
    """Build a value-free rejection summary suitable for either adapter."""

    if digest is not None and not _is_digest(digest):
        raise ValueError("payload_digest must be a 64-character lowercase hexadecimal digest")
    safe_fields = (
        _safe_rejection_field_names_from_list(field_names)
        if field_names is not None
        else _safe_rejection_field_names(item)
    )
    return {
        "item_digest": digest if digest is not None else _digest(item),
        "field_names": safe_fields,
    }


def controlled_rejection_reason(reason: object, item: object) -> str:
    """Map arbitrary local error text to a stable, bounded reason code."""

    if isinstance(reason, str) and reason in _REJECTION_REASON_CODES:
        return reason
    if not isinstance(item, Mapping):
        return "item_not_mapping"
    return "normalization_error"


def redact_bounded_json(
    value: object, *, max_string_length: int = 512, _nested: bool = False
) -> object:
    """Redact sensitive keys and bound untrusted JSON before persistence."""
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        result: dict[str, object] = {}
        redacted_fields: list[str] = []
        for key, item in mapping.items():
            name = str(key)
            normalized = "".join(character for character in name.lower() if character.isalnum())
            if normalized in _SENSITIVE_KEYS:
                redacted_fields.append(hashlib.sha256(name.encode("utf-8")).hexdigest()[:16])
                continue
            result[name] = redact_bounded_json(
                item, max_string_length=max_string_length, _nested=True
            )
        if redacted_fields:
            result["_redacted_fields"] = sorted(redacted_fields)
        return result
    if isinstance(value, (list, tuple)):
        sequence = cast(tuple[object, ...] | list[object], value)
        return [
            redact_bounded_json(item, max_string_length=max_string_length, _nested=True)
            for item in sequence
        ]
    if isinstance(value, str):
        if not _nested:
            return {
                "type": "str",
                "digest": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            }
        return value if len(value) <= max_string_length else value[:max_string_length] + "..."
    if isinstance(value, Decimal):
        return str(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return {
        "type": type(value).__name__,
        "digest": hashlib.sha256(str(value).encode("utf-8")).hexdigest(),
    }


@dataclass(frozen=True, slots=True)
class EvidenceEnvelope:
    """Audit envelope retained with every accepted or rejected item."""

    raw_capture_id: str
    raw_object_id: str
    checksum: str
    source: str
    source_revision: str | None
    schema_version: str
    normalizer_version: str
    payload_digest: str
    item_ordinal: int
    event_time: datetime | None = None
    publish_time: datetime | None = None
    ingest_time: datetime | None = None
    available_time: datetime | None = None
    processing_time: datetime | None = None

    def __post_init__(self) -> None:
        if not self.raw_capture_id.strip() or not self.raw_object_id.strip():
            raise ValueError("raw capture/object identity is required")
        if not self.checksum:
            raise ValueError("checksum is required")
        normalized_digest = self.payload_digest.lower()
        if not _is_digest(normalized_digest):
            raise ValueError("payload_digest must be a 64-character lowercase hexadecimal digest")
        object.__setattr__(self, "payload_digest", normalized_digest)
        if type(self.item_ordinal) is not int or self.item_ordinal < 0:
            raise ValueError("item_ordinal must be a non-negative integer")
        for name in (
            "event_time",
            "publish_time",
            "ingest_time",
            "available_time",
            "processing_time",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _utc(value))

    @property
    def record_id(self) -> str:
        """Stable identity derived only from capture identity and ordinal."""
        return f"{self.raw_capture_id}:{self.item_ordinal}"

    @property
    def raw_evidence_id(self) -> str:
        """Alias used by quality/evidence consumers."""
        return self.record_id


@dataclass(frozen=True, slots=True)
class RejectedObservation:
    """A normalized record rejected with a bounded reason and evidence."""

    record_id: str
    kind: str
    payload: dict[str, object]
    reason: str
    evidence: EvidenceEnvelope

    def __post_init__(self) -> None:
        if self.evidence.record_id != self.record_id:
            raise ValueError("rejection record/evidence identity mismatch")
        if len(self.reason) > 512:
            raise ValueError("rejection reason is too long")


def controlled_rejection(item: RejectedObservation) -> RejectedObservation:
    """Normalize a rejection before any adapter stores or returns it."""

    if not _is_digest(item.evidence.payload_digest):
        raise ValueError("payload_digest must be a 64-character lowercase hexadecimal digest")
    return RejectedObservation(
        record_id=item.record_id,
        kind=item.kind,
        payload=controlled_rejection_payload(
            item.payload,
            digest=item.evidence.payload_digest,
            field_names=[],
        ),
        reason=controlled_rejection_reason(item.reason, item.payload),
        evidence=item.evidence,
    )


@dataclass(frozen=True, slots=True)
class FundQualityEvent:
    """Durable quality event; evidence links preserve every source candidate."""

    event_id: str
    kind: str
    semantic_key: str
    detail: str
    evidence_ids: tuple[str, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", _utc(self.created_at))
        if len(self.detail) > 2048:
            raise ValueError("quality detail is too long")


def controlled_quality_event(event: FundQualityEvent) -> FundQualityEvent:
    """Normalize quality events to bounded, value-free durable fields."""

    if not event.kind:
        raise ValueError("quality event kind must be non-empty")
    if len(event.kind) > 64 or not event.kind.isascii():
        raise ValueError("quality event kind is invalid")
    if len(event.semantic_key) > 512:
        raise ValueError("quality event semantic_key is invalid")
    prefix = f"{event.kind}:detail_sha256="
    detail = event.detail.strip()
    if detail.startswith(prefix) and _is_digest(detail[len(prefix) :]):
        safe_detail = detail
    else:
        safe_detail = prefix + hashlib.sha256(detail.encode("utf-8")).hexdigest()
    evidence_ids = tuple(sorted(event.evidence_ids))
    if any(not evidence_id for evidence_id in evidence_ids):
        raise ValueError("quality event evidence_ids must be non-empty strings")
    return FundQualityEvent(
        event_id=event.event_id,
        kind=event.kind,
        semantic_key=event.semantic_key,
        detail=safe_detail,
        evidence_ids=evidence_ids,
        created_at=event.created_at,
    )


def _quality_event_content(event: FundQualityEvent) -> tuple[object, ...]:
    return (event.kind, event.semantic_key, event.detail, tuple(sorted(event.evidence_ids)))


@dataclass(frozen=True, slots=True)
class PageCommitResult:
    """Counts returned after an atomic page commit."""

    accepted: int
    rejected: int
    quality_events: int
    checkpoint: dict[str, object]


@dataclass(frozen=True, slots=True)
class StoredFundObservation:
    """Typed read model returned by the PostgreSQL semantic-candidate port."""

    kind: str
    observation_id: str
    semantic_key: str
    payload: dict[str, object]
    evidence: EvidenceEnvelope
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LeaseContext:
    """Small owner context passed from the scheduler to a page commit."""

    task_id: str
    lease_token: str
    lease_expires_at: datetime

    def valid_at(self, now: datetime) -> bool:
        return bool(self.lease_token) and _utc(self.lease_expires_at) > _utc(now)


class FundPersistence(Protocol):
    """Port implemented by in-memory and PostgreSQL fund stores."""

    def commit_page(
        self,
        *,
        accepted: Sequence[object],
        rejected: Sequence[RejectedObservation],
        quality_events: Sequence[FundQualityEvent],
        checkpoint: dict[str, object],
        context: LeaseContext | None = None,
        checkpoint_key: str | None = None,
    ) -> PageCommitResult: ...

    def observations(self, kind: str | None = None) -> Sequence[object]: ...

    def rejections(self) -> list[RejectedObservation]: ...

    def quality_events(self) -> list[FundQualityEvent]: ...

    def evidence(self) -> list[EvidenceEnvelope]: ...

    def get_checkpoint(self, task_id: str) -> dict[str, object] | None: ...


def _observation_evidence(observation: object) -> EvidenceEnvelope:
    evidence = getattr(observation, "evidence", None)
    if not isinstance(evidence, EvidenceEnvelope):
        raise TypeError("accepted observation must expose EvidenceEnvelope as evidence")
    return evidence


def _observation_kind(observation: object) -> str:
    return str(getattr(observation, "kind", ""))


def _observation_payload(observation: object) -> dict[str, object]:
    payload = getattr(observation, "payload", None)
    if isinstance(payload, dict):
        payload_dict = cast(dict[str, object], payload)
        return copy.deepcopy(payload_dict)
    data = getattr(observation, "to_dict", None)
    if callable(data):
        result = data()
        if isinstance(result, dict):
            return cast(dict[str, object], result)
    # Dataclass/domain instances are serialized only for the persistence fake;
    # the PostgreSQL adapter stores the same bounded JSON shape.
    return {"value": repr(observation)}


def _evidence_content(evidence: EvidenceEnvelope) -> tuple[object, ...]:
    """Return immutable evidence fields excluding the first-write clock."""

    return (
        evidence.raw_capture_id,
        evidence.raw_object_id,
        evidence.checksum,
        evidence.source,
        evidence.source_revision,
        evidence.schema_version,
        evidence.normalizer_version,
        evidence.payload_digest,
        evidence.item_ordinal,
        evidence.event_time,
        evidence.publish_time,
        evidence.ingest_time,
        evidence.available_time,
    )


def _rejection_content(item: RejectedObservation) -> tuple[object, ...]:
    """Compare a rejection without treating processing time as immutable."""

    return (item.record_id, item.kind, item.payload, item.reason, _evidence_content(item.evidence))


def _logical_observation_id(observation: object) -> str:
    """Derive the stable logical identity independently of capture identity."""

    evidence = _observation_evidence(observation)
    payload = _observation_payload(observation)
    kind = _observation_kind(observation)
    code = payload.get("unifiedCode", payload.get("unified_code", ""))
    reference_date = payload.get(
        "date", payload.get("reference_date", payload.get("validFrom", ""))
    )
    semantic_key = f"{kind}:{code}:{reference_date}"
    content_digest = _digest(payload)
    route = f"{evidence.source_revision or ''}"
    digest = _digest((kind, evidence.source, semantic_key, route, content_digest))
    return f"obs-{digest}"


class StorageConflictError(ValueError):
    """A stable record/evidence identity was reused for different content."""


class LeaseFenceError(RuntimeError):
    """A stale or taken-over owner attempted an atomic page commit."""


def fund_checkpoint_key(owner_task_id: str, kind: str, exchange: str) -> str:
    """Return a bounded route-specific checkpoint key.

    The scheduler task remains the lease owner, while persisted checkpoint rows
    are isolated by endpoint route.  The owner identifier is represented only
    by a short digest so checkpoint storage never mirrors an untrusted task
    string or a remote cursor.
    """

    values = (owner_task_id, kind, exchange)
    if any(not value for value in values):
        raise ValueError("checkpoint route values must be non-empty strings")
    if any(len(value) > 128 for value in values):
        raise ValueError("checkpoint route value is too long")
    if any(
        any(
            not (character.isascii() and (character.isalnum() or character in "_.-"))
            for character in value
        )
        for value in values
    ):
        raise ValueError("checkpoint route values contain unsafe characters")
    owner_digest = hashlib.sha256(owner_task_id.encode("utf-8")).hexdigest()[:24]
    return f"fund:{kind}:{exchange}:{owner_digest}"


def _safe_checkpoint_state(checkpoint: Mapping[str, object]) -> dict[str, object]:
    """Validate the immutable attempt state before either adapter persists it."""

    state = copy.deepcopy(dict(checkpoint))
    if "next_cursor" in state or "consumed_cursors" in state:
        raise ValueError("checkpoint must not persist a remote cursor")
    attempt_id = state.get("attempt_id")
    if attempt_id is not None and (
        not isinstance(attempt_id, str)
        or not attempt_id
        or len(attempt_id) > 64
        or any(
            not (character.isascii() and (character.isalnum() or character in "._-"))
            for character in attempt_id
        )
    ):
        raise ValueError("checkpoint attempt_id is invalid")
    committed_page_count = state.get("committed_page_count")
    if committed_page_count is not None and (
        type(committed_page_count) is not int or committed_page_count < 0
    ):
        raise ValueError("checkpoint committed_page_count must be non-negative")
    return state


class InMemoryFundStorage:
    """Deterministic persistence fake with idempotent record/evidence writes."""

    def __init__(self, *, lease_store: object | None = None, now: object | None = None) -> None:
        self._observations: dict[str, object] = {}
        self._observation_payloads: dict[str, str] = {}
        self._logical_ids: dict[str, str] = {}
        self._evidence: dict[str, EvidenceEnvelope] = {}
        self._rejections: dict[str, RejectedObservation] = {}
        self._quality_events: dict[str, FundQualityEvent] = {}
        self._checkpoints: dict[str, dict[str, object]] = {}
        self._lease_store = lease_store
        self._now = now if callable(now) else (lambda: datetime.now(UTC))

    def _verify_lease(self, context: LeaseContext | None) -> None:
        if context is None:
            return
        now = _utc(cast(Any, self._now)())
        if not context.valid_at(now):
            raise LeaseFenceError("lease expired before page commit")
        if self._lease_store is None:
            return
        get = getattr(self._lease_store, "get", None)
        if not callable(get):
            raise LeaseFenceError("lease store does not expose get")
        record = get(context.task_id)
        record_expiry = cast(Any, record).lease_expires_at
        if (
            getattr(record, "lease_token", None) != context.lease_token
            or record_expiry is None
            or _utc(record_expiry) <= now
        ):
            raise LeaseFenceError("lease token is stale or owned by another worker")

    def commit_page(
        self,
        *,
        accepted: Sequence[object],
        rejected: Sequence[RejectedObservation],
        quality_events: Sequence[FundQualityEvent],
        checkpoint: dict[str, object],
        context: LeaseContext | None = None,
        checkpoint_key: str | None = None,
    ) -> PageCommitResult:
        self._verify_lease(context)
        checkpoint = _safe_checkpoint_state(checkpoint)
        task_id = checkpoint_key or (context.task_id if context is not None else "default")
        if not task_id:
            raise ValueError("checkpoint key must be a non-empty string")
        safe_rejected = tuple(controlled_rejection(item) for item in rejected)
        safe_quality_events = tuple(controlled_quality_event(event) for event in quality_events)
        # Validate and stage every item before mutating any state.  This gives
        # the fake the same all-or-nothing semantics as the PostgreSQL adapter.
        staged_observations: list[tuple[str, str, object, str, EvidenceEnvelope]] = []
        staged_claims: dict[str, str] = {}
        staged_payloads: dict[str, str] = {}
        staged_evidence: dict[str, EvidenceEnvelope] = {}
        staged_rejection_ids: set[str] = set()
        for observation in accepted:
            evidence = _observation_evidence(observation)
            record_id = evidence.record_id
            logical_id = _logical_observation_id(observation)
            payload = _observation_payload(observation)
            payload_digest = _digest(payload)
            existing_payload = self._observation_payloads.get(record_id)
            staged_payload = staged_payloads.get(record_id)
            if (existing_payload is not None and existing_payload != payload_digest) or (
                staged_payload is not None and staged_payload != payload_digest
            ):
                raise StorageConflictError(f"record {record_id} already stores different content")
            existing_claim = self._logical_ids.get(record_id)
            staged_claim = staged_claims.get(record_id)
            if (existing_claim is not None and existing_claim != logical_id) or (
                staged_claim is not None and staged_claim != logical_id
            ):
                raise StorageConflictError(
                    f"record {record_id} already claims a different observation"
                )
            if record_id in self._rejections or record_id in staged_rejection_ids:
                raise StorageConflictError(f"record {record_id} already stores a rejection")
            prior_evidence = self._evidence.get(record_id)
            staged_prior_evidence = staged_evidence.get(record_id)
            if prior_evidence is not None and _evidence_content(
                prior_evidence
            ) != _evidence_content(evidence):
                raise StorageConflictError(f"record {record_id} already stores different evidence")
            if staged_prior_evidence is not None and _evidence_content(
                staged_prior_evidence
            ) != _evidence_content(evidence):
                raise StorageConflictError(f"record {record_id} already stores different evidence")
            staged_claims[record_id] = logical_id
            staged_payloads[record_id] = payload_digest
            staged_evidence.setdefault(record_id, evidence)
            staged_observations.append(
                (logical_id, record_id, observation, payload_digest, evidence)
            )
        for item in safe_rejected:
            if item.evidence.record_id != item.record_id:
                raise StorageConflictError("rejection evidence identity mismatch")
            record_id = item.record_id
            if record_id in self._logical_ids or record_id in staged_claims:
                raise StorageConflictError(
                    f"record {record_id} already stores an accepted observation"
                )
            if record_id in staged_rejection_ids:
                prior = next(
                    candidate for candidate in safe_rejected if candidate.record_id == record_id
                )
                if _rejection_content(prior) != _rejection_content(item):
                    raise StorageConflictError(
                        f"rejection {record_id} already stores different content"
                    )
            existing_rejection = self._rejections.get(record_id)
            if existing_rejection is not None and _rejection_content(
                existing_rejection
            ) != _rejection_content(item):
                raise StorageConflictError(
                    f"rejection {record_id} already stores different content"
                )
            prior_evidence = self._evidence.get(record_id)
            if prior_evidence is not None and _evidence_content(
                prior_evidence
            ) != _evidence_content(item.evidence):
                raise StorageConflictError(f"record {record_id} already stores different evidence")
            staged_rejection_ids.add(record_id)
            staged_evidence.setdefault(record_id, item.evidence)
        for event in safe_quality_events:
            existing_event = self._quality_events.get(event.event_id)
            if existing_event is not None and _quality_event_content(
                existing_event
            ) != _quality_event_content(event):
                raise StorageConflictError(
                    f"quality event {event.event_id} already stores different content"
                )

        # Commit accepted observations/evidence and keep duplicate retries no-op.
        for logical_id, record_id, observation, payload_digest, evidence in staged_observations:
            self._evidence.setdefault(record_id, evidence)
            self._observations.setdefault(logical_id, observation)
            self._observation_payloads.setdefault(record_id, payload_digest)
            self._logical_ids[record_id] = logical_id
        for item in safe_rejected:
            prior = self._rejections.get(item.record_id)
            if prior is not None and _rejection_content(prior) != _rejection_content(item):
                raise StorageConflictError(
                    f"rejection {item.record_id} already stores different content"
                )
            self._rejections.setdefault(item.record_id, item)
            self._evidence.setdefault(item.record_id, item.evidence)
        for event in safe_quality_events:
            self._quality_events.setdefault(event.event_id, event)
        self._checkpoints[task_id] = copy.deepcopy(checkpoint)
        return PageCommitResult(
            accepted=len(staged_observations),
            rejected=len(safe_rejected),
            quality_events=len(safe_quality_events),
            checkpoint=copy.deepcopy(checkpoint),
        )

    def observations(self, kind: str | None = None) -> list[object]:
        values = list(self._observations.values())
        if kind is None:
            return values
        return [item for item in values if _observation_kind(item) == kind]

    def rejections(self) -> list[RejectedObservation]:
        return list(self._rejections.values())

    def quality_events(self) -> list[FundQualityEvent]:
        return list(self._quality_events.values())

    def get_checkpoint(self, task_id: str) -> dict[str, object] | None:
        value = self._checkpoints.get(task_id)
        return None if value is None else copy.deepcopy(value)

    def evidence(self) -> list[EvidenceEnvelope]:
        return list(self._evidence.values())


class PostgresFundStorage:
    """Synchronous PostgreSQL adapter for one-page atomic commits."""

    def __init__(self, connection: Connection[Any], *, now: object | None = None) -> None:
        self._connection = connection
        self._now = now if callable(now) else (lambda: datetime.now(UTC))

    def migrate(self) -> None:
        """Apply the additive fund schema explicitly (never on import)."""
        from data_worker.storage.migrations import apply_precious_metals_migration

        apply_precious_metals_migration(self._connection)

    def commit_page(
        self,
        *,
        accepted: Sequence[object],
        rejected: Sequence[RejectedObservation],
        quality_events: Sequence[FundQualityEvent],
        checkpoint: dict[str, object],
        context: LeaseContext | None = None,
        checkpoint_key: str | None = None,
    ) -> PageCommitResult:
        if context is None:
            raise LeaseFenceError("PostgreSQL page commits require an owner lease context")
        checkpoint = _safe_checkpoint_state(checkpoint)
        safe_rejected = tuple(controlled_rejection(item) for item in rejected)
        task_id = context.task_id
        storage_checkpoint_key = checkpoint_key or task_id
        if checkpoint_key is not None:
            kind = checkpoint.get("kind")
            exchange = checkpoint.get("exchange")
            if not isinstance(kind, str) or not isinstance(exchange, str):
                raise ValueError("checkpoint route is required with checkpoint_key")
            expected_key = fund_checkpoint_key(context.task_id, kind, exchange)
            if checkpoint_key != expected_key:
                raise LeaseFenceError("checkpoint key is not owned by the active lease")
        try:
            with self._connection.transaction(), self._connection.cursor() as cursor:
                cursor.execute(
                    """
                        SELECT lease_token, lease_expires_at
                          FROM tasks
                         WHERE id = %s
                           AND lease_token = %s
                           AND lease_expires_at > CURRENT_TIMESTAMP
                         FOR UPDATE
                        """,
                    (task_id, context.lease_token),
                )
                row = cursor.fetchone()
                now = cast(Any, self._now)()
                if row is None or row[0] != context.lease_token or row[1] is None:
                    raise LeaseFenceError("lease token is stale or task is missing")
                if _utc(cast(datetime, row[1])) <= _utc(cast(datetime, now)):
                    raise LeaseFenceError("lease expired before page commit")

                for observation in accepted:
                    _insert_evidence(cursor, _observation_evidence(observation))
                    _insert_observation(cursor, observation)
                for item in safe_rejected:
                    _insert_evidence(cursor, item.evidence)
                    _insert_rejection(cursor, item)
                for event in quality_events:
                    _insert_quality_event(cursor, event)
                cursor.execute(
                    """
                        INSERT INTO checkpoints (task_id, cursor, state, updated_at)
                        VALUES (%s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                        ON CONFLICT (task_id) DO UPDATE
                           SET cursor = EXCLUDED.cursor,
                               state = EXCLUDED.state,
                               updated_at = EXCLUDED.updated_at
                        """,
                    (
                        storage_checkpoint_key,
                        None,
                        json.dumps(checkpoint, ensure_ascii=False, default=str),
                    ),
                )
        except LeaseFenceError:
            raise
        return PageCommitResult(
            accepted=len(accepted),
            rejected=len(safe_rejected),
            quality_events=len(quality_events),
            checkpoint=copy.deepcopy(checkpoint),
        )

    def observations(self, kind: str | None = None) -> list[StoredFundObservation]:
        """Read semantic candidates with their persisted evidence envelope.

        The adapter deliberately returns a typed domain model rather than
        leaking database tuples.  The current additive schema stores the
        observation's creation timestamp on the evidence envelope, so the
        processing/ingest/available timestamp is used as the read model's
        ``created_at`` in that order.
        """
        tables = {
            "metadata": "fund_metadata_observations",
            "nav": "fund_nav_observations",
            "inav": "fund_inav_observations",
            "benchmark": "fund_benchmark_observations",
            "fees": "fund_fee_observations",
        }
        kinds = tuple(tables) if kind is None else (kind,)
        unknown = [candidate for candidate in kinds if candidate not in tables]
        if unknown:
            raise ValueError(f"unsupported observation kind: {unknown[0]}")
        result: list[StoredFundObservation] = []
        with self._connection.cursor() as cursor:
            for candidate in kinds:
                if candidate == "metadata":
                    cursor.execute(
                        "SELECT DISTINCT ON (observation_id) record_id, observation_id, "
                        "unified_code, payload, semantic_key, evidence_id "
                        "FROM fund_metadata_observations ORDER BY observation_id, record_id"
                    )
                    rows = cursor.fetchall()
                    for row in rows:
                        evidence = _read_evidence(cursor, str(row[5]))
                        payload = _json_mapping(row[3])
                        result.append(
                            StoredFundObservation(
                                kind="metadata",
                                observation_id=str(row[1]),
                                semantic_key=str(row[4]),
                                payload=payload,
                                evidence=evidence,
                                created_at=_evidence_created_at(evidence, self._now),
                            )
                        )
                    continue
                if candidate == "benchmark":
                    cursor.execute(
                        "SELECT DISTINCT ON (observation_id) record_id, observation_id, "
                        "unified_code, reference_date, benchmark, semantic_key, evidence_id "
                        "FROM fund_benchmark_observations ORDER BY observation_id, record_id"
                    )
                else:
                    value_column = "management_fee_rate" if candidate == "fees" else "value"
                    query = (
                        f"SELECT DISTINCT ON (observation_id) record_id, observation_id, "
                        f"unified_code, reference_date, {value_column}, semantic_key, evidence_id "
                        f"FROM {tables[candidate]} ORDER BY observation_id, record_id"
                    )
                    # ``tables`` is a closed, internal allowlist; this is the
                    # adapter's dynamic SQL boundary.
                    cursor.execute(cast(Any, query))
                rows = cursor.fetchall()
                for row in rows:
                    evidence = _read_evidence(cursor, str(row[6]))
                    date_value = row[3]
                    date_text = (
                        date_value.isoformat()
                        if hasattr(date_value, "isoformat")
                        else str(date_value)
                    )
                    value_key = {
                        "nav": "nav",
                        "inav": "inav",
                        "fees": "managementFeeRate",
                        "benchmark": "benchmarkOrTrackingIndex",
                    }[candidate]
                    payload: dict[str, object] = {
                        "unifiedCode": str(row[2]),
                        "date": date_text,
                        value_key: str(row[4]),
                    }
                    result.append(
                        StoredFundObservation(
                            kind=candidate,
                            observation_id=str(row[1]),
                            semantic_key=str(row[5]),
                            payload=payload,
                            evidence=evidence,
                            created_at=_evidence_created_at(evidence, self._now),
                        )
                    )
        return result

    def rejections(self) -> list[RejectedObservation]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT record_id, kind, reason, payload, raw_capture_id "
                "FROM fund_rejections ORDER BY record_id"
            )
            result: list[RejectedObservation] = []
            for row in cursor.fetchall():
                record_id = str(row[0])
                evidence = _read_evidence(cursor, record_id)
                if evidence.raw_capture_id != str(row[4]):
                    raise StorageConflictError(
                        f"rejection {record_id} disagrees with evidence capture"
                    )
                result.append(
                    controlled_rejection(
                        RejectedObservation(
                            record_id=record_id,
                            kind=str(row[1]),
                            payload=_json_mapping(row[3]),
                            reason=str(row[2]),
                            evidence=evidence,
                        )
                    )
                )
            return result

    def quality_events(self) -> list[FundQualityEvent]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT event_id, kind, semantic_key, detail, created_at "
                "FROM fund_quality_events ORDER BY event_id"
            )
            result: list[FundQualityEvent] = []
            for row in cursor.fetchall():
                event_id = str(row[0])
                cursor.execute(
                    "SELECT evidence_id FROM fund_quality_event_evidence "
                    "WHERE quality_event_id = %s ORDER BY evidence_id",
                    (event_id,),
                )
                evidence_ids = tuple(str(link[0]) for link in cursor.fetchall())
                result.append(
                    controlled_quality_event(
                        FundQualityEvent(
                            event_id=event_id,
                            kind=str(row[1]),
                            semantic_key=str(row[2]),
                            detail=str(row[3]),
                            evidence_ids=evidence_ids,
                            created_at=cast(datetime, row[4]),
                        )
                    )
                )
            return result

    def evidence(self) -> list[EvidenceEnvelope]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT record_id, raw_capture_id, raw_object_id, checksum, source, "
                "source_revision, schema_version, normalizer_version, payload_digest, "
                "item_ordinal, event_time, publish_time, ingest_time, available_time, "
                "processing_time FROM fund_observation_evidence ORDER BY record_id"
            )
            return [_evidence_from_row(row) for row in cursor.fetchall()]

    def get_checkpoint(self, task_id: str) -> dict[str, object] | None:
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT state FROM checkpoints WHERE task_id = %s", (task_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            value = row[0]
            return cast(dict[str, object], value if isinstance(value, dict) else json.loads(value))


_OBSERVATION_TABLES = (
    ("metadata", "fund_metadata_observations"),
    ("nav", "fund_nav_observations"),
    ("inav", "fund_inav_observations"),
    ("benchmark", "fund_benchmark_observations"),
    ("fees", "fund_fee_observations"),
)


def _ensure_record_claim(
    cursor: Any,
    record_id: str,
    kind: str,
    logical_id: str | None,
    *,
    rejected: bool,
) -> None:
    """Serialize the single accepted/rejected claim for one evidence record."""

    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        (f"kunlun-fund-record:{record_id}",),
    )
    cursor.execute("SELECT 1 FROM fund_rejections WHERE record_id = %s", (record_id,))
    has_rejection = cursor.fetchone() is not None
    claims: list[tuple[str, str]] = []
    for candidate_kind, table in _OBSERVATION_TABLES:
        cursor.execute(f"SELECT observation_id FROM {table} WHERE record_id = %s", (record_id,))
        row = cursor.fetchone()
        if row is not None:
            claims.append((candidate_kind, str(row[0])))
    if rejected:
        if claims:
            raise StorageConflictError(f"record {record_id} already stores an accepted observation")
        return
    if has_rejection:
        raise StorageConflictError(f"record {record_id} already stores a rejection")
    for claimed_kind, claimed_logical_id in claims:
        if claimed_kind != kind or claimed_logical_id != logical_id:
            raise StorageConflictError(f"record {record_id} already claims a different observation")


def _insert_rejection(cursor: Any, item: RejectedObservation) -> None:
    item = controlled_rejection(item)
    _ensure_record_claim(cursor, item.record_id, item.kind, None, rejected=True)
    safe_payload = item.payload
    encoded_payload = json.dumps(safe_payload, ensure_ascii=False, default=str)
    cursor.execute(
        "SELECT kind, reason, payload, raw_capture_id FROM fund_rejections WHERE record_id = %s",
        (item.record_id,),
    )
    existing = cursor.fetchone()
    if existing is not None:
        current = {
            "kind": str(existing[0]),
            "reason": str(existing[1]),
            "payload": existing[2],
            "raw_capture_id": str(existing[3]),
        }
        expected = {
            "kind": item.kind,
            "reason": item.reason,
            "payload": safe_payload,
            "raw_capture_id": item.evidence.raw_capture_id,
        }
        if _digest(current) != _digest(expected):
            raise StorageConflictError(
                f"rejection {item.record_id} already stores different content"
            )
        return
    cursor.execute(
        """
            INSERT INTO fund_rejections
              (record_id, kind, reason, payload, raw_capture_id)
            VALUES (%s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (record_id) DO UPDATE
              SET record_id = EXCLUDED.record_id
            WHERE fund_rejections.kind IS NOT DISTINCT FROM EXCLUDED.kind
              AND fund_rejections.reason IS NOT DISTINCT FROM EXCLUDED.reason
              AND fund_rejections.payload IS NOT DISTINCT FROM EXCLUDED.payload
              AND fund_rejections.raw_capture_id IS NOT DISTINCT FROM EXCLUDED.raw_capture_id
            RETURNING record_id
            """,
        (
            item.record_id,
            item.kind,
            item.reason,
            encoded_payload,
            item.evidence.raw_capture_id,
        ),
    )
    if cursor.fetchone() is None:
        raise StorageConflictError(f"rejection {item.record_id} already stores different content")


def _insert_quality_event(cursor: Any, event: FundQualityEvent) -> None:
    event = controlled_quality_event(event)
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        (f"kunlun-fund-quality:{event.event_id}",),
    )
    cursor.execute(
        "SELECT kind, semantic_key, detail, created_at FROM fund_quality_events "
        "WHERE event_id = %s",
        (event.event_id,),
    )
    existing = cursor.fetchone()
    if existing is not None and (
        str(existing[0]) != event.kind
        or str(existing[1]) != event.semantic_key
        or str(existing[2]) != event.detail
    ):
        raise StorageConflictError(
            f"quality event {event.event_id} already stores different content"
        )
    if existing is None:
        cursor.execute(
            """
                INSERT INTO fund_quality_events
                  (event_id, kind, semantic_key, detail, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO UPDATE
                  SET event_id = EXCLUDED.event_id
                  WHERE fund_quality_events.kind IS NOT DISTINCT FROM EXCLUDED.kind
                  AND fund_quality_events.semantic_key IS NOT DISTINCT FROM EXCLUDED.semantic_key
                  AND fund_quality_events.detail IS NOT DISTINCT FROM EXCLUDED.detail
                RETURNING event_id
                """,
            (event.event_id, event.kind, event.semantic_key, event.detail, event.created_at),
        )
        if cursor.fetchone() is None:
            raise StorageConflictError(
                f"quality event {event.event_id} already stores different content"
            )
    cursor.execute(
        "SELECT evidence_id FROM fund_quality_event_evidence "
        "WHERE quality_event_id = %s ORDER BY evidence_id",
        (event.event_id,),
    )
    existing_links = cursor.fetchall()
    existing_ids = tuple(str(row[0]) for row in existing_links)
    expected_ids = tuple(sorted(event.evidence_ids))
    if existing is not None and existing_ids != expected_ids:
        raise StorageConflictError(f"quality event {event.event_id} has different evidence links")
    for evidence_id in expected_ids:
        cursor.execute(
            """
                INSERT INTO fund_quality_event_evidence
                  (quality_event_id, evidence_id)
                VALUES (%s, %s)
                ON CONFLICT (quality_event_id, evidence_id) DO UPDATE
                  SET quality_event_id = EXCLUDED.quality_event_id
                RETURNING quality_event_id, evidence_id
                """,
            (event.event_id, evidence_id),
        )
        if cursor.fetchone() is None:
            raise StorageConflictError(f"quality event {event.event_id} evidence link conflict")


def _insert_evidence(cursor: Any, evidence: EvidenceEnvelope) -> None:
    # Serialize retries for one evidence identity across independent lease
    # owners.  The lock is transaction-scoped and keeps the exact read/compare
    # decision atomic without relying on a particular unique-index arbiter.
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        (f"kunlun-fund-evidence:{evidence.record_id}",),
    )
    cursor.execute(
        """
        SELECT record_id, raw_capture_id, raw_object_id, checksum, source,
               source_revision, schema_version, normalizer_version,
               payload_digest, item_ordinal, event_time, publish_time,
               ingest_time, available_time, processing_time
          FROM fund_observation_evidence
         WHERE record_id = %s
        """,
        (evidence.record_id,),
    )
    existing = cursor.fetchone()
    if existing is not None:
        if _evidence_content(_evidence_from_row(existing)) != _evidence_content(evidence):
            raise StorageConflictError(
                f"evidence {evidence.record_id} already stores different content"
            )
        return
    try:
        cursor.execute(
            """
            INSERT INTO fund_observation_evidence
              (record_id, raw_capture_id, raw_object_id, checksum, source,
               source_revision, schema_version, normalizer_version, payload_digest,
               item_ordinal, event_time, publish_time, ingest_time,
               available_time, processing_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (record_id) DO UPDATE
              SET record_id = EXCLUDED.record_id
            WHERE fund_observation_evidence.record_id
                IS NOT DISTINCT FROM EXCLUDED.record_id
              AND fund_observation_evidence.raw_capture_id
                IS NOT DISTINCT FROM EXCLUDED.raw_capture_id
              AND fund_observation_evidence.raw_object_id
                IS NOT DISTINCT FROM EXCLUDED.raw_object_id
              AND fund_observation_evidence.checksum IS NOT DISTINCT FROM EXCLUDED.checksum
              AND fund_observation_evidence.source IS NOT DISTINCT FROM EXCLUDED.source
              AND fund_observation_evidence.source_revision
                IS NOT DISTINCT FROM EXCLUDED.source_revision
              AND fund_observation_evidence.schema_version
                IS NOT DISTINCT FROM EXCLUDED.schema_version
              AND fund_observation_evidence.normalizer_version
                IS NOT DISTINCT FROM EXCLUDED.normalizer_version
              AND fund_observation_evidence.payload_digest
                IS NOT DISTINCT FROM EXCLUDED.payload_digest
              AND fund_observation_evidence.item_ordinal IS NOT DISTINCT FROM EXCLUDED.item_ordinal
              AND fund_observation_evidence.event_time IS NOT DISTINCT FROM EXCLUDED.event_time
              AND fund_observation_evidence.publish_time IS NOT DISTINCT FROM EXCLUDED.publish_time
              AND fund_observation_evidence.ingest_time IS NOT DISTINCT FROM EXCLUDED.ingest_time
              AND fund_observation_evidence.available_time
                IS NOT DISTINCT FROM EXCLUDED.available_time
            RETURNING record_id
            """,
            (
                evidence.record_id,
                evidence.raw_capture_id,
                evidence.raw_object_id,
                evidence.checksum,
                evidence.source,
                evidence.source_revision,
                evidence.schema_version,
                evidence.normalizer_version,
                evidence.payload_digest,
                evidence.item_ordinal,
                evidence.event_time,
                evidence.publish_time,
                evidence.ingest_time,
                evidence.available_time,
                evidence.processing_time,
            ),
        )
    except Exception as exc:
        if exc.__class__.__name__ == "UniqueViolation":
            raise StorageConflictError(
                f"evidence {evidence.record_id} already stores different content"
            ) from exc
        raise
    if cursor.fetchone() is None:
        raise StorageConflictError(
            f"evidence {evidence.record_id} already stores different content"
        )


def _evidence_from_row(row: Sequence[object]) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        raw_capture_id=str(row[1]),
        raw_object_id=str(row[2]),
        checksum=str(row[3]),
        source=str(row[4]),
        source_revision=None if row[5] is None else str(row[5]),
        schema_version=str(row[6]),
        normalizer_version=str(row[7]),
        payload_digest=str(row[8]),
        item_ordinal=int(cast(str | int, row[9])),
        event_time=cast(datetime | None, row[10]),
        publish_time=cast(datetime | None, row[11]),
        ingest_time=cast(datetime | None, row[12]),
        available_time=cast(datetime | None, row[13]),
        processing_time=cast(datetime | None, row[14]),
    )


def _read_evidence(cursor: Any, evidence_id: str) -> EvidenceEnvelope:
    cursor.execute(
        """
        SELECT record_id, raw_capture_id, raw_object_id, checksum, source,
               source_revision, schema_version, normalizer_version,
               payload_digest, item_ordinal, event_time, publish_time,
               ingest_time, available_time, processing_time
          FROM fund_observation_evidence
         WHERE record_id = %s
        """,
        (evidence_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise StorageConflictError(f"missing evidence {evidence_id}")
    return _evidence_from_row(row)


def _json_mapping(value: object) -> dict[str, object]:
    """Decode a JSONB value without exposing an untyped database payload."""
    candidate: object = value
    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except json.JSONDecodeError:
            candidate = None
    if isinstance(candidate, dict):
        mapping = cast(dict[str, object], candidate)
        return copy.deepcopy(mapping)
    # The migration requires JSONB objects for metadata/rejection payloads;
    # return a bounded diagnostic if a legacy/rogue row violates that contract.
    safe = redact_bounded_json(candidate)
    if isinstance(safe, dict):
        return cast(dict[str, object], safe)
    return {"type": type(candidate).__name__, "digest": _digest(candidate)}


def _evidence_created_at(evidence: EvidenceEnvelope, now: object) -> datetime:
    for value in (
        evidence.processing_time,
        evidence.ingest_time,
        evidence.available_time,
        evidence.publish_time,
        evidence.event_time,
    ):
        if value is not None:
            return value
    return _utc(cast(Any, now)())


def _observation_semantic_key(observation: object) -> str:
    payload = _observation_payload(observation)
    kind = _observation_kind(observation)
    code = payload.get("unifiedCode", payload.get("unified_code", ""))
    reference_date = payload.get(
        "date", payload.get("reference_date", payload.get("validFrom", ""))
    )
    return f"{kind}:{code}:{reference_date}"


def _insert_logical_observation(cursor: Any, observation: object) -> str:
    evidence = _observation_evidence(observation)
    payload = _observation_payload(observation)
    kind = _observation_kind(observation)
    logical_id = _logical_observation_id(observation)
    semantic_key = _observation_semantic_key(observation)
    content_digest = _digest(payload)
    created_at = _evidence_created_at(evidence, lambda: datetime.now(UTC))
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        (f"kunlun-fund-logical:{logical_id}",),
    )
    cursor.execute(
        "SELECT kind, source, source_revision, semantic_key, content_digest, payload "
        "FROM fund_logical_observations WHERE observation_id = %s",
        (logical_id,),
    )
    existing = cursor.fetchone()
    expected = {
        "kind": kind,
        "source": evidence.source,
        "source_revision": evidence.source_revision,
        "semantic_key": semantic_key,
        "content_digest": content_digest,
        "payload": payload,
    }
    if existing is not None:
        current = {
            "kind": str(existing[0]),
            "source": str(existing[1]),
            "source_revision": None if existing[2] is None else str(existing[2]),
            "semantic_key": str(existing[3]),
            "content_digest": str(existing[4]),
            "payload": existing[5],
        }
        if _digest(current) != _digest(expected):
            raise StorageConflictError(
                f"logical observation {logical_id} already stores different content"
            )
    else:
        cursor.execute(
            """
            INSERT INTO fund_logical_observations
              (observation_id, kind, source, source_revision, semantic_key,
               content_digest, payload, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (observation_id) DO UPDATE
              SET observation_id = EXCLUDED.observation_id
            WHERE fund_logical_observations.kind IS NOT DISTINCT FROM EXCLUDED.kind
              AND fund_logical_observations.source IS NOT DISTINCT FROM EXCLUDED.source
              AND fund_logical_observations.source_revision
                IS NOT DISTINCT FROM EXCLUDED.source_revision
              AND fund_logical_observations.semantic_key IS NOT DISTINCT FROM EXCLUDED.semantic_key
              AND fund_logical_observations.content_digest
                IS NOT DISTINCT FROM EXCLUDED.content_digest
              AND fund_logical_observations.payload IS NOT DISTINCT FROM EXCLUDED.payload
            RETURNING observation_id
            """,
            (
                logical_id,
                kind,
                evidence.source,
                evidence.source_revision,
                semantic_key,
                content_digest,
                json.dumps(payload, default=str),
                created_at,
            ),
        )
        if cursor.fetchone() is None:
            raise StorageConflictError(
                f"logical observation {logical_id} already stores different content"
            )
    cursor.execute(
        """
        INSERT INTO fund_observation_evidence_links (observation_id, evidence_id)
        VALUES (%s, %s)
        ON CONFLICT (observation_id, evidence_id) DO UPDATE
          SET observation_id = EXCLUDED.observation_id
        RETURNING observation_id, evidence_id
        """,
        (logical_id, evidence.record_id),
    )
    if cursor.fetchone() is None:
        raise StorageConflictError(f"logical observation {logical_id} evidence link conflict")
    return logical_id


def _insert_observation(cursor: Any, observation: object) -> None:
    evidence = _observation_evidence(observation)
    kind = _observation_kind(observation)
    payload = _observation_payload(observation)
    logical_id = _logical_observation_id(observation)
    _ensure_record_claim(cursor, evidence.record_id, kind, logical_id, rejected=False)
    logical_id = _insert_logical_observation(cursor, observation)
    semantic_key = _observation_semantic_key(observation)
    unified_code = str(payload.get("unifiedCode", payload.get("unified_code", "")))
    reference_date = payload.get("date")
    value = {
        "nav": payload.get("nav"),
        "inav": payload.get("inav"),
        "fees": payload.get("managementFeeRate", payload.get("management_fee_rate")),
    }.get(kind)
    table = {
        "metadata": "fund_metadata_observations",
        "nav": "fund_nav_observations",
        "inav": "fund_inav_observations",
        "benchmark": "fund_benchmark_observations",
        "fees": "fund_fee_observations",
    }.get(kind)
    if table is None:
        raise ValueError(f"unsupported observation kind: {kind}")
    if kind == "metadata":
        cursor.execute(
            "SELECT observation_id, unified_code, payload, semantic_key, evidence_id "
            "FROM fund_metadata_observations "
            "WHERE record_id = %s",
            (evidence.record_id,),
        )
    elif kind == "benchmark":
        cursor.execute(
            "SELECT observation_id, unified_code, reference_date, benchmark, "
            "semantic_key, evidence_id FROM fund_benchmark_observations "
            "WHERE record_id = %s",
            (evidence.record_id,),
        )
    else:
        value_column = "management_fee_rate" if kind == "fees" else "value"
        cursor.execute(
            f"SELECT observation_id, unified_code, reference_date, {value_column}, "
            f"semantic_key, evidence_id FROM {table} "
            "WHERE record_id = %s",
            (evidence.record_id,),
        )
    existing = cursor.fetchone()
    if existing is not None:
        if kind == "metadata":
            current = {
                "observation_id": str(existing[0]),
                "unified_code": str(existing[1]),
                "payload": existing[2],
                "semantic_key": str(existing[3]),
                "evidence_id": str(existing[4]),
            }
            expected = {
                "observation_id": logical_id,
                "unified_code": unified_code,
                "payload": payload,
                "semantic_key": semantic_key,
                "evidence_id": evidence.record_id,
            }
        elif kind == "benchmark":
            current = {
                "observation_id": str(existing[0]),
                "unified_code": str(existing[1]),
                "reference_date": str(existing[2]),
                "benchmark": str(existing[3]),
                "semantic_key": str(existing[4]),
                "evidence_id": str(existing[5]),
            }
            expected = {
                "observation_id": logical_id,
                "unified_code": unified_code,
                "reference_date": str(reference_date),
                "benchmark": str(payload.get("benchmarkOrTrackingIndex", "")),
                "semantic_key": semantic_key,
                "evidence_id": evidence.record_id,
            }
        else:
            current = {
                "observation_id": str(existing[0]),
                "unified_code": str(existing[1]),
                "reference_date": str(existing[2]),
                "value": str(existing[3]),
                "semantic_key": str(existing[4]),
                "evidence_id": str(existing[5]),
            }
            expected = {
                "observation_id": logical_id,
                "unified_code": unified_code,
                "reference_date": str(reference_date),
                "value": str(Decimal(str(value))),
                "semantic_key": semantic_key,
                "evidence_id": evidence.record_id,
            }
        if _digest(current) != _digest(expected):
            raise StorageConflictError(
                f"observation {evidence.record_id} already stores different content"
            )
        return
    if kind == "metadata":
        cursor.execute(
            f"""
            INSERT INTO {table}
              (record_id, observation_id, unified_code, payload, semantic_key, evidence_id)
            VALUES (%s, %s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (record_id) DO UPDATE
              SET record_id = EXCLUDED.record_id
            WHERE {table}.observation_id IS NOT DISTINCT FROM EXCLUDED.observation_id
              AND {table}.unified_code IS NOT DISTINCT FROM EXCLUDED.unified_code
              AND {table}.payload IS NOT DISTINCT FROM EXCLUDED.payload
              AND {table}.semantic_key IS NOT DISTINCT FROM EXCLUDED.semantic_key
              AND {table}.evidence_id IS NOT DISTINCT FROM EXCLUDED.evidence_id
            RETURNING record_id
            """,
            (
                evidence.record_id,
                logical_id,
                unified_code,
                json.dumps(payload, default=str),
                semantic_key,
                evidence.record_id,
            ),
        )
        if cursor.fetchone() is None:
            raise StorageConflictError(
                f"observation {evidence.record_id} already stores different content"
            )
    elif kind == "benchmark":
        benchmark = payload.get("benchmarkOrTrackingIndex")
        if not isinstance(benchmark, str) or not benchmark:
            raise ValueError("benchmark observation is missing its benchmark")
        cursor.execute(
            f"""
            INSERT INTO {table}
              (record_id, observation_id, unified_code, reference_date,
               benchmark, semantic_key, evidence_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (record_id) DO UPDATE
              SET record_id = EXCLUDED.record_id
            WHERE {table}.observation_id IS NOT DISTINCT FROM EXCLUDED.observation_id
              AND {table}.unified_code IS NOT DISTINCT FROM EXCLUDED.unified_code
              AND {table}.reference_date IS NOT DISTINCT FROM EXCLUDED.reference_date
              AND {table}.benchmark IS NOT DISTINCT FROM EXCLUDED.benchmark
              AND {table}.semantic_key IS NOT DISTINCT FROM EXCLUDED.semantic_key
              AND {table}.evidence_id IS NOT DISTINCT FROM EXCLUDED.evidence_id
            RETURNING record_id
            """,
            (
                evidence.record_id,
                logical_id,
                unified_code,
                reference_date,
                benchmark,
                semantic_key,
                evidence.record_id,
            ),
        )
        if cursor.fetchone() is None:
            raise StorageConflictError(
                f"observation {evidence.record_id} already stores different content"
            )
    else:
        if value is None:
            raise ValueError(f"{kind} observation is missing its reference value")
        value_column = "management_fee_rate" if kind == "fees" else "value"
        cursor.execute(
            f"""
            INSERT INTO {table}
              (record_id, observation_id, unified_code, reference_date,
               {value_column}, semantic_key, evidence_id)
            VALUES (%s, %s, %s, %s, %s::numeric, %s, %s)
            ON CONFLICT (record_id) DO UPDATE
              SET record_id = EXCLUDED.record_id
            WHERE {table}.observation_id IS NOT DISTINCT FROM EXCLUDED.observation_id
              AND {table}.unified_code IS NOT DISTINCT FROM EXCLUDED.unified_code
              AND {table}.reference_date IS NOT DISTINCT FROM EXCLUDED.reference_date
              AND {table}.{value_column} IS NOT DISTINCT FROM EXCLUDED.{value_column}
              AND {table}.semantic_key IS NOT DISTINCT FROM EXCLUDED.semantic_key
              AND {table}.evidence_id IS NOT DISTINCT FROM EXCLUDED.evidence_id
            RETURNING record_id
            """,
            (
                evidence.record_id,
                logical_id,
                unified_code,
                reference_date,
                str(Decimal(str(value))),
                semantic_key,
                evidence.record_id,
            ),
        )
        if cursor.fetchone() is None:
            raise StorageConflictError(
                f"observation {evidence.record_id} already stores different content"
            )
