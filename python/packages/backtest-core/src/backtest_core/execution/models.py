"""Configuration-driven, point-in-time execution simulation models."""

# Runtime type checks below are intentional: frozen nominal objects can be forged.
# pyright: reportUnnecessaryIsInstance=false

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Final, cast
from zoneinfo import ZoneInfo

from backtest_core.engine import (
    BacktestOrderIntent,
    BacktestValidationError,
    ExecutionCapability,
    IntentSide,
    canonical_digest,
    require_hex_digest,
    revalidate_backtest_order_intent,
)

SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
EXECUTION_SCHEMA_VERSION = "execution-v1"
MATCHING_SCHEMA_VERSION = "matching-v1"


class ExecutionValidationError(BacktestValidationError):
    """Raised when an execution simulation boundary is invalid."""


class InstrumentKind(str, Enum):
    A_SHARE_STOCK = "A_SHARE_STOCK"
    EXCHANGE_LISTED_FUND = "EXCHANGE_LISTED_FUND"


class OrderType(str, Enum):
    LIMIT_IOC = "LIMIT_IOC"
    MARKET_PROTECTED_IOC = "MARKET_PROTECTED_IOC"


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    HALTED = "HALTED"
    CLOSED = "CLOSED"


class SessionKind(str, Enum):
    CONTINUOUS = "CONTINUOUS"
    AUCTION = "AUCTION"


class SameDaySellPolicy(str, Enum):
    T_PLUS_1 = "T_PLUS_1"
    T_PLUS_0 = "T_PLUS_0"


class OddLotSellPolicy(str, Enum):
    DISALLOW = "DISALLOW"
    FULL_SELLABLE_REMAINDER = "FULL_SELLABLE_REMAINDER"


class PriceSource(str, Enum):
    EXECUTABLE_QUOTE = "EXECUTABLE_QUOTE"
    NAV = "NAV"
    INAV = "INAV"
    BAR_RAW = "BAR_RAW"
    BAR_ADJUSTED = "BAR_ADJUSTED"


class LimitLockState(str, Enum):
    NONE = "NONE"
    UPPER_LOCKED = "UPPER_LOCKED"
    LOWER_LOCKED = "LOWER_LOCKED"


class MatchStatus(str, Enum):
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    UNFILLED = "UNFILLED"
    REJECTED = "REJECTED"


class FeeScope(str, Enum):
    PER_FILL = "PER_FILL"
    PER_ORDER = "PER_ORDER"


class RoundingMode(str, Enum):
    DOWN = "DOWN"
    UP = "UP"
    HALF_UP = "HALF_UP"
    HALF_EVEN = "HALF_EVEN"


class RejectReason(str, Enum):
    DUPLICATE_ORDER_ID = "DUPLICATE_ORDER_ID"
    SOURCE_INTENT_MISMATCH = "SOURCE_INTENT_MISMATCH"
    SOURCE_MANIFEST_MISMATCH = "SOURCE_MANIFEST_MISMATCH"
    SOURCE_TIME_MISMATCH = "SOURCE_TIME_MISMATCH"
    INSTRUMENT_MISMATCH = "INSTRUMENT_MISMATCH"
    SIDE_MISMATCH = "SIDE_MISMATCH"
    MANIFEST_MISMATCH = "MANIFEST_MISMATCH"
    FUTURE_DATA = "FUTURE_DATA"
    CALENDAR = "CALENDAR"
    NON_TRADING_DAY = "NON_TRADING_DAY"
    UNSUPPORTED_SESSION = "UNSUPPORTED_SESSION"
    SUSPENDED = "SUSPENDED"
    HALTED = "HALTED"
    CLOSED = "CLOSED"
    RULES = "RULES"
    EFFECTIVE_INTERVAL = "EFFECTIVE_INTERVAL"
    UNSUPPORTED_ORDER_TYPE = "UNSUPPORTED_ORDER_TYPE"
    LOT_SIZE = "LOT_SIZE"
    BUY_MIN_QUANTITY = "BUY_MIN_QUANTITY"
    BUY_INCREMENT = "BUY_INCREMENT"
    MAX_ORDER_QUANTITY = "MAX_ORDER_QUANTITY"
    ODD_LOT = "ODD_LOT"
    TICK_SIZE = "TICK_SIZE"
    DAILY_PRICE_BAND = "DAILY_PRICE_BAND"
    DYNAMIC_PRICE_RANGE = "DYNAMIC_PRICE_RANGE"
    PROTECTION_PRICE = "PROTECTION_PRICE"
    LIMIT_PRICE = "LIMIT_PRICE"
    REFERENCE_PRICE = "REFERENCE_PRICE"
    INVALID_PRICE_SOURCE = "INVALID_PRICE_SOURCE"
    MISSING_EXECUTABLE_LIQUIDITY = "MISSING_EXECUTABLE_LIQUIDITY"
    UPPER_LOCKED = "UPPER_LOCKED"
    LOWER_LOCKED = "LOWER_LOCKED"
    SELLABILITY_SNAPSHOT_MISSING = "SELLABILITY_SNAPSHOT_MISSING"
    T_PLUS_ONE_NOT_SELLABLE = "T_PLUS_ONE_NOT_SELLABLE"
    INSUFFICIENT_SELLABLE_QUANTITY = "INSUFFICIENT_SELLABLE_QUANTITY"
    SLIPPAGE_LEVEL_MISSING = "SLIPPAGE_LEVEL_MISSING"


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutionValidationError(f"{field_name} must be a non-empty string")
    return value


def _require_digest(value: object, field_name: str) -> str:
    try:
        return require_hex_digest(value, field_name)
    except (BacktestValidationError, TypeError) as error:
        raise ExecutionValidationError(str(error)) from error


def _require_aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ExecutionValidationError(f"{field_name} must be timezone-aware")
    return value


def _require_decimal(value: object, field_name: str, *, positive: bool = False) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ExecutionValidationError(f"{field_name} must be a finite Decimal")
    if value < 0 or (positive and value <= 0):
        comparator = "positive" if positive else "non-negative"
        raise ExecutionValidationError(f"{field_name} must be {comparator}")
    return value


def _require_int(value: object, field_name: str, *, positive: bool = False) -> int:
    if type(value) is not int or (positive and value <= 0) or (not positive and value < 0):
        comparator = "positive" if positive else "non-negative"
        raise ExecutionValidationError(f"{field_name} must be a {comparator} integer")
    return value


def _require_tuple(value: object, field_name: str) -> tuple[object, ...]:
    if type(value) is not tuple:
        raise ExecutionValidationError(f"{field_name} must be an exact tuple")
    return cast(tuple[object, ...], value)


