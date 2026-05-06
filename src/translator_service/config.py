from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    service_name: str = os.getenv("SERVICE_NAME", "DeepSeek Document Translator")
    environment: str = os.getenv("ENVIRONMENT", "development")
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "50"))
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    object_storage_root: str = os.getenv("OBJECT_STORAGE_ROOT", "var/object-storage")
    persistent_jobs_db_path: str = os.getenv(
        "PERSISTENT_JOBS_DB_PATH",
        "var/jobs.sqlite3",
    )
