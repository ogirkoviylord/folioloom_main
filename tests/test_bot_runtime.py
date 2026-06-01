import asyncio
import io
import unittest
from base64 import urlsafe_b64encode
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from translator_service.admin.ai_provider_keys import SQLiteAIProviderKeyStore
from translator_service.admin.beta_safety_settings import (
    BETA_TRANSLATIONS_PAUSED_SETTING,
)
from translator_service.admin.provider_runtime import SQLiteAIProviderRuntimeStore
from translator_service.admin.secrets import SQLiteEncryptedSecretStore
from translator_service.admin.settings import SQLiteAdminSettingsStore
from translator_service.beta_access import BETA_ALLOWLIST_SETTING
from translator_service.beta_safety import BETA_SAFETY_KILL_SWITCH
from translator_service.bot.runtime import (
    HEARTBEAT_PATTERNS,
    BotRuntimeConfig,
    ReloadableDeepSeekTranslator,
    _answer_callback_if_spam,
    _CallbackSpamGuard,
    _cancel_active_translation,
    _cancel_inline_keyboard,
    _choose_heartbeat_pattern_name,
    _confirm_pending_translation,
    _confirm_pending_upload_rights,
    _continue_pending_translation_after_preview,
    _deepseek_parallel_capacity,
    _deepseek_parallel_capacity_from_env,
    _deepseek_throttle_config_from_env,
    _document_exceeds_upload_limit,
    _edit_callback_message,
    _include_progress_preview,
    _is_language_button_text,
    _log_message_edit_error,
    _main_menu_keyboard,
    _my_books_keyboard,
    _next_heartbeat_frame,
    _next_spinner_frame,
    _polled_progress_estimated_total_seconds,
    _prepare_and_send_translation_preview,
    _print_translation_progress,
    _print_translation_progress_update,
    _print_translation_summary,
    _progress_message_for_current_user_language,
    _resume_user_book_translation,
    _schedule_message_edit,
    _send_translation_result_document,
    _send_translation_result_document_once,
    _send_user_book_result,
    _settings_keyboard,
    _should_schedule_progress_edit,
    _UserActionInFlightGuard,
    bot_runtime_config_from_settings,
    build_beta_safety_guard,
    build_deepseek_translator,
    build_default_pricing_rules,
    build_document_scanner,
    build_translation_service,
    create_router,
)
from translator_service.bot_translation_service import (
    TRANSLATION_MODE_BOOK_MANUSCRIPT,
    TRANSLATION_MODE_DOCUMENT_FORM,
    PreviewTranslationError,
    UserBookResult,
)
from translator_service.config import Settings
from translator_service.deepseek_key_pool import DeepSeekKeyPoolTranslator
from translator_service.document_sandbox import DocumentSandbox
from translator_service.document_scanner import LimitedConcurrencyDocumentScanner
from translator_service.job_runner import (
    DocumentKind,
    TranslationJob,
    TranslationJobStatus,
)
from translator_service.translation_jobs import TranslationProgress
from translator_service.user_activity import SQLiteUserActivityStore

MASTER_KEY = urlsafe_b64encode(b"5" * 32).decode("ascii")


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
        self.edited_reply_markups: list[object] = []

    def edit_text(self, text: str, reply_markup=None):
        def record() -> None:
            self.edited_texts.append(text)
            self.edited_reply_markups.append(reply_markup)

        return TelegramMethodLikeAwaitable(record)


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


class User:
    id = 42


class RecordingCallback:
    def __init__(self, *, data: str = "my_books") -> None:
        self.from_user = User()
        self.data = data
        self.answers: list[tuple[object, ...]] = []

    async def answer(self, *args, **kwargs) -> None:
        self.answers.append((args, kwargs))


class RecordingMessage:
    def __init__(self) -> None:
        self.from_user = User()
        self.answers: list[tuple[str, object | None]] = []
        self.answer_messages: list[EditableMessage] = []
        self.documents: list[object] = []

    async def answer(self, text: str, reply_markup=None, **kwargs):
        self.answers.append((text, reply_markup))
        message = EditableMessage()
        self.answer_messages.append(message)
        return message

    async def answer_document(self, document) -> None:
        self.documents.append(document)


class FailingOnceRecordingMessage(RecordingMessage):
    def __init__(self) -> None:
        super().__init__()
        self._failed = False

    async def answer_document(self, document) -> None:
        if not self._failed:
            self._failed = True
            raise RuntimeError("telegram send failed")
        await super().answer_document(document)


class CancellingOnceRecordingMessage(RecordingMessage):
    def __init__(self) -> None:
        super().__init__()
        self._cancelled = False

    async def answer_document(self, document) -> None:
        if not self._cancelled:
            self._cancelled = True
            raise asyncio.CancelledError()
        await super().answer_document(document)


class _RuntimeRecordingTranslator:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, str]] = []

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        self.requests.append((text, source_language, target_language))
        return f"[{target_language}] {text}"


class _RuntimeFailingTranslator:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, str]] = []

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        self.requests.append((text, source_language, target_language))
        raise RuntimeError("provider unavailable")


class _QueuedThenReadyService:
    def __init__(self) -> None:
        self.progress_calls = 0

    def get_interface_language(self, user_telegram_id: int) -> str:
        return "en"

    def get_progress_preview_enabled(self, user_telegram_id: int) -> bool:
        return True

    def is_translation_cancelling(self, user_telegram_id: int) -> bool:
        return False

    def resume_user_book_translation(self, **kwargs) -> TranslationJob:
        return _runtime_job(status=TranslationJobStatus.QUEUED)

    def get_user_book_progress(self, **kwargs):
        self.progress_calls += 1
        return type(
            "Progress",
            (),
            {
                "completed_fragments": 1,
                "total_fragments": 2,
            },
        )()

    def get_user_book_translation_job(self, **kwargs):
        if self.progress_calls == 0:
            return _runtime_job(status=TranslationJobStatus.QUEUED)
        return _runtime_job(status=TranslationJobStatus.READY)

    def get_user_book_detail(self, **kwargs):
        return {
            "job_id": "job-1",
            "file_name": "book.txt",
            "document_kind": "txt",
            "source_language": "en",
            "target_language": "uk",
            "status": "ready",
            "has_result": False,
            "can_resume": False,
            "can_cancel": False,
        }


class _CancelWithResultService:
    def __init__(self, job: TranslationJob | None) -> None:
        self.job = job
        self._automatic_result_delivered_keys: set[tuple[str, str | None]] = set()
        self._automatic_result_delivery_in_flight: set[tuple[str, str | None]] = set()

    def get_interface_language(self, user_telegram_id: int) -> str:
        return "en"

    def begin_automatic_result_delivery(self, job: TranslationJob) -> bool:
        key = (job.id, job.result_file_name)
        if not (job.result_file_name and job.result_content):
            return False
        if (
            key in self._automatic_result_delivered_keys
            or key in self._automatic_result_delivery_in_flight
        ):
            return False
        self._automatic_result_delivery_in_flight.add(key)
        return True

    def finish_automatic_result_delivery(self, job: TranslationJob, *, delivered: bool):
        key = (job.id, job.result_file_name)
        self._automatic_result_delivery_in_flight.discard(key)
        if delivered:
            self._automatic_result_delivered_keys.add(key)

    def cancel_translation_with_result(self, user_telegram_id: int):
        return type(
            "CancelResult",
            (),
            {
                "cancelled": True,
                "job": self.job,
            },
        )()


def _runtime_job(*, status: TranslationJobStatus) -> TranslationJob:
    return TranslationJob(
        id="job-1",
        user_telegram_id=42,
        file_name="book.txt",
        content=b"",
        source_language="en",
        target_language="uk",
        status=status,
        document_kind=DocumentKind.TXT,
    )


class _RuntimeKeyEchoDeepSeekClient:
    def __init__(self, *, api_key: str, **kwargs) -> None:
        self.api_key = api_key
        self.last_usage = None

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        return f"{self.api_key}:{target_language}:{text}"