def _require_date(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ExecutionValidationError(f"{field_name} must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ExecutionValidationError(f"{field_name} must be an ISO date string") from error
    if parsed.isoformat() != value:
        raise ExecutionValidationError(f"{field_name} must use canonical ISO date form")
    return value


def _require_effective_interval(
    effective_from: object, effective_to: object | None, field_name: str
) -> None:
    start = _require_aware(effective_from, f"{field_name}.effective_from")
    if effective_to is not None:
        end = _require_aware(effective_to, f"{field_name}.effective_to")
        if start >= end:
            raise ExecutionValidationError(f"{field_name} effective interval must be increasing")


def _revalidate_provenance(value: object, field_name: str) -> ExecutionProvenance:
    if not isinstance(value, ExecutionProvenance):
        raise ExecutionValidationError(f"{field_name} must be ExecutionProvenance")
    try:
        value.__post_init__()
    except ExecutionValidationError:
        raise
    except (AttributeError, TypeError) as error:
        raise ExecutionValidationError(f"{field_name} contains a forged value") from error
    return value


def _revalidate_level(value: object, field_name: str) -> ExecutableLiquidityLevel:
    if not isinstance(value, ExecutableLiquidityLevel):
        raise ExecutionValidationError(f"{field_name} must be ExecutableLiquidityLevel")
    try:
        value.__post_init__()
    except ExecutionValidationError:
        raise
    except (AttributeError, TypeError) as error:
        raise ExecutionValidationError(f"{field_name} contains a forged value") from error
    return value


def _check_digest(actual: object, expected: str, field_name: str) -> None:
    _require_digest(actual, field_name)
    if actual != expected:
        raise ExecutionValidationError(f"{field_name} does not match canonical payload")


@dataclass(frozen=True, slots=True)
class ExecutionProvenance:
    source_id: str
    source_version: str
    record_id: str
    digest: str
    available_time: datetime

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.source_version, "source_version")
        _require_text(self.record_id, "record_id")
        _require_digest(self.digest, "provenance.digest")
        _require_aware(self.available_time, "provenance.available_time")


def _price_band_payload(value: PriceBand) -> dict[str, object]:
    return {
        "daily_lower": value.daily_lower,
        "daily_upper": value.daily_upper,
        "dynamic_valid_lower": value.dynamic_valid_lower,
        "dynamic_valid_upper": value.dynamic_valid_upper,
    }


def _validate_price_band(value: PriceBand) -> None:
    values = (
        ("daily_lower", value.daily_lower),
        ("daily_upper", value.daily_upper),
        ("dynamic_valid_lower", value.dynamic_valid_lower),
        ("dynamic_valid_upper", value.dynamic_valid_upper),
    )
    for field_name, field_value in values:
        if field_value is not None:
            _require_decimal(field_value, f"price_band.{field_name}", positive=True)
    for lower_name, upper_name in (
        ("daily_lower", "daily_upper"),
        ("dynamic_valid_lower", "dynamic_valid_upper"),
    ):
        lower = getattr(value, lower_name)
        upper = getattr(value, upper_name)
        if lower is not None and upper is not None and lower > upper:
            raise ExecutionValidationError(f"price_band {lower_name} must not exceed {upper_name}")


@dataclass(frozen=True, slots=True)
class PriceBand:
    daily_lower: Decimal | None
    daily_upper: Decimal | None
    dynamic_valid_lower: Decimal | None
    dynamic_valid_upper: Decimal | None
    price_band_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_price_band(self)
        object.__setattr__(self, "price_band_digest", canonical_digest(_price_band_payload(self)))

    def validate_integrity(self) -> None:
        _validate_price_band(self)
        _check_digest(
            self.price_band_digest,
            canonical_digest(_price_band_payload(self)),
            "price_band_digest",
        )


@dataclass(frozen=True, slots=True)
class ExecutableLiquidityLevel:
    level_id: str
    side: IntentSide
    price: Decimal
    quantity: int
    available_time: datetime
    price_source: PriceSource
    source: ExecutionProvenance

    def __post_init__(self) -> None:
        _require_text(self.level_id, "level_id")
        if not isinstance(self.side, IntentSide):
            raise ExecutionValidationError("level.side must be BUY or SELL")
        _require_decimal(self.price, "level.price", positive=True)
        _require_int(self.quantity, "level.quantity", positive=True)
        _require_aware(self.available_time, "level.available_time")
        if self.price_source is not PriceSource.EXECUTABLE_QUOTE:
            raise ExecutionValidationError("liquidity levels require EXECUTABLE_QUOTE price_source")
        _revalidate_provenance(self.source, "level.source")


def _snapshot_payload(value: MarketExecutionSnapshot) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "snapshot_id": value.snapshot_id,
        "instrument_code": value.instrument_code,
        "match_time": value.match_time,
        "observed_time": value.observed_time,
        "available_time": value.available_time,
        "processing_time": value.processing_time,
        "trading_date": value.trading_date,
        "is_trading_day": value.is_trading_day,
        "calendar_id": value.calendar_id,
        "calendar_version": value.calendar_version,
        "calendar_digest": value.calendar_digest,
        "session": value.session,
        "trade_status": value.trade_status,
        "price_band": value.price_band,
        "bid_levels": value.bid_levels,
        "ask_levels": value.ask_levels,
        "lock_state": value.lock_state,
        "source": value.source,
    }


