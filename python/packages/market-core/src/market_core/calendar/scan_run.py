"""Immutable proof types for an audited direct-daily calendar scan run.

The types in this module deliberately do not import the authoritative snapshot
module.  A provider adapter may construct them only after it has retained and
replayed the source bytes.  These types prove the identity, ordering,
membership, and point-in-time relationships supplied by that adapter; they do
not, by themselves, claim that an external source's raw bytes are authentic.
"""

from __future__ import annotations

import calendar as _calendar
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from re import fullmatch
from typing import Final, NoReturn
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

_INVALID_SCAN_RUN = "invalid calendar scan run"
_SHA256_PATTERN = r"[0-9a-f]{64}"
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
SZSE_DIRECT_DAILY_POLICY_ID: Final = "szse-direct-daily-v1"
_PASS_NAMES: Final[tuple[int, int]] = (1, 2)
_CATALOG_DIGEST_VERSION: Final = "calendar-scan-catalog-v1"
_PASS_DIGEST_VERSION: Final = "calendar-scan-pass-v1"
_MANIFEST_DIGEST_VERSION: Final = "calendar-scan-manifest-v1"
_PROOF_DIGEST_VERSION: Final = "calendar-scan-run-proof-v2"


class CalendarScanRunError(ValueError):
    """Raised when a scan-run proof is not structurally trustworthy."""


class ScanRunCoverageLevel(StrEnum):
    """Point-in-time coverage derived from source and cutoff watermarks."""

    FINAL_YEAR = "FINAL_YEAR"
    CONFIRMED_HORIZON = "CONFIRMED_HORIZON"
    INDETERMINATE = "INDETERMINATE"


def _fail() -> NoReturn:
    """Raise a fixed error without exposing hostile input or parser details."""

    raise CalendarScanRunError(_INVALID_SCAN_RUN) from None


def _strict_uuid(value: object) -> UUID:
    if type(value) is not UUID:
        _fail()
    return value


def _strict_date(value: object) -> date:
    if type(value) is not date:
        _fail()
    return value


def _strict_text(value: object) -> str:
    if type(value) is not str or not value or "\x00" in value:
        _fail()
    return value


def _strict_sha256(value: object) -> str:
    if type(value) is not str or fullmatch(_SHA256_PATTERN, value) is None:
        _fail()
    return value


def _strict_bool(value: object) -> bool:
    if type(value) is not bool:
        _fail()
    return value


def _strict_datetime(value: object) -> datetime:
    if type(value) is not datetime:
        _fail()
    normalized: datetime | None = None
    try:
        if value.tzinfo is not None and value.utcoffset() is not None:
            normalized = value.astimezone(UTC)
    except Exception:
        normalized = None
    if normalized is None:
        _fail()
    return normalized


def _month_dates(year: int, month: int) -> tuple[date, ...]:
    try:
        count = _calendar.monthrange(year, month)[1]
        first = date(year, month, 1)
    except Exception:
        _fail()
    return tuple(date.fromordinal(first.toordinal() + offset) for offset in range(count))


def calendar_scan_run_resource_id(year: int, month: int) -> str:
    """Return the sole resource key for one SZSE direct-daily month."""

    if type(year) is not int or not 1 <= year <= 9999:
        _fail()
    if type(month) is not int or not 1 <= month <= 12:
        _fail()
    return f"szse-direct-daily-{year:04d}-{month:02d}"


def calendar_scan_run_pass_id(run_id: UUID, pass_number: int) -> UUID:
    """Derive the only accepted pass id for a run and pass number."""

    _strict_uuid(run_id)
    if type(pass_number) is not int or pass_number not in _PASS_NAMES:
        _fail()
    return uuid5(run_id, f"pass:{pass_number}")


@dataclass(frozen=True, slots=True)
class CalendarScanRunDay:
    """One direct-daily row with no provider-specific free text."""

    date: date
    is_trading_day: bool

    def __post_init__(self) -> None:
        if type(self) is not CalendarScanRunDay:
            _fail()
        _strict_date(self.date)
        _strict_bool(self.is_trading_day)


ScanRunDay = CalendarScanRunDay


