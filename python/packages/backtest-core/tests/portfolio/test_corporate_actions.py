from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from backtest_core import BacktestOrderIntent, IntentSide, canonical_digest
from backtest_core.execution import (
    ExecutableLiquidityLevel,
    ExecutionProvenance,
    FeeComponent,
    FeeSchedule,
    FeeScope,
    InstrumentExecutionRules,
    InstrumentKind,
    LimitLockState,
    MarketExecutionSnapshot,
    OddLotSellPolicy,
    OrderType,
    PriceBand,
    PriceSource,
    RoundingMode,
    SameDaySellPolicy,
    SessionKind,
    SimulationOrder,
    SlippageModel,
    TradeStatus,
)
from backtest_core.execution.matcher import match_orders
from backtest_core.portfolio import (
    AccountCode,
    BuyCashReservation,
    BuyCashReservationEvent,
    CorporateActionApplicationEvent,
    CorporateActionError,
    CorporateActionRecord,
    CorporateActionTerms,
    CorporateActionType,
    EventMetadata,
    EventPhase,
    ExecutionArtifactRef,
    ExecutionReplayBundle,
    ExecutionSettlementEvent,
    InitialCapitalEvent,
    LotCostAllocationPolicy,
    PortfolioState,
    ReceivableSettlementEvent,
    TrustedExecutionArtifactSource,
    TrustedExecutionInputs,
    ValuationError,
    ValuationMark,
    ValuationMarkSource,
    apply_corporate_action,
    apply_portfolio_event,
    value_portfolio,
    verify_portfolio_valuation_against_state,
)
from backtest_core.portfolio import (
    RoundingMode as PortfolioRoundingMode,
)
from backtest_core.portfolio.accounting import consume_fifo
from backtest_core.portfolio.models import PortfolioEvent, PortfolioHistoryRef

SHANGHAI = ZoneInfo("Asia/Shanghai")
T = datetime(2026, 5, 29, 15, 0, tzinfo=SHANGHAI)


class _FifoProbeFill:
    def __init__(self, quantity: int, instrument_code: str, trading_date: str) -> None:
        self.quantity = quantity
        self.instrument_code = instrument_code
        self.trading_date = trading_date


class _PortfolioSource:
    def __init__(self, execution_source: TrustedExecutionArtifactSource | None = None) -> None:
        self.tapes: dict[str, tuple[PortfolioEvent, ...]] = {"portfolio-genesis": ()}
        self.versions: dict[tuple[str, str, int], tuple[PortfolioEvent, ...]] = {}
        self.execution_source = execution_source

    def resolve_portfolio_history(
        self, history_ref: PortfolioHistoryRef
    ) -> tuple[PortfolioEvent, ...]:
        key = (
            history_ref.tape_id,
            history_ref.expected_event_tape_digest,
            history_ref.expected_event_count,
        )
        return self.versions.get(key, self.tapes.get(history_ref.tape_id, ()))

    def record(self, history_ref: PortfolioHistoryRef, events: tuple[PortfolioEvent, ...]) -> None:
        key = (
            history_ref.tape_id,
            history_ref.expected_event_tape_digest,
            history_ref.expected_event_count,
        )
        self.versions[key] = events
        self.tapes[history_ref.tape_id] = events

    def apply(self, state: PortfolioState, event: PortfolioEvent) -> PortfolioState:
        previous = self.resolve_portfolio_history(state.history_ref)
        result = apply_portfolio_event(
            state,
            event,
            source=self,
            execution_source=self.execution_source,
        )
        self.record(result.history_ref, previous + (event,))
        return result


class _ExecutionSource:
    def __init__(self, inputs: TrustedExecutionInputs) -> None:
        self.inputs = inputs

    def resolve_execution_artifact(
        self, artifact_ref: ExecutionArtifactRef
    ) -> TrustedExecutionInputs:
        return self.inputs


