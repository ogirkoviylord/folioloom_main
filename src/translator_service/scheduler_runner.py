import json
import logging
from collections.abc import Callable, Container
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from translator_service.beta_safety import BetaSafetyGuard
from translator_service.book_mode_output_audit import audit_book_mode_output
from translator_service.file_storage import LocalObjectStorage
from translator_service.format_adapters.epub import extract_epub_book_mode_audit_chunks
from translator_service.job_runner import DocumentKind
from translator_service.persistent_assembly import (
    assemble_persistent_docx_result,
    assemble_persistent_epub_content,
    assemble_persistent_epub_result,
    assemble_persistent_txt_result,
    count_unassembled_work_units,
    store_persistent_epub_result,
)
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    PersistentWorkUnit,
    PersistentWorkUnitStatus,
    SQLiteTranslationJobStore,
)
from translator_service.scheduler import (
    ProviderSlotLease,
    SchedulerClaim,
    SchedulerLimits,
    WorkUnitFailureKind,
)
from translator_service.translation_run_logs import (
    finish_running_translation_runs_for_job,
    record_book_mode_audit_fragment_for_job,
    record_book_mode_audit_gate_for_job,
)
from translator_service.translation_runner import GlossaryRuntimeAdapterHookConfig
from translator_service.worker import (
    PersistentWorkUnitTranslator,
    _acquire_provider_slot_lease_for_claim,
    _allowed_source_object_keys_for_work_unit,
    _defer_claimed_work_unit_for_provider_capacity,
    _fail_claimed_work_unit_or_ignore_stale,
    _is_stale_work_unit_claim,
    _job_translation_context,
    _provider_failure_diagnostic_for_error,
    _provider_io_diagnostic_sink,
    _provider_slot_failure_release_reason,
    _provider_slot_stale_release_reason,
    _release_provider_slot_lease,
    _safe_provider_failure_error_message,
    _scheduled_glossary_adapter_metadata_callback,
    _scheduled_glossary_runtime_hook,
    load_scheduled_work_unit_text,
    recover_expired_scheduled_work_unit_leases,
    refresh_scheduled_provider_slot_inventory,
    run_next_scheduled_stored_text_work_unit,
    translate_claimed_scheduled_stored_text_work_unit,
)