def _day_payload(day: CalendarScanRunDay) -> dict[str, object]:
    if type(day) is not CalendarScanRunDay:
        _fail()
    return {
        "date": day.date.isoformat(),
        "status": "TRADING" if day.is_trading_day else "NON_TRADING",
    }


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except Exception:
        _fail()


def calendar_scan_run_payload_digest(days: tuple[CalendarScanRunDay, ...]) -> str:
    """Hash a stable canonical representation of ordered page rows."""

    if type(days) is not tuple or any(type(day) is not CalendarScanRunDay for day in days):
        _fail()
    payload = _canonical_json([_day_payload(day) for day in days])
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class CalendarScanRunCatalogReceipt:
    """One verified, fixed-year/month catalog mapping belonging to a run."""

    run_id: UUID
    year: int
    month: int
    catalog_id: UUID
    resource_id: str
    raw_evidence_id: UUID
    raw_artifact_sha256: str
    identity_verified: bool
    replay_verified: bool

    def __post_init__(self) -> None:
        if type(self) is not CalendarScanRunCatalogReceipt:
            _fail()
        _strict_uuid(self.run_id)
        if type(self.year) is not int or not 1 <= self.year <= 9999:
            _fail()
        if type(self.month) is not int or not 1 <= self.month <= 12:
            _fail()
        _strict_uuid(self.catalog_id)
        _strict_text(self.resource_id)
        if self.resource_id != calendar_scan_run_resource_id(self.year, self.month):
            _fail()
        _strict_uuid(self.raw_evidence_id)
        _strict_sha256(self.raw_artifact_sha256)
        _strict_bool(self.identity_verified)
        _strict_bool(self.replay_verified)


@dataclass(frozen=True, slots=True)
class CalendarScanRunPage:
    """One month page bound to a run, pass, resource, and raw receipt."""

    run_id: UUID
    pass_number: int
    pass_id: UUID
    month: int
    year: int
    page_id: UUID
    catalog_id: UUID
    resource_id: str
    raw_evidence_id: UUID
    raw_artifact_sha256: str
    canonical_payload_sha256: str
    artifact_id: UUID
    capture_id: UUID
    opened_at: datetime
    observed_at: datetime
    available_at: datetime
    source_nowdate: date
    identity_verified: bool
    replay_verified: bool
    days: tuple[CalendarScanRunDay, ...]

    def __post_init__(self) -> None:
        if type(self) is not CalendarScanRunPage:
            _fail()
        run_id = _strict_uuid(self.run_id)
        if type(self.pass_number) is not int or self.pass_number not in _PASS_NAMES:
            _fail()
        if _strict_uuid(self.pass_id) != calendar_scan_run_pass_id(run_id, self.pass_number):
            _fail()
        if type(self.month) is not int or not 1 <= self.month <= 12:
            _fail()
        if type(self.year) is not int or not 1 <= self.year <= 9999:
            _fail()
        _strict_uuid(self.page_id)
        _strict_uuid(self.catalog_id)
        _strict_text(self.resource_id)
        if self.resource_id != calendar_scan_run_resource_id(self.year, self.month):
            _fail()
        _strict_uuid(self.raw_evidence_id)
        _strict_sha256(self.raw_artifact_sha256)
        _strict_sha256(self.canonical_payload_sha256)
        _strict_uuid(self.artifact_id)
        _strict_uuid(self.capture_id)
        opened_at = _strict_datetime(self.opened_at)
        observed_at = _strict_datetime(self.observed_at)
        available_at = _strict_datetime(self.available_at)
        if not opened_at <= observed_at <= available_at:
            _fail()
        source_nowdate = _strict_date(self.source_nowdate)
        _strict_bool(self.identity_verified)
        _strict_bool(self.replay_verified)
        if type(self.days) is not tuple or not self.days:
            _fail()
        if any(type(day) is not CalendarScanRunDay for day in self.days):
            _fail()
        expected = _month_dates(self.year, self.month)
        if tuple(day.date for day in self.days) != expected:
            _fail()
        if calendar_scan_run_payload_digest(self.days) != self.canonical_payload_sha256:
            _fail()
        # A page may only report the source date at which it was observed.  A
        # later local date would permit a future source watermark to be forged.
        try:
            observed_local_date = observed_at.astimezone(_SHANGHAI_TZ).date()
            available_local_date = available_at.astimezone(_SHANGHAI_TZ).date()
        except Exception:
            _fail()
        if source_nowdate != observed_local_date or source_nowdate > available_local_date:
            _fail()
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "available_at", available_at)


