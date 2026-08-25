from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from quant_core.strategy import Signal, StrategyContext, StrategyRunner

from .models import BacktestOrderIntent


@runtime_checkable
class RandomSource(Protocol):
    """Per-run deterministic entropy boundary supplied by the engine."""

    @property
    def manifest_digest(self) -> str: ...

    @property
    def seed(self) -> str | int: ...

    @property
    def algorithm_name(self) -> str: ...

    @property
    def domain_name(self) -> str: ...

    def bytes(self, event_id: str, purpose: str, index: int, length: int = 32) -> bytes: ...

    def unit_value(self, event_id: str, purpose: str, index: int) -> Decimal: ...

    def unit_decimal(self, event_id: str, purpose: str, index: int) -> Decimal: ...

    def integer(self, event_id: str, purpose: str, index: int, upper_bound: int) -> int: ...


@runtime_checkable
class PortfolioIntentPolicy(Protocol):
    """Pure Signal-to-intent boundary; it owns no portfolio or fill state."""

    policy_id: str
    policy_version: str
    implementation_fingerprint: str

    def to_intents(
        self,
        signals: tuple[Signal, ...],
        *,
        context: StrategyContext,
        event_id: str,
        random_source: RandomSource,
        manifest_digest: str,
        domain: str,
    ) -> tuple[BacktestOrderIntent, ...]: ...


@runtime_checkable
class BacktestProgram(Protocol):
    """Trusted factory boundary for run-local strategy and policy instances.

    The fingerprint fields are provenance declarations injected by trusted
    build/orchestration code, not remote proof of Python source or bytecode
    identity and freshness. The factory MUST return objects scoped to one
    run; the engine does not protect against a non-conforming in-process
    program that lies or observes global state.
    """

    strategy_implementation_fingerprint: str
    policy_implementation_fingerprint: str

    def create_strategy_runner(self) -> StrategyRunner: ...

    def create_portfolio_intent_policy(self) -> PortfolioIntentPolicy: ...


__all__ = ["BacktestProgram", "PortfolioIntentPolicy", "RandomSource"]