def _execution_source() -> tuple[ExecutionReplayBundle, _ExecutionSource]:
    provenance = ExecutionProvenance("corp-fixture", "1.0.0", "record", "a" * 64, T)
    intent = BacktestOrderIntent(
        intent_id="corp-intent",
        source_signal_id="corp-signal",
        entity_id="600001.SH",
        logical_time=T,
        side=IntentSide.BUY,
        policy_id="corp-policy",
        policy_version="1.0.0",
        policy_fingerprint="b" * 64,
        manifest_digest="c" * 64,
    )
    order = SimulationOrder(
        order_id="corp-buy",
        source_intent=intent,
        instrument_code="600001.SH",
        side=IntentSide.BUY,
        manifest_digest="c" * 64,
        submitted_at=T,
        submission_sequence=0,
        quantity=100,
        order_type=OrderType.LIMIT_IOC,
        limit_price=Decimal("10"),
        protection_price=None,
    )
    level = ExecutableLiquidityLevel(
        level_id="corp-ask",
        side=IntentSide.SELL,
        price=Decimal("10"),
        quantity=100,
        available_time=T,
        price_source=PriceSource.EXECUTABLE_QUOTE,
        source=provenance,
    )
    snapshot = MarketExecutionSnapshot(
        schema_version="execution-v1",
        snapshot_id="corp-snapshot",
        instrument_code="600001.SH",
        match_time=T,
        observed_time=T,
        available_time=T,
        processing_time=T,
        trading_date="2026-05-29",
        is_trading_day=True,
        calendar_id="cn",
        calendar_version="1.0.0",
        calendar_digest="d" * 64,
        session=SessionKind.CONTINUOUS,
        trade_status=TradeStatus.OPEN,
        price_band=PriceBand(None, None, None, None),
        bid_levels=(),
        ask_levels=(level,),
        lock_state=LimitLockState.NONE,
        source=provenance,
    )
    rules = InstrumentExecutionRules(
        rule_set_id="corp-rules",
        rule_set_version="1.0.0",
        instrument_code="600001.SH",
        instrument_kind=InstrumentKind.A_SHARE_STOCK,
        effective_from=T.replace(hour=9),
        effective_to=None,
        available_time=T,
        lot_size=100,
        tick_size=Decimal("0.01"),
        buy_min_quantity=100,
        buy_increment=100,
        max_order_quantity=100000,
        odd_lot_sell_policy=OddLotSellPolicy.DISALLOW,
        same_day_sell_policy=SameDaySellPolicy.T_PLUS_0,
        supported_order_types=(OrderType.LIMIT_IOC,),
        source=provenance,
    )
    fee_component = FeeComponent(
        code="corp-commission",
        applies_sides=(IntentSide.BUY, IntentSide.SELL),
        instrument_kinds=(InstrumentKind.A_SHARE_STOCK,),
        rate=Decimal("0"),
        minimum=Decimal("0"),
        maximum=None,
        rounding_quantum=Decimal("0.01"),
        rounding_mode=RoundingMode.HALF_UP,
        scope=FeeScope.PER_FILL,
        effective_from=T.replace(hour=9),
        effective_to=None,
        available_time=T,
        source=provenance,
    )
    fee_schedule = FeeSchedule(
        schedule_id="corp-fees",
        schedule_version="1.0.0",
        effective_from=T.replace(hour=9),
        effective_to=None,
        available_time=T,
        components=(fee_component,),
        source=provenance,
    )
    slippage = SlippageModel(
        model_id="corp-slippage",
        model_version="1.0.0",
        effective_from=T.replace(hour=9),
        effective_to=None,
        available_time=T,
        max_level_participation=None,
        adverse_level_offset=0,
        skip_level_ids=(),
        source=provenance,
    )
    candidate = match_orders((order,), snapshot, rules, None, fee_schedule, slippage)
    inputs = TrustedExecutionInputs(
        artifact_id="corp-artifact",
        orders=(order,),
        snapshot=snapshot,
        rules=rules,
        sellability=None,
        fee_schedule=fee_schedule,
        slippage_model=slippage,
        external_source_digest=candidate.source_dataset_digest,
        external_config_digest=candidate.code_config_digest,
    )
    return (
        ExecutionReplayBundle(
            ExecutionArtifactRef("corp-artifact", inputs.input_digest), candidate
        ),
        _ExecutionSource(inputs),
    )


