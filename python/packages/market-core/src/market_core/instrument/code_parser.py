"""A-share instrument code parser.

Python port of the TypeScript parser in packages/contracts/src/instrument.
Both read the same prefix rules from packages/contracts/instrument/
code-prefix-rules.json, which is the single source of truth.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

ExchangeCode = Literal["SH", "SZ", "BJ"]
BoardId = Literal["MAIN", "CHINEXT", "STAR", "BSE"]
SecurityType = Literal["STOCK", "ETF", "LOF", "FUND"]

_RULES_PATH = (
    Path(__file__).resolve().parents[6]
    / "packages"
    / "contracts"
    / "instrument"
    / "code-prefix-rules.json"
)

_CODE_RE = re.compile(r"^\d{6}$")
_UNIFIED_CODE_RE = re.compile(r"^(?P<code>\d{6})\.(?P<exchange>SH|SZ|BJ)$")


@dataclass(frozen=True)
class InstrumentCodeRef:
    """Result of parsing a raw exchange code."""

    code: str
    unified_code: str
    exchange: ExchangeCode
    board: BoardId
    type: SecurityType


def _load_rules() -> list[dict[str, str]]:
    with _RULES_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    # Longest prefix first so longer prefixes win (e.g. 159 -> ETF, 15 -> FUND).
    return sorted(data["rules"], key=lambda r: len(r["prefix"]), reverse=True)


_RULES = _load_rules()


def parse_instrument_code(input: str) -> InstrumentCodeRef | None:
    """Parse a raw 6-digit A-share code into the unified instrument reference.

    Returns None when the input is not a valid exchange code (bad format or
    unassigned code segment).
    """
    code = input.strip()
    if not _CODE_RE.match(code):
        return None
    for rule in _RULES:
        if code.startswith(rule["prefix"]):
            return InstrumentCodeRef(
                code=code,
                unified_code=f"{code}.{rule['exchange']}",
                exchange=cast(ExchangeCode, rule["exchange"]),
                board=cast(BoardId, rule["board"]),
                type=cast(SecurityType, rule["type"]),
            )
    return None


def to_unified_code(exchange: ExchangeCode, code: str) -> str | None:
    """Build a suffix-form unified code after validating exchange agreement."""
    normalized_code = code.strip()
    if not _CODE_RE.fullmatch(normalized_code):
        return None
    parsed = parse_instrument_code(normalized_code)
    if parsed is None or parsed.exchange != exchange:
        return None
    return parsed.unified_code


def is_unified_code_for_exchange(unified_code: str, exchange: ExchangeCode) -> bool:
    """Check suffix/exchange identity and known prefix ownership.

    Market-domain records use the shared suffix-form identity. The suffix must
    match ``exchange`` and the shared prefix table must recognize the code and
    assign it to that same exchange.
    """
    match = _UNIFIED_CODE_RE.fullmatch(unified_code)
    if match is None:
        return False
    if match.group("exchange") != exchange:
        return False
    parsed = parse_instrument_code(match.group("code"))
    return parsed is not None and parsed.exchange == exchange
