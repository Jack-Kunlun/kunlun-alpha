from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import backtest_core.execution as execution
import pytest
from backtest_core.engine import BacktestOrderIntent, IntentSide, canonical_digest
from backtest_core.execution import (
    EXECUTION_SCHEMA_VERSION,
    BatchMatchResult,
    ExecutableLiquidityLevel,
    ExecutionProvenance,
    ExecutionValidationError,
    FeeComponent,
    FeeSchedule,
    FeeScope,
    Fill,
    InstrumentExecutionRules,
    InstrumentKind,
    LimitLockState,
    MarketExecutionSnapshot,
    MatchResult,
    MatchStatus,
    OddLotSellPolicy,
    OrderType,
    PriceBand,
    PriceSource,
    RejectReason,
    RoundingMode,
    SameDaySellPolicy,
    SellabilitySnapshot,
    SellableLot,
    SessionKind,
    SimulationOrder,
    SlippageModel,
    TradeStatus,
    match_orders,
    revalidate_batch_match_result,
    revalidate_fill,
    revalidate_market_execution_snapshot,
    revalidate_match_result,
    revalidate_simulation_order,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
MATCH_TIME = datetime(2026, 6, 1, 10, 0, tzinfo=SHANGHAI)
MANIFEST_DIGEST = "a" * 64


def _provenance(
    record_id: str = "record-1",
    digest: str = "b" * 64,
    available_time: datetime | None = None,
) -> ExecutionProvenance:
    return ExecutionProvenance(
        source_id="fixture.market",
        source_version="1.0.0",
        record_id=record_id,
        digest=digest,
        available_time=available_time or MATCH_TIME - timedelta(minutes=5),
    )


def _intent(
    *,
    intent_id: str = "intent-1",
    instrument_code: str = "600001.SH",
    side: IntentSide = IntentSide.BUY,
    logical_time: datetime | None = None,
    manifest_digest: str = MANIFEST_DIGEST,
) -> BacktestOrderIntent:
    return BacktestOrderIntent(
        intent_id=intent_id,
        source_signal_id=f"signal:{intent_id}",
        entity_id=instrument_code,
        logical_time=logical_time or MATCH_TIME - timedelta(minutes=1),
        side=side,
        policy_id="fixture.policy",
        policy_version="1.0.0",
        policy_fingerprint="policy-fingerprint-v1",
        manifest_digest=manifest_digest,
    )


def _level(
    level_id: str,
    side: IntentSide,
    price: str,
    quantity: int,
    *,
    price_source: PriceSource = PriceSource.EXECUTABLE_QUOTE,
    available_time: datetime | None = None,
) -> ExecutableLiquidityLevel:
    return ExecutableLiquidityLevel(
        level_id=level_id,
        side=side,
        price=Decimal(price),
        quantity=quantity,
        available_time=available_time or MATCH_TIME - timedelta(minutes=2),
        price_source=price_source,
        source=_provenance(record_id=level_id, digest=(level_id.encode().hex() * 64)[:64]),
    )


def _snapshot(
    *,
    bid_levels: tuple[ExecutableLiquidityLevel, ...] = (),
    ask_levels: tuple[ExecutableLiquidityLevel, ...] = (),
    is_trading_day: bool = True,
    session: SessionKind = SessionKind.CONTINUOUS,
    trade_status: TradeStatus = TradeStatus.OPEN,
    lock_state: LimitLockState = LimitLockState.NONE,
    available_time: datetime | None = None,
    match_time: datetime = MATCH_TIME,
    trading_date: str | None = None,
    price_band: PriceBand | None = None,
    schema_version: str = EXECUTION_SCHEMA_VERSION,
) -> MarketExecutionSnapshot:
    return MarketExecutionSnapshot(
        schema_version=schema_version,
        snapshot_id="snapshot-1",
        instrument_code="600001.SH",
        match_time=match_time,
        observed_time=match_time - timedelta(seconds=30),
        available_time=available_time or match_time - timedelta(seconds=20),
        processing_time=match_time - timedelta(seconds=10),
        trading_date=trading_date or match_time.astimezone(SHANGHAI).date().isoformat(),
        is_trading_day=is_trading_day,
        calendar_id="cn.exchange.calendar",
        calendar_version="2026.1",
        calendar_digest="c" * 64,
        session=session,
        trade_status=trade_status,
        price_band=price_band
        or PriceBand(
            daily_lower=Decimal("1"),
            daily_upper=Decimal("20"),
            dynamic_valid_lower=Decimal("1"),
            dynamic_valid_upper=Decimal("20"),
        ),
        bid_levels=bid_levels,
        ask_levels=ask_levels,
        lock_state=lock_state,
        source=_provenance(record_id="snapshot-1", digest="d" * 64),
    )


def _rules(
    *,
    instrument_code: str = "600001.SH",
    kind: InstrumentKind = InstrumentKind.A_SHARE_STOCK,
    same_day_policy: SameDaySellPolicy = SameDaySellPolicy.T_PLUS_1,
    odd_lot_policy: OddLotSellPolicy = OddLotSellPolicy.DISALLOW,
    available_time: datetime | None = None,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> InstrumentExecutionRules:
    return InstrumentExecutionRules(
        rule_set_id="fixture.rules",
        rule_set_version="1.0.0",
        instrument_code=instrument_code,
        instrument_kind=kind,
        effective_from=effective_from or MATCH_TIME - timedelta(days=1),
        effective_to=effective_to or MATCH_TIME + timedelta(days=1),
        available_time=available_time or MATCH_TIME - timedelta(minutes=5),
        lot_size=100,
        tick_size=Decimal("0.01"),
        buy_min_quantity=100,
        buy_increment=100,
        max_order_quantity=1000,
        odd_lot_sell_policy=odd_lot_policy,
        same_day_sell_policy=same_day_policy,
        supported_order_types=(OrderType.LIMIT_IOC, OrderType.MARKET_PROTECTED_IOC),
        source=_provenance(record_id="rules-1", digest="e" * 64),
    )


def _lot(
    lot_id: str = "lot-1",
    *,
    acquisition_trade_date: str = "2026-05-29",
    sellable_from_trade_date: str = "2026-05-30",
    quantity: int = 1000,
    sellable_quantity: int = 1000,
    available_time: datetime | None = None,
    source_available_time: datetime | None = None,
) -> SellableLot:
    return SellableLot(
        lot_id=lot_id,
        acquisition_trade_date=acquisition_trade_date,
        sellable_from_trade_date=sellable_from_trade_date,
        quantity=quantity,
        sellable_quantity=sellable_quantity,
        available_time=available_time or MATCH_TIME - timedelta(minutes=5),
        source=_provenance(
            record_id=lot_id,
            digest=(lot_id.encode().hex() * 64)[:64],
            available_time=source_available_time,
        ),
    )


def _sellability(
    lots: tuple[SellableLot, ...] = (_lot(),),
    *,
    as_of_time: datetime | None = None,
    available_time: datetime | None = None,
) -> SellabilitySnapshot:
    return SellabilitySnapshot(
        snapshot_id="sellability-1",
        instrument_code="600001.SH",
        as_of_time=as_of_time or MATCH_TIME - timedelta(minutes=1),
        available_time=available_time or MATCH_TIME - timedelta(minutes=2),
        lots=lots,
        source=_provenance(record_id="sellability-1", digest="f" * 64),
    )


def _component(
    code: str = "commission",
    *,
    rate: str = "0.001",
    minimum: str = "0",
    maximum: str | None = None,
    scope: FeeScope = FeeScope.PER_FILL,
    rounding_quantum: str = "0.01",
    rounding_mode: RoundingMode = RoundingMode.HALF_UP,
) -> FeeComponent:
    return FeeComponent(
        code=code,
        applies_sides=(IntentSide.BUY, IntentSide.SELL),
        instrument_kinds=(InstrumentKind.A_SHARE_STOCK, InstrumentKind.EXCHANGE_LISTED_FUND),
        rate=Decimal(rate),
        minimum=Decimal(minimum),
        maximum=Decimal(maximum) if maximum is not None else None,
        rounding_quantum=Decimal(rounding_quantum),
        rounding_mode=rounding_mode,
        scope=scope,
        effective_from=MATCH_TIME - timedelta(days=1),
        effective_to=MATCH_TIME + timedelta(days=1),
        available_time=MATCH_TIME - timedelta(minutes=5),
        source=_provenance(record_id=f"fee:{code}", digest=(code.encode().hex() * 64)[:64]),
    )


def _fee_schedule(*components: FeeComponent | None) -> FeeSchedule:
    selected = tuple(component for component in components if component is not None)
    return FeeSchedule(
        schedule_id="fixture.fees",
        schedule_version="1.0.0",
        effective_from=MATCH_TIME - timedelta(days=1),
        effective_to=MATCH_TIME + timedelta(days=1),
        available_time=MATCH_TIME - timedelta(minutes=5),
        components=selected or (_component(),),
        source=_provenance(record_id="fee-schedule-1", digest="1" * 64),
    )


def _slippage(
    *,
    max_level_participation: str | None = None,
    adverse_level_offset: int = 0,
    skip_level_ids: tuple[str, ...] = (),
    available_time: datetime | None = None,
) -> SlippageModel:
    return SlippageModel(
        model_id="fixture.slippage",
        model_version="1.0.0",
        effective_from=MATCH_TIME - timedelta(days=1),
        effective_to=MATCH_TIME + timedelta(days=1),
        available_time=available_time or MATCH_TIME - timedelta(minutes=5),
        max_level_participation=(
            Decimal(max_level_participation) if max_level_participation is not None else None
        ),
        adverse_level_offset=adverse_level_offset,
        skip_level_ids=skip_level_ids,
        source=_provenance(record_id="slippage-1", digest="2" * 64),
    )


def _order(
    order_id: str = "order-1",
    *,
    side: IntentSide = IntentSide.BUY,
    quantity: int = 100,
    order_type: OrderType = OrderType.LIMIT_IOC,
    limit_price: str | None = "10.00",
    protection_price: str | None = None,
    submitted_at: datetime | None = None,
    submission_sequence: int = 1,
    intent_id: str | None = None,
    instrument_code: str = "600001.SH",
) -> SimulationOrder:
    intent = _intent(
        intent_id=intent_id or f"intent:{order_id}",
        instrument_code=instrument_code,
        side=side,
    )
    return SimulationOrder(
        order_id=order_id,
        source_intent=intent,
        instrument_code=instrument_code,
        side=side,
        manifest_digest=MANIFEST_DIGEST,
        submitted_at=submitted_at or MATCH_TIME - timedelta(seconds=30),
        submission_sequence=submission_sequence,
        quantity=quantity,
        order_type=order_type,
        limit_price=Decimal(limit_price) if limit_price is not None else None,
        protection_price=Decimal(protection_price) if protection_price is not None else None,
    )


def _match(
    orders: tuple[SimulationOrder, ...],
    *,
    snapshot: MarketExecutionSnapshot | None = None,
    rules: InstrumentExecutionRules | None = None,
    sellability: SellabilitySnapshot | None = None,
    fee_schedule: FeeSchedule | None = None,
    slippage: SlippageModel | None = None,
):
    return match_orders(
        orders,
        snapshot or _snapshot(ask_levels=(_level("ask-1", IntentSide.SELL, "10.00", 100),)),
        rules or _rules(),
        sellability,
        fee_schedule or _fee_schedule(),
        slippage or _slippage(),
    )


def _snapshot_digest(snapshot: MarketExecutionSnapshot) -> str:
    return canonical_digest(
        {
            "schema_version": snapshot.schema_version,
            "snapshot_id": snapshot.snapshot_id,
            "instrument_code": snapshot.instrument_code,
            "match_time": snapshot.match_time,
            "observed_time": snapshot.observed_time,
            "available_time": snapshot.available_time,
            "processing_time": snapshot.processing_time,
            "trading_date": snapshot.trading_date,
            "is_trading_day": snapshot.is_trading_day,
            "calendar_id": snapshot.calendar_id,
            "calendar_version": snapshot.calendar_version,
            "calendar_digest": snapshot.calendar_digest,
            "session": snapshot.session,
            "trade_status": snapshot.trade_status,
            "price_band": snapshot.price_band,
            "bid_levels": snapshot.bid_levels,
            "ask_levels": snapshot.ask_levels,
            "lock_state": snapshot.lock_state,
            "source": snapshot.source,
        }
    )


def _fill_digest(fill: Fill) -> str:
    return canonical_digest(
        {
            "fill_id": fill.fill_id,
            "order_id": fill.order_id,
            "source_intent_id": fill.source_intent_id,
            "instrument_code": fill.instrument_code,
            "side": fill.side,
            "quantity": fill.quantity,
            "execution_sequence": fill.execution_sequence,
            "price": fill.price,
            "gross_notional": fill.gross_notional,
            "match_time": fill.match_time,
            "trading_date": fill.trading_date,
            "liquidity_level_id": fill.liquidity_level_id,
            "snapshot_digest": fill.snapshot_digest,
            "rules_digest": fill.rules_digest,
            "fee_schedule_digest": fill.fee_schedule_digest,
            "slippage_model_digest": fill.slippage_model_digest,
            "source_intent_digest": fill.source_intent_digest,
            "source_order_digest": fill.source_order_digest,
            "manifest_digest": fill.manifest_digest,
            "fees": fill.fees,
            "total_fee": fill.total_fee,
            "simulation_only": fill.simulation_only,
            "execution_capability": fill.execution_capability,
        }
    )


def _result_digest(result: MatchResult) -> str:
    return canonical_digest(
        {
            "order_id": result.order_id,
            "status": result.status,
            "requested_quantity": result.requested_quantity,
            "filled_quantity": result.filled_quantity,
            "remaining_quantity": result.remaining_quantity,
            "fills": result.fills,
            "reject_reason": result.reject_reason,
            "reject_detail": result.reject_detail,
            "order_digest": result.order_digest,
            "source_intent_id": result.source_intent_id,
            "instrument_code": result.instrument_code,
            "side": result.side,
            "manifest_digest": result.manifest_digest,
            "snapshot_digest": result.snapshot_digest,
            "rules_digest": result.rules_digest,
            "fee_schedule_digest": result.fee_schedule_digest,
            "slippage_model_digest": result.slippage_model_digest,
            "skipped_level_ids": result.skipped_level_ids,
        }
    )


def _batch_digest(batch: BatchMatchResult) -> str:
    return canonical_digest(
        {
            "matching_schema_version": batch.matching_schema_version,
            "backtest_manifest_digest": batch.backtest_manifest_digest,
            "orders_digest": batch.orders_digest,
            "snapshot_digest": batch.snapshot_digest,
            "rules_digest": batch.rules_digest,
            "sellability_digest": batch.sellability_digest,
            "calendar_digest": batch.calendar_digest,
            "fee_schedule_digest": batch.fee_schedule_digest,
            "slippage_model_digest": batch.slippage_model_digest,
            "source_dataset_digest": batch.source_dataset_digest,
            "code_config_digest": batch.code_config_digest,
            "results": batch.results,
            "skipped_level_ids": batch.skipped_level_ids,
        }
    )


def test_limit_buy_consumes_real_ask_and_records_traceability() -> None:
    result = _match((_order(),))

    assert result.results[0].status is MatchStatus.FILLED
    fill = result.results[0].fills[0]
    assert fill.quantity == 100
    assert fill.price == Decimal("10.00")
    assert fill.liquidity_level_id == "ask-1"
    assert fill.snapshot_digest == result.snapshot_digest
    assert fill.rules_digest == result.rules_digest
    assert fill.manifest_digest == MANIFEST_DIGEST
    assert fill.simulation_only is True


def test_execution_provenance_requires_available_time() -> None:
    provenance_constructor = cast(Callable[..., ExecutionProvenance], ExecutionProvenance)
    with pytest.raises((TypeError, ExecutionValidationError)):
        provenance_constructor(
            source_id="fixture.market",
            source_version="1.0.0",
            record_id="missing-availability",
            digest="b" * 64,
        )
    with pytest.raises(ExecutionValidationError, match="available_time"):
        provenance_constructor(
            source_id="fixture.market",
            source_version="1.0.0",
            record_id="none-availability",
            digest="b" * 64,
            available_time=None,
        )


def test_snapshot_rejects_unsupported_schema_version() -> None:
    with pytest.raises(ExecutionValidationError, match="schema_version"):
        _snapshot(schema_version="market-execution-snapshot-v1")


def test_trusted_replay_accepts_unmodified_result_and_executable_quote() -> None:
    orders = (_order(),)
    snapshot = _snapshot(ask_levels=(_level("ask-replay", IntentSide.SELL, "10.00", 100),))
    rules = _rules()
    fee_schedule = _fee_schedule()
    slippage = _slippage()
    candidate = match_orders(orders, snapshot, rules, None, fee_schedule, slippage)

    assert candidate.results[0].fills[0].price == Decimal("10.00")
    assert (
        execution.verify_batch_match_result_against_inputs(
            candidate,
            orders,
            snapshot,
            rules,
            None,
            fee_schedule,
            slippage,
        )
        == candidate
    )


def test_trusted_replay_rejects_rehashed_price_mutation() -> None:
    orders = (_order(),)
    snapshot = _snapshot(ask_levels=(_level("ask-replay", IntentSide.SELL, "10.00", 100),))
    rules = _rules()
    fee_schedule = _fee_schedule()
    slippage = _slippage()
    candidate = match_orders(orders, snapshot, rules, None, fee_schedule, slippage)
    original_fill = candidate.results[0].fills[0]
    forged_fill = replace(
        original_fill,
        price=Decimal("10.01"),
        gross_notional=Decimal("1001.00"),
    )
    forged_result = replace(candidate.results[0], fills=(forged_fill,))
    forged_batch = replace(candidate, results=(forged_result,))

    revalidate_batch_match_result(forged_batch)
    with pytest.raises(ExecutionValidationError, match="trusted replay"):
        execution.verify_batch_match_result_against_inputs(
            forged_batch,
            orders,
            snapshot,
            rules,
            None,
            fee_schedule,
            slippage,
        )


def test_trusted_replay_rejects_rehashed_liquidity_level_mutation() -> None:
    orders = (_order(),)
    snapshot = _snapshot(ask_levels=(_level("ask-replay", IntentSide.SELL, "10.00", 100),))
    rules = _rules()
    fee_schedule = _fee_schedule()
    slippage = _slippage()
    candidate = match_orders(orders, snapshot, rules, None, fee_schedule, slippage)
    forged_fill = replace(candidate.results[0].fills[0], liquidity_level_id="ask-forged")
    forged_result = replace(candidate.results[0], fills=(forged_fill,))
    forged_batch = replace(candidate, results=(forged_result,))

    revalidate_batch_match_result(forged_batch)
    with pytest.raises(ExecutionValidationError, match="trusted replay"):
        execution.verify_batch_match_result_against_inputs(
            forged_batch,
            orders,
            snapshot,
            rules,
            None,
            fee_schedule,
            slippage,
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("instrument_code", "000001.SZ"),
        ("side", IntentSide.SELL),
        ("manifest_digest", "9" * 64),
        ("submitted_at", MATCH_TIME - timedelta(minutes=2)),
    ),
)
def test_order_source_intent_mismatch_is_rejected(field_name: str, value: object) -> None:
    intent = _intent()
    kwargs: dict[str, object] = {
        "order_id": "mismatch",
        "source_intent": intent,
        "instrument_code": "600001.SH",
        "side": IntentSide.BUY,
        "manifest_digest": MANIFEST_DIGEST,
        "submitted_at": MATCH_TIME - timedelta(seconds=30),
        "submission_sequence": 1,
        "quantity": 100,
        "order_type": OrderType.LIMIT_IOC,
        "limit_price": Decimal("10.00"),
        "protection_price": None,
    }
    if field_name == "submitted_at":
        intent = replace(intent, logical_time=MATCH_TIME - timedelta(seconds=1))
        kwargs["source_intent"] = intent
        kwargs["submitted_at"] = value
    else:
        kwargs[field_name] = value
    with pytest.raises(ExecutionValidationError):
        SimulationOrder(**kwargs)  # type: ignore[arg-type]


def test_duplicate_order_id_is_structural_error_and_permutation_is_canonical() -> None:
    first = _order("order-a", submission_sequence=1)
    second = _order("order-b", submission_sequence=2)
    left = _match((first, second))
    right = _match((second, first))
    assert left.batch_digest == right.batch_digest
    assert left.results == right.results
    with pytest.raises(ExecutionValidationError, match="duplicate order_id"):
        _match((first, replace(first, submission_sequence=2)))


@pytest.mark.parametrize(
    "field_name", ("snapshot", "rules", "sellability", "fee_schedule", "slippage")
)
def test_future_point_in_time_input_fails_closed(field_name: str) -> None:
    with pytest.raises(ExecutionValidationError, match="available_time"):
        if field_name == "snapshot":
            _match(
                (_order(),),
                snapshot=replace(_snapshot(), available_time=MATCH_TIME + timedelta(seconds=1)),
            )
        elif field_name == "rules":
            _match(
                (_order(),),
                rules=replace(_rules(), available_time=MATCH_TIME + timedelta(seconds=1)),
            )
        elif field_name == "sellability":
            _match(
                (_order(side=IntentSide.SELL),),
                sellability=replace(
                    _sellability(), available_time=MATCH_TIME + timedelta(seconds=1)
                ),
            )
        elif field_name == "fee_schedule":
            _match(
                (_order(),),
                fee_schedule=replace(
                    _fee_schedule(), available_time=MATCH_TIME + timedelta(seconds=1)
                ),
            )
        else:
            _match(
                (_order(),),
                slippage=replace(_slippage(), available_time=MATCH_TIME + timedelta(seconds=1)),
            )


def test_sellability_as_of_time_must_not_exceed_match_time() -> None:
    sellability = _sellability(
        as_of_time=MATCH_TIME + timedelta(seconds=1),
        available_time=MATCH_TIME - timedelta(minutes=2),
    )
    with pytest.raises(ExecutionValidationError, match="as_of_time"):
        _match(
            (_order(side=IntentSide.SELL, limit_price="9"),),
            snapshot=_snapshot(bid_levels=(_level("bid-future-as-of", IntentSide.BUY, "9", 100),)),
            sellability=sellability,
        )


def test_future_lot_and_provenance_in_valid_sellability_graph_fail_closed() -> None:
    future_time = MATCH_TIME + timedelta(seconds=1)
    sellability = _sellability(
        lots=(
            _lot(
                quantity=100,
                sellable_quantity=100,
                available_time=future_time,
                source_available_time=future_time,
            ),
        ),
        as_of_time=MATCH_TIME + timedelta(seconds=2),
        available_time=MATCH_TIME - timedelta(minutes=2),
    )
    with pytest.raises(ExecutionValidationError, match="match_time|as_of_time"):
        _match(
            (_order(side=IntentSide.SELL, limit_price="9"),),
            snapshot=_snapshot(bid_levels=(_level("bid-future-lot", IntentSide.BUY, "9", 100),)),
            sellability=sellability,
        )


@pytest.mark.parametrize(
    ("field_name", "value", "reason"),
    (
        ("is_trading_day", False, RejectReason.NON_TRADING_DAY),
        ("session", SessionKind.AUCTION, RejectReason.UNSUPPORTED_SESSION),
        ("trade_status", TradeStatus.SUSPENDED, RejectReason.SUSPENDED),
        ("trade_status", TradeStatus.HALTED, RejectReason.HALTED),
        ("trade_status", TradeStatus.CLOSED, RejectReason.CLOSED),
    ),
)
def test_calendar_session_and_trade_status_fail_closed(
    field_name: str, value: object, reason: RejectReason
) -> None:
    snapshot = replace(
        _snapshot(ask_levels=(_level("ask-1", IntentSide.SELL, "10", 100),)),
        **{field_name: value},
    )
    result = _match((_order(),), snapshot=snapshot)
    assert result.results[0].status is MatchStatus.REJECTED
    assert result.results[0].reject_reason is reason


@pytest.mark.parametrize(
    ("quantity", "reason"),
    (
        (50, RejectReason.BUY_MIN_QUANTITY),
        (150, RejectReason.BUY_INCREMENT),
        (1100, RejectReason.MAX_ORDER_QUANTITY),
    ),
)
def test_buy_lot_increment_and_max_quantity(quantity: int, reason: RejectReason) -> None:
    result = _match((_order(quantity=quantity),))
    assert result.results[0].status is MatchStatus.REJECTED
    assert result.results[0].reject_reason is reason


def test_sell_max_order_quantity_is_rejected_before_matching() -> None:
    order = _order("sell-over-cap", side=IntentSide.SELL, quantity=1100, limit_price="9")
    result = _match(
        (order,),
        snapshot=_snapshot(bid_levels=(_level("bid-cap", IntentSide.BUY, "9", 1100),)),
        sellability=_sellability(lots=(_lot(quantity=2000, sellable_quantity=2000),)),
    )
    assert result.results[0].status is MatchStatus.REJECTED
    assert result.results[0].reject_reason is RejectReason.MAX_ORDER_QUANTITY


def test_snapshot_requires_canonical_liquidity_order_and_tie_break() -> None:
    ask_a = _level("ask-a", IntentSide.SELL, "10", 100)
    ask_b = _level("ask-b", IntentSide.SELL, "10", 100)
    bid_a = _level("bid-a", IntentSide.BUY, "9", 100)
    bid_b = _level("bid-b", IntentSide.BUY, "9", 100)

    with pytest.raises(ExecutionValidationError, match="canonical"):
        _snapshot(ask_levels=(ask_b, ask_a))
    with pytest.raises(ExecutionValidationError, match="canonical"):
        _snapshot(bid_levels=(bid_b, bid_a))
    with pytest.raises(ExecutionValidationError, match="canonical"):
        _snapshot(
            ask_levels=(
                _level("ask-high", IntentSide.SELL, "10.01", 100),
                _level("ask-low", IntentSide.SELL, "10.00", 100),
            )
        )
    with pytest.raises(ExecutionValidationError, match="canonical"):
        _snapshot(
            bid_levels=(
                _level("bid-low", IntentSide.BUY, "8.99", 100),
                _level("bid-high", IntentSide.BUY, "9.00", 100),
            )
        )

    canonical = _snapshot(
        bid_levels=(bid_a, bid_b),
        ask_levels=(ask_a, ask_b),
    )
    assert tuple(level.level_id for level in canonical.bid_levels) == ("bid-a", "bid-b")
    assert tuple(level.level_id for level in canonical.ask_levels) == ("ask-a", "ask-b")


def test_rehashed_forged_nested_price_band_is_rejected() -> None:
    snapshot = _snapshot()
    object.__setattr__(snapshot.price_band, "daily_upper", Decimal("19"))
    object.__setattr__(snapshot, "snapshot_digest", _snapshot_digest(snapshot))

    with pytest.raises(ExecutionValidationError):
        revalidate_market_execution_snapshot(snapshot)


def test_sell_odd_lot_policy_allows_only_full_sellable_remainder() -> None:
    sellability = _sellability(lots=(_lot(quantity=250, sellable_quantity=250),))
    legal = _order(
        "legal-remainder",
        side=IntentSide.SELL,
        quantity=250,
        limit_price="9.00",
    )
    illegal = _order(
        "illegal-remainder",
        side=IntentSide.SELL,
        quantity=150,
        limit_price="9.00",
    )
    snapshot = _snapshot(bid_levels=(_level("bid-1", IntentSide.BUY, "9.00", 250),))
    rules = _rules(odd_lot_policy=OddLotSellPolicy.FULL_SELLABLE_REMAINDER)
    result = _match((illegal, legal), snapshot=snapshot, rules=rules, sellability=sellability)
    by_id = {item.order_id: item for item in result.results}
    assert by_id["legal-remainder"].status is MatchStatus.FILLED
    assert by_id["illegal-remainder"].reject_reason is RejectReason.ODD_LOT


@pytest.mark.parametrize(
    ("limit_price", "reason"),
    (
        ("10.005", RejectReason.TICK_SIZE),
        ("0.99", RejectReason.DAILY_PRICE_BAND),
        ("19.99", RejectReason.DYNAMIC_PRICE_RANGE),
    ),
)
def test_order_price_must_be_tick_aligned_and_inside_bands(
    limit_price: str, reason: RejectReason
) -> None:
    band = PriceBand(
        daily_lower=Decimal("1"),
        daily_upper=Decimal("20"),
        dynamic_valid_lower=Decimal("5"),
        dynamic_valid_upper=Decimal("15"),
    )
    result = _match((_order(limit_price=limit_price),), snapshot=_snapshot(price_band=band))
    assert result.results[0].status is MatchStatus.REJECTED
    assert result.results[0].reject_reason is reason


def test_market_protected_order_requires_protection_price() -> None:
    order = _order(
        order_type=OrderType.MARKET_PROTECTED_IOC,
        limit_price=None,
        protection_price=None,
    )
    result = _match((order,))
    assert result.results[0].status is MatchStatus.REJECTED
    assert result.results[0].reject_reason is RejectReason.PROTECTION_PRICE


def test_missing_liquidity_is_unfilled_without_synthetic_price() -> None:
    result = _match((_order(),), snapshot=_snapshot())
    assert result.results[0].status is MatchStatus.UNFILLED
    assert result.results[0].reject_reason is RejectReason.MISSING_EXECUTABLE_LIQUIDITY
    assert result.results[0].fills == ()


def test_explicit_limit_lock_blocks_only_locked_side_and_unlocked_limit_can_fill() -> None:
    locked = _snapshot(
        ask_levels=(),
        lock_state=LimitLockState.UPPER_LOCKED,
        price_band=PriceBand(Decimal("1"), Decimal("10"), Decimal("1"), Decimal("10")),
    )
    locked_result = _match((_order(limit_price="10"),), snapshot=locked)
    assert locked_result.results[0].reject_reason is RejectReason.UPPER_LOCKED

    unlocked = _snapshot(
        ask_levels=(_level("ask-limit", IntentSide.SELL, "10", 100),),
        lock_state=LimitLockState.NONE,
        price_band=PriceBand(Decimal("1"), Decimal("10"), Decimal("1"), Decimal("10")),
    )
    unlocked_result = _match((_order(limit_price="10"),), snapshot=unlocked)
    assert unlocked_result.results[0].status is MatchStatus.FILLED


def test_t_plus_one_blocks_same_day_but_explicit_t_plus_zero_allows_it() -> None:
    same_day_lot = _lot(
        acquisition_trade_date="2026-06-01",
        sellable_from_trade_date="2026-06-01",
        quantity=100,
        sellable_quantity=100,
    )
    order = _order("same-day", side=IntentSide.SELL, quantity=100, limit_price="9")
    snapshot = _snapshot(bid_levels=(_level("bid-1", IntentSide.BUY, "9", 100),))
    blocked = _match(
        (order,),
        snapshot=snapshot,
        rules=_rules(same_day_policy=SameDaySellPolicy.T_PLUS_1),
        sellability=_sellability((same_day_lot,)),
    )
    assert blocked.results[0].reject_reason is RejectReason.T_PLUS_ONE_NOT_SELLABLE

    allowed = _match(
        (order,),
        snapshot=snapshot,
        rules=_rules(
            kind=InstrumentKind.EXCHANGE_LISTED_FUND,
            same_day_policy=SameDaySellPolicy.T_PLUS_0,
        ),
        sellability=_sellability((same_day_lot,)),
    )
    assert allowed.results[0].status is MatchStatus.FILLED


def test_insufficient_sellable_quantity_rejects_whole_order() -> None:
    order = _order("too-large-sell", side=IntentSide.SELL, quantity=200, limit_price="9")
    result = _match(
        (order,),
        snapshot=_snapshot(bid_levels=(_level("bid-1", IntentSide.BUY, "9", 100),)),
        sellability=_sellability(lots=(_lot(quantity=100, sellable_quantity=100),)),
    )
    assert result.results[0].status is MatchStatus.REJECTED
    assert result.results[0].reject_reason is RejectReason.INSUFFICIENT_SELLABLE_QUANTITY


def test_batch_sellability_is_temporarily_decremented_by_priority() -> None:
    first = _order(
        "sell-first", side=IntentSide.SELL, quantity=100, limit_price="9", submission_sequence=1
    )
    second = _order(
        "sell-second", side=IntentSide.SELL, quantity=100, limit_price="9", submission_sequence=2
    )
    result = _match(
        (second, first),
        snapshot=_snapshot(bid_levels=(_level("bid-1", IntentSide.BUY, "9", 200),)),
        sellability=_sellability(lots=(_lot(quantity=100, sellable_quantity=100),)),
    )
    by_id = {item.order_id: item for item in result.results}
    assert by_id["sell-first"].status is MatchStatus.FILLED
    assert by_id["sell-second"].reject_reason is RejectReason.INSUFFICIENT_SELLABLE_QUANTITY


def test_multi_level_partial_fill_never_oversells_a_level() -> None:
    snapshot = _snapshot(
        ask_levels=(
            _level("ask-1", IntentSide.SELL, "10.00", 100),
            _level("ask-2", IntentSide.SELL, "10.01", 100),
        )
    )
    result = _match((_order(quantity=300, limit_price="10.01"),), snapshot=snapshot)
    match = result.results[0]
    assert match.status is MatchStatus.PARTIALLY_FILLED
    assert tuple(fill.quantity for fill in match.fills) == (100, 100)
    assert tuple(fill.price for fill in match.fills) == (Decimal("10.00"), Decimal("10.01"))


def test_price_time_priority_uses_cap_then_submission_time_then_sequence_then_id() -> None:
    low = _order("low", quantity=100, limit_price="11.00", submission_sequence=1)
    high = _order("high", quantity=100, limit_price="12.00", submission_sequence=99)
    snapshot = _snapshot(
        ask_levels=(
            _level("ask-1", IntentSide.SELL, "10.00", 100),
            _level("ask-2", IntentSide.SELL, "11.00", 100),
        )
    )
    result = _match((low, high), snapshot=snapshot)
    by_id = {item.order_id: item for item in result.results}
    assert by_id["high"].fills[0].price == Decimal("10.00")
    assert by_id["low"].fills[0].price == Decimal("11.00")


def test_slippage_only_selects_existing_levels_and_skipped_best_level_stays_unavailable() -> None:
    snapshot = _snapshot(
        ask_levels=(
            _level("ask-best", IntentSide.SELL, "10.00", 100),
            _level("ask-next", IntentSide.SELL, "10.01", 100),
        )
    )
    first = _order("first", quantity=100, limit_price="10.01", submission_sequence=1)
    second = _order("second", quantity=100, limit_price="10.01", submission_sequence=2)
    result = _match(
        (second, first),
        snapshot=snapshot,
        slippage=_slippage(adverse_level_offset=1),
    )
    by_id = {item.order_id: item for item in result.results}
    assert by_id["first"].fills[0].liquidity_level_id == "ask-next"
    assert by_id["second"].status is MatchStatus.UNFILLED
    assert "ask-best" in result.skipped_level_ids
    assert all(fill.price != Decimal("10.00") for item in result.results for fill in item.fills)


def test_max_level_participation_limits_shared_existing_liquidity() -> None:
    result = _match(
        (_order(quantity=100),),
        slippage=_slippage(max_level_participation="0.5"),
    )
    assert result.results[0].status is MatchStatus.PARTIALLY_FILLED
    assert result.results[0].filled_quantity == 50


@pytest.mark.parametrize(
    "price_source",
    (PriceSource.NAV, PriceSource.INAV, PriceSource.BAR_RAW, PriceSource.BAR_ADJUSTED),
)
def test_non_executable_price_sources_cannot_form_liquidity_or_fill(
    price_source: PriceSource,
) -> None:
    with pytest.raises(ExecutionValidationError, match="EXECUTABLE_QUOTE"):
        _level("bad-source", IntentSide.SELL, "10", 100, price_source=price_source)


def test_per_order_minimum_is_applied_once_and_allocated_across_fills() -> None:
    fee = _fee_schedule(_component(scope=FeeScope.PER_ORDER, minimum="5", rate="0"))
    snapshot = _snapshot(
        ask_levels=(
            _level("ask-1", IntentSide.SELL, "10.00", 100),
            _level("ask-2", IntentSide.SELL, "10.01", 100),
        )
    )
    result = _match(
        (_order(quantity=200, limit_price="10.01"),), snapshot=snapshot, fee_schedule=fee
    )
    fills = result.results[0].fills
    assert sum((fill.total_fee for fill in fills), Decimal("0")) == Decimal("5.00")
    assert sum(
        (fee_item.allocated_amount for fill in fills for fee_item in fill.fees), Decimal("0")
    ) == Decimal("5.00")
    assert all(
        fee_item.rounded_amount == fee_item.allocated_amount
        for fill in fills
        for fee_item in fill.fees
    )
    assert sum(
        (fee_item.rounded_amount for fill in fills for fee_item in fill.fees), Decimal("0")
    ) == Decimal("5.00")


def test_per_order_residual_uses_execution_order_and_replays_deterministically() -> None:
    orders = (_order(quantity=200, limit_price="10.01"),)
    snapshot = _snapshot(
        ask_levels=(
            _level("ask-1", IntentSide.SELL, "10.00", 100),
            _level("ask-2", IntentSide.SELL, "10.01", 100),
        )
    )
    rules = _rules()
    fee_schedule = _fee_schedule(_component(scope=FeeScope.PER_ORDER, rate="0.0005"))
    slippage = _slippage()

    result = match_orders(orders, snapshot, rules, None, fee_schedule, slippage)
    fills = result.results[0].fills
    fee_items = tuple(fill.fees[0] for fill in fills)

    assert tuple(fill.execution_sequence for fill in fills) == (0, 1)
    fill_ids = tuple(fill.fill_id for fill in fills)
    assert fill_ids[0] > fill_ids[1]
    assert tuple(item.unrounded_amount for item in fee_items) == (
        Decimal("0.500000"),
        Decimal("0.500500"),
    )
    assert tuple(item.rounded_amount for item in fee_items) == (
        Decimal("0.49"),
        Decimal("0.51"),
    )
    assert tuple(item.allocated_amount for item in fee_items) == (
        Decimal("0.49"),
        Decimal("0.51"),
    )
    assert fills[1].execution_sequence == 1
    assert fills[1].fees[0].allocated_amount == Decimal("0.51")

    replayed = execution.verify_batch_match_result_against_inputs(
        result,
        orders,
        snapshot,
        rules,
        None,
        fee_schedule,
        slippage,
    )
    assert replayed == result
    assert tuple(fill.fees[0].allocated_amount for fill in replayed.results[0].fills) == (
        Decimal("0.49"),
        Decimal("0.51"),
    )


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    (("0.005", None), ("0", "0.005")),
)
def test_fee_bounds_must_be_aligned_to_rounding_quantum(minimum: str, maximum: str | None) -> None:
    with pytest.raises(ExecutionValidationError, match="multiple|aligned"):
        _component(minimum=minimum, maximum=maximum)


