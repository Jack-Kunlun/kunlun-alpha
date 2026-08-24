"""Public contract adapters for hotspot snapshots."""

from hotspot_core import HotTopicSnapshot

HOT_TOPIC_SNAPSHOT_SCHEMA_VERSION = "hot-topic-snapshot-v1"


def to_hot_topic_contract(snapshot: HotTopicSnapshot) -> dict[str, object]:
    """Serialize a domain snapshot into the versioned shared-contract payload."""

    components = snapshot.components
    return {
        "schemaVersion": HOT_TOPIC_SNAPSHOT_SCHEMA_VERSION,
        "snapshotId": snapshot.snapshot_id,
        "topicId": snapshot.topic_id,
        "topicName": snapshot.topic_name,
        "lifecycle": snapshot.lifecycle.value,
        "decisionTime": snapshot.decision_time.isoformat(),
        "windowStart": snapshot.window_start.isoformat(),
        "windowEnd": snapshot.window_end.isoformat(),
        "scoreBps": snapshot.score_bps,
        "confidenceBps": snapshot.confidence_bps,
        "components": {
            "evidenceQualityBps": components.evidence_quality_bps,
            "recencyBps": components.recency_bps,
            "sourceDiversityBps": components.source_diversity_bps,
            "breadthBps": components.breadth_bps,
            "momentumBps": components.momentum_bps,
        },
        "eventCount": snapshot.event_count,
        "recentEventCount": snapshot.recent_event_count,
        "staleEventCount": snapshot.stale_event_count,
        "sourceCount": snapshot.source_count,
        "instrumentCount": snapshot.instrument_count,
        "sectorCount": snapshot.sector_count,
        "eventIds": list(snapshot.event_ids),
        "policyFingerprint": snapshot.policy_fingerprint,
        "previousSnapshotId": snapshot.previous_snapshot_id,
        "algorithmVersion": snapshot.algorithm_version,
    }
