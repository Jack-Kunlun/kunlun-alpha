"""Provider error hierarchy.

Each failure is classified with a stable :class:`ProviderErrorCode` so engines
can retry transient errors (timeout / rate limit / unavailable) and fail fast
on permanent ones (auth / data error) without depending on vendor exceptions.
"""

from __future__ import annotations

from ashare_contracts.providers import ProviderErrorCode


class ProviderError(Exception):
    """Base class for all provider failures, tagged with a stable error code."""

    code: ProviderErrorCode

    def __init__(self, code: ProviderErrorCode, message: str = "") -> None:
        self.code = code
        super().__init__(message or code.value)


class ProviderTimeoutError(ProviderError):
    """The upstream call exceeded its deadline; safe to retry."""

    def __init__(self, message: str = "provider call timed out") -> None:
        super().__init__(ProviderErrorCode.TIMEOUT, message)


class ProviderRateLimitError(ProviderError):
    """The provider throttled the request; retry after backoff."""

    def __init__(self, message: str = "provider rate limit exceeded") -> None:
        super().__init__(ProviderErrorCode.RATE_LIMIT, message)


class ProviderAuthError(ProviderError):
    """Authentication or authorization failed; not retryable."""

    def __init__(self, message: str = "provider authentication failed") -> None:
        super().__init__(ProviderErrorCode.AUTH, message)


class ProviderNotFoundError(ProviderError):
    """The requested resource or page does not exist."""

    def __init__(self, message: str = "resource not found") -> None:
        super().__init__(ProviderErrorCode.NOT_FOUND, message)


class ProviderDataError(ProviderError):
    """The response was malformed or failed validation; not retryable."""

    def __init__(self, message: str = "provider returned invalid data") -> None:
        super().__init__(ProviderErrorCode.DATA_ERROR, message)


class ProviderUnavailableError(ProviderError):
    """The provider service is down; retry later."""

    def __init__(self, message: str = "provider unavailable") -> None:
        super().__init__(ProviderErrorCode.UNAVAILABLE, message)
