import asyncio
import hashlib
import inspect
import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

from translator_service.admin.beta_safety_settings import (
    beta_safety_rates_from_settings,
    load_beta_safety_limits,
)
from translator_service.admin.provider_runtime import (
    AIProviderRuntimeChannel,
    AIProviderRuntimeProviderState,
    SQLiteAIProviderRuntimeStore,
)
from translator_service.admin.settings import SQLiteAdminSettingsStore
from translator_service.ai_provider_runtime import load_ai_provider_runtime_keys
from translator_service.beta_access import (
    BetaAccessDenied,
    SQLiteBackedBetaAccessPolicy,
    load_beta_access_policy,
)
from translator_service.beta_safety_store import (
    ConfiguredBetaSafetyGuard,
    SQLiteBetaSafetyStore,
)
from translator_service.bot.messages import (
    build_back_to_menu_message,
    build_book_deleted_message,
    build_cancel_requested_message,
    build_delete_book_confirmation_message,
    build_delete_unavailable_message,
    build_download_unavailable_message,
    build_duplicate_upload_message,
    build_help_message,
    build_how_it_works_message,
    build_language_selected_message,
    build_language_selection_message,
    build_main_menu,
    build_my_book_detail_message,
    build_my_books_message,
    build_no_pending_translation_message,
    build_nothing_to_cancel_message,
    build_pending_translation_message,
    build_preview_required_message,
    build_preview_translation_message,
    build_rights_confirmation_message,
    build_same_language_translation_blocked_message,
    build_settings_message,
    build_settings_reset_message,
    build_start_message,
    build_translation_job_status_message,
    build_translation_language_selection_message,
    build_translation_mode_required_message,
    build_translation_mode_selection_message,
    build_translation_progress_message,
    build_unknown_text_message,
    build_upload_error_message,
    build_upload_prompt_message,
    get_back_text,
    get_back_to_my_books_text,
    get_cancel_text,
    get_confirm_delete_book_text,
    get_confirm_rights_text,
    get_confirm_translation_text,
    get_continue_translation_text,
    get_delete_book_text,
    get_download_translation_text,
    get_duplicate_open_existing_text,
    get_duplicate_translate_again_text,
    get_keep_book_text,
    get_last_book_text,
    get_main_menu_button_text,
    get_main_menu_text,
    get_open_book_text,
    get_reset_settings_text,
    get_toggle_progress_preview_text,
    get_translation_mode_book_manuscript_text,
    get_translation_mode_document_form_text,
    is_back_text,
    is_cancel_text,
    is_confirm_rights_text,
    is_confirm_translation_text,
    is_continue_translation_text,
    is_help_text,
    is_how_it_works_text,
    is_language_menu_text,
    is_main_menu_text,
    is_my_books_text,
    is_reset_settings_text,
    is_settings_text,
    is_toggle_progress_preview_text,
    is_translate_book_text,
    is_translation_mode_button_text,
    translation_mode_for_button_text,
)
from translator_service.bot_translation_service import (
    BotTranslationService,
    PreviewAcceptanceRequired,
    PreviewTranslationError,
    RightsConfirmationRequired,
    SameLanguageTranslationBlocked,
    TranslationModeRequired,
)
from translator_service.config import Settings
from translator_service.deepseek_client import DeepSeekClient
from translator_service.deepseek_key_pool import (
    DeepSeekChannelConfig,
    DeepSeekKeyPoolTranslator,
)
from translator_service.document_sandbox import DocumentSandbox, DocumentSandboxLimits
from translator_service.document_scanner import (
    ClamdDocumentScanner,
    DocumentScanner,
    LimitedConcurrencyDocumentScanner,
)
from translator_service.documents import FileTooLargeError, UnsupportedDocumentError
from translator_service.extractors import TextExtractionError
from translator_service.file_storage import LocalObjectStorage
from translator_service.job_runner import (
    InMemoryTranslationJobRepository,
    TranslationJob,
    TranslationJobStatus,
)
from translator_service.languages import (
    SUPPORTED_TARGET_LANGUAGES,
    find_language_by_button_text,
)
from translator_service.order_estimates import DocumentEstimationNotReadyError
from translator_service.persistent_job_store import open_persistent_job_store
from translator_service.pricing import PricingRules
from translator_service.provider_throttle import ProviderThrottleConfig
from translator_service.security_telemetry import (
    SecurityCooldownActive,
    SecurityCooldownPolicy,
    SecurityThresholdPolicy,
)
from translator_service.translation_jobs import TextTranslator, TranslationProgress
from translator_service.user_activity import SQLiteUserActivityStore
from translator_service.users import SQLiteUserSettingsRepository

logger = logging.getLogger(__name__)

TRANSLATION_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
TRANSLATION_SPINNER_INTERVAL_SECONDS = 5
TRANSLATION_PROGRESS_EDIT_MIN_INTERVAL_SECONDS = 5
HEARTBEAT_PATTERNS = {
    "calm_dots": ("·", "•", "●", "•"),
    "fleuron": ("❦", "❧", "❦", "❧"),
    "editorial": ("¶", "§", "¶", "§"),
    "page": ("□", "▣", "■", "▣"),
    "star": ("✦", "✧", "✦", "✧"),
}
_BOOK_ACTIVE_STATUS_INDICATOR_STATUSES = {
    "queued",
    "translating",
    "assembling",
    "cancel_requested",
}
_BOOK_RECOVERABLE_STATUS_INDICATOR_STATUSES = {
    "cancelled",
    "failed",
    "interrupted",
    "partial",
    "paused",
}
TELEGRAM_BOT_API_DOWNLOAD_LIMIT_MB = 20


@dataclass(frozen=True)
class BotRuntimeConfig:
    source_language: str = "auto"
    target_language: str = "en"
    max_fragment_chars: int = 4_000
    max_upload_mb: int = 50
    require_upload_scan: bool = False
    upload_scanner_backend: str = "none"
    upload_scan_max_concurrency: int = 1
    upload_scan_backpressure_timeout_seconds: float = 1.0
    clamd_host: str = "127.0.0.1"
    clamd_port: int = 3310
    clamd_timeout_seconds: float = 10.0
    clamd_chunk_size_bytes: int = 65_536
    clamd_response_limit_bytes: int = 4_096
    object_storage_root: str = "var/object-storage"
    persistent_jobs_db_path: str = "var/jobs.sqlite3"
    scheduler_backend: str = "sqlite"
    postgres_dsn: str = "postgresql://translator:translator@localhost:5432/translator"
    user_settings_db_path: str = "var/user-settings.sqlite3"
    admin_db_path: str = "var/admin.sqlite3"
    translation_run_log_root: str = "var/translation-runs"
    max_parallel_work_units: int = 1
    provider_parallel_capacity: int = 1
    defer_persistent_jobs_to_worker: bool = False
    security_max_events_per_run: int = 20
    security_max_unsafe_model_outputs_per_run: int = 3
    security_max_repair_failures_per_run: int = 1
    security_user_cooldown_thresholds_per_window: int = 2
    security_user_cooldown_window_seconds: int = 3600
    security_user_cooldown_seconds: int = 900
    callback_spam_min_interval_seconds: float = 0.7
    callback_spam_burst_limit: int = 20
    callback_spam_burst_window_seconds: float = 10.0
    user_action_lock_ttl_seconds: float = 900.0
    beta_allowlist_enabled: bool = False
    beta_allowlist_telegram_ids: tuple[int, ...] = ()
    beta_translations_paused: bool = False
    beta_global_daily_cost_cap_usd: float = 5.0
    beta_global_monthly_cost_cap_usd: float = 50.0
    beta_user_daily_cost_cap_usd: float = 1.0
    beta_user_monthly_cost_cap_usd: float = 10.0
    beta_user_daily_job_limit: int = 3
    beta_max_job_estimated_cost_usd: float = 2.0
    beta_cost_input_usd_per_million: float = 0.28
    beta_cost_output_usd_per_million: float = 1.10
    beta_cost_warning_fraction: float = 0.8


class _CallbackSpamGuard:
    def __init__(
        self,
        *,
        min_interval_seconds: float,
        burst_limit: int,
        burst_window_seconds: float,
        clock=time.monotonic,
    ) -> None:
        self._min_interval_seconds = max(0.0, min_interval_seconds)
        self._burst_limit = max(1, burst_limit)
        self._burst_window_seconds = max(0.1, burst_window_seconds)
        self._clock = clock
        self._last_action_at: dict[tuple[int, str], float] = {}
        self._user_action_times: dict[int, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, *, user_id: int, action: str) -> bool:
        now = self._clock()
        normalized_action = action or "unknown"
        key = (user_id, normalized_action)
        with self._lock:
            recent_times = [
                action_at
                for action_at in self._user_action_times.get(user_id, [])
                if now - action_at <= self._burst_window_seconds
            ]
            if len(recent_times) >= self._burst_limit:
                self._user_action_times[user_id] = recent_times
                return False

            last_action_at = self._last_action_at.get(key)
            if (
                last_action_at is not None
                and now - last_action_at < self._min_interval_seconds
            ):
                self._user_action_times[user_id] = recent_times
                return False

            recent_times.append(now)
            self._user_action_times[user_id] = recent_times
            self._last_action_at[key] = now
            return True


class _UserActionInFlightGuard:
    def __init__(
        self,
        *,
        ttl_seconds: float,
        clock=time.monotonic,
    ) -> None:
        self._ttl_seconds = max(1.0, ttl_seconds)
        self._clock = clock
        self._expires_at: dict[tuple[int, str], float] = {}
        self._lock = threading.Lock()

    def try_begin(self, *, user_id: int, action: str) -> bool:
        now = self._clock()
        key = (user_id, action or "unknown")
        with self._lock:
            expires_at = self._expires_at.get(key)
            if expires_at is not None and expires_at > now:
                return False
            self._expires_at[key] = now + self._ttl_seconds
            return True

    def finish(self, *, user_id: int, action: str) -> None:
        key = (user_id, action or "unknown")
        with self._lock:
            self._expires_at.pop(key, None)


def build_default_pricing_rules() -> PricingRules:
    return PricingRules(
        deepseek_input_usd_per_million_tokens=0.28,
        expected_output_multiplier=1.2,
        service_markup_multiplier=3.0,
        minimum_price_usd=0.10,
    )


def build_polling_started_message() -> str:
    return "Telegram bot polling started. Open Telegram and send /start."


def build_beta_safety_guard(config: BotRuntimeConfig) -> ConfiguredBetaSafetyGuard:
    beta_safety_store = SQLiteBetaSafetyStore(config.admin_db_path)

    def load_limits():
        with SQLiteAdminSettingsStore(config.admin_db_path) as settings_store:
            return load_beta_safety_limits(settings_store, config)

    return ConfiguredBetaSafetyGuard(
        store=beta_safety_store,
        limits_loader=load_limits,
        rates_loader=lambda: beta_safety_rates_from_settings(config),
    )


def build_document_scanner(config: BotRuntimeConfig) -> DocumentScanner | None:
    backend = config.upload_scanner_backend.strip().lower()
    if backend in {"", "none", "disabled"}:
        return None
    if backend != "clamd":
        raise ValueError(f"Unsupported upload scanner backend: {backend}")

    scanner: DocumentScanner = ClamdDocumentScanner(
        host=config.clamd_host,
        port=config.clamd_port,
        timeout_seconds=config.clamd_timeout_seconds,
        chunk_size=config.clamd_chunk_size_bytes,
        response_limit_bytes=config.clamd_response_limit_bytes,
    )
    return LimitedConcurrencyDocumentScanner(
        scanner,
        max_concurrent_scans=config.upload_scan_max_concurrency,
        acquire_timeout_seconds=config.upload_scan_backpressure_timeout_seconds,
        scanner_name="clamd",
    )


def bot_runtime_config_from_settings(settings: Settings) -> BotRuntimeConfig:
    return BotRuntimeConfig(
        max_upload_mb=settings.max_upload_mb,
        require_upload_scan=settings.require_upload_scan,
        upload_scanner_backend=settings.upload_scanner_backend,
        upload_scan_max_concurrency=settings.upload_scan_max_concurrency,
        upload_scan_backpressure_timeout_seconds=(
            settings.upload_scan_backpressure_timeout_seconds
        ),
        clamd_host=settings.clamd_host,
        clamd_port=settings.clamd_port,
        clamd_timeout_seconds=settings.clamd_timeout_seconds,
        clamd_chunk_size_bytes=settings.clamd_chunk_size_bytes,
        clamd_response_limit_bytes=settings.clamd_response_limit_bytes,
        object_storage_root=settings.object_storage_root,
        persistent_jobs_db_path=settings.persistent_jobs_db_path,
        scheduler_backend=settings.scheduler_backend,
        postgres_dsn=settings.postgres_dsn,
        user_settings_db_path=settings.user_settings_db_path,
        admin_db_path=settings.admin_db_path,
        translation_run_log_root=settings.translation_run_log_root,
        max_parallel_work_units=settings.translation_max_parallel_units,
        provider_parallel_capacity=_deepseek_parallel_capacity(settings),
        defer_persistent_jobs_to_worker=settings.bot_defer_persistent_jobs_to_worker,
        security_max_events_per_run=settings.security_max_events_per_run,
        security_max_unsafe_model_outputs_per_run=(
            settings.security_max_unsafe_model_outputs_per_run
        ),
        security_max_repair_failures_per_run=(
            settings.security_max_repair_failures_per_run
        ),
        security_user_cooldown_thresholds_per_window=(
            settings.security_user_cooldown_thresholds_per_window
        ),
        security_user_cooldown_window_seconds=(
            settings.security_user_cooldown_window_seconds
        ),
        security_user_cooldown_seconds=settings.security_user_cooldown_seconds,
        beta_allowlist_enabled=settings.beta_allowlist_enabled,
        beta_allowlist_telegram_ids=tuple(
            sorted(load_beta_access_policy(settings).allowed_telegram_ids)
        ),
        beta_translations_paused=settings.beta_translations_paused,
        beta_global_daily_cost_cap_usd=settings.beta_global_daily_cost_cap_usd,
        beta_global_monthly_cost_cap_usd=settings.beta_global_monthly_cost_cap_usd,
        beta_user_daily_cost_cap_usd=settings.beta_user_daily_cost_cap_usd,
        beta_user_monthly_cost_cap_usd=settings.beta_user_monthly_cost_cap_usd,
        beta_user_daily_job_limit=settings.beta_user_daily_job_limit,
        beta_max_job_estimated_cost_usd=settings.beta_max_job_estimated_cost_usd,
        beta_cost_input_usd_per_million=settings.beta_cost_input_usd_per_million,
        beta_cost_output_usd_per_million=settings.beta_cost_output_usd_per_million,
        beta_cost_warning_fraction=settings.beta_cost_warning_fraction,
    )