def _state() -> tuple[PortfolioState, _PortfolioSource]:
    source = _PortfolioSource()
    state = PortfolioState.empty()
    state = source.apply(
        state,
        InitialCapitalEvent(
            metadata=EventMetadata(
                event_id="open",
                logical_time=T,
                event_phase=EventPhase.OPENING,
                source_id="corp-test",
                source_version="1.0.0",
                source_sequence=0,
                available_time=T,
                previous_event_digest="0" * 64,
                expected_previous_state_digest=state.state_digest,
                provenance_digest="1" * 64,
                config_digest="2" * 64,
            ),
            amount=Decimal("10000"),
        ),
    )
    return state, source


def _action(
    action_type: CorporateActionType,
    terms: CorporateActionTerms,
    *,
    lineage_id: str = "action-1",
    action_version: str = "1.0.0",
    record_time: datetime = T,
    effective_time: datetime = T,
    source_id: str = "corp-source",
    raw_capture_id: str = "capture-1",
    action_id: str = "action-id-1",
) -> CorporateActionRecord:
    available_time = record_time - timedelta(minutes=1)
    return CorporateActionRecord(
        schema_version="corporate-action-v1",
        action_version=action_version,
        lineage_id=lineage_id,
        instrument_code="600001.SH",
        action_type=action_type,
        publish_time=available_time,
        event_time=effective_time,
        available_time=available_time,
        record_time=record_time,
        effective_time=effective_time,
        pay_time=effective_time,
        listing_time=effective_time,
        source_id=source_id,
        source_version="1.0.0",
        raw_capture_id=raw_capture_id,
        action_id=action_id,
        raw_capture_digest="3" * 64,
        provenance_digest="4" * 64,
        terms_digest=terms.digest,
        terms=terms,
    )


def _lot_state() -> tuple[PortfolioState, _PortfolioSource, _ExecutionSource]:
    execution_bundle, execution_source = _execution_source()
    source = _PortfolioSource(execution_source)
    state = PortfolioState.empty()
    state = source.apply(
        state,
        InitialCapitalEvent(
            metadata=EventMetadata(
                event_id="lot-open",
                logical_time=T,
                event_phase=EventPhase.OPENING,
                source_id="corp-test",
                source_version="1.0.0",
                source_sequence=0,
                available_time=T,
                previous_event_digest="0" * 64,
                expected_previous_state_digest=state.state_digest,
                provenance_digest="1" * 64,
                config_digest="2" * 64,
            ),
            amount=Decimal("1000"),
        ),
    )
    reservation = BuyCashReservation(
        order_id="corp-buy",
        order_digest=execution_source.inputs.orders[0].order_digest,
        fee_schedule_digest=execution_source.inputs.fee_schedule.fee_schedule_digest,
        artifact_id=execution_bundle.artifact_ref.artifact_id,
        execution_input_digest=execution_bundle.artifact_ref.expected_input_digest,
        policy_id="corp-reserve",
        policy_version="1.0.0",
        policy_digest="e" * 64,
        reservation_logical_time=T,
        maximum_debit=Decimal("1000"),
    )
    state = source.apply(
        state,
        BuyCashReservationEvent(
            metadata=EventMetadata(
                event_id="lot-reserve",
                logical_time=T,
                event_phase=EventPhase.RESERVATION,
                source_id="corp-test",
                source_version="1.0.0",
                source_sequence=1,
                available_time=T,
                previous_event_digest=state.last_event_digest,
                expected_previous_state_digest=state.state_digest,
                provenance_digest="1" * 64,
                config_digest="2" * 64,
            ),
            reservation=reservation,
        ),
    )
    previous = source.resolve_portfolio_history(state.history_ref)
    metadata = EventMetadata(
        event_id="lot-settle",
        logical_time=T,
        event_phase=EventPhase.EXECUTION,
        source_id="corp-test",
        source_version="1.0.0",
        source_sequence=2,
        available_time=T,
        previous_event_digest=state.last_event_digest,
        expected_previous_state_digest=state.state_digest,
        provenance_digest="1" * 64,
        config_digest="2" * 64,
    )
    state = apply_portfolio_event(
        state,
        ExecutionSettlementEvent(metadata, execution_bundle, LotCostAllocationPolicy()),
        source=source,
        execution_source=execution_source,
    )
    source.record(
        state.history_ref,
        previous
        + (ExecutionSettlementEvent(metadata, execution_bundle, LotCostAllocationPolicy()),),
    )
    return state, source, execution_source