def _validate_snapshot(value: MarketExecutionSnapshot) -> None:
    _require_text(value.schema_version, "snapshot.schema_version")
    if value.schema_version != EXECUTION_SCHEMA_VERSION:
        raise ExecutionValidationError("snapshot.schema_version is not supported")
    _require_text(value.snapshot_id, "snapshot.snapshot_id")
    _require_text(value.instrument_code, "snapshot.instrument_code")
    match_time = _require_aware(value.match_time, "snapshot.match_time")
    for field_name in ("observed_time", "available_time", "processing_time"):
        timestamp = _require_aware(getattr(value, field_name), f"snapshot.{field_name}")
        if timestamp > match_time:
            raise ExecutionValidationError(f"snapshot.{field_name} must not exceed match_time")
    if (
        _require_date(value.trading_date, "snapshot.trading_date")
        != match_time.astimezone(SHANGHAI).date().isoformat()
    ):
        raise ExecutionValidationError(
            "snapshot.trading_date must match match_time in Asia/Shanghai"
        )
    if type(value.is_trading_day) is not bool:
        raise ExecutionValidationError("snapshot.is_trading_day must be bool")
    _require_text(value.calendar_id, "snapshot.calendar_id")
    _require_text(value.calendar_version, "snapshot.calendar_version")
    _require_digest(value.calendar_digest, "snapshot.calendar_digest")
    if not isinstance(value.session, SessionKind):
        raise ExecutionValidationError("snapshot.session is invalid")
    if not isinstance(value.trade_status, TradeStatus):
        raise ExecutionValidationError("snapshot.trade_status is invalid")
    if not isinstance(value.price_band, PriceBand):
        raise ExecutionValidationError("snapshot.price_band is invalid")
    try:
        value.price_band.validate_integrity()
    except ExecutionValidationError:
        raise
    except (AttributeError, TypeError) as error:
        raise ExecutionValidationError("snapshot.price_band contains a forged value") from error
    _require_tuple(value.bid_levels, "snapshot.bid_levels")
    _require_tuple(value.ask_levels, "snapshot.ask_levels")
    if not isinstance(value.lock_state, LimitLockState):
        raise ExecutionValidationError("snapshot.lock_state is invalid")
    _revalidate_provenance(value.source, "snapshot.source")
    if value.source.available_time > match_time:
        raise ExecutionValidationError("snapshot.source.available_time must not exceed match_time")
    level_ids: set[str] = set()
    for side_name, levels, expected_side in (
        ("bid_levels", value.bid_levels, IntentSide.BUY),
        ("ask_levels", value.ask_levels, IntentSide.SELL),
    ):
        for index, level in enumerate(levels):
            typed_level = _revalidate_level(level, f"snapshot.{side_name}[{index}]")
            if typed_level.side is not expected_side:
                raise ExecutionValidationError(f"snapshot.{side_name} has a wrong level side")
            if typed_level.available_time > match_time:
                raise ExecutionValidationError(
                    f"snapshot.{side_name}[{index}].available_time is future data"
                )
            if typed_level.source.available_time > match_time:
                raise ExecutionValidationError(
                    f"snapshot.{side_name}[{index}].source.available_time is future data"
                )
            if typed_level.level_id in level_ids:
                raise ExecutionValidationError("snapshot level_id values must be unique")
            level_ids.add(typed_level.level_id)
        canonical_levels = tuple(
            sorted(
                levels,
                key=lambda level: (
                    -level.price if expected_side is IntentSide.BUY else level.price,
                    level.level_id,
                ),
            )
        )
        if levels != canonical_levels:
            raise ExecutionValidationError(
                f"snapshot.{side_name} must be in canonical price-time order"
            )
    if value.lock_state is LimitLockState.UPPER_LOCKED and value.ask_levels:
        raise ExecutionValidationError("UPPER_LOCKED snapshot cannot expose ask liquidity")
    if value.lock_state is LimitLockState.LOWER_LOCKED and value.bid_levels:
        raise ExecutionValidationError("LOWER_LOCKED snapshot cannot expose bid liquidity")


@dataclass(frozen=True, slots=True)
class MarketExecutionSnapshot:
    schema_version: str
    snapshot_id: str
    instrument_code: str
    match_time: datetime
    observed_time: datetime
    available_time: datetime
    processing_time: datetime
    trading_date: str
    is_trading_day: bool
    calendar_id: str
    calendar_version: str
    calendar_digest: str
    session: SessionKind
    trade_status: TradeStatus
    price_band: PriceBand
    bid_levels: tuple[ExecutableLiquidityLevel, ...]
    ask_levels: tuple[ExecutableLiquidityLevel, ...]
    lock_state: LimitLockState
    source: ExecutionProvenance
    snapshot_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_snapshot(self)
        object.__setattr__(self, "snapshot_digest", canonical_digest(_snapshot_payload(self)))

    def validate_integrity(self) -> None:
        _validate_snapshot(self)
        _check_digest(
            self.snapshot_digest, canonical_digest(_snapshot_payload(self)), "snapshot_digest"
        )

    @property
    def digest(self) -> str:
        return self.snapshot_digest


def _rules_payload(value: InstrumentExecutionRules) -> dict[str, object]:
    return {
        "rule_set_id": value.rule_set_id,
        "rule_set_version": value.rule_set_version,
        "instrument_code": value.instrument_code,
        "instrument_kind": value.instrument_kind,
        "effective_from": value.effective_from,
        "effective_to": value.effective_to,
        "available_time": value.available_time,
        "lot_size": value.lot_size,
        "tick_size": value.tick_size,
        "buy_min_quantity": value.buy_min_quantity,
        "buy_increment": value.buy_increment,
        "max_order_quantity": value.max_order_quantity,
        "odd_lot_sell_policy": value.odd_lot_sell_policy,
        "same_day_sell_policy": value.same_day_sell_policy,
        "supported_order_types": value.supported_order_types,
        "source": value.source,
    }


def _validate_rules(value: InstrumentExecutionRules) -> None:
    _require_text(value.rule_set_id, "rules.rule_set_id")
    _require_text(value.rule_set_version, "rules.rule_set_version")
    _require_text(value.instrument_code, "rules.instrument_code")
    if not isinstance(value.instrument_kind, InstrumentKind):
        raise ExecutionValidationError("rules.instrument_kind is invalid")
    _require_effective_interval(value.effective_from, value.effective_to, "rules")
    _require_aware(value.available_time, "rules.available_time")
    for field_name in ("lot_size", "buy_min_quantity", "buy_increment", "max_order_quantity"):
        _require_int(getattr(value, field_name), f"rules.{field_name}", positive=True)
    if value.buy_min_quantity > value.max_order_quantity:
        raise ExecutionValidationError("rules.buy_min_quantity must not exceed max_order_quantity")
    _require_decimal(value.tick_size, "rules.tick_size", positive=True)
    if not isinstance(value.odd_lot_sell_policy, OddLotSellPolicy):
        raise ExecutionValidationError("rules.odd_lot_sell_policy is invalid")
    if not isinstance(value.same_day_sell_policy, SameDaySellPolicy):
        raise ExecutionValidationError("rules.same_day_sell_policy is invalid")
    _require_tuple(value.supported_order_types, "rules.supported_order_types")
    if not value.supported_order_types or len(set(value.supported_order_types)) != len(
        value.supported_order_types
    ):
        raise ExecutionValidationError("rules.supported_order_types must be unique and non-empty")
    if any(not isinstance(item, OrderType) for item in value.supported_order_types):
        raise ExecutionValidationError("rules.supported_order_types contains an invalid type")
    _revalidate_provenance(value.source, "rules.source")


@dataclass(frozen=True, slots=True)
class InstrumentExecutionRules:
    rule_set_id: str
    rule_set_version: str
    instrument_code: str
    instrument_kind: InstrumentKind
    effective_from: datetime
    effective_to: datetime | None
    available_time: datetime
    lot_size: int
    tick_size: Decimal
    buy_min_quantity: int
    buy_increment: int
    max_order_quantity: int
    odd_lot_sell_policy: OddLotSellPolicy
    same_day_sell_policy: SameDaySellPolicy
    supported_order_types: tuple[OrderType, ...]
    source: ExecutionProvenance
    rules_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_rules(self)
        object.__setattr__(self, "rules_digest", canonical_digest(_rules_payload(self)))

    def validate_integrity(self) -> None:
        _validate_rules(self)
        _check_digest(self.rules_digest, canonical_digest(_rules_payload(self)), "rules_digest")

    @property
    def digest(self) -> str:
        return self.rules_digest


