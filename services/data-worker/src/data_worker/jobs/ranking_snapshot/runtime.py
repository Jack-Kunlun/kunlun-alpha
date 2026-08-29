"""One-shot local real-market ranking materialization runtime."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from data_worker.jobs.local_reference import load_local_reference_catalog
from quant_core.ranking import ranking_terminal_payload

from .materializer import build_local_ranking_snapshot
from .publisher import RankingPublishResult, RankingSnapshotPublisher
from .reader import ClickHouseRankingBarsReader, ClickHouseRankingConfig

_DEFAULT_CATALOG_PATH = Path("/workspace/data/reference/local-terminal-instruments-v1.json")


def _positive_float(environ: Mapping[str, str], name: str, default: float) -> float:
    raw = environ.get(name, str(default))
    try:
        value = float(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be numeric") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


def run_materialization(
    environ: Mapping[str, str],
    *,
    now: datetime | None = None,
) -> RankingPublishResult:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    timeout = _positive_float(environ, "RANKING_MATERIALIZER_TIMEOUT_SECONDS", 5.0)
    catalog = load_local_reference_catalog(
        Path(environ.get("LOCAL_TERMINAL_REFERENCE_FILE", str(_DEFAULT_CATALOG_PATH)))
    )
    reader = ClickHouseRankingBarsReader(
        ClickHouseRankingConfig(
            url=environ.get("CLICKHOUSE_URL", "http://localhost:8123"),
            database=environ.get("CLICKHOUSE_DATABASE", "kunlun"),
            user=environ.get("CLICKHOUSE_USER", "kunlun"),
            password=environ.get("CLICKHOUSE_PASSWORD") or None,
            timeout_seconds=timeout,
        )
    )
    bars = {
        instrument.instrument_id: reader.read(instrument.instrument_id, current, limit=20)
        for instrument in catalog.instruments
    }
    snapshot = build_local_ranking_snapshot(
        catalog=catalog,
        bars_by_instrument=bars,
        read_cutoff=current,
        generated_at=current,
    )
    publisher = RankingSnapshotPublisher(
        environ.get("QUANT_ENGINE_URL", "http://localhost:8081"),
        timeout_seconds=timeout,
    )
    return publisher.publish(ranking_terminal_payload(snapshot))


def main() -> None:
    result = run_materialization(os.environ)
    action = "published" if result.published else "already-present"
    print(f"Local real-market ranking snapshot {action}: {result.payload['snapshotId']}")


if __name__ == "__main__":
    main()
