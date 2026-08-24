"""Security resolution (P3-N04)."""

from market_core.resolver.alias import AliasEntry, AliasTable, AliasType
from market_core.resolver.models import (
    RESOLVER_VERSION,
    ResolutionCandidate,
    ResolutionReason,
    ResolutionStatus,
    ResolverPolicy,
    ResolverPolicyVersionError,
    SecurityResolution,
)
from market_core.resolver.override import ManualOverride, OverrideScopeType
from market_core.resolver.resolver import resolve_mentions, resolve_security
from market_core.resolver.universe import InstrumentSnapshot, InstrumentUniverse

__all__ = [
    "RESOLVER_VERSION",
    "AliasEntry",
    "AliasTable",
    "AliasType",
    "InstrumentSnapshot",
    "InstrumentUniverse",
    "ManualOverride",
    "OverrideScopeType",
    "ResolutionCandidate",
    "ResolutionReason",
    "ResolutionStatus",
    "ResolverPolicy",
    "ResolverPolicyVersionError",
    "SecurityResolution",
    "resolve_mentions",
    "resolve_security",
]
