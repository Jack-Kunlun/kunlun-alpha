"""Wire projection for published, versioned ranking snapshots."""

from __future__ import annotations

from .models import RankingSnapshot, canonical_instant


def ranking_terminal_payload(snapshot: RankingSnapshot) -> dict[str, object]:
    """Project a domain snapshot to the versioned terminal JSON contract."""
    return {
        "snapshotId": snapshot.snapshot_id,
        "inputFingerprint": snapshot.input_fingerprint,
        "asOf": canonical_instant(snapshot.as_of, field_name="as_of"),
        "generatedAt": canonical_instant(snapshot.generated_at, field_name="generated_at"),
        "sourceMode": "VERSIONED_RESEARCH_SNAPSHOT",
        "spec": {
            "specId": snapshot.spec.spec_id,
            "version": snapshot.spec.version,
            "algorithmVersion": snapshot.spec.algorithm_version,
            "fingerprint": snapshot.spec.fingerprint,
            "minimumCoverageBps": snapshot.spec.minimum_coverage_bps,
            "features": [
                {
                    "key": feature.key,
                    "label": feature.label,
                    "weightBps": feature.weight_bps,
                    "direction": feature.direction.value,
                    "missingPolicy": feature.missing_policy.value,
                }
                for feature in snapshot.spec.features
            ],
        },
        "rows": [
            {
                "instrumentId": row.instrument_id,
                "instrumentName": row.instrument_name,
                "sector": row.sector,
                "status": row.status.value,
                "rank": row.rank,
                "scoreBps": row.score_bps,
                "coverageBps": row.coverage_bps,
                "contributions": [
                    {
                        "featureKey": item.feature_key,
                        "label": item.label,
                        "direction": item.direction.value,
                        "rawValue": (
                            format(item.raw_value, "f") if item.raw_value is not None else None
                        ),
                        "normalizedScoreBps": item.normalized_score_bps,
                        "configuredWeightBps": item.configured_weight_bps,
                        "effectiveWeightBps": item.effective_weight_bps,
                        "contributionBps": item.contribution_bps,
                        "missingReason": item.missing_reason,
                        "availableTime": (
                            canonical_instant(item.available_time, field_name="available_time")
                            if item.available_time is not None
                            else None
                        ),
                        "source": item.source,
                    }
                    for item in row.contributions
                ],
                "exclusionReasons": list(row.exclusion_reasons),
            }
            for row in snapshot.rows
        ],
    }