def test_per_fill_maximum_is_applied_to_each_fill() -> None:
    fee = _fee_schedule(_component(rate="1", maximum="5", scope=FeeScope.PER_FILL))
    snapshot = _snapshot(
        ask_levels=(
            _level("ask-1", IntentSide.SELL, "10.00", 100),
            _level("ask-2", IntentSide.SELL, "10.01", 100),
        )
    )
    result = _match(
        (_order(quantity=200, limit_price="10.01"),),
        snapshot=snapshot,
        fee_schedule=fee,
    )

    assert tuple(fill.total_fee for fill in result.results[0].fills) == (
        Decimal("5.00"),
        Decimal("5.00"),
    )


def test_per_order_maximum_is_applied_once_and_allocated_across_fills() -> None:
    fee = _fee_schedule(_component(rate="1", maximum="5", scope=FeeScope.PER_ORDER))
    snapshot = _snapshot(
        ask_levels=(
            _level("ask-1", IntentSide.SELL, "10.00", 100),
            _level("ask-2", IntentSide.SELL, "10.01", 100),
        )
    )
    result = _match(
        (_order(quantity=200, limit_price="10.01"),),
        snapshot=snapshot,
        fee_schedule=fee,
    )
    fills = result.results[0].fills

    assert sum((fill.total_fee for fill in fills), Decimal("0")) == Decimal("5.00")
    assert all(
        fee_item.rounded_amount == fee_item.allocated_amount
        for fill in fills
        for fee_item in fill.fees
    )


