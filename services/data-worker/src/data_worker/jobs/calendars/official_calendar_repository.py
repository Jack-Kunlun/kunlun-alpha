"""Immutable V4 persistence for replay-verified SZSE direct-daily runs.

The public writer accepts only raw storage coordinates.  It always performs a
fresh C2A final-ledger replay before opening a database transaction; callers
cannot inject a result or proof into the authoritative path.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from threading import RLock
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from data_worker.jobs.calendars.official_szse_daily import (
    SZSE_CALENDAR_SOURCE,
    SZSE_CAPTURE_STATE_SOURCE,
    SZSE_CATALOG_SOURCE,
    SZSE_CONTRACT_VERSION,
    SZSE_MANIFEST_SOURCE,
    SZSE_PARSER_VERSION,
    SzseCaptureAttempt,
    SzseOfficialDailyResult,
    SzseRawReference,
    replay_szse_daily_run,
)
from data_worker.raw import RawStorage
from market_core.calendar.authoritative_snapshot import (
    CalendarResolution,
    CalendarResolutionReason,
    CalendarResolutionStatus,
    CalendarSnapshot,
    compose_direct_daily_snapshot,
    resolve,
)
from market_core.calendar.scan_run import (
    CalendarScanRunCatalogReceipt,
    CalendarScanRunDay,
    CalendarScanRunManifestReceipt,
    CalendarScanRunPage,
    CalendarScanRunPassReceipt,
    CalendarScanRunReceipt,
)
from psycopg.pq import TransactionStatus

if TYPE_CHECKING:
    from psycopg import Connection


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SNAPSHOT_NAMESPACE = "official-calendar-v4:snapshot"
_ADVISORY_KEY_PREFIX = "official-calendar-v4:SZSE:SZ:"
_EXPECTED_REF_COUNT = 69
_EXPECTED_ATTEMPT_COUNT = 28
_EXPECTED_CATALOG_COUNT = 12
_EXPECTED_PASS_COUNT = 2
_EXPECTED_PAGE_COUNT = 24
_IDENTITY_KINDS: Final = ("root", "path", "concat", "js")
_HEX_DIGEST_LENGTH = 64
_SOURCE_BY_KIND: Final[dict[str, str]] = {
    "root": SZSE_CALENDAR_SOURCE,
    "path": SZSE_CALENDAR_SOURCE,
    "concat": SZSE_CALENDAR_SOURCE,
    "js": SZSE_CALENDAR_SOURCE,
    "page": SZSE_CALENDAR_SOURCE,
    "run": SZSE_CAPTURE_STATE_SOURCE,
    "catalog": SZSE_CATALOG_SOURCE,
    "manifest": SZSE_MANIFEST_SOURCE,
}


class OfficialCalendarPersistenceError(RuntimeError):
    """Fixed, non-sensitive V4 persistence failure."""


@dataclass(frozen=True, slots=True)
class OfficialCalendarPersistResult:
    """Small immutable outcome returned after a V4 transaction commits."""

    run_id: UUID
    snapshot_id: UUID | None
    disposition: str
    terminal: str
    coverage_level: str
    run_disposition: str = "CONFIRMED"


def official_calendar_snapshot_id(run_id: UUID) -> UUID:
    if type(run_id) is not UUID:
        raise OfficialCalendarPersistenceError("official calendar persistence failed")
    return uuid5(run_id, _SNAPSHOT_NAMESPACE)


def _fixed_error() -> OfficialCalendarPersistenceError:
    return OfficialCalendarPersistenceError("official calendar persistence failed")


def _digest_bytes(value: str) -> bytes:
    if type(value) is not str or len(value) != _HEX_DIGEST_LENGTH:
        raise _fixed_error()
    try:
        return bytes.fromhex(value)
    except (TypeError, ValueError):
        raise _fixed_error() from None


def _ref_key(reference: SzseRawReference) -> tuple[str, str, str]:
    return (reference.kind, reference.capture_id, reference.checksum)


def _reference_source(reference: SzseRawReference) -> str:
    source = _SOURCE_BY_KIND.get(reference.kind)
    if source is None:
        raise _fixed_error()
    return source


def _reference_id(run_id: UUID, reference: SzseRawReference) -> UUID:
    return uuid5(run_id, f"official-calendar-v4:evidence:{reference.kind}:{reference.capture_id}")


def _is_canonical_state_request(value: object) -> bool:
    if type(value) is not str:
        return False
    prefix = "PUT path_sha256="
    digest = value[len(prefix) :] if value.startswith(prefix) else ""
    return len(digest) == _HEX_DIGEST_LENGTH and all(
        character in "0123456789abcdef" for character in digest
    )


def _expected_capture_attempt(
    run_id: UUID, ordinal: int
) -> tuple[str, str, str, int | None, int | None, str, str]:
    if ordinal in range(1, len(_IDENTITY_KINDS) + 1):
        endpoint_kind = _IDENTITY_KINDS[ordinal - 1]
        pass_number = None
        month = None
        label = endpoint_kind
        raw_role = f"IDENTITY_{endpoint_kind.upper()}"
    elif ordinal in range(len(_IDENTITY_KINDS) + 1, _EXPECTED_ATTEMPT_COUNT + 1):
        offset = ordinal - len(_IDENTITY_KINDS) - 1
        pass_number = offset // 12 + 1
        month = offset % 12 + 1
        endpoint_kind = "page"
        label = f"page:{pass_number}:{month}"
        raw_role = "RESPONSE"
    else:
        raise _fixed_error()
    attempt_id = f"capture-{uuid5(run_id, f'attempt:{label}').hex}"
    capture_id = f"capture-{uuid5(run_id, f'capture:{label}').hex}"
    state_capture_id = f"capture-{uuid5(run_id, f'state:{attempt_id}').hex}"
    return attempt_id, capture_id, endpoint_kind, pass_number, month, raw_role, state_capture_id


def _all_references(result: SzseOfficialDailyResult) -> tuple[SzseRawReference, ...]:
    ordered: list[SzseRawReference] = []
    seen: set[tuple[str, str, str]] = set()

    def add(reference: SzseRawReference | None) -> None:
        if reference is None:
            return
        if type(reference) is not SzseRawReference:
            raise _fixed_error()
        key = _ref_key(reference)
        if key not in seen:
            seen.add(key)
            ordered.append(reference)

    for identity_reference, attempt in zip(
        result.identity_assets, result.attempts[: len(_IDENTITY_KINDS)], strict=True
    ):
        add(identity_reference)
        add(attempt.state_ref)
    for reference in result.catalog_refs:
        add(reference)
    for attempt in result.attempts[len(_IDENTITY_KINDS) :]:
        add(attempt.raw_ref)
        add(attempt.state_ref)
    add(result.raw_manifest_ref)
    if len(ordered) != _EXPECTED_REF_COUNT:
        raise _fixed_error()
    previous_available: datetime | None = None
    for reference in ordered:
        if previous_available is not None and reference.observed_at < previous_available:
            raise _fixed_error()
        previous_available = reference.available_at
    return tuple(ordered)


def _roles(
    result: SzseOfficialDailyResult, references: tuple[SzseRawReference, ...]
) -> dict[tuple[str, str, str], str]:
    identity = tuple(result.identity_assets)
    if (
        len(identity) != len(_IDENTITY_KINDS)
        or tuple(reference.kind for reference in identity) != _IDENTITY_KINDS
    ):
        raise _fixed_error()
    state_keys = {
        _ref_key(attempt.state_ref) for attempt in result.attempts if attempt.state_ref is not None
    }
    catalog_keys = {_ref_key(reference) for reference in result.catalog_refs}
    manifest_key = _ref_key(result.raw_manifest_ref)
    role_map: dict[tuple[str, str, str], str] = {
        _ref_key(identity[0]): "IDENTITY_ROOT",
        _ref_key(identity[1]): "IDENTITY_PATH",
        _ref_key(identity[2]): "IDENTITY_CONCAT",
        _ref_key(identity[3]): "IDENTITY_JS",
        **{key: "CATALOG" for key in catalog_keys},
        **{key: "STATE" for key in state_keys},
        manifest_key: "MANIFEST",
    }
    for reference in references:
        key = _ref_key(reference)
        if key in role_map:
            continue
        if reference.kind == "page":
            role_map[key] = "RESPONSE"
        else:
            raise _fixed_error()
    if set(role_map) != {_ref_key(reference) for reference in references}:
        raise _fixed_error()
    return role_map


def _validate_result_shape(
    result: SzseOfficialDailyResult,
) -> tuple[tuple[SzseRawReference, ...], dict[tuple[str, str, str], str]]:
    if type(result) is not SzseOfficialDailyResult or result.exchange != "SZ":
        raise _fixed_error()
    proof = result.proof
    if type(proof) is not CalendarScanRunReceipt or proof.run_id != result.run_id:
        raise _fixed_error()
    if (
        proof.parser_version != SZSE_PARSER_VERSION
        or proof.contract_version != SZSE_CONTRACT_VERSION
    ):
        raise _fixed_error()
    if len(result.attempts) != _EXPECTED_ATTEMPT_COUNT:
        raise _fixed_error()
    if (
        len(result.catalog_refs) != _EXPECTED_CATALOG_COUNT
        or len(proof.catalog_receipts) != _EXPECTED_CATALOG_COUNT
    ):
        raise _fixed_error()
    if len(proof.pass_receipts) != _EXPECTED_PASS_COUNT or len(proof.pages) != _EXPECTED_PAGE_COUNT:
        raise _fixed_error()
    if (
        type(result.identity_assets) is not tuple
        or len(result.identity_assets) != len(_IDENTITY_KINDS)
        or tuple(reference.kind for reference in result.identity_assets) != _IDENTITY_KINDS
        or any(type(reference) is not SzseRawReference for reference in result.identity_assets)
    ):
        raise _fixed_error()
    if any(type(attempt) is not SzseCaptureAttempt for attempt in result.attempts):
        raise _fixed_error()
    for ordinal, attempt in enumerate(result.attempts, start=1):
        (
            expected_attempt_id,
            expected_capture_id,
            expected_endpoint_kind,
            expected_pass_number,
            expected_month,
            _expected_raw_role,
            expected_state_capture_id,
        ) = _expected_capture_attempt(result.run_id, ordinal)
        if (
            attempt.attempt_id != expected_attempt_id
            or attempt.capture_id != expected_capture_id
            or attempt.endpoint_kind != expected_endpoint_kind
            or attempt.pass_number != expected_pass_number
            or attempt.month != expected_month
            or type(attempt.raw_ref) is not SzseRawReference
            or attempt.raw_ref.kind != expected_endpoint_kind
            or attempt.raw_ref.capture_id != expected_capture_id
            or type(attempt.state_ref) is not SzseRawReference
            or attempt.state_ref.kind != "run"
            or attempt.state_ref.capture_id != expected_state_capture_id
        ):
            raise _fixed_error()
    references = _all_references(result)
    return references, _roles(result, references)


def _is_idle(connection: Any) -> bool:
    try:
        return connection.info.transaction_status is TransactionStatus.IDLE
    except Exception:
        return False


def _as_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise _fixed_error() from None


def _as_utc(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise _fixed_error()
    try:
        return value.astimezone(UTC)
    except Exception:
        raise _fixed_error() from None


def _insert_evidence(
    cursor: Any,
    *,
    run_id: UUID,
    preferred_ids: Mapping[tuple[str, str, str], UUID],
    references: tuple[SzseRawReference, ...],
    role_map: Mapping[tuple[str, str, str], str],
) -> dict[tuple[str, str, str], UUID]:
    ids: dict[tuple[str, str, str], UUID] = {}
    for reference in references:
        key = _ref_key(reference)
        evidence_id = preferred_ids.get(key, _reference_id(run_id, reference))
        ids[key] = evidence_id
        cursor.execute(
            "INSERT INTO official_calendar_evidence_refs "
            "(evidence_ref_id, run_id, role, source, raw_capture_id, raw_date, raw_size, "
            "content_type, object_sha256, route_sha256, request_identity, "
            "identity_verified, replay_verified, observed_at, available_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                evidence_id,
                run_id,
                role_map[key],
                _reference_source(reference),
                reference.capture_id,
                _as_date(reference.raw_date),
                reference.size,
                reference.content_type,
                _digest_bytes(reference.checksum),
                _digest_bytes(reference.route_digest),
                reference.request_identity,
                True,
                True,
                _as_utc(reference.observed_at),
                _as_utc(reference.available_at),
            ),
        )
    return ids


def _attempt_ref_id(
    ids: Mapping[tuple[str, str, str], UUID], reference: SzseRawReference | None
) -> UUID:
    if reference is None:
        raise _fixed_error()
    try:
        return ids[_ref_key(reference)]
    except (KeyError, TypeError):
        raise _fixed_error() from None


def _preferred_evidence_ids(
    run_id: UUID,
    result: SzseOfficialDailyResult,
    references: tuple[SzseRawReference, ...],
) -> dict[tuple[str, str, str], UUID]:
    """Bind V4 evidence rows to the domain proof's receipt IDs where available."""

    preferred: dict[tuple[str, str, str], UUID] = {}
    identity_keys = {_ref_key(reference) for reference in result.identity_assets}
    for reference in result.identity_assets:
        preferred[_ref_key(reference)] = uuid5(
            run_id, f"official-calendar-v4:identity:{reference.kind}"
        )
    for index, reference in enumerate(result.catalog_refs):
        preferred[_ref_key(reference)] = result.proof.catalog_receipts[index].raw_evidence_id
    for page in result.proof.pages:
        attempt_index = len(_IDENTITY_KINDS) + (page.pass_number - 1) * 12 + page.month - 1
        if attempt_index >= len(result.attempts):
            raise _fixed_error()
        attempt = result.attempts[attempt_index]
        if attempt.raw_ref is None or _ref_key(attempt.raw_ref) not in {
            _ref_key(reference) for reference in references
        }:
            raise _fixed_error()
        preferred[_ref_key(attempt.raw_ref)] = page.raw_evidence_id
    preferred[_ref_key(result.raw_manifest_ref)] = result.proof.manifest.raw_evidence_id
    for reference in references:
        key = _ref_key(reference)
        if key not in preferred and key not in identity_keys:
            preferred[key] = uuid5(
                run_id, f"official-calendar-v4:evidence:{reference.kind}:{reference.capture_id}"
            )
    if len(set(preferred.values())) != len(preferred):
        raise _fixed_error()
    return preferred


