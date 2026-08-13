"""Bar and tick normalization.

Turns raw provider records (dicts) into domain models. A missing required
column raises :class:`MissingFieldError` so the record is routed to the
rejection zone instead of being silently dropped or half-filled.
"""

from __future__ import annotations

from market_core.models.validators import Bar, Tick, bar_from_dict, tick_from_dict


class MissingFieldError(Exception):
    """A required column is absent from the raw record."""


_REQUIRED_BAR_FIELDS = (
    "unifiedCode",
    "exchange",
    "date",
    "interval",
    "session",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "priceType",
)

_REQUIRED_TICK_FIELDS = (
    "unifiedCode",
    "exchange",
    "date",
    "timestamp",
    "price",
    "volume",
    "amount",
    "direction",
    "tradeType",
)


def _require(record: dict[str, object], fields: tuple[str, ...]) -> None:
    missing = [f for f in fields if f not in record]
    if missing:
        raise MissingFieldError(f"missing required fields: {', '.join(missing)}")


def normalize_bar(record: dict[str, object]) -> Bar:
    """Normalize a raw bar record into a :class:`Bar` model."""
    _require(record, _REQUIRED_BAR_FIELDS)
    return bar_from_dict(record)


def normalize_tick(record: dict[str, object]) -> Tick:
    """Normalize a raw tick record into a :class:`Tick` model."""
    _require(record, _REQUIRED_TICK_FIELDS)
    return tick_from_dict(record)
