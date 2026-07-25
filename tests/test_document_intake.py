from __future__ import annotations

import io
import re
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from translator_service.api import create_app
from translator_service.config import Settings
from translator_service.file_storage import LocalObjectStorage
from translator_service.persistent_jobs import SQLiteTranslationJobStore
from translator_service.source_registry_service import SourceRegistryActor


class DocumentIntakeServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        root = Path(self._temp_dir.name)
        self.store = SQLiteTranslationJobStore(root / "jobs.sqlite3")
        self.addCleanup(self.store.close)
        self.storage = LocalObjectStorage(root / "objects")
        self.actor = SourceRegistryActor(
            actor_id="bootstrap-owner",
            role="owner",
            authn_schema_version="admin-session-v1",
        )

    def test_ingest_stores_verifies_registers_and_catalogs_owner_docx(self) -> None:
        from translator_service.document_intake import (
            catalog_registered_original_docx_sources,
            ingest_owner_docx,
            select_owner_registered_original_docx_source,
        )

        registered = ingest_owner_docx(
            store=self.store,
            storage=self.storage,
            actor=self.actor,
            file_name="book.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            content=_docx_bytes(),
            maximum_size_bytes=1024 * 1024,
        )

        self.assertEqual(registered.source_size_bytes, len(_docx_bytes()))
        catalog = catalog_registered_original_docx_sources(
            store=self.store, storage=self.storage, actor=self.actor
        )
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0].document_custody_id, registered.document_custody_id)
        self.assertEqual(catalog[0].file_name, "book.docx")
        selected = select_owner_registered_original_docx_source(
            store=self.store,
            storage=self.storage,
            actor=self.actor,
            document_custody_id=registered.document_custody_id,
        )
        self.assertEqual(selected, registered)
        self.assertFalse(hasattr(catalog[0], "source_object_key"))

    def test_ingest_denies_invalid_or_oversize_bytes_without_storage_write(
        self,
    ) -> None:
        from translator_service.document_intake import (
            DocumentIntakeDenied,
            ingest_owner_docx,
        )

        for file_name, content, maximum, expected in (
            ("book.txt", _docx_bytes(), 1024 * 1024, "document_intake_file_invalid"),
            ("book.docx", b"not a docx", 1024 * 1024, "document_intake_file_invalid"),
            ("book.docx", _docx_bytes(), 1, "document_intake_file_too_large"),
        ):
            with self.subTest(file_name=file_name, maximum=maximum):
                result = ingest_owner_docx(
                    store=self.store,
                    storage=self.storage,
                    actor=self.actor,
                    file_name=file_name,
                    content_type="application/octet-stream",
                    content=content,
                    maximum_size_bytes=maximum,
                )
                self.assertEqual(result, DocumentIntakeDenied(expected))
                self.assertFalse((Path(self._temp_dir.name) / "objects").exists())

    def test_created_object_is_compensated_when_registration_is_denied(self) -> None:
        from translator_service.document_intake import (
            DocumentIntakeDenied,
            ingest_owner_docx,
        )

        result = ingest_owner_docx(
            store=object(),
            storage=self.storage,
            actor=self.actor,
            file_name="book.docx",
            content_type="application/octet-stream",
            content=_docx_bytes(),
            maximum_size_bytes=1024 * 1024,
        )

        self.assertEqual(
            result, DocumentIntakeDenied("source_registry_unsupported_backend")
        )
        self.assertEqual(
            list((Path(self._temp_dir.name) / "objects").rglob("*.docx")), []
        )

    def test_owner_documents_upload_and_selection_require_session_and_csrf(
        self,
    ) -> None:
        root = Path(self._temp_dir.name)
        client = TestClient(
            create_app(
                Settings(
                    admin_owner_password="owner-pass",
                    admin_session_secret="session-secret",
                    persistent_jobs_db_path=str(root / "route-jobs.sqlite3"),
                    object_storage_root=str(root / "route-objects"),
                )
            )
        )
        self.assertEqual(
            client.get("/admin/documents", follow_redirects=False).status_code, 303
        )
        client.post("/admin/login", data={"password": "owner-pass"})
        page = client.get("/admin/documents")
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf_token is not None
        missing_file = client.post(
            "/admin/documents/upload",
            data={"csrf_token": csrf_token.group(1)},
            follow_redirects=False,
        )
        self.assertEqual(missing_file.status_code, 400)
        uploaded = client.post(
            "/admin/documents/upload",
            data={"csrf_token": csrf_token.group(1)},
            files={"file": ("book.docx", _docx_bytes(), "application/octet-stream")},
            follow_redirects=False,
        )
        self.assertEqual(uploaded.status_code, 303)
        after_upload = client.get("/admin/documents")
        custody = re.search(
            r'name="document_custody_id" value="([^"]+)"', after_upload.text
        )
        assert custody is not None
        self.assertIn("book.docx", after_upload.text)
        bad_csrf = client.post(
            "/admin/documents/select",
            data={"csrf_token": "bad", "document_custody_id": custody.group(1)},
            follow_redirects=False,
        )
        self.assertEqual(bad_csrf.status_code, 403)
        selected = client.post(
            "/admin/documents/select",
            data={
                "csrf_token": csrf_token.group(1),
                "document_custody_id": custody.group(1),
            },
            follow_redirects=False,
        )
        self.assertEqual(selected.status_code, 303)
        self.assertTrue(selected.headers["location"].startswith("/admin/workbench/"))

    def test_ingest_reuses_matching_owner_registration_without_second_catalog_entry(
        self,
    ) -> None:
        from translator_service.document_intake import (
            catalog_registered_original_docx_sources,
            ingest_owner_docx,
        )

        first = ingest_owner_docx(
            store=self.store,
            storage=self.storage,
            actor=self.actor,
            file_name="book.docx",
            content_type="application/octet-stream",
            content=_docx_bytes(),
            maximum_size_bytes=1024 * 1024,
        )
        second = ingest_owner_docx(
            store=self.store,
            storage=self.storage,
            actor=self.actor,
            file_name="book.docx",
            content_type="application/octet-stream",
            content=_docx_bytes(),
            maximum_size_bytes=1024 * 1024,
        )
        catalog = catalog_registered_original_docx_sources(
            store=self.store, storage=self.storage, actor=self.actor
        )

        self.assertEqual(first, second)
        self.assertIsInstance(catalog, tuple)
        self.assertEqual(len(catalog), 1)


def _docx_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<w:document />")
    return output.getvalue()
