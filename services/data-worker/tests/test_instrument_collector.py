"""Instrument collection job tests.

Covers idempotency (repeated runs produce an empty diff), add/change/delist
auditing, unified_code as the unique key (name changes do not change identity),
and retry behaviour for transient vs permanent provider errors.
"""

from __future__ import annotations

import pytest
from ashare_contracts.instrument_instrument import Instrument
from ashare_contracts.providers import Capability, Cursor, Page
from data_worker.jobs.instruments.collector import InstrumentCollector
from data_worker.jobs.instruments.repository import InMemoryInstrumentRepository
from market_core.providers import ProviderAuthError, ProviderRateLimitError
from market_core.providers.interfaces import InstrumentProvider


def _instrument(code: str, name: str, exchange: str = "SH") -> Instrument:
    return Instrument.model_validate(
        {
            "unifiedCode": f"{exchange}.{code}",
            "code": code,
            "exchange": exchange,
            "board": "MAIN",
            "type": "STOCK",
            "name": name,
            "tradingStatus": "LISTED",
            "currency": "CNY",
        }
    )


class FakeInstrumentProvider(InstrumentProvider):
    """Scripted provider: fixed pages, optionally raising transient/permanent errors."""

    def __init__(
        self, instruments: list[Instrument], transient_failures: int = 0, permanent: bool = False
    ) -> None:
        self._instruments = instruments
        self._transient_failures = transient_failures
        self._permanent = permanent
        self.calls = 0

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_INSTRUMENTS})

    def fetch_instruments(self, exchange: str, cursor: Cursor | None = None) -> Page[Instrument]:
        self.calls += 1
        if self._permanent:
            raise ProviderAuthError("bad credentials")
        if self._transient_failures > 0:
            self._transient_failures -= 1
            raise ProviderRateLimitError("throttled")
        return Page(items=list(self._instruments), next_cursor=None)


def test_first_run_adds_everything() -> None:
    provider = FakeInstrumentProvider(
        [_instrument("600000", "浦发银行"), _instrument("600001", "邯郸钢铁")]
    )
    repo = InMemoryInstrumentRepository()
    collector = InstrumentCollector(provider, repo)

    result = collector.collect("SH")

    assert len(result.added) == 2
    assert result.changed == []
    assert result.delisted == []
    assert len(repo.get_all("SH")) == 2


def test_repeated_run_is_idempotent() -> None:
    instruments = [_instrument("600000", "浦发银行")]
    provider = FakeInstrumentProvider(instruments)
    repo = InMemoryInstrumentRepository()
    collector = InstrumentCollector(provider, repo)

    collector.collect("SH")
    second = collector.collect("SH")

    assert second.is_empty()
    assert len(repo.get_all("SH")) == 1


def test_change_and_delist_are_audited() -> None:
    repo = InMemoryInstrumentRepository()
    provider_a = FakeInstrumentProvider(
        [_instrument("600000", "浦发银行"), _instrument("600001", "邯郸钢铁")]
    )
    InstrumentCollector(provider_a, repo).collect("SH")

    # Second run: 600000 renamed, 600001 delisted, 600002 added.
    provider_b = FakeInstrumentProvider(
        [_instrument("600000", "浦发银行(更名)"), _instrument("600002", "新增")]
    )
    result = InstrumentCollector(provider_b, repo).collect("SH")

    assert [c.unified_code for c in result.changed] == ["SH.600000"]
    assert [c.unified_code for c in result.delisted] == ["SH.600001"]
    assert [a.unified_code for a in result.added] == ["SH.600002"]

    audit = repo.audit_log()
    assert any("UPSERT SH.600000" in line for line in audit)
    assert any("DELIST SH.600001" in line for line in audit)


def test_unified_code_is_unique_key_not_name() -> None:
    repo = InMemoryInstrumentRepository()
    provider_a = FakeInstrumentProvider([_instrument("600000", "浦发银行")])
    InstrumentCollector(provider_a, repo).collect("SH")

    provider_b = FakeInstrumentProvider([_instrument("600000", "完全不同的名字")])
    result = InstrumentCollector(provider_b, repo).collect("SH")

    # Same unified code -> a change, not a delist + add.
    assert [c.unified_code for c in result.changed] == ["SH.600000"]
    assert result.delisted == []
    assert result.added == []


def test_transient_error_is_retried() -> None:
    provider = FakeInstrumentProvider([_instrument("600000", "浦发银行")], transient_failures=2)
    repo = InMemoryInstrumentRepository()
    result = InstrumentCollector(provider, repo).collect("SH")

    assert len(result.added) == 1
    assert provider.calls == 3  # 2 failures + 1 success


def test_permanent_error_fails_fast() -> None:
    provider = FakeInstrumentProvider([_instrument("600000", "浦发银行")], permanent=True)
    repo = InMemoryInstrumentRepository()

    with pytest.raises(ProviderAuthError):
        InstrumentCollector(provider, repo).collect("SH")
    assert provider.calls == 1
