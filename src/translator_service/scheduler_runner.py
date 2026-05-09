from collections.abc import Callable
from dataclasses import dataclass

from translator_service.file_storage import LocalObjectStorage
from translator_service.job_runner import DocumentKind
from translator_service.persistent_assembly import (
    assemble_persistent_docx_result,
    assemble_persistent_epub_result,
    assemble_persistent_txt_result,
    count_unassembled_work_units,
)
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    PersistentWorkUnit,
    SQLiteTranslationJobStore,
)
from translator_service.scheduler import SchedulerLimits
from translator_service.worker import (
    PersistentWorkUnitTranslator,
    run_next_scheduled_stored_text_work_unit,
)


@dataclass(frozen=True)
class SchedulerRunOnceSummary:
    completed_units: int
    failed_units: int
    assembled_jobs: int


def run_scheduler_once(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    worker_id: str,
    translator: PersistentWorkUnitTranslator,
    limits: SchedulerLimits,
    lease_seconds: int,
    retry_base_delay_seconds: int = 30,
    retry_max_delay_seconds: int = 600,
    work_unit_started_callback: Callable[[PersistentWorkUnit], None] | None = None,
) -> SchedulerRunOnceSummary:
    completed_units = 0
    failed_units = 0
    completed = run_next_scheduled_stored_text_work_unit(
        store=store,
        storage=storage,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        limits=limits,
        translator=translator,
        retry_base_delay_seconds=retry_base_delay_seconds,
        retry_max_delay_seconds=retry_max_delay_seconds,
        work_unit_started_callback=work_unit_started_callback,
    )
    if completed is not None:
        if completed.status.value in {"translated", "cached"}:
            completed_units = 1
        elif completed.status.value.startswith("failed"):
            failed_units = 1

    assembled_jobs = assemble_due_jobs(store=store, storage=storage)
    return SchedulerRunOnceSummary(
        completed_units=completed_units,
        failed_units=failed_units,
        assembled_jobs=assembled_jobs,
    )


def assemble_due_jobs(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
) -> int:
    assembled = 0
    for job in store.list_jobs_by_status(PersistentTranslationJobStatus.ASSEMBLING):
        if job.final_object_key is not None:
            store.mark_job_assembled(job.id, partial=False)
            assembled += 1
            continue
        if job.partial_object_key is not None:
            store.mark_job_assembled(job.id, partial=True)
            assembled += 1
            continue
        partial = count_unassembled_work_units(store.list_work_units(job.id)) > 0
        result_name = _translated_file_name(
            job.file_name,
            job.target_language,
            job.document_kind,
            partial=partial,
        )
        if job.document_kind == DocumentKind.TXT.value:
            assemble_persistent_txt_result(
                store=store,
                storage=storage,
                job_id=job.id,
                file_name=result_name,
                partial=partial,
            )
        elif job.document_kind == DocumentKind.DOCX.value:
            assemble_persistent_docx_result(
                store=store,
                storage=storage,
                job_id=job.id,
                file_name=result_name,
                partial=partial,
            )
        elif job.document_kind == DocumentKind.EPUB.value:
            assemble_persistent_epub_result(
                store=store,
                storage=storage,
                job_id=job.id,
                file_name=result_name,
                partial=partial,
            )
        else:
            raise ValueError(
                f"Unsupported document kind for assembly: {job.document_kind}"
            )
        store.mark_job_assembled(job.id, partial=partial)
        assembled += 1
    return assembled


def _translated_file_name(
    file_name: str,
    target_language: str,
    document_kind: str,
    *,
    partial: bool,
) -> str:
    suffix = f".{target_language}"
    if partial:
        suffix += ".partial"
    if file_name.lower().endswith(f".{document_kind}"):
        return f"{file_name[: -(len(document_kind) + 1)]}{suffix}.{document_kind}"
    return f"{file_name}{suffix}.{document_kind}"
