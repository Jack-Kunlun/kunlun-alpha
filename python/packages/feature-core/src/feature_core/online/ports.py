from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from feature_core.batch.models import CalculatorIdentity, RegistrySnapshotRef
from feature_core.registry import FeatureSpec

from .models import (
    EventTimeWindow,
    OnlineCasResult,
    OnlineFeatureEvent,
    OnlineStateEnvelope,
    OnlineStreamState,
)

type OnlineCalculator = Callable[
    [FeatureSpec, EventTimeWindow, tuple[OnlineFeatureEvent, ...]],
    object,
]


@dataclass(frozen=True, slots=True)
class OnlineCalculatorArtifact:
    identity: CalculatorIdentity
    calculator: OnlineCalculator


class OnlineStateStore(Protocol):
    def load(self, stream_key: str) -> OnlineStateEnvelope | None: ...

    def compare_and_set(
        self,
        *,
        expected_revision: int | None,
        candidate: OnlineStateEnvelope,
    ) -> OnlineCasResult: ...


class OnlineStateIntegrity(Protocol):
    def seal(
        self,
        state: OnlineStreamState,
        *,
        retain_until: datetime,
    ) -> OnlineStateEnvelope: ...

    def verify(self, envelope: OnlineStateEnvelope) -> bool: ...


class OnlineCalculatorTrust(Protocol):
    def resolve(
        self,
        registry_ref: RegistrySnapshotRef,
    ) -> OnlineCalculatorArtifact | None: ...
