"""Precious-metal fund classification and provenance validation.

The fund asset class is deliberately distinct from the underlying commodity:
``fund_asset_class`` is always ``PRECIOUS_METALS`` while
``underlying_commodity`` is one of ``GOLD``, ``SILVER`` or ``OTHER``. Records
retain validity, point-in-time provenance, confidence and review status so
classification is never inferred from a product name.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

AssetType = Literal["ETF", "LOF", "FUND"]
FundAssetClass = Literal["PRECIOUS_METALS"]
# Public compatibility alias for callers that imported the old type name; the
# semantics now correctly represent the single precious-metals fund class.
AssetClass = FundAssetClass
UnderlyingCommodity = Literal["GOLD", "SILVER", "OTHER"]
ReviewStatus = Literal["UNREVIEWED", "NEEDS_REVIEW", "REVIEWED", "REJECTED"]

_ASSET_TYPES = ("ETF", "LOF", "FUND")
_COMMODITIES = ("GOLD", "SILVER", "OTHER")
_REVIEW_STATUSES = ("UNREVIEWED", "NEEDS_REVIEW", "REVIEWED", "REJECTED")


@dataclass(frozen=True)
class RecurringFee:
    """An optional recurring fee with its own validity and provenance."""

    kind: str
    rate: Decimal
    valid_from: str
    valid_to: str | None
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "rate", _decimal_from_external(self.rate))


@dataclass(frozen=True)
class PreciousMetalFund:
    """Exchange-listed precious-metal fund metadata."""

    unified_code: str
    exchange: Literal["SH", "SZ", "BJ"]
    asset_type: AssetType
    fund_asset_class: FundAssetClass | str
    underlying_commodity: UnderlyingCommodity | str
    trading_currency: str
    nav_currency: str
    benchmark_or_tracking_index: str
    management_fee_rate: Decimal
    valid_from: str
    valid_to: str | None
    source: str
    publish_time: datetime
    ingest_time: datetime
    available_time: datetime
    processing_time: datetime
    raw_object_id: str
    confidence: Decimal
    review_status: ReviewStatus | str
    recurring_fees: tuple[RecurringFee, ...] = ()
    event_time: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "management_fee_rate",
            _decimal_from_external(self.management_fee_rate),
        )
        object.__setattr__(self, "confidence", _decimal_from_external(self.confidence))


@dataclass(frozen=True)
class ValidationResult:
    """Result of a validation: valid flag plus accumulated error messages."""

    valid: bool
    errors: list[str]


def fund_from_dict(raw: dict[str, object]) -> PreciousMetalFund:
    """Build a :class:`PreciousMetalFund` from a camelCase JSON mapping."""
    raw_valid_to = raw.get("validTo")
    return PreciousMetalFund(
        unified_code=str(raw["unifiedCode"]),
        exchange=str(raw["exchange"]),  # type: ignore[arg-type]
        asset_type=str(raw["assetType"]),  # type: ignore[arg-type]
        fund_asset_class=str(raw["fundAssetClass"]),
        underlying_commodity=str(raw["underlyingCommodity"]),
        trading_currency=str(raw["tradingCurrency"]),
        nav_currency=str(raw["navCurrency"]),
        benchmark_or_tracking_index=str(raw["benchmarkOrTrackingIndex"]),
        management_fee_rate=_decimal_from_external(raw["managementFeeRate"]),
        valid_from=str(raw["validFrom"]),
        valid_to=None if raw_valid_to is None else str(raw_valid_to),
        source=str(raw["source"]),
        publish_time=_parse_datetime(raw["publishTime"]),
        ingest_time=_parse_datetime(raw["ingestTime"]),
        available_time=_parse_datetime(raw["availableTime"]),
        processing_time=_parse_datetime(raw["processingTime"]),
        raw_object_id=str(raw["rawObjectId"]),
        confidence=_decimal_from_external(raw["confidence"]),
        review_status=str(raw["reviewStatus"]),
        recurring_fees=_recurring_fees_from_dict(raw.get("recurringFees")),
        event_time=(None if raw.get("eventTime") is None else _parse_datetime(raw["eventTime"])),
    )


def validate_precious_metal_fund(
    fund: PreciousMetalFund, *, decision_time: datetime | None = None
) -> ValidationResult:
    """Validate classification, provenance, point-in-time and interval semantics."""
    errors: list[str] = []

    if not _is_suffix_code(fund.unified_code):
        errors.append("unifiedCode must use suffix form")
    elif fund.unified_code[7:] != fund.exchange:
        errors.append("exchange must match unifiedCode suffix")
    if fund.asset_type not in _ASSET_TYPES:
        errors.append("assetType must be ETF/LOF/FUND")
    if fund.fund_asset_class != "PRECIOUS_METALS":
        errors.append("fundAssetClass must be PRECIOUS_METALS")
    if fund.underlying_commodity not in _COMMODITIES:
        errors.append("underlyingCommodity must be GOLD/SILVER/OTHER")
    if fund.trading_currency != "CNY":
        errors.append("tradingCurrency must be CNY")
    if not _is_currency_code(fund.nav_currency):
        errors.append("navCurrency must be an ISO 4217 currency code")
    if not fund.benchmark_or_tracking_index.strip():
        errors.append("benchmarkOrTrackingIndex must be non-empty")
    if not fund.management_fee_rate.is_finite() or fund.management_fee_rate < 0:
        errors.append("managementFeeRate must be >= 0")
    elif fund.management_fee_rate > 1:
        errors.append("managementFeeRate must be <= 1")
    if not _is_iso_date(fund.valid_from):
        errors.append("validFrom must be an ISO date")
    if fund.valid_to is not None and not _is_iso_date(fund.valid_to):
        errors.append("validTo must be an ISO date or null")
    if fund.valid_to is not None and fund.valid_from > fund.valid_to:
        errors.append("validFrom must be <= validTo")
    if not fund.source.strip():
        errors.append("source must be non-empty")
    if not fund.raw_object_id.strip():
        errors.append("rawObjectId must be non-empty")
    if not fund.confidence.is_finite() or fund.confidence < 0 or fund.confidence > 1:
        errors.append("confidence must be between 0 and 1")
    if fund.review_status not in _REVIEW_STATUSES:
        errors.append("reviewStatus is invalid")

    timestamps = [
        ("publishTime", fund.publish_time),
        ("ingestTime", fund.ingest_time),
        ("availableTime", fund.available_time),
        ("processingTime", fund.processing_time),
    ]
    if fund.event_time is not None:
        timestamps.insert(0, ("eventTime", fund.event_time))
    naive = [
        name for name, value in timestamps if value.tzinfo is None or value.utcoffset() is None
    ]
    if naive:
        errors.append(f"timezone required for {', '.join(naive)}")
    elif not _is_monotonic(tuple(value for _, value in timestamps)):
        errors.append("event/publish/ingest/available/processing order invalid")
    if decision_time is not None:
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            errors.append("decision_time must be timezone-aware")
        elif not naive and fund.available_time > decision_time:
            errors.append("availableTime must not be later than decision_time")

    for fee in fund.recurring_fees:
        if not fee.kind.strip():
            errors.append("recurring fee kind must be non-empty")
        if not fee.rate.is_finite() or fee.rate < 0 or fee.rate > 1:
            errors.append("recurring fee rate must be between 0 and 1")
        if not _is_iso_date(fee.valid_from):
            errors.append("recurring fee validFrom must be an ISO date")
        if fee.valid_to is not None and not _is_iso_date(fee.valid_to):
            errors.append("recurring fee validTo must be an ISO date or null")
        if fee.valid_to is not None and fee.valid_from > fee.valid_to:
            errors.append("recurring fee validFrom must be <= validTo")
        if not fee.source.strip():
            errors.append("recurring fee source must be non-empty")

    return ValidationResult(valid=not errors, errors=errors)


def _decimal_from_external(value: object) -> Decimal:
    """Convert JSON number/string values without constructing ``Decimal(float)``."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a decimal value")
    if isinstance(value, float):
        raise TypeError("float is not an accepted decimal boundary value")
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("timestamp must be an ISO 8601 string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_monotonic(values: tuple[datetime, ...]) -> bool:
    return all(left <= right for left, right in zip(values, values[1:], strict=False))


def _recurring_fees_from_dict(value: object) -> tuple[RecurringFee, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TypeError("recurringFees must be a list")
    fees: list[RecurringFee] = []
    for raw_value in cast(list[object], value):
        if not isinstance(raw_value, dict):
            raise TypeError("recurringFees entries must be objects")
        raw_fee = cast(dict[str, object], raw_value)
        fees.append(
            RecurringFee(
                kind=str(raw_fee["kind"]),
                rate=_decimal_from_external(raw_fee["rate"]),
                valid_from=str(raw_fee["validFrom"]),
                valid_to=(None if raw_fee.get("validTo") is None else str(raw_fee["validTo"])),
                source=str(raw_fee["source"]),
            )
        )
    return tuple(fees)


def _is_suffix_code(value: str) -> bool:
    if len(value) != 9 or value[6] != ".":
        return False
    return value[:6].isdigit() and value[7:] in ("SH", "SZ", "BJ")


def _is_currency_code(value: str) -> bool:
    return len(value) == 3 and value.isascii() and value.isupper() and value.isalpha()


def _is_iso_date(value: str) -> bool:
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return False
    year, month, day = value[:4], value[5:7], value[8:]
    if not (year.isdigit() and month.isdigit() and day.isdigit()):
        return False
    try:
        from datetime import date

        date(int(year), int(month), int(day))
    except ValueError:
        return False
    return True
