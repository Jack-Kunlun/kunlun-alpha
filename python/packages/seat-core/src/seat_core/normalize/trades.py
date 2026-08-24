"""Standard-library-only symbol and exact-money normalization."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


class TradeNormalizationError(ValueError):
    """Machine-readable validation failure at the seat-trade boundary."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


_CODE_RE = re.compile(r"^[0-9]{6}$")
_EXCHANGE_CODES = {
    "SH": "SH",
    "SSE": "SH",
    "SZ": "SZ",
    "SZSE": "SZ",
    "BJ": "BJ",
    "BSE": "BJ",
}


def _parse_exact_decimal(value: object, field_name: str) -> Decimal:
    if type(value) is Decimal:
        parsed = value
    elif type(value) is str:
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise TradeNormalizationError(
                "amount_not_decimal", f"{field_name} must be an exact decimal string"
            ) from exc
    else:
        raise TradeNormalizationError(
            "amount_not_decimal", f"{field_name} must use exact Decimal or string input"
        )
    if not parsed.is_finite():
        raise TradeNormalizationError(
            "amount_not_decimal", f"{field_name} must be a finite exact decimal"
        )
    return parsed


def normalize_instrument_id(raw_symbol: object, *, exchange: object | None = None) -> str:
    """Convert supported vendor symbols to the internal ``######.EX`` form."""
    if type(raw_symbol) is not str or not raw_symbol.strip():
        raise TradeNormalizationError("invalid_symbol", "instrument symbol must be a string")
    value = raw_symbol.strip().upper().replace(":", ".")
    parts = value.split(".")
    code: str
    exchange_code: str
    if len(parts) == 2 and parts[0] in _EXCHANGE_CODES and _CODE_RE.fullmatch(parts[1]):
        exchange_code = _EXCHANGE_CODES[parts[0]]
        code = parts[1]
    elif len(parts) == 2 and _CODE_RE.fullmatch(parts[0]) and parts[1] in _EXCHANGE_CODES:
        code = parts[0]
        exchange_code = _EXCHANGE_CODES[parts[1]]
    elif len(parts) == 1 and _CODE_RE.fullmatch(parts[0]):
        if type(exchange) is not str or exchange.strip().upper() not in _EXCHANGE_CODES:
            raise TradeNormalizationError(
                "exchange_required", "exchange is required for an unqualified instrument symbol"
            )
        code = parts[0]
        exchange_code = _EXCHANGE_CODES[exchange.strip().upper()]
    else:
        raise TradeNormalizationError("invalid_symbol", "instrument symbol has an invalid format")
    return f"{code}.{exchange_code}"


def normalize_trade_amounts(
    buy_amount: object, sell_amount: object, vendor_net_amount: object
) -> tuple[Decimal, Decimal, Decimal]:
    """Validate exact buy/sell values and derive net as ``buy - sell``."""
    buy = _parse_exact_decimal(buy_amount, "buy_amount")
    sell = _parse_exact_decimal(sell_amount, "sell_amount")
    vendor_net = _parse_exact_decimal(vendor_net_amount, "vendor_net_amount")
    if buy < 0 or sell < 0:
        raise TradeNormalizationError(
            "negative_amount", "buy and sell amounts must be non-negative"
        )
    normalized_net = buy - sell
    if normalized_net != vendor_net:
        raise TradeNormalizationError(
            "vendor_net_mismatch", "vendor net amount does not equal buy amount minus sell amount"
        )
    return buy, sell, normalized_net
