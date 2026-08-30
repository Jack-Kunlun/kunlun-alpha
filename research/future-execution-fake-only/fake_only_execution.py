"""Planned research-only execution safety semantics.

This module is intentionally an in-memory, fake-only, offline prototype.  It
has no service entry point and cannot submit anything to a broker.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from hashlib import sha256
from threading import Lock

__all__ = (
    "FakeOnlyEnvironment",
    "FakeOnlyIntent",
    "FakeOnlyLedger",
    "FakeOnlyReceipt",
    "simulate_fake_only",
)

_ALLOWED_SIDES = {"BUY", "SELL"}
_INSTRUMENT_EXCHANGES = {"SH", "SZ"}
_ACCOUNT_PREFIX = "fixture-account-"
_CLIENT_ORDER_ID_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
_MISSING = object()


@dataclass(frozen=True, slots=True)
class FakeOnlyIntent:
    """A sanitized order intent accepted by this prototype's boundary."""

    account_ref: str
    instrument: str
    side: str
    quantity: int
    reference_price: Decimal
    client_order_id: str
    broker_executable: bool = False
    execution_capability: str = "PAPER_ONLY"


@dataclass(frozen=True, slots=True)
class FakeOnlyEnvironment:
    """Fail-closed conditions required before a fake simulation."""

    risk_ready: bool
    simulated_transport_ready: bool
    reconciliation_matched: bool
    kill_switch_active: bool


@dataclass(frozen=True, slots=True)
class FakeOnlyReceipt:
    """Deterministic result of a fake-only simulation attempt."""

    status: str
    reason: str | None
    account_ref: str | None
    instrument: str | None
    side: str | None
    quantity: int | None
    reference_price: Decimal | None
    client_order_id: str | None
    broker_executable: bool
    execution_capability: str
    payload_digest: str
    summary: str

    @property
    def accepted(self) -> bool:
        """Return whether this receipt represents the first accepted attempt."""

        return self.status == "ACCEPTED"


@dataclass(frozen=True, slots=True)
class _LedgerRecord:
    payload_digest: str
    receipt: FakeOnlyReceipt


