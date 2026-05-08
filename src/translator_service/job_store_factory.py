from typing import Protocol

from translator_service.config import Settings
from translator_service.job_store import TranslationJobStore
from translator_service.persistent_jobs import SQLiteTranslationJobStore
from translator_service.postgres_jobs import PostgreSQLTranslationJobStore


class JobStoreSettings(Protocol):
    job_store_backend: str
    persistent_jobs_db_path: str
    postgres_dsn: str


def create_translation_job_store(
    settings: JobStoreSettings | Settings,
) -> TranslationJobStore:
    if settings.job_store_backend == "sqlite":
        return SQLiteTranslationJobStore(settings.persistent_jobs_db_path)
    if settings.job_store_backend == "postgres":
        return PostgreSQLTranslationJobStore(settings.postgres_dsn)
    raise ValueError(f"Unsupported JOB_STORE_BACKEND: {settings.job_store_backend}")
