import json
import unittest
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import patch

from translator_service.file_storage import (
    LocalObjectStorage,
    ObjectPublishError,
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

    def test_put_bytes_if_absent_waits_for_metadata_before_reusing(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            metadata_write_entered = Event()
            allow_metadata_write = Event()
            results = []
            original_write_metadata = storage._write_metadata

            def write_metadata(stored):
                metadata_write_entered.set()
                allow_metadata_write.wait(timeout=1)
                original_write_metadata(stored)

            def store() -> None:
                results.append(
                    storage.put_bytes_if_absent(
                        kind=StoredFileKind.ORIGINAL,
                        file_name="book.docx",
                        content_type="application/octet-stream",
                        content=b"document",
                    )
                )

            with patch.object(storage, "_write_metadata", side_effect=write_metadata):
                creator = Thread(target=store)
                creator.start()
                self.assertTrue(metadata_write_entered.wait(timeout=1))
                reuser = Thread(target=store)
                reuser.start()
                self.assertTrue(reuser.is_alive())
                allow_metadata_write.set()
                creator.join(timeout=1)
                reuser.join(timeout=1)

            self.assertFalse(creator.is_alive())
            self.assertFalse(reuser.is_alive())
            self.assertEqual(sorted(created for _, created in results), [False, True])

    def test_put_bytes_if_absent_recovers_matching_content_without_metadata(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root)
            content = b"recoverable document bytes"
            object_key = f"original/{sha256(content).hexdigest()[:16]}-book.docx"
            object_path = root / object_key
            object_path.parent.mkdir(parents=True)
            object_path.write_bytes(content)

            stored, created = storage.put_bytes_if_absent(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=content,
            )

            self.assertFalse(created)
            self.assertEqual(stored.object_key, object_key)
            self.assertEqual(storage.get_bytes(object_key), content)
            self.assertTrue(storage.exists(object_key))

    def test_put_bytes_if_absent_recovers_matching_content_with_malformed_metadata(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root)
            content = b"recoverable document bytes"
            object_key = f"original/{sha256(content).hexdigest()[:16]}-book.docx"
            object_path = root / object_key
            metadata_path = root / f"{object_key}.metadata.json"
            object_path.parent.mkdir(parents=True)
            object_path.write_bytes(content)
            metadata_path.write_text("{", encoding="utf-8")

            stored, created = storage.put_bytes_if_absent(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=content,
            )

            self.assertFalse(created)
            self.assertEqual(stored.object_key, object_key)
            self.assertEqual(storage.get_bytes(object_key), content)
            self.assertEqual(
                json.loads(metadata_path.read_text(encoding="utf-8"))["sha256"],
                sha256(content).hexdigest(),
            )

    def test_put_bytes_if_absent_rejects_mismatched_bytes_without_replacing_them(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root)
            content = b"expected document bytes"
            object_key = f"original/{sha256(content).hexdigest()[:16]}-book.docx"
            object_path = root / object_key
            metadata_path = root / f"{object_key}.metadata.json"
            object_path.parent.mkdir(parents=True)
            object_path.write_bytes(b"different document bytes")
            metadata_path.write_text("{", encoding="utf-8")

            with self.assertRaises(ObjectPublishError):
                storage.put_bytes_if_absent(
                    kind=StoredFileKind.ORIGINAL,
                    file_name="book.docx",
                    content_type=(
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document"
                    ),
                    content=content,
                )

            self.assertEqual(object_path.read_bytes(), b"different document bytes")
            self.assertEqual(metadata_path.read_text(encoding="utf-8"), "{")

    def test_metadata_publish_failure_leaves_no_partial_final_sidecar(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root)
            content = b"document"
            object_key = f"original/{sha256(content).hexdigest()[:16]}-book.docx"
            metadata_path = root / f"{object_key}.metadata.json"

            with patch(
                "translator_service.file_storage.os.replace",
                side_effect=OSError("replace failed"),
            ), self.assertRaises(ObjectPublishError):
                storage.put_bytes_if_absent(
                    kind=StoredFileKind.ORIGINAL,
                    file_name="book.docx",
                    content_type="application/octet-stream",
                    content=content,
                )

            self.assertFalse(metadata_path.exists())
            self.assertEqual(
                list(metadata_path.parent.glob(f".{metadata_path.name}.*.tmp")), []
            )


if __name__ == "__main__":
    unittest.main()
