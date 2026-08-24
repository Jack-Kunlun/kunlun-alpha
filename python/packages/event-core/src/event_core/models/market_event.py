"""Immutable, evidence-backed MarketEvent domain model (P3-N05)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

MARKET_EVENT_SCHEMA_VERSION = "market-event-v1"
EVENT_ID_ALGORITHM_VERSION = "market-event-id-v1"

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_INSTRUMENT_PATTERN = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$")


class MarketEventType(StrEnum):
    CORPORATE = "CORPORATE"
    EARNINGS = "EARNINGS"
    FINANCING = "FINANCING"
    REGULATORY = "REGULATORY"
    POLICY = "POLICY"
    MACRO = "MACRO"
    INDUSTRY = "INDUSTRY"
    MARKET = "MARKET"
    RISK = "RISK"
    OTHER = "OTHER"


class ProducerType(StrEnum):
    MODEL = "MODEL"
    RULE = "RULE"


def _require_non_empty(value: object, name: str, *, max_length: int | None = None) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-empty str")
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"{name} must be at most {max_length} characters")
    return value


def _require_aware_utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _require_sha256(value: object, name: str) -> str:
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a 64-hex lowercase SHA-256")
    return value


def _require_bps(value: object, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an int in basis points")
    if not 0 <= value <= 10000:
        raise ValueError(f"{name} must be within [0, 10000]")
    return value


@dataclass(frozen=True)
class EventEvidence:
    """Exact RawContent evidence span supporting the event conclusion."""

    evidence_id: str
    content_record_id: str
    content_version_id: str
    source_id: str
    source_version: str
    available_time: datetime
    start_offset: int
    end_offset: int
    excerpt: str

    def __post_init__(self) -> None:
        _require_non_empty(self.evidence_id, "evidence_id")
        _require_non_empty(self.content_record_id, "content_record_id")
        _require_sha256(self.content_version_id, "content_version_id")
        _require_non_empty(self.source_id, "source_id")
        _require_non_empty(self.source_version, "source_version")
        object.__setattr__(
            self,
            "available_time",
            _require_aware_utc(self.available_time, "evidence.available_time"),
        )
        if type(self.start_offset) is not int or type(self.end_offset) is not int:
            raise TypeError("evidence offsets must be ints")
        if self.start_offset < 0 or self.end_offset <= self.start_offset:
            raise ValueError("evidence offsets must satisfy 0 <= start_offset < end_offset")
        _require_non_empty(self.excerpt, "excerpt", max_length=2000)
        if len(self.excerpt) != self.end_offset - self.start_offset:
            raise ValueError("excerpt length must equal the evidence span length")

    @property
    def identity(self) -> tuple[str, str, int, int]:
        return (
            self.evidence_id,
            self.content_version_id,
            self.start_offset,
            self.end_offset,
        )


@dataclass(frozen=True)
class ModelProvenance:
    """Registered model/rule identity used to produce an event."""

    producer_type: ProducerType
    provider: str
    model_id: str
    model_version: str
    prompt_version: str
    output_schema_version: str
    configuration_fingerprint: str
    extraction_run_id: str
    processing_time: datetime

    def __post_init__(self) -> None:
        if type(self.producer_type) is not ProducerType:
            raise TypeError("producer_type must be a ProducerType")
        _require_non_empty(self.provider, "provider")
        _require_non_empty(self.model_id, "model_id")
        _require_non_empty(self.model_version, "model_version")
        _require_non_empty(self.prompt_version, "prompt_version")
        if self.output_schema_version != MARKET_EVENT_SCHEMA_VERSION:
            raise ValueError(f"output_schema_version must be {MARKET_EVENT_SCHEMA_VERSION!r}")
        _require_sha256(self.configuration_fingerprint, "configuration_fingerprint")
        _require_non_empty(self.extraction_run_id, "extraction_run_id")
        object.__setattr__(
            self,
            "processing_time",
            _require_aware_utc(self.processing_time, "processing_time"),
        )


def _evidence_sort_key(item: EventEvidence) -> tuple[str, str, int, int, str, str]:
    return (
        item.content_version_id,
        item.evidence_id,
        item.start_offset,
        item.end_offset,
        item.source_id,
        item.source_version,
    )


@dataclass(frozen=True)
class MarketEvent:
    """One immutable event conclusion backed by source evidence and versions."""

    event_type: MarketEventType
    headline: str
    summary: str
    occur_time: datetime
    publish_time: datetime
    available_time: datetime
    instrument_ids: tuple[str, ...]
    sector_ids: tuple[str, ...]
    evidence: tuple[EventEvidence, ...]
    model_provenance: ModelProvenance
    confidence_bps: int
    schema_version: str = MARKET_EVENT_SCHEMA_VERSION
    event_id: str = field(init=False, default="")

    def __post_init__(self) -> None:
        if self.schema_version != MARKET_EVENT_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {MARKET_EVENT_SCHEMA_VERSION!r}")
        if type(self.event_type) is not MarketEventType:
            raise TypeError("event_type must be a MarketEventType")
        _require_non_empty(self.headline, "headline", max_length=500)
        _require_non_empty(self.summary, "summary", max_length=5000)
        occur = _require_aware_utc(self.occur_time, "occur_time")
        publish = _require_aware_utc(self.publish_time, "publish_time")
        available = _require_aware_utc(self.available_time, "available_time")
        object.__setattr__(self, "occur_time", occur)
        object.__setattr__(self, "publish_time", publish)
        object.__setattr__(self, "available_time", available)
        if publish > available:
            raise ValueError("publish_time must be <= available_time")

        if type(self.instrument_ids) is not tuple:
            raise TypeError("instrument_ids must be a tuple")
        if len(set(self.instrument_ids)) != len(self.instrument_ids):
            raise ValueError("instrument_ids must not contain duplicates")
        for instrument_id in self.instrument_ids:
            if (
                type(instrument_id) is not str
                or _INSTRUMENT_PATTERN.fullmatch(instrument_id) is None
            ):
                raise ValueError(f"invalid canonical instrument id: {instrument_id!r}")
        object.__setattr__(self, "instrument_ids", tuple(sorted(self.instrument_ids)))

        if type(self.sector_ids) is not tuple:
            raise TypeError("sector_ids must be a tuple")
        if len(set(self.sector_ids)) != len(self.sector_ids):
            raise ValueError("sector_ids must not contain duplicates")
        for sector_id in self.sector_ids:
            _require_non_empty(sector_id, "sector_id")
        object.__setattr__(self, "sector_ids", tuple(sorted(self.sector_ids)))

        if type(self.evidence) is not tuple or not self.evidence:
            raise ValueError("evidence must be a non-empty tuple")
        identities: set[tuple[str, str, int, int]] = set()
        for item in self.evidence:
            if type(item) is not EventEvidence:
                raise TypeError("evidence must contain EventEvidence instances")
            if item.identity in identities:
                raise ValueError(f"duplicate evidence reference: {item.identity!r}")
            identities.add(item.identity)
            if item.available_time > available:
                raise ValueError("evidence.available_time must be <= event.available_time")
        object.__setattr__(self, "evidence", tuple(sorted(self.evidence, key=_evidence_sort_key)))

        if type(self.model_provenance) is not ModelProvenance:
            raise TypeError("model_provenance must be a ModelProvenance")
        if self.model_provenance.processing_time > available:
            raise ValueError("processing_time must be <= event.available_time")
        _require_bps(self.confidence_bps, "confidence_bps")
        object.__setattr__(self, "event_id", self._derive_event_id())

    def _derive_event_id(self) -> str:
        material = {
            "algorithm": EVENT_ID_ALGORITHM_VERSION,
            "schema_version": self.schema_version,
            "event_type": self.event_type.value,
            "headline": self.headline,
            "summary": self.summary,
            "occur_time": self.occur_time.isoformat(),
            "publish_time": self.publish_time.isoformat(),
            "available_time": self.available_time.isoformat(),
            "instrument_ids": list(self.instrument_ids),
            "sector_ids": list(self.sector_ids),
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "content_record_id": item.content_record_id,
                    "content_version_id": item.content_version_id,
                    "source_id": item.source_id,
                    "source_version": item.source_version,
                    "available_time": item.available_time.isoformat(),
                    "start_offset": item.start_offset,
                    "end_offset": item.end_offset,
                    "excerpt": item.excerpt,
                }
                for item in self.evidence
            ],
            "model_provenance": {
                "producer_type": self.model_provenance.producer_type.value,
                "provider": self.model_provenance.provider,
                "model_id": self.model_provenance.model_id,
                "model_version": self.model_provenance.model_version,
                "prompt_version": self.model_provenance.prompt_version,
                "output_schema_version": self.model_provenance.output_schema_version,
                "configuration_fingerprint": self.model_provenance.configuration_fingerprint,
                "extraction_run_id": self.model_provenance.extraction_run_id,
                "processing_time": self.model_provenance.processing_time.isoformat(),
            },
            "confidence_bps": self.confidence_bps,
        }
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "EVENT_ID_ALGORITHM_VERSION",
    "MARKET_EVENT_SCHEMA_VERSION",
    "EventEvidence",
    "MarketEvent",
    "MarketEventType",
    "ModelProvenance",
    "ProducerType",
]