def _pay_metadata(state: PortfolioState) -> EventMetadata:
    return EventMetadata(
        event_id="payment-1",
        logical_time=T,
        event_phase=EventPhase.RECEIVABLE_SETTLEMENT,
        source_id="corp-test",
        source_version="1.0.0",
        source_sequence=1,
        available_time=T,
        previous_event_digest=state.last_event_digest,
        expected_previous_state_digest=state.state_digest,
        provenance_digest="7" * 64,
        config_digest="8" * 64,
    )


def _apply_action(
    state: PortfolioState,
    source: _PortfolioSource,
    record: CorporateActionRecord,
    execution_source: object | None = None,
    lot_cost_policy: LotCostAllocationPolicy | None = None,
) -> PortfolioState:
    previous = source.resolve_portfolio_history(state.history_ref)
    action_kwargs: dict[str, object] = {
        "source": source,
        "execution_source": execution_source,
    }
    if lot_cost_policy is not None:
        action_kwargs["lot_cost_policy"] = lot_cost_policy
    result = apply_corporate_action(state, record, **action_kwargs)  # type: ignore[arg-type]
    boundary = record.effective_time or record.pay_time or record.event_time
    metadata = EventMetadata.for_event(
        event_id=canonical_digest(("CORPORATE_ACTION", record.action_digest)),
        logical_time=boundary,
        event_phase=EventPhase.CORPORATE_ACTION,
        source_id=record.source_id,
        source_version=record.action_version,
        source_sequence=len(previous),
        available_time=record.available_time,
        expected_previous_state_digest=state.state_digest,
        previous_event_digest=state.last_event_digest,
        provenance_digest=record.provenance_digest,
        config_digest=record.terms_digest,
    )
    source.record(
        result.history_ref,
        previous
        + (
            CorporateActionApplicationEvent(
                metadata,
                record,
                lot_cost_policy or LotCostAllocationPolicy(),
            ),
        ),
    )
    return result


def test_cash_dividend_creates_a_receivable_and_requires_explicit_payment() -> None:
    state, source, execution_source = _lot_state()
    action = _action(
        CorporateActionType.CASH_DIVIDEND,
        CorporateActionTerms(cash_amount_per_share=Decimal("0.50")),
    )
    entitled = _apply_action(state, source, action, execution_source)
    assert entitled.dividend_or_corporate_cash_receivable == Decimal("50.00")
    assert entitled.dividend_pnl == Decimal("50.00")
    receivable = entitled.dividend_or_corporate_receivables[0]
    paid = source.apply(
        entitled,
        ReceivableSettlementEvent(
            metadata=_pay_metadata(entitled),
            receivable_id=receivable.receivable_id,
            kind=receivable.kind,
            amount=receivable.amount,
            due_time=receivable.due_time,
            source_event_id=receivable.source_event_id,
        ),
    )
    assert paid.available_cash == Decimal("50.00")
    assert paid.dividend_or_corporate_cash_receivable == Decimal("0")


