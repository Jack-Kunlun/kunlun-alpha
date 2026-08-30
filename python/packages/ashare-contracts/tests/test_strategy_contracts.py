from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from ashare_contracts.strategy_signal import Signal
from ashare_contracts.strategy_strategy_descriptor import StrategyDescriptor
from pydantic import ValidationError

DECISION_TIME = datetime(2026, 6, 1, 7, tzinfo=UTC)


def _signal_payload() -> dict[str, object]:
    return {
        "schemaVersion": "signal-v1",
        "signalId": "signal:momentum:600001.SH:20260601",
        "strategyId": "momentum.research",
        "strategyVersion": "1.0.0",
        "algorithmVersion": "1.0.0",
        "entityId": "600001.SH",
        "decisionTime": DECISION_TIME.isoformat(),
        "dataCutoffTime": (DECISION_TIME - timedelta(minutes=1)).isoformat(),
        "direction": "LONG",
        "score": "0.7",
        "confidence": "0.8",
        "horizonSessions": 20,
        "rationale": "Point-in-time momentum research signal.",
        "inputSnapshotId": "strategy-context:2026-06-01",
        "inputSnapshotVersion": "1.0.0",
        "evidenceIds": ["feature:momentum.window_20d:600001.SH"],
        "isExecutable": False,
        "executionCapability": "NONE",
    }


def _descriptor_payload() -> dict[str, object]:
    return {
        "schemaVersion": "strategy-descriptor-v1",
        "strategyId": "momentum.research",
        "strategyVersion": "1.0.0",
        "algorithmVersion": "1.0.0",
        "sdkVersion": "1.0.0",
        "lifecycleVersion": "1.0.0",
        "description": "Point-in-time momentum research strategy",
        "requiredFeatures": ["momentum.window_20d"],
        "parameterSpecs": [
            {
                "name": "lookback",
                "valueType": "INTEGER",
                "required": True,
                "description": "Research lookback sessions",
                "minimum": 1,
                "maximum": 250,
            }
        ],
        "lifecycleHooks": ["initialize", "onDecision", "finalize"],
        "signalSchemaVersion": "signal-v1",
        "executionCapability": "NONE",
    }


def test_generated_signal_forbids_execution_and_unknown_order_fields() -> None:
    signal = Signal.model_validate(_signal_payload())

    assert signal.is_executable is False
    assert signal.execution_capability == "NONE"
    with pytest.raises(ValidationError):
        Signal.model_validate({**_signal_payload(), "isExecutable": True})
    with pytest.raises(ValidationError):
        Signal.model_validate({**_signal_payload(), "quantity": 100})
    with pytest.raises(ValidationError, match="dataCutoffTime"):
        Signal.model_validate(
            {
                **_signal_payload(),
                "dataCutoffTime": (DECISION_TIME + timedelta(minutes=1)).isoformat(),
            }
        )
    with pytest.raises(ValidationError, match="evidenceIds"):
        Signal.model_validate({**_signal_payload(), "evidenceIds": ["same", "same"]})
    assert isinstance(signal.evidence_ids, tuple)
    with pytest.raises(ValidationError):
        signal.evidence_ids = signal.evidence_ids
    with pytest.raises(ValidationError):
        signal.evidence_ids[0].root = "mutated:evidence"


def test_generated_descriptor_preserves_research_only_contract() -> None:
    descriptor = StrategyDescriptor.model_validate(_descriptor_payload())

    assert descriptor.algorithm_version == "1.0.0"
    assert descriptor.execution_capability == "NONE"
    assert isinstance(descriptor.required_features, tuple)
    assert isinstance(descriptor.parameter_specs, tuple)
    assert isinstance(descriptor.lifecycle_hooks, tuple)
    with pytest.raises(ValidationError):
        descriptor.required_features[0].root = "mutated.feature"
    with pytest.raises(ValidationError, match="lifecycleHooks"):
        StrategyDescriptor.model_validate(
            {**_descriptor_payload(), "lifecycleHooks": ["onDecision"]}
        )
    payload = _descriptor_payload()
    payload["parameterSpecs"] = [
        {**payload["parameterSpecs"][0], "defaultValue": "20"}  # type: ignore[index]
    ]
    with pytest.raises(ValidationError, match="INTEGER"):
        StrategyDescriptor.model_validate(payload)


def test_generated_descriptor_rejects_coerced_boolean_parameter_defaults() -> None:
    payload = _descriptor_payload()
    payload["parameterSpecs"] = [
        {
            "name": "enabled",
            "valueType": "BOOLEAN",
            "required": True,
            "description": "Whether the research branch is enabled",
            "defaultValue": "true",
        }
    ]

    with pytest.raises(ValidationError):
        StrategyDescriptor.model_validate(payload)
