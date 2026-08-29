"""Tests for the future fake-only execution safety spike."""

from __future__ import annotations

import ast
import builtins
import importlib
import threading
import unittest
from decimal import Decimal, localcontext
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from fake_only_execution import FakeOnlyReceipt

_MODULE_PATH = Path(__file__).with_name("fake_only_execution.py")
_ALLOWED_IMPORTS = {"dataclasses", "decimal", "hashlib", "threading"}
_FORBIDDEN_NAMES = {
    "__builtins__",
    "__import__",
    "eval",
    "exec",
    "globals",
    "locals",
    "open",
    "vars",
}
_FORBIDDEN_ATTRIBUTES = {
    "Popen",
    "call",
    "check_call",
    "check_output",
    "connect",
    "create_connection",
    "environ",
    "__builtins__",
    "__import__",
    "eval",
    "exec",
    "getattr",
    "globals",
    "getenv",
    "locals",
    "open",
    "popen",
    "read_text",
    "recv",
    "run",
    "send",
    "socket",
    "system",
    "unlink",
    "urlopen",
    "vars",
    "write_text",
}
_ALLOWED_GETATTR_FIELDS = {
    "intent": {
        "account_ref",
        "instrument",
        "side",
        "quantity",
        "reference_price",
        "client_order_id",
        "broker_executable",
        "execution_capability",
    },
    "environment": {
        "risk_ready",
        "simulated_transport_ready",
        "reconciliation_matched",
        "kill_switch_active",
    },
}


