import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.bot_translation_service import (
    BotTranslationService,
    PendingTranslation,
    PendingUpload,
)
from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.job_runner import (
    DocumentKind,
    InMemoryTranslationJobRepository,
    TranslationJobStatus,
)
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    PersistentWorkUnitStatus,
    SQLiteTranslationJobStore,
)
from translator_service.pricing import PricingRules


class RecordingTranslator:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, str]] = []

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        self.requests.append((text, source_language, target_language))
        return f"[{target_language}] {text}"


class FailingTranslator:
    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        raise RuntimeError("network failed")


class CancellingTranslator:
    def __init__(self, service: BotTranslationService, user_telegram_id: int) -> None:
        self._service = service
        self._user_telegram_id = user_telegram_id
        self.requests: list[str] = []

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        self.requests.append(text)
        if len(self.requests) == 1:
            self._service.cancel_translation(self._user_telegram_id)
        return f"[{target_language}] {text}"


class BlockingTranslator:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        self.requests.append(text)
        time.sleep(0.05)
        return f"[{target_language}] {text}"


class BotTranslationServiceTest(unittest.TestCase):
    def test_rejects_unknown_translation_execution_mode(self):
        with self.assertRaisesRegex(ValueError, "translation_execution_mode"):
            BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                translation_execution_mode="wroker",
            )

    def test_prepares_txt_estimate_for_uploaded_document(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )

        pending = service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content="Первый абзац.\n\nВторой абзац.".encode("utf-8"),
            source_language="ru",
            target_language="en",
        )

        self.assertEqual(
            pending,
            PendingTranslation(
                user_telegram_id=42,
                file_name="notes.txt",
                content="Первый абзац.\n\nВторой абзац.".encode("utf-8"),
                source_language="ru",
                target_language="en",
                price_usd=0.10,
                fragment_count=2,
                source_language_display="ru",
                estimated_seconds=24,
            ),
        )
        self.assertEqual(service.get_pending(42), pending)

    def test_stores_selected_interface_language_per_user(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )

        service.set_interface_language(user_telegram_id=42, language_code="uk")

        self.assertEqual(service.get_interface_language(42), "uk")
        self.assertEqual(service.get_interface_language(100), "en")

    def test_stores_progress_preview_preference_per_user(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )

        self.assertTrue(service.get_progress_preview_enabled(42))

        service.set_progress_preview_enabled(
            user_telegram_id=42,
            enabled=False,
        )

        self.assertFalse(service.get_progress_preview_enabled(42))
        self.assertTrue(service.get_progress_preview_enabled(100))

    def test_upload_waits_for_translation_language_before_estimate(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )

        upload = service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"This is an English document.",
            source_language="auto",
        )

        self.assertEqual(
            upload,
            PendingUpload(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"This is an English document.",
                source_language="auto",
                source_language_display="auto (English)",
            ),
        )
        self.assertEqual(service.get_pending_upload(42), upload)

    def test_upload_can_be_persisted_to_object_storage_before_estimate(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                file_storage=storage,
            )

            upload = service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"This is an English document.",
                source_language="auto",
            )
            pending = service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )

            self.assertIsNotNone(upload.source_object_key)
            self.assertEqual(upload.source_object_key, pending.source_object_key)
            self.assertEqual(storage.get_bytes(upload.source_object_key), upload.content)
            self.assertEqual(
                storage.get_metadata(upload.source_object_key).kind,
                StoredFileKind.ORIGINAL,
            )

    def test_auto_language_display_lists_mixed_document_languages(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=200,
        )

        upload = service.store_uploaded_document(
            user_telegram_id=42,
            file_name="mixed.txt",
            content=(
                "Русский текст документа.\n"
                "English: The quick brown fox jumps over the lazy dog.\n"
                "Polski: Zażółć gęślą jaźń.\n"
                "Nederlands: Ik fiets vandaag naar Zwolle."
            ).encode("utf-8"),
            source_language="auto",
        )

        self.assertEqual(
            upload.source_language_display,
            "auto (mixed: Russian, English, Polish, Dutch)",
        )

    def test_prepares_estimate_from_pending_upload_after_translation_language_choice(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"This is an English document.",
            source_language="auto",
        )

        pending = service.prepare_pending_upload(
            user_telegram_id=42,
            target_language="uk",
        )

        self.assertEqual(pending.target_language, "uk")
        self.assertEqual(pending.source_language_display, "auto (English)")
        self.assertIsNone(service.get_pending_upload(42))
        self.assertEqual(service.get_pending(42), pending)

    def test_confirms_pending_txt_translation_and_runs_job(self):
        repository = InMemoryTranslationJobRepository()
        service = BotTranslationService(
            job_repository=repository,
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.\n\nTwo.",
            source_language="en",
            target_language="uk",
        )

        job = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=RecordingTranslator(),
        )

        self.assertEqual(job.status, TranslationJobStatus.READY)
        self.assertEqual(job.result_file_name, "notes.uk.txt")
        self.assertEqual(job.result_content.decode("utf-8"), "[uk] One.\n\n[uk] Two.")
        self.assertIsNone(service.get_pending(42))

    def test_persistent_txt_confirmation_uses_stored_work_units(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One.\n\nTwo.",
                source_language="en",
            )
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

            persisted_job = persistent_store.get_job(job.id)
            work_units = persistent_store.list_work_units(job.id)
            self.assertEqual(job.status, TranslationJobStatus.READY)
            self.assertEqual(job.result_file_name, "notes.uk.txt")
            self.assertEqual(
                job.result_content.decode("utf-8"),
                "[uk] One.\n\n[uk] Two.",
            )
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.READY,
            )
            self.assertIsNotNone(persisted_job.final_object_key)
            self.assertEqual(
                storage.get_bytes(persisted_job.final_object_key),
                job.result_content,
            )
            self.assertEqual(
                [unit.status for unit in work_units],
                [
                    PersistentWorkUnitStatus.TRANSLATED,
                    PersistentWorkUnitStatus.TRANSLATED,
                ],
            )

    def test_worker_mode_confirmation_queues_persistent_txt_without_inline_translation(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_execution_mode="worker",
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One.\n\nTwo.",
                source_language="en",
            )
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            translator = RecordingTranslator()

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

            persisted_job = persistent_store.get_job(job.id)
            work_units = persistent_store.list_work_units(job.id)
            self.assertEqual(job.status, TranslationJobStatus.QUEUED)
            self.assertIsNone(job.result_file_name)
            self.assertIsNone(job.result_content)
            self.assertIsNone(service.get_pending(42))
            self.assertEqual(translator.requests, [])
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.QUEUED,
            )
            self.assertEqual(
                [unit.status for unit in work_units],
                [
                    PersistentWorkUnitStatus.PENDING,
                    PersistentWorkUnitStatus.PENDING,
                ],
            )

    def test_worker_mode_rejects_non_persistent_path_without_inline_translation(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_execution_mode="worker",
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="contract.docx",
                content=_make_docx(
                    """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body>
                    </w:document>
                    """
                ),
                source_language="en",
            )
            pending = service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="fr",
            )
            translator = RecordingTranslator()

            with self.assertRaisesRegex(ValueError, "Worker mode currently supports"):
                service.confirm_pending_translation(
                    user_telegram_id=42,
                    translator=translator,
                )

            self.assertEqual(service.get_pending(42), pending)
            self.assertEqual(translator.requests, [])

    def test_persistent_txt_cancellation_returns_partial_result(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One.\n\nTwo.",
                source_language="en",
            )
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=CancellingTranslator(service, 42),
            )

            persisted_job = persistent_store.get_job(job.id)
            self.assertEqual(job.status, TranslationJobStatus.CANCELLED)
            self.assertEqual(job.result_file_name, "notes.uk.partial.txt")
            self.assertEqual(job.result_content.decode("utf-8"), "[uk] One.")
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.CANCELLED,
            )
            self.assertIsNotNone(persisted_job.partial_object_key)
            self.assertEqual(
                storage.get_bytes(persisted_job.partial_object_key),
                job.result_content,
            )

    def test_concurrent_confirm_claims_pending_translation_once(self):
        repository = InMemoryTranslationJobRepository()
        service = BotTranslationService(
            job_repository=repository,
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.",
            source_language="en",
            target_language="uk",
        )
        translator = BlockingTranslator()

        def confirm():
            return service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(confirm), pool.submit(confirm)]
            results = []
            errors = []
            for future in futures:
                try:
                    results.append(future.result(timeout=5))
                except ValueError as error:
                    errors.append(str(error))

        self.assertEqual([job.id for job in results], ["job-1"])
        self.assertEqual(errors, ["No pending translation for this user"])
        self.assertEqual(len(translator.requests), 1)

    def test_failed_translation_returns_failed_job_and_keeps_pending_retry(self):
        repository = InMemoryTranslationJobRepository()
        service = BotTranslationService(
            job_repository=repository,
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
        )
        pending = service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.",
            source_language="en",
            target_language="uk",
        )

        with self.assertLogs("translator_service.bot_translation_service", level="ERROR") as logs:
            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=FailingTranslator(),
            )

        self.assertEqual(job.status, TranslationJobStatus.FAILED)
        self.assertEqual(job.error_message, "network failed")
        self.assertEqual(service.get_pending(42), pending)
        self.assertIn("Translation job failed", logs.output[0])
        self.assertIn("notes.txt", logs.output[0])
        self.assertIn("job-1", logs.output[0])

    def test_cancel_translation_requests_active_job_cancellation(self):
        repository = InMemoryTranslationJobRepository()
        service = BotTranslationService(
            job_repository=repository,
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.\n\nTwo.",
            source_language="en",
            target_language="uk",
        )

        job = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=CancellingTranslator(service, 42),
        )

        self.assertEqual(job.status, TranslationJobStatus.CANCELLED)
        self.assertEqual(job.result_file_name, "notes.uk.partial.txt")
        self.assertEqual(job.result_content.decode("utf-8"), "[uk] One.")
        self.assertIsNone(service.get_pending(42))

    def test_cancel_translation_returns_false_without_active_job(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
        )

        self.assertFalse(service.cancel_translation(42))

    def test_discard_pending_translation_clears_unconfirmed_order(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"Some text",
            source_language="en",
            target_language="uk",
        )

        self.assertTrue(service.discard_pending_translation(42))
        self.assertIsNone(service.get_pending(42))
        self.assertFalse(service.discard_pending_translation(42))

    def test_confirm_without_pending_translation_is_rejected(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )

        with self.assertRaises(ValueError):
            service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

    def test_bot_prototype_rejects_pdf_before_confirmation(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )

        with self.assertRaises(ValueError) as error:
            service.prepare_document(
                user_telegram_id=42,
                file_name="scan.pdf",
                content=b"%PDF-1.4 fake",
                source_language="en",
                target_language="uk",
            )

        self.assertIn("TXT, DOCX, and EPUB", str(error.exception))

    def test_accepts_docx_upload_and_runs_docx_translation(self):
        repository = InMemoryTranslationJobRepository()
        service = BotTranslationService(
            job_repository=repository,
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="contract.docx",
            content=_make_docx(
                """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body>
                </w:document>
                """
            ),
            source_language="en",
        )
        service.prepare_pending_upload(user_telegram_id=42, target_language="fr")

        job = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=RecordingTranslator(),
        )

        self.assertEqual(job.document_kind, DocumentKind.DOCX)
        self.assertEqual(job.result_file_name, "contract.fr.docx")

    def test_docx_translation_memory_is_used_through_bot_service(self):
        repository = InMemoryTranslationJobRepository()
        service = BotTranslationService(
            job_repository=repository,
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        translator = RecordingTranslator()
        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Repeated sentence.</w:t></w:r></w:p></w:body>
            </w:document>
            """
        )

        service.prepare_document(
            user_telegram_id=42,
            file_name="first.docx",
            content=content,
            source_language="en",
            target_language="uk",
        )
        first_job = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=translator,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="second.docx",
            content=content,
            source_language="en",
            target_language="uk",
        )
        second_job = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=translator,
        )

        self.assertEqual(first_job.status, TranslationJobStatus.READY)
        self.assertEqual(second_job.status, TranslationJobStatus.READY)
        self.assertEqual(len(translator.requests), 1)

    def test_accepts_epub_upload_and_runs_epub_translation(self):
        repository = InMemoryTranslationJobRepository()
        service = BotTranslationService(
            job_repository=repository,
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="book.epub",
            content=_make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body><p>Hello book</p></body>
                    </html>
                    """
                }
            ),
            source_language="en",
        )
        service.prepare_pending_upload(user_telegram_id=42, target_language="es")

        job = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=RecordingTranslator(),
        )

        self.assertEqual(job.document_kind, DocumentKind.EPUB)
        self.assertEqual(job.result_file_name, "book.es.epub")

    def test_epub_translation_memory_is_used_through_bot_service(self):
        repository = InMemoryTranslationJobRepository()
        service = BotTranslationService(
            job_repository=repository,
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=200,
        )
        translator = RecordingTranslator()
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>Repeated book sentence.</p></body>
                </html>
                """
            }
        )

        service.prepare_document(
            user_telegram_id=42,
            file_name="first.epub",
            content=content,
            source_language="en",
            target_language="uk",
        )
        first_job = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=translator,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="second.epub",
            content=content,
            source_language="en",
            target_language="uk",
        )
        second_job = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=translator,
        )

        self.assertEqual(first_job.status, TranslationJobStatus.READY)
        self.assertEqual(second_job.status, TranslationJobStatus.READY)
        self.assertEqual(len(translator.requests), 1)


def _pricing_rules() -> PricingRules:
    return PricingRules(
        deepseek_input_usd_per_million_tokens=0.28,
        expected_output_multiplier=1.2,
        service_markup_multiplier=3.0,
        minimum_price_usd=0.10,
    )


if __name__ == "__main__":
    unittest.main()


def _make_docx(document_xml: str) -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr("word/document.xml", document_xml)
    return archive.getvalue()


def _make_epub(xhtml_items: dict[str, str]) -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr("META-INF/container.xml", "<container />")
        for file_name, content in xhtml_items.items():
            epub.writestr(file_name, content)
    return archive.getvalue()
