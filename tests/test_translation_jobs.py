import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.beta_safety import BETA_SAFETY_ALLOWED, BetaSafetyDecision
from translator_service.bot_translation_service import BotTranslationService
from translator_service.file_storage import LocalObjectStorage
from translator_service.job_runner import (
    InMemoryTranslationJobRepository,
    TranslationJobStatus,
)
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    SQLiteTranslationJobStore,
)
from translator_service.pricing import PricingRules
from translator_service.translation_jobs import (
    CancellationToken,
    FragmentTranslation,
    TranslationCancelled,
    TranslationJobResult,
    TranslationProgress,
    translate_text_fragments,
)


class RecordingTranslator:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, str]] = []
        self.last_usage = None

    def translate(
        self, *, text: str, source_language: str, target_language: str
    ) -> str:
        self.requests.append((text, source_language, target_language))
        return f"[{target_language}] {text}"


class TokenReportingTranslator:
    def __init__(self) -> None:
        self.last_usage = None

    def translate(
        self, *, text: str, source_language: str, target_language: str
    ) -> str:
        self.last_usage = _Usage(prompt_tokens=7, completion_tokens=5, total_tokens=12)
        return f"[{target_language}] {text}"


class CancellationRequestingTranslator(RecordingTranslator):
    def __init__(self, service: BotTranslationService, user_telegram_id: int) -> None:
        super().__init__()
        self._service = service
        self._user_telegram_id = user_telegram_id

    def translate(
        self, *, text: str, source_language: str, target_language: str
    ) -> str:
        translated = super().translate(
            text=text,
            source_language=source_language,
            target_language=target_language,
        )
        if len(self.requests) == 1:
            self._service.cancel_translation(self._user_telegram_id)
        return translated


class RecordingBetaSafetyGuard:
    def __init__(self) -> None:
        self.releases: list[tuple[str, str]] = []

    def can_start_new_work(self) -> BetaSafetyDecision:
        return BetaSafetyDecision(
            allowed=True,
            reason_code=BETA_SAFETY_ALLOWED,
            safe_message="allowed",
        )

    def reserve_job(self, **kwargs) -> BetaSafetyDecision:
        return self.can_start_new_work()

    def release_job(self, *, job_id: str, reason: str) -> None:
        self.releases.append((job_id, reason))

    def mark_job_consumed(self, *, job_id: str) -> None:
        pass

    def record_work_unit_usage(self, **kwargs) -> None:
        pass


class _Usage:
    def __init__(
        self, *, prompt_tokens: int, completion_tokens: int, total_tokens: int
    ) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens


