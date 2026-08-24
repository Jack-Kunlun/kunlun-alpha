"""Security resolution orchestration (P3-N04).

Deterministic, pure resolution of entity mentions against an as-of
instrument universe and a decision-time-filtered alias table.

Rules honoured here:

* point-in-time: the universe and alias table filter by ``decision_time``
  and ``reference_time``; future alias/Instrument information never leaks;
* low confidence, ties and insufficient margins never bind a security —
  they produce ``UNRESOLVED``/``AMBIGUOUS`` without a resolved target;
* canonical symbol is the repository ``unified_code`` form (``600519.SH``);
  vendor-specific symbols are never produced;
* person/institution/policy/region mentions never bind a security;
* a mention below the extraction eligibility gate is never auto-bound
  (``LOW_CONFIDENCE``); only a complete, explicit manual override may change
  the outcome;
* business validity: a security must be listed by ``reference_time``
  (``listDate <= reference_date`` and ``delistDate`` empty or later);
* multi-symbol contexts never pick an arbitrary symbol hint; companies stay
  ``AMBIGUOUS`` unless exactly one canonical symbol is present;
* manual overrides are audited annotations; conflicts fail closed;
* everything is integer basis points; no float threshold comparisons.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from ashare_contracts import Instrument
from event_core.entities import (
    ENTITY_EXTRACTION_VERSION,
    EntityCandidate,
    EntityMention,
    EntityType,
    ExtractionReason,
    is_eligible,
    normalize_surface,
)

from market_core.resolver.alias import AliasTable, AliasType
from market_core.resolver.models import (
    RESOLVER_VERSION,
    ResolutionCandidate,
    ResolutionReason,
    ResolutionStatus,
    ResolverPolicy,
    SecurityResolution,
    require_aware,
)
from market_core.resolver.override import ManualOverride
from market_core.resolver.universe import InstrumentSnapshot, InstrumentUniverse

_MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class _NameHit:
    instrument_id: str
    score_bps: int
    reason: ResolutionReason
    provenance: tuple[str, ...]


def _validate_mention(mention: EntityMention) -> None:
    if mention.extractor_version != ENTITY_EXTRACTION_VERSION:
        raise ValueError(f"unsupported extractor version: {mention.extractor_version!r}")
    if not mention.policy_fingerprint:
        raise ValueError("mention.policy_fingerprint must be non-empty")


def _is_listed_at(instrument: Instrument, reference_time: datetime) -> bool:
    """Business-validity window check against ``reference_time``.

    A security is resolvable only when ``listDate <= reference_date`` and
    either ``delistDate`` is absent or ``reference_date <= delistDate``.
    Known-but-not-yet-listed and already-delisted securities never bind.
    """
    reference_date = reference_time.astimezone(_MARKET_TIMEZONE).date()
    if instrument.list_date is not None and reference_date < instrument.list_date:
        return False
    return not (instrument.delist_date is not None and reference_date > instrument.delist_date)


def _canonical_symbol(value: str) -> str:
    return normalize_surface(value).upper()


def _candidate_sort_key(candidate: ResolutionCandidate) -> tuple[int, str]:
    """Stable ordering: score desc, then canonical id asc (tie-break)."""
    return (-candidate.score_bps, candidate.instrument_id)


def _exact_symbol_candidates(
    mention: EntityMention,
    universe: InstrumentUniverse,
    decision_time: datetime,
    reference_time: datetime,
    policy: ResolverPolicy,
) -> tuple[ResolutionCandidate, ...]:
    """Canonical symbol lookup (SECURITY mentions only)."""
    surface = _canonical_symbol(mention.surface)
    snapshot = universe.lookup(surface, decision_time=decision_time)
    if snapshot is None:
        return ()
    if not _is_listed_at(snapshot.instrument, reference_time):
        return ()
    return (
        ResolutionCandidate(
            instrument_id=snapshot.instrument_id,
            canonical_symbol=snapshot.canonical_symbol,
            name=snapshot.instrument.name,
            score_bps=policy.exact_symbol_score_bps,
            reason=ResolutionReason.EXACT_SYMBOL,
            instrument_version=snapshot.version,
            instrument_source=snapshot.source,
            instrument_available_time=snapshot.available_time,
            alias_provenance=("canonical_symbol",),
        ),
    )


def _name_hits(
    mention: EntityMention,
    universe: InstrumentUniverse,
    aliases: AliasTable,
    decision_time: datetime,
    reference_time: datetime,
    policy: ResolverPolicy,
) -> list[_NameHit]:
    """Collect full-name and alias matches for company mentions."""
    surface = mention.normalized_surface
    hits: list[_NameHit] = []

    # Full registered name (as-of visible, business-listed instruments only).
    for snapshot in universe.as_of(decision_time):
        if not _is_listed_at(snapshot.instrument, reference_time):
            continue
        if normalize_surface(snapshot.instrument.name) == surface:
            hits.append(
                _NameHit(
                    instrument_id=snapshot.instrument_id,
                    score_bps=policy.full_name_score_bps,
                    reason=ResolutionReason.FULL_NAME,
                    provenance=("name",),
                )
            )

    # Aliases known by decision_time and valid at reference_time.
    alias_matches: dict[str, _NameHit] = {}
    for entry in aliases.lookup(
        surface, decision_time=decision_time, reference_time=reference_time
    ):
        target = _canonical_symbol(entry.target)
        snapshot = universe.lookup(target, decision_time=decision_time)
        if snapshot is None:
            continue
        if not _is_listed_at(snapshot.instrument, reference_time):
            continue
        if entry.alias_type is AliasType.FORMER_NAME:
            reason = ResolutionReason.FORMER_NAME
            score = policy.former_name_score_bps
        else:
            reason = ResolutionReason.SHORT_NAME
            score = policy.short_name_score_bps
        # Same target via multiple aliases: keep the highest caller reliability.
        combined = min(score, entry.reliability)
        current = alias_matches.get(target)
        provenance = (entry.alias_id, entry.version, entry.source)
        candidate_rank = (-combined, reason.value, provenance)
        current_rank = (
            None
            if current is None
            else (-current.score_bps, current.reason.value, current.provenance)
        )
        if current_rank is None or candidate_rank < current_rank:
            alias_matches[target] = _NameHit(
                instrument_id=target,
                score_bps=combined,
                reason=reason,
                provenance=provenance,
            )

    hits.extend(alias_matches.values())
    return hits


def _apply_symbol_hint(
    hits: list[_NameHit],
    symbol_hint: str | None,
    universe: InstrumentUniverse,
    decision_time: datetime,
) -> tuple[list[_NameHit], bool]:
    """Narrow a multi-candidate set when a canonical symbol context exists.

    Returns ``(hits, narrowed)``. Narrowing only happens when exactly one
    candidate matches the hint; a hint that matches no candidate is ignored.
    """
    if symbol_hint is None:
        return hits, False
    symbol = _canonical_symbol(symbol_hint)
    matched = [h for h in hits if _canonical_symbol(h.instrument_id) == symbol]
    if matched:
        return matched, True
    return hits, False


def _build_candidates(
    hits: list[_NameHit],
    universe: InstrumentUniverse,
    decision_time: datetime,
) -> tuple[ResolutionCandidate, ...]:
    selected: dict[str, tuple[_NameHit, InstrumentSnapshot]] = {}
    for hit in hits:
        snapshot = universe.lookup(hit.instrument_id, decision_time=decision_time)
        if snapshot is None:
            continue
        current = selected.get(snapshot.instrument_id)
        rank = (-hit.score_bps, hit.reason.value, hit.provenance)
        if current is None:
            selected[snapshot.instrument_id] = (hit, snapshot)
            continue
        current_hit = current[0]
        current_rank = (-current_hit.score_bps, current_hit.reason.value, current_hit.provenance)
        if rank < current_rank:
            selected[snapshot.instrument_id] = (hit, snapshot)

    candidates: list[ResolutionCandidate] = []
    for hit, snapshot in selected.values():
        candidates.append(
            ResolutionCandidate(
                instrument_id=snapshot.instrument_id,
                canonical_symbol=snapshot.canonical_symbol,
                name=snapshot.instrument.name,
                score_bps=hit.score_bps,
                reason=hit.reason,
                instrument_version=snapshot.version,
                instrument_source=snapshot.source,
                instrument_available_time=snapshot.available_time,
                alias_provenance=hit.provenance,
            )
        )
    return tuple(sorted(candidates, key=_candidate_sort_key))


def _has_entity_candidate_conflict(
    mention: EntityMention,
    entity_candidates: tuple[EntityCandidate, ...],
) -> bool:
    targets = {
        normalize_surface(candidate.target)
        for candidate in entity_candidates
        if candidate.mention_id == mention.mention_id
        and candidate.entity_type is mention.entity_type
    }
    return len(targets) > 1


def _decide(
    mention: EntityMention,
    candidates: tuple[ResolutionCandidate, ...],
    policy: ResolverPolicy,
    decision_time: datetime,
    reference_time: datetime,
) -> SecurityResolution:
    """Threshold/margin decision. Never binds below threshold or on ties."""
    if not candidates:
        return SecurityResolution(
            mention_id=mention.mention_id,
            status=ResolutionStatus.UNRESOLVED,
            candidates=(),
            resolver_version=RESOLVER_VERSION,
            policy_fingerprint=policy.fingerprint(),
            decision_time=decision_time,
            reference_time=reference_time,
            reason=ResolutionReason.NO_MATCH,
        )

    top = candidates[0]
    if top.score_bps < policy.resolved_threshold_bps:
        return SecurityResolution(
            mention_id=mention.mention_id,
            status=ResolutionStatus.UNRESOLVED,
            candidates=candidates,
            resolver_version=RESOLVER_VERSION,
            policy_fingerprint=policy.fingerprint(),
            decision_time=decision_time,
            reference_time=reference_time,
            reason=ResolutionReason.BELOW_THRESHOLD,
        )

    if len(candidates) > 1:
        second = candidates[1]
        if top.score_bps == second.score_bps:
            reason = ResolutionReason.AMBIGUOUS_TIE
        elif top.score_bps - second.score_bps < policy.ambiguity_margin_bps:
            reason = ResolutionReason.MARGIN_INSUFFICIENT
        else:
            reason = top.reason
        if reason is not top.reason:
            return SecurityResolution(
                mention_id=mention.mention_id,
                status=ResolutionStatus.AMBIGUOUS,
                candidates=candidates,
                resolver_version=RESOLVER_VERSION,
                policy_fingerprint=policy.fingerprint(),
                decision_time=decision_time,
                reference_time=reference_time,
                reason=reason,
            )

    return SecurityResolution(
        mention_id=mention.mention_id,
        status=ResolutionStatus.RESOLVED,
        candidates=candidates,
        resolver_version=RESOLVER_VERSION,
        policy_fingerprint=policy.fingerprint(),
        decision_time=decision_time,
        reference_time=reference_time,
        reason=top.reason,
        resolved_instrument_id=top.instrument_id,
        resolved_symbol=top.canonical_symbol,
    )


def resolve_security(
    mention: EntityMention,
    *,
    universe: InstrumentUniverse,
    aliases: AliasTable,
    decision_time: datetime,
    reference_time: datetime,
    policy: ResolverPolicy | None = None,
    override: ManualOverride | None = None,
    symbol_hint: str | None = None,
    entity_candidates: tuple[EntityCandidate, ...] = (),
) -> SecurityResolution:
    """Resolve one mention to a security (or explicitly not)."""
    _validate_mention(mention)
    require_aware(decision_time, "decision_time")
    require_aware(reference_time, "reference_time")
    policy = policy or ResolverPolicy()

    # Non-security entity kinds never bind a security.
    if mention.entity_type in (
        EntityType.PERSON,
        EntityType.INSTITUTION,
        EntityType.POLICY,
        EntityType.REGION,
    ):
        return SecurityResolution(
            mention_id=mention.mention_id,
            status=ResolutionStatus.UNRESOLVED,
            candidates=(),
            resolver_version=RESOLVER_VERSION,
            policy_fingerprint=policy.fingerprint(),
            decision_time=decision_time,
            reference_time=reference_time,
            reason=ResolutionReason.NOT_SECURITY,
        )

    # Explicit canonical symbol.
    if mention.entity_type is EntityType.SECURITY:
        candidates = _exact_symbol_candidates(
            mention, universe, decision_time, reference_time, policy
        )
        resolution = _decide(mention, candidates, policy, decision_time, reference_time)
        symbol_context_matched = True
    else:
        # Company name resolution.
        hits = _name_hits(mention, universe, aliases, decision_time, reference_time, policy)
        hits, symbol_context_matched = _apply_symbol_hint(
            hits, symbol_hint, universe, decision_time
        )
        candidates = _build_candidates(hits, universe, decision_time)
        resolution = _decide(mention, candidates, policy, decision_time, reference_time)

    extraction_conflict = mention.entity_type is EntityType.COMPANY and (
        mention.reason is ExtractionReason.AMBIGUOUS_LEXICON
        or _has_entity_candidate_conflict(mention, entity_candidates)
    )
    if (
        extraction_conflict
        and not symbol_context_matched
        and resolution.status is ResolutionStatus.RESOLVED
    ):
        resolution = SecurityResolution(
            mention_id=mention.mention_id,
            status=ResolutionStatus.AMBIGUOUS,
            candidates=resolution.candidates,
            resolver_version=RESOLVER_VERSION,
            policy_fingerprint=resolution.policy_fingerprint,
            decision_time=decision_time,
            reference_time=reference_time,
            reason=ResolutionReason.ENTITY_CANDIDATE_CONFLICT,
        )

    # Eligibility gate: a low-confidence mention is never auto-bound even when
    # an alias/name/symbol matches with high reliability. Candidates are kept
    # for audit; only a complete, explicit manual override may change outcome.
    if not is_eligible(mention):
        if override is not None and policy.override_enabled:
            return _apply_override(
                resolution,
                override,
                universe,
                decision_time,
                reference_time,
                mention,
            )
        return SecurityResolution(
            mention_id=mention.mention_id,
            status=ResolutionStatus.UNRESOLVED,
            candidates=resolution.candidates,
            resolver_version=RESOLVER_VERSION,
            policy_fingerprint=resolution.policy_fingerprint,
            decision_time=decision_time,
            reference_time=reference_time,
            reason=ResolutionReason.LOW_CONFIDENCE,
        )

    # Manual override annotation (single-record API; conflicts handled by
    # the batch API, which filters and validates before calling here).
    if override is not None and policy.override_enabled:
        return _apply_override(
            resolution,
            override,
            universe,
            decision_time,
            reference_time,
            mention,
        )
    return resolution


def _apply_override(
    resolution: SecurityResolution,
    override: ManualOverride,
    universe: InstrumentUniverse,
    decision_time: datetime,
    reference_time: datetime,
    mention: EntityMention,
) -> SecurityResolution:
    """Annotate with OVERRIDDEN when the override is valid, else unchanged."""
    if not override.visible_at(decision_time) or not override.effective_at(reference_time):
        return resolution
    if not override.matches_mention(
        mention_id=mention.mention_id,
        content_id=mention.content_id,
        surface=mention.normalized_surface,
    ):
        return resolution
    target = universe.lookup(_canonical_symbol(override.target), decision_time=decision_time)
    if target is None:
        return resolution
    if not _is_listed_at(target.instrument, reference_time):
        return resolution
    if not any(c.instrument_id == target.instrument_id for c in resolution.candidates):
        # Override target not among original candidates: annotate with the
        # canonical target while preserving the original candidate list.
        annotated_candidates = resolution.candidates + (
            ResolutionCandidate(
                instrument_id=target.instrument_id,
                canonical_symbol=target.canonical_symbol,
                name=target.instrument.name,
                score_bps=10000,
                reason=ResolutionReason.OVERRIDE,
                instrument_version=target.version,
                instrument_source=target.source,
                instrument_available_time=target.available_time,
                alias_provenance=(override.override_id,),
            ),
        )
        candidates = tuple(sorted(annotated_candidates, key=_candidate_sort_key))
    else:
        candidates = resolution.candidates
    return SecurityResolution(
        mention_id=resolution.mention_id,
        status=ResolutionStatus.OVERRIDDEN,
        candidates=candidates,
        resolver_version=RESOLVER_VERSION,
        policy_fingerprint=resolution.policy_fingerprint,
        decision_time=resolution.decision_time,
        reference_time=resolution.reference_time,
        reason=ResolutionReason.OVERRIDE,
        resolved_instrument_id=target.instrument_id,
        resolved_symbol=target.canonical_symbol,
        override_reference=override.override_id,
    )


def _matching_overrides(
    mention: EntityMention,
    overrides: tuple[ManualOverride, ...],
    universe: InstrumentUniverse,
    decision_time: datetime,
    reference_time: datetime,
) -> tuple[tuple[ManualOverride, ...], bool]:
    """Return valid matches and whether duplicate identities conflict."""
    seen: dict[str, ManualOverride] = {}
    conflicting_ids: set[str] = set()
    for ov in overrides:
        if not ov.visible_at(decision_time) or not ov.effective_at(reference_time):
            continue
        if not ov.matches_mention(
            mention_id=mention.mention_id,
            content_id=mention.content_id,
            surface=mention.normalized_surface,
        ):
            continue
        previous = seen.get(ov.override_id)
        if previous is not None:
            if previous != ov:
                conflicting_ids.add(ov.override_id)
            continue
        seen[ov.override_id] = ov

    valid: list[ManualOverride] = []
    for override_id, ov in seen.items():
        if override_id in conflicting_ids:
            continue
        target = universe.lookup(_canonical_symbol(ov.target), decision_time=decision_time)
        if target is None or not _is_listed_at(target.instrument, reference_time):
            continue
        valid.append(ov)
    valid.sort(
        key=lambda ov: (
            ov.override_id,
            ov.scope_type.value,
            normalize_surface(ov.scope_value),
            _canonical_symbol(ov.target),
        )
    )
    return tuple(valid), bool(conflicting_ids)


def _resolve_batch_mention(
    mention: EntityMention,
    *,
    universe: InstrumentUniverse,
    aliases: AliasTable,
    decision_time: datetime,
    reference_time: datetime,
    policy: ResolverPolicy,
    overrides: tuple[ManualOverride, ...],
    symbol_hint: str | None,
    entity_candidates: tuple[EntityCandidate, ...],
) -> SecurityResolution:
    matched: tuple[ManualOverride, ...] = ()
    conflicting = False
    if policy.override_enabled:
        matched, conflicting = _matching_overrides(
            mention,
            overrides,
            universe,
            decision_time,
            reference_time,
        )
        if len(matched) > 1:
            targets = {_canonical_symbol(override.target) for override in matched}
            conflicting = conflicting or len(targets) > 1

    resolution = resolve_security(
        mention,
        universe=universe,
        aliases=aliases,
        decision_time=decision_time,
        reference_time=reference_time,
        policy=policy,
        override=None if conflicting or not matched else matched[0],
        symbol_hint=symbol_hint,
        entity_candidates=entity_candidates,
    )
    if not conflicting:
        return resolution
    return SecurityResolution(
        mention_id=resolution.mention_id,
        status=ResolutionStatus.AMBIGUOUS,
        candidates=resolution.candidates,
        resolver_version=RESOLVER_VERSION,
        policy_fingerprint=resolution.policy_fingerprint,
        decision_time=resolution.decision_time,
        reference_time=resolution.reference_time,
        reason=ResolutionReason.CONFLICTING_OVERRIDES,
    )


def resolve_mentions(
    mentions: tuple[EntityMention, ...],
    *,
    universe: InstrumentUniverse,
    aliases: AliasTable,
    decision_time: datetime,
    reference_time: datetime,
    policy: ResolverPolicy | None = None,
    overrides: tuple[ManualOverride, ...] = (),
    entity_candidates: tuple[EntityCandidate, ...] = (),
) -> tuple[SecurityResolution, ...]:
    """Resolve a batch; SECURITY mentions provide symbol context for the rest.

    Overrides that disagree on the same mention fail closed to ``AMBIGUOUS``.
    """
    require_aware(decision_time, "decision_time")
    require_aware(reference_time, "reference_time")
    policy = policy or ResolverPolicy()

    security_results: dict[int, SecurityResolution] = {}
    symbols_by_content: dict[str, set[str]] = {}
    for index, mention in enumerate(mentions):
        if mention.entity_type is not EntityType.SECURITY:
            continue
        resolution = _resolve_batch_mention(
            mention,
            universe=universe,
            aliases=aliases,
            decision_time=decision_time,
            reference_time=reference_time,
            policy=policy,
            overrides=overrides,
            symbol_hint=None,
            entity_candidates=entity_candidates,
        )
        security_results[index] = resolution
        if (
            resolution.status in (ResolutionStatus.RESOLVED, ResolutionStatus.OVERRIDDEN)
            and resolution.resolved_symbol is not None
        ):
            symbols_by_content.setdefault(mention.content_id, set()).add(
                _canonical_symbol(resolution.resolved_symbol)
            )

    results: list[SecurityResolution] = []
    for index, mention in enumerate(mentions):
        if mention.entity_type is EntityType.SECURITY:
            results.append(security_results[index])
            continue
        symbols = symbols_by_content.get(mention.content_id, set())
        hint = next(iter(symbols)) if len(symbols) == 1 else None
        results.append(
            _resolve_batch_mention(
                mention,
                universe=universe,
                aliases=aliases,
                decision_time=decision_time,
                reference_time=reference_time,
                policy=policy,
                overrides=overrides,
                symbol_hint=hint,
                entity_candidates=entity_candidates,
            )
        )

    return tuple(results)


__all__ = [
    "RESOLVER_VERSION",
    "ResolutionCandidate",
    "ResolutionReason",
    "ResolutionStatus",
    "ResolverPolicy",
    "SecurityResolution",
    "resolve_mentions",
    "resolve_security",
]
