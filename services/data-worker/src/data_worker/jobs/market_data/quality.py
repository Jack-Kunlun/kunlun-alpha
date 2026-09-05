"""Immutable, file-backed quality evidence for rejected market captures."""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol, cast

from data_worker.normalize.rejection import RejectedRecord
from data_worker.raw.manifest import RawObjectManifest
from data_worker.raw.storage import LocalFileStorage
from market_core.validation import QualityEvent

Clock = Callable[[], datetime]
QUALITY_SCHEMA_VERSION = "market-data-quality-v1"
QUALITY_STATUS = "REJECTED"
FILTERED_STATUS = "FILTERED"
PROVIDER_PARSE_ERROR = "PROVIDER_PARSE_ERROR"
BAR_QUALITY_REJECTED = "BAR_QUALITY_REJECTED"
SINA_OVERFETCH_OUTSIDE_REQUEST = "SINA_OVERFETCH_OUTSIDE_REQUEST"
_STATUS_CODES = frozenset({QUALITY_STATUS, FILTERED_STATUS})
_REASON_CODES = frozenset(
    {PROVIDER_PARSE_ERROR, BAR_QUALITY_REJECTED, SINA_OVERFETCH_OUTSIDE_REQUEST}
)
_FILTERED_RECORD_KEYS = frozenset(
    {"rawRowIndex", "timestamp", "requestedStart", "requestedEnd", "reasonCode"}
)
_MAX_TEXT_LENGTH = 256
_MAX_EVIDENCE_BYTES = 1_048_576
_SECRET_MARKERS = ("token", "secret", "password", "credential", "cookie", "authorization", "dsn")

type RejectedInput = RejectedRecord | Mapping[str, object]
type QualityEventInput = QualityEvent | Mapping[str, object]
type FilteredRecordInput = Mapping[str, object]


class QualitySinkError(RuntimeError):
    """The quality evidence could not be safely persisted."""


class QualityEvidenceConflictError(QualitySinkError):
    """A capture id already contains different quality evidence."""


