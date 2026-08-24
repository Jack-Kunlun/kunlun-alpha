"""Resolver behaviour tests (P3-N04): full/short/former names, exact symbol,
ambiguity, multi-security, manual override and point-in-time. Run with
``--no-cov``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timezone

import pytest
from event_core.entities.models import EntityMention, EntityType
from market_core.resolver import (
    AliasEntry,
    AliasTable,
    AliasType,
    ManualOverride,
    OverrideScopeType,
    ResolutionReason,
    ResolutionStatus,
    ResolverPolicy,
    SecurityResolution,
    resolve_mentions,
    resolve_security,
)
from market_core.resolver.universe import InstrumentUniverse
from test_resolver_models import (
    T0,
    T_PAST,
    base_aliases,
    base_universe,
    make_instrument,
    make_mention,
    snap,
)

T_2023 = datetime(2023, 6, 1, 0, 0, 0, tzinfo=UTC)
T_2022 = datetime(2022, 6, 1, 0, 0, 0, tzinfo=UTC)


def resolve(
    mention: EntityMention,
    *,
    universe: InstrumentUniverse | None = None,
    aliases: AliasTable | None = None,
    decision_time: datetime = T0,
    reference_time: datetime = T0,
    policy: ResolverPolicy | None = None,
    override: ManualOverride | None = None,
    symbol_hint: str | None = None,
) -> SecurityResolution:
    return resolve_security(
        mention,
        universe=universe or base_universe(),
        aliases=aliases or base_aliases(),
        decision_time=decision_time,
        reference_time=reference_time,
        policy=policy,
        override=override,
        symbol_hint=symbol_hint,
    )


def make_override(
    mention: EntityMention,
    *,
    override_id: str,
    target: str,
    scope_type: OverrideScopeType = OverrideScopeType.MENTION,
    scope_value: str | None = None,
    reason: str = "audit correction",
) -> ManualOverride:
    return ManualOverride(
        override_id=override_id,
        scope_type=scope_type,
        scope_value=scope_value or mention.mention_id,
        target=target,
        reason=reason,
        reviewer="analyst-1",
        created_time=T_PAST,
        available_time=T_PAST,
        effective_from=T_PAST,
        effective_to=None,
        version="v1",
        evidence_reference="ticket-1",
    )


class TestExactSymbol:
    def test_security_mention_resolves_canonical_symbol(self) -> None:
        mention = make_mention("600519.SH", entity_type=EntityType.SECURITY)
        result = resolve(mention)
        assert result.status is ResolutionStatus.RESOLVED
        assert result.reason is ResolutionReason.EXACT_SYMBOL
        assert result.resolved_instrument_id == "600519.SH"
        assert result.resolved_symbol == "600519.SH"
        assert result.candidates[0].score_bps == 10000
        assert result.candidates[0].canonical_symbol == "600519.SH"

    def test_unknown_symbol_unresolved(self) -> None:
        mention = make_mention("999999.SH", entity_type=EntityType.SECURITY)
        result = resolve(mention)
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.reason is ResolutionReason.NO_MATCH
        assert result.resolved_instrument_id is None

    def test_etf_symbol_resolves(self) -> None:
        mention = make_mention("510300.SH", entity_type=EntityType.SECURITY)
        result = resolve(mention)
        assert result.status is ResolutionStatus.RESOLVED
        assert result.resolved_instrument_id == "510300.SH"
        assert result.reason is ResolutionReason.EXACT_SYMBOL

    def test_precious_metal_etf_resolves_not_expanded(self) -> None:
        mention = make_mention("518880.SH", entity_type=EntityType.SECURITY)
        result = resolve(mention)
        assert result.status is ResolutionStatus.RESOLVED
        assert result.resolved_instrument_id == "518880.SH"
        assert result.candidates[0].name == "黄金ETF"

    def test_bare_six_digits_not_bound(self) -> None:
        mention = make_mention("600519", entity_type=EntityType.SECURITY)
        result = resolve(mention)
        # 600519 is not a canonical symbol form; must not be bound by regex.
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.resolved_instrument_id is None


class TestNameResolution:
    def test_full_name_resolves(self) -> None:
        mention = make_mention("贵州茅台")
        result = resolve(mention)
        assert result.status is ResolutionStatus.RESOLVED
        assert result.reason is ResolutionReason.FULL_NAME
        assert result.resolved_instrument_id == "600519.SH"
        assert result.candidates[0].score_bps == 9000

    def test_short_name_alias_resolves(self) -> None:
        mention = make_mention("茅台")
        result = resolve(mention)
        assert result.status is ResolutionStatus.RESOLVED
        assert result.reason is ResolutionReason.SHORT_NAME
        assert result.resolved_instrument_id == "600519.SH"

    def test_former_name_valid_at_reference(self) -> None:
        mention = make_mention("贵州茅台酒厂")
        t_ref = datetime(2020, 6, 1, 0, 0, 0, tzinfo=UTC)
        result = resolve(mention, decision_time=T_2023, reference_time=t_ref)
        assert result.status is ResolutionStatus.RESOLVED
        assert result.reason is ResolutionReason.FORMER_NAME
        assert result.resolved_instrument_id == "600519.SH"

    def test_former_name_expired_at_reference_unresolved(self) -> None:
        mention = make_mention("贵州茅台酒厂")
        result = resolve(mention, decision_time=T_2023, reference_time=T_2022)
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.resolved_instrument_id is None

    def test_person_never_binds_security(self) -> None:
        mention = make_mention("李明", entity_type=EntityType.PERSON)
        result = resolve(mention)
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.reason is ResolutionReason.NOT_SECURITY
        assert result.candidates == ()

    def test_policy_never_binds_security(self) -> None:
        mention = make_mention("全面注册制", entity_type=EntityType.POLICY)
        result = resolve(mention)
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.reason is ResolutionReason.NOT_SECURITY

    def test_region_never_binds_security(self) -> None:
        mention = make_mention("上海", entity_type=EntityType.REGION)
        result = resolve(mention)
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.reason is ResolutionReason.NOT_SECURITY


class TestAmbiguity:
    def test_same_name_no_context_ambiguous(self) -> None:
        mention = make_mention("平安")
        result = resolve(mention)
        assert result.status is ResolutionStatus.AMBIGUOUS
        assert result.resolved_instrument_id is None
        assert {c.instrument_id for c in result.candidates} == {
            "000001.SZ",
            "601318.SH",
        }

    def test_same_name_with_symbol_hint_resolves(self) -> None:
        mention = make_mention("平安")
        result = resolve(mention, symbol_hint="601318.SH")
        assert result.status is ResolutionStatus.RESOLVED
        assert result.resolved_instrument_id == "601318.SH"
        assert result.reason is ResolutionReason.SHORT_NAME

    def test_ambiguous_keeps_all_candidates_sorted(self) -> None:
        mention = make_mention("平安")
        result = resolve(mention)
        scores = [c.score_bps for c in result.candidates]
        assert scores == sorted(scores, reverse=True)
        ids = [c.instrument_id for c in result.candidates]
        assert ids == sorted(ids)

    def test_tie_ambiguous_not_first_item(self) -> None:
        mention = make_mention("平安")
        result = resolve(mention)
        # Same score for both candidates -> must be AMBIGUOUS, never first-item.
        assert result.status is ResolutionStatus.AMBIGUOUS
        assert result.resolved_instrument_id is None


class TestThresholdAndMargin:
    def test_top_below_threshold_unresolved(self) -> None:
        aliases = AliasTable(
            [
                AliasEntry(
                    alias_id="a-low",
                    alias="某公司",
                    alias_type=AliasType.SHORT_NAME,
                    target="600519.SH",
                    effective_from=T_PAST,
                    effective_to=None,
                    available_time=T_PAST,
                    source="s",
                    version="v1",
                    reliability=5000,
                )
            ]
        )
        mention = make_mention("某公司")
        result = resolve(mention, aliases=aliases)
        # 5000 reliability maps to score below the 8000 resolved threshold.
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.reason is ResolutionReason.BELOW_THRESHOLD
        assert result.resolved_instrument_id is None

    def test_margin_insufficient_ambiguous(self) -> None:
        aliases = AliasTable(
            [
                AliasEntry(
                    alias_id="a1",
                    alias="同标",
                    alias_type=AliasType.SHORT_NAME,
                    target="600519.SH",
                    effective_from=T_PAST,
                    effective_to=None,
                    available_time=T_PAST,
                    source="s",
                    version="v1",
                    reliability=8200,
                ),
                AliasEntry(
                    alias_id="a2",
                    alias="同标",
                    alias_type=AliasType.SHORT_NAME,
                    target="000001.SZ",
                    effective_from=T_PAST,
                    effective_to=None,
                    available_time=T_PAST,
                    source="s",
                    version="v1",
                    reliability=7800,
                ),
            ]
        )
        mention = make_mention("同标")
        result = resolve(mention, aliases=aliases)
        # 8200 vs 7800: top clears threshold but gap 400 < margin 1000.
        assert result.status is ResolutionStatus.AMBIGUOUS
        assert result.reason is ResolutionReason.MARGIN_INSUFFICIENT

    def test_threshold_boundary_just_above_resolves(self) -> None:
        aliases = AliasTable(
            [
                AliasEntry(
                    alias_id="a1",
                    alias="边界标",
                    alias_type=AliasType.SHORT_NAME,
                    target="600519.SH",
                    effective_from=T_PAST,
                    effective_to=None,
                    available_time=T_PAST,
                    source="s",
                    version="v1",
                    reliability=8000,
                )
            ]
        )
        mention = make_mention("边界标")
        result = resolve(mention, aliases=aliases)
        assert result.status is ResolutionStatus.RESOLVED
        assert result.resolved_instrument_id == "600519.SH"

    def test_threshold_boundary_just_below_unresolved(self) -> None:
        aliases = AliasTable(
            [
                AliasEntry(
                    alias_id="a1",
                    alias="边界标",
                    alias_type=AliasType.SHORT_NAME,
                    target="600519.SH",
                    effective_from=T_PAST,
                    effective_to=None,
                    available_time=T_PAST,
                    source="s",
                    version="v1",
                    reliability=7999,
                )
            ]
        )
        mention = make_mention("边界标")
        result = resolve(mention, aliases=aliases)
        assert result.status is ResolutionStatus.UNRESOLVED

    def test_margin_boundary_equal_ambiguous(self) -> None:
        aliases = AliasTable(
            [
                AliasEntry(
                    alias_id="a1",
                    alias="边界标",
                    alias_type=AliasType.SHORT_NAME,
                    target="600519.SH",
                    effective_from=T_PAST,
                    effective_to=None,
                    available_time=T_PAST,
                    source="s",
                    version="v1",
                    reliability=9000,
                ),
                AliasEntry(
                    alias_id="a2",
                    alias="边界标",
                    alias_type=AliasType.SHORT_NAME,
                    target="000001.SZ",
                    effective_from=T_PAST,
                    effective_to=None,
                    available_time=T_PAST,
                    source="s",
                    version="v1",
                    reliability=8000,
                ),
            ]
        )
        mention = make_mention("边界标")
        result = resolve(mention, aliases=aliases)
        # gap == margin (1000) is not strictly greater -> AMBIGUOUS.
        assert result.status is ResolutionStatus.AMBIGUOUS


class TestPointInTime:
    def test_future_alias_not_used_at_earlier_decision(self) -> None:
        aliases = AliasTable(
            [
                AliasEntry(
                    alias_id="a-late",
                    alias="新茅台",
                    alias_type=AliasType.SHORT_NAME,
                    target="600519.SH",
                    effective_from=T_PAST,
                    effective_to=None,
                    available_time=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
                    source="s",
                    version="v1",
                    reliability=9000,
                )
            ]
        )
        mention = make_mention("新茅台")
        result = resolve(mention, aliases=aliases, decision_time=T_2023)
        assert result.status is ResolutionStatus.UNRESOLVED

    def test_future_instrument_not_visible(self) -> None:
        from market_core.resolver.universe import InstrumentUniverse

        future = snap(
            make_instrument("600999", "SH", "MAIN", "STOCK", "未来公司"),
            available_time=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        uni = InstrumentUniverse([future])
        mention = make_mention("600999.SH", entity_type=EntityType.SECURITY)
        result = resolve(mention, universe=uni, decision_time=T_2023)
        assert result.status is ResolutionStatus.UNRESOLVED

    def test_cross_timezone_same_instant_equal(self) -> None:
        from datetime import timedelta

        mention = make_mention("600519.SH", entity_type=EntityType.SECURITY)
        utc = resolve(mention, decision_time=T0)
        cst = resolve(
            mention,
            decision_time=datetime(2026, 8, 24, 16, 0, 0, tzinfo=timezone(timedelta(hours=8))),
        )
        assert utc.status is cst.status
        assert utc.resolved_instrument_id == cst.resolved_instrument_id

    def test_naive_decision_time_rejected(self) -> None:
        mention = make_mention("600519.SH", entity_type=EntityType.SECURITY)
        with pytest.raises(ValueError):
            resolve(mention, decision_time=datetime(2026, 8, 24, 8, 0))

    def test_historical_replay_is_deterministic(self) -> None:
        mention = make_mention("贵州茅台")
        r1 = resolve(mention)
        r2 = resolve(mention)
        assert r1 == r2
        assert r1.candidates == r2.candidates


class TestManualOverride:
    def test_valid_override_overrides(self) -> None:
        mention = make_mention("贵州茅台")
        ov = ManualOverride(
            override_id="ov-1",
            scope_type=OverrideScopeType.MENTION,
            scope_value=mention.mention_id,
            target="000001.SZ",
            reason="audit correction",
            reviewer="analyst-1",
            created_time=T_PAST,
            available_time=T_PAST,
            effective_from=T_PAST,
            effective_to=None,
            version="v1",
            evidence_reference="ticket-1",
        )
        result = resolve(mention, override=ov)
        assert result.status is ResolutionStatus.OVERRIDDEN
        assert result.resolved_instrument_id == "000001.SZ"
        assert result.override_reference == "ov-1"
        assert result.reason is ResolutionReason.OVERRIDE
        # Original candidates are preserved and the override target annotated.
        assert {c.instrument_id for c in result.candidates} == {
            "600519.SH",
            "000001.SZ",
        }

    def test_future_override_not_effective(self) -> None:
        mention = make_mention("贵州茅台")
        ov = ManualOverride(
            override_id="ov-f",
            scope_type=OverrideScopeType.MENTION,
            scope_value=mention.mention_id,
            target="000001.SZ",
            reason="r",
            reviewer="a",
            created_time=T_PAST,
            available_time=datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC),
            effective_from=T_PAST,
            effective_to=None,
            version="v1",
            evidence_reference="t",
        )
        result = resolve(mention, override=ov)
        assert result.status is ResolutionStatus.RESOLVED
        assert result.resolved_instrument_id == "600519.SH"
        assert result.override_reference is None

    def test_expired_override_not_effective(self) -> None:
        mention = make_mention("贵州茅台")
        ov = ManualOverride(
            override_id="ov-e",
            scope_type=OverrideScopeType.MENTION,
            scope_value=mention.mention_id,
            target="000001.SZ",
            reason="r",
            reviewer="a",
            created_time=T_PAST,
            available_time=T_PAST,
            effective_from=T_PAST,
            effective_to=datetime(2021, 1, 1, 0, 0, 0, tzinfo=UTC),
            version="v1",
            evidence_reference="t",
        )
        result = resolve(mention, override=ov)
        assert result.status is ResolutionStatus.RESOLVED
        assert result.resolved_instrument_id == "600519.SH"

    def test_scope_mismatch_not_effective(self) -> None:
        mention = make_mention("贵州茅台")
        ov = ManualOverride(
            override_id="ov-s",
            scope_type=OverrideScopeType.MENTION,
            scope_value="some-other-mention",
            target="000001.SZ",
            reason="r",
            reviewer="a",
            created_time=T_PAST,
            available_time=T_PAST,
            effective_from=T_PAST,
            effective_to=None,
            version="v1",
            evidence_reference="t",
        )
        result = resolve(mention, override=ov)
        assert result.status is ResolutionStatus.RESOLVED
        assert result.resolved_instrument_id == "600519.SH"

    def test_invalid_target_not_effective(self) -> None:
        mention = make_mention("贵州茅台")
        ov = ManualOverride(
            override_id="ov-t",
            scope_type=OverrideScopeType.MENTION,
            scope_value=mention.mention_id,
            target="999999.SH",
            reason="r",
            reviewer="a",
            created_time=T_PAST,
            available_time=T_PAST,
            effective_from=T_PAST,
            effective_to=None,
            version="v1",
            evidence_reference="t",
        )
        result = resolve(mention, override=ov)
        assert result.status is ResolutionStatus.RESOLVED
        assert result.resolved_instrument_id == "600519.SH"

    def test_conflicting_overrides_fail_closed(self) -> None:
        mention = make_mention("贵州茅台")
        ov1 = ManualOverride(
            override_id="ov-c1",
            scope_type=OverrideScopeType.MENTION,
            scope_value=mention.mention_id,
            target="000001.SZ",
            reason="r",
            reviewer="a",
            created_time=T_PAST,
            available_time=T_PAST,
            effective_from=T_PAST,
            effective_to=None,
            version="v1",
            evidence_reference="t",
        )
        ov2 = ManualOverride(
            override_id="ov-c2",
            scope_type=OverrideScopeType.MENTION,
            scope_value=mention.mention_id,
            target="601318.SH",
            reason="r",
            reviewer="a",
            created_time=T_PAST,
            available_time=T_PAST,
            effective_from=T_PAST,
            effective_to=None,
            version="v1",
            evidence_reference="t",
        )
        result = resolve_mentions(
            (mention,),
            universe=base_universe(),
            aliases=base_aliases(),
            decision_time=T0,
            reference_time=T0,
            overrides=(ov1, ov2),
        )[0]
        assert result.status is ResolutionStatus.AMBIGUOUS
        assert result.reason is ResolutionReason.CONFLICTING_OVERRIDES
        assert result.resolved_instrument_id is None

    def test_override_disabled_by_policy(self) -> None:
        mention = make_mention("贵州茅台")
        ov = ManualOverride(
            override_id="ov-1",
            scope_type=OverrideScopeType.MENTION,
            scope_value=mention.mention_id,
            target="000001.SZ",
            reason="r",
            reviewer="a",
            created_time=T_PAST,
            available_time=T_PAST,
            effective_from=T_PAST,
            effective_to=None,
            version="v1",
            evidence_reference="t",
        )
        result = resolve(
            mention,
            override=ov,
            policy=ResolverPolicy(override_enabled=False),
        )
        assert result.status is ResolutionStatus.RESOLVED
        assert result.resolved_instrument_id == "600519.SH"


class TestBatchResolution:
    def test_mentions_with_symbol_context(self) -> None:
        company = make_mention("平安")
        symbol = make_mention(
            "601318.SH",
            entity_type=EntityType.SECURITY,
            content_id="content-1",
        )
        results = resolve_mentions(
            (company, symbol),
            universe=base_universe(),
            aliases=base_aliases(),
            decision_time=T0,
            reference_time=T0,
        )
        by_id = {r.mention_id: r for r in results}
        assert by_id[symbol.mention_id].status is ResolutionStatus.RESOLVED
        assert by_id[symbol.mention_id].resolved_instrument_id == "601318.SH"
        # Company mention picks up the symbol context and resolves.
        assert by_id[company.mention_id].status is ResolutionStatus.RESOLVED
        assert by_id[company.mention_id].resolved_instrument_id == "601318.SH"

    def test_batch_without_symbol_context_ambiguous(self) -> None:
        mention = make_mention("平安")
        results = resolve_mentions(
            (mention,),
            universe=base_universe(),
            aliases=base_aliases(),
            decision_time=T0,
            reference_time=T0,
        )
        assert results[0].status is ResolutionStatus.AMBIGUOUS


class TestEligibilityGate:
    def test_low_confidence_with_high_reliability_alias_not_bound(self) -> None:
        # confidence_bps=3000 even with a high-reliability alias must never be
        # auto-RESOLVED.
        mention = make_mention("茅台", confidence_bps=3000)
        result = resolve(mention)
        assert result.status is not ResolutionStatus.RESOLVED
        assert result.resolved_instrument_id is None
        # Candidates may still be surfaced for audit, but not bound.
        assert result.candidates

    def test_low_confidence_exact_symbol_not_bound(self) -> None:
        mention = make_mention("600519.SH", entity_type=EntityType.SECURITY, confidence_bps=3000)
        result = resolve(mention)
        assert result.status is not ResolutionStatus.RESOLVED
        assert result.resolved_instrument_id is None

    def test_override_can_override_low_confidence(self) -> None:
        mention = make_mention("茅台", confidence_bps=3000)
        ov = ManualOverride(
            override_id="ov-low",
            scope_type=OverrideScopeType.MENTION,
            scope_value=mention.mention_id,
            target="600519.SH",
            reason="audit correction",
            reviewer="analyst-1",
            created_time=T_PAST,
            available_time=T_PAST,
            effective_from=T_PAST,
            effective_to=None,
            version="v1",
            evidence_reference="ticket-1",
        )
        result = resolve(mention, override=ov)
        assert result.status is ResolutionStatus.OVERRIDDEN
        assert result.resolved_instrument_id == "600519.SH"
        assert result.override_reference == "ov-low"


class TestNonSecurityTypes:
    def test_institution_same_name_as_security_not_bound(self) -> None:
        # INSTITUTION is not a security subject; even sharing a name with a
        # listed company it must stay UNRESOLVED.
        mention = make_mention("平安", entity_type=EntityType.INSTITUTION)
        result = resolve(mention)
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.reason is ResolutionReason.NOT_SECURITY
        assert result.resolved_instrument_id is None
        assert result.candidates == ()

    def test_institution_exact_symbol_still_not_bound(self) -> None:
        mention = make_mention("600519.SH", entity_type=EntityType.INSTITUTION)
        result = resolve(mention)
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.reason is ResolutionReason.NOT_SECURITY


class TestMultiSymbolContext:
    def test_two_symbols_company_stays_ambiguous(self) -> None:
        company = make_mention("平安", content_id="c1")
        sym_a = make_mention("000001.SZ", entity_type=EntityType.SECURITY, content_id="c1")
        sym_b = make_mention("601318.SH", entity_type=EntityType.SECURITY, content_id="c1")
        results = resolve_mentions(
            (company, sym_a, sym_b),
            universe=base_universe(),
            aliases=base_aliases(),
            decision_time=T0,
            reference_time=T0,
        )
        by_id = {r.mention_id: r for r in results}
        assert by_id[company.mention_id].status is ResolutionStatus.AMBIGUOUS
        assert by_id[company.mention_id].resolved_instrument_id is None

    def test_two_symbols_deterministic_across_hash_seeds(self) -> None:
        import os
        import subprocess
        import sys

        code = (
            "import sys; sys.path.insert(0, 'python/packages/market-core/tests'); "
            "from datetime import UTC, datetime; "
            "from event_core.entities.models import EntityType; "
            "from market_core.resolver import resolve_mentions; "
            "from market_core.resolver.universe import InstrumentUniverse; "
            "from test_resolver_models import T0, T_PAST, base_aliases, base_universe, make_instrument, make_mention, snap; "  # noqa: E501
            "company = make_mention('平安', content_id='c1'); "
            "sym_a = make_mention('000001.SZ', entity_type=EntityType.SECURITY, content_id='c1'); "
            "sym_b = make_mention('601318.SH', entity_type=EntityType.SECURITY, content_id='c1'); "
            "results = resolve_mentions((company, sym_a, sym_b), universe=base_universe(), aliases=base_aliases(), decision_time=T0, reference_time=T0); "  # noqa: E501
            "r = {x.mention_id: x for x in results}[company.mention_id]; "
            "print(r.status.value, r.resolved_instrument_id)"
        )
        outputs: set[str] = set()
        for seed in ("0", "1", "42"):
            env = dict(os.environ)
            env["PYTHONHASHSEED"] = seed
            proc = subprocess.run(
                [sys.executable, "-c", code],
                cwd=os.getcwd(),
                env=env,
                capture_output=True,
                text=True,
            )
            assert proc.returncode == 0, proc.stderr
            outputs.add(proc.stdout.strip())
        assert outputs == {"ambiguous None"}

    def test_single_symbol_context_still_resolves(self) -> None:
        company = make_mention("平安", content_id="c1")
        symbol = make_mention("601318.SH", entity_type=EntityType.SECURITY, content_id="c1")
        results = resolve_mentions(
            (company, symbol),
            universe=base_universe(),
            aliases=base_aliases(),
            decision_time=T0,
            reference_time=T0,
        )
        by_id = {r.mention_id: r for r in results}
        assert by_id[company.mention_id].status is ResolutionStatus.RESOLVED
        assert by_id[company.mention_id].resolved_instrument_id == "601318.SH"

    def test_input_order_does_not_change_result(self) -> None:
        a = make_mention("平安", content_id="c1")
        b = make_mention("000001.SZ", entity_type=EntityType.SECURITY, content_id="c1")
        c = make_mention("601318.SH", entity_type=EntityType.SECURITY, content_id="c1")
        r1 = resolve_mentions(
            (a, b, c),
            universe=base_universe(),
            aliases=base_aliases(),
            decision_time=T0,
            reference_time=T0,
        )
        r2 = resolve_mentions(
            (c, b, a),
            universe=base_universe(),
            aliases=base_aliases(),
            decision_time=T0,
            reference_time=T0,
        )

        def result_key(r: SecurityResolution) -> tuple[str, ResolutionStatus, str | None]:
            return (r.mention_id, r.status, r.resolved_instrument_id)

        assert sorted(result_key(r) for r in r1) == sorted(result_key(r) for r in r2)


class TestReferenceTimeListing:
    def test_not_listed_before_list_date(self) -> None:
        uni = InstrumentUniverse(
            [
                snap(
                    make_instrument(
                        "688001",
                        "SH",
                        "STAR",
                        "STOCK",
                        "未上市公司",
                        list_date=date(2026, 9, 1),
                    ),
                    T_PAST,
                )
            ]
        )
        mention = make_mention("688001.SH", entity_type=EntityType.SECURITY)
        result = resolve(
            mention,
            universe=uni,
            reference_time=datetime(2026, 8, 24, 0, 0, 0, tzinfo=UTC),
        )
        assert result.status is ResolutionStatus.UNRESOLVED

    def test_listed_on_list_date(self) -> None:
        uni = InstrumentUniverse(
            [
                snap(
                    make_instrument(
                        "688001",
                        "SH",
                        "STAR",
                        "STOCK",
                        "上市当日公司",
                        list_date=date(2026, 8, 24),
                    ),
                    T_PAST,
                )
            ]
        )
        mention = make_mention("688001.SH", entity_type=EntityType.SECURITY)
        result = resolve(
            mention,
            universe=uni,
            reference_time=datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC),
        )
        assert result.status is ResolutionStatus.RESOLVED

    def test_unresolved_on_delist_date(self) -> None:
        uni = InstrumentUniverse(
            [
                snap(
                    make_instrument(
                        "600519",
                        "SH",
                        "MAIN",
                        "STOCK",
                        "贵州茅台",
                        list_date=date(2001, 8, 27),
                        delist_date=date(2026, 8, 24),
                    ),
                    T_PAST,
                )
            ]
        )
        mention = make_mention("600519.SH", entity_type=EntityType.SECURITY)
        # reference_date == delistDate is still within the window.
        result = resolve(
            mention,
            universe=uni,
            reference_time=datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC),
        )
        assert result.status is ResolutionStatus.RESOLVED

    def test_unresolved_after_delist_date(self) -> None:
        uni = InstrumentUniverse(
            [
                snap(
                    make_instrument(
                        "600519",
                        "SH",
                        "MAIN",
                        "STOCK",
                        "贵州茅台",
                        list_date=date(2001, 8, 27),
                        delist_date=date(2026, 8, 23),
                    ),
                    T_PAST,
                )
            ]
        )
        mention = make_mention("600519.SH", entity_type=EntityType.SECURITY)
        result = resolve(
            mention,
            universe=uni,
            reference_time=datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC),
        )
        assert result.status is ResolutionStatus.UNRESOLVED

    def test_name_alias_respects_reference_listing(self) -> None:
        uni = InstrumentUniverse(
            [
                snap(
                    make_instrument(
                        "688001",
                        "SH",
                        "STAR",
                        "STOCK",
                        "贵州茅台",
                        list_date=date(2026, 9, 1),
                    ),
                    T_PAST,
                )
            ]
        )
        mention = make_mention("贵州茅台")
        result = resolve(
            mention,
            universe=uni,
            reference_time=datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC),
        )
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.resolved_instrument_id is None


def timedelta_hours(hours: int):
    from datetime import timedelta

    return timedelta(hours=hours)


class TestSecondRoundFailClosedRegressions:
    def test_extraction_threshold_is_carried_into_resolver_gate(self) -> None:
        mention = make_mention(
            "茅台",
            confidence_bps=8000,
            eligibility_threshold_bps=9000,
        )
        result = resolve(mention)
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.reason is ResolutionReason.LOW_CONFIDENCE

    def test_low_confidence_security_does_not_hint_same_content_company(self) -> None:
        company = make_mention("平安", content_id="c1")
        security = make_mention(
            "601318.SH",
            entity_type=EntityType.SECURITY,
            confidence_bps=8000,
            eligibility_threshold_bps=9000,
            content_id="c1",
        )
        results = resolve_mentions(
            (company, security),
            universe=base_universe(),
            aliases=base_aliases(),
            decision_time=T0,
            reference_time=T0,
        )
        by_id = {item.mention_id: item for item in results}
        assert by_id[security.mention_id].reason is ResolutionReason.LOW_CONFIDENCE
        assert by_id[company.mention_id].status is ResolutionStatus.AMBIGUOUS

    def test_security_hint_isolated_by_content_and_multiple_symbols_fail_closed(self) -> None:
        company_a = make_mention("平安", content_id="c1")
        symbol_a = make_mention("601318.SH", entity_type=EntityType.SECURITY, content_id="c1")
        company_b = make_mention("平安", content_id="c2")
        symbol_b1 = make_mention("000001.SZ", entity_type=EntityType.SECURITY, content_id="c2")
        symbol_b2 = make_mention("601318.SH", entity_type=EntityType.SECURITY, content_id="c2")
        results = resolve_mentions(
            (company_a, symbol_a, company_b, symbol_b1, symbol_b2),
            universe=base_universe(),
            aliases=base_aliases(),
            decision_time=T0,
            reference_time=T0,
        )
        by_id = {item.mention_id: item for item in results}
        assert by_id[company_a.mention_id].resolved_instrument_id == "601318.SH"
        assert by_id[company_b.mention_id].status is ResolutionStatus.AMBIGUOUS

    def test_symbol_scope_override_normalizes_case_and_whitespace(self) -> None:
        mention = make_mention("600519.SH", entity_type=EntityType.SECURITY)
        override = make_override(
            mention,
            override_id="ov-symbol",
            target="000001.SZ",
            scope_type=OverrideScopeType.SYMBOL,
            scope_value=" 600519.sh ",
        )
        result = resolve(mention, override=override)
        assert result.status is ResolutionStatus.OVERRIDDEN
        assert result.resolved_instrument_id == "000001.SZ"

    def test_override_target_must_be_listed_at_reference_time(self) -> None:
        mention = make_mention("贵州茅台")
        extra = (
            snap(
                make_instrument(
                    "600999",
                    "SH",
                    "MAIN",
                    "STOCK",
                    "未来公司",
                    list_date=date(2027, 1, 1),
                )
            ),
            snap(
                make_instrument(
                    "600998",
                    "SH",
                    "MAIN",
                    "STOCK",
                    "历史公司",
                    delist_date=date(2025, 1, 1),
                )
            ),
        )
        universe = InstrumentUniverse((*base_universe().snapshots, *extra))
        for target in ("600999.SH", "600998.SH"):
            result = resolve(
                mention,
                universe=universe,
                override=make_override(mention, override_id=f"ov-{target}", target=target),
            )
            assert result.status is ResolutionStatus.RESOLVED
            assert result.resolved_instrument_id == "600519.SH"

    def test_duplicate_override_id_conflicts_independent_of_order(self) -> None:
        mention = make_mention("贵州茅台")
        first = make_override(mention, override_id="ov-duplicate", target="000001.SZ")
        second = make_override(mention, override_id="ov-duplicate", target="601318.SH")
        for overrides in ((first, second), (second, first)):
            result = resolve_mentions(
                (mention,),
                universe=base_universe(),
                aliases=base_aliases(),
                decision_time=T0,
                reference_time=T0,
                overrides=overrides,
            )[0]
            assert result.status is ResolutionStatus.AMBIGUOUS
            assert result.reason is ResolutionReason.CONFLICTING_OVERRIDES

    def test_duplicate_override_same_target_different_record_conflicts(self) -> None:
        mention = make_mention("贵州茅台")
        first = make_override(
            mention, override_id="ov-duplicate", target="000001.SZ", reason="first"
        )
        second = make_override(
            mention, override_id="ov-duplicate", target="000001.SZ", reason="second"
        )
        result = resolve_mentions(
            (mention,),
            universe=base_universe(),
            aliases=base_aliases(),
            decision_time=T0,
            reference_time=T0,
            overrides=(second, first),
        )[0]
        assert result.status is ResolutionStatus.AMBIGUOUS
        assert result.reason is ResolutionReason.CONFLICTING_OVERRIDES

    def test_exact_duplicate_override_is_deduplicated(self) -> None:
        mention = make_mention("贵州茅台")
        override = make_override(mention, override_id="ov-exact", target="000001.SZ")
        result = resolve_mentions(
            (mention,),
            universe=base_universe(),
            aliases=base_aliases(),
            decision_time=T0,
            reference_time=T0,
            overrides=(override, override),
        )[0]
        assert result.status is ResolutionStatus.OVERRIDDEN

    def test_conflicting_security_overrides_cannot_create_trusted_hint(self) -> None:
        company = make_mention("绑定", content_id="c1")
        security = make_mention("600519.SH", entity_type=EntityType.SECURITY, content_id="c1")
        aliases = AliasTable(
            [
                AliasEntry(
                    alias_id="binding-mt",
                    alias="绑定",
                    alias_type=AliasType.SHORT_NAME,
                    target="600519.SH",
                    effective_from=T_PAST,
                    effective_to=None,
                    available_time=T_PAST,
                    source="test",
                    version="v1",
                    reliability=9000,
                ),
                AliasEntry(
                    alias_id="binding-bank",
                    alias="绑定",
                    alias_type=AliasType.SHORT_NAME,
                    target="000001.SZ",
                    effective_from=T_PAST,
                    effective_to=None,
                    available_time=T_PAST,
                    source="test",
                    version="v1",
                    reliability=9000,
                ),
            ]
        )
        first = make_override(security, override_id="ov-security", target="000001.SZ")
        second = make_override(security, override_id="ov-security", target="601318.SH")
        results = resolve_mentions(
            (company, security),
            universe=base_universe(),
            aliases=aliases,
            decision_time=T0,
            reference_time=T0,
            overrides=(first, second),
        )
        by_id = {item.mention_id: item for item in results}
        assert by_id[security.mention_id].reason is ResolutionReason.CONFLICTING_OVERRIDES
        assert by_id[company.mention_id].status is ResolutionStatus.AMBIGUOUS


class TestSolAuditRegressions:
    def test_same_instrument_full_name_and_alias_are_one_candidate(self) -> None:
        aliases = AliasTable(
            [
                AliasEntry(
                    alias_id="same-name",
                    alias="贵州茅台",
                    alias_type=AliasType.SHORT_NAME,
                    target="600519.SH",
                    effective_from=T_PAST,
                    effective_to=None,
                    available_time=T_PAST,
                    source="test-source",
                    version="v1",
                    reliability=9000,
                )
            ]
        )
        result = resolve(make_mention("贵州茅台"), aliases=aliases)
        assert result.status is ResolutionStatus.RESOLVED
        assert [candidate.instrument_id for candidate in result.candidates] == ["600519.SH"]

    def test_canonically_equivalent_alias_targets_are_one_candidate(self) -> None:
        aliases = AliasTable(
            [
                AliasEntry(
                    alias_id=alias_id,
                    alias="茅台",
                    alias_type=AliasType.SHORT_NAME,
                    target=target,
                    effective_from=T_PAST,
                    effective_to=None,
                    available_time=T_PAST,
                    source="test-source",
                    version="v1",
                    reliability=9000,
                )
                for alias_id, target in (
                    ("lower", "600519.sh"),
                    ("upper", "600519.SH"),
                )
            ]
        )
        result = resolve(make_mention("茅台"), aliases=aliases)
        assert result.status is ResolutionStatus.RESOLVED
        assert [candidate.instrument_id for candidate in result.candidates] == ["600519.SH"]

    def test_listing_date_uses_shanghai_date_for_same_instant(self) -> None:
        universe = InstrumentUniverse(
            [
                snap(
                    make_instrument(
                        "688001",
                        "SH",
                        "STAR",
                        "STOCK",
                        "边界公司",
                        list_date=date(2026, 1, 2),
                    ),
                    T_PAST,
                )
            ]
        )
        mention = make_mention("688001.SH", entity_type=EntityType.SECURITY)
        shanghai_time = datetime(
            2026,
            1,
            2,
            0,
            30,
            tzinfo=timezone(timedelta_hours(8)),
        )
        utc_time = shanghai_time.astimezone(UTC)
        shanghai_result = resolve(mention, universe=universe, reference_time=shanghai_time)
        utc_result = resolve(mention, universe=universe, reference_time=utc_time)
        assert shanghai_result.status is ResolutionStatus.RESOLVED
        assert utc_result.status is shanghai_result.status

    def test_agreeing_overrides_apply_deterministically(self) -> None:
        mention = make_mention("贵州茅台")
        first = make_override(mention, override_id="ov-a", target="000001.SZ")
        second = make_override(mention, override_id="ov-b", target="000001.SZ")
        for overrides in ((first, second), (second, first)):
            result = resolve_mentions(
                (mention,),
                universe=base_universe(),
                aliases=base_aliases(),
                decision_time=T0,
                reference_time=T0,
                overrides=overrides,
            )[0]
            assert result.status is ResolutionStatus.OVERRIDDEN
            assert result.resolved_instrument_id == "000001.SZ"
            assert result.override_reference == "ov-a"

    def test_resolution_candidate_carries_instrument_snapshot_provenance(self) -> None:
        result = resolve(make_mention("600519.SH", entity_type=EntityType.SECURITY))
        candidate = result.candidates[0]
        assert candidate.instrument_version == "v1"
        assert candidate.instrument_source == "test-source"
        assert candidate.instrument_available_time == T_PAST
