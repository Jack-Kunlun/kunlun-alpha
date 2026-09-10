"""Append-only persistence for calendar quality assessments and alerts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from threading import RLock
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast
from uuid import UUID, uuid4

from data_worker.jobs.calendars.calendar_quality import (
    CalendarClosureEvidence,
    CalendarQualityAlert,
    CalendarQualityAssessment,
    CalendarQualityDay,
    CalendarQualityEvidenceLink,
    CalendarQualityOverlay,
    CalendarQualitySource,
    CalendarQualitySourceKind,
    QualityAlertKind,
    QualityCoverageLevel,
    assess_calendar_quality,
)
from data_worker.jobs.calendars.official_calendar_repository import official_calendar_snapshot_id
from data_worker.storage.migrations import (
    CALENDAR_QUALITY_SCHEMA,
    CalendarQualityRoles,
    prepare_calendar_quality_runtime_context,
    verify_calendar_quality_runtime,
)
from psycopg.pq import TransactionStatus

if TYPE_CHECKING:
    from psycopg import Connection


QUALITY_ASSESSMENTS_TABLE = "calendar_quality_assessments"
QUALITY_SOURCES_TABLE = "calendar_quality_assessment_sources"
QUALITY_DAYS_TABLE = "calendar_quality_assessment_days"
QUALITY_MISSING_DATES_TABLE = "calendar_quality_missing_dates"
QUALITY_ALERTS_TABLE = "calendar_quality_alerts"
QUALITY_ALERT_SOURCES_TABLE = "calendar_quality_alert_sources"
QUALITY_OVERLAYS_TABLE = "calendar_quality_manual_overlays"
QUALITY_AUDIT_TABLE = "calendar_quality_audit"

_TRANSACTION_ERROR = "calendar quality repository requires an idle connection"
_PERSISTENCE_ERROR = "calendar quality persistence failed"
_OPERATION_CONFLICT = "calendar quality operation conflicts with existing content"
_SOURCE_ERROR = "calendar quality source reference is unavailable"
_OVERLAY_CONFLICT = "calendar quality overlay conflicts with existing content"
_T = TypeVar("_T")
_DEFAULT_ROLES = CalendarQualityRoles()


def _enum_text(value: StrEnum | str) -> str:
    return value.value if isinstance(value, StrEnum) else value


class CalendarQualityPersistenceError(RuntimeError):
    """Raised when an assessment cannot be safely persisted."""


class CalendarQualityOperationConflictError(CalendarQualityPersistenceError):
    """The same operation identity was reused with different evidence."""


class CalendarQualityOverlayConflictError(CalendarQualityPersistenceError):
    """The same overlay operation was reused with different content."""


class CalendarQualityDisposition(str):
    """String constants kept small for JSON/CLI callers."""

    CREATED = "CREATED"
    DUPLICATE = "DUPLICATE"


class CalendarQualityRepository:
    """Protocol-like base for quality persistence implementations."""

    def persist_assessment(self, assessment: CalendarQualityAssessment) -> QualityPersistResult:
        raise NotImplementedError

    def list_assessments(
        self, exchange: str, year: int, as_of: datetime
    ) -> tuple[CalendarQualityAssessment, ...]:
        raise NotImplementedError


def _validate_canonical_projection(assessment: CalendarQualityAssessment) -> None:
    """Reject caller-built values that do not equal the deterministic projection."""

    try:
        canonical = assess_calendar_quality(
            operation_id=assessment.operation_id,
            exchange=assessment.exchange,
            year=assessment.year,
            detected_at=assessment.detected_at,
            sources=assessment.sources,
        )
    except Exception:
        raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR) from None
    if canonical != assessment:
        raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR)


class InMemoryCalendarQualityRepository(CalendarQualityRepository):
    """Deterministic repository used by offline projection and contract tests."""

    def __init__(self) -> None:
        self._assessments: dict[UUID, CalendarQualityAssessment] = {}
        self._operations: dict[bytes, tuple[UUID, str]] = {}
        self._overlays: dict[UUID, CalendarQualityOverlay] = {}
        self._overlay_operations: dict[bytes, tuple[UUID, str]] = {}
        self._lock = RLock()

    def persist_assessment(self, assessment: CalendarQualityAssessment) -> QualityPersistResult:
        if type(assessment) is not CalendarQualityAssessment:
            raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR)
        _validate_canonical_projection(assessment)
        with self._lock:
            operation = self._operations.get(assessment.operation_key_hash)
            if operation is not None:
                existing_id, fingerprint = operation
                if fingerprint != assessment.content_fingerprint:
                    raise CalendarQualityOperationConflictError(_OPERATION_CONFLICT)
                existing = self._assessments.get(existing_id)
                if existing is None:
                    raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR)
                return QualityPersistResult(
                    assessment_id=existing.assessment_id,
                    disposition=CalendarQualityDisposition.DUPLICATE,
                    alert_count=len(existing.alerts),
                )
            if assessment.assessment_id in self._assessments:
                raise CalendarQualityOperationConflictError(_OPERATION_CONFLICT)
            self._assessments[assessment.assessment_id] = assessment
            self._operations[assessment.operation_key_hash] = (
                assessment.assessment_id,
                assessment.content_fingerprint,
            )
            return QualityPersistResult(
                assessment_id=assessment.assessment_id,
                disposition=CalendarQualityDisposition.CREATED,
                alert_count=len(assessment.alerts),
            )

    def assessment(self, assessment_id: UUID) -> CalendarQualityAssessment | None:
        with self._lock:
            return self._assessments.get(assessment_id)

    def list_assessments(
        self, exchange: str, year: int, as_of: datetime
    ) -> tuple[CalendarQualityAssessment, ...]:
        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR)
        cutoff = as_of.astimezone()
        with self._lock:
            return tuple(
                sorted(
                    (
                        assessment
                        for assessment in self._assessments.values()
                        if assessment.exchange == exchange
                        and assessment.year == year
                        and assessment.available_at <= cutoff
                    ),
                    key=lambda assessment: (
                        assessment.available_at,
                        assessment.assessment_id.bytes,
                    ),
                )
            )

    def list_alerts(
        self, exchange: str, year: int, as_of: datetime
    ) -> tuple[CalendarQualityAlert, ...]:
        return tuple(
            alert
            for assessment in self.list_assessments(exchange, year, as_of)
            for alert in assessment.alerts
            if alert.available_at <= as_of.astimezone()
        )

    def persist_manual_overlay(self, overlay: CalendarQualityOverlay) -> OverlayPersistResult:
        if type(overlay) is not CalendarQualityOverlay:
            raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR)
        with self._lock:
            assessment = self._assessments.get(overlay.assessment_id)
            if assessment is None or overlay.source_id not in assessment.source_ids:
                raise CalendarQualityPersistenceError(_SOURCE_ERROR)
            if overlay.calendar_date.year != assessment.year:
                raise CalendarQualityPersistenceError(_SOURCE_ERROR)
            if overlay.available_at < assessment.available_at:
                raise CalendarQualityPersistenceError(_SOURCE_ERROR)
            operation = self._overlay_operations.get(overlay.operation_key_hash)
            if operation is not None:
                existing_id, fingerprint = operation
                if fingerprint != _overlay_fingerprint(overlay):
                    raise CalendarQualityOverlayConflictError(_OVERLAY_CONFLICT)
                return OverlayPersistResult(existing_id, CalendarQualityDisposition.DUPLICATE)
            self._overlays[overlay.overlay_id] = overlay
            self._overlay_operations[overlay.operation_key_hash] = (
                overlay.overlay_id,
                _overlay_fingerprint(overlay),
            )
            return OverlayPersistResult(overlay.overlay_id, CalendarQualityDisposition.CREATED)

    def list_manual_overlays(
        self, assessment_id: UUID, as_of: datetime
    ) -> tuple[CalendarQualityOverlay, ...]:
        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR)
        cutoff = as_of.astimezone()
        with self._lock:
            return tuple(
                sorted(
                    (
                        overlay
                        for overlay in self._overlays.values()
                        if overlay.assessment_id == assessment_id and overlay.available_at <= cutoff
                    ),
                    key=lambda overlay: (overlay.available_at, overlay.overlay_id.bytes),
                )
            )


def _overlay_fingerprint(overlay: CalendarQualityOverlay) -> str:
    payload = {
        "assessment_id": str(overlay.assessment_id),
        "source_id": str(overlay.source_id),
        "calendar_date": overlay.calendar_date.isoformat(),
        "decision": overlay.decision,
        "reason_code": overlay.reason_code,
        "note": overlay.note,
        "author": overlay.author,
        "available_at": overlay.available_at.isoformat(),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class QualityPersistResult:
    assessment_id: UUID
    disposition: Literal["CREATED", "DUPLICATE"]
    alert_count: int


@dataclass(frozen=True, slots=True)
class OverlayPersistResult:
    overlay_id: UUID
    disposition: Literal["CREATED", "DUPLICATE"]


def _json_source_days(source: CalendarQualitySource) -> list[dict[str, object]]:
    return [
        {
            "date": day.calendar_date.isoformat(),
            "trading": day.is_trading_day,
            "reason": day.reason,
        }
        for day in source.days
    ]


def _json_source_closures(source: CalendarQualitySource) -> list[dict[str, object]]:
    return [
        {
            "source_id": str(closure.source_id),
            "date": closure.closure_date.isoformat(),
            "evidence_ref": closure.evidence_ref,
            "artifact_sha256": closure.artifact_sha256,
            "captured_at": closure.captured_at.isoformat(),
            "available_at": closure.available_at.isoformat(),
        }
        for closure in source.closures
    ]


def _decode_json_objects(value: object) -> list[dict[str, object]]:
    parsed: object = value
    if not isinstance(parsed, list):
        parsed = cast(object, json.loads(str(value)))
    if not isinstance(parsed, list):
        raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR)
    objects: list[dict[str, object]] = []
    parsed_items = cast(list[object], parsed)
    for item in parsed_items:
        if not isinstance(item, Mapping):
            raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR)
        item_mapping = cast(Mapping[object, object], item)
        objects.append({str(key): item_value for key, item_value in item_mapping.items()})
    return objects


def _decoded_datetime(item: Mapping[str, object], key: str) -> datetime:
    value = item.get(key)
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _source_from_row(row: tuple[Any, ...]) -> CalendarQualitySource:
    (
        source_id,
        source_kind,
        source_name,
        exchange,
        year,
        coverage_level,
        confirmed_through,
        captured_at,
        available_at,
        content_fingerprint,
        source_fingerprint,
        evidence_links_json,
        days_json,
        closures_json,
    ) = row
    try:
        raw_days = _decode_json_objects(days_json)
        raw_closures = _decode_json_objects(closures_json)
        raw_links = _decode_json_objects(evidence_links_json)
        evidence_links = tuple(
            CalendarQualityEvidenceLink(
                source_id=UUID(str(item["source_id"])),
                evidence_ref=str(item["evidence_ref"]),
                artifact_sha256=str(item["artifact_sha256"]),
            )
            for item in raw_links
        )
        days = tuple(
            CalendarQualityDay(
                calendar_date=date.fromisoformat(str(item["date"])),
                is_trading_day=bool(item["trading"]),
                reason=None if item.get("reason") is None else str(item["reason"]),
            )
            for item in raw_days
        )
        closures = tuple(
            CalendarClosureEvidence(
                source_id=UUID(str(item["source_id"])),
                closure_date=date.fromisoformat(str(item["date"])),
                evidence_ref=str(item["evidence_ref"]),
                artifact_sha256=str(item["artifact_sha256"]),
                captured_at=_decoded_datetime(item, "captured_at"),
                available_at=_decoded_datetime(item, "available_at"),
            )
            for item in raw_closures
        )
        source = CalendarQualitySource(
            source_id=UUID(str(source_id)),
            source_kind=str(source_kind),
            source_name=str(source_name),
            exchange=str(exchange),
            year=int(year),
            captured_at=cast(datetime, captured_at),
            available_at=cast(datetime, available_at),
            coverage_level=str(coverage_level),
            confirmed_through=confirmed_through,
            source_fingerprint=bytes(source_fingerprint).hex(),
            days=days,
            evidence_links=evidence_links,
            closures=closures,
        )
    except Exception:
        raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR) from None
    if source.content_fingerprint != bytes(content_fingerprint).hex():
        raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR)
    return source


class PostgresCalendarQualityRepository(CalendarQualityRepository):
    """PostgreSQL adapter for the additive V5 quality ledger."""

    def __init__(
        self,
        connection: Connection[Any],
        *,
        schema: str = CALENDAR_QUALITY_SCHEMA,
        roles: CalendarQualityRoles = _DEFAULT_ROLES,
    ) -> None:
        self._connection = connection
        self._schema = schema
        self._roles = roles
        self._mutex = RLock()

    def initialize(self) -> None:
        self._ensure_idle()
        try:
            verify_calendar_quality_runtime(
                self._connection,
                schema=self._schema,
                roles=self._roles,
            )
        except CalendarQualityPersistenceError:
            raise
        except Exception:
            raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR) from None

    def _ensure_idle(self) -> None:
        try:
            status = self._connection.info.transaction_status
        except AttributeError:
            raise CalendarQualityPersistenceError(_TRANSACTION_ERROR) from None
        if status != TransactionStatus.IDLE:
            raise CalendarQualityPersistenceError(_TRANSACTION_ERROR)

    def _run(self, operation: Any) -> Any:
        with self._mutex:
            self._ensure_idle()
            try:
                transaction = cast(AbstractContextManager[Any], self._connection.transaction())
                with transaction:
                    cursor_context = cast(AbstractContextManager[Any], self._connection.cursor())
                    with cursor_context as raw_cursor:
                        prepare_calendar_quality_runtime_context(
                            raw_cursor,
                            schema=self._schema,
                            expected_role=self._roles.runtime,
                        )
                        return operation(raw_cursor)
            except CalendarQualityPersistenceError:
                raise
            except Exception:
                raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR) from None

    @staticmethod
    def _as_utc(value: object) -> datetime:
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise CalendarQualityPersistenceError(_SOURCE_ERROR)
        try:
            return value.astimezone(UTC)
        except Exception:
            raise CalendarQualityPersistenceError(_SOURCE_ERROR) from None

    @classmethod
    def _load_official_source(
        cls,
        cursor: Any,
        source_id: UUID,
        *,
        exchange: str,
        year: int,
        detected_at: datetime,
    ) -> CalendarQualitySource:
        cursor.execute(
            "SELECT snapshot.snapshot_id, snapshot.run_id, snapshot.authority, "
            "snapshot.exchange, snapshot.calendar_year, snapshot.captured_at, "
            "snapshot.available_at, snapshot.terminal, snapshot.coverage_level, "
            "snapshot.confirmed_through, snapshot.disposition, run.run_disposition, "
            "run.authority, run.exchange, run.calendar_year, run.opened_at, run.cutoff_at, "
            "run.coverage_level, run.confirmed_through, run.parser_version, "
            "run.source_version, run.contract_version, run.policy_id, "
            "run.manifest_raw_evidence_id, run.manifest_capture_id, "
            "run.manifest_raw_sha256, run.proof_sha256 "
            "FROM official_calendar_snapshots AS snapshot "
            "JOIN official_calendar_scan_runs AS run ON run.run_id=snapshot.run_id "
            "WHERE snapshot.snapshot_id=%s AND snapshot.exchange=%s "
            "AND snapshot.calendar_year=%s",
            (source_id, exchange, year),
        )
        row = cursor.fetchone()
        if row is None:
            raise CalendarQualityPersistenceError(_SOURCE_ERROR)
        try:
            snapshot_id = UUID(str(row[0]))
            run_id = UUID(str(row[1]))
            authority = str(row[2])
            snapshot_exchange = str(row[3])
            snapshot_year = int(row[4])
            captured_at = cls._as_utc(row[5])
            available_at = cls._as_utc(row[6])
            terminal = str(row[7])
            coverage_level = QualityCoverageLevel(str(row[8]))
            confirmed_through = row[9]
            disposition = str(row[10])
            run_disposition = str(row[11])
            run_authority = str(row[12])
            run_exchange = str(row[13])
            run_year = int(row[14])
            run_opened_at = cls._as_utc(row[15])
            run_cutoff_at = cls._as_utc(row[16])
            run_coverage_level = QualityCoverageLevel(str(row[17]))
            run_confirmed_through = row[18]
            parser_version = str(row[19])
            source_version = str(row[20])
            contract_version = str(row[21])
            policy_id = str(row[22])
            manifest_raw_evidence_id = UUID(str(row[23]))
            manifest_capture_uuid = UUID(str(row[24]))
            manifest_raw_fingerprint = bytes(row[25]).hex()
            proof_fingerprint = bytes(row[26]).hex()
        except (TypeError, ValueError, CalendarQualityPersistenceError):
            raise CalendarQualityPersistenceError(_SOURCE_ERROR) from None
        expected_terminal = (
            "COMPLETE" if coverage_level is QualityCoverageLevel.FINAL_YEAR else "INDETERMINATE"
        )
        if (
            snapshot_id != source_id
            or snapshot_id != official_calendar_snapshot_id(run_id)
            or authority != "SZSE"
            or snapshot_exchange != exchange
            or snapshot_year != year
            or coverage_level
            not in {
                QualityCoverageLevel.CONFIRMED_HORIZON,
                QualityCoverageLevel.FINAL_YEAR,
            }
            or terminal != expected_terminal
            or disposition != "SNAPSHOT_CREATED"
            or run_disposition != "CONFIRMED"
            or captured_at > available_at
            or available_at > detected_at
            or run_authority != "SZSE"
            or run_exchange != exchange
            or run_year != year
            or run_opened_at != captured_at
            or run_cutoff_at != available_at
            or run_coverage_level is not coverage_level
            or run_confirmed_through != confirmed_through
            or parser_version != "szse-direct-daily-v4"
            or source_version != "szse-direct-daily-v4"
            or contract_version != "calendar-scan-run-v4"
            or policy_id != "szse-direct-daily-v1"
            or manifest_capture_uuid.version != 5
            or len(proof_fingerprint) != 64
            or len(manifest_raw_fingerprint) != 64
        ):
            raise CalendarQualityPersistenceError(_SOURCE_ERROR)

        cursor.execute(
            "SELECT se.ordinal, se.role, se.evidence_ref_id, evidence.raw_capture_id, "
            "evidence.object_sha256, "
            "evidence.run_id, evidence.role, evidence.source, evidence.identity_verified, "
            "evidence.replay_verified, evidence.observed_at, evidence.available_at "
            "FROM official_calendar_snapshot_evidence AS se "
            "JOIN official_calendar_evidence_refs AS evidence "
            "ON evidence.run_id=se.run_id AND evidence.evidence_ref_id=se.evidence_ref_id "
            "WHERE se.snapshot_id=%s AND se.run_id=%s ORDER BY se.ordinal",
            (snapshot_id, run_id),
        )
        evidence_rows = cursor.fetchall()
        expected_roles = {
            "IDENTITY_ROOT": 1,
            "IDENTITY_PATH": 1,
            "IDENTITY_CONCAT": 1,
            "IDENTITY_JS": 1,
            "CATALOG": 12,
            "RESPONSE": 24,
            "STATE": 28,
            "MANIFEST": 1,
        }
        role_counts: dict[str, int] = {}
        evidence_ref_ids: set[UUID] = set()
        evidence_links: list[CalendarQualityEvidenceLink] = []
        for expected_ordinal, evidence_row in enumerate(evidence_rows):
            try:
                (
                    ordinal,
                    snapshot_role,
                    evidence_ref_id,
                    raw_capture_id,
                    object_sha256,
                    evidence_run_id,
                    evidence_role,
                    evidence_source,
                    identity_verified,
                    replay_verified,
                    observed_at_raw,
                    evidence_available_raw,
                ) = evidence_row
                role = str(snapshot_role)
                observed_at = cls._as_utc(observed_at_raw)
                evidence_available_at = cls._as_utc(evidence_available_raw)
                evidence_ref_uuid = UUID(str(evidence_ref_id))
                digest = bytes(object_sha256).hex()
                raw_capture_text = str(raw_capture_id)
            except (TypeError, ValueError, CalendarQualityPersistenceError):
                raise CalendarQualityPersistenceError(_SOURCE_ERROR) from None
            expected_source = (
                "szse-calendar-catalog"
                if role == "CATALOG"
                else "szse-calendar-state"
                if role == "STATE"
                else "szse-calendar-manifest"
                if role == "MANIFEST"
                else "szse-calendar"
            )
            if (
                int(ordinal) != expected_ordinal
                or evidence_run_id != run_id
                or str(evidence_role) != role
                or str(evidence_source) != expected_source
                or type(identity_verified) is not bool
                or not identity_verified
                or type(replay_verified) is not bool
                or not replay_verified
                or observed_at < captured_at
                or evidence_available_at < observed_at
                or evidence_available_at > available_at
                or len(digest) != 64
            ):
                raise CalendarQualityPersistenceError(_SOURCE_ERROR)
            if evidence_ref_uuid in evidence_ref_ids:
                raise CalendarQualityPersistenceError(_SOURCE_ERROR)
            evidence_ref_ids.add(evidence_ref_uuid)
            role_counts[role] = role_counts.get(role, 0) + 1
            evidence_links.append(
                CalendarQualityEvidenceLink(
                    source_id=source_id,
                    evidence_ref=raw_capture_text,
                    artifact_sha256=digest,
                )
            )
        if role_counts != expected_roles:
            raise CalendarQualityPersistenceError(_SOURCE_ERROR)
        manifest_rows = [
            (evidence_row, evidence_link)
            for evidence_row, evidence_link in zip(evidence_rows, evidence_links, strict=True)
            if str(evidence_row[1]) == "MANIFEST"
        ]
        if len(manifest_rows) != 1:
            raise CalendarQualityPersistenceError(_SOURCE_ERROR)
        manifest_row, manifest_link = manifest_rows[0]
        # The domain manifest UUID identifies the logical receipt.  The paired
        # evidence link deliberately carries the raw-storage capture text;
        # these are separate identity domains and must not be compared.
        if (
            UUID(str(manifest_row[2])) != manifest_raw_evidence_id
            or manifest_link.artifact_sha256 != manifest_raw_fingerprint
        ):
            raise CalendarQualityPersistenceError(_SOURCE_ERROR)

        cursor.execute(
            "SELECT ordinal, calendar_date, is_trading_day, reason "
            "FROM official_calendar_snapshot_days WHERE snapshot_id=%s ORDER BY ordinal",
            (snapshot_id,),
        )
        day_rows = cursor.fetchall()
        expected_day_count = (date(year + 1, 1, 1) - date(year, 1, 1)).days
        if len(day_rows) != expected_day_count:
            raise CalendarQualityPersistenceError(_SOURCE_ERROR)
        days: list[CalendarQualityDay] = []
        for expected_ordinal, day_row in enumerate(day_rows):
            try:
                ordinal, calendar_date, is_trading_day, reason = day_row
                expected_date = date(year, 1, 1) + timedelta(days=expected_ordinal)
            except (TypeError, ValueError):
                raise CalendarQualityPersistenceError(_SOURCE_ERROR) from None
            expected_reason = None if is_trading_day is True else "SPECIAL"
            if (
                int(ordinal) != expected_ordinal
                or calendar_date != expected_date
                or type(is_trading_day) is not bool
                or reason != expected_reason
            ):
                raise CalendarQualityPersistenceError(_SOURCE_ERROR)
            days.append(
                CalendarQualityDay(
                    calendar_date=calendar_date,
                    is_trading_day=is_trading_day,
                    reason=reason,
                )
            )
        try:
            return CalendarQualitySource(
                source_id=source_id,
                source_kind=CalendarQualitySourceKind.OFFICIAL,
                source_name=authority,
                exchange=snapshot_exchange,
                year=snapshot_year,
                captured_at=captured_at,
                available_at=available_at,
                coverage_level=coverage_level,
                confirmed_through=confirmed_through,
                source_fingerprint=proof_fingerprint,
                days=tuple(days),
                evidence_links=tuple(evidence_links),
                closures=(),
            )
        except Exception:
            raise CalendarQualityPersistenceError(_SOURCE_ERROR) from None

    @classmethod
    def _load_trusted_sources(
        cls, cursor: Any, assessment: CalendarQualityAssessment
    ) -> tuple[CalendarQualitySource, ...]:
        if not assessment.sources:
            if assessment.source_ids:
                raise CalendarQualityPersistenceError(_SOURCE_ERROR)
            return ()
        if tuple(source.source_id for source in assessment.sources) != assessment.source_ids:
            raise CalendarQualityPersistenceError(_SOURCE_ERROR)
        trusted: list[CalendarQualitySource] = []
        for source in assessment.sources:
            if source.source_kind is not CalendarQualitySourceKind.OFFICIAL:
                raise CalendarQualityPersistenceError(_SOURCE_ERROR)
            trusted.append(
                cls._load_official_source(
                    cursor,
                    source.source_id,
                    exchange=assessment.exchange,
                    year=assessment.year,
                    detected_at=assessment.detected_at,
                )
            )
        return tuple(trusted)

    @classmethod
    def _validate_trusted_projection(
        cls, cursor: Any, assessment: CalendarQualityAssessment
    ) -> CalendarQualityAssessment:
        trusted_sources = cls._load_trusted_sources(cursor, assessment)
        try:
            canonical = assess_calendar_quality(
                operation_id=assessment.operation_id,
                exchange=assessment.exchange,
                year=assessment.year,
                detected_at=assessment.detected_at,
                sources=trusted_sources,
            )
        except Exception:
            raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR) from None
        if canonical != assessment:
            raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR)
        return canonical

    @staticmethod
    def _validate_projection(assessment: CalendarQualityAssessment) -> None:
        _validate_canonical_projection(assessment)

    def _persist(self, cursor: Any, assessment: CalendarQualityAssessment) -> QualityPersistResult:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (f"calendar-quality:{assessment.exchange}:{assessment.year}",),
        )
        assessment = self._validate_trusted_projection(cursor, assessment)
        cursor.execute(
            f"SELECT assessment_id, content_fingerprint FROM {QUALITY_ASSESSMENTS_TABLE} "
            "WHERE operation_key_hash=%s",
            (assessment.operation_key_hash,),
        )
        existing = cursor.fetchone()
        if existing is not None:
            if bytes(existing[1]).hex() != assessment.content_fingerprint:
                raise CalendarQualityOperationConflictError(_OPERATION_CONFLICT)
            cursor.execute(
                f"SELECT count(*) FROM {QUALITY_ALERTS_TABLE} WHERE assessment_id=%s",
                (existing[0],),
            )
            return QualityPersistResult(
                assessment_id=UUID(str(existing[0])),
                disposition=CalendarQualityDisposition.DUPLICATE,
                alert_count=int(cursor.fetchone()[0]),
            )
        cursor.execute(
            f"INSERT INTO {QUALITY_ASSESSMENTS_TABLE} "
            "(assessment_id, operation_id, operation_key_hash, content_fingerprint, exchange, "
            "calendar_year, "
            "status, coverage_level, confirmed_through, detected_at, available_at, "
            "source_count, "
            "missing_date_count, conflict_date_count, confirmed_days_json) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                assessment.assessment_id,
                assessment.operation_id,
                assessment.operation_key_hash,
                bytes.fromhex(assessment.content_fingerprint),
                assessment.exchange,
                assessment.year,
                _enum_text(assessment.status),
                _enum_text(assessment.coverage_level),
                assessment.confirmed_through,
                assessment.detected_at,
                assessment.available_at,
                len(assessment.sources),
                len(assessment.missing_dates),
                sum(alert.kind is QualityAlertKind.SOURCE_CONFLICT for alert in assessment.alerts),
                json.dumps(
                    [
                        {
                            "date": day.calendar_date.isoformat(),
                            "trading": day.is_trading_day,
                            "reason": day.reason,
                        }
                        for day in assessment.confirmed_days
                    ],
                    separators=(",", ":"),
                ),
            ),
        )
        for ordinal, source in enumerate(assessment.sources):
            cursor.execute(
                f"INSERT INTO {QUALITY_SOURCES_TABLE} "
                "(assessment_id, ordinal, source_id, source_kind, source_name, exchange, "
                "calendar_year, coverage_level, confirmed_through, captured_at, available_at, "
                "content_fingerprint, source_fingerprint, evidence_links_json, days_json, "
                "closures_json) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    assessment.assessment_id,
                    ordinal,
                    source.source_id,
                    _enum_text(source.source_kind),
                    source.source_name,
                    source.exchange,
                    source.year,
                    _enum_text(source.coverage_level),
                    source.confirmed_through,
                    source.captured_at,
                    source.available_at,
                    bytes.fromhex(source.content_fingerprint),
                    bytes.fromhex(source.source_fingerprint),
                    json.dumps(
                        [
                            {
                                "source_id": str(link.source_id),
                                "evidence_ref": link.evidence_ref,
                                "artifact_sha256": link.artifact_sha256,
                            }
                            for link in source.evidence_links
                        ],
                        separators=(",", ":"),
                    ),
                    json.dumps(_json_source_days(source), separators=(",", ":")),
                    json.dumps(_json_source_closures(source), separators=(",", ":")),
                ),
            )
        for ordinal, day in enumerate(assessment.confirmed_days):
            cursor.execute(
                f"INSERT INTO {QUALITY_DAYS_TABLE} "
                "(assessment_id, ordinal, calendar_date, is_trading_day, reason) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    assessment.assessment_id,
                    ordinal,
                    day.calendar_date,
                    day.is_trading_day,
                    day.reason,
                ),
            )
        for ordinal, missing_date in enumerate(assessment.missing_dates):
            cursor.execute(
                f"INSERT INTO {QUALITY_MISSING_DATES_TABLE} "
                "(assessment_id, ordinal, calendar_date) VALUES (%s, %s, %s)",
                (assessment.assessment_id, ordinal, missing_date),
            )
        for alert in assessment.alerts:
            cursor.execute(
                f"INSERT INTO {QUALITY_ALERTS_TABLE} "
                "(alert_id, assessment_id, kind, calendar_date, detail_code, detected_at, "
                "available_at, source_count, evidence_fingerprint) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    alert.alert_id,
                    assessment.assessment_id,
                    _enum_text(alert.kind),
                    alert.calendar_date,
                    alert.detail_code,
                    alert.detected_at,
                    alert.available_at,
                    len(alert.evidence_links),
                    bytes.fromhex(_alert_fingerprint(alert)),
                ),
            )
            for ordinal, link in enumerate(alert.evidence_links):
                cursor.execute(
                    f"INSERT INTO {QUALITY_ALERT_SOURCES_TABLE} "
                    "(alert_id, ordinal, source_id, evidence_ref, artifact_sha256) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        alert.alert_id,
                        ordinal,
                        link.source_id,
                        link.evidence_ref,
                        bytes.fromhex(link.artifact_sha256),
                    ),
                )
        cursor.execute(
            f"INSERT INTO {QUALITY_AUDIT_TABLE} "
            "(audit_id, assessment_id, operation_key_hash, action, entry) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                uuid4(),
                assessment.assessment_id,
                assessment.operation_key_hash,
                "ASSESSMENT_CREATED",
                "calendar quality assessment persisted",
            ),
        )
        return QualityPersistResult(
            assessment_id=assessment.assessment_id,
            disposition=CalendarQualityDisposition.CREATED,
            alert_count=len(assessment.alerts),
        )

    def persist_assessment(self, assessment: CalendarQualityAssessment) -> QualityPersistResult:
        if type(assessment) is not CalendarQualityAssessment:
            raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR)
        self._validate_projection(assessment)

        def persist(cursor: Any) -> QualityPersistResult:
            return self._persist(cursor, assessment)

        return cast(QualityPersistResult, self._run(persist))

    def persist_manual_overlay(self, overlay: CalendarQualityOverlay) -> OverlayPersistResult:
        if type(overlay) is not CalendarQualityOverlay:
            raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR)

        def persist(cursor: Any) -> OverlayPersistResult:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"calendar-quality-overlay:{overlay.operation_key_hash.hex()}",),
            )
            cursor.execute(
                f"SELECT a.exchange, a.calendar_year, a.available_at "
                f"FROM {QUALITY_ASSESSMENTS_TABLE} a WHERE a.assessment_id=%s",
                (overlay.assessment_id,),
            )
            assessment_row = cursor.fetchone()
            if assessment_row is None or overlay.calendar_date.year != int(assessment_row[1]):
                raise CalendarQualityPersistenceError(_SOURCE_ERROR)
            if overlay.available_at < assessment_row[2]:
                raise CalendarQualityPersistenceError(_SOURCE_ERROR)
            cursor.execute(
                f"SELECT 1 FROM {QUALITY_SOURCES_TABLE} WHERE assessment_id=%s AND source_id=%s",
                (overlay.assessment_id, overlay.source_id),
            )
            if cursor.fetchone() is None:
                raise CalendarQualityPersistenceError(_SOURCE_ERROR)
            cursor.execute(
                f"SELECT overlay_id, operation_id, operation_key_hash, assessment_id, source_id, "
                "calendar_date, decision, "
                "reason_code, note, author, available_at "
                f"FROM {QUALITY_OVERLAYS_TABLE} WHERE operation_key_hash=%s",
                (overlay.operation_key_hash,),
            )
            existing = cursor.fetchone()
            if existing is not None:
                existing_overlay = _overlay_from_row(existing)
                if _overlay_fingerprint(existing_overlay) != _overlay_fingerprint(overlay):
                    raise CalendarQualityOverlayConflictError(_OVERLAY_CONFLICT)
                return OverlayPersistResult(
                    existing_overlay.overlay_id, CalendarQualityDisposition.DUPLICATE
                )
            cursor.execute(
                f"INSERT INTO {QUALITY_OVERLAYS_TABLE} "
                "(overlay_id, operation_id, operation_key_hash, assessment_id, source_id, "
                "calendar_date, "
                "decision, reason_code, note, author, available_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    overlay.overlay_id,
                    overlay.operation_id,
                    overlay.operation_key_hash,
                    overlay.assessment_id,
                    overlay.source_id,
                    overlay.calendar_date,
                    overlay.decision,
                    overlay.reason_code,
                    overlay.note,
                    overlay.author,
                    overlay.available_at,
                ),
            )
            cursor.execute(
                f"INSERT INTO {QUALITY_AUDIT_TABLE} "
                "(audit_id, assessment_id, operation_key_hash, action, entry) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    uuid4(),
                    overlay.assessment_id,
                    overlay.operation_key_hash,
                    "MANUAL_OVERLAY_CREATED",
                    "calendar quality manual overlay persisted",
                ),
            )
            return OverlayPersistResult(overlay.overlay_id, CalendarQualityDisposition.CREATED)

        return cast(OverlayPersistResult, self._run(persist))

    def list_assessments(
        self, exchange: str, year: int, as_of: datetime
    ) -> tuple[CalendarQualityAssessment, ...]:
        def read(cursor: Any) -> tuple[CalendarQualityAssessment, ...]:
            cursor.execute(
                f"SELECT assessment_id, operation_id, operation_key_hash, content_fingerprint, "
                "exchange, "
                "calendar_year, status, coverage_level, confirmed_through, detected_at, "
                "available_at, source_count, missing_date_count, conflict_date_count, "
                "confirmed_days_json "
                f"FROM {QUALITY_ASSESSMENTS_TABLE} WHERE exchange=%s AND calendar_year=%s "
                "AND available_at <= %s ORDER BY available_at, assessment_id",
                (exchange, year, as_of),
            )
            rows = cursor.fetchall()
            results: list[CalendarQualityAssessment] = []
            for row in rows:
                assessment_id = UUID(str(row[0]))
                cursor.execute(
                    f"SELECT source_id, source_kind, source_name, exchange, calendar_year, "
                    "coverage_level, "
                    "confirmed_through, captured_at, available_at, content_fingerprint, "
                    "source_fingerprint, evidence_links_json, days_json, closures_json "
                    f"FROM {QUALITY_SOURCES_TABLE} WHERE assessment_id=%s ORDER BY ordinal",
                    (assessment_id,),
                )
                source_rows = cursor.fetchall()
                source_values: list[CalendarQualitySource] = []
                for source_row in source_rows:
                    # The source table records its scope, but the assessment query already
                    # establishes the exact scope.  Injecting it avoids duplicating trust in
                    # untrusted JSON while CalendarQualitySource revalidates all values.
                    source = _source_from_row(tuple(source_row))
                    if source.exchange != exchange or source.year != year:
                        raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR)
                    source_values.append(source)
                cursor.execute(
                    f"SELECT ordinal, calendar_date, is_trading_day, reason "
                    f"FROM {QUALITY_DAYS_TABLE} "
                    "WHERE assessment_id=%s ORDER BY ordinal",
                    (assessment_id,),
                )
                confirmed_days = tuple(
                    CalendarQualityDay(
                        calendar_date=cast(date, item[1]),
                        is_trading_day=bool(item[2]),
                        reason=None if item[3] is None else str(item[3]),
                    )
                    for item in cursor.fetchall()
                )
                cursor.execute(
                    f"SELECT calendar_date FROM {QUALITY_MISSING_DATES_TABLE} "
                    "WHERE assessment_id=%s ORDER BY ordinal",
                    (assessment_id,),
                )
                missing_dates = tuple(cast(date, item[0]) for item in cursor.fetchall())
                cursor.execute(
                    f"SELECT alert_id, kind, calendar_date, detail_code, detected_at, "
                    "available_at, "
                    "source_count, evidence_fingerprint "
                    f"FROM {QUALITY_ALERTS_TABLE} WHERE assessment_id=%s ORDER BY alert_id",
                    (assessment_id,),
                )
                alerts: list[CalendarQualityAlert] = []
                for alert_row in cursor.fetchall():
                    cursor.execute(
                        f"SELECT source_id, evidence_ref, artifact_sha256 "
                        f"FROM {QUALITY_ALERT_SOURCES_TABLE} "
                        "WHERE alert_id=%s ORDER BY ordinal",
                        (alert_row[0],),
                    )
                    evidence_rows = cursor.fetchall()
                    alert = CalendarQualityAlert(
                        alert_id=UUID(str(alert_row[0])),
                        kind=str(alert_row[1]),
                        calendar_date=alert_row[2],
                        detail_code=str(alert_row[3]),
                        evidence_links=tuple(
                            CalendarQualityEvidenceLink(
                                source_id=UUID(str(item[0])),
                                evidence_ref=str(item[1]),
                                artifact_sha256=bytes(item[2]).hex(),
                            )
                            for item in evidence_rows
                        ),
                        detected_at=cast(datetime, alert_row[4]),
                        available_at=cast(datetime, alert_row[5]),
                    )
                    if int(alert_row[6]) != len(alert.evidence_links) or bytes(
                        alert_row[7]
                    ).hex() != _alert_fingerprint(alert):
                        raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR)
                    alerts.append(alert)
                expected_confirmed_days = [
                    {
                        "date": day.calendar_date.isoformat(),
                        "trading": day.is_trading_day,
                        "reason": day.reason,
                    }
                    for day in confirmed_days
                ]
                stored_confirmed_days = _decode_json_objects(row[14])
                if (
                    bytes(row[2]) != hashlib.sha256(str(row[1]).encode("utf-8")).digest()
                    or int(row[11]) != len(source_values)
                    or int(row[12]) != len(missing_dates)
                    or int(row[13])
                    != sum(alert.kind is QualityAlertKind.SOURCE_CONFLICT for alert in alerts)
                    or stored_confirmed_days != expected_confirmed_days
                ):
                    raise CalendarQualityPersistenceError(_PERSISTENCE_ERROR)
                result = CalendarQualityAssessment(
                    assessment_id=assessment_id,
                    operation_id=str(row[1]),
                    exchange=str(row[4]),
                    year=int(row[5]),
                    detected_at=cast(datetime, row[9]),
                    available_at=cast(datetime, row[10]),
                    status=str(row[6]),
                    coverage_level=str(row[7]),
                    confirmed_through=row[8],
                    source_ids=tuple(source.source_id for source in source_values),
                    missing_dates=missing_dates,
                    confirmed_days=confirmed_days,
                    alerts=tuple(alerts),
                    content_fingerprint=bytes(row[3]).hex(),
                    sources=tuple(source_values),
                )
                _validate_canonical_projection(result)
                results.append(result)
            return tuple(results)

        return cast(tuple[CalendarQualityAssessment, ...], self._run(read))

    def list_manual_overlays(
        self, assessment_id: UUID, as_of: datetime
    ) -> tuple[CalendarQualityOverlay, ...]:
        def read(cursor: Any) -> tuple[CalendarQualityOverlay, ...]:
            cursor.execute(
                f"SELECT overlay_id, operation_id, operation_key_hash, assessment_id, source_id, "
                f"calendar_date, decision, reason_code, note, author, available_at "
                f"FROM {QUALITY_OVERLAYS_TABLE} "
                "WHERE assessment_id=%s AND available_at <= %s "
                "ORDER BY available_at, overlay_id",
                (assessment_id, as_of),
            )
            return tuple(_overlay_from_row(tuple(row)) for row in cursor.fetchall())

        return cast(tuple[CalendarQualityOverlay, ...], self._run(read))


def _alert_fingerprint(alert: CalendarQualityAlert) -> str:
    payload = {
        "kind": _enum_text(alert.kind),
        "date": None if alert.calendar_date is None else alert.calendar_date.isoformat(),
        "detail": alert.detail_code,
        "evidence_links": [
            {
                "source_id": str(link.source_id),
                "evidence_ref": link.evidence_ref,
                "artifact_sha256": link.artifact_sha256,
            }
            for link in alert.evidence_links
        ],
        "detected_at": alert.detected_at.isoformat(),
        "available_at": alert.available_at.isoformat(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _overlay_from_row(row: tuple[Any, ...]) -> CalendarQualityOverlay:
    return CalendarQualityOverlay(
        overlay_id=UUID(str(row[0])),
        operation_id=str(row[1]),
        assessment_id=UUID(str(row[3])),
        source_id=UUID(str(row[4])),
        calendar_date=cast(date, row[5]),
        decision=cast(Any, str(row[6])),
        reason_code=str(row[7]),
        note=str(row[8]),
        author=str(row[9]),
        available_at=cast(datetime, row[10]),
    )


__all__ = [
    "CalendarQualityDisposition",
    "CalendarQualityOperationConflictError",
    "CalendarQualityOverlayConflictError",
    "CalendarQualityPersistenceError",
    "CalendarQualityRepository",
    "InMemoryCalendarQualityRepository",
    "OverlayPersistResult",
    "PostgresCalendarQualityRepository",
    "QualityPersistResult",
]
