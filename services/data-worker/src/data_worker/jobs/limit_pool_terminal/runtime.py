"""One-shot composition root for canonical limit-pool terminal materialization."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, Never, cast

from data_worker.jobs.limit_pool_terminal import materialize_and_persist_terminal_snapshot
from data_worker.jobs.limit_pool_terminal.writer import (
    ClickHouseLimitPoolTerminalWriter,
    ClickHouseTerminalConfig,
    HttpTransport,
)
from emotion_core.ladder import BoardLadderSnapshot
from emotion_core.limit_pool import TerminalInstrumentEvidence, TerminalSnapshotProjection
from emotion_core.models import (
    LimitPoolSnapshot,
    SnapshotObservationProvenance,
)
from emotion_core.pit import Instant
from emotion_core.provenance import SampleProvenance

Completeness = Literal["COMPLETE", "PARTIAL"]
Exchange = Literal["SH", "SZ", "BJ"]
ListingBoard = Literal["MAIN", "CHINEXT", "STAR", "BSE"]
PoolSide = Literal["LIMIT_UP", "LIMIT_DOWN"]
PoolState = Literal["SEALED", "OPENED", "LIMIT_DOWN"]
_MAX_REQUEST_BYTES = 2_000_000


@dataclass(frozen=True)
class LimitPoolTerminalMaterializationRequest:
    pool_snapshot: LimitPoolSnapshot
    ladder_snapshot: BoardLadderSnapshot
    entries: tuple[TerminalInstrumentEvidence, ...]
    previous_day_eligible_counts: Mapping[int, int]
    available_time: Instant
    processing_time: Instant
    revision: int
    previous_trading_date: str | None
    completeness: Completeness
    missing_reasons: tuple[str, ...]


def _record(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    record = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in record):
        raise ValueError(f"{field} must have string keys")
    return cast(dict[str, object], record)


def _field(record: Mapping[str, object], key: str) -> object:
    if key not in record:
        raise ValueError(f"{key} is required")
    return record[key]


def _string(record: Mapping[str, object], key: str) -> str:
    value = _field(record, key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_string(record: Mapping[str, object], key: str) -> str | None:
    value = _field(record, key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be null or a non-empty string")
    return value


def _integer(record: Mapping[str, object], key: str) -> int:
    value = _field(record, key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _boolean(record: Mapping[str, object], key: str) -> bool:
    value = _field(record, key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _items(record: Mapping[str, object], key: str) -> list[object]:
    value = _field(record, key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array")
    return cast(list[object], value)


def _strings(record: Mapping[str, object], key: str) -> tuple[str, ...]:
    values = _items(record, key)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{key} must contain non-empty strings")
    return tuple(cast(list[str], values))


def _choice(record: Mapping[str, object], key: str, allowed: set[str]) -> str:
    value = _string(record, key)
    if value not in allowed:
        raise ValueError(f"{key} has an unsupported value")
    return value


def _instant(record: Mapping[str, object], key: str) -> Instant:
    return Instant.parse(_string(record, key))


def _optional_instant(record: Mapping[str, object], key: str) -> Instant | None:
    value = _optional_string(record, key)
    return None if value is None else Instant.parse(value)


def _decimal(record: Mapping[str, object], key: str) -> Decimal:
    value = _string(record, key)
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{key} must be a decimal string") from error
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{key} must be a positive finite decimal")
    return parsed


def _reject_non_finite_json(value: str) -> Never:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _observation_provenance(value: object) -> SnapshotObservationProvenance:
    record = _record(value, "poolSnapshot.provenance[]")
    return SnapshotObservationProvenance(
        unified_code=_string(record, "unifiedCode"),
        event_time=_string(record, "eventTime"),
        available_time=_string(record, "availableTime"),
        revision=_integer(record, "revision"),
        source=_string(record, "source"),
        source_version=_string(record, "sourceVersion"),
        evidence_id=_string(record, "evidenceId"),
    )


def _pool_snapshot(record: Mapping[str, object]) -> LimitPoolSnapshot:
    provenance = tuple(_observation_provenance(value) for value in _items(record, "provenance"))
    return LimitPoolSnapshot(
        date=_string(record, "date"),
        timestamp=_string(record, "timestamp"),
        limit_up_count=_integer(record, "limitUpCount"),
        limit_down_count=_integer(record, "limitDownCount"),
        sealed_count=_integer(record, "sealedCount"),
        limit_up_instruments=_strings(record, "limitUpInstruments"),
        limit_down_instruments=_strings(record, "limitDownInstruments"),
        first_seal_time=_optional_string(record, "firstSealTime"),
        last_seal_time=_optional_string(record, "lastSealTime"),
        total_open_count=_integer(record, "totalOpenCount"),
        provenance=provenance,
        algorithm_version=_string(record, "algorithmVersion"),
        limit_rule_version=_string(record, "limitRuleVersion"),
    )


def _integer_keyed_records(
    record: Mapping[str, object],
    key: str,
) -> dict[int, object]:
    raw = _record(_field(record, key), key)
    parsed: dict[int, object] = {}
    for raw_key, value in raw.items():
        try:
            parsed_key = int(raw_key)
        except ValueError as error:
            raise ValueError(f"{key} keys must be integers") from error
        if parsed_key < 1 or str(parsed_key) != raw_key:
            raise ValueError(f"{key} keys must be positive canonical integers")
        parsed[parsed_key] = value
    return parsed


def _ladder_snapshot(record: Mapping[str, object]) -> BoardLadderSnapshot:
    raw_boards = _integer_keyed_records(record, "boards")
    boards: dict[int, list[str]] = {}
    for level, value in raw_boards.items():
        wrapped = {"codes": value}
        boards[level] = list(_strings(wrapped, "codes"))

    raw_advancement = _integer_keyed_records(record, "advancement")
    advancement: dict[int, float] = {}
    for level, value in raw_advancement.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("advancement values must be numeric")
        parsed = float(value)
        if not math.isfinite(parsed) or not 0 <= parsed <= 1:
            raise ValueError("advancement values must be finite ratios")
        advancement[level] = parsed

    provenance = _record(_field(record, "provenance"), "ladderSnapshot.provenance")
    return BoardLadderSnapshot(
        date=_string(record, "date"),
        boards=boards,
        advancement=advancement,
        provenance=SampleProvenance(
            algorithm_version=_string(provenance, "algorithmVersion"),
            as_of=_string(provenance, "asOf"),
            included=_strings(provenance, "included"),
            source_versions=_strings(provenance, "sourceVersions"),
            evidence_ids=_strings(provenance, "evidenceIds"),
        ),
        version=_string(record, "version"),
    )


def _entry(value: object) -> TerminalInstrumentEvidence:
    record = _record(value, "entries[]")
    return TerminalInstrumentEvidence(
        instrument_id=_string(record, "instrumentId"),
        name=_string(record, "name"),
        exchange=cast(Exchange, _choice(record, "exchange", {"SH", "SZ", "BJ"})),
        listing_board=cast(
            ListingBoard,
            _choice(record, "listingBoard", {"MAIN", "CHINEXT", "STAR", "BSE"}),
        ),
        is_st=_boolean(record, "isSt"),
        side=cast(PoolSide, _choice(record, "side", {"LIMIT_UP", "LIMIT_DOWN"})),
        state=cast(
            PoolState,
            _choice(record, "state", {"SEALED", "OPENED", "LIMIT_DOWN"}),
        ),
        streak_days=_integer(record, "streakDays"),
        previous_streak_days=_integer(record, "previousStreakDays"),
        open_count=_integer(record, "openCount"),
        price_cny=_decimal(record, "priceCny"),
        previous_close_cny=_decimal(record, "previousCloseCny"),
        first_seal_time=_optional_instant(record, "firstSealTime"),
        last_seal_time=_optional_instant(record, "lastSealTime"),
        event_time=_instant(record, "eventTime"),
        available_time=_instant(record, "availableTime"),
        revision=_integer(record, "revision"),
        source_version=_string(record, "sourceVersion"),
        evidence_id=_string(record, "evidenceId"),
    )


def load_materialization_request(path: Path) -> LimitPoolTerminalMaterializationRequest:
    """Load and strictly validate one bounded external materialization request."""
    if path.stat().st_size > _MAX_REQUEST_BYTES:
        raise ValueError("limit-pool materialization request is too large")
    with path.open(encoding="utf-8") as handle:
        root = _record(
            cast(object, json.load(handle, parse_constant=_reject_non_finite_json)),
            "request",
        )

    counts = _integer_keyed_records(root, "previousDayEligibleCounts")
    previous_day_eligible_counts: dict[int, int] = {}
    for level, value in counts.items():
        wrapped = {"count": value}
        previous_day_eligible_counts[level] = _integer(wrapped, "count")

    completeness = cast(
        Completeness,
        _choice(root, "completeness", {"COMPLETE", "PARTIAL"}),
    )
    return LimitPoolTerminalMaterializationRequest(
        pool_snapshot=_pool_snapshot(_record(_field(root, "poolSnapshot"), "poolSnapshot")),
        ladder_snapshot=_ladder_snapshot(_record(_field(root, "ladderSnapshot"), "ladderSnapshot")),
        entries=tuple(_entry(value) for value in _items(root, "entries")),
        previous_day_eligible_counts=previous_day_eligible_counts,
        available_time=_instant(root, "availableTime"),
        processing_time=_instant(root, "processingTime"),
        revision=_integer(root, "revision"),
        previous_trading_date=_optional_string(root, "previousTradingDate"),
        completeness=completeness,
        missing_reasons=_strings(root, "missingReasons"),
    )


def run_materialization_file(
    path: Path,
    config: ClickHouseTerminalConfig,
    *,
    transport: HttpTransport | None = None,
) -> TerminalSnapshotProjection:
    """Compose the canonical materializer and ClickHouse writer for one request."""
    request = load_materialization_request(path)
    writer = (
        ClickHouseLimitPoolTerminalWriter(config)
        if transport is None
        else ClickHouseLimitPoolTerminalWriter(config, transport=transport)
    )
    return materialize_and_persist_terminal_snapshot(
        writer,
        pool_snapshot=request.pool_snapshot,
        ladder_snapshot=request.ladder_snapshot,
        entries=request.entries,
        previous_day_eligible_counts=request.previous_day_eligible_counts,
        available_time=request.available_time,
        processing_time=request.processing_time,
        revision=request.revision,
        previous_trading_date=request.previous_trading_date,
        completeness=request.completeness,
        missing_reasons=request.missing_reasons,
    )


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} is required")
    return value


def main() -> None:
    """Materialize one configured request and exit non-zero on any failure."""
    timeout_value = os.environ.get("CLICKHOUSE_TIMEOUT_SECONDS", "4")
    try:
        timeout_seconds = float(timeout_value)
    except ValueError as error:
        raise RuntimeError("CLICKHOUSE_TIMEOUT_SECONDS must be numeric") from error
    projection = run_materialization_file(
        Path(_required_environment("LIMIT_POOL_TERMINAL_REQUEST_FILE")),
        ClickHouseTerminalConfig(
            url=_required_environment("CLICKHOUSE_URL"),
            database=_required_environment("CLICKHOUSE_DATABASE"),
            user=_required_environment("CLICKHOUSE_USER"),
            password=os.environ.get("CLICKHOUSE_PASSWORD") or None,
            timeout_seconds=timeout_seconds,
        ),
    )
    print(f"Materialized limit-pool terminal snapshot {projection.snapshot_id}")


if __name__ == "__main__":
    main()