@dataclass(frozen=True, slots=True)
class SellableLot:
    lot_id: str
    acquisition_trade_date: str
    sellable_from_trade_date: str
    quantity: int
    sellable_quantity: int
    available_time: datetime
    source: ExecutionProvenance

    def __post_init__(self) -> None:
        _require_text(self.lot_id, "lot.lot_id")
        acquisition = _require_date(self.acquisition_trade_date, "lot.acquisition_trade_date")
        sellable_from = _require_date(self.sellable_from_trade_date, "lot.sellable_from_trade_date")
        if acquisition > sellable_from:
            raise ExecutionValidationError(
                "lot.acquisition_trade_date must not exceed sellable_from_trade_date"
            )
        _require_int(self.quantity, "lot.quantity", positive=True)
        _require_int(self.sellable_quantity, "lot.sellable_quantity")
        if self.sellable_quantity > self.quantity:
            raise ExecutionValidationError("lot.sellable_quantity must not exceed quantity")
        _require_aware(self.available_time, "lot.available_time")
        _revalidate_provenance(self.source, "lot.source")


def _sellability_payload(value: SellabilitySnapshot) -> dict[str, object]:
    return {
        "snapshot_id": value.snapshot_id,
        "instrument_code": value.instrument_code,
        "as_of_time": value.as_of_time,
        "available_time": value.available_time,
        "lots": value.lots,
        "source": value.source,
    }


def _validate_sellability(value: SellabilitySnapshot) -> None:
    _require_text(value.snapshot_id, "sellability.snapshot_id")
    _require_text(value.instrument_code, "sellability.instrument_code")
    as_of = _require_aware(value.as_of_time, "sellability.as_of_time")
    available = _require_aware(value.available_time, "sellability.available_time")
    if available > as_of:
        raise ExecutionValidationError("sellability.available_time must not exceed as_of_time")
    _require_tuple(value.lots, "sellability.lots")
    _revalidate_provenance(value.source, "sellability.source")
    if value.source.available_time > as_of:
        raise ExecutionValidationError(
            "sellability.source.available_time must not exceed as_of_time"
        )
    lot_ids: set[str] = set()
    for index, lot in enumerate(value.lots):
        if not isinstance(lot, SellableLot):
            raise ExecutionValidationError(f"sellability.lots[{index}] must be SellableLot")
        lot.__post_init__()
        if lot.lot_id in lot_ids:
            raise ExecutionValidationError("sellability lot_id values must be unique")
        lot_ids.add(lot.lot_id)
        if lot.available_time > as_of:
            raise ExecutionValidationError(
                "sellability lot available_time must not exceed as_of_time"
            )
        if lot.source.available_time > as_of:
            raise ExecutionValidationError(
                "sellability lot source.available_time must not exceed as_of_time"
            )


@dataclass(frozen=True, slots=True)
class SellabilitySnapshot:
    snapshot_id: str
    instrument_code: str
    as_of_time: datetime
    available_time: datetime
    lots: tuple[SellableLot, ...]
    source: ExecutionProvenance
    sellability_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_sellability(self)
        object.__setattr__(self, "sellability_digest", canonical_digest(_sellability_payload(self)))

    def validate_integrity(self) -> None:
        _validate_sellability(self)
        _check_digest(
            self.sellability_digest,
            canonical_digest(_sellability_payload(self)),
            "sellability_digest",
        )

    @property
    def digest(self) -> str:
        return self.sellability_digest


def _component_payload(value: FeeComponent) -> dict[str, object]:
    return {
        "code": value.code,
        "applies_sides": value.applies_sides,
        "instrument_kinds": value.instrument_kinds,
        "rate": value.rate,
        "minimum": value.minimum,
        "maximum": value.maximum,
        "rounding_quantum": value.rounding_quantum,
        "rounding_mode": value.rounding_mode,
        "scope": value.scope,
        "effective_from": value.effective_from,
        "effective_to": value.effective_to,
        "available_time": value.available_time,
        "source": value.source,
    }


def _validate_component(value: FeeComponent) -> None:
    _require_text(value.code, "fee_component.code")
    _require_tuple(value.applies_sides, "fee_component.applies_sides")
    _require_tuple(value.instrument_kinds, "fee_component.instrument_kinds")
    if not value.applies_sides or any(
        not isinstance(item, IntentSide) for item in value.applies_sides
    ):
        raise ExecutionValidationError(
            "fee_component.applies_sides must be non-empty IntentSide values"
        )
    if not value.instrument_kinds or any(
        not isinstance(item, InstrumentKind) for item in value.instrument_kinds
    ):
        raise ExecutionValidationError(
            "fee_component.instrument_kinds must be non-empty InstrumentKind values"
        )
    if len(set(value.applies_sides)) != len(value.applies_sides) or len(
        set(value.instrument_kinds)
    ) != len(value.instrument_kinds):
        raise ExecutionValidationError("fee_component applicability values must be unique")
    _require_decimal(value.rate, "fee_component.rate")
    rounding_quantum = _require_decimal(
        value.rounding_quantum, "fee_component.rounding_quantum", positive=True
    )
    if value.minimum is not None:
        minimum = _require_decimal(value.minimum, "fee_component.minimum")
        if minimum % rounding_quantum != 0:
            raise ExecutionValidationError(
                "fee_component.minimum must be an exact multiple of rounding_quantum"
            )
    if value.maximum is not None:
        maximum = _require_decimal(value.maximum, "fee_component.maximum")
        if maximum % rounding_quantum != 0:
            raise ExecutionValidationError(
                "fee_component.maximum must be an exact multiple of rounding_quantum"
            )
    if value.minimum is not None and value.maximum is not None and value.minimum > value.maximum:
        raise ExecutionValidationError("fee_component.minimum must not exceed maximum")
    if not isinstance(value.rounding_mode, RoundingMode):
        raise ExecutionValidationError("fee_component.rounding_mode is invalid")
    if not isinstance(value.scope, FeeScope):
        raise ExecutionValidationError("fee_component.scope is invalid")
    _require_effective_interval(value.effective_from, value.effective_to, "fee_component")
    _require_aware(value.available_time, "fee_component.available_time")
    _revalidate_provenance(value.source, "fee_component.source")


@dataclass(frozen=True, slots=True)
class FeeComponent:
    code: str
    applies_sides: tuple[IntentSide, ...]
    instrument_kinds: tuple[InstrumentKind, ...]
    rate: Decimal
    minimum: Decimal | None
    maximum: Decimal | None
    rounding_quantum: Decimal
    rounding_mode: RoundingMode
    scope: FeeScope
    effective_from: datetime
    effective_to: datetime | None
    available_time: datetime
    source: ExecutionProvenance
    component_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_component(self)
        object.__setattr__(self, "component_digest", canonical_digest(_component_payload(self)))

    def validate_integrity(self) -> None:
        _validate_component(self)
        _check_digest(
            self.component_digest,
            canonical_digest(_component_payload(self)),
            "component_digest",
        )


def _schedule_payload(value: FeeSchedule) -> dict[str, object]:
    return {
        "schedule_id": value.schedule_id,
        "schedule_version": value.schedule_version,
        "effective_from": value.effective_from,
        "effective_to": value.effective_to,
        "available_time": value.available_time,
        "components": value.components,
        "source": value.source,
    }


