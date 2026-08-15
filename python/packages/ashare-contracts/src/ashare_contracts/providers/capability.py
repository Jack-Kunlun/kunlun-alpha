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
    # Precious-metals fund capabilities are deliberately independent.  A
    # provider may expose metadata while omitting NAV, iNAV, benchmark or fee
    # data; callers must gate each endpoint separately.
    FETCH_FUND_METADATA = "FETCH_FUND_METADATA"
    FETCH_FUND_NAV = "FETCH_FUND_NAV"
    FETCH_FUND_INAV = "FETCH_FUND_INAV"
    FETCH_FUND_BENCHMARK = "FETCH_FUND_BENCHMARK"
    FETCH_FUND_FEES = "FETCH_FUND_FEES"

    # Descriptive aliases kept for adapters that use the longer endpoint
    # terminology.  They intentionally share the canonical values above so
    # capability sets remain five independent gates.
    FETCH_FUND_BENCHMARK_METADATA = "FETCH_FUND_BENCHMARK"
    FETCH_FUND_FEE_METADATA = "FETCH_FUND_FEES"
