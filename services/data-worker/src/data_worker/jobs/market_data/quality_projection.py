"""Pure, bounded projection of raw market-quality envelopes.

The quality sink intentionally stores richer evidence for offline recovery.  This
module is the one-way boundary to the separately mounted public evidence tree:
it validates only the envelope fields needed for the projection and never
copies raw records, reasons, requests, object ids, or checksums.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import cast
from zoneinfo import ZoneInfo

from ashare_contracts.data_quality_market_quality_evidence import (
    MarketQualityEvidenceRecord,
)
from data_worker.raw.manifest import RawObjectManifest

MARKET_QUALITY_EVIDENCE_SCHEMA_VERSION = "market-quality-evidence-v1"
MARKET_QUALITY_SNAPSHOT_SCHEMA_VERSION = "market-quality-snapshot-v1"
MARKET_QUALITY_CURRENT_SCHEMA_VERSION = "market-quality-current-v1"
MARKET_QUALITY_MAX_RECORDS = 10_000
MARKET_QUALITY_MAX_BYTES = 8 * 1024 * 1024
MARKET_QUALITY_MAX_INPUT_BYTES = 1 * 1024 * 1024
MARKET_QUALITY_MAX_CANDIDATE_FILES = 10_000
MARKET_QUALITY_PAGE_LIMIT = 100
MARKET_QUALITY_MAX_RAW_ROW_INDEX = 2**53 - 1

MARKET_QUALITY_SOURCES = frozenset(
    {"tushare-pro", "akshare-tencent", "akshare-sina", "akshare-eastmoney"}
)
MARKET_QUALITY_INTERVALS = frozenset({"DAILY", "MINUTE_1", "MINUTE_5"})
MARKET_QUALITY_STATUSES = frozenset({"REJECTED", "FILTERED"})
MARKET_QUALITY_REASONS = frozenset(
    {"PROVIDER_PARSE_ERROR", "BAR_QUALITY_REJECTED", "SINA_OVERFETCH_OUTSIDE_REQUEST"}
)
MARKET_QUALITY_KINDS = frozenset(
    {"OUT_OF_ORDER", "DUPLICATE", "NEGATIVE_PRICE", "ABNORMAL_VOLUME", "MISSING_FIELD"}
)
MARKET_QUALITY_FILTER_REASON = "SINA_OVERFETCH_OUTSIDE_REQUEST"
_CODE_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EVIDENCE_ID_DOMAIN = b"kunlun.market-quality.evidence.v1\x00"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_QUALITY_KEYS = frozenset(
    {
        "schemaVersion",
        "captureId",
        "rawObjectId",
        "rawChecksum",
        "source",
        "status",
        "reasonCode",
        "reasonDetail",
        "rejectedRecords",
        "qualityEvents",
        "recordedAt",
        "filteredRecords",
    }
)
_REJECTED_RECORD_KEYS = frozenset({"record", "reason"})
_EVENT_KEYS = frozenset({"kind", "unifiedCode", "timestamp", "detail"})
_FILTERED_RECORD_KEYS = frozenset(
    {"rawRowIndex", "timestamp", "requestedStart", "requestedEnd", "reasonCode"}
)


class MarketQualityProjectionError(ValueError):
    """The raw quality envelope cannot be safely projected."""


def _mapping(value: object, message: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise MarketQualityProjectionError(message)
    return cast(Mapping[str, object], value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise MarketQualityProjectionError(f"quality evidence {field} is invalid")
    return value


def _date_text(value: object, field: str) -> str:
    candidate = _text(value, field)
    if _DATE_RE.fullmatch(candidate) is None:
        raise MarketQualityProjectionError(f"quality evidence {field} is invalid")
    try:
        date.fromisoformat(candidate)
    except ValueError as error:
        raise MarketQualityProjectionError(f"quality evidence {field} is invalid") from error
    return candidate


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise MarketQualityProjectionError(f"quality evidence {field} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MarketQualityProjectionError(f"quality evidence {field} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MarketQualityProjectionError(f"quality evidence {field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _optional_event_timestamp(value: object) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC).isoformat()


def _optional_event_code(value: object, expected_code: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or _CODE_RE.fullmatch(value) is None:
        return None
    return value if value == expected_code else None


def _evidence_id(source: str, manifest: RawObjectManifest) -> str:
    identity = (
        _EVIDENCE_ID_DOMAIN
        + source.encode("utf-8")
        + b"\x00"
        + manifest.capture_id.encode("utf-8")
        + b"\x00"
        + manifest.object_id.encode("ascii")
    )
    return "mqe-" + hashlib.sha256(identity).hexdigest()


def _validate_rejected_records(value: object) -> int:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise MarketQualityProjectionError("quality evidence rejected records are invalid")
    values = cast(Sequence[object], value)
    if len(values) > MARKET_QUALITY_MAX_RECORDS:
        raise MarketQualityProjectionError("quality evidence rejected records exceed the limit")
    for item in values:
        record = _mapping(item, "quality evidence rejected record is invalid")
        if frozenset(record.keys()) != _REJECTED_RECORD_KEYS:
            raise MarketQualityProjectionError("quality evidence rejected record is invalid")
        if not isinstance(record["record"], Mapping) or not isinstance(record["reason"], str):
            raise MarketQualityProjectionError("quality evidence rejected record is invalid")
    return len(values)


def _project_event(value: object, expected_code: str) -> dict[str, object]:
    event = _mapping(value, "quality evidence quality event is invalid")
    if frozenset(event.keys()) != _EVENT_KEYS:
        raise MarketQualityProjectionError("quality evidence quality event is invalid")
    kind = _text(event["kind"], "quality event kind")
    if kind not in MARKET_QUALITY_KINDS:
        raise MarketQualityProjectionError("quality evidence quality event kind is unsupported")
    return {
        "kind": kind,
        "unifiedCode": _optional_event_code(event["unifiedCode"], expected_code),
        "timestamp": _optional_event_timestamp(event["timestamp"]),
    }


def _project_events(value: object, expected_code: str) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise MarketQualityProjectionError("quality evidence quality events are invalid")
    values = cast(Sequence[object], value)
    if len(values) > MARKET_QUALITY_MAX_RECORDS:
        raise MarketQualityProjectionError("quality evidence quality events exceed the limit")
    return [_project_event(item, expected_code) for item in values]


def _project_filtered_record(
    value: object,
    *,
    expected_requested_start: str,
    expected_requested_end: str,
) -> dict[str, object]:
    record = _mapping(value, "quality evidence filtered record is invalid")
    if frozenset(record.keys()) != _FILTERED_RECORD_KEYS:
        raise MarketQualityProjectionError("quality evidence filtered record is invalid")
    raw_row_index = record["rawRowIndex"]
    if (
        type(raw_row_index) is not int
        or raw_row_index < 0
        or raw_row_index > MARKET_QUALITY_MAX_RAW_ROW_INDEX
    ):
        raise MarketQualityProjectionError("quality evidence filtered row index is invalid")
    timestamp = _timestamp(record["timestamp"], "filtered timestamp")
    requested_start = _date_text(record["requestedStart"], "filtered requested start")
    requested_end = _date_text(record["requestedEnd"], "filtered requested end")
    if requested_end < requested_start:
        raise MarketQualityProjectionError("quality evidence filtered request window is invalid")
    if requested_start != expected_requested_start or requested_end != expected_requested_end:
        raise MarketQualityProjectionError(
            "quality evidence filtered request window is inconsistent"
        )
    local_date = timestamp.astimezone(_SHANGHAI).date().isoformat()
    if expected_requested_start <= local_date <= expected_requested_end:
        raise MarketQualityProjectionError(
            "quality evidence filtered timestamp is in request window"
        )
    reason_code = _text(record["reasonCode"], "filtered reason code")
    if reason_code != MARKET_QUALITY_FILTER_REASON:
        raise MarketQualityProjectionError("quality evidence filtered reason code is unsupported")
    return {
        "rawRowIndex": raw_row_index,
        "timestamp": timestamp.isoformat(),
        "requestedStart": requested_start,
        "requestedEnd": requested_end,
        "reasonCode": reason_code,
    }


def _project_filtered_records(
    value: object,
    *,
    expected_requested_start: str,
    expected_requested_end: str,
) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise MarketQualityProjectionError("quality evidence filtered records are invalid")
    values = cast(Sequence[object], value)
    if len(values) > MARKET_QUALITY_MAX_RECORDS:
        raise MarketQualityProjectionError("quality evidence filtered records exceed the limit")
    projected: list[dict[str, object]] = []
    seen_indices: set[int] = set()
    for item in values:
        record = _project_filtered_record(
            item,
            expected_requested_start=expected_requested_start,
            expected_requested_end=expected_requested_end,
        )
        row_index = cast(int, record["rawRowIndex"])
        if row_index in seen_indices:
            raise MarketQualityProjectionError("quality evidence filtered row index is duplicated")
        seen_indices.add(row_index)
        projected.append(record)
    return projected


def project_market_quality_evidence(
    quality: Mapping[str, object],
    manifest: RawObjectManifest,
    *,
    published_at: datetime | None = None,
) -> dict[str, object]:
    """Project one raw quality envelope into the public allowlisted record.

    Invalid non-empty event code/timestamp values become ``null`` while the
    event kind remains visible.  Envelope identity, status, schema, and
    structural errors fail closed because they could associate evidence with
    the wrong capture.
    """

    if not manifest.is_market_capture or manifest.available_time is None:
        raise MarketQualityProjectionError("quality evidence requires a market manifest")
    if manifest.source not in MARKET_QUALITY_SOURCES:
        raise MarketQualityProjectionError("quality evidence source is unsupported")
    if manifest.unified_code is None or manifest.interval is None:
        raise MarketQualityProjectionError("quality evidence market route is incomplete")
    if manifest.interval not in MARKET_QUALITY_INTERVALS:
        raise MarketQualityProjectionError("quality evidence interval is unsupported")

    envelope = _mapping(quality, "quality evidence envelope is invalid")
    envelope_keys = frozenset(envelope)
    if not envelope_keys.issubset(_QUALITY_KEYS):
        raise MarketQualityProjectionError("quality evidence envelope contains unknown fields")
    required = _QUALITY_KEYS - {"filteredRecords"}
    if envelope_keys not in (required, _QUALITY_KEYS):
        raise MarketQualityProjectionError("quality evidence envelope is incomplete")

    if envelope["schemaVersion"] != "market-data-quality-v1":
        raise MarketQualityProjectionError("quality evidence schema is unsupported")
    if envelope["captureId"] != manifest.capture_id:
        raise MarketQualityProjectionError("quality evidence capture identity does not match")
    if envelope["rawObjectId"] != manifest.object_id:
        raise MarketQualityProjectionError("quality evidence object identity does not match")
    if envelope["rawChecksum"] != manifest.checksum:
        raise MarketQualityProjectionError("quality evidence checksum identity does not match")
    if envelope["source"] != manifest.source or envelope["source"] not in MARKET_QUALITY_SOURCES:
        raise MarketQualityProjectionError("quality evidence source identity does not match")
    if envelope["reasonDetail"] is not None and not isinstance(envelope["reasonDetail"], str):
        raise MarketQualityProjectionError("quality evidence reason detail is invalid")

    status = _text(envelope["status"], "status")
    reason_code = _text(envelope["reasonCode"], "reason code")
    if status not in MARKET_QUALITY_STATUSES or reason_code not in MARKET_QUALITY_REASONS:
        raise MarketQualityProjectionError("quality evidence status or reason is unsupported")
    rejected_count = _validate_rejected_records(envelope["rejectedRecords"])
    events = _project_events(envelope["qualityEvents"], manifest.unified_code)
    requested_start = manifest.requested_start
    requested_end = manifest.requested_end
    if not isinstance(requested_start, str) or not isinstance(requested_end, str):
        raise MarketQualityProjectionError("quality evidence request window is incomplete")
    filtered_records = _project_filtered_records(
        envelope.get("filteredRecords", []),
        expected_requested_start=requested_start,
        expected_requested_end=requested_end,
    )
    if (status == "FILTERED" or filtered_records) and manifest.source != "akshare-sina":
        raise MarketQualityProjectionError("filtered quality evidence source is unsupported")

    if status == "FILTERED":
        if (
            reason_code != MARKET_QUALITY_FILTER_REASON
            or not filtered_records
            or rejected_count != 0
            or events
        ):
            raise MarketQualityProjectionError("filtered quality evidence semantics are invalid")
    elif reason_code == MARKET_QUALITY_FILTER_REASON:
        raise MarketQualityProjectionError("rejected quality evidence reason is invalid")
    if status == "REJECTED" and filtered_records and reason_code != "BAR_QUALITY_REJECTED":
        raise MarketQualityProjectionError("quality evidence filtered records are inconsistent")

    quality_recorded_at = _timestamp(envelope["recordedAt"], "recordedAt")
    capture_available_at = manifest.available_time.astimezone(UTC)
    if quality_recorded_at < capture_available_at:
        raise MarketQualityProjectionError(
            "quality evidence recordedAt precedes capture availability"
        )
    if published_at is not None:
        if published_at.tzinfo is None or published_at.utcoffset() is None:
            raise MarketQualityProjectionError(
                "quality evidence publishedAt must be timezone-aware"
            )
        if quality_recorded_at > published_at.astimezone(UTC):
            raise MarketQualityProjectionError("quality evidence is from the future")

    payload: dict[str, object] = {
        "evidenceId": _evidence_id(manifest.source, manifest),
        "source": manifest.source,
        "unifiedCode": manifest.unified_code,
        "interval": manifest.interval,
        "requestedStart": manifest.requested_start,
        "requestedEnd": manifest.requested_end,
        "status": status,
        "reasonCode": reason_code,
        "captureAvailableAt": capture_available_at.isoformat(),
        "qualityRecordedAt": quality_recorded_at.isoformat(),
        "rejectedRecordCount": rejected_count,
        "qualityEventCount": len(events),
        "filteredRecordCount": len(filtered_records),
        "qualityEvents": events,
        "filteredRecords": filtered_records,
    }
    try:
        validated = MarketQualityEvidenceRecord.model_validate(payload)
    except Exception as error:
        raise MarketQualityProjectionError("quality evidence projection is invalid") from error
    return cast(dict[str, object], validated.model_dump(by_alias=True, mode="json"))


__all__ = [
    "MARKET_QUALITY_CURRENT_SCHEMA_VERSION",
    "MARKET_QUALITY_EVIDENCE_SCHEMA_VERSION",
    "MARKET_QUALITY_FILTER_REASON",
    "MARKET_QUALITY_INTERVALS",
    "MARKET_QUALITY_KINDS",
    "MARKET_QUALITY_MAX_BYTES",
    "MARKET_QUALITY_MAX_CANDIDATE_FILES",
    "MARKET_QUALITY_MAX_INPUT_BYTES",
    "MARKET_QUALITY_MAX_RECORDS",
    "MARKET_QUALITY_MAX_RAW_ROW_INDEX",
    "MARKET_QUALITY_PAGE_LIMIT",
    "MARKET_QUALITY_REASONS",
    "MARKET_QUALITY_SNAPSHOT_SCHEMA_VERSION",
    "MARKET_QUALITY_SOURCES",
    "MARKET_QUALITY_STATUSES",
    "MarketQualityProjectionError",
    "project_market_quality_evidence",
]