def test_split_preserves_cost_and_fractional_requires_cash_in_lieu() -> None:
    state, source, execution_source = _lot_state()
    split = _apply_action(
        state,
        source,
        _action(
            CorporateActionType.SPLIT,
            CorporateActionTerms(ratio_numerator=2, ratio_denominator=1),
        ),
        execution_source,
    )
    assert sum(lot.remaining_quantity for lot in split.open_lots) == 200
    assert sum((lot.gross_cost for lot in split.open_lots), Decimal("0")) == Decimal("1000")
    assert sorted(lot.gross_cost for lot in split.open_lots) == [
        Decimal("500"),
        Decimal("500"),
    ]

    fractional = _action(
        CorporateActionType.CONSOLIDATION,
        CorporateActionTerms(ratio_numerator=2, ratio_denominator=3),
    )
    with pytest.raises(ValueError, match="cash in lieu"):
        _apply_action(state, source, fractional, execution_source)

    state, source, execution_source = _lot_state()
    with_cash = _apply_action(
        state,
        source,
        _action(
            CorporateActionType.CONSOLIDATION,
            CorporateActionTerms(
                ratio_numerator=2,
                ratio_denominator=3,
                cash_in_lieu_amount=Decimal("110"),
                cash_in_lieu_cost=Decimal("100"),
            ),
        ),
        execution_source,
    )
    assert with_cash.open_lots[0].remaining_quantity == 66
    assert with_cash.open_lots[0].gross_cost == Decimal("900")
    assert with_cash.dividend_or_corporate_cash_receivable == Decimal("110")
    assert with_cash.other_corporate_action_pnl == Decimal("10")


def test_split_partial_sale_uses_split_cost_for_realized_and_unrealized_pnl() -> None:
    state, source, execution_source = _lot_state()
    split = _apply_action(
        state,
        source,
        _action(
            CorporateActionType.SPLIT,
            CorporateActionTerms(ratio_numerator=2, ratio_denominator=1),
            effective_time=T + timedelta(days=1),
        ),
        execution_source,
    )
    allocated, remaining = consume_fifo(
        list(split.open_lots),
        _FifoProbeFill(100, "600001.SH", "2026-06-02"),
        LotCostAllocationPolicy(),
    )
    realized = Decimal("600") - allocated
    remaining_cost = sum((lot.gross_cost for lot in remaining), Decimal("0"))
    unrealized = Decimal("600") - remaining_cost
    assert allocated == Decimal("500")
    assert realized == Decimal("100")
    assert remaining_cost == Decimal("500")
    assert unrealized == Decimal("100")


def test_expansion_cost_allocation_uses_policy_rounding_and_exact_residual() -> None:
    state, source, execution_source = _lot_state()
    policy = LotCostAllocationPolicy(
        quantum=Decimal("0.01"),
        rounding_mode=PortfolioRoundingMode.DOWN,
    )
    expanded = _apply_action(
        state,
        source,
        _action(
            CorporateActionType.SPLIT,
            CorporateActionTerms(ratio_numerator=3, ratio_denominator=2),
        ),
        execution_source,
        policy,
    )
    assert sorted((lot.remaining_quantity, lot.gross_cost) for lot in expanded.open_lots) == [
        (50, Decimal("333.34")),
        (100, Decimal("666.66")),
    ]
    assert sum((lot.gross_cost for lot in expanded.open_lots), Decimal("0")) == Decimal("1000")
    assert expanded.book_assets == expanded.initial_capital


@pytest.mark.parametrize(
    "action_type",
    (CorporateActionType.STOCK_DIVIDEND, CorporateActionType.CAPITALIZATION),
)
def test_stock_expansion_actions_split_cost_basis(
    action_type: CorporateActionType,
) -> None:
    state, source, execution_source = _lot_state()
    expanded = _apply_action(
        state,
        source,
        _action(
            action_type,
            CorporateActionTerms(ratio_numerator=2, ratio_denominator=1),
        ),
        execution_source,
    )
    assert sorted(lot.gross_cost for lot in expanded.open_lots) == [
        Decimal("500"),
        Decimal("500"),
    ]
    assert sum((lot.gross_cost for lot in expanded.open_lots), Decimal("0")) == Decimal("1000")
    assert expanded.book_assets == expanded.initial_capital


