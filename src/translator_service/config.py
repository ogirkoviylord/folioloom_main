import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    service_name: str = os.getenv("SERVICE_NAME", "DeepSeek Document Translator")
    environment: str = os.getenv("ENVIRONMENT", "development")
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "50"))
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
