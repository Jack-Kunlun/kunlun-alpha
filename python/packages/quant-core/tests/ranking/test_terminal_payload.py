from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from quant_core.ranking import (
    FeatureObservation,
    InstrumentFeatureSnapshot,
    MissingFeaturePolicy,
    RankingDirection,
    RankingFeatureSpec,
    RankingSpec,
    rank_instruments,
    ranking_terminal_payload,
)


def test_terminal_payload_preserves_exact_decimal_and_point_in_time_provenance() -> None:
    as_of = datetime(2026, 8, 29, 16, 0, tzinfo=UTC)
    spec = RankingSpec(
        spec_id="local-market-bars",
        version="1.0.0",
        features=(
            RankingFeatureSpec(
                key="momentum_20d",
                label="20 日动量",
                weight_bps=10_000,
                direction=RankingDirection.HIGHER_IS_BETTER,
                missing_policy=MissingFeaturePolicy.EXCLUDE,
            ),
        ),
    )
    snapshot = rank_instruments(
        spec=spec,
        as_of=as_of,
        generated_at=as_of + timedelta(seconds=1),
        instruments=(
            InstrumentFeatureSnapshot(
                instrument_id="600519.SH",
                instrument_name="贵州茅台",
                sector="食品饮料",
                observations=(
                    FeatureObservation(
                        feature_key="momentum_20d",
                        value=Decimal("0.123400"),
                        available_time=as_of,
                        source="bars_daily_v2:test-evidence",
                    ),
                ),
            ),
        ),
    )

    payload = ranking_terminal_payload(snapshot)

    assert payload["sourceMode"] == "VERSIONED_RESEARCH_SNAPSHOT"
    assert payload["snapshotId"] == snapshot.snapshot_id
    assert payload["asOf"] == "2026-08-29T16:00:00Z"
    row = cast(list[dict[str, object]], payload["rows"])[0]
    assert row["instrumentName"] == "贵州茅台"
    contribution = cast(list[dict[str, object]], row["contributions"])[0]
    assert contribution["rawValue"] == "0.123400"
    assert contribution["availableTime"] == "2026-08-29T16:00:00Z"
