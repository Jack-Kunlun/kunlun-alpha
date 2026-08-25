from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import backtest_core.portfolio as portfolio_api
import pytest
from backtest_core import BacktestOrderIntent, IntentSide
from backtest_core.execution import (
    BatchMatchResult,
    ExecutableLiquidityLevel,
    ExecutionProvenance,
    FeeComponent,
    FeeSchedule,
    FeeScope,
    InstrumentExecutionRules,
    InstrumentKind,
    LimitLockState,
    MarketExecutionSnapshot,
    OrderType,
    PriceBand,
    RoundingMode,
    SameDaySellPolicy,
    SellabilitySnapshot,
    SessionKind,
    SimulationOrder,
    SlippageModel,
    TradeStatus,
)
from backtest_core.execution.matcher import match_orders
from backtest_core.portfolio import (
    ZERO_DIGEST,
    BuyCashReservation,
    BuyCashReservationEvent,
    EventMetadata,
    EventPhase,
    ExecutionArtifactRef,
    ExecutionReplayBundle,
    ExecutionSettlementEvent,
    InitialCapitalEvent,
    LotCostAllocationPolicy,
    NextTradingDateResolution,
    PortfolioState,
    ReceivableSettlementEvent,
    TrustedExecutionInputs,
    TrustedReplayError,
    apply_portfolio_event,
    export_sellability_snapshot,
    settle_execution_bundle,
    verify_execution_bundle_against_source,
    verify_portfolio_state_from_source,
)
from backtest_core.portfolio.accounting import consume_fifo
from backtest_core.portfolio.models import PortfolioEvent, PortfolioHistoryRef, PortfolioLot

SHANGHAI = ZoneInfo("Asia/Shanghai")
T = datetime(2026, 5, 29, 9, 30, tzinfo=SHANGHAI)
MANIFEST = "d" * 64


@dataclass(frozen=True)
class _FifoProbeFill:
    instrument_code: str
    quantity: int
    trading_date: str


class _ExecutionSource:
    def __init__(self) -> None:
        self.artifacts: dict[str, TrustedExecutionInputs] = {}

    def resolve_execution_artifact(
        self, artifact_ref: ExecutionArtifactRef
    ) -> TrustedExecutionInputs:
        return self.artifacts[artifact_ref.artifact_id]


EXECUTION_SOURCE = _ExecutionSource()


class _PortfolioSource:
    def __init__(self) -> None:
        self.tapes: dict[str, tuple[PortfolioEvent, ...]] = {"portfolio-genesis": ()}
        self.versions: dict[tuple[str, str, int], tuple[PortfolioEvent, ...]] = {}

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
            execution_source=EXECUTION_SOURCE,
        )
        if result is not state:
            self.record(result.history_ref, previous + (event,))
        return result


def _source(record: str = "source-1") -> ExecutionProvenance:
    return ExecutionProvenance(
        source_id="fixture",
        source_version="1.0.0",
        record_id=record,
        digest="e" * 64,
        available_time=T,
    )


def _order(
    side: IntentSide = IntentSide.BUY,
    quantity: int = 100,
    order_id: str = "order-1",
) -> SimulationOrder:
    intent = BacktestOrderIntent(
        intent_id=f"intent-{order_id}",
        source_signal_id=f"signal-{order_id}",
        entity_id="600001.SH",
        logical_time=T,
        side=side,
        policy_id="policy-1",
        policy_version="1.0.0",
        policy_fingerprint="f" * 64,
        manifest_digest=MANIFEST,
    )
    return SimulationOrder(
        order_id=order_id,
        source_intent=intent,
        instrument_code="600001.SH",
        side=side,
        manifest_digest=MANIFEST,
        submitted_at=T,
        submission_sequence=1,
        quantity=quantity,
        order_type=OrderType.LIMIT_IOC,
        limit_price=Decimal("10.00"),
        protection_price=None,
    )


