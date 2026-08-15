"""Instrument code parser tests.

Driven by the same fixtures file as the TypeScript suite
(packages/contracts/instrument/fixtures.json) so the two parsers stay aligned.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict, cast

import pytest
from ashare_contracts.instrument_instrument import Instrument
from market_core.instrument import code_parser
from market_core.instrument.code_parser import InstrumentCodeRef, parse_instrument_code
from pydantic import ValidationError


class ValidFixture(TypedDict):
    code: str
    exchange: str
    board: str
    type: str
    unifiedCode: str


class InvalidFixture(TypedDict):
    code: str
    reason: str


class StatusFixture(TypedDict):
    code: str


_FIXTURES = cast(
    dict[str, list[dict[str, str]]],
    json.loads(
        (
            Path(__file__).resolve().parents[4]
            / "packages"
            / "contracts"
            / "instrument"
            / "fixtures.json"
        ).read_text(encoding="utf-8"),
    ),
)


@pytest.mark.parametrize(
    "fixture",
    cast(list[ValidFixture], _FIXTURES["valid"]),
    ids=lambda f: f["code"],
)
def test_valid_codes(fixture: ValidFixture) -> None:
    ref: InstrumentCodeRef | None = parse_instrument_code(fixture["code"])
    assert ref is not None, f"expected {fixture['code']} to parse"
    assert ref.exchange == fixture["exchange"]
    assert ref.board == fixture["board"]
    assert ref.type == fixture["type"]
    assert ref.unified_code == fixture["unifiedCode"]


@pytest.mark.parametrize(
    "fixture",
    cast(list[InvalidFixture], _FIXTURES["invalid"]),
    ids=lambda f: repr(f["code"]),
)
def test_invalid_codes(fixture: InvalidFixture) -> None:
    assert parse_instrument_code(fixture["code"]) is None, (
        f"expected {fixture['code']!r} to be rejected ({fixture['reason']})"
    )


def test_obsolete_exchange_prefix_form_is_rejected() -> None:
    assert parse_instrument_code("SH.600519") is None


@pytest.mark.parametrize(
    "fixture",
    cast(list[StatusFixture], _FIXTURES["stAndDelisted"]),
    ids=lambda f: f["code"],
)
def test_status_does_not_change_code(fixture: StatusFixture) -> None:
    """ST / delisted / suspended instruments keep their exchange code."""
    ref = parse_instrument_code(fixture["code"])
    assert ref is not None, f"expected {fixture['code']} to parse"
    assert ref.unified_code.startswith(f"{fixture['code']}.")
    assert ref.type == "STOCK"


def test_to_unified_code_uses_suffix_form() -> None:
    to_unified_code = getattr(code_parser, "to_unified_code", None)
    assert callable(to_unified_code), "to_unified_code must be exposed by the parser"
    assert to_unified_code("SH", "600519") == "600519.SH"
    assert to_unified_code("SZ", " 000001 ") == "000001.SZ"


def test_to_unified_code_rejects_exchange_mismatch() -> None:
    to_unified_code = getattr(code_parser, "to_unified_code", None)
    assert callable(to_unified_code), "to_unified_code must be exposed by the parser"
    assert to_unified_code("SZ", "600519") is None


_VALID_INSTRUMENT = {
    "unifiedCode": "600519.SH",
    "code": "600519",
    "exchange": "SH",
    "board": "MAIN",
    "type": "STOCK",
    "name": "贵州茅台",
    "tradingStatus": "LISTED",
    "currency": "CNY",
}


def test_complete_instrument_accepts_consistent_identity() -> None:
    instrument = Instrument.model_validate(_VALID_INSTRUMENT)
    assert instrument.unified_code == "600519.SH"


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"code": "000001"}, id="code-mismatch"),
        pytest.param({"exchange": "SZ"}, id="exchange-mismatch"),
        pytest.param({"unifiedCode": "SH.600519"}, id="suffix-mismatch"),
        pytest.param(
            {"unifiedCode": "600519.SZ", "exchange": "SZ"},
            id="prefix-rule-exchange-mismatch",
        ),
        pytest.param({"board": "CHINEXT"}, id="prefix-rule-board-mismatch"),
        pytest.param({"type": "ETF"}, id="prefix-rule-type-mismatch"),
    ],
)
def test_complete_instrument_rejects_identity_mismatch(overrides: dict[str, str]) -> None:
    payload = {**_VALID_INSTRUMENT, **overrides}
    with pytest.raises(ValidationError):
        Instrument.model_validate(payload)
