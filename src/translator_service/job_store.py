from typing import Protocol

from translator_service.persistent_jobs import (
    JobUsageSummary,
    PersistentTranslationJob,
    PersistentWorkUnit,
    WorkUnitPlan,
)


class TranslationJobStore(Protocol):
    def close(self) -> None:
        ...

    def create_job(
        self,
        *,
        order_id: str,
        user_id: str,
        file_id: str,
        file_name: str,
        document_kind: str,
        source_language: str,
        target_language: str,
        adapter_version: str,
        prompt_version: str,
        pricing_snapshot_id: str,
        source_object_key: str | None = None,
    ) -> PersistentTranslationJob:
        ...

    def attach_job_output(
        self,
        job_id: str,
        *,
        partial_object_key: str | None = None,
        final_object_key: str | None = None,
    ) -> PersistentTranslationJob:
        ...

    def get_job(self, job_id: str) -> PersistentTranslationJob | None:
        ...

    def list_claimable_jobs(self) -> list[PersistentTranslationJob]:
        ...

    def add_work_units(
        self,
        job_id: str,
        work_units: list[WorkUnitPlan],
    ) -> list[PersistentWorkUnit]:
        ...

    def list_work_units(self, job_id: str) -> list[PersistentWorkUnit]:
        ...

    def claim_next_work_unit(
        self,
        job_id: str,
        *,
        worker_id: str,
    ) -> PersistentWorkUnit | None:
        ...

    def reclaim_stale_work_units(self, *, lease_seconds: int, worker_id: str) -> int:
        ...

    def complete_work_unit(
        self,
        work_unit_id: str,
        *,
        translated_text: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_hit_tokens: int,
        cache_miss_tokens: int,
        worker_id: str | None = None,
    ) -> PersistentWorkUnit:
        ...

    def fail_work_unit(
        self,
        work_unit_id: str,
        *,
        error_message: str,
        retry_count: int,
        worker_id: str | None = None,
    ) -> PersistentWorkUnit:
        ...

    def cancel_job(self, job_id: str) -> PersistentTranslationJob:
        ...

    def resume_job(self, job_id: str) -> PersistentTranslationJob:
        ...

    def get_usage_summary(self, job_id: str) -> JobUsageSummary:
        ...
