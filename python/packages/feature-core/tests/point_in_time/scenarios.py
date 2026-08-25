from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Self, cast


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _checksum(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _lineage_checksum(
    revision_id: str,
    value_checksum: str,
    source_snapshot_version: str,
) -> str:
    return _checksum(f"{revision_id}|{value_checksum}|{source_snapshot_version}")


def _fingerprint(value: object, field: str) -> str:
    text = _text(value, field)
    if not text.startswith("sha256:") or len(text) != 71:
        raise ValueError(f"{field} must be a sha256 fingerprint")
    try:
        int(text.removeprefix("sha256:"), 16)
    except ValueError as exc:
        raise ValueError(f"{field} must be a sha256 fingerprint") from exc
    return text


@dataclass(frozen=True, slots=True)
class SyntheticFeatureRevision:
    entity_id: str
    feature_name: str
    event_time: datetime
    available_time: datetime
    processing_time: datetime
    revision_id: str
    value: str
    value_checksum: str
    lineage_checksum: str
    source_snapshot_version: str

    def __post_init__(self) -> None:
        for field, value in (
            ("entity_id", self.entity_id),
            ("feature_name", self.feature_name),
            ("revision_id", self.revision_id),
            ("value", self.value),
            ("source_snapshot_version", self.source_snapshot_version),
        ):
            _text(value, field)
        _fingerprint(self.value_checksum, "value_checksum")
        _fingerprint(self.lineage_checksum, "lineage_checksum")
        if self.value_checksum != _checksum(self.value):
            raise ValueError("value_checksum does not match value")
        if self.lineage_checksum != _lineage_checksum(
            self.revision_id,
            self.value_checksum,
            self.source_snapshot_version,
        ):
            raise ValueError("lineage_checksum does not match revision provenance")
        _aware(self.event_time, "event_time")
        _aware(self.available_time, "available_time")
        _aware(self.processing_time, "processing_time")
        if self.available_time < self.event_time:
            raise ValueError("available_time cannot precede event_time")
        if self.processing_time < self.available_time:
            raise ValueError("processing_time cannot precede available_time")

    @classmethod
    def create(
        cls,
        *,
        entity_id: str,
        feature_name: str,
        event_time: datetime,
        available_time: datetime,
        processing_time: datetime,
        revision_id: str,
        value: str,
        source_snapshot_version: str,
    ) -> Self:
        return cls(
            entity_id=entity_id,
            feature_name=feature_name,
            event_time=event_time,
            available_time=available_time,
            processing_time=processing_time,
            revision_id=revision_id,
            value=value,
            value_checksum=_checksum(value),
            lineage_checksum=_lineage_checksum(
                revision_id,
                _checksum(value),
                source_snapshot_version,
            ),
            source_snapshot_version=source_snapshot_version,
        )

    @property
    def sample_key(self) -> tuple[str, str, datetime]:
        return (self.entity_id, self.feature_name, self.event_time)

    @property
    def visibility_order(self) -> tuple[datetime, datetime]:
        return (self.available_time, self.processing_time)

    def visible_at(self, decision_time: datetime) -> bool:
        return (
            self.event_time <= decision_time
            and self.available_time <= decision_time
            and self.processing_time <= decision_time
        )


@dataclass(frozen=True, slots=True)
class SyntheticMembershipRevision:
    entity_id: str
    effective_start: datetime
    effective_end: datetime | None
    available_time: datetime
    processing_time: datetime
    revision_id: str

    def __post_init__(self) -> None:
        _text(self.entity_id, "entity_id")
        _text(self.revision_id, "revision_id")
        _aware(self.effective_start, "effective_start")
        if self.effective_end is not None:
            _aware(self.effective_end, "effective_end")
            if self.effective_end <= self.effective_start:
                raise ValueError("effective_end must follow effective_start")
        _aware(self.available_time, "available_time")
        _aware(self.processing_time, "processing_time")
        if self.processing_time < self.available_time:
            raise ValueError("processing_time cannot precede available_time")

    @property
    def visibility_order(self) -> tuple[datetime, datetime]:
        return (self.available_time, self.processing_time)

    def visible_at(self, decision_time: datetime) -> bool:
        return self.available_time <= decision_time and self.processing_time <= decision_time

    def active_at(self, decision_time: datetime) -> bool:
        return self.effective_start <= decision_time and (
            self.effective_end is None or decision_time < self.effective_end
        )


class MembershipSnapshotState(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"


@dataclass(frozen=True, slots=True)
class PointInTimeScenario:
    scenario_id: str
    decision_time: datetime
    present_time: datetime
    feature_revisions: tuple[SyntheticFeatureRevision, ...]
    membership_revisions: tuple[SyntheticMembershipRevision, ...]
    membership_snapshot_state: MembershipSnapshotState = MembershipSnapshotState.AVAILABLE

    def __post_init__(self) -> None:
        _text(self.scenario_id, "scenario_id")
        _aware(self.decision_time, "decision_time")
        _aware(self.present_time, "present_time")
        if self.present_time <= self.decision_time:
            raise ValueError("present_time must follow decision_time")
        if type(cast(object, self.membership_snapshot_state)) is not MembershipSnapshotState:
            raise ValueError("membership_snapshot_state is invalid")
        feature_revisions = tuple(self.feature_revisions)
        membership_revisions = tuple(self.membership_revisions)
        if any(
            type(cast(object, revision)) is not SyntheticFeatureRevision
            for revision in feature_revisions
        ):
            raise ValueError("feature revision type is invalid")
        if any(
            type(cast(object, revision)) is not SyntheticMembershipRevision
            for revision in membership_revisions
        ):
            raise ValueError("membership revision type is invalid")
        if (
            self.membership_snapshot_state is MembershipSnapshotState.MISSING
            and membership_revisions
        ):
            raise ValueError("missing membership snapshot cannot contain revisions")
        object.__setattr__(self, "feature_revisions", feature_revisions)
        object.__setattr__(self, "membership_revisions", membership_revisions)


@dataclass(frozen=True, slots=True)
class ResolvedPointInTimeSnapshot:
    decision_time: datetime
    feature_revisions: tuple[SyntheticFeatureRevision, ...]
    universe_entity_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _aware(self.decision_time, "decision_time")
        object.__setattr__(self, "feature_revisions", tuple(self.feature_revisions))
        object.__setattr__(self, "universe_entity_ids", tuple(self.universe_entity_ids))


def synthetic_point_in_time_scenario() -> PointInTimeScenario:
    decision_time = datetime(2026, 1, 10, 6, tzinfo=UTC)
    event_time = decision_time - timedelta(days=1)
    feature_revisions = (
        SyntheticFeatureRevision.create(
            entity_id="600519.SH",
            feature_name="momentum-5d",
            event_time=event_time,
            available_time=event_time + timedelta(hours=1),
            processing_time=event_time + timedelta(hours=1, minutes=1),
            revision_id="momentum-visible-v1",
            value="0.05",
            source_snapshot_version="feature-snapshot-v1",
        ),
        SyntheticFeatureRevision.create(
            entity_id="600519.SH",
            feature_name="momentum-5d",
            event_time=event_time,
            available_time=decision_time + timedelta(days=1),
            processing_time=decision_time + timedelta(days=1, minutes=1),
            revision_id="momentum-revised-v2",
            value="0.08",
            source_snapshot_version="feature-snapshot-v2",
        ),
        SyntheticFeatureRevision.create(
            entity_id="600519.SH",
            feature_name="future-only-signal",
            event_time=event_time,
            available_time=decision_time + timedelta(hours=1),
            processing_time=decision_time + timedelta(hours=1, minutes=1),
            revision_id="future-only-v1",
            value="1",
            source_snapshot_version="future-source-v1",
        ),
        SyntheticFeatureRevision.create(
            entity_id="600519.SH",
            feature_name="processing-only-signal",
            event_time=event_time,
            available_time=decision_time - timedelta(minutes=1),
            processing_time=decision_time + timedelta(hours=1),
            revision_id="processing-only-v1",
            value="1",
            source_snapshot_version="processing-source-v1",
        ),
        SyntheticFeatureRevision.create(
            entity_id="000001.SZ",
            feature_name="momentum-5d",
            event_time=event_time,
            available_time=event_time + timedelta(hours=1),
            processing_time=event_time + timedelta(hours=1, minutes=1),
            revision_id="delisted-visible-v1",
            value="-0.02",
            source_snapshot_version="delisted-source-v1",
        ),
    )
    membership_revisions = (
        SyntheticMembershipRevision(
            entity_id="600519.SH",
            effective_start=decision_time - timedelta(days=365),
            effective_end=None,
            available_time=decision_time - timedelta(days=365),
            processing_time=decision_time - timedelta(days=365) + timedelta(minutes=1),
            revision_id="membership-600519-v1",
        ),
        SyntheticMembershipRevision(
            entity_id="000001.SZ",
            effective_start=decision_time - timedelta(days=365),
            effective_end=None,
            available_time=decision_time - timedelta(days=365),
            processing_time=decision_time - timedelta(days=365) + timedelta(minutes=1),
            revision_id="membership-000001-visible-v1",
        ),
        SyntheticMembershipRevision(
            entity_id="000001.SZ",
            effective_start=decision_time - timedelta(days=365),
            effective_end=decision_time - timedelta(days=2),
            available_time=decision_time + timedelta(days=2),
            processing_time=decision_time + timedelta(days=2, minutes=1),
            revision_id="membership-000001-backfill-v2",
        ),
    )
    return PointInTimeScenario(
        scenario_id="future-revision-and-survivor-bias",
        decision_time=decision_time,
        present_time=decision_time + timedelta(days=10),
        feature_revisions=feature_revisions,
        membership_revisions=membership_revisions,
    )