def build_translation_service(config: BotRuntimeConfig) -> BotTranslationService:
    beta_safety_guard = build_beta_safety_guard(config)
    return BotTranslationService(
        job_repository=InMemoryTranslationJobRepository(),
        pricing_rules=build_default_pricing_rules(),
        max_upload_mb=config.max_upload_mb,
        max_fragment_chars=config.max_fragment_chars,
        require_upload_scan=config.require_upload_scan,
        document_scanner=build_document_scanner(config),
        file_storage=LocalObjectStorage(config.object_storage_root),
        persistent_job_store=open_persistent_job_store(config),
        translation_run_log_root=config.translation_run_log_root,
        user_settings_repository=SQLiteUserSettingsRepository(
            config.user_settings_db_path,
        ),
        activity_store=SQLiteUserActivityStore(config.admin_db_path),
        max_parallel_work_units=config.max_parallel_work_units,
        provider_parallel_capacity=config.provider_parallel_capacity,
        use_scheduler_runner=config.scheduler_backend == "postgres",
        defer_persistent_jobs_to_worker=config.defer_persistent_jobs_to_worker,
        document_sandbox=DocumentSandbox(
            limits=DocumentSandboxLimits(timeout_seconds=15.0),
        ),
        security_threshold_policy=SecurityThresholdPolicy(
            max_events_per_run=config.security_max_events_per_run,
            max_unsafe_model_outputs_per_run=(
                config.security_max_unsafe_model_outputs_per_run
            ),
            max_repair_failures_per_run=config.security_max_repair_failures_per_run,
        ),
        security_cooldown_policy=SecurityCooldownPolicy(
            max_thresholds_per_window=(
                config.security_user_cooldown_thresholds_per_window
            ),
            window_seconds=config.security_user_cooldown_window_seconds,
            cooldown_seconds=config.security_user_cooldown_seconds,
        ),
        beta_access_policy=SQLiteBackedBetaAccessPolicy(
            admin_db_path=config.admin_db_path,
            fallback_telegram_ids=config.beta_allowlist_telegram_ids,
            fallback_enabled=config.beta_allowlist_enabled,
        ),
        beta_safety_guard=beta_safety_guard,
        beta_safety_rates=beta_safety_rates_from_settings(config),
        beta_safety_guard_owned=True,
    )


def build_deepseek_translator(settings: Settings) -> TextTranslator:
    if settings.admin_secret_master_key:
        return ReloadableDeepSeekTranslator(settings=settings)

    channels = _deepseek_env_channel_configs()
    if not channels:
        raise RuntimeError("DEEPSEEK_API_KEY or DEEPSEEK_API_KEYS is not set")
    return _deepseek_translator_from_channels(settings, channels)


