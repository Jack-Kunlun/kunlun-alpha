"""Instrument code parser tests.

Driven by the same fixtures file as the TypeScript suite
(packages/contracts/instrument/fixtures.json) so the two parsers stay aligned.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict, cast

import pytest
from market_core.instrument.code_parser import InstrumentCodeRef, parse_instrument_code


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


@pytest.mark.parametrize(
    "fixture",
    cast(list[StatusFixture], _FIXTURES["stAndDelisted"]),
    ids=lambda f: f["code"],
)
def test_status_does_not_change_code(fixture: StatusFixture) -> None:
    """ST / delisted / suspended instruments keep their exchange code."""
    ref = parse_instrument_code(fixture["code"])
    assert ref is not None, f"expected {fixture['code']} to parse"
    assert ref.unified_code.endswith(f".{fixture['code']}")
    assert ref.type == "STOCK"