@pytest.mark.parametrize(
    ("rounding_mode", "expected"),
    (
        (RoundingMode.DOWN, Decimal("1.00")),
        (RoundingMode.UP, Decimal("1.01")),
        (RoundingMode.HALF_UP, Decimal("1.01")),
        (RoundingMode.HALF_EVEN, Decimal("1.00")),
    ),
)
def test_aligned_fee_bounds_hold_for_every_rounding_mode(
    rounding_mode: RoundingMode, expected: Decimal
) -> None:
    fee = _fee_schedule(
        _component(
            rate="0.001",
            minimum="1.00",
            maximum="1.01",
            rounding_mode=rounding_mode,
        )
    )
    result = _match(
        (_order(quantity=100, limit_price="10.05"),),
        snapshot=_snapshot(ask_levels=(_level("ask-rounding", IntentSide.SELL, "10.05", 100),)),
        fee_schedule=fee,
    )
    fee_item = result.results[0].fills[0].fees[0]

    assert fee_item.rounded_amount == expected
    assert Decimal("1.00") <= fee_item.rounded_amount <= Decimal("1.01")


def test_per_fill_minimum_is_applied_for_each_fill() -> None:
    fee = _fee_schedule(_component(scope=FeeScope.PER_FILL, minimum="5", rate="0"))
    snapshot = _snapshot(
        ask_levels=(
            _level("ask-1", IntentSide.SELL, "10.00", 100),
            _level("ask-2", IntentSide.SELL, "10.01", 100),
        )
    )
    result = _match(
        (_order(quantity=200, limit_price="10.01"),), snapshot=snapshot, fee_schedule=fee
    )
    assert sum((fill.total_fee for fill in result.results[0].fills), Decimal("0")) == Decimal(
        "10.00"
    )


