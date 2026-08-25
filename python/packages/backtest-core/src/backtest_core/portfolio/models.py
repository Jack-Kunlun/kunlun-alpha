"""Immutable, simulation-only portfolio accounting contracts."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Final, Protocol, cast

from backtest_core.engine import (
    BacktestValidationError,
    ExecutionCapability,
    canonical_digest,
    require_hex_digest,
)
from backtest_core.execution import (
    BatchMatchResult,
    FeeSchedule,
    InstrumentExecutionRules,
    MarketExecutionSnapshot,
    SameDaySellPolicy,
    SellabilitySnapshot,
    SimulationOrder,
    SlippageModel,
)

PORTFOLIO_SCHEMA_VERSION = "portfolio-accounting-v1"
VALUATION_SCHEMA_VERSION = "portfolio-valuation-v1"
CORPORATE_ACTION_SCHEMA_VERSION = "corporate-action-v1"
METADATA_SCHEMA_VERSION = "portfolio-event-metadata-v1"
ZERO_DIGEST: Final[str] = "0" * 64
SHANGHAI: Final = __import__("zoneinfo", fromlist=["ZoneInfo"]).ZoneInfo("Asia/Shanghai")


class PortfolioError(BacktestValidationError):
    """Base error for the portfolio accounting boundary."""


class PortfolioValidationError(PortfolioError, ValueError):
    """Raised when an immutable portfolio value is invalid."""


class DuplicateEventConflictError(PortfolioError):
    """Raised when an event id is reused with another event digest."""


class EventOrderError(PortfolioError):
    """Raised when the append-only journal contract is violated."""


class AccountingInvariantError(PortfolioError):
    """Raised when a double-entry or book-assets invariant fails."""


class TrustedReplayError(PortfolioError):
    """Raised when a P5-N11 result does not replay from trusted inputs."""


class ReceivableError(PortfolioError):
    """Raised for invalid receivable settlement."""


class CorporateActionError(PortfolioError):
    """Raised for unsupported or invalid corporate actions."""


class ValuationError(PortfolioError):
    """Raised when an accounting valuation mark is not admissible."""


class EventPhase(str, Enum):
    OPENING = "OPENING"
    RESERVATION = "RESERVATION"
    EXECUTION = "EXECUTION"
    RECEIVABLE_SETTLEMENT = "RECEIVABLE_SETTLEMENT"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    VALUATION = "VALUATION"


class AccountCode(str, Enum):
    CASH_AVAILABLE = "CASH_AVAILABLE"
    CASH_FROZEN = "CASH_FROZEN"
    RECEIVABLE_SALE = "RECEIVABLE_SALE"
    RECEIVABLE_DIVIDEND_CORPORATE = "RECEIVABLE_DIVIDEND_CORPORATE"
    POSITION_GROSS_COST = "POSITION_GROSS_COST"
    EQUITY_INITIAL_CAPITAL = "EQUITY_INITIAL_CAPITAL"
    REALIZED_PRICE_PNL = "REALIZED_PRICE_PNL"
    DIVIDEND_PNL = "DIVIDEND_PNL"
    OTHER_CORPORATE_ACTION_PNL = "OTHER_CORPORATE_ACTION_PNL"
    FEE_PNL = "FEE_PNL"


class ReceivableKind(str, Enum):
    SALE_PROCEEDS = "SALE_PROCEEDS"
    DIVIDEND_OR_CORPORATE = "DIVIDEND_OR_CORPORATE"


class CorporateActionType(str, Enum):
    CASH_DIVIDEND = "CASH_DIVIDEND"
    STOCK_DIVIDEND = "STOCK_DIVIDEND"
    CAPITALIZATION = "CAPITALIZATION"
    SPLIT = "SPLIT"
    CONSOLIDATION = "CONSOLIDATION"


class ValuationMarkSource(str, Enum):
    RAW_EXECUTABLE_QUOTE = "RAW_EXECUTABLE_QUOTE"
    RAW_MARKET_CLOSE = "RAW_MARKET_CLOSE"
    BAR_ADJUSTED = "BAR_ADJUSTED"
    NAV = "NAV"
    INAV = "INAV"
    REFERENCE_OVERLAY = "REFERENCE_OVERLAY"
    FILL_PRICE_FALLBACK = "FILL_PRICE_FALLBACK"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise PortfolioValidationError(f"{field_name} must be a non-empty string")
    return value


def _version(value: object, field_name: str) -> str:
    return _text(value, field_name)


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise PortfolioValidationError(f"{field_name} must be timezone-aware")
    return value


def _decimal(value: object, field_name: str, *, positive: bool = False) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise PortfolioValidationError(f"{field_name} must be a finite Decimal")
    if value < 0 or (positive and value <= 0):
        qualifier = "positive" if positive else "non-negative"
        raise PortfolioValidationError(f"{field_name} must be {qualifier}")
    return value


def _signed_decimal(value: object, field_name: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise PortfolioValidationError(f"{field_name} must be a finite Decimal")
    return value


def _integer(value: object, field_name: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < 0 or (positive and value <= 0):
        qualifier = "positive" if positive else "non-negative"
        raise PortfolioValidationError(f"{field_name} must be a {qualifier} integer")
    return value


def _digest(value: object, field_name: str, *, allow_zero: bool = False) -> str:
    try:
        result = require_hex_digest(value, field_name)
    except (BacktestValidationError, TypeError) as error:
        raise PortfolioValidationError(str(error)) from error
    if not allow_zero and result == ZERO_DIGEST:
        raise PortfolioValidationError(f"{field_name} must not be the empty digest")
    return result


def _tuple(value: object, field_name: str) -> tuple[object, ...]:
    if type(value) is not tuple:
        raise PortfolioValidationError(f"{field_name} must be an exact tuple")
    return cast(tuple[object, ...], value)


def _iso_date(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise PortfolioValidationError(f"{field_name} must be a canonical ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise PortfolioValidationError(f"{field_name} must be a canonical ISO date") from error
    if parsed.isoformat() != value:
        raise PortfolioValidationError(f"{field_name} must be a canonical ISO date")
    return value


def _enum(value: object, expected: type[Enum], field_name: str) -> Enum:
    if type(value) is not expected:
        raise PortfolioValidationError(f"{field_name} must be {expected.__name__}")
    return value


class _Validatable(Protocol):
    def validate_integrity(self) -> None: ...


class _EventWithMetadata(Protocol):
    metadata: EventMetadata


def _model[T](value: object, expected: type[T], field_name: str) -> T:
    if type(value) is not expected:
        raise PortfolioValidationError(f"{field_name} must be {expected.__name__}")
    typed = cast(T, value)
    validator = cast(_Validatable, typed).validate_integrity
    try:
        validator()
    except PortfolioValidationError:
        raise
    except (AttributeError, TypeError, ValueError) as error:
        raise PortfolioValidationError(f"{field_name} contains a forged value") from error
    return typed


def _phase_order(phase: EventPhase) -> int:
    return {
        EventPhase.OPENING: 0,
        EventPhase.RESERVATION: 10,
        EventPhase.EXECUTION: 20,
        EventPhase.CORPORATE_ACTION: 30,
        EventPhase.RECEIVABLE_SETTLEMENT: 40,
        EventPhase.VALUATION: 50,
    }[phase]


class RoundingMode(str, Enum):
    DOWN = "DOWN"
    UP = "UP"
    HALF_UP = "HALF_UP"
    HALF_EVEN = "HALF_EVEN"


@dataclass(frozen=True, slots=True)
class PortfolioHistoryRef:
    """Externally anchored identity of an append-only portfolio event tape."""

    tape_id: str
    expected_event_tape_digest: str
    expected_event_count: int

    def __post_init__(self) -> None:
        _text(self.tape_id, "history_ref.tape_id")
        _integer(self.expected_event_count, "history_ref.expected_event_count")
        _digest(
            self.expected_event_tape_digest,
            "history_ref.expected_event_tape_digest",
            allow_zero=self.expected_event_count == 0,
        )
        if self.expected_event_count == 0 and self.expected_event_tape_digest != ZERO_DIGEST:
            raise PortfolioValidationError("empty history must use ZERO_DIGEST")
        if self.expected_event_count > 0 and self.expected_event_tape_digest == ZERO_DIGEST:
            raise PortfolioValidationError("non-empty history must have a tape digest")

    @classmethod
    def genesis(cls, tape_id: str = "portfolio-genesis") -> PortfolioHistoryRef:
        return cls(tape_id, ZERO_DIGEST, 0)

    @property
    def event_tape_digest(self) -> str:
        return self.expected_event_tape_digest

    @property
    def event_count(self) -> int:
        return self.expected_event_count

    def validate_integrity(self) -> None:
        self.__post_init__()


def event_tape_digest(event_digests: tuple[str, ...]) -> str:
    return ZERO_DIGEST if not event_digests else canonical_digest(event_digests)


@dataclass(frozen=True, slots=True)
class EventMetadata:
    event_id: str
    logical_time: datetime
    event_phase: EventPhase
    source_id: str
    source_version: str
    source_sequence: int
    available_time: datetime
    previous_event_digest: str = ZERO_DIGEST
    expected_previous_state_digest: str = ZERO_DIGEST
    provenance_digest: str = ZERO_DIGEST
    config_digest: str = ZERO_DIGEST
    payload_digest: str = ZERO_DIGEST
    schema_version: str = METADATA_SCHEMA_VERSION
    event_digest: str = field(init=False)
    simulation_only: bool = field(default=True, init=False)
    execution_capability: ExecutionCapability = field(
        default=ExecutionCapability.BACKTEST_ONLY, init=False
    )

    def __post_init__(self) -> None:
        _text(self.event_id, "event_id")
        _aware(self.logical_time, "logical_time")
        _enum(self.event_phase, EventPhase, "event_phase")
        _text(self.source_id, "source_id")
        _version(self.source_version, "source_version")
        _integer(self.source_sequence, "source_sequence")
        available = _aware(self.available_time, "available_time")
        if available > self.logical_time:
            raise PortfolioValidationError("available_time must not exceed logical_time")
        for name in (
            "previous_event_digest",
            "expected_previous_state_digest",
            "provenance_digest",
            "config_digest",
        ):
            _digest(getattr(self, name), name, allow_zero=True)
        _digest(self.payload_digest, "payload_digest", allow_zero=True)
        if self.schema_version != METADATA_SCHEMA_VERSION:
            raise PortfolioValidationError("schema_version is not supported")
        if self.simulation_only is not True:
            raise PortfolioValidationError("simulation_only must be True")
        if self.execution_capability is not ExecutionCapability.BACKTEST_ONLY:
            raise PortfolioValidationError("execution_capability must be BACKTEST_ONLY")
        object.__setattr__(self, "event_digest", canonical_digest(self._payload()))

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "logical_time": self.logical_time.astimezone(UTC),
            "event_phase": self.event_phase,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "source_sequence": self.source_sequence,
            "available_time": self.available_time.astimezone(UTC),
            "previous_event_digest": self.previous_event_digest,
            "expected_previous_state_digest": self.expected_previous_state_digest,
            "provenance_digest": self.provenance_digest,
            "config_digest": self.config_digest,
            "payload_digest": self.payload_digest,
            "simulation_only": self.simulation_only,
            "execution_capability": self.execution_capability,
        }

    @property
    def phase(self) -> EventPhase:
        return self.event_phase

    @property
    def ordering_key(self) -> tuple[datetime, int, str, int, str]:
        return (
            self.logical_time.astimezone(UTC),
            _phase_order(self.event_phase),
            self.source_id,
            self.source_sequence,
            self.event_id,
        )

    @classmethod
    def for_event(
        cls,
        *,
        event_id: str,
        logical_time: datetime,
        event_phase: EventPhase,
        source_id: str,
        source_version: str,
        source_sequence: int,
        expected_previous_state_digest: str,
        previous_event_digest: str,
        provenance_digest: str,
        config_digest: str,
        payload: object | None = None,
        available_time: datetime | None = None,
    ) -> EventMetadata:
        effective_available = logical_time if available_time is None else available_time
        payload_digest = ZERO_DIGEST if payload is None else canonical_digest(payload)
        return cls(
            event_id=event_id,
            logical_time=logical_time,
            event_phase=event_phase,
            source_id=source_id,
            source_version=source_version,
            source_sequence=source_sequence,
            available_time=effective_available,
            previous_event_digest=previous_event_digest,
            expected_previous_state_digest=expected_previous_state_digest,
            provenance_digest=provenance_digest,
            config_digest=config_digest,
            payload_digest=payload_digest,
        )

    def validate_integrity(self) -> None:
        original = self.event_digest
        self.__post_init__()
        expected = canonical_digest(self._payload())
        if original != expected:
            raise PortfolioValidationError("event metadata integrity mismatch")


@dataclass(frozen=True, slots=True)
class ReservationPolicy:
    policy_id: str
    policy_version: str
    policy_digest: str

    def __post_init__(self) -> None:
        _text(self.policy_id, "policy_id")
        _version(self.policy_version, "policy_version")
        _digest(self.policy_digest, "policy_digest")


@dataclass(frozen=True, slots=True)
class BuyCashReservation:
    order_id: str
    order_digest: str
    fee_schedule_digest: str
    artifact_id: str
    execution_input_digest: str
    policy_id: str
    policy_version: str
    policy_digest: str
    reservation_logical_time: datetime
    maximum_debit: Decimal

    def __post_init__(self) -> None:
        _text(self.order_id, "reservation.order_id")
        _digest(self.order_digest, "reservation.order_digest")
        _digest(self.fee_schedule_digest, "reservation.fee_schedule_digest")
        _text(self.artifact_id, "reservation.artifact_id")
        _digest(self.execution_input_digest, "reservation.execution_input_digest")
        _text(self.policy_id, "reservation.policy_id")
        _version(self.policy_version, "reservation.policy_version")
        _digest(self.policy_digest, "reservation.policy_digest")
        _aware(self.reservation_logical_time, "reservation_logical_time")
        _decimal(self.maximum_debit, "reservation.maximum_debit", positive=True)

    @property
    def reservation_digest(self) -> str:
        return canonical_digest(self._payload())

    def _payload(self) -> dict[str, object]:
        return {
            "order_id": self.order_id,
            "order_digest": self.order_digest,
            "fee_schedule_digest": self.fee_schedule_digest,
            "artifact_id": self.artifact_id,
            "execution_input_digest": self.execution_input_digest,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_digest": self.policy_digest,
            "reservation_logical_time": self.reservation_logical_time.astimezone(UTC),
            "maximum_debit": self.maximum_debit,
        }

    def validate_integrity(self) -> None:
        self.__post_init__()


@dataclass(frozen=True, slots=True)
class NextTradingDateResolution:
    calendar_id: str
    calendar_version: str
    calendar_digest: str
    trading_date: str
    next_trading_date: str
    available_time: datetime
    match_time: datetime | None = None
    provenance_available_time: datetime | None = None
    resolution_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.calendar_id, "calendar_id")
        _version(self.calendar_version, "calendar_version")
        _digest(self.calendar_digest, "calendar_digest")
        trading = _iso_date(self.trading_date, "trading_date")
        next_date = _iso_date(self.next_trading_date, "next_trading_date")
        if next_date <= trading:
            raise PortfolioValidationError("next_trading_date must be after trading_date")
        available = _aware(self.available_time, "available_time")
        boundary: datetime | None = None
        if self.match_time is not None:
            boundary = _aware(self.match_time, "match_time")
            if available > boundary:
                raise PortfolioValidationError("resolution is not available by match_time")
        if self.provenance_available_time is not None:
            provenance_available = _aware(
                self.provenance_available_time, "provenance_available_time"
            )
            if boundary is not None and provenance_available > boundary:
                raise PortfolioValidationError("resolution provenance is future data")
        object.__setattr__(self, "resolution_digest", canonical_digest(self._payload()))

    def _payload(self) -> dict[str, object]:
        return {
            "calendar_id": self.calendar_id,
            "calendar_version": self.calendar_version,
            "calendar_digest": self.calendar_digest,
            "trading_date": self.trading_date,
            "next_trading_date": self.next_trading_date,
            "available_time": self.available_time.astimezone(UTC),
            "match_time": None if self.match_time is None else self.match_time.astimezone(UTC),
            "provenance_available_time": (
                None
                if self.provenance_available_time is None
                else self.provenance_available_time.astimezone(UTC)
            ),
        }

    def validate_integrity(self) -> None:
        original = self.resolution_digest
        self.__post_init__()
        if original != canonical_digest(self._payload()):
            raise PortfolioValidationError("resolution integrity mismatch")

    @property
    def digest(self) -> str:
        return self.resolution_digest


@dataclass(frozen=True, slots=True)
class LotCostAllocationPolicy:
    policy_id: str = "fifo-cost"
    policy_version: str = "1.0.0"
    quantum: Decimal = Decimal("0.01")
    rounding_mode: RoundingMode = RoundingMode.DOWN
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.policy_id, "lot_cost.policy_id")
        _version(self.policy_version, "lot_cost.policy_version")
        _decimal(self.quantum, "lot_cost.quantum", positive=True)
        _enum(self.rounding_mode, RoundingMode, "lot_cost.rounding_mode")
        object.__setattr__(self, "policy_digest", canonical_digest(self._payload()))

    def _payload(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "quantum": self.quantum,
            "rounding_mode": self.rounding_mode,
        }

    def validate_integrity(self) -> None:
        original = self.policy_digest
        self.__post_init__()
        if original != canonical_digest(self._payload()):
            raise PortfolioValidationError("lot cost policy integrity mismatch")


@dataclass(frozen=True, slots=True)
class PortfolioLot:
    lot_id: str
    instrument_code: str
    acquisition_trade_date: str
    acquisition_time: datetime
    sellable_from_trade_date: str
    remaining_quantity: int
    gross_cost: Decimal
    available_time: datetime
    source_order_id: str
    source_fill_ids: tuple[str, ...]
    lineage_digest: str

    def __post_init__(self) -> None:
        _text(self.lot_id, "lot_id")
        _text(self.instrument_code, "instrument_code")
        acquisition = _iso_date(self.acquisition_trade_date, "acquisition_trade_date")
        acquisition_time = _aware(self.acquisition_time, "acquisition_time")
        if acquisition_time.astimezone(SHANGHAI).date().isoformat() != acquisition:
            raise PortfolioValidationError("acquisition_time must belong to acquisition_trade_date")
        sellable = _iso_date(self.sellable_from_trade_date, "sellable_from_trade_date")
        if sellable < acquisition:
            raise PortfolioValidationError("sellable_from_trade_date precedes acquisition")
        _integer(self.remaining_quantity, "remaining_quantity", positive=True)
        _decimal(self.gross_cost, "gross_cost")
        _aware(self.available_time, "available_time")
        _text(self.source_order_id, "source_order_id")
        raw_ids = _tuple(self.source_fill_ids, "source_fill_ids")
        fill_ids = tuple(_text(item, "source_fill_id") for item in raw_ids)
        if fill_ids != tuple(sorted(set(fill_ids))):
            raise PortfolioValidationError("source_fill_ids must be sorted and unique")
        _digest(self.lineage_digest, "lineage_digest")

    @property
    def quantity(self) -> int:
        return self.remaining_quantity

    @property
    def cost(self) -> Decimal:
        return self.gross_cost

    def validate_integrity(self) -> None:
        self.__post_init__()


@dataclass(frozen=True, slots=True)
class CashReceivable:
    receivable_id: str
    kind: ReceivableKind
    instrument_code: str
    amount: Decimal
    due_time: datetime
    source_event_id: str
    provenance_digest: str

    def __post_init__(self) -> None:
        _digest(self.receivable_id, "receivable_id")
        _enum(self.kind, ReceivableKind, "receivable.kind")
        _text(self.instrument_code, "receivable.instrument_code")
        _decimal(self.amount, "receivable.amount", positive=True)
        _aware(self.due_time, "receivable.due_time")
        _text(self.source_event_id, "receivable.source_event_id")
        _digest(self.provenance_digest, "receivable.provenance_digest", allow_zero=True)

    def validate_integrity(self) -> None:
        self.__post_init__()


@dataclass(frozen=True, slots=True)
class AppliedEventRecord:
    event_id: str
    event_digest: str

    def __post_init__(self) -> None:
        _text(self.event_id, "applied.event_id")
        _digest(self.event_digest, "applied.event_digest")

    def validate_integrity(self) -> None:
        self.__post_init__()


@dataclass(frozen=True, slots=True)
class CorporateActionTerms:
    cash_amount_per_share: Decimal | None = None
    amount_per_share: Decimal | None = None
    ratio_numerator: int | None = None
    ratio_denominator: int | None = None
    cash_in_lieu_amount: Decimal | None = None
    cash_in_lieu_cost: Decimal | None = None
    cash_in_lieu_quantity: int | None = None
    sellable_from_time: datetime | None = None

    def __post_init__(self) -> None:
        if self.cash_amount_per_share is not None:
            _decimal(self.cash_amount_per_share, "terms.cash_amount_per_share", positive=True)
        if self.amount_per_share is not None:
            _decimal(self.amount_per_share, "terms.amount_per_share", positive=True)
        if (
            self.cash_amount_per_share is not None
            and self.amount_per_share is not None
            and self.cash_amount_per_share != self.amount_per_share
        ):
            raise CorporateActionError("dividend amount aliases disagree")
        if self.ratio_numerator is not None:
            _integer(self.ratio_numerator, "terms.ratio_numerator", positive=True)
        if self.ratio_denominator is not None:
            _integer(self.ratio_denominator, "terms.ratio_denominator", positive=True)
        if (self.ratio_numerator is None) != (self.ratio_denominator is None):
            raise CorporateActionError("ratio numerator and denominator are both required")
        if self.cash_in_lieu_amount is not None:
            _decimal(self.cash_in_lieu_amount, "terms.cash_in_lieu_amount", positive=True)
        if self.cash_in_lieu_cost is not None:
            _decimal(self.cash_in_lieu_cost, "terms.cash_in_lieu_cost")
        if self.cash_in_lieu_quantity is not None:
            _integer(self.cash_in_lieu_quantity, "terms.cash_in_lieu_quantity", positive=True)
        if self.sellable_from_time is not None:
            _aware(self.sellable_from_time, "terms.sellable_from_time")

    @property
    def dividend_amount_per_share(self) -> Decimal | None:
        return self.cash_amount_per_share or self.amount_per_share

    @property
    def digest(self) -> str:
        return canonical_digest(self._payload())

    def _payload(self) -> dict[str, object]:
        return {
            "cash_amount_per_share": self.cash_amount_per_share,
            "amount_per_share": self.amount_per_share,
            "ratio_numerator": self.ratio_numerator,
            "ratio_denominator": self.ratio_denominator,
            "cash_in_lieu_amount": self.cash_in_lieu_amount,
            "cash_in_lieu_cost": self.cash_in_lieu_cost,
            "cash_in_lieu_quantity": self.cash_in_lieu_quantity,
            "sellable_from_time": None
            if self.sellable_from_time is None
            else self.sellable_from_time.astimezone(UTC),
        }

    def validate_integrity(self) -> None:
        self.__post_init__()


CashDividendTerms = CorporateActionTerms
StockDividendTerms = CorporateActionTerms
SplitTerms = CorporateActionTerms
ConsolidationTerms = CorporateActionTerms


@dataclass(frozen=True, slots=True)
class CorporateActionRecord:
    schema_version: str
    action_version: str
    lineage_id: str
    instrument_code: str
    action_type: CorporateActionType
    publish_time: datetime
    event_time: datetime
    available_time: datetime
    record_time: datetime | None
    effective_time: datetime | None
    pay_time: datetime | None
    listing_time: datetime | None
    source_id: str
    source_version: str
    raw_capture_id: str
    action_id: str
    raw_capture_digest: str
    provenance_digest: str
    terms_digest: str
    terms: CorporateActionTerms
    action_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != CORPORATE_ACTION_SCHEMA_VERSION:
            raise CorporateActionError("unsupported corporate action schema")
        _version(self.action_version, "action_version")
        _text(self.lineage_id, "lineage_id")
        _text(self.instrument_code, "instrument_code")
        _enum(self.action_type, CorporateActionType, "action_type")
        publish = _aware(self.publish_time, "publish_time")
        event = _aware(self.event_time, "event_time")
        available = _aware(self.available_time, "available_time")
        if publish > event:
            raise CorporateActionError("publish_time must not exceed event_time")
        if available < publish:
            raise CorporateActionError("available_time must not precede publish_time")
        for name in ("record_time", "effective_time", "pay_time", "listing_time"):
            value = getattr(self, name)
            if value is not None:
                _aware(value, name)
        if self.record_time is not None and available > self.record_time:
            raise CorporateActionError("available_time must be no later than record_time")
        if self.effective_time is not None and available > self.effective_time:
            raise CorporateActionError("available_time must be no later than effective_time")
        if (
            self.pay_time is not None
            and self.record_time is not None
            and self.pay_time < self.record_time
        ):
            raise CorporateActionError("pay_time must not precede record_time")
        if (
            self.listing_time is not None
            and self.effective_time is not None
            and self.listing_time < self.effective_time
        ):
            raise CorporateActionError("listing_time must not precede effective_time")
        _text(self.source_id, "source_id")
        _version(self.source_version, "source_version")
        _text(self.raw_capture_id, "raw_capture_id")
        _text(self.action_id, "action_id")
        _digest(self.raw_capture_digest, "raw_capture_digest")
        _digest(self.provenance_digest, "provenance_digest")
        _digest(self.terms_digest, "terms_digest")
        terms = _model(self.terms, CorporateActionTerms, "terms")
        if terms.digest != self.terms_digest:
            raise CorporateActionError("terms_digest does not match terms")
        if self.action_type is CorporateActionType.CASH_DIVIDEND:
            if terms.dividend_amount_per_share is None or self.record_time is None:
                raise CorporateActionError("cash dividend requires record time and amount")
        else:
            if terms.ratio_numerator is None or terms.ratio_denominator is None:
                raise CorporateActionError("stock action requires an explicit ratio")
        if (
            self.action_type
            in (
                CorporateActionType.STOCK_DIVIDEND,
                CorporateActionType.CAPITALIZATION,
            )
            and terms.ratio_numerator is not None
            and terms.ratio_denominator is not None
            and terms.ratio_numerator > terms.ratio_denominator
            and terms.sellable_from_time is None
            and self.listing_time is None
        ):
            raise CorporateActionError("new shares require an explicit sellable/listing time")
        object.__setattr__(self, "action_digest", canonical_digest(self._payload()))

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "action_version": self.action_version,
            "lineage_id": self.lineage_id,
            "instrument_code": self.instrument_code,
            "action_type": self.action_type,
            "publish_time": self.publish_time.astimezone(UTC),
            "event_time": self.event_time.astimezone(UTC),
            "available_time": self.available_time.astimezone(UTC),
            "record_time": None if self.record_time is None else self.record_time.astimezone(UTC),
            "effective_time": None
            if self.effective_time is None
            else self.effective_time.astimezone(UTC),
            "pay_time": None if self.pay_time is None else self.pay_time.astimezone(UTC),
            "listing_time": None
            if self.listing_time is None
            else self.listing_time.astimezone(UTC),
            "source_id": self.source_id,
            "source_version": self.source_version,
            "raw_capture_id": self.raw_capture_id,
            "action_id": self.action_id,
            "raw_capture_digest": self.raw_capture_digest,
            "provenance_digest": self.provenance_digest,
            "terms_digest": self.terms_digest,
            "terms": self.terms,
        }

    @property
    def digest(self) -> str:
        return self.action_digest

    def validate_integrity(self) -> None:
        original = self.action_digest
        self.__post_init__()
        if original != canonical_digest(self._payload()):
            raise CorporateActionError("corporate action digest mismatch")


@dataclass(frozen=True, slots=True)
class CorporateActionApplication:
    source_id: str
    raw_capture_id: str
    action_id: str
    lineage_id: str
    action_version: str
    action_digest: str
    entitlement_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.source_id, "application.source_id")
        _text(self.raw_capture_id, "application.raw_capture_id")
        _text(self.action_id, "application.action_id")
        _text(self.lineage_id, "application.lineage_id")
        _version(self.action_version, "application.action_version")
        _digest(self.action_digest, "application.action_digest")
        values = _tuple(self.entitlement_ids, "application.entitlement_ids")
        ids = tuple(_digest(item, "entitlement_id") for item in values)
        if ids != tuple(sorted(set(ids))):
            raise CorporateActionError("entitlement_ids must be sorted and unique")

    def validate_integrity(self) -> None:
        self.__post_init__()


@dataclass(frozen=True, slots=True)
class ValuationPolicy:
    policy_id: str = "raw-accounting-mark"
    policy_version: str = "1.0.0"
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.policy_id, "valuation.policy_id")
        _version(self.policy_version, "valuation.policy_version")
        object.__setattr__(self, "policy_digest", canonical_digest(self._payload()))

    def _payload(self) -> dict[str, str]:
        return {"policy_id": self.policy_id, "policy_version": self.policy_version}

    def validate_integrity(self) -> None:
        self.__post_init__()
        if self.policy_digest != canonical_digest(self._payload()):
            raise ValuationError("valuation policy digest mismatch")


@dataclass(frozen=True, slots=True)
class ValuationMark:
    instrument_code: str
    mark_time: datetime
    available_time: datetime
    price: Decimal
    source: ValuationMarkSource
    source_id: str
    source_version: str
    provenance_digest: str
    provenance_available_time: datetime | None = None
    mark_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.instrument_code, "mark.instrument_code")
        _aware(self.mark_time, "mark.mark_time")
        _aware(self.available_time, "mark.available_time")
        _decimal(self.price, "mark.price", positive=True)
        _enum(self.source, ValuationMarkSource, "mark.source")
        _text(self.source_id, "mark.source_id")
        _version(self.source_version, "mark.source_version")
        _digest(self.provenance_digest, "mark.provenance_digest")
        if self.provenance_available_time is not None:
            _aware(self.provenance_available_time, "mark.provenance_available_time")
        object.__setattr__(self, "mark_digest", canonical_digest(self._payload()))

    def _payload(self) -> dict[str, object]:
        return {
            "instrument_code": self.instrument_code,
            "mark_time": self.mark_time.astimezone(UTC),
            "available_time": self.available_time.astimezone(UTC),
            "price": self.price,
            "source": self.source,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "provenance_digest": self.provenance_digest,
            "provenance_available_time": None
            if self.provenance_available_time is None
            else self.provenance_available_time.astimezone(UTC),
        }

    @property
    def digest(self) -> str:
        return self.mark_digest

    def validate_integrity(self) -> None:
        self.__post_init__()
        if self.mark_digest != canonical_digest(self._payload()):
            raise ValuationError("valuation mark digest mismatch")


@dataclass(frozen=True, slots=True)
class PortfolioValuation:
    cutoff_time: datetime
    initial_capital: Decimal
    available_cash: Decimal
    frozen_cash: Decimal
    sale_cash_receivable: Decimal
    dividend_or_corporate_cash_receivable: Decimal
    raw_marked_position_value: Decimal
    book_position_cost: Decimal
    nav: Decimal
    realized_price_pnl: Decimal
    unrealized_price_pnl: Decimal
    dividend_pnl: Decimal
    other_corporate_action_pnl: Decimal
    fee_pnl: Decimal
    total_pnl: Decimal
    complete_mark_coverage: bool
    valuation_policy_id: str
    valuation_policy_version: str
    valuation_policy_digest: str
    input_digest: str
    state_digest: str
    sample_count: int
    schema_version: str = VALUATION_SCHEMA_VERSION
    algorithm_version: str = "1.0.0"
    simulation_only: bool = field(default=True, init=False)
    execution_capability: ExecutionCapability = field(
        default=ExecutionCapability.BACKTEST_ONLY, init=False
    )

    def __post_init__(self) -> None:
        _aware(self.cutoff_time, "valuation.cutoff_time")
        for name in (
            "initial_capital",
            "available_cash",
            "frozen_cash",
            "sale_cash_receivable",
            "dividend_or_corporate_cash_receivable",
            "raw_marked_position_value",
            "book_position_cost",
            "nav",
        ):
            _decimal(getattr(self, name), f"valuation.{name}")
        for name in (
            "realized_price_pnl",
            "unrealized_price_pnl",
            "dividend_pnl",
            "other_corporate_action_pnl",
            "fee_pnl",
            "total_pnl",
        ):
            _signed_decimal(getattr(self, name), f"valuation.{name}")
        if type(self.complete_mark_coverage) is not bool:
            raise ValuationError("complete_mark_coverage must be boolean")
        for name in ("valuation_policy_id", "valuation_policy_version"):
            _text(getattr(self, name), name)
        _digest(self.valuation_policy_digest, "valuation_policy_digest")
        _digest(self.input_digest, "input_digest")
        _digest(self.state_digest, "state_digest")
        _integer(self.sample_count, "sample_count")
        if self.schema_version != VALUATION_SCHEMA_VERSION:
            raise ValuationError("unsupported valuation schema")
        _version(self.algorithm_version, "algorithm_version")
        if (
            self.simulation_only is not True
            or self.execution_capability is not ExecutionCapability.BACKTEST_ONLY
        ):
            raise ValuationError("valuation must remain simulation-only")
        if (
            self.nav
            != self.available_cash
            + self.frozen_cash
            + self.sale_cash_receivable
            + self.dividend_or_corporate_cash_receivable
            + self.raw_marked_position_value
        ):
            raise ValuationError("valuation NAV assets do not reconcile")
        if self.unrealized_price_pnl != self.raw_marked_position_value - self.book_position_cost:
            raise ValuationError("valuation unrealized PnL does not reconcile")
        if self.total_pnl != self.nav - self.initial_capital:
            raise ValuationError("valuation total PnL does not reconcile to initial capital")
        if (
            self.total_pnl
            != self.realized_price_pnl
            + self.unrealized_price_pnl
            + self.dividend_pnl
            + self.other_corporate_action_pnl
            + self.fee_pnl
        ):
            raise ValuationError("valuation PnL decomposition does not reconcile")

    def validate_integrity(self) -> None:
        self.__post_init__()

    @property
    def book_assets(self) -> Decimal:
        return (
            self.available_cash
            + self.frozen_cash
            + self.sale_cash_receivable
            + self.dividend_or_corporate_cash_receivable
            + self.book_position_cost
        )


@dataclass(frozen=True, slots=True)
class LedgerPosting:
    account: AccountCode
    debit: Decimal
    credit: Decimal
    reference_id: str

    def __post_init__(self) -> None:
        _enum(self.account, AccountCode, "posting.account")
        _decimal(self.debit, "posting.debit")
        _decimal(self.credit, "posting.credit")
        _text(self.reference_id, "posting.reference_id")
        if self.debit > 0 and self.credit > 0:
            raise AccountingInvariantError("a posting cannot have both debit and credit")

    def validate_integrity(self) -> None:
        self.__post_init__()


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    metadata: EventMetadata
    event_type: str
    postings: tuple[LedgerPosting, ...]
    payload_digest: str
    simulation_only: bool = field(default=True, init=False)
    execution_capability: ExecutionCapability = field(
        default=ExecutionCapability.BACKTEST_ONLY, init=False
    )

    def __post_init__(self) -> None:
        _model(self.metadata, EventMetadata, "ledger.metadata")
        _text(self.event_type, "ledger.event_type")
        raw = _tuple(self.postings, "ledger.postings")
        for item in raw:
            _model(item, LedgerPosting, "ledger.posting")
        _digest(self.payload_digest, "ledger.payload_digest", allow_zero=True)
        if self.payload_digest != self.metadata.payload_digest:
            raise AccountingInvariantError("ledger payload digest is not bound to metadata")
        if self.total_debits != self.total_credits:
            raise AccountingInvariantError("ledger debits and credits are not equal")

    @property
    def event_digest(self) -> str:
        return self.metadata.event_digest

    @property
    def total_debits(self) -> Decimal:
        return sum((item.debit for item in self.postings), Decimal("0"))

    @property
    def total_credits(self) -> Decimal:
        return sum((item.credit for item in self.postings), Decimal("0"))

    def validate_integrity(self) -> None:
        self.__post_init__()


@dataclass(frozen=True, slots=True)
class InitialCapitalEvent:
    metadata: EventMetadata
    amount: Decimal
    currency: str = "CNY"
    simulation_only: bool = field(default=True, init=False)
    execution_capability: ExecutionCapability = field(
        default=ExecutionCapability.BACKTEST_ONLY, init=False
    )

    def __post_init__(self) -> None:
        _model(self.metadata, EventMetadata, "initial.metadata")
        _decimal(self.amount, "initial.amount", positive=True)
        if self.currency != "CNY":
            raise PortfolioValidationError("initial capital currency must be CNY")
        _bind_event_metadata(self, self._payload())
        _event_safety(self.simulation_only, self.execution_capability)

    def _payload(self) -> dict[str, object]:
        return {
            "event_type": "INITIAL_CAPITAL",
            "amount": self.amount,
            "currency": self.currency,
        }

    @property
    def event_digest(self) -> str:
        return self.metadata.event_digest

    @property
    def ordering_key(self) -> tuple[datetime, int, str, int, str]:
        return self.metadata.ordering_key

    def validate_integrity(self) -> None:
        self.__post_init__()
        _check_event_metadata(self.metadata, self._payload())


@dataclass(frozen=True, slots=True)
class BuyCashReservationEvent:
    metadata: EventMetadata
    reservation: BuyCashReservation
    simulation_only: bool = field(default=True, init=False)
    execution_capability: ExecutionCapability = field(
        default=ExecutionCapability.BACKTEST_ONLY, init=False
    )

    def __post_init__(self) -> None:
        _model(self.metadata, EventMetadata, "reservation.metadata")
        _model(self.reservation, BuyCashReservation, "reservation")
        if self.reservation.reservation_logical_time != self.metadata.logical_time:
            raise PortfolioValidationError("reservation logical time must match metadata")
        _bind_event_metadata(self, self._payload())
        _event_safety(self.simulation_only, self.execution_capability)

    def _payload(self) -> dict[str, object]:
        return {"event_type": "BUY_CASH_RESERVATION", "reservation": self.reservation}

    @property
    def event_digest(self) -> str:
        return self.metadata.event_digest

    @property
    def ordering_key(self) -> tuple[datetime, int, str, int, str]:
        return self.metadata.ordering_key

    def validate_integrity(self) -> None:
        self.__post_init__()
        _check_event_metadata(self.metadata, self._payload())


@dataclass(frozen=True, slots=True)
class ReservationReleaseEvent:
    metadata: EventMetadata
    order_id: str
    simulation_only: bool = field(default=True, init=False)
    execution_capability: ExecutionCapability = field(
        default=ExecutionCapability.BACKTEST_ONLY, init=False
    )

    def __post_init__(self) -> None:
        _model(self.metadata, EventMetadata, "release.metadata")
        _text(self.order_id, "release.order_id")
        _bind_event_metadata(self, self._payload())
        _event_safety(self.simulation_only, self.execution_capability)

    def _payload(self) -> dict[str, object]:
        return {"event_type": "RESERVATION_RELEASE", "order_id": self.order_id}

    @property
    def event_digest(self) -> str:
        return self.metadata.event_digest

    @property
    def ordering_key(self) -> tuple[datetime, int, str, int, str]:
        return self.metadata.ordering_key

    def validate_integrity(self) -> None:
        self.__post_init__()
        _check_event_metadata(self.metadata, self._payload())


@dataclass(frozen=True, slots=True)
class ExecutionArtifactRef:
    """Engine-owned reference; it deliberately contains no replay inputs."""

    artifact_id: str
    expected_input_digest: str

    def __post_init__(self) -> None:
        _text(self.artifact_id, "artifact_ref.artifact_id")
        _digest(self.expected_input_digest, "artifact_ref.expected_input_digest")

    def validate_integrity(self) -> None:
        self.__post_init__()


def _execution_input_payload(value: TrustedExecutionInputs) -> dict[str, object]:
    return {
        "orders": value.orders,
        "snapshot": value.snapshot,
        "rules": value.rules,
        "sellability": value.sellability,
        "fee_schedule": value.fee_schedule,
        "slippage_model": value.slippage_model,
        "external_source_digest": value.external_source_digest,
        "external_config_digest": value.external_config_digest,
        "next_trading_date_resolution": value.next_trading_date_resolution,
    }


@dataclass(frozen=True, slots=True)
class TrustedExecutionInputs:
    """The exact P5-N11 inputs returned by an injected artifact source."""

    artifact_id: str
    orders: tuple[SimulationOrder, ...]
    snapshot: MarketExecutionSnapshot
    rules: InstrumentExecutionRules
    sellability: SellabilitySnapshot | None
    fee_schedule: FeeSchedule
    slippage_model: SlippageModel
    external_source_digest: str
    external_config_digest: str
    next_trading_date_resolution: NextTradingDateResolution | None = None
    input_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.artifact_id, "trusted_inputs.artifact_id")
        raw_orders = _tuple(self.orders, "trusted_inputs.orders")
        orders = tuple(_model(item, SimulationOrder, "trusted_inputs.order") for item in raw_orders)
        if not orders:
            raise TrustedReplayError("trusted execution orders must not be empty")
        order_ids = tuple(item.order_id for item in orders)
        if order_ids != tuple(sorted(set(order_ids))):
            raise TrustedReplayError("trusted execution orders must be sorted and unique")
        snapshot = _model(self.snapshot, MarketExecutionSnapshot, "trusted_inputs.snapshot")
        rules = _model(self.rules, InstrumentExecutionRules, "trusted_inputs.rules")
        if rules.instrument_code != snapshot.instrument_code:
            raise TrustedReplayError("trusted rules and snapshot instrument differ")
        if self.sellability is not None:
            _model(self.sellability, SellabilitySnapshot, "trusted_inputs.sellability")
        _model(self.fee_schedule, FeeSchedule, "trusted_inputs.fee_schedule")
        _model(self.slippage_model, SlippageModel, "trusted_inputs.slippage_model")
        _digest(self.external_source_digest, "trusted_inputs.external_source_digest")
        _digest(self.external_config_digest, "trusted_inputs.external_config_digest")
        if self.external_source_digest != snapshot.source.digest:
            raise TrustedReplayError("trusted source digest does not match snapshot source")
        if self.next_trading_date_resolution is not None:
            resolution = _model(
                self.next_trading_date_resolution,
                NextTradingDateResolution,
                "trusted_inputs.calendar",
            )
            if resolution.calendar_id != snapshot.calendar_id:
                raise TrustedReplayError("calendar id does not match execution snapshot")
            if resolution.calendar_version != snapshot.calendar_version:
                raise TrustedReplayError("calendar version does not match execution snapshot")
            if resolution.calendar_digest != snapshot.calendar_digest:
                raise TrustedReplayError("calendar digest does not match execution snapshot")
            if resolution.trading_date != snapshot.trading_date:
                raise TrustedReplayError("calendar source trading date does not match snapshot")
            if resolution.available_time > snapshot.match_time:
                raise TrustedReplayError("calendar resolution is future data")
            if (
                resolution.provenance_available_time is not None
                and resolution.provenance_available_time > snapshot.match_time
            ):
                raise TrustedReplayError("calendar provenance is future data")
            if resolution.match_time is not None and resolution.match_time != snapshot.match_time:
                raise TrustedReplayError("calendar match boundary does not match snapshot")
        elif rules.same_day_sell_policy is SameDaySellPolicy.T_PLUS_1:
            raise TrustedReplayError("T_PLUS_1 requires a trusted calendar resolution")
        object.__setattr__(self, "input_digest", canonical_digest(_execution_input_payload(self)))

    @property
    def trusted_input_digest(self) -> str:
        return self.input_digest

    def validate_integrity(self) -> None:
        original = self.input_digest
        self.__post_init__()
        if original != canonical_digest(_execution_input_payload(self)):
            raise TrustedReplayError("trusted execution input digest mismatch")


@dataclass(frozen=True, slots=True)
class ExecutionReplayBundle:
    artifact_ref: ExecutionArtifactRef
    candidate: BatchMatchResult
    bundle_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _model(self.artifact_ref, ExecutionArtifactRef, "bundle.artifact_ref")
        try:
            _model(self.candidate, BatchMatchResult, "bundle.candidate")
        except Exception as error:
            raise TrustedReplayError("bundle candidate contains a forged value") from error
        object.__setattr__(self, "bundle_digest", canonical_digest(self._payload()))

    def _payload(self) -> dict[str, object]:
        return {
            "artifact_ref": self.artifact_ref,
            "candidate": self.candidate,
        }

    @property
    def digest(self) -> str:
        return self.bundle_digest

    def validate_integrity(self) -> None:
        original = self.bundle_digest
        self.__post_init__()
        if original != canonical_digest(self._payload()):
            raise TrustedReplayError("bundle digest mismatch")


@dataclass(frozen=True, slots=True)
class ExecutionSettlementEvent:
    metadata: EventMetadata
    bundle: ExecutionReplayBundle
    lot_cost_policy: LotCostAllocationPolicy = field(default_factory=LotCostAllocationPolicy)
    simulation_only: bool = field(default=True, init=False)
    execution_capability: ExecutionCapability = field(
        default=ExecutionCapability.BACKTEST_ONLY, init=False
    )

    def __post_init__(self) -> None:
        _model(self.metadata, EventMetadata, "settlement.metadata")
        _model(self.bundle, ExecutionReplayBundle, "settlement.bundle")
        _model(self.lot_cost_policy, LotCostAllocationPolicy, "settlement.lot_cost_policy")
        _bind_event_metadata(self, self._payload())
        _event_safety(self.simulation_only, self.execution_capability)

    def _payload(self) -> dict[str, object]:
        return {
            "event_type": "EXECUTION_SETTLEMENT",
            "bundle": self.bundle,
            "lot_cost_policy": self.lot_cost_policy,
        }

    @property
    def event_digest(self) -> str:
        return self.metadata.event_digest

    @property
    def ordering_key(self) -> tuple[datetime, int, str, int, str]:
        return self.metadata.ordering_key

    def validate_integrity(self) -> None:
        self.__post_init__()
        _check_event_metadata(self.metadata, self._payload())


@dataclass(frozen=True, slots=True)
class ReceivableSettlementEvent:
    metadata: EventMetadata
    receivable_id: str
    kind: ReceivableKind
    amount: Decimal
    due_time: datetime
    source_event_id: str
    simulation_only: bool = field(default=True, init=False)
    execution_capability: ExecutionCapability = field(
        default=ExecutionCapability.BACKTEST_ONLY, init=False
    )

    def __post_init__(self) -> None:
        _model(self.metadata, EventMetadata, "receivable_settlement.metadata")
        _digest(self.receivable_id, "receivable_id")
        _enum(self.kind, ReceivableKind, "receivable.kind")
        _decimal(self.amount, "receivable.amount", positive=True)
        due = _aware(self.due_time, "due_time")
        if due > self.metadata.logical_time:
            raise ReceivableError("settlement cannot precede due_time")
        _text(self.source_event_id, "source_event_id")
        _bind_event_metadata(self, self._payload())
        _event_safety(self.simulation_only, self.execution_capability)

    def _payload(self) -> dict[str, object]:
        return {
            "event_type": "RECEIVABLE_SETTLEMENT",
            "receivable_id": self.receivable_id,
            "kind": self.kind,
            "amount": self.amount,
            "due_time": self.due_time,
            "source_event_id": self.source_event_id,
        }

    @property
    def event_digest(self) -> str:
        return self.metadata.event_digest

    @property
    def ordering_key(self) -> tuple[datetime, int, str, int, str]:
        return self.metadata.ordering_key

    def validate_integrity(self) -> None:
        self.__post_init__()
        _check_event_metadata(self.metadata, self._payload())


@dataclass(frozen=True, slots=True)
class CorporateActionApplicationEvent:
    metadata: EventMetadata
    record: CorporateActionRecord
    lot_cost_policy: LotCostAllocationPolicy = field(default_factory=LotCostAllocationPolicy)
    simulation_only: bool = field(default=True, init=False)
    execution_capability: ExecutionCapability = field(
        default=ExecutionCapability.BACKTEST_ONLY, init=False
    )

    def __post_init__(self) -> None:
        _model(self.metadata, EventMetadata, "corporate.metadata")
        _model(self.record, CorporateActionRecord, "corporate.record")
        _model(self.lot_cost_policy, LotCostAllocationPolicy, "corporate.lot_cost_policy")
        boundary = self.record.record_time or self.record.effective_time
        if boundary is not None and self.metadata.logical_time < boundary:
            raise CorporateActionError("corporate action event precedes its boundary")
        _bind_event_metadata(self, self._payload())
        _event_safety(self.simulation_only, self.execution_capability)

    def _payload(self) -> dict[str, object]:
        return {
            "event_type": "CORPORATE_ACTION",
            "record": self.record,
            "lot_cost_policy": self.lot_cost_policy,
        }

    @property
    def event_digest(self) -> str:
        return self.metadata.event_digest

    @property
    def ordering_key(self) -> tuple[datetime, int, str, int, str]:
        return self.metadata.ordering_key

    def validate_integrity(self) -> None:
        self.__post_init__()
        _check_event_metadata(self.metadata, self._payload())


@dataclass(frozen=True, slots=True)
class PortfolioState:
    initial_capital: Decimal = Decimal("0")
    available_cash: Decimal = Decimal("0")
    frozen_cash: Decimal = Decimal("0")
    sale_cash_receivable: Decimal = Decimal("0")
    dividend_or_corporate_cash_receivable: Decimal = Decimal("0")
    active_buy_reservations: tuple[BuyCashReservation, ...] = ()
    open_lots: tuple[PortfolioLot, ...] = ()
    sale_receivables: tuple[CashReceivable, ...] = ()
    dividend_or_corporate_receivables: tuple[CashReceivable, ...] = ()
    realized_price_pnl: Decimal = Decimal("0")
    dividend_pnl: Decimal = Decimal("0")
    other_corporate_action_pnl: Decimal = Decimal("0")
    fee_pnl: Decimal = Decimal("0")
    last_ordering_key: tuple[datetime, int, str, int, str] | None = None
    last_event_digest: str = ZERO_DIGEST
    applied_event_records: tuple[AppliedEventRecord, ...] = ()
    journal_chain_digest: str = ZERO_DIGEST
    journal: tuple[LedgerEvent, ...] = ()
    settled_order_ids: tuple[str, ...] = ()
    corporate_action_applications: tuple[CorporateActionApplication, ...] = ()
    history_ref: PortfolioHistoryRef = field(default_factory=PortfolioHistoryRef.genesis)
    state_digest: str = field(init=False)
    simulation_only: bool = field(default=True, init=False)
    execution_capability: ExecutionCapability = field(
        default=ExecutionCapability.BACKTEST_ONLY, init=False
    )

    def __post_init__(self) -> None:
        for name in (
            "initial_capital",
            "available_cash",
            "frozen_cash",
            "sale_cash_receivable",
            "dividend_or_corporate_cash_receivable",
        ):
            _decimal(getattr(self, name), f"state.{name}")
        for name in (
            "realized_price_pnl",
            "dividend_pnl",
            "other_corporate_action_pnl",
            "fee_pnl",
        ):
            _signed_decimal(getattr(self, name), f"state.{name}")
        if self.fee_pnl > 0:
            raise AccountingInvariantError("fee_pnl must be non-positive")
        _model(self.history_ref, PortfolioHistoryRef, "state.history_ref")
        reservations = _tuple(self.active_buy_reservations, "active_buy_reservations")
        typed_reservations = tuple(
            _model(item, BuyCashReservation, "active reservation") for item in reservations
        )
        reservation_ids = tuple(item.order_id for item in typed_reservations)
        if reservation_ids != tuple(sorted(set(reservation_ids))):
            raise AccountingInvariantError("active reservations must be sorted and unique")
        lots = _tuple(self.open_lots, "open_lots")
        typed_lots = tuple(_model(item, PortfolioLot, "open lot") for item in lots)
        lot_keys = tuple(
            (item.instrument_code, item.acquisition_trade_date, item.lot_id) for item in typed_lots
        )
        if lot_keys != tuple(sorted(set(lot_keys))):
            raise AccountingInvariantError("open lots must be canonical and unique")
        sale_items = _typed_receivables(self.sale_receivables, "sale_receivables")
        corp_items = _typed_receivables(
            self.dividend_or_corporate_receivables, "dividend_or_corporate_receivables"
        )
        if any(item.kind is not ReceivableKind.SALE_PROCEEDS for item in sale_items):
            raise AccountingInvariantError("sale receivables have a wrong kind")
        if any(item.kind is not ReceivableKind.DIVIDEND_OR_CORPORATE for item in corp_items):
            raise AccountingInvariantError("corporate receivables have a wrong kind")
        if self.sale_cash_receivable != sum((item.amount for item in sale_items), Decimal("0")):
            raise AccountingInvariantError("sale receivable aggregate mismatch")
        if self.dividend_or_corporate_cash_receivable != sum(
            (item.amount for item in corp_items), Decimal("0")
        ):
            raise AccountingInvariantError("corporate receivable aggregate mismatch")
        if self.frozen_cash != sum(
            (item.maximum_debit for item in typed_reservations), Decimal("0")
        ):
            raise AccountingInvariantError("frozen cash does not equal reservations")
        _digest(self.last_event_digest, "last_event_digest", allow_zero=True)
        _digest(self.journal_chain_digest, "journal_chain_digest", allow_zero=True)
        records = _tuple(self.applied_event_records, "applied_event_records")
        typed_records = tuple(_model(item, AppliedEventRecord, "applied event") for item in records)
        ids = tuple(item.event_id for item in typed_records)
        if len(ids) != len(set(ids)):
            raise AccountingInvariantError("applied event ids must be unique")
        if self.history_ref.expected_event_count != len(typed_records):
            raise AccountingInvariantError("history ref event count does not match journal")
        if self.history_ref.expected_event_tape_digest != event_tape_digest(
            tuple(item.event_digest for item in typed_records)
        ):
            raise AccountingInvariantError("history ref tape digest does not match journal")
        if typed_records and self.last_event_digest == ZERO_DIGEST:
            raise AccountingInvariantError("non-empty journal must have a last event digest")
        if not typed_records and self.last_event_digest != ZERO_DIGEST:
            raise AccountingInvariantError("empty journal must have ZERO_DIGEST last event")
        if self.initial_capital > 0 and (
            not typed_records or self.last_event_digest == ZERO_DIGEST
        ):
            raise AccountingInvariantError(
                "positive-capital state must contain an initial-capital journal event"
            )
        journal = _tuple(self.journal, "journal")
        typed_journal = tuple(_model(item, LedgerEvent, "journal event") for item in journal)
        if tuple(item.event_digest for item in typed_journal) != tuple(
            item.event_digest for item in typed_records
        ):
            raise AccountingInvariantError("journal and applied event lineage diverge")
        settled = _tuple(self.settled_order_ids, "settled_order_ids")
        settled_ids = tuple(_text(item, "settled_order_id") for item in settled)
        if settled_ids != tuple(sorted(set(settled_ids))):
            raise AccountingInvariantError("settled order ids must be sorted and unique")
        applications = _tuple(self.corporate_action_applications, "corporate_action_applications")
        typed_apps = tuple(
            _model(item, CorporateActionApplication, "corporate application")
            for item in applications
        )
        app_keys = tuple((item.lineage_id, item.action_version) for item in typed_apps)
        if len(app_keys) != len(set(app_keys)):
            raise AccountingInvariantError("corporate action lineages must be unique")
        if self.last_ordering_key is not None:
            key = _tuple(self.last_ordering_key, "last_ordering_key")
            if (
                len(key) != 5
                or type(key[0]) is not datetime
                or type(key[1]) is not int
                or type(key[2]) is not str
                or type(key[3]) is not int
                or type(key[4]) is not str
            ):
                raise AccountingInvariantError("last_ordering_key is malformed")
        if (
            self.simulation_only is not True
            or self.execution_capability is not ExecutionCapability.BACKTEST_ONLY
        ):
            raise AccountingInvariantError("portfolio state must remain simulation-only")
        object.__setattr__(self, "state_digest", canonical_digest(self._payload()))
        book_assets = self.book_assets
        identity = (
            self.initial_capital
            + self.realized_price_pnl
            + self.dividend_pnl
            + self.other_corporate_action_pnl
            + self.fee_pnl
        )
        if book_assets != identity:
            raise AccountingInvariantError("book-assets and PnL identity does not reconcile")

    def _payload(self) -> dict[str, object]:
        return {
            "initial_capital": self.initial_capital,
            "available_cash": self.available_cash,
            "frozen_cash": self.frozen_cash,
            "sale_cash_receivable": self.sale_cash_receivable,
            "dividend_or_corporate_cash_receivable": self.dividend_or_corporate_cash_receivable,
            "active_buy_reservations": self.active_buy_reservations,
            "open_lots": self.open_lots,
            "sale_receivables": self.sale_receivables,
            "dividend_or_corporate_receivables": self.dividend_or_corporate_receivables,
            "realized_price_pnl": self.realized_price_pnl,
            "dividend_pnl": self.dividend_pnl,
            "other_corporate_action_pnl": self.other_corporate_action_pnl,
            "fee_pnl": self.fee_pnl,
            "last_ordering_key": self.last_ordering_key,
            "last_event_digest": self.last_event_digest,
            "applied_event_records": self.applied_event_records,
            "journal_chain_digest": self.journal_chain_digest,
            "journal": self.journal,
            "settled_order_ids": self.settled_order_ids,
            "corporate_action_applications": self.corporate_action_applications,
            "history_ref": self.history_ref,
            "simulation_only": self.simulation_only,
            "execution_capability": self.execution_capability,
        }

    @classmethod
    def empty(cls, tape_id: str = "portfolio-genesis") -> PortfolioState:
        return cls(history_ref=PortfolioHistoryRef.genesis(tape_id))

    @property
    def lots(self) -> tuple[PortfolioLot, ...]:
        return self.open_lots

    @property
    def reservations(self) -> tuple[BuyCashReservation, ...]:
        return self.active_buy_reservations

    @property
    def book_assets(self) -> Decimal:
        return (
            self.available_cash
            + self.frozen_cash
            + self.sale_cash_receivable
            + self.dividend_or_corporate_cash_receivable
            + sum((lot.gross_cost for lot in self.open_lots), Decimal("0"))
        )

    @property
    def realized_pnl(self) -> Decimal:
        return self.realized_price_pnl

    @property
    def total_pnl(self) -> Decimal:
        return self.book_assets - self.initial_capital

    def validate_integrity(self) -> None:
        original = self.state_digest
        self.__post_init__()
        if original != canonical_digest(self._payload()):
            raise AccountingInvariantError("state digest mismatch")


def _typed_receivables(value: object, field_name: str) -> tuple[CashReceivable, ...]:
    raw = _tuple(value, field_name)
    typed = tuple(_model(item, CashReceivable, field_name) for item in raw)
    keys = tuple(item.receivable_id for item in typed)
    if keys != tuple(sorted(set(keys))):
        raise AccountingInvariantError(f"{field_name} must be sorted and unique")
    return typed


def _event_safety(simulation_only: object, capability: object) -> None:
    if simulation_only is not True or capability is not ExecutionCapability.BACKTEST_ONLY:
        raise PortfolioValidationError("portfolio events must remain BACKTEST_ONLY")


def _event_payload_digest(payload: object) -> str:
    return canonical_digest(payload)


def _bind_event_metadata(event: object, payload: object) -> None:
    typed_event = cast(_EventWithMetadata, event)
    metadata = typed_event.metadata
    digest = _event_payload_digest(payload)
    if metadata.payload_digest == ZERO_DIGEST:
        object.__setattr__(event, "metadata", replace(metadata, payload_digest=digest))
    elif metadata.payload_digest != digest:
        raise PortfolioValidationError("event metadata payload digest does not match event")


def _check_event_metadata(metadata: EventMetadata, payload: object) -> None:
    metadata.validate_integrity()
    digest = _event_payload_digest(payload)
    if metadata.payload_digest != digest:
        raise PortfolioValidationError("event payload digest mismatch")


PortfolioEvent = (
    InitialCapitalEvent
    | BuyCashReservationEvent
    | ReservationReleaseEvent
    | ExecutionSettlementEvent
    | ReceivableSettlementEvent
    | CorporateActionApplicationEvent
)


def revalidate_portfolio_state(value: object, field_name: str = "state") -> PortfolioState:
    return _model(value, PortfolioState, field_name)


def revalidate_portfolio_event(value: object, field_name: str = "event") -> PortfolioEvent:
    expected = (
        InitialCapitalEvent,
        BuyCashReservationEvent,
        ReservationReleaseEvent,
        ExecutionSettlementEvent,
        ReceivableSettlementEvent,
        CorporateActionApplicationEvent,
    )
    if type(value) not in expected:
        raise PortfolioValidationError(f"{field_name} is not a supported portfolio event")
    event = cast(PortfolioEvent, value)
    event.validate_integrity()
    return event


__all__ = [
    "AccountCode",
    "AccountingInvariantError",
    "AppliedEventRecord",
    "BuyCashReservation",
    "BuyCashReservationEvent",
    "CashDividendTerms",
    "CashReceivable",
    "ConsolidationTerms",
    "CorporateActionApplication",
    "CorporateActionApplicationEvent",
    "CorporateActionError",
    "CorporateActionRecord",
    "CorporateActionTerms",
    "CorporateActionType",
    "DuplicateEventConflictError",
    "EventMetadata",
    "EventOrderError",
    "EventPhase",
    "ExecutionArtifactRef",
    "ExecutionReplayBundle",
    "ExecutionSettlementEvent",
    "InitialCapitalEvent",
    "LedgerEvent",
    "LedgerPosting",
    "LotCostAllocationPolicy",
    "NextTradingDateResolution",
    "PortfolioError",
    "PortfolioEvent",
    "PortfolioHistoryRef",
    "PortfolioLot",
    "PortfolioState",
    "PortfolioValidationError",
    "ReceivableError",
    "ReceivableKind",
    "ReceivableSettlementEvent",
    "ReservationPolicy",
    "ReservationReleaseEvent",
    "RoundingMode",
    "SplitTerms",
    "StockDividendTerms",
    "TrustedReplayError",
    "TrustedExecutionInputs",
    "ValuationError",
    "ValuationMark",
    "ValuationMarkSource",
    "ValuationPolicy",
    "PortfolioValuation",
    "VALUATION_SCHEMA_VERSION",
    "CORPORATE_ACTION_SCHEMA_VERSION",
    "METADATA_SCHEMA_VERSION",
    "PORTFOLIO_SCHEMA_VERSION",
    "ZERO_DIGEST",
    "revalidate_portfolio_event",
    "revalidate_portfolio_state",
]
