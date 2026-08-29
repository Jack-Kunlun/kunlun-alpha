"""Strict catalog parser and deterministic revision planner for local terminal data."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from zoneinfo import ZoneInfo

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_CATALOG_VERSION = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[1-9][0-9]*$")
_INSTRUMENT = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")


class LocalReferenceCatalogError(ValueError):
    """The checked-in local reference catalog is invalid or ambiguous."""


@dataclass(frozen=True, slots=True)
class SectorCatalogEntry:
    sector_id: str
    name: str
    kind: Literal["INDUSTRY", "CONCEPT", "THEME"]
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InstrumentCatalogEntry:
    instrument_id: str
    name: str
    board: Literal["MAIN", "CHINEXT", "STAR", "BSE"]
    instrument_type: Literal["STOCK"]
    sector_id: str


@dataclass(frozen=True, slots=True)
class LocalReferenceCatalog:
    catalog_version: str
    source: str
    source_version: str
    evidence_id: str
    effective_from: datetime
    available_time: datetime
    sectors: tuple[SectorCatalogEntry, ...]
    instruments: tuple[InstrumentCatalogEntry, ...]


@dataclass(frozen=True, slots=True)
class InstrumentReferenceRevision:
    revision_id: str
    instrument_id: str
    payload: dict[str, JsonValue]
    payload_fingerprint: str


@dataclass(frozen=True, slots=True)
class SectorReferenceRevision:
    revision_id: str
    sector_id: str
    payload: dict[str, JsonValue]
    payload_fingerprint: str


@dataclass(frozen=True, slots=True)
class MembershipReferenceRevision:
    revision_id: str
    instrument_id: str
    sector_id: str
    payload: dict[str, JsonValue]
    payload_fingerprint: str


type ReferenceRevision = (
    InstrumentReferenceRevision | SectorReferenceRevision | MembershipReferenceRevision
)


@dataclass(frozen=True, slots=True)
class LocalReferencePlan:
    catalog: LocalReferenceCatalog
    instrument_revisions: tuple[InstrumentReferenceRevision, ...]
    sector_revisions: tuple[SectorReferenceRevision, ...]
    membership_revisions: tuple[MembershipReferenceRevision, ...]

    @property
    def all_revisions(self) -> tuple[ReferenceRevision, ...]:
        return (*self.instrument_revisions, *self.sector_revisions, *self.membership_revisions)


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise LocalReferenceCatalogError(f"{field} must be an object")
    raw = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw):
        raise LocalReferenceCatalogError(f"{field} must be an object")
    return cast(dict[str, object], raw)


def _exact_keys(value: dict[str, object], expected: frozenset[str], field: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise LocalReferenceCatalogError(
            f"{field} fields differ: missing={sorted(expected - actual)} "
            f"extra={sorted(actual - expected)}"
        )


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise LocalReferenceCatalogError(f"{field} must be non-empty canonical text")
    return value


def _instant(value: object, field: str) -> datetime:
    raw = _text(value, field)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise LocalReferenceCatalogError(f"{field} must be RFC3339") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LocalReferenceCatalogError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _string_array(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise LocalReferenceCatalogError(f"{field} must be an array")
    items = tuple(_text(item, field) for item in cast(list[object], value))
    if len(items) != len(set(items)):
        raise LocalReferenceCatalogError(f"{field} must not contain duplicates")
    return items


def _sector(value: object, ordinal: int) -> SectorCatalogEntry:
    raw = _object(value, f"sectors[{ordinal}]")
    _exact_keys(raw, frozenset({"sectorId", "name", "kind", "aliases"}), f"sectors[{ordinal}]")
    sector_id = _text(raw["sectorId"], f"sectors[{ordinal}].sectorId")
    if _SAFE_ID.fullmatch(sector_id) is None:
        raise LocalReferenceCatalogError("sectorId must use lowercase letters, digits and hyphens")
    kind = _text(raw["kind"], f"sectors[{ordinal}].kind")
    if kind not in {"INDUSTRY", "CONCEPT", "THEME"}:
        raise LocalReferenceCatalogError("sector kind is unsupported")
    return SectorCatalogEntry(
        sector_id=sector_id,
        name=_text(raw["name"], f"sectors[{ordinal}].name"),
        kind=cast(Literal["INDUSTRY", "CONCEPT", "THEME"], kind),
        aliases=_string_array(raw["aliases"], f"sectors[{ordinal}].aliases"),
    )


def _expected_board(instrument_id: str) -> str:
    code, exchange = instrument_id.split(".")
    if exchange == "BJ":
        return "BSE"
    if code.startswith(("300", "301")):
        return "CHINEXT"
    if code.startswith(("688", "689")):
        return "STAR"
    return "MAIN"


def _instrument(value: object, ordinal: int) -> InstrumentCatalogEntry:
    raw = _object(value, f"instruments[{ordinal}]")
    _exact_keys(
        raw,
        frozenset({"instrumentId", "name", "board", "type", "sectorId"}),
        f"instruments[{ordinal}]",
    )
    instrument_id = _text(raw["instrumentId"], f"instruments[{ordinal}].instrumentId")
    if _INSTRUMENT.fullmatch(instrument_id) is None:
        raise LocalReferenceCatalogError("instrumentId must use canonical suffix form")
    instrument_type = _text(raw["type"], f"instruments[{ordinal}].type")
    if instrument_type != "STOCK":
        raise LocalReferenceCatalogError("local terminal catalog accepts STOCK entries only")
    board = _text(raw["board"], f"instruments[{ordinal}].board")
    if board != _expected_board(instrument_id):
        raise LocalReferenceCatalogError(f"instrument {instrument_id} has an inconsistent board")
    return InstrumentCatalogEntry(
        instrument_id=instrument_id,
        name=_text(raw["name"], f"instruments[{ordinal}].name"),
        board=cast(Literal["MAIN", "CHINEXT", "STAR", "BSE"], board),
        instrument_type="STOCK",
        sector_id=_text(raw["sectorId"], f"instruments[{ordinal}].sectorId"),
    )


def load_local_reference_catalog(path: Path) -> LocalReferenceCatalog:
    """Load a strict, local-only stock reference catalog from a checked-in JSON file."""
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LocalReferenceCatalogError(
            f"local reference catalog cannot be read: {error}"
        ) from error
    raw = _object(value, "catalog")
    _exact_keys(
        raw,
        frozenset(
            {
                "schemaVersion",
                "catalogVersion",
                "source",
                "sourceVersion",
                "evidenceId",
                "effectiveFrom",
                "availableTime",
                "sectors",
                "instruments",
            }
        ),
        "catalog",
    )
    if raw["schemaVersion"] != "local-terminal-instrument-catalog-v1":
        raise LocalReferenceCatalogError("unsupported local reference catalog schemaVersion")
    catalog_version = _text(raw["catalogVersion"], "catalogVersion")
    if _CATALOG_VERSION.fullmatch(catalog_version) is None:
        raise LocalReferenceCatalogError("catalogVersion must use YYYY.MM.DD.REVISION")
    raw_sectors = raw["sectors"]
    raw_instruments = raw["instruments"]
    if not isinstance(raw_sectors, list) or not raw_sectors:
        raise LocalReferenceCatalogError("sectors must be a non-empty array")
    if not isinstance(raw_instruments, list) or not raw_instruments:
        raise LocalReferenceCatalogError("instruments must be a non-empty array")
    sectors = tuple(
        _sector(item, index) for index, item in enumerate(cast(list[object], raw_sectors))
    )
    instruments = tuple(
        _instrument(item, index) for index, item in enumerate(cast(list[object], raw_instruments))
    )
    sector_ids = [item.sector_id for item in sectors]
    instrument_ids = [item.instrument_id for item in instruments]
    if len(sector_ids) != len(set(sector_ids)):
        raise LocalReferenceCatalogError("duplicate sectorId")
    if len(instrument_ids) != len(set(instrument_ids)):
        raise LocalReferenceCatalogError("duplicate instrumentId")
    if sector_ids != sorted(sector_ids) or instrument_ids != sorted(instrument_ids):
        raise LocalReferenceCatalogError("catalog entries must be sorted by stable identifier")
    unknown_sector_ids = sorted({item.sector_id for item in instruments} - set(sector_ids))
    if unknown_sector_ids:
        raise LocalReferenceCatalogError(
            f"instrument references unknown sectorIds: {unknown_sector_ids}"
        )
    effective_from = _instant(raw["effectiveFrom"], "effectiveFrom")
    available_time = _instant(raw["availableTime"], "availableTime")
    if available_time < effective_from:
        raise LocalReferenceCatalogError("availableTime must not precede effectiveFrom")
    return LocalReferenceCatalog(
        catalog_version=catalog_version,
        source=_text(raw["source"], "source"),
        source_version=_text(raw["sourceVersion"], "sourceVersion"),
        evidence_id=_text(raw["evidenceId"], "evidenceId"),
        effective_from=effective_from,
        available_time=available_time,
        sectors=sectors,
        instruments=instruments,
    )


def _canonical_json(payload: dict[str, JsonValue]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _fingerprint(payload: dict[str, JsonValue]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _revision_id(kind: str, identity: str, catalog: LocalReferenceCatalog) -> str:
    material = f"{kind}:{identity}:{catalog.catalog_version}"
    return f"local-{kind}-{hashlib.sha256(material.encode()).hexdigest()[:32]}"


def build_local_reference_plan(catalog: LocalReferenceCatalog) -> LocalReferencePlan:
    """Create immutable revision payloads without performing I/O."""
    valid_from = catalog.effective_from.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    available_time = catalog.available_time.isoformat().replace("+00:00", "Z")
    instrument_revisions: list[InstrumentReferenceRevision] = []
    for item in catalog.instruments:
        code, exchange = item.instrument_id.split(".")
        payload: dict[str, JsonValue] = {
            "unifiedCode": item.instrument_id,
            "code": code,
            "exchange": exchange,
            "board": item.board,
            "type": item.instrument_type,
            "name": item.name,
            "tradingStatus": "LISTED",
            "currency": "CNY",
        }
        instrument_revisions.append(
            InstrumentReferenceRevision(
                revision_id=_revision_id("instrument", item.instrument_id, catalog),
                instrument_id=item.instrument_id,
                payload=payload,
                payload_fingerprint=_fingerprint(payload),
            )
        )

    sector_revisions: list[SectorReferenceRevision] = []
    for item in catalog.sectors:
        payload = {
            "sectorId": item.sector_id,
            "name": item.name,
            "parentId": None,
            "kind": item.kind,
            "source": catalog.source,
            "sourceVersion": catalog.source_version,
            "availableTime": available_time,
            "evidenceId": catalog.evidence_id,
            "validFrom": valid_from,
            "validTo": None,
            "aliases": list(item.aliases),
        }
        sector_revisions.append(
            SectorReferenceRevision(
                revision_id=_revision_id("sector", item.sector_id, catalog),
                sector_id=item.sector_id,
                payload=payload,
                payload_fingerprint=_fingerprint(payload),
            )
        )

    membership_revisions: list[MembershipReferenceRevision] = []
    for item in catalog.instruments:
        payload = {
            "unifiedCode": item.instrument_id,
            "sectorId": item.sector_id,
            "validFrom": valid_from,
            "validTo": None,
            "source": catalog.source,
            "sourceVersion": catalog.source_version,
            "availableTime": available_time,
            "evidenceId": catalog.evidence_id,
        }
        membership_revisions.append(
            MembershipReferenceRevision(
                revision_id=_revision_id(
                    "membership", f"{item.instrument_id}:{item.sector_id}", catalog
                ),
                instrument_id=item.instrument_id,
                sector_id=item.sector_id,
                payload=payload,
                payload_fingerprint=_fingerprint(payload),
            )
        )

    return LocalReferencePlan(
        catalog=catalog,
        instrument_revisions=tuple(instrument_revisions),
        sector_revisions=tuple(sector_revisions),
        membership_revisions=tuple(membership_revisions),
    )
