"""Provider abstraction: capability declaration, error taxonomy, rate limiting
and cursor-paged interface family."""

from market_core.providers.base import Provider
from market_core.providers.errors import (
    ProviderAuthError,
    ProviderDataError,
    ProviderError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from market_core.providers.interfaces import (
    CalendarProvider,
    InstrumentProvider,
    MarketDataProvider,
    NewsProvider,
    SectorProvider,
)
from market_core.providers.ratelimit import RateLimiter

__all__ = [
    "CalendarProvider",
    "InstrumentProvider",
    "MarketDataProvider",
    "NewsProvider",
    "Provider",
    "ProviderAuthError",
    "ProviderDataError",
    "ProviderError",
    "ProviderNotFoundError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "RateLimiter",
    "SectorProvider",
]