@dataclass(frozen=True, slots=True)
class CalendarScanRunPassReceipt:
    """Immutable receipt for one complete twelve-month pass."""

    run_id: UUID
    pass_number: int
    pass_id: UUID
    opened_at: datetime
    finished_at: datetime
    page_refs: tuple[UUID, ...]
    member_digest: str

    def __post_init__(self) -> None:
        if type(self) is not CalendarScanRunPassReceipt:
            _fail()
        run_id = _strict_uuid(self.run_id)
        if type(self.pass_number) is not int or self.pass_number not in _PASS_NAMES:
            _fail()
        if _strict_uuid(self.pass_id) != calendar_scan_run_pass_id(run_id, self.pass_number):
            _fail()
        opened_at = _strict_datetime(self.opened_at)
        finished_at = _strict_datetime(self.finished_at)
        if not opened_at < finished_at:
            _fail()
        if type(self.page_refs) is not tuple or len(self.page_refs) != 12:
            _fail()
        if any(type(page_id) is not UUID for page_id in self.page_refs):
            _fail()
        if len(set(self.page_refs)) != len(self.page_refs):
            _fail()
        _strict_sha256(self.member_digest)
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(self, "finished_at", finished_at)

    @property
    def page_ids(self) -> tuple[UUID, ...]:
        """Compatibility spelling for the ordered page references."""

        return self.page_refs


@dataclass(frozen=True, slots=True)
class CalendarScanRunManifestReceipt:
    """Immutable final manifest receipt for one scan run."""

    run_id: UUID
    raw_evidence_id: UUID
    artifact_id: UUID
    capture_id: UUID
    raw_artifact_sha256: str
    canonical_member_digest: str
    finalized_at: datetime

    def __post_init__(self) -> None:
        if type(self) is not CalendarScanRunManifestReceipt:
            _fail()
        _strict_uuid(self.run_id)
        raw_evidence_id = _strict_uuid(self.raw_evidence_id)
        artifact_id = _strict_uuid(self.artifact_id)
        capture_id = _strict_uuid(self.capture_id)
        if len({raw_evidence_id, artifact_id, capture_id}) != 3:
            _fail()
        _strict_sha256(self.raw_artifact_sha256)
        _strict_sha256(self.canonical_member_digest)
        finalized_at = _strict_datetime(self.finalized_at)
        object.__setattr__(self, "finalized_at", finalized_at)

    @property
    def raw_sha256(self) -> str:
        """Return the manifest raw-artifact digest."""

        return self.raw_artifact_sha256


def _day_payloads(days: tuple[CalendarScanRunDay, ...]) -> tuple[dict[str, object], ...]:
    return tuple(_day_payload(day) for day in days)


def _page_payload(page: CalendarScanRunPage) -> dict[str, object]:
    if type(page) is not CalendarScanRunPage:
        _fail()
    return {
        "run_id": str(page.run_id),
        "pass_number": page.pass_number,
        "pass_id": str(page.pass_id),
        "month": page.month,
        "year": page.year,
        "page_id": str(page.page_id),
        "catalog_id": str(page.catalog_id),
        "resource_id": page.resource_id,
        "raw_evidence_id": str(page.raw_evidence_id),
        "raw_artifact_sha256": page.raw_artifact_sha256,
        "canonical_payload_sha256": page.canonical_payload_sha256,
        "artifact_id": str(page.artifact_id),
        "capture_id": str(page.capture_id),
        "opened_at": page.opened_at.isoformat(),
        "observed_at": page.observed_at.isoformat(),
        "available_at": page.available_at.isoformat(),
        "source_nowdate": page.source_nowdate.isoformat(),
        "identity_verified": page.identity_verified,
        "replay_verified": page.replay_verified,
        "days": _day_payloads(page.days),
    }


