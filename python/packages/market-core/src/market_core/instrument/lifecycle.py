"""Versioned security-master lifecycle and availability domain.

The generated ``Instrument`` contract predates raw provider evidence and
combines listing, trading and risk concepts in one status enum.  This module
is intentionally independent: a provider can report a listed security that
is suspended, and ``ST`` remains a risk tag rather than a lifecycle state.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Self, cast

from .code_parser import is_unified_code_for_exchange

LIFECYCLE_CONTRACT_VERSION = "instrument-lifecycle-v1"
_SAFE_SOURCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_TAG_RE = re.compile(r"^[A-Z][A-Z0-9_:-]{0,31}$")
_EXCHANGES = frozenset({"SH", "SZ", "BJ"})
_BOARDS = frozenset({"MAIN", "CHINEXT", "STAR", "BSE"})
_TYPES = frozenset({"STOCK", "ETF", "LOF", "FUND"})


class ListingLifecycle(StrEnum):
    """PIT listing lifecycle, independent from day-level availability."""

    PRE_LISTING = "PRE_LISTING"
    LISTED = "LISTED"
    DELISTED = "DELISTED"
    UNKNOWN = "UNKNOWN"


class TradingAvailability(StrEnum):
    """Provider-reported trading availability for a listed instrument."""

    ACTIVE = "ACTIVE"
    SUSPENDED_FULL_DAY = "SUSPENDED_FULL_DAY"
    SUSPENDED_PARTIAL = "SUSPENDED_PARTIAL"
    UNKNOWN = "UNKNOWN"


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _date_value(value: object, field_name: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a date")
    return value


def _safe_text(value: object, field_name: str, *, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    normalized = value.strip()
    if len(normalized) > max_length or any(ord(char) < 32 for char in normalized):
        raise ValueError(f"{field_name} is invalid")
    return normalized


@dataclass(frozen=True, slots=True)
class InstrumentMasterRecord:
    """One immutable provider observation of a supported security."""

    unified_code: str
    code: str
    exchange: str
    board: str
    security_type: str
    name: str
    listing_lifecycle: ListingLifecycle
    trading_availability: TradingAvailability
    risk_tags: tuple[str, ...]
    list_date: date | None
    delist_date: date | None
    observed_at: datetime
    available_at: datetime
    source: str
    source_revision: str | None
    evidence_ref: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"\d{6}", self.code) is None:
            raise ValueError("code must be six digits")
        if self.exchange not in _EXCHANGES:
            raise ValueError("exchange is unsupported")
        expected = f"{self.code}.{self.exchange}"
        if self.unified_code != expected or not is_unified_code_for_exchange(
            self.unified_code,
            self.exchange,  # type: ignore[arg-type]
        ):
            raise ValueError("unified_code is not the canonical code.exchange identity")
        if self.board not in _BOARDS:
            raise ValueError("board is unsupported")
        if self.security_type not in _TYPES:
            raise ValueError("security_type is unsupported")
        object.__setattr__(self, "name", _safe_text(self.name, "name", max_length=256))
        tags = tuple(self.risk_tags)
        if any(_SAFE_TAG_RE.fullmatch(tag) is None for tag in tags):
            raise ValueError("risk_tags contain an invalid tag")
        if len(set(tags)) != len(tags):
            raise ValueError("risk_tags contain duplicates")
        object.__setattr__(self, "risk_tags", tuple(sorted(tags)))
        list_date = _date_value(self.list_date, "list_date")
        delist_date = _date_value(self.delist_date, "delist_date")
        if list_date is not None and delist_date is not None and delist_date < list_date:
            raise ValueError("delist_date cannot precede list_date")
        object.__setattr__(self, "list_date", list_date)
        object.__setattr__(self, "delist_date", delist_date)
        observed_at = _aware(self.observed_at, "observed_at")
        available_at = _aware(self.available_at, "available_at")
        if available_at < observed_at:
            raise ValueError("available_at cannot precede observed_at")
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "available_at", available_at)
        if _SAFE_SOURCE_RE.fullmatch(self.source) is None:
            raise ValueError("source is invalid")
        if (
            self.source_revision is not None
            and _SAFE_SOURCE_RE.fullmatch(self.source_revision) is None
        ):
            raise ValueError("source_revision is invalid")
        if _SAFE_SOURCE_RE.fullmatch(self.evidence_ref) is None:
            raise ValueError("evidence_ref is invalid")

    @property
    def instrument_id(self) -> str:
        """Stable identity alias; names never participate in identity."""

        return self.unified_code

    def to_dict(self) -> dict[str, object]:
        """Return a canonical, JSON-compatible representation."""

        return {
            "contract_version": LIFECYCLE_CONTRACT_VERSION,
            "unified_code": self.unified_code,
            "code": self.code,
            "exchange": self.exchange,
            "board": self.board,
            "security_type": self.security_type,
            "name": self.name,
            "listing_lifecycle": self.listing_lifecycle.value,
            "trading_availability": self.trading_availability.value,
            "risk_tags": list(self.risk_tags),
            "list_date": self.list_date.isoformat() if self.list_date is not None else None,
            "delist_date": self.delist_date.isoformat() if self.delist_date is not None else None,
            "observed_at": self.observed_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "source": self.source,
            "source_revision": self.source_revision,
            "evidence_ref": self.evidence_ref,
        }

    def fingerprint(self) -> str:
        """Hash stable business payload fields for version reuse."""

        payload = self.to_dict()
        for provenance_field in (
            "observed_at",
            "available_at",
            "source_revision",
            "evidence_ref",
        ):
            del payload[provenance_field]
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        """Validate a replayed canonical representation."""

        if value.get("contract_version") != LIFECYCLE_CONTRACT_VERSION:
            raise ValueError("unsupported instrument lifecycle contract version")

        def _parse_date(field_name: str) -> date | None:
            raw = value.get(field_name)
            if raw is None:
                return None
            if not isinstance(raw, str):
                raise ValueError(f"{field_name} must be an ISO date")
            try:
                return date.fromisoformat(raw)
            except ValueError as error:
                raise ValueError(f"{field_name} must be an ISO date") from error

        def _parse_datetime(field_name: str) -> datetime:
            raw = value.get(field_name)
            if not isinstance(raw, str):
                raise ValueError(f"{field_name} must be an ISO timestamp")
            try:
                return datetime.fromisoformat(raw)
            except ValueError as error:
                raise ValueError(f"{field_name} must be an ISO timestamp") from error

        raw_tags = value.get("risk_tags")
        if not isinstance(raw_tags, list):
            raise ValueError("risk_tags must be a list of strings")
        raw_tag_values = cast(list[object], raw_tags)
        tags_list: list[str] = []
        for tag in raw_tag_values:
            if not isinstance(tag, str):
                raise ValueError("risk_tags must be a list of strings")
            tags_list.append(tag)
        tags = tuple(tags_list)
        try:
            lifecycle = ListingLifecycle(str(value["listing_lifecycle"]))
            availability = TradingAvailability(str(value["trading_availability"]))
        except (KeyError, ValueError) as error:
            raise ValueError("lifecycle or availability is invalid") from error
        return cls(
            unified_code=str(value["unified_code"]),
            code=str(value["code"]),
            exchange=str(value["exchange"]),
            board=str(value["board"]),
            security_type=str(value["security_type"]),
            name=str(value["name"]),
            listing_lifecycle=lifecycle,
            trading_availability=availability,
            risk_tags=tags,
            list_date=_parse_date("list_date"),
            delist_date=_parse_date("delist_date"),
            observed_at=_parse_datetime("observed_at"),
            available_at=_parse_datetime("available_at"),
            source=str(value["source"]),
            source_revision=(
                None if value.get("source_revision") is None else str(value["source_revision"])
            ),
            evidence_ref=str(value["evidence_ref"]),
        )


__all__ = [
    "InstrumentMasterRecord",
    "ListingLifecycle",
    "LIFECYCLE_CONTRACT_VERSION",
    "TradingAvailability",
]
