"""Security resolution domain model (P3-N04).

Pure, deterministic, offline security resolution. No I/O, no network, no
database, no LLM and no embedding. All Instrument/alias data is passed in
explicitly by the caller as as-of snapshots; this package never fetches data.

Key facts enforced here:

* every decision is backed by an integer basis-point confidence and a stable
  reason code; float comparisons are never used for thresholds;
* ``RESOLVED``/``OVERRIDDEN`` are the only statuses that expose a canonical
  resolved target; ``AMBIGUOUS``/``UNRESOLVED`` never do;
* ``decision_time`` (system knowledge) and ``reference_time`` (business
  validity) are explicit and timezone-aware; the wall clock is never used;
* canonical symbol is the repository ``unified_code`` form (``600519.SH``);
  vendor-specific symbols are never produced.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

RESOLVER_VERSION = "resolver-v1"
"""The only implemented resolver algorithm generation.

Versioned identity prefix shared by every resolution and policy fingerprint
in V1. Callers can never stamp a ``resolver-v2`` / ``latest`` / arbitrary
string onto a V1 result.
"""


class ResolutionStatus(StrEnum):
    """Stable resolution outcomes.

    ``RESOLVED`` and ``OVERRIDDEN`` expose a canonical target; ``AMBIGUOUS``
    and ``UNRESOLVED`` never do. Downstream code must not treat the first
    candidate as a binding.
    """

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    OVERRIDDEN = "overridden"


class ResolutionReason(StrEnum):
    """Stable reason codes for a resolution decision."""

    FULL_NAME = "full_name"
    """Normalized surface equals the instrument's registered display name."""

    SHORT_NAME = "short_name"
    """A short-name alias matched and is valid at decision/reference time."""

    FORMER_NAME = "former_name"
    """A former-name alias matched and is valid at decision/reference time."""

    EXACT_SYMBOL = "exact_symbol"
    """The surface is a registered canonical symbol (as-of valid)."""

    NOT_SECURITY = "not_security"
    """Entity kinds that never bind to a security (person/institution/
    policy/region)."""

    NO_MATCH = "no_match"
    """No instrument or alias matched the surface."""

    BELOW_THRESHOLD = "below_threshold"
    """Top candidate score is below the resolved threshold."""

    LOW_CONFIDENCE = "low_confidence"
    """The mention itself failed the resolver eligibility gate: it was
    extracted at too low a confidence to ever be auto-bound, regardless of
    alias/name/symbol matches. Candidates are kept for audit only; a complete,
    explicit manual override may still change the outcome."""

    AMBIGUOUS_TIE = "ambiguous_tie"
    """Top candidates are tied; no context selects one."""

    MARGIN_INSUFFICIENT = "margin_insufficient"
    """Top candidate wins but the gap to second place is too small."""

    OVERRIDE = "override"
    """A valid, non-conflicting manual override was applied."""

    CONFLICTING_OVERRIDES = "conflicting_overrides"
    """Multiple valid overrides disagree; fail-closed."""

    ENTITY_CANDIDATE_CONFLICT = "entity_candidate_conflict"
    """Extraction retained multiple entity targets without decisive context."""


class ResolverPolicyVersionError(ValueError):
    """An unsupported resolver policy version was requested."""


def _require_bps(value: int, name: str) -> None:
    if type(value) is not int or not 0 <= value <= 10000:
        raise ValueError(f"{name} must be an integer in [0, 10000]")


def require_aware(dt: datetime, name: str) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class ResolutionCandidate:
    """A single candidate security for a mention (audit record).

    No candidate is ever "the answer" by position; the resolution status is
    the only binding signal.
    """

    instrument_id: str
    """Canonical instrument id (unified code), e.g. ``600519.SH``."""

    canonical_symbol: str
    """Canonical symbol; identical to ``instrument_id`` in V1."""

    name: str
    """Instrument display name at decision time."""

    score_bps: int
    """Integer basis-point score assigned by this resolver."""

    reason: ResolutionReason
    """How this candidate was matched (full/short/former/exact symbol)."""

    instrument_version: str
    """Version of the Instrument snapshot used for this candidate."""

    instrument_source: str
    """Source of the Instrument snapshot used for this candidate."""

    instrument_available_time: datetime
    """Knowledge time of the Instrument snapshot used for this candidate."""

    alias_provenance: tuple[str, ...] = ()
    """Alias/version/source provenance for the match, ordered and stable."""

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise ValueError("instrument_id must be non-empty")
        if self.canonical_symbol != self.instrument_id:
            raise ValueError("canonical_symbol must equal instrument_id in V1")
        if not self.name:
            raise ValueError("name must be non-empty")
        _require_bps(self.score_bps, "score_bps")
        if not self.instrument_version:
            raise ValueError("instrument_version must be non-empty")
        if not self.instrument_source:
            raise ValueError("instrument_source must be non-empty")
        require_aware(self.instrument_available_time, "instrument_available_time")