def test_forged_nominal_types_and_recomputed_digests_are_rejected() -> None:
    order = _order()
    object.__setattr__(order, "quantity", 200)
    with pytest.raises(ExecutionValidationError):
        revalidate_simulation_order(order)

    valid_result = _match((_order(),))
    object.__setattr__(valid_result, "batch_digest", "3" * 64)
    with pytest.raises(ExecutionValidationError):
        revalidate_batch_match_result(valid_result)

    fill = _match((_order(),)).results[0].fills[0]
    object.__setattr__(fill, "fill_digest", "4" * 64)
    with pytest.raises(ExecutionValidationError):
        revalidate_fill(fill)

    match_result = _match((_order(),)).results[0]
    object.__setattr__(match_result, "result_digest", "5" * 64)
    with pytest.raises(ExecutionValidationError):
        revalidate_match_result(match_result)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("source_intent_id", "forged-intent"),
        ("instrument_code", "000001.SZ"),
        ("side", IntentSide.SELL),
        ("source_order_digest", "6" * 64),
        ("manifest_digest", "7" * 64),
        ("snapshot_digest", "8" * 64),
        ("rules_digest", "9" * 64),
        ("fee_schedule_digest", "1" * 64),
        ("slippage_model_digest", "2" * 64),
    ),
)
def test_rehashed_forged_fill_context_is_rejected(field_name: str, value: object) -> None:
    result = _match((_order(),)).results[0]
    fill = result.fills[0]
    object.__setattr__(fill, field_name, value)
    object.__setattr__(fill, "fill_digest", _fill_digest(fill))
    object.__setattr__(result, "result_digest", _result_digest(result))

    with pytest.raises(ExecutionValidationError):
        revalidate_match_result(result)


