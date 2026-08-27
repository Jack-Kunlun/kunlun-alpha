from __future__ import annotations

from copy import deepcopy

import pytest
from quant_engine.ranking_store import (
    RankingSnapshotConflictError,
    RankingSnapshotNotFoundError,
    RankingSnapshotStore,
)


def snapshot(snapshot_id: str = "a" * 64, as_of: str = "2026-08-27T02:00:00Z") -> dict[str, object]:
    return {
        "snapshotId": snapshot_id,
        "inputFingerprint": "b" * 64,
        "asOf": as_of,
        "generatedAt": "2026-08-27T02:01:00Z",
        "sourceMode": "VERSIONED_RESEARCH_SNAPSHOT",
        "spec": {
            "specId": "cn-equity-intelligence",
            "version": "1.0.0",
            "algorithmVersion": "intelligence-ranking-v1",
            "fingerprint": "c" * 64,
            "minimumCoverageBps": 5000,
            "features": [
                {
                    "key": "momentum",
                    "label": "趋势强度",
                    "weightBps": 10000,
                    "direction": "HIGHER_IS_BETTER",
                    "missingPolicy": "EXCLUDE",
                }
            ],
        },
        "rows": [
            {
                "instrumentId": "600519.SH",
                "instrumentName": "贵州茅台",
                "sector": "食品饮料",
                "status": "INCLUDED",
                "rank": 1,
                "scoreBps": 9000,
                "coverageBps": 10000,
                "contributions": [
                    {
                        "featureKey": "momentum",
                        "label": "趋势强度",
                        "direction": "HIGHER_IS_BETTER",
                        "rawValue": "0.9",
                        "normalizedScoreBps": 9000,
                        "configuredWeightBps": 10000,
                        "effectiveWeightBps": 10000,
                        "contributionBps": 9000,
                        "missingReason": None,
                        "availableTime": "2026-08-27T01:59:00Z",
                        "source": "feature-store@1.0.0",
                    }
                ],
                "exclusionReasons": [],
            }
        ],
    }


def test_store_requires_publication_and_supports_point_in_time_reads() -> None:
    store = RankingSnapshotStore()
    with pytest.raises(RankingSnapshotNotFoundError):
        store.latest()
    published = store.publish(snapshot())
    assert published["sourceMode"] == "VERSIONED_RESEARCH_SNAPSHOT"
    assert store.latest()["snapshotId"] == "a" * 64
    with pytest.raises(RankingSnapshotNotFoundError):
        store.latest("2026-08-27T01:59:59Z")


def test_snapshot_publication_is_idempotent_and_conflicts_fail_closed() -> None:
    store = RankingSnapshotStore()
    payload = snapshot()
    store.publish(payload)
    assert store.publish(payload)["snapshotId"] == "a" * 64
    changed = deepcopy(payload)
    changed["inputFingerprint"] = "d" * 64
    with pytest.raises(RankingSnapshotConflictError):
        store.publish(changed)
