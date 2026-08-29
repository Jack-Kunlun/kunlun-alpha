"""Real market-data collection composition."""

from data_worker.jobs.market_data.collector import MarketDataCollectionResult, MarketDataCollector
from data_worker.jobs.market_data.quality import (
    MarketDataQualitySink,
    QualityEvidenceConflictError,
    QualitySinkError,
)

__all__ = [
    "MarketDataCollectionResult",
    "MarketDataCollector",
    "MarketDataQualitySink",
    "QualityEvidenceConflictError",
    "QualitySinkError",
]
