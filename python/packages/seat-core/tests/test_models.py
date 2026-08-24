from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from ashare_contracts import Alias as SectorAlias
from ashare_contracts import SeatAlias as SeatAliasDTO
from seat_core import (
    Alias,
    AliasCatalog,
    AliasType,
    Currency,
    LineageRelation,
    Performance,
    Preference,
    SeatKind,
    SeatLineage,
    SeatProfile,
    Trade,
    compute_seat_id,
    from_contract,
    parse_alias_payload,
    parse_performance_payload,
    parse_preference_payload,
    parse_seat_profile_payload,
    parse_trade_payload,
    to_contract,
)

T0 = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
T1 = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)
T2 = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)


def make_profile(
    *,
    identity_key: str = "broker:alpha-001",
    canonical_name: str | None = "Old Branch Name",
    seat_kind: SeatKind = SeatKind.BROKER_BRANCH,
    revision_id: str = "profile-rev-1",
    previous_revision_id: str | None = None,
    valid_from: datetime = T0,
    valid_to: datetime | None = None,
    lineage: tuple[SeatLineage, ...] = (),
) -> SeatProfile:
    return SeatProfile.from_identity(
        identity_key,
        canonical_name=canonical_name,
        seat_kind=seat_kind,
        valid_from=valid_from,
        valid_to=valid_to,
        available_time=T0,
        revision_id=revision_id,
        previous_revision_id=previous_revision_id,
        source="seat-master",
        source_version="2026-08",
        evidence_id="evidence-seat-1",
        lineage=lineage,
    )


def make_alias(
    *,
    alias_id: str = "alias-1",
    seat_id: str | None = None,
    name: str = "Old Branch Name",
    valid_from: datetime = T0,
    valid_to: datetime | None = None,
) -> Alias:
    return Alias(
        alias_id=alias_id,
        seat_id=seat_id or compute_seat_id("broker:alpha-001"),
        name=name,
        alias_type=AliasType.OFFICIAL,
        valid_from=valid_from,
        valid_to=valid_to,
        available_time=T0,
        source="seat-master",
        source_version="2026-08",
        evidence_id="evidence-alias-1",
        revision_id=f"{alias_id}-rev-1",
    )


def make_trade() -> Trade:
    return Trade(
        trade_id="trade-1",
        revision_id="trade-1-rev-2",
        previous_revision_id="trade-1-rev-1",
        seat_id=compute_seat_id("broker:alpha-001"),
        raw_seat_name="Old Branch Name (source spelling)",
        instrument_id="600519.SH",
        trade_date=date(2026, 8, 21),
        currency=Currency.CNY,
        buy_amount=Decimal("123.4500"),
        sell_amount=Decimal("100.0000"),
        net_amount=Decimal("23.4500"),
        source="exchange-disclosure",
        source_version="2026-08",
        raw_record_id="raw-lhb-1",
        evidence_id="evidence-trade-1",
        available_time=T1,
    )


def test_seat_id_is_derived_from_immutable_identity_not_display_name() -> None:
    old = make_profile(canonical_name="Old Branch Name")
    renamed = make_profile(
        canonical_name="New Branch Name",
        revision_id="profile-rev-2",
        previous_revision_id="profile-rev-1",
    )

    assert old.seat_id == renamed.seat_id == compute_seat_id("broker:alpha-001")
    assert old.canonical_name != renamed.canonical_name
    assert old.revision_id != renamed.revision_id


def test_seat_id_algorithm_and_identity_key_are_explicitly_canonical() -> None:
    with pytest.raises(ValueError, match="identity_key"):
        compute_seat_id("broker: alpha-001")

    with pytest.raises(ValueError, match="schema_version|algorithm"):
        replace(make_profile(), seat_id_algorithm="seat-id-v0")