SAFE_DEFERRED_WORKER_FAILURE_MESSAGE = "Translation failed in the background worker."
SAFE_FINAL_EPUB_AUDIT_FAILURE_MESSAGE = "Final EPUB surface audit failed safely."
_BOOK_MODE_TRANSLATION_MODE = "book_manuscript"
_BOOK_MODE_PROFILE = "book-manuscript-v1"
_CYRILLIC_TARGETS = {"ru", "uk"}
_FINAL_EPUB_NAVIGATION_RESIDUE_THRESHOLD = 2

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
    allowed_source_object_keys: Container[str] | None = None,
    require_upload_safety_policy: bool = False,
    glossary_runtime_hook: GlossaryRuntimeAdapterHookConfig | None = None,
    glossary_runtime_hook_resolver: Callable[
        [PersistentWorkUnit],
        GlossaryRuntimeAdapterHookConfig | None,
    ]
    | None = None,
    glossary_adapter_metadata_callback: Callable[[dict[str, object]], None]
    | None = None,
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
                translation_run_log_root=translation_run_log_root,
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
                translation_run_log_root=translation_run_log_root,
                allowed_source_object_keys=allowed_source_object_keys,
                require_upload_safety_policy=require_upload_safety_policy,
                glossary_runtime_hook=glossary_runtime_hook,
                glossary_runtime_hook_resolver=glossary_runtime_hook_resolver,
                glossary_adapter_metadata_callback=glossary_adapter_metadata_callback,
            )
        if completed is not None:
            if completed.status.value in {"translated", "cached"}:
                completed_units = 1
                _record_book_mode_audit_for_work_unit(
                    translation_run_log_root,
                    completed,
                )
            elif completed.status.value.startswith("failed"):
                failed_units = 1
                _finish_failed_translation_run_for_work_unit(
                    translation_run_log_root,
                    work_unit=completed,
                    beta_safety_guard=beta_safety_guard,
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
            allowed_source_object_keys=allowed_source_object_keys,
            require_upload_safety_policy=require_upload_safety_policy,
            beta_safety_guard=beta_safety_guard,
            glossary_runtime_hook=glossary_runtime_hook,
            glossary_runtime_hook_resolver=glossary_runtime_hook_resolver,
            glossary_adapter_metadata_callback=glossary_adapter_metadata_callback,
        )

    assembled_jobs = assemble_due_jobs(
        store=store,
        storage=storage,
        beta_safety_guard=beta_safety_guard,
        translation_run_log_root=translation_run_log_root,
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
    allowed_source_object_keys: Container[str] | None,
    require_upload_safety_policy: bool,
    beta_safety_guard: BetaSafetyGuard | None,
    glossary_runtime_hook: GlossaryRuntimeAdapterHookConfig | None,
    glossary_runtime_hook_resolver: Callable[
        [PersistentWorkUnit],
        GlossaryRuntimeAdapterHookConfig | None,
    ]
    | None,
    glossary_adapter_metadata_callback: Callable[[dict[str, object]], None] | None,
) -> tuple[int, int]:
    refresh_scheduled_provider_slot_inventory(store=store, translator=translator)
    recover_expired_scheduled_work_unit_leases(
        store=store,
        retry_base_delay_seconds=retry_base_delay_seconds,
        retry_max_delay_seconds=retry_max_delay_seconds,
    )

    completed_units = 0
    failed_units = 0
    active: dict[Future[object], tuple[SchedulerClaim, ProviderSlotLease | None]] = {}
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
                try:
                    source_text = load_scheduled_work_unit_text(
                        storage=storage,
                        work_unit=work_unit,
                        allowed_source_object_keys=(
                            _allowed_source_object_keys_for_work_unit(
                                store=store,
                                work_unit=work_unit,
                                allowed_source_object_keys=allowed_source_object_keys,
                                require_upload_safety_policy=(
                                    require_upload_safety_policy
                                ),
                            )
                        ),
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
                        beta_safety_guard=beta_safety_guard,
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
                        beta_safety_guard=beta_safety_guard,
                    )
                    continue

                lease_attempt = _acquire_provider_slot_lease_for_claim(
                    store=store,
                    translator=translator,
                    claim=claim,
                    lease_seconds=lease_seconds,
                )
                if lease_attempt.required and lease_attempt.lease is None:
                    _defer_claimed_work_unit_for_provider_capacity(
                        store=store,
                        claim=claim,
                    )
                    break

                if work_unit_started_callback is not None:
                    work_unit_started_callback(work_unit)

                resolved_glossary_runtime_hook = _scheduled_glossary_runtime_hook(
                    store=store,
                    work_unit=work_unit,
                    source_text=source_text,
                    glossary_runtime_hook=glossary_runtime_hook,
                    glossary_runtime_hook_resolver=glossary_runtime_hook_resolver,
                )
                resolved_glossary_adapter_metadata_callback = (
                    _scheduled_glossary_adapter_metadata_callback(
                        translation_run_log_root=translation_run_log_root,
                        work_unit=work_unit,
                        glossary_runtime_hook=resolved_glossary_runtime_hook,
                        glossary_adapter_metadata_callback=(
                            glossary_adapter_metadata_callback
                        ),
                    )
                )
                future = executor.submit(
                    translate_claimed_scheduled_stored_text_work_unit,
                    work_unit=work_unit,
                    source_text=source_text,
                    translator=translator,
                    job_context=_job_translation_context(store, claim.job_id),
                    provider_slot_lease=lease_attempt.lease,
                    provider_io_diagnostic_sink=_provider_io_diagnostic_sink(
                        translation_run_log_root,
                        job_id=claim.job_id,
                    ),
                    glossary_runtime_hook=resolved_glossary_runtime_hook,
                    glossary_adapter_metadata_callback=(
                        resolved_glossary_adapter_metadata_callback
                    ),
                )
                active[future] = (claim, lease_attempt.lease)

            if not active:
                break

            completed_futures, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in completed_futures:
                claim, provider_slot_lease = active.pop(future)
                release_reason = "released"
                try:
                    try:
                        translation_result = future.result()
                    except Exception as error:
                        release_reason = "retryable_failure"
                        provider_failure_diagnostic = (
                            _provider_failure_diagnostic_for_error(
                                error,
                                translator=translator,
                            )
                        )
                        logger.error(
                            "Scheduled parallel worker failed safely: "
                            "job_id=%s work_unit_id=%s error=%s",
                            claim.job_id,
                            claim.work_unit_id,
                            _safe_provider_failure_error_message(
                                provider_failure_diagnostic
                            ),
                        )
                        failed = _fail_claimed_work_unit_or_ignore_stale(
                            store=store,
                            claim=claim,
                            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
                            error_message=_safe_provider_failure_error_message(
                                provider_failure_diagnostic
                            ),
                            retry_base_delay_seconds=retry_base_delay_seconds,
                            retry_max_delay_seconds=retry_max_delay_seconds,
                            provider_failure_diagnostic=provider_failure_diagnostic,
                        )
                        release_reason = _provider_slot_failure_release_reason(failed)
                        failed_units += _failed_unit_count(failed)
                        _finish_failed_translation_run_for_work_unit(
                            translation_run_log_root,
                            work_unit=failed,
                            beta_safety_guard=beta_safety_guard,
                        )
                        continue

                    try:
                        completed = store.complete_claimed_work_unit(
                            work_unit_id=claim.work_unit_id,
                            claim_token=claim.claim_token,
                            translated_text=translation_result.translated_text,
                            prompt_tokens=translation_result.usage.prompt_tokens,
                            completion_tokens=(
                                translation_result.usage.completion_tokens
                            ),
                            cache_hit_tokens=(
                                translation_result.usage.prompt_cache_hit_tokens
                            ),
                            cache_miss_tokens=(
                                translation_result.usage.prompt_cache_miss_tokens
                            ),
                        )
                        release_reason = "completed"
                    except ValueError as error:
                        if _is_stale_work_unit_claim(error):
                            logger.warning(
                                "Ignoring stale scheduled work-unit completion: "
                                "job_id=%s work_unit_id=%s",
                                claim.job_id,
                                claim.work_unit_id,
                            )
                            release_reason = _provider_slot_stale_release_reason(
                                store=store,
                                claim=claim,
                            )
                            continue
                        raise
                    if completed.status.value in {"translated", "cached"}:
                        completed_units += 1
                        _record_book_mode_audit_for_work_unit(
                            translation_run_log_root,
                            completed,
                        )
                        if usage_completed_callback is not None:
                            usage_completed_callback(completed)
                    elif completed.status.value.startswith("failed"):
                        failed_units += 1
                finally:
                    _release_provider_slot_lease(
                        store=store,
                        claim=claim,
                        provider_slot_lease=provider_slot_lease,
                        release_reason=release_reason,
                    )

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