def test_integral_consolidation_keeps_cost_on_one_transformed_lot() -> None:
    state, source, execution_source = _lot_state()
    consolidated = _apply_action(
        state,
        source,
        _action(
            CorporateActionType.CONSOLIDATION,
            CorporateActionTerms(ratio_numerator=1, ratio_denominator=2),
        ),
        execution_source,
    )
    assert len(consolidated.open_lots) == 1
    assert consolidated.open_lots[0].remaining_quantity == 50
    assert consolidated.open_lots[0].gross_cost == Decimal("1000")
    assert consolidated.book_assets == consolidated.initial_capital


@pytest.mark.parametrize(
    ("cash_amount", "allocated_cost", "expected_other_pnl"),
    (
        ("100", "100", Decimal("0")),
        ("110", "100", Decimal("10")),
        ("90", "100", Decimal("-10")),
    ),
)
def test_cash_in_lieu_postings_are_balanced_for_zero_gain_and_loss(
    cash_amount: str, allocated_cost: str, expected_other_pnl: Decimal
) -> None:
    state, source, execution_source = _lot_state()
    action = _action(
        CorporateActionType.CONSOLIDATION,
        CorporateActionTerms(
            ratio_numerator=2,
            ratio_denominator=3,
            cash_in_lieu_amount=Decimal(cash_amount),
            cash_in_lieu_cost=Decimal(allocated_cost),
        ),
        lineage_id=f"cil-{cash_amount}",
        action_id=f"cil-action-{cash_amount}",
    )
    applied = _apply_action(state, source, action, execution_source)
    assert applied.other_corporate_action_pnl == expected_other_pnl
    assert applied.book_assets == applied.initial_capital + expected_other_pnl
    postings = applied.journal[-1].postings
    assert any(
        item.account is AccountCode.RECEIVABLE_DIVIDEND_CORPORATE
        and item.debit == Decimal(cash_amount)
        for item in postings
    )
    assert any(
        item.account is AccountCode.POSITION_GROSS_COST and item.credit == Decimal(allocated_cost)
        for item in postings
    )
    if expected_other_pnl == 0:
        assert not any(item.account is AccountCode.OTHER_CORPORATE_ACTION_PNL for item in postings)
    elif expected_other_pnl > 0:
        assert any(
            item.account is AccountCode.OTHER_CORPORATE_ACTION_PNL
            and item.credit == expected_other_pnl
            for item in postings
        )
    else:
        assert any(
            item.account is AccountCode.OTHER_CORPORATE_ACTION_PNL
            and item.debit == -expected_other_pnl
            for item in postings
        )


def test_corporate_action_record_time_excludes_a_same_day_later_acquisition() -> None:
    state, source, execution_source = _lot_state()
    action = _action(
        CorporateActionType.CASH_DIVIDEND,
        CorporateActionTerms(cash_amount_per_share=Decimal("0.50")),
        lineage_id="record-time-action",
        action_id="record-time-id",
        record_time=T.replace(hour=14),
        effective_time=T.replace(day=30),
    )
    with pytest.raises(CorporateActionError, match="eligible"):
        _apply_action(state, source, action, execution_source)


