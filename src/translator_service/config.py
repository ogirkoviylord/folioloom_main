from dataclasses import dataclass, field
import os


def _env_int(name: str, default: str) -> int:
    return int(os.getenv(name, default))


def _env_float(name: str, default: str) -> float:
    return float(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    service_name: str = field(
        default_factory=lambda: os.getenv(
            "SERVICE_NAME",
            "DeepSeek Document Translator",
        )
    )
    environment: str = field(
        default_factory=lambda: os.getenv("ENVIRONMENT", "development")
    )
    max_upload_mb: int = field(default_factory=lambda: _env_int("MAX_UPLOAD_MB", "50"))
    deepseek_model: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    )
    object_storage_root: str = field(
        default_factory=lambda: os.getenv("OBJECT_STORAGE_ROOT", "var/object-storage")
    )
    persistent_jobs_db_path: str = field(
        default_factory=lambda: os.getenv(
            "PERSISTENT_JOBS_DB_PATH",
            "var/jobs.sqlite3",
        )
    )
    job_store_backend: str = field(
        default_factory=lambda: os.getenv("JOB_STORE_BACKEND", "sqlite")
    )
    postgres_dsn: str = field(
        default_factory=lambda: os.getenv(
            "POSTGRES_DSN",
            os.getenv(
                "DATABASE_URL",
                "postgresql://translator:translator@localhost:5432/translator",
            ),
        )
    )
    translation_execution_mode: str = field(
        default_factory=lambda: os.getenv("TRANSLATION_EXECUTION_MODE", "inline")
    )
    worker_poll_seconds: float = field(
        default_factory=lambda: _env_float("WORKER_POLL_SECONDS", "3")
    )
    work_unit_lease_seconds: int = field(
        default_factory=lambda: _env_int("WORK_UNIT_LEASE_SECONDS", "900")
    )
    worker_id: str = field(
        default_factory=lambda: os.getenv("WORKER_ID", "worker-local")
    )


def validate_server_settings(settings: Settings) -> None:
    if settings.work_unit_lease_seconds <= 0:
        raise ValueError("WORK_UNIT_LEASE_SECONDS must be greater than 0")
    if settings.translation_execution_mode == "worker":
        if settings.job_store_backend != "postgres":
            raise ValueError(
                "TRANSLATION_EXECUTION_MODE=worker requires JOB_STORE_BACKEND=postgres"
            )
        if not settings.postgres_dsn.startswith(("postgresql://", "postgres://")):
            raise ValueError("POSTGRES_DSN must be a PostgreSQL DSN")
    if not settings.object_storage_root:
        raise ValueError("OBJECT_STORAGE_ROOT is required")
