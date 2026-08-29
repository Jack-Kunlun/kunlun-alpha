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
    FundBenchmarkProvider,
    FundFeeProvider,
    FundInavProvider,
    FundMetadataProvider,
    FundNavProvider,
    InstrumentProvider,
    MarketDataProvider,
    NewsProvider,
    RawFundProviderResponse,
    SectorProvider,
)
from market_core.providers.ratelimit import RateLimiter
from market_core.providers.tushare import (
    TushareBarCapture,
    TushareConfig,
    TushareMarketDataProvider,
)

__all__ = [
    "CalendarProvider",
    "FundBenchmarkProvider",
    "FundFeeProvider",
    "FundInavProvider",
    "FundMetadataProvider",
    "FundNavProvider",
    "InstrumentProvider",
    "MarketDataProvider",
    "NewsProvider",
    "RawFundProviderResponse",
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
    "TushareBarCapture",
    "TushareConfig",
    "TushareMarketDataProvider",
]
