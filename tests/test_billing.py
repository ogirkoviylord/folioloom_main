from decimal import Decimal
import unittest

from translator_service.billing import (
    BalanceError,
    InMemoryBalanceRepository,
    InMemoryLedgerRepository,
    adjust_balance,
    charge_order,
    refund_order,
)


class BillingTest(unittest.TestCase):
    def test_admin_adjustment_increases_user_balance_and_records_ledger_entry(self):
        balances = InMemoryBalanceRepository()
        ledger = InMemoryLedgerRepository()

        entry = adjust_balance(
            balances=balances,
            ledger=ledger,
            user_telegram_id=42,
            amount=Decimal("15.00"),
            reason="manual beta top-up",
        )

        self.assertEqual(balances.get_available(42), Decimal("15.00"))
        self.assertEqual(entry.id, "ledger-1")
        self.assertEqual(entry.kind, "admin_adjustment")
        self.assertEqual(entry.amount, Decimal("15.00"))
        self.assertEqual(entry.balance_after, Decimal("15.00"))
        self.assertEqual(ledger.list_for_user(42), [entry])

    def test_order_charge_decreases_balance_and_is_idempotent_per_order(self):
        balances = InMemoryBalanceRepository()
        ledger = InMemoryLedgerRepository()
        adjust_balance(
            balances=balances,
            ledger=ledger,
            user_telegram_id=42,
            amount=Decimal("10.00"),
            reason="top-up",
        )

        first = charge_order(
            balances=balances,
            ledger=ledger,
            user_telegram_id=42,
            order_id="order-1",
            amount=Decimal("3.25"),
        )
        second = charge_order(
            balances=balances,
            ledger=ledger,
            user_telegram_id=42,
            order_id="order-1",
            amount=Decimal("3.25"),
        )

        self.assertEqual(first, second)
        self.assertEqual(balances.get_available(42), Decimal("6.75"))
        self.assertEqual(len(ledger.list_for_user(42)), 2)

    def test_order_charge_rejects_insufficient_balance(self):
        balances = InMemoryBalanceRepository()
        ledger = InMemoryLedgerRepository()
        adjust_balance(
            balances=balances,
            ledger=ledger,
            user_telegram_id=42,
            amount=Decimal("1.00"),
            reason="top-up",
        )

        with self.assertRaises(BalanceError):
            charge_order(
                balances=balances,
                ledger=ledger,
                user_telegram_id=42,
                order_id="order-1",
                amount=Decimal("2.00"),
            )

        self.assertEqual(balances.get_available(42), Decimal("1.00"))
        self.assertEqual(len(ledger.list_for_user(42)), 1)

    def test_order_refund_restores_charged_amount_once(self):
        balances = InMemoryBalanceRepository()
        ledger = InMemoryLedgerRepository()
        adjust_balance(
            balances=balances,
            ledger=ledger,
            user_telegram_id=42,
            amount=Decimal("10.00"),
            reason="top-up",
        )
        charge_order(
            balances=balances,
            ledger=ledger,
            user_telegram_id=42,
            order_id="order-1",
            amount=Decimal("4.00"),
        )

        first = refund_order(
            balances=balances,
            ledger=ledger,
            user_telegram_id=42,
            order_id="order-1",
            reason="translation failed",
        )
        second = refund_order(
            balances=balances,
            ledger=ledger,
            user_telegram_id=42,
            order_id="order-1",
            reason="translation failed",
        )

        self.assertEqual(first, second)
        self.assertEqual(first.kind, "refund")
        self.assertEqual(first.amount, Decimal("4.00"))
        self.assertEqual(balances.get_available(42), Decimal("10.00"))
        self.assertEqual(len(ledger.list_for_user(42)), 3)


if __name__ == "__main__":
    unittest.main()
