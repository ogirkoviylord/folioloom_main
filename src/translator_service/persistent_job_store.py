from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from translator_service.persistent_jobs import (
    ApprovedGlossarySnapshot,
    DeleteJobResult,
    GlossaryApproval,
    JobUsageSummary,
    PersistentTranslationJob,
    PersistentTranslationJobStatus,
    PersistentWorkUnit,
    SQLiteTranslationJobStore,
    StrictAdmissionResult,
    StrictDocxAdmissionRequest,
    WorkUnitPlan,
)


class PersistentJobStore(Protocol):
    def close(self) -> None: ...

    def create_job(self, **kwargs) -> PersistentTranslationJob: ...

    def get_job(self, job_id: str) -> PersistentTranslationJob | None: ...

    def add_work_units(
        self,
        job_id: str,
        work_units: list[WorkUnitPlan],
    ) -> list[PersistentWorkUnit]: ...

    def list_work_units(self, job_id: str) -> list[PersistentWorkUnit]: ...

    def list_recent_work_units(
        self,
        job_id: str,
        *,
        limit: int,
    ) -> list[PersistentWorkUnit]: ...

    def list_jobs_by_status(
        self,
        status: PersistentTranslationJobStatus,
        *,
        limit: int = 50,
    ) -> list[PersistentTranslationJob]: ...

    def list_jobs_for_user(
        self,
        user_id: str,
        *,
        limit: int = 10,
    ) -> list[PersistentTranslationJob]: ...

    def cancel_job(self, job_id: str) -> PersistentTranslationJob: ...

    def request_cancel_job(self, job_id: str) -> PersistentTranslationJob: ...

    def pause_job(self, job_id: str) -> PersistentTranslationJob: ...

    def resume_job(self, job_id: str) -> PersistentTranslationJob: ...

    def delete_job(self, job_id: str) -> DeleteJobResult | bool: ...

    def mark_job_interrupted(self, job_id: str) -> PersistentTranslationJob: ...

    def mark_job_failed(self, job_id: str) -> PersistentTranslationJob: ...

    def get_usage_summary(self, job_id: str) -> JobUsageSummary: ...


@runtime_checkable
class StrictDocxJobStore(PersistentJobStore, Protocol):
    def create_glossary_approval(
        self,
        *,
        snapshot_payload: bytes,
        snapshot_digest: str,
        snapshot_schema_version: int,
        approval_schema_version: int,
    ) -> GlossaryApproval: ...

    def revoke_glossary_approval(self, *, approval_id: str) -> GlossaryApproval: ...

    def read_approved_glossary_snapshot(
        self,
        *,
        approval_id: str,
    ) -> ApprovedGlossarySnapshot | None: ...

    def admit_strict_docx_job(
        self,
        request: StrictDocxAdmissionRequest,
    ) -> StrictAdmissionResult: ...


def admit_strict_docx_job(
    store: PersistentJobStore,
    request: StrictDocxAdmissionRequest,
) -> StrictAdmissionResult:
    if not isinstance(store, StrictDocxJobStore):
        return StrictAdmissionResult(
            job=None,
            work_units=[],
            denial_code="strict_docx_unsupported_backend",
        )
    return store.admit_strict_docx_job(request)


class PersistentJobStoreSettings(Protocol):
    scheduler_backend: str
    persistent_jobs_db_path: str
    postgres_dsn: str


def open_persistent_job_store(
    settings: PersistentJobStoreSettings,
) -> PersistentJobStore:
    if settings.scheduler_backend == "sqlite":
        return SQLiteTranslationJobStore(settings.persistent_jobs_db_path)
    if settings.scheduler_backend == "postgres":
        from translator_service.postgres_scheduler import (
            PostgresSchedulerStore,
            initialize_postgres_scheduler_schema,
        )

        store = PostgresSchedulerStore(settings.postgres_dsn)
        try:
            initialize_postgres_scheduler_schema(store.connection)
        except Exception:
            store.close()
            raise
        return store
    raise ValueError(f"Unsupported scheduler backend: {settings.scheduler_backend}")


def sqlite_store_exists(db_path: str | Path) -> bool:
    if str(db_path) == ":memory:":
        return True
    db_file = Path(db_path)
    return db_file.exists() and db_file.stat().st_size > 0