def test_institution_and_unknown_seats_are_first_class_profiles() -> None:
    institution = make_profile(
        identity_key="exchange:institution-seat:001",
        canonical_name="Institution Seat",
        seat_kind=SeatKind.INSTITUTION,
    )
    unknown = make_profile(
        identity_key="source:unknown:row-001",
        canonical_name=None,
        seat_kind=SeatKind.UNKNOWN,
    )

    assert institution.seat_kind is SeatKind.INSTITUTION
    assert unknown.seat_kind is SeatKind.UNKNOWN
    assert unknown.canonical_name is None
    assert institution.seat_id != unknown.seat_id


def test_alias_validity_is_half_open_and_catalog_rejects_overlaps() -> None:
    seat_id = compute_seat_id("broker:alpha-001")
    former = make_alias(
        alias_id="alias-former",
        seat_id=seat_id,
        name="Former Name",
        valid_from=T0,
        valid_to=T1,
    )
    current = make_alias(
        alias_id="alias-current",
        seat_id=seat_id,
        name="Former Name",
        valid_from=T1,
    )

    catalog = AliasCatalog((former, current))
    assert former.is_valid_at(T0)
    assert not former.is_valid_at(T1)
    assert current.is_valid_at(T1)
    assert len(catalog.aliases) == 2

    with pytest.raises(ValueError, match="overlap"):
        AliasCatalog(
            (
                former,
                make_alias(
                    alias_id="alias-overlap",
                    seat_id=seat_id,
                    name="Former Name",
                    valid_from=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
                    valid_to=T2,
                ),
            )
        )


def test_alias_rejects_invalid_or_naive_validity() -> None:
    with pytest.raises(ValueError, match="valid_to"):
        make_alias(valid_from=T1, valid_to=T1)
    with pytest.raises(ValueError, match="timezone-aware"):
        make_alias(valid_from=datetime(2026, 8, 24, 8, 0))


def test_merge_and_split_lineage_keeps_predecessors_and_successors() -> None:
    predecessor_a = compute_seat_id("broker:alpha-001")
    predecessor_b = compute_seat_id("broker:beta-002")
    merged_id = compute_seat_id("broker:merged-003")
    merge = SeatLineage(
        lineage_id="lineage-merge-1",
        relation=LineageRelation.MERGE,
        predecessor_seat_ids=(predecessor_a, predecessor_b),
        successor_seat_ids=(merged_id,),
        effective_at=T1,
        source="seat-master",
        source_version="2026-08",
        evidence_id="evidence-merge-1",
        revision_id="lineage-merge-1-rev-1",
    )
    merged = make_profile(
        identity_key="broker:merged-003",
        canonical_name="Merged Branch",
        lineage=(merge,),
    )

    split_a = compute_seat_id("broker:split-a-004")
    split_b = compute_seat_id("broker:split-b-005")
    split = SeatLineage(
        lineage_id="lineage-split-1",
        relation=LineageRelation.SPLIT,
        predecessor_seat_ids=(merged_id,),
        successor_seat_ids=(split_a, split_b),
        effective_at=T2,
        source="seat-master",
        source_version="2026-08",
        evidence_id="evidence-split-1",
        revision_id="lineage-split-1-rev-1",
    )
    split_profile = make_profile(
        identity_key="broker:merged-003",
        canonical_name="Pre-split Branch",
        lineage=(split,),
    )

    assert merged.lineage[0].predecessor_seat_ids == (predecessor_a, predecessor_b)
    assert merged.lineage[0].successor_seat_ids == (merged_id,)
    assert split_profile.seat_id == merged_id
    assert split_profile.lineage[0].successor_seat_ids == (split_a, split_b)