class QualityPublisher(Protocol):
    """Optional public evidence publication hook."""

    def publish_capture(self) -> object:
        """Publish the durable quality tree after the raw envelope is safe."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _controlled_text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        if allow_empty and value == "":
            return ""
        raise QualitySinkError(f"quality evidence {field_name} is invalid")
    text = value.strip()
    if len(text) > _MAX_TEXT_LENGTH or any(ord(char) < 32 for char in text):
        raise QualitySinkError(f"quality evidence {field_name} is invalid")
    lowered = text.casefold()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        raise QualitySinkError(f"quality evidence {field_name} contains unsafe material")
    return text


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise QualitySinkError("quality evidence contains a non-finite number")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise QualitySinkError("quality evidence contains a non-finite decimal")
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise QualitySinkError("quality evidence datetime must be timezone-aware")
        return value.isoformat()
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        result: dict[str, object] = {}
        for raw_key, raw_item in mapping.items():
            if not isinstance(raw_key, str):
                raise QualitySinkError("quality evidence object keys must be strings")
            key = _controlled_text(raw_key, "record key")
            result[key] = _json_safe(raw_item)
        return result
    if isinstance(value, (list, tuple)):
        sequence = cast(list[object] | tuple[object, ...], value)
        return [_json_safe(item) for item in sequence]
    raise QualitySinkError("quality evidence contains an unsupported value")


def _rejected_record(value: RejectedInput) -> dict[str, object]:
    if isinstance(value, RejectedRecord):
        raw_record: object = cast(object, value.record)
        raw_reason: object = cast(object, value.reason)
    else:  # pragma: no cover - protected by the TypeAlias
        mapping = value
        raw_record = mapping.get("record")
        raw_reason = mapping.get("reason")
    if not isinstance(raw_record, Mapping):
        raise QualitySinkError("quality evidence rejected record payload is invalid")
    safe_record = _json_safe(cast(Mapping[object, object], raw_record))
    if not isinstance(safe_record, dict):  # pragma: no cover - Mapping becomes dict above
        raise QualitySinkError("quality evidence rejected record payload is invalid")
    return {"record": safe_record, "reason": _controlled_text(raw_reason, "rejection reason")}


def _quality_event(value: QualityEventInput) -> dict[str, object]:
    if isinstance(value, QualityEvent):
        kind: object = value.kind
        unified_code: object = value.unified_code
        timestamp: object = value.timestamp
        detail: object = value.detail
    else:
        mapping = value
        kind = mapping.get("kind")
        unified_code = mapping.get("unifiedCode", mapping.get("unified_code"))
        timestamp = mapping.get("timestamp")
        detail = mapping.get("detail")
    if isinstance(timestamp, datetime):
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise QualitySinkError("quality event timestamp must be timezone-aware")
        normalized_timestamp = timestamp.astimezone(UTC).isoformat()
    else:
        normalized_timestamp = _controlled_text(
            timestamp,
            "event timestamp",
            allow_empty=True,
        )
    return {
        "kind": _controlled_text(kind, "event kind"),
        "unifiedCode": _controlled_text(unified_code, "event code", allow_empty=True),
        "timestamp": normalized_timestamp,
        "detail": _controlled_text(detail, "event detail"),
    }


def _filtered_record(value: object) -> dict[str, object]:
    """Validate and canonicalize one provider exclusion without raw payloads."""

    if not isinstance(value, Mapping):
        raise QualitySinkError("quality evidence filtered record payload is invalid")
    mapping = cast(Mapping[str, object], value)
    if frozenset(mapping.keys()) != _FILTERED_RECORD_KEYS:
        raise QualitySinkError("quality evidence filtered record payload is invalid")

    raw_row_index = mapping["rawRowIndex"]
    if type(raw_row_index) is not int or raw_row_index < 0:
        raise QualitySinkError("quality evidence filtered row index is invalid")

    raw_timestamp = _controlled_text(mapping["timestamp"], "filtered timestamp")
    try:
        parsed_timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise QualitySinkError("quality evidence filtered timestamp is invalid") from error
    if parsed_timestamp.tzinfo is None or parsed_timestamp.utcoffset() is None:
        raise QualitySinkError("quality evidence filtered timestamp must be timezone-aware")

    raw_start = _controlled_text(mapping["requestedStart"], "filtered requested start")
    raw_end = _controlled_text(mapping["requestedEnd"], "filtered requested end")
    try:
        requested_start = date.fromisoformat(raw_start)
        requested_end = date.fromisoformat(raw_end)
    except ValueError as error:
        raise QualitySinkError("quality evidence filtered request window is invalid") from error
    if requested_end < requested_start:
        raise QualitySinkError("quality evidence filtered request window is invalid")

    reason_code = _controlled_text(mapping["reasonCode"], "filtered reason code")
    if reason_code != SINA_OVERFETCH_OUTSIDE_REQUEST:
        raise QualitySinkError("quality evidence filtered reason code is unsupported")
    return {
        "rawRowIndex": raw_row_index,
        "timestamp": parsed_timestamp.astimezone(UTC).isoformat(),
        "requestedStart": requested_start.isoformat(),
        "requestedEnd": requested_end.isoformat(),
        "reasonCode": reason_code,
    }


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise QualitySinkError("quality evidence is not JSON serializable") from exc
    result = encoded.encode("utf-8")
    if len(result) > _MAX_EVIDENCE_BYTES:
        raise QualitySinkError("quality evidence exceeds the maximum size")
    return result


def _semantic_bytes(payload: Mapping[str, object]) -> bytes:
    semantic = dict(payload)
    semantic.pop("recordedAt", None)
    return _canonical_bytes(semantic)


class MarketDataQualitySink:
    """Publish one immutable JSON rejection envelope per capture id."""

    def __init__(
        self,
        root: Path,
        *,
        clock: Clock = _utc_now,
        publisher: QualityPublisher | None = None,
    ) -> None:
        self.root = Path(root)
        self._clock = clock
        self._publisher = publisher
        self._lock_path = self.root / ".market-quality.lock"

    def _recorded_at(self, value: datetime | None) -> datetime:
        timestamp = self._clock() if value is None else value
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise QualitySinkError("quality evidence recorded_at must be timezone-aware")
        return timestamp.astimezone(UTC)

    def _evidence_path(self, manifest: RawObjectManifest) -> Path:
        return self.root / f"{manifest.capture_id}.json"

    @staticmethod
    def _read_existing(path: Path) -> Mapping[str, object]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QualitySinkError("existing quality evidence is unreadable") from exc
        if not isinstance(raw, dict):
            raise QualitySinkError("existing quality evidence is invalid")
        return cast(Mapping[str, object], raw)

    def record(
        self,
        manifest: RawObjectManifest,
        *,
        status: str = QUALITY_STATUS,
        reason_code: str,
        reason_detail: str,
        rejected_records: Sequence[RejectedInput],
        quality_events: Sequence[QualityEventInput],
        filtered_records: Sequence[FilteredRecordInput] = (),
        recorded_at: datetime | None = None,
    ) -> Path:
        """Atomically persist controlled rejection evidence for one capture."""

        if not manifest.is_market_capture:
            raise QualitySinkError("quality evidence requires a market capture manifest")
        if status not in _STATUS_CODES:
            raise QualitySinkError("quality evidence status is unsupported")
        if reason_code not in _REASON_CODES:
            raise QualitySinkError("quality evidence reason code is unsupported")
        normalized_filtered_records = [_filtered_record(item) for item in filtered_records]
        if status == FILTERED_STATUS:
            if reason_code != SINA_OVERFETCH_OUTSIDE_REQUEST or not normalized_filtered_records:
                raise QualitySinkError("filtered quality evidence requires overfetch records")
        elif normalized_filtered_records and reason_code != BAR_QUALITY_REJECTED:
            raise QualitySinkError("rejected filtered records require bar quality rejection")
        evidence: dict[str, object] = {
            "schemaVersion": QUALITY_SCHEMA_VERSION,
            "captureId": manifest.capture_id,
            "rawObjectId": manifest.object_id,
            "rawChecksum": manifest.checksum,
            "source": manifest.source,
            "status": status,
            "reasonCode": reason_code,
            "reasonDetail": _controlled_text(reason_detail, "reason detail"),
            "rejectedRecords": [_rejected_record(item) for item in rejected_records],
            "qualityEvents": [_quality_event(item) for item in quality_events],
            "recordedAt": self._recorded_at(recorded_at).isoformat(),
        }
        if normalized_filtered_records:
            evidence["filteredRecords"] = normalized_filtered_records
        payload = _canonical_bytes(evidence)
        semantic = _semantic_bytes(evidence)
        target = self._evidence_path(manifest)
        temporary_path: Path | None = None
        try:
            with LocalFileStorage._exclusive_lock(self._lock_path):  # pyright: ignore[reportPrivateUsage]
                if target.exists():
                    existing = self._read_existing(target)
                    if _semantic_bytes(existing) != semantic:
                        raise QualityEvidenceConflictError(
                            f"quality evidence conflicts for capture {manifest.capture_id}"
                        )
                else:
                    self.root.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(
                        mode="wb",
                        dir=self.root,
                        prefix=".quality-",
                        suffix=".tmp",
                        delete=False,
                    ) as temporary:
                        temporary_path = Path(temporary.name)
                        temporary.write(payload)
                        temporary.flush()
                        os.fsync(temporary.fileno())
                    assert temporary_path is not None
                    os.replace(temporary_path, target)
                    temporary_path = None
        except QualitySinkError:
            raise
        except (OSError, ValueError) as exc:
            raise QualitySinkError("quality evidence publish failed") from exc
        finally:
            if temporary_path is not None:
                with suppress(FileNotFoundError):
                    temporary_path.unlink()
        if self._publisher is not None:
            try:
                self._publisher.publish_capture()
            except Exception as error:
                raise QualitySinkError("quality evidence public publish failed") from error
        return target


__all__ = [
    "BAR_QUALITY_REJECTED",
    "FILTERED_STATUS",
    "MarketDataQualitySink",
    "PROVIDER_PARSE_ERROR",
    "QualityEvidenceConflictError",
    "QualityPublisher",
    "QualitySinkError",
    "SINA_OVERFETCH_OUTSIDE_REQUEST",
]