class ReloadableDeepSeekTranslator:
    provider_id = "deepseek"

    def __init__(
        self,
        *,
        settings: Settings,
        clock=time.monotonic,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._reload_interval_seconds = max(
            0.0,
            settings.admin_provider_runtime_reload_seconds,
        )
        self._lock = threading.RLock()
        self._last_usage = threading.local()
        self._provider_slot_channel_id = threading.local()
        self._signature: tuple[object, ...] | None = None
        self._translator: TextTranslator | None = None
        self._channels: list[DeepSeekChannelConfig] = []
        self._runtime_source = "admin_store"
        self._runtime_status = "missing_keys"
        self._runtime_error: str | None = None
        self._next_reload_at = 0.0
        with self._lock:
            self._reload_locked(now=self._clock())

    @property
    def last_usage(self):
        return getattr(self._last_usage, "value", None)

    def snapshot(self):
        with self._lock:
            now = self._clock()
            self._reload_if_due_locked(now=now)
            translator = self._translator
            channels = list(self._channels)
            source = self._runtime_source
            status = self._runtime_status
            error = self._runtime_error
        if translator is None:
            return []
        snapshot = getattr(translator, "snapshot", None)
        if snapshot is None:
            return channels
        snapshots = snapshot()
        provider_snapshot = _provider_snapshot_from_translator(translator)
        self._record_runtime_snapshot(
            source=source,
            status=status,
            channels=channels,
            snapshots=snapshots,
            provider_snapshot=provider_snapshot,
            error=error,
        )
        return snapshots

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        translator = self._current_translator()
        try:
            channel_id = getattr(self._provider_slot_channel_id, "value", None)
            if channel_id is None:
                translated = translator.translate(
                    text=text,
                    source_language=source_language,
                    target_language=target_language,
                )
            else:
                channel_context = getattr(
                    translator,
                    "provider_slot_channel_lease",
                    None,
                )
                if not callable(channel_context):
                    raise RuntimeError(
                        "DeepSeek provider slot channel lease is not available"
                    )
                with channel_context(channel_id):
                    translated = translator.translate(
                        text=text,
                        source_language=source_language,
                        target_language=target_language,
                    )
        finally:
            self._record_current_runtime_snapshot(translator)
        self._last_usage.value = getattr(translator, "last_usage", None)
        return translated

    def available_parallel_slots(self) -> int:
        translator = self._current_translator()
        available = getattr(translator, "available_parallel_slots", None)
        if available is None:
            return 1
        return max(0, int(available()))

    def provider_slot_inventory(self):
        translator = self._current_translator()
        inventory = getattr(translator, "provider_slot_inventory", None)
        if not callable(inventory):
            return []
        return list(inventory())

    def provider_capacity_caps(self):
        translator = self._current_translator()
        capacity_caps = getattr(translator, "provider_capacity_caps", None)
        if not callable(capacity_caps):
            return []
        return list(capacity_caps())

    @contextmanager
    def provider_slot_channel_lease(self, channel_id: str):
        previous = getattr(self._provider_slot_channel_id, "value", None)
        had_previous = hasattr(self._provider_slot_channel_id, "value")
        self._provider_slot_channel_id.value = channel_id
        try:
            yield
        finally:
            if had_previous:
                self._provider_slot_channel_id.value = previous
            else:
                del self._provider_slot_channel_id.value

    def _current_translator(self) -> TextTranslator:
        with self._lock:
            now = self._clock()
            self._reload_if_due_locked(now=now)
            if self._translator is None:
                raise RuntimeError("No active DeepSeek admin provider keys are set")
            return self._translator

    def _reload_if_due_locked(self, *, now: float) -> None:
        try:
            reload_requested = _consume_deepseek_reload_request(self._settings)
        except Exception:
            if self._translator is None:
                raise
            logger.warning(
                "DeepSeek runtime reload check skipped: provider_id=deepseek",
                exc_info=True,
            )
            self._next_reload_at = _next_best_effort_reload_at(
                now=now,
                reload_interval_seconds=self._reload_interval_seconds,
            )
            return

        if not reload_requested and now < self._next_reload_at:
            return

        try:
            self._reload_locked(
                now=now,
                reload_requested=reload_requested,
            )
        except Exception:
            if self._translator is None:
                raise
            logger.warning(
                "DeepSeek runtime reload skipped: provider_id=deepseek",
                exc_info=True,
            )
            self._next_reload_at = _next_best_effort_reload_at(
                now=now,
                reload_interval_seconds=self._reload_interval_seconds,
            )

    def _record_current_runtime_snapshot(self, translator: TextTranslator) -> None:
        snapshot = getattr(translator, "snapshot", None)
        if snapshot is None:
            return
        with self._lock:
            source = self._runtime_source
            status = self._runtime_status
            channels = list(self._channels)
            error = self._runtime_error
        self._record_runtime_snapshot(
            source=source,
            status=status,
            channels=channels,
            snapshots=snapshot(),
            provider_snapshot=_provider_snapshot_from_translator(translator),
            error=error,
        )

    def _record_runtime_snapshot(
        self,
        *,
        source: str,
        status: str,
        channels: list[DeepSeekChannelConfig],
        snapshots,
        provider_snapshot,
        error: str | None,
    ) -> None:
        runtime_channels = tuple(
            _runtime_channel_from_snapshot(snapshot) for snapshot in snapshots
        )
        provider_state = (
            _runtime_provider_state_from_snapshot(provider_snapshot)
            if provider_snapshot is not None
            else AIProviderRuntimeProviderState()
        )
        _record_deepseek_runtime_status_best_effort(
            self._settings,
            source=source,
            status=_deepseek_runtime_status_from_channels(
                status,
                runtime_channels,
                provider_state,
            ),
            channels=channels,
            error=error,
            runtime_channels=runtime_channels,
            provider_state=provider_state,
        )

    def _reload_locked(
        self,
        *,
        now: float,
        reload_requested: bool = False,
    ) -> None:
        runtime_keys = load_ai_provider_runtime_keys(
            self._settings,
            provider_id="deepseek",
        )
        env_channels = _deepseek_env_channel_configs()
        source = "admin_store"
        channels = [
            *_deepseek_admin_channel_configs(runtime_keys),
            *env_channels,
        ]
        status = "ok" if channels else "missing_keys"
        error = None if channels else "No active DeepSeek admin or env keys."
        if not channels:
            source = "env_fallback"
            status = "ok" if channels else "missing_keys"
            error = None if channels else "No active DeepSeek admin or env keys."
        elif runtime_keys and env_channels:
            source = "admin_store+env"
        elif env_channels:
            source = "env_fallback"
        self._runtime_source = source
        self._runtime_status = status
        self._runtime_error = error
        signature = (source, tuple(runtime_keys), tuple(channels))
        if reload_requested or signature != self._signature:
            self._translator = (
                _deepseek_translator_from_channels(self._settings, channels)
                if channels
                else None
            )
            self._channels = channels
            self._signature = signature
            _record_deepseek_runtime_status_best_effort(
                self._settings,
                source=source,
                status=status,
                channels=channels,
                error=error,
            )
        self._next_reload_at = now + self._reload_interval_seconds


def _deepseek_translator_from_channels(
    settings: Settings,
    channels: list[DeepSeekChannelConfig],
) -> TextTranslator:
    base_url = os.getenv("DEEPSEEK_BASE_URL", settings.deepseek_base_url)
    timeout_seconds = _env_float("DEEPSEEK_TIMEOUT_SECONDS", 120.0)
    retry_attempts = _env_int("DEEPSEEK_RETRY_ATTEMPTS", 3)
    retry_delay_seconds = _env_float("DEEPSEEK_RETRY_DELAY_SECONDS", 1.0)

    cooldown_seconds = _env_float("DEEPSEEK_CHANNEL_COOLDOWN_SECONDS", 30.0)
    max_cooldown_seconds = _env_float(
        "DEEPSEEK_CHANNEL_MAX_COOLDOWN_SECONDS",
        max(300.0, cooldown_seconds),
    )

    def client_factory(*, api_key: str):
        return DeepSeekClient(
            api_key=api_key,
            model=settings.deepseek_model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            retry_attempts=retry_attempts,
            retry_delay_seconds=retry_delay_seconds,
        )

    return DeepSeekKeyPoolTranslator(
        channels=channels,
        client_factory=client_factory,
        model=settings.deepseek_model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        retry_attempts=retry_attempts,
        retry_delay_seconds=retry_delay_seconds,
        cooldown_seconds=cooldown_seconds,
        max_cooldown_seconds=max_cooldown_seconds,
        throttle_config=_deepseek_throttle_config_from_env(),
        cooldown_jitter_fraction=_env_float(
            "DEEPSEEK_CHANNEL_COOLDOWN_JITTER_FRACTION",
            0.20,
        ),
    )


def _deepseek_channel_configs(settings: Settings) -> list[DeepSeekChannelConfig]:
    admin_keys = load_ai_provider_runtime_keys(settings, provider_id="deepseek")
    return [
        *_deepseek_admin_channel_configs(admin_keys),
        *_deepseek_env_channel_configs(),
    ]


def _deepseek_admin_channel_configs(admin_keys) -> list[DeepSeekChannelConfig]:
    return [
        DeepSeekChannelConfig(
            api_key=key.api_key,
            label=key.label,
            max_parallel_requests=key.max_parallel_requests,
            weight=key.weight,
        )
        for key in admin_keys
    ]


def _deepseek_env_channel_configs() -> list[DeepSeekChannelConfig]:
    api_keys = _deepseek_api_keys_from_env()
    max_parallel_per_key = _env_int("DEEPSEEK_MAX_PARALLEL_PER_KEY", 1)
    channel_weights = _deepseek_channel_weights_from_env(len(api_keys))
    return [
        DeepSeekChannelConfig(
            api_key=api_key,
            label=f"deepseek-{index}",
            max_parallel_requests=max_parallel_per_key,
            weight=channel_weights[index - 1],
        )
        for index, api_key in enumerate(api_keys, start=1)
    ]


def _deepseek_api_keys_from_env() -> list[str]:
    key_list = os.getenv("DEEPSEEK_API_KEYS", "")
    candidates = (
        key_list.split(",") if key_list else [os.getenv("DEEPSEEK_API_KEY", "")]
    )
    keys: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        api_key = candidate.strip()
        if not api_key or api_key in seen:
            continue
        seen.add(api_key)
        keys.append(api_key)
    return keys


def _deepseek_parallel_capacity_from_env() -> int:
    return max(1, len(_deepseek_api_keys_from_env())) * _env_int(
        "DEEPSEEK_MAX_PARALLEL_PER_KEY",
        1,
    )


def _deepseek_parallel_capacity(settings: Settings) -> int:
    admin_keys = load_ai_provider_runtime_keys(settings, provider_id="deepseek")
    admin_capacity = sum(max(1, key.max_parallel_requests) for key in admin_keys)
    return admin_capacity + _deepseek_parallel_capacity_from_env()


def _consume_deepseek_reload_request(settings: Settings) -> bool:
    with SQLiteAIProviderRuntimeStore(settings.admin_db_path) as store:
        return store.consume_reload_request("deepseek") is not None


def _next_best_effort_reload_at(
    *,
    now: float,
    reload_interval_seconds: float,
) -> float:
    return now + max(1.0, reload_interval_seconds)


def _record_deepseek_runtime_status(
    settings: Settings,
    *,
    source: str = "admin_store",
    status: str,
    channels: list[DeepSeekChannelConfig],
    error: str | None,
    runtime_channels: tuple[AIProviderRuntimeChannel, ...] | None = None,
    provider_state: AIProviderRuntimeProviderState | None = None,
) -> None:
    with SQLiteAIProviderRuntimeStore(settings.admin_db_path) as store:
        store.record_status(
            provider_id="deepseek",
            source=source,
            status=status,
            reload_interval_seconds=settings.admin_provider_runtime_reload_seconds,
            active_channels=runtime_channels
            if runtime_channels is not None
            else tuple(
                AIProviderRuntimeChannel(
                    label=channel.label or "unnamed",
                    weight=channel.weight,
                    max_parallel_requests=channel.max_parallel_requests,
                )
                for channel in channels
            ),
            provider_state=provider_state,
            error=error,
        )


def _record_deepseek_runtime_status_best_effort(
    settings: Settings,
    *,
    source: str = "admin_store",
    status: str,
    channels: list[DeepSeekChannelConfig],
    error: str | None,
    runtime_channels: tuple[AIProviderRuntimeChannel, ...] | None = None,
    provider_state: AIProviderRuntimeProviderState | None = None,
) -> None:
    try:
        _record_deepseek_runtime_status(
            settings,
            source=source,
            status=status,
            channels=channels,
            error=error,
            runtime_channels=runtime_channels,
            provider_state=provider_state,
        )
    except Exception:
        logger.warning(
            "DeepSeek runtime status update skipped: provider_id=deepseek",
            exc_info=True,
        )


def _runtime_channel_from_snapshot(snapshot) -> AIProviderRuntimeChannel:
    return AIProviderRuntimeChannel(
        label=snapshot.label,
        weight=snapshot.weight,
        max_parallel_requests=snapshot.max_parallel_requests,
        active_requests=snapshot.active_requests,
        health=snapshot.health,
        cooldown_remaining_seconds=snapshot.cooldown_remaining_seconds,
        total_started_requests=snapshot.total_started_requests,
        total_successful_requests=snapshot.total_successful_requests,
        total_temporary_failures=snapshot.total_temporary_failures,
        total_permanent_failures=snapshot.total_permanent_failures,
        total_rate_limit_failures=snapshot.total_rate_limit_failures,
        total_unavailable_failures=snapshot.total_unavailable_failures,
        total_timeout_failures=snapshot.total_timeout_failures,
        total_malformed_response_failures=(snapshot.total_malformed_response_failures),
        total_auth_failures=snapshot.total_auth_failures,
        total_billing_failures=snapshot.total_billing_failures,
        total_other_provider_failures=snapshot.total_other_provider_failures,
        total_unsafe_model_output_failures=(
            snapshot.total_unsafe_model_output_failures
        ),
        average_latency_ms=snapshot.average_latency_ms,
        last_latency_ms=snapshot.last_latency_ms,
        error_kind=snapshot.error_kind,
        last_error_excerpt=snapshot.last_error,
    )


def _provider_snapshot_from_translator(translator: TextTranslator):
    provider_snapshot = getattr(translator, "provider_snapshot", None)
    if provider_snapshot is None:
        return None
    return provider_snapshot()


def _runtime_provider_state_from_snapshot(snapshot) -> AIProviderRuntimeProviderState:
    return AIProviderRuntimeProviderState(
        adaptive_enabled=snapshot.enabled,
        current_limit=snapshot.current_limit,
        max_capacity=snapshot.max_capacity,
        active_requests=snapshot.active_requests,
        available_slots=snapshot.available_slots,
        circuit_state=snapshot.circuit_state,
        circuit_open_remaining_seconds=snapshot.circuit_open_remaining_seconds,
        last_reason=snapshot.last_reason,
        total_ramp_ups=snapshot.total_ramp_ups,
        total_decreases=snapshot.total_decreases,
        total_circuit_opened=snapshot.total_circuit_opened,
    )


def _deepseek_runtime_status_from_channels(
    status: str,
    runtime_channels: tuple[AIProviderRuntimeChannel, ...],
    provider_state: AIProviderRuntimeProviderState | None = None,
) -> str:
    if status == "missing_keys":
        return status
    if provider_state is not None and provider_state.circuit_state in {
        "open",
        "half_open",
    }:
        return "degraded"
    if any(
        channel.health in {"cooling_down", "degraded"} for channel in runtime_channels
    ):
        return "degraded"
    return "ok"


def _deepseek_channel_weights_from_env(channel_count: int) -> list[int]:
    raw = os.getenv("DEEPSEEK_CHANNEL_WEIGHTS", "")
    if not raw.strip():
        return [1] * channel_count
    try:
        weights = [int(part.strip()) for part in raw.split(",")]
    except ValueError:
        logger.warning("Ignoring invalid DeepSeek channel weights: %r", raw)
        return [1] * channel_count
    if len(weights) != channel_count or any(weight < 1 for weight in weights):
        logger.warning("Ignoring invalid DeepSeek channel weights: %r", raw)
        return [1] * channel_count
    return weights


def _deepseek_throttle_config_from_env() -> ProviderThrottleConfig:
    return ProviderThrottleConfig(
        enabled=_env_bool("DEEPSEEK_ADAPTIVE_THROTTLING_ENABLED", True),
        initial_parallel=max(
            1,
            _env_int("DEEPSEEK_ADAPTIVE_INITIAL_PARALLEL", 1),
        ),
        min_parallel=max(
            1,
            _env_int("DEEPSEEK_ADAPTIVE_MIN_PARALLEL", 1),
        ),
        success_ramp_interval=max(
            1,
            _env_int("DEEPSEEK_ADAPTIVE_SUCCESS_RAMP_INTERVAL", 8),
        ),
        decrease_factor=min(
            0.95,
            max(0.1, _env_float("DEEPSEEK_ADAPTIVE_DECREASE_FACTOR", 0.5)),
        ),
        circuit_failure_threshold=max(
            1,
            _env_int("DEEPSEEK_PROVIDER_CIRCUIT_FAILURE_THRESHOLD", 5),
        ),
        circuit_reset_seconds=max(
            1.0,
            _env_float("DEEPSEEK_PROVIDER_CIRCUIT_RESET_SECONDS", 120.0),
        ),
    )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("Ignoring invalid integer environment value: %s=%r", name, raw)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("Ignoring invalid float environment value: %s=%r", name, raw)
        return default


def create_router(
    *,
    service: BotTranslationService,
    translator: TextTranslator,
    config: BotRuntimeConfig,
):
    from aiogram import F, Router
    from aiogram.filters import Command
    from aiogram.types import CallbackQuery, Message

    router = Router()
    callback_spam_guard = _CallbackSpamGuard(
        min_interval_seconds=config.callback_spam_min_interval_seconds,
        burst_limit=config.callback_spam_burst_limit,
        burst_window_seconds=config.callback_spam_burst_window_seconds,
    )
    user_action_guard = _UserActionInFlightGuard(
        ttl_seconds=config.user_action_lock_ttl_seconds,
    )

    def record_message_activity(
        message: Message,
        *,
        event_type: str,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        user_id = getattr(getattr(message, "from_user", None), "id", None)
        if user_id is None:
            return
        service.record_user_activity(
            user_telegram_id=user_id,
            event_type=event_type,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata=metadata,
        )

    def record_callback_activity(
        callback: CallbackQuery,
        *,
        event_type: str,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        user_id = getattr(getattr(callback, "from_user", None), "id", None)
        if user_id is None:
            return
        service.record_user_activity(
            user_telegram_id=user_id,
            event_type=event_type,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata={"callback_data": callback.data, **(metadata or {})},
        )

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.command.received",
            action="start",
            target_type="command",
            target_id="/start",
        )
        if not service.has_interface_language(message.from_user.id):
            await message.answer(
                build_language_selection_message(interface_language="en"),
                reply_markup=_interface_language_keyboard(),
            )
            return

        await message.answer(
            build_start_message(
                interface_language=service.get_interface_language(message.from_user.id)
            ),
            reply_markup=_main_menu_keyboard(
                service.get_interface_language(message.from_user.id)
            ),
        )

    @router.message(Command("menu"))
    async def menu(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.command.received",
            action="menu",
            target_type="command",
            target_id="/menu",
        )
        interface_language = service.get_interface_language(message.from_user.id)
        service.discard_pending_translation(message.from_user.id)
        await message.answer(
            get_main_menu_text(interface_language=interface_language),
            reply_markup=_main_menu_keyboard(interface_language),
        )

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.command.received",
            action="help",
            target_type="command",
            target_id="/help",
        )
        interface_language = service.get_interface_language(message.from_user.id)
        await message.answer(
            build_help_message(interface_language),
            reply_markup=_menu_detail_keyboard(interface_language),
        )

    @router.message(Command("language"))
    async def language(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.command.received",
            action="language",
            target_type="command",
            target_id="/language",
        )
        await message.answer(
            build_language_selection_message(
                interface_language=service.get_interface_language(message.from_user.id)
            ),
            reply_markup=_interface_language_keyboard(),
        )

    @router.message(F.text.func(is_main_menu_text))
    async def main_menu(message: Message) -> None:
        interface_language = service.get_interface_language(message.from_user.id)
        service.discard_pending_translation(message.from_user.id)
        await message.answer(
            get_main_menu_text(interface_language=interface_language),
            reply_markup=_main_menu_keyboard(interface_language),
        )

    @router.message(F.text.func(is_translate_book_text))
    async def translate_book(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.button.clicked",
            action="clicked",
            target_type="button",
            target_id="translate_book",
        )
        interface_language = service.get_interface_language(message.from_user.id)
        if not service.is_beta_allowed(message.from_user.id):
            await message.answer(
                build_upload_error_message(
                    BetaAccessDenied(),
                    interface_language,
                )
            )
            return
        await message.answer(
            build_upload_prompt_message(interface_language),
            reply_markup=_back_keyboard(interface_language),
        )

    @router.message(F.text.func(is_how_it_works_text))
    async def how_it_works(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.button.clicked",
            action="clicked",
            target_type="button",
            target_id="how_it_works",
        )
        interface_language = service.get_interface_language(message.from_user.id)
        await message.answer(
            build_how_it_works_message(interface_language),
            reply_markup=_menu_detail_keyboard(interface_language),
        )

    @router.message(F.text.func(is_my_books_text))
    async def my_books(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.button.clicked",
            action="clicked",
            target_type="button",
            target_id="my_books",
        )
        interface_language = service.get_interface_language(message.from_user.id)
        books = service.list_user_books(user_telegram_id=message.from_user.id)
        queue_summary = service.get_user_queue_summary(
            user_telegram_id=message.from_user.id
        )
        await message.answer(
            build_my_books_message(
                books,
                interface_language=interface_language,
                queue_summary=queue_summary,
            ),
            reply_markup=(
                _my_books_keyboard(books, interface_language=interface_language)
                or _menu_detail_keyboard(interface_language)
            ),
        )

    @router.callback_query(F.data == "my_books")
    async def my_books_callback(callback: CallbackQuery) -> None:
        if await _answer_callback_if_spam(callback, callback_spam_guard):
            return
        record_callback_activity(
            callback,
            event_type="bot.callback.clicked",
            action="clicked",
            target_type="callback",
            target_id="my_books",
        )
        if callback.message is None:
            await callback.answer()
            return
        interface_language = service.get_interface_language(callback.from_user.id)
        books = service.list_user_books(user_telegram_id=callback.from_user.id)
        queue_summary = service.get_user_queue_summary(
            user_telegram_id=callback.from_user.id
        )
        await callback.answer()
        await _edit_callback_message(
            callback.message,
            build_my_books_message(
                books,
                interface_language=interface_language,
                queue_summary=queue_summary,
            ),
            reply_markup=(
                _my_books_keyboard(books, interface_language=interface_language)
                or _menu_detail_keyboard(interface_language)
            ),
        )

    @router.callback_query(F.data.startswith("book_detail:"))
    async def book_detail(callback: CallbackQuery) -> None:
        if await _answer_callback_if_spam(callback, callback_spam_guard):
            return
        interface_language = service.get_interface_language(callback.from_user.id)
        job_id = (callback.data or "").split(":", 1)[1]
        record_callback_activity(
            callback,
            event_type="bot.callback.clicked",
            action="opened",
            target_type="book",
            target_id=job_id,
        )
        book = service.get_user_book_detail(
            user_telegram_id=callback.from_user.id,
            job_id=job_id,
        )
        if book is None or callback.message is None:
            await callback.answer(
                build_download_unavailable_message(interface_language),
                show_alert=True,
            )
            return

        await callback.answer()
        await _edit_callback_message(
            callback.message,
            build_my_book_detail_message(book, interface_language=interface_language),
            reply_markup=_my_book_detail_keyboard(
                book,
                interface_language=interface_language,
            ),
        )

    @router.callback_query(F.data.startswith("resume_book:"))
    async def resume_book(callback: CallbackQuery) -> None:
        if await _answer_callback_if_spam(callback, callback_spam_guard):
            return
        interface_language = service.get_interface_language(callback.from_user.id)
        job_id = (callback.data or "").split(":", 1)[1]
        record_callback_activity(
            callback,
            event_type="bot.callback.clicked",
            action="resume_requested",
            target_type="book",
            target_id=job_id,
        )
        book = service.get_user_book_detail(
            user_telegram_id=callback.from_user.id,
            job_id=job_id,
        )
        if book is None or not book.can_resume or callback.message is None:
            await callback.answer(
                build_download_unavailable_message(interface_language),
                show_alert=True,
            )
            return

        if not user_action_guard.try_begin(
            user_id=callback.from_user.id,
            action="translation_start",
        ):
            await callback.answer()
            return

        try:
            await callback.answer()
            await _resume_user_book_translation(
                message=callback.message,
                user_telegram_id=callback.from_user.id,
                job_id=job_id,
                service=service,
                translator=translator,
            )
        finally:
            user_action_guard.finish(
                user_id=callback.from_user.id,
                action="translation_start",
            )

    @router.callback_query(F.data.startswith("cancel_book:"))
    async def cancel_book(callback: CallbackQuery) -> None:
        if await _answer_callback_if_spam(callback, callback_spam_guard):
            return
        interface_language = service.get_interface_language(callback.from_user.id)
        job_id = (callback.data or "").split(":", 1)[1]
        record_callback_activity(
            callback,
            event_type="bot.callback.clicked",
            action="cancel_requested",
            target_type="book",
            target_id=job_id,
        )
        if callback.message is None:
            await callback.answer(
                build_download_unavailable_message(interface_language),
                show_alert=True,
            )
            return

        if not service.cancel_user_book(
            user_telegram_id=callback.from_user.id,
            job_id=job_id,
        ):
            await callback.answer(
                build_nothing_to_cancel_message(interface_language),
                show_alert=True,
            )
            return

        job = service.get_user_book_translation_job(
            user_telegram_id=callback.from_user.id,
            job_id=job_id,
        )
        book = service.get_user_book_detail(
            user_telegram_id=callback.from_user.id,
            job_id=job_id,
        )
        await callback.answer()
        if job is not None:
            await _edit_callback_message(
                callback.message,
                build_translation_job_status_message(
                    job,
                    interface_language=interface_language,
                ),
                reply_markup=(
                    _my_book_detail_keyboard(
                        book,
                        interface_language=interface_language,
                    )
                    if book is not None
                    else None
                ),
            )
            await _send_translation_result_document_once(callback.message, job, service)
        elif book is not None:
            await _edit_callback_message(
                callback.message,
                build_my_book_detail_message(
                    book,
                    interface_language=interface_language,
                ),
                reply_markup=_my_book_detail_keyboard(
                    book,
                    interface_language=interface_language,
                ),
            )

    @router.callback_query(F.data.startswith("delete_book:"))
    async def delete_book(callback: CallbackQuery) -> None:
        if await _answer_callback_if_spam(callback, callback_spam_guard):
            return
        interface_language = service.get_interface_language(callback.from_user.id)
        job_id = (callback.data or "").split(":", 1)[1]
        record_callback_activity(
            callback,
            event_type="bot.callback.clicked",
            action="delete_requested",
            target_type="book",
            target_id=job_id,
        )
        book = service.get_user_book_detail(
            user_telegram_id=callback.from_user.id,
            job_id=job_id,
        )
        if book is None or callback.message is None:
            await callback.answer(
                build_delete_unavailable_message(interface_language),
                show_alert=True,
            )
            return

        await callback.answer()
        await _edit_callback_message(
            callback.message,
            build_delete_book_confirmation_message(
                book,
                interface_language=interface_language,
            ),
            reply_markup=_delete_book_confirmation_keyboard(
                job_id,
                interface_language=interface_language,
            ),
        )

    @router.callback_query(F.data.startswith("keep_book:"))
    async def keep_book(callback: CallbackQuery) -> None:
        if await _answer_callback_if_spam(callback, callback_spam_guard):
            return
        interface_language = service.get_interface_language(callback.from_user.id)
        job_id = (callback.data or "").split(":", 1)[1]
        book = service.get_user_book_detail(
            user_telegram_id=callback.from_user.id,
            job_id=job_id,
        )
        if book is None or callback.message is None:
            await callback.answer(
                build_delete_unavailable_message(interface_language),
                show_alert=True,
            )
            return

        await callback.answer()
        await _edit_callback_message(
            callback.message,
            build_my_book_detail_message(book, interface_language=interface_language),
            reply_markup=_my_book_detail_keyboard(
                book,
                interface_language=interface_language,
            ),
        )

    @router.callback_query(F.data.startswith("confirm_delete_book:"))
    async def confirm_delete_book(callback: CallbackQuery) -> None:
        if await _answer_callback_if_spam(callback, callback_spam_guard):
            return
        interface_language = service.get_interface_language(callback.from_user.id)
        job_id = (callback.data or "").split(":", 1)[1]
        record_callback_activity(
            callback,
            event_type="bot.callback.clicked",
            action="delete_confirmed",
            target_type="book",
            target_id=job_id,
        )
        if callback.message is None:
            await callback.answer(
                build_delete_unavailable_message(interface_language),
                show_alert=True,
            )
            return

        deleted = service.delete_user_book(
            user_telegram_id=callback.from_user.id,
            job_id=job_id,
        )
        if not deleted:
            await callback.answer(
                build_delete_unavailable_message(interface_language),
                show_alert=True,
            )
            return

        await callback.answer()
        books = service.list_user_books(user_telegram_id=callback.from_user.id)
        await _edit_callback_message(
            callback.message,
            build_book_deleted_message(interface_language),
            reply_markup=(
                _my_books_keyboard(books, interface_language=interface_language)
                or _menu_detail_keyboard(interface_language)
            ),
        )

    @router.callback_query(F.data.startswith("download_book:"))
    async def download_book(callback: CallbackQuery) -> None:
        if await _answer_callback_if_spam(callback, callback_spam_guard):
            return
        interface_language = service.get_interface_language(callback.from_user.id)
        job_id = (callback.data or "").split(":", 1)[1]
        record_callback_activity(
            callback,
            event_type="bot.callback.clicked",
            action="download_requested",
            target_type="book",
            target_id=job_id,
        )
        result = service.get_user_book_result(
            user_telegram_id=callback.from_user.id,
            job_id=job_id,
        )
        if result is None or callback.message is None:
            await callback.answer(
                build_download_unavailable_message(interface_language),
                show_alert=True,
            )
            return

        await callback.answer()
        await _send_user_book_result(callback.message, result)

    @router.callback_query(F.data == "duplicate_upload_translate_again")
    async def duplicate_upload_translate_again(callback: CallbackQuery) -> None:
        if await _answer_callback_if_spam(callback, callback_spam_guard):
            return
        interface_language = service.get_interface_language(callback.from_user.id)
        duplicate = service.find_pending_translation_duplicate(
            user_telegram_id=callback.from_user.id,
        )
        if duplicate is not None and not duplicate.can_translate_again:
            if callback.message is not None:
                await _edit_callback_message(
                    callback.message,
                    build_duplicate_upload_message(
                        duplicate,
                        interface_language=interface_language,
                    ),
                    reply_markup=_duplicate_upload_keyboard(
                        duplicate,
                        interface_language=interface_language,
                    ),
                )
            await callback.answer()
            return
        if callback.message is None:
            await callback.answer(
                build_download_unavailable_message(interface_language),
                show_alert=True,
            )
            return
        try:
            await _send_pending_translation_preview(
                message=callback.message,
                service=service,
                translator=translator,
                interface_language=interface_language,
                user_telegram_id=callback.from_user.id,
            )
        except (
            BetaAccessDenied,
            DocumentEstimationNotReadyError,
            PreviewTranslationError,
            RightsConfirmationRequired,
            SecurityCooldownActive,
            TranslationModeRequired,
            TextExtractionError,
            UnsupportedDocumentError,
            ValueError,
        ) as error:
            await callback.message.answer(
                build_upload_error_message(error, interface_language)
            )
        await callback.answer()

    @router.callback_query(F.data == "duplicate_upload_back")
    async def duplicate_upload_back(callback: CallbackQuery) -> None:
        if await _answer_callback_if_spam(callback, callback_spam_guard):
            return
        interface_language = service.get_interface_language(callback.from_user.id)
        pending_upload = service.restore_pending_translation_upload(
            user_telegram_id=callback.from_user.id,
        )
        if callback.message is None or pending_upload is None:
            await callback.answer()
            return
        await callback.message.answer(
            build_translation_language_selection_message(
                pending_upload.file_name,
                interface_language=interface_language,
                source_language_display=pending_upload.source_language_display,
            ),
            reply_markup=_target_language_keyboard(interface_language),
        )
        await callback.answer()

    @router.message(F.text.func(is_help_text))
    async def help_text(message: Message) -> None:
        interface_language = service.get_interface_language(message.from_user.id)
        await message.answer(
            build_help_message(interface_language),
            reply_markup=_menu_detail_keyboard(interface_language),
        )

    @router.message(F.text.func(is_language_menu_text))
    async def language_menu(message: Message) -> None:
        interface_language = service.get_interface_language(message.from_user.id)
        await message.answer(
            build_language_selection_message(interface_language=interface_language),
            reply_markup=_interface_language_keyboard(),
        )

    @router.message(F.text.func(is_settings_text))
    async def settings_menu(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.button.clicked",
            action="clicked",
            target_type="button",
            target_id="settings",
        )
        interface_language = service.get_interface_language(message.from_user.id)
        await message.answer(
            build_settings_message(
                interface_language=interface_language,
                progress_preview_enabled=service.get_progress_preview_enabled(
                    message.from_user.id
                ),
            ),
            reply_markup=_settings_keyboard(
                interface_language,
                progress_preview_enabled=service.get_progress_preview_enabled(
                    message.from_user.id
                ),
            ),
        )

    @router.message(F.text.func(is_toggle_progress_preview_text))
    async def toggle_progress_preview(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.button.clicked",
            action="clicked",
            target_type="button",
            target_id="toggle_progress_preview",
        )
        interface_language = service.get_interface_language(message.from_user.id)
        enabled = not service.get_progress_preview_enabled(message.from_user.id)
        service.set_progress_preview_enabled(
            user_telegram_id=message.from_user.id,
            enabled=enabled,
        )
        await message.answer(
            build_settings_message(
                interface_language=interface_language,
                progress_preview_enabled=enabled,
            ),
            reply_markup=_settings_keyboard(
                interface_language,
                progress_preview_enabled=enabled,
            ),
        )

    @router.message(F.text.func(is_reset_settings_text))
    async def reset_settings(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.button.clicked",
            action="clicked",
            target_type="button",
            target_id="reset_settings",
        )
        interface_language = service.get_interface_language(message.from_user.id)
        service.reset_user_settings(message.from_user.id)
        await message.answer(build_settings_reset_message(interface_language))
        await message.answer(
            build_language_selection_message(interface_language="en"),
            reply_markup=_interface_language_keyboard(),
        )

    @router.message(F.text.func(is_translation_mode_button_text))
    async def translation_mode_text(message: Message) -> None:
        translation_mode = translation_mode_for_button_text(message.text)
        interface_language = service.get_interface_language(message.from_user.id)
        if translation_mode is None:
            await message.answer(
                build_translation_mode_required_message(interface_language)
            )
            return

        try:
            selected = service.select_pending_upload_translation_mode(
                user_telegram_id=message.from_user.id,
                translation_mode=translation_mode,
            )
        except RightsConfirmationRequired:
            pending_upload = service.get_pending_upload(message.from_user.id)
            await message.answer(
                build_rights_confirmation_message(
                    pending_upload.file_name if pending_upload else "document",
                    interface_language=interface_language,
                ),
                reply_markup=_rights_confirmation_keyboard(interface_language),
            )
            return
        except (BetaAccessDenied, SecurityCooldownActive) as error:
            await message.answer(build_upload_error_message(error, interface_language))
            return
        except ValueError as error:
            await message.answer(str(error))
            return

        await message.answer(
            build_translation_language_selection_message(
                selected.file_name,
                interface_language=interface_language,
                source_language_display=selected.source_language_display,
            ),
            reply_markup=_target_language_keyboard(interface_language),
        )

    @router.message(F.text.func(_is_language_button_text))
    async def language_text(message: Message) -> None:
        language_option = find_language_by_button_text(message.text)
        if language_option is None:
            await message.answer(
                build_language_selection_message(
                    interface_language=service.get_interface_language(
                        message.from_user.id
                    )
                )
            )
            return

        interface_language = service.get_interface_language(message.from_user.id)
        pending_upload = service.get_pending_upload(message.from_user.id)
        if pending_upload is not None:
            try:
                await _prepare_and_send_translation_preview(
                    message=message,
                    service=service,
                    translator=translator,
                    target_language=language_option.code,
                    interface_language=interface_language,
                )
            except (
                BetaAccessDenied,
                DocumentEstimationNotReadyError,
                PreviewTranslationError,
                RightsConfirmationRequired,
                SecurityCooldownActive,
                TranslationModeRequired,
                TextExtractionError,
                UnsupportedDocumentError,
                ValueError,
            ) as error:
                if isinstance(error, RightsConfirmationRequired):
                    await message.answer(
                        build_rights_confirmation_message(
                            pending_upload.file_name,
                            interface_language=interface_language,
                        ),
                        reply_markup=_rights_confirmation_keyboard(
                            interface_language,
                        ),
                    )
                    return
                if isinstance(error, TranslationModeRequired):
                    await message.answer(
                        build_translation_mode_selection_message(
                            pending_upload.file_name,
                            interface_language=interface_language,
                            source_language_display=(
                                pending_upload.source_language_display
                            ),
                        ),
                        reply_markup=_translation_mode_keyboard(interface_language),
                    )
                    return
                await message.answer(
                    build_upload_error_message(error, interface_language)
                )
                return
            return

        service.set_interface_language(
            user_telegram_id=message.from_user.id,
            language_code=language_option.code,
        )
        await message.answer(
            build_language_selected_message(
                language_option.button_text,
                interface_language=language_option.code,
            )
        )
        await message.answer(
            get_main_menu_text(interface_language=language_option.code),
            reply_markup=_main_menu_keyboard(language_option.code),
        )

    @router.message(Command("confirm"))
    async def confirm(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.command.received",
            action="confirm",
            target_type="command",
            target_id="/confirm",
        )
        await _confirm_pending_translation(
            message=message,
            service=service,
            translator=translator,
            action_guard=user_action_guard,
        )

    @router.message(Command("cancel"))
    async def cancel(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.command.received",
            action="cancel",
            target_type="command",
            target_id="/cancel",
        )
        await _cancel_active_translation(message=message, service=service)

    @router.message(F.text.func(is_cancel_text))
    async def cancel_text(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.button.clicked",
            action="clicked",
            target_type="button",
            target_id="cancel",
        )
        await _cancel_active_translation(message=message, service=service)

    @router.message(F.text.func(is_confirm_rights_text))
    async def confirm_rights_text(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.button.clicked",
            action="clicked",
            target_type="button",
            target_id="confirm_rights",
        )
        await _confirm_pending_upload_rights(
            message=message,
            service=service,
        )

    @router.callback_query(F.data == "cancel_translation")
    async def cancel_callback(callback: CallbackQuery) -> None:
        if await _answer_callback_if_spam(callback, callback_spam_guard):
            return
        record_callback_activity(
            callback,
            event_type="bot.callback.clicked",
            action="cancel_requested",
            target_type="translation",
            target_id="active",
        )
        interface_language = service.get_interface_language(callback.from_user.id)
        result = service.cancel_translation_with_result(callback.from_user.id)
        if result.cancelled:
            await callback.answer(build_cancel_requested_message(interface_language))
            if result.job is not None and callback.message is not None:
                await _edit_callback_message(
                    callback.message,
                    build_translation_job_status_message(
                        result.job,
                        interface_language=interface_language,
                    ),
                    reply_markup=None,
                )
                await _send_translation_result_document_once(
                    callback.message,
                    result.job,
                    service,
                )
            return

        await callback.answer(
            build_nothing_to_cancel_message(interface_language),
            show_alert=True,
        )

    @router.message(F.text.func(is_back_text))
    async def back_text(message: Message) -> None:
        interface_language = service.get_interface_language(message.from_user.id)
        restored_upload = service.restore_pending_translation_upload(
            user_telegram_id=message.from_user.id,
        )
        if restored_upload is not None and restored_upload.rights_confirmed:
            if restored_upload.translation_mode is None:
                await message.answer(
                    build_translation_mode_selection_message(
                        restored_upload.file_name,
                        interface_language=interface_language,
                        source_language_display=(
                            restored_upload.source_language_display
                        ),
                    ),
                    reply_markup=_translation_mode_keyboard(interface_language),
                )
                return
            await message.answer(
                build_translation_language_selection_message(
                    restored_upload.file_name,
                    interface_language=interface_language,
                    source_language_display=restored_upload.source_language_display,
                ),
                reply_markup=_target_language_keyboard(interface_language),
            )
            return
        service.discard_pending_translation(message.from_user.id)
        await message.answer(build_back_to_menu_message(interface_language))
        await message.answer(
            get_main_menu_text(interface_language=interface_language),
            reply_markup=_main_menu_keyboard(interface_language),
        )

    @router.message(F.text.func(is_confirm_translation_text))
    async def confirm_text(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.button.clicked",
            action="clicked",
            target_type="button",
            target_id="confirm_translation",
        )
        await _confirm_pending_translation(
            message=message,
            service=service,
            translator=translator,
            action_guard=user_action_guard,
        )

    @router.message(F.text.func(is_continue_translation_text))
    async def continue_translation_text(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.button.clicked",
            action="clicked",
            target_type="button",
            target_id="continue_translation",
        )
        await _continue_pending_translation_after_preview(
            message=message,
            service=service,
            translator=translator,
            action_guard=user_action_guard,
        )

    @router.message(Command("status"))
    async def status(message: Message) -> None:
        record_message_activity(
            message,
            event_type="bot.command.received",
            action="status",
            target_type="command",
            target_id="/status",
        )
        interface_language = service.get_interface_language(message.from_user.id)
        pending_upload = service.get_pending_upload(message.from_user.id)
        if pending_upload is not None:
            if pending_upload.rights_confirmed:
                if pending_upload.translation_mode is None:
                    await message.answer(
                        build_translation_mode_selection_message(
                            pending_upload.file_name,
                            interface_language=interface_language,
                            source_language_display=(
                                pending_upload.source_language_display
                            ),
                        ),
                        reply_markup=_translation_mode_keyboard(interface_language),
                    )
                else:
                    await message.answer(
                        build_translation_language_selection_message(
                            pending_upload.file_name,
                            interface_language=interface_language,
                            source_language_display=(
                                pending_upload.source_language_display
                            ),
                        ),
                        reply_markup=_target_language_keyboard(interface_language),
                    )
            else:
                await message.answer(
                    build_rights_confirmation_message(
                        pending_upload.file_name,
                        interface_language=interface_language,
                    ),
                    reply_markup=_rights_confirmation_keyboard(interface_language),
                )
            return

        pending = service.get_pending(message.from_user.id)
        if pending is None:
            await message.answer(
                build_no_pending_translation_message(interface_language)
            )
            return

        await message.answer(
            build_pending_translation_message(
                pending,
                interface_language=interface_language,
            ),
            reply_markup=_confirm_keyboard(interface_language, include_back=True),
        )

    @router.message(F.document)
    async def document_upload(message: Message) -> None:
        document = message.document
        interface_language = service.get_interface_language(message.from_user.id)
        if not service.is_beta_allowed(message.from_user.id):
            await message.answer(
                build_upload_error_message(
                    BetaAccessDenied(),
                    interface_language,
                )
            )
            return
        record_message_activity(
            message,
            event_type="document.uploaded",
            action="uploaded",
            target_type="document",
            target_id=document.file_name or "document.txt",
            metadata={
                "file_name": document.file_name or "document.txt",
                "file_size": getattr(document, "file_size", None),
                "mime_type": getattr(document, "mime_type", None),
            },
        )
        effective_upload_limit_mb = min(
            config.max_upload_mb,
            TELEGRAM_BOT_API_DOWNLOAD_LIMIT_MB,
        )
        if _document_exceeds_upload_limit(
            document,
            max_upload_mb=effective_upload_limit_mb,
        ):
            error = FileTooLargeError(
                f"File exceeds the upload limit of {effective_upload_limit_mb} MB"
            )
            await message.answer(build_upload_error_message(error, interface_language))
            return

        bot = message.bot
        file = await bot.get_file(document.file_id)
        downloaded = await bot.download_file(file.file_path)
        content = downloaded.read()

        try:
            pending_upload = service.store_uploaded_document(
                user_telegram_id=message.from_user.id,
                file_name=document.file_name or "document.txt",
                content=content,
                source_language=config.source_language,
            )
        except (
            BetaAccessDenied,
            DocumentEstimationNotReadyError,
            SecurityCooldownActive,
            TextExtractionError,
            UnsupportedDocumentError,
            ValueError,
        ) as error:
            await message.answer(build_upload_error_message(error, interface_language))
            return

        await message.answer(
            build_rights_confirmation_message(
                pending_upload.file_name,
                interface_language=interface_language,
            ),
            reply_markup=_rights_confirmation_keyboard(interface_language),
        )

    @router.message(F.text)
    async def unknown_text(message: Message) -> None:
        interface_language = service.get_interface_language(message.from_user.id)
        await message.answer(
            build_unknown_text_message(interface_language),
            reply_markup=_main_menu_keyboard(interface_language),
        )

    return router


def _confirm_keyboard(interface_language: str = "en", *, include_back: bool = False):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    keyboard = [[KeyboardButton(text=get_confirm_translation_text(interface_language))]]
    if include_back:
        keyboard.append([KeyboardButton(text=get_back_text(interface_language))])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _rights_confirmation_keyboard(interface_language: str = "en"):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=get_confirm_rights_text(interface_language))],
            [KeyboardButton(text=get_back_text(interface_language))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _main_menu_keyboard(interface_language: str = "en"):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    menu = build_main_menu(interface_language)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=menu[0])],
            [KeyboardButton(text=menu[1])],
            [KeyboardButton(text=menu[2]), KeyboardButton(text=menu[3])],
            [KeyboardButton(text=menu[4])],
            [KeyboardButton(text=menu[5])],
        ],
        resize_keyboard=True,
    )