def _validate_schedule(value: FeeSchedule) -> None:
    _require_text(value.schedule_id, "fee_schedule.schedule_id")
    _require_text(value.schedule_version, "fee_schedule.schedule_version")
    _require_effective_interval(value.effective_from, value.effective_to, "fee_schedule")
    _require_aware(value.available_time, "fee_schedule.available_time")
    _require_tuple(value.components, "fee_schedule.components")
    if not value.components:
        raise ExecutionValidationError("fee_schedule.components must not be empty")
    _revalidate_provenance(value.source, "fee_schedule.source")
    codes: set[str] = set()
    for index, component in enumerate(value.components):
        if not isinstance(component, FeeComponent):
            raise ExecutionValidationError(f"fee_schedule.components[{index}] must be FeeComponent")
        component.validate_integrity()
        if component.code in codes:
            raise ExecutionValidationError("fee component code values must be unique")
        codes.add(component.code)


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    schedule_id: str
    schedule_version: str
    effective_from: datetime
    effective_to: datetime | None
    available_time: datetime
    components: tuple[FeeComponent, ...]
    source: ExecutionProvenance
    fee_schedule_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_schedule(self)
        object.__setattr__(self, "fee_schedule_digest", canonical_digest(_schedule_payload(self)))

    def validate_integrity(self) -> None:
        _validate_schedule(self)
        _check_digest(
            self.fee_schedule_digest,
            canonical_digest(_schedule_payload(self)),
            "fee_schedule_digest",
        )

    @property
    def digest(self) -> str:
        return self.fee_schedule_digest


def _slippage_payload(value: SlippageModel) -> dict[str, object]:
    return {
        "model_id": value.model_id,
        "model_version": value.model_version,
        "effective_from": value.effective_from,
        "effective_to": value.effective_to,
        "available_time": value.available_time,
        "max_level_participation": value.max_level_participation,
        "adverse_level_offset": value.adverse_level_offset,
        "skip_level_ids": value.skip_level_ids,
        "source": value.source,
    }


def _validate_slippage(value: SlippageModel) -> None:
    _require_text(value.model_id, "slippage.model_id")
    _require_text(value.model_version, "slippage.model_version")
    _require_effective_interval(value.effective_from, value.effective_to, "slippage")
    _require_aware(value.available_time, "slippage.available_time")
    if value.max_level_participation is not None:
        _require_decimal(
            value.max_level_participation, "slippage.max_level_participation", positive=True
        )
        if value.max_level_participation > Decimal("1"):
            raise ExecutionValidationError("slippage.max_level_participation must not exceed one")
    _require_int(value.adverse_level_offset, "slippage.adverse_level_offset")
    _require_tuple(value.skip_level_ids, "slippage.skip_level_ids")
    if len(set(value.skip_level_ids)) != len(value.skip_level_ids) or any(
        not isinstance(item, str) or not item for item in value.skip_level_ids
    ):
        raise ExecutionValidationError("slippage.skip_level_ids must be unique non-empty strings")
    _revalidate_provenance(value.source, "slippage.source")


@dataclass(frozen=True, slots=True)
class SlippageModel:
    model_id: str
    model_version: str
    effective_from: datetime
    effective_to: datetime | None
    available_time: datetime
    max_level_participation: Decimal | None
    adverse_level_offset: int
    skip_level_ids: tuple[str, ...]
    source: ExecutionProvenance
    slippage_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_slippage(self)
        object.__setattr__(self, "slippage_digest", canonical_digest(_slippage_payload(self)))

    def validate_integrity(self) -> None:
        _validate_slippage(self)
        _check_digest(
            self.slippage_digest,
            canonical_digest(_slippage_payload(self)),
            "slippage_digest",
        )

    @property
    def digest(self) -> str:
        return self.slippage_digest


def _validate_simulation_order(value: SimulationOrder) -> None:
    _require_text(value.order_id, "order.order_id")
    revalidate_backtest_order_intent(value.source_intent, "order.source_intent")
    _require_text(value.instrument_code, "order.instrument_code")
    if value.instrument_code != value.source_intent.entity_id:
        raise ExecutionValidationError("order.instrument_code must match source_intent.entity_id")
    if not isinstance(value.side, IntentSide):
        raise ExecutionValidationError("order.side is invalid")
    if value.side is not value.source_intent.side:
        raise ExecutionValidationError("order.side must match source_intent.side")
    _require_digest(value.manifest_digest, "order.manifest_digest")
    if value.manifest_digest != value.source_intent.manifest_digest:
        raise ExecutionValidationError("order.manifest_digest must match source intent")
    submitted_at = _require_aware(value.submitted_at, "order.submitted_at")
    if submitted_at < value.source_intent.logical_time:
        raise ExecutionValidationError(
            "order.submitted_at must not precede source intent logical_time"
        )
    _require_int(value.submission_sequence, "order.submission_sequence")
    _require_int(value.quantity, "order.quantity", positive=True)
    if not isinstance(value.order_type, OrderType):
        raise ExecutionValidationError("order.order_type is invalid")
    for field_name in ("limit_price", "protection_price"):
        price = getattr(value, field_name)
        if price is not None:
            _require_decimal(price, f"order.{field_name}", positive=True)
    if value.simulation_only is not True:
        raise ExecutionValidationError("order.simulation_only must be True")
    if value.execution_capability is not ExecutionCapability.BACKTEST_ONLY:
        raise ExecutionValidationError("order.execution_capability must be BACKTEST_ONLY")


def _order_payload(value: SimulationOrder) -> dict[str, object]:
    return {
        "order_id": value.order_id,
        "source_intent": value.source_intent,
        "instrument_code": value.instrument_code,
        "side": value.side,
        "manifest_digest": value.manifest_digest,
        "submitted_at": value.submitted_at,
        "submission_sequence": value.submission_sequence,
        "quantity": value.quantity,
        "order_type": value.order_type,
        "limit_price": value.limit_price,
        "protection_price": value.protection_price,
        "simulation_only": value.simulation_only,
        "execution_capability": value.execution_capability,
    }


@dataclass(frozen=True, slots=True)
class SimulationOrder:
    order_id: str
    source_intent: BacktestOrderIntent
    instrument_code: str
    side: IntentSide
    manifest_digest: str
    submitted_at: datetime
    submission_sequence: int
    quantity: int
    order_type: OrderType
    limit_price: Decimal | None
    protection_price: Decimal | None
    simulation_only: bool = field(default=True, init=False)
    execution_capability: ExecutionCapability = field(
        default=ExecutionCapability.BACKTEST_ONLY, init=False
    )
    order_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_simulation_order(self)
        object.__setattr__(self, "order_digest", canonical_digest(_order_payload(self)))

    def validate_integrity(self) -> None:
        _validate_simulation_order(self)
        _check_digest(self.order_digest, canonical_digest(_order_payload(self)), "order_digest")

    @property
    def digest(self) -> str:
        return self.order_digest