def _bundle(
    order: SimulationOrder | None = None,
    sellability: SellabilitySnapshot | None = None,
    liquidity_quantity: int | None = None,
    same_day_policy: SameDaySellPolicy = SameDaySellPolicy.T_PLUS_0,
    is_trading_day: bool = True,
    next_trading_date_resolution: NextTradingDateResolution | None = None,
    order_id: str = "order-1",
) -> ExecutionReplayBundle:
    typed_order = order or _order(order_id=order_id)
    available_quantity = typed_order.quantity if liquidity_quantity is None else liquidity_quantity
    levels: tuple[ExecutableLiquidityLevel, ...] = ()
    if available_quantity > 0:
        levels = (
            ExecutableLiquidityLevel(
                level_id="ask-1",
                side=IntentSide.SELL if typed_order.side is IntentSide.BUY else IntentSide.BUY,
                price=Decimal("10.00"),
                quantity=available_quantity,
                available_time=T,
                price_source=__import__(
                    "backtest_core.execution", fromlist=["PriceSource"]
                ).PriceSource.EXECUTABLE_QUOTE,
                source=_source("level-1"),
            ),
        )
    snapshot = MarketExecutionSnapshot(
        schema_version="execution-v1",
        snapshot_id="snapshot-1",
        instrument_code="600001.SH",
        match_time=T,
        observed_time=T,
        available_time=T,
        processing_time=T,
        trading_date="2026-05-29",
        is_trading_day=is_trading_day,
        calendar_id="cn",
        calendar_version="1.0.0",
        calendar_digest="1" * 64,
        session=SessionKind.CONTINUOUS,
        trade_status=TradeStatus.OPEN,
        price_band=PriceBand(None, None, None, None),
        bid_levels=levels if typed_order.side is IntentSide.SELL else (),
        ask_levels=levels if typed_order.side is IntentSide.BUY else (),
        lock_state=LimitLockState.NONE,
        source=_source("snapshot-1"),
    )
    rules = InstrumentExecutionRules(
        rule_set_id="rules-1",
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
        odd_lot_sell_policy=__import__(
            "backtest_core.execution", fromlist=["OddLotSellPolicy"]
        ).OddLotSellPolicy.DISALLOW,
        same_day_sell_policy=same_day_policy,
        supported_order_types=(OrderType.LIMIT_IOC,),
        source=_source("rules-1"),
    )
    fee = FeeComponent(
        code="commission",
        applies_sides=(IntentSide.BUY, IntentSide.SELL),
        instrument_kinds=(InstrumentKind.A_SHARE_STOCK,),
        rate=Decimal("0.001"),
        minimum=Decimal("0"),
        maximum=None,
        rounding_quantum=Decimal("0.01"),
        rounding_mode=RoundingMode.HALF_UP,
        scope=FeeScope.PER_FILL,
        effective_from=T.replace(hour=9),
        effective_to=None,
        available_time=T,
        source=_source("fee-1"),
    )
    schedule = FeeSchedule(
        schedule_id="fees-1",
        schedule_version="1.0.0",
        effective_from=T.replace(hour=9),
        effective_to=None,
        available_time=T,
        components=(fee,),
        source=_source("schedule-1"),
    )
    slippage = SlippageModel(
        model_id="slippage-1",
        model_version="1.0.0",
        effective_from=T.replace(hour=9),
        effective_to=None,
        available_time=T,
        max_level_participation=None,
        adverse_level_offset=0,
        skip_level_ids=(),
        source=_source("slippage-1"),
    )
    candidate = match_orders((typed_order,), snapshot, rules, sellability, schedule, slippage)
    artifact_id = f"artifact-{typed_order.order_id}"
    inputs = TrustedExecutionInputs(
        artifact_id=artifact_id,
        orders=(typed_order,),
        snapshot=snapshot,
        rules=rules,
        sellability=sellability,
        fee_schedule=schedule,
        slippage_model=slippage,
        external_source_digest=candidate.source_dataset_digest,
        external_config_digest=candidate.code_config_digest,
        next_trading_date_resolution=next_trading_date_resolution,
    )
    EXECUTION_SOURCE.artifacts[artifact_id] = inputs
    return ExecutionReplayBundle(
        artifact_ref=ExecutionArtifactRef(artifact_id, inputs.input_digest),
        candidate=candidate,
    )


def _inputs(bundle: ExecutionReplayBundle) -> TrustedExecutionInputs:
    return EXECUTION_SOURCE.artifacts[bundle.artifact_ref.artifact_id]


