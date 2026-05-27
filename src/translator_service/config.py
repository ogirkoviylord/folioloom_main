import os
import re
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float, *, minimum: float | None = None) -> float:
    raw = os.getenv(name)
    value = default if raw is None or not raw.strip() else float(raw)
    if minimum is not None:
        value = max(minimum, value)
    return value


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.getenv(name)
    value = default if raw is None or not raw.strip() else int(raw)
    if minimum is not None:
        value = max(minimum, value)
    return value


def _clamp(value: float, *, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _env_telegram_ids(name: str) -> tuple[int, ...]:
    raw = os.getenv(name, "")
    ids: list[int] = []
    seen: set[int] = set()
    for part in re.split(r"[\s,;]+", raw):
        if not part:
            continue
        try:
            user_id = int(part)
        except ValueError:
            continue
        if user_id <= 0 or user_id in seen:
            continue
        seen.add(user_id)
        ids.append(user_id)
    return tuple(ids)


@dataclass(frozen=True)
class Settings:
    service_name: str = os.getenv("SERVICE_NAME", "DeepSeek Document Translator")
    environment: str = os.getenv("ENVIRONMENT", "development")
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "50"))
    require_upload_scan: bool = field(
        default_factory=lambda: _env_bool("REQUIRE_UPLOAD_SCAN", False)
    )
    upload_scanner_backend: str = field(
        default_factory=lambda: os.getenv("UPLOAD_SCANNER_BACKEND", "none").lower()
    )
    upload_scan_max_concurrency: int = field(
        default_factory=lambda: _env_int("UPLOAD_SCAN_MAX_CONCURRENCY", 1, minimum=1)
    )
    upload_scan_backpressure_timeout_seconds: float = field(
        default_factory=lambda: _env_float(
            "UPLOAD_SCAN_BACKPRESSURE_TIMEOUT_SECONDS",
            1.0,
            minimum=0.0,
        )
    )
    clamd_host: str = field(
        default_factory=lambda: os.getenv("CLAMD_HOST", "127.0.0.1")
    )
    clamd_port: int = field(
        default_factory=lambda: _env_int("CLAMD_PORT", 3310, minimum=1)
    )
    clamd_timeout_seconds: float = field(
        default_factory=lambda: _env_float(
            "CLAMD_TIMEOUT_SECONDS",
            10.0,
            minimum=0.1,
        )
    )
    clamd_chunk_size_bytes: int = field(
        default_factory=lambda: _env_int(
            "CLAMD_CHUNK_SIZE_BYTES",
            65536,
            minimum=1,
        )
    )
    clamd_response_limit_bytes: int = field(
        default_factory=lambda: _env_int(
            "CLAMD_RESPONSE_LIMIT_BYTES",
            4096,
            minimum=1,
        )
    )
    beta_allowlist_enabled: bool = field(
        default_factory=lambda: _env_bool("BETA_ALLOWLIST_ENABLED", False)
    )
    beta_allowlist_telegram_ids: tuple[int, ...] = field(
        default_factory=lambda: _env_telegram_ids("BETA_ALLOWLIST_TELEGRAM_IDS")
    )
    beta_translations_paused: bool = field(
        default_factory=lambda: _env_bool("BETA_TRANSLATIONS_PAUSED", False)
    )
    beta_global_daily_cost_cap_usd: float = field(
        default_factory=lambda: _env_float(
            "BETA_GLOBAL_DAILY_COST_CAP_USD",
            5.0,
            minimum=0.0,
        )
    )
    beta_global_monthly_cost_cap_usd: float = field(
        default_factory=lambda: _env_float(
            "BETA_GLOBAL_MONTHLY_COST_CAP_USD",
            50.0,
            minimum=0.0,
        )
    )
    beta_user_daily_cost_cap_usd: float = field(
        default_factory=lambda: _env_float(
            "BETA_USER_DAILY_COST_CAP_USD",
            1.0,
            minimum=0.0,
        )
    )
    beta_user_monthly_cost_cap_usd: float = field(
        default_factory=lambda: _env_float(
            "BETA_USER_MONTHLY_COST_CAP_USD",
            10.0,
            minimum=0.0,
        )
    )
    beta_user_daily_job_limit: int = field(
        default_factory=lambda: _env_int(
            "BETA_USER_DAILY_JOB_LIMIT",
            3,
            minimum=0,
        )
    )
    beta_max_job_estimated_cost_usd: float = field(
        default_factory=lambda: _env_float(
            "BETA_MAX_JOB_ESTIMATED_COST_USD",
            2.0,
            minimum=0.0,
        )
    )
    beta_cost_input_usd_per_million: float = field(
        default_factory=lambda: _env_float(
            "BETA_COST_INPUT_USD_PER_MILLION",
            0.28,
            minimum=0.0,
        )
    )
    beta_cost_output_usd_per_million: float = field(
        default_factory=lambda: _env_float(
            "BETA_COST_OUTPUT_USD_PER_MILLION",
            1.10,
            minimum=0.0,
        )
    )
    beta_cost_warning_fraction: float = field(
        default_factory=lambda: _clamp(
            _env_float("BETA_COST_WARNING_FRACTION", 0.8),
            minimum=0.0,
            maximum=1.0,
        )
    )
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    object_storage_root: str = os.getenv("OBJECT_STORAGE_ROOT", "var/object-storage")
    persistent_jobs_db_path: str = os.getenv(
        "PERSISTENT_JOBS_DB_PATH",
        "var/jobs.sqlite3",
    )
    user_settings_db_path: str = os.getenv(
        "USER_SETTINGS_DB_PATH",
        "var/user-settings.sqlite3",
    )
    translation_run_log_root: str = field(
        default_factory=lambda: os.getenv(
            "TRANSLATION_RUN_LOG_ROOT",
            "var/translation-runs",
        )
    )
    translation_max_parallel_units: int = field(
        default_factory=lambda: max(
            1,
            int(os.getenv("TRANSLATION_MAX_PARALLEL_UNITS", "1")),
        )
    )
    bot_defer_persistent_jobs_to_worker: bool = field(
        default_factory=lambda: _env_bool("BOT_DEFER_PERSISTENT_JOBS_TO_WORKER", False)
    )
    scheduler_backend: str = field(
        default_factory=lambda: os.getenv("SCHEDULER_BACKEND", "sqlite")
    )
    postgres_dsn: str = field(
        default_factory=lambda: os.getenv(
            "POSTGRES_DSN",
            "postgresql://translator:translator@localhost:5432/translator",
        )
    )
    scheduler_lease_seconds: int = field(
        default_factory=lambda: max(
            1,
            int(os.getenv("SCHEDULER_LEASE_SECONDS", "300")),
        )
    )
    scheduler_poll_seconds: float = field(
        default_factory=lambda: max(
            0.1,
            float(os.getenv("SCHEDULER_POLL_SECONDS", "2.0")),
        )
    )
    scheduler_retry_base_delay_seconds: int = field(
        default_factory=lambda: max(
            0,
            int(os.getenv("SCHEDULER_RETRY_BASE_DELAY_SECONDS", "30")),
        )
    )
    scheduler_retry_max_delay_seconds: int = field(
        default_factory=lambda: max(
            0,
            int(os.getenv("SCHEDULER_RETRY_MAX_DELAY_SECONDS", "600")),
        )
    )
    scheduler_max_active_units_global: int = field(
        default_factory=lambda: max(
            1,
            int(os.getenv("SCHEDULER_MAX_ACTIVE_UNITS_GLOBAL", "2")),
        )
    )
    scheduler_max_active_units_per_user: int = field(
        default_factory=lambda: max(
            1,
            int(os.getenv("SCHEDULER_MAX_ACTIVE_UNITS_PER_USER", "1")),
        )
    )
    scheduler_max_active_jobs_per_user: int = field(
        default_factory=lambda: max(
            1,
            int(os.getenv("SCHEDULER_MAX_ACTIVE_JOBS_PER_USER", "1")),
        )
    )
    scheduler_max_active_units_per_job: int = field(
        default_factory=lambda: max(
            1,
            int(os.getenv("SCHEDULER_MAX_ACTIVE_UNITS_PER_JOB", "1")),
        )
    )
    scheduler_priority_aging_seconds: int = field(
        default_factory=lambda: max(
            0,
            int(os.getenv("SCHEDULER_PRIORITY_AGING_SECONDS", "1800")),
        )
    )
    security_max_events_per_run: int = field(
        default_factory=lambda: max(
            0,
            int(os.getenv("SECURITY_MAX_EVENTS_PER_RUN", "20")),
        )
    )
    security_max_unsafe_model_outputs_per_run: int = field(
        default_factory=lambda: max(
            0,
            int(os.getenv("SECURITY_MAX_UNSAFE_MODEL_OUTPUTS_PER_RUN", "3")),
        )
    )
    security_max_repair_failures_per_run: int = field(
        default_factory=lambda: max(
            0,
            int(os.getenv("SECURITY_MAX_REPAIR_FAILURES_PER_RUN", "1")),
        )
    )
    security_user_cooldown_thresholds_per_window: int = field(
        default_factory=lambda: max(
            0,
            int(os.getenv("SECURITY_USER_COOLDOWN_THRESHOLDS_PER_WINDOW", "2")),
        )
    )
    security_user_cooldown_window_seconds: int = field(
        default_factory=lambda: max(
            0,
            int(os.getenv("SECURITY_USER_COOLDOWN_WINDOW_SECONDS", "3600")),
        )
    )
    security_user_cooldown_seconds: int = field(
        default_factory=lambda: max(
            0,
            int(os.getenv("SECURITY_USER_COOLDOWN_SECONDS", "900")),
        )
    )
    admin_db_path: str = field(
        default_factory=lambda: os.getenv("ADMIN_DB_PATH", "var/admin.sqlite3")
    )
    admin_session_secret: str = field(
        default_factory=lambda: os.getenv("ADMIN_SESSION_SECRET", "")
    )
    admin_owner_password: str = field(
        default_factory=lambda: os.getenv("ADMIN_OWNER_PASSWORD", "")
    )
    admin_secret_master_key: str = field(
        default_factory=lambda: os.getenv("ADMIN_SECRET_MASTER_KEY", "")
    )
    admin_cookie_secure: bool = field(
        default_factory=lambda: _env_bool("ADMIN_COOKIE_SECURE", False)
    )
    admin_provider_probe_timeout_seconds: float = field(
        default_factory=lambda: max(
            0.1,
            float(os.getenv("ADMIN_PROVIDER_PROBE_TIMEOUT_SECONDS", "10")),
        )
    )
    admin_provider_runtime_reload_seconds: float = field(
        default_factory=lambda: max(
            0.0,
            float(os.getenv("ADMIN_PROVIDER_RUNTIME_RELOAD_SECONDS", "30")),
        )
    )
    admin_deepseek_balance_stale_seconds: int = field(
        default_factory=lambda: max(
            1,
            int(os.getenv("ADMIN_DEEPSEEK_BALANCE_STALE_SECONDS", "300")),
        )
    )
    admin_deepseek_low_balance_threshold: str = field(
        default_factory=lambda: os.getenv(
            "ADMIN_DEEPSEEK_LOW_BALANCE_THRESHOLD",
            "5.00",
        )
    )
    admin_deepseek_low_balance_currency: str = field(
        default_factory=lambda: os.getenv("ADMIN_DEEPSEEK_LOW_BALANCE_CURRENCY", "USD")
    )
    admin_deepseek_top_up_url: str = field(
        default_factory=lambda: os.getenv(
            "ADMIN_DEEPSEEK_TOP_UP_URL",
            "https://platform.deepseek.com/usage",
        )
    )
