"""Atomic repositories for P4-N03 raw, normalized and rejected outcomes."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from threading import RLock
from typing import Any, Protocol, TypeVar, cast, runtime_checkable

from data_worker.jobs.seats.models import (
    BatchConflictError,
    NormalizedSeatTrade,
    RawSeatListRecord,
    RejectedSeatRecord,
    RevisionConflictError,
    SeatBatchResult,
)
from seat_core import Currency, SeatKind, Trade
from seat_core.resolution import ResolutionStatus

_REVISION_REASONS = frozenset(
    {
        "missing_previous_revision",
        "out_of_order_revision",
        "revision_predecessor_mismatch",
        "stale_previous_revision",
    }
)
_RevisionIdentity = tuple[str, str]
_RevisionKey = tuple[str, date, str, str]


def _revision_key_text(key: _RevisionKey) -> str:
    return json.dumps([key[0], key[1].isoformat(), key[2], key[3]], separators=(",", ":"))


def _advisory_resource_keys(records: tuple[RawSeatListRecord, ...]) -> tuple[str, ...]:
    keys: set[str] = set()
    for record in records:
        keys.add(f"seat-raw:{record.raw_record_id}")
        keys.add(f"seat-revision:{record.source}:{record.revision_id}")
        keys.add(f"seat-revision-key:{record.source}:{_revision_key_text(record.revision_key)}")
        if record.previous_revision_id is not None:
            keys.add(f"seat-revision:{record.source}:{record.previous_revision_id}")
    return tuple(sorted(keys))


def _revision_rejections_for_state(
    records: tuple[RawSeatListRecord, ...],
    existing_raw: Mapping[str, RawSeatListRecord],
    existing_revisions: Mapping[_RevisionIdentity, RawSeatListRecord],
    latest_by_key: Mapping[_RevisionKey, str],
) -> dict[str, str]:
    rejections: dict[str, str] = {}
    local_by_revision: dict[_RevisionIdentity, RawSeatListRecord] = {}
    local_latest_by_key: dict[_RevisionKey, str] = {}
    for index, record in enumerate(records):
        existing_record = existing_raw.get(record.raw_record_id)
        if existing_record is not None and existing_record != record:
            raise RevisionConflictError("raw_record_id has conflicting immutable content")
        existing_revision = existing_revisions.get(record.revision_identity)
        if existing_revision is not None and existing_revision != record:
            raise RevisionConflictError("source/revision_id has conflicting immutable content")
        if existing_record is not None or existing_revision is not None:
            continue

        local_revision = local_by_revision.get(record.revision_identity)
        if local_revision is not None and local_revision != record:
            raise RevisionConflictError("source/revision_id is duplicated with conflicting content")
        if local_revision is not None:
            continue

        reason: str | None = None
        predecessor: RawSeatListRecord | None = None
        if record.previous_revision_id is None:
            if record.revision_key in latest_by_key or record.revision_key in local_latest_by_key:
                reason = "missing_previous_revision"
        else:
            predecessor_identity = (record.source, record.previous_revision_id)
            predecessor = existing_revisions.get(predecessor_identity)
            if predecessor is None:
                predecessor = local_by_revision.get(predecessor_identity)
            if predecessor is None:
                later_revision = any(
                    item.revision_identity == predecessor_identity for item in records[index + 1 :]
                )
                reason = "out_of_order_revision" if later_revision else "missing_previous_revision"
            elif predecessor.revision_key != record.revision_key:
                reason = "revision_predecessor_mismatch"
            else:
                latest_revision = local_latest_by_key.get(
                    record.revision_key, latest_by_key.get(record.revision_key)
                )
                if latest_revision != record.previous_revision_id:
                    reason = "stale_previous_revision"

        if reason is not None:
            rejections[record.raw_record_id] = reason
        else:
            local_by_revision[record.revision_identity] = record
            local_latest_by_key[record.revision_key] = record.revision_id
    return rejections


@runtime_checkable
class SeatRepository(Protocol):
    def revision_rejections(
        self,
        records: tuple[RawSeatListRecord, ...],
        *,
        route_key: str | None = None,
    ) -> dict[str, str]: ...

    def commit(self, result: SeatBatchResult) -> SeatBatchResult: ...

    def checkpoint(self, route_key: str) -> str | None: ...

    def get_batch(self, route_key: str, batch_id: str) -> SeatBatchResult | None: ...


class InMemorySeatRepository:
    """Explicit test adapter with lock-protected atomic state transitions."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._batches: dict[tuple[str, str], SeatBatchResult] = {}
        self._raw_records: dict[str, RawSeatListRecord] = {}
        self._revisions: dict[_RevisionIdentity, RawSeatListRecord] = {}
        self._latest_by_key: dict[_RevisionKey, str] = {}
        self._normalized: dict[str, NormalizedSeatTrade] = {}
        self._rejected: dict[tuple[str, str], RejectedSeatRecord] = {}
        self._checkpoints: dict[str, str | None] = {}

    @property
    def raw_records(self) -> tuple[RawSeatListRecord, ...]:
        with self._lock:
            return tuple(sorted(self._raw_records.values(), key=lambda item: item.raw_record_id))

    @property
    def normalized_trades(self) -> tuple[NormalizedSeatTrade, ...]:
        with self._lock:
            return tuple(sorted(self._normalized.values(), key=lambda item: item.trade.trade_id))

    @property
    def rejected_records(self) -> tuple[RejectedSeatRecord, ...]:
        with self._lock:
            return tuple(
                sorted(self._rejected.values(), key=lambda item: (item.raw_record_id, item.reason))
            )

    def get_batch(self, route_key: str, batch_id: str) -> SeatBatchResult | None:
        with self._lock:
            return self._batches.get((route_key, batch_id))

    def checkpoint(self, route_key: str) -> str | None:
        with self._lock:
            return self._checkpoints.get(route_key)

    def revision_rejections(
        self,
        records: tuple[RawSeatListRecord, ...],
        *,
        route_key: str | None = None,
    ) -> dict[str, str]:
        del route_key
        with self._lock:
            return _revision_rejections_for_state(
                records,
                self._raw_records,
                self._revisions,
                self._latest_by_key,
            )

    def commit(self, result: SeatBatchResult) -> SeatBatchResult:
        with self._lock:
            batch_key = (result.route_key, result.batch_id)
            existing_batch = self._batches.get(batch_key)
            if existing_batch is not None:
                if (
                    existing_batch.request_fingerprint != result.request_fingerprint
                    or existing_batch.batch_fingerprint != result.batch_fingerprint
                    or existing_batch != result
                ):
                    raise BatchConflictError("route/batch identity has conflicting content")
                return existing_batch
            if self._checkpoints.get(result.route_key) != result.expected_previous_checkpoint:
                raise BatchConflictError(
                    "checkpoint conflict: expected previous checkpoint changed"
                )

            revision_rejections = _revision_rejections_for_state(
                result.raw_records,
                self._raw_records,
                self._revisions,
                self._latest_by_key,
            )
            expected_rejections = {
                item.raw_record_id: item.reason
                for item in result.rejected_records
                if item.reason in _REVISION_REASONS
            }
            if revision_rejections != expected_rejections:
                raise BatchConflictError("revision chain changed before atomic commit")

            next_raw = dict(self._raw_records)
            next_revisions = dict(self._revisions)
            next_latest = dict(self._latest_by_key)
            next_normalized = dict(self._normalized)
            next_rejected = dict(self._rejected)
            for record in result.raw_records:
                existing_raw = next_raw.get(record.raw_record_id)
                if existing_raw is not None and existing_raw != record:
                    raise RevisionConflictError("raw_record_id has conflicting immutable content")
                existing_revision = next_revisions.get(record.revision_identity)
                if existing_revision is not None and existing_revision != record:
                    raise RevisionConflictError(
                        "source/revision_id has conflicting immutable content"
                    )
                next_raw[record.raw_record_id] = record
                next_revisions[record.revision_identity] = record
                if record.raw_record_id not in revision_rejections:
                    next_latest[record.revision_key] = record.revision_id

            for normalized in result.normalized_trades:
                existing = next_normalized.get(normalized.trade.trade_id)
                if existing is not None and existing != normalized:
                    raise BatchConflictError("normalized trade identity has conflicting content")
                next_normalized[normalized.trade.trade_id] = normalized
            for rejected in result.rejected_records:
                key = (rejected.raw_record_id, rejected.reason)
                existing = next_rejected.get(key)
                if existing is not None and existing != rejected:
                    raise BatchConflictError("rejected outcome has conflicting content")
                next_rejected[key] = rejected

            self._raw_records = next_raw
            self._revisions = next_revisions
            self._latest_by_key = next_latest
            self._normalized = next_normalized
            self._rejected = next_rejected
            self._batches[batch_key] = result
            self._checkpoints[result.route_key] = result.checkpoint_token
            return result


