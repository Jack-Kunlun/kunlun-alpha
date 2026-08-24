"""Trusted aggregate boundary for KOL content, evidence, claims and positions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeGuard, TypeVar, cast

from kol_core.models import (
    KolClaim,
    KolContent,
    KolEvidence,
    KolPositionClaim,
    parse_kol_claim_payload,
    parse_kol_content_payload,
    parse_kol_evidence_payload,
    parse_kol_position_claim_payload,
    validate_evidence_binding,
    validate_position_claim_link,
)


class _Revisioned(Protocol):
    @property
    def revision_id(self) -> str: ...

    @property
    def previous_revision_id(self) -> str | None: ...

    @property
    def available_time(self) -> datetime: ...


RevisionedT = TypeVar("RevisionedT", bound=_Revisioned)


@dataclass(frozen=True, slots=True)
class KolDomainSnapshot:
    """Complete immutable KOL revision graph and its cross-entity links."""

    content: tuple[KolContent, ...]
    evidence: tuple[KolEvidence, ...]
    claims: tuple[KolClaim, ...]
    position_claims: tuple[KolPositionClaim, ...]

    def __post_init__(self) -> None:
        if type(self.content) is not tuple:
            raise TypeError("content must be a tuple")
        if type(self.evidence) is not tuple:
            raise TypeError("evidence must be a tuple")
        if type(self.claims) is not tuple:
            raise TypeError("claims must be a tuple")
        if type(self.position_claims) is not tuple:
            raise TypeError("position_claims must be a tuple")
        validate_kol_domain_snapshot(self)

    def select_visible(self, decision_time: datetime) -> KolVisibleDomainSnapshot:
        decision = _aware(decision_time, "decision_time")
        return KolVisibleDomainSnapshot(
            content=_latest_visible(self.content, lambda item: item.content_id, decision),
            evidence=_latest_visible(self.evidence, lambda item: item.evidence_id, decision),
            claims=_latest_visible(self.claims, lambda item: item.claim_id, decision),
            position_claims=_latest_visible(
                self.position_claims,
                lambda item: item.position_claim_id,
                decision,
            ),
        )


@dataclass(frozen=True, slots=True)
class KolVisibleDomainSnapshot:
    """Latest visible revision per logical entity at one decision time."""

    content: tuple[KolContent, ...]
    evidence: tuple[KolEvidence, ...]
    claims: tuple[KolClaim, ...]
    position_claims: tuple[KolPositionClaim, ...]


def _aware(value: datetime, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    return type(value) is list


def _is_string_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    if not isinstance(value, Mapping):
        return False
    unknown_mapping = cast(Mapping[object, object], value)
    return all(type(key) is str for key in unknown_mapping)


def _validate_revision_graph(
    records: Sequence[RevisionedT],
    entity_name: str,
    entity_id: Callable[[RevisionedT], str],
) -> list[str]:
    errors: list[str] = []
    groups: dict[str, list[RevisionedT]] = {}
    for record in records:
        groups.setdefault(entity_id(record), []).append(record)

    for logical_id, group in groups.items():
        by_revision: dict[str, RevisionedT] = {}
        for record in group:
            if record.revision_id in by_revision:
                errors.append(f"{entity_name} has duplicate logical id and revision")
            else:
                by_revision[record.revision_id] = record

        roots = [record.revision_id for record in group if record.previous_revision_id is None]
        if len(roots) != 1:
            errors.append(f"{entity_name} logical id {logical_id!r} must have exactly one root")

        children: dict[str, str] = {}
        parents: dict[str, str] = {}
        for record in group:
            previous = record.previous_revision_id
            if previous is None:
                continue
            if previous == record.revision_id:
                errors.append(f"{entity_name} revision graph contains a cycle")
                continue
            parent = by_revision.get(previous)
            if parent is None:
                errors.append(
                    f"{entity_name} previous revision must exist under the same logical id"
                )
                continue
            existing_child = children.get(previous)
            if existing_child is not None and existing_child != record.revision_id:
                errors.append(f"{entity_name} revision graph contains a fork")
            children[previous] = record.revision_id
            parents[record.revision_id] = previous
            if record.available_time <= parent.available_time:
                errors.append(
                    f"{entity_name} revisions must have strictly increasing available_time"
                )

        for revision_id in by_revision:
            visited: set[str] = set()
            walk: str | None = revision_id
            while walk is not None:
                if walk in visited:
                    errors.append(f"{entity_name} revision graph contains a cycle")
                    break
                visited.add(walk)
                walk = parents.get(walk)
                if walk is not None and walk not in by_revision:
                    errors.append(f"{entity_name} revision graph is disconnected")
                    break

        if len(roots) == 1:
            reachable: set[str] = set()
            reachable_current: str | None = roots[0]
            while reachable_current is not None:
                if reachable_current in reachable:
                    errors.append(f"{entity_name} revision graph contains a cycle")
                    break
                reachable.add(reachable_current)
                reachable_current = children.get(reachable_current)
            if reachable != set(by_revision):
                errors.append(f"{entity_name} revision graph is disconnected")
    return errors


def _validate_links(snapshot: KolDomainSnapshot) -> list[str]:
    errors: list[str] = []
    content_by_version: dict[tuple[str, str], KolContent] = {}
    for content in snapshot.content:
        key = (content.content_id, content.content_version)
        if key in content_by_version:
            errors.append("content has duplicate content_id/content_version")
        content_by_version[key] = content

    evidence_by_revision = {
        (evidence.evidence_id, evidence.revision_id): evidence for evidence in snapshot.evidence
    }
    claim_by_revision = {(claim.claim_id, claim.revision_id): claim for claim in snapshot.claims}

    for evidence in snapshot.evidence:
        content = content_by_version.get((evidence.content_id, evidence.content_version))
        if content is None:
            errors.append("evidence must bind to an actual content id and version")
            continue
        try:
            validate_evidence_binding(content, evidence)
        except ValueError as error:
            errors.append(str(error))

    for claim in snapshot.claims:
        content = content_by_version.get((claim.content_id, claim.content_version))
        if content is None:
            errors.append("claim must bind to an actual content id and version")
        else:
            if claim.content_available_time != content.available_time:
                errors.append("claim content_available_time must match actual content revision")
            if claim.available_time < content.available_time:
                errors.append("claim available_time must include content availability")
        for reference in claim.evidence:
            evidence = evidence_by_revision.get(
                (reference.evidence_id, reference.evidence_revision_id)
            )
            if evidence is None:
                errors.append("claim evidence must bind to an actual evidence revision")
                continue
            if (
                reference.content_id != evidence.content_id
                or reference.content_version != evidence.content_version
            ):
                errors.append("claim evidence content identity does not match evidence")
            if reference.content_available_time != evidence.content_available_time:
                errors.append("claim evidence content availability does not match evidence")
            if reference.evidence_available_time != evidence.available_time:
                errors.append("claim evidence availability does not match evidence")
            if (
                reference.source != evidence.source
                or reference.source_version != evidence.source_version
            ):
                errors.append("claim evidence source does not match evidence")
            if claim.available_time < evidence.available_time:
                errors.append("claim available_time must include evidence availability")

    for position in snapshot.position_claims:
        claim = claim_by_revision.get((position.claim_id, position.claim_revision_id))
        if claim is None:
            errors.append("position claim must bind to an actual claim revision")
            continue
        try:
            validate_position_claim_link(position, claim)
        except ValueError as error:
            errors.append(str(error))
    return errors


def validate_kol_domain_snapshot(snapshot: KolDomainSnapshot) -> None:
    """Validate complete revision graphs and all exact cross-entity links."""

    errors = [
        *_validate_revision_graph(snapshot.content, "content", lambda item: item.content_id),
        *_validate_revision_graph(snapshot.evidence, "evidence", lambda item: item.evidence_id),
        *_validate_revision_graph(snapshot.claims, "claims", lambda item: item.claim_id),
        *_validate_revision_graph(
            snapshot.position_claims,
            "positionClaims",
            lambda item: item.position_claim_id,
        ),
        *_validate_links(snapshot),
    ]
    if errors:
        raise ValueError(f"invalid KOL domain snapshot: {'; '.join(errors)}")


def _collection(payload: Mapping[str, object], field: str) -> tuple[Mapping[str, object], ...]:
    value = payload.get(field)
    if not _is_object_list(value):
        raise TypeError(f"snapshot {field} must be a list")
    records: list[Mapping[str, object]] = []
    for index, item in enumerate(value):
        if not _is_string_mapping(item):
            raise TypeError(f"snapshot {field}[{index}] must be an object")
        records.append(item)
    return tuple(records)


def parse_kol_domain_snapshot_payload(payload: object) -> KolDomainSnapshot:
    """Parse untrusted collections and return the only trusted aggregate boundary."""

    if not _is_string_mapping(payload):
        raise TypeError("snapshot must be an object with string keys")
    expected = {"content", "evidence", "claims", "positionClaims"}
    unknown = set(payload) - expected
    if unknown:
        raise ValueError(f"snapshot has unknown fields: {sorted(unknown)!r}")
    snapshot = KolDomainSnapshot(
        content=tuple(parse_kol_content_payload(item) for item in _collection(payload, "content")),
        evidence=tuple(
            parse_kol_evidence_payload(item) for item in _collection(payload, "evidence")
        ),
        claims=tuple(parse_kol_claim_payload(item) for item in _collection(payload, "claims")),
        position_claims=tuple(
            parse_kol_position_claim_payload(item)
            for item in _collection(payload, "positionClaims")
        ),
    )
    return snapshot


def _latest_visible(
    records: Sequence[RevisionedT],
    entity_id: Callable[[RevisionedT], str],
    decision_time: datetime,
) -> tuple[RevisionedT, ...]:
    latest: dict[str, RevisionedT] = {}
    for record in records:
        if record.available_time > decision_time:
            continue
        previous = latest.get(entity_id(record))
        if previous is None or record.available_time > previous.available_time:
            latest[entity_id(record)] = record
    return tuple(latest[key] for key in sorted(latest))


__all__ = [
    "KolDomainSnapshot",
    "KolVisibleDomainSnapshot",
    "parse_kol_domain_snapshot_payload",
    "validate_kol_domain_snapshot",
]
