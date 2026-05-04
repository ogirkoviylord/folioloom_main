from translator_service.billing import (
    InMemoryBalanceRepository,
    InMemoryLedgerRepository,
    charge_order,
    refund_order,
)
from translator_service.orders import (
    DraftOrder,
    DraftOrderRepository,
    mark_order_paid,
    mark_order_refunded,
)


def confirm_order_payment(
    *,
    orders: DraftOrderRepository,
    balances: InMemoryBalanceRepository,
    ledger: InMemoryLedgerRepository,
    order_id: str,
) -> DraftOrder:
    order = _require_payable_order(orders, order_id)
    charge_order(
        balances=balances,
        ledger=ledger,
        user_telegram_id=order.user_telegram_id,
        order_id=order.id,
        amount=order.price_usd,
    )
    return mark_order_paid(orders, order_id=order.id)


def refund_order_payment(
    *,
    orders: DraftOrderRepository,
    balances: InMemoryBalanceRepository,
    ledger: InMemoryLedgerRepository,
    order_id: str,
    reason: str,
) -> DraftOrder:
    order = _require_existing_order(orders, order_id)
    refund_order(
        balances=balances,
        ledger=ledger,
        user_telegram_id=order.user_telegram_id,
        order_id=order.id,
        reason=reason,
    )
    return mark_order_refunded(orders, order_id=order.id)


def _require_payable_order(
    orders: DraftOrderRepository,
    order_id: str,
) -> DraftOrder:
    order = _require_existing_order(orders, order_id)
    if order.price_usd is None:
        raise ValueError("Order must have a price estimate before payment")
    if order.status not in {"estimated", "paid"}:
        raise ValueError(f"Order cannot be paid from status: {order.status}")
    return order


def _require_existing_order(
    orders: DraftOrderRepository,
    order_id: str,
) -> DraftOrder:
    order = orders.get(order_id)
    if order is None:
        raise ValueError(f"Order does not exist: {order_id}")
    return order
