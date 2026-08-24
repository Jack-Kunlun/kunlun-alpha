"""Immutable contracts for deterministic seat alias resolution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from seat_core.models import AliasType, SeatKind

NORMALIZATION_POLICY_VERSION = "seat-normalization-v1"
RESOLUTION_ALGORITHM_VERSION = "seat-resolution-v1"
RESOLUTION_POLICY_VERSION = "seat-resolution-policy-v1"


def _require_non_empty(value: str, name: str) -> None:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_aware(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_probability(value: Decimal, name: str) -> None:
    if (
        type(value) is not Decimal
        or not value.is_finite()
        or not Decimal("0") <= value <= Decimal("1")
    ):
        raise ValueError(f"{name} must be a Decimal in [0, 1]")


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _fingerprint(prefix: str, payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    material = f"seat-{prefix}-fingerprint-v1\0".encode() + encoded
    return f"{prefix}-{hashlib.sha256(material).hexdigest()}"


class ResolutionStatus(StrEnum):
    AUTO = "AUTO"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


class ReviewOutcome(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


@dataclass(frozen=True)
class NormalizationPolicy:
    """Versioned, deterministic normalization rules for source names."""

    version: str = NORMALIZATION_POLICY_VERSION
    use_nfkc: bool = True
    use_casefold: bool = True
    remove_whitespace: bool = True
    strip_common_suffixes: tuple[str, ...] = (
        "证券营业部",
        "营业部",
        "营业厅",
        "分公司",
    )

    def __post_init__(self) -> None:
        _require_non_empty(self.version, "version")
        if self.version != NORMALIZATION_POLICY_VERSION:
            raise ValueError(f"unsupported normalization policy version: {self.version!r}")
        if type(self.strip_common_suffixes) is not tuple or not self.strip_common_suffixes:
            raise ValueError("strip_common_suffixes must be a non-empty tuple")
        if len(set(self.strip_common_suffixes)) != len(self.strip_common_suffixes):
            raise ValueError("strip_common_suffixes must not contain duplicates")
        for suffix in self.strip_common_suffixes:
            _require_non_empty(suffix, "suffix")


@dataclass(frozen=True)
class ResolutionPolicy:
    """Versioned thresholds; review is the safe default below both gates."""

    version: str = RESOLUTION_POLICY_VERSION
    algorithm_version: str = RESOLUTION_ALGORITHM_VERSION
    normalization_policy: NormalizationPolicy = field(default_factory=NormalizationPolicy)
    auto_score_threshold: Decimal = Decimal("0.9000")
    minimum_margin: Decimal = Decimal("0.0500")
    golden_accuracy_threshold: Decimal = Decimal("0.9500")

    def __post_init__(self) -> None:
        _require_non_empty(self.version, "version")
        _require_non_empty(self.algorithm_version, "algorithm_version")
        if self.version != RESOLUTION_POLICY_VERSION:
            raise ValueError(f"unsupported resolution policy version: {self.version!r}")
        if self.algorithm_version != RESOLUTION_ALGORITHM_VERSION:
            raise ValueError(f"unsupported algorithm_version: {self.algorithm_version!r}")
        if type(self.normalization_policy) is not NormalizationPolicy:
            raise TypeError("normalization_policy must be NormalizationPolicy")
        if self.normalization_policy.version != NORMALIZATION_POLICY_VERSION:
            raise ValueError("normalization policy version is not supported")
        _require_probability(self.auto_score_threshold, "auto_score_threshold")
        _require_probability(self.minimum_margin, "minimum_margin")
        _require_probability(self.golden_accuracy_threshold, "golden_accuracy_threshold")
        if self.auto_score_threshold < Decimal("0.9000"):
            raise ValueError("auto_score_threshold must be at least 0.9000")
        if self.minimum_margin < Decimal("0.0500"):
            raise ValueError("minimum_margin must be at least 0.0500")

    @property
    def policy_fingerprint(self) -> str:
        return _fingerprint(
            "policy",
            {
                "version": self.version,
                "algorithm_version": self.algorithm_version,
                "normalization": {
                    "version": self.normalization_policy.version,
                    "use_nfkc": self.normalization_policy.use_nfkc,
                    "use_casefold": self.normalization_policy.use_casefold,
                    "remove_whitespace": self.normalization_policy.remove_whitespace,
                    "strip_common_suffixes": list(self.normalization_policy.strip_common_suffixes),
                },
                "auto_score_threshold": _decimal_text(self.auto_score_threshold),
                "minimum_margin": _decimal_text(self.minimum_margin),
                "golden_accuracy_threshold": _decimal_text(self.golden_accuracy_threshold),
            },
        )


@dataclass(frozen=True)
class AliasResolutionRequest:
    request_id: str
    raw_name: str
    decision_time: datetime
    source: str
    source_version: str
    evidence_id: str
    seat_kind_hint: SeatKind | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.request_id, "request_id")
        _require_non_empty(self.raw_name, "raw_name")
        _require_aware(self.decision_time, "decision_time")
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        _require_non_empty(self.evidence_id, "evidence_id")
        if self.seat_kind_hint is not None and type(self.seat_kind_hint) is not SeatKind:
            raise TypeError("seat_kind_hint must be SeatKind or None")

    @property
    def request_fingerprint(self) -> str:
        return compute_request_fingerprint(
            request_id=self.request_id,
            raw_name=self.raw_name,
            decision_time=self.decision_time,
            source=self.source,
            source_version=self.source_version,
            evidence_ids=(self.evidence_id,),
            seat_kind_hint=self.seat_kind_hint,
        )


def compute_request_fingerprint(
    *,
    request_id: str,
    raw_name: str,
    decision_time: datetime,
    source: str,
    source_version: str,
    evidence_ids: tuple[str, ...],
    seat_kind_hint: SeatKind | None,
) -> str:
    return _fingerprint(
        "request",
        {
            "request_id": request_id,
            "raw_name": raw_name,
            "decision_time": decision_time.isoformat(),
            "source": source,
            "source_version": source_version,
            "evidence_ids": list(evidence_ids),
            "seat_kind_hint": None if seat_kind_hint is None else seat_kind_hint.value,
        },
    )


@dataclass(frozen=True)
class AliasEvidence:
    alias_id: str
    name: str
    alias_type: AliasType
    source: str
    source_version: str
    evidence_id: str
    available_time: datetime
    valid_from: datetime
    valid_to: datetime | None

    def __post_init__(self) -> None:
        _require_non_empty(self.alias_id, "alias_id")
        _require_non_empty(self.name, "name")
        if type(self.alias_type) is not AliasType:
            raise TypeError("alias_type must be AliasType")
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        _require_non_empty(self.evidence_id, "evidence_id")
        _require_aware(self.available_time, "available_time")
        _require_aware(self.valid_from, "valid_from")
        if self.valid_to is not None:
            _require_aware(self.valid_to, "valid_to")


@dataclass(frozen=True)
class AliasCandidate:
    seat_id: str
    score: Decimal
    rule_hits: tuple[str, ...]
    evidence: tuple[AliasEvidence, ...]
    seat_kind: SeatKind
    type_conflict: bool

    def __post_init__(self) -> None:
        _require_non_empty(self.seat_id, "seat_id")
        _require_probability(self.score, "score")
        if type(self.rule_hits) is not tuple or not self.rule_hits:
            raise ValueError("rule_hits must be a non-empty tuple")
        if len(set(self.rule_hits)) != len(self.rule_hits):
            raise ValueError("rule_hits must not contain duplicates")
        if type(self.evidence) is not tuple or not self.evidence:
            raise ValueError("evidence must be a non-empty tuple")
        if type(self.seat_kind) is not SeatKind:
            raise TypeError("seat_kind must be SeatKind")
        if type(self.type_conflict) is not bool:
            raise TypeError("type_conflict must be bool")


@dataclass(frozen=True)
class ResolutionResult:
    request_id: str
    raw_name: str
    decision_time: datetime
    source: str
    source_version: str
    seat_kind_hint: SeatKind | None
    status: ResolutionStatus
    selected_seat_id: str | None
    confidence: Decimal
    candidates: tuple[AliasCandidate, ...]
    algorithm_version: str
    policy_version: str
    policy: ResolutionPolicy
    policy_fingerprint: str
    request_fingerprint: str
    input_evidence_ids: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        _require_non_empty(self.request_id, "request_id")
        _require_non_empty(self.raw_name, "raw_name")
        _require_aware(self.decision_time, "decision_time")
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        if self.seat_kind_hint is not None and type(self.seat_kind_hint) is not SeatKind:
            raise TypeError("seat_kind_hint must be SeatKind or None")
        if type(self.status) is not ResolutionStatus:
            raise TypeError("status must be ResolutionStatus")
        if self.selected_seat_id is not None:
            _require_non_empty(self.selected_seat_id, "selected_seat_id")
        _require_probability(self.confidence, "confidence")
        if type(self.candidates) is not tuple:
            raise TypeError("candidates must be a tuple")
        _require_non_empty(self.algorithm_version, "algorithm_version")
        _require_non_empty(self.policy_version, "policy_version")
        if type(self.policy) is not ResolutionPolicy:
            raise TypeError("policy must be ResolutionPolicy")
        if self.algorithm_version != self.policy.algorithm_version:
            raise ValueError("result algorithm_version does not match policy")
        if self.policy_version != self.policy.version:
            raise ValueError("result policy_version does not match policy")
        if self.policy_fingerprint != self.policy.policy_fingerprint:
            raise ValueError("result policy_fingerprint does not match policy")
        expected_request_fingerprint = compute_request_fingerprint(
            request_id=self.request_id,
            raw_name=self.raw_name,
            decision_time=self.decision_time,
            source=self.source,
            source_version=self.source_version,
            evidence_ids=self.input_evidence_ids,
            seat_kind_hint=self.seat_kind_hint,
        )
        if self.request_fingerprint != expected_request_fingerprint:
            raise ValueError("result request_fingerprint does not match request identity")
        if type(self.input_evidence_ids) is not tuple or not self.input_evidence_ids:
            raise ValueError("input_evidence_ids must be a non-empty tuple")
        for evidence_id in self.input_evidence_ids:
            _require_non_empty(evidence_id, "input_evidence_id")
        _require_non_empty(self.reason, "reason")
        if self.status is ResolutionStatus.AUTO:
            if not self.candidates:
                raise ValueError("AUTO result must contain candidates")
            top = self.candidates[0]
            if self.selected_seat_id != top.seat_id:
                raise ValueError("AUTO result selected_seat_id must equal top candidate")
            if self.confidence != top.score:
                raise ValueError("AUTO result confidence must equal top candidate score")
            if self.confidence < self.policy.auto_score_threshold:
                raise ValueError("AUTO result does not meet score threshold")
            if len(self.candidates) > 1 and (
                self.confidence - self.candidates[1].score < self.policy.minimum_margin
            ):
                raise ValueError("AUTO result does not meet minimum margin")
            if top.seat_kind is SeatKind.UNKNOWN or top.type_conflict:
                raise ValueError("AUTO result cannot use unknown or type-conflict candidate")
            if self.seat_kind_hint is None:
                raise ValueError("AUTO result requires seat_kind_hint")
            if self.seat_kind_hint is not top.seat_kind:
                raise ValueError("AUTO result seat_kind_hint must match top candidate")
        elif self.selected_seat_id is not None:
            raise ValueError("non-AUTO result must not select a seat")
        if self.status is ResolutionStatus.REJECT and self.candidates:
            raise ValueError("REJECT result must not contain candidates")

    @property
    def resolution_fingerprint(self) -> str:
        return _fingerprint(
            "resolution",
            {
                "request_fingerprint": self.request_fingerprint,
                "policy_fingerprint": self.policy_fingerprint,
                "status": self.status.value,
                "selected_seat_id": self.selected_seat_id,
                "confidence": _decimal_text(self.confidence),
                "candidates": [_candidate_payload(candidate) for candidate in self.candidates],
                "reason": self.reason,
            },
        )


@dataclass(frozen=True)
class ReviewDecision:
    request_id: str
    outcome: ReviewOutcome
    seat_id: str | None
    reviewer: str
    reviewed_at: datetime
    reason: str
    algorithm_version: str
    policy_version: str
    policy_fingerprint: str
    request_fingerprint: str
    resolution_fingerprint: str
    input_name: str
    input_evidence_ids: tuple[str, ...]
    review_evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_non_empty(self.request_id, "request_id")
        if type(self.outcome) is not ReviewOutcome:
            raise TypeError("outcome must be ReviewOutcome")
        if self.outcome is ReviewOutcome.APPROVE and self.seat_id is None:
            raise ValueError("approved review must contain seat_id")
        if self.outcome is ReviewOutcome.REJECT and self.seat_id is not None:
            raise ValueError("rejected review must not contain seat_id")
        if self.seat_id is not None:
            _require_non_empty(self.seat_id, "seat_id")
        _require_non_empty(self.reviewer, "reviewer")
        _require_aware(self.reviewed_at, "reviewed_at")
        _require_non_empty(self.reason, "reason")
        _require_non_empty(self.algorithm_version, "algorithm_version")
        _require_non_empty(self.policy_version, "policy_version")
        _require_non_empty(self.policy_fingerprint, "policy_fingerprint")
        _require_non_empty(self.request_fingerprint, "request_fingerprint")
        _require_non_empty(self.resolution_fingerprint, "resolution_fingerprint")
        _require_non_empty(self.input_name, "input_name")
        _require_evidence_ids(self.input_evidence_ids, "input_evidence_ids")
        _require_evidence_ids(self.review_evidence_ids, "review_evidence_ids")
        if set(self.input_evidence_ids).intersection(self.review_evidence_ids):
            raise ValueError("review evidence must be independent from input evidence")


@dataclass(frozen=True)
class ReviewQueue:
    """Persistent review queue; every operation returns a new queue."""

    items: tuple[ResolutionResult, ...] = ()
    decisions: tuple[ReviewDecision, ...] = ()

    def enqueue(self, result: ResolutionResult) -> ReviewQueue:
        if type(result) is not ResolutionResult:
            raise TypeError("result must be ResolutionResult")
        if result.status is not ResolutionStatus.REVIEW:
            raise ValueError("only REVIEW results may enter the review queue")
        existing = next((item for item in self.items if item.request_id == result.request_id), None)
        if existing is not None:
            if existing != result:
                raise ValueError("conflicting payload for request_id")
            return self
        return replace(self, items=self.items + (result,))

    def record_decision(self, decision: ReviewDecision) -> ReviewQueue:
        if type(decision) is not ReviewDecision:
            raise TypeError("decision must be ReviewDecision")
        existing = next(
            (item for item in self.decisions if item.request_id == decision.request_id),
            None,
        )
        if existing is not None:
            if existing != decision:
                raise ValueError("conflicting decision for request_id")
            return self
        queued = next((item for item in self.items if item.request_id == decision.request_id), None)
        if queued is None:
            raise ValueError("request_id is not in the review queue")
        validate_review_decision(queued, decision)
        return replace(self, decisions=self.decisions + (decision,))


AuditRecord = ResolutionResult | ReviewDecision


@dataclass(frozen=True)
class ResolutionAuditLog:
    """Append-only value object for resolution and human-review evidence."""

    entries: tuple[AuditRecord, ...] = ()

    def record_resolution(self, result: ResolutionResult) -> ResolutionAuditLog:
        if type(result) is not ResolutionResult:
            raise TypeError("result must be ResolutionResult")
        existing = next(
            (
                entry
                for entry in self.entries
                if type(entry) is ResolutionResult and entry.request_id == result.request_id
            ),
            None,
        )
        if existing is not None:
            if existing != result:
                raise ValueError("conflicting resolution for request_id")
            return self
        return replace(self, entries=self.entries + (result,))

    def record_review(self, decision: ReviewDecision) -> ResolutionAuditLog:
        if type(decision) is not ReviewDecision:
            raise TypeError("decision must be ReviewDecision")
        resolution = next(
            (
                entry
                for entry in self.entries
                if type(entry) is ResolutionResult and entry.request_id == decision.request_id
            ),
            None,
        )
        if resolution is None:
            raise ValueError("orphan review has no corresponding resolution")
        validate_review_decision(resolution, decision)
        existing = next(
            (
                entry
                for entry in self.entries
                if type(entry) is ReviewDecision and entry.request_id == decision.request_id
            ),
            None,
        )
        if existing is not None:
            if existing != decision:
                raise ValueError("conflicting review for request_id")
            return self
        return replace(self, entries=self.entries + (decision,))


def _require_evidence_ids(values: tuple[str, ...], name: str) -> None:
    if type(values) is not tuple or not values:
        raise ValueError(f"{name} must be a non-empty tuple")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not contain duplicates")
    for evidence_id in values:
        _require_non_empty(evidence_id, "evidence_id")


def _candidate_payload(candidate: AliasCandidate) -> dict[str, object]:
    return {
        "seat_id": candidate.seat_id,
        "score": _decimal_text(candidate.score),
        "rule_hits": list(candidate.rule_hits),
        "seat_kind": candidate.seat_kind.value,
        "type_conflict": candidate.type_conflict,
        "evidence": [
            {
                "alias_id": evidence.alias_id,
                "name": evidence.name,
                "alias_type": evidence.alias_type.value,
                "source": evidence.source,
                "source_version": evidence.source_version,
                "evidence_id": evidence.evidence_id,
                "available_time": evidence.available_time.isoformat(),
                "valid_from": evidence.valid_from.isoformat(),
                "valid_to": None if evidence.valid_to is None else evidence.valid_to.isoformat(),
            }
            for evidence in candidate.evidence
        ],
    }


def validate_review_decision(resolution: ResolutionResult, decision: ReviewDecision) -> None:
    """Validate a review against the exact resolution it is intended to close."""
    if resolution.status is not ResolutionStatus.REVIEW:
        raise ValueError("review decision requires REVIEW resolution")
    if decision.algorithm_version != resolution.algorithm_version:
        raise ValueError("review algorithm_version does not match resolution")
    if decision.policy_version != resolution.policy_version:
        raise ValueError("review policy_version does not match resolution")
    if decision.policy_fingerprint != resolution.policy_fingerprint:
        raise ValueError("review policy fingerprint does not match resolution")
    if decision.request_fingerprint != resolution.request_fingerprint:
        raise ValueError("review request fingerprint does not match resolution")
    if decision.resolution_fingerprint != resolution.resolution_fingerprint:
        raise ValueError("review resolution fingerprint does not match resolution")
    if decision.input_name != resolution.raw_name:
        raise ValueError("review input does not match resolution")
    if decision.input_evidence_ids != resolution.input_evidence_ids:
        raise ValueError("review input evidence does not match resolution")
    if decision.outcome is ReviewOutcome.APPROVE:
        candidate_seat_ids = {candidate.seat_id for candidate in resolution.candidates}
        if decision.seat_id not in candidate_seat_ids:
            raise ValueError("approved seat_id must be one of the candidates")
    elif decision.outcome is ReviewOutcome.REJECT and decision.seat_id is not None:
        raise ValueError("rejected review must not contain seat_id")


__all__ = [
    "AliasCandidate",
    "AliasEvidence",
    "AliasResolutionRequest",
    "AuditRecord",
    "compute_request_fingerprint",
    "NORMALIZATION_POLICY_VERSION",
    "NormalizationPolicy",
    "RESOLUTION_ALGORITHM_VERSION",
    "RESOLUTION_POLICY_VERSION",
    "ResolutionAuditLog",
    "ResolutionPolicy",
    "ResolutionResult",
    "ResolutionStatus",
    "ReviewDecision",
    "ReviewOutcome",
    "ReviewQueue",
    "validate_review_decision",
]
