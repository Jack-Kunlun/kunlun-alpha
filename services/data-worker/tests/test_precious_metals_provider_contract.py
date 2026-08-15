"""RED tests for independently gated precious-metals provider capabilities."""

from __future__ import annotations

import pytest
from ashare_contracts.providers import Capability
from market_core.providers import interfaces
from market_core.providers.base import Provider


class MetadataOnlyProvider(Provider):
    def capabilities(self) -> frozenset[Capability]:
        metadata = getattr(Capability, "FETCH_FUND_METADATA", None)
        assert metadata is not None
        return frozenset({metadata})

    def fetch_fund_metadata(self, exchange: str, cursor: object = None) -> object:
        return {"unifiedCode": "518880.SH"}


def test_each_precious_metals_capability_is_a_distinct_provider_gate() -> None:
    names = (
        "FETCH_FUND_METADATA",
        "FETCH_FUND_NAV",
        "FETCH_FUND_INAV",
        "FETCH_FUND_BENCHMARK",
        "FETCH_FUND_FEES",
    )
    values = [getattr(Capability, name, None) for name in names]
    assert all(value is not None for value in values)
    assert len(set(values)) == 5


def test_unsupported_capability_fails_fast_without_fabricated_values() -> None:
    provider = MetadataOnlyProvider()

    metadata = getattr(Capability, "FETCH_FUND_METADATA", None)
    assert metadata is not None
    provider.require(metadata)
    for name in (
        "FETCH_FUND_NAV",
        "FETCH_FUND_INAV",
        "FETCH_FUND_BENCHMARK",
        "FETCH_FUND_FEES",
    ):
        capability = getattr(Capability, name, None)
        assert capability is not None
        with pytest.raises(NotImplementedError):
            provider.require(capability)


def test_provider_interface_family_exposes_one_method_per_capability() -> None:
    for name in (
        "FundMetadataProvider",
        "FundNavProvider",
        "FundInavProvider",
        "FundBenchmarkProvider",
        "FundFeeProvider",
    ):
        interface = getattr(interfaces, name, None)
        assert interface is not None
        assert interface.__abstractmethods__