@dataclass(frozen=True)
class SecurityResolution:
    """Deterministic outcome of resolving one mention to a security."""

    mention_id: str
    status: ResolutionStatus
    candidates: tuple[ResolutionCandidate, ...]
    """All candidates, stable sorted by (score desc, instrument_id asc)."""

    resolver_version: str
    policy_fingerprint: str
    decision_time: datetime
    reference_time: datetime
    reason: ResolutionReason
    resolved_instrument_id: str | None = None
    resolved_symbol: str | None = None
    override_reference: str | None = None

    def __post_init__(self) -> None:
        if not self.mention_id:
            raise ValueError("mention_id must be non-empty")
        if self.resolver_version != RESOLVER_VERSION:
            raise ResolverPolicyVersionError(
                f"unsupported resolver version: {self.resolver_version!r}"
            )
        require_aware(self.decision_time, "decision_time")
        require_aware(self.reference_time, "reference_time")
        if self.status in (ResolutionStatus.RESOLVED, ResolutionStatus.OVERRIDDEN):
            if not self.resolved_instrument_id or not self.resolved_symbol:
                raise ValueError(f"{self.status.value} requires resolved_instrument_id/symbol")
            if self.resolved_instrument_id != self.resolved_symbol:
                raise ValueError("resolved_symbol must equal resolved_instrument_id")
            if not any(c.instrument_id == self.resolved_instrument_id for c in self.candidates):
                raise ValueError("resolved target must be present among candidates")
        else:
            if self.resolved_instrument_id is not None or self.resolved_symbol is not None:
                raise ValueError(f"{self.status.value} must not expose a resolved target")


@dataclass(frozen=True)
class ResolverPolicy:
    """Versioned, deterministic resolution parameters (integer bps only).

    ``resolved_threshold_bps`` is the bar a top candidate must clear;
    ``ambiguity_margin_bps`` is the required lead over the second candidate.
    Both must hold for ``RESOLVED``; anything below or tied is ``AMBIGUOUS``
    or ``UNRESOLVED``. Equal/just-below/just-above threshold values are tested.
    """

    version: str = RESOLVER_VERSION
    resolved_threshold_bps: int = 8000
    ambiguity_margin_bps: int = 1000
    full_name_score_bps: int = 9000
    short_name_score_bps: int = 8500
    former_name_score_bps: int = 8000
    exact_symbol_score_bps: int = 10000
    override_enabled: bool = True

    def __post_init__(self) -> None:
        if self.version != RESOLVER_VERSION:
            raise ResolverPolicyVersionError(
                f"unsupported version: {self.version!r} (supported: {RESOLVER_VERSION!r})"
            )
        for name in (
            "resolved_threshold_bps",
            "ambiguity_margin_bps",
            "full_name_score_bps",
            "short_name_score_bps",
            "former_name_score_bps",
            "exact_symbol_score_bps",
        ):
            _require_bps(getattr(self, name), name)
        if type(self.override_enabled) is not bool:
            raise TypeError("override_enabled must be bool")

    def fingerprint(self) -> str:
        """Deterministic 64-hex SHA-256 over every result-affecting parameter.

        Canonical JSON (sorted keys, fixed separators, UTF-8, non-ASCII
        preserved). Never the built-in ``hash()``.
        """
        material = {
            "version": self.version,
            "resolved_threshold_bps": self.resolved_threshold_bps,
            "ambiguity_margin_bps": self.ambiguity_margin_bps,
            "full_name_score_bps": self.full_name_score_bps,
            "short_name_score_bps": self.short_name_score_bps,
            "former_name_score_bps": self.former_name_score_bps,
            "exact_symbol_score_bps": self.exact_symbol_score_bps,
            "override_enabled": self.override_enabled,
        }
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "RESOLVER_VERSION",
    "ResolutionCandidate",
    "ResolutionReason",
    "ResolutionStatus",
    "ResolverPolicy",
    "ResolverPolicyVersionError",
    "SecurityResolution",
]
