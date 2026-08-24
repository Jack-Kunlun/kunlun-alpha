"""P4-N02 deterministic seat alias resolution public API."""

from seat_core.resolution.models import (
    NORMALIZATION_POLICY_VERSION,
    RESOLUTION_ALGORITHM_VERSION,
    RESOLUTION_POLICY_VERSION,
    AliasCandidate,
    AliasEvidence,
    AliasResolutionRequest,
    AuditRecord,
    NormalizationPolicy,
    ResolutionAuditLog,
    ResolutionPolicy,
    ResolutionResult,
    ResolutionStatus,
    ReviewDecision,
    ReviewOutcome,
    ReviewQueue,
    compute_request_fingerprint,
    validate_review_decision,
)
from seat_core.resolution.normalization import (
    edit_similarity,
    normalize_alias_name,
    normalize_alias_name_parts,
)
from seat_core.resolution.resolver import resolve_alias

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
    "edit_similarity",
    "normalize_alias_name",
    "normalize_alias_name_parts",
    "resolve_alias",
]