def test_lineage_rejects_overlap_self_loop_and_wrong_cardinality() -> None:
    seat_a = compute_seat_id("broker:lineage-a-001")
    seat_b = compute_seat_id("broker:lineage-b-002")
    seat_c = compute_seat_id("broker:lineage-c-003")

    with pytest.raises(ValueError, match="distinct|self|overlap"):
        SeatLineage(
            lineage_id="lineage-self-loop",
            relation=LineageRelation.MERGE,
            predecessor_seat_ids=(seat_a, seat_b),
            successor_seat_ids=(seat_a,),
            effective_at=T0,
            source="seat-master",
            source_version="2026-08",
            evidence_id="evidence-self-loop",
            revision_id="lineage-self-loop-rev-1",
        )

    with pytest.raises(ValueError, match="at least two|predecessor"):
        SeatLineage(
            lineage_id="lineage-merge-one",
            relation=LineageRelation.MERGE,
            predecessor_seat_ids=(seat_a,),
            successor_seat_ids=(seat_b,),
            effective_at=T0,
            source="seat-master",
            source_version="2026-08",
            evidence_id="evidence-merge-one",
            revision_id="lineage-merge-one-rev-1",
        )

    with pytest.raises(ValueError, match="at least two|successor"):
        SeatLineage(
            lineage_id="lineage-split-one",
            relation=LineageRelation.SPLIT,
            predecessor_seat_ids=(seat_a,),
            successor_seat_ids=(seat_c,),
            effective_at=T0,
            source="seat-master",
            source_version="2026-08",
            evidence_id="evidence-split-one",
            revision_id="lineage-split-one-rev-1",
        )


def test_profile_rejects_duplicate_lineage_out_of_range_and_wrong_side() -> None:
    current = compute_seat_id("broker:lineage-current-004")
    other_a = compute_seat_id("broker:lineage-other-a-005")
    other_b = compute_seat_id("broker:lineage-other-b-006")
    merge = SeatLineage(
        lineage_id="lineage-profile-merge",
        relation=LineageRelation.MERGE,
        predecessor_seat_ids=(other_a, other_b),
        successor_seat_ids=(current,),
        effective_at=T1,
        source="seat-master",
        source_version="2026-08",
        evidence_id="evidence-profile-merge",
        revision_id="lineage-profile-merge-rev-1",
    )

    with pytest.raises(ValueError, match="duplicate"):
        make_profile(
            identity_key="broker:lineage-current-004",
            lineage=(merge, merge),
        )
    with pytest.raises(ValueError, match="valid|effective"):
        make_profile(
            identity_key="broker:lineage-current-004",
            valid_from=T0,
            valid_to=T1,
            lineage=(merge,),
        )

    split = SeatLineage(
        lineage_id="lineage-profile-split",
        relation=LineageRelation.SPLIT,
        predecessor_seat_ids=(current,),
        successor_seat_ids=(other_a, other_b),
        effective_at=T1,
        source="seat-master",
        source_version="2026-08",
        evidence_id="evidence-profile-split",
        revision_id="lineage-profile-split-rev-1",
    )
    with pytest.raises(ValueError, match="predecessor|side"):
        make_profile(
            identity_key="broker:lineage-other-a-005",
            lineage=(split,),
        )


def test_trade_preserves_public_fact_provenance_and_exact_amounts() -> None:
    trade = make_trade()
    dto = to_contract(trade)
    restored = from_contract(dto)

    assert dto.raw_seat_name == "Old Branch Name (source spelling)"
    assert dto.buy_amount == "123.4500"
    assert dto.sell_amount == "100.0000"
    assert dto.net_amount == "23.4500"
    assert restored == trade


def test_generated_alias_exports_preserve_sector_api_and_add_seat_alias() -> None:
    assert SectorAlias.__module__ == "ashare_contracts.sector_sector"
    assert SeatAliasDTO.__module__ == "ashare_contracts.seat_alias"
    assert type(to_contract(make_alias())) is SeatAliasDTO


def test_trade_rejects_float_amounts_and_inconsistent_net_amount() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        replace(make_trade(), buy_amount=123.45)  # pyright: ignore[reportArgumentType]
    with pytest.raises(ValueError, match="net_amount"):
        replace(make_trade(), net_amount=Decimal("24.4500"))


