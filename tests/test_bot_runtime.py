import asyncio
import io
import unittest
from base64 import urlsafe_b64encode
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from translator_service.admin.ai_provider_keys import SQLiteAIProviderKeyStore
from translator_service.admin.provider_runtime import SQLiteAIProviderRuntimeStore
from translator_service.admin.secrets import SQLiteEncryptedSecretStore
from translator_service.bot.runtime import (
    HEARTBEAT_PATTERNS,
    BotRuntimeConfig,
    ReloadableDeepSeekTranslator,
    _answer_callback_if_spam,
    _CallbackSpamGuard,
    _cancel_inline_keyboard,
    _choose_heartbeat_pattern_name,
    _confirm_pending_translation,
    _deepseek_parallel_capacity,
    _deepseek_parallel_capacity_from_env,
    _document_exceeds_upload_limit,
    _edit_callback_message,
    _include_progress_preview,
    _is_language_button_text,
    _log_message_edit_error,
    _main_menu_keyboard,
    _my_books_keyboard,
    _next_heartbeat_frame,
    _next_spinner_frame,
    _print_translation_progress,
    _print_translation_progress_update,
    _print_translation_summary,
    _progress_message_for_current_user_language,
    _schedule_message_edit,
    _settings_keyboard,
    _should_schedule_progress_edit,
    _UserActionInFlightGuard,
    build_deepseek_translator,
    build_default_pricing_rules,
    build_translation_service,
)
from translator_service.config import Settings
from translator_service.deepseek_client import DeepSeekClient
from translator_service.deepseek_key_pool import DeepSeekKeyPoolTranslator
from translator_service.document_sandbox import DocumentSandbox
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

    async def answer(self, text: str, reply_markup=None, **kwargs):
        self.answers.append((text, reply_markup))
        return EditableMessage()


class _RuntimeRecordingTranslator:
    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        return f"[{target_language}] {text}"


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

    def test_build_translation_service_wires_persistent_txt_confirmation(self):
        with TemporaryDirectory() as temp_dir:
            service = build_translation_service(
                BotRuntimeConfig(
                    object_storage_root=str(Path(temp_dir) / "objects"),
                    persistent_jobs_db_path=str(Path(temp_dir) / "jobs.sqlite3"),
                    user_settings_db_path=str(Path(temp_dir) / "settings.sqlite3"),
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
            self.assertEqual(
                job.result_content.decode("utf-8"),
                "[uk] One.\n\n[uk] Two.",
            )

    def test_build_deepseek_translator_keeps_single_key_client(self):
        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEY": "single-key",
                "DEEPSEEK_BASE_URL": "https://deepseek.test",
            },
            clear=False,
        ):
            translator = build_deepseek_translator(
                Settings(deepseek_model="deepseek-test")
            )

        self.assertIsInstance(translator, DeepSeekClient)

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

    def test_build_deepseek_translator_prefers_admin_provider_keys(self):
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
        self.assertEqual([channel.label for channel in snapshot], ["stable", "dev"])
        self.assertEqual(
            [channel.max_parallel_requests for channel in snapshot],
            [3, 2],
        )
        self.assertEqual([channel.weight for channel in snapshot], [4, 1])
        self.assertEqual(capacity, 5)

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

    def test_admin_deepseek_translator_switches_from_env_without_restart(
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

        self.assertIsInstance(translator, ReloadableDeepSeekTranslator)
        self.assertEqual(first, "env-key:uk:Hello")
        self.assertEqual(second, "admin-key:uk:Hello")

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
                {"job_id": "job-1", "file_name": "first.epub", "has_result": True},
                {"job_id": "job-2", "file_name": "second.docx", "has_result": False},
                {"job_id": "job-3", "file_name": "third.txt", "has_result": True},
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
                [("Book 2", "book_detail:job-2")],
                [("Book 3", "book_detail:job-3")],
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
