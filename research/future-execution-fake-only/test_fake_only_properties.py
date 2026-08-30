"""Deterministic property tests for the fake-only execution safety spike."""

from __future__ import annotations

import itertools
import re
import sys
import threading
import unittest
from dataclasses import replace
from decimal import Decimal

from fake_only_execution import (
    FakeOnlyEnvironment,
    FakeOnlyIntent,
    FakeOnlyLedger,
    FakeOnlyReceipt,
    simulate_fake_only,
)

_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")


class FakeOnlyExecutionPropertyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intent = FakeOnlyIntent(
            account_ref="fixture-account-property-001",
            instrument="518880.SH",
            side="BUY",
            quantity=100,
            reference_price=Decimal("1.2345"),
            client_order_id="fixture-property-order-001",
        )
        self.environment = FakeOnlyEnvironment(
            risk_ready=True,
            simulated_transport_ready=True,
            reconciliation_matched=True,
            kill_switch_active=False,
        )

    def assert_receipt_stays_fake_only(self, receipt: FakeOnlyReceipt) -> None:
        self.assertFalse(receipt.broker_executable)
        self.assertEqual(receipt.execution_capability, "PAPER_ONLY")
        self.assertEqual(receipt.accepted, receipt.status == "ACCEPTED")
        self.assertIsNotNone(_DIGEST_PATTERN.fullmatch(receipt.payload_digest))
        self.assertNotIn("broker_executable=True", receipt.summary)
        self.assertNotIn("execution_capability=LIVE", receipt.summary)

    def test_environment_truth_table_has_exactly_one_accepting_state(self) -> None:
        accepted_states: list[tuple[bool, bool, bool, bool]] = []

        for (
            risk_ready,
            simulated_transport_ready,
            reconciliation_matched,
            kill_switch_active,
        ) in itertools.product((False, True), repeat=4):
            state = (
                risk_ready,
                simulated_transport_ready,
                reconciliation_matched,
                kill_switch_active,
            )
            with self.subTest(state=state):
                environment = FakeOnlyEnvironment(
                    risk_ready=risk_ready,
                    simulated_transport_ready=simulated_transport_ready,
                    reconciliation_matched=reconciliation_matched,
                    kill_switch_active=kill_switch_active,
                )
                ledger = FakeOnlyLedger()

                receipt = simulate_fake_only(self.intent, environment, ledger)

                self.assert_receipt_stays_fake_only(receipt)
                if receipt.status == "ACCEPTED":
                    accepted_states.append(state)
                    self.assertEqual(ledger.size, 1)
                else:
                    self.assertEqual(receipt.status, "REJECTED")
                    self.assertEqual(ledger.size, 0)

        self.assertEqual(accepted_states, [(True, True, True, False)])

    def test_first_valid_payload_wins_for_every_short_payload_sequence(self) -> None:
        variants = (
            self.intent,
            replace(self.intent, quantity=200),
            replace(self.intent, side="SELL"),
        )

        for indexes in itertools.product(range(len(variants)), repeat=5):
            with self.subTest(indexes=indexes):
                ledger = FakeOnlyLedger()
                winner = variants[indexes[0]]
                receipts = [
                    simulate_fake_only(variants[index], self.environment, ledger)
                    for index in indexes
                ]
                expected_statuses = [
                    "ACCEPTED",
                    *(
                        "DUPLICATE" if variants[index] == winner else "IDEMPOTENCY_CONFLICT"
                        for index in indexes[1:]
                    ),
                ]

                self.assertEqual(
                    [receipt.status for receipt in receipts],
                    expected_statuses,
                )
                self.assertEqual(ledger.size, 1)
                for receipt in receipts:
                    self.assert_receipt_stays_fake_only(receipt)

    def test_rejected_payloads_cannot_reserve_or_replace_an_idempotency_key(
        self,
    ) -> None:
        invalid_intents = (
            replace(self.intent, instrument="SH.518880"),
            replace(self.intent, side="HOLD"),
            replace(self.intent, quantity=0),
            replace(self.intent, reference_price=Decimal("0")),
            replace(self.intent, broker_executable=True),
            replace(self.intent, execution_capability="LIVE"),
        )

        for invalid_intent in invalid_intents:
            with self.subTest(invalid_intent=invalid_intent):
                ledger = FakeOnlyLedger()

                rejected_before = simulate_fake_only(
                    invalid_intent,
                    self.environment,
                    ledger,
                )
                accepted = simulate_fake_only(self.intent, self.environment, ledger)
                rejected_after = simulate_fake_only(
                    invalid_intent,
                    self.environment,
                    ledger,
                )
                duplicate = simulate_fake_only(self.intent, self.environment, ledger)

                self.assertEqual(
                    [
                        rejected_before.status,
                        accepted.status,
                        rejected_after.status,
                        duplicate.status,
                    ],
                    ["REJECTED", "ACCEPTED", "REJECTED", "DUPLICATE"],
                )
                self.assertEqual(ledger.size, 1)
                for receipt in (
                    rejected_before,
                    accepted,
                    rejected_after,
                    duplicate,
                ):
                    self.assert_receipt_stays_fake_only(receipt)

    def test_same_client_order_id_is_scoped_by_fixture_account(self) -> None:
        ledger = FakeOnlyLedger()
        intents = tuple(
            replace(self.intent, account_ref=f"fixture-account-property-{index:03d}")
            for index in range(1, 9)
        )

        first_statuses = [
            simulate_fake_only(intent, self.environment, ledger).status for intent in intents
        ]
        retry_statuses = [
            simulate_fake_only(intent, self.environment, ledger).status
            for intent in reversed(intents)
        ]

        self.assertEqual(first_statuses, ["ACCEPTED"] * len(intents))
        self.assertEqual(retry_statuses, ["DUPLICATE"] * len(intents))
        self.assertEqual(ledger.size, len(intents))

    def test_mixed_payload_concurrency_preserves_one_atomic_winner(self) -> None:
        ledger = FakeOnlyLedger()
        candidates = (
            self.intent,
            replace(self.intent, quantity=200),
            replace(self.intent, quantity=300),
        )
        intents = candidates * 12
        start = threading.Barrier(len(intents))
        results_lock = threading.Lock()
        receipts: list[FakeOnlyReceipt] = []
        errors: list[BaseException] = []

        def worker(intent: FakeOnlyIntent) -> None:
            try:
                start.wait(timeout=3.0)
                receipt = simulate_fake_only(intent, self.environment, ledger)
                with results_lock:
                    receipts.append(receipt)
            except BaseException as error:
                with results_lock:
                    errors.append(error)

        threads = [threading.Thread(target=worker, args=(intent,)) for intent in intents]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5.0)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        accepted = [receipt for receipt in receipts if receipt.status == "ACCEPTED"]
        self.assertEqual(len(accepted), 1)
        winning_digest = accepted[0].payload_digest
        self.assertEqual(
            sorted(receipt.status for receipt in receipts),
            sorted(
                [
                    "ACCEPTED",
                    *("DUPLICATE" for _ in range(11)),
                    *("IDEMPOTENCY_CONFLICT" for _ in range(24)),
                ]
            ),
        )
        self.assertTrue(
            all(
                receipt.status in {"ACCEPTED", "DUPLICATE"}
                if receipt.payload_digest == winning_digest
                else receipt.status == "IDEMPOTENCY_CONFLICT"
                for receipt in receipts
            )
        )
        self.assertEqual(ledger.size, 1)
        for receipt in receipts:
            self.assert_receipt_stays_fake_only(receipt)

    def test_unserializable_integer_quantity_fails_closed(self) -> None:
        original_limit = sys.get_int_max_str_digits()
        try:
            sys.set_int_max_str_digits(640)
            intent = replace(self.intent, quantity=10**640)

            receipt = simulate_fake_only(intent, self.environment, FakeOnlyLedger())
        finally:
            sys.set_int_max_str_digits(original_limit)

        self.assertEqual(receipt.status, "REJECTED")
        self.assertEqual(receipt.reason, "quantity_invalid")
        self.assertIsNone(receipt.quantity)
        self.assert_receipt_stays_fake_only(receipt)


if __name__ == "__main__":
    unittest.main()
