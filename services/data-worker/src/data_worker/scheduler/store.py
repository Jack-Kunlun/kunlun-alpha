"""Task stores and owner-bound lease contracts."""

from __future__ import annotations

import copy
import json
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from data_worker.scheduler.scheduler import JsonValue, TaskRecord

type LeaseToken = str

ERROR_CATEGORIES = frozenset(
    {
        "transient",
        "permanent",
        "timeout",
        "rate_limit",
        "auth",
        "authorization",
        "not_found",
        "data_error",
        "validation",
        "unavailable",
        "conflict",
        "internal",
    }
)


class TaskStore(Protocol):
    """Persistence for task records, checkpoints and owner-bound leases."""

    def get(self, task_id: str) -> TaskRecord: ...

    def acquire_lease(self, task_id: str, lease_seconds: float) -> LeaseToken | None: ...

    def release_lease(self, task_id: str, lease_token: LeaseToken) -> bool: ...

    def mark_succeeded(self, task_id: str, lease_token: LeaseToken) -> bool: ...

    def mark_failed(
        self,
        task_id: str,
        lease_token: LeaseToken,
        *,
        error_category: str | None = None,
        error_detail: JsonValue | None = None,
        next_run_at: datetime | None = None,
    ) -> bool: ...

    def mark_dead(
        self,
        task_id: str,
        lease_token: LeaseToken,
        *,
        error_category: str | None = None,
        error_detail: JsonValue | None = None,
        dead_letter_detail: JsonValue | None = None,
    ) -> bool: ...

    def save_checkpoint(
        self, task_id: str, lease_token: LeaseToken, checkpoint: JsonValue
    ) -> bool: ...

    def get_checkpoint(self, task_id: str) -> JsonValue | None: ...


class InMemoryTaskStore:
    """In-memory contract fake with the same owner-CAS behavior as PostgreSQL."""

    def __init__(
        self,
        now: Callable[[], datetime] | None = None,
        *,
        max_attempts: int = 3,
    ) -> None:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        self._records: dict[str, TaskRecord] = {}
        self._checkpoints: dict[str, JsonValue] = {}
        self._now = now or (lambda: datetime.now(UTC))
        self._max_attempts = max_attempts

    def get(self, task_id: str) -> TaskRecord:
        record = self._records.get(task_id)
        if record is None:
            now = _utc_datetime(self._now())
            record = TaskRecord(
                task_id=task_id,
                max_attempts=self._max_attempts,
                created_at=now,
                updated_at=now,
            )
            self._records[task_id] = record
        return record

    def acquire_lease(self, task_id: str, lease_seconds: float) -> LeaseToken | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        record = self.get(task_id)
        now = _utc_datetime(self._now())
        if record.status in {"SUCCEEDED", "DEAD"}:
            return None
        if record.attempts >= record.max_attempts:
            record.status = "DEAD"
            record.dead_letter_detail = {"message": "retry limit reached"}
            record.lease_token = None
            record.lease_expires_at = None
            record.updated_at = now
            return None
        if record.next_run_at is not None and record.next_run_at > now:
            return None
        if (
            record.lease_token is not None
            and record.lease_expires_at is not None
            and record.lease_expires_at > now
        ):
            return None
        token = secrets.token_urlsafe(32)
        record.status = "RUNNING"
        record.attempts += 1
        record.lease_token = token
        record.lease_expires_at = now + timedelta(seconds=lease_seconds)
        record.updated_at = now
        return token

    def release_lease(self, task_id: str, lease_token: LeaseToken) -> bool:
        record = self._records.get(task_id)
        if record is None or record.lease_token != lease_token:
            return False
        if record.lease_expires_at is None or record.lease_expires_at <= _utc_datetime(self._now()):
            return False
        record.lease_token = None
        record.lease_expires_at = None
        record.updated_at = _utc_datetime(self._now())
        return True

    def mark_succeeded(self, task_id: str, lease_token: LeaseToken) -> bool:
        record = self._owned_record(task_id, lease_token)
        if record is None:
            return False
        now = _utc_datetime(self._now())
        record.status = "SUCCEEDED"
        record.lease_token = None
        record.lease_expires_at = None
        record.next_run_at = None
        record.error_category = None
        record.error_detail = None
        record.updated_at = now
        return True

    def mark_failed(
        self,
        task_id: str,
        lease_token: LeaseToken,
        *,
        error_category: str | None = None,
        error_detail: JsonValue | None = None,
        next_run_at: datetime | None = None,
    ) -> bool:
        validated_category = validate_error_category(error_category)
        record = self._owned_record(task_id, lease_token)
        if record is None:
            return False
        now = _utc_datetime(self._now())
        exhausted = record.attempts >= record.max_attempts
        record.status = "DEAD" if exhausted else "FAILED"
        record.lease_token = None
        record.lease_expires_at = None
        record.next_run_at = None if exhausted else optional_utc_datetime(next_run_at)
        record.error_category = validated_category
        record.error_detail = validate_json_payload(error_detail, "error_detail")
        if exhausted:
            record.dead_letter_detail = {"message": "retry limit reached"}
        record.updated_at = now
        return True

    def mark_dead(
        self,
        task_id: str,
        lease_token: LeaseToken,
        *,
        error_category: str | None = None,
        error_detail: JsonValue | None = None,
        dead_letter_detail: JsonValue | None = None,
    ) -> bool:
        validated_category = validate_error_category(error_category)
        record = self._owned_record(task_id, lease_token)
        if record is None:
            return False
        now = _utc_datetime(self._now())
        record.status = "DEAD"
        record.lease_token = None
        record.lease_expires_at = None
        record.next_run_at = None
        record.error_category = validated_category
        record.error_detail = validate_json_payload(error_detail, "error_detail")
        record.dead_letter_detail = validate_json_payload(dead_letter_detail, "dead_letter_detail")
        record.updated_at = now
        return True

    def save_checkpoint(self, task_id: str, lease_token: LeaseToken, checkpoint: JsonValue) -> bool:
        record = self._owned_record(task_id, lease_token)
        if record is None:
            return False
        validated = validate_json_payload(checkpoint, "checkpoint")
        self._checkpoints[task_id] = copy.deepcopy(validated)
        record.checkpoint = copy.deepcopy(validated)
        record.updated_at = _utc_datetime(self._now())
        return True

    def get_checkpoint(self, task_id: str) -> JsonValue | None:
        if task_id in self._checkpoints:
            return copy.deepcopy(self._checkpoints[task_id])
        return copy.deepcopy(self.get(task_id).checkpoint)

    def _owned_record(self, task_id: str, lease_token: LeaseToken) -> TaskRecord | None:
        record = self._records.get(task_id)
        if record is None or record.lease_token != lease_token:
            return None
        if record.lease_expires_at is None or record.lease_expires_at <= _utc_datetime(self._now()):
            return None
        return record


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def optional_utc_datetime(value: datetime | None) -> datetime | None:
    return None if value is None else _utc_datetime(value)


