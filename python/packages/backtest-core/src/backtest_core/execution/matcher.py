"""Pure deterministic matching, slippage selection, and fee calculation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
    localcontext,
)

from backtest_core.engine import IntentSide, canonical_digest

from .models import (
    MATCHING_SCHEMA_VERSION,
    BatchMatchResult,
    ExecutableLiquidityLevel,
    ExecutionValidationError,
    FeeBreakdown,
    FeeComponent,
    FeeSchedule,
    FeeScope,
    Fill,
    InstrumentExecutionRules,
    LimitLockState,
    MarketExecutionSnapshot,
    MatchResult,
    MatchStatus,
    OrderType,
    RejectReason,
    RoundingMode,
    SameDaySellPolicy,
    SellabilitySnapshot,
    SimulationOrder,
    SlippageModel,
    TradeStatus,
    revalidate_batch_match_result,
    revalidate_fee_schedule,
    revalidate_instrument_execution_rules,
    revalidate_market_execution_snapshot,
    revalidate_sellability_snapshot,
    revalidate_simulation_order,
    revalidate_slippage_model,
)


def _covers(start: datetime, end: datetime | None, point: datetime) -> bool:
    return start <= point and (end is None or point < end)


def _tick_aligned(price: Decimal, tick_size: Decimal) -> bool:
    return (price % tick_size) == 0


def _global_reject_reason(snapshot: MarketExecutionSnapshot) -> RejectReason | None:
    if not snapshot.is_trading_day:
        return RejectReason.NON_TRADING_DAY
    if snapshot.session.value != "CONTINUOUS":
        return RejectReason.UNSUPPORTED_SESSION
    return {
        TradeStatus.SUSPENDED: RejectReason.SUSPENDED,
        TradeStatus.HALTED: RejectReason.HALTED,
        TradeStatus.CLOSED: RejectReason.CLOSED,
    }.get(snapshot.trade_status)


def _effective_price(order: SimulationOrder) -> Decimal | None:
    if order.order_type is OrderType.LIMIT_IOC:
        return order.limit_price
    return order.protection_price


def _price_reason(order: SimulationOrder, rules: InstrumentExecutionRules) -> RejectReason | None:
    effective_price = _effective_price(order)
    if order.order_type is OrderType.MARKET_PROTECTED_IOC and effective_price is None:
        return RejectReason.PROTECTION_PRICE
    if order.order_type is OrderType.LIMIT_IOC and effective_price is None:
        return RejectReason.LIMIT_PRICE
    if effective_price is None:
        return RejectReason.REFERENCE_PRICE
    if not _tick_aligned(effective_price, rules.tick_size):
        return RejectReason.TICK_SIZE
    return None


def _band_reason(price: Decimal, snapshot: MarketExecutionSnapshot) -> RejectReason | None:
    band = snapshot.price_band
    if band.daily_lower is not None and price < band.daily_lower:
        return RejectReason.DAILY_PRICE_BAND
    if band.daily_upper is not None and price > band.daily_upper:
        return RejectReason.DAILY_PRICE_BAND
    if band.dynamic_valid_lower is not None and price < band.dynamic_valid_lower:
        return RejectReason.DYNAMIC_PRICE_RANGE
    if band.dynamic_valid_upper is not None and price > band.dynamic_valid_upper:
        return RejectReason.DYNAMIC_PRICE_RANGE
    return None


def _static_order_reason(
    order: SimulationOrder,
    snapshot: MarketExecutionSnapshot,
    rules: InstrumentExecutionRules,
) -> RejectReason | None:
    global_reason = _global_reject_reason(snapshot)
    if global_reason is not None:
        return global_reason
    if order.side is IntentSide.BUY and snapshot.lock_state is LimitLockState.UPPER_LOCKED:
        return RejectReason.UPPER_LOCKED
    if order.side is IntentSide.SELL and snapshot.lock_state is LimitLockState.LOWER_LOCKED:
        return RejectReason.LOWER_LOCKED
    if order.submitted_at > snapshot.match_time:
        return RejectReason.FUTURE_DATA
    if order.order_type not in rules.supported_order_types:
        return RejectReason.UNSUPPORTED_ORDER_TYPE
    reason = _price_reason(order, rules)
    if reason is not None:
        return reason
    effective_price = _effective_price(order)
    assert effective_price is not None
    reason = _band_reason(effective_price, snapshot)
    if reason is not None:
        return reason
    if order.quantity > rules.max_order_quantity:
        return RejectReason.MAX_ORDER_QUANTITY
    if order.side is IntentSide.BUY:
        if order.quantity < rules.buy_min_quantity:
            return RejectReason.BUY_MIN_QUANTITY
        if (order.quantity - rules.buy_min_quantity) % rules.buy_increment != 0:
            return RejectReason.BUY_INCREMENT
    return None


def _eligible_lots(
    sellability: SellabilitySnapshot,
    rules: InstrumentExecutionRules,
    trading_date: str,
) -> tuple[tuple[tuple[str, int], ...], int]:
    eligible: list[tuple[str, int]] = []
    for lot in sellability.lots:
        if lot.sellable_from_trade_date > trading_date:
            continue
        if (
            rules.same_day_sell_policy is SameDaySellPolicy.T_PLUS_1
            and lot.acquisition_trade_date >= trading_date
        ):
            continue
        if lot.sellable_quantity > 0:
            eligible.append((lot.lot_id, lot.sellable_quantity))
    return tuple(sorted(eligible)), sum(quantity for _, quantity in eligible)


def _sell_reason(
    order: SimulationOrder,
    rules: InstrumentExecutionRules,
    sellability: SellabilitySnapshot | None,
    remaining_lots: dict[str, int],
    trading_date: str,
) -> RejectReason | None:
    if sellability is None:
        return RejectReason.SELLABILITY_SNAPSHOT_MISSING
    eligible_lots, _ = _eligible_lots(sellability, rules, trading_date)
    eligible_ids = {lot_id for lot_id, _ in eligible_lots}
    eligible_quantity = sum(remaining_lots.get(lot_id, 0) for lot_id in eligible_ids)
    if eligible_quantity == 0:
        same_day_lot = any(
            lot.acquisition_trade_date == trading_date and lot.sellable_quantity > 0
            for lot in sellability.lots
        )
        if rules.same_day_sell_policy is SameDaySellPolicy.T_PLUS_1 and same_day_lot:
            return RejectReason.T_PLUS_ONE_NOT_SELLABLE
        return RejectReason.INSUFFICIENT_SELLABLE_QUANTITY
    if order.quantity > eligible_quantity:
        return RejectReason.INSUFFICIENT_SELLABLE_QUANTITY
    if order.quantity % rules.lot_size != 0:
        if rules.odd_lot_sell_policy.value == "DISALLOW":
            return RejectReason.ODD_LOT
        if order.quantity != eligible_quantity:
            return RejectReason.ODD_LOT
    return None


def _priority_key(order: SimulationOrder) -> tuple[Decimal, datetime, int, str]:
    effective_price = _effective_price(order)
    assert effective_price is not None
    price_key = -effective_price if order.side is IntentSide.BUY else effective_price
    return (
        price_key,
        order.submitted_at.astimezone(UTC),
        order.submission_sequence,
        order.order_id,
    )


def _rounding_mode(mode: RoundingMode):
    return {
        RoundingMode.DOWN: ROUND_DOWN,
        RoundingMode.UP: ROUND_UP,
        RoundingMode.HALF_UP: ROUND_HALF_UP,
        RoundingMode.HALF_EVEN: ROUND_HALF_EVEN,
    }[mode]


def _rounded(value: Decimal, component: FeeComponent) -> Decimal:
    return value.quantize(
        component.rounding_quantum, rounding=_rounding_mode(component.rounding_mode)
    )


def _bounded(value: Decimal, component: FeeComponent) -> Decimal:
    if component.minimum is not None and value < component.minimum:
        value = component.minimum
    if component.maximum is not None and value > component.maximum:
        value = component.maximum
    return value


def _fee_breakdowns(
    fill_data: tuple[tuple[str, Decimal], ...],
    order: SimulationOrder,
    rules: InstrumentExecutionRules,
    fee_schedule: FeeSchedule,
) -> tuple[tuple[FeeBreakdown, ...], ...]:
    applicable = tuple(
        component
        for component in fee_schedule.components
        if order.side in component.applies_sides
        and rules.instrument_kind in component.instrument_kinds
    )
    result: list[list[FeeBreakdown]] = [[] for _ in fill_data]
    with localcontext() as context:
        context.prec = 60
        for component in applicable:
            raw_by_fill = tuple(
                (fill_id, gross_notional * component.rate) for fill_id, gross_notional in fill_data
            )
            if component.scope is FeeScope.PER_FILL:
                for index, (_, raw_amount) in enumerate(raw_by_fill):
                    bounded_amount = _bounded(raw_amount, component)
                    rounded_amount = _rounded(bounded_amount, component)
                    result[index].append(
                        FeeBreakdown(
                            component_code=component.code,
                            scope=component.scope,
                            unrounded_amount=raw_amount,
                            rounded_amount=rounded_amount,
                            allocated_amount=rounded_amount,
                        )
                    )
                continue
            total_raw = sum((raw for _, raw in raw_by_fill), Decimal("0"))
            total_rounded = _rounded(_bounded(total_raw, component), component)
            allocations: list[Decimal] = []
            if not raw_by_fill:
                continue
            if total_raw == 0:
                allocations = [Decimal("0")] * len(raw_by_fill)
                allocations[0] = total_rounded
            else:
                allocated = Decimal("0")
                for _, raw_amount in raw_by_fill[:-1]:
                    share = (total_rounded * raw_amount / total_raw).quantize(
                        component.rounding_quantum, rounding=ROUND_DOWN
                    )
                    allocations.append(share)
                    allocated += share
                allocations.append(total_rounded - allocated)
            for index, (_, raw_amount) in enumerate(raw_by_fill):
                result[index].append(
                    FeeBreakdown(
                        component_code=component.code,
                        scope=component.scope,
                        unrounded_amount=raw_amount,
                        rounded_amount=allocations[index],
                        allocated_amount=allocations[index],
                    )
                )
    return tuple(tuple(items) for items in result)


def _make_fill(
    order: SimulationOrder,
    level_id: str,
    quantity: int,
    price: Decimal,
    sequence: int,
    snapshot: MarketExecutionSnapshot,
    rules: InstrumentExecutionRules,
    fee_schedule: FeeSchedule,
    slippage: SlippageModel,
    fees: tuple[FeeBreakdown, ...],
) -> Fill:
    gross_notional = price * quantity
    fill_id = canonical_digest(
        {
            "order_id": order.order_id,
            "level_id": level_id,
            "sequence": sequence,
            "quantity": quantity,
            "price": price,
            "snapshot_digest": snapshot.snapshot_digest,
            "rules_digest": rules.rules_digest,
            "slippage_digest": slippage.slippage_digest,
        }
    )
    return Fill(
        fill_id=fill_id,
        order_id=order.order_id,
        source_intent_id=order.source_intent.intent_id,
        instrument_code=order.instrument_code,
        side=order.side,
        quantity=quantity,
        execution_sequence=sequence,
        price=price,
        gross_notional=gross_notional,
        match_time=snapshot.match_time,
        trading_date=snapshot.trading_date,
        liquidity_level_id=level_id,
        snapshot_digest=snapshot.snapshot_digest,
        rules_digest=rules.rules_digest,
        fee_schedule_digest=fee_schedule.fee_schedule_digest,
        slippage_model_digest=slippage.slippage_digest,
        source_intent_digest=canonical_digest(order.source_intent),
        source_order_digest=order.order_digest,
        manifest_digest=order.manifest_digest,
        fees=fees,
        total_fee=sum((fee.allocated_amount for fee in fees), Decimal("0")),
    )


def _make_result(
    order: SimulationOrder,
    status: MatchStatus,
    fills: tuple[Fill, ...],
    reason: RejectReason | None,
    detail: str | None,
    snapshot: MarketExecutionSnapshot,
    rules: InstrumentExecutionRules,
    fee_schedule: FeeSchedule,
    slippage: SlippageModel,
    skipped_level_ids: tuple[str, ...],
) -> MatchResult:
    filled_quantity = sum((fill.quantity for fill in fills), 0)
    return MatchResult(
        order_id=order.order_id,
        status=status,
        requested_quantity=order.quantity,
        filled_quantity=filled_quantity,
        remaining_quantity=order.quantity - filled_quantity,
        fills=fills,
        reject_reason=reason,
        reject_detail=detail,
        order_digest=order.order_digest,
        source_intent_id=order.source_intent.intent_id,
        instrument_code=order.instrument_code,
        side=order.side,
        manifest_digest=order.manifest_digest,
        snapshot_digest=snapshot.snapshot_digest,
        rules_digest=rules.rules_digest,
        fee_schedule_digest=fee_schedule.fee_schedule_digest,
        slippage_model_digest=slippage.slippage_digest,
        skipped_level_ids=skipped_level_ids,
    )


def _level_capacities(
    snapshot: MarketExecutionSnapshot,
    side: IntentSide,
    slippage: SlippageModel,
) -> tuple[tuple[ExecutableLiquidityLevel, ...], dict[str, int], tuple[str, ...]]:
    levels = snapshot.ask_levels if side is IntentSide.BUY else snapshot.bid_levels
    ordered = tuple(
        sorted(
            levels,
            key=lambda level: (
                level.price if side is IntentSide.BUY else -level.price,
                level.level_id,
            ),
        )
    )
    all_level_ids = {level.level_id for level in snapshot.bid_levels + snapshot.ask_levels}
    missing = set(slippage.skip_level_ids) - all_level_ids
    if missing:
        raise ExecutionValidationError("slippage references a missing liquidity level")
    offset_ids = {level.level_id for level in ordered[: slippage.adverse_level_offset]}
    skipped = tuple(sorted(offset_ids | set(slippage.skip_level_ids)))
    capacities: dict[str, int] = {}
    for level in ordered:
        if level.level_id in offset_ids or level.level_id in slippage.skip_level_ids:
            capacities[level.level_id] = 0
        elif slippage.max_level_participation is None:
            capacities[level.level_id] = level.quantity
        else:
            capacities[level.level_id] = int(
                (Decimal(level.quantity) * slippage.max_level_participation).to_integral_value(
                    rounding=ROUND_DOWN
                )
            )
    return ordered, capacities, skipped


def _matches_price(order: SimulationOrder, level_price: Decimal) -> bool:
    effective_price = _effective_price(order)
    assert effective_price is not None
    if order.side is IntentSide.BUY:
        return level_price <= effective_price
    return level_price >= effective_price


def _consume_sellable(
    remaining_lots: dict[str, int],
    sellability: SellabilitySnapshot,
    rules: InstrumentExecutionRules,
    trading_date: str,
    quantity: int,
) -> None:
    eligible, _ = _eligible_lots(sellability, rules, trading_date)
    left = quantity
    for lot_id, _ in eligible:
        available = remaining_lots.get(lot_id, 0)
        consumed = min(available, left)
        remaining_lots[lot_id] = available - consumed
        left -= consumed
        if left == 0:
            return
    if left:
        raise ExecutionValidationError("temporary sellability decrement exceeded eligible quantity")


def match_orders(
    orders: tuple[SimulationOrder, ...],
    snapshot: MarketExecutionSnapshot,
    rules: InstrumentExecutionRules,
    sellability: SellabilitySnapshot | None,
    fee_schedule: FeeSchedule,
    slippage_model: SlippageModel,
) -> BatchMatchResult:
    """Match one instrument and one point-in-time snapshot without external state."""

    if type(orders) is not tuple:
        raise ExecutionValidationError("orders must be an exact tuple")
    if not orders:
        raise ExecutionValidationError("orders must not be empty")
    typed_snapshot = revalidate_market_execution_snapshot(snapshot)
    typed_rules = revalidate_instrument_execution_rules(rules)
    typed_fee_schedule = revalidate_fee_schedule(fee_schedule)
    typed_slippage = revalidate_slippage_model(slippage_model)
    typed_sellability = (
        revalidate_sellability_snapshot(sellability) if sellability is not None else None
    )
    typed_orders = tuple(
        revalidate_simulation_order(order, f"orders[{index}]") for index, order in enumerate(orders)
    )
    order_ids = tuple(order.order_id for order in typed_orders)
    if len(order_ids) != len(set(order_ids)):
        raise ExecutionValidationError("duplicate order_id values are not allowed")
    if typed_snapshot.instrument_code != typed_rules.instrument_code:
        raise ExecutionValidationError("snapshot and rules instrument_code mismatch")
    if (
        typed_sellability is not None
        and typed_sellability.instrument_code != typed_snapshot.instrument_code
    ):
        raise ExecutionValidationError("sellability instrument_code mismatch")
    manifest_digests = {order.manifest_digest for order in typed_orders}
    if len(manifest_digests) != 1:
        raise ExecutionValidationError("orders must share one backtest manifest digest")
    for order in typed_orders:
        if order.instrument_code != typed_snapshot.instrument_code:
            raise ExecutionValidationError("order instrument_code mismatch")
        if order.submitted_at > typed_snapshot.match_time:
            continue
    match_time = typed_snapshot.match_time
    if typed_sellability is not None:
        if typed_sellability.as_of_time > match_time:
            raise ExecutionValidationError(
                "sellability.as_of_time must not exceed snapshot.match_time"
            )
        if typed_sellability.source.available_time > match_time:
            raise ExecutionValidationError("sellability.source.available_time is future data")
        for index, lot in enumerate(typed_sellability.lots):
            if lot.available_time > match_time:
                raise ExecutionValidationError(
                    f"sellability.lots[{index}].available_time is future data"
                )
            if lot.source.available_time > match_time:
                raise ExecutionValidationError(
                    f"sellability.lots[{index}].source.available_time is future data"
                )
    for field_name, available_time in (
        ("snapshot.available_time", typed_snapshot.available_time),
        ("rules.available_time", typed_rules.available_time),
        ("fee_schedule.available_time", typed_fee_schedule.available_time),
        ("slippage.available_time", typed_slippage.available_time),
    ):
        if available_time > match_time:
            raise ExecutionValidationError(f"{field_name} is future data")
    for field_name, available_time in (
        ("snapshot.source.available_time", typed_snapshot.source.available_time),
        ("rules.source.available_time", typed_rules.source.available_time),
        ("fee_schedule.source.available_time", typed_fee_schedule.source.available_time),
        ("slippage.source.available_time", typed_slippage.source.available_time),
    ):
        if available_time > match_time:
            raise ExecutionValidationError(f"{field_name} is future data")
    if typed_sellability is not None and typed_sellability.available_time > match_time:
        raise ExecutionValidationError("sellability.available_time is future data")
    if not _covers(typed_rules.effective_from, typed_rules.effective_to, match_time):
        raise ExecutionValidationError("rules effective interval does not cover match_time")
    if not _covers(typed_fee_schedule.effective_from, typed_fee_schedule.effective_to, match_time):
        raise ExecutionValidationError("fee_schedule effective interval does not cover match_time")
    if not _covers(typed_slippage.effective_from, typed_slippage.effective_to, match_time):
        raise ExecutionValidationError("slippage effective interval does not cover match_time")
    for component in typed_fee_schedule.components:
        if component.available_time > match_time or not _covers(
            component.effective_from, component.effective_to, match_time
        ):
            raise ExecutionValidationError(
                "fee component is not available and effective at match_time"
            )
        if component.source.available_time > match_time:
            raise ExecutionValidationError("fee component source.available_time is future data")
    for level in typed_snapshot.bid_levels + typed_snapshot.ask_levels:
        if not _tick_aligned(level.price, typed_rules.tick_size):
            raise ExecutionValidationError("liquidity level price is not tick aligned")
        if _band_reason(level.price, typed_snapshot) is not None:
            raise ExecutionValidationError(
                "liquidity level price is outside configured price bands"
            )

    initial_lots: dict[str, int] = {}
    if typed_sellability is not None:
        initial_lots = {lot.lot_id: lot.sellable_quantity for lot in typed_sellability.lots}
    skipped_by_side = {
        IntentSide.BUY: _level_capacities(typed_snapshot, IntentSide.BUY, typed_slippage),
        IntentSide.SELL: _level_capacities(typed_snapshot, IntentSide.SELL, typed_slippage),
    }
    skipped_level_ids = tuple(
        sorted(set(skipped_by_side[IntentSide.BUY][2]) | set(skipped_by_side[IntentSide.SELL][2]))
    )
    result_by_order_id: dict[str, MatchResult] = {}
    candidates: list[SimulationOrder] = []
    for order in typed_orders:
        reason = _static_order_reason(order, typed_snapshot, typed_rules)
        if reason is None and order.side is IntentSide.SELL and typed_sellability is None:
            reason = RejectReason.SELLABILITY_SNAPSHOT_MISSING
        if reason is not None:
            result_by_order_id[order.order_id] = _make_result(
                order,
                MatchStatus.REJECTED,
                (),
                reason,
                reason.value,
                typed_snapshot,
                typed_rules,
                typed_fee_schedule,
                typed_slippage,
                skipped_level_ids,
            )
        else:
            candidates.append(order)

    for side in (IntentSide.BUY, IntentSide.SELL):
        side_orders = sorted(
            (order for order in candidates if order.side is side),
            key=_priority_key,
        )
        ordered_levels, capacities, _ = skipped_by_side[side]
        for order in side_orders:
            if side is IntentSide.SELL:
                assert typed_sellability is not None
                reason = _sell_reason(
                    order,
                    typed_rules,
                    typed_sellability,
                    initial_lots,
                    typed_snapshot.trading_date,
                )
                if reason is not None:
                    result_by_order_id[order.order_id] = _make_result(
                        order,
                        MatchStatus.REJECTED,
                        (),
                        reason,
                        reason.value,
                        typed_snapshot,
                        typed_rules,
                        typed_fee_schedule,
                        typed_slippage,
                        skipped_level_ids,
                    )
                    continue
            remaining = order.quantity
            raw_fills: list[tuple[str, int, Decimal]] = []
            for level in ordered_levels:
                available = capacities[level.level_id]
                if available <= 0 or not _matches_price(order, level.price):
                    continue
                quantity = min(remaining, available)
                if quantity <= 0:
                    continue
                capacities[level.level_id] -= quantity
                raw_fills.append((level.level_id, quantity, level.price))
                remaining -= quantity
                if remaining == 0:
                    break
            if not raw_fills:
                result_by_order_id[order.order_id] = _make_result(
                    order,
                    MatchStatus.UNFILLED,
                    (),
                    RejectReason.MISSING_EXECUTABLE_LIQUIDITY,
                    RejectReason.MISSING_EXECUTABLE_LIQUIDITY.value,
                    typed_snapshot,
                    typed_rules,
                    typed_fee_schedule,
                    typed_slippage,
                    skipped_level_ids,
                )
                continue
            filled_quantity = sum(quantity for _, quantity, _ in raw_fills)
            if side is IntentSide.SELL:
                assert typed_sellability is not None
                _consume_sellable(
                    initial_lots,
                    typed_sellability,
                    typed_rules,
                    typed_snapshot.trading_date,
                    filled_quantity,
                )
            fill_data = tuple(
                (
                    canonical_digest(
                        {
                            "order_id": order.order_id,
                            "level_id": level_id,
                            "sequence": sequence,
                            "quantity": quantity,
                            "price": price,
                            "snapshot_digest": typed_snapshot.snapshot_digest,
                            "rules_digest": typed_rules.rules_digest,
                            "slippage_digest": typed_slippage.slippage_digest,
                        }
                    ),
                    price * quantity,
                )
                for sequence, (level_id, quantity, price) in enumerate(raw_fills)
            )
            fees_by_fill = _fee_breakdowns(fill_data, order, typed_rules, typed_fee_schedule)
            fills = tuple(
                _make_fill(
                    order,
                    level_id,
                    quantity,
                    price,
                    sequence,
                    typed_snapshot,
                    typed_rules,
                    typed_fee_schedule,
                    typed_slippage,
                    fees_by_fill[sequence],
                )
                for sequence, (level_id, quantity, price) in enumerate(raw_fills)
            )
            status = MatchStatus.FILLED if remaining == 0 else MatchStatus.PARTIALLY_FILLED
            result_by_order_id[order.order_id] = _make_result(
                order,
                status,
                fills,
                None,
                None,
                typed_snapshot,
                typed_rules,
                typed_fee_schedule,
                typed_slippage,
                skipped_level_ids,
            )

    ordered_results = tuple(result_by_order_id[order_id] for order_id in sorted(result_by_order_id))
    orders_digest = canonical_digest(
        tuple(
            (order.order_id, order.order_digest)
            for order in sorted(typed_orders, key=lambda item: item.order_id)
        )
    )
    code_config_digest = canonical_digest(
        {
            "matching_schema_version": MATCHING_SCHEMA_VERSION,
            "rules_digest": typed_rules.rules_digest,
            "fee_schedule_digest": typed_fee_schedule.fee_schedule_digest,
            "slippage_digest": typed_slippage.slippage_digest,
        }
    )
    return BatchMatchResult(
        matching_schema_version=MATCHING_SCHEMA_VERSION,
        backtest_manifest_digest=next(iter(manifest_digests)),
        orders_digest=orders_digest,
        snapshot_digest=typed_snapshot.snapshot_digest,
        rules_digest=typed_rules.rules_digest,
        sellability_digest=(
            typed_sellability.sellability_digest if typed_sellability is not None else None
        ),
        calendar_digest=typed_snapshot.calendar_digest,
        fee_schedule_digest=typed_fee_schedule.fee_schedule_digest,
        slippage_model_digest=typed_slippage.slippage_digest,
        source_dataset_digest=typed_snapshot.source.digest,
        code_config_digest=code_config_digest,
        results=ordered_results,
        skipped_level_ids=skipped_level_ids,
    )


def verify_batch_match_result_against_inputs(
    candidate: BatchMatchResult,
    orders: tuple[SimulationOrder, ...],
    snapshot: MarketExecutionSnapshot,
    rules: InstrumentExecutionRules,
    sellability: SellabilitySnapshot | None,
    fee_schedule: FeeSchedule,
    slippage_model: SlippageModel,
) -> BatchMatchResult:
    """Verify a result by replaying it against externally trusted inputs."""

    typed_candidate = revalidate_batch_match_result(candidate)
    expected = match_orders(
        orders,
        snapshot,
        rules,
        sellability,
        fee_schedule,
        slippage_model,
    )
    if typed_candidate.batch_digest != expected.batch_digest:
        raise ExecutionValidationError("batch result does not match trusted replay inputs")
    return typed_candidate


__all__ = [
    "match_orders",
    "revalidate_batch_match_result",
    "verify_batch_match_result_against_inputs",
]
