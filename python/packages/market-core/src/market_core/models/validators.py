"""Market data validators.

Python port of the TypeScript validators in packages/contracts/src/market-data.
Both read the same precision rules and fixtures from
packages/contracts/market-data/ — the single source of truth.

Rules: prices/volumes/amounts are non-negative; bar high >= max(open, close,
low) and low <= min(open, close, high) unless the instrument was suspended
(suspended bars must have zero volume/amount); adjustment factors must be
strictly positive. Research prices (FORWARD_ADJUSTED / BACKWARD_ADJUSTED) and
trade prices (RAW) are kept separate via the required priceType field.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

from market_core.instrument.code_parser import is_unified_code_for_exchange

ExchangeId = Literal["SH", "SZ", "BJ"]
BarInterval = Literal["DAILY", "MINUTE_1", "MINUTE_5"]
SessionKind = Literal["CONTINUOUS", "OPEN_AUCTION", "CLOSE_AUCTION"]
PriceType = Literal["RAW", "FORWARD_ADJUSTED", "BACKWARD_ADJUSTED"]
TickDirection = Literal["BUY", "SELL", "NEUTRAL"]
TradeType = Literal["MATCH", "AUCTION", "BLOCK"]
FactorType = Literal["FORWARD", "BACKWARD"]
ActionType = Literal["DIVIDEND", "STOCK_DIVIDEND", "SPLIT", "RIGHTS_ISSUE"]


@dataclass(frozen=True)
class Bar:
    """OHLCV bar with explicit price type."""

    unified_code: str
    exchange: ExchangeId
    date: str
    interval: BarInterval
    session: SessionKind
    timestamp: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    amount: Decimal
    price_type: PriceType
    suspended: bool = False

    def __post_init__(self) -> None:
        _validate_unified_identity(self.unified_code, self.exchange)
        _validate_integer(self.volume, "volume")
        for field in ("open", "high", "low", "close", "amount"):
            object.__setattr__(self, field, _decimal_from_external(getattr(self, field)))


@dataclass(frozen=True)
class Tick:
    """A single executed trade with millisecond-precision timestamp."""

    unified_code: str
    exchange: ExchangeId
    date: str
    timestamp: str
    price: Decimal
    volume: int
    amount: Decimal
    direction: TickDirection
    trade_type: TradeType

    def __post_init__(self) -> None:
        _validate_unified_identity(self.unified_code, self.exchange)
        _validate_integer(self.volume, "volume")
        for field in ("price", "amount"):
            object.__setattr__(self, field, _decimal_from_external(getattr(self, field)))


@dataclass(frozen=True)
class AdjustmentFactor:
    """Adjustment factor applied on ex-date to derive adjusted research prices."""

    unified_code: str
    exchange: ExchangeId
    date: str
    factor: Decimal
    factor_type: FactorType
    note: str | None = None

    def __post_init__(self) -> None:
        _validate_unified_identity(self.unified_code, self.exchange)
        object.__setattr__(self, "factor", _decimal_from_external(self.factor))


@dataclass(frozen=True)
class CorporateAction:
    """A corporate action event: dividend, stock dividend, split or rights issue."""

    unified_code: str
    exchange: ExchangeId
    ex_date: str
    action_type: ActionType
    description: str
    per_share_cash: Decimal | None = None
    per_share_stock: Decimal | None = None
    ratio: Decimal | None = None

    def __post_init__(self) -> None:
        _validate_unified_identity(self.unified_code, self.exchange)
        for field in ("per_share_cash", "per_share_stock", "ratio"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _decimal_from_external(value))


@dataclass(frozen=True)
class ValidationResult:
    """Result of a validation: valid flag plus accumulated error messages."""

    valid: bool
    errors: list[str]


def _ok() -> ValidationResult:
    return ValidationResult(True, [])


def _fail(message: str) -> ValidationResult:
    return ValidationResult(False, [message])


def _validate_unified_identity(unified_code: str, exchange: ExchangeId) -> None:
    if not is_unified_code_for_exchange(unified_code, exchange):
        raise ValueError("unifiedCode/exchange identity mismatch")


def _validate_integer(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")


def _is_non_negative(value: Decimal | int) -> bool:
    if isinstance(value, int):
        return value >= 0
    return value.is_finite() and value >= Decimal("0")


def validate_bar(bar: Bar) -> ValidationResult:
    """Validate an OHLCV bar.

    A suspended bar must have zero volume and amount and skips the high/low
    relationship check. A non-suspended bar must satisfy
    high >= max(open, close, low) and low <= min(open, close, high).
    """
    if not _is_non_negative(bar.open):
        return _fail("open must be >= 0")
    if not _is_non_negative(bar.high):
        return _fail("high must be >= 0")
    if not _is_non_negative(bar.low):
        return _fail("low must be >= 0")
    if not _is_non_negative(bar.close):
        return _fail("close must be >= 0")
    if not _is_non_negative(bar.volume):
        return _fail("volume must be >= 0")
    if not _is_non_negative(bar.amount):
        return _fail("amount must be >= 0")

    if bar.suspended:
        if bar.volume != 0:
            return _fail("suspended bar must have zero volume")
        if bar.amount != 0:
            return _fail("suspended bar must have zero amount")
        return _ok()

    if bar.high < max(bar.open, bar.close, bar.low):
        return _fail("high must be >= max(open, close, low)")
    if bar.low > min(bar.open, bar.close, bar.high):
        return _fail("low must be <= min(open, close, high)")
    return _ok()


def validate_tick(tick: Tick) -> ValidationResult:
    """Validate a single executed trade: price, volume and amount non-negative."""
    if not _is_non_negative(tick.price):
        return _fail("price must be >= 0")
    if not _is_non_negative(tick.volume):
        return _fail("volume must be >= 0")
    if not _is_non_negative(tick.amount):
        return _fail("amount must be >= 0")
    return _ok()


def validate_adjustment_factor(factor: AdjustmentFactor) -> ValidationResult:
    """Validate an adjustment factor: factor must be strictly positive."""
    if not factor.factor.is_finite() or factor.factor <= 0:
        return _fail("factor must be > 0")
    return _ok()


def validate_corporate_action(action: CorporateAction) -> ValidationResult:
    """Validate a corporate action. Optional cash/stock/ratio must be non-negative."""
    if action.per_share_cash is not None and action.per_share_cash < 0:
        return _fail("perShareCash must be >= 0")
    if action.per_share_stock is not None and action.per_share_stock < 0:
        return _fail("perShareStock must be >= 0")
    if action.ratio is not None and action.ratio < 0:
        return _fail("ratio must be >= 0")
    return _ok()


def bar_from_dict(raw: dict[str, object]) -> Bar:
    """Build a Bar from a camelCase JSON dict (fixtures format)."""
    return Bar(
        unified_code=str(raw["unifiedCode"]),
        exchange=cast(ExchangeId, raw["exchange"]),
        date=str(raw["date"]),
        interval=cast(BarInterval, raw["interval"]),
        session=cast(SessionKind, raw["session"]),
        timestamp=str(raw["timestamp"]),
        open=_decimal_from_external(raw["open"]),
        high=_decimal_from_external(raw["high"]),
        low=_decimal_from_external(raw["low"]),
        close=_decimal_from_external(raw["close"]),
        volume=cast(int, raw["volume"]),
        amount=_decimal_from_external(raw["amount"]),
        price_type=cast(PriceType, raw["priceType"]),
        suspended=bool(raw.get("suspended", False)),
    )


def tick_from_dict(raw: dict[str, object]) -> Tick:
    """Build a Tick from a camelCase JSON dict (fixtures format)."""
    return Tick(
        unified_code=str(raw["unifiedCode"]),
        exchange=cast(ExchangeId, raw["exchange"]),
        date=str(raw["date"]),
        timestamp=str(raw["timestamp"]),
        price=_decimal_from_external(raw["price"]),
        volume=cast(int, raw["volume"]),
        amount=_decimal_from_external(raw["amount"]),
        direction=cast(TickDirection, raw["direction"]),
        trade_type=cast(TradeType, raw["tradeType"]),
    )


def factor_from_dict(raw: dict[str, object]) -> AdjustmentFactor:
    """Build an AdjustmentFactor from a camelCase JSON dict (fixtures format)."""
    return AdjustmentFactor(
        unified_code=str(raw["unifiedCode"]),
        exchange=cast(ExchangeId, raw["exchange"]),
        date=str(raw["date"]),
        factor=_decimal_from_external(raw["factor"]),
        factor_type=cast(FactorType, raw["factorType"]),
        note=cast("str | None", raw.get("note")),
    )


def action_from_dict(raw: dict[str, object]) -> CorporateAction:
    """Build a CorporateAction from a camelCase JSON dict (fixtures format)."""
    return CorporateAction(
        unified_code=str(raw["unifiedCode"]),
        exchange=cast(ExchangeId, raw["exchange"]),
        ex_date=str(raw["exDate"]),
        action_type=cast(ActionType, raw["actionType"]),
        description=str(raw["description"]),
        per_share_cash=(
            None
            if raw.get("perShareCash") is None
            else _decimal_from_external(raw["perShareCash"])
        ),
        per_share_stock=(
            None
            if raw.get("perShareStock") is None
            else _decimal_from_external(raw["perShareStock"])
        ),
        ratio=(None if raw.get("ratio") is None else _decimal_from_external(raw["ratio"])),
    )


def _decimal_from_external(value: object) -> Decimal:
    """Convert JSON numbers/strings without constructing ``Decimal(float)``."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a decimal value")
    if isinstance(value, float):
        raise TypeError("float is not an accepted decimal boundary value")
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc
