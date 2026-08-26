"""Deterministic Signal to paper OrderIntent allocation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from enum import Enum
from typing import Literal

from quant_core.strategy import Signal, SignalDirection, StrategyInputError

from .models import (
    PaperAccountState,
    PaperAccountStatus,
    PaperAccountValidationError,
    canonical_digest,
)

ALLOCATION_SCHEMA_VERSION = "paper-allocation-decision-v1"
ORDER_INTENT_SCHEMA_VERSION = "paper-order-intent-v1"
_INSTRUMENT = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$")


class PaperAllocationError(PaperAccountValidationError):
    """Raised when allocation inputs violate the deterministic boundary."""


class PaperIntentSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class AllocationRejectionReason(str, Enum):
    ACCOUNT_NOT_ACTIVE = "ACCOUNT_NOT_ACTIVE"
    CONFLICTING_SIGNALS = "CONFLICTING_SIGNALS"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    SHORT_NOT_SUPPORTED = "SHORT_NOT_SUPPORTED"
    MISSING_MARKET_DATA = "MISSING_MARKET_DATA"
    FUTURE_DATA = "FUTURE_DATA"
    MISSING_VALUATION = "MISSING_VALUATION"
    BOARD_LOT_ROUNDED_TO_ZERO = "BOARD_LOT_ROUNDED_TO_ZERO"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    NO_ACTION = "NO_ACTION"


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise PaperAllocationError(f"{name} must be timezone-aware")
    return value


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise PaperAllocationError(f"{name} must be a non-empty string")
    return value


def _weight(value: object, name: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite() or value < 0 or value > 1:
        raise PaperAllocationError(f"{name} must be a Decimal between 0 and 1")
    return value


def _positive_money(value: object, name: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite() or value <= 0:
        raise PaperAllocationError(f"{name} must be a positive Decimal")
    return value


def _decimal_text(value: Decimal) -> str:
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result or "0"


def _time_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class PaperMarketQuote:
    instrument_id: str
    price: Decimal
    observed_time: datetime
    available_time: datetime
    lot_size: int
    source_version: str
    evidence_id: str

    def __post_init__(self) -> None:
        if _INSTRUMENT.fullmatch(self.instrument_id) is None:
            raise PaperAllocationError("instrument_id must use canonical A-share form")
        _positive_money(self.price, "price")
        observed = _aware(self.observed_time, "observed_time")
        available = _aware(self.available_time, "available_time")
        if observed > available:
            raise PaperAllocationError("quote observed_time must not exceed available_time")
        if type(self.lot_size) is not int or self.lot_size <= 0:
            raise PaperAllocationError("lot_size must be a positive integer")
        _text(self.source_version, "source_version")
        _text(self.evidence_id, "evidence_id")


@dataclass(frozen=True, slots=True)
class PaperAllocationPolicy:
    policy_id: str
    policy_version: str
    maximum_position_weight: Decimal
    maximum_total_weight: Decimal
    cash_buffer_weight: Decimal
    minimum_confidence: Decimal
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.policy_id, "policy_id")
        _text(self.policy_version, "policy_version")
        maximum_position = _weight(self.maximum_position_weight, "maximum_position_weight")
        maximum_total = _weight(self.maximum_total_weight, "maximum_total_weight")
        cash_buffer = _weight(self.cash_buffer_weight, "cash_buffer_weight")
        _weight(self.minimum_confidence, "minimum_confidence")
        if maximum_position <= 0 or maximum_total <= 0:
            raise PaperAllocationError("position and total weights must be positive")
        if maximum_position > maximum_total:
            raise PaperAllocationError("maximum_position_weight cannot exceed total weight")
        if maximum_total + cash_buffer > 1:
            raise PaperAllocationError("total allocation plus cash buffer cannot exceed one")
        object.__setattr__(
            self,
            "policy_digest",
            canonical_digest(
                {
                    "policy_id": self.policy_id,
                    "policy_version": self.policy_version,
                    "maximum_position_weight": _decimal_text(maximum_position),
                    "maximum_total_weight": _decimal_text(maximum_total),
                    "cash_buffer_weight": _decimal_text(cash_buffer),
                    "minimum_confidence": _decimal_text(self.minimum_confidence),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class PaperTargetPosition:
    instrument_id: str
    source_signal_ids: tuple[str, ...]
    current_quantity: int
    target_quantity: int
    target_weight: Decimal
    reference_price: Decimal
    rounding_lot_size: int
    explanation: str


@dataclass(frozen=True, slots=True)
class PaperOrderIntent:
    intent_id: str
    account_id: str
    source_signal_ids: tuple[str, ...]
    instrument_id: str
    decision_time: datetime
    side: PaperIntentSide
    quantity: int
    reference_price: Decimal
    target_quantity: int
    target_weight: Decimal
    policy_id: str
    policy_version: str
    policy_digest: str
    explanation: str
    schema_version: str = field(default=ORDER_INTENT_SCHEMA_VERSION, init=False)
    broker_executable: Literal[False] = field(default=False, init=False)
    execution_capability: Literal["PAPER_ONLY"] = field(default="PAPER_ONLY", init=False)

    def __post_init__(self) -> None:
        if type(self.quantity) is not int or self.quantity <= 0:
            raise PaperAllocationError("intent quantity must be positive")
        if self.broker_executable is not False or self.execution_capability != "PAPER_ONLY":
            raise PaperAllocationError("paper intent must not expose a broker execution path")


@dataclass(frozen=True, slots=True)
class PaperAllocationRejection:
    instrument_id: str
    source_signal_ids: tuple[str, ...]
    reason: AllocationRejectionReason
    explanation: str


@dataclass(frozen=True, slots=True)
class PaperAllocationDecision:
    decision_id: str
    account_id: str
    decision_time: datetime
    account_state_digest: str
    policy_id: str
    policy_version: str
    policy_digest: str
    targets: tuple[PaperTargetPosition, ...]
    intents: tuple[PaperOrderIntent, ...]
    rejections: tuple[PaperAllocationRejection, ...]
    decision_digest: str
    schema_version: str = field(default=ALLOCATION_SCHEMA_VERSION, init=False)
    execution_capability: Literal["PAPER_ONLY"] = field(default="PAPER_ONLY", init=False)

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "decisionId": self.decision_id,
            "accountId": self.account_id,
            "decisionTime": _time_text(self.decision_time),
            "accountStateDigest": self.account_state_digest,
            "policyId": self.policy_id,
            "policyVersion": self.policy_version,
            "policyDigest": self.policy_digest,
            "targets": [
                {
                    "instrumentId": target.instrument_id,
                    "sourceSignalIds": list(target.source_signal_ids),
                    "currentQuantity": target.current_quantity,
                    "targetQuantity": target.target_quantity,
                    "targetWeight": _decimal_text(target.target_weight),
                    "referencePrice": _decimal_text(target.reference_price),
                    "roundingLotSize": target.rounding_lot_size,
                    "explanation": target.explanation,
                }
                for target in self.targets
            ],
            "intents": [
                {
                    "schemaVersion": intent.schema_version,
                    "intentId": intent.intent_id,
                    "accountId": intent.account_id,
                    "sourceSignalIds": list(intent.source_signal_ids),
                    "instrumentId": intent.instrument_id,
                    "decisionTime": _time_text(intent.decision_time),
                    "side": intent.side.value,
                    "quantity": intent.quantity,
                    "referencePrice": _decimal_text(intent.reference_price),
                    "targetQuantity": intent.target_quantity,
                    "targetWeight": _decimal_text(intent.target_weight),
                    "policyId": intent.policy_id,
                    "policyVersion": intent.policy_version,
                    "policyDigest": intent.policy_digest,
                    "explanation": intent.explanation,
                    "brokerExecutable": intent.broker_executable,
                    "executionCapability": intent.execution_capability,
                }
                for intent in self.intents
            ],
            "rejections": [
                {
                    "instrumentId": rejection.instrument_id,
                    "sourceSignalIds": list(rejection.source_signal_ids),
                    "reason": rejection.reason.value,
                    "explanation": rejection.explanation,
                }
                for rejection in self.rejections
            ],
            "decisionDigest": self.decision_digest,
            "executionCapability": self.execution_capability,
            "dataMeaning": "INTENT_ONLY_NO_BROKER_PATH",
        }


@dataclass(frozen=True, slots=True)
class _Candidate:
    instrument_id: str
    source_signal_ids: tuple[str, ...]
    signal: Signal
    raw_weight: Decimal


def allocate_signals(
    signals: tuple[Signal, ...],
    *,
    account: PaperAccountState,
    quotes: tuple[PaperMarketQuote, ...],
    decision_time: datetime,
    policy: PaperAllocationPolicy,
) -> PaperAllocationDecision:
    decision_at = _aware(decision_time, "decision_time")
    if canonical_digest(account.digest_payload()) != account.state_digest:
        raise PaperAllocationError("account state digest is invalid")
    if type(signals) is not tuple or type(quotes) is not tuple:
        raise PaperAllocationError("signals and quotes must be immutable tuples")
    quote_map = {quote.instrument_id: quote for quote in quotes}
    if len(quote_map) != len(quotes):
        raise PaperAllocationError("quotes must be unique by instrument")
    groups: dict[str, list[Signal]] = {}
    for signal in signals:
        if type(signal) is not Signal:
            raise PaperAllocationError("signals must contain exact Signal values")
        try:
            Signal.__post_init__(signal)
        except StrategyInputError as error:
            raise PaperAllocationError("signal failed integrity validation") from error
        if _INSTRUMENT.fullmatch(signal.entity_id) is None:
            raise PaperAllocationError("signal entity_id must be a canonical A-share instrument")
        groups.setdefault(signal.entity_id, []).append(signal)

    rejections: list[PaperAllocationRejection] = []
    candidates: list[_Candidate] = []
    account_rejection = _account_rejection(account, decision_at)
    for instrument_id in sorted(groups):
        group = sorted(groups[instrument_id], key=lambda item: item.signal_id)
        signal_ids = tuple(item.signal_id for item in group)
        if account_rejection is not None:
            rejections.append(_reject(instrument_id, signal_ids, *account_rejection))
            continue
        directions = {item.direction for item in group}
        if len(directions) > 1:
            rejections.append(
                _reject(
                    instrument_id,
                    signal_ids,
                    AllocationRejectionReason.CONFLICTING_SIGNALS,
                    "同一证券在同一决策时点存在互相冲突的方向",
                )
            )
            continue
        selected = max(group, key=lambda item: (item.confidence, abs(item.score), item.signal_id))
        if selected.decision_time > decision_at or selected.data_cutoff_time > decision_at:
            rejections.append(
                _reject(
                    instrument_id,
                    signal_ids,
                    AllocationRejectionReason.FUTURE_DATA,
                    "Signal 的决策时间或数据截止时间晚于当前决策",
                )
            )
            continue
        if selected.confidence < policy.minimum_confidence:
            rejections.append(
                _reject(
                    instrument_id,
                    signal_ids,
                    AllocationRejectionReason.LOW_CONFIDENCE,
                    "Signal 置信度低于分配策略门槛",
                )
            )
            continue
        if selected.direction is SignalDirection.SHORT:
            rejections.append(
                _reject(
                    instrument_id,
                    signal_ids,
                    AllocationRejectionReason.SHORT_NOT_SUPPORTED,
                    "模拟账户不支持卖空目标",
                )
            )
            continue
        score = max(selected.score, Decimal("0"))
        raw_weight = (
            Decimal("0")
            if selected.direction is SignalDirection.NEUTRAL
            else min(policy.maximum_position_weight, score * selected.confidence)
        )
        candidates.append(_Candidate(instrument_id, signal_ids, selected, raw_weight))

    total = sum((candidate.raw_weight for candidate in candidates), start=Decimal("0"))
    scale = (
        Decimal("1")
        if total <= policy.maximum_total_weight
        else policy.maximum_total_weight / total
    )
    nav = _account_nav(account)
    targets: list[PaperTargetPosition] = []
    intents: list[PaperOrderIntent] = []
    available_cash = max(Decimal("0"), account.cash - nav * policy.cash_buffer_weight)
    positions = {position.instrument_id: position for position in account.positions}
    for candidate in candidates:
        quote = quote_map.get(candidate.instrument_id)
        if quote is None:
            rejections.append(
                _reject(
                    candidate.instrument_id,
                    candidate.source_signal_ids,
                    AllocationRejectionReason.MISSING_MARKET_DATA,
                    "缺少用于目标仓位和板手数计算的行情",
                )
            )
            continue
        if quote.available_time > decision_at:
            rejections.append(
                _reject(
                    candidate.instrument_id,
                    candidate.source_signal_ids,
                    AllocationRejectionReason.FUTURE_DATA,
                    "行情在当前决策时点尚不可用",
                )
            )
            continue
        weight = candidate.raw_weight * scale
        current_position = positions.get(candidate.instrument_id)
        current_quantity = 0 if current_position is None else current_position.quantity
        desired_quantity = int((nav * weight / quote.price).to_integral_value(rounding=ROUND_DOWN))
        target_quantity = _round_target(current_quantity, desired_quantity, quote.lot_size)
        delta = target_quantity - current_quantity
        if delta == 0:
            reason = (
                AllocationRejectionReason.BOARD_LOT_ROUNDED_TO_ZERO
                if desired_quantity != current_quantity
                else AllocationRejectionReason.NO_ACTION
            )
            rejections.append(
                _reject(
                    candidate.instrument_id,
                    candidate.source_signal_ids,
                    reason,
                    "目标变化不足一个交易单位，未生成 OrderIntent"
                    if reason is AllocationRejectionReason.BOARD_LOT_ROUNDED_TO_ZERO
                    else "当前持仓已经等于目标持仓",
                )
            )
            continue
        required_cash = Decimal(delta) * quote.price if delta > 0 else Decimal("0")
        if required_cash > available_cash:
            rejections.append(
                _reject(
                    candidate.instrument_id,
                    candidate.source_signal_ids,
                    AllocationRejectionReason.INSUFFICIENT_CASH,
                    f"目标买入需要 {_decimal_text(required_cash)} CNY，"
                    f"可分配现金仅 {_decimal_text(available_cash)} CNY",
                )
            )
            continue
        if delta > 0:
            available_cash -= required_cash
        explanation = (
            f"目标权重 {_decimal_text(weight)}，按 {quote.lot_size} 股交易单位从 "
            f"{current_quantity} 股调整到 {target_quantity} 股"
        )
        target = PaperTargetPosition(
            candidate.instrument_id,
            candidate.source_signal_ids,
            current_quantity,
            target_quantity,
            weight,
            quote.price,
            quote.lot_size,
            explanation,
        )
        targets.append(target)
        side = PaperIntentSide.BUY if delta > 0 else PaperIntentSide.SELL
        intent_seed = {
            "account_id": account.account_id,
            "signals": list(candidate.source_signal_ids),
            "instrument_id": candidate.instrument_id,
            "decision_time": _time_text(decision_at),
            "side": side.value,
            "quantity": abs(delta),
            "target_quantity": target_quantity,
            "policy_digest": policy.policy_digest,
            "account_state_digest": account.state_digest,
        }
        intent_id = canonical_digest(intent_seed)
        intents.append(
            PaperOrderIntent(
                intent_id=intent_id,
                account_id=account.account_id,
                source_signal_ids=candidate.source_signal_ids,
                instrument_id=candidate.instrument_id,
                decision_time=decision_at,
                side=side,
                quantity=abs(delta),
                reference_price=quote.price,
                target_quantity=target_quantity,
                target_weight=weight,
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                policy_digest=policy.policy_digest,
                explanation=explanation,
            )
        )

    targets.sort(key=lambda item: item.instrument_id)
    intents.sort(key=lambda item: item.instrument_id)
    rejections.sort(key=lambda item: (item.instrument_id, item.reason.value))
    decision_seed = {
        "account_id": account.account_id,
        "decision_time": _time_text(decision_at),
        "account_state_digest": account.state_digest,
        "policy_digest": policy.policy_digest,
        "targets": [_target_payload(item) for item in targets],
        "intents": [item.intent_id for item in intents],
        "rejections": [_rejection_payload(item) for item in rejections],
    }
    decision_digest = canonical_digest(decision_seed)
    return PaperAllocationDecision(
        decision_id=decision_digest,
        account_id=account.account_id,
        decision_time=decision_at,
        account_state_digest=account.state_digest,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_digest=policy.policy_digest,
        targets=tuple(targets),
        intents=tuple(intents),
        rejections=tuple(rejections),
        decision_digest=decision_digest,
    )


def _account_rejection(
    account: PaperAccountState,
    decision_time: datetime,
) -> tuple[AllocationRejectionReason, str] | None:
    if account.status is not PaperAccountStatus.ACTIVE:
        return AllocationRejectionReason.ACCOUNT_NOT_ACTIVE, "模拟账户当前不是 ACTIVE 状态"
    if account.data_cutoff_time > decision_time:
        return AllocationRejectionReason.FUTURE_DATA, "账户状态在当前决策时点尚不可用"
    if account.positions and account.latest_valuation is None:
        return AllocationRejectionReason.MISSING_VALUATION, "持仓账户缺少当前可用估值"
    if account.latest_valuation and account.latest_valuation.available_time > decision_time:
        return AllocationRejectionReason.FUTURE_DATA, "账户估值在当前决策时点尚不可用"
    return None


def _account_nav(account: PaperAccountState) -> Decimal:
    if account.latest_valuation is not None:
        return account.latest_valuation.nav
    return account.cash


def _round_target(current: int, desired: int, lot_size: int) -> int:
    if desired >= current:
        return current + ((desired - current) // lot_size) * lot_size
    if desired == 0:
        return 0
    return current - ((current - desired) // lot_size) * lot_size


def _reject(
    instrument_id: str,
    source_signal_ids: tuple[str, ...],
    reason: AllocationRejectionReason,
    explanation: str,
) -> PaperAllocationRejection:
    return PaperAllocationRejection(instrument_id, source_signal_ids, reason, explanation)


def _target_payload(target: PaperTargetPosition) -> dict[str, object]:
    return {
        "instrument_id": target.instrument_id,
        "signals": list(target.source_signal_ids),
        "current_quantity": target.current_quantity,
        "target_quantity": target.target_quantity,
        "target_weight": _decimal_text(target.target_weight),
        "reference_price": _decimal_text(target.reference_price),
        "lot_size": target.rounding_lot_size,
    }


def _rejection_payload(rejection: PaperAllocationRejection) -> dict[str, object]:
    return {
        "instrument_id": rejection.instrument_id,
        "signals": list(rejection.source_signal_ids),
        "reason": rejection.reason.value,
        "explanation": rejection.explanation,
    }