@dataclass(frozen=True, slots=True)
class FeeBreakdown:
    component_code: str
    scope: FeeScope
    unrounded_amount: Decimal
    rounded_amount: Decimal
    allocated_amount: Decimal

    def __post_init__(self) -> None:
        _require_text(self.component_code, "fee.component_code")
        if not isinstance(self.scope, FeeScope):
            raise ExecutionValidationError("fee.scope is invalid")
        for field_name in ("unrounded_amount", "rounded_amount", "allocated_amount"):
            _require_decimal(getattr(self, field_name), f"fee.{field_name}")
        if self.rounded_amount != self.allocated_amount:
            raise ExecutionValidationError(
                "fee.rounded_amount must equal the exact allocated amount"
            )

    @property
    def total(self) -> Decimal:
        return self.allocated_amount


def _fill_payload(value: Fill) -> dict[str, object]:
    return {
        "fill_id": value.fill_id,
        "order_id": value.order_id,
        "source_intent_id": value.source_intent_id,
        "instrument_code": value.instrument_code,
        "side": value.side,
        "quantity": value.quantity,
        "execution_sequence": value.execution_sequence,
        "price": value.price,
        "gross_notional": value.gross_notional,
        "match_time": value.match_time,
        "trading_date": value.trading_date,
        "liquidity_level_id": value.liquidity_level_id,
        "snapshot_digest": value.snapshot_digest,
        "rules_digest": value.rules_digest,
        "fee_schedule_digest": value.fee_schedule_digest,
        "slippage_model_digest": value.slippage_model_digest,
        "source_intent_digest": value.source_intent_digest,
        "source_order_digest": value.source_order_digest,
        "manifest_digest": value.manifest_digest,
        "fees": value.fees,
        "total_fee": value.total_fee,
        "simulation_only": value.simulation_only,
        "execution_capability": value.execution_capability,
    }


def _validate_fill(value: Fill) -> None:
    _require_text(value.fill_id, "fill.fill_id")
    _require_text(value.order_id, "fill.order_id")
    _require_text(value.source_intent_id, "fill.source_intent_id")
    _require_text(value.instrument_code, "fill.instrument_code")
    if not isinstance(value.side, IntentSide):
        raise ExecutionValidationError("fill.side is invalid")
    _require_int(value.quantity, "fill.quantity", positive=True)
    _require_int(value.execution_sequence, "fill.execution_sequence")
    _require_decimal(value.price, "fill.price", positive=True)
    _require_decimal(value.gross_notional, "fill.gross_notional", positive=True)
    if value.gross_notional != value.price * value.quantity:
        raise ExecutionValidationError(
            "fill.gross_notional must equal price multiplied by quantity"
        )
    match_time = _require_aware(value.match_time, "fill.match_time")
    if (
        _require_date(value.trading_date, "fill.trading_date")
        != match_time.astimezone(SHANGHAI).date().isoformat()
    ):
        raise ExecutionValidationError("fill.trading_date must match match_time in Asia/Shanghai")
    for field_name in (
        "snapshot_digest",
        "rules_digest",
        "fee_schedule_digest",
        "slippage_model_digest",
        "source_intent_digest",
        "source_order_digest",
        "manifest_digest",
    ):
        _require_digest(getattr(value, field_name), f"fill.{field_name}")
    _require_text(value.liquidity_level_id, "fill.liquidity_level_id")
    _require_tuple(value.fees, "fill.fees")
    for index, fee in enumerate(value.fees):
        if not isinstance(fee, FeeBreakdown):
            raise ExecutionValidationError(f"fill.fees[{index}] must be FeeBreakdown")
        fee.__post_init__()
    _require_decimal(value.total_fee, "fill.total_fee")
    if value.total_fee != sum((fee.allocated_amount for fee in value.fees), Decimal("0")):
        raise ExecutionValidationError("fill.total_fee must equal allocated fee amounts")
    if value.simulation_only is not True:
        raise ExecutionValidationError("fill.simulation_only must be True")
    if value.execution_capability is not ExecutionCapability.BACKTEST_ONLY:
        raise ExecutionValidationError("fill.execution_capability must be BACKTEST_ONLY")


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: str
    order_id: str
    source_intent_id: str
    instrument_code: str
    side: IntentSide
    quantity: int
    execution_sequence: int
    price: Decimal
    gross_notional: Decimal
    match_time: datetime
    trading_date: str
    liquidity_level_id: str
    snapshot_digest: str
    rules_digest: str
    fee_schedule_digest: str
    slippage_model_digest: str
    source_intent_digest: str
    source_order_digest: str
    manifest_digest: str
    fees: tuple[FeeBreakdown, ...]
    total_fee: Decimal
    simulation_only: bool = field(default=True, init=False)
    execution_capability: ExecutionCapability = field(
        default=ExecutionCapability.BACKTEST_ONLY, init=False
    )
    fill_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_fill(self)
        object.__setattr__(self, "fill_digest", canonical_digest(_fill_payload(self)))

    def validate_integrity(self) -> None:
        _validate_fill(self)
        _check_digest(self.fill_digest, canonical_digest(_fill_payload(self)), "fill_digest")

    @property
    def digest(self) -> str:
        return self.fill_digest


def _result_payload(value: MatchResult) -> dict[str, object]:
    return {
        "order_id": value.order_id,
        "status": value.status,
        "requested_quantity": value.requested_quantity,
        "filled_quantity": value.filled_quantity,
        "remaining_quantity": value.remaining_quantity,
        "fills": value.fills,
        "reject_reason": value.reject_reason,
        "reject_detail": value.reject_detail,
        "order_digest": value.order_digest,
        "source_intent_id": value.source_intent_id,
        "instrument_code": value.instrument_code,
        "side": value.side,
        "manifest_digest": value.manifest_digest,
        "snapshot_digest": value.snapshot_digest,
        "rules_digest": value.rules_digest,
        "fee_schedule_digest": value.fee_schedule_digest,
        "slippage_model_digest": value.slippage_model_digest,
        "skipped_level_ids": value.skipped_level_ids,
    }


