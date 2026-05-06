import asyncio
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.bot.runtime import (
    BotRuntimeConfig,
    HEARTBEAT_PATTERNS,
    _cancel_inline_keyboard,
    _choose_heartbeat_pattern_name,
    _document_exceeds_upload_limit,
    _include_progress_preview,
    _is_language_button_text,
    _main_menu_keyboard,
    _next_heartbeat_frame,
    _next_spinner_frame,
    _print_translation_progress,
    _print_translation_summary,
    _schedule_message_edit,
    _settings_keyboard,
    build_default_pricing_rules,
    build_translation_service,
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
        self.edits: list[tuple[str, int, int, object, str | None]] = []

    async def edit_message_text(
        self,
        *,
        text: str,
        chat_id: int,
        message_id: int,
        reply_markup=None,
        parse_mode=None,
    ) -> None:
        self.edits.append((text, chat_id, message_id, reply_markup, parse_mode))


class Chat:
    id = 100


class BotBackedMessage:
    def __init__(self) -> None:
        self.bot = RecordingBot()
        self.chat = Chat()
        self.message_id = 55


class _RuntimeRecordingTranslator:
    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        return f"[{target_language}] {text}"


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
        self.assertEqual(config.object_storage_root, "var/object-storage")
        self.assertEqual(config.persistent_jobs_db_path, "var/jobs.sqlite3")

    def test_build_translation_service_wires_local_object_storage(self):
        with TemporaryDirectory() as temp_dir:
            service = build_translation_service(
                BotRuntimeConfig(
                    object_storage_root=temp_dir,
                    persistent_jobs_db_path=str(Path(temp_dir) / "jobs.sqlite3"),
                )
            )
            self.addCleanup(service.close)

            upload = service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"This is an English document.",
                source_language="auto",
            )

            self.assertIsNotNone(upload.source_object_key)
            self.assertTrue((Path(temp_dir) / upload.source_object_key).exists())

    def test_build_translation_service_wires_persistent_txt_confirmation(self):
        with TemporaryDirectory() as temp_dir:
            service = build_translation_service(
                BotRuntimeConfig(
                    object_storage_root=str(Path(temp_dir) / "objects"),
                    persistent_jobs_db_path=str(Path(temp_dir) / "jobs.sqlite3"),
                    max_fragment_chars=5,
                )
            )
            self.addCleanup(service.close)
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
                translator=_RuntimeRecordingTranslator(),
            )

            self.assertEqual(job.id, "job-1")
            self.assertEqual(job.result_file_name, "notes.uk.txt")
            self.assertEqual(job.result_content.decode("utf-8"), "[uk] One.\n\n[uk] Two.")

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
        self.assertEqual(message.bot.edits, [("Progress 2", 100, 55, "inline-keyboard", "HTML")])

    async def test_schedules_message_edit_with_html_parse_mode_for_expandable_quotes(self):
        message = BotBackedMessage()
        loop = asyncio.get_running_loop()

        future = _schedule_message_edit(
            loop=loop,
            message=message,
            text="<blockquote expandable>Preview</blockquote>",
        )

        await asyncio.wrap_future(future)
        self.assertEqual(message.bot.edits[0][4], "HTML")

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
                ["⚙️ Settings"],
                ["Help"],
            ],
        )

    def test_progress_preview_helper_respects_user_setting(self):
        with TemporaryDirectory() as temp_dir:
            service = build_translation_service(
                BotRuntimeConfig(
                    object_storage_root=str(Path(temp_dir) / "objects"),
                    persistent_jobs_db_path=str(Path(temp_dir) / "jobs.sqlite3"),
                )
            )
            self.addCleanup(service.close)

            self.assertEqual(
                _include_progress_preview(service, 42, "translated"),
                "translated",
            )

            service.set_progress_preview_enabled(user_telegram_id=42, enabled=False)

            self.assertIsNone(_include_progress_preview(service, 42, "translated"))

    def test_settings_keyboard_exposes_only_preview_toggle_and_main_menu(self):
        keyboard = _settings_keyboard("ru", progress_preview_enabled=False)

        self.assertEqual(
            [[button.text for button in row] for row in keyboard.keyboard],
            [
                ["Показывать фрагмент"],
                ["Главное меню"],
            ],
        )

    def test_document_size_guard_uses_telegram_metadata_before_download(self):
        class Document:
            file_size = 6 * 1024 * 1024

        self.assertTrue(_document_exceeds_upload_limit(Document(), max_upload_mb=5))
        self.assertFalse(_document_exceeds_upload_limit(Document(), max_upload_mb=6))

    def test_translation_progress_log_includes_last_translated_fragment_preview(self):
        output = io.StringIO()

        with redirect_stdout(output):
            _print_translation_progress(
                progress=TranslationProgress(
                    completed_fragments=1,
                    total_fragments=2,
                    source_text="private source text",
                    translated_text="translated text\nwith a second line",
                    elapsed_seconds=1.25,
                    total_tokens=9,
                ),
                elapsed_total_seconds=2,
            )

        self.assertNotIn("private source text", output.getvalue())
        self.assertIn("last_translated=", output.getvalue())
        self.assertIn("translated text with a second line", output.getvalue())
        self.assertIn("tokens=9", output.getvalue())

    def test_spinner_frame_cycles(self):
        self.assertEqual(_next_spinner_frame(-1), "⠋")
        self.assertEqual(_next_spinner_frame(0), "⠙")
        self.assertEqual(_next_spinner_frame(9), "⠋")

    def test_heartbeat_patterns_are_mono_typographic(self):
        self.assertGreaterEqual(len(HEARTBEAT_PATTERNS), 5)
        self.assertEqual(HEARTBEAT_PATTERNS["calm_dots"], ("·", "•", "●", "•"))
        self.assertEqual(HEARTBEAT_PATTERNS["fleuron"], ("❦", "❧", "❦", "❧"))
        self.assertEqual(HEARTBEAT_PATTERNS["editorial"], ("¶", "§", "¶", "§"))
        flattened = "".join(symbol for pattern in HEARTBEAT_PATTERNS.values() for symbol in pattern)
        self.assertNotIn("❤️", flattened)
        self.assertNotIn("💕", flattened)

    def test_heartbeat_pattern_choice_is_stable_for_order_seed(self):
        first = _choose_heartbeat_pattern_name(user_telegram_id=42, file_name="book.epub")
        second = _choose_heartbeat_pattern_name(user_telegram_id=42, file_name="book.epub")

        self.assertEqual(first, second)
        self.assertIn(first, HEARTBEAT_PATTERNS)

    def test_heartbeat_frame_cycles_with_selected_pattern(self):
        self.assertEqual(_next_heartbeat_frame("page", -1), "□")
        self.assertEqual(_next_heartbeat_frame("page", 0), "▣")
        self.assertEqual(_next_heartbeat_frame("page", 3), "□")
        self.assertEqual(_next_heartbeat_frame("unknown", -1), "·")

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