def _metadata(
    state: PortfolioState, event_id: str, phase: EventPhase, when: datetime
) -> EventMetadata:
    return EventMetadata(
        event_id=event_id,
        logical_time=when,
        event_phase=phase,
        source_id="replay-test",
        source_version="1.0.0",
        source_sequence=0,
        available_time=when,
        previous_event_digest=state.last_event_digest,
        expected_previous_state_digest=state.state_digest,
        provenance_digest="1" * 64,
        config_digest="2" * 64,
    )


def _settle(
    source: _PortfolioSource,
    state: PortfolioState,
    bundle: ExecutionReplayBundle,
    event_id: str,
) -> PortfolioState:
    metadata = _metadata(state, event_id, EventPhase.EXECUTION, T)
    previous = source.resolve_portfolio_history(state.history_ref)
    result = settle_execution_bundle(
        state,
        bundle,
        source=source,
        execution_source=EXECUTION_SOURCE,
        metadata=metadata,
    )
    event = ExecutionSettlementEvent(metadata, bundle, LotCostAllocationPolicy())
    source.record(result.history_ref, previous + (event,))
    return result


def _settled_buy_state() -> tuple[PortfolioState, _PortfolioSource]:
    source = _PortfolioSource()
    state = PortfolioState.empty()
    state = source.apply(
        state,
        InitialCapitalEvent(
            metadata=EventMetadata(
                event_id="open-buy",
                logical_time=T,
                event_phase=EventPhase.OPENING,
                source_id="replay-test",
                source_version="1.0.0",
                source_sequence=0,
                available_time=T,
                expected_previous_state_digest=state.state_digest,
                previous_event_digest=ZERO_DIGEST,
                provenance_digest="1" * 64,
                config_digest="2" * 64,
            ),
            amount=Decimal("10000"),
        ),
    )
    bundle = _bundle(order_id="settled-buy")
    state = source.apply(
        state,
        BuyCashReservationEvent(
            metadata=_metadata(state, "reserve-buy", EventPhase.RESERVATION, T),
            reservation=BuyCashReservation(
                order_id="settled-buy",
                order_digest=_inputs(bundle).orders[0].order_digest,
                fee_schedule_digest=_inputs(bundle).fee_schedule.fee_schedule_digest,
                artifact_id=bundle.artifact_ref.artifact_id,
                execution_input_digest=bundle.artifact_ref.expected_input_digest,
                policy_id="reserve-policy",
                policy_version="1.0.0",
                policy_digest="3" * 64,
                reservation_logical_time=T,
                maximum_debit=Decimal("1001"),
            ),
        ),
    )
    return _settle(source, state, bundle, "settle-buy"), source


def test_valid_bundle_is_verified_before_buy_settlement_and_releases_reserve() -> None:
    source = _PortfolioSource()
    state = PortfolioState.empty()
    state = source.apply(
        state,
        InitialCapitalEvent(
            metadata=EventMetadata(
                event_id="open",
                logical_time=T,
                event_phase=EventPhase.OPENING,
                source_id="replay-test",
                source_version="1.0.0",
                source_sequence=0,
                available_time=T,
                expected_previous_state_digest=state.state_digest,
                previous_event_digest=ZERO_DIGEST,
                provenance_digest="1" * 64,
                config_digest="2" * 64,
            ),
            amount=Decimal("10000"),
        ),
    )
    bundle = _bundle(order_id="valid-buy")
    state = source.apply(
        state,
        BuyCashReservationEvent(
            metadata=_metadata(state, "reserve", EventPhase.RESERVATION, T),
            reservation=BuyCashReservation(
                order_id="valid-buy",
                order_digest=_inputs(bundle).orders[0].order_digest,
                fee_schedule_digest=_inputs(bundle).fee_schedule.fee_schedule_digest,
                artifact_id=bundle.artifact_ref.artifact_id,
                execution_input_digest=bundle.artifact_ref.expected_input_digest,
                policy_id="reserve-policy",
                policy_version="1.0.0",
                policy_digest="3" * 64,
                reservation_logical_time=T,
                maximum_debit=Decimal("1001"),
            ),
        ),
    )
    settled = _settle(source, state, bundle, "settle")
    assert settled.lots[0].remaining_quantity == 100
    assert settled.lots[0].gross_cost == Decimal("1000")
    assert settled.available_cash == Decimal("8999")
    assert settled.fee_pnl == Decimal("-1.00")
    assert settled.active_buy_reservations == ()


