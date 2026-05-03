import unittest

from translator_service.bot_translation_service import (
    BotTranslationService,
    PendingTranslation,
)
from translator_service.job_runner import InMemoryTranslationJobRepository, TranslationJobStatus
from translator_service.pricing import PricingRules


class RecordingTranslator:
    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
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
            ),
        )
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


def _pricing_rules() -> PricingRules:
    return PricingRules(
        deepseek_input_usd_per_million_tokens=0.28,
        expected_output_multiplier=1.2,
        service_markup_multiplier=3.0,
        minimum_price_usd=0.10,
    )


if __name__ == "__main__":
    unittest.main()