def test_payload_revision_chain_is_checked_for_all_five_models() -> None:
    profile_payload = to_contract(make_profile()).model_dump(by_alias=True, mode="python")
    profile_payload["seatIdAlgorithm"] = "seat-id-v1"
    profile_payload["previousRevisionId"] = profile_payload["revisionId"]
    with pytest.raises(ValueError, match="previous_revision_id"):
        parse_seat_profile_payload(profile_payload)

    alias_payload = to_contract(make_alias()).model_dump(by_alias=True, mode="python")
    alias_payload["previousRevisionId"] = alias_payload["revisionId"]
    with pytest.raises(ValueError, match="previous_revision_id"):
        parse_alias_payload(alias_payload)

    performance_payload = {
        "schemaVersion": "seat-performance-v1",
        "performanceId": "performance-payload-1",
        "seatId": compute_seat_id("broker:alpha-001"),
        "windowStart": date(2026, 8, 1),
        "windowEnd": date(2026, 8, 21),
        "calculationVersion": "seat-performance-v1",
        "sampleCount": 1,
        "tPlus1Return": "0.0100",
        "tPlus3Return": None,
        "tPlus5Return": None,
        "winRate": "1.0000",
        "maxDrawdown": "0.0000",
        "source": "feature-job",
        "sourceVersion": "2026-08",
        "evidenceId": "evidence-performance-payload-1",
        "revisionId": "performance-payload-1-rev-1",
        "previousRevisionId": "performance-payload-1-rev-1",
        "availableTime": T2,
    }
    with pytest.raises(ValueError, match="previous_revision_id"):
        parse_performance_payload(performance_payload)

    preference_payload = {
        "schemaVersion": "seat-preference-v1",
        "preferenceId": "preference-payload-1",
        "seatId": compute_seat_id("broker:alpha-001"),
        "validFrom": T0,
        "validTo": None,
        "preferenceVersion": "seat-preference-v1",
        "styleTags": ["momentum"],
        "confidenceBps": 7000,
        "source": "feature-job",
        "sourceVersion": "2026-08",
        "evidenceId": "evidence-preference-payload-1",
        "revisionId": "preference-payload-1-rev-1",
        "previousRevisionId": "preference-payload-1-rev-1",
        "availableTime": T2,
    }
    with pytest.raises(ValueError, match="previous_revision_id"):
        parse_preference_payload(preference_payload)

    trade_payload = to_contract(make_trade()).model_dump(by_alias=True, mode="python")
    trade_payload["currency"] = "CNY"
    trade_payload["previousRevisionId"] = trade_payload["revisionId"]
    with pytest.raises(ValueError, match="previous_revision_id"):
        parse_trade_payload(trade_payload)


def test_trade_payload_requires_cny_and_exact_decimal_strings() -> None:
    payload = to_contract(make_trade()).model_dump(by_alias=True, mode="python")
    payload["currency"] = "CNY"
    payload["buyAmount"] = "999999999999999999999999999999.1200"
    payload["sellAmount"] = "0.0001"
    payload["netAmount"] = "999999999999999999999999999999.1199"
    assert parse_trade_payload(payload).buy_amount == Decimal("999999999999999999999999999999.1200")

    for field, value in (("buyAmount", -1.0), ("sellAmount", -1), ("buyAmount", 1.0)):
        invalid = dict(payload)
        invalid[field] = value
        with pytest.raises(ValueError):
            parse_trade_payload(invalid)

    contradictory = dict(payload)
    contradictory["netAmount"] = "999999999999999999999999999999.1200"
    with pytest.raises(ValueError, match="net_amount"):
        parse_trade_payload(contradictory)


