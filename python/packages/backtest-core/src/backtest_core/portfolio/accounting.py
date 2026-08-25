"""Pure state transitions for the immutable portfolio journal."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP, Decimal, localcontext
from typing import Protocol

from backtest_core.engine import IntentSide, canonical_digest
from backtest_core.execution import (
    ExecutionProvenance,
    Fill,
    SameDaySellPolicy,
    SellabilitySnapshot,
    SellableLot,
)

from .models import (
    ZERO_DIGEST,
    AccountCode,
    AccountingInvariantError,
    AppliedEventRecord,
    BuyCashReservation,
    BuyCashReservationEvent,
    CashReceivable,
    CorporateActionApplication,
    CorporateActionApplicationEvent,
    CorporateActionError,
    CorporateActionRecord,
    CorporateActionType,
    DuplicateEventConflictError,
    EventMetadata,
    EventOrderError,
    EventPhase,
    ExecutionReplayBundle,
    ExecutionSettlementEvent,
    InitialCapitalEvent,
    LedgerEvent,
    LedgerPosting,
    LotCostAllocationPolicy,
    PortfolioEvent,
    PortfolioHistoryRef,
    PortfolioLot,
    PortfolioState,
    PortfolioValidationError,
    PortfolioValuation,
    ReceivableError,
    ReceivableKind,
    ReceivableSettlementEvent,
    ReservationReleaseEvent,
    RoundingMode,
    TrustedExecutionInputs,
    TrustedReplayError,
    ValuationError,
    ValuationMark,
    ValuationMarkSource,
    ValuationPolicy,
    event_tape_digest,
    revalidate_portfolio_event,
    revalidate_portfolio_state,
)
from .replay import (
    TrustedExecutionArtifactSource,
    TrustedPortfolioEventSource,
    verify_execution_bundle_against_source,
    verify_portfolio_state_from_source,
)


def _rounding(mode: RoundingMode) -> str:
    return {
        RoundingMode.DOWN: ROUND_DOWN,
        RoundingMode.UP: ROUND_UP,
        RoundingMode.HALF_UP: ROUND_HALF_UP,
        RoundingMode.HALF_EVEN: ROUND_HALF_EVEN,
    }[mode]


def _posting(
    account: AccountCode,
    *,
    debit: Decimal = Decimal("0"),
    credit: Decimal = Decimal("0"),
    reference_id: str,
) -> LedgerPosting:
    return LedgerPosting(account, debit, credit, reference_id)


def _ledger(event: PortfolioEvent, postings: tuple[LedgerPosting, ...]) -> LedgerEvent:
    result = LedgerEvent(
        metadata=event.metadata,
        event_type=type(event).__name__,
        postings=postings,
        payload_digest=event.metadata.payload_digest,
    )
    if result.total_debits != result.total_credits:
        raise AccountingInvariantError("ledger event is not double-entry balanced")
    return result


def _append(
    state: PortfolioState,
    event: PortfolioEvent,
    ledger: LedgerEvent,
    **changes: object,
) -> PortfolioState:
    record = AppliedEventRecord(event.metadata.event_id, event.event_digest)
    records = state.applied_event_records + (record,)
    chain = canonical_digest((state.journal_chain_digest, event.event_digest))
    history_ref = PortfolioHistoryRef(
        tape_id=state.history_ref.tape_id,
        expected_event_tape_digest=event_tape_digest(tuple(item.event_digest for item in records)),
        expected_event_count=len(records),
    )
    values: dict[str, object] = {
        "last_ordering_key": event.ordering_key,
        "last_event_digest": event.event_digest,
        "applied_event_records": records,
        "journal_chain_digest": chain,
        "journal": state.journal + (ledger,),
        "history_ref": history_ref,
    }
    values.update(changes)
    return replace(state, **values)


def _check_progress(state: PortfolioState, event: PortfolioEvent) -> None:
    metadata = event.metadata
    if metadata.expected_previous_state_digest != state.state_digest:
        raise EventOrderError("expected previous state digest does not match current state")
    if metadata.previous_event_digest != state.last_event_digest:
        raise EventOrderError("journal chain gap or previous event digest mismatch")
    if state.last_ordering_key is not None and event.ordering_key <= state.last_ordering_key:
        raise EventOrderError("portfolio events must be in strict canonical order")


def _existing_event(state: PortfolioState, event: PortfolioEvent) -> AppliedEventRecord | None:
    return next(
        (item for item in state.applied_event_records if item.event_id == event.metadata.event_id),
        None,
    )


def _apply_portfolio_event_unchecked(
    state: PortfolioState,
    event: PortfolioEvent,
    *,
    execution_source: TrustedExecutionArtifactSource | None = None,
) -> PortfolioState:
    """Apply one event after its predecessor has already crossed the source boundary."""

    current = revalidate_portfolio_state(state)
    typed_event = revalidate_portfolio_event(event)
    existing = _existing_event(current, typed_event)
    if existing is not None:
        if existing.event_digest == typed_event.event_digest:
            return current
        raise DuplicateEventConflictError("event_id was reused with a different digest")
    _check_progress(current, typed_event)

    if type(typed_event) is InitialCapitalEvent:
        return _apply_initial(current, typed_event)
    if type(typed_event) is BuyCashReservationEvent:
        return _apply_reservation(current, typed_event)
    if type(typed_event) is ReservationReleaseEvent:
        return _apply_release(current, typed_event)
    if type(typed_event) is ExecutionSettlementEvent:
        return _apply_settlement(current, typed_event, execution_source=execution_source)
    if type(typed_event) is ReceivableSettlementEvent:
        return _apply_receivable_settlement(current, typed_event)
    if type(typed_event) is CorporateActionApplicationEvent:
        return _apply_corporate_action_event(current, typed_event)
    raise PortfolioValidationError("unsupported portfolio event")


def apply_portfolio_event(
    state: PortfolioState,
    event: PortfolioEvent,
    *,
    source: TrustedPortfolioEventSource | None = None,
    execution_source: TrustedExecutionArtifactSource | None = None,
) -> PortfolioState:
    """Verify the predecessor from the trusted tape before applying one event."""

    if source is None:
        raise TrustedReplayError("trusted portfolio event source is required")
    current = verify_portfolio_state_from_source(
        state,
        source,
        execution_source=execution_source,
    )
    return _apply_portfolio_event_unchecked(
        current,
        event,
        execution_source=execution_source,
    )


def _apply_initial(state: PortfolioState, event: InitialCapitalEvent) -> PortfolioState:
    if state.initial_capital != 0 or state.applied_event_records:
        raise PortfolioValidationError("initial capital can be opened only once")
    ledger = _ledger(
        event,
        (
            _posting(
                AccountCode.CASH_AVAILABLE,
                debit=event.amount,
                reference_id=event.metadata.event_id,
            ),
            _posting(
                AccountCode.EQUITY_INITIAL_CAPITAL,
                credit=event.amount,
                reference_id=event.metadata.event_id,
            ),
        ),
    )
    return _append(
        state,
        event,
        ledger,
        initial_capital=event.amount,
        available_cash=event.amount,
    )


def _apply_reservation(state: PortfolioState, event: BuyCashReservationEvent) -> PortfolioState:
    reservation = event.reservation
    if any(item.order_id == reservation.order_id for item in state.active_buy_reservations):
        raise PortfolioValidationError("order already has an active reservation")
    if reservation.order_id in state.settled_order_ids:
        raise PortfolioValidationError("settled order cannot be reserved")
    if state.available_cash < reservation.maximum_debit:
        raise PortfolioValidationError("insufficient available cash for reservation")
    reservations = tuple(
        sorted(state.active_buy_reservations + (reservation,), key=lambda item: item.order_id)
    )
    ledger = _ledger(
        event,
        (
            _posting(
                AccountCode.CASH_FROZEN,
                debit=reservation.maximum_debit,
                reference_id=reservation.order_id,
            ),
            _posting(
                AccountCode.CASH_AVAILABLE,
                credit=reservation.maximum_debit,
                reference_id=reservation.order_id,
            ),
        ),
    )
    return _append(
        state,
        event,
        ledger,
        available_cash=state.available_cash - reservation.maximum_debit,
        frozen_cash=state.frozen_cash + reservation.maximum_debit,
        active_buy_reservations=reservations,
    )


def _apply_release(state: PortfolioState, event: ReservationReleaseEvent) -> PortfolioState:
    if event.order_id in state.settled_order_ids:
        raise PortfolioValidationError("reservation release is not allowed after settlement")
    reservation = next(
        (item for item in state.active_buy_reservations if item.order_id == event.order_id),
        None,
    )
    if reservation is None:
        raise PortfolioValidationError("unknown active reservation")
    reservations = tuple(
        item for item in state.active_buy_reservations if item.order_id != event.order_id
    )
    ledger = _ledger(
        event,
        (
            _posting(
                AccountCode.CASH_AVAILABLE,
                debit=reservation.maximum_debit,
                reference_id=reservation.order_id,
            ),
            _posting(
                AccountCode.CASH_FROZEN,
                credit=reservation.maximum_debit,
                reference_id=reservation.order_id,
            ),
        ),
    )
    return _append(
        state,
        event,
        ledger,
        available_cash=state.available_cash + reservation.maximum_debit,
        frozen_cash=state.frozen_cash - reservation.maximum_debit,
        active_buy_reservations=reservations,
    )


def _apply_settlement(
    state: PortfolioState,
    event: ExecutionSettlementEvent,
    *,
    execution_source: TrustedExecutionArtifactSource | None,
) -> PortfolioState:
    bundle = event.bundle
    if execution_source is None:
        raise TrustedReplayError("trusted execution artifact source is required")
    inputs = verify_execution_bundle_against_source(bundle, execution_source)
    if event.metadata.logical_time < inputs.snapshot.match_time:
        raise TrustedReplayError("settlement event precedes match time")
    return _settle_verified_bundle(state, event, inputs, event.lot_cost_policy)


def _settle_verified_bundle(
    state: PortfolioState,
    event: ExecutionSettlementEvent,
    inputs: TrustedExecutionInputs,
    policy: LotCostAllocationPolicy,
) -> PortfolioState:
    candidate = event.bundle.candidate
    order_by_id = {order.order_id: order for order in inputs.orders}
    result_ids = tuple(result.order_id for result in candidate.results)
    if result_ids != tuple(sorted(order_by_id)) or set(result_ids) != set(order_by_id):
        raise TrustedReplayError("candidate results do not cover the original orders")

    reservations = {item.order_id: item for item in state.active_buy_reservations}
    lots = list(state.open_lots)
    sale_receivables = list(state.sale_receivables)
    available_cash = state.available_cash
    frozen_cash = state.frozen_cash
    realized = state.realized_price_pnl
    fee_pnl = state.fee_pnl
    postings: list[LedgerPosting] = []
    settled_ids: set[str] = set(state.settled_order_ids)

    if any(order_id in state.settled_order_ids for order_id in result_ids):
        raise TrustedReplayError("terminal order has already been settled")

    if any(order.side is IntentSide.SELL for order in order_by_id.values()):
        _require_canonical_sellability(state, inputs)

    for result in candidate.results:
        order = order_by_id[result.order_id]
        if result.order_digest != order.order_digest or result.side is not order.side:
            raise TrustedReplayError("candidate result is not bound to its original order")
        settled_ids.add(order.order_id)
        if order.side is IntentSide.BUY:
            reservation = reservations.pop(order.order_id, None)
            if reservation is None:
                raise TrustedReplayError("BUY result has no matching reservation")
            if reservation.order_digest != order.order_digest:
                raise TrustedReplayError("reservation order digest mismatch")
            if reservation.fee_schedule_digest != inputs.fee_schedule.fee_schedule_digest:
                raise TrustedReplayError("reservation fee schedule digest mismatch")
            if reservation.artifact_id != inputs.artifact_id:
                raise TrustedReplayError("reservation artifact id mismatch")
            if reservation.execution_input_digest != inputs.input_digest:
                raise TrustedReplayError("reservation execution input digest mismatch")
            gross = sum((fill.gross_notional for fill in result.fills), Decimal("0"))
            fees = sum((fill.total_fee for fill in result.fills), Decimal("0"))
            actual_debit = gross + fees
            if actual_debit > reservation.maximum_debit:
                raise TrustedReplayError("actual BUY debit exceeds frozen reservation")
            unused = reservation.maximum_debit - actual_debit
            frozen_cash -= reservation.maximum_debit
            available_cash += unused
            fee_pnl -= fees
            if gross > 0:
                postings.append(
                    _posting(
                        AccountCode.POSITION_GROSS_COST,
                        debit=gross,
                        reference_id=order.order_id,
                    )
                )
            if fees > 0:
                postings.append(
                    _posting(AccountCode.FEE_PNL, debit=fees, reference_id=order.order_id)
                )
            if unused > 0:
                postings.append(
                    _posting(
                        AccountCode.CASH_AVAILABLE,
                        debit=unused,
                        reference_id=order.order_id,
                    )
                )
            postings.append(
                _posting(
                    AccountCode.CASH_FROZEN,
                    credit=reservation.maximum_debit,
                    reference_id=order.order_id,
                )
            )
            for fill in result.fills:
                sellable_from = _sellable_from_fill(inputs, fill)
                lot = PortfolioLot(
                    lot_id=fill.fill_id,
                    instrument_code=fill.instrument_code,
                    acquisition_trade_date=fill.trading_date,
                    acquisition_time=fill.match_time,
                    sellable_from_trade_date=sellable_from,
                    remaining_quantity=fill.quantity,
                    gross_cost=fill.gross_notional,
                    available_time=fill.match_time,
                    source_order_id=order.order_id,
                    source_fill_ids=(fill.fill_id,),
                    lineage_digest=canonical_digest((event.bundle.bundle_digest, fill.fill_id)),
                )
                if any(item.lot_id == lot.lot_id for item in lots):
                    raise TrustedReplayError("duplicate lot id in trusted settlement")
                lots.append(lot)
        else:
            for fill in result.fills:
                allocated_cost, lots = consume_fifo(lots, fill, policy)
                gross = fill.gross_notional
                fee = fill.total_fee
                net = gross - fee
                if net < 0:
                    raise TrustedReplayError("SELL fees exceed gross proceeds")
                realized += gross - allocated_cost
                fee_pnl -= fee
                receivable_id = canonical_digest((event.metadata.event_id, fill.fill_id))
                sale_receivables.append(
                    CashReceivable(
                        receivable_id=receivable_id,
                        kind=ReceivableKind.SALE_PROCEEDS,
                        instrument_code=fill.instrument_code,
                        amount=net,
                        due_time=fill.match_time,
                        source_event_id=event.metadata.event_id,
                        provenance_digest=event.metadata.provenance_digest,
                    )
                )
                if net > 0:
                    postings.append(
                        _posting(
                            AccountCode.RECEIVABLE_SALE,
                            debit=net,
                            reference_id=receivable_id,
                        )
                    )
                if fee > 0:
                    postings.append(
                        _posting(AccountCode.FEE_PNL, debit=fee, reference_id=fill.fill_id)
                    )
                if allocated_cost >= gross:
                    loss = allocated_cost - gross
                    if loss > 0:
                        postings.append(
                            _posting(
                                AccountCode.REALIZED_PRICE_PNL,
                                debit=loss,
                                reference_id=fill.fill_id,
                            )
                        )
                    postings.append(
                        _posting(
                            AccountCode.POSITION_GROSS_COST,
                            credit=allocated_cost,
                            reference_id=fill.fill_id,
                        )
                    )
                else:
                    gain = gross - allocated_cost
                    postings.append(
                        _posting(
                            AccountCode.POSITION_GROSS_COST,
                            credit=allocated_cost,
                            reference_id=fill.fill_id,
                        )
                    )
                    if gain > 0:
                        postings.append(
                            _posting(
                                AccountCode.REALIZED_PRICE_PNL,
                                credit=gain,
                                reference_id=fill.fill_id,
                            )
                        )

    # A result is terminal in the P5-N11 IOC contract; reservations outside this
    # batch remain active and are not implicitly released.
    active_reservations = tuple(sorted(reservations.values(), key=lambda item: item.order_id))
    lots_tuple = tuple(
        sorted(
            lots, key=lambda item: (item.instrument_code, item.acquisition_trade_date, item.lot_id)
        )
    )
    sales_tuple = tuple(sorted(sale_receivables, key=lambda item: item.receivable_id))
    settled_tuple = tuple(sorted(settled_ids))
    ledger = _ledger(event, tuple(postings))
    return _append(
        state,
        event,
        ledger,
        available_cash=available_cash,
        frozen_cash=frozen_cash,
        active_buy_reservations=active_reservations,
        open_lots=lots_tuple,
        sale_receivables=sales_tuple,
        sale_cash_receivable=sum((item.amount for item in sales_tuple), Decimal("0")),
        realized_price_pnl=realized,
        fee_pnl=fee_pnl,
        settled_order_ids=settled_tuple,
    )


def _sellable_from_fill(inputs: TrustedExecutionInputs, fill: Fill) -> str:
    if inputs.rules.same_day_sell_policy is SameDaySellPolicy.T_PLUS_0:
        return fill.trading_date
    resolution = inputs.next_trading_date_resolution
    if resolution is None:
        raise TrustedReplayError("T_PLUS_1 settlement requires explicit next trading date")
    if resolution.calendar_id != inputs.snapshot.calendar_id:
        raise TrustedReplayError("next trading date calendar id mismatch")
    if resolution.calendar_version != inputs.snapshot.calendar_version:
        raise TrustedReplayError("next trading date calendar version mismatch")
    if resolution.calendar_digest != inputs.snapshot.calendar_digest:
        raise TrustedReplayError("next trading date calendar digest mismatch")
    if resolution.trading_date != inputs.snapshot.trading_date:
        raise TrustedReplayError("next trading date source date mismatch")
    if resolution.trading_date != fill.trading_date:
        raise TrustedReplayError("next trading date resolution is for another trading date")
    if resolution.match_time is None:
        raise TrustedReplayError("next trading date resolution lacks match boundary")
    if resolution.match_time != inputs.snapshot.match_time:
        raise TrustedReplayError("next trading date resolution match boundary mismatch")
    if resolution.available_time > inputs.snapshot.match_time:
        raise TrustedReplayError("next trading date resolution is future data")
    if (
        resolution.provenance_available_time is not None
        and resolution.provenance_available_time > inputs.snapshot.match_time
    ):
        raise TrustedReplayError("next trading date resolution provenance is future data")
    return resolution.next_trading_date


def _require_canonical_sellability(state: PortfolioState, inputs: TrustedExecutionInputs) -> None:
    sellability = inputs.sellability
    if sellability is None:
        raise TrustedReplayError("SELL settlement requires a sellability snapshot")
    expected = _export_sellability_snapshot_unchecked(
        state,
        inputs.snapshot.instrument_code,
        inputs.snapshot.match_time,
        available_time=sellability.available_time,
        provenance=sellability.source,
    )
    if expected.sellability_digest != sellability.sellability_digest:
        raise TrustedReplayError("bundle sellability does not equal state-derived snapshot")


class FifoFillInput(Protocol):
    @property
    def instrument_code(self) -> str: ...

    @property
    def quantity(self) -> int: ...

    @property
    def trading_date(self) -> str: ...


def consume_fifo(
    lots: list[PortfolioLot], fill: FifoFillInput, policy: LotCostAllocationPolicy
) -> tuple[Decimal, list[PortfolioLot]]:
    remaining = fill.quantity
    allocated_total = Decimal("0")
    candidates = [
        lot
        for lot in lots
        if lot.instrument_code == fill.instrument_code
        and lot.sellable_from_trade_date <= fill.trading_date
        and lot.remaining_quantity > 0
    ]
    candidates.sort(key=lambda lot: (lot.acquisition_trade_date, lot.lot_id))
    if sum(lot.remaining_quantity for lot in candidates) < remaining:
        raise TrustedReplayError("SELL would short the persistent FIFO lots")
    candidate_ids = {lot.lot_id for lot in candidates}
    replacements: list[PortfolioLot] = []
    for lot in lots:
        if remaining == 0 or lot.lot_id not in candidate_ids:
            replacements.append(lot)
            continue
        take = min(remaining, lot.remaining_quantity)
        if take == lot.remaining_quantity:
            allocated = lot.gross_cost
        else:
            with localcontext() as context:
                context.prec = 80
                raw = lot.gross_cost * Decimal(take) / Decimal(lot.remaining_quantity)
                allocated = raw.quantize(policy.quantum, rounding=_rounding(policy.rounding_mode))
            if allocated <= 0 or allocated >= lot.gross_cost:
                raise TrustedReplayError("FIFO partial-lot allocation is not representable")
        remaining_quantity = lot.remaining_quantity - take
        if remaining_quantity > 0:
            replacements.append(
                replace(
                    lot,
                    remaining_quantity=remaining_quantity,
                    gross_cost=lot.gross_cost - allocated,
                )
            )
        remaining -= take
        allocated_total += allocated
    if remaining != 0:
        raise TrustedReplayError("FIFO allocation left an unsatisfied quantity")
    return allocated_total, replacements


def reserve_buy_cash(
    state: PortfolioState,
    order_id: str,
    order_digest: str,
    fee_schedule_digest: str,
    artifact_id: str,
    execution_input_digest: str,
    policy: ReservationPolicyLike,
    maximum_debit: Decimal,
    *,
    metadata: EventMetadata | None = None,
    source: TrustedPortfolioEventSource | None = None,
    execution_source: TrustedExecutionArtifactSource | None = None,
) -> PortfolioState:
    """Create and apply an explicit BUY reservation without recomputing fees."""

    when = _metadata_time(metadata, state)
    reservation = BuyCashReservation(
        order_id=order_id,
        order_digest=order_digest,
        fee_schedule_digest=fee_schedule_digest,
        artifact_id=artifact_id,
        execution_input_digest=execution_input_digest,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_digest=policy.policy_digest,
        reservation_logical_time=when,
        maximum_debit=maximum_debit,
    )
    if metadata is None:
        metadata = EventMetadata.for_event(
            event_id=canonical_digest(("BUY_CASH_RESERVATION", reservation.reservation_digest)),
            logical_time=when,
            event_phase=EventPhase.RESERVATION,
            source_id="portfolio-reservation",
            source_version="1.0.0",
            source_sequence=len(state.applied_event_records),
            available_time=when,
            expected_previous_state_digest=state.state_digest,
            previous_event_digest=state.last_event_digest,
            provenance_digest=ZERO_DIGEST,
            config_digest=policy.policy_digest,
        )
    return apply_portfolio_event(
        state,
        BuyCashReservationEvent(metadata, reservation),
        source=source,
        execution_source=execution_source,
    )


class ReservationPolicyLike:
    policy_id: str
    policy_version: str
    policy_digest: str


def create_portfolio(
    initial_capital: Decimal,
    *,
    tape_id: str = "portfolio",
    metadata: EventMetadata | None = None,
) -> PortfolioState:
    """Create a portfolio with a real opening journal event at the genesis boundary."""

    state = PortfolioState.empty(tape_id)
    when = datetime(1970, 1, 1, tzinfo=UTC) if metadata is None else metadata.logical_time
    if metadata is None:
        metadata = EventMetadata.for_event(
            event_id=canonical_digest(("INITIAL_CAPITAL", tape_id, initial_capital)),
            logical_time=when,
            event_phase=EventPhase.OPENING,
            source_id="portfolio-opening",
            source_version="1.0.0",
            source_sequence=0,
            available_time=when,
            expected_previous_state_digest=state.state_digest,
            previous_event_digest=ZERO_DIGEST,
            provenance_digest=ZERO_DIGEST,
            config_digest=ZERO_DIGEST,
        )
    return _apply_portfolio_event_unchecked(
        state,
        InitialCapitalEvent(metadata=metadata, amount=initial_capital),
    )


def _metadata_time(metadata: EventMetadata | None, state: PortfolioState) -> datetime:
    if metadata is not None:
        return metadata.logical_time
    if state.last_ordering_key is not None:
        return state.last_ordering_key[0]
    return datetime(1970, 1, 1, tzinfo=UTC)


def settle_execution_bundle(
    state: PortfolioState,
    bundle: ExecutionReplayBundle,
    *,
    source: TrustedPortfolioEventSource | None = None,
    execution_source: TrustedExecutionArtifactSource | None = None,
    metadata: EventMetadata | None = None,
    lot_cost_policy: LotCostAllocationPolicy | None = None,
) -> PortfolioState:
    """Verify and settle only a complete trusted P5-N11 replay bundle."""

    if type(bundle) is not ExecutionReplayBundle:
        raise TrustedReplayError("bare Fill, MatchResult, or BatchMatchResult cannot be settled")
    if source is None:
        raise TrustedReplayError("trusted portfolio event source is required")
    if execution_source is None:
        raise TrustedReplayError("trusted execution artifact source is required")
    typed_state = verify_portfolio_state_from_source(
        state,
        source,
        execution_source=execution_source,
    )
    inputs = verify_execution_bundle_against_source(bundle, execution_source)
    when = inputs.snapshot.match_time if metadata is None else metadata.logical_time
    policy = LotCostAllocationPolicy() if lot_cost_policy is None else lot_cost_policy
    if metadata is None:
        metadata = EventMetadata.for_event(
            event_id=canonical_digest(("EXECUTION_SETTLEMENT", bundle.bundle_digest)),
            logical_time=when,
            event_phase=EventPhase.EXECUTION,
            source_id="portfolio-execution",
            source_version="1.0.0",
            source_sequence=len(typed_state.applied_event_records),
            available_time=inputs.snapshot.available_time,
            expected_previous_state_digest=typed_state.state_digest,
            previous_event_digest=typed_state.last_event_digest,
            provenance_digest=inputs.external_source_digest,
            config_digest=inputs.external_config_digest,
        )
    return apply_portfolio_event(
        typed_state,
        ExecutionSettlementEvent(metadata, bundle, policy),
        source=source,
        execution_source=execution_source,
    )


def settle_execution_result(*args: object, **kwargs: object) -> PortfolioState:
    """Explicitly reject the unsafe bare-result settlement shape."""

    del args, kwargs
    raise TrustedReplayError("settlement requires ExecutionReplayBundle with trusted inputs")


def _apply_receivable_settlement(
    state: PortfolioState, event: ReceivableSettlementEvent
) -> PortfolioState:
    if event.kind is ReceivableKind.SALE_PROCEEDS:
        items = list(state.sale_receivables)
    else:
        items = list(state.dividend_or_corporate_receivables)
    match_index = next(
        (index for index, item in enumerate(items) if item.receivable_id == event.receivable_id),
        None,
    )
    if match_index is None:
        raise ReceivableError("unknown receivable identity")
    receivable = items[match_index]
    if receivable.amount != event.amount:
        raise ReceivableError("settlement amount must exactly equal receivable amount")
    if receivable.kind is not event.kind:
        raise ReceivableError("receivable kind mismatch")
    if receivable.due_time != event.due_time:
        raise ReceivableError("settlement due identity mismatch")
    if receivable.source_event_id != event.source_event_id:
        raise ReceivableError("settlement source identity mismatch")
    del items[match_index]
    values: dict[str, object] = {
        "available_cash": state.available_cash + event.amount,
    }
    if event.kind is ReceivableKind.SALE_PROCEEDS:
        values["sale_receivables"] = tuple(items)
        values["sale_cash_receivable"] = state.sale_cash_receivable - event.amount
        account = AccountCode.RECEIVABLE_SALE
    else:
        values["dividend_or_corporate_receivables"] = tuple(items)
        values["dividend_or_corporate_cash_receivable"] = (
            state.dividend_or_corporate_cash_receivable - event.amount
        )
        account = AccountCode.RECEIVABLE_DIVIDEND_CORPORATE
    ledger = _ledger(
        event,
        (
            _posting(
                AccountCode.CASH_AVAILABLE, debit=event.amount, reference_id=event.receivable_id
            ),
            _posting(account, credit=event.amount, reference_id=event.receivable_id),
        ),
    )
    return _append(state, event, ledger, **values)


def apply_corporate_action(
    state: PortfolioState,
    record: CorporateActionRecord,
    *,
    source: TrustedPortfolioEventSource | None = None,
    execution_source: TrustedExecutionArtifactSource | None = None,
    metadata: EventMetadata | None = None,
    lot_cost_policy: LotCostAllocationPolicy | None = None,
) -> PortfolioState:
    """Apply one point-in-time corporate action through a journal event."""

    if source is None:
        raise TrustedReplayError("trusted portfolio event source is required")
    typed_state = verify_portfolio_state_from_source(
        state,
        source,
        execution_source=execution_source,
    )
    policy = LotCostAllocationPolicy() if lot_cost_policy is None else lot_cost_policy
    if metadata is None:
        boundary = record.effective_time or record.pay_time or record.event_time
        metadata = EventMetadata.for_event(
            event_id=canonical_digest(("CORPORATE_ACTION", record.action_digest)),
            logical_time=boundary,
            event_phase=EventPhase.CORPORATE_ACTION,
            source_id=record.source_id,
            source_version=record.action_version,
            source_sequence=len(typed_state.applied_event_records),
            available_time=record.available_time,
            expected_previous_state_digest=typed_state.state_digest,
            previous_event_digest=typed_state.last_event_digest,
            provenance_digest=record.provenance_digest,
            config_digest=record.terms_digest,
        )
    return apply_portfolio_event(
        typed_state,
        CorporateActionApplicationEvent(metadata, record, policy),
        source=source,
        execution_source=execution_source,
    )


def _apply_corporate_action_event(
    state: PortfolioState, event: CorporateActionApplicationEvent
) -> PortfolioState:
    record = event.record
    for application in state.corporate_action_applications:
        same_identity = (
            application.source_id == record.source_id
            and application.raw_capture_id == record.raw_capture_id
            and application.action_id == record.action_id
        )
        if same_identity:
            raise CorporateActionError("corporate action identity is already applied")
        if application.lineage_id == record.lineage_id:
            raise CorporateActionError("corporate action corrections or revisions are unsupported")
    lots = [lot for lot in state.open_lots if lot.instrument_code == record.instrument_code]
    if not lots:
        raise CorporateActionError("no eligible lots for corporate action")
    if record.action_type is CorporateActionType.CASH_DIVIDEND:
        return _apply_cash_dividend(state, event, lots)
    return _apply_stock_action(state, event, lots, event.lot_cost_policy)


def _eligible_lots_for_record(
    state: PortfolioState, record: CorporateActionRecord
) -> list[PortfolioLot]:
    boundary = record.record_time or record.effective_time or record.event_time
    assert boundary is not None
    return [
        lot
        for lot in state.open_lots
        if lot.instrument_code == record.instrument_code
        and lot.remaining_quantity > 0
        and lot.acquisition_time <= boundary
    ]


def _apply_cash_dividend(
    state: PortfolioState,
    event: CorporateActionApplicationEvent,
    lots: list[PortfolioLot],
) -> PortfolioState:
    record = event.record
    eligible = _eligible_lots_for_record(state, record)
    amount_per_share = record.terms.dividend_amount_per_share
    if not eligible or amount_per_share is None:
        raise CorporateActionError("cash dividend has no eligible lots")
    receivables = list(state.dividend_or_corporate_receivables)
    total = Decimal("0")
    entitlement_ids: list[str] = []
    due_time = record.pay_time or record.record_time
    if due_time is None:
        raise CorporateActionError("cash dividend requires an explicit record or pay time")
    for lot in eligible:
        amount = amount_per_share * Decimal(lot.remaining_quantity)
        if amount <= 0:
            continue
        entitlement_id = canonical_digest((record.lineage_id, record.action_version, lot.lot_id))
        entitlement_ids.append(entitlement_id)
        receivables.append(
            CashReceivable(
                receivable_id=entitlement_id,
                kind=ReceivableKind.DIVIDEND_OR_CORPORATE,
                instrument_code=record.instrument_code,
                amount=amount,
                due_time=due_time,
                source_event_id=event.metadata.event_id,
                provenance_digest=record.provenance_digest,
            )
        )
        total += amount
    if total <= 0:
        raise CorporateActionError("cash dividend creates no positive entitlement")
    application = CorporateActionApplication(
        source_id=record.source_id,
        raw_capture_id=record.raw_capture_id,
        action_id=record.action_id,
        lineage_id=record.lineage_id,
        action_version=record.action_version,
        action_digest=record.action_digest,
        entitlement_ids=tuple(sorted(entitlement_ids)),
    )
    receivable_tuple = tuple(sorted(receivables, key=lambda item: item.receivable_id))
    ledger = _ledger(
        event,
        (
            _posting(
                AccountCode.RECEIVABLE_DIVIDEND_CORPORATE,
                debit=total,
                reference_id=record.lineage_id,
            ),
            _posting(
                AccountCode.DIVIDEND_PNL,
                credit=total,
                reference_id=record.lineage_id,
            ),
        ),
    )
    return _append(
        state,
        event,
        ledger,
        dividend_or_corporate_receivables=receivable_tuple,
        dividend_or_corporate_cash_receivable=state.dividend_or_corporate_cash_receivable + total,
        dividend_pnl=state.dividend_pnl + total,
        corporate_action_applications=state.corporate_action_applications + (application,),
    )


def _allocate_expansion_cost(
    total_cost: Decimal,
    old_quantity: int,
    post_quantity: int,
    policy: LotCostAllocationPolicy,
) -> tuple[Decimal, Decimal]:
    if post_quantity <= old_quantity:
        return total_cost, Decimal("0")
    with localcontext() as context:
        context.prec = 80
        retained_raw = total_cost * Decimal(old_quantity) / Decimal(post_quantity)
        retained_cost = retained_raw.quantize(
            policy.quantum,
            rounding=_rounding(policy.rounding_mode),
        )
    added_cost = total_cost - retained_cost
    if retained_cost < 0 or added_cost < 0:
        raise CorporateActionError("stock action cost allocation exceeds total cost")
    return retained_cost, added_cost


def _apply_stock_action(
    state: PortfolioState,
    event: CorporateActionApplicationEvent,
    lots: list[PortfolioLot],
    policy: LotCostAllocationPolicy,
) -> PortfolioState:
    record = event.record
    eligible = _eligible_lots_for_record(state, record)
    terms = record.terms
    if not eligible or terms.ratio_numerator is None or terms.ratio_denominator is None:
        raise CorporateActionError("stock action has no eligible lots or ratio")
    numerator = terms.ratio_numerator
    denominator = terms.ratio_denominator
    changed: list[PortfolioLot] = []
    receivables = list(state.dividend_or_corporate_receivables)
    other_pnl = Decimal("0")
    entitlement_ids: list[str] = []
    cil_postings: list[LedgerPosting] = []
    eligible_ids = {lot.lot_id for lot in eligible}
    for lot in state.open_lots:
        if lot.lot_id not in eligible_ids:
            changed.append(lot)
            continue
        with localcontext() as context:
            context.prec = 80
            raw_quantity = (
                Decimal(lot.remaining_quantity) * Decimal(numerator) / Decimal(denominator)
            )
        integral = raw_quantity == raw_quantity.to_integral_value()
        if not integral and (terms.cash_in_lieu_amount is None or terms.cash_in_lieu_cost is None):
            raise CorporateActionError("fractional corporate action requires explicit cash in lieu")
        post_quantity = int(raw_quantity.to_integral_value(rounding=ROUND_DOWN))
        cash_in_lieu_amount = Decimal("0")
        cash_in_lieu_cost = Decimal("0")
        if not integral:
            assert terms.cash_in_lieu_amount is not None
            assert terms.cash_in_lieu_cost is not None
            cash_in_lieu_amount = terms.cash_in_lieu_amount
            cash_in_lieu_cost = terms.cash_in_lieu_cost
            if post_quantity == 0 and cash_in_lieu_cost != lot.gross_cost:
                raise CorporateActionError("cash-in-lieu cost must close a fully converted lot")
            if cash_in_lieu_cost > lot.gross_cost:
                raise CorporateActionError("cash-in-lieu cost exceeds lot cost")
        if post_quantity > 0:
            existing_quantity = min(lot.remaining_quantity, post_quantity)
            remaining_cost = lot.gross_cost - cash_in_lieu_cost
            if remaining_cost < 0:
                raise CorporateActionError("cash-in-lieu cost exceeds remaining lot cost")
            existing_cost, added_cost = _allocate_expansion_cost(
                remaining_cost,
                lot.remaining_quantity,
                post_quantity,
                policy,
            )
            existing_lot = replace(
                lot,
                remaining_quantity=existing_quantity,
                gross_cost=existing_cost,
            )
            changed.append(existing_lot)
            added = post_quantity - existing_quantity
            if added > 0:
                sellable_time = terms.sellable_from_time or record.listing_time
                if sellable_time is None:
                    raise CorporateActionError("new shares require explicit listing/sellable time")
                added_lot = PortfolioLot(
                    lot_id=canonical_digest((lot.lot_id, record.action_digest, "new")),
                    instrument_code=lot.instrument_code,
                    acquisition_trade_date=lot.acquisition_trade_date,
                    acquisition_time=lot.acquisition_time,
                    sellable_from_trade_date=sellable_time.astimezone(
                        __import__("zoneinfo", fromlist=["ZoneInfo"]).ZoneInfo("Asia/Shanghai")
                    )
                    .date()
                    .isoformat(),
                    remaining_quantity=added,
                    available_time=record.available_time,
                    source_order_id=lot.source_order_id,
                    source_fill_ids=lot.source_fill_ids,
                    gross_cost=added_cost,
                    lineage_digest=canonical_digest(
                        (
                            lot.lineage_digest,
                            record.lineage_id,
                            record.action_version,
                            record.action_digest,
                            "added",
                        )
                    ),
                )
                changed.append(added_lot)
        if cash_in_lieu_amount > 0:
            entitlement_id = canonical_digest(
                (record.lineage_id, record.action_version, lot.lot_id, "cash-in-lieu")
            )
            entitlement_ids.append(entitlement_id)
            due_time = record.pay_time or record.effective_time or record.event_time
            receivables.append(
                CashReceivable(
                    receivable_id=entitlement_id,
                    kind=ReceivableKind.DIVIDEND_OR_CORPORATE,
                    instrument_code=record.instrument_code,
                    amount=cash_in_lieu_amount,
                    due_time=due_time,
                    source_event_id=event.metadata.event_id,
                    provenance_digest=record.provenance_digest,
                )
            )
            other_pnl += cash_in_lieu_amount - cash_in_lieu_cost
            cil_postings.extend(
                (
                    _posting(
                        AccountCode.RECEIVABLE_DIVIDEND_CORPORATE,
                        debit=cash_in_lieu_amount,
                        reference_id=entitlement_id,
                    ),
                    _posting(
                        AccountCode.POSITION_GROSS_COST,
                        credit=cash_in_lieu_cost,
                        reference_id=entitlement_id,
                    ),
                )
            )
            difference = cash_in_lieu_amount - cash_in_lieu_cost
            if difference > 0:
                cil_postings.append(
                    _posting(
                        AccountCode.OTHER_CORPORATE_ACTION_PNL,
                        credit=difference,
                        reference_id=entitlement_id,
                    )
                )
            elif difference < 0:
                cil_postings.append(
                    _posting(
                        AccountCode.OTHER_CORPORATE_ACTION_PNL,
                        debit=-difference,
                        reference_id=entitlement_id,
                    )
                )
    application = CorporateActionApplication(
        source_id=record.source_id,
        raw_capture_id=record.raw_capture_id,
        action_id=record.action_id,
        lineage_id=record.lineage_id,
        action_version=record.action_version,
        action_digest=record.action_digest,
        entitlement_ids=tuple(sorted(entitlement_ids)),
    )
    changed_tuple = tuple(
        sorted(
            changed,
            key=lambda item: (item.instrument_code, item.acquisition_trade_date, item.lot_id),
        )
    )
    receivable_tuple = tuple(sorted(receivables, key=lambda item: item.receivable_id))
    ledger = _ledger(event, tuple(cil_postings))
    return _append(
        state,
        event,
        ledger,
        open_lots=changed_tuple,
        dividend_or_corporate_receivables=receivable_tuple,
        dividend_or_corporate_cash_receivable=state.dividend_or_corporate_cash_receivable
        + sum((item.amount for item in receivable_tuple), Decimal("0"))
        - state.dividend_or_corporate_cash_receivable,
        other_corporate_action_pnl=state.other_corporate_action_pnl + other_pnl,
        corporate_action_applications=state.corporate_action_applications + (application,),
    )


def _export_sellability_snapshot_unchecked(
    state: PortfolioState,
    instrument_code: str,
    as_of_time: datetime,
    *,
    available_time: datetime | None = None,
    provenance: ExecutionProvenance | None = None,
) -> SellabilitySnapshot:
    """Export the persistent state sellability used by the P5-N11 matcher."""

    typed_state = revalidate_portfolio_state(state)
    if not instrument_code.strip():
        raise PortfolioValidationError("instrument_code must be non-empty")
    if as_of_time.tzinfo is None or as_of_time.utcoffset() is None:
        raise PortfolioValidationError("as_of_time must be timezone-aware")
    effective_available = as_of_time if available_time is None else available_time
    if effective_available.tzinfo is None or effective_available.utcoffset() is None:
        raise PortfolioValidationError("available_time must be timezone-aware")
    if effective_available > as_of_time:
        raise PortfolioValidationError("sellability cannot be available after as_of_time")
    if provenance is None:
        source_id = "portfolio-accounting"
        source_version = "1.0.0"
        record_id = canonical_digest(
            (typed_state.state_digest, instrument_code, as_of_time.astimezone(UTC))
        )
        source_digest = canonical_digest(
            (source_id, source_version, record_id, effective_available.astimezone(UTC))
        )
        provenance = ExecutionProvenance(
            source_id, source_version, record_id, source_digest, effective_available
        )
    else:
        provenance.__post_init__()
        if provenance.available_time > as_of_time:
            raise TrustedReplayError("sellability source is future data")
    boundary_date = (
        as_of_time.astimezone(
            __import__("zoneinfo", fromlist=["ZoneInfo"]).ZoneInfo("Asia/Shanghai")
        )
        .date()
        .isoformat()
    )
    lots: list[SellableLot] = []
    for lot in typed_state.open_lots:
        if lot.instrument_code != instrument_code:
            continue
        if lot.available_time > as_of_time:
            raise TrustedReplayError("state lot is not available at sellability boundary")
        lots.append(
            SellableLot(
                lot_id=lot.lot_id,
                acquisition_trade_date=lot.acquisition_trade_date,
                sellable_from_trade_date=lot.sellable_from_trade_date,
                quantity=lot.remaining_quantity,
                sellable_quantity=lot.remaining_quantity
                if lot.sellable_from_trade_date <= boundary_date
                else 0,
                available_time=min(lot.available_time, effective_available),
                source=provenance,
            )
        )
    lots_tuple = tuple(sorted(lots, key=lambda item: item.lot_id))
    snapshot_id = canonical_digest(
        (
            typed_state.state_digest,
            instrument_code,
            as_of_time.astimezone(UTC),
            effective_available.astimezone(UTC),
            provenance,
        )
    )
    return SellabilitySnapshot(
        snapshot_id=snapshot_id,
        instrument_code=instrument_code,
        as_of_time=as_of_time,
        available_time=effective_available,
        lots=lots_tuple,
        source=provenance,
    )


def export_sellability_snapshot(
    state: PortfolioState,
    instrument_code: str,
    as_of_time: datetime,
    *,
    source: TrustedPortfolioEventSource | None = None,
    execution_source: TrustedExecutionArtifactSource | None = None,
    available_time: datetime | None = None,
    provenance: ExecutionProvenance | None = None,
) -> SellabilitySnapshot:
    """Export sellability only after the predecessor is replayed from its tape."""

    if source is None:
        raise TrustedReplayError("trusted portfolio event source is required")
    typed_state = verify_portfolio_state_from_source(
        state,
        source,
        execution_source=execution_source,
    )
    return _export_sellability_snapshot_unchecked(
        typed_state,
        instrument_code,
        as_of_time,
        available_time=available_time,
        provenance=provenance,
    )


def value_portfolio(
    state: PortfolioState,
    cutoff_time: datetime,
    marks: tuple[ValuationMark, ...],
    *,
    source: TrustedPortfolioEventSource | None = None,
    execution_source: TrustedExecutionArtifactSource | None = None,
    policy: ValuationPolicy | None = None,
) -> PortfolioValuation:
    """Value only from point-in-time raw executable or raw market-close marks."""

    if source is None:
        raise TrustedReplayError("trusted portfolio event source is required")
    typed_state = verify_portfolio_state_from_source(
        state,
        source,
        execution_source=execution_source,
    )
    if cutoff_time.tzinfo is None or cutoff_time.utcoffset() is None:
        raise ValuationError("cutoff_time must be timezone-aware")
    if type(marks) is not tuple:
        raise ValuationError("marks must be an exact tuple")
    typed_marks: list[ValuationMark] = []
    for mark in marks:
        if type(mark) is not ValuationMark:
            raise ValuationError("marks must contain ValuationMark values")
        mark.validate_integrity()
        if mark.source not in (
            ValuationMarkSource.RAW_EXECUTABLE_QUOTE,
            ValuationMarkSource.RAW_MARKET_CLOSE,
        ):
            raise ValuationError("only raw accounting marks are admissible")
        if mark.mark_time > cutoff_time or mark.available_time > cutoff_time:
            raise ValuationError("valuation mark is future data")
        if (
            mark.provenance_available_time is not None
            and mark.provenance_available_time > cutoff_time
        ):
            raise ValuationError("valuation mark provenance is future data")
        typed_marks.append(mark)
    mark_keys = tuple(item.instrument_code for item in typed_marks)
    if mark_keys != tuple(sorted(mark_keys)) or len(mark_keys) != len(set(mark_keys)):
        raise ValuationError("marks must be canonical, unique, and sorted by instrument")
    instruments = tuple(sorted({lot.instrument_code for lot in typed_state.open_lots}))
    if any(item.instrument_code not in instruments for item in typed_marks):
        raise ValuationError("mark contains an instrument outside the portfolio")
    by_instrument = {item.instrument_code: item for item in typed_marks}
    if any(instrument not in by_instrument for instrument in instruments):
        raise ValuationError("complete raw mark coverage is required")
    marked_value = sum(
        (
            Decimal(lot.remaining_quantity) * by_instrument[lot.instrument_code].price
            for lot in typed_state.open_lots
        ),
        Decimal("0"),
    )
    book_cost = sum((lot.gross_cost for lot in typed_state.open_lots), Decimal("0"))
    nav = (
        typed_state.available_cash
        + typed_state.frozen_cash
        + typed_state.sale_cash_receivable
        + typed_state.dividend_or_corporate_cash_receivable
        + marked_value
    )
    unrealized = marked_value - book_cost
    total = nav - typed_state.initial_capital
    decomposition = (
        typed_state.realized_price_pnl
        + unrealized
        + typed_state.dividend_pnl
        + typed_state.other_corporate_action_pnl
        + typed_state.fee_pnl
    )
    if total != decomposition:
        raise ValuationError("valuation PnL decomposition does not reconcile")
    valuation_policy = ValuationPolicy() if policy is None else policy
    valuation_policy.validate_integrity()
    input_digest = canonical_digest(
        (cutoff_time.astimezone(UTC), typed_marks, valuation_policy.policy_digest)
    )
    return PortfolioValuation(
        cutoff_time=cutoff_time,
        initial_capital=typed_state.initial_capital,
        available_cash=typed_state.available_cash,
        frozen_cash=typed_state.frozen_cash,
        sale_cash_receivable=typed_state.sale_cash_receivable,
        dividend_or_corporate_cash_receivable=typed_state.dividend_or_corporate_cash_receivable,
        raw_marked_position_value=marked_value,
        book_position_cost=book_cost,
        nav=nav,
        realized_price_pnl=typed_state.realized_price_pnl,
        unrealized_price_pnl=unrealized,
        dividend_pnl=typed_state.dividend_pnl,
        other_corporate_action_pnl=typed_state.other_corporate_action_pnl,
        fee_pnl=typed_state.fee_pnl,
        total_pnl=total,
        complete_mark_coverage=True,
        valuation_policy_id=valuation_policy.policy_id,
        valuation_policy_version=valuation_policy.policy_version,
        valuation_policy_digest=valuation_policy.policy_digest,
        input_digest=input_digest,
        state_digest=typed_state.state_digest,
        sample_count=len(typed_marks),
    )


def verify_portfolio_valuation_against_state(
    valuation: PortfolioValuation,
    state: PortfolioState,
    source: TrustedPortfolioEventSource,
    marks: tuple[ValuationMark, ...],
    *,
    cutoff_time: datetime | None = None,
    policy: ValuationPolicy | None = None,
    execution_source: TrustedExecutionArtifactSource | None = None,
) -> PortfolioValuation:
    """Recompute a valuation from trusted history and original point-in-time marks."""

    try:
        valuation.validate_integrity()
    except Exception as error:
        raise ValuationError("valuation is structurally invalid") from error
    effective_cutoff = valuation.cutoff_time if cutoff_time is None else cutoff_time
    expected = value_portfolio(
        state,
        effective_cutoff,
        marks,
        source=source,
        execution_source=execution_source,
        policy=policy,
    )
    if expected != valuation:
        raise ValuationError("valuation does not match trusted state and marks")
    return expected


__all__ = [
    "apply_corporate_action",
    "apply_portfolio_event",
    "create_portfolio",
    "export_sellability_snapshot",
    "reserve_buy_cash",
    "settle_execution_bundle",
    "settle_execution_result",
    "value_portfolio",
    "verify_portfolio_valuation_against_state",
]
