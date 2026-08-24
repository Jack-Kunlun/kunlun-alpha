from datetime import UTC, datetime, timedelta

from ashare_contracts.event_hot_topic_snapshot import (
    HotTopicSnapshot as ContractHotTopicSnapshot,
)
from hotspot_core import HotScoreComponents, HotTopicSnapshot, TopicLifecycle
from hotspot_core.contract_adapter import (
    HOT_TOPIC_SNAPSHOT_SCHEMA_VERSION,
    to_hot_topic_contract,
)


def test_hot_topic_snapshot_serializes_to_shared_contract() -> None:
    decision_time = datetime(2026, 8, 24, 8, tzinfo=UTC)
    snapshot = HotTopicSnapshot(
        topic_id="topic-semiconductor",
        topic_name="半导体",
        lifecycle=TopicLifecycle.HOT,
        decision_time=decision_time,
        window_start=decision_time - timedelta(hours=24),
        window_end=decision_time,
        score_bps=7_500,
        confidence_bps=8_000,
        components=HotScoreComponents(
            evidence_quality_bps=8_000,
            recency_bps=7_500,
            source_diversity_bps=7_000,
            breadth_bps=7_500,
            momentum_bps=7_500,
        ),
        event_count=2,
        recent_event_count=1,
        stale_event_count=1,
        source_count=2,
        instrument_count=1,
        sector_count=1,
        event_ids=("1" * 64, "2" * 64),
        policy_fingerprint="a" * 64,
    )

    payload = to_hot_topic_contract(snapshot)
    contract = ContractHotTopicSnapshot.model_validate(payload)

    assert payload["schemaVersion"] == HOT_TOPIC_SNAPSHOT_SCHEMA_VERSION
    assert contract.snapshot_id == snapshot.snapshot_id
    assert [event_id.root for event_id in contract.event_ids] == ["1" * 64, "2" * 64]
    assert contract.components.evidence_quality_bps == 8_000
    assert contract.previous_snapshot_id is None