def validate_error_category(value: str | None) -> str | None:
    """Accept only the short, controlled scheduler/provider categories."""

    if value is None:
        return None
    if type(value) is not str or len(value) > 32 or value not in ERROR_CATEGORIES:
        raise ValueError("error_category must be a controlled scheduler category")
    return value


def validate_json_payload(value: JsonValue | None, field_name: str) -> JsonValue | None:
    if value is None:
        return None
    _validate_json_shape(value, field_name, depth=0)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be JSON-compatible") from error
    if len(encoded.encode("utf-8")) > 16_384:
        raise ValueError(f"{field_name} exceeds the 16 KiB limit")
    return copy.deepcopy(value)


def _validate_json_shape(value: JsonValue, field_name: str, depth: int) -> None:
    if depth > 8:
        raise ValueError(f"{field_name} exceeds the maximum nesting depth")
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        for key, item in mapping.items():
            if not isinstance(key, str):
                raise ValueError(f"{field_name} object keys must be strings")
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if normalized in {
                "password",
                "passwd",
                "secret",
                "credential",
                "credentials",
                "token",
                "apikey",
                "accesstoken",
                "accesskey",
                "privatekey",
                "authorization",
                "cookie",
                "setcookie",
            }:
                raise ValueError(f"{field_name} contains a sensitive key")
            _validate_json_shape(item, field_name, depth + 1)
    elif isinstance(value, list):
        items = cast(list[object], value)
        for item in items:
            _validate_json_shape(item, field_name, depth + 1)
    elif isinstance(value, str) and _contains_sensitive_text(value):
        raise ValueError(f"{field_name} contains a sensitive value")


def _contains_sensitive_text(value: str) -> bool:
    text = value.strip()
    lowered = text.lower()
    return bool(
        re.search(r"\b(?:bearer|basic)\s+[a-z0-9._~+/=-]+", text, re.IGNORECASE)
        or re.search(
            r"\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*:",
            text,
            re.IGNORECASE,
        )
        or re.search(r"\b(?:password|passwd|secret|token|api[-_]?key)\s*[=:]", text, re.IGNORECASE)
        or re.search(r"\bpostgres(?:ql)?(?:\+\w+)?://", lowered)
        or re.search(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^@\s]+@", lowered)
    )
