"""Immutable seat domain models and generated-contract adapters for P4-N01.

This module models public Dragon-Tiger List facts only. It contains no broker
SDK, account, order, collection, alias-resolution, or performance-calculation
logic. Names are evidence and display data; ``seat_id`` is derived only from
an explicit immutable identity key.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import overload

from ashare_contracts import SeatAlias as AliasDTO
from ashare_contracts import SeatLineage as SeatLineageDTO
from ashare_contracts import SeatPerformance as PerformanceDTO
from ashare_contracts import SeatPreference as PreferenceDTO
from ashare_contracts import SeatProfile as SeatProfileDTO
from ashare_contracts import SeatTrade as TradeDTO

SEAT_ID_ALGORITHM_VERSION = "seat-id-v1"
SEAT_ID_NAMESPACE = "kunlun-seat-id-v1"
SEAT_ID_PREFIX = "seat-"
SEAT_PROFILE_SCHEMA_VERSION = "seat-profile-v1"
ALIAS_SCHEMA_VERSION = "alias-v1"
TRADE_SCHEMA_VERSION = "seat-trade-v1"
PERFORMANCE_SCHEMA_VERSION = "seat-performance-v1"
PREFERENCE_SCHEMA_VERSION = "seat-preference-v1"

_SEAT_ID_RE = re.compile(r"^seat-[0-9a-f]{64}$")
_IDENTITY_KEY_RE = re.compile(r"^[^\s:]+(?::[^\s:]+)+$")
_INSTRUMENT_ID_RE = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$")


class SeatKind(StrEnum):
    BROKER_BRANCH = "BROKER_BRANCH"
    INSTITUTION = "INSTITUTION"
    UNKNOWN = "UNKNOWN"
    OTHER = "OTHER"


class AliasType(StrEnum):
    OFFICIAL = "OFFICIAL"
    FORMER = "FORMER"
    SOURCE = "SOURCE"
    ALTERNATE = "ALTERNATE"


class LineageRelation(StrEnum):
    MERGE = "MERGE"
    SPLIT = "SPLIT"


class Currency(StrEnum):
    CNY = "CNY"


def _require_non_empty(value: str, name: str) -> None:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_revision(value: str, name: str = "revision_id") -> None:
    _require_non_empty(value, name)


def _require_aware(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_interval(start: datetime, end: datetime | None, name: str) -> None:
    _require_aware(start, f"{name}_from")
    if end is not None:
        _require_aware(end, f"{name}_to")
        if end <= start:
            raise ValueError(f"{name}_to must be greater than {name}_from")


def _require_seat_id(value: str, name: str = "seat_id") -> None:
    if type(value) is not str or _SEAT_ID_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must match seat-[0-9a-f]{{64}}")


def _require_instrument_id(value: str) -> None:
    if _INSTRUMENT_ID_RE.fullmatch(value) is None:
        raise ValueError("instrument_id must use canonical unified code form")


def normalize_identity_key(identity_key: str) -> str:
    """Validate the canonical, non-display identity-key representation."""

    if type(identity_key) is not str or not identity_key:
        raise ValueError("identity_key must be a non-empty string")
    if "\x00" in identity_key:
        raise ValueError("identity_key must not contain NUL")
    normalized = unicodedata.normalize("NFC", identity_key)
    if normalized != identity_key:
        raise ValueError("identity_key must already be Unicode NFC-normalized")
    if _IDENTITY_KEY_RE.fullmatch(identity_key) is None:
        raise ValueError("identity_key must use namespace:opaque segments without whitespace")
    return identity_key


def _require_decimal(value: Decimal, name: str, *, non_negative: bool = False) -> None:
    if type(value) is not Decimal:
        raise TypeError(f"{name} must be Decimal; binary float is not accepted")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if non_negative and value < 0:
        raise ValueError(f"{name} must be non-negative")


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _decimal_from_text(value: str, name: str) -> Decimal:
    if type(value) is not str:
        raise TypeError(f"{name} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a valid decimal string") from exc
    _require_decimal(result, name)
    return result


def _decimal_unscaled(value: Decimal) -> tuple[int, int]:
    sign, digits, exponent = value.as_tuple()
    if type(exponent) is not int:
        raise ValueError("decimal must be finite")
    coefficient = int("".join(str(digit) for digit in digits) or "0")
    if sign:
        coefficient = -coefficient
    if exponent >= 0:
        return coefficient * 10**exponent, 0
    return coefficient, -exponent


def _decimal_difference_matches(buy: Decimal, sell: Decimal, net: Decimal) -> bool:
    buy_unscaled, buy_scale = _decimal_unscaled(buy)
    sell_unscaled, sell_scale = _decimal_unscaled(sell)
    net_unscaled, net_scale = _decimal_unscaled(net)
    scale = max(buy_scale, sell_scale, net_scale)
    return net_unscaled * 10 ** (scale - net_scale) == buy_unscaled * 10 ** (
        scale - buy_scale
    ) - sell_unscaled * 10 ** (scale - sell_scale)


def _require_string_tuple(values: tuple[str, ...], name: str, *, non_empty: bool = True) -> None:
    if type(values) is not tuple:
        raise TypeError(f"{name} must be a tuple")
    if non_empty and not values:
        raise ValueError(f"{name} must not be empty")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not contain duplicates")
    for value in values:
        _require_non_empty(value, f"{name} item")


def compute_seat_id(identity_key: str) -> str:
    """Derive a stable seat id from an immutable, non-display identity key."""

    normalized = normalize_identity_key(identity_key)
    material = f"{SEAT_ID_NAMESPACE}\0{normalized}".encode()
    return f"{SEAT_ID_PREFIX}{hashlib.sha256(material).hexdigest()}"


@dataclass(frozen=True)
class SeatLineage:
    """Auditable merge/split relation between stable seat identities."""

    lineage_id: str
    relation: LineageRelation
    predecessor_seat_ids: tuple[str, ...]
    successor_seat_ids: tuple[str, ...]
    effective_at: datetime
    source: str
    source_version: str
    evidence_id: str
    revision_id: str

    def __post_init__(self) -> None:
        _require_non_empty(self.lineage_id, "lineage_id")
        if type(self.relation) is not LineageRelation:
            raise TypeError("relation must be LineageRelation")
        _require_string_tuple(self.predecessor_seat_ids, "predecessor_seat_ids")
        _require_string_tuple(self.successor_seat_ids, "successor_seat_ids")
        for seat_id in (*self.predecessor_seat_ids, *self.successor_seat_ids):
            _require_seat_id(seat_id)
        if set(self.predecessor_seat_ids).intersection(self.successor_seat_ids):
            raise ValueError("predecessor and successor seat ids must be distinct")
        if self.relation is LineageRelation.MERGE and (
            len(self.predecessor_seat_ids) < 2 or len(self.successor_seat_ids) != 1
        ):
            raise ValueError("MERGE must have at least two predecessors and exactly one successor")
        if self.relation is LineageRelation.SPLIT and (
            len(self.predecessor_seat_ids) != 1 or len(self.successor_seat_ids) < 2
        ):
            raise ValueError("SPLIT must have exactly one predecessor and at least two successors")
        _require_aware(self.effective_at, "effective_at")
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        _require_non_empty(self.evidence_id, "evidence_id")
        _require_revision(self.revision_id)


@dataclass(frozen=True)
class SeatProfile:
    """Versioned seat identity profile; names are mutable evidence."""

    seat_id: str
    seat_id_algorithm: str
    identity_key: str
    seat_kind: SeatKind
    canonical_name: str | None
    valid_from: datetime
    valid_to: datetime | None
    available_time: datetime
    revision_id: str
    source: str
    source_version: str
    evidence_id: str
    previous_revision_id: str | None = None
    lineage: tuple[SeatLineage, ...] = ()
    schema_version: str = SEAT_PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_seat_id(self.seat_id)
        if (
            type(self.seat_id_algorithm) is not str
            or self.seat_id_algorithm != SEAT_ID_ALGORITHM_VERSION
        ):
            raise ValueError(f"unsupported seat_id_algorithm: {self.seat_id_algorithm!r}")
        normalize_identity_key(self.identity_key)
        if compute_seat_id(self.identity_key) != self.seat_id:
            raise ValueError("seat_id does not match identity_key")
        if type(self.seat_kind) is not SeatKind:
            raise TypeError("seat_kind must be SeatKind")
        if self.canonical_name is not None:
            _require_non_empty(self.canonical_name, "canonical_name")
        _require_interval(self.valid_from, self.valid_to, "valid")
        _require_aware(self.available_time, "available_time")
        _require_revision(self.revision_id)
        if self.previous_revision_id is not None:
            _require_revision(self.previous_revision_id, "previous_revision_id")
            if self.previous_revision_id == self.revision_id:
                raise ValueError("previous_revision_id must differ from revision_id")
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        _require_non_empty(self.evidence_id, "evidence_id")
        if self.schema_version != SEAT_PROFILE_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {self.schema_version!r}")
        if type(self.lineage) is not tuple:
            raise TypeError("lineage must be a tuple")
        lineage_ids: set[str] = set()
        lineage_values: set[SeatLineage] = set()
        for item in self.lineage:
            if type(item) is not SeatLineage:
                raise TypeError("lineage must contain SeatLineage instances")
            if item.lineage_id in lineage_ids or item in lineage_values:
                raise ValueError("lineage contains duplicate lineage_id or equal record")
            lineage_ids.add(item.lineage_id)
            lineage_values.add(item)
            if not self.is_valid_at(item.effective_at):
                raise ValueError("lineage.effective_at must be inside profile validity")
            if item.relation is LineageRelation.MERGE:
                if self.seat_id not in item.successor_seat_ids:
                    raise ValueError("MERGE profile seat_id must be a successor")
            elif self.seat_id not in item.predecessor_seat_ids:
                raise ValueError("SPLIT profile seat_id must be a predecessor")

    @classmethod
    def from_identity(
        cls,
        identity_key: str,
        *,
        canonical_name: str | None,
        seat_kind: SeatKind,
        valid_from: datetime,
        valid_to: datetime | None,
        available_time: datetime,
        revision_id: str,
        source: str,
        source_version: str,
        evidence_id: str,
        previous_revision_id: str | None = None,
        lineage: tuple[SeatLineage, ...] = (),
    ) -> SeatProfile:
        return cls(
            seat_id=compute_seat_id(identity_key),
            seat_id_algorithm=SEAT_ID_ALGORITHM_VERSION,
            identity_key=identity_key,
            canonical_name=canonical_name,
            seat_kind=seat_kind,
            valid_from=valid_from,
            valid_to=valid_to,
            available_time=available_time,
            revision_id=revision_id,
            source=source,
            source_version=source_version,
            evidence_id=evidence_id,
            previous_revision_id=previous_revision_id,
            lineage=lineage,
        )

    def is_valid_at(self, instant: datetime) -> bool:
        _require_aware(instant, "instant")
        return self.valid_from <= instant and (self.valid_to is None or instant < self.valid_to)


@dataclass(frozen=True)
class Alias:
    """Immutable source/display name alias for one stable seat."""

    alias_id: str
    seat_id: str
    name: str
    alias_type: AliasType
    valid_from: datetime
    valid_to: datetime | None
    available_time: datetime
    source: str
    source_version: str
    evidence_id: str
    revision_id: str
    previous_revision_id: str | None = None
    schema_version: str = ALIAS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_non_empty(self.alias_id, "alias_id")
        _require_seat_id(self.seat_id)
        _require_non_empty(self.name, "name")
        if type(self.alias_type) is not AliasType:
            raise TypeError("alias_type must be AliasType")
        _require_interval(self.valid_from, self.valid_to, "valid")
        _require_aware(self.available_time, "available_time")
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        _require_non_empty(self.evidence_id, "evidence_id")
        _require_revision(self.revision_id)
        if self.previous_revision_id is not None:
            _require_revision(self.previous_revision_id, "previous_revision_id")
            if self.previous_revision_id == self.revision_id:
                raise ValueError("previous_revision_id must differ from revision_id")
        if self.schema_version != ALIAS_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {self.schema_version!r}")

    def is_valid_at(self, instant: datetime) -> bool:
        _require_aware(instant, "instant")
        return self.valid_from <= instant and (self.valid_to is None or instant < self.valid_to)


class AliasCatalog:
    """Immutable alias collection with same-seat/name interval validation.

    Different seats may share a source name; P4-N02 owns resolving that
    ambiguity. This catalog only rejects overlapping intervals for the same
    stable seat and exact source name.
    """

    def __init__(self, aliases: Iterable[Alias]) -> None:
        by_id: dict[str, Alias] = {}
        for alias in aliases:
            previous = by_id.get(alias.alias_id)
            if previous is not None and previous != alias:
                raise ValueError(f"conflicting duplicate alias_id: {alias.alias_id!r}")
            by_id[alias.alias_id] = alias

        grouped: dict[tuple[str, str], list[Alias]] = {}
        for alias in by_id.values():
            grouped.setdefault((alias.seat_id, alias.name), []).append(alias)
        for key, entries in grouped.items():
            ordered = sorted(entries, key=lambda item: (item.valid_from, item.alias_id))
            previous: Alias | None = None
            for current in ordered:
                if previous is not None and (
                    previous.valid_to is None or current.valid_from < previous.valid_to
                ):
                    raise ValueError(f"alias validity intervals overlap for {key!r}")
                previous = current

        self._aliases = tuple(sorted(by_id.values(), key=lambda item: item.alias_id))

    @property
    def aliases(self) -> tuple[Alias, ...]:
        return self._aliases


@dataclass(frozen=True)
class Trade:
    """Immutable public Dragon-Tiger List fact, never a broker order."""

    trade_id: str
    revision_id: str
    previous_revision_id: str | None
    seat_id: str
    raw_seat_name: str
    instrument_id: str
    trade_date: date
    currency: Currency
    buy_amount: Decimal
    sell_amount: Decimal
    net_amount: Decimal
    source: str
    source_version: str
    raw_record_id: str
    evidence_id: str
    available_time: datetime
    schema_version: str = TRADE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_non_empty(self.trade_id, "trade_id")
        _require_revision(self.revision_id)
        if self.previous_revision_id is not None:
            _require_revision(self.previous_revision_id, "previous_revision_id")
            if self.previous_revision_id == self.revision_id:
                raise ValueError("previous_revision_id must differ from revision_id")
        _require_seat_id(self.seat_id)
        _require_non_empty(self.raw_seat_name, "raw_seat_name")
        _require_instrument_id(self.instrument_id)
        if type(self.trade_date) is not date:
            raise TypeError("trade_date must be date")
        if type(self.currency) is not Currency:
            raise TypeError("currency must be Currency")
        if self.currency is not Currency.CNY:
            raise ValueError("currency must be CNY")
        _require_decimal(self.buy_amount, "buy_amount", non_negative=True)
        _require_decimal(self.sell_amount, "sell_amount", non_negative=True)
        _require_decimal(self.net_amount, "net_amount")
        if not _decimal_difference_matches(self.buy_amount, self.sell_amount, self.net_amount):
            raise ValueError("net_amount must equal buy_amount - sell_amount")
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        _require_non_empty(self.raw_record_id, "raw_record_id")
        _require_non_empty(self.evidence_id, "evidence_id")
        _require_aware(self.available_time, "available_time")
        if self.schema_version != TRADE_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {self.schema_version!r}")


@dataclass(frozen=True)
class Performance:
    """Versioned performance snapshot; calculation belongs to P4-N04."""

    performance_id: str
    seat_id: str
    window_start: date
    window_end: date
    calculation_version: str
    sample_count: int
    t_plus_1_return: Decimal | None
    t_plus_3_return: Decimal | None
    t_plus_5_return: Decimal | None
    win_rate: Decimal | None
    max_drawdown: Decimal | None
    source: str
    source_version: str
    evidence_id: str
    revision_id: str
    available_time: datetime
    previous_revision_id: str | None = None
    schema_version: str = PERFORMANCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_non_empty(self.performance_id, "performance_id")
        _require_seat_id(self.seat_id)
        if type(self.window_start) is not date or type(self.window_end) is not date:
            raise TypeError("window_start/window_end must be date")
        if self.window_end < self.window_start:
            raise ValueError("window_end must be >= window_start")
        _require_non_empty(self.calculation_version, "calculation_version")
        if type(self.sample_count) is not int or self.sample_count < 0:
            raise ValueError("sample_count must be a non-negative integer")
        for name, value in (
            ("t_plus_1_return", self.t_plus_1_return),
            ("t_plus_3_return", self.t_plus_3_return),
            ("t_plus_5_return", self.t_plus_5_return),
            ("win_rate", self.win_rate),
            ("max_drawdown", self.max_drawdown),
        ):
            if value is not None:
                _require_decimal(value, name)
        if self.win_rate is not None and not Decimal("0") <= self.win_rate <= Decimal("1"):
            raise ValueError("win_rate must be in [0, 1]")
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        _require_non_empty(self.evidence_id, "evidence_id")
        _require_revision(self.revision_id)
        if self.previous_revision_id is not None:
            _require_revision(self.previous_revision_id, "previous_revision_id")
            if self.previous_revision_id == self.revision_id:
                raise ValueError("previous_revision_id must differ from revision_id")
        _require_aware(self.available_time, "available_time")
        if self.schema_version != PERFORMANCE_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {self.schema_version!r}")


@dataclass(frozen=True)
class Preference:
    """Versioned, provenance-backed style preference snapshot."""

    preference_id: str
    seat_id: str
    valid_from: datetime
    valid_to: datetime | None
    preference_version: str
    style_tags: tuple[str, ...]
    confidence_bps: int
    source: str
    source_version: str
    evidence_id: str
    revision_id: str
    available_time: datetime
    previous_revision_id: str | None = None
    schema_version: str = PREFERENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_non_empty(self.preference_id, "preference_id")
        _require_seat_id(self.seat_id)
        _require_interval(self.valid_from, self.valid_to, "valid")
        _require_non_empty(self.preference_version, "preference_version")
        _require_string_tuple(self.style_tags, "style_tags")
        if type(self.confidence_bps) is not int or not 0 <= self.confidence_bps <= 10000:
            raise ValueError("confidence_bps must be an integer in [0, 10000]")
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        _require_non_empty(self.evidence_id, "evidence_id")
        _require_revision(self.revision_id)
        _require_aware(self.available_time, "available_time")
        if self.previous_revision_id is not None:
            _require_revision(self.previous_revision_id, "previous_revision_id")
            if self.previous_revision_id == self.revision_id:
                raise ValueError("previous_revision_id must differ from revision_id")
        if self.schema_version != PREFERENCE_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {self.schema_version!r}")

    def is_valid_at(self, instant: datetime) -> bool:
        _require_aware(instant, "instant")
        return self.valid_from <= instant and (self.valid_to is None or instant < self.valid_to)


Contract = AliasDTO | PerformanceDTO | PreferenceDTO | SeatProfileDTO | TradeDTO
DomainModel = Alias | Performance | Preference | SeatProfile | Trade


def _enum_value(value: object, name: str) -> str:
    raw = getattr(value, "value", value)
    if not isinstance(raw, str):
        raise TypeError(f"{name} must contain a string enum value")
    return raw


def _root_text(value: object, name: str) -> str:
    raw = getattr(value, "root", value)
    if not isinstance(raw, str):
        raise TypeError(f"{name} must contain a string value")
    return raw


def _lineage_to_payload(item: SeatLineage) -> dict[str, object]:
    return {
        "lineageId": item.lineage_id,
        "relation": item.relation.value,
        "predecessorSeatIds": list(item.predecessor_seat_ids),
        "successorSeatIds": list(item.successor_seat_ids),
        "effectiveAt": item.effective_at,
        "source": item.source,
        "sourceVersion": item.source_version,
        "evidenceId": item.evidence_id,
        "revisionId": item.revision_id,
    }


def _lineage_from_dto(item: SeatLineageDTO) -> SeatLineage:
    return SeatLineage(
        lineage_id=item.lineage_id,
        relation=LineageRelation(_enum_value(item.relation, "relation")),
        predecessor_seat_ids=tuple(
            _root_text(value, "predecessor_seat_ids") for value in item.predecessor_seat_ids
        ),
        successor_seat_ids=tuple(
            _root_text(value, "successor_seat_ids") for value in item.successor_seat_ids
        ),
        effective_at=item.effective_at,
        source=item.source,
        source_version=item.source_version,
        evidence_id=item.evidence_id,
        revision_id=item.revision_id,
    )


def _profile_to_contract(model: SeatProfile) -> SeatProfileDTO:
    return SeatProfileDTO.model_validate(
        {
            "schemaVersion": model.schema_version,
            "seatId": model.seat_id,
            "seatIdAlgorithm": model.seat_id_algorithm,
            "identityKey": model.identity_key,
            "seatKind": model.seat_kind.value,
            "canonicalName": model.canonical_name,
            "validFrom": model.valid_from,
            "validTo": model.valid_to,
            "availableTime": model.available_time,
            "revisionId": model.revision_id,
            "source": model.source,
            "sourceVersion": model.source_version,
            "evidenceId": model.evidence_id,
            "previousRevisionId": model.previous_revision_id,
            "lineage": [_lineage_to_payload(item) for item in model.lineage],
        }
    )


def _alias_to_contract(model: Alias) -> AliasDTO:
    return AliasDTO.model_validate(
        {
            "schemaVersion": model.schema_version,
            "aliasId": model.alias_id,
            "seatId": model.seat_id,
            "name": model.name,
            "aliasType": model.alias_type.value,
            "validFrom": model.valid_from,
            "validTo": model.valid_to,
            "availableTime": model.available_time,
            "source": model.source,
            "sourceVersion": model.source_version,
            "evidenceId": model.evidence_id,
            "revisionId": model.revision_id,
            "previousRevisionId": model.previous_revision_id,
        }
    )


def _trade_to_contract(model: Trade) -> TradeDTO:
    return TradeDTO.model_validate(
        {
            "schemaVersion": model.schema_version,
            "tradeId": model.trade_id,
            "revisionId": model.revision_id,
            "previousRevisionId": model.previous_revision_id,
            "seatId": model.seat_id,
            "rawSeatName": model.raw_seat_name,
            "instrumentId": model.instrument_id,
            "tradeDate": model.trade_date,
            "currency": model.currency.value,
            "buyAmount": _decimal_text(model.buy_amount),
            "sellAmount": _decimal_text(model.sell_amount),
            "netAmount": _decimal_text(model.net_amount),
            "source": model.source,
            "sourceVersion": model.source_version,
            "rawRecordId": model.raw_record_id,
            "evidenceId": model.evidence_id,
            "availableTime": model.available_time,
        }
    )


def _performance_to_contract(model: Performance) -> PerformanceDTO:
    return PerformanceDTO.model_validate(
        {
            "schemaVersion": model.schema_version,
            "performanceId": model.performance_id,
            "seatId": model.seat_id,
            "windowStart": model.window_start,
            "windowEnd": model.window_end,
            "calculationVersion": model.calculation_version,
            "sampleCount": model.sample_count,
            "tPlus1Return": (
                None if model.t_plus_1_return is None else _decimal_text(model.t_plus_1_return)
            ),
            "tPlus3Return": (
                None if model.t_plus_3_return is None else _decimal_text(model.t_plus_3_return)
            ),
            "tPlus5Return": (
                None if model.t_plus_5_return is None else _decimal_text(model.t_plus_5_return)
            ),
            "winRate": None if model.win_rate is None else _decimal_text(model.win_rate),
            "maxDrawdown": (
                None if model.max_drawdown is None else _decimal_text(model.max_drawdown)
            ),
            "source": model.source,
            "sourceVersion": model.source_version,
            "evidenceId": model.evidence_id,
            "revisionId": model.revision_id,
            "availableTime": model.available_time,
            "previousRevisionId": model.previous_revision_id,
        }
    )


def _preference_to_contract(model: Preference) -> PreferenceDTO:
    return PreferenceDTO.model_validate(
        {
            "schemaVersion": model.schema_version,
            "preferenceId": model.preference_id,
            "seatId": model.seat_id,
            "validFrom": model.valid_from,
            "validTo": model.valid_to,
            "preferenceVersion": model.preference_version,
            "styleTags": list(model.style_tags),
            "confidenceBps": model.confidence_bps,
            "source": model.source,
            "sourceVersion": model.source_version,
            "evidenceId": model.evidence_id,
            "revisionId": model.revision_id,
            "availableTime": model.available_time,
            "previousRevisionId": model.previous_revision_id,
        }
    )


@overload
def to_contract(model: SeatProfile) -> SeatProfileDTO: ...


@overload
def to_contract(model: Alias) -> AliasDTO: ...


@overload
def to_contract(model: Trade) -> TradeDTO: ...


@overload
def to_contract(model: Performance) -> PerformanceDTO: ...


@overload
def to_contract(model: Preference) -> PreferenceDTO: ...


def to_contract(model: DomainModel) -> Contract:
    if type(model) is SeatProfile:
        return _profile_to_contract(model)
    if type(model) is Alias:
        return _alias_to_contract(model)
    if type(model) is Trade:
        return _trade_to_contract(model)
    if type(model) is Performance:
        return _performance_to_contract(model)
    if type(model) is Preference:
        return _preference_to_contract(model)
    raise TypeError(f"unsupported seat domain model: {type(model).__name__}")


def _profile_from_contract(dto: SeatProfileDTO) -> SeatProfile:
    return SeatProfile(
        seat_id=dto.seat_id,
        seat_id_algorithm=_enum_value(dto.seat_id_algorithm, "seat_id_algorithm"),
        identity_key=dto.identity_key,
        seat_kind=SeatKind(_enum_value(dto.seat_kind, "seat_kind")),
        canonical_name=dto.canonical_name,
        valid_from=dto.valid_from,
        valid_to=dto.valid_to,
        available_time=dto.available_time,
        revision_id=dto.revision_id,
        source=dto.source,
        source_version=dto.source_version,
        evidence_id=dto.evidence_id,
        previous_revision_id=dto.previous_revision_id,
        lineage=tuple(_lineage_from_dto(item) for item in dto.lineage),
        schema_version=_enum_value(dto.schema_version, "schema_version"),
    )


def _alias_from_contract(dto: AliasDTO) -> Alias:
    return Alias(
        alias_id=dto.alias_id,
        seat_id=dto.seat_id,
        name=dto.name,
        alias_type=AliasType(_enum_value(dto.alias_type, "alias_type")),
        valid_from=dto.valid_from,
        valid_to=dto.valid_to,
        available_time=dto.available_time,
        source=dto.source,
        source_version=dto.source_version,
        evidence_id=dto.evidence_id,
        revision_id=dto.revision_id,
        previous_revision_id=dto.previous_revision_id,
        schema_version=_enum_value(dto.schema_version, "schema_version"),
    )


def _trade_from_contract(dto: TradeDTO) -> Trade:
    return Trade(
        trade_id=dto.trade_id,
        revision_id=dto.revision_id,
        previous_revision_id=dto.previous_revision_id,
        seat_id=dto.seat_id,
        raw_seat_name=dto.raw_seat_name,
        instrument_id=dto.instrument_id,
        trade_date=dto.trade_date,
        currency=Currency(_enum_value(dto.currency, "currency")),
        buy_amount=_decimal_from_text(dto.buy_amount, "buy_amount"),
        sell_amount=_decimal_from_text(dto.sell_amount, "sell_amount"),
        net_amount=_decimal_from_text(dto.net_amount, "net_amount"),
        source=dto.source,
        source_version=dto.source_version,
        raw_record_id=dto.raw_record_id,
        evidence_id=dto.evidence_id,
        available_time=dto.available_time,
        schema_version=_enum_value(dto.schema_version, "schema_version"),
    )


def _performance_from_contract(dto: PerformanceDTO) -> Performance:
    return Performance(
        performance_id=dto.performance_id,
        seat_id=dto.seat_id,
        window_start=dto.window_start,
        window_end=dto.window_end,
        calculation_version=dto.calculation_version,
        sample_count=dto.sample_count,
        t_plus_1_return=(
            None
            if dto.t_plus1_return is None
            else _decimal_from_text(dto.t_plus1_return, "t_plus_1_return")
        ),
        t_plus_3_return=(
            None
            if dto.t_plus3_return is None
            else _decimal_from_text(dto.t_plus3_return, "t_plus_3_return")
        ),
        t_plus_5_return=(
            None
            if dto.t_plus5_return is None
            else _decimal_from_text(dto.t_plus5_return, "t_plus_5_return")
        ),
        win_rate=(None if dto.win_rate is None else _decimal_from_text(dto.win_rate, "win_rate")),
        max_drawdown=(
            None
            if dto.max_drawdown is None
            else _decimal_from_text(dto.max_drawdown, "max_drawdown")
        ),
        source=dto.source,
        source_version=dto.source_version,
        evidence_id=dto.evidence_id,
        revision_id=dto.revision_id,
        available_time=dto.available_time,
        previous_revision_id=dto.previous_revision_id,
        schema_version=_enum_value(dto.schema_version, "schema_version"),
    )


def _preference_from_contract(dto: PreferenceDTO) -> Preference:
    return Preference(
        preference_id=dto.preference_id,
        seat_id=dto.seat_id,
        valid_from=dto.valid_from,
        valid_to=dto.valid_to,
        preference_version=dto.preference_version,
        style_tags=tuple(_root_text(item, "style_tags") for item in dto.style_tags),
        confidence_bps=dto.confidence_bps,
        source=dto.source,
        source_version=dto.source_version,
        evidence_id=dto.evidence_id,
        revision_id=dto.revision_id,
        available_time=dto.available_time,
        previous_revision_id=dto.previous_revision_id,
        schema_version=_enum_value(dto.schema_version, "schema_version"),
    )


@overload
def from_contract(value: SeatProfileDTO) -> SeatProfile: ...


@overload
def from_contract(value: AliasDTO) -> Alias: ...


@overload
def from_contract(value: TradeDTO) -> Trade: ...


@overload
def from_contract(value: PerformanceDTO) -> Performance: ...


@overload
def from_contract(value: PreferenceDTO) -> Preference: ...


def from_contract(value: Contract) -> DomainModel:
    if type(value) is SeatProfileDTO:
        return _profile_from_contract(value)
    if type(value) is AliasDTO:
        return _alias_from_contract(value)
    if type(value) is TradeDTO:
        return _trade_from_contract(value)
    if type(value) is PerformanceDTO:
        return _performance_from_contract(value)
    if type(value) is PreferenceDTO:
        return _preference_from_contract(value)
    raise TypeError(f"unsupported seat contract: {type(value).__name__}")


def parse_seat_profile_payload(payload: Mapping[str, object]) -> SeatProfile:
    return _profile_from_contract(SeatProfileDTO.model_validate(payload))


def parse_alias_payload(payload: Mapping[str, object]) -> Alias:
    return _alias_from_contract(AliasDTO.model_validate(payload))


def parse_trade_payload(payload: Mapping[str, object]) -> Trade:
    return _trade_from_contract(TradeDTO.model_validate(payload))


def parse_performance_payload(payload: Mapping[str, object]) -> Performance:
    return _performance_from_contract(PerformanceDTO.model_validate(payload))


def parse_preference_payload(payload: Mapping[str, object]) -> Preference:
    return _preference_from_contract(PreferenceDTO.model_validate(payload))


__all__ = [
    "ALIAS_SCHEMA_VERSION",
    "Currency",
    "PERFORMANCE_SCHEMA_VERSION",
    "PREFERENCE_SCHEMA_VERSION",
    "SEAT_ID_ALGORITHM_VERSION",
    "SEAT_ID_NAMESPACE",
    "SEAT_ID_PREFIX",
    "SEAT_PROFILE_SCHEMA_VERSION",
    "TRADE_SCHEMA_VERSION",
    "Alias",
    "AliasCatalog",
    "AliasType",
    "LineageRelation",
    "Performance",
    "Preference",
    "SeatKind",
    "SeatLineage",
    "SeatProfile",
    "Trade",
    "compute_seat_id",
    "normalize_identity_key",
    "from_contract",
    "parse_alias_payload",
    "parse_performance_payload",
    "parse_preference_payload",
    "parse_seat_profile_payload",
    "parse_trade_payload",
    "to_contract",
]
