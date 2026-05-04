from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from translator_service.documents import DocumentFormat, DocumentUpload


@dataclass(frozen=True)
class DraftOrder:
    id: str
    user_telegram_id: int
    file_name: str
    document_format: DocumentFormat
    size_bytes: int
    status: str
    created_at: datetime
    updated_at: datetime | None = None
    price_usd: Decimal | None = None
    fragment_count: int | None = None
    paid_at: datetime | None = None
    refunded_at: datetime | None = None


class DraftOrderRepository:
    def __init__(self) -> None:
        self._orders: dict[str, DraftOrder] = {}
        self._next_id = 1

    def next_id(self) -> str:
        order_id = f"order-{self._next_id}"
        self._next_id += 1
        return order_id

    def save(self, order: DraftOrder) -> DraftOrder:
        self._orders[order.id] = order
        return order

    def get(self, order_id: str) -> DraftOrder | None:
        return self._orders.get(order_id)


def create_draft_order(
    repository: DraftOrderRepository,
    *,
    user_telegram_id: int,
    upload: DocumentUpload,
) -> DraftOrder:
    now = datetime.now(UTC)
    return repository.save(
        DraftOrder(
            id=repository.next_id(),
            user_telegram_id=user_telegram_id,
            file_name=upload.file_name,
            document_format=upload.document_format,
            size_bytes=upload.size_bytes,
            status="file_received",
            created_at=now,
            updated_at=now,
        )
    )


def attach_order_estimate(
    repository: DraftOrderRepository,
    *,
    order_id: str,
    price_usd: Decimal,
    fragment_count: int,
) -> DraftOrder:
    order = _require_order(repository, order_id)
    return repository.save(
        DraftOrder(
            id=order.id,
            user_telegram_id=order.user_telegram_id,
            file_name=order.file_name,
            document_format=order.document_format,
            size_bytes=order.size_bytes,
            status="estimated",
            created_at=order.created_at,
            updated_at=datetime.now(UTC),
            price_usd=price_usd,
            fragment_count=fragment_count,
            paid_at=order.paid_at,
            refunded_at=order.refunded_at,
        )
    )


def mark_order_paid(
    repository: DraftOrderRepository,
    *,
    order_id: str,
) -> DraftOrder:
    order = _require_order(repository, order_id)
    now = datetime.now(UTC)
    return repository.save(
        DraftOrder(
            id=order.id,
            user_telegram_id=order.user_telegram_id,
            file_name=order.file_name,
            document_format=order.document_format,
            size_bytes=order.size_bytes,
            status="paid",
            created_at=order.created_at,
            updated_at=now,
            price_usd=order.price_usd,
            fragment_count=order.fragment_count,
            paid_at=now,
            refunded_at=order.refunded_at,
        )
    )


def mark_order_refunded(
    repository: DraftOrderRepository,
    *,
    order_id: str,
) -> DraftOrder:
    order = _require_order(repository, order_id)
    now = datetime.now(UTC)
    return repository.save(
        DraftOrder(
            id=order.id,
            user_telegram_id=order.user_telegram_id,
            file_name=order.file_name,
            document_format=order.document_format,
            size_bytes=order.size_bytes,
            status="refunded",
            created_at=order.created_at,
            updated_at=now,
            price_usd=order.price_usd,
            fragment_count=order.fragment_count,
            paid_at=order.paid_at,
            refunded_at=now,
        )
    )


def _require_order(repository: DraftOrderRepository, order_id: str) -> DraftOrder:
    order = repository.get(order_id)
    if order is None:
        raise ValueError(f"Order does not exist: {order_id}")
    return order
