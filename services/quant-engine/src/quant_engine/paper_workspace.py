"""Simulation-only paper workspace backed by the paper-core event models."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import cast
from zoneinfo import ZoneInfo

from ashare_contracts import (
    PaperTerminalCreateAccountCommand,
    PaperTerminalSimulationCommand,
    PaperTerminalWorkspace,
)
from paper_core import (
    ZERO_DIGEST,
    ApplyPaperFill,
    CreatePaperOrder,
    InMemoryPaperAccountEventStore,
    OpenPaperAccount,
    PaperAccountState,
    PaperAccountTape,
    PaperAllocationDecision,
    PaperAllocationPolicy,
    PaperBookPosition,
    PaperEventMetadata,
    PaperExecutionMetadata,
    PaperExecutionProjection,
    PaperExecutionTape,
    PaperIntentSide,
    PaperMarketQuote,
    PaperOrderIntent,
    PaperReconciliationResult,
    PaperRiskDecision,
    PaperRiskEnvironment,
    PaperRiskPolicy,
    PaperSettlementBook,
    PaperValuationMark,
    PositionTransferReason,
    ReconciliationHealth,
    RecordPaperValuation,
    SubmitPaperOrder,
    TransferPaperPosition,
    ValuationMarkSource,
    allocate_signals,
    append_execution_event,
    create_risk_check_event,
    evaluate_pretrade_risk,
    project_execution_book,
    reconcile_paper_books,
    replay_account,
    replay_execution,
)
from quant_core.strategy import Signal, SignalDirection

from .paper_journal import PaperCommandJournal, PaperCommandJournalError, PaperJournalEntry
from .paper_preview import preview_allocation

SHANGHAI = ZoneInfo("Asia/Shanghai")
VOLATILE_LIMITATIONS = (
    "未配置持久化目录；服务重启会清空当前模拟工作区。",
    "仅执行模拟撮合，不连接真实账户或券商，也不会生成真实订单。",
)
DURABLE_LIMITATIONS = (
    "本地单实例模拟命令使用哈希日志恢复；日志损坏时服务会拒绝加载。",
    "仅执行模拟撮合，不连接真实账户或券商，也不会生成真实订单。",
)


class PaperWorkspaceError(ValueError):
    """Bounded command or lifecycle failure."""


class PaperWorkspaceConflictError(PaperWorkspaceError):
    """Idempotency or single-workspace conflict."""


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _money(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


class PaperWorkspace:
    """One lock-protected, simulation-only paper account and execution tape."""

    def __init__(
        self,
        clock: Callable[[], datetime] | None = None,
        journal_path: Path | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(tz=SHANGHAI))
        self._lock = RLock()
        self._store = InMemoryPaperAccountEventStore()
        self._account_id: str | None = None
        self._execution: PaperExecutionTape | None = None
        self._opening_book: PaperSettlementBook | None = None
        self._latest_allocation: PaperAllocationDecision | None = None
        self._latest_risk: PaperRiskDecision | None = None
        self._latest_reconciliation: PaperReconciliationResult | None = None
        self._marks: dict[str, tuple[Decimal, datetime, str]] = {}
        self._requests: dict[str, str] = {}
        self._last_client_request_id: str | None = None
        self._journal: PaperCommandJournal | None = None
        if journal_path is not None:
            try:
                self._journal = PaperCommandJournal(journal_path)
                for entry in self._journal.entries:
                    self._replay(entry)
            except (PaperCommandJournalError, PaperWorkspaceError, ValueError) as error:
                raise PaperWorkspaceError(f"模拟工作区持久化日志损坏：{error}") from error

    def create_account(self, raw: Mapping[str, object]) -> dict[str, object]:
        command = PaperTerminalCreateAccountCommand.model_validate(raw)
        fingerprint = _digest(command.model_dump_json(by_alias=True))
        with self._lock:
            if self._accept_retry(command.client_request_id, fingerprint):
                return self.snapshot()
            if self._account_id is not None:
                raise PaperWorkspaceConflictError("本地模拟工作区已存在账户")
            now = self._now()
            self._append_command(
                "CREATE_ACCOUNT",
                now,
                command.model_dump(by_alias=True, mode="json"),
            )
            self._apply_create_account(command, fingerprint, now)
            return self.snapshot()

    def preview(self, raw: Mapping[str, object]) -> dict[str, object]:
        command = PaperTerminalSimulationCommand.model_validate(raw, strict=True)
        with self._lock:
            tape = self._account_tape()
            if self.snapshot()["status"] != "READY":
                raise PaperWorkspaceError("账本存在异常，暂不提供仓位试算")
            try:
                return preview_allocation(self._state(tape), command, self._now())
            except ValueError as error:
                raise PaperWorkspaceError(str(error)) from error

    def simulate(self, raw: Mapping[str, object]) -> dict[str, object]:
        command = PaperTerminalSimulationCommand.model_validate(raw)
        fingerprint = _digest(command.model_dump_json(by_alias=True))
        with self._lock:
            if self._accept_retry(command.client_request_id, fingerprint):
                return self.snapshot()
            tape = self._account_tape()
            now = self._now()
            self._append_command("SIMULATE", now, command.model_dump(by_alias=True, mode="json"))
            self._apply_simulation(command, fingerprint, now, tape)
            return self.snapshot()

    def _apply_create_account(
        self,
        command: PaperTerminalCreateAccountCommand,
        fingerprint: str,
        now: datetime,
    ) -> None:
        account_id = _digest(f"paper-account:{command.client_request_id}:{fingerprint}")
        opened = OpenPaperAccount(
            metadata=PaperEventMetadata(
                account_id=account_id,
                event_id=_digest(f"account-open:{account_id}"),
                sequence=0,
                event_time=now,
                available_time=now,
                previous_event_digest=ZERO_DIGEST,
                source_id="paper-terminal",
                source_version="1.0.0",
            ),
            owner_ref="local-paper-operator",
            name=command.name,
            initial_capital=Decimal(command.initial_capital),
        )
        tape = self._store.append(opened, expected_tape_digest=ZERO_DIGEST)
        tape = self._store.append(
            RecordPaperValuation(metadata=self._account_metadata(tape, now), marks=()),
            expected_tape_digest=tape.tape_digest,
        )
        state = self._state(tape)
        self._account_id = account_id
        self._execution = PaperExecutionTape(account_id)
        self._opening_book = PaperSettlementBook(account_id, state.cash, (), now)
        self._record_request(command.client_request_id, fingerprint)

    def _apply_simulation(
        self,
        command: PaperTerminalSimulationCommand,
        fingerprint: str,
        now: datetime,
        tape: PaperAccountTape,
    ) -> None:
        account = self._state(tape)
        execution_tape = self._execution_tape()
        evidence_id = _digest(f"quote:{command.client_request_id}:{command.instrument_id}")
        signal = Signal(
            signal_id=_digest(f"signal:{command.client_request_id}"),
            schema_version="signal-v1",
            strategy_id="paper-terminal-manual-signal",
            strategy_version="1.0.0",
            algorithm_version="1.0.0",
            entity_id=command.instrument_id,
            decision_time=now,
            data_cutoff_time=now,
            direction=SignalDirection.LONG,
            score=Decimal(command.score),
            confidence=Decimal(command.confidence),
            horizon_sessions=5,
            rationale="用户发起的本地模拟信号演练",
            input_snapshot_id=_digest(f"snapshot:{command.client_request_id}"),
            input_snapshot_version="1.0.0",
            evidence_ids=(evidence_id,),
        )
        quote = PaperMarketQuote(
            instrument_id=command.instrument_id,
            price=Decimal(command.price),
            observed_time=now,
            available_time=now,
            lot_size=command.lot_size,
            source_version="manual-paper-quote-v1",
            evidence_id=evidence_id,
        )
        allocation = allocate_signals(
            (signal,),
            account=account,
            quotes=(quote,),
            decision_time=now,
            policy=PaperAllocationPolicy(
                "paper-terminal-allocation",
                "1.0.0",
                Decimal("0.30"),
                Decimal("0.95"),
                Decimal("0.05"),
                Decimal("0.50"),
            ),
        )
        self._latest_allocation = allocation
        if not allocation.intents:
            self._record_request(command.client_request_id, fingerprint)
            return

        intent = allocation.intents[0]
        execution_tape = append_execution_event(
            execution_tape,
            CreatePaperOrder(
                self._execution_metadata(execution_tape, now),
                command.client_request_id,
                intent,
            ),
        )
        projection = replay_execution(execution_tape)
        risk = evaluate_pretrade_risk(
            intent,
            account=account,
            execution=projection,
            decision_time=now,
            policy=PaperRiskPolicy(
                "paper-terminal-risk",
                "1.0.0",
                Decimal("100000000"),
                Decimal("0.35"),
                Decimal("1000000000"),
                20,
                Decimal("0"),
            ),
            environment=PaperRiskEnvironment(True, True, ReconciliationHealth.MATCHED),
        )
        self._latest_risk = risk
        order = projection.orders[-1]
        execution_tape = append_execution_event(
            execution_tape,
            create_risk_check_event(
                self._execution_metadata(execution_tape, now),
                order=order,
                execution=projection,
                decision=risk,
            ),
        )
        if risk.allowed:
            order_id = order.order_id
            execution_tape = append_execution_event(
                execution_tape,
                SubmitPaperOrder(self._execution_metadata(execution_tape, now), order_id),
            )
            notional = intent.reference_price * intent.quantity
            fee = max(Decimal("1"), (notional * Decimal("0.0003")).quantize(Decimal("0.01")))
            execution_tape = append_execution_event(
                execution_tape,
                ApplyPaperFill(
                    self._execution_metadata(execution_tape, now),
                    order_id,
                    _digest(f"fill:{command.client_request_id}:{order_id}"),
                    intent.quantity,
                    intent.reference_price,
                    fee,
                    evidence_id,
                ),
            )
            tape = self._settle_buy(tape, intent, fee, now)
            self._marks[intent.instrument_id] = (intent.reference_price, now, evidence_id)
            tape = self._record_valuation(tape, now)

        self._execution = execution_tape
        self._latest_reconciliation = self._reconcile(tape, execution_tape, now)
        self._record_request(command.client_request_id, fingerprint)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            now = self._now()
            if self._account_id is None:
                return self._validated(
                    {
                        "schemaVersion": "paper-terminal-workspace-v1",
                        "status": "EMPTY",
                        "dataMeaning": "SIMULATION_ONLY_NO_BROKER_PATH",
                        "executionCapability": "PAPER_ONLY",
                        "persistenceMode": self._persistence_mode,
                        "generatedAt": now.isoformat(),
                        "limitations": list(self._limitations),
                        "account": None,
                        "latestAllocation": None,
                        "orders": [],
                        "latestRisk": None,
                        "reconciliation": None,
                        "audit": self._audit(None, None),
                    }
                )
            tape = self._account_tape()
            state = self._state(tape)
            execution = replay_execution(self._execution_tape())
            degraded = bool(execution.alerts)
            if self._latest_risk is not None and not self._latest_risk.allowed:
                degraded = True
            if self._latest_reconciliation is not None:
                degraded = degraded or self._latest_reconciliation.status.value == "DRIFTED"
            return self._validated(
                {
                    "schemaVersion": "paper-terminal-workspace-v1",
                    "status": "DEGRADED" if degraded else "READY",
                    "dataMeaning": "SIMULATION_ONLY_NO_BROKER_PATH",
                    "executionCapability": "PAPER_ONLY",
                    "persistenceMode": self._persistence_mode,
                    "generatedAt": now.isoformat(),
                    "limitations": list(self._limitations),
                    "account": self._account_payload(state),
                    "latestAllocation": self._allocation_payload(),
                    "orders": [
                        {
                            "orderId": order.order_id,
                            "instrumentId": order.intent.instrument_id,
                            "side": order.intent.side.value,
                            "status": order.status.value,
                            "quantity": order.intent.quantity,
                            "filledQuantity": order.filled_quantity,
                            "averageFillPrice": (
                                None
                                if order.average_fill_price is None
                                else _money(order.average_fill_price)
                            ),
                            "totalFees": _money(order.total_fees),
                            "explanation": order.intent.explanation,
                            "updatedAt": order.updated_at.isoformat(),
                        }
                        for order in execution.orders
                    ],
                    "latestRisk": self._risk_payload(),
                    "reconciliation": self._reconciliation_payload(),
                    "audit": self._audit(tape, execution),
                }
            )

    def _settle_buy(
        self,
        tape: PaperAccountTape,
        intent: PaperOrderIntent,
        fee: Decimal,
        now: datetime,
    ) -> PaperAccountTape:
        if intent.side is not PaperIntentSide.BUY:
            raise PaperWorkspaceError("当前终端只支持模拟买入信号")
        notional = intent.reference_price * intent.quantity
        event = TransferPaperPosition(
            metadata=self._account_metadata(tape, now),
            instrument_id=intent.instrument_id,
            quantity_delta=intent.quantity,
            available_quantity_delta=0,
            cash_delta=-(notional + fee),
            position_cost_delta=notional + fee,
            reason=PositionTransferReason.RECONCILIATION,
            explanation="模拟成交后按执行事件对账入账",
        )
        return self._store.append(event, expected_tape_digest=tape.tape_digest)

    def _record_valuation(self, tape: PaperAccountTape, now: datetime) -> PaperAccountTape:
        state = self._state(tape)
        marks = tuple(
            PaperValuationMark(
                position.instrument_id,
                self._marks[position.instrument_id][0],
                self._marks[position.instrument_id][1],
                self._marks[position.instrument_id][1],
                ValuationMarkSource.EXECUTABLE_QUOTE,
                "manual-paper-quote-v1",
                self._marks[position.instrument_id][2],
            )
            for position in state.positions
        )
        return self._store.append(
            RecordPaperValuation(self._account_metadata(tape, now), marks),
            expected_tape_digest=tape.tape_digest,
        )

    def _reconcile(
        self,
        tape: PaperAccountTape,
        execution_tape: PaperExecutionTape,
        now: datetime,
    ) -> PaperReconciliationResult:
        if self._opening_book is None:
            raise PaperWorkspaceError("模拟账户缺少期初账簿")
        expected = project_execution_book(
            self._opening_book,
            replay_execution(execution_tape),
            as_of=now,
        )
        state = self._state(tape)
        observed = PaperSettlementBook(
            state.account_id,
            state.cash,
            tuple(
                PaperBookPosition(item.instrument_id, item.quantity, item.cost_amount)
                for item in state.positions
            ),
            now,
        )
        return reconcile_paper_books(expected, observed)

    def _account_payload(self, state: PaperAccountState) -> dict[str, object]:
        nav = state.latest_valuation.nav if state.latest_valuation is not None else state.cash
        return {
            "accountId": state.account_id,
            "name": state.name,
            "status": state.status.value,
            "baseCurrency": "CNY",
            "initialCapital": _money(state.initial_capital),
            "cash": _money(state.cash),
            "nav": _money(nav),
            "dataCutoffTime": state.data_cutoff_time.isoformat(),
            "eventCount": state.event_count,
            "eventChainDigest": state.event_chain_digest,
            "positions": [
                {
                    "instrumentId": item.instrument_id,
                    "quantity": item.quantity,
                    "availableQuantity": item.available_quantity,
                    "costAmount": _money(item.cost_amount),
                    "marketValue": _money(
                        self._marks.get(item.instrument_id, (Decimal("0"), self._now(), ""))[0]
                        * item.quantity
                    ),
                }
                for item in state.positions
            ],
        }

    def _allocation_payload(self) -> dict[str, object] | None:
        value = self._latest_allocation
        if value is None:
            return None
        return {
            "decisionId": value.decision_id,
            "policyId": value.policy_id,
            "policyVersion": value.policy_version,
            "intentCount": len(value.intents),
            "rejectionCount": len(value.rejections),
            "rejections": [
                {
                    "instrumentId": item.instrument_id,
                    "reason": item.reason.value,
                    "explanation": item.explanation,
                }
                for item in value.rejections
            ],
        }

    def _risk_payload(self) -> dict[str, object] | None:
        value = self._latest_risk
        if value is None:
            return None
        return {
            "decisionId": value.decision_id,
            "allowed": value.allowed,
            "policyId": value.policy_id,
            "policyVersion": value.policy_version,
            "checks": [
                {
                    "code": item.code.value,
                    "status": item.status.value,
                    "actual": item.actual,
                    "limit": item.limit,
                    "explanation": item.explanation,
                }
                for item in value.checks
            ],
        }

    def _reconciliation_payload(self) -> dict[str, object] | None:
        value = self._latest_reconciliation
        if value is None:
            return None
        return {
            "reconciliationId": value.reconciliation_id,
            "status": value.status.value,
            "asOf": value.as_of.isoformat(),
            "duplicateFillCount": value.duplicate_fill_count,
            "diffs": [
                {
                    "kind": item.kind.value,
                    "instrumentId": item.instrument_id,
                    "expected": item.expected,
                    "observed": item.observed,
                    "difference": item.difference,
                }
                for item in value.diffs
            ],
        }

    def _audit(
        self,
        tape: PaperAccountTape | None,
        execution: PaperExecutionProjection | None,
    ) -> dict[str, object]:
        execution_tape = self._execution
        return {
            "accountEventCount": 0 if tape is None else len(tape.events),
            "executionEventCount": 0 if execution_tape is None else len(execution_tape.events),
            "orderAuditCount": 0 if execution is None else len(execution.audits),
            "alertCount": 0 if execution is None else len(execution.alerts),
            "accountDigest": None if tape is None else tape.tape_digest,
            "executionDigest": None if execution_tape is None else execution_tape.tape_digest,
            "lastClientRequestId": self._last_client_request_id,
        }

    def _account_metadata(self, tape: PaperAccountTape, now: datetime) -> PaperEventMetadata:
        return PaperEventMetadata(
            account_id=tape.account_id,
            event_id=_digest(
                f"account-event:{tape.account_id}:{len(tape.events)}:{now.isoformat()}"
            ),
            sequence=len(tape.events),
            event_time=now,
            available_time=now,
            previous_event_digest=tape.last_event_digest,
            source_id="paper-terminal",
            source_version="1.0.0",
        )

    def _execution_metadata(
        self,
        tape: PaperExecutionTape,
        now: datetime,
    ) -> PaperExecutionMetadata:
        return PaperExecutionMetadata(
            account_id=tape.account_id,
            event_id=_digest(
                f"execution-event:{tape.account_id}:{len(tape.events)}:{now.isoformat()}"
            ),
            sequence=len(tape.events),
            event_time=now,
            available_time=now,
            previous_event_digest=tape.last_event_digest,
            source_id="paper-terminal",
            source_version="1.0.0",
        )

    def _account_tape(self) -> PaperAccountTape:
        if self._account_id is None:
            raise PaperWorkspaceError("请先创建模拟账户")
        tape = self._store.load(self._account_id)
        if tape is None:
            raise PaperWorkspaceError("模拟账户事件链不可用")
        return tape

    def _execution_tape(self) -> PaperExecutionTape:
        if self._execution is None:
            raise PaperWorkspaceError("模拟执行事件链不可用")
        return self._execution

    @staticmethod
    def _state(tape: PaperAccountTape) -> PaperAccountState:
        state = replay_account(tape)
        if state is None:
            raise PaperWorkspaceError("模拟账户尚未建立")
        return state

    def _accept_retry(self, client_request_id: str, fingerprint: str) -> bool:
        previous = self._requests.get(client_request_id)
        if previous is None:
            return False
        if previous != fingerprint:
            raise PaperWorkspaceConflictError("clientRequestId 已用于不同命令")
        self._last_client_request_id = client_request_id
        return True

    def _record_request(self, client_request_id: str, fingerprint: str) -> None:
        self._requests[client_request_id] = fingerprint
        self._last_client_request_id = client_request_id

    @property
    def _persistence_mode(self) -> str:
        return "VOLATILE_IN_MEMORY" if self._journal is None else "DURABLE_COMMAND_JOURNAL"

    @property
    def _limitations(self) -> tuple[str, ...]:
        return VOLATILE_LIMITATIONS if self._journal is None else DURABLE_LIMITATIONS

    def _append_command(
        self,
        kind: str,
        now: datetime,
        command: Mapping[str, object],
    ) -> None:
        if self._journal is None:
            return
        try:
            self._journal.append(kind=kind, occurred_at=now, command=command)
        except PaperCommandJournalError as error:
            raise PaperWorkspaceError(f"无法持久化模拟命令：{error}") from error

    def _replay(self, entry: PaperJournalEntry) -> None:
        if entry.kind == "CREATE_ACCOUNT":
            command = PaperTerminalCreateAccountCommand.model_validate(entry.command)
            fingerprint = _digest(command.model_dump_json(by_alias=True))
            if self._accept_retry(command.client_request_id, fingerprint):
                raise PaperCommandJournalError("journal contains a duplicate command")
            if self._account_id is not None:
                raise PaperCommandJournalError("journal contains more than one paper account")
            self._apply_create_account(command, fingerprint, entry.occurred_at)
            return
        if entry.kind == "SIMULATE":
            command = PaperTerminalSimulationCommand.model_validate(entry.command)
            fingerprint = _digest(command.model_dump_json(by_alias=True))
            if self._accept_retry(command.client_request_id, fingerprint):
                raise PaperCommandJournalError("journal contains a duplicate command")
            tape = self._account_tape()
            self._apply_simulation(command, fingerprint, entry.occurred_at, tape)
            return
        raise PaperCommandJournalError("journal command kind is unsupported")

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise PaperWorkspaceError("clock must return a timezone-aware datetime")
        return value

    @staticmethod
    def _validated(payload: Mapping[str, object]) -> dict[str, object]:
        model = PaperTerminalWorkspace.model_validate(payload)
        return cast(dict[str, object], model.model_dump(by_alias=True, mode="json"))
