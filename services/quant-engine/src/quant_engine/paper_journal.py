"""Hash-linked durable command journal for the local paper workspace."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import cast

PAPER_JOURNAL_SCHEMA_VERSION = "paper-workspace-command-v1"
PAPER_JOURNAL_GENESIS_DIGEST = "0" * 64
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_KINDS = frozenset({"CREATE_ACCOUNT", "SIMULATE"})
_FIELDS = frozenset(
    {
        "schemaVersion",
        "sequence",
        "kind",
        "occurredAt",
        "command",
        "previousDigest",
        "digest",
    }
)
_MAX_JOURNAL_BYTES = 16 * 1024 * 1024
_MAX_RECORD_BYTES = 64 * 1024


class PaperCommandJournalError(ValueError):
    """The durable command journal could not be safely read or written."""


@dataclass(frozen=True, slots=True)
class PaperJournalEntry:
    sequence: int
    kind: str
    occurred_at: datetime
    command: dict[str, object]
    previous_digest: str
    digest: str


def _instant(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PaperCommandJournalError("journal timestamp must be timezone-aware")
    return value.isoformat()


def _parse_instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise PaperCommandJournalError("journal occurredAt must be RFC3339")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PaperCommandJournalError("journal occurredAt must be RFC3339") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PaperCommandJournalError("journal occurredAt must include a timezone")
    return parsed


def _canonical(payload: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise PaperCommandJournalError("journal command must be JSON serializable") from error


def _digest_payload(payload: Mapping[str, object]) -> str:
    return sha256(_canonical(payload)).hexdigest()


class PaperCommandJournal:
    """Append-only single-process journal with a validated digest chain."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = RLock()
        self._entries = self._load()

    @property
    def entries(self) -> tuple[PaperJournalEntry, ...]:
        return self._entries

    def append(
        self,
        *,
        kind: str,
        occurred_at: datetime,
        command: Mapping[str, object],
    ) -> PaperJournalEntry:
        if kind not in _KINDS:
            raise PaperCommandJournalError("unsupported journal command kind")
        with self._lock:
            previous = (
                PAPER_JOURNAL_GENESIS_DIGEST if not self._entries else self._entries[-1].digest
            )
            payload: dict[str, object] = {
                "schemaVersion": PAPER_JOURNAL_SCHEMA_VERSION,
                "sequence": len(self._entries) + 1,
                "kind": kind,
                "occurredAt": _instant(occurred_at),
                "command": dict(command),
                "previousDigest": previous,
            }
            record = {**payload, "digest": _digest_payload(payload)}
            encoded = _canonical(record) + b"\n"
            if len(encoded) > _MAX_RECORD_BYTES:
                raise PaperCommandJournalError("journal record exceeds size limit")
            self._append_bytes(encoded)
            entry = self._entry(record, len(self._entries) + 1, previous)
            self._entries = (*self._entries, entry)
            return entry

    def _load(self) -> tuple[PaperJournalEntry, ...]:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists():
                return ()
            if self._path.stat().st_size > _MAX_JOURNAL_BYTES:
                raise PaperCommandJournalError("journal exceeds size limit")
            raw_lines = self._path.read_bytes().splitlines()
        except OSError as error:
            raise PaperCommandJournalError(f"failed to read journal: {error}") from error

        entries: list[PaperJournalEntry] = []
        previous = PAPER_JOURNAL_GENESIS_DIGEST
        for expected_sequence, raw_line in enumerate(raw_lines, start=1):
            if not raw_line or len(raw_line) > _MAX_RECORD_BYTES:
                raise PaperCommandJournalError("journal contains an invalid record size")
            try:
                value: object = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise PaperCommandJournalError("journal contains invalid JSON") from error
            if not isinstance(value, dict):
                raise PaperCommandJournalError("journal record must be an object")
            entries.append(self._entry(cast(dict[str, object], value), expected_sequence, previous))
            previous = entries[-1].digest
        return tuple(entries)

    @staticmethod
    def _entry(
        record: Mapping[str, object],
        expected_sequence: int,
        expected_previous: str,
    ) -> PaperJournalEntry:
        if frozenset(record) != _FIELDS:
            raise PaperCommandJournalError("journal record fields are invalid")
        if record.get("schemaVersion") != PAPER_JOURNAL_SCHEMA_VERSION:
            raise PaperCommandJournalError("journal schema version is unsupported")
        sequence = record.get("sequence")
        if type(sequence) is not int or sequence != expected_sequence:
            raise PaperCommandJournalError("journal sequence is not contiguous")
        kind = record.get("kind")
        if not isinstance(kind, str) or kind not in _KINDS:
            raise PaperCommandJournalError("journal command kind is invalid")
        previous = record.get("previousDigest")
        if previous != expected_previous:
            raise PaperCommandJournalError("journal digest chain is broken")
        digest = record.get("digest")
        if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
            raise PaperCommandJournalError("journal digest is invalid")
        command = record.get("command")
        if not isinstance(command, dict):
            raise PaperCommandJournalError("journal command must be an object")
        untyped_command = cast(dict[object, object], command)
        if not all(isinstance(key, str) for key in untyped_command):
            raise PaperCommandJournalError("journal command must use string keys")
        typed_command = cast(dict[str, object], untyped_command)
        payload = {key: value for key, value in record.items() if key != "digest"}
        if _digest_payload(payload) != digest:
            raise PaperCommandJournalError("journal digest does not match content")
        return PaperJournalEntry(
            sequence=sequence,
            kind=kind,
            occurred_at=_parse_instant(record.get("occurredAt")),
            command=typed_command,
            previous_digest=cast(str, previous),
            digest=digest,
        )

    def _append_bytes(self, encoded: bytes) -> None:
        try:
            current_size = self._path.stat().st_size if self._path.exists() else 0
            if current_size + len(encoded) > _MAX_JOURNAL_BYTES:
                raise PaperCommandJournalError("journal exceeds size limit")
            descriptor = os.open(
                self._path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            with os.fdopen(descriptor, "ab", closefd=True) as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            if os.name != "nt":
                parent_descriptor = os.open(self._path.parent, os.O_RDONLY)
                try:
                    os.fsync(parent_descriptor)
                finally:
                    os.close(parent_descriptor)
        except PaperCommandJournalError:
            raise
        except OSError as error:
            raise PaperCommandJournalError(f"failed to append journal: {error}") from error