def test_rehashed_candidate_is_rejected_by_trusted_replay_and_state_is_unchanged() -> None:
    bundle = _bundle(order_id="forged-candidate")
    forged = object.__new__(BatchMatchResult)
    for name in (
        "matching_schema_version",
        "backtest_manifest_digest",
        "orders_digest",
        "snapshot_digest",
        "rules_digest",
        "sellability_digest",
        "calendar_digest",
        "fee_schedule_digest",
        "slippage_model_digest",
        "source_dataset_digest",
        "code_config_digest",
        "results",
        "skipped_level_ids",
        "batch_digest",
    ):
        object.__setattr__(forged, name, getattr(bundle.candidate, name))
    object.__setattr__(forged, "results", ())
    object.__setattr__(forged, "batch_digest", "0" * 64)
    with pytest.raises(TrustedReplayError):
        verify_execution_bundle_against_source(
            ExecutionReplayBundle(bundle.artifact_ref, forged),
            EXECUTION_SOURCE,
        )


def test_sell_consumes_persistent_fifo_lot_creates_receivable_and_settles_explicitly() -> None:
    state, source = _settled_buy_state()
    sellability = export_sellability_snapshot(
        state,
        "600001.SH",
        T,
        source=source,
        execution_source=EXECUTION_SOURCE,
    )
    sell_bundle = _bundle(
        _order(IntentSide.SELL, order_id="sell-order"),
        sellability,
        order_id="sell-order",
    )
    sold = _settle(source, state, sell_bundle, "settle-sell")
    assert sold.open_lots == ()
    assert sold.sale_cash_receivable == Decimal("999.00")
    assert sold.realized_price_pnl == Decimal("0")
    assert sold.fee_pnl == Decimal("-2.00")
    receivable = sold.sale_receivables[0]
    paid = source.apply(
        sold,
        ReceivableSettlementEvent(
            metadata=_metadata(sold, "sale-payment", EventPhase.RECEIVABLE_SETTLEMENT, T),
            receivable_id=receivable.receivable_id,
            kind=receivable.kind,
            amount=receivable.amount,
            due_time=receivable.due_time,
            source_event_id=receivable.source_event_id,
        ),
    )
    assert paid.available_cash == Decimal("9998")
    assert paid.sale_cash_receivable == Decimal("0")


def test_sellability_snapshot_from_another_state_is_rejected() -> None:
    state, source = _settled_buy_state()
    empty_source = _PortfolioSource()
    empty_snapshot = export_sellability_snapshot(
        PortfolioState.empty(), "600001.SH", T, source=empty_source
    )
    sell_bundle = _bundle(
        _order(IntentSide.SELL, order_id="sell-mismatch"),
        empty_snapshot,
        order_id="sell-mismatch",
    )
    with pytest.raises(TrustedReplayError, match="sellability"):
        _settle(source, state, sell_bundle, "settle-zbad-sell")