def test_rehashed_forged_match_result_context_is_rejected_by_batch() -> None:
    batch = _match((_order(),))
    result = batch.results[0]
    object.__setattr__(result, "snapshot_digest", "3" * 64)
    object.__setattr__(result, "result_digest", _result_digest(result))
    object.__setattr__(batch, "batch_digest", _batch_digest(batch))

    with pytest.raises(ExecutionValidationError):
        revalidate_batch_match_result(batch)


def test_filled_result_requires_a_positive_fill_and_no_rejection_metadata() -> None:
    result = _match((_order(),)).results[0]
    object.__setattr__(result, "status", MatchStatus.FILLED)
    object.__setattr__(result, "fills", ())
    object.__setattr__(result, "filled_quantity", 0)
    object.__setattr__(result, "remaining_quantity", 0)
    object.__setattr__(result, "reject_reason", None)
    object.__setattr__(result, "reject_detail", None)
    object.__setattr__(result, "result_digest", _result_digest(result))

    with pytest.raises(ExecutionValidationError):
        revalidate_match_result(result)


def test_partial_result_rejects_reason_and_duplicate_fills() -> None:
    partial = _match(
        (_order(quantity=200, limit_price="10.01"),),
        snapshot=_snapshot(
            ask_levels=(
                _level("ask-1", IntentSide.SELL, "10", 100),
                _level("ask-2", IntentSide.SELL, "10.01", 100),
            )
        ),
    ).results[0]
    object.__setattr__(partial, "reject_reason", RejectReason.MISSING_EXECUTABLE_LIQUIDITY)
    object.__setattr__(partial, "reject_detail", "must be absent")
    object.__setattr__(partial, "result_digest", _result_digest(partial))
    with pytest.raises(ExecutionValidationError):
        revalidate_match_result(partial)

    duplicate = _match(
        (_order(quantity=200, limit_price="10.01"),),
        snapshot=_snapshot(
            ask_levels=(
                _level("ask-1", IntentSide.SELL, "10", 100),
                _level("ask-2", IntentSide.SELL, "10.01", 100),
            )
        ),
    ).results[0]
    first_fill = duplicate.fills[0]
    object.__setattr__(duplicate, "fills", (first_fill, first_fill))
    object.__setattr__(duplicate, "result_digest", _result_digest(duplicate))
    with pytest.raises(ExecutionValidationError):
        revalidate_match_result(duplicate)

    reordered = _match(
        (_order(quantity=200, limit_price="10.01"),),
        snapshot=_snapshot(
            ask_levels=(
                _level("ask-1", IntentSide.SELL, "10", 100),
                _level("ask-2", IntentSide.SELL, "10.01", 100),
            )
        ),
    ).results[0]
    object.__setattr__(reordered, "fills", tuple(reversed(reordered.fills)))
    object.__setattr__(reordered, "result_digest", _result_digest(reordered))
    with pytest.raises(ExecutionValidationError):
        revalidate_match_result(reordered)


