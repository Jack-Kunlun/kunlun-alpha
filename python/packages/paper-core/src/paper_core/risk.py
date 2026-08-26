"""Fail-closed paper risk checks and independent book reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal
from zoneinfo import ZoneInfo

from .allocation import PaperIntentSide, PaperOrderIntent
from .execution import (
    CheckPaperOrder,
    PaperExecutionMetadata,
    PaperExecutionProjection,
    PaperFill,
    PaperOrder,
    PaperOrderStatus,
)
from .models import PaperAccountState, PaperAccountStatus, canonical_digest

RISK_DECISION_SCHEMA_VERSION = "paper-risk-decision-v1"
RECONCILIATION_SCHEMA_VERSION = "paper-reconciliation-result-v1"
SHANGHAI = ZoneInfo("Asia/Shanghai")


class PaperRiskError(ValueError):
    """Raised when risk or reconciliation inputs are not trustworthy."""


class RiskCheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class RiskCheckCode(str, Enum):
    ACCOUNT_ACTIVE = "ACCOUNT_ACTIVE"
    RISK_ENGINE_READY = "RISK_ENGINE_READY"
    EXECUTION_CONNECTED = "EXECUTION_CONNECTED"
    RECONCILIATION_HEALTHY = "RECONCILIATION_HEALTHY"
    ORDER_NOTIONAL_LIMIT = "ORDER_NOTIONAL_LIMIT"
    POSITION_WEIGHT_LIMIT = "POSITION_WEIGHT_LIMIT"
    DAILY_TURNOVER_LIMIT = "DAILY_TURNOVER_LIMIT"
    OPEN_ORDER_LIMIT = "OPEN_ORDER_LIMIT"
    CASH_AVAILABLE = "CASH_AVAILABLE"
    PAPER_ONLY_BOUNDARY = "PAPER_ONLY_BOUNDARY"


class ReconciliationHealth(str, Enum):
    MATCHED = "MATCHED"
    DRIFTED = "DRIFTED"
    UNAVAILABLE = "UNAVAILABLE"


class ReconciliationStatus(str, Enum):
    MATCHED = "MATCHED"
    DRIFTED = "DRIFTED"


class BookDiffKind(str, Enum):
    CASH = "CASH"
    POSITION_QUANTITY = "POSITION_QUANTITY"
    POSITION_COST = "POSITION_COST"


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise PaperRiskError(f"{name} must be a non-empty string")
    return value


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise PaperRiskError(f"{name} must be timezone-aware")
    return value


def _decimal(value: object, name: str, *, positive: bool = False) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise PaperRiskError(f"{name} must be a finite Decimal")
    if value < 0 or (positive and value <= 0):
        qualifier = "positive" if positive else "non-negative"
        raise PaperRiskError(f"{name} must be {qualifier}")
    return value


def _decimal_text(value: Decimal) -> str:
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result or "0"


def _time_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class PaperRiskPolicy:
    policy_id: str
    policy_version: str
    maximum_order_notional: Decimal
    maximum_position_weight: Decimal
    maximum_daily_turnover: Decimal
    maximum_open_orders: int
    minimum_cash_buffer: Decimal
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.policy_id, "policy_id")
        _text(self.policy_version, "policy_version")
        _decimal(self.maximum_order_notional, "maximum_order_notional", positive=True)
        position_weight = _decimal(
            self.maximum_position_weight, "maximum_position_weight", positive=True
        )
        if position_weight > 1:
            raise PaperRiskError("maximum_position_weight cannot exceed one")
        _decimal(self.maximum_daily_turnover, "maximum_daily_turnover", positive=True)
        if type(self.maximum_open_orders) is not int or self.maximum_open_orders <= 0:
            raise PaperRiskError("maximum_open_orders must be a positive integer")
        _decimal(self.minimum_cash_buffer, "minimum_cash_buffer")
        object.__setattr__(
            self,
            "policy_digest",
            canonical_digest(
                {
                    "policy_id": self.policy_id,
                    "policy_version": self.policy_version,
                    "maximum_order_notional": _decimal_text(self.maximum_order_notional),
                    "maximum_position_weight": _decimal_text(self.maximum_position_weight),
                    "maximum_daily_turnover": _decimal_text(self.maximum_daily_turnover),
                    "maximum_open_orders": self.maximum_open_orders,
                    "minimum_cash_buffer": _decimal_text(self.minimum_cash_buffer),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class PaperRiskEnvironment:
    risk_engine_ready: bool
    execution_connected: bool
    reconciliation_health: ReconciliationHealth

    def __post_init__(self) -> None:
        if type(self.risk_engine_ready) is not bool or type(self.execution_connected) is not bool:
            raise PaperRiskError("risk and execution health flags must be booleans")
        if type(self.reconciliation_health) is not ReconciliationHealth:
            raise PaperRiskError("reconciliation_health must be ReconciliationHealth")


@dataclass(frozen=True, slots=True)
class PaperRiskCheck:
    code: RiskCheckCode
    status: RiskCheckStatus
    actual: str
    limit: str | None
    explanation: str


@dataclass(frozen=True, slots=True)
class PaperRiskDecision:
    decision_id: str
    account_id: str
    intent_id: str
    decision_time: datetime
    allowed: bool
    checks: tuple[PaperRiskCheck, ...]
    account_state_digest: str
    execution_state_digest: str
    policy_id: str
    policy_version: str
    policy_digest: str
    schema_version: str = field(default=RISK_DECISION_SCHEMA_VERSION, init=False)
    execution_capability: Literal["PAPER_ONLY"] = field(default="PAPER_ONLY", init=False)

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "decisionId": self.decision_id,
            "accountId": self.account_id,
            "intentId": self.intent_id,
            "decisionTime": _time_text(self.decision_time),
            "allowed": self.allowed,
            "checks": [
                {
                    "code": check.code.value,
                    "status": check.status.value,
                    "actual": check.actual,
                    "limit": check.limit,
                    "explanation": check.explanation,
                }
                for check in self.checks
            ],
            "accountStateDigest": self.account_state_digest,
            "executionStateDigest": self.execution_state_digest,
            "policyId": self.policy_id,
            "policyVersion": self.policy_version,
            "policyDigest": self.policy_digest,
            "executionCapability": self.execution_capability,
            "dataMeaning": "SERVER_SIDE_RISK_NO_BROKER_PATH",
        }


def evaluate_pretrade_risk(
    intent: PaperOrderIntent,
    *,
    account: PaperAccountState,
    execution: PaperExecutionProjection,
    decision_time: datetime,
    policy: PaperRiskPolicy,
    environment: PaperRiskEnvironment,
) -> PaperRiskDecision:
    decision_at = _aware(decision_time, "decision_time")
    PaperOrderIntent.__post_init__(intent)
    if canonical_digest(account.digest_payload()) != account.state_digest:
        raise PaperRiskError("account state digest is invalid")
    if canonical_digest(execution.digest_payload()) != execution.state_digest:
        raise PaperRiskError("execution state digest is invalid")
    if account.account_id != intent.account_id or execution.account_id != intent.account_id:
        raise PaperRiskError("risk inputs belong to different accounts")
    active_statuses = {
        PaperOrderStatus.CREATED,
        PaperOrderStatus.CHECKED,
        PaperOrderStatus.SUBMITTED,
        PaperOrderStatus.PARTIALLY_FILLED,
        PaperOrderStatus.CANCEL_PENDING,
    }
    open_orders = tuple(order for order in execution.orders if order.status in active_statuses)
    other_buy_reservations = sum(
        (
            Decimal(order.remaining_quantity) * order.intent.reference_price
            for order in open_orders
            if order.intent.side is PaperIntentSide.BUY
            and order.intent.intent_id != intent.intent_id
        ),
        start=Decimal("0"),
    )
    order_notional = Decimal(intent.quantity) * intent.reference_price
    turnover = _daily_turnover(execution, decision_at)
    required_cash = order_notional if intent.side is PaperIntentSide.BUY else Decimal("0")
    cash_after_existing_reservations = account.cash - other_buy_reservations
    paper_boundary = (
        intent.broker_executable is False and intent.execution_capability == "PAPER_ONLY"
    )
    checks = (
        _check(
            RiskCheckCode.ACCOUNT_ACTIVE,
            account.status is PaperAccountStatus.ACTIVE,
            account.status.value,
            PaperAccountStatus.ACTIVE.value,
            "账户必须处于 ACTIVE 状态",
        ),
        _check(
            RiskCheckCode.RISK_ENGINE_READY,
            environment.risk_engine_ready,
            str(environment.risk_engine_ready).lower(),
            "true",
            "风控引擎不可用时拒绝新意图",
        ),
        _check(
            RiskCheckCode.EXECUTION_CONNECTED,
            environment.execution_connected,
            str(environment.execution_connected).lower(),
            "true",
            "模拟执行边界断连时拒绝新意图",
        ),
        _check(
            RiskCheckCode.RECONCILIATION_HEALTHY,
            environment.reconciliation_health is ReconciliationHealth.MATCHED,
            environment.reconciliation_health.value,
            ReconciliationHealth.MATCHED.value,
            "仅在最近一次账簿对账一致时允许新意图",
        ),
        _check(
            RiskCheckCode.ORDER_NOTIONAL_LIMIT,
            order_notional <= policy.maximum_order_notional,
            _decimal_text(order_notional),
            _decimal_text(policy.maximum_order_notional),
            "单笔参考名义金额不得超过策略上限",
        ),
        _check(
            RiskCheckCode.POSITION_WEIGHT_LIMIT,
            intent.target_weight <= policy.maximum_position_weight,
            _decimal_text(intent.target_weight),
            _decimal_text(policy.maximum_position_weight),
            "目标持仓权重不得超过风控集中度上限",
        ),
        _check(
            RiskCheckCode.DAILY_TURNOVER_LIMIT,
            turnover + order_notional <= policy.maximum_daily_turnover,
            _decimal_text(turnover + order_notional),
            _decimal_text(policy.maximum_daily_turnover),
            "当日已成交金额加当前意图不得超过换手上限",
        ),
        _check(
            RiskCheckCode.OPEN_ORDER_LIMIT,
            len(open_orders) <= policy.maximum_open_orders,
            str(len(open_orders)),
            str(policy.maximum_open_orders),
            "活动模拟订单数量不得超过上限",
        ),
        _check(
            RiskCheckCode.CASH_AVAILABLE,
            cash_after_existing_reservations - required_cash >= policy.minimum_cash_buffer,
            _decimal_text(cash_after_existing_reservations - required_cash),
            _decimal_text(policy.minimum_cash_buffer),
            "扣除其他活动买单和当前买单后必须保留最低现金",
        ),
        _check(
            RiskCheckCode.PAPER_ONLY_BOUNDARY,
            paper_boundary,
            intent.execution_capability,
            "PAPER_ONLY",
            "风控只接受永久模拟隔离的 OrderIntent",
        ),
    )
    allowed = all(check.status is RiskCheckStatus.PASS for check in checks)
    seed = {
        "account_id": account.account_id,
        "intent_id": intent.intent_id,
        "decision_time": _time_text(decision_at),
        "account_state_digest": account.state_digest,
        "execution_state_digest": execution.state_digest,
        "policy_digest": policy.policy_digest,
        "checks": [
            {"code": check.code.value, "status": check.status.value, "actual": check.actual}
            for check in checks
        ],
    }
    decision_id = canonical_digest(seed)
    return PaperRiskDecision(
        decision_id,
        account.account_id,
        intent.intent_id,
        decision_at,
        allowed,
        checks,
        account.state_digest,
        execution.state_digest,
        policy.policy_id,
        policy.policy_version,
        policy.policy_digest,
    )


def create_risk_check_event(
    metadata: PaperExecutionMetadata,
    *,
    order: PaperOrder,
    execution: PaperExecutionProjection,
    decision: PaperRiskDecision,
) -> CheckPaperOrder:
    if execution.state_digest != decision.execution_state_digest:
        raise PaperRiskError("risk decision is stale for the current execution state")
    if (
        order.intent.intent_id != decision.intent_id
        or order.intent.account_id != decision.account_id
    ):
        raise PaperRiskError("risk decision is not bound to this order intent")
    if metadata.account_id != decision.account_id:
        raise PaperRiskError("risk check metadata belongs to another account")
    failures = [
        check.code.value for check in decision.checks if check.status is RiskCheckStatus.FAIL
    ]
    rejection_code = None if decision.allowed else ",".join(failures)
    explanation = (
        "服务端风控检查全部通过" if decision.allowed else f"服务端风控拒绝: {rejection_code}"
    )
    return CheckPaperOrder(
        metadata,
        order.order_id,
        decision.allowed,
        rejection_code,
        explanation,
        decision.decision_id,
        decision.policy_digest,
    )


def _check(
    code: RiskCheckCode, passed: bool, actual: str, limit: str | None, explanation: str
) -> PaperRiskCheck:
    return PaperRiskCheck(
        code, RiskCheckStatus.PASS if passed else RiskCheckStatus.FAIL, actual, limit, explanation
    )


def _daily_turnover(execution: PaperExecutionProjection, decision_time: datetime) -> Decimal:
    trading_date = decision_time.astimezone(SHANGHAI).date()
    return sum(
        (
            fill.price * Decimal(fill.quantity)
            for order in execution.orders
            for fill in order.fills
            if fill.available_time <= decision_time
            and fill.event_time.astimezone(SHANGHAI).date() == trading_date
        ),
        start=Decimal("0"),
    )


@dataclass(frozen=True, slots=True)
class PaperBookPosition:
    instrument_id: str
    quantity: int
    cost_amount: Decimal

    def __post_init__(self) -> None:
        _text(self.instrument_id, "instrument_id")
        if type(self.quantity) is not int or self.quantity <= 0:
            raise PaperRiskError("book position quantity must be positive")
        _decimal(self.cost_amount, "cost_amount")


@dataclass(frozen=True, slots=True)
class PaperSettlementBook:
    account_id: str
    cash: Decimal
    positions: tuple[PaperBookPosition, ...]
    cutoff_time: datetime
    book_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.account_id, "account_id")
        if type(self.cash) is not Decimal or not self.cash.is_finite():
            raise PaperRiskError("cash must be a finite Decimal")
        if type(self.positions) is not tuple:
            raise PaperRiskError("positions must be an immutable tuple")
        ids = [position.instrument_id for position in self.positions]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise PaperRiskError("book positions must be sorted and unique")
        _aware(self.cutoff_time, "cutoff_time")
        object.__setattr__(self, "book_digest", canonical_digest(self.payload()))

    def payload(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "cash": _decimal_text(self.cash),
            "positions": [
                {
                    "instrument_id": position.instrument_id,
                    "quantity": position.quantity,
                    "cost_amount": _decimal_text(position.cost_amount),
                }
                for position in self.positions
            ],
            "cutoff_time": _time_text(self.cutoff_time),
        }


@dataclass(frozen=True, slots=True)
class PaperExecutionBookProjection:
    book: PaperSettlementBook
    duplicate_fill_count: int


@dataclass(frozen=True, slots=True)
class PaperBookDiff:
    kind: BookDiffKind
    instrument_id: str | None
    expected: str
    observed: str
    difference: str


@dataclass(frozen=True, slots=True)
class PaperReconciliationResult:
    reconciliation_id: str
    account_id: str
    as_of: datetime
    status: ReconciliationStatus
    expected_book_digest: str
    observed_book_digest: str
    diffs: tuple[PaperBookDiff, ...]
    duplicate_fill_count: int
    schema_version: str = field(default=RECONCILIATION_SCHEMA_VERSION, init=False)
    execution_capability: Literal["PAPER_ONLY"] = field(default="PAPER_ONLY", init=False)

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "reconciliationId": self.reconciliation_id,
            "accountId": self.account_id,
            "asOf": _time_text(self.as_of),
            "status": self.status.value,
            "expectedBookDigest": self.expected_book_digest,
            "observedBookDigest": self.observed_book_digest,
            "diffs": [
                {
                    "kind": diff.kind.value,
                    "instrumentId": diff.instrument_id,
                    "expected": diff.expected,
                    "observed": diff.observed,
                    "difference": diff.difference,
                }
                for diff in self.diffs
            ],
            "duplicateFillCount": self.duplicate_fill_count,
            "executionCapability": self.execution_capability,
            "dataMeaning": "SIMULATION_BOOK_RECONCILIATION",
        }


def book_from_account(account: PaperAccountState, *, as_of: datetime) -> PaperSettlementBook:
    cutoff = _aware(as_of, "as_of")
    if account.data_cutoff_time > cutoff:
        raise PaperRiskError("account state is not available at reconciliation cutoff")
    return PaperSettlementBook(
        account.account_id,
        account.cash,
        tuple(
            PaperBookPosition(position.instrument_id, position.quantity, position.cost_amount)
            for position in account.positions
        ),
        cutoff,
    )


def project_execution_book(
    opening: PaperSettlementBook, execution: PaperExecutionProjection, *, as_of: datetime
) -> PaperExecutionBookProjection:
    cutoff = _aware(as_of, "as_of")
    if opening.account_id != execution.account_id:
        raise PaperRiskError("opening and execution books belong to different accounts")
    if canonical_digest(execution.digest_payload()) != execution.state_digest:
        raise PaperRiskError("execution state digest is invalid")
    cash = opening.cash
    positions: dict[str, tuple[int, Decimal]] = {
        position.instrument_id: (position.quantity, position.cost_amount)
        for position in opening.positions
    }
    fills: list[tuple[datetime, str, PaperIntentSide, str, PaperFill]] = []
    seen: dict[str, tuple[PaperIntentSide, str, int, Decimal, Decimal]] = {}
    duplicate_count = 0
    for order in execution.orders:
        for fill in order.fills:
            if fill.available_time > cutoff:
                continue
            identity = (
                order.intent.side,
                order.intent.instrument_id,
                fill.quantity,
                fill.price,
                fill.fee,
            )
            previous = seen.get(fill.fill_id)
            if previous is not None:
                if previous != identity:
                    raise PaperRiskError("fillId conflict detected during reconciliation")
                duplicate_count += 1
                continue
            seen[fill.fill_id] = identity
            fills.append(
                (
                    fill.available_time,
                    fill.fill_id,
                    order.intent.side,
                    order.intent.instrument_id,
                    fill,
                )
            )
    for _, _, side, instrument_id, fill in sorted(fills, key=lambda item: (item[0], item[1])):
        gross = fill.price * Decimal(fill.quantity)
        quantity, cost = positions.get(instrument_id, (0, Decimal("0")))
        if side is PaperIntentSide.BUY:
            cash -= gross + fill.fee
            quantity += fill.quantity
            cost += gross + fill.fee
        else:
            if fill.quantity > quantity:
                raise PaperRiskError("sell fill exceeds reconciliation position")
            removed_cost = (
                cost
                if fill.quantity == quantity
                else cost * Decimal(fill.quantity) / Decimal(quantity)
            )
            cash += gross - fill.fee
            quantity -= fill.quantity
            cost -= removed_cost
        if quantity == 0:
            positions.pop(instrument_id, None)
        else:
            positions[instrument_id] = (quantity, cost)
    projected_positions = tuple(
        PaperBookPosition(instrument_id, quantity, cost)
        for instrument_id, (quantity, cost) in sorted(positions.items())
    )
    return PaperExecutionBookProjection(
        PaperSettlementBook(opening.account_id, cash, projected_positions, cutoff), duplicate_count
    )


def reconcile_paper_books(
    expected: PaperExecutionBookProjection,
    observed: PaperSettlementBook,
    *,
    tolerance: Decimal = Decimal("0"),
) -> PaperReconciliationResult:
    allowed_tolerance = _decimal(tolerance, "tolerance")
    if expected.book.account_id != observed.account_id:
        raise PaperRiskError("expected and observed books belong to different accounts")
    if expected.book.cutoff_time != observed.cutoff_time:
        raise PaperRiskError("expected and observed books must use the same cutoff")
    diffs: list[PaperBookDiff] = []
    cash_difference = observed.cash - expected.book.cash
    if abs(cash_difference) > allowed_tolerance:
        diffs.append(
            PaperBookDiff(
                BookDiffKind.CASH,
                None,
                _decimal_text(expected.book.cash),
                _decimal_text(observed.cash),
                _decimal_text(cash_difference),
            )
        )
    expected_positions = {item.instrument_id: item for item in expected.book.positions}
    observed_positions = {item.instrument_id: item for item in observed.positions}
    for instrument_id in sorted(expected_positions.keys() | observed_positions.keys()):
        expected_position = expected_positions.get(instrument_id)
        observed_position = observed_positions.get(instrument_id)
        expected_quantity = expected_position.quantity if expected_position else 0
        observed_quantity = observed_position.quantity if observed_position else 0
        if expected_quantity != observed_quantity:
            diffs.append(
                PaperBookDiff(
                    BookDiffKind.POSITION_QUANTITY,
                    instrument_id,
                    str(expected_quantity),
                    str(observed_quantity),
                    str(observed_quantity - expected_quantity),
                )
            )
        expected_cost = expected_position.cost_amount if expected_position else Decimal("0")
        observed_cost = observed_position.cost_amount if observed_position else Decimal("0")
        cost_difference = observed_cost - expected_cost
        if abs(cost_difference) > allowed_tolerance:
            diffs.append(
                PaperBookDiff(
                    BookDiffKind.POSITION_COST,
                    instrument_id,
                    _decimal_text(expected_cost),
                    _decimal_text(observed_cost),
                    _decimal_text(cost_difference),
                )
            )
    status = ReconciliationStatus.MATCHED if not diffs else ReconciliationStatus.DRIFTED
    seed = {
        "account_id": observed.account_id,
        "as_of": _time_text(observed.cutoff_time),
        "expected": expected.book.book_digest,
        "observed": observed.book_digest,
        "diffs": [
            {
                "kind": diff.kind.value,
                "instrument_id": diff.instrument_id,
                "difference": diff.difference,
            }
            for diff in diffs
        ],
        "duplicate_fill_count": expected.duplicate_fill_count,
    }
    return PaperReconciliationResult(
        canonical_digest(seed),
        observed.account_id,
        observed.cutoff_time,
        status,
        expected.book.book_digest,
        observed.book_digest,
        tuple(diffs),
        expected.duplicate_fill_count,
    )