def test_terminal_partial_unfilled_and_rejected_buys_release_unused_reserve() -> None:
    cases = (
        (
            _bundle(_order(quantity=200, order_id="terminal-partial"), liquidity_quantity=100),
            100,
            Decimal("8999"),
        ),
        (_bundle(_order(order_id="terminal-empty"), liquidity_quantity=0), 0, Decimal("10000")),
        (
            _bundle(_order(order_id="terminal-rejected"), is_trading_day=False),
            0,
            Decimal("10000"),
        ),
    )
    for index, (bundle, expected_quantity, expected_cash) in enumerate(cases):
        source = _PortfolioSource()
        state = PortfolioState.empty()
        state = source.apply(
            state,
            InitialCapitalEvent(
                metadata=EventMetadata(
                    event_id=f"open-terminal-{index}",
                    logical_time=T,
                    event_phase=EventPhase.OPENING,
                    source_id="replay-test",
                    source_version="1.0.0",
                    source_sequence=0,
                    available_time=T,
                    expected_previous_state_digest=state.state_digest,
                    previous_event_digest=ZERO_DIGEST,
                    provenance_digest="1" * 64,
                    config_digest="2" * 64,
                ),
                amount=Decimal("10000"),
            ),
        )
        order = _inputs(bundle).orders[0]
        maximum_debit = Decimal(order.quantity * 10) + Decimal("2")
        state = source.apply(
            state,
            BuyCashReservationEvent(
                metadata=_metadata(state, f"reserve-terminal-{index}", EventPhase.RESERVATION, T),
                reservation=BuyCashReservation(
                    order_id=order.order_id,
                    order_digest=order.order_digest,
                    fee_schedule_digest=_inputs(bundle).fee_schedule.fee_schedule_digest,
                    artifact_id=bundle.artifact_ref.artifact_id,
                    execution_input_digest=bundle.artifact_ref.expected_input_digest,
                    policy_id="reserve-policy",
                    policy_version="1.0.0",
                    policy_digest="3" * 64,
                    reservation_logical_time=T,
                    maximum_debit=maximum_debit,
                ),
            ),
        )
        settled = _settle(source, state, bundle, f"settle-terminal-{index}")
        assert sum(lot.remaining_quantity for lot in settled.open_lots) == expected_quantity
        assert settled.available_cash == expected_cash
        assert settled.active_buy_reservations == ()


def test_t_plus_1_uses_explicit_next_trading_date_resolution() -> None:
    resolution = NextTradingDateResolution(
        calendar_id="cn",
        calendar_version="1.0.0",
        calendar_digest="1" * 64,
        trading_date="2026-05-29",
        next_trading_date="2026-06-01",
        available_time=T,
        match_time=T,
    )
    bundle = _bundle(
        _order(order_id="tplus1-buy"),
        same_day_policy=SameDaySellPolicy.T_PLUS_1,
        next_trading_date_resolution=resolution,
        order_id="tplus1-buy",
    )
    source = _PortfolioSource()
    state = PortfolioState.empty()
    state = source.apply(
        state,
        InitialCapitalEvent(
            metadata=EventMetadata(
                event_id="open-t-plus-1",
                logical_time=T,
                event_phase=EventPhase.OPENING,
                source_id="replay-test",
                source_version="1.0.0",
                source_sequence=0,
                available_time=T,
                expected_previous_state_digest=state.state_digest,
                previous_event_digest=ZERO_DIGEST,
                provenance_digest="1" * 64,
                config_digest="2" * 64,
            ),
            amount=Decimal("10000"),
        ),
    )
    order = _inputs(bundle).orders[0]
    state = source.apply(
        state,
        BuyCashReservationEvent(
            metadata=_metadata(state, "reserve-t-plus-1", EventPhase.RESERVATION, T),
            reservation=BuyCashReservation(
                order_id=order.order_id,
                order_digest=order.order_digest,
                fee_schedule_digest=_inputs(bundle).fee_schedule.fee_schedule_digest,
                artifact_id=bundle.artifact_ref.artifact_id,
                execution_input_digest=bundle.artifact_ref.expected_input_digest,
                policy_id="reserve-policy",
                policy_version="1.0.0",
                policy_digest="3" * 64,
                reservation_logical_time=T,
                maximum_debit=Decimal("1001"),
            ),
        ),
    )
    settled = _settle(source, state, bundle, "settle-t-plus-1")
    assert settled.open_lots[0].sellable_from_trade_date == "2026-06-01"