def test_execution_source_has_no_runtime_or_live_execution_escape_hatches() -> None:
    source_dir = Path(__file__).parents[2] / "src" / "backtest_core" / "execution"
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_dir.glob("*.py"))
    lowered = source.lower()
    for forbidden in (
        "uuid",
        "random",
        "time.time",
        ".now(",
        "broker",
        "qmt",
        "account",
        "credential",
        "network",
    ):
        assert forbidden not in lowered
    assert "datetime.now" not in inspect.getsource(match_orders)


def test_combined_market_protected_t_plus_zero_fee_and_slippage_scenario() -> None:
    same_day_lot = _lot(
        acquisition_trade_date="2026-06-01",
        sellable_from_trade_date="2026-06-01",
        quantity=200,
        sellable_quantity=200,
    )
    order = _order(
        "combined",
        side=IntentSide.SELL,
        quantity=200,
        order_type=OrderType.MARKET_PROTECTED_IOC,
        limit_price=None,
        protection_price="9.00",
    )
    snapshot = _snapshot(
        bid_levels=(
            _level("bid-best", IntentSide.BUY, "9.10", 100),
            _level("bid-next", IntentSide.BUY, "9.00", 200),
        )
    )
    result = _match(
        (order,),
        snapshot=snapshot,
        rules=_rules(
            kind=InstrumentKind.EXCHANGE_LISTED_FUND,
            same_day_policy=SameDaySellPolicy.T_PLUS_0,
        ),
        sellability=_sellability((same_day_lot,)),
        slippage=_slippage(adverse_level_offset=1),
    )
    match = result.results[0]
    assert match.status is MatchStatus.FILLED
    assert tuple(fill.price for fill in match.fills) == (Decimal("9.00"),)
    assert match.total_fee > Decimal("0")