class PostgresOfficialCalendarRepository:
    """V4 repository whose authority boundary is the C2A public replay."""

    _mutex = RLock()

    def __init__(self, connection: Connection[Any]) -> None:
        if not _is_idle(connection):
            raise OfficialCalendarPersistenceError(
                "official calendar persistence requires idle connection"
            )
        self._connection = connection

    def persist_authoritative_szse_run(
        self,
        raw_storage: RawStorage,
        run_id: UUID,
        manifest_date: str,
        manifest_capture_id: str,
    ) -> OfficialCalendarPersistResult:
        """Replay raw evidence, then atomically append its immutable V4 graph."""

        try:
            result = replay_szse_daily_run(
                raw_storage,
                run_id=run_id,
                manifest_date=manifest_date,
                manifest_capture_id=manifest_capture_id,
            )
            references, role_map = _validate_result_shape(result)
        except OfficialCalendarPersistenceError:
            raise
        except Exception:
            raise _fixed_error() from None

        if not _is_idle(self._connection):
            raise OfficialCalendarPersistenceError(
                "official calendar persistence requires idle connection"
            )
        with self._mutex:
            try:
                with self._connection.transaction(), self._connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (f"{_ADVISORY_KEY_PREFIX}{result.proof.year}",),
                    )
                    existing = self._existing_run(cursor, result)
                    if existing is not None:
                        return existing
                    disposition, supersedes, run_disposition, create_snapshot = self._disposition(
                        cursor, result
                    )
                    snapshot = (
                        compose_direct_daily_snapshot(
                            snapshot_id=official_calendar_snapshot_id(result.run_id),
                            run_receipt=result.proof,
                            supersedes=supersedes,
                        )
                        if create_snapshot
                        else None
                    )
                    evidence_ids = self._insert_graph(
                        cursor,
                        result=result,
                        snapshot=snapshot,
                        references=references,
                        role_map=role_map,
                        disposition=disposition,
                        supersedes=supersedes,
                        run_disposition=run_disposition,
                    )
                    del evidence_ids
                    return OfficialCalendarPersistResult(
                        run_id=result.run_id,
                        snapshot_id=None if snapshot is None else snapshot.snapshot_id,
                        disposition=disposition,
                        terminal="INDETERMINATE" if snapshot is None else snapshot.terminal.value,
                        coverage_level=result.proof.coverage.level.value,
                        run_disposition=run_disposition,
                    )
            except OfficialCalendarPersistenceError:
                raise
            except Exception:
                raise _fixed_error() from None

    def _existing_run(
        self, cursor: Any, result: SzseOfficialDailyResult
    ) -> OfficialCalendarPersistResult | None:
        cursor.execute(
            "SELECT r.run_id, r.proof_sha256, r.manifest_capture_id, s.snapshot_id, "
            "r.run_disposition, s.disposition, s.terminal, s.coverage_level "
            "FROM official_calendar_scan_runs r LEFT JOIN official_calendar_snapshots s "
            "USING (run_id) "
            "WHERE r.run_id = %s",
            (result.run_id,),
        )
        rows = cursor.fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise _fixed_error()
        row = rows[0]
        if bytes(row[1]) != _digest_bytes(result.proof.proof_digest) or str(row[2]) != str(
            result.proof.manifest.capture_id
        ):
            raise _fixed_error()
        expected_snapshot = official_calendar_snapshot_id(result.run_id)
        if row[3] is not None and row[3] != expected_snapshot:
            raise _fixed_error()
        return OfficialCalendarPersistResult(
            run_id=result.run_id,
            snapshot_id=None if row[3] is None else expected_snapshot,
            disposition="DUPLICATE",
            terminal="INDETERMINATE" if row[6] is None else str(row[6]),
            coverage_level=result.proof.coverage.level.value if row[7] is None else str(row[7]),
            run_disposition=str(row[4]),
        )

    def _disposition(
        self, cursor: Any, result: SzseOfficialDailyResult
    ) -> tuple[str, UUID | None, str, bool]:
        cursor.execute(
            "SELECT r.run_id, r.run_disposition, r.cutoff_at, s.snapshot_id, "
            "s.available_at, s.disposition "
            "FROM official_calendar_scan_runs r "
            "LEFT JOIN official_calendar_snapshots s ON s.run_id=r.run_id "
            "WHERE r.authority='SZSE' AND r.exchange='SZ' AND r.calendar_year=%s "
            "ORDER BY r.cutoff_at, r.run_id",
            (result.proof.year,),
        )
        rows = cursor.fetchall()
        if not rows:
            return "SNAPSHOT_CREATED", None, "CONFIRMED", True
        if any(str(row[1]) != "CONFIRMED" for row in rows):
            return "OUT_OF_ORDER_BLOCKED", None, "OUT_OF_ORDER", False
        if any(row[3] is None or str(row[5]) != "SNAPSHOT_CREATED" for row in rows):
            return "OUT_OF_ORDER_BLOCKED", None, "OUT_OF_ORDER", False
        cutoff = _as_utc(result.proof.cutoff_at)
        if any(_as_utc(row[2]) == cutoff for row in rows):
            return "CONFLICT_HEAD", None, "CONFLICT", False
        latest = max(rows, key=lambda row: _as_utc(row[2]))
        if cutoff <= _as_utc(latest[2]):
            return "OUT_OF_ORDER_BLOCKED", None, "OUT_OF_ORDER", False
        return "SNAPSHOT_CREATED", latest[3], "CONFIRMED", True

    def _insert_graph(
        self,
        cursor: Any,
        *,
        result: SzseOfficialDailyResult,
        snapshot: CalendarSnapshot | None,
        references: tuple[SzseRawReference, ...],
        role_map: Mapping[tuple[str, str, str], str],
        disposition: str,
        supersedes: UUID | None,
        run_disposition: str,
    ) -> dict[tuple[str, str, str], UUID]:
        proof = result.proof
        coverage = proof.coverage
        manifest = proof.manifest
        ids = {
            "manifest_raw": manifest.raw_evidence_id,
            "manifest_artifact": manifest.artifact_id,
            "manifest_capture": manifest.capture_id,
        }
        cursor.execute(
            "INSERT INTO official_calendar_scan_runs "
            "(run_id, authority, exchange, calendar_year, parser_version, contract_version, "
            "source_version, policy_id, "
            "compiled_catalog_sha256, manifest_member_sha256, manifest_raw_sha256, proof_sha256, "
            "manifest_raw_evidence_id, manifest_artifact_id, manifest_capture_id, opened_at, "
            "cutoff_at, "
            "source_nowdate, coverage_level, confirmed_through, run_disposition) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                result.run_id,
                proof.authority,
                proof.exchange,
                proof.year,
                proof.parser_version,
                proof.contract_version,
                proof.parser_version,
                proof.policy_id,
                _digest_bytes(proof.compiled_catalog_sha256),
                _digest_bytes(manifest.canonical_member_digest),
                _digest_bytes(manifest.raw_artifact_sha256),
                _digest_bytes(proof.proof_digest),
                ids["manifest_raw"],
                ids["manifest_artifact"],
                ids["manifest_capture"],
                _as_utc(proof.opened_at),
                _as_utc(proof.cutoff_at),
                coverage.source_nowdate,
                coverage.level.value,
                coverage.confirmed_through,
                run_disposition,
            ),
        )
        evidence_ids = _insert_evidence(
            cursor,
            run_id=result.run_id,
            preferred_ids=_preferred_evidence_ids(result.run_id, result, references),
            references=references,
            role_map=role_map,
        )
        for catalog in proof.catalog_receipts:
            cursor.execute(
                "INSERT INTO official_calendar_run_catalogs "
                "(run_id, month, catalog_id, resource_id, raw_evidence_ref_id, "
                "raw_artifact_sha256) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    result.run_id,
                    catalog.month,
                    catalog.catalog_id,
                    catalog.resource_id,
                    evidence_ids[_ref_key(result.catalog_refs[catalog.month - 1])],
                    _digest_bytes(catalog.raw_artifact_sha256),
                ),
            )
        for receipt in proof.pass_receipts:
            cursor.execute(
                "INSERT INTO official_calendar_run_passes "
                "(run_id, pass_number, pass_id, opened_at, finished_at, member_sha256) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    result.run_id,
                    receipt.pass_number,
                    receipt.pass_id,
                    _as_utc(receipt.opened_at),
                    _as_utc(receipt.finished_at),
                    _digest_bytes(receipt.member_digest),
                ),
            )
        for page in proof.pages:
            cursor.execute(
                "INSERT INTO official_calendar_run_pages "
                "(run_id, pass_number, month, page_id, pass_id, catalog_id, resource_id, "
                "raw_evidence_ref_id, raw_artifact_sha256, canonical_payload_sha256, "
                "artifact_id, capture_id, opened_at, observed_at, available_at, source_nowdate) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    result.run_id,
                    page.pass_number,
                    page.month,
                    page.page_id,
                    page.pass_id,
                    page.catalog_id,
                    page.resource_id,
                    _attempt_ref_id(
                        evidence_ids,
                        result.attempts[
                            len(_IDENTITY_KINDS) + (page.pass_number - 1) * 12 + page.month - 1
                        ].raw_ref,
                    ),
                    _digest_bytes(page.raw_artifact_sha256),
                    _digest_bytes(page.canonical_payload_sha256),
                    page.artifact_id,
                    page.capture_id,
                    _as_utc(page.opened_at),
                    _as_utc(page.observed_at),
                    _as_utc(page.available_at),
                    page.source_nowdate,
                ),
            )
        for ordinal, attempt in enumerate(result.attempts, start=1):
            cursor.execute(
                "INSERT INTO official_calendar_capture_attempts "
                "(run_id, ordinal, attempt_id, capture_id, endpoint_kind, pass_number, month, "
                "status_code, error_code, replay_allowed, observed_at, available_at, "
                "raw_evidence_ref_id, state_evidence_ref_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    result.run_id,
                    ordinal,
                    attempt.attempt_id,
                    attempt.capture_id,
                    attempt.endpoint_kind,
                    attempt.pass_number,
                    attempt.month,
                    attempt.status_code or 200,
                    attempt.error_code,
                    attempt.replay_allowed,
                    _as_utc(attempt.observed_at),
                    _as_utc(attempt.available_at),
                    _attempt_ref_id(evidence_ids, attempt.raw_ref),
                    _attempt_ref_id(evidence_ids, attempt.state_ref),
                ),
            )
        if snapshot is not None:
            cursor.execute(
                "INSERT INTO official_calendar_snapshots "
                "(snapshot_id, run_id, authority, exchange, calendar_year, captured_at, "
                "available_at, "
                "terminal, "
                "coverage_level, confirmed_through, supersedes_snapshot_id, disposition) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    snapshot.snapshot_id,
                    result.run_id,
                    proof.authority,
                    proof.exchange,
                    proof.year,
                    _as_utc(snapshot.captured_at),
                    _as_utc(snapshot.available_at),
                    snapshot.terminal.value,
                    coverage.level.value,
                    coverage.confirmed_through,
                    supersedes,
                    disposition,
                ),
            )
            for ordinal, reference in enumerate(references):
                cursor.execute(
                    "INSERT INTO official_calendar_snapshot_evidence "
                    "(snapshot_id, run_id, ordinal, evidence_ref_id, role) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        snapshot.snapshot_id,
                        result.run_id,
                        ordinal,
                        evidence_ids[_ref_key(reference)],
                        role_map[_ref_key(reference)],
                    ),
                )
            for ordinal, day in enumerate(proof.daily_days):
                cursor.execute(
                    "INSERT INTO official_calendar_snapshot_days "
                    "(snapshot_id, ordinal, calendar_date, is_trading_day, reason) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        snapshot.snapshot_id,
                        ordinal,
                        day.date,
                        day.is_trading_day,
                        None if day.is_trading_day else "SPECIAL",
                    ),
                )
        return evidence_ids

    def resolve_szse_direct_daily_as_of(
        self, target_date: date, decision_time: datetime
    ) -> CalendarResolution:
        """Hydrate one visible V4 lineage and resolve it point-in-time."""

        if type(target_date) is not date or type(decision_time) is not datetime:
            raise _fixed_error()
        decision = _as_utc(decision_time)
        if not _is_idle(self._connection):
            raise OfficialCalendarPersistenceError(
                "official calendar persistence requires idle connection"
            )
        try:
            with (
                self._connection.transaction(force_rollback=True),
                self._connection.cursor() as cursor,
            ):
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cursor.execute(
                    "SELECT run_disposition FROM official_calendar_scan_runs "
                    "WHERE authority='SZSE' AND exchange='SZ' AND calendar_year=%s "
                    "AND cutoff_at <= %s",
                    (target_date.year, decision),
                )
                run_dispositions = tuple(str(row[0]) for row in cursor.fetchall())
                if "OUT_OF_ORDER" in run_dispositions:
                    raise _fixed_error()
                if "DUPLICATE" in run_dispositions:
                    raise _fixed_error()
                if "CONFLICT" in run_dispositions:
                    return CalendarResolution(
                        exchange="SZ",
                        date=target_date,
                        as_of=decision,
                        status=CalendarResolutionStatus.INDETERMINATE,
                        reason=CalendarResolutionReason.OFFICIAL_CONFLICT,
                    )
                if any(disposition != "CONFIRMED" for disposition in run_dispositions):
                    raise _fixed_error()
                cursor.execute(
                    "SELECT s.snapshot_id, s.run_id, s.disposition, s.supersedes_snapshot_id, "
                    "s.available_at, r.run_disposition "
                    "FROM official_calendar_snapshots s "
                    "JOIN official_calendar_scan_runs r ON r.run_id=s.run_id "
                    "WHERE s.authority='SZSE' AND s.exchange='SZ' "
                    "AND s.calendar_year=%s AND s.available_at <= %s "
                    "ORDER BY available_at, snapshot_id",
                    (target_date.year, decision),
                )
                rows = cursor.fetchall()
                if not rows:
                    return resolve("SZ", target_date, decision, ())
                if any(str(row[5]) != "CONFIRMED" for row in rows):
                    raise _fixed_error()
                if any(str(row[2]) != "SNAPSHOT_CREATED" for row in rows):
                    raise _fixed_error()
                snapshots = tuple(
                    self._hydrate_snapshot(
                        cursor,
                        UUID(str(row[0])),
                        UUID(str(row[1])),
                    )
                    for row in rows
                )
                return resolve("SZ", target_date, decision, snapshots)
        except OfficialCalendarPersistenceError:
            raise
        except Exception:
            raise _fixed_error() from None

    @staticmethod
    def _select_visible_lineage(rows: Iterable[tuple[Any, ...]]) -> tuple[UUID, UUID]:
        values = tuple(rows)
        if not values:
            raise _fixed_error()
        latest = max(values, key=lambda row: (_as_utc(row[4]), row[0]))
        if sum(1 for row in values if _as_utc(row[4]) == _as_utc(latest[4])) != 1:
            raise _fixed_error()
        return UUID(str(latest[0])), UUID(str(latest[1]))

    def _hydrate_snapshot(self, cursor: Any, snapshot_id: UUID, run_id: UUID) -> CalendarSnapshot:
        self._assert_complete_graph(cursor, snapshot_id, run_id)
        cursor.execute(
            "SELECT authority, exchange, calendar_year, captured_at, available_at, terminal, "
            "coverage_level, confirmed_through, supersedes_snapshot_id "
            "FROM official_calendar_snapshots "
            "WHERE snapshot_id=%s AND run_id=%s",
            (snapshot_id, run_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise _fixed_error()
        cursor.execute(
            "SELECT ordinal, calendar_date, is_trading_day FROM official_calendar_snapshot_days "
            "WHERE snapshot_id=%s ORDER BY ordinal",
            (snapshot_id,),
        )
        day_rows = cursor.fetchall()
        if len(day_rows) not in (365, 366):
            raise _fixed_error()
        days = tuple(
            CalendarScanRunDay(date=day[1], is_trading_day=bool(day[2])) for day in day_rows
        )
        proof = self._hydrate_proof(cursor, run_id, days)
        snapshot = compose_direct_daily_snapshot(
            snapshot_id=snapshot_id,
            run_receipt=proof,
            supersedes=row[8],
        )
        if (
            str(row[0]) != "SZSE"
            or str(row[1]) != "SZ"
            or int(row[2]) != proof.year
            or _as_utc(row[3]) != proof.opened_at
            or _as_utc(row[4]) != proof.cutoff_at
            or snapshot.coverage is None
            or snapshot.terminal.value != str(row[5])
            or snapshot.coverage.level.value != str(row[6])
            or snapshot.coverage.confirmed_through != row[7]
            or proof.coverage.level.value != str(row[6])
            or proof.coverage.confirmed_through != row[7]
        ):
            raise _fixed_error()
        return snapshot

    @staticmethod
    def _assert_complete_graph(cursor: Any, snapshot_id: UUID, run_id: UUID) -> None:
        cursor.execute(
            "SELECT "
            "(SELECT count(*) FROM official_calendar_evidence_refs WHERE run_id=%s), "
            "(SELECT count(*) FROM official_calendar_capture_attempts WHERE run_id=%s), "
            "(SELECT count(*) FROM official_calendar_run_catalogs WHERE run_id=%s), "
            "(SELECT count(*) FROM official_calendar_run_passes WHERE run_id=%s), "
            "(SELECT count(*) FROM official_calendar_run_pages WHERE run_id=%s), "
            "(SELECT count(*) FROM official_calendar_snapshot_evidence WHERE snapshot_id=%s), "
            "(SELECT count(*) FROM official_calendar_snapshot_days WHERE snapshot_id=%s)",
            (run_id, run_id, run_id, run_id, run_id, snapshot_id, snapshot_id),
        )
        counts = tuple(int(value) for value in cursor.fetchone() or ())
        if counts != (
            _EXPECTED_REF_COUNT,
            _EXPECTED_ATTEMPT_COUNT,
            _EXPECTED_CATALOG_COUNT,
            _EXPECTED_PASS_COUNT,
            _EXPECTED_PAGE_COUNT,
            _EXPECTED_REF_COUNT,
            365,
        ) and counts != (
            _EXPECTED_REF_COUNT,
            _EXPECTED_ATTEMPT_COUNT,
            _EXPECTED_CATALOG_COUNT,
            _EXPECTED_PASS_COUNT,
            _EXPECTED_PAGE_COUNT,
            _EXPECTED_REF_COUNT,
            366,
        ):
            raise _fixed_error()
        cursor.execute(
            "SELECT role, count(*) FROM official_calendar_evidence_refs "
            "WHERE run_id=%s GROUP BY role ORDER BY role",
            (run_id,),
        )
        if dict(cursor.fetchall()) != {
            "CATALOG": _EXPECTED_CATALOG_COUNT,
            "IDENTITY_CONCAT": 1,
            "IDENTITY_JS": 1,
            "IDENTITY_PATH": 1,
            "IDENTITY_ROOT": 1,
            "MANIFEST": 1,
            "RESPONSE": _EXPECTED_PAGE_COUNT,
            "STATE": _EXPECTED_ATTEMPT_COUNT,
        }:
            raise _fixed_error()
        cursor.execute(
            "SELECT role, source, count(*) FROM official_calendar_evidence_refs "
            "WHERE run_id=%s GROUP BY role, source ORDER BY role, source",
            (run_id,),
        )
        if tuple(cursor.fetchall()) != (
            ("CATALOG", SZSE_CATALOG_SOURCE, _EXPECTED_CATALOG_COUNT),
            ("IDENTITY_CONCAT", SZSE_CALENDAR_SOURCE, 1),
            ("IDENTITY_JS", SZSE_CALENDAR_SOURCE, 1),
            ("IDENTITY_PATH", SZSE_CALENDAR_SOURCE, 1),
            ("IDENTITY_ROOT", SZSE_CALENDAR_SOURCE, 1),
            ("MANIFEST", SZSE_MANIFEST_SOURCE, 1),
            ("RESPONSE", SZSE_CALENDAR_SOURCE, _EXPECTED_PAGE_COUNT),
            ("STATE", SZSE_CAPTURE_STATE_SOURCE, _EXPECTED_ATTEMPT_COUNT),
        ):
            raise _fixed_error()
        cursor.execute(
            "SELECT count(*) FROM official_calendar_scan_runs r "
            "LEFT JOIN official_calendar_evidence_refs e "
            "ON e.run_id=r.run_id AND e.evidence_ref_id=r.manifest_raw_evidence_id "
            "WHERE r.run_id=%s AND (e.evidence_ref_id IS NULL OR e.run_id<>r.run_id "
            "OR e.role<>'MANIFEST' OR e.source<>%s "
            "OR e.object_sha256<>r.manifest_raw_sha256 "
            "OR e.observed_at<>r.cutoff_at OR e.available_at<>r.cutoff_at)",
            (run_id, SZSE_MANIFEST_SOURCE),
        )
        if int(cursor.fetchone()[0]) != 0:
            raise _fixed_error()
        cursor.execute(
            "SELECT count(*) FROM official_calendar_capture_attempts a "
            "JOIN official_calendar_evidence_refs raw ON raw.evidence_ref_id=a.raw_evidence_ref_id "
            "JOIN official_calendar_evidence_refs state "
            "ON state.evidence_ref_id=a.state_evidence_ref_id "
            "WHERE a.run_id=%s AND (raw.run_id<>%s OR state.run_id<>%s "
            "OR (a.ordinal=1 AND raw.role<>'IDENTITY_ROOT') "
            "OR (a.ordinal=2 AND raw.role<>'IDENTITY_PATH') "
            "OR (a.ordinal=3 AND raw.role<>'IDENTITY_CONCAT') "
            "OR (a.ordinal=4 AND raw.role<>'IDENTITY_JS') "
            "OR (a.ordinal>4 AND raw.role<>'RESPONSE') OR state.role<>'STATE' "
            "OR raw.source<>%s OR state.source<>%s "
            "OR a.observed_at<>raw.observed_at OR a.available_at<>raw.available_at "
            "OR a.observed_at<>state.observed_at OR a.available_at<>state.available_at)",
            (run_id, run_id, run_id, SZSE_CALENDAR_SOURCE, SZSE_CAPTURE_STATE_SOURCE),
        )
        if int(cursor.fetchone()[0]) != 0:
            raise _fixed_error()
        cursor.execute(
            "SELECT count(*) FROM official_calendar_evidence_refs e "
            "JOIN official_calendar_scan_runs r ON r.run_id=e.run_id "
            "WHERE e.run_id=%s AND (e.observed_at < r.opened_at "
            "OR e.available_at > r.cutoff_at OR e.observed_at > e.available_at "
            "OR NOT e.identity_verified OR NOT e.replay_verified)",
            (run_id,),
        )
        if int(cursor.fetchone()[0]) != 0:
            raise _fixed_error()
        cursor.execute(
            "SELECT count(*) FROM ("
            "SELECT a.observed_at, a.available_at, "
            "lag(a.available_at) OVER (ORDER BY a.ordinal) AS previous_available "
            "FROM official_calendar_capture_attempts a WHERE a.run_id=%s"
            ") ordered WHERE previous_available IS NOT NULL "
            "AND (observed_at < previous_available OR available_at < previous_available)",
            (run_id,),
        )
        if int(cursor.fetchone()[0]) != 0:
            raise _fixed_error()
        cursor.execute(
            "SELECT count(*) FROM official_calendar_run_catalogs c "
            "JOIN official_calendar_evidence_refs e ON e.evidence_ref_id=c.raw_evidence_ref_id "
            "WHERE c.run_id=%s AND (e.run_id<>%s OR e.role<>'CATALOG' "
            "OR e.source<>%s "
            "OR e.object_sha256<>c.raw_artifact_sha256)",
            (run_id, run_id, SZSE_CATALOG_SOURCE),
        )
        if int(cursor.fetchone()[0]) != 0:
            raise _fixed_error()
        cursor.execute(
            "SELECT count(*) FROM official_calendar_run_pages p "
            "JOIN official_calendar_evidence_refs e ON e.evidence_ref_id=p.raw_evidence_ref_id "
            "WHERE p.run_id=%s AND (e.run_id<>%s OR e.role<>'RESPONSE' "
            "OR e.source<>%s "
            "OR e.object_sha256<>p.raw_artifact_sha256 "
            "OR e.observed_at<>p.observed_at OR e.available_at<>p.available_at)",
            (run_id, run_id, SZSE_CALENDAR_SOURCE),
        )
        if int(cursor.fetchone()[0]) != 0:
            raise _fixed_error()
        cursor.execute(
            "SELECT ordinal, role FROM official_calendar_snapshot_evidence "
            "WHERE snapshot_id=%s ORDER BY ordinal",
            (snapshot_id,),
        )
        if tuple(cursor.fetchall()) != (
            (0, "IDENTITY_ROOT"),
            (1, "STATE"),
            (2, "IDENTITY_PATH"),
            (3, "STATE"),
            (4, "IDENTITY_CONCAT"),
            (5, "STATE"),
            (6, "IDENTITY_JS"),
            (7, "STATE"),
            *((ordinal, "CATALOG") for ordinal in range(8, 20)),
            *(
                (ordinal, "RESPONSE" if (ordinal - 20) % 2 == 0 else "STATE")
                for ordinal in range(20, 68)
            ),
            (68, "MANIFEST"),
        ):
            raise _fixed_error()
        cursor.execute(
            "SELECT count(*) FROM official_calendar_snapshot_evidence se "
            "JOIN official_calendar_evidence_refs e ON e.evidence_ref_id=se.evidence_ref_id "
            "WHERE se.snapshot_id=%s AND (e.run_id<>%s OR se.run_id<>%s "
            "OR se.role<>e.role)",
            (snapshot_id, run_id, run_id),
        )
        if int(cursor.fetchone()[0]) != 0:
            raise _fixed_error()
        cursor.execute(
            "SELECT count(*) FROM ("
            "SELECT e.observed_at, e.available_at, "
            "lag(e.available_at) OVER (ORDER BY se.ordinal) AS previous_available "
            "FROM official_calendar_snapshot_evidence se "
            "JOIN official_calendar_evidence_refs e "
            "ON e.run_id=se.run_id AND e.evidence_ref_id=se.evidence_ref_id "
            "WHERE se.snapshot_id=%s"
            ") ordered WHERE previous_available IS NOT NULL "
            "AND (observed_at < previous_available OR available_at < previous_available)",
            (snapshot_id,),
        )
        if int(cursor.fetchone()[0]) != 0:
            raise _fixed_error()

    def _hydrate_proof(
        self, cursor: Any, run_id: UUID, days: tuple[CalendarScanRunDay, ...]
    ) -> CalendarScanRunReceipt:
        cursor.execute(
            "SELECT authority, exchange, calendar_year, parser_version, source_version, "
            "contract_version, policy_id, "
            "compiled_catalog_sha256, manifest_member_sha256, manifest_raw_sha256, proof_sha256, "
            "manifest_raw_evidence_id, manifest_artifact_id, manifest_capture_id, opened_at, "
            "cutoff_at, source_nowdate, "
            "coverage_level, confirmed_through, run_disposition "
            "FROM official_calendar_scan_runs WHERE run_id=%s",
            (run_id,),
        )
        run = cursor.fetchone()
        if run is None:
            raise _fixed_error()
        cursor.execute(
            "SELECT a.ordinal, a.attempt_id, a.capture_id, a.endpoint_kind, "
            "a.pass_number, a.month, a.status_code, a.error_code, a.replay_allowed, "
            "a.observed_at, a.available_at, raw.raw_capture_id, raw.role, raw.source, "
            "raw.observed_at, raw.available_at, state.raw_capture_id, state.request_identity, "
            "state.role, state.source, state.observed_at, state.available_at "
            "FROM official_calendar_capture_attempts a "
            "JOIN official_calendar_evidence_refs raw "
            "ON raw.run_id=a.run_id AND raw.evidence_ref_id=a.raw_evidence_ref_id "
            "JOIN official_calendar_evidence_refs state "
            "ON state.run_id=a.run_id AND state.evidence_ref_id=a.state_evidence_ref_id "
            "WHERE a.run_id=%s ORDER BY a.ordinal",
            (run_id,),
        )
        attempt_rows = cursor.fetchall()
        if len(attempt_rows) != _EXPECTED_ATTEMPT_COUNT:
            raise _fixed_error()
        previous_available: datetime | None = None
        for row in attempt_rows:
            ordinal = int(row[0])
            (
                expected_attempt_id,
                expected_capture_id,
                expected_endpoint_kind,
                expected_pass_number,
                expected_month,
                expected_raw_role,
                expected_state_capture_id,
            ) = _expected_capture_attempt(run_id, ordinal)
            observed_at = _as_utc(row[9])
            available_at = _as_utc(row[10])
            raw_observed_at = _as_utc(row[14])
            raw_available_at = _as_utc(row[15])
            state_observed_at = _as_utc(row[20])
            state_available_at = _as_utc(row[21])
            if (
                str(row[1]) != expected_attempt_id
                or str(row[2]) != expected_capture_id
                or str(row[3]) != expected_endpoint_kind
                or row[4] != expected_pass_number
                or row[5] != expected_month
                or int(row[6]) != 200
                or row[7] is not None
                or not bool(row[8])
                or str(row[11]) != expected_capture_id
                or str(row[12]) != expected_raw_role
                or str(row[13]) != SZSE_CALENDAR_SOURCE
                or str(row[16]) != expected_state_capture_id
                or not _is_canonical_state_request(row[17])
                or str(row[18]) != "STATE"
                or str(row[19]) != SZSE_CAPTURE_STATE_SOURCE
                or raw_observed_at != observed_at
                or raw_available_at != available_at
                or state_observed_at != available_at
                or state_available_at != available_at
                or available_at < observed_at
                or (previous_available is not None and observed_at < previous_available)
            ):
                raise _fixed_error()
            previous_available = available_at
        cursor.execute(
            "SELECT month, catalog_id, resource_id, raw_evidence_ref_id, raw_artifact_sha256 "
            "FROM official_calendar_run_catalogs WHERE run_id=%s ORDER BY month",
            (run_id,),
        )
        catalogs_rows = cursor.fetchall()
        cursor.execute(
            "SELECT pass_number, pass_id, opened_at, finished_at, member_sha256 "
            "FROM official_calendar_run_passes WHERE run_id=%s ORDER BY pass_number",
            (run_id,),
        )
        pass_rows = cursor.fetchall()
        cursor.execute(
            "SELECT pass_number, month, page_id, pass_id, catalog_id, resource_id, "
            "raw_evidence_ref_id, raw_artifact_sha256, canonical_payload_sha256, artifact_id, "
            "capture_id, opened_at, observed_at, available_at, source_nowdate "
            "FROM official_calendar_run_pages WHERE run_id=%s ORDER BY pass_number, month",
            (run_id,),
        )
        page_rows = cursor.fetchall()
        if len(catalogs_rows) != 12 or len(pass_rows) != 2 or len(page_rows) != 24:
            raise _fixed_error()

        def ref_for(evidence_id: UUID) -> SzseRawReference:
            cursor.execute(
                "SELECT source, raw_capture_id, raw_date, raw_size, content_type, object_sha256, "
                "route_sha256, request_identity, identity_verified, replay_verified, "
                "observed_at, available_at "
                "FROM official_calendar_evidence_refs WHERE evidence_ref_id=%s",
                (evidence_id,),
            )
            value = cursor.fetchone()
            if value is None:
                raise _fixed_error()
            (
                source,
                capture,
                raw_date,
                size,
                mime,
                object_sha,
                route_sha,
                request,
                identity_verified,
                replay_verified,
                observed,
                available,
            ) = value
            if not identity_verified or not replay_verified:
                raise _fixed_error()
            kind = "page"
            if str(source) == SZSE_CATALOG_SOURCE:
                kind = "catalog"
            elif str(source) == SZSE_CAPTURE_STATE_SOURCE:
                kind = "run"
            elif str(source) == SZSE_MANIFEST_SOURCE:
                kind = "manifest"
            elif str(request).startswith("GET") and "/aboutus/calendar" in str(request):
                kind = "root"
            elif str(request).startswith("GET") and "static.szse.cn" in str(request):
                kind = "js"
            return SzseRawReference(
                kind=kind,
                capture_id=str(capture),
                object_id=bytes(object_sha).hex(),
                checksum=bytes(object_sha).hex(),
                size=int(size),
                raw_date=raw_date.isoformat(),
                content_type=str(mime),
                route_digest=bytes(route_sha).hex(),
                request_identity=str(request),
                observed_at=observed,
                available_at=available,
            )

        catalog_receipts = tuple(
            CalendarScanRunCatalogReceipt(
                run_id=run_id,
                year=int(run[2]),
                month=int(row[0]),
                catalog_id=row[1],
                resource_id=str(row[2]),
                raw_evidence_id=UUID(str(row[3])),
                raw_artifact_sha256=bytes(row[4]).hex(),
                identity_verified=True,
                replay_verified=True,
            )
            for row in catalogs_rows
        )
        day_by_month: dict[int, tuple[CalendarScanRunDay, ...]] = {}
        for month in range(1, 13):
            day_by_month[month] = tuple(day for day in days if day.date.month == month)
        pages: list[CalendarScanRunPage] = []
        for row in page_rows:
            page_number, month = int(row[0]), int(row[1])
            expected_catalog = catalog_receipts[month - 1]
            if (
                UUID(str(row[4])) != expected_catalog.catalog_id
                or str(row[5]) != expected_catalog.resource_id
            ):
                raise _fixed_error()
            raw_ref = ref_for(UUID(str(row[6])))
            pages.append(
                CalendarScanRunPage(
                    run_id=run_id,
                    pass_number=page_number,
                    pass_id=row[3],
                    month=month,
                    year=int(run[2]),
                    page_id=row[2],
                    catalog_id=row[4],
                    resource_id=str(row[5]),
                    raw_evidence_id=UUID(str(row[6])),
                    raw_artifact_sha256=bytes(row[7]).hex(),
                    canonical_payload_sha256=bytes(row[8]).hex(),
                    artifact_id=row[9],
                    capture_id=row[10],
                    opened_at=row[11],
                    observed_at=row[12],
                    available_at=row[13],
                    source_nowdate=row[14],
                    identity_verified=True,
                    replay_verified=True,
                    days=day_by_month[month],
                )
            )
            del raw_ref
        page_tuple = tuple(pages)
        pass_receipts = tuple(
            CalendarScanRunPassReceipt(
                run_id=run_id,
                pass_number=int(row[0]),
                pass_id=row[1],
                opened_at=row[2],
                finished_at=row[3],
                page_refs=tuple(
                    page.page_id for page in page_tuple[(int(row[0]) - 1) * 12 : int(row[0]) * 12]
                ),
                member_digest=bytes(row[4]).hex(),
            )
            for row in pass_rows
        )
        manifest = CalendarScanRunManifestReceipt(
            run_id=run_id,
            raw_evidence_id=UUID(str(run[11])),
            artifact_id=UUID(str(run[12])),
            capture_id=UUID(str(run[13])),
            raw_artifact_sha256=bytes(run[9]).hex(),
            canonical_member_digest=bytes(run[8]).hex(),
            finalized_at=run[15],
        )
        receipt = CalendarScanRunReceipt(
            run_id=run_id,
            authority=str(run[0]),
            exchange=str(run[1]),
            year=int(run[2]),
            parser_version=str(run[3]),
            contract_version=str(run[5]),
            policy_id=str(run[6]),
            compiled_catalog_sha256=bytes(run[7]).hex(),
            opened_at=run[14],
            cutoff_at=run[15],
            catalog_receipts=catalog_receipts,
            pass_receipts=pass_receipts,
            pages=page_tuple,
            manifest=manifest,
            proof_digest=bytes(run[10]).hex(),
        )
        if (
            str(run[4]) != SZSE_PARSER_VERSION
            or str(run[3]) != SZSE_PARSER_VERSION
            or str(run[5]) != SZSE_CONTRACT_VERSION
            or str(run[17]) != receipt.coverage.level.value
            or receipt.coverage.confirmed_through != run[18]
            or receipt.coverage.source_nowdate != run[16]
            or str(run[19]) not in {"CONFIRMED", "CONFLICT", "DUPLICATE"}
        ):
            raise _fixed_error()
        return receipt


__all__ = [
    "OfficialCalendarPersistResult",
    "OfficialCalendarPersistenceError",
    "PostgresOfficialCalendarRepository",
    "official_calendar_snapshot_id",
]
