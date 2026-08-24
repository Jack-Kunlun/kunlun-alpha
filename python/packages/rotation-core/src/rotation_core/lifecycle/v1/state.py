"""Versioned, evidence-preserving sector lifecycle V1."""

from __future__ import annotations

import hashlib
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


@dataclass(frozen=True)
class LifecycleConfig:
    version: str = LIFECYCLE_VERSION
    freeze_change: float = -0.03
    freeze_breadth: float = 0.2
    ebb_change: float = -0.01
    weak_breadth: float = 0.5
    accelerate_change: float = 0.03
    climax_breadth: float = 0.8


DEFAULT_CONFIG = LifecycleConfig()
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
    transition_id: str
    sector_id: str
    timestamp: str
    from_state: LifecycleState
    to_state: LifecycleState
    reason: str
    confidence: float
    lifecycle_version: str
    snapshot_version: str
    sample_size: int
    freshness_seconds: int | None
    evidence_ids: tuple[str, ...]


def classify(snapshot: SectorSnapshot, config: LifecycleConfig = DEFAULT_CONFIG) -> LifecycleState:
    change = snapshot.average_change
    breadth = snapshot.breadth
    if change < config.freeze_change and breadth < config.freeze_breadth:
        return "FREEZE"
    if change < config.ebb_change and breadth < config.weak_breadth:
        return "EBB"
    if change < 0 and breadth >= config.weak_breadth:
        return "DIVERGENCE"
    if change < 0:
        return "REPAIR"
    if change < config.accelerate_change:
        return "FERMENT" if breadth >= config.weak_breadth else "STARTUP"
    if breadth >= config.climax_breadth:
        return "CLIMAX"
    return "ACCELERATE"


def _transition_id(
    snapshot: SectorSnapshot,
    from_state: LifecycleState,
    to_state: LifecycleState,
    config: LifecycleConfig,
) -> str:
    payload = "|".join(
        (
            config.version,
            snapshot.version,
            snapshot.sector_id,
            snapshot.timestamp,
            from_state,
            to_state,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LifecycleClassifier:
    def __init__(
        self,
        initial: LifecycleState = "STARTUP",
        config: LifecycleConfig = DEFAULT_CONFIG,
    ) -> None:
        if initial not in _TRANSITIONS:
            raise ValueError(f"unknown lifecycle state: {initial!r}")
        self._state: LifecycleState = initial
        self._config = config

    @property
    def state(self) -> LifecycleState:
        return self._state

    def transition(self, snapshot: SectorSnapshot) -> LifecycleTransition:
        target = classify(snapshot, self._config)
        if target != self._state and target not in _TRANSITIONS[self._state]:
            raise IllegalTransitionError(f"illegal transition {self._state} -> {target}")
        previous = self._state
        stable = target == previous
        transition = LifecycleTransition(
            transition_id=_transition_id(snapshot, previous, target, self._config),
            sector_id=snapshot.sector_id,
            timestamp=snapshot.timestamp,
            from_state=previous,
            to_state=target,
            reason=(
                "stable"
                if stable
                else (
                    f"change={snapshot.average_change:.4f} "
                    f"breadth={snapshot.breadth:.4f} "
                    f"speed={snapshot.speed:.4f} "
                    f"config={self._config.version}"
                )
            ),
            confidence=(
                round(snapshot.confidence * 0.9, 6) if stable else _confidence(target, snapshot)
            ),
            lifecycle_version=self._config.version,
            snapshot_version=snapshot.version,
            sample_size=snapshot.sample_size,
            freshness_seconds=snapshot.freshness_seconds,
            evidence_ids=snapshot.evidence_ids,
        )
        self._state = target
        return transition


def _confidence(to_state: LifecycleState, snapshot: SectorSnapshot) -> float:
    if to_state in ("CLIMAX", "ACCELERATE"):
        metric = min(0.5 + snapshot.breadth / 2, 1.0)
    elif to_state in ("EBB", "FREEZE"):
        metric = min(0.5 + (1.0 - snapshot.breadth) / 2, 1.0)
    else:
        metric = 0.6
    return round(metric * snapshot.confidence, 6)
