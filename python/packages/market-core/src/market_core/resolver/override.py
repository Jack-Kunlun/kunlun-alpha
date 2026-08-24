"""Manual override records (P3-N04).

Overrides are immutable, auditable domain records. This package implements no
database, permission or UI. An override never modifies the original mention
and never deletes original candidates: it annotates the resolution with
``OVERRIDDEN`` while preserving the pre-override candidate list.

Rules:

* the override must be known by ``decision_time`` (``available_time``) and
  effective at ``reference_time`` (business window);
* the scope must match the mention (mention id, content id or canonical
  symbol), and the target must exist in the decision-time-visible universe;
* multiple valid overrides that disagree fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from event_core.entities import normalize_surface

from market_core.resolver.models import require_aware


class OverrideScopeType(StrEnum):
    """How an override selects mentions."""

    MENTION = "mention"
    """Single mention id."""

    CONTENT = "content"
    """All mentions of one content id."""

    SYMBOL = "symbol"
    """Mentions whose surface is a canonical symbol."""


@dataclass(frozen=True)
class ManualOverride:
    """One immutable manual override record."""

    override_id: str
    scope_type: OverrideScopeType
    scope_value: str
    target: str
    """Canonical instrument id; must exist in the decision-time universe."""

    reason: str
    reviewer: str
    created_time: datetime
    available_time: datetime
    """System knowledge time; must be ``<= decision_time`` to be usable."""

    effective_from: datetime
    effective_to: datetime | None
    version: str
    evidence_reference: str

    def __post_init__(self) -> None:
        if not self.override_id:
            raise ValueError("override_id must be non-empty")
        if not self.scope_value:
            raise ValueError("scope_value must be non-empty")
        if not self.target:
            raise ValueError("target must be non-empty")
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if not self.reviewer:
            raise ValueError("reviewer must be non-empty")
        require_aware(self.created_time, "created_time")
        require_aware(self.available_time, "available_time")
        if self.created_time > self.available_time:
            raise ValueError("created_time must be <= available_time")
        require_aware(self.effective_from, "effective_from")
        if self.effective_to is not None:
            require_aware(self.effective_to, "effective_to")
            if self.effective_to < self.effective_from:
                raise ValueError("effective_to must be >= effective_from")
        if not self.version:
            raise ValueError("version must be non-empty")
        if not self.evidence_reference:
            raise ValueError("evidence_reference must be non-empty")

    def visible_at(self, decision_time: datetime) -> bool:
        """Whether the system knew this override at ``decision_time``."""
        return self.available_time <= decision_time

    def effective_at(self, reference_time: datetime) -> bool:
        """Whether the override is business-valid at ``reference_time``."""
        if reference_time < self.effective_from:
            return False
        return not (self.effective_to is not None and reference_time > self.effective_to)

    def matches_mention(self, *, mention_id: str, content_id: str, surface: str) -> bool:
        """Whether this override's scope selects the given mention."""
        if self.scope_type is OverrideScopeType.MENTION:
            return self.scope_value == mention_id
        if self.scope_type is OverrideScopeType.CONTENT:
            return self.scope_value == content_id
        if self.scope_type is OverrideScopeType.SYMBOL:
            return normalize_surface(self.scope_value) == normalize_surface(surface)
        return False


__all__ = [
    "ManualOverride",
    "OverrideScopeType",
]
