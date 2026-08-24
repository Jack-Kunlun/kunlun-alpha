"""Point-in-time, fail-to-review seat alias resolution."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from seat_core.models import Alias, SeatKind, SeatProfile
from seat_core.resolution.models import (
    AliasCandidate,
    AliasEvidence,
    AliasResolutionRequest,
    ResolutionPolicy,
    ResolutionResult,
    ResolutionStatus,
)
from seat_core.resolution.normalization import edit_similarity, normalize_alias_name_parts


def _index_profiles(profiles: Iterable[SeatProfile]) -> dict[str, SeatProfile]:
    indexed: dict[str, SeatProfile] = {}
    for profile in profiles:
        if type(profile) is not SeatProfile:
            raise TypeError("profiles must contain SeatProfile instances")
        existing = indexed.get(profile.seat_id)
        if existing is not None and existing != profile:
            raise ValueError(f"conflicting profiles for seat_id: {profile.seat_id!r}")
        indexed[profile.seat_id] = profile
    return indexed


def _ordered_aliases(aliases: Iterable[Alias]) -> tuple[Alias, ...]:
    by_id: dict[str, Alias] = {}
    for alias in aliases:
        if type(alias) is not Alias:
            raise TypeError("aliases must contain Alias instances")
        existing = by_id.get(alias.alias_id)
        if existing is not None and existing != alias:
            raise ValueError(f"conflicting aliases for alias_id: {alias.alias_id!r}")
        by_id[alias.alias_id] = alias
    return tuple(sorted(by_id.values(), key=lambda item: (item.alias_id, item.seat_id)))


def _evidence(alias: Alias) -> AliasEvidence:
    return AliasEvidence(
        alias_id=alias.alias_id,
        name=alias.name,
        alias_type=alias.alias_type,
        source=alias.source,
        source_version=alias.source_version,
        evidence_id=alias.evidence_id,
        available_time=alias.available_time,
        valid_from=alias.valid_from,
        valid_to=alias.valid_to,
    )


def _match(
    request: AliasResolutionRequest,
    alias: Alias,
    profile: SeatProfile,
    policy: ResolutionPolicy,
) -> tuple[Decimal, tuple[str, ...]]:
    request_name, request_suffix_removed = normalize_alias_name_parts(
        request.raw_name, policy.normalization_policy
    )
    alias_name, alias_suffix_removed = normalize_alias_name_parts(
        alias.name, policy.normalization_policy
    )
    if request_name == alias_name:
        score = Decimal("1.0000")
        rule_hits = ["normalized_exact"]
    else:
        score = edit_similarity(request_name, alias_name)
        rule_hits = ["edit_similarity"]
    if request_suffix_removed or alias_suffix_removed:
        rule_hits.append("common_suffix_normalized")
    if request.seat_kind_hint is not None and request.seat_kind_hint is not profile.seat_kind:
        rule_hits.append("seat_kind_conflict")
    if profile.seat_kind is SeatKind.UNKNOWN:
        rule_hits.append("unknown_seat_kind")
    return score, tuple(rule_hits)


def resolve_alias(
    request: AliasResolutionRequest,
    *,
    profiles: Iterable[SeatProfile],
    aliases: Iterable[Alias],
    policy: ResolutionPolicy | None = None,
) -> ResolutionResult:
    """Resolve one source name without mutating any P4-N01 record."""

    if type(request) is not AliasResolutionRequest:
        raise TypeError("request must be AliasResolutionRequest")
    selected_policy = ResolutionPolicy() if policy is None else policy
    if type(selected_policy) is not ResolutionPolicy:
        raise TypeError("policy must be ResolutionPolicy")
    try:
        normalize_alias_name_parts(request.raw_name, selected_policy.normalization_policy)
    except ValueError as exc:
        return ResolutionResult(
            request_id=request.request_id,
            raw_name=request.raw_name,
            decision_time=request.decision_time,
            source=request.source,
            source_version=request.source_version,
            seat_kind_hint=request.seat_kind_hint,
            status=ResolutionStatus.REJECT,
            selected_seat_id=None,
            confidence=Decimal("0.0000"),
            candidates=(),
            algorithm_version=selected_policy.algorithm_version,
            policy_version=selected_policy.version,
            policy=selected_policy,
            policy_fingerprint=selected_policy.policy_fingerprint,
            request_fingerprint=request.request_fingerprint,
            input_evidence_ids=(request.evidence_id,),
            reason=f"invalid input: {exc}",
        )

    profile_by_seat = _index_profiles(profiles)
    matches: dict[str, list[tuple[Decimal, tuple[str, ...], Alias]]] = {}
    for alias in _ordered_aliases(aliases):
        profile = profile_by_seat.get(alias.seat_id)
        if profile is None:
            continue
        if alias.available_time > request.decision_time or not alias.is_valid_at(
            request.decision_time
        ):
            continue
        if profile.available_time > request.decision_time or not profile.is_valid_at(
            request.decision_time
        ):
            continue
        score, rule_hits = _match(request, alias, profile, selected_policy)
        matches.setdefault(alias.seat_id, []).append((score, rule_hits, alias))

    candidates: list[AliasCandidate] = []
    for seat_id, seat_matches in matches.items():
        best_score = max(match[0] for match in seat_matches)
        best_matches = sorted(
            (match for match in seat_matches if match[0] == best_score),
            key=lambda item: item[2].alias_id,
        )
        profile = profile_by_seat[seat_id]
        rule_hits = tuple(sorted({rule for _, rules, _ in best_matches for rule in rules}))
        candidates.append(
            AliasCandidate(
                seat_id=seat_id,
                score=best_score,
                rule_hits=rule_hits,
                evidence=tuple(_evidence(alias) for _, _, alias in best_matches),
                seat_kind=profile.seat_kind,
                type_conflict=(
                    request.seat_kind_hint is not None
                    and request.seat_kind_hint is not profile.seat_kind
                ),
            )
        )
    ordered_candidates = tuple(sorted(candidates, key=lambda item: (-item.score, item.seat_id)))
    if not ordered_candidates:
        return ResolutionResult(
            request_id=request.request_id,
            raw_name=request.raw_name,
            decision_time=request.decision_time,
            source=request.source,
            source_version=request.source_version,
            seat_kind_hint=request.seat_kind_hint,
            status=ResolutionStatus.REJECT,
            selected_seat_id=None,
            confidence=Decimal("0.0000"),
            candidates=(),
            algorithm_version=selected_policy.algorithm_version,
            policy_version=selected_policy.version,
            policy=selected_policy,
            policy_fingerprint=selected_policy.policy_fingerprint,
            request_fingerprint=request.request_fingerprint,
            input_evidence_ids=(request.evidence_id,),
            reason="no eligible alias candidate",
        )

    top = ordered_candidates[0]
    second = ordered_candidates[1] if len(ordered_candidates) > 1 else None
    blocked_reasons: list[str] = []
    if top.score < selected_policy.auto_score_threshold:
        blocked_reasons.append("low_confidence")
    if second is not None and top.score - second.score < selected_policy.minimum_margin:
        blocked_reasons.append("ambiguous_margin")
    if top.type_conflict:
        blocked_reasons.append("seat_kind_conflict")
    if top.seat_kind is SeatKind.UNKNOWN:
        blocked_reasons.append("unknown_seat")
    if request.seat_kind_hint is None:
        blocked_reasons.append("missing_seat_kind_hint")
    if blocked_reasons:
        return ResolutionResult(
            request_id=request.request_id,
            raw_name=request.raw_name,
            decision_time=request.decision_time,
            source=request.source,
            source_version=request.source_version,
            seat_kind_hint=request.seat_kind_hint,
            status=ResolutionStatus.REVIEW,
            selected_seat_id=None,
            confidence=top.score,
            candidates=ordered_candidates,
            algorithm_version=selected_policy.algorithm_version,
            policy_version=selected_policy.version,
            policy=selected_policy,
            policy_fingerprint=selected_policy.policy_fingerprint,
            request_fingerprint=request.request_fingerprint,
            input_evidence_ids=(request.evidence_id,),
            reason=";".join(blocked_reasons),
        )
    return ResolutionResult(
        request_id=request.request_id,
        raw_name=request.raw_name,
        decision_time=request.decision_time,
        source=request.source,
        source_version=request.source_version,
        seat_kind_hint=request.seat_kind_hint,
        status=ResolutionStatus.AUTO,
        selected_seat_id=top.seat_id,
        confidence=top.score,
        candidates=ordered_candidates,
        algorithm_version=selected_policy.algorithm_version,
        policy_version=selected_policy.version,
        policy=selected_policy,
        policy_fingerprint=selected_policy.policy_fingerprint,
        request_fingerprint=request.request_fingerprint,
        input_evidence_ids=(request.evidence_id,),
        reason="score_and_margin_thresholds_met",
    )


__all__ = ["resolve_alias"]