class _FakePostgresStore:
    connection = object()

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class BotRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def _router_message_handler(self, router, name: str):
        for handler in router.message.handlers:
            if getattr(handler.callback, "__name__", None) == name:
                return handler.callback
        self.fail(f"Router message handler not found: {name}")

    def _router_callback_handler(self, router, name: str):
        for handler in router.callback_query.handlers:
            if getattr(handler.callback, "__name__", None) == name:
                return handler.callback
        self.fail(f"Router callback handler not found: {name}")

    def _accept_pending_preview(self, service, *, user_telegram_id: int = 42) -> None:
        with service._state_lock:
            pending = service._pending[user_telegram_id]
            service._pending[user_telegram_id] = replace(
                pending,
                preview_id=f"preview:{user_telegram_id}:test",
                preview_shown=True,
                preview_accepted=True,
                preview_accepted_at="2026-05-16T00:00:00+00:00",
                translation_mode=pending.translation_mode
                or TRANSLATION_MODE_BOOK_MANUSCRIPT,
            )

    def _select_default_translation_mode(
        self,
        service,
        *,
        user_telegram_id: int = 42,
        translation_mode: str = TRANSLATION_MODE_BOOK_MANUSCRIPT,
    ) -> None:
        service.select_pending_upload_translation_mode(
            user_telegram_id=user_telegram_id,
            translation_mode=translation_mode,
        )

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
        self.assertFalse(config.require_upload_scan)
        self.assertEqual(config.upload_scanner_backend, "none")
        self.assertEqual(config.upload_scan_max_concurrency, 1)
        self.assertEqual(config.upload_scan_backpressure_timeout_seconds, 1.0)
        self.assertEqual(config.clamd_host, "127.0.0.1")
        self.assertEqual(config.clamd_port, 3310)
        self.assertEqual(config.clamd_timeout_seconds, 10.0)
        self.assertEqual(config.clamd_chunk_size_bytes, 65_536)
        self.assertEqual(config.clamd_response_limit_bytes, 4_096)
        self.assertEqual(config.object_storage_root, "var/object-storage")
        self.assertEqual(config.persistent_jobs_db_path, "var/jobs.sqlite3")
        self.assertEqual(config.scheduler_backend, "sqlite")
        self.assertEqual(config.max_parallel_work_units, 1)
        self.assertEqual(config.provider_parallel_capacity, 1)
        self.assertEqual(config.security_max_events_per_run, 20)
        self.assertEqual(config.security_max_unsafe_model_outputs_per_run, 3)
        self.assertEqual(config.security_max_repair_failures_per_run, 1)
        self.assertEqual(config.security_user_cooldown_thresholds_per_window, 2)
        self.assertEqual(config.security_user_cooldown_window_seconds, 3600)
        self.assertEqual(config.security_user_cooldown_seconds, 900)
        self.assertEqual(config.callback_spam_min_interval_seconds, 0.7)
        self.assertEqual(config.callback_spam_burst_limit, 20)
        self.assertEqual(config.callback_spam_burst_window_seconds, 10.0)
        self.assertEqual(config.user_action_lock_ttl_seconds, 900.0)

    def test_runtime_config_maps_production_scanner_fail_closed_defaults(self):
        with patch.dict(
            "os.environ",
            {
                "ENVIRONMENT": "production",
            },
            clear=True,
        ):
            config = bot_runtime_config_from_settings(Settings())

        self.assertTrue(config.require_upload_scan)
        self.assertEqual(config.upload_scanner_backend, "clamd")
        self.assertEqual(config.clamd_host, "clamd")
        self.assertIsInstance(
            build_document_scanner(config),
            LimitedConcurrencyDocumentScanner,
        )

    def test_runtime_config_maps_server_beta_scanner_fail_closed_defaults(self):
        with patch.dict(
            "os.environ",
            {
                "ENVIRONMENT": "server-beta",
            },
            clear=True,
        ):
            config = bot_runtime_config_from_settings(Settings())

        self.assertTrue(config.require_upload_scan)
        self.assertEqual(config.upload_scanner_backend, "clamd")
        self.assertEqual(config.clamd_host, "clamd")
        self.assertIsInstance(
            build_document_scanner(config),
            LimitedConcurrencyDocumentScanner,
        )

    def test_translation_service_uses_postgres_store_for_postgres_backend(self):
        fake_store = _FakePostgresStore()

        with (
            patch(
                "translator_service.postgres_scheduler.PostgresSchedulerStore",
                return_value=fake_store,
            ),
            patch(
                "translator_service.postgres_scheduler."
                "initialize_postgres_scheduler_schema"
            ),
        ):
            service = build_translation_service(
                BotRuntimeConfig(
                    scheduler_backend="postgres",
                    postgres_dsn="postgresql://translator",
                )
            )

        self.addCleanup(service.close)
        self.assertIs(service._persistent_job_store, fake_store)
        self.assertTrue(service._use_scheduler_runner)
        self.assertFalse(service._defer_persistent_jobs_to_worker)

    def test_build_document_scanner_wires_clamd_with_backpressure(self):
        scanner = build_document_scanner(
            BotRuntimeConfig(
                upload_scanner_backend="clamd",
                clamd_host="clamd",
                clamd_port=3310,
                clamd_timeout_seconds=2.0,
                clamd_chunk_size_bytes=8192,
                clamd_response_limit_bytes=1024,
                upload_scan_max_concurrency=1,
                upload_scan_backpressure_timeout_seconds=0.1,
            )
        )

        self.assertIsInstance(scanner, LimitedConcurrencyDocumentScanner)

    def test_build_document_scanner_rejects_unknown_backend(self):
        with self.assertRaises(ValueError):
            build_document_scanner(BotRuntimeConfig(upload_scanner_backend="public-av"))

    def test_callback_spam_guard_blocks_fast_duplicate_actions(self):
        now = 100.0
        guard = _CallbackSpamGuard(
            min_interval_seconds=0.7,
            burst_limit=20,
            burst_window_seconds=10.0,
            clock=lambda: now,
        )

        self.assertTrue(guard.allow(user_id=42, action="my_books"))
        self.assertFalse(guard.allow(user_id=42, action="my_books"))

        now = 100.8

        self.assertTrue(guard.allow(user_id=42, action="my_books"))

    def test_callback_spam_guard_blocks_user_bursts_across_actions(self):
        now = 100.0
        guard = _CallbackSpamGuard(
            min_interval_seconds=0.0,
            burst_limit=2,
            burst_window_seconds=10.0,
            clock=lambda: now,
        )

        self.assertTrue(guard.allow(user_id=42, action="book_detail:1"))
        now = 101.0
        self.assertTrue(guard.allow(user_id=42, action="book_detail:2"))
        now = 102.0
        self.assertFalse(guard.allow(user_id=42, action="download_book:1"))

        now = 112.1

        self.assertTrue(guard.allow(user_id=42, action="download_book:1"))

    def test_user_action_guard_blocks_duplicate_translation_starts_until_finished(self):
        now = 100.0
        guard = _UserActionInFlightGuard(ttl_seconds=30.0, clock=lambda: now)

        self.assertTrue(guard.try_begin(user_id=42, action="translation_start"))
        now = 131.0

        self.assertTrue(guard.try_begin(user_id=42, action="translation_start"))
        self.assertFalse(guard.try_begin(user_id=42, action="translation_start"))

        guard.finish(user_id=42, action="translation_start")

        self.assertTrue(guard.try_begin(user_id=42, action="translation_start"))

    def test_user_action_guard_expires_abandoned_actions(self):
        now = 100.0
        guard = _UserActionInFlightGuard(ttl_seconds=30.0, clock=lambda: now)

        self.assertTrue(guard.try_begin(user_id=42, action="translation_start"))

    async def test_callback_spam_helper_answers_and_skips_duplicate_callback(self):
        now = 100.0
        guard = _CallbackSpamGuard(
            min_interval_seconds=0.7,
            burst_limit=20,
            burst_window_seconds=10.0,
            clock=lambda: now,
        )
        callback = RecordingCallback(data="my_books")

        self.assertFalse(await _answer_callback_if_spam(callback, guard))
        self.assertTrue(await _answer_callback_if_spam(callback, guard))

        self.assertEqual(len(callback.answers), 1)

    async def test_confirm_guard_ignores_duplicate_start_without_progress_message(self):
        service = build_translation_service(
            BotRuntimeConfig(
                persistent_jobs_db_path=":memory:",
                user_settings_db_path=":memory:",
            )
        )
        self.addCleanup(service.close)
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.",
            source_language="en",
            target_language="uk",
        )
        guard = _UserActionInFlightGuard(ttl_seconds=30.0)
        self.assertTrue(guard.try_begin(user_id=42, action="translation_start"))
        message = RecordingMessage()

        await _confirm_pending_translation(
            message=message,
            service=service,
            translator=_RuntimeRecordingTranslator(),
            action_guard=guard,
        )

        self.assertEqual(message.answers, [])
        self.assertIsNotNone(service.get_pending(42))

    async def test_confirm_before_rights_prompts_without_starting_translation(self):
        service = build_translation_service(
            BotRuntimeConfig(
                persistent_jobs_db_path=":memory:",
                user_settings_db_path=":memory:",
            )
        )
        self.addCleanup(service.close)
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.",
            source_language="en",
        )
        translator = _RuntimeRecordingTranslator()
        message = RecordingMessage()

        await _confirm_pending_translation(
            message=message,
            service=service,
            translator=translator,
        )

        self.assertEqual(translator.requests, [])
        self.assertEqual(len(message.answers), 1)
        self.assertIn("right to translate this document", message.answers[0][0])
        self.assertIsNotNone(service.get_pending_upload(42))

    async def test_confirm_translation_edits_progress_message_to_terminal_status(self):
        service = build_translation_service(
            BotRuntimeConfig(
                persistent_jobs_db_path=":memory:",
                user_settings_db_path=":memory:",
                max_fragment_chars=5,
            )
        )
        self.addCleanup(service.close)
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.",
            source_language="en",
            target_language="uk",
        )
        self._accept_pending_preview(service)
        message = RecordingMessage()

        await _confirm_pending_translation(
            message=message,
            service=service,
            translator=_RuntimeRecordingTranslator(),
        )

        self.assertTrue(message.answer_messages[0].edited_texts)
        self.assertIn(
            "Your translation is ready",
            message.answer_messages[0].edited_texts[-1],
        )
        self.assertIsNone(message.answer_messages[0].edited_reply_markups[-1])
        self.assertEqual(len(message.documents), 1)

    async def test_confirm_rights_prompts_translation_mode_without_creating_job(self):
        service = build_translation_service(
            BotRuntimeConfig(
                persistent_jobs_db_path=":memory:",
                user_settings_db_path=":memory:",
            )
        )
        self.addCleanup(service.close)
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.",
            source_language="en",
        )
        message = RecordingMessage()

        await _confirm_pending_upload_rights(message=message, service=service)
        await _confirm_pending_upload_rights(message=message, service=service)

        self.assertEqual(len(message.answers), 2)
        self.assertIn("Choose how to translate this document", message.answers[0][0])
        self.assertIn("Choose how to translate this document", message.answers[1][0])
        self.assertTrue(service.get_pending_upload(42).rights_confirmed)
        self.assertIsNone(service.get_pending_upload(42).translation_mode)
        self.assertEqual(service.list_user_books(user_telegram_id=42), [])

    async def test_mode_choice_prompts_target_language_without_creating_job(self):
        service = build_translation_service(
            BotRuntimeConfig(
                persistent_jobs_db_path=":memory:",
                user_settings_db_path=":memory:",
            )
        )
        self.addCleanup(service.close)
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.",
            source_language="en",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        message = RecordingMessage()
        message.text = "Document / form"
        router = create_router(
            service=service,
            translator=_RuntimeRecordingTranslator(),
            config=BotRuntimeConfig(),
        )

        handler = self._router_message_handler(router, "translation_mode_text")
        await handler(message)

        pending_upload = service.get_pending_upload(42)
        self.assertIsNotNone(pending_upload)
        self.assertEqual(
            pending_upload.translation_mode,
            TRANSLATION_MODE_DOCUMENT_FORM,
        )
        self.assertEqual(service.list_user_books(user_telegram_id=42), [])
        self.assertIn("Choose the target language", message.answers[0][0])

    async def test_language_choice_before_mode_prompts_mode_without_preview(self):
        service = build_translation_service(
            BotRuntimeConfig(
                persistent_jobs_db_path=":memory:",
                user_settings_db_path=":memory:",
            )
        )
        self.addCleanup(service.close)
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One meaningful paragraph for preview.",
            source_language="en",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        translator = _RuntimeRecordingTranslator()
        message = RecordingMessage()
        message.text = "🇺🇦 Українська"
        router = create_router(
            service=service,
            translator=translator,
            config=BotRuntimeConfig(),
        )

        handler = self._router_message_handler(router, "language_text")
        await handler(message)

        self.assertEqual(len(translator.requests), 0)
        self.assertIsNone(service.get_pending(42))
        self.assertIsNotNone(service.get_pending_upload(42))
        self.assertIn("Choose how to translate this document", message.answers[0][0])

    async def test_language_choice_shows_preview_without_creating_job(self):
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = build_translation_service(
            BotRuntimeConfig(
                admin_db_path=str(Path(temp_dir.name) / "admin.sqlite3"),
                persistent_jobs_db_path=":memory:",
                user_settings_db_path=":memory:",
                object_storage_root=str(Path(temp_dir.name) / "objects"),
            )
        )
        self.addCleanup(service.close)
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One meaningful paragraph for preview.",
            source_language="en",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        self._select_default_translation_mode(service)
        translator = _RuntimeRecordingTranslator()
        message = RecordingMessage()

        await _prepare_and_send_translation_preview(
            message=message,
            service=service,
            translator=translator,
            target_language="uk",
            interface_language="en",
        )

        self.assertEqual(len(translator.requests), 1)
        self.assertEqual(service.list_user_books(user_telegram_id=42), [])
        self.assertIsNotNone(service.get_pending(42))
        self.assertIsNone(service.get_pending_upload(42))
        self.assertEqual(len(message.answers), 1)
        self.assertIn("Translation preview", message.answers[0][0])
        self.assertIn("[uk] One meaningful paragraph", message.answers[0][0])
        self.assertIn("Cost: ???", message.answers[0][0])
        keyboard_texts = [
            button.text
            for row in message.answers[0][1].keyboard
            for button in row
        ]
        self.assertEqual(keyboard_texts, ["Continue Translation", "Back"])

    async def test_language_choice_shows_ready_duplicate_choice_without_preview(self):
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = build_translation_service(
            BotRuntimeConfig(
                admin_db_path=str(Path(temp_dir.name) / "admin.sqlite3"),
                persistent_jobs_db_path=":memory:",
                user_settings_db_path=":memory:",
                object_storage_root=str(Path(temp_dir.name) / "objects"),
            )
        )
        self.addCleanup(service.close)
        content = b"One meaningful paragraph for duplicate prompt."
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=content,
            source_language="en",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        self._select_default_translation_mode(service)
        service.prepare_pending_upload(user_telegram_id=42, target_language="uk")
        self._accept_pending_preview(service)
        completed = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=_RuntimeRecordingTranslator(),
        )
        self.assertEqual(completed.status, TranslationJobStatus.READY)

        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="copy.txt",
            content=content,
            source_language="en",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        self._select_default_translation_mode(service)
        translator = _RuntimeRecordingTranslator()
        message = RecordingMessage()

        await _prepare_and_send_translation_preview(
            message=message,
            service=service,
            translator=translator,
            target_language="uk",
            interface_language="en",
        )

        self.assertEqual(translator.requests, [])
        self.assertEqual(len(message.answers), 1)
        self.assertIn("has already been translated", message.answers[0][0])
        keyboard_buttons = [
            (button.text, button.callback_data)
            for row in message.answers[0][1].inline_keyboard
            for button in row
        ]
        self.assertEqual(
            keyboard_buttons,
            [
                ("Download Translation", f"download_book:{completed.id}"),
                ("Translate Again", "duplicate_upload_translate_again"),
                ("Back", "duplicate_upload_back"),
            ],
        )
        self.assertNotIn("Continue Translation", message.answers[0][0])
        self.assertIsNotNone(service.get_pending(42))
        self.assertIsNone(service.get_pending_upload(42))

    async def test_duplicate_translate_again_callback_shows_fresh_preview(self):
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = build_translation_service(
            BotRuntimeConfig(
                admin_db_path=str(Path(temp_dir.name) / "admin.sqlite3"),
                persistent_jobs_db_path=":memory:",
                user_settings_db_path=":memory:",
                object_storage_root=str(Path(temp_dir.name) / "objects"),
            )
        )
        self.addCleanup(service.close)
        content = b"One meaningful paragraph for duplicate translate again."
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=content,
            source_language="en",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        self._select_default_translation_mode(service)
        service.prepare_pending_upload(user_telegram_id=42, target_language="uk")
        self._accept_pending_preview(service)
        service.confirm_pending_translation(
            user_telegram_id=42,
            translator=_RuntimeRecordingTranslator(),
        )

        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="copy.txt",
            content=content,
            source_language="en",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        self._select_default_translation_mode(service)
        service.prepare_pending_upload(user_telegram_id=42, target_language="uk")
        translator = _RuntimeRecordingTranslator()
        router = create_router(
            service=service,
            translator=translator,
            config=BotRuntimeConfig(),
        )
        callback = RecordingCallback(data="duplicate_upload_translate_again")
        callback.message = RecordingMessage()

        handler = self._router_callback_handler(
            router,
            "duplicate_upload_translate_again",
        )
        await handler(callback)

        self.assertEqual(len(translator.requests), 1)
        self.assertEqual(len(callback.message.answers), 1)
        self.assertIn("Translation preview", callback.message.answers[0][0])
        keyboard_texts = [
            button.text
            for row in callback.message.answers[0][1].keyboard
            for button in row
        ]
        self.assertEqual(keyboard_texts, ["Continue Translation", "Back"])
        pending = service.get_pending(42)
        self.assertIsNotNone(pending)
        self.assertTrue(pending.preview_shown)

    async def test_preview_failure_restores_language_selection_state(self):
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = build_translation_service(
            BotRuntimeConfig(
                admin_db_path=str(Path(temp_dir.name) / "admin.sqlite3"),
                persistent_jobs_db_path=":memory:",
                user_settings_db_path=":memory:",
                object_storage_root=str(Path(temp_dir.name) / "objects"),
            )
        )
        self.addCleanup(service.close)
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One meaningful paragraph for preview.",
            source_language="en",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        self._select_default_translation_mode(service)
        translator = _RuntimeFailingTranslator()

        with self.assertRaises(PreviewTranslationError):
            await _prepare_and_send_translation_preview(
                message=RecordingMessage(),
                service=service,
                translator=translator,
                target_language="uk",
                interface_language="en",
            )

        self.assertEqual(len(translator.requests), 1)
        self.assertIsNone(service.get_pending(42))
        restored_upload = service.get_pending_upload(42)
        self.assertIsNotNone(restored_upload)
        self.assertTrue(restored_upload.rights_confirmed)
        self.assertEqual(
            restored_upload.translation_mode,
            TRANSLATION_MODE_BOOK_MANUSCRIPT,
        )
        self.assertEqual(service.list_user_books(user_telegram_id=42), [])

    async def test_continue_after_preview_starts_translation(self):
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = build_translation_service(
            BotRuntimeConfig(
                admin_db_path=str(Path(temp_dir.name) / "admin.sqlite3"),
                persistent_jobs_db_path=":memory:",
                user_settings_db_path=":memory:",
            )
        )
        self.addCleanup(service.close)
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One meaningful paragraph for preview.",
            source_language="en",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        self._select_default_translation_mode(service)
        translator = _RuntimeRecordingTranslator()
        message = RecordingMessage()

        await _prepare_and_send_translation_preview(
            message=message,
            service=service,
            translator=translator,
            target_language="uk",
            interface_language="en",
        )
        await _continue_pending_translation_after_preview(
            message=message,
            service=service,
            translator=translator,
        )

        self.assertEqual(len(translator.requests), 2)
        self.assertIsNone(service.get_pending(42))
        self.assertEqual(len(message.documents), 1)
        rendered_text = "\n".join(answer[0] for answer in message.answers)
        self.assertNotIn("paid", rendered_text.lower())
        self.assertNotIn("Оплатить", rendered_text)

    async def test_confirm_before_continue_prompts_without_starting(self):
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        service = build_translation_service(
            BotRuntimeConfig(
                admin_db_path=str(Path(temp_dir.name) / "admin.sqlite3"),
                persistent_jobs_db_path=":memory:",
                user_settings_db_path=":memory:",
            )
        )
        self.addCleanup(service.close)
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One meaningful paragraph for preview.",
            source_language="en",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        self._select_default_translation_mode(service)
        translator = _RuntimeRecordingTranslator()
        message = RecordingMessage()

        await _prepare_and_send_translation_preview(
            message=message,
            service=service,
            translator=translator,
            target_language="uk",
            interface_language="en",
        )
        await _confirm_pending_translation(
            message=message,
            service=service,
            translator=translator,
        )

        self.assertEqual(len(translator.requests), 1)
        self.assertIsNotNone(service.get_pending(42))
        self.assertEqual(len(message.documents), 0)
        self.assertIn("Review the translation preview", message.answers[-1][0])

    async def test_router_start_translation_handler_cannot_accept_preview(self):
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        config = BotRuntimeConfig(
            admin_db_path=str(Path(temp_dir.name) / "admin.sqlite3"),
            persistent_jobs_db_path=":memory:",
            user_settings_db_path=":memory:",
        )
        service = build_translation_service(config)
        self.addCleanup(service.close)
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One meaningful paragraph for preview.",
            source_language="en",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        self._select_default_translation_mode(service)
        translator = _RuntimeRecordingTranslator()
        message = RecordingMessage()
        await _prepare_and_send_translation_preview(
            message=message,
            service=service,
            translator=translator,
            target_language="uk",
            interface_language="en",
        )

        router = create_router(service=service, translator=translator, config=config)
        handler = self._router_message_handler(router, "confirm_text")
        await handler(message)

        self.assertEqual(len(translator.requests), 1)
        self.assertIsNotNone(service.get_pending(42))
        self.assertEqual(len(message.documents), 0)
        self.assertIn("Review the translation preview", message.answers[-1][0])

    async def test_router_continue_handler_accepts_preview_and_starts_once(self):
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        config = BotRuntimeConfig(
            admin_db_path=str(Path(temp_dir.name) / "admin.sqlite3"),
            persistent_jobs_db_path=":memory:",
            user_settings_db_path=":memory:",
        )
        service = build_translation_service(config)
        self.addCleanup(service.close)
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One meaningful paragraph for preview.",
            source_language="en",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        self._select_default_translation_mode(service)
        translator = _RuntimeRecordingTranslator()
        message = RecordingMessage()
        await _prepare_and_send_translation_preview(
            message=message,
            service=service,
            translator=translator,
            target_language="uk",
            interface_language="en",
        )

        router = create_router(service=service, translator=translator, config=config)
        handler = self._router_message_handler(router, "continue_translation_text")
        await handler(message)
        await handler(message)

        self.assertEqual(len(translator.requests), 2)
        self.assertIsNone(service.get_pending(42))
        self.assertEqual(len(message.documents), 1)

    async def test_cancel_button_discards_pending_preview_without_starting_job(self):
        service = build_translation_service(
            BotRuntimeConfig(
                persistent_jobs_db_path=":memory:",
                user_settings_db_path=":memory:",
            )
        )
        self.addCleanup(service.close)
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One meaningful paragraph.",
            source_language="en",
            target_language="uk",
        )
        message = RecordingMessage()

        await _cancel_active_translation(message=message, service=service)

        self.assertIsNone(service.get_pending(42))
        self.assertEqual(service.list_user_books(user_telegram_id=42), [])
        self.assertEqual(len(message.answers), 2)
        self.assertIn("Returning to the Main menu", message.answers[0][0])

    async def test_resume_translation_sends_progress_message_for_queued_job(self):
        message = RecordingMessage()
        service = _QueuedThenReadyService()

        await _resume_user_book_translation(
            message=message,
            user_telegram_id=42,
            job_id="job-1",
            service=service,
            translator=_RuntimeRecordingTranslator(),
            queued_poll_interval_seconds=0.01,
        )

        self.assertGreaterEqual(len(message.answers), 1)
        self.assertTrue(message.answer_messages[0].edited_texts)
        queued_edits = [
            text
            for text in message.answer_messages[0].edited_texts
            if "Your translation is queued" in text
        ]
        self.assertTrue(queued_edits)
        self.assertTrue(
            all("Translation progress" not in text for text in queued_edits)
        )
        queued_cancel_markup = message.answer_messages[0].edited_reply_markups[0]
        self.assertEqual(
            queued_cancel_markup.inline_keyboard[0][0].callback_data,
            "cancel_book:job-1",
        )
        self.assertIn(
            "Your translation is ready",
            message.answer_messages[0].edited_texts[-1],
        )
        self.assertEqual(service.progress_calls, 1)

    async def test_book_detail_callback_renders_persistent_progress(self):
        class BookDetailProgressService:
            def __init__(self) -> None:
                self.activity: list[dict[str, object]] = []

            def get_interface_language(self, user_telegram_id: int) -> str:
                return "en"

            def record_user_activity(self, **kwargs) -> None:
                self.activity.append(kwargs)

            def get_user_book_detail(self, **kwargs):
                return {
                    "job_id": "job-1",
                    "file_name": "active.txt",
                    "document_kind": "txt",
                    "source_language": "en",
                    "target_language": "uk",
                    "status": "translating",
                    "has_result": False,
                    "can_resume": False,
                    "can_cancel": True,
                    "progress_completed_fragments": 2,
                    "progress_total_fragments": 5,
                    "progress_percent": 40,
                }

        service = BookDetailProgressService()
        router = create_router(
            service=service,
            translator=_RuntimeRecordingTranslator(),
            config=BotRuntimeConfig(),
        )
        callback = RecordingCallback(data="book_detail:job-1")
        callback.message = EditableMessage()

        handler = self._router_callback_handler(router, "book_detail")
        await handler(callback)

        self.assertEqual(len(callback.message.edited_texts), 1)
        self.assertIn(
            "Translation progress: 40% (2/5)",
            callback.message.edited_texts[0],
        )
        self.assertIn(
            "cancel_book:job-1",
            "\n".join(
                button.callback_data
                for row in callback.message.edited_reply_markups[0].inline_keyboard
                for button in row
            ),
        )

    async def test_cancel_active_translation_sends_persistent_partial_result(self):
        message = RecordingMessage()
        job = TranslationJob(
            id="job-1",
            user_telegram_id=42,
            file_name="book.txt",
            content=b"",
            source_language="en",
            target_language="uk",
            status=TranslationJobStatus.CANCELLED,
            result_file_name="book.uk.partial.txt",
            result_content=b"[uk] First.",
        )

        await _cancel_active_translation(
            message=message,
            service=_CancelWithResultService(job),
        )

        self.assertEqual(len(message.answers), 1)
        self.assertIn("cancelled", message.answers[0][0].lower())
        self.assertEqual(len(message.documents), 1)
        self.assertEqual(message.documents[0].filename, "book.uk.partial.txt")

    async def test_cancel_result_delivery_is_idempotent_across_runtime_paths(self):
        message = RecordingMessage()
        job = TranslationJob(
            id="job-1",
            user_telegram_id=42,
            file_name="book.txt",
            content=b"",
            source_language="en",
            target_language="uk",
            status=TranslationJobStatus.CANCELLED,
            result_file_name="book.uk.partial.txt",
            result_content=b"[uk] First.",
        )

        service = _CancelWithResultService(job)
        await _cancel_active_translation(message=message, service=service)
        await _send_translation_result_document_once(message, job, service)

        self.assertEqual(
            [document.filename for document in message.documents],
            ["book.uk.partial.txt"],
        )

    async def test_failed_automatic_result_delivery_can_retry(self):
        message = FailingOnceRecordingMessage()
        job = TranslationJob(
            id="job-1",
            user_telegram_id=42,
            file_name="book.txt",
            content=b"",
            source_language="en",
            target_language="uk",
            status=TranslationJobStatus.CANCELLED,
            result_file_name="book.uk.partial.txt",
            result_content=b"[uk] First.",
        )
        service = _CancelWithResultService(job)

        with self.assertRaises(RuntimeError):
            await _send_translation_result_document_once(message, job, service)
        await _send_translation_result_document_once(message, job, service)

        self.assertEqual(
            [document.filename for document in message.documents],
            ["book.uk.partial.txt"],
        )

    async def test_cancelled_automatic_result_delivery_can_retry(self):
        message = CancellingOnceRecordingMessage()
        job = TranslationJob(
            id="job-1",
            user_telegram_id=42,
            file_name="book.txt",
            content=b"",
            source_language="en",
            target_language="uk",
            status=TranslationJobStatus.CANCELLED,
            result_file_name="book.uk.partial.txt",
            result_content=b"[uk] First.",
        )
        service = _CancelWithResultService(job)

        with self.assertRaises(asyncio.CancelledError):
            await _send_translation_result_document_once(message, job, service)
        await _send_translation_result_document_once(message, job, service)

        self.assertEqual(
            [document.filename for document in message.documents],
            ["book.uk.partial.txt"],
        )

    async def test_manual_book_download_still_sends_after_automatic_delivery(self):
        message = RecordingMessage()
        job = TranslationJob(
            id="job-1",
            user_telegram_id=42,
            file_name="book.txt",
            content=b"",
            source_language="en",
            target_language="uk",
            status=TranslationJobStatus.CANCELLED,
            result_file_name="book.uk.partial.txt",
            result_content=b"[uk] First.",
        )
        service = _CancelWithResultService(job)

        await _send_translation_result_document_once(message, job, service)
        await _send_user_book_result(
            message,
            UserBookResult(
                job_id=job.id,
                file_name="book.uk.partial.txt",
                content=b"[uk] First.",
                content_type="text/plain; charset=utf-8",
            ),
        )

        self.assertEqual(
            [document.filename for document in message.documents],
            ["book.uk.partial.txt", "book.uk.partial.txt"],
        )

    async def test_send_translation_result_document_ignores_empty_result(self):
        message = RecordingMessage()

        await _send_translation_result_document(
            message,
            _runtime_job(status=TranslationJobStatus.CANCELLED),
        )

        self.assertEqual(message.documents, [])

    def test_build_translation_service_wires_local_object_storage(self):
        with TemporaryDirectory() as temp_dir:
            service = build_translation_service(
                BotRuntimeConfig(
                    object_storage_root=temp_dir,
                    persistent_jobs_db_path=str(Path(temp_dir) / "jobs.sqlite3"),
                    user_settings_db_path=str(Path(temp_dir) / "settings.sqlite3"),
                )
            )
            self.addCleanup(service.close)
            self.assertIsInstance(service._document_sandbox, DocumentSandbox)

            upload = service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"This is an English document.",
                source_language="auto",
            )

            self.assertIsNotNone(upload.source_object_key)
            self.assertTrue((Path(temp_dir) / upload.source_object_key).exists())

    def test_build_translation_service_wires_beta_allowlist(self):
        with TemporaryDirectory() as temp_dir:
            admin_db_path = Path(temp_dir) / "admin.sqlite3"
            service = build_translation_service(
                BotRuntimeConfig(
                    admin_db_path=str(admin_db_path),
                    beta_allowlist_telegram_ids=(42,),
                    beta_allowlist_enabled=True,
                )
            )
            self.addCleanup(service.close)

            self.assertTrue(service.is_beta_allowed(42))
            self.assertFalse(service.is_beta_allowed(100))

            with SQLiteAdminSettingsStore(admin_db_path) as store:
                store.set_value(
                    BETA_ALLOWLIST_SETTING,
                    "100",
                    changed_by="owner",
                )

            self.assertFalse(service.is_beta_allowed(42))
            self.assertTrue(service.is_beta_allowed(100))

    def test_build_translation_service_wires_user_activity_store(self):
        with TemporaryDirectory() as temp_dir:
            admin_db_path = Path(temp_dir) / "admin.sqlite3"
            service = build_translation_service(
                BotRuntimeConfig(
                    object_storage_root=str(Path(temp_dir) / "objects"),
                    persistent_jobs_db_path=str(Path(temp_dir) / "jobs.sqlite3"),
                    user_settings_db_path=str(Path(temp_dir) / "settings.sqlite3"),
                    admin_db_path=str(admin_db_path),
                )
            )
            self.addCleanup(service.close)

            service.prepare_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One.",
                source_language="en",
                target_language="uk",
            )

            with SQLiteUserActivityStore(admin_db_path) as activity_store:
                events = activity_store.list_events(actor_id="telegram:42")

            self.assertIn("document.estimated", [event.event_type for event in events])

    def test_build_translation_service_wires_and_owns_beta_safety_guard(self):
        class FakeBetaSafetyGuard:
            def __init__(self) -> None:
                self.closed = False

            def close(self) -> None:
                self.closed = True

        with TemporaryDirectory() as temp_dir:
            guard = FakeBetaSafetyGuard()
            with patch(
                "translator_service.bot.runtime.build_beta_safety_guard",
                return_value=guard,
            ):
                service = build_translation_service(
                    BotRuntimeConfig(
                        object_storage_root=str(Path(temp_dir) / "objects"),
                        persistent_jobs_db_path=str(Path(temp_dir) / "jobs.sqlite3"),
                        user_settings_db_path=str(Path(temp_dir) / "settings.sqlite3"),
                        admin_db_path=str(Path(temp_dir) / "admin.sqlite3"),
                    )
                )

            self.assertIs(service._beta_safety_guard, guard)
            service.close()
            self.assertTrue(guard.closed)

    def test_build_beta_safety_guard_uses_admin_db_path_and_live_settings(self):
        with TemporaryDirectory() as temp_dir:
            admin_db_path = Path(temp_dir) / "admin.sqlite3"
            guard = build_beta_safety_guard(
                BotRuntimeConfig(admin_db_path=str(admin_db_path))
            )
            self.addCleanup(guard.close)

            initial = guard.can_start_new_work()
            self.assertTrue(initial.allowed)

            with SQLiteAdminSettingsStore(admin_db_path) as store:
                store.set_value(
                    BETA_TRANSLATIONS_PAUSED_SETTING,
                    "true",
                    changed_by="owner",
                )

            paused = guard.can_start_new_work()
            self.assertFalse(paused.allowed)
            self.assertEqual(paused.reason_code, BETA_SAFETY_KILL_SWITCH)

    def test_build_translation_service_wires_persistent_txt_confirmation(self):
        with TemporaryDirectory() as temp_dir:
            service = build_translation_service(
                BotRuntimeConfig(
                    object_storage_root=str(Path(temp_dir) / "objects"),
                    persistent_jobs_db_path=str(Path(temp_dir) / "jobs.sqlite3"),
                    user_settings_db_path=str(Path(temp_dir) / "settings.sqlite3"),
                    admin_db_path=str(Path(temp_dir) / "admin.sqlite3"),
                    translation_run_log_root=str(Path(temp_dir) / "translation-runs"),
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
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=_RuntimeRecordingTranslator(),
            )

            self.assertEqual(job.id, "job-1")
            self.assertEqual(job.result_file_name, "notes.uk.txt")
            self.assertEqual(
                job.result_content.decode("utf-8"),
                "[uk] One.\n\n[uk] Two.",
            )

    def test_build_deepseek_translator_uses_key_pool_for_single_env_key(self):
        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEYS": "",
                "DEEPSEEK_API_KEY": "single-key",
                "DEEPSEEK_BASE_URL": "https://deepseek.test",
            },
            clear=False,
        ):
            translator = build_deepseek_translator(
                Settings(deepseek_model="deepseek-test")
            )

        self.assertIsInstance(translator, DeepSeekKeyPoolTranslator)
        snapshot = translator.snapshot()
        self.assertEqual([channel.label for channel in snapshot], ["deepseek-1"])
        self.assertEqual([channel.max_parallel_requests for channel in snapshot], [1])

    def test_build_deepseek_translator_uses_key_pool_for_multiple_keys(self):
        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEYS": "key-a, key-b",
                "DEEPSEEK_BASE_URL": "https://deepseek.test",
                "DEEPSEEK_MAX_PARALLEL_PER_KEY": "2",
                "DEEPSEEK_CHANNEL_COOLDOWN_SECONDS": "7",
                "DEEPSEEK_CHANNEL_MAX_COOLDOWN_SECONDS": "31",
                "DEEPSEEK_CHANNEL_WEIGHTS": "3, 1",
            },
            clear=False,
        ):
            translator = build_deepseek_translator(
                Settings(deepseek_model="deepseek-test")
            )

        self.assertIsInstance(translator, DeepSeekKeyPoolTranslator)
        snapshot = translator.snapshot()
        self.assertEqual(
            [channel.label for channel in snapshot],
            ["deepseek-1", "deepseek-2"],
        )
        self.assertEqual(
            [channel.max_parallel_requests for channel in snapshot],
            [2, 2],
        )
        self.assertEqual([channel.weight for channel in snapshot], [3, 1])

    def test_build_deepseek_translator_combines_admin_and_env_provider_keys(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    keys.add_key(
                        provider_id="deepseek",
                        label="stable",
                        plaintext="admin-key-a",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                        weight=4,
                        max_parallel_requests=3,
                    )
                    keys.add_key(
                        provider_id="deepseek",
                        label="dev",
                        plaintext="admin-key-b",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                        weight=1,
                        max_parallel_requests=2,
                    )
            with patch.dict(
                "os.environ",
                {
                    "DEEPSEEK_API_KEYS": "env-key-a, env-key-b",
                    "DEEPSEEK_BASE_URL": "https://deepseek.test",
                    "DEEPSEEK_MAX_PARALLEL_PER_KEY": "1",
                    "DEEPSEEK_CHANNEL_WEIGHTS": "1, 1",
                },
                clear=False,
            ):
                translator = build_deepseek_translator(
                    Settings(
                        admin_db_path=str(db_path),
                        admin_secret_master_key=MASTER_KEY,
                        deepseek_model="deepseek-test",
                    )
                )
                capacity = _deepseek_parallel_capacity(
                    Settings(
                        admin_db_path=str(db_path),
                        admin_secret_master_key=MASTER_KEY,
                    )
                )

        self.assertIsInstance(translator, ReloadableDeepSeekTranslator)
        snapshot = translator.snapshot()
        self.assertEqual(
            [channel.label for channel in snapshot],
            ["stable", "dev", "deepseek-1", "deepseek-2"],
        )
        self.assertEqual(
            [channel.max_parallel_requests for channel in snapshot],
            [3, 2, 1, 1],
        )
        self.assertEqual([channel.weight for channel in snapshot], [4, 1, 1, 1])
        self.assertEqual(capacity, 7)

    def test_admin_deepseek_translator_reloads_changed_key_pool(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            settings = Settings(
                admin_db_path=str(db_path),
                admin_secret_master_key=MASTER_KEY,
                deepseek_model="deepseek-test",
                admin_provider_runtime_reload_seconds=0.0,
            )
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    stable = keys.add_key(
                        provider_id="deepseek",
                        label="stable",
                        plaintext="admin-key-a",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                        weight=2,
                        max_parallel_requests=2,
                    )
                    dev = keys.add_key(
                        provider_id="deepseek",
                        label="dev",
                        plaintext="admin-key-b",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                        weight=1,
                        max_parallel_requests=1,
                    )

            translator = build_deepseek_translator(settings)
            self.assertIsInstance(translator, ReloadableDeepSeekTranslator)
            self.assertEqual(
                [channel.label for channel in translator.snapshot()],
                ["stable", "dev"],
            )

            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    keys.update_key(
                        provider_id="deepseek",
                        key_id=stable.key_id,
                        label="stable-v2",
                        weight=5,
                        max_parallel_requests=4,
                        actor_id="bootstrap-owner",
                        secret_describer=secrets.describe_secret,
                    )
                    keys.set_key_enabled(
                        provider_id="deepseek",
                        key_id=dev.key_id,
                        enabled=False,
                        actor_id="bootstrap-owner",
                        secret_describer=secrets.describe_secret,
                    )

            snapshot = translator.snapshot()

        self.assertEqual([channel.label for channel in snapshot], ["stable-v2"])
        self.assertEqual([channel.max_parallel_requests for channel in snapshot], [4])
        self.assertEqual([channel.weight for channel in snapshot], [5])

    def test_admin_deepseek_translator_honors_manual_reload_request(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            settings = Settings(
                admin_db_path=str(db_path),
                admin_secret_master_key=MASTER_KEY,
                deepseek_model="deepseek-test",
                admin_provider_runtime_reload_seconds=999.0,
            )
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    old_key = keys.add_key(
                        provider_id="deepseek",
                        label="old",
                        plaintext="admin-key-old",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                    )

            translator = build_deepseek_translator(settings)
            self.assertEqual(
                [channel.label for channel in translator.snapshot()],
                ["old"],
            )
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    keys.add_key(
                        provider_id="deepseek",
                        label="new",
                        plaintext="admin-key-new",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                    )
                    keys.set_key_enabled(
                        provider_id="deepseek",
                        key_id=old_key.key_id,
                        enabled=False,
                        actor_id="bootstrap-owner",
                        secret_describer=secrets.describe_secret,
                    )
            with SQLiteAIProviderRuntimeStore(db_path) as runtime:
                runtime.request_reload(
                    provider_id="deepseek",
                    actor_id="bootstrap-owner",
                )

            snapshot = translator.snapshot()
            with SQLiteAIProviderRuntimeStore(db_path) as runtime:
                status = runtime.get_status("deepseek")

        self.assertEqual([channel.label for channel in snapshot], ["new"])
        self.assertIsNotNone(status)
        self.assertEqual(status.source, "admin_store")
        self.assertEqual(status.status, "ok")
        self.assertEqual(status.active_channels[0].label, "new")

    def test_admin_deepseek_translator_uses_reloaded_key_for_translation(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            settings = Settings(
                admin_db_path=str(db_path),
                admin_secret_master_key=MASTER_KEY,
                deepseek_model="deepseek-test",
                admin_provider_runtime_reload_seconds=0.0,
            )
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    old_key = keys.add_key(
                        provider_id="deepseek",
                        label="old",
                        plaintext="admin-key-old",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                    )

            with patch(
                "translator_service.bot.runtime.DeepSeekClient",
                _RuntimeKeyEchoDeepSeekClient,
            ):
                translator = build_deepseek_translator(settings)
                first = translator.translate(
                    text="Hello",
                    source_language="en",
                    target_language="uk",
                )

                with SQLiteEncryptedSecretStore(
                    db_path,
                    master_key=MASTER_KEY,
                ) as secrets:
                    with SQLiteAIProviderKeyStore(db_path) as keys:
                        keys.add_key(
                            provider_id="deepseek",
                            label="new",
                            plaintext="admin-key-new",
                            actor_id="bootstrap-owner",
                            secret_store=secrets,
                        )
                        keys.set_key_enabled(
                            provider_id="deepseek",
                            key_id=old_key.key_id,
                            enabled=False,
                            actor_id="bootstrap-owner",
                            secret_describer=secrets.describe_secret,
                        )

                second = translator.translate(
                    text="Hello",
                    source_language="en",
                    target_language="uk",
                )

        self.assertEqual(first, "admin-key-old:uk:Hello")
        self.assertEqual(second, "admin-key-new:uk:Hello")

    def test_reloadable_deepseek_translator_records_channel_telemetry_snapshot(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            settings = Settings(
                admin_db_path=str(db_path),
                admin_secret_master_key=MASTER_KEY,
                deepseek_model="deepseek-test",
                admin_provider_runtime_reload_seconds=999.0,
            )
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    keys.add_key(
                        provider_id="deepseek",
                        label="stable",
                        plaintext="admin-key-secret",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                    )

            with (
                patch.dict(
                    "os.environ",
                    {"DEEPSEEK_API_KEY": "", "DEEPSEEK_API_KEYS": ""},
                    clear=False,
                ),
                patch(
                    "translator_service.bot.runtime.DeepSeekClient",
                    _RuntimeKeyEchoDeepSeekClient,
                ),
            ):
                translator = build_deepseek_translator(settings)
                snapshot = translator.snapshot()
                with SQLiteAIProviderRuntimeStore(db_path) as runtime:
                    status_after_snapshot = runtime.get_status("deepseek")

                translated = translator.translate(
                    text="Hello",
                    source_language="en",
                    target_language="uk",
                )
                with SQLiteAIProviderRuntimeStore(db_path) as runtime:
                    status_after_translate = runtime.get_status("deepseek")

        self.assertEqual([channel.label for channel in snapshot], ["stable"])
        self.assertEqual(translated, "admin-key-secret:uk:Hello")
        self.assertIsNotNone(status_after_snapshot)
        snapshot_channel = status_after_snapshot.active_channels[0]
        self.assertEqual(snapshot_channel.label, "stable")
        self.assertEqual(snapshot_channel.health, "healthy")
        self.assertEqual(snapshot_channel.active_requests, 0)
        self.assertEqual(snapshot_channel.total_started_requests, 0)

        self.assertIsNotNone(status_after_translate)
        translate_channel = status_after_translate.active_channels[0]
        self.assertEqual(status_after_translate.status, "ok")
        self.assertEqual(translate_channel.health, "healthy")
        self.assertEqual(translate_channel.active_requests, 0)
        self.assertEqual(translate_channel.total_started_requests, 1)
        self.assertEqual(translate_channel.total_successful_requests, 1)
        self.assertNotIn("admin-key-secret", repr(translate_channel))

    def test_reloadable_deepseek_translator_ignores_runtime_status_write_failure(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            settings = Settings(
                admin_db_path=str(db_path),
                admin_secret_master_key=MASTER_KEY,
                deepseek_model="deepseek-test",
                admin_provider_runtime_reload_seconds=999.0,
            )
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    keys.add_key(
                        provider_id="deepseek",
                        label="stable",
                        plaintext="admin-key-secret",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                    )

            with (
                patch.dict(
                    "os.environ",
                    {"DEEPSEEK_API_KEY": "", "DEEPSEEK_API_KEYS": ""},
                    clear=False,
                ),
                patch(
                    "translator_service.bot.runtime.DeepSeekClient",
                    _RuntimeKeyEchoDeepSeekClient,
                ),
            ):
                translator = build_deepseek_translator(settings)
                with patch(
                    "translator_service.bot.runtime._record_deepseek_runtime_status",
                    side_effect=RuntimeError("database is locked"),
                ):
                    translated = translator.translate(
                        text="Hello",
                        source_language="en",
                        target_language="uk",
                    )

        self.assertEqual(translated, "admin-key-secret:uk:Hello")

    def test_reloadable_deepseek_translator_uses_current_on_reload_check_failure(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            settings = Settings(
                admin_db_path=str(db_path),
                admin_secret_master_key=MASTER_KEY,
                deepseek_model="deepseek-test",
                admin_provider_runtime_reload_seconds=999.0,
            )
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    keys.add_key(
                        provider_id="deepseek",
                        label="stable",
                        plaintext="admin-key-secret",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                    )

            with (
                patch.dict(
                    "os.environ",
                    {"DEEPSEEK_API_KEY": "", "DEEPSEEK_API_KEYS": ""},
                    clear=False,
                ),
                patch(
                    "translator_service.bot.runtime.DeepSeekClient",
                    _RuntimeKeyEchoDeepSeekClient,
                ),
            ):
                translator = build_deepseek_translator(settings)
                with patch(
                    "translator_service.bot.runtime._consume_deepseek_reload_request",
                    side_effect=RuntimeError("database is locked"),
                ):
                    translated = translator.translate(
                        text="Hello",
                        source_language="en",
                        target_language="uk",
                    )

        self.assertEqual(translated, "admin-key-secret:uk:Hello")

    def test_reloadable_deepseek_translator_records_provider_adaptive_state(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            settings = Settings(
                admin_db_path=str(db_path),
                admin_secret_master_key=MASTER_KEY,
                deepseek_model="deepseek-test",
                admin_provider_runtime_reload_seconds=999.0,
            )
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    keys.add_key(
                        provider_id="deepseek",
                        label="stable",
                        plaintext="admin-key-secret",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                        max_parallel_requests=2,
                    )

            with (
                patch.dict(
                    "os.environ",
                    {"DEEPSEEK_API_KEY": "", "DEEPSEEK_API_KEYS": ""},
                    clear=False,
                ),
                patch(
                    "translator_service.bot.runtime.DeepSeekClient",
                    _RuntimeKeyEchoDeepSeekClient,
                ),
            ):
                translator = build_deepseek_translator(settings)
                translator.snapshot()
                with SQLiteAIProviderRuntimeStore(db_path) as runtime:
                    status = runtime.get_status("deepseek")

        self.assertIsNotNone(status)
        self.assertTrue(status.provider_state.adaptive_enabled)
        self.assertEqual(status.provider_state.current_limit, 1)
        self.assertEqual(status.provider_state.max_capacity, 2)
        self.assertEqual(status.provider_state.available_slots, 1)
        self.assertEqual(status.provider_state.circuit_state, "closed")

    def test_reloadable_deepseek_translator_exposes_available_parallel_slots(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            settings = Settings(
                admin_db_path=str(db_path),
                admin_secret_master_key=MASTER_KEY,
                deepseek_model="deepseek-test",
                admin_provider_runtime_reload_seconds=999.0,
            )
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    keys.add_key(
                        provider_id="deepseek",
                        label="stable",
                        plaintext="admin-key-secret",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                        max_parallel_requests=2,
                    )

            with (
                patch.dict(
                    "os.environ",
                    {"DEEPSEEK_API_KEY": "", "DEEPSEEK_API_KEYS": ""},
                    clear=False,
                ),
                patch(
                    "translator_service.bot.runtime.DeepSeekClient",
                    _RuntimeKeyEchoDeepSeekClient,
                ),
            ):
                translator = build_deepseek_translator(settings)
                slots = translator.available_parallel_slots()

        self.assertEqual(slots, 1)

    def test_admin_deepseek_translator_adds_admin_without_dropping_env(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            settings = Settings(
                admin_db_path=str(db_path),
                admin_secret_master_key=MASTER_KEY,
                deepseek_model="deepseek-test",
                admin_provider_runtime_reload_seconds=999.0,
            )

            with patch.dict(
                "os.environ",
                {"DEEPSEEK_API_KEY": "env-key"},
                clear=False,
            ):
                with patch(
                    "translator_service.bot.runtime.DeepSeekClient",
                    _RuntimeKeyEchoDeepSeekClient,
                ):
                    translator = build_deepseek_translator(settings)
                    first = translator.translate(
                        text="Hello",
                        source_language="en",
                        target_language="uk",
                    )

                    with SQLiteEncryptedSecretStore(
                        db_path,
                        master_key=MASTER_KEY,
                    ) as secrets:
                        with SQLiteAIProviderKeyStore(db_path) as keys:
                            keys.add_key(
                                provider_id="deepseek",
                                label="stable",
                                plaintext="admin-key",
                                actor_id="bootstrap-owner",
                                secret_store=secrets,
                            )
                    with SQLiteAIProviderRuntimeStore(db_path) as runtime:
                        runtime.request_reload(
                            provider_id="deepseek",
                            actor_id="bootstrap-owner",
                        )

                    second = translator.translate(
                        text="Hello",
                        source_language="en",
                        target_language="uk",
                    )
                    snapshot = translator.snapshot()

        self.assertIsInstance(translator, ReloadableDeepSeekTranslator)
        self.assertEqual(first, "env-key:uk:Hello")
        self.assertIn(second, {"admin-key:uk:Hello", "env-key:uk:Hello"})
        self.assertEqual(
            [channel.label for channel in snapshot],
            ["stable", "deepseek-1"],
        )

    def test_build_deepseek_translator_deduplicates_multiple_keys(self):
        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEYS": "key-a, key-a, key-b",
                "DEEPSEEK_BASE_URL": "https://deepseek.test",
            },
            clear=False,
        ):
            translator = build_deepseek_translator(
                Settings(deepseek_model="deepseek-test")
            )

        self.assertIsInstance(translator, DeepSeekKeyPoolTranslator)
        self.assertEqual(
            [channel.label for channel in translator.snapshot()],
            ["deepseek-1", "deepseek-2"],
        )

    def test_invalid_deepseek_channel_weights_fall_back_to_one(self):
        with self.assertLogs("translator_service.bot.runtime", level="WARNING") as logs:
            with patch.dict(
                "os.environ",
                {
                    "DEEPSEEK_API_KEYS": "key-a, key-b",
                    "DEEPSEEK_BASE_URL": "https://deepseek.test",
                    "DEEPSEEK_CHANNEL_WEIGHTS": "3",
                },
                clear=False,
            ):
                translator = build_deepseek_translator(
                    Settings(deepseek_model="deepseek-test")
                )

        self.assertIsInstance(translator, DeepSeekKeyPoolTranslator)
        self.assertEqual([channel.weight for channel in translator.snapshot()], [1, 1])
        self.assertIn("Ignoring invalid DeepSeek channel weights", logs.output[0])

    def test_deepseek_parallel_capacity_matches_keys_and_per_key_limit(self):
        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEYS": "key-a, key-b, key-a, key-c",
                "DEEPSEEK_MAX_PARALLEL_PER_KEY": "2",
            },
            clear=False,
        ):
            self.assertEqual(_deepseek_parallel_capacity_from_env(), 6)

    def test_deepseek_parallel_capacity_falls_back_to_single_key(self):
        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEY": "single-key",
                "DEEPSEEK_API_KEYS": "",
                "DEEPSEEK_MAX_PARALLEL_PER_KEY": "3",
            },
            clear=False,
        ):
            self.assertEqual(_deepseek_parallel_capacity_from_env(), 3)

    def test_deepseek_throttle_config_uses_safe_beta_defaults(self):
        with patch.dict("os.environ", {}, clear=True):
            config = _deepseek_throttle_config_from_env()

        self.assertTrue(config.enabled)
        self.assertEqual(config.initial_parallel, 1)
        self.assertEqual(config.min_parallel, 1)
        self.assertEqual(config.success_ramp_interval, 8)
        self.assertEqual(config.decrease_factor, 0.5)
        self.assertEqual(config.circuit_failure_threshold, 5)
        self.assertEqual(config.circuit_reset_seconds, 120.0)

    def test_deepseek_throttle_config_can_be_disabled_for_legacy_behavior(self):
        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_ADAPTIVE_THROTTLING_ENABLED": "false",
                "DEEPSEEK_ADAPTIVE_INITIAL_PARALLEL": "3",
                "DEEPSEEK_ADAPTIVE_MIN_PARALLEL": "2",
                "DEEPSEEK_ADAPTIVE_SUCCESS_RAMP_INTERVAL": "4",
                "DEEPSEEK_ADAPTIVE_DECREASE_FACTOR": "0.75",
                "DEEPSEEK_PROVIDER_CIRCUIT_FAILURE_THRESHOLD": "7",
                "DEEPSEEK_PROVIDER_CIRCUIT_RESET_SECONDS": "60",
            },
            clear=True,
        ):
            config = _deepseek_throttle_config_from_env()

        self.assertFalse(config.enabled)
        self.assertEqual(config.initial_parallel, 3)
        self.assertEqual(config.min_parallel, 2)
        self.assertEqual(config.success_ramp_interval, 4)
        self.assertEqual(config.decrease_factor, 0.75)
        self.assertEqual(config.circuit_failure_threshold, 7)
        self.assertEqual(config.circuit_reset_seconds, 60.0)

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

    async def test_schedules_message_edit_through_bot_api_when_message_has_context(
        self,
    ):
        message = BotBackedMessage()
        loop = asyncio.get_running_loop()

        future = _schedule_message_edit(
            loop=loop,
            message=message,
            text="Progress 2",
            reply_markup="inline-keyboard",
        )

        await asyncio.wrap_future(future)
        self.assertEqual(
            message.bot.edits,
            [("Progress 2", 100, 55, "inline-keyboard", "HTML")],
        )

    async def test_schedules_message_edit_with_html_parse_mode_for_expandable_quotes(
        self,
    ):
        message = BotBackedMessage()
        loop = asyncio.get_running_loop()

        future = _schedule_message_edit(
            loop=loop,
            message=message,
            text="<blockquote expandable>Preview</blockquote>",
        )

        await asyncio.wrap_future(future)
        self.assertEqual(message.bot.edits[0][4], "HTML")

    def test_progress_edit_scheduler_throttles_frequent_updates(self):
        progress_stats = {"last_edit_scheduled_at": 10.0}

        self.assertFalse(
            _should_schedule_progress_edit(
                progress_stats,
                now=12.0,
                min_interval_seconds=5.0,
            )
        )
        self.assertEqual(progress_stats["last_edit_scheduled_at"], 10.0)
        self.assertTrue(
            _should_schedule_progress_edit(
                progress_stats,
                now=15.0,
                min_interval_seconds=5.0,
            )
        )
        self.assertEqual(progress_stats["last_edit_scheduled_at"], 15.0)

    def test_message_edit_error_logs_retry_after_without_traceback(self):
        class FakeRetryAfter(Exception):
            retry_after = 13

        class FakeFuture:
            def result(self):
                raise FakeRetryAfter(
                    "Telegram server says - Flood control exceeded. "
                    "Retry in 13 seconds."
                )

        with self.assertLogs("translator_service.bot.runtime", level="WARNING") as logs:
            _log_message_edit_error(FakeFuture())

        self.assertIn("flood control", logs.output[0].lower())
        self.assertIn("13", logs.output[0])

    def test_cancel_inline_keyboard_uses_callback_data(self):
        keyboard = _cancel_inline_keyboard("en")

        button = keyboard.inline_keyboard[0][0]
        self.assertEqual(button.text, "Cancel")
        self.assertEqual(button.callback_data, "cancel_translation")

    def test_cancel_inline_keyboard_can_target_specific_book_job(self):
        keyboard = _cancel_inline_keyboard("en", job_id="job-1")

        button = keyboard.inline_keyboard[0][0]
        self.assertEqual(button.text, "Cancel")
        self.assertEqual(button.callback_data, "cancel_book:job-1")

    def test_main_menu_keyboard_uses_folioloom_buttons(self):
        keyboard = _main_menu_keyboard("en")

        self.assertEqual(
            [[button.text for button in row] for row in keyboard.keyboard],
            [
                ["📖 Translate a Book"],
                ["📚 My Books"],
                ["🧵 How It Works", "🌍 Language"],
                ["⚙️ Settings"],
                ["Help"],
            ],
        )

    def test_my_books_keyboard_opens_last_book_and_each_book_detail(self):
        keyboard = _my_books_keyboard(
            [
                {
                    "job_id": "job-1",
                    "file_name": "first.epub",
                    "status": "ready",
                    "has_result": True,
                },
                {
                    "job_id": "job-2",
                    "file_name": "second.docx",
                    "status": "translating",
                    "has_result": False,
                },
                {
                    "job_id": "job-3",
                    "file_name": "third.txt",
                    "status": "failed",
                    "has_result": False,
                    "can_resume": True,
                },
            ],
            interface_language="en",
        )

        self.assertEqual(
            [
                [(button.text, button.callback_data) for button in row]
                for row in keyboard.inline_keyboard
            ],
            [
                [("✅ Last Book", "book_detail:job-1")],
                [("✅ Book 1", "book_detail:job-1")],
                [("⚙️ Book 2", "book_detail:job-2")],
                [("↻ Book 3", "book_detail:job-3")],
            ],
        )

    def test_my_books_keyboard_does_not_mark_non_resumable_failed_book_as_resumable(
        self,
    ):
        keyboard = _my_books_keyboard(
            [
                {
                    "job_id": "job-1",
                    "file_name": "missing-source.txt",
                    "status": "failed",
                    "has_result": False,
                    "can_resume": False,
                },
            ],
            interface_language="en",
        )

        self.assertEqual(
            [
                [(button.text, button.callback_data) for button in row]
                for row in keyboard.inline_keyboard
            ],
            [
                [("Last Book", "book_detail:job-1")],
                [("Book 1", "book_detail:job-1")],
            ],
        )

    def test_my_book_detail_keyboard_uses_status_specific_actions(self):
        from translator_service.bot.runtime import _my_book_detail_keyboard

        keyboard = _my_book_detail_keyboard(
            {
                "job_id": "job-1",
                "has_result": True,
                "can_resume": True,
                "can_cancel": True,
            },
            interface_language="en",
        )

        self.assertEqual(
            [
                [(button.text, button.callback_data) for button in row]
                for row in keyboard.inline_keyboard
            ],
            [
                [("Download Translation", "download_book:job-1")],
                [("Continue Translation", "resume_book:job-1")],
                [("Cancel", "cancel_book:job-1")],
                [("Delete Book", "delete_book:job-1")],
                [("Back to My Books", "my_books")],
            ],
        )

    def test_duplicate_upload_keyboard_for_partial_result_links_my_books_recovery(self):
        from translator_service.bot.runtime import _duplicate_upload_keyboard

        keyboard = _duplicate_upload_keyboard(
            SimpleNamespace(
                job_id="job-1",
                status="partial",
                can_download_existing=True,
                can_open_existing=True,
                can_translate_again=True,
            ),
            interface_language="en",
        )

        self.assertEqual(
            [
                [(button.text, button.callback_data) for button in row]
                for row in keyboard.inline_keyboard
            ],
            [
                [("Download Translation", "download_book:job-1")],
                [("Open Existing Translation", "book_detail:job-1")],
                [("Translate Again", "duplicate_upload_translate_again")],
                [("Back", "duplicate_upload_back")],
            ],
        )
        self.assertNotIn(
            "resume_book",
            "\n".join(
                button.callback_data
                for row in keyboard.inline_keyboard
                for button in row
            ),
        )

    async def test_callback_message_helper_edits_existing_inline_message(self):
        message = EditableMessage()
        await _edit_callback_message(
            message,
            text="My Books",
            reply_markup="inline-keyboard",
        )

        self.assertEqual(message.edited_texts, ["My Books"])
        self.assertEqual(message.edited_reply_markups, ["inline-keyboard"])

    async def test_callback_message_helper_drops_reply_keyboard_markup(self):
        message = EditableMessage()
        await _edit_callback_message(
            message,
            text="Book deleted.",
            reply_markup=_main_menu_keyboard("en"),
        )

        self.assertEqual(message.edited_texts, ["Book deleted."])
        self.assertEqual(message.edited_reply_markups, [None])

    def test_progress_preview_helper_respects_user_setting(self):
        with TemporaryDirectory() as temp_dir:
            service = build_translation_service(
                BotRuntimeConfig(
                    object_storage_root=str(Path(temp_dir) / "objects"),
                    persistent_jobs_db_path=str(Path(temp_dir) / "jobs.sqlite3"),
                    user_settings_db_path=str(Path(temp_dir) / "settings.sqlite3"),
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
                ["Показывать отрывок"],
                ["Сбросить настройки"],
                ["Главное меню"],
            ],
        )

    def test_progress_message_uses_current_user_interface_language(self):
        with TemporaryDirectory() as temp_dir:
            service = build_translation_service(
                BotRuntimeConfig(
                    object_storage_root=str(Path(temp_dir) / "objects"),
                    persistent_jobs_db_path=str(Path(temp_dir) / "jobs.sqlite3"),
                    user_settings_db_path=str(Path(temp_dir) / "settings.sqlite3"),
                )
            )
            self.addCleanup(service.close)
            service.set_interface_language(user_telegram_id=42, language_code="ru")

            text = _progress_message_for_current_user_language(
                service=service,
                user_telegram_id=42,
                completed_fragments=1,
                total_fragments=4,
                estimated_total_seconds=120,
                elapsed_seconds=30,
                last_translated_text="переведенный отрывок",
                activity_indicator="·",
                activity_phrase_index=1,
            )

            self.assertIn("Прогресс перевода", text)
            self.assertIn("Осталось", text)
            self.assertIn("Последний переведенный отрывок", text)

    def test_polled_progress_estimate_uses_stored_baseline(self):
        progress = type(
            "Progress",
            (),
            {
                "completed_fragments": 1,
                "total_fragments": 4,
                "estimated_seconds": 300,
            },
        )()

        estimated_total = _polled_progress_estimated_total_seconds(
            progress,
            elapsed_seconds=10,
        )

        self.assertEqual(estimated_total, 235)

    def test_document_size_guard_uses_telegram_metadata_before_download(self):
        class Document:
            file_size = 6 * 1024 * 1024

        self.assertTrue(_document_exceeds_upload_limit(Document(), max_upload_mb=5))
        self.assertFalse(_document_exceeds_upload_limit(Document(), max_upload_mb=6))

    def test_translation_progress_log_excludes_last_translated_fragment_preview(self):
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
        self.assertNotIn("last_translated=", output.getvalue())
        self.assertNotIn("translated text with a second line", output.getvalue())
        self.assertIn("translated_chars=34", output.getvalue())
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
        flattened = "".join(
            symbol for pattern in HEARTBEAT_PATTERNS.values() for symbol in pattern
        )
        self.assertNotIn("❤️", flattened)
        self.assertNotIn("💕", flattened)

    def test_heartbeat_pattern_choice_is_stable_for_order_seed(self):
        first = _choose_heartbeat_pattern_name(
            user_telegram_id=42,
            file_name="book.epub",
        )
        second = _choose_heartbeat_pattern_name(
            user_telegram_id=42,
            file_name="book.epub",
        )

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

    def test_cancelled_progress_update_is_reported_as_stopping(self):
        output = io.StringIO()

        with redirect_stdout(output):
            _print_translation_progress_update(
                progress=TranslationProgress(
                    completed_fragments=35,
                    total_fragments=1002,
                    source_text="One.",
                    translated_text="Один.",
                    elapsed_seconds=94.84,
                    prompt_tokens=51695,
                    completion_tokens=3986,
                    total_tokens=55681,
                ),
                elapsed_total_seconds=251,
                is_stopping=True,
            )

        text = output.getvalue()
        self.assertIn("TRANSLATION STOPPING", text)
        self.assertIn("fragment=35/1002", text)
        self.assertNotIn("status=ok", text)

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
