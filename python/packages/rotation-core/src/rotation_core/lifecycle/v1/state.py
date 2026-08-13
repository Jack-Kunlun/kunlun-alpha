"""Sector lifecycle V1.

Classifies a sector into one of eight lifecycle states (startup, ferment,
accelerate, climax, divergence, repair, ebb, freeze) using multiple metrics —
not a single change threshold. Transitions are validated against a legal
transition table; an illegal jump is rejected. Every transition carries a
reason and a confidence, so replay is explainable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rotation_core.snapshot import SectorSnapshot

LifecycleState = Literal[
    "STARTUP",
    "FERMENT",
    "ACCELERATE",
    "CLIMAX",
    "DIVERGENCE",
    "REPAIR",
    "EBB",
    "FREEZE",
]

LIFECYCLE_VERSION = "lifecycle_v1"

# Legal transitions. An illegal jump (e.g. FREEZE -> ACCELERATE) is rejected.
_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    "STARTUP": frozenset({"FERMENT", "EBB"}),
    "FERMENT": frozenset({"ACCELERATE", "EBB"}),
    "ACCELERATE": frozenset({"CLIMAX", "EBB"}),
    "CLIMAX": frozenset({"DIVERGENCE", "EBB"}),
    "DIVERGENCE": frozenset({"REPAIR", "EBB"}),
    "REPAIR": frozenset({"FERMENT", "EBB"}),
    "EBB": frozenset({"FREEZE", "REPAIR"}),
    "FREEZE": frozenset({"STARTUP"}),
}


class IllegalTransitionError(Exception):
    """A lifecycle jump that is not in the legal transition table."""


@dataclass(frozen=True)
class LifecycleTransition:
    """One lifecycle transition with reason and confidence."""

    from_state: LifecycleState
    to_state: LifecycleState
    reason: str
    confidence: float


def classify(snapshot: SectorSnapshot) -> LifecycleState:
    """Classify a snapshot into a lifecycle state using multiple metrics."""
    change = snapshot.average_change
    breadth = snapshot.breadth

    if change < -0.03 and breadth < 0.2:
        return "FREEZE"
    if change < -0.01 and breadth < 0.5:
        return "EBB"
    if change < 0 and breadth >= 0.5:
        return "DIVERGENCE"
    if change < 0:
        return "REPAIR"
    if change < 0.03:
        return "FERMENT" if breadth >= 0.5 else "STARTUP"
    if breadth >= 0.8:
        return "CLIMAX"
    return "ACCELERATE"


class LifecycleClassifier:
    """Tracks a sector's lifecycle transitions across snapshots."""

    def __init__(self, initial: LifecycleState = "STARTUP") -> None:
        self._state: LifecycleState = initial

    @property
    def state(self) -> LifecycleState:
        return self._state

    def transition(self, snapshot: SectorSnapshot) -> LifecycleTransition:
        """Advance the lifecycle based on a snapshot.

        Raises :class:`IllegalTransitionError` when the classified target is
        not reachable from the current state.
        """
        target = classify(snapshot)
        if target == self._state:
            return LifecycleTransition(self._state, target, "stable", 0.9)

        legal = _TRANSITIONS.get(self._state, frozenset())
        if target not in legal:
            raise IllegalTransitionError(f"illegal transition {self._state} -> {target}")

        transition = LifecycleTransition(
            from_state=self._state,
            to_state=target,
            reason=f"change={snapshot.average_change:.4f} breadth={snapshot.breadth:.4f}",
            confidence=_confidence(self._state, target, snapshot),
        )
        self._state = target
        return transition


def _confidence(
    from_state: LifecycleState, to_state: LifecycleState, snapshot: SectorSnapshot
) -> float:
    # Higher confidence when the target state's defining metric is strong.
    if to_state in ("CLIMAX", "ACCELERATE"):
        return min(0.5 + snapshot.breadth / 2, 1.0)
    if to_state in ("EBB", "FREEZE"):
        return min(0.5 + (1.0 - snapshot.breadth) / 2, 1.0)
    return 0.6
