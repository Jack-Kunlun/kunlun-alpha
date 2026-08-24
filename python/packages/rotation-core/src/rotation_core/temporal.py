"""Strict point-in-time helpers for sector rotation."""

from __future__ import annotations

from datetime import UTC, date, datetime


def parse_instant(value: object) -> datetime:
    """Parse a timezone-aware instant and normalize it to UTC."""
    if not isinstance(value, str):
        raise TypeError("instant must be a string")
    text = value.strip()
    if not text:
        raise ValueError("instant must be non-empty")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 instant: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("instant must include a timezone offset")
    return parsed.astimezone(UTC)


def canonical_instant(value: str) -> str:
    """Return a millisecond UTC ISO-8601 representation."""
    return parse_instant(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_date(value: object) -> date:
    """Parse an exact YYYY-MM-DD date."""
    if not isinstance(value, str):
        raise TypeError("date must be a string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid YYYY-MM-DD date: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"date must use YYYY-MM-DD form: {value!r}")
    return parsed
