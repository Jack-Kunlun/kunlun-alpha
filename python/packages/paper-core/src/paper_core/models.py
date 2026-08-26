"""Immutable contracts for simulation-only account state and events."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Final

ACCOUNT_SCHEMA_VERSION: Final = "paper-account-ledger-v1"
SNAPSHOT_SCHEMA_VERSION: Final = "paper-account-snapshot-v1"
ZERO_DIGEST: Final = "0" * 64
_HASH = re.compile(r"^[0-9a-f]{64}$")
_INSTRUMENT = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$")


class PaperAccountError(Exception):
    """Base error for the paper-account boundary."""


class PaperAccountValidationError(PaperAccountError, ValueError):
    """Raised when a simulation account value violates its contract."""


class PaperAccountEventConflictError(PaperAccountError):
    """Raised when an event identity is reused with different content."""


class PaperAccountConcurrencyError(PaperAccountError):
    """Raised when an append is based on a stale event-tape digest."""


class PaperAccountLifecycleError(PaperAccountError):
    """Raised for an illegal account lifecycle transition."""


class PaperAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class PositionTransferReason(str, Enum):
    SIMULATION_SEED = "SIMULATION_SEED"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    RECONCILIATION = "RECONCILIATION"


class ValuationMarkSource(str, Enum):
    EXECUTABLE_QUOTE = "EXECUTABLE_QUOTE"
    MARKET_CLOSE = "MARKET_CLOSE"
    STALE_FALLBACK = "STALE_FALLBACK"


def _text(value: object, name: str, maximum: int = 240) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise PaperAccountValidationError(f"{name} must be a non-empty bounded string")
    return value


def _digest(value: object, name: str, *, allow_zero: bool = False) -> str:
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise PaperAccountValidationError(f"{name} must be a lowercase sha256 digest")
    if not allow_zero and value == ZERO_DIGEST:
        raise PaperAccountValidationError(f"{name} must not be the zero digest")
    return value


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise PaperAccountValidationError(f"{name} must be timezone-aware")
    return value


def _money(value: object, name: str, *, positive: bool = False) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise PaperAccountValidationError(f"{name} must be a finite Decimal")
    if value < 0 or (positive and value <= 0):
        qualifier = "positive" if positive else "non-negative"
        raise PaperAccountValidationError(f"{name} must be {qualifier}")
    return value


def _signed_money(value: object, name: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise PaperAccountValidationError(f"{name} must be a finite Decimal")
    return value


def _instrument(value: object, name: str = "instrument_id") -> str:
    if type(value) is not str or _INSTRUMENT.fullmatch(value) is None:
        raise PaperAccountValidationError(f"{name} must use the canonical A-share form")
    return value


def _decimal_text(value: Decimal) -> str:
    normalized = format(value, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _time_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def canonical_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PaperEventMetadata:
    account_id: str
    event_id: str
    sequence: int
    event_time: datetime
    available_time: datetime
    previous_event_digest: str
    source_id: str
    source_version: str
    schema_version: str = ACCOUNT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _digest(self.account_id, "account_id")
        _digest(self.event_id, "event_id")
        if type(self.sequence) is not int or self.sequence < 0:
            raise PaperAccountValidationError("sequence must be a non-negative integer")
        event_time = _aware(self.event_time, "event_time")
        available_time = _aware(self.available_time, "available_time")
        if event_time > available_time:
            raise PaperAccountValidationError("event_time must not exceed available_time")
        _digest(self.previous_event_digest, "previous_event_digest", allow_zero=True)
        _text(self.source_id, "source_id")
        _text(self.source_version, "source_version")
        if self.schema_version != ACCOUNT_SCHEMA_VERSION:
            raise PaperAccountValidationError("unsupported account event schema")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "account_id": self.account_id,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "event_time": _time_text(self.event_time),
            "available_time": _time_text(self.available_time),
            "previous_event_digest": self.previous_event_digest,
            "source_id": self.source_id,
            "source_version": self.source_version,
        }


@dataclass(frozen=True, slots=True)
class OpenPaperAccount:
    metadata: PaperEventMetadata
    owner_ref: str
    name: str
    initial_capital: Decimal
    base_currency: str = "CNY"

    def __post_init__(self) -> None:
        _text(self.owner_ref, "owner_ref", 128)
        _text(self.name, "name", 80)
        _money(self.initial_capital, "initial_capital", positive=True)
        if self.base_currency != "CNY":
            raise PaperAccountValidationError("paper accounts support CNY only")

    def payload(self) -> dict[str, object]:
        return {
            "type": type(self).__name__,
            "metadata": self.metadata.payload(),
            "owner_ref": self.owner_ref,
            "name": self.name,
            "initial_capital": _decimal_text(self.initial_capital),
            "base_currency": self.base_currency,
        }


@dataclass(frozen=True, slots=True)
class TransferPaperPosition:
    """Balanced simulation-only transfer between cash and position cost."""

    metadata: PaperEventMetadata
    instrument_id: str
    quantity_delta: int
    available_quantity_delta: int
    cash_delta: Decimal
    position_cost_delta: Decimal
    reason: PositionTransferReason
    explanation: str

    def __post_init__(self) -> None:
        _instrument(self.instrument_id)
        if type(self.quantity_delta) is not int or self.quantity_delta == 0:
            raise PaperAccountValidationError("quantity_delta must be a non-zero integer")
        if type(self.available_quantity_delta) is not int:
            raise PaperAccountValidationError("available_quantity_delta must be an integer")
        cash_delta = _signed_money(self.cash_delta, "cash_delta")
        cost_delta = _signed_money(self.position_cost_delta, "position_cost_delta")
        if cash_delta + cost_delta != 0:
            raise PaperAccountValidationError("cash and position-cost transfer must balance")
        if type(self.reason) is not PositionTransferReason:
            raise PaperAccountValidationError("reason must be PositionTransferReason")
        _text(self.explanation, "explanation")

    def payload(self) -> dict[str, object]:
        return {
            "type": type(self).__name__,
            "metadata": self.metadata.payload(),
            "instrument_id": self.instrument_id,
            "quantity_delta": self.quantity_delta,
            "available_quantity_delta": self.available_quantity_delta,
            "cash_delta": _decimal_text(self.cash_delta),
            "position_cost_delta": _decimal_text(self.position_cost_delta),
            "reason": self.reason.value,
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True)
class PaperValuationMark:
    instrument_id: str
    price: Decimal
    mark_time: datetime
    available_time: datetime
    source: ValuationMarkSource
    source_version: str
    evidence_id: str

    def __post_init__(self) -> None:
        _instrument(self.instrument_id)
        _money(self.price, "price", positive=True)
        mark_time = _aware(self.mark_time, "mark_time")
        available_time = _aware(self.available_time, "available_time")
        if mark_time > available_time:
            raise PaperAccountValidationError("mark_time must not exceed mark available_time")
        if type(self.source) is not ValuationMarkSource:
            raise PaperAccountValidationError("source must be ValuationMarkSource")
        _text(self.source_version, "source_version")
        _text(self.evidence_id, "evidence_id")

    def payload(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "price": _decimal_text(self.price),
            "mark_time": _time_text(self.mark_time),
            "available_time": _time_text(self.available_time),
            "source": self.source.value,
            "source_version": self.source_version,
            "evidence_id": self.evidence_id,
        }


@dataclass(frozen=True, slots=True)
class RecordPaperValuation:
    metadata: PaperEventMetadata
    marks: tuple[PaperValuationMark, ...]

    def __post_init__(self) -> None:
        if type(self.marks) is not tuple:
            raise PaperAccountValidationError("marks must be an immutable tuple")
        instrument_ids = [mark.instrument_id for mark in self.marks]
        if len(set(instrument_ids)) != len(instrument_ids):
            raise PaperAccountValidationError("valuation marks must be unique by instrument")
        if any(mark.available_time > self.metadata.available_time for mark in self.marks):
            raise PaperAccountValidationError("future-available marks cannot enter a valuation")

    def payload(self) -> dict[str, object]:
        return {
            "type": type(self).__name__,
            "metadata": self.metadata.payload(),
            "marks": [mark.payload() for mark in self.marks],
        }


@dataclass(frozen=True, slots=True)
class ChangePaperAccountStatus:
    metadata: PaperEventMetadata
    target_status: PaperAccountStatus
    reason: str

    def __post_init__(self) -> None:
        if type(self.target_status) is not PaperAccountStatus:
            raise PaperAccountValidationError("target_status must be PaperAccountStatus")
        if self.target_status is PaperAccountStatus.ACTIVE and self.metadata.sequence == 0:
            raise PaperAccountValidationError("account opening uses OpenPaperAccount")
        _text(self.reason, "reason")

    def payload(self) -> dict[str, object]:
        return {
            "type": type(self).__name__,
            "metadata": self.metadata.payload(),
            "target_status": self.target_status.value,
            "reason": self.reason,
        }


PaperAccountEvent = (
    OpenPaperAccount | TransferPaperPosition | RecordPaperValuation | ChangePaperAccountStatus
)


def event_digest(event: PaperAccountEvent) -> str:
    return canonical_digest(event.payload())


@dataclass(frozen=True, slots=True)
class PaperPosition:
    instrument_id: str
    quantity: int
    available_quantity: int
    cost_amount: Decimal

    def __post_init__(self) -> None:
        _instrument(self.instrument_id)
        if type(self.quantity) is not int or self.quantity <= 0:
            raise PaperAccountValidationError("position quantity must be positive")
        if (
            type(self.available_quantity) is not int
            or self.available_quantity < 0
            or self.available_quantity > self.quantity
        ):
            raise PaperAccountValidationError("available quantity must be within total quantity")
        _money(self.cost_amount, "cost_amount")

    @property
    def average_cost(self) -> Decimal:
        return self.cost_amount / Decimal(self.quantity)

    def payload(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "quantity": self.quantity,
            "available_quantity": self.available_quantity,
            "cost_amount": _decimal_text(self.cost_amount),
            "average_cost": _decimal_text(self.average_cost),
        }


@dataclass(frozen=True, slots=True)
class PaperValuation:
    valuation_id: str
    valuation_time: datetime
    available_time: datetime
    cash: Decimal
    position_market_value: Decimal
    nav: Decimal
    marks: tuple[PaperValuationMark, ...]

    def __post_init__(self) -> None:
        _digest(self.valuation_id, "valuation_id")
        _aware(self.valuation_time, "valuation_time")
        _aware(self.available_time, "available_time")
        _money(self.cash, "cash")
        _money(self.position_market_value, "position_market_value")
        _money(self.nav, "nav")
        if self.cash + self.position_market_value != self.nav:
            raise PaperAccountValidationError("valuation NAV must equal cash plus market value")
        if type(self.marks) is not tuple:
            raise PaperAccountValidationError("valuation marks must be an immutable tuple")

    def payload(self, positions: tuple[PaperPosition, ...]) -> dict[str, object]:
        quantities = {position.instrument_id: position.quantity for position in positions}
        return {
            "valuationId": self.valuation_id,
            "valuationTime": _time_text(self.valuation_time),
            "availableTime": _time_text(self.available_time),
            "cash": _decimal_text(self.cash),
            "positionMarketValue": _decimal_text(self.position_market_value),
            "nav": _decimal_text(self.nav),
            "marks": [
                {
                    "instrumentId": mark.instrument_id,
                    "price": _decimal_text(mark.price),
                    "markTime": _time_text(mark.mark_time),
                    "availableTime": _time_text(mark.available_time),
                    "source": mark.source.value,
                    "sourceVersion": mark.source_version,
                    "evidenceId": mark.evidence_id,
                    "quantity": quantities[mark.instrument_id],
                    "marketValue": _decimal_text(
                        mark.price * Decimal(quantities[mark.instrument_id])
                    ),
                }
                for mark in self.marks
            ],
        }


@dataclass(frozen=True, slots=True)
class PaperAccountState:
    account_id: str
    owner_ref: str
    name: str
    status: PaperAccountStatus
    initial_capital: Decimal
    cash: Decimal
    positions: tuple[PaperPosition, ...]
    latest_valuation: PaperValuation | None
    data_cutoff_time: datetime
    event_count: int
    event_chain_digest: str
    state_digest: str = field(init=False)
    base_currency: str = field(default="CNY", init=False)
    execution_capability: str = field(default="PAPER_ONLY", init=False)

    def __post_init__(self) -> None:
        _digest(self.account_id, "account_id")
        _text(self.owner_ref, "owner_ref", 128)
        _text(self.name, "name", 80)
        if type(self.status) is not PaperAccountStatus:
            raise PaperAccountValidationError("status must be PaperAccountStatus")
        _money(self.initial_capital, "initial_capital", positive=True)
        _money(self.cash, "cash")
        if type(self.positions) is not tuple:
            raise PaperAccountValidationError("positions must be an immutable tuple")
        _aware(self.data_cutoff_time, "data_cutoff_time")
        if type(self.event_count) is not int or self.event_count < 1:
            raise PaperAccountValidationError("event_count must be positive")
        _digest(self.event_chain_digest, "event_chain_digest")
        if self.execution_capability != "PAPER_ONLY":
            raise PaperAccountValidationError("execution capability must remain PAPER_ONLY")
        object.__setattr__(self, "state_digest", canonical_digest(self.digest_payload()))

    def digest_payload(self) -> dict[str, object]:
        return {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "account_id": self.account_id,
            "owner_ref": self.owner_ref,
            "name": self.name,
            "status": self.status.value,
            "initial_capital": _decimal_text(self.initial_capital),
            "cash": _decimal_text(self.cash),
            "positions": [position.payload() for position in self.positions],
            "latest_valuation": (
                None
                if self.latest_valuation is None
                else self.latest_valuation.payload(self.positions)
            ),
            "data_cutoff_time": _time_text(self.data_cutoff_time),
            "event_count": self.event_count,
            "event_chain_digest": self.event_chain_digest,
            "execution_capability": self.execution_capability,
        }

    def snapshot(self, requested_as_of: datetime) -> dict[str, object]:
        requested = _aware(requested_as_of, "requested_as_of")
        return {
            "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
            "accountId": self.account_id,
            "name": self.name,
            "status": self.status.value,
            "baseCurrency": self.base_currency,
            "initialCapital": _decimal_text(self.initial_capital),
            "cash": _decimal_text(self.cash),
            "positions": [
                {
                    "instrumentId": position.instrument_id,
                    "quantity": position.quantity,
                    "availableQuantity": position.available_quantity,
                    "costAmount": _decimal_text(position.cost_amount),
                    "averageCost": _decimal_text(position.average_cost),
                }
                for position in self.positions
            ],
            "latestValuation": (
                None
                if self.latest_valuation is None
                else self.latest_valuation.payload(self.positions)
            ),
            "requestedAsOf": _time_text(requested),
            "dataCutoffTime": _time_text(self.data_cutoff_time),
            "eventCount": self.event_count,
            "eventChainDigest": self.event_chain_digest,
            "stateDigest": self.state_digest,
            "executionCapability": self.execution_capability,
            "dataMeaning": "SIMULATION_ONLY_NO_BROKER_PATH",
        }
