from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from translator_service.file_storage import (
    LocalObjectStorage,
    StoredFileKind,
)


class LocalObjectStorageTest(unittest.TestCase):
    def test_put_and_get_bytes_with_persisted_metadata(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))

            stored = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="My Book.epub",
                content_type="application/epub+zip",
                content=b"epub bytes",
            )

            reopened = LocalObjectStorage(Path(temp_dir))
            metadata = reopened.get_metadata(stored.object_key)

            self.assertEqual(reopened.get_bytes(stored.object_key), b"epub bytes")
            self.assertEqual(metadata.object_key, stored.object_key)
            self.assertEqual(metadata.file_name, "My Book.epub")
            self.assertEqual(metadata.kind, StoredFileKind.ORIGINAL)
            self.assertEqual(metadata.content_type, "application/epub+zip")
            self.assertEqual(metadata.size_bytes, 10)
            self.assertEqual(
                metadata.sha256,
                "227dae38658f29c3a8494e65302e70b406162c2f581845339dfa19cbfad839d4",
            )
            self.assertIsInstance(metadata.created_at, datetime)
            self.assertEqual(metadata.created_at.tzinfo, UTC)

    def test_sanitizes_file_names_and_prevents_path_traversal(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root)

            stored = storage.put_bytes(
                kind=StoredFileKind.FINAL,
                file_name="../secret/../../translated book.txt",
                content_type="text/plain",
                content=b"done",
            )

            self.assertTrue(stored.object_key.startswith("final/"))
            self.assertIn("translated_book.txt", stored.object_key)
            self.assertNotIn("..", stored.object_key)
            self.assertEqual(storage.get_bytes(stored.object_key), b"done")
            self.assertFalse((root.parent / "secret").exists())

    def test_delete_removes_content_and_metadata(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            stored = storage.put_bytes(
                kind=StoredFileKind.PARTIAL,
                file_name="book.uk.partial.epub",
                content_type="application/epub+zip",
                content=b"partial",
            )

            self.assertTrue(storage.delete(stored.object_key))
            self.assertFalse(storage.exists(stored.object_key))
            self.assertFalse(storage.delete(stored.object_key))
            with self.assertRaises(FileNotFoundError):
                storage.get_bytes(stored.object_key)

    def test_rejects_empty_content(self):
        storage = LocalObjectStorage(":memory:")

        with self.assertRaises(ValueError):
            storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="empty.txt",
                content_type="text/plain",
                content=b"",
            )


if __name__ == "__main__":
    unittest.main()
