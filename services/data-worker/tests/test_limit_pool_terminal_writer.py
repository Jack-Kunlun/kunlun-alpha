"""Controlled P2 terminal projection writer tests."""

from __future__ import annotations

from collections.abc import Mapping
from unittest.mock import Mock, patch

from data_worker.jobs.limit_pool_terminal import (
    ClickHouseLimitPoolTerminalWriter,
    ClickHouseTerminalConfig,
    materialize_and_persist_terminal_snapshot,
)
from emotion_core.limit_pool import TerminalSnapshotProjection
from emotion_core.pit import Instant


def _projection() -> TerminalSnapshotProjection:
    return TerminalSnapshotProjection(
        snapshot_id="a" * 64,
        trading_date="2026-08-25",
        event_time=Instant.parse("2026-08-25T06:40:00Z"),
        available_time=Instant.parse("2026-08-25T06:40:01Z"),
        processing_time=Instant.parse("2026-08-25T06:40:02Z"),
        revision=1,
        pool_algorithm_version="limit_pool_v2",
        ladder_algorithm_version="board_ladder_v2",
        limit_rule_version="limit_rules_v1",
        materializer_version="limit-pool-terminal-materializer-v1",
        source_versions=("vendor-a:v7",),
        evidence_ids=("evidence-1",),
        payload={"entries": []},
        payload_digest="b" * 64,
    )


def test_writer_posts_canonical_projection_to_v2_table() -> None:
    calls: list[tuple[str, Mapping[str, str], bytes, float]] = []

    def transport(
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> tuple[int, bytes]:
        calls.append((url, headers, body, timeout_seconds))
        return 200, b""

    writer = ClickHouseLimitPoolTerminalWriter(
        ClickHouseTerminalConfig(
            url="http://clickhouse:8123",
            database="kunlun",
            user="writer",
            password="secret",
        ),
        transport=transport,
    )
    assert writer.write(_projection()) == _projection()
    url, headers, body, timeout = calls[0]
    assert "database=kunlun" in url
    assert headers["x-clickhouse-user"] == "writer"
    assert headers["x-clickhouse-key"] == "secret"
    assert body.startswith(b"INSERT INTO limit_pool_terminal_snapshots_v2 FORMAT JSONEachRow\n")
    assert b'"materializer_version":"limit-pool-terminal-materializer-v1"' in body
    assert timeout == 4.0


def test_writer_sanitizes_provider_failures() -> None:
    writer = ClickHouseLimitPoolTerminalWriter(
        ClickHouseTerminalConfig(url="http://clickhouse:8123", database="kunlun", user="writer"),
        transport=lambda *_args: (500, b"secret backend diagnostics"),
    )
    try:
        writer.write(_projection())
    except RuntimeError as error:
        assert str(error) == "ClickHouse terminal write failed (500)"
    else:
        raise AssertionError("writer must fail closed")


def test_writer_rejects_unsafe_database_identifiers() -> None:
    try:
        ClickHouseTerminalConfig(
            url="http://clickhouse:8123",
            database="kunlun; DROP TABLE x",
            user="writer",
        )
    except ValueError as error:
        assert "database" in str(error)
    else:
        raise AssertionError("unsafe database identifier was accepted")


def test_governed_entrypoint_materializes_then_persists() -> None:
    projection = _projection()
    writer = Mock()
    writer.write.return_value = projection

    with patch(
        "data_worker.jobs.limit_pool_terminal.materialize_terminal_snapshot",
        return_value=projection,
    ) as materialize:
        result = materialize_and_persist_terminal_snapshot(
            writer,
            pool_snapshot=Mock(),
            ladder_snapshot=Mock(),
            entries=(),
            previous_day_eligible_counts={},
            available_time=Instant.parse("2026-08-25T06:40:01Z"),
            processing_time=Instant.parse("2026-08-25T06:40:02Z"),
            revision=1,
        )

    assert result is projection
    materialize.assert_called_once()
    writer.write.assert_called_once_with(projection)
