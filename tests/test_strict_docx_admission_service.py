import unittest
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.persistent_job_store import read_strict_docx_glossary_snapshot
from translator_service.persistent_jobs import (
    GLOSSARY_APPROVAL_SCHEMA_VERSION,
    GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
    SQLiteTranslationJobStore,
)
from translator_service.persistent_planner import StrictAdmissionDenied
from translator_service.postgres_scheduler import PostgresSchedulerStore
from translator_service.strict_docx_admission_service import (
    StrictDocxAdmissionServiceRequest,
    admit_strict_docx_service_request,
)


class StrictDocxAdmissionServiceTest(unittest.TestCase):
    def test_migration_not_ready_postgres_is_denied_before_planning_or_reader_access(
        self,
    ):
        store = object.__new__(PostgresSchedulerStore)
        request = StrictDocxAdmissionServiceRequest(
            store=store,
            storage=object(),
            approval_id="approval-exact",
            source_object_key="originals/book.docx",
            order_id="order-strict",
            user_id="user-42",
            file_name="book.docx",
            source_language="en",
            target_language="uk",
            max_fragment_chars=1_000,
        )

        result = admit_strict_docx_service_request(request)

        self.assertEqual(
            result,
            StrictAdmissionDenied(code="strict_docx_migration_not_ready"),
        )
        self.assertIsNone(read_strict_docx_glossary_snapshot(store, "job-strict"))

    def test_explicit_request_forwards_exact_approval_to_strict_planner_once(self):
        store = SQLiteTranslationJobStore(":memory:")
        self.addCleanup(store.close)
        request = StrictDocxAdmissionServiceRequest(
            store=store,
            storage=object(),
            approval_id="approval-exact",
            source_object_key="originals/book.docx",
            order_id="order-strict",
            user_id="user-42",
            file_name="book.docx",
            source_language="en",
            target_language="uk",
            max_fragment_chars=1_000,
        )
        denied = StrictAdmissionDenied(code="approval_missing")

        with patch(
            "translator_service.strict_docx_admission_service."
            "create_persistent_strict_docx_job_plan",
            return_value=denied,
        ) as strict_planner:
            result = admit_strict_docx_service_request(request)

        self.assertIs(result, denied)
        strict_planner.assert_called_once_with(
            store=request.store,
            storage=request.storage,
            approval_id="approval-exact",
            source_object_key="originals/book.docx",
            order_id="order-strict",
            user_id="user-42",
            file_name="book.docx",
            source_language="en",
            target_language="uk",
            max_fragment_chars=1_000,
            adapter_version=request.adapter_version,
            prompt_version=request.prompt_version,
            pricing_snapshot_id=request.pricing_snapshot_id,
            rights_confirmation=None,
            translation_mode=None,
            upload_safety_id=None,
        )

    def test_invalid_approval_is_denied_without_persisting_a_legacy_job(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                content=_make_docx(),
            )
            payload = b"approved-snapshot"
            store.create_glossary_approval(
                snapshot_payload=payload,
                snapshot_digest=sha256(payload).hexdigest(),
                snapshot_schema_version=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
                approval_schema_version=GLOSSARY_APPROVAL_SCHEMA_VERSION,
            )

            result = admit_strict_docx_service_request(
                StrictDocxAdmissionServiceRequest(
                    store=store,
                    storage=storage,
                    approval_id="missing-approval",
                    source_object_key=source.object_key,
                    order_id="order-strict",
                    user_id="user-42",
                    file_name="book.docx",
                    source_language="en",
                    target_language="uk",
                    max_fragment_chars=1_000,
                )
            )

            self.assertEqual(result, StrictAdmissionDenied(code="approval_missing"))
            self.assertEqual(
                store._connection.execute(
                    "SELECT COUNT(*) FROM translation_jobs"
                ).fetchone()[0],
                0,
            )


def _make_docx() -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr(
            "word/document.xml",
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Strict source.</w:t></w:r></w:p></w:body>
            </w:document>
            """,
        )
    return archive.getvalue()


if __name__ == "__main__":
    unittest.main()