def _validate_result(value: MatchResult) -> None:
    _require_text(value.order_id, "result.order_id")
    if not isinstance(value.status, MatchStatus):
        raise ExecutionValidationError("result.status is invalid")
    _require_int(value.requested_quantity, "result.requested_quantity", positive=True)
    _require_int(value.filled_quantity, "result.filled_quantity")
    _require_int(value.remaining_quantity, "result.remaining_quantity")
    if value.filled_quantity > value.requested_quantity:
        raise ExecutionValidationError("result.filled_quantity must not exceed requested_quantity")
    _require_tuple(value.fills, "result.fills")
    fill_ids: list[str] = []
    fill_sequences: list[int] = []
    for index, fill in enumerate(value.fills):
        if not isinstance(fill, Fill):
            raise ExecutionValidationError(f"result.fills[{index}] must be Fill")
        fill.validate_integrity()
        for field_name in (
            "order_id",
            "source_intent_id",
            "instrument_code",
            "side",
            "manifest_digest",
            "snapshot_digest",
            "rules_digest",
            "fee_schedule_digest",
            "slippage_model_digest",
        ):
            if getattr(fill, field_name) != getattr(value, field_name):
                raise ExecutionValidationError(f"result fill {field_name} must match result")
        if fill.source_order_digest != value.order_digest:
            raise ExecutionValidationError("result fill source_order_digest must match result")
        fill_ids.append(fill.fill_id)
        fill_sequences.append(fill.execution_sequence)
    if len(fill_ids) != len(set(fill_ids)):
        raise ExecutionValidationError("result fill_id values must be unique")
    if tuple(fill_sequences) != tuple(range(len(fill_sequences))):
        raise ExecutionValidationError("result fills must be in canonical execution_sequence order")
    filled_quantity = sum((fill.quantity for fill in value.fills), 0)
    if (
        value.filled_quantity != filled_quantity
        or value.remaining_quantity != value.requested_quantity - filled_quantity
    ):
        raise ExecutionValidationError("result quantities do not reconcile")
    if value.reject_reason is not None and not isinstance(value.reject_reason, RejectReason):
        raise ExecutionValidationError("result.reject_reason is invalid")
    if value.reject_detail is not None:
        _require_text(value.reject_detail, "result.reject_detail")
        if value.reject_reason is None:
            raise ExecutionValidationError("result.reject_detail requires reject_reason")
    if value.status is MatchStatus.FILLED:
        if value.filled_quantity <= 0 or value.remaining_quantity != 0 or not value.fills:
            raise ExecutionValidationError("FILLED result must contain a positive fill")
        if value.reject_reason is not None or value.reject_detail is not None:
            raise ExecutionValidationError("FILLED result cannot contain rejection metadata")
    elif value.status is MatchStatus.PARTIALLY_FILLED:
        if value.filled_quantity <= 0 or value.remaining_quantity <= 0 or not value.fills:
            raise ExecutionValidationError(
                "PARTIALLY_FILLED result must contain fills and remaining quantity"
            )
        if value.reject_reason is not None or value.reject_detail is not None:
            raise ExecutionValidationError(
                "PARTIALLY_FILLED result cannot contain rejection metadata"
            )
    elif value.status in (MatchStatus.UNFILLED, MatchStatus.REJECTED):
        if (
            value.filled_quantity != 0
            or value.remaining_quantity != value.requested_quantity
            or value.fills
        ):
            raise ExecutionValidationError("UNFILLED and REJECTED results cannot contain fills")
        if value.reject_reason is None:
            raise ExecutionValidationError("UNFILLED and REJECTED results require reject_reason")
    _require_digest(value.order_digest, "result.order_digest")
    _require_text(value.source_intent_id, "result.source_intent_id")
    _require_text(value.instrument_code, "result.instrument_code")
    if not isinstance(value.side, IntentSide):
        raise ExecutionValidationError("result.side is invalid")
    for field_name in (
        "manifest_digest",
        "snapshot_digest",
        "rules_digest",
        "fee_schedule_digest",
        "slippage_model_digest",
    ):
        _require_digest(getattr(value, field_name), f"result.{field_name}")
    _require_tuple(value.skipped_level_ids, "result.skipped_level_ids")
    if len(set(value.skipped_level_ids)) != len(value.skipped_level_ids):
        raise ExecutionValidationError("result.skipped_level_ids must be unique")
    if value.skipped_level_ids != tuple(sorted(value.skipped_level_ids)):
        raise ExecutionValidationError("result.skipped_level_ids must be canonical")


@dataclass(frozen=True, slots=True)
class MatchResult:
    order_id: str
    status: MatchStatus
    requested_quantity: int
    filled_quantity: int
    remaining_quantity: int
    fills: tuple[Fill, ...]
    reject_reason: RejectReason | None
    reject_detail: str | None
    order_digest: str
    source_intent_id: str
    instrument_code: str
    side: IntentSide
    manifest_digest: str
    snapshot_digest: str
    rules_digest: str
    fee_schedule_digest: str
    slippage_model_digest: str
    skipped_level_ids: tuple[str, ...]
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_result(self)
        object.__setattr__(self, "result_digest", canonical_digest(_result_payload(self)))

    def validate_integrity(self) -> None:
        _validate_result(self)
        _check_digest(self.result_digest, canonical_digest(_result_payload(self)), "result_digest")

    @property
    def total_fee(self) -> Decimal:
        return sum((fill.total_fee for fill in self.fills), Decimal("0"))


def _batch_payload(value: BatchMatchResult) -> dict[str, object]:
    return {
        "matching_schema_version": value.matching_schema_version,
        "backtest_manifest_digest": value.backtest_manifest_digest,
        "orders_digest": value.orders_digest,
        "snapshot_digest": value.snapshot_digest,
        "rules_digest": value.rules_digest,
        "sellability_digest": value.sellability_digest,
        "calendar_digest": value.calendar_digest,
        "fee_schedule_digest": value.fee_schedule_digest,
        "slippage_model_digest": value.slippage_model_digest,
        "source_dataset_digest": value.source_dataset_digest,
        "code_config_digest": value.code_config_digest,
        "results": value.results,
        "skipped_level_ids": value.skipped_level_ids,
    }


def _validate_batch(value: BatchMatchResult) -> None:
    if value.matching_schema_version != MATCHING_SCHEMA_VERSION:
        raise ExecutionValidationError("matching_schema_version is not supported")
    for field_name in (
        "backtest_manifest_digest",
        "orders_digest",
        "snapshot_digest",
        "rules_digest",
        "calendar_digest",
        "fee_schedule_digest",
        "slippage_model_digest",
        "source_dataset_digest",
        "code_config_digest",
    ):
        _require_digest(getattr(value, field_name), f"batch.{field_name}")
    if value.sellability_digest is not None:
        _require_digest(value.sellability_digest, "batch.sellability_digest")
    _require_tuple(value.skipped_level_ids, "batch.skipped_level_ids")
    if len(set(value.skipped_level_ids)) != len(value.skipped_level_ids):
        raise ExecutionValidationError("batch.skipped_level_ids must be unique")
    if value.skipped_level_ids != tuple(sorted(value.skipped_level_ids)):
        raise ExecutionValidationError("batch.skipped_level_ids must be canonical")
    _require_tuple(value.results, "batch.results")
    result_ids: list[str] = []
    order_pairs: list[tuple[str, str]] = []
    for index, result in enumerate(value.results):
        if not isinstance(result, MatchResult):
            raise ExecutionValidationError(f"batch.results[{index}] must be MatchResult")
        result.validate_integrity()
        result_ids.append(result.order_id)
        order_pairs.append((result.order_id, result.order_digest))
        if result.manifest_digest != value.backtest_manifest_digest:
            raise ExecutionValidationError("result manifest digest must match batch")
        for field_name in (
            "snapshot_digest",
            "rules_digest",
            "fee_schedule_digest",
            "slippage_model_digest",
        ):
            if getattr(result, field_name) != getattr(value, field_name):
                raise ExecutionValidationError(f"result {field_name} must match batch")
        if result.skipped_level_ids != value.skipped_level_ids:
            raise ExecutionValidationError("result skipped_level_ids must match batch")
    if result_ids != sorted(result_ids) or len(result_ids) != len(set(result_ids)):
        raise ExecutionValidationError("batch.results must be unique and sorted by order_id")
    if value.orders_digest != canonical_digest(tuple(order_pairs)):
        raise ExecutionValidationError("batch.orders_digest does not match results")