def _record_book_mode_audit_for_work_unit(
    translation_run_log_root: str | Path | None,
    work_unit: PersistentWorkUnit,
) -> None:
    translated_text = work_unit.translated_text or ""
    if not translated_text:
        return
    record_book_mode_audit_fragment_for_job(
        translation_run_log_root,
        job_id=work_unit.job_id,
        sequence=work_unit.sequence,
        translated_text=translated_text,
        source_block_ids=work_unit.source_block_ids,
    )


def _finish_failed_translation_run_for_work_unit(
    root: str | Path | None,
    *,
    work_unit: PersistentWorkUnit | None,
    beta_safety_guard: BetaSafetyGuard | None,
) -> None:
    if work_unit is None:
        return
    if work_unit.status not in {
        PersistentWorkUnitStatus.FAILED,
        PersistentWorkUnitStatus.FAILED_TERMINAL,
    }:
        return
    if root is not None:
        finish_running_translation_runs_for_job(
            root,
            job_id=work_unit.job_id,
            status="failed",
            error_message=SAFE_DEFERRED_WORKER_FAILURE_MESSAGE,
        )
    if beta_safety_guard is not None:
        beta_safety_guard.release_job(
            job_id=work_unit.job_id,
            reason="terminal_failure",
        )


def assemble_due_jobs(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    beta_safety_guard: BetaSafetyGuard | None = None,
    translation_run_log_root: str | Path | None = None,
) -> int:
    assembled = 0
    for job in _jobs_due_for_assembly(store):
        work_units = store.list_work_units(job.id)
        if (
            job.status == PersistentTranslationJobStatus.INTERRUPTED
            and job.final_object_key is None
            and job.partial_object_key is None
            and not _has_available_translated_work_units(work_units)
        ):
            continue
        if job.final_object_key is not None and storage.exists(job.final_object_key):
            store.mark_job_assembled(job.id, partial=False)
            _finish_assembled_translation_run(
                translation_run_log_root,
                job_id=job.id,
                status="ready",
                result_file_name=_stored_file_name(storage, job.final_object_key),
            )
            _record_assembled_beta_safety_terminal(
                beta_safety_guard=beta_safety_guard,
                job_id=job.id,
                partial=False,
            )
            assembled += 1
            continue
        if job.partial_object_key is not None and storage.exists(job.partial_object_key):
            store.mark_job_assembled(job.id, partial=True)
            _finish_assembled_translation_run(
                translation_run_log_root,
                job_id=job.id,
                status="partial",
                result_file_name=_stored_file_name(storage, job.partial_object_key),
            )
            _record_assembled_beta_safety_terminal(
                beta_safety_guard=beta_safety_guard,
                job_id=job.id,
                partial=True,
            )
            assembled += 1
            continue
        if (
            (job.final_object_key is not None or job.partial_object_key is not None)
            and not _has_available_translated_work_units(work_units)
        ):
            continue
        partial = _should_assemble_partial_result(work_units)
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
            if partial:
                assemble_persistent_epub_result(
                    store=store,
                    storage=storage,
                    job_id=job.id,
                    file_name=result_name,
                    partial=partial,
                )
            else:
                content = assemble_persistent_epub_content(
                    store=store,
                    storage=storage,
                    job_id=job.id,
                    partial=False,
                )
                gate = _final_epub_book_mode_surface_gate(
                    job=job,
                    content=content,
                )
                if gate is not None:
                    record_book_mode_audit_gate_for_job(
                        translation_run_log_root,
                        job_id=job.id,
                        gate=gate,
                    )
                    store.mark_job_failed(job.id)
                    _finish_assembled_translation_run(
                        translation_run_log_root,
                        job_id=job.id,
                        status="failed",
                        result_file_name=None,
                        error_message=SAFE_FINAL_EPUB_AUDIT_FAILURE_MESSAGE,
                    )
                    _record_failed_beta_safety_terminal(
                        beta_safety_guard=beta_safety_guard,
                        job_id=job.id,
                    )
                    assembled += 1
                    continue
                store_persistent_epub_result(
                    store=store,
                    storage=storage,
                    job_id=job.id,
                    file_name=result_name,
                    partial=False,
                    content=content,
                )
        else:
            raise ValueError(
                f"Unsupported document kind for assembly: {job.document_kind}"
            )
        store.mark_job_assembled(job.id, partial=partial)
        _finish_assembled_translation_run(
            translation_run_log_root,
            job_id=job.id,
            status="partial" if partial else "ready",
            result_file_name=result_name,
        )
        _record_assembled_beta_safety_terminal(
            beta_safety_guard=beta_safety_guard,
            job_id=job.id,
            partial=partial,
        )
        assembled += 1
    return assembled