def _catalog_payload(catalog: CalendarScanRunCatalogReceipt) -> dict[str, object]:
    if type(catalog) is not CalendarScanRunCatalogReceipt:
        _fail()
    return {
        "run_id": str(catalog.run_id),
        "year": catalog.year,
        "month": catalog.month,
        "catalog_id": str(catalog.catalog_id),
        "resource_id": catalog.resource_id,
        "raw_evidence_id": str(catalog.raw_evidence_id),
        "raw_artifact_sha256": catalog.raw_artifact_sha256,
        "identity_verified": catalog.identity_verified,
        "replay_verified": catalog.replay_verified,
    }


def _pass_payload(receipt: CalendarScanRunPassReceipt) -> dict[str, object]:
    if type(receipt) is not CalendarScanRunPassReceipt:
        _fail()
    return {
        "run_id": str(receipt.run_id),
        "pass_number": receipt.pass_number,
        "pass_id": str(receipt.pass_id),
        "opened_at": receipt.opened_at.isoformat(),
        "finished_at": receipt.finished_at.isoformat(),
        "page_refs": tuple(str(page_id) for page_id in receipt.page_refs),
        "member_digest": receipt.member_digest,
    }


def _manifest_payload(manifest: CalendarScanRunManifestReceipt) -> dict[str, object]:
    if type(manifest) is not CalendarScanRunManifestReceipt:
        _fail()
    return {
        "run_id": str(manifest.run_id),
        "raw_evidence_id": str(manifest.raw_evidence_id),
        "artifact_id": str(manifest.artifact_id),
        "capture_id": str(manifest.capture_id),
        "raw_artifact_sha256": manifest.raw_artifact_sha256,
        "canonical_member_digest": manifest.canonical_member_digest,
        "finalized_at": manifest.finalized_at.isoformat(),
    }


def _ordered_catalogs(catalogs: tuple[CalendarScanRunCatalogReceipt, ...]) -> bool:
    if type(catalogs) is not tuple or len(catalogs) != 12:
        return False
    if any(type(catalog) is not CalendarScanRunCatalogReceipt for catalog in catalogs):
        return False
    return (
        tuple(catalog.month for catalog in catalogs) == tuple(range(1, 13))
        and len({catalog.year for catalog in catalogs}) == 1
    )