def _assert_source_safe(
    source: str,
    filename: str = "<source>",
) -> ast.Module:
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in _ALLOWED_IMPORTS:
                    raise AssertionError(f"disallowed import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module not in _ALLOWED_IMPORTS:
                raise AssertionError(f"disallowed import: {node.module}")
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            raise AssertionError(f"disallowed name: {node.id}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _FORBIDDEN_NAMES:
                raise AssertionError(f"disallowed call: {node.func.id}")
            if node.func.id == "getattr":
                _assert_allowed_getattr(node)
        elif isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_ATTRIBUTES:
            raise AssertionError(f"disallowed attribute: {node.attr}")
    return tree


def _assert_allowed_getattr(node: ast.Call) -> None:
    if len(node.args) != 3 or node.keywords:
        raise AssertionError("getattr must use the validated three-argument form")
    target, field, default = node.args
    if not isinstance(target, ast.Name):
        raise AssertionError("getattr target is not an allowed DTO name")
    allowed_fields = _ALLOWED_GETATTR_FIELDS.get(target.id)
    if allowed_fields is None:
        raise AssertionError("getattr target is not an allowed DTO name")
    if (
        not isinstance(field, ast.Constant)
        or type(field.value) is not str
        or field.value not in allowed_fields
    ):
        raise AssertionError("getattr field is not an allowed DTO field")
    if not isinstance(default, ast.Name) or default.id != "_MISSING":
        raise AssertionError("getattr default must be _MISSING")


def _scan_module_source_before_import() -> tuple[str, ast.Module]:
    source = _MODULE_PATH.read_text(encoding="utf-8")
    tree = _assert_source_safe(source, str(_MODULE_PATH))
    return source, tree


_MODULE_SOURCE, _MODULE_TREE = _scan_module_source_before_import()
fake_only_execution = importlib.import_module("fake_only_execution")
FakeOnlyEnvironment = fake_only_execution.FakeOnlyEnvironment
FakeOnlyIntent = fake_only_execution.FakeOnlyIntent
FakeOnlyLedger = fake_only_execution.FakeOnlyLedger
simulate_fake_only = fake_only_execution.simulate_fake_only


class FakeOnlyExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intent = FakeOnlyIntent(
            account_ref="fixture-account-001",
            instrument="518880.SH",
            side="BUY",
            quantity=100,
            reference_price=Decimal("1.2345"),
            client_order_id="fixture-order-001",
        )
        self.environment = FakeOnlyEnvironment(
            risk_ready=True,
            simulated_transport_ready=True,
            reconciliation_matched=True,
            kill_switch_active=False,
        )
        self.ledger = FakeOnlyLedger()

    def test_first_simulation_is_accepted(self) -> None:
        receipt = simulate_fake_only(self.intent, self.environment, self.ledger)

        self.assertEqual(receipt.status, "ACCEPTED")
        self.assertFalse(receipt.broker_executable)
        self.assertEqual(receipt.execution_capability, "PAPER_ONLY")
        self.assertEqual(self.ledger.size, 1)

    def test_each_environment_gate_fails_closed(self) -> None:
        for gate in (
            "risk_ready",
            "simulated_transport_ready",
            "reconciliation_matched",
        ):
            with self.subTest(gate=gate):
                values = {
                    "risk_ready": True,
                    "simulated_transport_ready": True,
                    "reconciliation_matched": True,
                    "kill_switch_active": False,
                }
                values[gate] = False
                ledger = FakeOnlyLedger()
                receipt = simulate_fake_only(
                    self.intent,
                    FakeOnlyEnvironment(**values),
                    ledger,
                )

                self.assertEqual(receipt.status, "REJECTED")
                self.assertIn(gate, receipt.reason or "")
                self.assertEqual(ledger.size, 0)

    def test_environment_requires_exact_boolean_gate_values(self) -> None:
        ledger = FakeOnlyLedger()
        environment = FakeOnlyEnvironment(
            risk_ready=1,
            simulated_transport_ready=True,
            reconciliation_matched=True,
            kill_switch_active=False,
        )

        receipt = simulate_fake_only(self.intent, environment, ledger)

        self.assertEqual(receipt.status, "REJECTED")
        self.assertIn("environment", receipt.reason or "")
        self.assertEqual(ledger.size, 0)

    def test_active_kill_switch_fails_closed(self) -> None:
        environment = FakeOnlyEnvironment(
            risk_ready=True,
            simulated_transport_ready=True,
            reconciliation_matched=True,
            kill_switch_active=True,
        )

        receipt = simulate_fake_only(self.intent, environment, self.ledger)

        self.assertEqual(receipt.status, "REJECTED")
        self.assertEqual(receipt.reason, "kill_switch_active=true")
        self.assertEqual(self.ledger.size, 0)

    def test_policy_is_fixed_to_paper_only(self) -> None:
        for field, value in (
            ("broker_executable", True),
            ("execution_capability", "SIMULATED_BROKER"),
        ):
            with self.subTest(field=field):
                intent = FakeOnlyIntent(
                    **{
                        "account_ref": self.intent.account_ref,
                        "instrument": self.intent.instrument,
                        "side": self.intent.side,
                        "quantity": self.intent.quantity,
                        "reference_price": self.intent.reference_price,
                        "client_order_id": self.intent.client_order_id,
                        field: value,
                    }
                )
                ledger = FakeOnlyLedger()

                receipt = simulate_fake_only(intent, self.environment, ledger)

                self.assertEqual(receipt.status, "REJECTED")
                self.assertEqual(receipt.reason, "intent_policy_mismatch")
                self.assertEqual(ledger.size, 0)

    def test_module_policy_attributes_cannot_change_the_safety_boundary(self) -> None:
        missing = object()
        module_values = vars(fake_only_execution)
        previous_paper_only = module_values.get("PAPER_ONLY", missing)
        previous_broker_executable = module_values.get("BROKER_EXECUTABLE", missing)
        try:
            module_values["PAPER_ONLY"] = "LIVE"
            module_values["BROKER_EXECUTABLE"] = True

            valid_receipt = simulate_fake_only(
                FakeOnlyIntent(
                    account_ref=self.intent.account_ref,
                    instrument=self.intent.instrument,
                    side=self.intent.side,
                    quantity=self.intent.quantity,
                    reference_price=self.intent.reference_price,
                    client_order_id="fixture-order-policy-valid",
                ),
                self.environment,
                FakeOnlyLedger(),
            )
            non_paper_receipt = simulate_fake_only(
                FakeOnlyIntent(
                    account_ref=self.intent.account_ref,
                    instrument=self.intent.instrument,
                    side=self.intent.side,
                    quantity=self.intent.quantity,
                    reference_price=self.intent.reference_price,
                    client_order_id="fixture-order-policy-invalid",
                    broker_executable=True,
                    execution_capability="LIVE",
                ),
                self.environment,
                FakeOnlyLedger(),
            )
        finally:
            if previous_paper_only is missing:
                module_values.pop("PAPER_ONLY", None)
            else:
                module_values["PAPER_ONLY"] = previous_paper_only
            if previous_broker_executable is missing:
                module_values.pop("BROKER_EXECUTABLE", None)
            else:
                module_values["BROKER_EXECUTABLE"] = previous_broker_executable

        self.assertEqual(valid_receipt.status, "ACCEPTED")
        self.assertFalse(valid_receipt.broker_executable)
        self.assertEqual(valid_receipt.execution_capability, "PAPER_ONLY")
        self.assertEqual(non_paper_receipt.status, "REJECTED")

    def test_same_key_concurrent_simulations_are_atomic(self) -> None:
        ledger = FakeOnlyLedger()
        worker_count = 16
        start = threading.Barrier(worker_count)
        receipts: list[FakeOnlyReceipt] = []
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                start.wait(timeout=2.0)
                receipts.append(simulate_fake_only(self.intent, self.environment, ledger))
            except BaseException as error:
                errors.append(error)

        threads = [threading.Thread(target=worker) for _ in range(worker_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3.0)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(
            sorted(receipt.status for receipt in receipts),
            ["ACCEPTED", *("DUPLICATE" for _ in range(worker_count - 1))],
        )
        self.assertEqual(ledger.size, 1)

    def test_decimal_digest_ignores_scale_and_context_precision(self) -> None:
        ledger = FakeOnlyLedger()
        first_intent = FakeOnlyIntent(
            account_ref=self.intent.account_ref,
            instrument=self.intent.instrument,
            side=self.intent.side,
            quantity=self.intent.quantity,
            reference_price=Decimal("1.0"),
            client_order_id=self.intent.client_order_id,
        )
        with localcontext() as context:
            context.prec = 2
            first = simulate_fake_only(
                first_intent,
                self.environment,
                ledger,
            )
            duplicates: list[FakeOnlyReceipt] = []
            for reference_price in (Decimal("1.00"), Decimal("1.00E+0")):
                equivalent = FakeOnlyIntent(
                    account_ref=self.intent.account_ref,
                    instrument=self.intent.instrument,
                    side=self.intent.side,
                    quantity=self.intent.quantity,
                    reference_price=reference_price,
                    client_order_id=self.intent.client_order_id,
                )
                context.prec = 50
                duplicates.append(
                    simulate_fake_only(
                        equivalent,
                        self.environment,
                        ledger,
                    )
                )

        self.assertEqual(first.status, "ACCEPTED")
        self.assertEqual(
            [duplicate.status for duplicate in duplicates],
            ["DUPLICATE", "DUPLICATE"],
        )
        self.assertTrue(
            all(duplicate.payload_digest == first.payload_digest for duplicate in duplicates)
        )
        self.assertEqual(ledger.size, 1)

    def test_string_reference_price_is_rejected(self) -> None:
        intent = FakeOnlyIntent(
            account_ref=self.intent.account_ref,
            instrument=self.intent.instrument,
            side=self.intent.side,
            quantity=self.intent.quantity,
            reference_price="1.2345",
            client_order_id="fixture-order-string-price",
        )

        receipt = simulate_fake_only(intent, self.environment, FakeOnlyLedger())

        self.assertEqual(receipt.status, "REJECTED")
        self.assertEqual(receipt.reason, "reference_price_invalid")

    def test_duplicate_is_idempotent_without_a_new_ledger_entry(self) -> None:
        first = simulate_fake_only(self.intent, self.environment, self.ledger)
        duplicate = simulate_fake_only(self.intent, self.environment, self.ledger)

        self.assertEqual(first.status, "ACCEPTED")
        self.assertEqual(duplicate.status, "DUPLICATE")
        self.assertEqual(duplicate.payload_digest, first.payload_digest)
        self.assertEqual(self.ledger.size, 1)

    def test_conflicting_payload_does_not_overwrite_the_original_entry(self) -> None:
        first = simulate_fake_only(self.intent, self.environment, self.ledger)
        conflicting_intent = FakeOnlyIntent(
            account_ref=self.intent.account_ref,
            instrument=self.intent.instrument,
            side=self.intent.side,
            quantity=200,
            reference_price=self.intent.reference_price,
            client_order_id=self.intent.client_order_id,
        )

        conflict = simulate_fake_only(
            conflicting_intent,
            self.environment,
            self.ledger,
        )
        original_again = simulate_fake_only(
            self.intent,
            self.environment,
            self.ledger,
        )

        self.assertEqual(first.status, "ACCEPTED")
        self.assertEqual(conflict.status, "IDEMPOTENCY_CONFLICT")
        self.assertEqual(original_again.status, "DUPLICATE")
        self.assertEqual(self.ledger.size, 1)

    def test_invalid_decimal_and_quantity_inputs_are_rejected(self) -> None:
        for value in (
            1.2345,
            Decimal("NaN"),
            Decimal("sNaN"),
            Decimal("Infinity"),
            Decimal("-Infinity"),
            Decimal("0"),
            Decimal("-1"),
        ):
            with self.subTest(reference_price=value):
                intent = FakeOnlyIntent(
                    account_ref=self.intent.account_ref,
                    instrument=self.intent.instrument,
                    side=self.intent.side,
                    quantity=self.intent.quantity,
                    reference_price=value,
                    client_order_id=f"fixture-order-{str(value).lower()}",
                )
                ledger = FakeOnlyLedger()

                receipt = simulate_fake_only(intent, self.environment, ledger)

                self.assertEqual(receipt.status, "REJECTED")
                self.assertEqual(ledger.size, 0)

        for quantity in (0, -1, 1.0, True):
            with self.subTest(quantity=quantity):
                intent = FakeOnlyIntent(
                    account_ref=self.intent.account_ref,
                    instrument=self.intent.instrument,
                    side=self.intent.side,
                    quantity=quantity,
                    reference_price=self.intent.reference_price,
                    client_order_id=f"fixture-order-quantity-{str(quantity)}",
                )
                ledger = FakeOnlyLedger()

                receipt = simulate_fake_only(intent, self.environment, ledger)

                self.assertEqual(receipt.status, "REJECTED")
                self.assertEqual(ledger.size, 0)

    def test_fixture_account_and_canonical_instrument_boundaries(self) -> None:
        for account_ref in (
            "account-001",
            "fixture-account-",
            "fixture-account-001/other",
            "fixture-account-001 with-space",
        ):
            with self.subTest(account_ref=account_ref):
                intent = FakeOnlyIntent(
                    account_ref=account_ref,
                    instrument=self.intent.instrument,
                    side=self.intent.side,
                    quantity=self.intent.quantity,
                    reference_price=self.intent.reference_price,
                    client_order_id=f"fixture-order-account-{len(account_ref)}",
                )
                receipt = simulate_fake_only(
                    intent,
                    self.environment,
                    FakeOnlyLedger(),
                )

                self.assertEqual(receipt.status, "REJECTED")

        for instrument in ("518880", "SH.518880", "518880.XS", "51888.SH"):
            with self.subTest(instrument=instrument):
                intent = FakeOnlyIntent(
                    account_ref=self.intent.account_ref,
                    instrument=instrument,
                    side=self.intent.side,
                    quantity=self.intent.quantity,
                    reference_price=self.intent.reference_price,
                    client_order_id=f"fixture-order-instrument-{len(instrument)}",
                )
                receipt = simulate_fake_only(
                    intent,
                    self.environment,
                    FakeOnlyLedger(),
                )

                self.assertEqual(receipt.status, "REJECTED")

    def test_digest_and_summary_are_deterministic(self) -> None:
        first = simulate_fake_only(
            self.intent,
            self.environment,
            FakeOnlyLedger(),
        )
        second = simulate_fake_only(
            self.intent,
            self.environment,
            FakeOnlyLedger(),
        )

        self.assertEqual(first.payload_digest, second.payload_digest)
        self.assertEqual(first.summary, second.summary)

    def test_invalid_shapes_fail_closed_without_touching_the_ledger(self) -> None:
        for intent, environment, ledger in (
            (object(), self.environment, FakeOnlyLedger()),
            (self.intent, object(), FakeOnlyLedger()),
            (self.intent, self.environment, object()),
        ):
            with self.subTest(
                intent_type=type(intent).__name__,
                environment_type=type(environment).__name__,
                ledger_type=type(ledger).__name__,
            ):
                receipt = simulate_fake_only(intent, environment, ledger)

                self.assertEqual(receipt.status, "REJECTED")

    def test_implementation_imports_and_calls_stay_within_offline_allowlist(
        self,
    ) -> None:
        self.assertIn("fake-only", _MODULE_SOURCE)
        self.assertIsInstance(_MODULE_TREE, ast.Module)

    def test_scanner_rejects_dynamic_builtin_file_access(self) -> None:
        malicious_sources = (
            'getattr(__builtins__, "open")',
            'globals()["__builtins__"]',
            'locals()["open"]',
            'vars()["open"]',
            'getattr(other, "account_ref", _MISSING)',
            "getattr(intent, dynamic_field, _MISSING)",
            'getattr(intent, "account_ref")',
            'module.getattr(intent, "account_ref", _MISSING)',
        )

        for malicious_source in malicious_sources:
            with (
                self.subTest(source=malicious_source),
                self.assertRaises(AssertionError),
            ):
                _assert_source_safe(malicious_source)

        _assert_source_safe('getattr(intent, "account_ref", _MISSING)')

    def test_simulation_does_not_use_file_io(self) -> None:
        def forbidden_open(*args: object, **kwargs: object) -> object:
            raise AssertionError(f"unexpected file I/O: {args!r} {kwargs!r}")

        with patch.object(builtins, "open", forbidden_open):
            receipt = simulate_fake_only(
                self.intent,
                self.environment,
                FakeOnlyLedger(),
            )

        self.assertEqual(receipt.status, "ACCEPTED")