def _settings_keyboard(
    interface_language: str = "en",
    *,
    progress_preview_enabled: bool = True,
):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text=get_toggle_progress_preview_text(
                        interface_language,
                        progress_preview_enabled,
                    )
                )
            ],
            [KeyboardButton(text=get_reset_settings_text(interface_language))],
            [KeyboardButton(text=get_main_menu_button_text(interface_language))],
        ],
        resize_keyboard=True,
    )


def _menu_detail_keyboard(interface_language: str = "en"):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    menu = build_main_menu(interface_language)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=menu[0])],
            [KeyboardButton(text=menu[1])],
            [KeyboardButton(text=get_main_menu_button_text(interface_language))],
        ],
        resize_keyboard=True,
    )


def _my_books_keyboard(books, interface_language: str = "en"):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    book_list = list(books)
    if not book_list:
        return None

    latest_job_id = _book_job_id(book_list[0])
    if latest_job_id:
        latest_indicator = _book_status_indicator(book_list[0])
        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"{latest_indicator}"
                        f"{get_last_book_text(interface_language)}"
                    ),
                    callback_data=f"book_detail:{latest_job_id}",
                )
            ]
        )
    for index, book in enumerate(book_list, start=1):
        job_id = _book_job_id(book)
        if not job_id:
            continue
        indicator = _book_status_indicator(book)
        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"{indicator}"
                        f"{get_open_book_text(index, interface_language)}"
                    ),
                    callback_data=f"book_detail:{job_id}",
                )
            ]
        )

    if not rows:
        return None

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _my_book_detail_keyboard(book, interface_language: str = "en"):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    job_id = _book_job_id(book)
    if not job_id:
        return None

    rows = []
    if _book_has_result(book):
        rows.append(
            [
                InlineKeyboardButton(
                    text=get_download_translation_text(interface_language),
                    callback_data=f"download_book:{job_id}",
                )
            ]
        )
    if _book_can_resume(book):
        rows.append(
            [
                InlineKeyboardButton(
                    text=get_continue_translation_text(interface_language),
                    callback_data=f"resume_book:{job_id}",
                )
            ]
        )
    if _book_can_cancel(book):
        rows.append(
            [
                InlineKeyboardButton(
                    text=get_cancel_text(interface_language),
                    callback_data=f"cancel_book:{job_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=get_delete_book_text(interface_language),
                callback_data=f"delete_book:{job_id}",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=get_back_to_my_books_text(interface_language),
                callback_data="my_books",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _delete_book_confirmation_keyboard(job_id: str, interface_language: str = "en"):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=get_confirm_delete_book_text(interface_language),
                    callback_data=f"confirm_delete_book:{job_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=get_keep_book_text(interface_language),
                    callback_data=f"keep_book:{job_id}",
                )
            ],
        ]
    )


