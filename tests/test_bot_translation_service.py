import unittest

from translator_service.bot_translation_service import (
    BotTranslationService,
    PendingUpload,
    PendingTranslation,
)
from translator_service.job_runner import DocumentKind
from translator_service.job_runner import InMemoryTranslationJobRepository, TranslationJobStatus
from translator_service.pricing import PricingRules


class RecordingTranslator:
    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
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


class BotTranslationServiceTest(unittest.TestCase):
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
        self.assertEqual(service.get_interface_language(100), "ru")

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
