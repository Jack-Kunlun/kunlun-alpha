"""V5 PostgreSQL persistence for replay-verified instrument-master runs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from threading import RLock
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID, uuid5

from data_worker.jobs.instruments.tushare_master import (
    TUSHARE_INSTRUMENT_PARSER_VERSION,
    TUSHARE_INSTRUMENT_PROFILE_VERSION,
    TUSHARE_INSTRUMENT_SCHEMA_VERSION,
    TUSHARE_INSTRUMENT_SOURCE,
    InstrumentMasterDisposition,
    InstrumentMasterRunResult,
    InstrumentMasterTerminal,
    replay_tushare_instrument_master_run,
)
from data_worker.raw import RawStorage
from data_worker.storage.migrations import (
    INSTRUMENT_MASTER_PROVIDER_SCHEMA,
    InstrumentMasterProviderRoles,
)
from market_core.instrument import InstrumentMasterRecord, ListingLifecycle, TradingAvailability
from psycopg.pq import TransactionStatus

if TYPE_CHECKING:
    from psycopg import Connection

_SNAPSHOT_NAMESPACE = "tushare-instrument-master-v1:snapshot"
_LOCK_PREFIX = "tushare-instrument-master:v1"
_PERSISTENCE_ERROR = "instrument master persistence failed"
_TRANSACTION_ERROR = "instrument master repository requires an idle connection"
_SCHEMA_ERROR = "instrument master provider schema is invalid"
_ROLE_ERROR = "instrument master runtime role is invalid"
_SAFE_SCHEMA_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


class InstrumentMasterPersistenceError(RuntimeError):
    """A fixed, non-sensitive persistence failure."""


class InstrumentMasterRepositoryTransactionError(InstrumentMasterPersistenceError):
    """The supplied connection was already inside a transaction."""


@dataclass(frozen=True, slots=True)
class InstrumentMasterPersistResult:
    run_id: UUID
    snapshot_id: UUID | None
    disposition: str
    terminal: str
    completeness: str
    run_disposition: str


@dataclass(frozen=True, slots=True)
class InstrumentMasterPITResult:
    unified_code: str
    decision_time: datetime
    status: str
    record: InstrumentMasterRecord | None


_T = TypeVar("_T")


def instrument_master_snapshot_id(run_id: UUID) -> UUID:
    if type(run_id) is not UUID:
        raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR)
    return uuid5(run_id, _SNAPSHOT_NAMESPACE)


def _digest_text(value: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR)
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR)
    return value.astimezone(UTC)


class _Cursor:
    def execute(self, query: str, params: Sequence[object] | None = None) -> object:
        raise NotImplementedError

    def fetchone(self) -> tuple[object, ...] | None:
        raise NotImplementedError

    def fetchall(self) -> list[tuple[object, ...]]:
        raise NotImplementedError


class PostgresInstrumentMasterRepository:
    """Persist only coordinates that have just been replay-verified."""

    def __init__(
        self,
        connection: Connection[Any],
        *,
        schema: str = INSTRUMENT_MASTER_PROVIDER_SCHEMA,
        runtime_role: str | None = None,
        provider_roles: InstrumentMasterProviderRoles | None = None,
    ) -> None:
        self._connection = connection
        if (
            type(schema) is not str
            or not 1 <= len(schema) <= 63
            or schema[0] not in "abcdefghijklmnopqrstuvwxyz_"
            or any(character not in _SAFE_SCHEMA_CHARS for character in schema)
        ):
            raise ValueError(_SCHEMA_ERROR)
        if provider_roles is None:
            provider_roles = InstrumentMasterProviderRoles()
        if type(provider_roles) is not InstrumentMasterProviderRoles:
            raise ValueError(_ROLE_ERROR)
        for role in provider_roles:
            if (
                type(role) is not str
                or not 1 <= len(role) <= 63
                or role[0] not in "abcdefghijklmnopqrstuvwxyz_"
                or any(character not in _SAFE_SCHEMA_CHARS for character in role)
            ):
                raise ValueError(_ROLE_ERROR)
        if len(set(provider_roles)) != 4:
            raise ValueError(_ROLE_ERROR)
        expected_runtime_role = provider_roles.runtime if runtime_role is None else runtime_role
        if (
            type(expected_runtime_role) is not str
            or not 1 <= len(expected_runtime_role) <= 63
            or expected_runtime_role[0] not in "abcdefghijklmnopqrstuvwxyz_"
            or any(character not in _SAFE_SCHEMA_CHARS for character in expected_runtime_role)
        ):
            raise ValueError(_ROLE_ERROR)
        self._schema = schema
        self._runtime_role = expected_runtime_role
        self._provider_roles = provider_roles
        self._mutex = RLock()

    def _ensure_idle(self) -> None:
        try:
            status = self._connection.info.transaction_status
        except AttributeError:
            raise InstrumentMasterRepositoryTransactionError(_TRANSACTION_ERROR) from None
        if status != TransactionStatus.IDLE:
            raise InstrumentMasterRepositoryTransactionError(_TRANSACTION_ERROR)

    def _ensure_runtime_identity(self, cursor: _Cursor) -> None:
        try:
            cursor.execute("SELECT SESSION_USER, CURRENT_USER")
            row = cursor.fetchone()
        except InstrumentMasterPersistenceError:
            raise
        except Exception:
            raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR) from None
        if row is None or len(row) != 2 or any(str(value) != self._runtime_role for value in row):
            raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR)

    def _run(self, operation: Callable[[_Cursor], _T]) -> _T:
        with self._mutex:
            self._ensure_idle()
            try:
                transaction = cast(AbstractContextManager[Any], self._connection.transaction())
                with transaction:
                    cursor_context = cast(AbstractContextManager[Any], self._connection.cursor())
                    with cursor_context as raw_cursor:
                        cursor = cast(_Cursor, raw_cursor)
                        self._ensure_runtime_identity(cursor)
                        cursor.execute(
                            f'SET LOCAL search_path = "{self._schema}", pg_catalog, pg_temp'
                        )
                        return operation(cursor)
            except InstrumentMasterPersistenceError:
                raise
            except Exception:
                raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR) from None

    @staticmethod
    def _lock(cursor: _Cursor) -> None:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (_LOCK_PREFIX,))

    @staticmethod
    def _manifest_object_id(raw_storage: RawStorage, result: InstrumentMasterRunResult) -> str:
        for manifest in raw_storage.list(TUSHARE_INSTRUMENT_SOURCE, result.manifest_date):
            if manifest.capture_id == result.manifest_capture_id:
                return _digest_text(manifest.object_id)
        raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR)

    def persist_authoritative_instrument_master_run(
        self,
        raw_storage: RawStorage,
        run_id: str | UUID,
        manifest_date: str,
        manifest_capture_id: str,
    ) -> InstrumentMasterPersistResult:
        """Replay raw coordinates before any database transaction is opened."""

        try:
            result = replay_tushare_instrument_master_run(
                raw_storage,
                run_id=run_id,
                manifest_date=manifest_date,
                manifest_capture_id=manifest_capture_id,
            )
            manifest_object_id = self._manifest_object_id(raw_storage, result)
            parsed_run_id = UUID(result.run_id)
            return self._run(
                lambda cursor: self._persist_replayed(
                    cursor,
                    result,
                    parsed_run_id,
                    manifest_object_id,
                )
            )
        except InstrumentMasterPersistenceError:
            raise
        except Exception:
            raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR) from None

    # Short public alias used by runtime composition tests.
    persist_authoritative_run = persist_authoritative_instrument_master_run

    def _persist_replayed(
        self,
        cursor: _Cursor,
        result: InstrumentMasterRunResult,
        run_id: UUID,
        manifest_object_id: str,
    ) -> InstrumentMasterPersistResult:
        self._lock(cursor)
        cursor.execute(
            "SELECT manifest_capture_id, manifest_object_id, disposition "
            "FROM tushare_instrument_master_runs WHERE run_id = %s",
            (run_id,),
        )
        existing = cursor.fetchone()
        if existing is not None:
            if existing[0] == result.manifest_capture_id and existing[1] == manifest_object_id:
                return InstrumentMasterPersistResult(
                    run_id=run_id,
                    snapshot_id=(
                        instrument_master_snapshot_id(run_id)
                        if result.completeness is InstrumentMasterDisposition.COMPLETE
                        else None
                    ),
                    disposition="DUPLICATE",
                    terminal=result.terminal.value,
                    completeness=result.completeness.value,
                    run_disposition="DUPLICATE",
                )
            return InstrumentMasterPersistResult(
                run_id=run_id,
                snapshot_id=None,
                disposition="CONFLICT",
                terminal="FAILED",
                completeness="REJECTED",
                run_disposition="CONFLICT",
            )

        now = datetime.now(UTC)
        opened_at, completed_at = _result_times(result, now)
        complete = result.completeness is InstrumentMasterDisposition.COMPLETE
        ordering_state = "NEW"
        if complete:
            cursor.execute(
                "SELECT s.available_at, r.manifest_object_id "
                "FROM tushare_instrument_master_snapshots AS s "
                "JOIN tushare_instrument_master_runs AS r ON r.run_id = s.run_id "
                "WHERE s.completeness = 'COMPLETE' "
                "AND s.disposition = 'SNAPSHOT_CANDIDATE' "
                "ORDER BY s.available_at DESC, s.snapshot_id DESC LIMIT 1"
            )
            latest = cursor.fetchone()
            if latest is not None:
                latest_available = _aware(cast(datetime, latest[0]), "snapshot.available_at")
                if completed_at < latest_available:
                    ordering_state = "OUT_OF_ORDER"
                elif completed_at == latest_available and str(latest[1]) != manifest_object_id:
                    ordering_state = "ORDER_CONFLICT"

        disposition = (
            "SNAPSHOT_CANDIDATE"
            if complete and ordering_state == "NEW"
            else "REJECTED"
            if ordering_state == "ORDER_CONFLICT"
            else "NO_HEAD_CHANGE"
        )
        terminal = result.terminal.value
        if terminal == InstrumentMasterTerminal.FAILED.value:
            terminal = "FAILED"
        cursor.execute(
            "INSERT INTO tushare_instrument_master_runs "
            "(run_id, source, profile_version, schema_version, parser_version, source_revision, "
            "manifest_date, manifest_capture_id, manifest_object_id, terminal, completeness, "
            "disposition, reason_code, record_count, opened_at, completed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                run_id,
                TUSHARE_INSTRUMENT_SOURCE,
                TUSHARE_INSTRUMENT_PROFILE_VERSION,
                TUSHARE_INSTRUMENT_SCHEMA_VERSION,
                TUSHARE_INSTRUMENT_PARSER_VERSION,
                result.source_revision,
                date.fromisoformat(result.manifest_date),
                result.manifest_capture_id,
                manifest_object_id,
                terminal,
                result.completeness.value,
                disposition,
                result.reason_code,
                len(result.records),
                opened_at,
                completed_at,
            ),
        )
        self._insert_raw_refs(cursor, result, run_id)
        if not complete:
            cursor.execute(
                "INSERT INTO tushare_instrument_master_audit "
                "(audit_id, run_id, action, details) VALUES (%s, %s, %s, %s::jsonb)",
                (uuid5(run_id, "audit:run-rejected"), run_id, "RUN_REJECTED", "{}"),
            )
            return InstrumentMasterPersistResult(
                run_id=run_id,
                snapshot_id=None,
                disposition=disposition,
                terminal=terminal,
                completeness=result.completeness.value,
                run_disposition="NO_HEAD_CHANGE",
            )

        snapshot_id = instrument_master_snapshot_id(run_id)
        snapshot_disposition = "SNAPSHOT_CANDIDATE" if ordering_state == "NEW" else "NO_HEAD_CHANGE"
        published_at = max(now, completed_at)
        cursor.execute(
            "INSERT INTO tushare_instrument_master_snapshots "
            "(snapshot_id, run_id, source, profile_version, terminal, completeness, disposition, "
            "available_at, published_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                snapshot_id,
                run_id,
                TUSHARE_INSTRUMENT_SOURCE,
                TUSHARE_INSTRUMENT_PROFILE_VERSION,
                result.terminal.value,
                result.completeness.value,
                snapshot_disposition,
                completed_at,
                published_at,
            ),
        )
        if ordering_state != "NEW":
            action = (
                "ORDER_CONFLICT" if ordering_state == "ORDER_CONFLICT" else "OUT_OF_ORDER_BLOCKED"
            )
            cursor.execute(
                "INSERT INTO tushare_instrument_master_audit "
                "(audit_id, run_id, snapshot_id, action, details) "
                "VALUES (%s, %s, %s, %s, %s::jsonb)",
                (
                    uuid5(run_id, "audit:ordering"),
                    run_id,
                    snapshot_id,
                    action,
                    f'{{"ordering_state":"{ordering_state}"}}',
                ),
            )
            return InstrumentMasterPersistResult(
                run_id=run_id,
                snapshot_id=snapshot_id,
                disposition="CONFLICT" if ordering_state == "ORDER_CONFLICT" else "NO_HEAD_CHANGE",
                terminal=result.terminal.value,
                completeness=result.completeness.value,
                run_disposition=(
                    "CONFLICT" if ordering_state == "ORDER_CONFLICT" else "OUT_OF_ORDER"
                ),
            )

        cursor.execute("SELECT unified_code, revision_id FROM tushare_instrument_master_heads")
        prior_heads = {str(row[0]): UUID(str(row[1])) for row in cursor.fetchall() if len(row) == 2}
        accepted_codes = {record.unified_code for record in result.records}
        for ordinal, record in enumerate(result.records):
            revision_id = uuid5(snapshot_id, f"revision:{record.unified_code}")
            cursor.execute(
                "SELECT h.revision_id, r.payload_fingerprint "
                "FROM tushare_instrument_master_heads AS h "
                "JOIN tushare_instrument_master_revisions AS r ON r.revision_id = h.revision_id "
                "WHERE h.unified_code = %s",
                (record.unified_code,),
            )
            head = cursor.fetchone()
            if head is not None and len(head) != 2:
                raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR)
            head_revision = None if head is None else head[1]
            head_matches = head_revision is not None and str(head_revision) == record.fingerprint()
            if head_matches:
                if head is None:
                    raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR)
                revision_id = UUID(str(head[0]))
            else:
                cursor.execute(
                    "SELECT revision_id FROM tushare_instrument_master_revisions "
                    "WHERE unified_code = %s AND payload_fingerprint = %s "
                    "ORDER BY created_at DESC, revision_id DESC LIMIT 1",
                    (record.unified_code, record.fingerprint()),
                )
                historical = cursor.fetchone()
                reused = historical is not None
                if reused:
                    revision_id = UUID(str(historical[0]))
                else:
                    self._insert_revision(cursor, snapshot_id, revision_id, record)
                cursor.execute(
                    "INSERT INTO tushare_instrument_master_audit "
                    "(audit_id, run_id, snapshot_id, unified_code, action, "
                    "after_revision_id, details) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)",
                    (
                        uuid5(snapshot_id, f"audit:{record.unified_code}"),
                        run_id,
                        snapshot_id,
                        record.unified_code,
                        "REVISION_ADDED",
                        revision_id,
                        '{"reused": %s}' % ("true" if reused else "false"),
                    ),
                )
            cursor.execute(
                f'SELECT "{self._schema}"."tushare_instrument_master_publish_head"(%s, %s, %s)',
                (record.unified_code, revision_id, completed_at),
            )
            publisher_result = cursor.fetchone()
            if publisher_result is None or not bool(publisher_result[0]):
                raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR)
            cursor.execute(
                "INSERT INTO tushare_instrument_master_snapshot_revisions "
                "(snapshot_id, revision_id, ordinal) VALUES (%s, %s, %s)",
                (snapshot_id, revision_id, ordinal),
            )
        for unified_code, prior_revision_id in sorted(prior_heads.items()):
            if unified_code in accepted_codes:
                continue
            candidate_id = uuid5(run_id, f"removal-candidate:{unified_code}")
            cursor.execute(
                "INSERT INTO tushare_instrument_master_removal_candidates "
                "(candidate_id, run_id, unified_code, prior_revision_id, reason, "
                "status, evidence_ref) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    candidate_id,
                    run_id,
                    unified_code,
                    prior_revision_id,
                    "ABSENT_FROM_COMPLETE_SNAPSHOT",
                    "REMOVAL_CANDIDATE",
                    result.manifest_capture_id,
                ),
            )
            cursor.execute(
                "INSERT INTO tushare_instrument_master_audit "
                "(audit_id, run_id, snapshot_id, unified_code, action, "
                "before_revision_id, details) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)",
                (
                    uuid5(snapshot_id, f"audit:removal:{unified_code}"),
                    run_id,
                    snapshot_id,
                    unified_code,
                    "REMOVAL_CANDIDATE",
                    prior_revision_id,
                    "{}",
                ),
            )
        cursor.execute(
            "INSERT INTO tushare_instrument_master_audit "
            "(audit_id, run_id, snapshot_id, action, details) VALUES (%s, %s, %s, %s, %s::jsonb)",
            (
                uuid5(run_id, "audit:snapshot-published"),
                run_id,
                snapshot_id,
                "SNAPSHOT_PUBLISHED",
                "{}",
            ),
        )
        return InstrumentMasterPersistResult(
            run_id=run_id,
            snapshot_id=snapshot_id,
            disposition=disposition,
            terminal=result.terminal.value,
            completeness=result.completeness.value,
            run_disposition="CONFIRMED",
        )

    @staticmethod
    def _insert_raw_refs(cursor: _Cursor, result: InstrumentMasterRunResult, run_id: UUID) -> None:
        page_capture_ids = {page.capture_id for page in result.page_refs}
        raw_date = date.fromisoformat(result.manifest_date)
        ordinal = 0
        for attempt in result.attempt_refs:
            # An accepted HTTP response is the same immutable capture as its
            # PAGE edge.  Store it once; rejected/transport attempts remain
            # separate edges so retry history is preserved exactly.
            if attempt.state == "ACCEPTED_RESPONSE" and attempt.capture_id in page_capture_ids:
                continue
            if attempt.state not in {"REJECTED_RESPONSE", "TRANSPORT_ERROR"}:
                raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR)
            parts = attempt.partition.split(":")
            if len(parts) != 3 or parts[0] not in {"stock_basic", "fund_basic"}:
                raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR)
            api_name, status_partition, market_value = parts
            market_partition = None if market_value == "ALL" else market_value
            if api_name == "stock_basic" and market_partition is not None:
                raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR)
            if api_name == "fund_basic" and market_partition != "E":
                raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR)
            if not attempt.request or not attempt.checksum:
                raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR)
            _digest_text(attempt.object_id)
            _digest_text(attempt.checksum)
            if type(attempt.size) is not int or attempt.size < 0:
                raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR)
            observed_at = _aware(attempt.observed_at, "attempt.observed_at")
            available_at = _aware(attempt.available_at, "attempt.available_at")
            if available_at < observed_at:
                raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR)
            cursor.execute(
                "INSERT INTO tushare_instrument_master_raw_refs "
                "(run_id, ordinal, ref_kind, api_name, status_partition, market_partition, "
                "offset_value, capture_id, object_id, raw_date, request_identity, status_code, "
                "content_type, observed_at, available_at, row_count, state, source_revision) "
                "VALUES (%s, %s, 'ATTEMPT', %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s, %s, 0, %s, %s)",
                (
                    run_id,
                    ordinal,
                    api_name,
                    status_partition,
                    market_partition,
                    attempt.offset,
                    attempt.capture_id,
                    attempt.object_id,
                    raw_date,
                    attempt.request,
                    attempt.status_code,
                    attempt.content_type,
                    observed_at,
                    available_at,
                    attempt.state,
                    attempt.source_revision,
                ),
            )
            ordinal += 1
        for page in result.page_refs:
            cursor.execute(
                "INSERT INTO tushare_instrument_master_raw_refs "
                "(run_id, ordinal, ref_kind, api_name, status_partition, market_partition, "
                "offset_value, capture_id, object_id, raw_date, request_identity, status_code, "
                "content_type, observed_at, available_at, row_count, state, source_revision) "
                "VALUES (%s, %s, 'PAGE', %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s, %s, %s, 'ACCEPTED_RESPONSE', %s)",
                (
                    run_id,
                    ordinal,
                    page.api_name,
                    page.status_partition,
                    page.market_partition,
                    page.offset,
                    page.capture_id,
                    page.object_id,
                    raw_date,
                    page.request,
                    page.status_code,
                    page.content_type,
                    page.observed_at,
                    page.available_at,
                    page.row_count,
                    page.source_revision,
                ),
            )
            ordinal += 1

    @staticmethod
    def _insert_revision(
        cursor: _Cursor,
        snapshot_id: UUID,
        revision_id: UUID,
        record: InstrumentMasterRecord,
    ) -> None:
        cursor.execute(
            "INSERT INTO tushare_instrument_master_revisions "
            "(revision_id, snapshot_id, unified_code, code, exchange, board, "
            "security_type, name, "
            "listing_lifecycle, trading_availability, risk_tags, list_date, delist_date, "
            "observed_at, available_at, source, source_revision, evidence_ref, "
            "payload_fingerprint) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                revision_id,
                snapshot_id,
                record.unified_code,
                record.code,
                record.exchange,
                record.board,
                record.security_type,
                record.name,
                record.listing_lifecycle.value,
                record.trading_availability.value,
                list(record.risk_tags),
                record.list_date,
                record.delist_date,
                record.observed_at,
                record.available_at,
                record.source,
                record.source_revision,
                record.evidence_ref,
                record.fingerprint(),
            ),
        )

    def query_as_of(self, unified_code: str, decision_time: datetime) -> InstrumentMasterPITResult:
        decision = _aware(decision_time, "decision_time")

        def query(cursor: _Cursor) -> InstrumentMasterPITResult:
            cursor.execute(
                "WITH latest_snapshot AS ("
                "SELECT s.run_id "
                "FROM tushare_instrument_master_snapshots AS s "
                "WHERE s.available_at <= %s "
                "AND s.published_at <= %s "
                "AND s.completeness = 'COMPLETE' "
                "AND s.disposition = 'SNAPSHOT_CANDIDATE' "
                "ORDER BY s.published_at DESC, s.snapshot_id DESC LIMIT 1"
                "), visible_revision AS ("
                "SELECT r.unified_code, r.code, r.exchange, r.board, r.security_type, r.name, "
                "r.listing_lifecycle, r.trading_availability, r.risk_tags, r.list_date, "
                "r.delist_date, r.observed_at, r.available_at, r.source, "
                "r.source_revision, r.evidence_ref, s.run_id "
                "FROM tushare_instrument_master_revisions AS r "
                "JOIN tushare_instrument_master_snapshot_revisions AS sr "
                "ON sr.revision_id = r.revision_id "
                "JOIN tushare_instrument_master_snapshots AS s "
                "ON s.snapshot_id = sr.snapshot_id "
                "WHERE r.unified_code = %s "
                "AND r.available_at <= %s "
                "AND s.available_at <= %s "
                "AND s.published_at <= %s "
                "AND s.completeness = 'COMPLETE' "
                "AND s.disposition = 'SNAPSHOT_CANDIDATE' "
                "ORDER BY s.published_at DESC, r.available_at DESC, "
                "r.created_at DESC, r.revision_id DESC LIMIT 1"
                ") SELECT v.unified_code, v.code, v.exchange, v.board, v.security_type, v.name, "
                "v.listing_lifecycle, v.trading_availability, v.risk_tags, v.list_date, "
                "v.delist_date, v.observed_at, v.available_at, v.source, "
                "v.source_revision, v.evidence_ref "
                "FROM visible_revision AS v "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM tushare_instrument_master_removal_candidates AS rc "
                "JOIN latest_snapshot AS latest ON latest.run_id = rc.run_id "
                "WHERE rc.unified_code = %s AND rc.status = 'REMOVAL_CANDIDATE'"
                ")",
                (decision, decision, unified_code, decision, decision, decision, unified_code),
            )
            row = cursor.fetchone()
            if row is None:
                return InstrumentMasterPITResult(unified_code, decision, "INDETERMINATE", None)
            try:
                record = InstrumentMasterRecord(
                    unified_code=str(row[0]),
                    code=str(row[1]),
                    exchange=str(row[2]),
                    board=str(row[3]),
                    security_type=str(row[4]),
                    name=str(row[5]),
                    listing_lifecycle=ListingLifecycle(str(row[6])),
                    trading_availability=TradingAvailability(str(row[7])),
                    risk_tags=tuple(cast(Sequence[str], row[8])),
                    list_date=cast(date | None, row[9]),
                    delist_date=cast(date | None, row[10]),
                    observed_at=cast(datetime, row[11]),
                    available_at=cast(datetime, row[12]),
                    source=str(row[13]),
                    source_revision=None if row[14] is None else str(row[14]),
                    evidence_ref=str(row[15]),
                )
            except (TypeError, ValueError):
                raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR) from None
            return InstrumentMasterPITResult(unified_code, decision, "VISIBLE", record)

        return self._run(query)

    def verify_schema(self) -> None:
        from data_worker.storage.migrations import verify_instrument_master_provider_schema

        with self._mutex:
            self._ensure_idle()
            try:
                transaction = cast(AbstractContextManager[Any], self._connection.transaction())
                with transaction:
                    cursor_context = cast(AbstractContextManager[Any], self._connection.cursor())
                    with cursor_context as raw_cursor:
                        cursor = cast(_Cursor, raw_cursor)
                        self._ensure_runtime_identity(cursor)
                        cursor.execute(
                            f'SET LOCAL search_path = "{self._schema}", pg_catalog, pg_temp'
                        )
                        verify_instrument_master_provider_schema(
                            self._connection,
                            schema=self._schema,
                            roles=self._provider_roles,
                        )
            except InstrumentMasterPersistenceError:
                raise
            except Exception:
                raise InstrumentMasterPersistenceError(_PERSISTENCE_ERROR) from None


def _result_times(
    result: InstrumentMasterRunResult,
    fallback: datetime,
) -> tuple[datetime, datetime]:
    # Failed runs can have no accepted PAGE edge, but their immutable
    # ATTEMPT edges still carry the exact observed/available timeline.  Use
    # those coordinates before falling back for a deliberately empty,
    # synthetic result (which the replay boundary never produces).
    times = [page.observed_at for page in result.page_refs] or [
        attempt.observed_at for attempt in result.attempt_refs
    ]
    ends = [page.available_at for page in result.page_refs] or [
        attempt.available_at for attempt in result.attempt_refs
    ]
    opened_at = min(times, default=fallback)
    completed_at = max(ends, default=fallback)
    if completed_at < opened_at:
        completed_at = opened_at
    return _aware(opened_at, "opened_at"), _aware(completed_at, "completed_at")


__all__ = [
    "InstrumentMasterPITResult",
    "InstrumentMasterPersistResult",
    "InstrumentMasterPersistenceError",
    "InstrumentMasterRepositoryTransactionError",
    "PostgresInstrumentMasterRepository",
    "instrument_master_snapshot_id",
]
