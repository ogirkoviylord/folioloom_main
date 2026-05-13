import logging
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from translator_service.beta_safety import BetaSafetyGuard
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
from translator_service.scheduler import (
    SchedulerClaim,
    SchedulerLimits,
    WorkUnitFailureKind,
)
from translator_service.translation_run_logs import (
    finish_running_translation_runs_for_job,
)
from translator_service.worker import (
    PersistentWorkUnitTranslator,
    _fail_claimed_work_unit_or_ignore_stale,
    _is_stale_work_unit_claim,
    _job_translation_context,
    load_scheduled_work_unit_text,
    run_next_scheduled_stored_text_work_unit,
    translate_claimed_scheduled_stored_text_work_unit,
)

SAFE_DEFERRED_WORKER_FAILURE_MESSAGE = "Translation failed in the background worker."

logger = logging.getLogger(__name__)


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
    max_parallel_units: int = 1,
    beta_safety_guard: BetaSafetyGuard | None = None,
    translation_run_log_root: str | Path | None = None,
) -> SchedulerRunOnceSummary:
    if beta_safety_guard is not None:
        decision = beta_safety_guard.can_start_new_work()
        if not decision.allowed:
            logger.warning(
                "Scheduler beta safety guard blocked new work: reason_code=%s",
                decision.reason_code,
            )
            assembled_jobs = assemble_due_jobs(
                store=store,
                storage=storage,
                beta_safety_guard=beta_safety_guard,
            )
            return SchedulerRunOnceSummary(
                completed_units=0,
                failed_units=0,
                assembled_jobs=assembled_jobs,
            )

    usage_completed_callback = _usage_completed_callback(
        store=store,
        beta_safety_guard=beta_safety_guard,
    )

    if max_parallel_units <= 1:
        completed_units = 0
        failed_units = 0
        hinted_slots = _translator_available_parallel_slots(translator)
        completed = None
        if hinted_slots is None or hinted_slots > 0:
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
                usage_completed_callback=usage_completed_callback,
            )
        if completed is not None:
            if completed.status.value in {"translated", "cached"}:
                completed_units = 1
            elif completed.status.value.startswith("failed"):
                failed_units = 1
                _finish_failed_translation_run_for_work_unit(
                    translation_run_log_root,
                    work_unit=completed,
                )
    else:
        completed_units, failed_units = _run_scheduled_parallel_once(
            store=store,
            storage=storage,
            worker_id=worker_id,
            translator=translator,
            limits=limits,
            lease_seconds=lease_seconds,
            retry_base_delay_seconds=retry_base_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
            work_unit_started_callback=work_unit_started_callback,
            max_parallel_units=max_parallel_units,
            usage_completed_callback=usage_completed_callback,
            translation_run_log_root=translation_run_log_root,
        )

    assembled_jobs = assemble_due_jobs(
        store=store,
        storage=storage,
        beta_safety_guard=beta_safety_guard,
    )
    return SchedulerRunOnceSummary(
        completed_units=completed_units,
        failed_units=failed_units,
        assembled_jobs=assembled_jobs,
    )