class TranslationJobsTest(unittest.TestCase):
    def test_translates_fragments_in_order_and_assembles_text(self):
        translator = RecordingTranslator()

        result = translate_text_fragments(
            fragments=["Первый абзац.", "Второй абзац."],
            source_language="ru",
            target_language="en",
            translator=translator,
        )

        self.assertEqual(
            result,
            TranslationJobResult(
                fragments=[
                    FragmentTranslation(
                        index=0,
                        source_text="Первый абзац.",
                        translated_text="[en] Первый абзац.",
                    ),
                    FragmentTranslation(
                        index=1,
                        source_text="Второй абзац.",
                        translated_text="[en] Второй абзац.",
                    ),
                ],
                assembled_text="[en] Первый абзац.\n\n[en] Второй абзац.",
            ),
        )
        self.assertEqual(
            translator.requests,
            [
                ("Первый абзац.", "ru", "en"),
                ("Второй абзац.", "ru", "en"),
            ],
        )

    def test_skips_blank_fragments(self):
        translator = RecordingTranslator()

        result = translate_text_fragments(
            fragments=["Первый абзац.", "   ", "Второй абзац."],
            source_language="ru",
            target_language="en",
            translator=translator,
        )

        self.assertEqual(len(result.fragments), 2)
        self.assertEqual(
            result.assembled_text,
            "[en] Первый абзац.\n\n[en] Второй абзац.",
        )

    def test_reports_progress_after_each_translated_fragment(self):
        progress_updates: list[tuple[int, int]] = []

        translate_text_fragments(
            fragments=["One", "Two", "Three"],
            source_language="en",
            target_language="uk",
            translator=RecordingTranslator(),
            progress_callback=progress_updates.append,
        )

        self.assertEqual(progress_updates, [(1, 3), (2, 3), (3, 3)])

    def test_reports_last_translated_fragment_and_token_usage_in_progress(self):
        progress_updates: list[TranslationProgress] = []

        translate_text_fragments(
            fragments=["One"],
            source_language="en",
            target_language="uk",
            translator=TokenReportingTranslator(),
            progress_callback=progress_updates.append,
        )

        self.assertEqual(len(progress_updates), 1)
        self.assertEqual(progress_updates[0].completed_fragments, 1)
        self.assertEqual(progress_updates[0].total_fragments, 1)
        self.assertEqual(progress_updates[0].source_text, "One")
        self.assertEqual(progress_updates[0].translated_text, "[uk] One")
        self.assertGreaterEqual(progress_updates[0].elapsed_seconds, 0)
        self.assertEqual(progress_updates[0].prompt_tokens, 7)
        self.assertEqual(progress_updates[0].completion_tokens, 5)
        self.assertEqual(progress_updates[0].total_tokens, 12)
        self.assertTrue(progress_updates[0].success)

    def test_stops_before_next_fragment_when_cancellation_is_requested(self):
        token = CancellationToken()

        def cancel_after_first(progress: tuple[int, int]) -> None:
            if progress == (1, 3):
                token.cancel()

        with self.assertRaises(TranslationCancelled) as error:
            translate_text_fragments(
                fragments=["One", "Two", "Three"],
                source_language="en",
                target_language="uk",
                translator=RecordingTranslator(),
                progress_callback=cancel_after_first,
                cancellation_token=token,
            )

        self.assertEqual(
            error.exception.partial_result,
            TranslationJobResult(
                fragments=[
                    FragmentTranslation(
                        index=0,
                        source_text="One",
                        translated_text="[uk] One",
                    )
                ],
                assembled_text="[uk] One",
            ),
        )

    def test_cancelled_persistent_job_releases_beta_reservation(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            guard = RecordingBetaSafetyGuard()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
                beta_safety_guard=guard,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One.\nTwo.\n",
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=CancellationRequestingTranslator(service, 42),
            )

            persisted_job = persistent_store.get_job(job.id)
            self.assertEqual(job.status, TranslationJobStatus.CANCELLED)
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.CANCELLED,
            )
            self.assertEqual(guard.releases, [(job.id, "cancelled")])

    def test_preserves_protected_tokens_in_plain_text_fragments(self):
        class TokenBreakingTranslator:
            def translate(
                self, *, text: str, source_language: str, target_language: str
            ) -> str:
                return (
                    text.replace("ROW-001", "СТРОКА-001")
                    .replace("ID", "Идентификатор")
                    .replace("inline_code", "встроенный_код")
                    .replace("{{PLACEHOLDER}}", "{{ЗАПОЛНИТЕЛЬ}}")
                    .replace("https://example.com/a", "https://example.ru/a")
                )

        result = translate_text_fragments(
            fragments=[
                "ID ROW-001 uses inline_code with {{PLACEHOLDER}} at https://example.com/a."
            ],
            source_language="auto",
            target_language="ru",
            translator=TokenBreakingTranslator(),
        )

        self.assertIn("ROW-001", result.assembled_text)
        self.assertIn("ID", result.assembled_text)
        self.assertIn("inline_code", result.assembled_text)
        self.assertIn("{{PLACEHOLDER}}", result.assembled_text)
        self.assertIn("https://example.com/a", result.assembled_text)
        self.assertNotIn("СТРОКА-001", result.assembled_text)
        self.assertNotIn("Идентификатор", result.assembled_text)
        self.assertNotIn("встроенный_код", result.assembled_text)

    def test_preserves_structured_data_keys_in_plain_text_fragments(self):
        class StructuredDataBreakingTranslator:
            def translate(
                self, *, text: str, source_language: str, target_language: str
            ) -> str:
                return (
                    text.replace('"price":', '"цена":')
                    .replace('"enabled":', '"включено":')
                    .replace("12.50", "12,50")
                    .replace("true", "истина")
                    .replace("provider:", "провайдер:")
                    .replace("timeout:", "тайм-аут:")
                )

        result = translate_text_fragments(
            fragments=[
                '"price": 12.50,\n"enabled": true\nprovider: deepseek\ntimeout: 120'
            ],
            source_language="auto",
            target_language="ru",
            translator=StructuredDataBreakingTranslator(),
        )

        self.assertIn('"price":', result.assembled_text)
        self.assertIn("12.50", result.assembled_text)
        self.assertIn('"enabled":', result.assembled_text)
        self.assertIn("true", result.assembled_text)
        self.assertIn("provider:", result.assembled_text)
        self.assertIn("timeout:", result.assembled_text)
        self.assertNotIn('"цена":', result.assembled_text)
        self.assertNotIn('"включено":', result.assembled_text)
        self.assertNotIn("12,50", result.assembled_text)
        self.assertNotIn("истина", result.assembled_text)
        self.assertNotIn("провайдер:", result.assembled_text)
        self.assertNotIn("тайм-аут:", result.assembled_text)

    def test_preserves_inline_json_literals_in_plain_text_fragments(self):
        class InlineJsonBreakingTranslator:
            def translate(
                self, *, text: str, source_language: str, target_language: str
            ) -> str:
                return (
                    text.replace('"keep":"keys"', '"keep":"ключи"')
                    .replace(
                        '"translate":"values maybe"',
                        '"translate":"возможные значения"',
                    )
                )

        result = translate_text_fragments(
            fragments=['{"keep":"keys", "translate":"values maybe"}'],
            source_language="auto",
            target_language="ru",
            translator=InlineJsonBreakingTranslator(),
        )

        self.assertEqual(
            result.assembled_text,
            '{"keep":"keys", "translate":"values maybe"}',
        )

    def test_preserves_special_spacing_characters_in_plain_text_fragments(self):
        class SpacingBreakingTranslator:
            def translate(
                self, *, text: str, source_language: str, target_language: str
            ) -> str:
                return (
                    text.replace("\u00a0", " ")
                    .replace("\u00ad", " ")
                    .replace("  ", " ")
                )

        result = translate_text_fragments(
            fragments=[
                "10\u00a0000\u00a0€, Mr.\u00a0Smith, "
                "здесь  после, микро\u00adсервис"
            ],
            source_language="auto",
            target_language="ru",
            translator=SpacingBreakingTranslator(),
        )

        self.assertEqual(
            result.assembled_text,
            "10\u00a0000\u00a0€, Mr.\u00a0Smith, здесь  после, микро\u00adсервис",
        )

    def test_preserves_short_proper_name_values_in_structured_data(self):
        class NameBreakingTranslator:
            def translate(
                self, *, text: str, source_language: str, target_language: str
            ) -> str:
                return text.replace('"Sergey"', '"Сергей"')

        result = translate_text_fragments(
            fragments=['"user_name": "Sergey",\n"city": "Zwolle"'],
            source_language="auto",
            target_language="ru",
            translator=NameBreakingTranslator(),
        )

        self.assertIn('"Sergey"', result.assembled_text)
        self.assertIn('"Zwolle"', result.assembled_text)
        self.assertNotIn('"Сергей"', result.assembled_text)

    def test_preserves_configured_technical_terms_in_plain_text_fragments(self):
        class TermBreakingTranslator:
            def translate(
                self, *, text: str, source_language: str, target_language: str
            ) -> str:
                return (
                    text.replace("tracked changes", "отслеживаемые изменения")
                    .replace("query-параметры", "параметры запроса")
                    .replace("regex", "регулярное выражение")
                    .replace("placeholders", "заполнители")
                )

        result = translate_text_fragments(
            fragments=[
                "Keep tracked changes, query-параметры, regex, and placeholders."
            ],
            source_language="auto",
            target_language="ru",
            translator=TermBreakingTranslator(),
        )

        self.assertIn("tracked changes", result.assembled_text)
        self.assertIn("query-параметры", result.assembled_text)
        self.assertIn("regex", result.assembled_text)
        self.assertIn("placeholders", result.assembled_text)
        self.assertNotIn("отслеживаемые изменения", result.assembled_text)
        self.assertNotIn("параметры запроса", result.assembled_text)
        self.assertNotIn("регулярное выражение", result.assembled_text)
        self.assertNotIn("заполнители", result.assembled_text)


def _pricing_rules() -> PricingRules:
    return PricingRules(
        deepseek_input_usd_per_million_tokens=0.28,
        expected_output_multiplier=1.2,
        service_markup_multiplier=3.0,
        minimum_price_usd=0.10,
    )


if __name__ == "__main__":
    unittest.main()
