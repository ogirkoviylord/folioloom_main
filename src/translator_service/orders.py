from dataclasses import dataclass
from datetime import UTC, datetime

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
    return repository.save(
        DraftOrder(
            id=repository.next_id(),
            user_telegram_id=user_telegram_id,
            file_name=upload.file_name,
            document_format=upload.document_format,
            size_bytes=upload.size_bytes,
            status="file_received",
            created_at=datetime.now(UTC),
        )
    )