def _run_scheduled_parallel_once(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    worker_id: str,
    translator: PersistentWorkUnitTranslator,
    limits: SchedulerLimits,
    lease_seconds: int,
    retry_base_delay_seconds: int,
    retry_max_delay_seconds: int,
    work_unit_started_callback: Callable[[PersistentWorkUnit], None] | None,
    max_parallel_units: int,
    usage_completed_callback: Callable[[PersistentWorkUnit], None] | None,
    translation_run_log_root: str | Path | None,
) -> tuple[int, int]:
    completed_units = 0
    failed_units = 0
    active: dict[Future[object], SchedulerClaim] = {}
    capacity = max(1, max_parallel_units)
    worker_sequence = 0

    with ThreadPoolExecutor(max_workers=capacity) as executor:
        while True:
            hinted_slots = _translator_available_parallel_slots(translator)
            claim_capacity = (
                capacity
                if hinted_slots is None
                else min(capacity, len(active) + hinted_slots)
            )
            while len(active) < claim_capacity:
                worker_sequence += 1
                claim = store.claim_next_scheduled_work_unit(
                    worker_id=f"{worker_id}-{worker_sequence}",
                    lease_seconds=lease_seconds,
                    limits=limits,
                )
                if claim is None:
                    break
                work_unit = store.get_work_unit(claim.work_unit_id)
                if work_unit is None:
                    raise ValueError(
                        f"Claimed work unit does not exist: {claim.work_unit_id}"
                    )
                if work_unit_started_callback is not None:
                    work_unit_started_callback(work_unit)
                try:
                    source_text = load_scheduled_work_unit_text(
                        storage=storage,
                        work_unit=work_unit,
                    )
                except FileNotFoundError as error:
                    failed = _fail_claimed_work_unit_or_ignore_stale(
                        store=store,
                        claim=claim,
                        failure_kind=WorkUnitFailureKind.MISSING_SOURCE_OBJECT,
                        error_message=str(error),
                        retry_base_delay_seconds=retry_base_delay_seconds,
                        retry_max_delay_seconds=retry_max_delay_seconds,
                    )
                    failed_units += _failed_unit_count(failed)
                    _finish_failed_translation_run_for_work_unit(
                        translation_run_log_root,
                        work_unit=failed,
                    )
                    continue
                except ValueError as error:
                    failed = _fail_claimed_work_unit_or_ignore_stale(
                        store=store,
                        claim=claim,
                        failure_kind=WorkUnitFailureKind.UNSUPPORTED_CONTRACT,
                        error_message=str(error),
                        retry_base_delay_seconds=retry_base_delay_seconds,
                        retry_max_delay_seconds=retry_max_delay_seconds,
                    )
                    failed_units += _failed_unit_count(failed)
                    _finish_failed_translation_run_for_work_unit(
                        translation_run_log_root,
                        work_unit=failed,
                    )
                    continue

                future = executor.submit(
                    translate_claimed_scheduled_stored_text_work_unit,
                    work_unit=work_unit,
                    source_text=source_text,
                    translator=translator,
                    job_context=_job_translation_context(store, claim.job_id),
                )
                active[future] = claim

            if not active:
                break

            completed_futures, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in completed_futures:
                claim = active.pop(future)
                try:
                    translation_result = future.result()
                except Exception as error:
                    logger.exception(
                        "Scheduled parallel worker failed: job_id=%s work_unit_id=%s",
                        claim.job_id,
                        claim.work_unit_id,
                    )
                    failed = _fail_claimed_work_unit_or_ignore_stale(
                        store=store,
                        claim=claim,
                        failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
                        error_message=str(error),
                        retry_base_delay_seconds=retry_base_delay_seconds,
                        retry_max_delay_seconds=retry_max_delay_seconds,
                    )
                    failed_units += _failed_unit_count(failed)
                    _finish_failed_translation_run_for_work_unit(
                        translation_run_log_root,
                        work_unit=failed,
                    )
                    continue

                try:
                    completed = store.complete_claimed_work_unit(
                        work_unit_id=claim.work_unit_id,
                        claim_token=claim.claim_token,
                        translated_text=translation_result.translated_text,
                        prompt_tokens=translation_result.usage.prompt_tokens,
                        completion_tokens=translation_result.usage.completion_tokens,
                        cache_hit_tokens=(
                            translation_result.usage.prompt_cache_hit_tokens
                        ),
                        cache_miss_tokens=(
                            translation_result.usage.prompt_cache_miss_tokens
                        ),
                    )
                except ValueError as error:
                    if _is_stale_work_unit_claim(error):
                        logger.warning(
                            "Ignoring stale scheduled work-unit completion: "
                            "job_id=%s work_unit_id=%s",
                            claim.job_id,
                            claim.work_unit_id,
                        )
                        continue
                    raise
                if completed.status.value in {"translated", "cached"}:
                    completed_units += 1
                    if usage_completed_callback is not None:
                        usage_completed_callback(completed)
                elif completed.status.value.startswith("failed"):
                    failed_units += 1

    return completed_units, failed_units


def _usage_completed_callback(
    *,
    store: SQLiteTranslationJobStore,
    beta_safety_guard: BetaSafetyGuard | None,
) -> Callable[[PersistentWorkUnit], None] | None:
    if beta_safety_guard is None:
        return None

    def record_usage(work_unit: PersistentWorkUnit) -> None:
        job = store.get_job(work_unit.job_id)
        if job is None:
            raise ValueError(f"Work unit job does not exist: {work_unit.job_id}")
        beta_safety_guard.record_work_unit_usage(
            job_id=work_unit.job_id,
            user_id=job.user_id,
            work_unit_id=work_unit.id,
            prompt_tokens=work_unit.prompt_tokens,
            completion_tokens=work_unit.completion_tokens,
        )

    return record_usage


def _translator_available_parallel_slots(
    translator: PersistentWorkUnitTranslator,
) -> int | None:
    available = getattr(translator, "available_parallel_slots", None)
    if available is None:
        return None
    return max(0, int(available()))


def _failed_unit_count(work_unit: PersistentWorkUnit | None) -> int:
    if work_unit is None:
        return 0
    return 1 if work_unit.status.value.startswith("failed") else 0


def _finish_failed_translation_run_for_work_unit(
    root: str | Path | None,
    *,
    work_unit: PersistentWorkUnit | None,
) -> None:
    if root is None or work_unit is None:
        return
    if not work_unit.status.value.startswith("failed"):
        return
    finish_running_translation_runs_for_job(
        root,
        job_id=work_unit.job_id,
        status="failed",
        error_message=SAFE_DEFERRED_WORKER_FAILURE_MESSAGE,
    )


def assemble_due_jobs(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    beta_safety_guard: BetaSafetyGuard | None = None,
) -> int:
    assembled = 0
    for job in store.list_jobs_by_status(PersistentTranslationJobStatus.ASSEMBLING):
        if job.final_object_key is not None:
            store.mark_job_assembled(job.id, partial=False)
            _record_assembled_beta_safety_terminal(
                beta_safety_guard=beta_safety_guard,
                job_id=job.id,
                partial=False,
            )
            assembled += 1
            continue
        if job.partial_object_key is not None:
            store.mark_job_assembled(job.id, partial=True)
            _record_assembled_beta_safety_terminal(
                beta_safety_guard=beta_safety_guard,
                job_id=job.id,
                partial=True,
            )
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
        _record_assembled_beta_safety_terminal(
            beta_safety_guard=beta_safety_guard,
            job_id=job.id,
            partial=partial,
        )
        assembled += 1
    return assembled


def _record_assembled_beta_safety_terminal(
    *,
    beta_safety_guard: BetaSafetyGuard | None,
    job_id: str,
    partial: bool,
) -> None:
    if beta_safety_guard is None:
        return
    if partial:
        beta_safety_guard.release_job(
            job_id=job_id,
            reason="partial_assembly",
        )
        return
    beta_safety_guard.mark_job_consumed(job_id=job_id)


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
