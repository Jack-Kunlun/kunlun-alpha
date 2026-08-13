"""Provider error taxonomy.

Every provider failure is classified into one of these stable codes so engines
can retry or fall back without depending on vendor-specific exceptions.
"""

from __future__ import annotations

from enum import Enum


class ProviderErrorCode(str, Enum):
    """Stable error classification shared across all providers."""

    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    AUTH = "AUTH"
    NOT_FOUND = "NOT_FOUND"
    DATA_ERROR = "DATA_ERROR"
    UNAVAILABLE = "UNAVAILABLE"