def calendar_scan_run_catalog_digest(
    catalogs: tuple[CalendarScanRunCatalogReceipt, ...],
) -> str:
    """Compute the versioned digest of the twelve ordered month mappings."""

    if not _ordered_catalogs(catalogs):
        _fail()
    payload = {
        "version": _CATALOG_DIGEST_VERSION,
        "catalogs": tuple(_catalog_payload(catalog) for catalog in catalogs),
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def calendar_scan_run_pass_member_digest(
    pages: tuple[CalendarScanRunPage, ...],
) -> str:
    """Compute a pass digest from its twelve ordered page members."""

    if type(pages) is not tuple or len(pages) != 12:
        _fail()
    if any(type(page) is not CalendarScanRunPage for page in pages):
        _fail()
    if tuple(page.month for page in pages) != tuple(range(1, 13)):
        _fail()
    if len({page.pass_number for page in pages}) != 1:
        _fail()
    payload = {
        "version": _PASS_DIGEST_VERSION,
        "run_id": str(pages[0].run_id),
        "pass_number": pages[0].pass_number,
        "pass_id": str(pages[0].pass_id),
        "pages": tuple(_page_payload(page) for page in pages),
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def calendar_scan_run_manifest_member_digest(
    catalogs: tuple[CalendarScanRunCatalogReceipt, ...],
    passes: tuple[CalendarScanRunPassReceipt, ...],
    pages: tuple[CalendarScanRunPage, ...],
) -> str:
    """Compute the manifest digest from every catalog, pass, and page member."""

    if not _ordered_catalogs(catalogs):
        _fail()
    if type(passes) is not tuple or len(passes) != 2:
        _fail()
    if any(type(receipt) is not CalendarScanRunPassReceipt for receipt in passes):
        _fail()
    if type(pages) is not tuple or len(pages) != 24:
        _fail()
    if any(type(page) is not CalendarScanRunPage for page in pages):
        _fail()
    payload = {
        "version": _MANIFEST_DIGEST_VERSION,
        "catalogs": tuple(_catalog_payload(catalog) for catalog in catalogs),
        "passes": tuple(_pass_payload(receipt) for receipt in passes),
        "pages": tuple(_page_payload(page) for page in pages),
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _coverage_candidate(
    *, year: int, source_nowdate: date, cutoff_at: datetime
) -> tuple[ScanRunCoverageLevel, date | None]:
    first = date(year, 1, 1)
    last = date(year, 12, 31)
    local_cutoff_date = cutoff_at.astimezone(_SHANGHAI_TZ).date()
    if source_nowdate <= first or local_cutoff_date <= first:
        return ScanRunCoverageLevel.INDETERMINATE, None
    candidate = min(
        source_nowdate - timedelta(days=1),
        local_cutoff_date - timedelta(days=1),
        last,
    )
    if candidate < first:
        return ScanRunCoverageLevel.INDETERMINATE, None
    if source_nowdate > last and local_cutoff_date > last:
        return ScanRunCoverageLevel.FINAL_YEAR, last
    return ScanRunCoverageLevel.CONFIRMED_HORIZON, candidate


@dataclass(frozen=True, slots=True)
class ScanRunCoverage:
    """Derived horizon; callers cannot declare it independently."""

    level: ScanRunCoverageLevel
    confirmed_through: date | None
    source_nowdate: date
    publication_cutoff: datetime

    def __post_init__(self) -> None:
        if type(self) is not ScanRunCoverage:
            _fail()
        if type(self.level) is not ScanRunCoverageLevel:
            _fail()
        if self.confirmed_through is not None:
            _strict_date(self.confirmed_through)
        _strict_date(self.source_nowdate)
        cutoff = _strict_datetime(self.publication_cutoff)
        if self.level is ScanRunCoverageLevel.INDETERMINATE:
            if self.confirmed_through is not None:
                _fail()
        elif self.confirmed_through is None:
            _fail()
        object.__setattr__(self, "publication_cutoff", cutoff)


CalendarScanRunCoverage = ScanRunCoverage


@dataclass(frozen=True, slots=True)
class CalendarScanRunReceipt:
    """Complete structural proof for one SZSE direct-daily dual-pass run.

    This receipt is a typed boundary for a trusted provider adapter.  It does
    not independently validate external raw bytes; an adapter must first
    retain, identify, and replay those bytes before constructing the receipt.
    """

    run_id: UUID
    authority: str
    exchange: str
    year: int
    parser_version: str
    contract_version: str
    policy_id: str
    compiled_catalog_sha256: str
    opened_at: datetime
    cutoff_at: datetime
    catalog_receipts: tuple[CalendarScanRunCatalogReceipt, ...]
    pass_receipts: tuple[CalendarScanRunPassReceipt, ...]
    pages: tuple[CalendarScanRunPage, ...]
    manifest: CalendarScanRunManifestReceipt
    proof_digest: str = ""
    _coverage: ScanRunCoverage = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self) is not CalendarScanRunReceipt:
            _fail()
        run_id = _strict_uuid(self.run_id)
        if type(self.authority) is not str or type(self.exchange) is not str:
            _fail()
        if self.authority != "SZSE" or self.exchange != "SZ":
            _fail()
        if type(self.year) is not int or not 1 <= self.year <= 9999:
            _fail()
        _strict_text(self.parser_version)
        _strict_text(self.contract_version)
        _strict_text(self.policy_id)
        if self.policy_id != SZSE_DIRECT_DAILY_POLICY_ID:
            _fail()
        _strict_sha256(self.compiled_catalog_sha256)
        opened_at = _strict_datetime(self.opened_at)
        cutoff_at = _strict_datetime(self.cutoff_at)
        if not opened_at <= cutoff_at:
            _fail()
        if not _ordered_catalogs(self.catalog_receipts):
            _fail()
        catalogs = self.catalog_receipts
        if any(
            catalog.run_id != run_id
            or catalog.year != self.year
            or not catalog.identity_verified
            or not catalog.replay_verified
            for catalog in catalogs
        ):
            _fail()
        catalog_ids = tuple(catalog.catalog_id for catalog in catalogs)
        catalog_raw_ids = tuple(catalog.raw_evidence_id for catalog in catalogs)
        if len(set(catalog_ids)) != 12 or len(set(catalog_raw_ids)) != 12:
            _fail()
        if len(set((*catalog_ids, *catalog_raw_ids))) != 24:
            _fail()
        if self.compiled_catalog_sha256 != calendar_scan_run_catalog_digest(catalogs):
            _fail()
        catalog_by_month = {(catalog.year, catalog.month): catalog for catalog in catalogs}

        if type(self.pages) is not tuple or len(self.pages) != 24:
            _fail()
        if any(type(page) is not CalendarScanRunPage for page in self.pages):
            _fail()
        pages = self.pages
        expected_order = tuple(
            (pass_number, month) for pass_number in _PASS_NAMES for month in range(1, 13)
        )
        if tuple((page.pass_number, page.month) for page in pages) != expected_order:
            _fail()
        if any(
            page.run_id != run_id
            or page.year != self.year
            or not page.identity_verified
            or not page.replay_verified
            or page.opened_at != opened_at
            or page.observed_at < opened_at
            or page.available_at > cutoff_at
            or (page.year, page.month) not in catalog_by_month
            or page.catalog_id != catalog_by_month[(page.year, page.month)].catalog_id
            or page.resource_id != catalog_by_month[(page.year, page.month)].resource_id
            for page in pages
        ):
            _fail()

        page_ids = tuple(page.page_id for page in pages)
        page_raw_ids = tuple(page.raw_evidence_id for page in pages)
        page_artifact_ids = tuple(page.artifact_id for page in pages)
        page_capture_ids = tuple(page.capture_id for page in pages)
        page_identity_ids = (*page_ids, *page_raw_ids, *page_artifact_ids, *page_capture_ids)
        if len(set(page_identity_ids)) != len(page_identity_ids):
            _fail()
        catalog_identity_ids = (*catalog_ids, *catalog_raw_ids)
        if set(catalog_identity_ids).intersection(page_identity_ids):
            _fail()

        if type(self.pass_receipts) is not tuple or len(self.pass_receipts) != 2:
            _fail()
        if any(type(receipt) is not CalendarScanRunPassReceipt for receipt in self.pass_receipts):
            _fail()
        passes = self.pass_receipts
        if tuple(receipt.pass_number for receipt in passes) != _PASS_NAMES:
            _fail()
        if any(
            receipt.run_id != run_id
            or receipt.pass_id != calendar_scan_run_pass_id(run_id, receipt.pass_number)
            for receipt in passes
        ):
            _fail()
        if passes[0].opened_at != opened_at:
            _fail()
        if not passes[0].finished_at < passes[1].opened_at:
            _fail()
        if passes[1].finished_at > cutoff_at:
            _fail()
        expected_page_refs = (page_ids[:12], page_ids[12:])
        if tuple(receipt.page_refs for receipt in passes) != expected_page_refs:
            _fail()
        for receipt, pass_pages in zip(passes, (pages[:12], pages[12:]), strict=True):
            if receipt.member_digest != calendar_scan_run_pass_member_digest(pass_pages):
                _fail()
            if any(
                page.observed_at < receipt.opened_at
                or page.available_at > receipt.finished_at
                or page.available_at < page.observed_at
                for page in pass_pages
            ):
                _fail()

        manifest = self.manifest
        if type(manifest) is not CalendarScanRunManifestReceipt:
            _fail()
        if manifest.run_id != run_id or manifest.finalized_at != cutoff_at:
            _fail()
        manifest_ids = (manifest.raw_evidence_id, manifest.artifact_id, manifest.capture_id)
        if len(set(manifest_ids)) != 3:
            _fail()
        if set(manifest_ids).intersection((*catalog_identity_ids, *page_identity_ids)):
            _fail()
        expected_manifest_digest = calendar_scan_run_manifest_member_digest(catalogs, passes, pages)
        if manifest.canonical_member_digest != expected_manifest_digest:
            _fail()

        source_nowdates = {page.source_nowdate for page in pages}
        if len(source_nowdates) != 1:
            _fail()
        source_nowdate = next(iter(source_nowdates))
        for page in pages:
            try:
                observed_local_date = page.observed_at.astimezone(_SHANGHAI_TZ).date()
                available_local_date = page.available_at.astimezone(_SHANGHAI_TZ).date()
            except Exception:
                _fail()
            if (
                page.source_nowdate != observed_local_date
                or page.source_nowdate > available_local_date
            ):
                _fail()
        for month in range(1, 13):
            first = pages[month - 1]
            second = pages[12 + month - 1]
            if (
                first.days != second.days
                or first.canonical_payload_sha256 != second.canonical_payload_sha256
                or first.source_nowdate != second.source_nowdate
            ):
                _fail()

        coverage_level, confirmed_through = _coverage_candidate(
            year=self.year, source_nowdate=source_nowdate, cutoff_at=cutoff_at
        )
        coverage = ScanRunCoverage(
            level=coverage_level,
            confirmed_through=confirmed_through,
            source_nowdate=source_nowdate,
            publication_cutoff=cutoff_at,
        )
        proof_payload = {
            "version": _PROOF_DIGEST_VERSION,
            "run_id": str(run_id),
            "authority": self.authority,
            "exchange": self.exchange,
            "year": self.year,
            "parser_version": self.parser_version,
            "contract_version": self.contract_version,
            "policy_id": self.policy_id,
            "compiled_catalog_sha256": self.compiled_catalog_sha256,
            "opened_at": opened_at.isoformat(),
            "cutoff_at": cutoff_at.isoformat(),
            "catalog_receipts": tuple(_catalog_payload(catalog) for catalog in catalogs),
            "pass_receipts": tuple(_pass_payload(receipt) for receipt in passes),
            "pages": tuple(_page_payload(page) for page in pages),
            "manifest": _manifest_payload(manifest),
            "coverage": {
                "level": coverage.level.value,
                "confirmed_through": (
                    None
                    if coverage.confirmed_through is None
                    else coverage.confirmed_through.isoformat()
                ),
                "source_nowdate": coverage.source_nowdate.isoformat(),
                "publication_cutoff": coverage.publication_cutoff.isoformat(),
            },
        }
        computed_digest = hashlib.sha256(_canonical_json(proof_payload)).hexdigest()
        if self.proof_digest:
            _strict_sha256(self.proof_digest)
            if self.proof_digest != computed_digest:
                _fail()
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(self, "cutoff_at", cutoff_at)
        object.__setattr__(self, "proof_digest", computed_digest)
        object.__setattr__(self, "_coverage", coverage)

    @property
    def coverage(self) -> ScanRunCoverage:
        """Return coverage derived from the validated pages and manifest cutoff."""

        return self._coverage

    @property
    def final_year_eligible(self) -> bool:
        return self.coverage.level is ScanRunCoverageLevel.FINAL_YEAR

    @property
    def daily_days(self) -> tuple[CalendarScanRunDay, ...]:
        return tuple(day for page in self.pages[:12] for day in page.days)

    @property
    def primary_provenance(self) -> tuple[UUID, UUID, str]:
        """Return provenance anchored to the final manifest, never a page choice."""

        return (
            self.manifest.artifact_id,
            self.manifest.capture_id,
            self.manifest.raw_artifact_sha256,
        )

    @property
    def manifest_member_digest(self) -> str:
        """Return the canonical membership digest bound by the manifest."""

        return self.manifest.canonical_member_digest

    @property
    def page_count(self) -> int:
        return len(self.pages)


__all__ = [
    "SZSE_DIRECT_DAILY_POLICY_ID",
    "CalendarScanRunCatalogReceipt",
    "CalendarScanRunDay",
    "CalendarScanRunError",
    "CalendarScanRunManifestReceipt",
    "CalendarScanRunPage",
    "CalendarScanRunPassReceipt",
    "CalendarScanRunReceipt",
    "CalendarScanRunCoverage",
    "ScanRunCoverage",
    "ScanRunCoverageLevel",
    "ScanRunDay",
    "calendar_scan_run_catalog_digest",
    "calendar_scan_run_manifest_member_digest",
    "calendar_scan_run_pass_id",
    "calendar_scan_run_pass_member_digest",
    "calendar_scan_run_payload_digest",
    "calendar_scan_run_resource_id",
]
