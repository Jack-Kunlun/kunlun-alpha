"""P6-N03 terminal materialization and persistence entrypoints."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from data_worker.jobs.limit_pool_terminal.writer import (
    ClickHouseLimitPoolTerminalWriter,
    ClickHouseTerminalConfig,
    HttpTransport,
    LimitPoolTerminalWriter,
)
from emotion_core.ladder import BoardLadderSnapshot
from emotion_core.limit_pool import (
    TerminalInstrumentEvidence,
    TerminalSnapshotProjection,
    materialize_terminal_snapshot,
)
from emotion_core.models import LimitPoolSnapshot
from emotion_core.pit import Instant

Completeness = Literal["COMPLETE", "PARTIAL"]


def materialize_and_persist_terminal_snapshot(
    writer: LimitPoolTerminalWriter,
    *,
    pool_snapshot: LimitPoolSnapshot,
    ladder_snapshot: BoardLadderSnapshot,
    entries: Sequence[TerminalInstrumentEvidence],
    previous_day_eligible_counts: Mapping[int, int],
    available_time: Instant,
    processing_time: Instant,
    revision: int,
    previous_trading_date: str | None = None,
    completeness: Completeness = "COMPLETE",
    missing_reasons: Sequence[str] = (),
) -> TerminalSnapshotProjection:
    """Materialize with canonical upstream versions, then persist the row."""
    projection = materialize_terminal_snapshot(
        pool_snapshot=pool_snapshot,
        ladder_snapshot=ladder_snapshot,
        entries=entries,
        previous_day_eligible_counts=previous_day_eligible_counts,
        available_time=available_time,
        processing_time=processing_time,
        revision=revision,
        previous_trading_date=previous_trading_date,
        completeness=completeness,
        missing_reasons=missing_reasons,
    )
    return writer.write(projection)


__all__ = [
    "ClickHouseLimitPoolTerminalWriter",
    "ClickHouseTerminalConfig",
    "HttpTransport",
    "LimitPoolTerminalWriter",
    "materialize_and_persist_terminal_snapshot",
]