@dataclass(frozen=True, slots=True)
class BatchMatchResult:
    matching_schema_version: str
    backtest_manifest_digest: str
    orders_digest: str
    snapshot_digest: str
    rules_digest: str
    sellability_digest: str | None
    calendar_digest: str
    fee_schedule_digest: str
    slippage_model_digest: str
    source_dataset_digest: str
    code_config_digest: str
    results: tuple[MatchResult, ...]
    skipped_level_ids: tuple[str, ...]
    batch_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_batch(self)
        object.__setattr__(self, "batch_digest", canonical_digest(_batch_payload(self)))

    def validate_integrity(self) -> None:
        _validate_batch(self)
        _check_digest(self.batch_digest, canonical_digest(_batch_payload(self)), "batch_digest")

    @property
    def digest(self) -> str:
        return self.batch_digest

    @property
    def total_fee(self) -> Decimal:
        return sum((result.total_fee for result in self.results), Decimal("0"))


def revalidate_simulation_order(value: object, field_name: str = "order") -> SimulationOrder:
    if not isinstance(value, SimulationOrder):
        raise ExecutionValidationError(f"{field_name} must be SimulationOrder")
    try:
        value.validate_integrity()
    except ExecutionValidationError:
        raise
    except (AttributeError, TypeError) as error:
        raise ExecutionValidationError(f"{field_name} contains a forged value") from error
    return value


def revalidate_market_execution_snapshot(
    value: object, field_name: str = "snapshot"
) -> MarketExecutionSnapshot:
    if not isinstance(value, MarketExecutionSnapshot):
        raise ExecutionValidationError(f"{field_name} must be MarketExecutionSnapshot")
    try:
        value.validate_integrity()
    except ExecutionValidationError:
        raise
    except (AttributeError, TypeError) as error:
        raise ExecutionValidationError(f"{field_name} contains a forged value") from error
    return value


def revalidate_instrument_execution_rules(
    value: object, field_name: str = "rules"
) -> InstrumentExecutionRules:
    if not isinstance(value, InstrumentExecutionRules):
        raise ExecutionValidationError(f"{field_name} must be InstrumentExecutionRules")
    try:
        value.validate_integrity()
    except ExecutionValidationError:
        raise
    except (AttributeError, TypeError) as error:
        raise ExecutionValidationError(f"{field_name} contains a forged value") from error
    return value


def revalidate_sellability_snapshot(
    value: object, field_name: str = "sellability"
) -> SellabilitySnapshot:
    if not isinstance(value, SellabilitySnapshot):
        raise ExecutionValidationError(f"{field_name} must be SellabilitySnapshot")
    try:
        value.validate_integrity()
    except ExecutionValidationError:
        raise
    except (AttributeError, TypeError) as error:
        raise ExecutionValidationError(f"{field_name} contains a forged value") from error
    return value


def revalidate_fee_schedule(value: object, field_name: str = "fee_schedule") -> FeeSchedule:
    if not isinstance(value, FeeSchedule):
        raise ExecutionValidationError(f"{field_name} must be FeeSchedule")
    try:
        value.validate_integrity()
    except ExecutionValidationError:
        raise
    except (AttributeError, TypeError) as error:
        raise ExecutionValidationError(f"{field_name} contains a forged value") from error
    return value


def revalidate_slippage_model(value: object, field_name: str = "slippage") -> SlippageModel:
    if not isinstance(value, SlippageModel):
        raise ExecutionValidationError(f"{field_name} must be SlippageModel")
    try:
        value.validate_integrity()
    except ExecutionValidationError:
        raise
    except (AttributeError, TypeError) as error:
        raise ExecutionValidationError(f"{field_name} contains a forged value") from error
    return value


def revalidate_batch_match_result(value: object, field_name: str = "batch") -> BatchMatchResult:
    if not isinstance(value, BatchMatchResult):
        raise ExecutionValidationError(f"{field_name} must be BatchMatchResult")
    try:
        value.validate_integrity()
    except ExecutionValidationError:
        raise
    except (AttributeError, TypeError) as error:
        raise ExecutionValidationError(f"{field_name} contains a forged value") from error
    return value


def revalidate_fill(value: object, field_name: str = "fill") -> Fill:
    if not isinstance(value, Fill):
        raise ExecutionValidationError(f"{field_name} must be Fill")
    try:
        value.validate_integrity()
    except ExecutionValidationError:
        raise
    except (AttributeError, TypeError) as error:
        raise ExecutionValidationError(f"{field_name} contains a forged value") from error
    return value


def revalidate_match_result(value: object, field_name: str = "result") -> MatchResult:
    if not isinstance(value, MatchResult):
        raise ExecutionValidationError(f"{field_name} must be MatchResult")
    try:
        value.validate_integrity()
    except ExecutionValidationError:
        raise
    except (AttributeError, TypeError) as error:
        raise ExecutionValidationError(f"{field_name} contains a forged value") from error
    return value


__all__ = [
    "BatchMatchResult",
    "EXECUTION_SCHEMA_VERSION",
    "ExecutionProvenance",
    "ExecutionValidationError",
    "ExecutableLiquidityLevel",
    "FeeBreakdown",
    "FeeComponent",
    "FeeScope",
    "FeeSchedule",
    "Fill",
    "InstrumentExecutionRules",
    "InstrumentKind",
    "LimitLockState",
    "MATCHING_SCHEMA_VERSION",
    "MarketExecutionSnapshot",
    "MatchResult",
    "MatchStatus",
    "OddLotSellPolicy",
    "OrderType",
    "PriceBand",
    "PriceSource",
    "RejectReason",
    "RoundingMode",
    "SameDaySellPolicy",
    "SellableLot",
    "SellabilitySnapshot",
    "SessionKind",
    "SimulationOrder",
    "SlippageModel",
    "TradeStatus",
    "revalidate_batch_match_result",
    "revalidate_fee_schedule",
    "revalidate_fill",
    "revalidate_instrument_execution_rules",
    "revalidate_market_execution_snapshot",
    "revalidate_match_result",
    "revalidate_sellability_snapshot",
    "revalidate_simulation_order",
    "revalidate_slippage_model",
]