def test_profile_payload_rejects_forged_identity_and_invalid_lineage_graphs() -> None:
    forged = to_contract(make_profile()).model_dump(by_alias=True, mode="python")
    forged["seatId"] = "seat-" + "a" * 64
    with pytest.raises(ValueError, match="seat_id"):
        parse_seat_profile_payload(forged)

    valid_profile = to_contract(make_profile(valid_to=T2)).model_dump(by_alias=True, mode="python")
    valid_seat_id = valid_profile["seatId"]
    lineage = {
        "lineageId": "lineage-payload-1",
        "relation": "MERGE",
        "predecessorSeatIds": [
            compute_seat_id("broker:predecessor-a"),
            compute_seat_id("broker:predecessor-b"),
        ],
        "successorSeatIds": [valid_seat_id],
        "effectiveAt": T0,
        "source": "seat-master",
        "sourceVersion": "2026-08",
        "evidenceId": "evidence-lineage-payload-1",
        "revisionId": "lineage-payload-1-rev-1",
    }

    malformed_member = dict(valid_profile)
    malformed_member["lineage"] = [
        {
            **lineage,
            "predecessorSeatIds": ["bad", compute_seat_id("broker:b")],
        }
    ]
    with pytest.raises(ValueError):
        parse_seat_profile_payload(malformed_member)

    invalid_cardinality = dict(valid_profile)
    invalid_cardinality["lineage"] = [
        {**lineage, "predecessorSeatIds": [compute_seat_id("broker:only-one")]}
    ]
    with pytest.raises(ValueError, match="MERGE"):
        parse_seat_profile_payload(invalid_cardinality)

    out_of_range = dict(valid_profile)
    out_of_range["lineage"] = [{**lineage, "effectiveAt": T2}]
    with pytest.raises(ValueError, match="effective_at"):
        parse_seat_profile_payload(out_of_range)


def test_all_models_require_timezone_aware_instants_and_explicit_versions() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(make_trade(), available_time=datetime(2026, 8, 24, 8, 0))

    performance = Performance(
        performance_id="performance-1",
        seat_id=compute_seat_id("broker:alpha-001"),
        window_start=date(2026, 8, 1),
        window_end=date(2026, 8, 21),
        calculation_version="seat-performance-v1",
        sample_count=12,
        t_plus_1_return=Decimal("0.0125"),
        t_plus_3_return=None,
        t_plus_5_return=Decimal("0.0350"),
        win_rate=Decimal("0.5833"),
        max_drawdown=Decimal("-0.0800"),
        source="feature-job",
        source_version="2026-08",
        evidence_id="evidence-performance-1",
        revision_id="performance-1-rev-1",
        available_time=T2,
    )
    preference = Preference(
        preference_id="preference-1",
        seat_id=performance.seat_id,
        valid_from=T0,
        valid_to=None,
        preference_version="seat-preference-v1",
        style_tags=("momentum", "small-cap"),
        confidence_bps=7200,
        source="feature-job",
        source_version="2026-08",
        evidence_id="evidence-preference-1",
        revision_id="preference-1-rev-1",
        available_time=T2,
    )

    assert performance.schema_version == "seat-performance-v1"
    assert preference.schema_version == "seat-preference-v1"


def test_all_public_models_round_trip_through_generated_python_contracts() -> None:
    performance = Performance(
        performance_id="performance-roundtrip",
        seat_id=compute_seat_id("broker:alpha-001"),
        window_start=date(2026, 8, 1),
        window_end=date(2026, 8, 21),
        calculation_version="seat-performance-v1",
        sample_count=12,
        t_plus_1_return=Decimal("0.0125"),
        t_plus_3_return=None,
        t_plus_5_return=Decimal("0.0350"),
        win_rate=Decimal("0.5833"),
        max_drawdown=Decimal("-0.0800"),
        source="feature-job",
        source_version="2026-08",
        evidence_id="evidence-performance-roundtrip",
        revision_id="performance-roundtrip-rev-1",
        available_time=T2,
    )
    preference = Preference(
        preference_id="preference-roundtrip",
        seat_id=performance.seat_id,
        valid_from=T0,
        valid_to=None,
        preference_version="seat-preference-v1",
        style_tags=("momentum", "small-cap"),
        confidence_bps=7200,
        source="feature-job",
        source_version="2026-08",
        evidence_id="evidence-preference-roundtrip",
        revision_id="preference-roundtrip-rev-1",
        available_time=T2,
    )
    alias = make_alias()
    models = (make_profile(), alias, make_trade(), performance, preference)

    for model in models:
        assert from_contract(to_contract(model)) == model