def test_t_plus_1_calendar_lineage_is_bound_to_the_execution_snapshot() -> None:
    resolution = NextTradingDateResolution(
        calendar_id="cn",
        calendar_version="1.0.0",
        calendar_digest="1" * 64,
        trading_date="2026-05-29",
        next_trading_date="2026-06-01",
        available_time=T,
        match_time=T,
    )
    bundle = _bundle(
        _order(order_id="calendar-bound"),
        same_day_policy=SameDaySellPolicy.T_PLUS_1,
        next_trading_date_resolution=resolution,
        order_id="calendar-bound",
    )
    inputs = _inputs(bundle)
    for field_name, value in (
        ("calendar_id", "other-calendar"),
        ("calendar_version", "2.0.0"),
        ("calendar_digest", "2" * 64),
        ("trading_date", "2026-05-28"),
    ):
        with pytest.raises(TrustedReplayError, match="calendar|trading date"):
            TrustedExecutionInputs(
                artifact_id=inputs.artifact_id,
                orders=inputs.orders,
                snapshot=inputs.snapshot,
                rules=inputs.rules,
                sellability=inputs.sellability,
                fee_schedule=inputs.fee_schedule,
                slippage_model=inputs.slippage_model,
                external_source_digest=inputs.external_source_digest,
                external_config_digest=inputs.external_config_digest,
                next_trading_date_resolution=replace(
                    resolution,
                    **{field_name: value},
                ),
            )
    with pytest.raises(ValueError, match="available"):
        NextTradingDateResolution(
            calendar_id="cn",
            calendar_version="1.0.0",
            calendar_digest="1" * 64,
            trading_date="2026-05-29",
            next_trading_date="2026-06-01",
            available_time=T.replace(hour=10),
            match_time=T,
        )


def test_public_state_mutation_requires_an_injected_history_source() -> None:
    state = PortfolioState.empty()
    event = InitialCapitalEvent(
        metadata=EventMetadata(
            event_id="source-required",
            logical_time=T,
            event_phase=EventPhase.OPENING,
            source_id="replay-test",
            source_version="1.0.0",
            source_sequence=0,
            available_time=T,
            expected_previous_state_digest=state.state_digest,
            previous_event_digest=ZERO_DIGEST,
            provenance_digest="1" * 64,
            config_digest="2" * 64,
        ),
        amount=Decimal("1000"),
    )
    with pytest.raises(TrustedReplayError, match="source"):
        apply_portfolio_event(state, event)


def test_rehashed_state_is_rejected_against_the_original_event_tape() -> None:
    state, source = _settled_buy_state()
    forged = replace(state, available_cash=Decimal("8998"), fee_pnl=Decimal("-2"))
    with pytest.raises(TrustedReplayError, match="reconstructed"):
        verify_portfolio_state_from_source(
            forged,
            source,
            execution_source=EXECUTION_SOURCE,
        )


def test_candidate_with_rehashed_substituted_snapshot_is_rejected_by_original_artifact() -> None:
    bundle = _bundle(order_id="artifact-original")
    inputs = _inputs(bundle)
    level = inputs.snapshot.ask_levels[0]
    substituted_snapshot = replace(
        inputs.snapshot,
        ask_levels=(replace(level, price=Decimal("11.00")),),
    )
    substituted_candidate = match_orders(
        inputs.orders,
        substituted_snapshot,
        inputs.rules,
        inputs.sellability,
        inputs.fee_schedule,
        inputs.slippage_model,
    )
    substituted_bundle = ExecutionReplayBundle(bundle.artifact_ref, substituted_candidate)
    with pytest.raises(TrustedReplayError, match="candidate"):
        verify_execution_bundle_against_source(substituted_bundle, EXECUTION_SOURCE)


def test_duplicate_sell_terminal_result_cannot_mutate_cash_or_lots_twice() -> None:
    state, source = _settled_buy_state()
    sellability = export_sellability_snapshot(
        state,
        "600001.SH",
        T,
        source=source,
        execution_source=EXECUTION_SOURCE,
    )
    bundle = _bundle(
        _order(IntentSide.SELL, order_id="duplicate-sell"),
        sellability,
        order_id="duplicate-sell",
    )
    sold = _settle(source, state, bundle, "z-duplicate-sell-first")
    with pytest.raises(TrustedReplayError, match="already"):
        _settle(source, sold, bundle, "z-duplicate-sell-second")
    assert sold.open_lots == ()
    assert sold.sale_cash_receivable == Decimal("999.00")