def _back_keyboard(interface_language: str = "en"):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=get_back_text(interface_language))]],
        resize_keyboard=True,
    )


def _cancel_keyboard(interface_language: str = "en"):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=get_cancel_text(interface_language))]],
        resize_keyboard=True,
    )


def _cancel_inline_keyboard(interface_language: str = "en", job_id: str | None = None):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    callback_data = f"cancel_book:{job_id}" if job_id else "cancel_translation"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=get_cancel_text(interface_language),
                    callback_data=callback_data,
                )
            ]
        ]
    )


def _interface_language_keyboard():
    return _language_keyboard()


def _target_language_keyboard(interface_language: str = "en"):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    keyboard = _language_keyboard_rows()
    keyboard.append([KeyboardButton(text=get_cancel_text(interface_language))])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def _translation_mode_keyboard(interface_language: str = "en"):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text=get_translation_mode_document_form_text(interface_language)
                )
            ],
            [
                KeyboardButton(
                    text=get_translation_mode_book_manuscript_text(interface_language)
                )
            ],
            [KeyboardButton(text=get_back_text(interface_language))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _language_keyboard():
    from aiogram.types import ReplyKeyboardMarkup

    return ReplyKeyboardMarkup(
        keyboard=_language_keyboard_rows(),
        resize_keyboard=True,
    )


def _preview_keyboard(interface_language: str = "en"):
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=get_continue_translation_text(interface_language))],
            [KeyboardButton(text=get_back_text(interface_language))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _duplicate_upload_keyboard(match, interface_language: str = "en"):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = []
    if match.can_download_existing:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=get_download_translation_text(interface_language),
                    callback_data=f"download_book:{match.job_id}",
                )
            ]
        )
    if match.can_open_existing and (
        not match.can_download_existing or getattr(match, "status", None) != "ready"
    ):
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=get_duplicate_open_existing_text(interface_language),
                    callback_data=f"book_detail:{match.job_id}",
                )
            ]
        )
    if match.can_translate_again:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=get_duplicate_translate_again_text(interface_language),
                    callback_data="duplicate_upload_translate_again",
                )
            ]
        )
    keyboard.append(
        [
            InlineKeyboardButton(
                text=get_back_text(interface_language),
                callback_data="duplicate_upload_back",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _language_keyboard_rows():
    from aiogram.types import KeyboardButton

    return [
        [KeyboardButton(text=language.button_text)]
        for language in SUPPORTED_TARGET_LANGUAGES
    ]


def _is_language_button_text(text: str | None) -> bool:
    return find_language_by_button_text(text) is not None


def _book_has_result(book) -> bool:
    if isinstance(book, dict):
        return bool(book.get("has_result"))
    return bool(getattr(book, "has_result", False))


def _book_job_id(book) -> str | None:
    if isinstance(book, dict):
        job_id = book.get("job_id")
    else:
        job_id = getattr(book, "job_id", None)
    return str(job_id) if job_id else None


def _book_can_resume(book) -> bool:
    if isinstance(book, dict):
        return bool(book.get("can_resume"))
    return bool(getattr(book, "can_resume", False))


def _book_can_cancel(book) -> bool:
    if isinstance(book, dict):
        return bool(book.get("can_cancel"))
    return bool(getattr(book, "can_cancel", False))


def _book_status_indicator(book) -> str:
    status = _book_status(book)
    if status == TranslationJobStatus.READY.value:
        return "✅ "
    if status in _BOOK_ACTIVE_STATUS_INDICATOR_STATUSES:
        return "⚙️ "
    if status in _BOOK_RECOVERABLE_STATUS_INDICATOR_STATUSES:
        return "↻ " if _book_can_resume(book) else ""
    if not status and _book_has_result(book):
        return "✅ "
    return ""


def _book_status(book) -> str:
    if isinstance(book, dict):
        status = book.get("status")
    else:
        status = getattr(book, "status", None)
    if status is None:
        return ""
    return str(getattr(status, "value", status))


async def _send_user_book_result(message, result) -> None:
    from aiogram.types import BufferedInputFile

    await message.answer_document(
        BufferedInputFile(result.content, filename=result.file_name)
    )


async def _edit_callback_message(message, text: str, reply_markup=None) -> None:
    result = message.edit_text(
        text,
        reply_markup=_inline_reply_markup_or_none(reply_markup),
    )
    if inspect.isawaitable(result):
        await result


async def _edit_progress_message_if_changed(
    message,
    text: str,
    reply_markup=None,
    should_edit=None,
    progress_stats: dict[str, object] | None = None,
) -> None:
    if should_edit is not None and not should_edit():
        return
    try:
        await _edit_callback_message(message, text, reply_markup=reply_markup)
    except Exception as error:
        message_text = str(error)
        if _is_message_not_modified_error(error):
            logger.debug("Skipping unchanged translation progress message edit")
            return
        if _handle_progress_edit_retry_after(
            error,
            message_text,
            progress_stats=progress_stats,
        ):
            return
        raise


def _is_message_not_modified_error(error: Exception) -> bool:
    return "message is not modified" in str(error).lower()


def _translation_progress_edit_allowed(
    *,
    service,
    user_telegram_id: int,
    job_id: str | None = None,
) -> bool:
    if service.is_translation_cancelling(user_telegram_id):
        return False
    if not job_id:
        return True

    current_job = service.get_user_book_translation_job(
        user_telegram_id=user_telegram_id,
        job_id=job_id,
    )
    if current_job is None:
        return False
    return current_job.status not in {
        TranslationJobStatus.CANCELLED,
        TranslationJobStatus.DELETED,
    }


def _translation_progress_edit_guard(
    *,
    service,
    user_telegram_id: int,
    job_id: str | None = None,
    job_id_getter=None,
):
    def guard() -> bool:
        current_job_id = job_id_getter() if job_id_getter is not None else job_id
        return _translation_progress_edit_allowed(
            service=service,
            user_telegram_id=user_telegram_id,
            job_id=current_job_id,
        )

    return guard


def _inline_reply_markup_or_none(reply_markup):
    if reply_markup is None:
        return None
    if hasattr(reply_markup, "inline_keyboard"):
        return reply_markup
    if hasattr(reply_markup, "keyboard"):
        return None
    return reply_markup


async def _answer_callback_if_spam(callback, guard: _CallbackSpamGuard) -> bool:
    user_id = getattr(getattr(callback, "from_user", None), "id", 0)
    action = str(getattr(callback, "data", "") or "unknown")
    if guard.allow(user_id=user_id, action=action):
        return False
    await callback.answer()
    return True


def _document_exceeds_upload_limit(document, *, max_upload_mb: int) -> bool:
    file_size = getattr(document, "file_size", None)
    if file_size is None:
        return False
    return int(file_size) > max_upload_mb * 1024 * 1024


def _progress_message_for_current_user_language(
    *,
    service: BotTranslationService,
    user_telegram_id: int,
    completed_fragments: int,
    total_fragments: int,
    estimated_total_seconds: int | None,
    elapsed_seconds: int,
    last_translated_text: str | None,
    activity_indicator: str,
    activity_phrase_index: int,
) -> str:
    interface_language = service.get_interface_language(user_telegram_id)
    return build_translation_progress_message(
        completed_fragments=completed_fragments,
        total_fragments=total_fragments,
        interface_language=interface_language,
        estimated_total_seconds=estimated_total_seconds,
        elapsed_seconds=elapsed_seconds,
        last_translated_text=_include_progress_preview(
            service,
            user_telegram_id,
            last_translated_text,
        ),
        activity_indicator=activity_indicator,
        activity_phrase_index=activity_phrase_index,
    )


async def _confirm_pending_translation(
    *,
    message,
    service: BotTranslationService,
    translator: TextTranslator,
    action_guard: _UserActionInFlightGuard | None = None,
) -> None:
    if action_guard is not None and not action_guard.try_begin(
        user_id=message.from_user.id,
        action="translation_start",
    ):
        return
    try:
        await _run_confirm_pending_translation(
            message=message,
            service=service,
            translator=translator,
        )
    finally:
        if action_guard is not None:
            action_guard.finish(
                user_id=message.from_user.id,
                action="translation_start",
            )


async def _prepare_and_send_translation_preview(
    *,
    message,
    service: BotTranslationService,
    translator: TextTranslator,
    target_language: str,
    interface_language: str,
) -> None:
    try:
        service.prepare_pending_upload(
            user_telegram_id=message.from_user.id,
            target_language=target_language,
        )
    except SameLanguageTranslationBlocked as error:
        await message.answer(
            build_same_language_translation_blocked_message(
                source_language_code=error.source_language_code,
                target_language_code=error.target_language_code,
                interface_language=interface_language,
            ),
            reply_markup=_target_language_keyboard(interface_language),
        )
        return
    duplicate = service.find_pending_translation_duplicate(
        user_telegram_id=message.from_user.id,
    )
    if duplicate is not None:
        await message.answer(
            build_duplicate_upload_message(
                duplicate,
                interface_language=interface_language,
            ),
            reply_markup=_duplicate_upload_keyboard(
                duplicate,
                interface_language=interface_language,
            ),
        )
        return

    await _send_pending_translation_preview(
        message=message,
        service=service,
        translator=translator,
        interface_language=interface_language,
    )


async def _send_pending_translation_preview(
    *,
    message,
    service: BotTranslationService,
    translator: TextTranslator,
    interface_language: str,
    user_telegram_id: int | None = None,
) -> None:
    resolved_user_telegram_id = (
        user_telegram_id if user_telegram_id is not None else message.from_user.id
    )
    try:
        preview = await asyncio.to_thread(
            service.generate_preview_translation,
            user_telegram_id=resolved_user_telegram_id,
            translator=translator,
        )
    except Exception:
        service.restore_pending_translation_upload(
            user_telegram_id=resolved_user_telegram_id,
        )
        raise
    await message.answer(
        build_preview_translation_message(
            preview,
            interface_language=interface_language,
        ),
        reply_markup=_preview_keyboard(interface_language),
        parse_mode="HTML",
    )
    service.mark_pending_translation_preview_shown(
        user_telegram_id=resolved_user_telegram_id,
        preview_id=preview.preview_id,
    )


async def _continue_pending_translation_after_preview(
    *,
    message,
    service: BotTranslationService,
    translator: TextTranslator,
    action_guard: _UserActionInFlightGuard | None = None,
) -> None:
    interface_language = service.get_interface_language(message.from_user.id)
    try:
        service.accept_pending_translation_preview(
            user_telegram_id=message.from_user.id,
        )
    except PreviewAcceptanceRequired:
        await message.answer(build_preview_required_message(interface_language))
        return
    except RightsConfirmationRequired:
        pending_upload = service.get_pending_upload(message.from_user.id)
        pending = service.get_pending(message.from_user.id)
        file_name = (
            pending_upload.file_name
            if pending_upload is not None
            else (pending.file_name if pending is not None else "document")
        )
        await message.answer(
            build_rights_confirmation_message(
                file_name,
                interface_language=interface_language,
            ),
            reply_markup=_rights_confirmation_keyboard(interface_language),
        )
        return
    except TranslationModeRequired:
        pending_upload = service.get_pending_upload(message.from_user.id)
        pending = service.get_pending(message.from_user.id)
        await message.answer(
            build_translation_mode_selection_message(
                (
                    pending_upload.file_name
                    if pending_upload is not None
                    else (pending.file_name if pending is not None else "document")
                ),
                interface_language=interface_language,
                source_language_display=(
                    pending_upload.source_language_display
                    if pending_upload is not None
                    else (
                        pending.source_language_display
                        if pending is not None
                        else None
                    )
                ),
            ),
            reply_markup=_translation_mode_keyboard(interface_language),
        )
        return
    except (BetaAccessDenied, SecurityCooldownActive) as error:
        await message.answer(build_upload_error_message(error, interface_language))
        return
    except ValueError as error:
        await message.answer(str(error))
        return

    await _confirm_pending_translation(
        message=message,
        service=service,
        translator=translator,
        action_guard=action_guard,
    )


async def _run_confirm_pending_translation(
    *,
    message,
    service: BotTranslationService,
    translator: TextTranslator,
) -> None:
    interface_language = service.get_interface_language(message.from_user.id)
    pending_upload = service.get_pending_upload(message.from_user.id)
    if pending_upload is not None and not pending_upload.rights_confirmed:
        await message.answer(
            build_rights_confirmation_message(
                pending_upload.file_name,
                interface_language=interface_language,
            ),
            reply_markup=_rights_confirmation_keyboard(interface_language),
        )
        return
    if pending_upload is not None and pending_upload.translation_mode is None:
        await message.answer(
            build_translation_mode_selection_message(
                pending_upload.file_name,
                interface_language=interface_language,
                source_language_display=pending_upload.source_language_display,
            ),
            reply_markup=_translation_mode_keyboard(interface_language),
        )
        return
    pending = service.get_pending(message.from_user.id)
    if pending is not None and not pending.rights_confirmed:
        await message.answer(
            build_rights_confirmation_message(
                pending.file_name,
                interface_language=interface_language,
            ),
            reply_markup=_rights_confirmation_keyboard(interface_language),
        )
        return
    if pending is not None and pending.translation_mode is None:
        await message.answer(
            build_translation_mode_required_message(interface_language)
        )
        return
    if pending is not None and not pending.preview_accepted:
        await message.answer(build_preview_required_message(interface_language))
        return
    total_fragments = pending.fragment_count if pending else 0
    heartbeat_pattern = _choose_heartbeat_pattern_name(
        user_telegram_id=message.from_user.id,
        file_name=pending.file_name if pending else "",
    )
    started_at = time.monotonic()
    progress_stats = {
        "completed": 0,
        "total": total_fragments,
        "estimated_total_seconds": pending.estimated_seconds if pending else None,
        "last_translated_text": None,
        "spinner_index": 0,
        "heartbeat_pattern": heartbeat_pattern,
        "tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cache_hit_tokens": 0,
        "cache_miss_tokens": 0,
        "last_edit_scheduled_at": started_at,
        "job_id": None,
    }
    progress_message = await message.answer(
        _progress_message_for_current_user_language(
            service=service,
            user_telegram_id=message.from_user.id,
            completed_fragments=0,
            total_fragments=total_fragments,
            estimated_total_seconds=pending.estimated_seconds if pending else None,
            elapsed_seconds=0,
            last_translated_text=None,
            activity_indicator=_next_heartbeat_frame(heartbeat_pattern, -1),
            activity_phrase_index=0,
        ),
        reply_markup=_cancel_inline_keyboard(interface_language),
        parse_mode="HTML",
    )
    loop = asyncio.get_running_loop()
    stop_heartbeat = asyncio.Event()

    def report_progress(progress: TranslationProgress | tuple[int, int]) -> None:
        now = time.monotonic()
        completed_fragments, total = _progress_counts(progress)
        elapsed_seconds = max(1, round(now - started_at))
        estimated_total_seconds = None
        if completed_fragments > 0:
            estimated_total_seconds = round(
                elapsed_seconds / completed_fragments * max(total, completed_fragments)
            )
        last_translated_text = _progress_translated_text(progress)
        progress_stats["completed"] = completed_fragments
        progress_stats["total"] = total
        progress_stats["estimated_total_seconds"] = estimated_total_seconds
        progress_stats["last_translated_text"] = last_translated_text
        progress_stats["spinner_index"] = int(progress_stats["spinner_index"]) + 1
        progress_text = _progress_message_for_current_user_language(
            service=service,
            user_telegram_id=message.from_user.id,
            completed_fragments=completed_fragments,
            total_fragments=total,
            estimated_total_seconds=estimated_total_seconds,
            elapsed_seconds=elapsed_seconds,
            last_translated_text=last_translated_text,
            activity_indicator=_next_heartbeat_frame(
                str(progress_stats["heartbeat_pattern"]),
                int(progress_stats["spinner_index"]) - 1,
            ),
            activity_phrase_index=int(progress_stats["spinner_index"]),
        )
        if isinstance(progress, TranslationProgress):
            progress_stats["tokens"] += progress.total_tokens
            progress_stats["prompt_tokens"] += progress.prompt_tokens
            progress_stats["completion_tokens"] += progress.completion_tokens
            progress_stats["cache_hit_tokens"] += progress.prompt_cache_hit_tokens
            progress_stats["cache_miss_tokens"] += progress.prompt_cache_miss_tokens
            _print_translation_progress_update(
                progress=progress,
                elapsed_total_seconds=elapsed_seconds,
                is_stopping=service.is_translation_cancelling(message.from_user.id),
            )
        if _should_schedule_progress_edit(progress_stats, now=now):
            _schedule_message_edit(
                loop=loop,
                message=progress_message,
                text=progress_text,
                reply_markup=_cancel_inline_keyboard(
                    service.get_interface_language(message.from_user.id)
                ),
                should_edit=_translation_progress_edit_guard(
                    service=service,
                    user_telegram_id=message.from_user.id,
                    job_id_getter=lambda: (
                        str(progress_stats["job_id"])
                        if progress_stats.get("job_id")
                        else None
                    ),
                ),
                progress_stats=progress_stats,
            )

    heartbeat_task = asyncio.create_task(
        _run_translation_progress_heartbeat(
            stop_event=stop_heartbeat,
            loop=loop,
            message=progress_message,
            interface_language=interface_language,
            service=service,
            user_telegram_id=message.from_user.id,
            started_at=started_at,
            progress_stats=progress_stats,
        )
    )
    try:
        job = await asyncio.to_thread(
            service.confirm_pending_translation,
            user_telegram_id=message.from_user.id,
            translator=translator,
            progress_callback=report_progress,
        )
    except SecurityCooldownActive as error:
        stop_heartbeat.set()
        await heartbeat_task
        await message.answer(build_upload_error_message(error, interface_language))
        return
    except RightsConfirmationRequired:
        stop_heartbeat.set()
        await heartbeat_task
        pending_upload = service.get_pending_upload(message.from_user.id)
        pending = service.get_pending(message.from_user.id)
        file_name = (
            pending_upload.file_name
            if pending_upload is not None
            else (pending.file_name if pending is not None else "document")
        )
        await message.answer(
            build_rights_confirmation_message(
                file_name,
                interface_language=interface_language,
            ),
            reply_markup=_rights_confirmation_keyboard(interface_language),
        )
        return
    except TranslationModeRequired:
        stop_heartbeat.set()
        await heartbeat_task
        pending_upload = service.get_pending_upload(message.from_user.id)
        pending = service.get_pending(message.from_user.id)
        await message.answer(
            build_translation_mode_selection_message(
                (
                    pending_upload.file_name
                    if pending_upload is not None
                    else (pending.file_name if pending is not None else "document")
                ),
                interface_language=interface_language,
                source_language_display=(
                    pending_upload.source_language_display
                    if pending_upload is not None
                    else (
                        pending.source_language_display
                        if pending is not None
                        else None
                    )
                ),
            ),
            reply_markup=_translation_mode_keyboard(interface_language),
        )
        return
    except PreviewAcceptanceRequired:
        stop_heartbeat.set()
        await heartbeat_task
        await message.answer(build_preview_required_message(interface_language))
        return
    except BetaAccessDenied as error:
        stop_heartbeat.set()
        await heartbeat_task
        await message.answer(build_upload_error_message(error, interface_language))
        return
    except ValueError as error:
        stop_heartbeat.set()
        await heartbeat_task
        await message.answer(str(error))
        return

    if job.status in {TranslationJobStatus.QUEUED, TranslationJobStatus.TRANSLATING}:
        watched_job = await _watch_worker_translation_progress(
            message=progress_message,
            service=service,
            user_telegram_id=message.from_user.id,
            job_id=job.id,
            started_at=started_at,
            progress_stats=progress_stats,
        )
        if watched_job is not None:
            job = watched_job

    stop_heartbeat.set()

    await heartbeat_task

    _print_translation_summary(
        job_id=job.id,
        file_name=job.file_name,
        result_file_name=job.result_file_name,
        document_kind=job.document_kind.value,
        completed_fragments=progress_stats["completed"],
        total_fragments=int(progress_stats["total"]),
        elapsed_seconds=time.monotonic() - started_at,
        prompt_tokens=progress_stats["prompt_tokens"],
        completion_tokens=progress_stats["completion_tokens"],
        total_tokens=progress_stats["tokens"],
        prompt_cache_hit_tokens=progress_stats["cache_hit_tokens"],
        prompt_cache_miss_tokens=progress_stats["cache_miss_tokens"],
        status=job.status.value,
    )
    await _edit_callback_message(
        progress_message,
        build_translation_job_status_message(
            job,
            interface_language=service.get_interface_language(message.from_user.id),
        ),
        reply_markup=None,
    )
    if job.result_file_name and job.result_content:
        await _send_translation_result_document_once(message, job, service)


async def _confirm_pending_upload_rights(
    *,
    message,
    service: BotTranslationService,
) -> None:
    interface_language = service.get_interface_language(message.from_user.id)
    pending_upload = service.get_pending_upload(message.from_user.id)
    if pending_upload is None:
        pending = service.get_pending(message.from_user.id)
        if pending is not None:
            await message.answer(
                build_pending_translation_message(
                    pending,
                    interface_language=interface_language,
                ),
                reply_markup=_confirm_keyboard(interface_language, include_back=True),
            )
            return
        await message.answer(build_no_pending_translation_message(interface_language))
        return

    try:
        confirmed = service.confirm_pending_upload_rights(
            user_telegram_id=message.from_user.id,
        )
    except (BetaAccessDenied, SecurityCooldownActive) as error:
        await message.answer(build_upload_error_message(error, interface_language))
        return
    except ValueError as error:
        await message.answer(str(error))
        return

    await message.answer(
        build_translation_mode_selection_message(
            confirmed.file_name,
            interface_language=interface_language,
            source_language_display=confirmed.source_language_display,
        ),
        reply_markup=_translation_mode_keyboard(interface_language),
    )


async def _resume_user_book_translation(
    *,
    message,
    user_telegram_id: int,
    job_id: str,
    service: BotTranslationService,
    translator: TextTranslator,
    queued_poll_interval_seconds: float = (
        TRANSLATION_PROGRESS_EDIT_MIN_INTERVAL_SECONDS
    ),
) -> None:
    interface_language = service.get_interface_language(user_telegram_id)
    heartbeat_pattern = _choose_heartbeat_pattern_name(
        user_telegram_id=user_telegram_id,
        file_name=job_id,
    )
    started_at = time.monotonic()
    progress_stats = {
        "completed": 0,
        "total": 0,
        "estimated_total_seconds": None,
        "last_translated_text": None,
        "spinner_index": 0,
        "heartbeat_pattern": heartbeat_pattern,
        "tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cache_hit_tokens": 0,
        "cache_miss_tokens": 0,
        "last_edit_scheduled_at": started_at,
        "job_id": job_id,
    }
    progress_message = await _send_translation_progress_message(
        message,
        _progress_message_for_current_user_language(
            service=service,
            user_telegram_id=user_telegram_id,
            completed_fragments=0,
            total_fragments=0,
            estimated_total_seconds=None,
            elapsed_seconds=0,
            last_translated_text=None,
            activity_indicator=_next_heartbeat_frame(heartbeat_pattern, -1),
            activity_phrase_index=0,
        ),
        reply_markup=_cancel_inline_keyboard(interface_language, job_id=job_id),
    )
    loop = asyncio.get_running_loop()
    stop_heartbeat = asyncio.Event()

    def report_progress(progress: TranslationProgress | tuple[int, int]) -> None:
        now = time.monotonic()
        completed_fragments, total = _progress_counts(progress)
        elapsed_seconds = max(1, round(now - started_at))
        estimated_total_seconds = None
        if completed_fragments > 0:
            estimated_total_seconds = round(
                elapsed_seconds / completed_fragments * max(total, completed_fragments)
            )
        last_translated_text = _progress_translated_text(progress)
        progress_stats["completed"] = completed_fragments
        progress_stats["total"] = total
        progress_stats["estimated_total_seconds"] = estimated_total_seconds
        progress_stats["last_translated_text"] = last_translated_text
        progress_stats["spinner_index"] = int(progress_stats["spinner_index"]) + 1
        progress_text = _progress_message_for_current_user_language(
            service=service,
            user_telegram_id=user_telegram_id,
            completed_fragments=completed_fragments,
            total_fragments=total,
            estimated_total_seconds=estimated_total_seconds,
            elapsed_seconds=elapsed_seconds,
            last_translated_text=last_translated_text,
            activity_indicator=_next_heartbeat_frame(
                str(progress_stats["heartbeat_pattern"]),
                int(progress_stats["spinner_index"]) - 1,
            ),
            activity_phrase_index=int(progress_stats["spinner_index"]),
        )
        if isinstance(progress, TranslationProgress):
            progress_stats["tokens"] += progress.total_tokens
            progress_stats["prompt_tokens"] += progress.prompt_tokens
            progress_stats["completion_tokens"] += progress.completion_tokens
            progress_stats["cache_hit_tokens"] += progress.prompt_cache_hit_tokens
            progress_stats["cache_miss_tokens"] += progress.prompt_cache_miss_tokens
            _print_translation_progress_update(
                progress=progress,
                elapsed_total_seconds=elapsed_seconds,
                is_stopping=service.is_translation_cancelling(user_telegram_id),
            )
        if _should_schedule_progress_edit(progress_stats, now=now):
            _schedule_message_edit(
                loop=loop,
                message=progress_message,
                text=progress_text,
                reply_markup=_cancel_inline_keyboard(
                    service.get_interface_language(user_telegram_id),
                    job_id=job_id,
                ),
                should_edit=_translation_progress_edit_guard(
                    service=service,
                    user_telegram_id=user_telegram_id,
                    job_id=job_id,
                ),
                progress_stats=progress_stats,
            )

    heartbeat_task = asyncio.create_task(
        _run_translation_progress_heartbeat(
            stop_event=stop_heartbeat,
            loop=loop,
            message=progress_message,
            interface_language=interface_language,
            service=service,
            user_telegram_id=user_telegram_id,
            started_at=started_at,
            progress_stats=progress_stats,
        )
    )
    try:
        job = await asyncio.to_thread(
            service.resume_user_book_translation,
            user_telegram_id=user_telegram_id,
            job_id=job_id,
            translator=translator,
            progress_callback=report_progress,
        )
    except SecurityCooldownActive as error:
        stop_heartbeat.set()
        await heartbeat_task
        await message.answer(build_upload_error_message(error, interface_language))
        return
    except BetaAccessDenied as error:
        stop_heartbeat.set()
        await heartbeat_task
        await message.answer(build_upload_error_message(error, interface_language))
        return

    if job is not None and job.status in {
        TranslationJobStatus.QUEUED,
        TranslationJobStatus.TRANSLATING,
    }:
        watched_job = await _watch_worker_translation_progress(
            message=progress_message,
            service=service,
            user_telegram_id=user_telegram_id,
            job_id=job.id,
            started_at=started_at,
            progress_stats=progress_stats,
            poll_interval_seconds=queued_poll_interval_seconds,
        )
        if watched_job is not None:
            job = watched_job

    stop_heartbeat.set()

    await heartbeat_task
    if job is None:
        await message.answer(build_download_unavailable_message(interface_language))
        return

    _print_translation_summary(
        job_id=job.id,
        file_name=job.file_name,
        result_file_name=job.result_file_name,
        document_kind=job.document_kind.value,
        completed_fragments=progress_stats["completed"],
        total_fragments=int(progress_stats["total"]),
        elapsed_seconds=time.monotonic() - started_at,
        prompt_tokens=progress_stats["prompt_tokens"],
        completion_tokens=progress_stats["completion_tokens"],
        total_tokens=progress_stats["tokens"],
        prompt_cache_hit_tokens=progress_stats["cache_hit_tokens"],
        prompt_cache_miss_tokens=progress_stats["cache_miss_tokens"],
        status=job.status.value,
    )
    detail = service.get_user_book_detail(
        user_telegram_id=user_telegram_id,
        job_id=job.id,
    )
    await _edit_callback_message(
        progress_message,
        build_translation_job_status_message(
            job,
            interface_language=service.get_interface_language(user_telegram_id),
        ),
        reply_markup=(
            _my_book_detail_keyboard(
                detail,
                interface_language=service.get_interface_language(user_telegram_id),
            )
            if detail is not None
            else None
        ),
    )
    if job.result_file_name and job.result_content:
        await _send_translation_result_document_once(message, job, service)


async def _cancel_active_translation(
    *,
    message,
    service: BotTranslationService,
) -> None:
    interface_language = service.get_interface_language(message.from_user.id)
    result = service.cancel_translation_with_result(message.from_user.id)
    if result.cancelled:
        if result.job is not None:
            await message.answer(
                build_translation_job_status_message(
                    result.job,
                    interface_language=interface_language,
                )
            )
            await _send_translation_result_document_once(message, result.job, service)
        else:
            await message.answer(build_cancel_requested_message(interface_language))
        return

    if service.discard_pending_translation(message.from_user.id):
        await message.answer(build_back_to_menu_message(interface_language))
        await message.answer(
            get_main_menu_text(interface_language=interface_language),
            reply_markup=_main_menu_keyboard(interface_language),
        )
        return

    await message.answer(build_nothing_to_cancel_message(interface_language))


async def _send_translation_result_document_once(
    message,
    job: TranslationJob,
    service: BotTranslationService,
) -> None:
    if not service.begin_automatic_result_delivery(job):
        return

    delivered = False
    try:
        await _send_translation_result_document(message, job)
        delivered = True
    finally:
        service.finish_automatic_result_delivery(job, delivered=delivered)


async def _send_translation_result_document(message, job: TranslationJob) -> None:
    if not (job.result_file_name and job.result_content):
        return

    from aiogram.types import BufferedInputFile

    await message.answer_document(
        BufferedInputFile(job.result_content, filename=job.result_file_name)
    )


async def _send_translation_progress_message(message, text: str, reply_markup=None):
    answer = getattr(message, "answer", None)
    if callable(answer):
        return await answer(
            text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )

    await _edit_callback_message(message, text, reply_markup=reply_markup)
    return message


async def _watch_worker_translation_progress(
    *,
    message,
    service: BotTranslationService,
    user_telegram_id: int,
    job_id: str,
    started_at: float,
    progress_stats: dict[str, object],
    poll_interval_seconds: float = TRANSLATION_PROGRESS_EDIT_MIN_INTERVAL_SECONDS,
):
    progress_stats["job_id"] = job_id
    current_job = service.get_user_book_translation_job(
        user_telegram_id=user_telegram_id,
        job_id=job_id,
    )
    while current_job is not None and current_job.status in {
        TranslationJobStatus.QUEUED,
        TranslationJobStatus.TRANSLATING,
    }:
        progress = service.get_user_book_progress(
            user_telegram_id=user_telegram_id,
            job_id=job_id,
        )
        if progress is None:
            break

        interface_language = service.get_interface_language(user_telegram_id)
        progress_stats["job_status"] = current_job.status.value
        progress_stats["completed"] = progress.completed_fragments
        progress_stats["total"] = progress.total_fragments
        now = time.monotonic()
        elapsed_seconds = max(1, round(now - started_at))
        estimated_total_seconds = _polled_progress_estimated_total_seconds(
            progress,
            elapsed_seconds=elapsed_seconds,
        )
        progress_stats["estimated_total_seconds"] = estimated_total_seconds
        progress_stats["spinner_index"] = int(progress_stats["spinner_index"]) + 1
        if current_job.status is TranslationJobStatus.QUEUED:
            progress_text = build_translation_job_status_message(
                current_job,
                interface_language=interface_language,
            )
            progress_stats["job_status_message"] = progress_text
        else:
            progress_stats["job_status_message"] = None
            progress_text = _progress_message_for_current_user_language(
                service=service,
                user_telegram_id=user_telegram_id,
                completed_fragments=progress.completed_fragments,
                total_fragments=progress.total_fragments,
                estimated_total_seconds=estimated_total_seconds,
                elapsed_seconds=elapsed_seconds,
                last_translated_text=None,
                activity_indicator=_next_heartbeat_frame(
                    str(progress_stats["heartbeat_pattern"]),
                    int(progress_stats["spinner_index"]) - 1,
                ),
                activity_phrase_index=int(progress_stats["spinner_index"]),
            )
        edit_allowed = _translation_progress_edit_guard(
            service=service,
            user_telegram_id=user_telegram_id,
            job_id=job_id,
        )
        if not edit_allowed():
            await asyncio.sleep(max(0.1, poll_interval_seconds))
        elif not _should_schedule_worker_progress_edit(
            progress_stats,
            now=now,
            min_interval_seconds=poll_interval_seconds,
        ):
            await asyncio.sleep(max(0.1, poll_interval_seconds))
        else:
            await _edit_progress_message_if_changed(
                message,
                progress_text,
                reply_markup=_cancel_inline_keyboard(
                    interface_language,
                    job_id=job_id,
                ),
                should_edit=edit_allowed,
                progress_stats=progress_stats,
            )

        current_job = service.get_user_book_translation_job(
            user_telegram_id=user_telegram_id,
            job_id=job_id,
        )

    return current_job or service.get_user_book_translation_job(
        user_telegram_id=user_telegram_id,
        job_id=job_id,
    )


async def _run_translation_progress_heartbeat(
    *,
    stop_event: asyncio.Event,
    loop,
    message,
    interface_language: str,
    service: BotTranslationService,
    user_telegram_id: int,
    started_at: float,
    progress_stats: dict[str, object],
) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=TRANSLATION_SPINNER_INTERVAL_SECONDS,
            )
            return
        except TimeoutError:
            pass

        now = time.monotonic()
        progress_stats["spinner_index"] = int(progress_stats["spinner_index"]) + 1
        elapsed_seconds = max(1, round(now - started_at))
        completed_fragments = int(progress_stats["completed"])
        total_fragments = int(progress_stats["total"])
        estimated_total_seconds = progress_stats["estimated_total_seconds"]
        if estimated_total_seconds is None and completed_fragments > 0:
            estimated_total_seconds = round(
                elapsed_seconds
                / completed_fragments
                * max(total_fragments, completed_fragments)
            )
        if progress_stats.get("job_status") == TranslationJobStatus.QUEUED.value:
            progress_text = str(progress_stats.get("job_status_message") or "")
        else:
            progress_text = _progress_message_for_current_user_language(
                service=service,
                user_telegram_id=user_telegram_id,
                completed_fragments=completed_fragments,
                total_fragments=total_fragments,
                estimated_total_seconds=(
                    int(estimated_total_seconds)
                    if estimated_total_seconds is not None
                    else None
                ),
                elapsed_seconds=elapsed_seconds,
                last_translated_text=(
                    str(progress_stats["last_translated_text"])
                    if progress_stats["last_translated_text"]
                    else None
                ),
                activity_indicator=_next_heartbeat_frame(
                    str(progress_stats["heartbeat_pattern"]),
                    int(progress_stats["spinner_index"]) - 1,
                ),
                activity_phrase_index=int(progress_stats["spinner_index"]),
            )
        if _should_schedule_progress_edit(progress_stats, now=now):
            job_id = progress_stats.get("job_id")
            current_job_id = str(job_id) if job_id else None
            _schedule_message_edit(
                loop=loop,
                message=message,
                text=progress_text,
                reply_markup=_cancel_inline_keyboard(
                    service.get_interface_language(user_telegram_id),
                    job_id=current_job_id,
                ),
                should_edit=_translation_progress_edit_guard(
                    service=service,
                    user_telegram_id=user_telegram_id,
                    job_id=current_job_id,
                ),
                progress_stats=progress_stats,
            )


def _schedule_message_edit(
    *,
    loop,
    message,
    text: str,
    reply_markup=None,
    should_edit=None,
    progress_stats: dict[str, object] | None = None,
):
    async def edit_message() -> None:
        if should_edit is not None and not should_edit():
            return
        bot = getattr(message, "bot", None)
        chat = getattr(message, "chat", None)
        message_id = getattr(message, "message_id", None)
        if bot is not None and chat is not None and message_id is not None:
            await bot.edit_message_text(
                text=text,
                chat_id=chat.id,
                message_id=message_id,
                reply_markup=_inline_reply_markup_or_none(reply_markup),
                parse_mode="HTML",
            )
            return

        result = message.edit_text(text)
        if inspect.isawaitable(result):
            await result

    future = asyncio.run_coroutine_threadsafe(edit_message(), loop)
    future.add_done_callback(
        lambda completed: _log_message_edit_error(
            completed,
            progress_stats=progress_stats,
        )
    )
    return future


def _should_schedule_progress_edit(
    progress_stats: dict[str, object],
    *,
    now: float,
    min_interval_seconds: float = TRANSLATION_PROGRESS_EDIT_MIN_INTERVAL_SECONDS,
) -> bool:
    retry_after_until = progress_stats.get("progress_edit_retry_after_until")
    if retry_after_until is not None:
        if now < float(retry_after_until):
            return False
        progress_stats.pop("progress_edit_retry_after_until", None)

    last_edit_scheduled_at = progress_stats.get("last_edit_scheduled_at")
    if last_edit_scheduled_at is not None:
        elapsed = now - float(last_edit_scheduled_at)
        if elapsed < min_interval_seconds:
            return False

    progress_stats["last_edit_scheduled_at"] = now
    return True


def _should_schedule_worker_progress_edit(
    progress_stats: dict[str, object],
    *,
    now: float,
    min_interval_seconds: float,
) -> bool:
    if (
        not progress_stats.get("worker_progress_edit_attempted")
        and progress_stats.get("progress_edit_retry_after_until") is None
    ):
        progress_stats["worker_progress_edit_attempted"] = True
        progress_stats["last_edit_scheduled_at"] = now
        return True

    should_edit = _should_schedule_progress_edit(
        progress_stats,
        now=now,
        min_interval_seconds=min_interval_seconds,
    )
    if should_edit:
        progress_stats["worker_progress_edit_attempted"] = True
    return should_edit


def _log_message_edit_error(
    future,
    *,
    progress_stats: dict[str, object] | None = None,
) -> None:
    try:
        future.result()
    except Exception as error:
        message = str(error)
        if _handle_progress_edit_retry_after(
            error,
            message,
            progress_stats=progress_stats,
        ):
            return
        if "message can't be edited" in message:
            logger.warning(
                "Telegram refused to edit translation progress message: %s",
                message,
            )
            return
        logger.exception("Failed to edit translation progress message")


def _handle_progress_edit_retry_after(
    error: Exception,
    message: str,
    *,
    progress_stats: dict[str, object] | None = None,
) -> bool:
    retry_after = _telegram_retry_after_seconds(error, message)
    if retry_after is None and "retry after" not in message.lower():
        return False
    if retry_after is not None and progress_stats is not None:
        progress_stats["progress_edit_retry_after_until"] = (
            time.monotonic() + retry_after
        )
    logger.warning(
        "Telegram flood control while editing progress message; "
        "retry_after=%s message=%s",
        retry_after if retry_after is not None else "unknown",
        message,
    )
    return True


def _telegram_retry_after_seconds(error: Exception, message: str) -> float | None:
    retry_after = getattr(error, "retry_after", None)
    if isinstance(retry_after, (int, float)):
        return max(0.0, float(retry_after))

    match = re.search(r"retry\s+in\s+([0-9]+(?:\.[0-9]+)?)\s+seconds?", message, re.I)
    if match is None:
        return None
    return max(0.0, float(match.group(1)))


def _progress_counts(
    progress: TranslationProgress | tuple[int, int],
) -> tuple[int, int]:
    if isinstance(progress, TranslationProgress):
        return progress.completed_fragments, progress.total_fragments
    return progress


def _progress_translated_text(
    progress: TranslationProgress | tuple[int, int],
) -> str | None:
    if isinstance(progress, TranslationProgress) and progress.translated_text:
        return progress.translated_text
    return None


def _polled_progress_estimated_total_seconds(
    progress,
    *,
    elapsed_seconds: int,
) -> int | None:
    completed_fragments = int(getattr(progress, "completed_fragments", 0) or 0)
    total_fragments = int(getattr(progress, "total_fragments", 0) or 0)
    if total_fragments <= 0:
        return None

    baseline_seconds = getattr(progress, "estimated_seconds", None)
    estimated_total_seconds = None
    if baseline_seconds is not None:
        estimated_total_seconds = max(elapsed_seconds, int(baseline_seconds))

    if completed_fragments <= 0:
        return estimated_total_seconds

    observed_total_seconds = round(
        elapsed_seconds
        / completed_fragments
        * max(total_fragments, completed_fragments)
    )
    if estimated_total_seconds is not None:
        return max(estimated_total_seconds, observed_total_seconds)
    return observed_total_seconds


def _include_progress_preview(
    service: BotTranslationService,
    user_telegram_id: int,
    translated_text: str | None,
) -> str | None:
    if not translated_text:
        return None
    if not service.get_progress_preview_enabled(user_telegram_id):
        return None
    return translated_text


def _next_spinner_frame(current_index: int) -> str:
    return TRANSLATION_SPINNER_FRAMES[
        (current_index + 1) % len(TRANSLATION_SPINNER_FRAMES)
    ]


def _choose_heartbeat_pattern_name(*, user_telegram_id: int, file_name: str) -> str:
    pattern_names = tuple(HEARTBEAT_PATTERNS)
    seed = f"{user_telegram_id}:{file_name}".encode()
    digest = hashlib.sha256(seed).digest()
    return pattern_names[digest[0] % len(pattern_names)]


def _next_heartbeat_frame(pattern_name: str, current_index: int) -> str:
    pattern = HEARTBEAT_PATTERNS.get(pattern_name, HEARTBEAT_PATTERNS["calm_dots"])
    return pattern[(current_index + 1) % len(pattern)]


def _print_translation_progress(
    *,
    progress: TranslationProgress,
    elapsed_total_seconds: int,
) -> None:
    status = "ok" if progress.success else "failed"
    print(
        "[translation] "
        f"fragment={progress.completed_fragments}/{progress.total_fragments} "
        f"status={status} "
        f"fragment_time={progress.elapsed_seconds:.2f}s "
        f"elapsed={elapsed_total_seconds}s "
        f"tokens={progress.total_tokens} "
        f"prompt_tokens={progress.prompt_tokens} "
        f"completion_tokens={progress.completion_tokens} "
        f"translated_chars={len(progress.translated_text)}",
        flush=True,
    )


def _print_translation_progress_update(
    *,
    progress: TranslationProgress,
    elapsed_total_seconds: int,
    is_stopping: bool,
) -> None:
    if not is_stopping:
        _print_translation_progress(
            progress=progress,
            elapsed_total_seconds=elapsed_total_seconds,
        )
        return

    print(
        "TRANSLATION STOPPING "
        f"fragment={progress.completed_fragments}/{progress.total_fragments} "
        "status=stopping "
        f"fragment_time={progress.elapsed_seconds:.2f}s "
        f"elapsed={elapsed_total_seconds}s "
        f"tokens={progress.total_tokens} "
        f"prompt_tokens={progress.prompt_tokens} "
        f"completion_tokens={progress.completion_tokens} "
        f"translated_chars={len(progress.translated_text)} "
        "note=waiting_for_active_requests",
        flush=True,
    )


def _print_translation_summary(
    *,
    job_id: str,
    file_name: str,
    result_file_name: str | None,
    document_kind: str,
    completed_fragments: int,
    total_fragments: int,
    elapsed_seconds: float,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    prompt_cache_hit_tokens: int,
    prompt_cache_miss_tokens: int,
    status: str,
) -> None:
    average_fragment_time = (
        elapsed_seconds / completed_fragments if completed_fragments > 0 else 0.0
    )
    summary = (
        "TRANSLATION FINISHED "
        f"status={status} "
        f"job_id={job_id} "
        f"file={file_name} "
        f"result={result_file_name or '-'} "
        f"kind={document_kind} "
        f"fragments={completed_fragments}/{total_fragments} "
        f"elapsed={elapsed_seconds:.2f}s "
        f"avg_fragment_time={average_fragment_time:.2f}s "
        f"tokens={total_tokens} "
        f"prompt_tokens={prompt_tokens} "
        f"completion_tokens={completion_tokens} "
        f"cache_hit_tokens={prompt_cache_hit_tokens} "
        f"cache_miss_tokens={prompt_cache_miss_tokens}"
    )
    if status in {"ready", "cancelled"}:
        summary = f"\033[92m{summary}\033[0m"
    print(summary, flush=True)


async def run_bot() -> None:
    settings = Settings()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    from aiogram import Bot, Dispatcher

    config = bot_runtime_config_from_settings(settings)
    service = build_translation_service(config)
    translator = build_deepseek_translator(settings)
    dispatcher = Dispatcher()
    dispatcher.include_router(
        create_router(service=service, translator=translator, config=config)
    )
    print(build_polling_started_message(), flush=True)
    try:
        await dispatcher.start_polling(Bot(token))
    finally:
        service.close()


def main() -> None:
    try:
        asyncio.run(run_bot())
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