def _jobs_due_for_assembly(store: SQLiteTranslationJobStore):
    yield from store.list_jobs_by_status(PersistentTranslationJobStatus.ASSEMBLING)
    yield from store.list_jobs_by_status(PersistentTranslationJobStatus.INTERRUPTED)


def _has_available_translated_work_units(
    work_units: list[PersistentWorkUnit],
) -> bool:
    return any(_work_unit_can_be_assembled(work_unit) for work_unit in work_units)


def _should_assemble_partial_result(work_units: list[PersistentWorkUnit]) -> bool:
    return any(
        not _work_unit_can_be_assembled(work_unit) for work_unit in work_units
    ) or count_unassembled_work_units(work_units) > 0


def _work_unit_can_be_assembled(work_unit: PersistentWorkUnit) -> bool:
    return (
        work_unit.status
        in {
            PersistentWorkUnitStatus.TRANSLATED,
            PersistentWorkUnitStatus.CACHED,
        }
        and bool(work_unit.translated_text)
    )


def _finish_assembled_translation_run(
    root: str | Path | None,
    *,
    job_id: str,
    status: str,
    result_file_name: str | None,
    error_message: str | None = None,
) -> None:
    if root is None:
        return
    current_statuses = ("running", "failed") if status == "partial" else ("running",)
    finish_running_translation_runs_for_job(
        root,
        job_id=job_id,
        status=status,
        result_file_name=result_file_name,
        error_message=error_message,
        current_statuses=current_statuses,
        preserve_existing_error_message=status == "partial",
    )


