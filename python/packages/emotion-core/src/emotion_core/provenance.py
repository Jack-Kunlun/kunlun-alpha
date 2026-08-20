"""Structured provenance for auditable emotion results.

Every derived metric carries a :class:`SampleProvenance` describing exactly how
its sample was formed: the algorithm version, the point-in-time decision instant
(``as_of``), the source data versions, the evidence identifiers, and the
included and excluded instruments with per-exclusion reasons. This is structured
data, not free-text — explanations may accompany it but must never replace it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SampleProvenance:
    """How a derived sample was formed, for point-in-time auditability."""

    algorithm_version: str
    as_of: str
    included: tuple[str, ...] = ()
    excluded: dict[str, str] = field(default_factory=dict)
    source_versions: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    @property
    def sample_size(self) -> int:
        """The number of included samples."""
        return len(self.included)
