import unittest

from translator_service.documents import validate_document_upload
from translator_service.orders import DraftOrderRepository, create_draft_order


class DraftOrderTest(unittest.TestCase):
    def test_creates_draft_order_for_validated_document(self):
        repository = DraftOrderRepository()
        upload = validate_document_upload(
            file_name="book.epub",
            size_bytes=2048,
            max_upload_mb=50,
        )

        order = create_draft_order(
            repository,
            user_telegram_id=42,
            upload=upload,
        )

        self.assertEqual(order.id, "order-1")
        self.assertEqual(order.user_telegram_id, 42)
        self.assertEqual(order.file_name, "book.epub")
        self.assertEqual(order.status, "file_received")
        self.assertEqual(repository.get(order.id), order)


if __name__ == "__main__":
    unittest.main()