def _stored_file_name(storage: LocalObjectStorage, object_key: str) -> str | None:
    try:
        return storage.get_metadata(object_key).file_name
    except (FileNotFoundError, ValueError):
        return None


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


def _record_failed_beta_safety_terminal(
    *,
    beta_safety_guard: BetaSafetyGuard | None,
    job_id: str,
) -> None:
    if beta_safety_guard is None:
        return
    beta_safety_guard.release_job(
        job_id=job_id,
        reason="final_epub_surface_audit_failed",
    )


def _final_epub_book_mode_surface_gate(
    *,
    job,
    content: bytes,
) -> dict[str, object] | None:
    if not _is_cyrillic_target(job.target_language):
        return None
    if not _is_book_mode_translation_policy(job.translation_policy):
        return None

    result = audit_book_mode_output(
        chunks=extract_epub_book_mode_audit_chunks(content),
        target_language=job.target_language,
    )
    blocking_findings = [
        finding
        for finding in result.findings
        if finding.code == "english_navigation_heading_residue"
        and finding.category == "navigation_heading"
    ]
    if len(blocking_findings) < _FINAL_EPUB_NAVIGATION_RESIDUE_THRESHOLD:
        return None

    return {
        "schema_version": "book-mode-final-surface-gate-v1",
        "phase": "final_epub_surface_audit",
        "status": "failed",
        "reason": "english_navigation_heading_residue",
        "blocking_findings": len(blocking_findings),
        "total_findings": len(result.findings),
        "counts_by_code": _audit_counts_by(result.findings, "code"),
        "counts_by_category": _audit_counts_by(result.findings, "category"),
        "counts_by_severity": _audit_counts_by(result.findings, "severity"),
        "surface_categories": _surface_categories(blocking_findings),
    }


def _audit_counts_by(findings, field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        value = str(getattr(finding, field_name, "") or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _surface_categories(findings) -> list[str]:
    return sorted(
        {
            _surface_category_from_chunk_id(finding.chunk_id)
            for finding in findings
        }
    )


def _surface_category_from_chunk_id(chunk_id: str) -> str:
    lowered = chunk_id.lower()
    if ":surface-opf:" in lowered:
        return "opf_metadata"
    if ":surface-ncx:" in lowered:
        return "toc_ncx"
    if ":surface-xhtml-title:" in lowered:
        return "xhtml_title"
    if ":surface-xhtml-navigation:" in lowered:
        return "xhtml_navigation"
    if lowered.startswith("epub:"):
        return "xhtml_body_heading"
    return "unknown"


def _is_book_mode_translation_policy(policy: str | None) -> bool:
    if not policy:
        return False
    try:
        payload = json.loads(policy)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    return (
        payload.get("translation_mode") == _BOOK_MODE_TRANSLATION_MODE
        or payload.get("translation_mode_profile") == _BOOK_MODE_PROFILE
    )


def _is_cyrillic_target(target_language: str) -> bool:
    root = target_language.strip().lower().replace("_", "-").split("-", 1)[0]
    return root in _CYRILLIC_TARGETS


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
