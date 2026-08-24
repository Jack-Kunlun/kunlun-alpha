"""Immutable raw and result contracts for Dragon-Tiger List collection."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from seat_core import SeatKind, Trade
from seat_core.resolution import ResolutionStatus


class SeatCollectionError(RuntimeError):
    """Base class for deterministic seat collection failures."""


class RevisionConflictError(SeatCollectionError):
    """The same revision identity was received with different immutable content."""


class BatchConflictError(SeatCollectionError):
    """A batch identity or immutable outcome was reused with different content."""


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _fingerprint(prefix: str, value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()}"


def _require_non_empty(value: str, name: str) -> None:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_aware(value: datetime | None, name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{name} must be timezone-aware")


def _parse_raw_decimal(value: object, name: str) -> Decimal:
    if type(value) is Decimal:
        parsed = value
    elif type(value) is str:
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"{name} must be an exact decimal") from exc
    else:
        raise TypeError(f"{name} must be Decimal or an exact decimal string")
    if not parsed.is_finite():
        raise ValueError(f"{name} must be finite")
    return parsed


def _raw_record_digest(
    *,
    source: str,
    source_version: str,
    trade_date: date,
    raw_seat_name: str,
    raw_instrument_id: str,
    revision_id: str,
    raw_payload_hash: str,
) -> str:
    material = "\0".join(
        (
            "seat-raw-record-v1",
            source,
            source_version,
            trade_date.isoformat(),
            raw_seat_name,
            raw_instrument_id,
            revision_id,
            raw_payload_hash,
        )
    ).encode("utf-8")
    return f"seat-raw-{hashlib.sha256(material).hexdigest()}"


@dataclass(frozen=True)
class RawSeatListRecord:
    """Exact provider observation; raw bytes and history are never overwritten."""

    raw_record_id: str
    revision_id: str
    previous_revision_id: str | None
    source: str
    source_version: str
    raw_payload: bytes
    raw_payload_hash: str
    trade_date: date
    event_time: datetime
    publish_time: datetime | None
    ingest_time: datetime
    available_time: datetime
    raw_seat_name: str
    listing_reason: str
    raw_instrument_id: str
    buy_amount: Decimal
    sell_amount: Decimal
    vendor_net_amount: Decimal
    evidence_id: str
    seat_kind_hint: SeatKind | None

    @classmethod
    def from_provider(
        cls,
        *,
        source: str,
        source_version: str,
        trade_date: date,
        event_time: datetime,
        publish_time: datetime | None,
        ingest_time: datetime,
        available_time: datetime,
        raw_seat_name: str,
        listing_reason: str,
        raw_instrument_id: str,
        buy_amount: object,
        sell_amount: object,
        vendor_net_amount: object,
        raw_payload: bytes,
        revision_id: str,
        previous_revision_id: str | None = None,
        seat_kind_hint: SeatKind | None = None,
    ) -> RawSeatListRecord:
        if type(raw_payload) is not bytes:
            raise TypeError("raw_payload must be bytes")
        payload_hash = hashlib.sha256(raw_payload).hexdigest()
        raw_record_id = _raw_record_digest(
            source=source,
            source_version=source_version,
            trade_date=trade_date,
            raw_seat_name=raw_seat_name,
            raw_instrument_id=raw_instrument_id,
            revision_id=revision_id,
            raw_payload_hash=payload_hash,
        )
        evidence_id = f"seat-source-evidence-{hashlib.sha256(raw_record_id.encode()).hexdigest()}"
        return cls(
            raw_record_id=raw_record_id,
            revision_id=revision_id,
            previous_revision_id=previous_revision_id,
            source=source,
            source_version=source_version,
            raw_payload=raw_payload,
            raw_payload_hash=payload_hash,
            trade_date=trade_date,
            event_time=event_time,
            publish_time=publish_time,
            ingest_time=ingest_time,
            available_time=available_time,
            raw_seat_name=raw_seat_name,
            listing_reason=listing_reason,
            raw_instrument_id=raw_instrument_id,
            buy_amount=_parse_raw_decimal(buy_amount, "buy_amount"),
            sell_amount=_parse_raw_decimal(sell_amount, "sell_amount"),
            vendor_net_amount=_parse_raw_decimal(vendor_net_amount, "vendor_net_amount"),
            evidence_id=evidence_id,
            seat_kind_hint=seat_kind_hint,
        )

    def __post_init__(self) -> None:
        _require_non_empty(self.raw_record_id, "raw_record_id")
        _require_non_empty(self.revision_id, "revision_id")
        if self.previous_revision_id == self.revision_id:
            raise ValueError("previous_revision_id must differ from revision_id")
        if self.previous_revision_id is not None:
            _require_non_empty(self.previous_revision_id, "previous_revision_id")
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        if type(self.raw_payload) is not bytes:
            raise TypeError("raw_payload must be bytes")
        if not _HASH_RE.fullmatch(self.raw_payload_hash):
            raise ValueError("raw_payload_hash must be a lowercase SHA-256 digest")
        if hashlib.sha256(self.raw_payload).hexdigest() != self.raw_payload_hash:
            raise ValueError("raw_payload_hash does not match raw_payload")
        expected_id = _raw_record_digest(
            source=self.source,
            source_version=self.source_version,
            trade_date=self.trade_date,
            raw_seat_name=self.raw_seat_name,
            raw_instrument_id=self.raw_instrument_id,
            revision_id=self.revision_id,
            raw_payload_hash=self.raw_payload_hash,
        )
        if self.raw_record_id != expected_id:
            raise ValueError("raw_record_id is not deterministic for this payload")
        _require_aware(self.event_time, "event_time")
        _require_aware(self.publish_time, "publish_time")
        _require_aware(self.ingest_time, "ingest_time")
        _require_aware(self.available_time, "available_time")
        _require_non_empty(self.raw_seat_name, "raw_seat_name")
        _require_non_empty(self.listing_reason, "listing_reason")
        _require_non_empty(self.raw_instrument_id, "raw_instrument_id")
        if type(self.buy_amount) is not Decimal or type(self.sell_amount) is not Decimal:
            raise TypeError("buy_amount and sell_amount must be Decimal")
        if type(self.vendor_net_amount) is not Decimal:
            raise TypeError("vendor_net_amount must be Decimal")
        _require_non_empty(self.evidence_id, "evidence_id")
        if self.seat_kind_hint is not None and type(self.seat_kind_hint) is not SeatKind:
            raise TypeError("seat_kind_hint must be SeatKind or None")

    @property
    def revision_key(self) -> tuple[str, date, str, str]:
        return (self.source, self.trade_date, self.raw_seat_name, self.raw_instrument_id)

    @property
    def revision_identity(self) -> tuple[str, str]:
        return (self.source, self.revision_id)

    @property
    def immutable_fingerprint(self) -> str:
        return _fingerprint(
            "seat-raw-fingerprint-v1",
            {
                "raw_record_id": self.raw_record_id,
                "revision_id": self.revision_id,
                "previous_revision_id": self.previous_revision_id,
                "source": self.source,
                "source_version": self.source_version,
                "raw_payload_hash": self.raw_payload_hash,
                "trade_date": self.trade_date.isoformat(),
                "event_time": self.event_time.isoformat(),
                "publish_time": None
                if self.publish_time is None
                else self.publish_time.isoformat(),
                "ingest_time": self.ingest_time.isoformat(),
                "available_time": self.available_time.isoformat(),
                "raw_seat_name": self.raw_seat_name,
                "listing_reason": self.listing_reason,
                "raw_instrument_id": self.raw_instrument_id,
                "buy_amount": str(self.buy_amount),
                "sell_amount": str(self.sell_amount),
                "vendor_net_amount": str(self.vendor_net_amount),
                "evidence_id": self.evidence_id,
                "seat_kind_hint": None
                if self.seat_kind_hint is None
                else self.seat_kind_hint.value,
            },
        )


@dataclass(frozen=True)
class SeatCollectionRequest:
    batch_id: str
    trade_date: date
    decision_time: datetime
    source: str = "dragon-tiger-fake"
    source_version: str = "2026-08"
    route_key: str = "dragon-tiger"
    expected_previous_checkpoint: str | None = None
    checkpoint_token: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.batch_id, "batch_id")
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        _require_non_empty(self.route_key, "route_key")
        _require_aware(self.decision_time, "decision_time")

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(
            "seat-request-fingerprint-v1",
            {
                "batch_id": self.batch_id,
                "trade_date": self.trade_date.isoformat(),
                "decision_time": self.decision_time.isoformat(),
                "source": self.source,
                "source_version": self.source_version,
                "route_key": self.route_key,
                "expected_previous_checkpoint": self.expected_previous_checkpoint,
                "checkpoint_token": self.checkpoint_token,
            },
        )

    @property
    def checkpoint_route(self) -> str:
        return f"{self.route_key}:{self.source}:{self.source_version}"


SeatFetchRequest = SeatCollectionRequest


@dataclass(frozen=True)
class SeatProviderBatch:
    batch_id: str
    source: str
    source_version: str
    records: tuple[RawSeatListRecord, ...]
    checkpoint_token: str | None

    def __post_init__(self) -> None:
        _require_non_empty(self.batch_id, "batch_id")
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        if type(self.records) is not tuple:
            raise TypeError("records must be a tuple")
        seen: dict[str, RawSeatListRecord] = {}
        seen_revisions: dict[tuple[str, str], RawSeatListRecord] = {}
        unique_records: list[RawSeatListRecord] = []
        for record in self.records:
            if type(record) is not RawSeatListRecord:
                raise TypeError("records must contain RawSeatListRecord instances")
            if record.source != self.source or record.source_version != self.source_version:
                raise ValueError("provider batch source provenance must match every record")
            existing = seen.get(record.raw_record_id)
            if existing is not None and existing != record:
                raise RevisionConflictError("duplicate raw_record_id has conflicting payload")
            revision_existing = seen_revisions.get(record.revision_identity)
            if revision_existing is not None and revision_existing != record:
                raise RevisionConflictError("duplicate source/revision has conflicting payload")
            if existing is None and revision_existing is None:
                unique_records.append(record)
            seen[record.raw_record_id] = record
            seen_revisions[record.revision_identity] = record
        object.__setattr__(self, "records", tuple(unique_records))

    @property
    def batch_fingerprint(self) -> str:
        return _fingerprint(
            "seat-batch-fingerprint-v1",
            {
                "batch_id": self.batch_id,
                "source": self.source,
                "source_version": self.source_version,
                "checkpoint_token": self.checkpoint_token,
                "records": sorted(record.immutable_fingerprint for record in self.records),
            },
        )


@dataclass(frozen=True)
class RejectedSeatRecord:
    raw_record_id: str
    revision_id: str
    reason: str
    detail: str
    resolution_status: ResolutionStatus | None
    candidate_seat_ids: tuple[str, ...]
    candidate_evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_non_empty(self.raw_record_id, "raw_record_id")
        _require_non_empty(self.revision_id, "revision_id")
        _require_non_empty(self.reason, "reason")
        _require_non_empty(self.detail, "detail")
        if type(self.candidate_seat_ids) is not tuple:
            raise TypeError("candidate_seat_ids must be a tuple")
        if type(self.candidate_evidence_ids) is not tuple:
            raise TypeError("candidate_evidence_ids must be a tuple")


@dataclass(frozen=True)
class NormalizedSeatTrade:
    trade: Trade
    listing_reason: str
    provider_evidence_id: str
    seat_evidence_ids: tuple[str, ...]
    resolution_status: ResolutionStatus
    resolution_fingerprint: str

    def __post_init__(self) -> None:
        if type(self.trade) is not Trade:
            raise TypeError("trade must be Trade")
        _require_non_empty(self.listing_reason, "listing_reason")
        _require_non_empty(self.provider_evidence_id, "provider_evidence_id")
        if type(self.seat_evidence_ids) is not tuple or not self.seat_evidence_ids:
            raise ValueError("seat_evidence_ids must be a non-empty tuple")
        if self.resolution_status is not ResolutionStatus.AUTO:
            raise ValueError("normalized trade requires AUTO resolution")
        _require_non_empty(self.resolution_fingerprint, "resolution_fingerprint")


@dataclass(frozen=True)
class SeatBatchResult:
    batch_id: str
    route_key: str
    request_fingerprint: str
    batch_fingerprint: str
    raw_records: tuple[RawSeatListRecord, ...]
    normalized_trades: tuple[NormalizedSeatTrade, ...]
    rejected_records: tuple[RejectedSeatRecord, ...]
    checkpoint_token: str | None
    expected_previous_checkpoint: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.batch_id, "batch_id")
        _require_non_empty(self.route_key, "route_key")
        _require_non_empty(self.request_fingerprint, "request_fingerprint")
        _require_non_empty(self.batch_fingerprint, "batch_fingerprint")
        if type(self.raw_records) is not tuple:
            raise TypeError("raw_records must be a tuple")
        if type(self.normalized_trades) is not tuple:
            raise TypeError("normalized_trades must be a tuple")
        if type(self.rejected_records) is not tuple:
            raise TypeError("rejected_records must be a tuple")
        raw_ids = [record.raw_record_id for record in self.raw_records]
        if len(raw_ids) != len(set(raw_ids)):
            raise ValueError("raw_records must not contain duplicate raw_record_id")
        trade_ids = [item.trade.trade_id for item in self.normalized_trades]
        if len(trade_ids) != len(set(trade_ids)):
            raise ValueError("normalized_trades must not contain duplicate trade_id")
        rejected_keys = [(item.raw_record_id, item.reason) for item in self.rejected_records]
        if len(rejected_keys) != len(set(rejected_keys)):
            raise ValueError("rejected_records must not contain duplicate outcomes")
        outcome_raw_ids = set(item.trade.raw_record_id for item in self.normalized_trades)
        outcome_raw_ids.update(item.raw_record_id for item in self.rejected_records)
        if not outcome_raw_ids.issubset(set(raw_ids)):
            raise ValueError("batch outcomes must reference raw_records")
        if any(
            record_id in {item.raw_record_id for item in self.rejected_records}
            for record_id in outcome_raw_ids.intersection(
                {item.trade.raw_record_id for item in self.normalized_trades}
            )
        ):
            raise ValueError("one raw record cannot be both normalized and rejected")


__all__ = [
    "BatchConflictError",
    "NormalizedSeatTrade",
    "RawSeatListRecord",
    "RejectedSeatRecord",
    "RevisionConflictError",
    "SeatBatchResult",
    "SeatCollectionRequest",
    "SeatCollectionError",
    "SeatFetchRequest",
    "SeatProviderBatch",
]
