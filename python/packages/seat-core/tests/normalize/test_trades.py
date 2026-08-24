from decimal import Decimal

import pytest
from seat_core.normalize import (
    TradeNormalizationError,
    normalize_instrument_id,
    normalize_trade_amounts,
)


def test_normalize_vendor_symbol_at_adapter_boundary() -> None:
    assert normalize_instrument_id("600519.SH") == "600519.SH"
    assert normalize_instrument_id("SH.600519") == "600519.SH"
    assert normalize_instrument_id("600519", exchange="SSE") == "600519.SH"
    assert normalize_instrument_id("000001", exchange="SZSE") == "000001.SZ"

    with pytest.raises(TradeNormalizationError, match="exchange"):
        normalize_instrument_id("600519")
    with pytest.raises(TradeNormalizationError, match="symbol"):
        normalize_instrument_id("600519.OF")


def test_normalize_trade_amounts_uses_exact_decimal_and_reconciles_vendor_net() -> None:
    buy, sell, net = normalize_trade_amounts(
        "999999999999999999999999.1200",
        Decimal("0.0000"),
        "999999999999999999999999.1200",
    )

    assert buy == Decimal("999999999999999999999999.1200")
    assert sell == Decimal("0.0000")
    assert net == Decimal("999999999999999999999999.1200")

    with pytest.raises(TradeNormalizationError, match="vendor net"):
        normalize_trade_amounts("10.00", "3.00", "8.00")
    with pytest.raises(TradeNormalizationError, match="non-negative"):
        normalize_trade_amounts("-1.00", "0.00", "-1.00")
    with pytest.raises(TradeNormalizationError, match="exact"):
        normalize_trade_amounts(1.25, 0, 1.25)
