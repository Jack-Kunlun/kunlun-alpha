"""Provider contract tests.

Covers the provider abstraction's key behaviours: timeout, rate limiting,
empty pages, capability declaration and the error taxonomy. Mock providers
stand in for vendor SDKs, proving engines can depend on the interface alone.
"""

from __future__ import annotations

import pytest
from ashare_contracts.providers import (
    Capability,
    ProviderErrorCode,
)
from market_core.providers import (
    ProviderAuthError,
    ProviderDataError,
    ProviderError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimiter,
)
from market_core.providers.mock import MockInstrumentProvider


def test_timeout_raises_typed_error() -> None:
    provider = MockInstrumentProvider(timeout=True)
    with pytest.raises(ProviderTimeoutError) as exc_info:
        provider.fetch_instruments("SH")
    assert exc_info.value.code is ProviderErrorCode.TIMEOUT


def test_rate_limiter_raises_after_bucket_drains() -> None:
    limiter = RateLimiter(max_requests=1, period_seconds=60.0)
    limiter.acquire()  # consumes the only token
    with pytest.raises(ProviderRateLimitError):
        limiter.acquire()


def test_empty_page_signals_end_of_results() -> None:
    provider = MockInstrumentProvider(empty_page=True)
    page = provider.fetch_instruments("SH")
    assert page.items == []
    assert page.next_cursor is None


def test_normal_page_returns_items() -> None:
    provider = MockInstrumentProvider()
    page = provider.fetch_instruments("SH")
    assert len(page.items) == 1
    assert page.items[0].unified_code == "SH.600000"
    assert page.next_cursor is None


def test_capability_declaration() -> None:
    provider = MockInstrumentProvider()
    assert provider.supports(Capability.FETCH_INSTRUMENTS)
    assert not provider.supports(Capability.FETCH_NEWS)


def test_require_raises_for_missing_capability() -> None:
    provider = MockInstrumentProvider()
    with pytest.raises(NotImplementedError):
        provider.require(Capability.FETCH_NEWS)


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (ProviderTimeoutError(), ProviderErrorCode.TIMEOUT),
        (ProviderRateLimitError(), ProviderErrorCode.RATE_LIMIT),
        (ProviderAuthError(), ProviderErrorCode.AUTH),
        (ProviderNotFoundError(), ProviderErrorCode.NOT_FOUND),
        (ProviderDataError(), ProviderErrorCode.DATA_ERROR),
        (ProviderUnavailableError(), ProviderErrorCode.UNAVAILABLE),
    ],
)
def test_error_taxonomy(error: ProviderError, expected_code: ProviderErrorCode) -> None:
    assert error.code is expected_code
