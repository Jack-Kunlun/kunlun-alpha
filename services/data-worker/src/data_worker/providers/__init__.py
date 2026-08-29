"""Data-worker-owned provider adapters.

Vendor SDKs stay at this deployable adapter boundary.  Shared domain packages
depend on provider contracts, never on these SDK integrations.
"""

from data_worker.providers.akshare import (
    AKShareBarCapture,
    AKShareConfig,
    AKShareMarketDataProvider,
)

__all__ = ["AKShareBarCapture", "AKShareConfig", "AKShareMarketDataProvider"]
