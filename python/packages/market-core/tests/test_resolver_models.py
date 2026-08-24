"""Resolver model and point-in-time data-layer tests (P3-N04).

Pure data-layer tests: alias/universe/override filtering, policy versioning
and resolution result invariants. Run with ``--no-cov``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from ashare_contracts import (
    Board_1 as Board,
)
from ashare_contracts import (
    Currency_1 as Currency,
)
from ashare_contracts import (
    Exchange_7 as Exchange,
)
from ashare_contracts import (
    Instrument,
    TradingStatus,
    Type,
)
from event_core.entities import (
    ENTITY_EXTRACTION_VERSION,
    EntityMention,
    EntityType,
    ExtractionPolicy,
    ExtractionReason,
    build_evidence,
    compute_mention_id,
    normalize_surface,
)
from market_core.resolver.alias import AliasEntry, AliasTable, AliasType
from market_core.resolver.models import (
    RESOLVER_VERSION,
    ResolutionReason,
    ResolutionStatus,
    ResolverPolicy,
    ResolverPolicyVersionError,
    SecurityResolution,
)
from market_core.resolver.override import ManualOverride, OverrideScopeType
from market_core.resolver.universe import InstrumentSnapshot, InstrumentUniverse

T0 = datetime(2026, 8, 24, 8, 0, 0, tzinfo=UTC)
T_PAST = datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)
T_FUTURE = datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC)


def make_instrument(
    code: str,
    exchange: str,
    board: str,
    type_: str,
    name: str,
    *,
    list_date: date | None = None,
    delist_date: date | None = None,
) -> Instrument:
    return Instrument(
        unifiedCode=f"{code}.{exchange}",
        code=code,
        exchange=Exchange(exchange),
        board=Board(board),
        type=Type(type_),
        name=name,
        tradingStatus=TradingStatus("LISTED"),
        currency=Currency("CNY"),
        listDate=list_date,
        delistDate=delist_date,
    )


def snap(instrument: Instrument, available_time: datetime = T_PAST) -> InstrumentSnapshot:
    return InstrumentSnapshot(
        instrument=instrument,
        available_time=available_time,
        source="test-source",
        version="v1",
    )


def make_mention(
    surface: str,
    *,
    entity_type: EntityType = EntityType.COMPANY,
    confidence_bps: int = 9000,
    content_id: str = "content-1",
    eligibility_threshold_bps: int = 6000,
) -> EntityMention:
    policy = ExtractionPolicy(min_confidence_bps=eligibility_threshold_bps)

    mention_id = compute_mention_id(
        content_id=content_id,
        entity_type=entity_type,
        start_offset=0,
        end_offset=len(surface),
        surface=surface,
        policy=policy,
    )
    return EntityMention(
        mention_id=mention_id,
        content_id=content_id,
        entity_type=entity_type,
        surface=surface,
        normalized_surface=normalize_surface(surface),
        start_offset=0,
        end_offset=len(surface),
        extractor_version=ENTITY_EXTRACTION_VERSION,
        policy_fingerprint=policy.fingerprint(),
        confidence_bps=confidence_bps,
        eligibility_threshold_bps=eligibility_threshold_bps,
        reason=ExtractionReason.LEXICON_EXACT,
        evidence=build_evidence(content_id, 0, len(surface), surface),
    )


def base_universe() -> InstrumentUniverse:
    instruments = [
        make_instrument("600519", "SH", "MAIN", "STOCK", "贵州茅台", list_date=date(2001, 8, 27)),
        make_instrument("000001", "SZ", "MAIN", "STOCK", "平安银行", list_date=date(1991, 4, 3)),
        make_instrument("601318", "SH", "MAIN", "STOCK", "中国平安", list_date=date(2007, 3, 1)),
        make_instrument("510300", "SH", "MAIN", "ETF", "沪深300ETF", list_date=date(2012, 5, 28)),
        make_instrument("518880", "SH", "MAIN", "ETF", "黄金ETF", list_date=date(2013, 7, 29)),
    ]
    return InstrumentUniverse(snap(i) for i in instruments)


def base_aliases() -> AliasTable:
    return AliasTable(
        [
            AliasEntry(
                alias_id="a-short-mt",
                alias="茅台",
                alias_type=AliasType.SHORT_NAME,
                target="600519.SH",
                effective_from=T_PAST,
                effective_to=None,
                available_time=T_PAST,
                source="test-source",
                version="v1",
                reliability=9500,
            ),
            AliasEntry(
                alias_id="a-former-mt",
                alias="贵州茅台酒厂",
                alias_type=AliasType.FORMER_NAME,
                target="600519.SH",
                effective_from=T_PAST,
                effective_to=datetime(2021, 12, 31, 23, 59, 59, tzinfo=UTC),
                available_time=T_PAST,
                source="test-source",
                version="v1",
                reliability=9000,
            ),
            AliasEntry(
                alias_id="a-pingan-bank",
                alias="平安",
                alias_type=AliasType.EQUIVALENT_NAME,
                target="000001.SZ",
                effective_from=T_PAST,
                effective_to=None,
                available_time=T_PAST,
                source="test-source",
                version="v1",
                reliability=8500,
            ),
            AliasEntry(
                alias_id="a-pingan-group",
                alias="平安",
                alias_type=AliasType.EQUIVALENT_NAME,
                target="601318.SH",
                effective_from=T_PAST,
                effective_to=None,
                available_time=T_PAST,
                source="test-source",
                version="v1",
                reliability=8500,
            ),
        ]
    )


class TestResolverPolicy:
    def test_default_fingerprint_stable(self) -> None:
        assert ResolverPolicy().fingerprint() == ResolverPolicy().fingerprint()
        assert len(ResolverPolicy().fingerprint()) == 64

    def test_fingerprint_changes_with_any_parameter(self) -> None:
        base = ResolverPolicy().fingerprint()
        assert ResolverPolicy(resolved_threshold_bps=7000).fingerprint() != base
        assert ResolverPolicy(ambiguity_margin_bps=500).fingerprint() != base
        assert ResolverPolicy(short_name_score_bps=8200).fingerprint() != base
        assert ResolverPolicy(override_enabled=False).fingerprint() != base

    def test_rejects_unsupported_version(self) -> None:
        with pytest.raises(ResolverPolicyVersionError):
            ResolverPolicy(version="latest")
        with pytest.raises(ResolverPolicyVersionError):
            ResolverPolicy(version="resolver-v2")
        with pytest.raises(ResolverPolicyVersionError):
            ResolverPolicy(version="")

    def test_rejects_non_int_bps(self) -> None:
        with pytest.raises(ValueError):
            ResolverPolicy(resolved_threshold_bps=8000.5)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            ResolverPolicy(ambiguity_margin_bps=-1)
        with pytest.raises(ValueError):
            ResolverPolicy(exact_symbol_score_bps=10001)


class TestAliasTable:
    def test_lookup_requires_aware_datetimes(self) -> None:
        with pytest.raises(ValueError):
            base_aliases().lookup(
                "茅台",
                decision_time=datetime(2026, 8, 24, 8, 0),
                reference_time=T0,
            )

    def test_later_known_alias_not_visible(self) -> None:
        late = AliasEntry(
            alias_id="a-late",
            alias="新酒名",
            alias_type=AliasType.SHORT_NAME,
            target="600519.SH",
            effective_from=T_PAST,
            effective_to=None,
            available_time=T_FUTURE,
            source="test-source",
            version="v1",
            reliability=9000,
        )
        table = AliasTable([late])
        assert table.lookup("新酒名", decision_time=T0, reference_time=T0) == ()

    def test_former_name_expired_by_reference(self) -> None:
        table = base_aliases()
        later = datetime(2022, 6, 1, 0, 0, 0, tzinfo=UTC)
        assert table.lookup("贵州茅台酒厂", decision_time=later, reference_time=later) == ()

    def test_former_name_valid_inside_window(self) -> None:
        table = base_aliases()
        at = datetime(2020, 6, 1, 0, 0, 0, tzinfo=UTC)
        hits = table.lookup("贵州茅台酒厂", decision_time=at, reference_time=at)
        assert [h.target for h in hits] == ["600519.SH"]
        assert hits[0].alias_type is AliasType.FORMER_NAME

    def test_same_name_multiple_targets(self) -> None:
        hits = base_aliases().lookup("平安", decision_time=T0, reference_time=T0)
        assert {h.target for h in hits} == {"000001.SZ", "601318.SH"}

    def test_alias_lookup_normalizes_ascii_case_and_whitespace(self) -> None:
        entry = AliasEntry(
            alias_id="a-abc",
            alias="  ABC  ",
            alias_type=AliasType.SHORT_NAME,
            target="600519.SH",
            effective_from=T_PAST,
            effective_to=None,
            available_time=T_PAST,
            source="test-source",
            version="v1",
            reliability=9000,
        )
        table = AliasTable([entry])
        hits = table.lookup(" abc ", decision_time=T0, reference_time=T0)
        assert [hit.alias_id for hit in hits] == ["a-abc"]

    def test_conflicting_duplicate_alias_id_is_rejected_in_either_order(self) -> None:
        first = AliasEntry(
            alias_id="duplicate",
            alias="茅台",
            alias_type=AliasType.SHORT_NAME,
            target="600519.SH",
            effective_from=T_PAST,
            effective_to=None,
            available_time=T_PAST,
            source="source-a",
            version="v1",
            reliability=9000,
        )
        second = AliasEntry(
            alias_id="duplicate",
            alias="茅台",
            alias_type=AliasType.SHORT_NAME,
            target="600519.SH",
            effective_from=T_PAST,
            effective_to=None,
            available_time=T_PAST,
            source="source-b",
            version="v2",
            reliability=9000,
        )
        for entries in ((first, second), (second, first)):
            with pytest.raises(ValueError, match="conflicting duplicate alias_id"):
                AliasTable(entries)

    def test_exact_duplicate_alias_is_deduplicated(self) -> None:
        entry = AliasEntry(
            alias_id="duplicate",
            alias="茅台",
            alias_type=AliasType.SHORT_NAME,
            target="600519.SH",
            effective_from=T_PAST,
            effective_to=None,
            available_time=T_PAST,
            source="source-a",
            version="v1",
            reliability=9000,
        )
        table = AliasTable((entry, entry))
        assert table.entries == (entry,)
        assert table.lookup("茅台", decision_time=T0, reference_time=T0) == (entry,)

    def test_rejects_naive_times_in_entry(self) -> None:
        with pytest.raises(ValueError):
            AliasEntry(
                alias_id="x",
                alias="x",
                alias_type=AliasType.SHORT_NAME,
                target="600519.SH",
                effective_from=datetime(2020, 1, 1),
                effective_to=None,
                available_time=T_PAST,
                source="s",
                version="v1",
                reliability=9000,
            )


class TestInstrumentUniverse:
    def test_future_snapshot_not_visible(self) -> None:
        future = snap(
            make_instrument("600999", "SH", "MAIN", "STOCK", "未来公司"),
            available_time=T_FUTURE,
        )
        uni = InstrumentUniverse([future])
        assert uni.lookup("600999.SH", decision_time=T0) is None

    def test_lookup_visible_snapshot(self) -> None:
        uni = base_universe()
        snap_ = uni.lookup("600519.SH", decision_time=T0)
        assert snap_ is not None
        assert snap_.instrument.name == "贵州茅台"

    def test_as_of_filters_future(self) -> None:
        uni = InstrumentUniverse(
            [
                snap(make_instrument("600999", "SH", "MAIN", "STOCK", "未来公司"), T_FUTURE),
                snap(make_instrument("600519", "SH", "MAIN", "STOCK", "贵州茅台"), T_PAST),
            ]
        )
        ids = {s.instrument_id for s in uni.as_of(T0)}
        assert ids == {"600519.SH"}

    def test_canonical_symbol_uses_unified_code(self) -> None:
        uni = base_universe()
        snap_ = uni.lookup("600519.SH", decision_time=T0)
        assert snap_ is not None
        assert snap_.canonical_symbol == "600519.SH"

    def test_old_and_future_snapshot_historical_replay(self) -> None:
        # Same instrument_id has an old snapshot (2020) and a future snapshot
        # (2027). At decision 2026 the old snapshot must be visible; the
        # future snapshot must not shadow it.
        old = snap(
            make_instrument("600519", "SH", "MAIN", "STOCK", "贵州茅台旧版"),
            available_time=datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        fut = snap(
            make_instrument("600519", "SH", "MAIN", "STOCK", "贵州茅台新版"),
            available_time=datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        uni = InstrumentUniverse([fut, old])
        seen = uni.lookup("600519.SH", decision_time=T0)
        assert seen is not None
        assert seen.instrument.name == "贵州茅台旧版"
        # At 2028 the future snapshot becomes visible and wins.
        later = uni.lookup(
            "600519.SH",
            decision_time=datetime(2028, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        assert later is not None
        assert later.instrument.name == "贵州茅台新版"

    def test_as_of_returns_one_version_per_id(self) -> None:
        old = snap(
            make_instrument("600519", "SH", "MAIN", "STOCK", "贵州茅台旧版"),
            available_time=datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        newer = snap(
            make_instrument("600519", "SH", "MAIN", "STOCK", "贵州茅台新版"),
            available_time=datetime(2023, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        uni = InstrumentUniverse(
            [
                old,
                newer,
                snap(make_instrument("000001", "SZ", "MAIN", "STOCK", "平安银行"), T_PAST),
            ]
        )
        ids = {s.instrument_id for s in uni.as_of(T0)}
        assert ids == {"600519.SH", "000001.SZ"}
        snapshots = {s.instrument_id: s for s in uni.as_of(T0)}
        assert snapshots["600519.SH"].instrument.name == "贵州茅台新版"

    def test_same_snapshot_identity_conflict_rejected_in_either_order(self) -> None:
        v1 = snap(
            make_instrument("600519", "SH", "MAIN", "STOCK", "茅台v1"),
            available_time=T_PAST,
        )
        v2 = snap(
            make_instrument("600519", "SH", "MAIN", "STOCK", "茅台v2"),
            available_time=T_PAST,
        )
        for snapshots in ((v1, v2), (v2, v1)):
            with pytest.raises(ValueError):
                InstrumentUniverse(snapshots)

    def test_exact_duplicate_snapshot_is_deduplicated(self) -> None:
        snapshot = snap(
            make_instrument("600519", "SH", "MAIN", "STOCK", "茅台"),
            available_time=T_PAST,
        )
        universe = InstrumentUniverse([snapshot, snapshot])
        assert len(universe.snapshots) == 1


class TestManualOverrideModel:
    def test_make_valid_override(self) -> None:
        ov = ManualOverride(
            override_id="ov-1",
            scope_type=OverrideScopeType.MENTION,
            scope_value="mention-abc",
            target="600519.SH",
            reason="manual audit",
            reviewer="analyst-1",
            created_time=T_PAST,
            available_time=T_PAST,
            effective_from=T_PAST,
            effective_to=None,
            version="v1",
            evidence_reference="ticket-42",
        )
        assert ov.matches_mention(mention_id="mention-abc", content_id="c", surface="贵州茅台")
        assert not ov.matches_mention(
            mention_id="mention-other", content_id="c", surface="贵州茅台"
        )

    def test_future_or_expired_override_not_effective(self) -> None:
        future = ManualOverride(
            override_id="ov-f",
            scope_type=OverrideScopeType.MENTION,
            scope_value="m",
            target="600519.SH",
            reason="r",
            reviewer="a",
            created_time=T_PAST,
            available_time=T_FUTURE,
            effective_from=T_PAST,
            effective_to=None,
            version="v1",
            evidence_reference="t",
        )
        assert not future.visible_at(T0)

        expired = ManualOverride(
            override_id="ov-e",
            scope_type=OverrideScopeType.MENTION,
            scope_value="m",
            target="600519.SH",
            reason="r",
            reviewer="a",
            created_time=T_PAST,
            available_time=T_PAST,
            effective_from=T_PAST,
            effective_to=datetime(2021, 1, 1, 0, 0, 0, tzinfo=UTC),
            version="v1",
            evidence_reference="t",
        )
        assert not expired.effective_at(T0)

    def test_rejects_naive_times(self) -> None:
        with pytest.raises(ValueError):
            ManualOverride(
                override_id="ov",
                scope_type=OverrideScopeType.MENTION,
                scope_value="m",
                target="600519.SH",
                reason="r",
                reviewer="a",
                created_time=datetime(2020, 1, 1),
                available_time=T_PAST,
                effective_from=T_PAST,
                effective_to=None,
                version="v1",
                evidence_reference="t",
            )

    def test_rejects_created_after_available(self) -> None:
        # A manual override whose creation time is after its availability time
        # is a self-contradictory timeline and must be rejected outright.
        with pytest.raises(ValueError):
            ManualOverride(
                override_id="ov",
                scope_type=OverrideScopeType.MENTION,
                scope_value="m",
                target="600519.SH",
                reason="r",
                reviewer="a",
                created_time=T_FUTURE,
                available_time=T_PAST,
                effective_from=T_PAST,
                effective_to=None,
                version="v1",
                evidence_reference="t",
            )

    def test_created_equal_available_accepted(self) -> None:
        ov = ManualOverride(
            override_id="ov",
            scope_type=OverrideScopeType.MENTION,
            scope_value="m",
            target="600519.SH",
            reason="r",
            reviewer="a",
            created_time=T_PAST,
            available_time=T_PAST,
            effective_from=T_PAST,
            effective_to=None,
            version="v1",
            evidence_reference="t",
        )
        assert ov.created_time <= ov.available_time


class TestSecurityResolutionModel:
    def test_resolved_requires_target_among_candidates(self) -> None:
        from market_core.resolver.models import ResolutionCandidate

        cand = ResolutionCandidate(
            instrument_id="600519.SH",
            canonical_symbol="600519.SH",
            name="贵州茅台",
            score_bps=9000,
            reason=ResolutionReason.FULL_NAME,
            instrument_version="v1",
            instrument_source="test-source",
            instrument_available_time=T_PAST,
        )
        with pytest.raises(ValueError):
            SecurityResolution(
                mention_id="m1",
                status=ResolutionStatus.RESOLVED,
                candidates=(cand,),
                resolver_version=RESOLVER_VERSION,
                policy_fingerprint=ResolverPolicy().fingerprint(),
                decision_time=T0,
                reference_time=T0,
                reason=ResolutionReason.FULL_NAME,
                resolved_instrument_id="000001.SZ",
                resolved_symbol="000001.SZ",
            )

    def test_ambiguous_must_not_expose_target(self) -> None:
        from market_core.resolver.models import ResolutionCandidate

        cand = ResolutionCandidate(
            instrument_id="000001.SZ",
            canonical_symbol="000001.SZ",
            name="平安银行",
            score_bps=8500,
            reason=ResolutionReason.SHORT_NAME,
            instrument_version="v1",
            instrument_source="test-source",
            instrument_available_time=T_PAST,
        )
        with pytest.raises(ValueError):
            SecurityResolution(
                mention_id="m1",
                status=ResolutionStatus.AMBIGUOUS,
                candidates=(cand,),
                resolver_version=RESOLVER_VERSION,
                policy_fingerprint=ResolverPolicy().fingerprint(),
                decision_time=T0,
                reference_time=T0,
                reason=ResolutionReason.AMBIGUOUS_TIE,
                resolved_instrument_id="000001.SZ",
                resolved_symbol="000001.SZ",
            )

    def test_rejects_naive_times(self) -> None:
        with pytest.raises(ValueError):
            SecurityResolution(
                mention_id="m1",
                status=ResolutionStatus.UNRESOLVED,
                candidates=(),
                resolver_version=RESOLVER_VERSION,
                policy_fingerprint=ResolverPolicy().fingerprint(),
                decision_time=datetime(2026, 8, 24, 8, 0),
                reference_time=T0,
                reason=ResolutionReason.NO_MATCH,
            )

    def test_rejects_unsupported_resolver_version(self) -> None:
        with pytest.raises(ResolverPolicyVersionError):
            SecurityResolution(
                mention_id="m1",
                status=ResolutionStatus.UNRESOLVED,
                candidates=(),
                resolver_version="resolver-v2",
                policy_fingerprint="x" * 64,
                decision_time=T0,
                reference_time=T0,
                reason=ResolutionReason.NO_MATCH,
            )
