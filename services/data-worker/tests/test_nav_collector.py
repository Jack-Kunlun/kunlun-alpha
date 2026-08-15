"""The legacy last-wins NAV collector is intentionally no longer public."""

from __future__ import annotations

import importlib


def test_legacy_nav_collector_is_private_and_unexported() -> None:
    package = importlib.import_module("data_worker.jobs.precious_metals_funds")
    collector_module = importlib.import_module(
        "data_worker.jobs.precious_metals_funds.collector"
    )
    assert not hasattr(package, "NavCollector")
    assert not hasattr(collector_module, "NavCollector")
