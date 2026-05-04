from decimal import Decimal
import unittest

from translator_service.billing import (
    BalanceError,
    InMemoryBalanceRepository,
    InMemoryLedgerRepository,
    adjust_balance,
)
from translator_service.documents import validate_document_upload
from translator_service.order_payments import confirm_order_payment, refund_order_payment
from translator_service.orders import (
    DraftOrderRepository,
    attach_order_estimate,
    create_draft_order,
)


class OrderPaymentsTest(unittest.TestCase):
    def test_confirm_order_payment_charges_balance_and_marks_order_paid(self):
        orders = DraftOrderRepository()
        balances = InMemoryBalanceRepository()
        ledger = InMemoryLedgerRepository()
        order = _estimated_order(orders)
        adjust_balance(
            balances=balances,
            ledger=ledger,
            user_telegram_id=42,
            amount=Decimal("5.00"),
            reason="top-up",
        )

        paid = confirm_order_payment(
            orders=orders,
            balances=balances,
            ledger=ledger,
            order_id=order.id,
        )

        self.assertEqual(paid.status, "paid")
        self.assertEqual(paid.paid_at, paid.updated_at)
        self.assertEqual(balances.get_available(42), Decimal("4.10"))
        self.assertEqual(orders.get(order.id), paid)

    def test_confirm_order_payment_rejects_unestimated_order(self):
        orders = DraftOrderRepository()
        balances = InMemoryBalanceRepository()
        ledger = InMemoryLedgerRepository()
        upload = validate_document_upload(
            file_name="book.epub",
            size_bytes=2048,
            max_upload_mb=50,
        )
        order = create_draft_order(
            orders,
            user_telegram_id=42,
            upload=upload,
        )

        with self.assertRaises(ValueError):
            confirm_order_payment(
                orders=orders,
                balances=balances,
                ledger=ledger,
                order_id=order.id,
            )

        self.assertEqual(orders.get(order.id).status, "file_received")

    def test_confirm_order_payment_keeps_order_estimated_when_balance_is_low(self):
        orders = DraftOrderRepository()
        balances = InMemoryBalanceRepository()
        ledger = InMemoryLedgerRepository()
        order = _estimated_order(orders)

        with self.assertRaises(BalanceError):
            confirm_order_payment(
                orders=orders,
                balances=balances,
                ledger=ledger,
                order_id=order.id,
            )

        self.assertEqual(orders.get(order.id), order)

    def test_refund_order_payment_restores_balance_and_marks_order_refunded(self):
        orders = DraftOrderRepository()
        balances = InMemoryBalanceRepository()
        ledger = InMemoryLedgerRepository()
        order = _estimated_order(orders)
        adjust_balance(
            balances=balances,
            ledger=ledger,
            user_telegram_id=42,
            amount=Decimal("5.00"),
            reason="top-up",
        )
        confirm_order_payment(
            orders=orders,
            balances=balances,
            ledger=ledger,
            order_id=order.id,
        )

        refunded = refund_order_payment(
            orders=orders,
            balances=balances,
            ledger=ledger,
            order_id=order.id,
            reason="translation failed",
        )

        self.assertEqual(refunded.status, "refunded")
        self.assertEqual(balances.get_available(42), Decimal("5.00"))


def _estimated_order(orders: DraftOrderRepository):
    upload = validate_document_upload(
        file_name="book.epub",
        size_bytes=2048,
        max_upload_mb=50,
    )
    order = create_draft_order(
        orders,
        user_telegram_id=42,
        upload=upload,
    )
    return attach_order_estimate(
        orders,
        order_id=order.id,
        price_usd=Decimal("0.90"),
        fragment_count=18,
    )


if __name__ == "__main__":
    unittest.main()