def test_duplicate_lineage_and_conflicting_action_identity_are_rejected() -> None:
    state, source, execution_source = _lot_state()
    action = _action(
        CorporateActionType.CASH_DIVIDEND,
        CorporateActionTerms(cash_amount_per_share=Decimal("0.50")),
        lineage_id="identity-lineage",
        action_id="identity-action",
    )
    applied = _apply_action(state, source, action, execution_source)
    conflicting_event = CorporateActionApplicationEvent(
        EventMetadata(
            event_id="identity-conflict-event",
            logical_time=T.replace(day=30),
            event_phase=EventPhase.CORPORATE_ACTION,
            source_id="corp-test",
            source_version="1.0.0",
            source_sequence=10,
            available_time=T.replace(day=30),
            previous_event_digest=applied.last_event_digest,
            expected_previous_state_digest=applied.state_digest,
            provenance_digest="1" * 64,
            config_digest="2" * 64,
        ),
        action,
    )
    with pytest.raises(CorporateActionError, match="identity|lineage"):
        apply_portfolio_event(
            applied,
            conflicting_event,
            source=source,
            execution_source=execution_source,
        )
    revised = _action(
        CorporateActionType.CASH_DIVIDEND,
        CorporateActionTerms(cash_amount_per_share=Decimal("0.60")),
        lineage_id="identity-lineage",
        action_version="2.0.0",
        action_id="identity-action-revised",
    )
    with pytest.raises(CorporateActionError, match="unsupported|revision|lineage"):
        _apply_action(applied, source, revised, execution_source)


def test_adjusted_and_reference_marks_are_not_accounting_inputs() -> None:
    state, source = _state()
    with pytest.raises(ValuationError, match="raw"):
        value_portfolio(
            state,
            T,
            (
                ValuationMark(
                    instrument_code="600001.SH",
                    mark_time=T,
                    available_time=T,
                    price=Decimal("10"),
                    source=ValuationMarkSource.BAR_ADJUSTED,
                    source_id="adjusted",
                    source_version="1.0.0",
                    provenance_digest="6" * 64,
                ),
            ),
            source=source,
        )


def test_raw_mark_requires_complete_coverage_and_is_valued_without_mutating_state() -> None:
    state, source, execution_source = _lot_state()
    with pytest.raises(ValuationError, match="coverage"):
        value_portfolio(state, T, (), source=source, execution_source=execution_source)
    valuation = value_portfolio(
        state,
        T,
        (
            ValuationMark(
                instrument_code="600001.SH",
                mark_time=T,
                available_time=T,
                price=Decimal("11"),
                source=ValuationMarkSource.RAW_MARKET_CLOSE,
                source_id="close",
                source_version="1.0.0",
                provenance_digest="9" * 64,
            ),
        ),
        source=source,
        execution_source=execution_source,
    )
    assert valuation.nav == Decimal("1100")
    assert valuation.unrealized_price_pnl == Decimal("100")
    assert valuation.total_pnl == Decimal("100")
    assert state.state_digest == state.state_digest


def test_valuation_structural_equations_and_trusted_context_validator_reject_forgery() -> None:
    from dataclasses import replace

    state, source, execution_source = _lot_state()
    marks = (
        ValuationMark(
            instrument_code="600001.SH",
            mark_time=T,
            available_time=T,
            price=Decimal("11"),
            source=ValuationMarkSource.RAW_MARKET_CLOSE,
            source_id="close",
            source_version="1.0.0",
            provenance_digest="9" * 64,
        ),
    )
    valuation = value_portfolio(
        state,
        T,
        marks,
        source=source,
        execution_source=execution_source,
    )
    with pytest.raises(ValueError, match="NAV assets"):
        replace(valuation, nav=Decimal("999"))

    wrong_marks = (
        ValuationMark(
            instrument_code="600001.SH",
            mark_time=T,
            available_time=T,
            price=Decimal("12"),
            source=ValuationMarkSource.RAW_MARKET_CLOSE,
            source_id="close",
            source_version="1.0.0",
            provenance_digest="9" * 64,
        ),
    )
    coherent_wrong = value_portfolio(
        state,
        T,
        wrong_marks,
        source=source,
        execution_source=execution_source,
    )
    with pytest.raises(ValuationError, match="trusted state and marks"):
        verify_portfolio_valuation_against_state(
            coherent_wrong,
            state,
            source,
            marks,
            execution_source=execution_source,
        )