def test_duplicate_terminal_unfilled_result_cannot_release_or_reserve_cash_twice() -> None:
    bundle = _bundle(_order(order_id="duplicate-unfilled"), liquidity_quantity=0)
    source = _PortfolioSource()
    state = PortfolioState.empty()
    state = source.apply(
        state,
        InitialCapitalEvent(
            metadata=EventMetadata(
                event_id="duplicate-unfilled-open",
                logical_time=T,
                event_phase=EventPhase.OPENING,
                source_id="replay-test",
                source_version="1.0.0",
                source_sequence=0,
                available_time=T,
                previous_event_digest=ZERO_DIGEST,
                expected_previous_state_digest=state.state_digest,
                provenance_digest="1" * 64,
                config_digest="2" * 64,
            ),
            amount=Decimal("10000"),
        ),
    )
    order = _inputs(bundle).orders[0]
    state = source.apply(
        state,
        BuyCashReservationEvent(
            metadata=_metadata(state, "duplicate-unfilled-reserve", EventPhase.RESERVATION, T),
            reservation=BuyCashReservation(
                order_id=order.order_id,
                order_digest=order.order_digest,
                fee_schedule_digest=_inputs(bundle).fee_schedule.fee_schedule_digest,
                artifact_id=bundle.artifact_ref.artifact_id,
                execution_input_digest=bundle.artifact_ref.expected_input_digest,
                policy_id="reserve-policy",
                policy_version="1.0.0",
                policy_digest="3" * 64,
                reservation_logical_time=T,
                maximum_debit=Decimal("1001"),
            ),
        ),
    )
    settled = _settle(source, state, bundle, "duplicate-unfilled-first")
    with pytest.raises(TrustedReplayError, match="already"):
        _settle(source, settled, bundle, "duplicate-unfilled-second")
    assert settled.available_cash == Decimal("10000")
    assert settled.frozen_cash == Decimal("0")
    assert settled.open_lots == ()


def test_fifo_two_one_share_probe_and_three_lot_partial_are_one_pass() -> None:
    lots = [
        PortfolioLot(
            lot_id="fifo-1",
            instrument_code="600001.SH",
            acquisition_trade_date="2026-05-26",
            acquisition_time=datetime(2026, 5, 26, 9, 30, tzinfo=SHANGHAI),
            sellable_from_trade_date="2026-05-29",
            remaining_quantity=1,
            gross_cost=Decimal("1.00"),
            available_time=T,
            source_order_id="fifo-order-1",
            source_fill_ids=("fifo-fill-1",),
            lineage_digest="a" * 64,
        ),
        PortfolioLot(
            lot_id="fifo-2",
            instrument_code="600001.SH",
            acquisition_trade_date="2026-05-27",
            acquisition_time=datetime(2026, 5, 27, 9, 30, tzinfo=SHANGHAI),
            sellable_from_trade_date="2026-05-29",
            remaining_quantity=1,
            gross_cost=Decimal("2.00"),
            available_time=T,
            source_order_id="fifo-order-2",
            source_fill_ids=("fifo-fill-2",),
            lineage_digest="b" * 64,
        ),
        PortfolioLot(
            lot_id="fifo-3",
            instrument_code="600001.SH",
            acquisition_trade_date="2026-05-28",
            acquisition_time=datetime(2026, 5, 28, 9, 30, tzinfo=SHANGHAI),
            sellable_from_trade_date="2026-05-29",
            remaining_quantity=4,
            gross_cost=Decimal("8.00"),
            available_time=T,
            source_order_id="fifo-order-3",
            source_fill_ids=("fifo-fill-3",),
            lineage_digest="c" * 64,
        ),
    ]
    allocated, remaining = consume_fifo(
        lots,
        _FifoProbeFill(quantity=2, instrument_code="600001.SH", trading_date="2026-05-29"),
        LotCostAllocationPolicy(),
    )
    assert allocated == Decimal("3.00")
    assert [lot.lot_id for lot in remaining] == ["fifo-3"]
    assert remaining[0].remaining_quantity == 4

    allocated, remaining = consume_fifo(
        remaining,
        _FifoProbeFill(quantity=4, instrument_code="600001.SH", trading_date="2026-05-29"),
        LotCostAllocationPolicy(),
    )
    assert allocated == Decimal("8.00")
    assert remaining == []


def test_public_portfolio_api_does_not_export_raw_replay_shortcuts() -> None:
    assert not hasattr(portfolio_api, "replay_portfolio")
    assert not hasattr(portfolio_api, "verify_checkpoint")
    assert not hasattr(portfolio_api, "verify_portfolio_checkpoint")
