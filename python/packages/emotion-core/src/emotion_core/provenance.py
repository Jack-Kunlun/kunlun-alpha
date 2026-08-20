"""Structured provenance for auditable emotion results.

Every derived metric carries a :class:`SampleProvenance` describing exactly how
its sample was formed: the algorithm version, the point-in-time decision instant
(``as_of``), the source data versions, the evidence identifiers, and the
included and excluded instruments with per-exclusion reasons. This is structured
data, not free-text — explanations may accompany it but must never replace it.

A :class:`ScoredMetric` is a typed, point-in-time input to a score (value +
availability + provenance), and :class:`MetricProvenance` records the per-metric
attribution that entered a score, so each component is traceable to its source.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from emotion_core.pit import Instant


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


@dataclass(frozen=True)
class ScoredMetric:
    """A typed metric input to a score.

    Carries the raw ``value`` plus its point-in-time ``available_time`` and the
    source / source_version / evidence_id provenance, so a score can enforce a
    single decision instant across all its inputs and record exactly which data
    produced each component.
    """

    value: float
    available_time: str
    source: str
    source_version: str
    evidence_id: str

    def __post_init__(self) -> None:
        # Normalize and validate the availability instant (fail-closed on a
        # naive or malformed timestamp), and require non-empty provenance.
        object.__setattr__(self, "available_time", Instant.parse(self.available_time).isoformat())
        if not self.source.strip():
            raise ValueError("source must be non-empty (missing provenance)")
        if not self.source_version.strip():
            raise ValueError("source_version must be non-empty (missing provenance)")
        if not self.evidence_id.strip():
            raise ValueError("evidence_id must be non-empty (missing evidence)")

    def available_at(self, decision_time: Instant) -> bool:
        """Whether the metric is available at ``decision_time`` (inclusive)."""
        return Instant.parse(self.available_time) <= decision_time


@dataclass(frozen=True)
class MetricProvenance:
    """Per-component provenance of a metric that entered a score."""

    value: float
    as_of: str
    source: str
    source_version: str
    evidence_id: str
