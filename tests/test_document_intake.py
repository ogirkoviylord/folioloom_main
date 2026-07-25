from __future__ import annotations

import asyncio
import io
import json
import os
import re
import unittest
import zipfile
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.requests import Request

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

    def test_selection_and_catalog_omit_source_when_verification_read_fails(
        self,
    ) -> None:
        from translator_service.document_intake import (
            DocumentIntakeDenied,
            catalog_registered_original_docx_sources,
            ingest_owner_docx,
            select_owner_registered_original_docx_source,
        )

        registered = ingest_owner_docx(
            store=self.store,
            storage=self.storage,
            actor=self.actor,
            file_name="book.docx",
            content_type="application/octet-stream",
            content=_docx_bytes(),
            maximum_size_bytes=1024 * 1024,
        )
        assert not isinstance(registered, DocumentIntakeDenied)

        with patch.object(
            self.storage,
            "get_bytes",
            side_effect=OSError("verification read unavailable"),
        ):
            selected = select_owner_registered_original_docx_source(
                store=self.store,
                storage=self.storage,
                actor=self.actor,
                document_custody_id=registered.document_custody_id,
            )
            catalog = catalog_registered_original_docx_sources(
                store=self.store,
                storage=self.storage,
                actor=self.actor,
            )

        self.assertEqual(
            selected,
            DocumentIntakeDenied("source_registry_source_document_storage_unavailable"),
        )
        self.assertEqual(catalog, ())

    def test_catalog_omits_source_when_second_metadata_read_fails(self) -> None:
        from translator_service.document_intake import (
            DocumentIntakeDenied,
            catalog_registered_original_docx_sources,
            ingest_owner_docx,
        )

        registered = ingest_owner_docx(
            store=self.store,
            storage=self.storage,
            actor=self.actor,
            file_name="book.docx",
            content_type="application/octet-stream",
            content=_docx_bytes(),
            maximum_size_bytes=1024 * 1024,
        )
        assert not isinstance(registered, DocumentIntakeDenied)
        original_get_metadata = LocalObjectStorage.get_metadata
        metadata_reads = 0

        def second_metadata_unavailable(
            storage: LocalObjectStorage, object_key: str
        ) -> object:
            nonlocal metadata_reads
            metadata_reads += 1
            if metadata_reads == 2:
                raise OSError("second metadata unavailable")
            return original_get_metadata(storage, object_key)

        with patch.object(
            LocalObjectStorage,
            "get_metadata",
            new=second_metadata_unavailable,
        ):
            catalog = catalog_registered_original_docx_sources(
                store=self.store,
                storage=self.storage,
                actor=self.actor,
            )

        self.assertEqual(metadata_reads, 2)
        self.assertEqual(catalog, ())


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

    def test_ingest_denies_unsafe_docx_archive_before_storage_or_registry_write(
        self,
    ) -> None:
        from translator_service.document_intake import (
            DocumentIntakeDenied,
            ingest_owner_docx,
        )

        result = ingest_owner_docx(
            store=self.store,
            storage=self.storage,
            actor=self.actor,
            file_name="book.docx",
            content_type="application/octet-stream",
            content=_docx_bytes({"../unsafe.xml": b"unsafe"}),
            maximum_size_bytes=1024 * 1024,
        )

        self.assertEqual(result, DocumentIntakeDenied("document_intake_file_invalid"))
        self.assertFalse((Path(self._temp_dir.name) / "objects").exists())
        self.assertEqual(
            self.store._connection.execute(
                "SELECT COUNT(*) FROM strict_docx_v3_document_custody"
            ).fetchone()[0],
            0,
        )

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

    def test_ingest_denies_verification_read_os_error_and_compensates_creator(
        self,
    ) -> None:
        from translator_service.document_intake import (
            DocumentIntakeDenied,
            ingest_owner_docx,
        )

        with patch.object(
            self.storage,
            "get_bytes",
            side_effect=OSError("read unavailable"),
        ):
            result = ingest_owner_docx(
                store=self.store,
                storage=self.storage,
                actor=self.actor,
                file_name="book.docx",
                content_type="application/octet-stream",
                content=_docx_bytes(),
                maximum_size_bytes=1024 * 1024,
            )

        self.assertEqual(
            result, DocumentIntakeDenied("document_intake_storage_unavailable")
        )
        self.assertEqual(
            list((Path(self._temp_dir.name) / "objects").rglob("*.docx")), []
        )

    def test_ingest_contains_creator_cleanup_os_error_after_verification_read_error(
        self,
    ) -> None:
        from translator_service.document_intake import (
            DocumentIntakeDenied,
            ingest_owner_docx,
        )

        with patch.object(
            self.storage,
            "get_bytes",
            side_effect=OSError("read unavailable"),
        ), patch.object(
            self.storage,
            "delete_if_unretained",
            side_effect=OSError("cleanup unavailable"),
        ):
            result = ingest_owner_docx(
                store=self.store,
                storage=self.storage,
                actor=self.actor,
                file_name="book.docx",
                content_type="application/octet-stream",
                content=_docx_bytes(),
                maximum_size_bytes=1024 * 1024,
            )

        self.assertEqual(
            result, DocumentIntakeDenied("document_intake_storage_unavailable")
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

    def test_bounded_request_body_rejects_chunked_oversize_before_multipart_parse(
        self,
    ) -> None:
        from translator_service.admin.routes import _read_bounded_request_body

        request = _streaming_request(
            chunks=(b"a" * 8, b"b" * 8),
            headers=(),
        )

        self.assertIsNone(asyncio.run(_read_bounded_request_body(request, 12)))

    def test_documents_upload_rejects_multiple_file_parts_over_request_allowance(
        self,
    ) -> None:
        root = Path(self._temp_dir.name)
        client = TestClient(
            create_app(
                Settings(
                    admin_owner_password="owner-pass",
                    admin_session_secret="session-secret",
                    max_upload_mb=1,
                    persistent_jobs_db_path=str(root / "multi-route-jobs.sqlite3"),
                    object_storage_root=str(root / "multi-route-objects"),
                )
            )
        )
        client.post("/admin/login", data={"password": "owner-pass"})
        page = client.get("/admin/documents")
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf_token is not None
        valid_large_docx = _docx_bytes({"word/payload.bin": os.urandom(600_000)})

        response = client.post(
            "/admin/documents/upload",
            data={"csrf_token": csrf_token.group(1)},
            files=[
                (
                    "file",
                    ("first.docx", valid_large_docx, "application/octet-stream"),
                ),
                (
                    "extra",
                    ("second.docx", valid_large_docx, "application/octet-stream"),
                ),
            ],
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 413)
        self.assertFalse((root / "multi-route-objects").exists())

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

    def test_upload_rejects_spoofed_small_content_length_before_form_parsing(
        self,
    ) -> None:
        root = Path(self._temp_dir.name)
        client = TestClient(
            create_app(
                Settings(
                    admin_owner_password="owner-pass",
                    admin_session_secret="session-secret",
                    max_upload_mb=1,
                    persistent_jobs_db_path=str(root / "route-jobs.sqlite3"),
                    object_storage_root=str(root / "route-objects"),
                )
            ),
            raise_server_exceptions=False,
        )
        client.post("/admin/login", data={"password": "owner-pass"})
        page = client.get("/admin/documents")
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf_token is not None
        boundary = "document-intake-boundary"
        body = _multipart_upload_body(
            boundary=boundary,
            csrf_token=csrf_token.group(1),
            content=b"x" * (1024 * 1024 + 65537),
        )

        with patch(
            "starlette.requests.Request.form",
            side_effect=AssertionError("form parsing must not start"),
        ):
            response = client.post(
                "/admin/documents/upload",
                content=body,
                headers={
                    "content-type": f"multipart/form-data; boundary={boundary}",
                    "content-length": "1",
                },
            )

        self.assertEqual(response.status_code, 413)

    def test_upload_recovers_after_metadata_publish_failure_without_server_error(
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
            ),
            raise_server_exceptions=False,
        )
        client.post("/admin/login", data={"password": "owner-pass"})
        page = client.get("/admin/documents")
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf_token is not None
        upload = {
            "file": ("book.docx", _docx_bytes(), "application/octet-stream")
        }

        with patch(
            "translator_service.file_storage.os.replace",
            side_effect=OSError("metadata unavailable"),
        ):
            failed_publish = client.post(
                "/admin/documents/upload",
                data={"csrf_token": csrf_token.group(1)},
                files=upload,
                follow_redirects=False,
            )
        recovered_upload = client.post(
            "/admin/documents/upload",
            data={"csrf_token": csrf_token.group(1)},
            files=upload,
            follow_redirects=False,
        )

        self.assertEqual(failed_publish.status_code, 400)
        self.assertEqual(recovered_upload.status_code, 303)

    def test_upload_denies_byte_write_os_error_without_server_error(self) -> None:
        root = Path(self._temp_dir.name)
        client = TestClient(
            create_app(
                Settings(
                    admin_owner_password="owner-pass",
                    admin_session_secret="session-secret",
                    persistent_jobs_db_path=str(root / "route-jobs.sqlite3"),
                    object_storage_root=str(root / "route-objects"),
                )
            ),
            raise_server_exceptions=False,
        )
        client.post("/admin/login", data={"password": "owner-pass"})
        page = client.get("/admin/documents")
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf_token is not None

        with patch(
            "translator_service.file_storage.os.fdopen",
            side_effect=OSError("write unavailable"),
        ):
            response = client.post(
                "/admin/documents/upload",
                data={"csrf_token": csrf_token.group(1)},
                files={
                    "file": (
                        "book.docx",
                        _docx_bytes(),
                        "application/octet-stream",
                    )
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 400)

    def test_upload_denies_verification_read_os_error_without_storage_disclosure(
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
            ),
            raise_server_exceptions=False,
        )
        client.post("/admin/login", data={"password": "owner-pass"})
        page = client.get("/admin/documents")
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf_token is not None

        with patch(
            "translator_service.file_storage.LocalObjectStorage.get_bytes",
            side_effect=OSError("read unavailable"),
        ):
            response = client.post(
                "/admin/documents/upload",
                data={"csrf_token": csrf_token.group(1)},
                files={
                    "file": (
                        "book.docx",
                        _docx_bytes(),
                        "application/octet-stream",
                    )
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("read unavailable", response.text)
        self.assertNotIn("original/", response.text)

    def test_selection_denies_verification_read_os_error_without_storage_disclosure(
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
            ),
            raise_server_exceptions=False,
        )
        client.post("/admin/login", data={"password": "owner-pass"})
        page = client.get("/admin/documents")
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf_token is not None
        uploaded = client.post(
            "/admin/documents/upload",
            data={"csrf_token": csrf_token.group(1)},
            files={"file": ("book.docx", _docx_bytes(), "application/octet-stream")},
            follow_redirects=False,
        )
        self.assertEqual(uploaded.status_code, 303)
        catalog = client.get("/admin/documents")
        custody = re.search(
            r'name="document_custody_id" value="([^"]+)"', catalog.text
        )
        assert custody is not None

        with patch(
            "translator_service.file_storage.LocalObjectStorage.get_bytes",
            side_effect=OSError("verification read unavailable"),
        ):
            response = client.post(
                "/admin/documents/select",
                data={
                    "csrf_token": csrf_token.group(1),
                    "document_custody_id": custody.group(1),
                },
                follow_redirects=False,
            )

        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("verification read unavailable", response.text)
        self.assertNotIn("original/", response.text)

    def test_catalog_route_omits_second_metadata_read_os_error_without_disclosure(
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
            ),
            raise_server_exceptions=False,
        )
        client.post("/admin/login", data={"password": "owner-pass"})
        page = client.get("/admin/documents")
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf_token is not None
        uploaded = client.post(
            "/admin/documents/upload",
            data={"csrf_token": csrf_token.group(1)},
            files={"file": ("book.docx", _docx_bytes(), "application/octet-stream")},
            follow_redirects=False,
        )
        self.assertEqual(uploaded.status_code, 303)
        original_get_metadata = LocalObjectStorage.get_metadata
        metadata_reads = 0

        def second_metadata_unavailable(
            storage: LocalObjectStorage, object_key: str
        ) -> object:
            nonlocal metadata_reads
            metadata_reads += 1
            if metadata_reads == 2:
                raise OSError("second metadata unavailable")
            return original_get_metadata(storage, object_key)

        with patch.object(
            LocalObjectStorage,
            "get_metadata",
            new=second_metadata_unavailable,
        ):
            response = client.get("/admin/documents")

        self.assertEqual(metadata_reads, 2)
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("second metadata unavailable", response.text)
        self.assertNotIn("original/", response.text)

    def test_upload_recovers_matching_bytes_with_malformed_metadata_without_500(
        self,
    ) -> None:
        root = Path(self._temp_dir.name)
        content = _docx_bytes()
        object_key = f"original/{sha256(content).hexdigest()[:16]}-book.docx"
        object_path = root / "route-objects" / object_key
        metadata_path = root / "route-objects" / f"{object_key}.metadata.json"
        object_path.parent.mkdir(parents=True)
        object_path.write_bytes(content)
        metadata_path.write_text("{", encoding="utf-8")
        client = TestClient(
            create_app(
                Settings(
                    admin_owner_password="owner-pass",
                    admin_session_secret="session-secret",
                    persistent_jobs_db_path=str(root / "route-jobs.sqlite3"),
                    object_storage_root=str(root / "route-objects"),
                )
            ),
            raise_server_exceptions=False,
        )
        client.post("/admin/login", data={"password": "owner-pass"})
        page = client.get("/admin/documents")
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf_token is not None

        response = client.post(
            "/admin/documents/upload",
            data={"csrf_token": csrf_token.group(1)},
            files={"file": ("book.docx", content, "application/octet-stream")},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            sha256(
                (root / "route-objects" / object_key).read_bytes()
            ).hexdigest(),
            sha256(content).hexdigest(),
        )
        self.assertEqual(
            json.loads(metadata_path.read_text(encoding="utf-8"))["sha256"],
            sha256(content).hexdigest(),
        )

    def test_concurrent_compensation_keeps_object_created_by_successful_request(
        self,
    ) -> None:
        from translator_service.document_intake import ingest_owner_docx
        from translator_service.source_registry_service import (
            RegisteredOriginalDocxSource,
            SourceRegistryDenied,
        )

        first_registration_entered = Event()
        allow_first_registration = Event()
        results = []

        def register(*, store, actor, source):
            del store, actor
            if not first_registration_entered.is_set():
                first_registration_entered.set()
                allow_first_registration.wait(timeout=1)
                return RegisteredOriginalDocxSource(
                    document_custody_id="successful-request",
                    source_sha256=source.sha256,
                    source_size_bytes=source.size_bytes,
                )
            return SourceRegistryDenied("source_registry_unsupported_backend")

        def ingest() -> None:
            results.append(
                ingest_owner_docx(
                    store=object(),
                    storage=self.storage,
                    actor=self.actor,
                    file_name="book.docx",
                    content_type="application/octet-stream",
                    content=_docx_bytes(),
                    maximum_size_bytes=1024 * 1024,
                )
            )

        with patch(
            "translator_service.document_intake.register_verified_original_docx_source",
            side_effect=register,
        ):
            first = Thread(target=ingest)
            first.start()
            self.assertTrue(first_registration_entered.wait(timeout=1))
            second = Thread(target=ingest)
            second.start()
            second.join(timeout=1)
            allow_first_registration.set()
            first.join(timeout=1)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(len(results), 2)
        self.assertTrue(
            self.storage.exists("original/" + _docx_digest_prefix() + "-book.docx")
        )

    def test_failed_creator_cannot_delete_reuser_registered_source(self) -> None:
        from translator_service.document_intake import (
            ingest_owner_docx,
            select_owner_registered_original_docx_source,
        )
        from translator_service.source_registry_service import (
            RegisteredOriginalDocxSource,
            SourceRegistryDenied,
        )
        from translator_service.source_registry_service import (
            register_verified_original_docx_source as register_source,
        )

        first_registration_entered = Event()
        allow_creator_denial = Event()
        results = []

        def register(*, store, actor, source):
            if not first_registration_entered.is_set():
                first_registration_entered.set()
                allow_creator_denial.wait(timeout=1)
                return SourceRegistryDenied("source_registry_unsupported_backend")
            return register_source(store=store, actor=actor, source=source)

        def ingest() -> None:
            results.append(
                ingest_owner_docx(
                    store=self.store,
                    storage=self.storage,
                    actor=self.actor,
                    file_name="book.docx",
                    content_type="application/octet-stream",
                    content=_docx_bytes(),
                    maximum_size_bytes=1024 * 1024,
                )
            )

        with patch(
            "translator_service.document_intake.register_verified_original_docx_source",
            side_effect=register,
        ):
            creator = Thread(target=ingest)
            creator.start()
            self.assertTrue(first_registration_entered.wait(timeout=1))
            reuser = Thread(target=ingest)
            reuser.start()
            reuser.join(timeout=1)
            allow_creator_denial.set()
            creator.join(timeout=1)

        self.assertFalse(creator.is_alive())
        self.assertFalse(reuser.is_alive())
        self.assertEqual(len(results), 2)
        registered = next(
            result
            for result in results
            if isinstance(result, RegisteredOriginalDocxSource)
        )
        self.assertTrue(
            self.storage.exists("original/" + _docx_digest_prefix() + "-book.docx")
        )
        self.assertEqual(
            select_owner_registered_original_docx_source(
                store=self.store,
                storage=self.storage,
                actor=self.actor,
                document_custody_id=registered.document_custody_id,
            ),
            registered,
        )


def _docx_bytes(extra_members: dict[str, bytes] | None = None) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<w:document />")
        for member_name, content in (extra_members or {}).items():
            archive.writestr(member_name, content)
    return output.getvalue()


def _streaming_request(
    *, chunks: tuple[bytes, ...], headers: tuple[tuple[bytes, bytes], ...]
) -> Request:
    messages = iter(
        (
            {
                "type": "http.request",
                "body": chunk,
                "more_body": index < len(chunks) - 1,
            }
            for index, chunk in enumerate(chunks)
        )
    )

    async def receive() -> dict:
        return next(messages)

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/admin/documents/upload",
            "headers": list(headers),
        },
        receive,
    )


def _multipart_upload_body(*, boundary: str, csrf_token: str, content: bytes) -> bytes:
    return (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="csrf_token"\r\n\r\n'
        f"{csrf_token}\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="book.docx"\r\n'
        "Content-Type: "
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()


def _docx_digest_prefix() -> str:
    return sha256(_docx_bytes()).hexdigest()[:16]
