import json
import unittest
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.format_adapters import (
    DOCX_ADAPTER_VERSION,
    DOCX_TRANSLATION_MODE_DOCUMENT_FORM_PROFILE,
    EPUB_ADAPTER_VERSION,
    TRANSLATION_MODE_BOOK_MANUSCRIPT,
    TRANSLATION_MODE_DOCUMENT_FORM,
    TXT_ADAPTER_VERSION,
)
from translator_service.persistent_jobs import (
    GLOSSARY_APPROVAL_SCHEMA_VERSION,
    GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
    PersistentTranslationJobStatus,
    PersistentWorkUnitStatus,
    SQLiteTranslationJobStore,
)
from translator_service.persistent_planner import (
    BOOK_MANUSCRIPT_TRANSLATION_MODE_PROFILE,
    StrictAdmissionDenied,
    create_persistent_docx_job_plan,
    create_persistent_epub_job_plan,
    create_persistent_strict_docx_job_plan,
    create_persistent_txt_job_plan,
)
from translator_service.scheduler import SchedulerLimits


class PersistentPlannerTest(unittest.TestCase):
    def test_creates_txt_job_and_stored_work_units_from_original_file(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="notes.txt",
                content_type="text/plain; charset=utf-8",
                content=b"One.\n\nTwo.",
            )

            plan = create_persistent_txt_job_plan(
                store=store,
                storage=storage,
                order_id="order-1",
                user_id="user-42",
                source_object_key=original.object_key,
                file_name="notes.txt",
                source_language="en",
                target_language="uk",
                max_fragment_chars=5,
            )

            persisted_job = store.get_job(plan.job.id)
            persisted_units = store.list_work_units(plan.job.id)
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.QUEUED,
            )
            self.assertEqual(persisted_job.source_object_key, original.object_key)
            self.assertEqual(persisted_job.document_kind, "txt")
            self.assertEqual(persisted_job.adapter_version, TXT_ADAPTER_VERSION)
            self.assertEqual(len(persisted_units), 2)
            self.assertEqual(
                [unit.status for unit in persisted_units],
                [PersistentWorkUnitStatus.PENDING, PersistentWorkUnitStatus.PENDING],
            )
            self.assertEqual(
                storage.get_bytes(persisted_units[0].source_object_key).decode("utf-8"),
                "One.",
            )
            self.assertEqual(
                persisted_units[0].source_block_ids,
                ("txt:segment:1",),
            )
            self.assertEqual(persisted_units[0].prompt_tier, "plain")
            self.assertEqual(
                storage.get_bytes(persisted_units[1].source_object_key).decode("utf-8"),
                "Two.",
            )
            self.assertEqual(plan.work_units, persisted_units)

    def test_creates_txt_job_with_translation_policy_snapshot(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="api-notes.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Set the API endpoint and pass the placeholder token.",
            )

            plan = create_persistent_txt_job_plan(
                store=store,
                storage=storage,
                order_id="order-1",
                user_id="user-42",
                source_object_key=original.object_key,
                file_name="api-notes.txt",
                source_language="en",
                target_language="ru",
                max_fragment_chars=1_000,
            )

            persisted_job = store.get_job(plan.job.id)
            translation_policy = json.loads(persisted_job.translation_policy)

            self.assertEqual(
                translation_policy["target_language_policy"],
                "target-profile:ru:russian-v2",
            )
            self.assertEqual(
                translation_policy["russian_quality_track"],
                "russian-quality:precision-v1",
            )
            self.assertEqual(translation_policy["text_type"], "technical")
            self.assertEqual(translation_policy["target_language"], "ru")

    def test_txt_book_manuscript_mode_persists_format_neutral_profile(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="chapter.txt",
                content_type="text/plain; charset=utf-8",
                content=(
                    b"Quiet chapter opening.\n\n"
                    b"The narrator kept the same voice in the next scene."
                ),
            )

            plan = create_persistent_txt_job_plan(
                store=store,
                storage=storage,
                order_id="order-txt-book",
                user_id="user-42",
                source_object_key=original.object_key,
                file_name="chapter.txt",
                source_language="en",
                target_language="uk",
                max_fragment_chars=1_000,
                translation_mode=TRANSLATION_MODE_BOOK_MANUSCRIPT,
            )

            persisted_job = store.get_job(plan.job.id)
            translation_policy = json.loads(persisted_job.translation_policy)

            self.assertEqual(
                translation_policy["translation_mode"],
                TRANSLATION_MODE_BOOK_MANUSCRIPT,
            )
            self.assertEqual(
                translation_policy["translation_mode_profile"],
                BOOK_MANUSCRIPT_TRANSLATION_MODE_PROFILE,
            )
            self.assertIn(
                "preserve chapter, scene, paragraph, dialogue",
                translation_policy["translation_context_memory"]["style_summary"],
            )

    def test_creates_docx_job_and_stored_work_units_from_adapter_plan(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                content=_make_docx(
                    """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body>
                        <w:p><w:r><w:t>Intro paragraph.</w:t></w:r></w:p>
                        <w:tbl>
                          <w:tr>
                            <w:tc><w:p><w:r><w:t>Source</w:t></w:r></w:p></w:tc>
                            <w:tc><w:p><w:r><w:t>Target</w:t></w:r></w:p></w:tc>
                          </w:tr>
                        </w:tbl>
                        <w:p><w:r><w:t>Outro paragraph.</w:t></w:r></w:p>
                      </w:body>
                    </w:document>
                    """
                ),
            )

            plan = create_persistent_docx_job_plan(
                store=store,
                storage=storage,
                order_id="order-2",
                user_id="user-42",
                source_object_key=original.object_key,
                file_name="book.docx",
                source_language="en",
                target_language="uk",
                max_fragment_chars=1_000,
            )

            persisted_job = store.get_job(plan.job.id)
            persisted_units = store.list_work_units(plan.job.id)
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.QUEUED,
            )
            self.assertEqual(persisted_job.source_object_key, original.object_key)
            self.assertEqual(persisted_job.document_kind, "docx")
            self.assertEqual(persisted_job.adapter_version, DOCX_ADAPTER_VERSION)
            self.assertEqual(len(persisted_units), 3)
            self.assertEqual(
                [unit.status for unit in persisted_units],
                [
                    PersistentWorkUnitStatus.PENDING,
                    PersistentWorkUnitStatus.PENDING,
                    PersistentWorkUnitStatus.PENDING,
                ],
            )
            self.assertEqual(
                [
                    storage.get_bytes(unit.source_object_key).decode("utf-8")
                    for unit in persisted_units
                ],
                ["Intro paragraph.", "Source\n\nTarget", "Outro paragraph."],
            )
            self.assertEqual(
                persisted_units[1].source_block_ids,
                ("docx:word/document.xml:1", "docx:word/document.xml:2"),
            )
            self.assertEqual(persisted_units[1].prompt_tier, "strict")
            self.assertEqual(
                persisted_units[1].source_text_hash,
                sha256("Source\n\nTarget".encode("utf-8")).hexdigest(),
            )
            self.assertEqual(plan.work_units, persisted_units)

    def test_legacy_docx_plan_with_glossary_creates_no_strict_binding_and_is_claimable(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="legacy.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                content=_make_docx(
                    """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body>
                        <w:p><w:r><w:t>First paragraph.</w:t></w:r></w:p>
                        <w:p><w:r><w:t>Second paragraph.</w:t></w:r></w:p>
                      </w:body>
                    </w:document>
                    """
                ),
            )

            plan = create_persistent_docx_job_plan(
                store=store,
                storage=storage,
                order_id="order-legacy-glossary",
                user_id="user-42",
                source_object_key=original.object_key,
                file_name="legacy.docx",
                source_language="en",
                target_language="uk",
                max_fragment_chars=10,
                glossary_mode="with_glossary",
            )

            binding_count = store._connection.execute(
                "SELECT COUNT(*) FROM strict_job_glossary_bindings"
            ).fetchone()[0]
            direct_claim = store.claim_next_work_unit(plan.job.id, worker_id="worker-a")

            self.assertEqual(binding_count, 0)
            self.assertGreaterEqual(len(plan.work_units), 2)
            self.assertIsNotNone(direct_claim)
            if direct_claim is None:
                self.fail("legacy DOCX job unexpectedly not directly claimable")
            store.complete_work_unit(
                direct_claim.id,
                translated_text="First paragraph.",
                prompt_tokens=0,
                completion_tokens=0,
                cache_hit_tokens=0,
                cache_miss_tokens=0,
            )

            scheduled_claim = store.claim_next_scheduled_work_unit(
                worker_id="worker-b",
                lease_seconds=300,
                limits=SchedulerLimits(),
            )

            self.assertIsNotNone(scheduled_claim)
            if scheduled_claim is not None:
                self.assertEqual(scheduled_claim.job_id, plan.job.id)

    def test_docx_document_form_mode_persists_strict_profile_route(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="application.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                content=_make_docx(
                    """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body>
                        <w:p><w:r><w:t>Заява</w:t></w:r></w:p>
                        <w:p><w:r><w:t>Адреса: Київ</w:t></w:r></w:p>
                        <w:p><w:r><w:t>Дата: 16.05.2026</w:t></w:r></w:p>
                        <w:p><w:r><w:t>Підпис: __________</w:t></w:r></w:p>
                      </w:body>
                    </w:document>
                    """
                ),
            )

            plan = create_persistent_docx_job_plan(
                store=store,
                storage=storage,
                order_id="order-form",
                user_id="user-42",
                source_object_key=original.object_key,
                file_name="application.docx",
                source_language="uk",
                target_language="ru",
                max_fragment_chars=1_000,
                translation_mode=TRANSLATION_MODE_DOCUMENT_FORM,
            )

            persisted_job = store.get_job(plan.job.id)
            persisted_units = store.list_work_units(plan.job.id)
            translation_policy = json.loads(persisted_job.translation_policy)

            self.assertEqual(
                [unit.prompt_tier for unit in persisted_units],
                ["strict"],
            )
            self.assertEqual(
                translation_policy["translation_mode"],
                TRANSLATION_MODE_DOCUMENT_FORM,
            )
            self.assertEqual(
                translation_policy["translation_mode_profile"],
                DOCX_TRANSLATION_MODE_DOCUMENT_FORM_PROFILE,
            )
            self.assertIn(
                "preserve structure, labels, tables, addresses, dates, numbers",
                translation_policy["translation_context_memory"]["style_summary"],
            )

    def test_docx_book_manuscript_mode_preserves_existing_prose_route(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="chapter.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                content=_make_docx(
                    """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body>
                        <w:p><w:r><w:t>Quiet chapter opening.</w:t></w:r></w:p>
                        <w:p><w:r><w:t>The same voice continued.</w:t></w:r></w:p>
                      </w:body>
                    </w:document>
                    """
                ),
            )

            plan = create_persistent_docx_job_plan(
                store=store,
                storage=storage,
                order_id="order-book",
                user_id="user-42",
                source_object_key=original.object_key,
                file_name="chapter.docx",
                source_language="en",
                target_language="uk",
                max_fragment_chars=1_000,
                translation_mode=TRANSLATION_MODE_BOOK_MANUSCRIPT,
            )

            persisted_job = store.get_job(plan.job.id)
            persisted_units = store.list_work_units(plan.job.id)
            translation_policy = json.loads(persisted_job.translation_policy)

            self.assertEqual(
                [unit.prompt_tier for unit in persisted_units],
                ["plain"],
            )
            self.assertEqual(
                translation_policy["translation_mode"],
                TRANSLATION_MODE_BOOK_MANUSCRIPT,
            )
            self.assertEqual(
                translation_policy["translation_mode_profile"],
                BOOK_MANUSCRIPT_TRANSLATION_MODE_PROFILE,
            )
            self.assertIn(
                "allow natural prose flow",
                translation_policy["translation_context_memory"]["style_summary"],
            )

    def test_strict_docx_plan_admits_approved_source_without_storage_writes(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=_make_docx(
                    """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body><w:p><w:r><w:t>Strict source.</w:t></w:r></w:p></w:body>
                    </w:document>
                    """
                ),
            )
            payload = b"approved-snapshot"
            approval = store.create_glossary_approval(
                snapshot_payload=payload,
                snapshot_digest=sha256(payload).hexdigest(),
                snapshot_schema_version=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
                approval_schema_version=GLOSSARY_APPROVAL_SCHEMA_VERSION,
            )
            object_files_before = sorted(
                path
                for path in (Path(temp_dir) / "objects").rglob("*")
                if path.is_file()
            )

            plan = create_persistent_strict_docx_job_plan(
                store=store,
                storage=storage,
                approval_id=approval.approval_id,
                source_object_key=source.object_key,
                order_id="order-strict",
                user_id="user-42",
                file_name="book.docx",
                source_language="en",
                target_language="uk",
                max_fragment_chars=1_000,
            )

            if isinstance(plan, StrictAdmissionDenied):
                self.fail(f"strict job admission unexpectedly denied: {plan.code}")
            self.assertTrue(storage.exists(source.object_key))
            self.assertTrue(plan.work_units)
            self.assertTrue(
                all(
                    unit.source_object_key == source.object_key
                    for unit in plan.work_units
                )
            )
            self.assertEqual(
                sorted(
                    path
                    for path in (Path(temp_dir) / "objects").rglob("*")
                    if path.is_file()
                ),
                object_files_before,
            )

    def test_strict_docx_plan_denies_unsupported_backend_without_legacy_writes(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = _UnsupportedPersistentJobStore()
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                content=_make_docx(
                    """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body><w:p><w:r><w:t>Strict source.</w:t></w:r></w:p></w:body>
                    </w:document>
                    """
                ),
            )

            result = create_persistent_strict_docx_job_plan(
                store=store,
                storage=storage,
                approval_id="approval-unsupported",
                source_object_key=source.object_key,
                order_id="order-strict",
                user_id="user-42",
                file_name="book.docx",
                source_language="en",
                target_language="uk",
                max_fragment_chars=1_000,
            )

            self.assertEqual(
                result,
                StrictAdmissionDenied(code="strict_docx_unsupported_backend"),
            )
            self.assertEqual(store.create_job_calls, 0)
            self.assertEqual(store.add_work_units_calls, 0)

    def test_strict_docx_plan_denials_preserve_source_and_state(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            docx_source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=_make_docx(
                    """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body><w:p><w:r><w:t>Denied source.</w:t></w:r></w:p></w:body>
                    </w:document>
                    """
                ),
            )
            txt_source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="notes.txt",
                content_type="text/plain",
                content=b"not docx",
            )
            payload = b"revoked-snapshot"
            approval = store.create_glossary_approval(
                snapshot_payload=payload,
                snapshot_digest=sha256(payload).hexdigest(),
                snapshot_schema_version=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
                approval_schema_version=GLOSSARY_APPROVAL_SCHEMA_VERSION,
            )
            store.revoke_glossary_approval(approval_id=approval.approval_id)

            denied_approval = create_persistent_strict_docx_job_plan(
                store=store,
                storage=storage,
                approval_id=approval.approval_id,
                source_object_key=docx_source.object_key,
                order_id="order-denied",
                user_id="user-42",
                file_name="book.docx",
                source_language="en",
                target_language="uk",
                max_fragment_chars=1_000,
            )
            denied_kind = create_persistent_strict_docx_job_plan(
                store=store,
                storage=storage,
                approval_id="missing-approval",
                source_object_key=txt_source.object_key,
                order_id="order-not-docx",
                user_id="user-42",
                file_name="notes.txt",
                source_language="en",
                target_language="uk",
                max_fragment_chars=1_000,
            )

            self.assertEqual(
                denied_approval,
                StrictAdmissionDenied(code="approval_revoked"),
            )
            self.assertEqual(
                denied_kind,
                StrictAdmissionDenied(code="document_kind_not_docx"),
            )
            self.assertTrue(storage.exists(docx_source.object_key))
            self.assertTrue(storage.exists(txt_source.object_key))
            for table in (
                "translation_jobs",
                "work_units",
                "strict_job_glossary_bindings",
                "work_unit_attempts",
                "scheduler_events",
            ):
                count = store._connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                self.assertEqual(
                    count, 0
                )

    def test_creates_epub_job_and_stored_work_units_from_adapter_plan(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.epub",
                content_type="application/epub+zip",
                content=_make_epub(
                    {
                        "OPS/front.xhtml": """
                        <html xmlns="http://www.w3.org/1999/xhtml">
                          <body>
                            <h1>Contents</h1>
                            <p>Chapter 1</p>
                            <p>Chapter 2</p>
                          </body>
                        </html>
                        """,
                        "OPS/chapter.xhtml": """
                        <html xmlns="http://www.w3.org/1999/xhtml">
                          <head><title>Chapter Metadata Title</title></head>
                          <body>
                            <p>Intro paragraph.</p>
                            <table>
                              <tr><td>Source</td><td>Target</td></tr>
                            </table>
                            <p>Outro paragraph.</p>
                          </body>
                        </html>
                        """,
                    },
                    opf_content="""
                    <package xmlns:dc="http://purl.org/dc/elements/1.1/">
                      <metadata>
                        <dc:title>Book Metadata Title</dc:title>
                        <dc:description>Book description.</dc:description>
                        <dc:language>en</dc:language>
                      </metadata>
                    </package>
                    """,
                    ncx_content="""
                    <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
                      <docTitle><text>NCX Book Title</text></docTitle>
                      <navMap>
                        <navPoint><navLabel><text>NCX Chapter One</text></navLabel></navPoint>
                      </navMap>
                    </ncx>
                    """,
                ),
            )

            plan = create_persistent_epub_job_plan(
                store=store,
                storage=storage,
                order_id="order-3",
                user_id="user-42",
                source_object_key=original.object_key,
                file_name="book.epub",
                source_language="en",
                target_language="uk",
                max_fragment_chars=1_000,
            )

            persisted_job = store.get_job(plan.job.id)
            persisted_units = store.list_work_units(plan.job.id)
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.QUEUED,
            )
            self.assertEqual(persisted_job.source_object_key, original.object_key)
            self.assertEqual(persisted_job.document_kind, "epub")
            self.assertEqual(persisted_job.adapter_version, EPUB_ADAPTER_VERSION)
            translation_policy = json.loads(persisted_job.translation_policy)
            self.assertIn("translation_context_memory", translation_policy)
            self.assertEqual(len(persisted_units), 11)
            self.assertEqual(
                [
                    storage.get_bytes(unit.source_object_key).decode("utf-8")
                    for unit in persisted_units
                ],
                [
                    "Intro paragraph.",
                    "Source\n\nTarget",
                    "Outro paragraph.",
                    "Book Metadata Title",
                    "Book description.",
                    "NCX Book Title",
                    "NCX Chapter One",
                    "Contents",
                    "Chapter 1",
                    "Chapter 2",
                    "Chapter Metadata Title",
                ],
            )
            self.assertEqual(
                [unit.source_block_ids for unit in persisted_units],
                [
                    ("epub:OPS/chapter.xhtml:0",),
                    ("epub:OPS/chapter.xhtml:1", "epub:OPS/chapter.xhtml:2"),
                    ("epub:OPS/chapter.xhtml:3",),
                    ("epub:aux:opf:OPS/content.opf:title:0",),
                    ("epub:aux:opf:OPS/content.opf:description:0",),
                    ("epub:aux:ncx:OPS/toc.ncx:text:0",),
                    ("epub:aux:ncx:OPS/toc.ncx:text:1",),
                    ("epub:aux:xhtml-navigation:OPS/front.xhtml:h1:0",),
                    ("epub:aux:xhtml-navigation:OPS/front.xhtml:p:0",),
                    ("epub:aux:xhtml-navigation:OPS/front.xhtml:p:1",),
                    ("epub:aux:xhtml-title:OPS/chapter.xhtml:title:0",),
                ],
            )
            self.assertEqual(
                persisted_units[1].source_block_ids,
                ("epub:OPS/chapter.xhtml:1", "epub:OPS/chapter.xhtml:2"),
            )
            self.assertEqual(persisted_units[1].prompt_tier, "strict")
            self.assertEqual(
                persisted_units[1].source_text_hash,
                sha256("Source\n\nTarget".encode("utf-8")).hexdigest(),
            )
            self.assertTrue(
                all(
                    "OPS/front.xhtml" not in block_id
                    for unit in persisted_units
                    for block_id in unit.source_block_ids
                    if not block_id.startswith("epub:aux:")
                )
            )
            self.assertEqual(plan.work_units, persisted_units)

    def test_epub_book_manuscript_mode_persists_format_neutral_profile(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="novel.epub",
                content_type="application/epub+zip",
                content=_make_epub(
                    {
                        "OPS/chapter.xhtml": """
                        <html xmlns="http://www.w3.org/1999/xhtml">
                          <body>
                            <p>Quiet chapter opening.</p>
                            <p>The narrator kept the same voice.</p>
                          </body>
                        </html>
                        """,
                    },
                ),
            )

            plan = create_persistent_epub_job_plan(
                store=store,
                storage=storage,
                order_id="order-epub-book",
                user_id="user-42",
                source_object_key=original.object_key,
                file_name="novel.epub",
                source_language="en",
                target_language="uk",
                max_fragment_chars=1_000,
                translation_mode=TRANSLATION_MODE_BOOK_MANUSCRIPT,
            )

            persisted_job = store.get_job(plan.job.id)
            translation_policy = json.loads(persisted_job.translation_policy)

            self.assertEqual(
                translation_policy["translation_mode"],
                TRANSLATION_MODE_BOOK_MANUSCRIPT,
            )
            self.assertEqual(
                translation_policy["translation_mode_profile"],
                BOOK_MANUSCRIPT_TRANSLATION_MODE_PROFILE,
            )
            self.assertIn(
                "narrator, speaker, and character continuity",
                translation_policy["translation_context_memory"]["style_summary"],
            )


