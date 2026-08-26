"""Immutable simulation-only order lifecycle and event replay."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Final, Literal

from .allocation import PaperOrderIntent
from .models import (
    ZERO_DIGEST,
    PaperAccountEventConflictError,
    PaperAccountValidationError,
    canonical_digest,
)

EXECUTION_EVENT_SCHEMA_VERSION: Final = "paper-execution-event-v1"
EXECUTION_WORKSPACE_SCHEMA_VERSION: Final = "paper-execution-workspace-v1"
PAPER_ORDER_SCHEMA_VERSION: Final = "paper-order-v1"
_HASH = re.compile(r"^[0-9a-f]{64}$")


class PaperExecutionError(PaperAccountValidationError):
    """Raised when execution events violate immutable tape requirements."""


class PaperOrderStatus(str, Enum):
    CREATED = "CREATED"
    CHECKED = "CHECKED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class PaperAuditOutcome(str, Enum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"


class PaperOrderAlertCode(str, Enum):
    ILLEGAL_ORDER_TRANSITION = "ILLEGAL_ORDER_TRANSITION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    UNKNOWN_ORDER = "UNKNOWN_ORDER"
    FILL_CONFLICT = "FILL_CONFLICT"
    OVERFILL_REJECTED = "OVERFILL_REJECTED"


def _text(value: object, name: str, maximum: int = 240) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise PaperExecutionError(f"{name} must be a non-empty bounded string")
    return value


def _digest(value: object, name: str, *, allow_zero: bool = False) -> str:
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise PaperExecutionError(f"{name} must be a lowercase sha256 digest")
    if not allow_zero and value == ZERO_DIGEST:
        raise PaperExecutionError(f"{name} must not be the zero digest")
    return value


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise PaperExecutionError(f"{name} must be timezone-aware")
    return value


def _money(value: object, name: str, *, positive: bool = False) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise PaperExecutionError(f"{name} must be a finite Decimal")
    if value < 0 or (positive and value <= 0):
        qualifier = "positive" if positive else "non-negative"
        raise PaperExecutionError(f"{name} must be {qualifier}")
    return value


def _decimal_text(value: Decimal) -> str:
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result or "0"


def _time_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class PaperExecutionMetadata:
    account_id: str
    event_id: str
    sequence: int
    event_time: datetime
    available_time: datetime
    previous_event_digest: str
    source_id: str
    source_version: str
    schema_version: str = EXECUTION_EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _digest(self.account_id, "account_id")
        _digest(self.event_id, "event_id")
        if type(self.sequence) is not int or self.sequence < 0:
            raise PaperExecutionError("sequence must be a non-negative integer")
        event_time = _aware(self.event_time, "event_time")
        available_time = _aware(self.available_time, "available_time")
        if event_time > available_time:
            raise PaperExecutionError("event_time must not exceed available_time")
        _digest(self.previous_event_digest, "previous_event_digest", allow_zero=True)
        _text(self.source_id, "source_id")
        _text(self.source_version, "source_version")
        if self.schema_version != EXECUTION_EVENT_SCHEMA_VERSION:
            raise PaperExecutionError("unsupported execution event schema")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "account_id": self.account_id,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "event_time": _time_text(self.event_time),
            "available_time": _time_text(self.available_time),
            "previous_event_digest": self.previous_event_digest,
            "source_id": self.source_id,
            "source_version": self.source_version,
        }


@dataclass(frozen=True, slots=True)
class CreatePaperOrder:
    metadata: PaperExecutionMetadata
    client_order_id: str
    intent: PaperOrderIntent

    def __post_init__(self) -> None:
        _text(self.client_order_id, "client_order_id", 128)
        if type(self.intent) is not PaperOrderIntent:
            raise PaperExecutionError("intent must be an exact PaperOrderIntent")
        PaperOrderIntent.__post_init__(self.intent)
        if self.intent.account_id != self.metadata.account_id:
            raise PaperExecutionError("intent belongs to another account")

    def payload(self) -> dict[str, object]:
        return {
            "type": type(self).__name__,
            "metadata": self.metadata.payload(),
            "client_order_id": self.client_order_id,
            "intent": _intent_payload(self.intent),
        }


@dataclass(frozen=True, slots=True)
class CheckPaperOrder:
    metadata: PaperExecutionMetadata
    order_id: str
    accepted: bool
    rejection_code: str | None
    explanation: str

    def __post_init__(self) -> None:
        _digest(self.order_id, "order_id")
        if type(self.accepted) is not bool:
            raise PaperExecutionError("accepted must be a boolean")
        if self.accepted and self.rejection_code is not None:
            raise PaperExecutionError("accepted check cannot carry rejection_code")
        if not self.accepted:
            _text(self.rejection_code, "rejection_code")
        _text(self.explanation, "explanation")

    def payload(self) -> dict[str, object]:
        return {
            "type": type(self).__name__,
            "metadata": self.metadata.payload(),
            "order_id": self.order_id,
            "accepted": self.accepted,
            "rejection_code": self.rejection_code,
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True)
class SubmitPaperOrder:
    metadata: PaperExecutionMetadata
    order_id: str

    def __post_init__(self) -> None:
        _digest(self.order_id, "order_id")

    def payload(self) -> dict[str, object]:
        return {
            "type": type(self).__name__,
            "metadata": self.metadata.payload(),
            "order_id": self.order_id,
        }


@dataclass(frozen=True, slots=True)
class ApplyPaperFill:
    metadata: PaperExecutionMetadata
    order_id: str
    fill_id: str
    quantity: int
    price: Decimal
    fee: Decimal
    liquidity_evidence_id: str

    def __post_init__(self) -> None:
        _digest(self.order_id, "order_id")
        _digest(self.fill_id, "fill_id")
        if type(self.quantity) is not int or self.quantity <= 0:
            raise PaperExecutionError("fill quantity must be positive")
        _money(self.price, "price", positive=True)
        _money(self.fee, "fee")
        _text(self.liquidity_evidence_id, "liquidity_evidence_id")

    def payload(self) -> dict[str, object]:
        return {
            "type": type(self).__name__,
            "metadata": self.metadata.payload(),
            "order_id": self.order_id,
            "fill_id": self.fill_id,
            "quantity": self.quantity,
            "price": _decimal_text(self.price),
            "fee": _decimal_text(self.fee),
            "liquidity_evidence_id": self.liquidity_evidence_id,
        }


@dataclass(frozen=True, slots=True)
class RequestPaperCancel:
    metadata: PaperExecutionMetadata
    order_id: str
    reason: str

    def __post_init__(self) -> None:
        _digest(self.order_id, "order_id")
        _text(self.reason, "reason")

    def payload(self) -> dict[str, object]:
        return {
            "type": type(self).__name__,
            "metadata": self.metadata.payload(),
            "order_id": self.order_id,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class AcknowledgePaperCancel:
    metadata: PaperExecutionMetadata
    order_id: str

    def __post_init__(self) -> None:
        _digest(self.order_id, "order_id")

    def payload(self) -> dict[str, object]:
        return {
            "type": type(self).__name__,
            "metadata": self.metadata.payload(),
            "order_id": self.order_id,
        }


PaperExecutionEvent = (
    CreatePaperOrder
    | CheckPaperOrder
    | SubmitPaperOrder
    | ApplyPaperFill
    | RequestPaperCancel
    | AcknowledgePaperCancel
)


def execution_event_digest(event: PaperExecutionEvent) -> str:
    return canonical_digest(event.payload())


def paper_order_id(account_id: str, client_order_id: str) -> str:
    _digest(account_id, "account_id")
    _text(client_order_id, "client_order_id", 128)
    return canonical_digest(
        {"account_id": account_id, "client_order_id": client_order_id, "scope": "paper-order"}
    )


@dataclass(frozen=True, slots=True)
class PaperFill:
    fill_id: str
    quantity: int
    price: Decimal
    fee: Decimal
    event_time: datetime
    available_time: datetime
    liquidity_evidence_id: str


@dataclass(frozen=True, slots=True)
class PaperOrder:
    order_id: str
    client_order_id: str
    intent: PaperOrderIntent
    status: PaperOrderStatus
    filled_quantity: int
    average_fill_price: Decimal | None
    total_fees: Decimal
    fills: tuple[PaperFill, ...]
    created_at: datetime
    submitted_at: datetime | None
    updated_at: datetime
    schema_version: str = field(default=PAPER_ORDER_SCHEMA_VERSION, init=False)
    execution_capability: Literal["PAPER_ONLY"] = field(default="PAPER_ONLY", init=False)

    @property
    def remaining_quantity(self) -> int:
        return self.intent.quantity - self.filled_quantity


@dataclass(frozen=True, slots=True)
class PaperOrderAudit:
    event_id: str
    order_id: str
    event_type: str
    outcome: PaperAuditOutcome
    detail: str
    available_time: datetime


@dataclass(frozen=True, slots=True)
class PaperOrderAlert:
    alert_id: str
    event_id: str
    order_id: str
    code: PaperOrderAlertCode
    detail: str
    available_time: datetime


@dataclass(frozen=True, slots=True)
class PaperExecutionProjection:
    account_id: str
    orders: tuple[PaperOrder, ...]
    audits: tuple[PaperOrderAudit, ...]
    alerts: tuple[PaperOrderAlert, ...]
    event_count: int
    event_chain_digest: str
    state_digest: str = field(init=False)
    schema_version: str = field(default=EXECUTION_WORKSPACE_SCHEMA_VERSION, init=False)
    execution_capability: Literal["PAPER_ONLY"] = field(default="PAPER_ONLY", init=False)

    def __post_init__(self) -> None:
        _digest(self.account_id, "account_id")
        _digest(self.event_chain_digest, "event_chain_digest", allow_zero=self.event_count == 0)
        object.__setattr__(self, "state_digest", canonical_digest(self._digest_payload()))

    def _digest_payload(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "orders": [_order_payload(order) for order in self.orders],
            "audits": [_audit_payload(audit) for audit in self.audits],
            "alerts": [_alert_payload(alert) for alert in self.alerts],
            "event_count": self.event_count,
            "event_chain_digest": self.event_chain_digest,
            "execution_capability": self.execution_capability,
        }

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "accountId": self.account_id,
            "orders": [_order_contract(order) for order in self.orders],
            "audits": [_audit_contract(audit) for audit in self.audits],
            "alerts": [_alert_contract(alert) for alert in self.alerts],
            "eventCount": self.event_count,
            "eventChainDigest": self.event_chain_digest,
            "stateDigest": self.state_digest,
            "executionCapability": self.execution_capability,
            "dataMeaning": "SIMULATED_EXECUTION_NO_BROKER_PATH",
        }


@dataclass(frozen=True, slots=True)
class PaperExecutionTape:
    account_id: str
    events: tuple[PaperExecutionEvent, ...] = ()
    tape_digest: str = ""

    def __post_init__(self) -> None:
        previous = ZERO_DIGEST
        previous_time: datetime | None = None
        digests: list[str] = []
        for sequence, event in enumerate(self.events):
            metadata = event.metadata
            if metadata.account_id != self.account_id:
                raise PaperExecutionError("execution event belongs to another account")
            if metadata.sequence != sequence:
                raise PaperExecutionError("execution event sequence must be contiguous")
            if metadata.previous_event_digest != previous:
                raise PaperExecutionError("execution event digest chain is broken")
            if previous_time and metadata.available_time < previous_time:
                raise PaperExecutionError("execution event availability must be non-decreasing")
            digest = execution_event_digest(event)
            digests.append(digest)
            previous = digest
            previous_time = metadata.available_time
        computed = ZERO_DIGEST if not digests else canonical_digest(digests)
        if self.tape_digest and self.tape_digest != computed:
            raise PaperExecutionError("declared execution tape digest does not match events")
        object.__setattr__(self, "tape_digest", computed)

    @property
    def last_event_digest(self) -> str:
        return ZERO_DIGEST if not self.events else execution_event_digest(self.events[-1])


def append_execution_event(
    tape: PaperExecutionTape,
    event: PaperExecutionEvent,
) -> PaperExecutionTape:
    existing = next(
        (
            candidate
            for candidate in tape.events
            if candidate.metadata.event_id == event.metadata.event_id
        ),
        None,
    )
    if existing is not None:
        if execution_event_digest(existing) == execution_event_digest(event):
            return tape
        raise PaperAccountEventConflictError("execution event_id was reused with different content")
    if event.metadata.sequence != len(tape.events):
        raise PaperExecutionError("execution event sequence was based on stale state")
    if event.metadata.previous_event_digest != tape.last_event_digest:
        raise PaperExecutionError("execution previous digest was based on stale state")
    candidate = PaperExecutionTape(tape.account_id, tape.events + (event,))
    replay_execution(candidate)
    return candidate


def replay_execution(tape: PaperExecutionTape) -> PaperExecutionProjection:
    projection = PaperExecutionProjection(tape.account_id, (), (), (), 0, ZERO_DIGEST)
    for event in tape.events:
        projection = _apply_event(projection, event)
    return projection


def _apply_event(
    projection: PaperExecutionProjection,
    event: PaperExecutionEvent,
) -> PaperExecutionProjection:
    event_type = type(event).__name__
    if isinstance(event, CreatePaperOrder):
        return _create_order(projection, event)
    order_id = event.order_id
    order = next(
        (candidate for candidate in projection.orders if candidate.order_id == order_id), None
    )
    if order is None:
        return _record(
            projection,
            event,
            order_id,
            PaperAuditOutcome.REJECTED,
            "订单不存在",
            PaperOrderAlertCode.UNKNOWN_ORDER,
        )
    if type(event) is CheckPaperOrder:
        if order.status is not PaperOrderStatus.CREATED:
            return _illegal(projection, event, order, event_type)
        status = PaperOrderStatus.CHECKED if event.accepted else PaperOrderStatus.REJECTED
        updated = replace(order, status=status, updated_at=event.metadata.available_time)
        return _applied(projection, event, updated, event.explanation)
    if type(event) is SubmitPaperOrder:
        if order.status is not PaperOrderStatus.CHECKED:
            return _illegal(projection, event, order, event_type)
        updated = replace(
            order,
            status=PaperOrderStatus.SUBMITTED,
            submitted_at=event.metadata.available_time,
            updated_at=event.metadata.available_time,
        )
        return _applied(projection, event, updated, "模拟订单已提交到内部撮合边界")
    if type(event) is ApplyPaperFill:
        return _apply_fill(projection, event, order)
    if type(event) is RequestPaperCancel:
        if order.status is PaperOrderStatus.CANCEL_PENDING:
            return _record(
                projection,
                event,
                order.order_id,
                PaperAuditOutcome.DUPLICATE,
                "撤单请求已在处理中",
                None,
            )
        if order.status not in {PaperOrderStatus.SUBMITTED, PaperOrderStatus.PARTIALLY_FILLED}:
            return _illegal(projection, event, order, event_type)
        updated = replace(
            order,
            status=PaperOrderStatus.CANCEL_PENDING,
            updated_at=event.metadata.available_time,
        )
        return _applied(projection, event, updated, event.reason)
    if type(event) is AcknowledgePaperCancel:
        if order.status is not PaperOrderStatus.CANCEL_PENDING:
            return _illegal(projection, event, order, event_type)
        updated = replace(
            order,
            status=PaperOrderStatus.CANCELLED,
            updated_at=event.metadata.available_time,
        )
        return _applied(projection, event, updated, "剩余模拟数量已取消")
    raise PaperExecutionError("unsupported execution event")


def _create_order(
    projection: PaperExecutionProjection,
    event: CreatePaperOrder,
) -> PaperExecutionProjection:
    order_id = paper_order_id(event.metadata.account_id, event.client_order_id)
    existing = next(
        (order for order in projection.orders if order.client_order_id == event.client_order_id),
        None,
    )
    if existing is not None:
        if existing.intent.intent_id == event.intent.intent_id:
            return _record(
                projection,
                event,
                existing.order_id,
                PaperAuditOutcome.DUPLICATE,
                "clientOrderId 已创建相同模拟订单",
                None,
            )
        return _record(
            projection,
            event,
            existing.order_id,
            PaperAuditOutcome.REJECTED,
            "clientOrderId 已绑定不同 OrderIntent",
            PaperOrderAlertCode.IDEMPOTENCY_CONFLICT,
        )
    order = PaperOrder(
        order_id=order_id,
        client_order_id=event.client_order_id,
        intent=event.intent,
        status=PaperOrderStatus.CREATED,
        filled_quantity=0,
        average_fill_price=None,
        total_fees=Decimal("0"),
        fills=(),
        created_at=event.metadata.available_time,
        submitted_at=None,
        updated_at=event.metadata.available_time,
    )
    return _applied(projection, event, order, "模拟订单已创建")


def _apply_fill(
    projection: PaperExecutionProjection,
    event: ApplyPaperFill,
    order: PaperOrder,
) -> PaperExecutionProjection:
    existing_fill = next(
        (
            fill
            for candidate in projection.orders
            for fill in candidate.fills
            if fill.fill_id == event.fill_id
        ),
        None,
    )
    if existing_fill is not None:
        same = (
            existing_fill.quantity == event.quantity
            and existing_fill.price == event.price
            and existing_fill.fee == event.fee
        )
        return _record(
            projection,
            event,
            order.order_id,
            PaperAuditOutcome.DUPLICATE if same else PaperAuditOutcome.REJECTED,
            "fillId 已处理" if same else "fillId 已绑定不同成交内容",
            None if same else PaperOrderAlertCode.FILL_CONFLICT,
        )
    if order.status not in {
        PaperOrderStatus.SUBMITTED,
        PaperOrderStatus.PARTIALLY_FILLED,
        PaperOrderStatus.CANCEL_PENDING,
    }:
        return _illegal(projection, event, order, type(event).__name__)
    if event.quantity > order.remaining_quantity:
        return _record(
            projection,
            event,
            order.order_id,
            PaperAuditOutcome.REJECTED,
            "成交数量超过订单剩余数量",
            PaperOrderAlertCode.OVERFILL_REJECTED,
        )
    fill = PaperFill(
        event.fill_id,
        event.quantity,
        event.price,
        event.fee,
        event.metadata.event_time,
        event.metadata.available_time,
        event.liquidity_evidence_id,
    )
    previous_value = (
        Decimal("0")
        if order.average_fill_price is None
        else order.average_fill_price * Decimal(order.filled_quantity)
    )
    filled_quantity = order.filled_quantity + event.quantity
    average = (previous_value + event.price * Decimal(event.quantity)) / Decimal(filled_quantity)
    if filled_quantity == order.intent.quantity:
        status = PaperOrderStatus.FILLED
    elif order.status is PaperOrderStatus.CANCEL_PENDING:
        status = PaperOrderStatus.CANCEL_PENDING
    else:
        status = PaperOrderStatus.PARTIALLY_FILLED
    updated = replace(
        order,
        status=status,
        filled_quantity=filled_quantity,
        average_fill_price=average,
        total_fees=order.total_fees + event.fee,
        fills=order.fills + (fill,),
        updated_at=event.metadata.available_time,
    )
    return _applied(projection, event, updated, "模拟成交已按事件顺序入账")


def _illegal(
    projection: PaperExecutionProjection,
    event: PaperExecutionEvent,
    order: PaperOrder,
    event_type: str,
) -> PaperExecutionProjection:
    return _record(
        projection,
        event,
        order.order_id,
        PaperAuditOutcome.REJECTED,
        f"{event_type} 不允许从 {order.status.value} 状态执行",
        PaperOrderAlertCode.ILLEGAL_ORDER_TRANSITION,
    )


def _applied(
    projection: PaperExecutionProjection,
    event: PaperExecutionEvent,
    order: PaperOrder,
    detail: str,
) -> PaperExecutionProjection:
    orders = [candidate for candidate in projection.orders if candidate.order_id != order.order_id]
    orders.append(order)
    orders.sort(key=lambda item: item.order_id)
    changed = replace(projection, orders=tuple(orders))
    return _record(changed, event, order.order_id, PaperAuditOutcome.APPLIED, detail, None)


def _record(
    projection: PaperExecutionProjection,
    event: PaperExecutionEvent,
    order_id: str,
    outcome: PaperAuditOutcome,
    detail: str,
    alert_code: PaperOrderAlertCode | None,
) -> PaperExecutionProjection:
    audit = PaperOrderAudit(
        event.metadata.event_id,
        order_id,
        type(event).__name__,
        outcome,
        detail,
        event.metadata.available_time,
    )
    alerts = projection.alerts
    if alert_code is not None:
        alerts += (
            PaperOrderAlert(
                canonical_digest({"event_id": event.metadata.event_id, "code": alert_code.value}),
                event.metadata.event_id,
                order_id,
                alert_code,
                detail,
                event.metadata.available_time,
            ),
        )
    chain = canonical_digest([projection.event_chain_digest, execution_event_digest(event)])
    return replace(
        projection,
        audits=projection.audits + (audit,),
        alerts=alerts,
        event_count=projection.event_count + 1,
        event_chain_digest=chain,
    )


def _intent_payload(intent: PaperOrderIntent) -> dict[str, object]:
    return {
        "intent_id": intent.intent_id,
        "account_id": intent.account_id,
        "source_signal_ids": list(intent.source_signal_ids),
        "instrument_id": intent.instrument_id,
        "decision_time": _time_text(intent.decision_time),
        "side": intent.side.value,
        "quantity": intent.quantity,
        "reference_price": _decimal_text(intent.reference_price),
        "target_quantity": intent.target_quantity,
        "target_weight": _decimal_text(intent.target_weight),
        "policy_id": intent.policy_id,
        "policy_version": intent.policy_version,
        "policy_digest": intent.policy_digest,
        "explanation": intent.explanation,
        "broker_executable": intent.broker_executable,
        "execution_capability": intent.execution_capability,
    }


def _fill_payload(fill: PaperFill) -> dict[str, object]:
    return {
        "fill_id": fill.fill_id,
        "quantity": fill.quantity,
        "price": _decimal_text(fill.price),
        "fee": _decimal_text(fill.fee),
        "event_time": _time_text(fill.event_time),
        "available_time": _time_text(fill.available_time),
        "liquidity_evidence_id": fill.liquidity_evidence_id,
    }


def _order_payload(order: PaperOrder) -> dict[str, object]:
    return {
        "order_id": order.order_id,
        "client_order_id": order.client_order_id,
        "intent": _intent_payload(order.intent),
        "status": order.status.value,
        "filled_quantity": order.filled_quantity,
        "average_fill_price": (
            None if order.average_fill_price is None else _decimal_text(order.average_fill_price)
        ),
        "total_fees": _decimal_text(order.total_fees),
        "fills": [_fill_payload(fill) for fill in order.fills],
        "created_at": _time_text(order.created_at),
        "submitted_at": None if order.submitted_at is None else _time_text(order.submitted_at),
        "updated_at": _time_text(order.updated_at),
    }


def _audit_payload(audit: PaperOrderAudit) -> dict[str, object]:
    return {
        "event_id": audit.event_id,
        "order_id": audit.order_id,
        "event_type": audit.event_type,
        "outcome": audit.outcome.value,
        "detail": audit.detail,
        "available_time": _time_text(audit.available_time),
    }


def _alert_payload(alert: PaperOrderAlert) -> dict[str, object]:
    return {
        "alert_id": alert.alert_id,
        "event_id": alert.event_id,
        "order_id": alert.order_id,
        "code": alert.code.value,
        "detail": alert.detail,
        "available_time": _time_text(alert.available_time),
    }


def _order_contract(order: PaperOrder) -> dict[str, object]:
    return {
        "schemaVersion": order.schema_version,
        "orderId": order.order_id,
        "clientOrderId": order.client_order_id,
        "intentId": order.intent.intent_id,
        "instrumentId": order.intent.instrument_id,
        "side": order.intent.side.value,
        "quantity": order.intent.quantity,
        "filledQuantity": order.filled_quantity,
        "remainingQuantity": order.remaining_quantity,
        "averageFillPrice": (
            None if order.average_fill_price is None else _decimal_text(order.average_fill_price)
        ),
        "totalFees": _decimal_text(order.total_fees),
        "status": order.status.value,
        "fills": [
            {
                "fillId": fill.fill_id,
                "quantity": fill.quantity,
                "price": _decimal_text(fill.price),
                "fee": _decimal_text(fill.fee),
                "eventTime": _time_text(fill.event_time),
                "availableTime": _time_text(fill.available_time),
                "liquidityEvidenceId": fill.liquidity_evidence_id,
            }
            for fill in order.fills
        ],
        "createdAt": _time_text(order.created_at),
        "submittedAt": None if order.submitted_at is None else _time_text(order.submitted_at),
        "updatedAt": _time_text(order.updated_at),
        "executionCapability": order.execution_capability,
    }


def _audit_contract(audit: PaperOrderAudit) -> dict[str, object]:
    return {
        "eventId": audit.event_id,
        "orderId": audit.order_id,
        "eventType": audit.event_type,
        "outcome": audit.outcome.value,
        "detail": audit.detail,
        "availableTime": _time_text(audit.available_time),
    }


def _alert_contract(alert: PaperOrderAlert) -> dict[str, object]:
    return {
        "alertId": alert.alert_id,
        "eventId": alert.event_id,
        "orderId": alert.order_id,
        "code": alert.code.value,
        "detail": alert.detail,
        "availableTime": _time_text(alert.available_time),
    }
