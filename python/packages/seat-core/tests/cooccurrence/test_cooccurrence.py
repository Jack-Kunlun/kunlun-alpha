"""P4-N05 seat co-occurrence tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from seat_core.cooccurrence import (
    BOOTSTRAP_ALGORITHM_VERSION,
    COOCCURRENCE_ALGORITHM_VERSION,
    COOCCURRENCE_FINGERPRINT_ALGORITHM_VERSION,
    COOCCURRENCE_POLICY_VERSION,
    COOCCURRENCE_SCHEMA_VERSION,
    HASH_TO_INDEX_ALGORITHM_VERSION,
    R7_QUANTILE_ALGORITHM_VERSION,
    SEAT_EVENT_ID_ALGORITHM_VERSION,
    SEED_SERIALIZATION_VERSION,
    TOPIC_MEMBERSHIP_SCHEMA_VERSION,
    CIStatus,
    CooccurrenceInputError,
    CooccurrenceKey,
    CooccurrencePolicy,
    CooccurrenceRecord,
    CooccurrenceResult,
    EventTopicMembership,
    SeatEventKey,
    compute_bootstrap_mean_ci,
    compute_seat_cooccurrence,
    compute_seat_event_id,
    r7_quantile,
)
from seat_core.features import (
    PERFORMANCE_ALGORITHM_VERSION,
    PERFORMANCE_FEATURE_SCHEMA_VERSION,
    PERFORMANCE_POLICY_VERSION,
    DailyPriceObservation,
    ExclusionReason,
    PerformanceSample,
    PerformanceStatus,
    SeatPerformanceFeature,
)
from seat_core.models import compute_seat_id

DECISION_TIME = datetime(2026, 1, 12, 8, 0, tzinfo=UTC)


def _bars_for(
    instrument_id: str,
    trade_date: date,
    closes: tuple[str, ...] = ("100", "101", "102", "103", "104", "105"),
    *,
    available_time: datetime = DECISION_TIME,
    source: str = "prices",
    source_version: str = "prices-v1",
    data_version: str = "prices-data-v1",
) -> tuple[DailyPriceObservation, ...]:
    days = tuple(trade_date + timedelta(days=index) for index in range(6))
    return tuple(
        DailyPriceObservation(
            instrument_id=instrument_id,
            trade_date=day,
            event_time=datetime(day.year, day.month, day.day, 15, tzinfo=UTC),
            close=Decimal(close),
            available_time=available_time,
            raw_capture_id=f"capture-{instrument_id}-{day}",
            replacement_version=1,
            source=source,
            source_version=source_version,
            data_version=data_version,
            adjustment="FORWARD_ADJUSTED",
            session="CONTINUOUS",
            schema_version="daily-bar-v1",
        )
        for day, close in zip(days, closes, strict=True)
    )


def _sample_for(
    instrument_id: str,
    trade_date: date,
    *,
    trade_suffix: str,
    closes: tuple[str, ...] = ("100", "101", "102", "103", "104", "105"),
    trade_available_time: datetime = DECISION_TIME,
    bars: tuple[DailyPriceObservation, ...] | None = None,
    included: bool = True,
    event_returns: tuple[Decimal, ...] | None = None,
) -> PerformanceSample:
    selected_bars = _bars_for(instrument_id, trade_date, closes) if bars is None else bars
    returns = (
        tuple(bar.close / selected_bars[0].close - Decimal("1") for bar in selected_bars[1:])
        if event_returns is None
        else event_returns
    )
    return PerformanceSample(
        trade_id=f"trade-{trade_suffix}",
        trade_lineage_id=f"lineage-{trade_suffix}",
        trade_revision_id=f"revision-{trade_suffix}",
        trade_previous_revision_id=None,
        trade_source="dragon-tiger",
        trade_source_version="2026-01",
        trade_raw_record_id=f"raw-{trade_suffix}",
        trade_evidence_id=f"evidence-{trade_suffix}",
        trade_available_time=trade_available_time,
        instrument_id=instrument_id,
        trade_date=trade_date,
        included=included,
        exclusion_reason=None,
        path_dates=tuple(bar.trade_date for bar in selected_bars),
        bars=selected_bars,
        event_returns=returns,
        max_drawdown=Decimal("0"),
    )


def _feature_with_samples(
    seat_name: str,
    samples: tuple[PerformanceSample, ...],
    *,
    schema_version: str = PERFORMANCE_FEATURE_SCHEMA_VERSION,
    window_start: date = date(2026, 1, 5),
    window_end: date = date(2026, 1, 12),
    decision_time: datetime = DECISION_TIME,
    algorithm_version: str = PERFORMANCE_ALGORITHM_VERSION,
    policy_version: str = PERFORMANCE_POLICY_VERSION,
    policy_fingerprint: str = "sha256:parent-policy",
) -> SeatPerformanceFeature:
    return SeatPerformanceFeature(
        schema_version=schema_version,
        seat_id=compute_seat_id(seat_name),
        window_start=window_start,
        window_end=window_end,
        decision_time=decision_time,
        logical_available_time=decision_time,
        status=PerformanceStatus.INSUFFICIENT_SAMPLES,
        sample_count=sum(sample.included for sample in samples),
        performance=None,
        preference=None,
        samples=samples,
        style_sample_count=0,
        style_observations=(),
        style_exclusions=(),
        algorithm_version=algorithm_version,
        policy_version=policy_version,
        policy_fingerprint=policy_fingerprint,
    )


def _feature(seat_name: str) -> SeatPerformanceFeature:
    return _feature_with_samples(
        seat_name,
        (_sample_for("600519.SH", date(2026, 1, 5), trade_suffix=seat_name),),
    )


def _topic(
    instrument_id: str = "600519.SH",
    trade_date: date = date(2026, 1, 5),
    *,
    topic_id: str = "topic-alpha",
    available_time: datetime = DECISION_TIME,
    taxonomy_id: str = "taxonomy-seat-v1",
    taxonomy_version: str = "taxonomy-v1",
    assignment_version: str = "assignment-v1",
    assignment_fingerprint: str = "sha256:assignment-v1",
    source: str = "curated",
    source_version: str = "curated-v1",
    evidence_id: str = "topic-evidence-1",
    upstream_market_event_ids: tuple[str, ...] = (),
) -> EventTopicMembership:
    return EventTopicMembership(
        seat_event_key=SeatEventKey(instrument_id, trade_date),
        topic_id=topic_id,
        taxonomy_id=taxonomy_id,
        taxonomy_version=taxonomy_version,
        assignment_version=assignment_version,
        assignment_fingerprint=assignment_fingerprint,
        source=source,
        source_version=source_version,
        evidence_id=evidence_id,
        available_time=available_time,
        upstream_market_event_ids=upstream_market_event_ids,
    )


def _topic_policy(**overrides: object) -> CooccurrencePolicy:
    policy = CooccurrencePolicy(
        allowed_taxonomy_ids=("taxonomy-seat-v1",),
        allowed_taxonomy_versions=("taxonomy-v1",),
        allowed_topic_sources=("curated",),
    )
    return replace(policy, **overrides)


def _record(result: CooccurrenceResult, *, topic_id: str | None = None) -> CooccurrenceRecord:
    records = result.records
    return next(item for item in records if item.key.topic_id == topic_id)


def test_three_seats_create_three_canonical_pairs() -> None:
    result = compute_seat_cooccurrence(
        [_feature("seat:alpha"), _feature("seat:beta"), _feature("seat:gamma")]
    )

    assert len(result.records) == 3
    assert all(record.key.left_seat_id < record.key.right_seat_id for record in result.records)
    assert all(record.key.left_seat_id != record.key.right_seat_id for record in result.records)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "other-schema"),
        ("window_start", date(2026, 1, 6)),
        ("window_end", date(2026, 1, 13)),
        ("decision_time", DECISION_TIME + timedelta(seconds=1)),
        ("algorithm_version", "other-algorithm"),
        ("policy_version", "other-policy"),
        ("policy_fingerprint", "sha256:other-policy"),
    ],
)
def test_parent_snapshot_mismatch_is_fail_closed(field: str, value: object) -> None:
    changed = replace(_feature("seat:beta"), **{field: value})

    with pytest.raises(CooccurrenceInputError, match="parent features"):
        compute_seat_cooccurrence([_feature("seat:alpha"), changed])


def test_reordering_features_samples_topics_and_duplicates_is_invariant() -> None:
    first = _feature("seat:alpha")
    second = _feature("seat:beta")
    third = _feature("seat:gamma")
    policy = _topic_policy()
    valid = _topic(upstream_market_event_ids=("market-event-7", "market-event-2"))
    future = _topic(
        topic_id="future-topic",
        available_time=DECISION_TIME + timedelta(seconds=1),
    )
    unknown = _topic(
        topic_id="unknown-topic",
        taxonomy_id="untrusted-taxonomy",
        evidence_id="unknown-evidence",
    )

    left = compute_seat_cooccurrence(
        [first, second, third], [valid, future, unknown], policy=policy
    )
    right = compute_seat_cooccurrence(
        [third, second, first],
        [unknown, valid, valid, future],
        policy=policy,
    )

    assert left == right
    assert left.fingerprint == right.fingerprint
    assert left.diagnostics == right.diagnostics


def test_same_seat_duplicate_samples_do_not_increase_support_and_keep_evidence() -> None:
    sample_a = _sample_for("600519.SH", date(2026, 1, 5), trade_suffix="duplicate-a")
    sample_b = _sample_for("600519.SH", date(2026, 1, 5), trade_suffix="duplicate-b")
    result = compute_seat_cooccurrence(
        [
            _feature_with_samples("seat:alpha", (sample_a, sample_b)),
            _feature("seat:beta"),
        ]
    )

    record = _record(result)
    assert record.support_count == 1
    alpha_evidence = next(
        evidence
        for evidence in record.provenance.seat_trade_evidence
        if evidence.seat_id == compute_seat_id("seat:alpha")
    )
    assert len(alpha_evidence.samples) == 2
    assert {sample.trade_evidence_id for sample in alpha_evidence.samples} == {
        "evidence-duplicate-a",
        "evidence-duplicate-b",
    }


def test_shared_event_outcome_conflict_fails_closed() -> None:
    original = _sample_for("600519.SH", date(2026, 1, 5), trade_suffix="conflict-a")
    conflicting = _sample_for(
        "600519.SH",
        date(2026, 1, 5),
        trade_suffix="conflict-b",
        closes=("100", "102", "103", "104", "105", "106"),
    )

    with pytest.raises(CooccurrenceInputError, match="outcome conflict"):
        compute_seat_cooccurrence(
            [
                _feature_with_samples("seat:alpha", (original,)),
                _feature_with_samples("seat:beta", (conflicting,)),
            ]
        )


def test_isolated_event_is_diagnostic_without_a_pair() -> None:
    result = compute_seat_cooccurrence([_feature("seat:alpha")])

    assert result.records == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["isolated_event"]


def _five_event_features() -> list[SeatPerformanceFeature]:
    samples_alpha = tuple(
        _sample_for(
            "600519.SH",
            date(2026, 1, 5) + timedelta(days=index),
            trade_suffix=f"five-alpha-{index}",
            closes=("100", "101", "102", "103", "104", str(105 + index)),
        )
        for index in range(5)
    )
    samples_beta = tuple(
        _sample_for(
            "600519.SH",
            date(2026, 1, 5) + timedelta(days=index),
            trade_suffix=f"five-beta-{index}",
            closes=("100", "101", "102", "103", "104", str(105 + index)),
        )
        for index in range(5)
    )
    return [
        _feature_with_samples("seat:alpha", samples_alpha),
        _feature_with_samples("seat:beta", samples_beta),
    ]


def test_sparse_ci_is_none_and_exactly_five_is_deterministic() -> None:
    sparse = _record(compute_seat_cooccurrence([_feature("seat:alpha"), _feature("seat:beta")]))
    assert sparse.statistics[0].count == 1
    assert sparse.statistics[0].ci_status is CIStatus.INSUFFICIENT_SAMPLES
    assert sparse.statistics[0].ci_lower is None
    assert sparse.statistics[0].ci_upper is None

    features = _five_event_features()
    result = compute_seat_cooccurrence(features)
    reordered = compute_seat_cooccurrence(
        [replace(features[1], samples=tuple(reversed(features[1].samples))), features[0]],
    )
    record = _record(result)
    assert record.support_count == 5
    assert all(metric.ci_status is CIStatus.PUBLISHED for metric in record.statistics)
    assert all(
        metric.ci_lower is not None and metric.ci_upper is not None for metric in record.statistics
    )
    assert result == reordered


def test_decimal_r7_and_bootstrap_are_exactly_repeatable() -> None:
    values = (Decimal("0"), Decimal("10"), Decimal("20"), Decimal("30"))
    assert r7_quantile(values, Decimal("0.25")) == Decimal("7.5")
    policy = CooccurrencePolicy(resamples=17, min_ci_samples=1)
    key = _record(compute_seat_cooccurrence([_feature("seat:alpha"), _feature("seat:beta")])).key
    first = compute_bootstrap_mean_ci(
        values, ("event-1", "event-2", "event-3", "event-4"), key, 1, policy
    )
    second = compute_bootstrap_mean_ci(
        values, ("event-1", "event-2", "event-3", "event-4"), key, 1, policy
    )
    assert first == second
    assert all(value is None or isinstance(value, Decimal) for value in first[:2])


def test_valid_topic_is_conditioned_but_market_event_ids_are_only_evidence() -> None:
    policy = _topic_policy()
    result = compute_seat_cooccurrence(
        [_feature("seat:alpha"), _feature("seat:beta")],
        [_topic(upstream_market_event_ids=("market-event-2", "market-event-1"))],
        policy=policy,
    )

    assert {record.key.topic_id for record in result.records} == {None, "topic-alpha"}
    conditioned = _record(result, topic_id="topic-alpha")
    assert conditioned.provenance.topic_memberships[0].upstream_market_event_ids == (
        "market-event-1",
        "market-event-2",
    )
    assert conditioned.provenance.events[0].seat_event_id.startswith("sha256:")
    assert conditioned.provenance.events[0].seat_event_id not in {
        "market-event-1",
        "market-event-2",
    }


def test_future_unknown_and_conflicting_topics_do_not_change_raw_pair() -> None:
    policy = _topic_policy()
    features = [_feature("seat:alpha"), _feature("seat:beta")]
    raw_only = _record(compute_seat_cooccurrence(features, policy=policy))
    future = _topic(
        topic_id="future-topic",
        available_time=DECISION_TIME + timedelta(seconds=1),
    )
    unknown = _topic(
        topic_id="unknown-topic",
        taxonomy_id="other-taxonomy",
        evidence_id="unknown-evidence",
    )
    conflict_a = _topic(
        topic_id="conflict-topic",
        assignment_fingerprint="sha256:a",
        evidence_id="conflict-a",
    )
    conflict_b = _topic(
        topic_id="conflict-topic",
        assignment_fingerprint="sha256:b",
        evidence_id="conflict-b",
    )
    result = compute_seat_cooccurrence(
        features,
        [future, unknown, conflict_b, conflict_a],
        policy=policy,
    )

    assert _record(result).statistics == raw_only.statistics
    assert _record(result).provenance == raw_only.provenance
    assert {record.key.topic_id for record in result.records} == {None}
    assert "future-topic" not in {diagnostic.topic_id for diagnostic in result.diagnostics}
    assert "topic_membership_not_allowed" in {diagnostic.code for diagnostic in result.diagnostics}
    assert "topic_membership_conflict" in {diagnostic.code for diagnostic in result.diagnostics}


def test_logical_available_time_and_complete_provenance_are_replayable() -> None:
    older = DECISION_TIME - timedelta(hours=2)
    later_trade = DECISION_TIME - timedelta(minutes=30)
    later_topic = DECISION_TIME - timedelta(minutes=10)
    bars = _bars_for("600519.SH", date(2026, 1, 5), available_time=older)
    first = _sample_for(
        "600519.SH",
        date(2026, 1, 5),
        trade_suffix="provenance-a",
        bars=bars,
        trade_available_time=DECISION_TIME - timedelta(hours=1),
    )
    second = _sample_for(
        "600519.SH",
        date(2026, 1, 5),
        trade_suffix="provenance-b",
        bars=bars,
        trade_available_time=later_trade,
    )
    result = compute_seat_cooccurrence(
        [
            _feature_with_samples("seat:alpha", (first,)),
            _feature_with_samples("seat:beta", (second,)),
        ],
        [_topic(available_time=later_topic)],
        policy=_topic_policy(),
    )

    raw = _record(result)
    conditioned = _record(result, topic_id="topic-alpha")
    assert raw.logical_available_time == later_trade
    assert conditioned.logical_available_time == later_topic
    assert len(raw.provenance.parent_features) == 2
    assert len(raw.provenance.seat_trade_evidence) == 2
    assert raw.provenance.shared_bars == bars
    assert conditioned.provenance.topic_memberships[0].available_time == later_topic


def test_budgets_fail_or_exclude_without_partial_results() -> None:
    first = _sample_for("600519.SH", date(2026, 1, 5), trade_suffix="budget-a")
    excluded = replace(first, included=False, trade_id="budget-excluded")
    with pytest.raises(CooccurrenceInputError, match="sample budget"):
        compute_seat_cooccurrence(
            [_feature_with_samples("seat:alpha", (first, excluded)), _feature("seat:beta")],
            policy=CooccurrencePolicy(max_input_samples=1),
        )

    with pytest.raises(CooccurrenceInputError, match="topic membership record budget"):
        compute_seat_cooccurrence(
            [_feature("seat:alpha"), _feature("seat:beta")],
            [_topic(), _topic(topic_id="topic-beta")],
            policy=_topic_policy(max_topic_membership_records=1),
        )

    second_event = _sample_for("000001.SZ", date(2026, 1, 5), trade_suffix="event-2")
    with pytest.raises(CooccurrenceInputError, match="SeatEventKey budget"):
        compute_seat_cooccurrence(
            [
                _feature_with_samples(
                    "seat:alpha",
                    (
                        _sample_for("600519.SH", date(2026, 1, 5), trade_suffix="event-1"),
                        second_event,
                    ),
                ),
                _feature("seat:beta"),
            ],
            policy=CooccurrencePolicy(max_events=1),
        )

    with pytest.raises(CooccurrenceInputError, match="edge budget"):
        compute_seat_cooccurrence(
            [_feature("seat:alpha"), _feature("seat:beta"), _feature("seat:gamma")],
            policy=CooccurrencePolicy(max_edges=2),
        )

    seat_limited = compute_seat_cooccurrence(
        [_feature("seat:alpha"), _feature("seat:beta"), _feature("seat:gamma")],
        policy=CooccurrencePolicy(max_seats_per_event=2),
    )
    assert seat_limited.records == ()
    assert "event_seat_limit_exceeded" in {
        diagnostic.code for diagnostic in seat_limited.diagnostics
    }

    topic_limited = compute_seat_cooccurrence(
        [_feature("seat:alpha"), _feature("seat:beta")],
        [_topic(), _topic(topic_id="topic-beta")],
        policy=_topic_policy(max_topics_per_event=1),
    )
    assert topic_limited.records == ()
    assert "event_topic_limit_exceeded" in {
        diagnostic.code for diagnostic in topic_limited.diagnostics
    }


def test_seat_event_id_is_versioned_and_hash_collision_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = SeatEventKey("600519.SH", date(2026, 1, 5))
    assert compute_seat_event_id(key) == compute_seat_event_id(key)
    assert SEAT_EVENT_ID_ALGORITHM_VERSION == "seat-event-id-v1"

    from seat_core.cooccurrence import engine

    def collision(_: SeatEventKey) -> str:
        return "sha256:collision"

    monkeypatch.setattr(engine, "compute_seat_event_id", collision)
    second_event = _sample_for("000001.SZ", date(2026, 1, 5), trade_suffix="collision-2")
    with pytest.raises(CooccurrenceInputError, match="multiple SeatEventKey"):
        compute_seat_cooccurrence(
            [
                _feature_with_samples(
                    "seat:alpha",
                    (
                        _sample_for("600519.SH", date(2026, 1, 5), trade_suffix="collision-1"),
                        second_event,
                    ),
                ),
                _feature("seat:beta"),
            ]
        )


def test_public_versions_are_importable_from_feature_and_top_level_facades() -> None:
    import seat_core

    assert seat_core.COOCCURRENCE_SCHEMA_VERSION == COOCCURRENCE_SCHEMA_VERSION
    assert seat_core.COOCCURRENCE_ALGORITHM_VERSION == COOCCURRENCE_ALGORITHM_VERSION
    assert seat_core.COOCCURRENCE_POLICY_VERSION == COOCCURRENCE_POLICY_VERSION
    assert seat_core.BOOTSTRAP_ALGORITHM_VERSION == BOOTSTRAP_ALGORITHM_VERSION
    assert seat_core.R7_QUANTILE_ALGORITHM_VERSION == R7_QUANTILE_ALGORITHM_VERSION
    assert seat_core.HASH_TO_INDEX_ALGORITHM_VERSION == HASH_TO_INDEX_ALGORITHM_VERSION
    assert seat_core.TOPIC_MEMBERSHIP_SCHEMA_VERSION == TOPIC_MEMBERSHIP_SCHEMA_VERSION
    assert seat_core.SEED_SERIALIZATION_VERSION == SEED_SERIALIZATION_VERSION
    assert (
        seat_core.COOCCURRENCE_FINGERPRINT_ALGORITHM_VERSION
        == COOCCURRENCE_FINGERPRINT_ALGORITHM_VERSION
    )


def test_multi_event_provenance_keeps_each_bar_path_and_latest_available_time() -> None:
    early = _bars_for(
        "600519.SH",
        date(2026, 1, 5),
        available_time=DECISION_TIME - timedelta(hours=2),
    )
    late = _bars_for(
        "600519.SH",
        date(2026, 1, 6),
        available_time=DECISION_TIME - timedelta(minutes=10),
    )
    features = [
        _feature_with_samples(
            "seat:alpha",
            (
                _sample_for(
                    "600519.SH",
                    date(2026, 1, 5),
                    trade_suffix="multi-a1",
                    bars=early,
                    trade_available_time=DECISION_TIME - timedelta(hours=2),
                ),
                _sample_for(
                    "600519.SH",
                    date(2026, 1, 6),
                    trade_suffix="multi-a2",
                    bars=late,
                    trade_available_time=DECISION_TIME - timedelta(minutes=10),
                ),
            ),
        ),
        _feature_with_samples(
            "seat:beta",
            (
                _sample_for(
                    "600519.SH",
                    date(2026, 1, 5),
                    trade_suffix="multi-b1",
                    bars=early,
                    trade_available_time=DECISION_TIME - timedelta(hours=2),
                ),
                _sample_for(
                    "600519.SH",
                    date(2026, 1, 6),
                    trade_suffix="multi-b2",
                    bars=late,
                    trade_available_time=DECISION_TIME - timedelta(minutes=10),
                ),
            ),
        ),
    ]

    record = _record(compute_seat_cooccurrence(features))

    assert len(record.provenance.event_outcomes) == 2
    assert record.provenance.event_outcomes[0].shared_bars == early
    assert record.provenance.event_outcomes[1].shared_bars == late
    assert record.provenance.shared_bars == (*early, *late)
    assert record.logical_available_time == DECISION_TIME - timedelta(minutes=10)


def test_feature_budget_stops_at_limit_plus_one_without_reading_next_feature() -> None:
    def features():
        yield _feature("seat:alpha")
        yield _feature("seat:beta")
        yield _feature("seat:gamma")
        raise RuntimeError("read limit+2 feature")

    with pytest.raises(CooccurrenceInputError, match="parent feature budget"):
        compute_seat_cooccurrence(features(), policy=CooccurrencePolicy(max_parent_features=2))


def test_input_sample_budget_stops_at_limit_plus_one_without_reading_next_feature() -> None:
    def features():
        yield _feature("seat:alpha")
        yield _feature("seat:beta")
        yield _feature("seat:gamma")
        raise RuntimeError("read limit+2 sample")

    with pytest.raises(CooccurrenceInputError, match="sample budget"):
        compute_seat_cooccurrence(features(), policy=CooccurrencePolicy(max_input_samples=2))


def test_topic_budget_stops_at_limit_plus_one_without_reading_next_topic() -> None:
    def topics():
        yield _topic(topic_id="topic-one")
        yield _topic(topic_id="topic-two")
        raise RuntimeError("read limit+2 topic")

    with pytest.raises(CooccurrenceInputError, match="topic membership record budget"):
        compute_seat_cooccurrence(
            [_feature("seat:alpha"), _feature("seat:beta")],
            topics(),
            policy=_topic_policy(max_topic_membership_records=1),
        )


def test_max_events_is_prechecked_before_reading_next_feature() -> None:
    def features():
        yield _feature("seat:alpha")
        yield _feature_with_samples(
            "seat:beta",
            (_sample_for("000001.SZ", date(2026, 1, 5), trade_suffix="new-event"),),
        )
        raise RuntimeError("read limit+2 event")

    with pytest.raises(CooccurrenceInputError, match="SeatEventKey budget"):
        compute_seat_cooccurrence(features(), policy=CooccurrencePolicy(max_events=1))


def test_max_edges_is_prechecked_before_constructing_next_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from seat_core.cooccurrence import engine

    constructed: list[tuple[str, str, str | None]] = []
    original_key = engine.CooccurrenceKey

    def spy_key(left: str, right: str, topic: str | None = None) -> CooccurrenceKey:
        constructed.append((left, right, topic))
        return original_key(left, right, topic)

    monkeypatch.setattr(engine, "CooccurrenceKey", spy_key)

    with pytest.raises(CooccurrenceInputError, match="edge budget"):
        compute_seat_cooccurrence(
            [_feature("seat:alpha"), _feature("seat:beta"), _feature("seat:gamma")],
            policy=CooccurrencePolicy(max_edges=2),
        )
    assert len(constructed) == 2


def test_event_seat_limit_is_checked_before_final_edge_budget() -> None:
    result = compute_seat_cooccurrence(
        [_feature("seat:alpha"), _feature("seat:beta"), _feature("seat:gamma")],
        policy=CooccurrencePolicy(max_seats_per_event=2, max_edges=2),
    )

    assert result.records == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["event_seat_limit_exceeded"]


def test_topics_are_indexed_by_event_key_and_do_not_cross_condition_events() -> None:
    first_key = ("600519.SH", date(2026, 1, 5))
    second_key = ("000001.SZ", date(2026, 1, 5))
    features = [
        _feature_with_samples(
            "seat:alpha",
            (
                _sample_for(*first_key, trade_suffix="indexed-a1"),
                _sample_for(*second_key, trade_suffix="indexed-a2"),
            ),
        ),
        _feature_with_samples(
            "seat:beta",
            (
                _sample_for(*first_key, trade_suffix="indexed-b1"),
                _sample_for(*second_key, trade_suffix="indexed-b2"),
            ),
        ),
    ]
    result = compute_seat_cooccurrence(
        features,
        [
            _topic(*first_key, topic_id="topic-first"),
            _topic(*second_key, topic_id="topic-second"),
        ],
        policy=_topic_policy(),
    )

    assert {
        (record.key.topic_id, record.provenance.events[0].seat_event_key.instrument_id)
        for record in result.records
        if record.key.topic_id is not None
    } == {
        ("topic-first", "600519.SH"),
        ("topic-second", "000001.SZ"),
    }


def test_bootstrap_draw_budget_fails_before_any_ci_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from seat_core.cooccurrence import engine

    def unexpected_bootstrap(*args: object, **kwargs: object) -> object:
        raise AssertionError("bootstrap must not run before budget validation")

    monkeypatch.setattr(engine, "compute_bootstrap_mean_ci", unexpected_bootstrap)
    policy = CooccurrencePolicy(
        resamples=1,
        min_ci_samples=1,
        max_bootstrap_draws=14,
    )

    with pytest.raises(CooccurrenceInputError, match="bootstrap draw budget"):
        compute_seat_cooccurrence(_five_event_features(), policy=policy)


def test_public_bootstrap_helper_checks_single_horizon_budget_before_hashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from seat_core.cooccurrence import engine

    key = _record(compute_seat_cooccurrence([_feature("seat:alpha"), _feature("seat:beta")])).key

    def unexpected_hash(*args: object, **kwargs: object) -> object:
        raise AssertionError("bootstrap hashing must not start before budget validation")

    monkeypatch.setattr(engine.hashlib, "sha256", unexpected_hash)
    policy = CooccurrencePolicy(resamples=2, min_ci_samples=1, max_bootstrap_draws=3)
    with pytest.raises(CooccurrenceInputError, match="bootstrap draw budget"):
        compute_bootstrap_mean_ci(
            (Decimal("1"), Decimal("2")),
            ("event-1", "event-2"),
            key,
            1,
            policy,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "spoof-schema"),
        ("algorithm_version", "spoof-algorithm"),
        ("event_id_algorithm_version", "spoof-event-id"),
        ("bootstrap_algorithm_version", "spoof-bootstrap"),
        ("r7_algorithm_version", "spoof-r7"),
        ("hash_to_index_algorithm_version", "spoof-hash"),
        ("fingerprint_algorithm_version", "spoof-fingerprint"),
        ("seed_serialization_version", "spoof-seed"),
        ("decimal_precision", 33),
        ("rounding", "ROUND_UP"),
    ],
)
def test_policy_version_and_precision_spoof_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        replace(CooccurrencePolicy(), **{field: value})


def test_invalid_topic_type_is_not_silently_dropped() -> None:
    from typing import cast

    with pytest.raises((TypeError, CooccurrenceInputError)):
        compute_seat_cooccurrence(
            [_feature("seat:alpha"), _feature("seat:beta")],
            cast(list[EventTopicMembership], [object()]),
        )


@pytest.mark.parametrize(
    "malformation",
    [
        "one_bar",
        "two_bars",
        "five_bars",
        "wrong_instrument",
        "wrong_returns",
        "suspended",
        "nonpositive_close",
        "missing_drawdown",
        "excluded_reason",
    ],
)
def test_malformed_included_parent_sample_fails_closed(malformation: str) -> None:
    sample = _sample_for("600519.SH", date(2024, 1, 2), trade_suffix="malformed")
    if malformation == "one_bar":
        sample = replace(
            sample,
            bars=sample.bars[:1],
            path_dates=sample.path_dates[:1],
            event_returns=(),
        )
    elif malformation == "two_bars":
        sample = replace(
            sample,
            bars=sample.bars[:2],
            path_dates=sample.path_dates[:2],
            event_returns=sample.event_returns[:1],
        )
    elif malformation == "five_bars":
        sample = replace(
            sample,
            bars=sample.bars[:5],
            path_dates=sample.path_dates[:5],
            event_returns=sample.event_returns[:4],
        )
    elif malformation == "wrong_instrument":
        sample = replace(
            sample,
            bars=(replace(sample.bars[0], instrument_id="000001.SZ"), *sample.bars[1:]),
        )
    elif malformation == "wrong_returns":
        sample = replace(sample, event_returns=(Decimal("9"), *sample.event_returns[1:]))
    elif malformation == "suspended":
        sample = replace(
            sample,
            bars=(replace(sample.bars[0], suspended=True), *sample.bars[1:]),
        )
    elif malformation == "nonpositive_close":
        sample = replace(
            sample,
            bars=(replace(sample.bars[0], close=Decimal("0")), *sample.bars[1:]),
        )
    elif malformation == "missing_drawdown":
        sample = replace(sample, max_drawdown=None)
    elif malformation == "excluded_reason":
        sample = replace(sample, exclusion_reason=ExclusionReason.MISSING_PRICE)
    else:
        raise AssertionError(f"unknown malformation: {malformation}")

    with pytest.raises(CooccurrenceInputError) as error:
        compute_seat_cooccurrence(
            (
                _feature_with_samples("seat:malformed", (sample,)),
                _feature_with_samples(
                    "seat:valid",
                    (_sample_for("600519.SH", date(2024, 1, 2), trade_suffix="valid"),),
                ),
            ),
            policy=CooccurrencePolicy(),
        )
    assert error.value.reason == "invalid_parent_sample"