class _UnsupportedPersistentJobStore:
    def __init__(self) -> None:
        self.create_job_calls = 0
        self.add_work_units_calls = 0

    def close(self) -> None:
        pass

    def create_job(self, **kwargs):
        self.create_job_calls += 1
        raise AssertionError("strict admission must not use legacy create_job")

    def get_job(self, job_id: str):
        raise AssertionError("strict admission must not read legacy jobs")

    def add_work_units(self, job_id: str, work_units):
        self.add_work_units_calls += 1
        raise AssertionError("strict admission must not add legacy work units")

    def list_work_units(self, job_id: str):
        raise AssertionError("strict admission must not list legacy work units")

    def list_recent_work_units(self, job_id: str, *, limit: int):
        raise AssertionError("strict admission must not list legacy work units")

    def list_jobs_by_status(self, status, *, limit: int = 50):
        raise AssertionError("strict admission must not list legacy jobs")

    def list_jobs_for_user(self, user_id: str, *, limit: int = 10):
        raise AssertionError("strict admission must not list legacy jobs")

    def cancel_job(self, job_id: str):
        raise AssertionError("strict admission must not modify legacy jobs")

    def request_cancel_job(self, job_id: str):
        raise AssertionError("strict admission must not modify legacy jobs")

    def pause_job(self, job_id: str):
        raise AssertionError("strict admission must not modify legacy jobs")

    def resume_job(self, job_id: str):
        raise AssertionError("strict admission must not modify legacy jobs")

    def delete_job(self, job_id: str):
        raise AssertionError("strict admission must not modify legacy jobs")

    def mark_job_interrupted(self, job_id: str):
        raise AssertionError("strict admission must not modify legacy jobs")

    def mark_job_failed(self, job_id: str):
        raise AssertionError("strict admission must not modify legacy jobs")

    def get_usage_summary(self, job_id: str):
        raise AssertionError("strict admission must not read legacy usage")


if __name__ == "__main__":
    unittest.main()


def _make_docx(document_xml: str) -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr("word/document.xml", document_xml)
    return archive.getvalue()


def _make_epub(
    xhtml_items: dict[str, str],
    *,
    opf_content: str | None = None,
    ncx_content: str | None = None,
) -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        if opf_content is None:
            epub.writestr("META-INF/container.xml", "<container />")
        else:
            epub.writestr(
                "META-INF/container.xml",
                """
                <container>
                  <rootfiles>
                    <rootfile full-path="OPS/content.opf" />
                  </rootfiles>
                </container>
                """,
            )
            epub.writestr("OPS/content.opf", opf_content)
        if ncx_content is not None:
            epub.writestr("OPS/toc.ncx", ncx_content)
        for file_name, content in xhtml_items.items():
            epub.writestr(file_name, content)
    return archive.getvalue()