@dataclass(slots=True)
class FakeOnlyLedger:
    """An in-memory idempotency ledger keyed by account and client order ID."""

    _records: dict[tuple[str, str], _LedgerRecord] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _lock: Lock = field(
        default_factory=Lock,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def size(self) -> int:
        """Return the number of accepted first simulations."""

        with self._lock:
            return len(self._records)

    @property
    def count(self) -> int:
        """Alias for ``size`` for simple experiment assertions."""

        return self.size

    def __len__(self) -> int:
        return self.size

    def register(
        self,
        key: tuple[str, str],
        record: _LedgerRecord,
    ) -> _LedgerRecord | None:
        """Atomically store the first record and return any prior record."""

        with self._lock:
            existing = self._records.get(key)
            if existing is None:
                self._records[key] = record
            return existing


def simulate_fake_only(
    intent: object,
    environment: object,
    ledger: object,
) -> FakeOnlyReceipt:
    """Simulate one validated intent without external I/O.

    All failed checks return a rejection receipt and leave the ledger unchanged.
    Only the first accepted payload for an idempotency key is stored.
    """

    if type(intent) is not FakeOnlyIntent:
        return _rejection("intent_invalid")
    if type(environment) is not FakeOnlyEnvironment:
        return _rejection("environment_invalid", intent)
    if type(ledger) is not FakeOnlyLedger:
        return _rejection("ledger_invalid", intent)

    intent_reason = _validate_intent(intent)
    if intent_reason is not None:
        return _rejection(intent_reason, intent)

    environment_reason = _validate_environment(environment)
    if environment_reason is not None:
        return _rejection(environment_reason, intent)

    payload_digest = _payload_digest(intent)
    key = (intent.account_ref, intent.client_order_id)
    receipt = _intent_receipt("ACCEPTED", intent, payload_digest, None)
    existing = ledger.register(
        key,
        _LedgerRecord(payload_digest=payload_digest, receipt=receipt),
    )
    if existing is None:
        return receipt
    if existing.payload_digest == payload_digest:
        return _intent_receipt(
            "DUPLICATE",
            intent,
            payload_digest,
            "idempotent_duplicate",
        )
    return _intent_receipt(
        "IDEMPOTENCY_CONFLICT",
        intent,
        payload_digest,
        "idempotency_conflict",
    )


def _validate_intent(intent: FakeOnlyIntent) -> str | None:
    account_ref = getattr(intent, "account_ref", _MISSING)
    if not _is_fixture_account_ref(account_ref):
        return "account_ref_invalid"

    instrument = getattr(intent, "instrument", _MISSING)
    if not _is_canonical_instrument(instrument):
        return "instrument_invalid"

    side = getattr(intent, "side", _MISSING)
    if type(side) is not str or side not in _ALLOWED_SIDES:
        return "side_invalid"

    quantity = getattr(intent, "quantity", _MISSING)
    if not _is_serializable_positive_integer(quantity):
        return "quantity_invalid"

    reference_price = getattr(intent, "reference_price", _MISSING)
    if not _is_finite_positive_decimal(reference_price):
        return "reference_price_invalid"

    client_order_id = getattr(intent, "client_order_id", _MISSING)
    if not _is_client_order_id(client_order_id):
        return "client_order_id_invalid"

    broker_executable = getattr(intent, "broker_executable", _MISSING)
    execution_capability = getattr(intent, "execution_capability", _MISSING)
    if (
        type(broker_executable) is not bool
        or broker_executable is not False
        or type(execution_capability) is not str
        or execution_capability != "PAPER_ONLY"
    ):
        return "intent_policy_mismatch"

    return None


def _validate_environment(environment: FakeOnlyEnvironment) -> str | None:
    gates = (
        (
            "risk_ready",
            getattr(environment, "risk_ready", _MISSING),
        ),
        (
            "simulated_transport_ready",
            getattr(environment, "simulated_transport_ready", _MISSING),
        ),
        (
            "reconciliation_matched",
            getattr(environment, "reconciliation_matched", _MISSING),
        ),
    )
    for gate, value in gates:
        if type(value) is not bool:
            return "environment_invalid"
        if not value:
            return f"{gate}=false"

    kill_switch_active = getattr(
        environment,
        "kill_switch_active",
        _MISSING,
    )
    if type(kill_switch_active) is not bool:
        return "environment_invalid"
    if kill_switch_active:
        return "kill_switch_active=true"
    return None


def _is_fixture_account_ref(value: object) -> bool:
    if type(value) is not str or not value.startswith(_ACCOUNT_PREFIX):
        return False
    suffix = value[len(_ACCOUNT_PREFIX) :]
    if not 1 <= len(suffix) <= 32 or not value.isascii():
        return False
    return all(character.isalnum() or character == "-" for character in suffix)


def _is_canonical_instrument(value: object) -> bool:
    if type(value) is not str or not value.isascii() or len(value) != 9:
        return False
    return value[:6].isdigit() and value[6] == "." and value[7:] in _INSTRUMENT_EXCHANGES


def _is_client_order_id(value: object) -> bool:
    if type(value) is not str or not value.isascii():
        return False
    if not 1 <= len(value) <= 128:
        return False
    return all(character in _CLIENT_ORDER_ID_CHARACTERS for character in value)


def _is_finite_positive_decimal(value: object) -> bool:
    if type(value) is not Decimal or not value.is_finite():
        return False
    return value > Decimal("0")


def _is_serializable_positive_integer(value: object) -> bool:
    if type(value) is not int or value <= 0:
        return False
    try:
        str(value)
    except ValueError:
        return False
    return True


def _payload_text(intent: FakeOnlyIntent) -> str:
    return "|".join(
        (
            f"account_ref={intent.account_ref}",
            f"instrument={intent.instrument}",
            f"side={intent.side}",
            f"quantity={intent.quantity}",
            f"reference_price={_decimal_canonical_text(intent.reference_price)}",
            f"client_order_id={intent.client_order_id}",
            "broker_executable=False",
            "execution_capability=PAPER_ONLY",
        )
    )


def _payload_digest(intent: FakeOnlyIntent) -> str:
    return sha256(_payload_text(intent).encode("ascii")).hexdigest()


def _decimal_canonical_text(value: Decimal) -> str:
    sign, digits, exponent = value.as_tuple()
    if type(exponent) is not int:
        raise ValueError("finite Decimal values must have an integer exponent")
    canonical_digits = list(digits)
    while len(canonical_digits) > 1 and canonical_digits[-1] == 0:
        canonical_digits.pop()
        exponent += 1
    coefficient = "".join(str(digit) for digit in canonical_digits)
    return f"sign={sign};coefficient={coefficient};exponent={exponent}"


def _intent_receipt(
    status: str,
    intent: FakeOnlyIntent,
    payload_digest: str,
    reason: str | None,
) -> FakeOnlyReceipt:
    summary_parts = [
        f"status={status}",
        _payload_text(intent),
        f"payload_digest={payload_digest}",
    ]
    if reason is not None:
        summary_parts.insert(1, f"reason={reason}")
    return FakeOnlyReceipt(
        status=status,
        reason=reason,
        account_ref=intent.account_ref,
        instrument=intent.instrument,
        side=intent.side,
        quantity=intent.quantity,
        reference_price=intent.reference_price,
        client_order_id=intent.client_order_id,
        broker_executable=False,
        execution_capability="PAPER_ONLY",
        payload_digest=payload_digest,
        summary="|".join(summary_parts),
    )


def _rejection(
    reason: str,
    intent: object | None = None,
) -> FakeOnlyReceipt:
    account_ref: str | None = None
    instrument: str | None = None
    side: str | None = None
    quantity: int | None = None
    reference_price: Decimal | None = None
    client_order_id: str | None = None
    if type(intent) is FakeOnlyIntent:
        candidate_account_ref = getattr(intent, "account_ref", _MISSING)
        candidate_instrument = getattr(intent, "instrument", _MISSING)
        candidate_side = getattr(intent, "side", _MISSING)
        candidate_quantity = getattr(intent, "quantity", _MISSING)
        candidate_price = getattr(intent, "reference_price", _MISSING)
        candidate_client_order_id = getattr(intent, "client_order_id", _MISSING)
        if type(candidate_account_ref) is str and _is_fixture_account_ref(candidate_account_ref):
            account_ref = candidate_account_ref
        if type(candidate_instrument) is str and _is_canonical_instrument(candidate_instrument):
            instrument = candidate_instrument
        if type(candidate_side) is str and candidate_side in _ALLOWED_SIDES:
            side = candidate_side
        if type(candidate_quantity) is int and _is_serializable_positive_integer(
            candidate_quantity
        ):
            quantity = candidate_quantity
        if type(candidate_price) is Decimal and _is_finite_positive_decimal(candidate_price):
            reference_price = candidate_price
        if type(candidate_client_order_id) is str and _is_client_order_id(
            candidate_client_order_id
        ):
            client_order_id = candidate_client_order_id

    payload_digest = sha256(f"REJECTED|{reason}".encode("ascii")).hexdigest()
    summary = "|".join(
        (
            "status=REJECTED",
            f"reason={reason}",
            "broker_executable=False",
            "execution_capability=PAPER_ONLY",
            f"payload_digest={payload_digest}",
        )
    )
    return FakeOnlyReceipt(
        status="REJECTED",
        reason=reason,
        account_ref=account_ref,
        instrument=instrument,
        side=side,
        quantity=quantity,
        reference_price=reference_price,
        client_order_id=client_order_id,
        broker_executable=False,
        execution_capability="PAPER_ONLY",
        payload_digest=payload_digest,
        summary=summary,
    )
