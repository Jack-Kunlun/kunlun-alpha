"""Canonical P6-N03 projection from Phase 2 pool and ladder outputs."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from emotion_core.ladder import LADDER_VERSION, BoardLadderSnapshot
from emotion_core.models import LimitPoolSnapshot
from emotion_core.pit import Instant

TERMINAL_MATERIALIZER_VERSION = "limit-pool-terminal-materializer-v1"

Exchange = Literal["SH", "SZ", "BJ"]
ListingBoard = Literal["MAIN", "CHINEXT", "STAR", "BSE"]
PoolSide = Literal["LIMIT_UP", "LIMIT_DOWN"]
PoolState = Literal["SEALED", "OPENED", "LIMIT_DOWN"]
Completeness = Literal["COMPLETE", "PARTIAL"]


def _iso(value: Instant) -> str:
    return value.as_utc().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _clickhouse_time(value: Instant) -> str:
    return value.as_utc().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty")
    return value


def _non_negative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _runtime_value(value: object) -> object:
    return value


@dataclass(frozen=True)
class TerminalInstrumentEvidence:
    instrument_id: str
    name: str
    exchange: Exchange
    listing_board: ListingBoard
    is_st: bool
    side: PoolSide
    state: PoolState
    streak_days: int
    previous_streak_days: int
    open_count: int
    price_cny: Decimal
    previous_close_cny: Decimal
    first_seal_time: Instant | None
    last_seal_time: Instant | None
    event_time: Instant
    available_time: Instant
    revision: int
    source_version: str
    evidence_id: str

    def __post_init__(self) -> None:
        if not self.instrument_id.endswith(f".{self.exchange}"):
            raise ValueError("instrument_id and exchange disagree")
        _non_empty(self.name, "name")
        _non_empty(self.source_version, "source_version")
        _non_empty(self.evidence_id, "evidence_id")
        runtime_is_st = _runtime_value(self.is_st)
        runtime_price = _runtime_value(self.price_cny)
        runtime_previous_close = _runtime_value(self.previous_close_cny)
        if not isinstance(runtime_is_st, bool):
            raise ValueError("is_st must be boolean")
        if (
            not isinstance(runtime_price, Decimal)
            or not runtime_price.is_finite()
            or runtime_price <= 0
        ):
            raise ValueError("price_cny must be a positive finite decimal")
        if (
            not isinstance(runtime_previous_close, Decimal)
            or not runtime_previous_close.is_finite()
            or runtime_previous_close <= 0
        ):
            raise ValueError("previous_close_cny must be a positive finite decimal")
        _non_negative_integer(self.streak_days, "streak_days")
        _non_negative_integer(self.previous_streak_days, "previous_streak_days")
        _non_negative_integer(self.open_count, "open_count")
        _non_negative_integer(self.revision, "revision")
        if self.side == "LIMIT_DOWN" and self.state != "LIMIT_DOWN":
            raise ValueError("limit-down evidence must have LIMIT_DOWN state")
        if self.side == "LIMIT_UP" and self.state == "LIMIT_DOWN":
            raise ValueError("limit-up evidence cannot have LIMIT_DOWN state")
        if self.side == "LIMIT_UP" and self.streak_days < 1:
            raise ValueError("limit-up streak_days must be positive")
        if self.event_time > self.available_time:
            raise ValueError("event_time must be <= available_time")
        if self.first_seal_time and self.first_seal_time > self.event_time:
            raise ValueError("first_seal_time must be <= event_time")
        if self.last_seal_time and self.last_seal_time > self.event_time:
            raise ValueError("last_seal_time must be <= event_time")
        if (
            self.first_seal_time
            and self.last_seal_time
            and self.first_seal_time > self.last_seal_time
        ):
            raise ValueError("first_seal_time must be <= last_seal_time")

    def as_payload(self) -> dict[str, object]:
        return {
            "instrumentId": self.instrument_id,
            "name": self.name,
            "exchange": self.exchange,
            "listingBoard": self.listing_board,
            "isSt": self.is_st,
            "side": self.side,
            "state": self.state,
            "streakDays": self.streak_days,
            "previousStreakDays": self.previous_streak_days,
            "openCount": self.open_count,
            "priceCny": format(self.price_cny, "f"),
            "previousCloseCny": format(self.previous_close_cny, "f"),
            "firstSealTime": None if self.first_seal_time is None else _iso(self.first_seal_time),
            "lastSealTime": None if self.last_seal_time is None else _iso(self.last_seal_time),
            "eventTime": _iso(self.event_time),
            "availableTime": _iso(self.available_time),
            "revision": self.revision,
            "sourceVersion": self.source_version,
            "evidenceId": self.evidence_id,
        }


@dataclass(frozen=True)
class TerminalSnapshotProjection:
    snapshot_id: str
    trading_date: str
    event_time: Instant
    available_time: Instant
    processing_time: Instant
    revision: int
    pool_algorithm_version: str
    ladder_algorithm_version: str
    limit_rule_version: str
    materializer_version: str
    source_versions: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    payload: dict[str, object]
    payload_digest: str

    def clickhouse_row(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "trading_date": self.trading_date,
            "event_time": _clickhouse_time(self.event_time),
            "available_time": _clickhouse_time(self.available_time),
            "processing_time": _clickhouse_time(self.processing_time),
            "revision": self.revision,
            "algorithm_version": self.pool_algorithm_version,
            "ladder_algorithm_version": self.ladder_algorithm_version,
            "limit_rule_version": self.limit_rule_version,
            "materializer_version": self.materializer_version,
            "source_versions": list(self.source_versions),
            "evidence_ids": list(self.evidence_ids),
            "payload_json": json.dumps(
                self.payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "payload_digest": self.payload_digest,
            "replacement_version": self.revision,
        }


def materialize_terminal_snapshot(
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
    """Materialize one deterministic ClickHouse terminal row, failing closed."""
    pool_version = _non_empty(pool_snapshot.algorithm_version, "pool_snapshot.algorithm_version")
    rule_version = _non_empty(pool_snapshot.limit_rule_version, "pool_snapshot.limit_rule_version")
    runtime_processing_time = _runtime_value(processing_time)
    if not isinstance(runtime_processing_time, Instant):
        raise ValueError("processing_time is required")
    processing_time = runtime_processing_time
    runtime_revision = _runtime_value(revision)
    if (
        isinstance(runtime_revision, bool)
        or not isinstance(runtime_revision, int)
        or runtime_revision < 0
    ):
        raise ValueError("revision must be a non-negative integer")
    validated_counts: dict[int, int] = {}
    for level, count in previous_day_eligible_counts.items():
        validated_level = _non_negative_integer(level, "previous-day eligible level")
        if validated_level < 1:
            raise ValueError("previous-day eligible level must be positive")
        validated_counts[validated_level] = _non_negative_integer(
            count, "previous-day eligible count"
        )
    validated_advancement: dict[int, float] = {}
    for level, observed in ladder_snapshot.advancement.items():
        validated_level = _non_negative_integer(level, "advancement level")
        if validated_level < 1:
            raise ValueError("advancement level must be positive")
        runtime_observed = _runtime_value(observed)
        if (
            isinstance(runtime_observed, bool)
            or not isinstance(runtime_observed, int | float)
            or not math.isfinite(runtime_observed)
            or not 0 <= runtime_observed <= 1
        ):
            raise ValueError("advancement values must be finite ratios")
        validated_advancement[validated_level] = float(runtime_observed)
    reasons = tuple(sorted(_non_empty(reason, "missing_reasons") for reason in missing_reasons))
    if completeness == "PARTIAL" and not reasons:
        raise ValueError("PARTIAL completeness requires missing_reasons")
    if completeness == "COMPLETE" and reasons:
        raise ValueError("COMPLETE completeness cannot carry missing_reasons")

    decision_time = Instant.parse(pool_snapshot.timestamp)
    if decision_time > available_time:
        raise ValueError("snapshot event time must be <= available_time")
    if available_time > processing_time:
        raise ValueError("available_time must be <= processing_time")
    if ladder_snapshot.date != pool_snapshot.date:
        raise ValueError("pool and ladder trading dates disagree")
    if ladder_snapshot.version != LADDER_VERSION:
        raise ValueError("unsupported ladder algorithm version")
    if Instant.parse(ladder_snapshot.provenance.as_of) != decision_time:
        raise ValueError("pool and ladder decision times disagree")

    ordered_entries = sorted(entries, key=lambda item: item.instrument_id)
    if len({entry.instrument_id for entry in ordered_entries}) != len(ordered_entries):
        raise ValueError("duplicate terminal instrument evidence")
    for entry in ordered_entries:
        if entry.event_time > decision_time or entry.available_time > available_time:
            raise ValueError("instrument evidence is not point-in-time eligible")

    up_codes = {entry.instrument_id for entry in ordered_entries if entry.side == "LIMIT_UP"}
    down_codes = {entry.instrument_id for entry in ordered_entries if entry.side == "LIMIT_DOWN"}
    if up_codes != set(pool_snapshot.limit_up_instruments):
        raise ValueError("limit-up instruments disagree with canonical pool snapshot")
    if down_codes != set(pool_snapshot.limit_down_instruments):
        raise ValueError("limit-down instruments disagree with canonical pool snapshot")
    if sum(entry.state == "SEALED" for entry in ordered_entries) != pool_snapshot.sealed_count:
        raise ValueError("sealed count disagrees with canonical pool snapshot")
    if sum(entry.open_count for entry in ordered_entries) != pool_snapshot.total_open_count:
        raise ValueError("open count disagrees with canonical pool snapshot")

    entry_boards: dict[int, list[str]] = {}
    for entry in ordered_entries:
        if entry.side == "LIMIT_UP":
            entry_boards.setdefault(entry.streak_days, []).append(entry.instrument_id)
    canonical_boards = {level: sorted(codes) for level, codes in ladder_snapshot.boards.items()}
    if entry_boards != canonical_boards:
        raise ValueError("terminal streaks disagree with canonical ladder snapshot")

    ladder_payload: list[dict[str, object]] = []
    for streak_days, codes in sorted(canonical_boards.items()):
        previous_level = streak_days - 1
        denominator = 0 if previous_level < 1 else validated_counts.get(previous_level, 0)
        if denominator < 0:
            raise ValueError("previous-day eligible counts must be non-negative")
        promoted = 0 if previous_level < 1 else len(codes)
        if promoted > denominator:
            raise ValueError("promoted count exceeds previous-day eligible count")
        if previous_level >= 1 and denominator:
            runtime_observed = validated_advancement.get(previous_level)
            if (
                isinstance(runtime_observed, bool)
                or not isinstance(runtime_observed, int | float)
                or not math.isfinite(runtime_observed)
                or not 0 <= runtime_observed <= 1
                or abs(runtime_observed - promoted / denominator) > 1e-12
            ):
                raise ValueError("advancement rate disagrees with canonical ladder snapshot")
        ladder_payload.append(
            {
                "streakDays": streak_days,
                "count": len(codes),
                "previousDayEligibleCount": denominator,
                "promotedCount": promoted,
            }
        )

    source_versions = tuple(
        sorted(
            {item.source_version for item in pool_snapshot.provenance}
            | set(ladder_snapshot.provenance.source_versions)
            | {entry.source_version for entry in ordered_entries}
        )
    )
    evidence_ids = tuple(
        sorted(
            {item.evidence_id for item in pool_snapshot.provenance}
            | set(ladder_snapshot.provenance.evidence_ids)
            | {entry.evidence_id for entry in ordered_entries}
        )
    )
    payload: dict[str, object] = {
        "tradingDate": pool_snapshot.date,
        "previousTradingDate": previous_trading_date,
        "completeness": completeness,
        "missingReasons": list(reasons),
        "limitUpCount": pool_snapshot.limit_up_count,
        "limitDownCount": pool_snapshot.limit_down_count,
        "sealedCount": pool_snapshot.sealed_count,
        "totalOpenCount": pool_snapshot.total_open_count,
        "ladder": ladder_payload,
        "entries": [entry.as_payload() for entry in ordered_entries],
    }
    canonical_envelope = {
        "tradingDate": pool_snapshot.date,
        "eventTime": _iso(decision_time),
        "revision": runtime_revision,
        "algorithmVersion": pool_version,
        "ladderAlgorithmVersion": LADDER_VERSION,
        "limitRuleVersion": rule_version,
        "materializerVersion": TERMINAL_MATERIALIZER_VERSION,
        "availableTime": _iso(available_time),
        "sourceVersions": list(source_versions),
        "evidenceIds": list(evidence_ids),
        "payload": payload,
    }
    canonical_payload = json.dumps(
        canonical_envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    identity = "|".join(
        (
            pool_snapshot.date,
            _iso(decision_time),
            pool_version,
            LADDER_VERSION,
            rule_version,
            TERMINAL_MATERIALIZER_VERSION,
            str(runtime_revision),
            digest,
        )
    )
    return TerminalSnapshotProjection(
        snapshot_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        trading_date=pool_snapshot.date,
        event_time=decision_time,
        available_time=available_time,
        processing_time=processing_time,
        revision=runtime_revision,
        pool_algorithm_version=pool_version,
        ladder_algorithm_version=LADDER_VERSION,
        limit_rule_version=rule_version,
        materializer_version=TERMINAL_MATERIALIZER_VERSION,
        source_versions=source_versions,
        evidence_ids=evidence_ids,
        payload=payload,
        payload_digest=digest,
    )
