"""Provider capability declarations.

A capability is a coarse-grained feature a data provider declares it supports.
Engines query ``Provider.capabilities()`` before calling a specific method so
an unsupported call fails fast instead of reaching the vendor SDK.
"""

from __future__ import annotations

from enum import Enum


class Capability(str, Enum):
    """A coarse-grained feature a provider may support."""

    FETCH_INSTRUMENTS = "FETCH_INSTRUMENTS"
    FETCH_CALENDAR = "FETCH_CALENDAR"
    FETCH_DAILY_BARS = "FETCH_DAILY_BARS"
    FETCH_MINUTE_BARS = "FETCH_MINUTE_BARS"
    FETCH_TICKS = "FETCH_TICKS"
    FETCH_SECTORS = "FETCH_SECTORS"
    FETCH_NEWS = "FETCH_NEWS"