def _as_dict(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    # The runtime check establishes a dict; object entries preserve unknown JSON values.
    typed_value = cast(dict[object, object], value)
    result: dict[str, object] = {}
    for key, item in typed_value.items():
        if not isinstance(key, str):
            raise ValueError(f"{name} keys must be strings")
        result[key] = item
    return result


def _as_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    # The runtime check establishes a list; object entries preserve unknown JSON values.
    return cast(list[object], value)


def _as_str(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _as_optional_str(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _as_str(value, name)


def _decode_json(value: object) -> object:
    if isinstance(value, str):
        decoded: object = json.loads(value)
        return decoded
    return value


def _as_datetime(value: object, name: str) -> datetime:
    return datetime.fromisoformat(_as_str(value, name))


def _raw_to_dict(record: RawSeatListRecord) -> dict[str, object]:
    return {
        "raw_record_id": record.raw_record_id,
        "revision_id": record.revision_id,
        "previous_revision_id": record.previous_revision_id,
        "source": record.source,
        "source_version": record.source_version,
        "raw_payload": base64.b64encode(record.raw_payload).decode("ascii"),
        "raw_payload_hash": record.raw_payload_hash,
        "trade_date": record.trade_date.isoformat(),
        "event_time": record.event_time.isoformat(),
        "publish_time": None if record.publish_time is None else record.publish_time.isoformat(),
        "ingest_time": record.ingest_time.isoformat(),
        "available_time": record.available_time.isoformat(),
        "raw_seat_name": record.raw_seat_name,
        "listing_reason": record.listing_reason,
        "raw_instrument_id": record.raw_instrument_id,
        "buy_amount": str(record.buy_amount),
        "sell_amount": str(record.sell_amount),
        "vendor_net_amount": str(record.vendor_net_amount),
        "evidence_id": record.evidence_id,
        "seat_kind_hint": None if record.seat_kind_hint is None else record.seat_kind_hint.value,
    }


def _raw_from_dict(value: object) -> RawSeatListRecord:
    data = _as_dict(value, "raw_record")
    hint = _as_optional_str(data["seat_kind_hint"], "seat_kind_hint")
    publish_time = data["publish_time"]
    return RawSeatListRecord(
        raw_record_id=_as_str(data["raw_record_id"], "raw_record_id"),
        revision_id=_as_str(data["revision_id"], "revision_id"),
        previous_revision_id=_as_optional_str(data["previous_revision_id"], "previous_revision_id"),
        source=_as_str(data["source"], "source"),
        source_version=_as_str(data["source_version"], "source_version"),
        raw_payload=base64.b64decode(_as_str(data["raw_payload"], "raw_payload")),
        raw_payload_hash=_as_str(data["raw_payload_hash"], "raw_payload_hash"),
        trade_date=date.fromisoformat(_as_str(data["trade_date"], "trade_date")),
        event_time=_as_datetime(data["event_time"], "event_time"),
        publish_time=None if publish_time is None else _as_datetime(publish_time, "publish_time"),
        ingest_time=_as_datetime(data["ingest_time"], "ingest_time"),
        available_time=_as_datetime(data["available_time"], "available_time"),
        raw_seat_name=_as_str(data["raw_seat_name"], "raw_seat_name"),
        listing_reason=_as_str(data["listing_reason"], "listing_reason"),
        raw_instrument_id=_as_str(data["raw_instrument_id"], "raw_instrument_id"),
        buy_amount=Decimal(_as_str(data["buy_amount"], "buy_amount")),
        sell_amount=Decimal(_as_str(data["sell_amount"], "sell_amount")),
        vendor_net_amount=Decimal(_as_str(data["vendor_net_amount"], "vendor_net_amount")),
        evidence_id=_as_str(data["evidence_id"], "evidence_id"),
        seat_kind_hint=None if hint is None else SeatKind(hint),
    )


def _normalized_to_dict(item: NormalizedSeatTrade) -> dict[str, object]:
    trade = item.trade
    return {
        "trade": {
            "trade_id": trade.trade_id,
            "revision_id": trade.revision_id,
            "previous_revision_id": trade.previous_revision_id,
            "seat_id": trade.seat_id,
            "raw_seat_name": trade.raw_seat_name,
            "instrument_id": trade.instrument_id,
            "trade_date": trade.trade_date.isoformat(),
            "currency": trade.currency.value,
            "buy_amount": str(trade.buy_amount),
            "sell_amount": str(trade.sell_amount),
            "net_amount": str(trade.net_amount),
            "source": trade.source,
            "source_version": trade.source_version,
            "raw_record_id": trade.raw_record_id,
            "evidence_id": trade.evidence_id,
            "available_time": trade.available_time.isoformat(),
            "schema_version": trade.schema_version,
        },
        "listing_reason": item.listing_reason,
        "provider_evidence_id": item.provider_evidence_id,
        "seat_evidence_ids": list(item.seat_evidence_ids),
        "resolution_status": item.resolution_status.value,
        "resolution_fingerprint": item.resolution_fingerprint,
    }


def _normalized_from_dict(value: object) -> NormalizedSeatTrade:
    data = _as_dict(value, "normalized_trade")
    trade_data = _as_dict(data["trade"], "trade")
    evidence_ids = tuple(
        _as_str(item, "seat_evidence_id")
        for item in _as_list(data["seat_evidence_ids"], "seat_evidence_ids")
    )
    trade = Trade(
        trade_id=_as_str(trade_data["trade_id"], "trade_id"),
        revision_id=_as_str(trade_data["revision_id"], "revision_id"),
        previous_revision_id=_as_optional_str(
            trade_data["previous_revision_id"], "previous_revision_id"
        ),
        seat_id=_as_str(trade_data["seat_id"], "seat_id"),
        raw_seat_name=_as_str(trade_data["raw_seat_name"], "raw_seat_name"),
        instrument_id=_as_str(trade_data["instrument_id"], "instrument_id"),
        trade_date=date.fromisoformat(_as_str(trade_data["trade_date"], "trade_date")),
        currency=Currency(_as_str(trade_data["currency"], "currency")),
        buy_amount=Decimal(_as_str(trade_data["buy_amount"], "buy_amount")),
        sell_amount=Decimal(_as_str(trade_data["sell_amount"], "sell_amount")),
        net_amount=Decimal(_as_str(trade_data["net_amount"], "net_amount")),
        source=_as_str(trade_data["source"], "source"),
        source_version=_as_str(trade_data["source_version"], "source_version"),
        raw_record_id=_as_str(trade_data["raw_record_id"], "raw_record_id"),
        evidence_id=_as_str(trade_data["evidence_id"], "evidence_id"),
        available_time=_as_datetime(trade_data["available_time"], "available_time"),
        schema_version=_as_str(trade_data["schema_version"], "schema_version"),
    )
    return NormalizedSeatTrade(
        trade=trade,
        listing_reason=_as_str(data["listing_reason"], "listing_reason"),
        provider_evidence_id=_as_str(data["provider_evidence_id"], "provider_evidence_id"),
        seat_evidence_ids=evidence_ids,
        resolution_status=ResolutionStatus(_as_str(data["resolution_status"], "resolution_status")),
        resolution_fingerprint=_as_str(data["resolution_fingerprint"], "resolution_fingerprint"),
    )


def _rejected_to_dict(item: RejectedSeatRecord) -> dict[str, object]:
    return {
        "raw_record_id": item.raw_record_id,
        "revision_id": item.revision_id,
        "reason": item.reason,
        "detail": item.detail,
        "resolution_status": None
        if item.resolution_status is None
        else item.resolution_status.value,
        "candidate_seat_ids": list(item.candidate_seat_ids),
        "candidate_evidence_ids": list(item.candidate_evidence_ids),
    }


def _rejected_from_dict(value: object) -> RejectedSeatRecord:
    data = _as_dict(value, "rejected_record")
    status = _as_optional_str(data["resolution_status"], "resolution_status")
    return RejectedSeatRecord(
        raw_record_id=_as_str(data["raw_record_id"], "raw_record_id"),
        revision_id=_as_str(data["revision_id"], "revision_id"),
        reason=_as_str(data["reason"], "reason"),
        detail=_as_str(data["detail"], "detail"),
        resolution_status=None if status is None else ResolutionStatus(status),
        candidate_seat_ids=tuple(
            _as_str(item, "candidate_seat_id")
            for item in _as_list(data["candidate_seat_ids"], "candidate_seat_ids")
        ),
        candidate_evidence_ids=tuple(
            _as_str(item, "candidate_evidence_id")
            for item in _as_list(data["candidate_evidence_ids"], "candidate_evidence_ids")
        ),
    )


def _result_to_json(result: SeatBatchResult) -> str:
    return json.dumps(
        {
            "batch_id": result.batch_id,
            "route_key": result.route_key,
            "request_fingerprint": result.request_fingerprint,
            "batch_fingerprint": result.batch_fingerprint,
            "raw_records": [_raw_to_dict(item) for item in result.raw_records],
            "normalized_trades": [_normalized_to_dict(item) for item in result.normalized_trades],
            "rejected_records": [_rejected_to_dict(item) for item in result.rejected_records],
            "checkpoint_token": result.checkpoint_token,
            "expected_previous_checkpoint": result.expected_previous_checkpoint,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _result_from_json(value: object) -> SeatBatchResult:
    data = _as_dict(value, "batch_result")
    return SeatBatchResult(
        batch_id=_as_str(data["batch_id"], "batch_id"),
        route_key=_as_str(data["route_key"], "route_key"),
        request_fingerprint=_as_str(data["request_fingerprint"], "request_fingerprint"),
        batch_fingerprint=_as_str(data["batch_fingerprint"], "batch_fingerprint"),
        raw_records=tuple(
            _raw_from_dict(item) for item in _as_list(data["raw_records"], "raw_records")
        ),
        normalized_trades=tuple(
            _normalized_from_dict(item)
            for item in _as_list(data["normalized_trades"], "normalized_trades")
        ),
        rejected_records=tuple(
            _rejected_from_dict(item)
            for item in _as_list(data["rejected_records"], "rejected_records")
        ),
        checkpoint_token=_as_optional_str(data["checkpoint_token"], "checkpoint_token"),
        expected_previous_checkpoint=_as_optional_str(
            data.get("expected_previous_checkpoint"), "expected_previous_checkpoint"
        ),
    )


class _PostgresCursor(Protocol):
    def execute(self, query: str, params: Sequence[object] | None = None) -> object: ...

    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...

    def close(self) -> None: ...


class _PostgresConnection(Protocol):
    def cursor(self) -> _PostgresCursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


_T = TypeVar("_T")


class PostgresSeatRepository:
    """Durable PostgreSQL adapter with one transaction per batch commit."""

    def __init__(self, connection: _PostgresConnection) -> None:
        self._connection = connection

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresSeatRepository:
        import psycopg

        connection = psycopg.connect(dsn)
        # psycopg's generic cursor overload is narrower than this adapter's minimal protocol.
        return cls(cast(_PostgresConnection, connection))

    def _transaction(
        self,
        operation: Callable[[_PostgresCursor], _T],
        *,
        route_key: str | None = None,
        records: tuple[RawSeatListRecord, ...] = (),
    ) -> _T:
        cursor = self._connection.cursor()
        try:
            cursor.execute("BEGIN")
            if route_key is not None:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (f"seat-route:{route_key}",),
                )
            for lock_key in _advisory_resource_keys(records):
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (lock_key,),
                )
            value = operation(cursor)
            self._connection.commit()
            return value
        except BaseException:
            self._connection.rollback()
            raise
        finally:
            cursor.close()

    def initialize(self) -> None:
        """Test helper; production startup uses the registered worker migration."""
        from data_worker.storage.migrations import apply_data_worker_migrations
        from psycopg import Connection

        # The runtime helper is called with a real psycopg connection in production;
        # the repository protocol remains narrow for collector and unit-test adapters.
        apply_data_worker_migrations(cast(Connection[Any], self._connection))

    def checkpoint(self, route_key: str) -> str | None:
        def read(cursor: _PostgresCursor) -> str | None:
            cursor.execute(
                "SELECT checkpoint_token FROM seat_collection_checkpoints WHERE route_key = %s",
                (route_key,),
            )
            row = cursor.fetchone()
            return None if row is None else _as_optional_str(row[0], "checkpoint_token")

        return self._transaction(read, route_key=route_key)

    def get_batch(self, route_key: str, batch_id: str) -> SeatBatchResult | None:
        def read(cursor: _PostgresCursor) -> SeatBatchResult | None:
            cursor.execute(
                (
                    "SELECT result_json FROM seat_collection_batches "
                    "WHERE route_key = %s AND batch_id = %s"
                ),
                (route_key, batch_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            raw_json = row[0]
            decoded: object = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
            return _result_from_json(decoded)

        return self._transaction(read, route_key=route_key)

    def revision_rejections(
        self,
        records: tuple[RawSeatListRecord, ...],
        *,
        route_key: str | None = None,
    ) -> dict[str, str]:
        def read(cursor: _PostgresCursor) -> dict[str, str]:
            existing_raw, existing_revisions, latest = self._load_state(cursor)
            return _revision_rejections_for_state(records, existing_raw, existing_revisions, latest)

        return self._transaction(read, route_key=route_key, records=records)

    def _load_state(
        self, cursor: _PostgresCursor
    ) -> tuple[
        dict[str, RawSeatListRecord],
        dict[_RevisionIdentity, RawSeatListRecord],
        dict[_RevisionKey, str],
    ]:
        cursor.execute(
            "SELECT raw_json, revision_accepted, is_latest "
            "FROM seat_collection_raw_records FOR UPDATE"
        )
        raw_by_id: dict[str, RawSeatListRecord] = {}
        revisions: dict[_RevisionIdentity, RawSeatListRecord] = {}
        latest: dict[_RevisionKey, str] = {}
        for row in cursor.fetchall():
            raw_value = row[0]
            decoded: object = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
            record = _raw_from_dict(decoded)
            raw_by_id[record.raw_record_id] = record
            revisions[record.revision_identity] = record
            if row[1] is True and row[2] is True:
                latest[record.revision_key] = record.revision_id
        return raw_by_id, revisions, latest

    def commit(self, result: SeatBatchResult) -> SeatBatchResult:
        def write(cursor: _PostgresCursor) -> SeatBatchResult:
            cursor.execute(
                """
                SELECT request_fingerprint, batch_fingerprint,
                       expected_previous_checkpoint, result_json
                FROM seat_collection_batches
                WHERE route_key = %s AND batch_id = %s
                FOR UPDATE
                """,
                (result.route_key, result.batch_id),
            )
            existing_batch = cursor.fetchone()
            if existing_batch is not None:
                if (
                    _as_str(existing_batch[0], "request_fingerprint") != result.request_fingerprint
                    or _as_str(existing_batch[1], "batch_fingerprint") != result.batch_fingerprint
                    or _as_optional_str(existing_batch[2], "expected_previous_checkpoint")
                    != result.expected_previous_checkpoint
                ):
                    raise BatchConflictError("route/batch identity has conflicting content")
                persisted = _result_from_json(_decode_json(existing_batch[3]))
                if persisted != result:
                    raise BatchConflictError("route/batch result has conflicting content")
                return persisted

            cursor.execute(
                """
                SELECT checkpoint_token
                FROM seat_collection_checkpoints
                WHERE route_key = %s
                FOR UPDATE
                """,
                (result.route_key,),
            )
            checkpoint_row = cursor.fetchone()
            current_checkpoint = (
                None
                if checkpoint_row is None
                else _as_optional_str(checkpoint_row[0], "checkpoint_token")
            )
            if current_checkpoint != result.expected_previous_checkpoint:
                raise BatchConflictError(
                    "checkpoint conflict: expected previous checkpoint changed"
                )

            existing_raw, existing_revisions, latest = self._load_state(cursor)
            current_rejections = _revision_rejections_for_state(
                result.raw_records, existing_raw, existing_revisions, latest
            )
            expected_rejections = {
                item.raw_record_id: item.reason
                for item in result.rejected_records
                if item.reason in _REVISION_REASONS
            }
            if current_rejections != expected_rejections:
                raise BatchConflictError("revision chain changed before durable commit")

            for record in result.raw_records:
                is_new = record.raw_record_id not in existing_raw
                if is_new and record.raw_record_id not in current_rejections:
                    cursor.execute(
                        """
                        UPDATE seat_collection_raw_records
                        SET is_latest = FALSE
                        WHERE revision_key = %s AND is_latest = TRUE
                        """,
                        (_revision_key_text(record.revision_key),),
                    )
                if is_new:
                    cursor.execute(
                        """
                        INSERT INTO seat_collection_raw_records
                        (source, revision_id, raw_record_id, previous_revision_id,
                         raw_payload, raw_payload_hash, revision_key, revision_accepted,
                         is_latest, raw_json)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            record.source,
                            record.revision_id,
                            record.raw_record_id,
                            record.previous_revision_id,
                            record.raw_payload,
                            record.raw_payload_hash,
                            _revision_key_text(record.revision_key),
                            record.raw_record_id not in current_rejections,
                            record.raw_record_id not in current_rejections,
                            json.dumps(_raw_to_dict(record), ensure_ascii=False, sort_keys=True),
                        ),
                    )

            for normalized in result.normalized_trades:
                normalized_json = _normalized_to_dict(normalized)
                cursor.execute(
                    """
                    SELECT trade_json
                    FROM seat_collection_normalized
                    WHERE trade_id = %s
                    FOR UPDATE
                    """,
                    (normalized.trade.trade_id,),
                )
                existing_normalized = cursor.fetchone()
                if existing_normalized is not None:
                    if _decode_json(existing_normalized[0]) != normalized_json:
                        raise BatchConflictError(
                            "normalized trade identity has conflicting content"
                        )
                    continue
                cursor.execute(
                    """
                    INSERT INTO seat_collection_normalized (trade_id, raw_record_id, trade_json)
                    VALUES (%s, %s, %s::jsonb)
                    """,
                    (
                        normalized.trade.trade_id,
                        normalized.trade.raw_record_id,
                        json.dumps(normalized_json, ensure_ascii=False, sort_keys=True),
                    ),
                )
            for rejected in result.rejected_records:
                rejected_json = _rejected_to_dict(rejected)
                cursor.execute(
                    """
                    SELECT rejected_json
                    FROM seat_collection_rejected
                    WHERE raw_record_id = %s AND reason = %s
                    FOR UPDATE
                    """,
                    (rejected.raw_record_id, rejected.reason),
                )
                existing_rejected = cursor.fetchone()
                if existing_rejected is not None:
                    if _decode_json(existing_rejected[0]) != rejected_json:
                        raise BatchConflictError("rejected outcome has conflicting content")
                    continue
                cursor.execute(
                    """
                    INSERT INTO seat_collection_rejected
                    (raw_record_id, reason, rejected_json)
                    VALUES (%s, %s, %s::jsonb)
                    """,
                    (
                        rejected.raw_record_id,
                        rejected.reason,
                        json.dumps(rejected_json, ensure_ascii=False, sort_keys=True),
                    ),
                )

            result_json = _result_to_json(result)
            cursor.execute(
                """
                INSERT INTO seat_collection_batches
                (route_key, batch_id, source, source_version, request_fingerprint,
                 batch_fingerprint, expected_previous_checkpoint, checkpoint_token, result_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    result.route_key,
                    result.batch_id,
                    result.raw_records[0].source if result.raw_records else "",
                    result.raw_records[0].source_version if result.raw_records else "",
                    result.request_fingerprint,
                    result.batch_fingerprint,
                    result.expected_previous_checkpoint,
                    result.checkpoint_token,
                    result_json,
                ),
            )
            if checkpoint_row is None:
                cursor.execute(
                    """
                    INSERT INTO seat_collection_checkpoints
                    (route_key, checkpoint_token, batch_id, request_fingerprint, batch_fingerprint)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        result.route_key,
                        result.checkpoint_token,
                        result.batch_id,
                        result.request_fingerprint,
                        result.batch_fingerprint,
                    ),
                )
            else:
                cursor.execute(
                    """
                    UPDATE seat_collection_checkpoints
                    SET checkpoint_token = %s,
                        batch_id = %s,
                        request_fingerprint = %s,
                        batch_fingerprint = %s,
                        updated_at = now()
                    WHERE route_key = %s
                    """,
                    (
                        result.checkpoint_token,
                        result.batch_id,
                        result.request_fingerprint,
                        result.batch_fingerprint,
                        result.route_key,
                    ),
                )
            return result

        return self._transaction(
            write,
            route_key=result.route_key,
            records=result.raw_records,
        )


__all__ = [
    "InMemorySeatRepository",
    "PostgresSeatRepository",
    "SeatRepository",
]
