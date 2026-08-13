"""Rejection zone.

Abnormal records are never silently dropped: they are kept here with the
reason they were rejected, so they can be inspected, repaired and replayed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RejectedRecord:
    """A raw record that failed normalization or validation."""

    record: dict[str, object]
    reason: str


class RejectionZone:
    """Accumulates rejected records and their reasons."""

    def __init__(self) -> None:
        self._records: list[RejectedRecord] = []

    def add(self, record: dict[str, object], reason: str) -> None:
        self._records.append(RejectedRecord(record=record, reason=reason))

    def records(self) -> list[RejectedRecord]:
        return list(self._records)

    def __len__(self) -> int:
        return len(self._records)
