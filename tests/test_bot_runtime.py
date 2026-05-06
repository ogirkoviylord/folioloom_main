import asyncio
from datetime import datetime
import io
import unittest
from contextlib import redirect_stdout

from translator_service.bot_translation_service import PendingTranslation
import translator_service.bot.runtime as runtime
from translator_service.bot.runtime import (
    BotRuntimeConfig,
    _cancel_inline_keyboard,
    _document_exceeds_upload_limit,
    _is_language_button_text,
    _main_menu_keyboard,
    _next_spinner_frame,
    _print_translation_progress,
    _print_translation_summary,
    _schedule_message_edit,
    build_default_pricing_rules,
)
from translator_service.translation_jobs import TranslationProgress


class TelegramMethodLikeAwaitable:
    def __init__(self, callback):
        self._callback = callback

    def __await__(self):
        async def run():
            self._callback()

        return run().__await__()


class EditableMessage:
    def __init__(self) -> None:
        self.edited_texts: list[str] = []

    def edit_text(self, text: str):
        return TelegramMethodLikeAwaitable(lambda: self.edited_texts.append(text))


class RecordingBot:
    def __init__(self) -> None:
        self.edits: list[tuple[str, int, int, object]] = []

    async def edit_message_text(
        self,
        *,
        text: str,
        chat_id: int,
        message_id: int,
        reply_markup=None,
    ) -> None:
        self.edits.append((text, chat_id, message_id, reply_markup))


class Chat:
    id = 100


class BotBackedMessage:
    def __init__(self) -> None:
        self.bot = RecordingBot()
        self.chat = Chat()
        self.message_id = 55


class BotRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def test_default_pricing_rules_match_mvp_tariff(self):
        rules = build_default_pricing_rules()

        self.assertEqual(rules.deepseek_input_usd_per_million_tokens, 0.28)
        self.assertEqual(rules.expected_output_multiplier, 1.2)
        self.assertEqual(rules.service_markup_multiplier, 3.0)
        self.assertEqual(rules.minimum_price_usd, 0.10)

    def test_runtime_config_has_safe_prototype_defaults(self):
        config = BotRuntimeConfig()

        self.assertEqual(config.source_language, "auto")
        self.assertEqual(config.target_language, "en")
        self.assertEqual(config.max_fragment_chars, 4_000)
        self.assertEqual(config.max_upload_mb, 50)

    def test_language_button_filter_ignores_missing_message_text(self):
        self.assertFalse(_is_language_button_text(None))

    async def test_schedules_message_edit_for_aiogram_method_awaitable(self):
        message = EditableMessage()
        loop = asyncio.get_running_loop()

        future = _schedule_message_edit(
            loop=loop,
            message=message,
            text="Progress",
        )

        await asyncio.wrap_future(future)
        self.assertEqual(message.edited_texts, ["Progress"])

    async def test_schedules_message_edit_through_bot_api_when_message_has_context(self):
        message = BotBackedMessage()
        loop = asyncio.get_running_loop()

        future = _schedule_message_edit(
            loop=loop,
            message=message,
            text="Progress 2",
            reply_markup="inline-keyboard",
        )

        await asyncio.wrap_future(future)
        self.assertEqual(message.bot.edits, [("Progress 2", 100, 55, "inline-keyboard")])

    def test_cancel_inline_keyboard_uses_callback_data(self):
        keyboard = _cancel_inline_keyboard("en")

        button = keyboard.inline_keyboard[0][0]
        self.assertEqual(button.text, "Cancel")
        self.assertEqual(button.callback_data, "cancel_translation")

    def test_main_menu_keyboard_uses_folioloom_buttons(self):
        keyboard = _main_menu_keyboard("en")

        self.assertEqual(
            [[button.text for button in row] for row in keyboard.keyboard],
            [
                ["📖 Translate a Book"],
                ["🧵 How It Works", "🌍 Language"],
                ["Help"],
            ],
        )

    def test_document_size_guard_uses_telegram_metadata_before_download(self):
        class Document:
            file_size = 6 * 1024 * 1024

        self.assertTrue(_document_exceeds_upload_limit(Document(), max_upload_mb=5))
        self.assertFalse(_document_exceeds_upload_limit(Document(), max_upload_mb=6))

    def test_translation_progress_log_does_not_include_user_text(self):
        output = io.StringIO()

        with redirect_stdout(output):
            _print_translation_progress(
                progress=TranslationProgress(
                    completed_fragments=1,
                    total_fragments=2,
                    source_text="private source text",
                    translated_text="private translated text",
                    elapsed_seconds=1.25,
                    total_tokens=9,
                ),
                elapsed_total_seconds=2,
            )

        self.assertNotIn("private source text", output.getvalue())
        self.assertNotIn("private translated text", output.getvalue())
        self.assertIn("tokens=9", output.getvalue())

    def test_translation_start_log_is_blue_and_contains_pending_metadata(self):
        output = io.StringIO()
        if not hasattr(runtime, "_print_translation_start"):
            self.fail("_print_translation_start is not implemented")

        with redirect_stdout(output):
            runtime._print_translation_start(
                PendingTranslation(
                    user_telegram_id=42,
                    file_name="book.epub",
                    content=b"book content",
                    source_language="auto",
                    target_language="ru",
                    price_usd=0.25,
                    fragment_count=4,
                    source_language_display="auto (English)",
                    estimated_seconds=48,
                    character_count=1200,
                    estimated_input_tokens=450,
                    estimated_output_tokens=540,
                    document_format="epub",
                ),
                started_at=datetime(2026, 5, 6, 12, 30, 5),
            )

        text = output.getvalue()
        self.assertIn("\033[94m", text)
        self.assertIn("\033[0m", text)
        self.assertIn("TRANSLATION STARTED", text)
        self.assertIn("started_at=2026-05-06T12:30:05", text)
        self.assertIn("file=book.epub", text)
        self.assertIn("type=epub", text)
        self.assertIn("size_bytes=12", text)
        self.assertIn("characters=1200", text)
        self.assertIn("source=auto (English)", text)
        self.assertIn("target=ru", text)
        self.assertIn("fragments=4", text)
        self.assertIn("estimated_time=48s", text)
        self.assertIn("price=$0.25", text)
        self.assertIn("input_tokens=450", text)
        self.assertIn("output_tokens=540", text)

    def test_spinner_frame_cycles(self):
        self.assertEqual(_next_spinner_frame(-1), "⠋")
        self.assertEqual(_next_spinner_frame(0), "⠙")
        self.assertEqual(_next_spinner_frame(9), "⠋")

    def test_success_translation_summary_is_green_and_contains_totals(self):
        output = io.StringIO()

        with redirect_stdout(output):
            _print_translation_summary(
                job_id="job-42",
                file_name="book.epub",
                result_file_name="book.uk.epub",
                document_kind="epub",
                completed_fragments=10,
                total_fragments=10,
                elapsed_seconds=125.4,
                prompt_tokens=1000,
                completion_tokens=700,
                total_tokens=1700,
                prompt_cache_hit_tokens=300,
                prompt_cache_miss_tokens=700,
                status="ready",
            )

        text = output.getvalue()
        self.assertIn("\033[92m", text)
        self.assertIn("\033[0m", text)
        self.assertIn("TRANSLATION FINISHED", text)
        self.assertIn("job_id=job-42", text)
        self.assertIn("file=book.epub", text)
        self.assertIn("result=book.uk.epub", text)
        self.assertIn("kind=epub", text)
        self.assertIn("fragments=10/10", text)
        self.assertIn("elapsed=125.40s", text)
        self.assertIn("avg_fragment_time=12.54s", text)
        self.assertIn("tokens=1700", text)
        self.assertIn("prompt_tokens=1000", text)
        self.assertIn("completion_tokens=700", text)
        self.assertIn("cache_hit_tokens=300", text)
        self.assertIn("cache_miss_tokens=700", text)

    def test_failed_translation_summary_is_not_green(self):
        output = io.StringIO()

        with redirect_stdout(output):
            _print_translation_summary(
                job_id="job-43",
                file_name="book.epub",
                result_file_name=None,
                document_kind="epub",
                completed_fragments=3,
                total_fragments=10,
                elapsed_seconds=30,
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                prompt_cache_hit_tokens=0,
                prompt_cache_miss_tokens=100,
                status="failed",
            )

        text = output.getvalue()
        self.assertNotIn("\033[92m", text)
        self.assertIn("TRANSLATION FINISHED", text)
        self.assertIn("status=failed", text)


if __name__ == "__main__":
    unittest.main()
