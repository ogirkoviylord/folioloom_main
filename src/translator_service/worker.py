import json
import logging
import re
import time
from collections.abc import Callable, Container
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Protocol

from translator_service.file_storage import (
    LocalObjectStorage,
    StoredFile,
    StoredFileKind,
)
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    PersistentWorkUnit,
    PersistentWorkUnitStatus,
    SQLiteTranslationJobStore,
)
from translator_service.protected_text import (
    ProtectedText,
    protect_text,
    restore_protected_text,
)
from translator_service.russian_quality import detect_russian_quality_track
from translator_service.russian_quality_checks import check_russian_translation_quality
from translator_service.scheduler import (
    SchedulerClaim,
    SchedulerLimits,
    WorkUnitFailureKind,
)
from translator_service.translation_context import (
    TranslationContextMemory,
    translate_with_context,
    translation_context_from_payload,
    update_translation_context_memory,
)
from translator_service.translation_postprocess import clean_inline_formatting_artifacts
from translator_service.translation_runner import (
    _clean_translated_text,
    _format_translation_batch,
    _has_untranslated_cjk_text,
    _has_untranslated_rtl_text,
    _parse_translation_batch,
    _required_protected_markers,
    _restore_protected_texts,
    _source_language_hints,
    _target_language_uses_cjk,
)

logger = logging.getLogger(__name__)


def _is_stale_work_unit_claim(error: ValueError) -> bool:
    return str(error).startswith("Stale work-unit claim:")


class PersistentWorkUnitTranslator(Protocol):
    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        pass


@dataclass(frozen=True)
class ProviderUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0


@dataclass(frozen=True)
class _WorkUnitTranslationResult:
    translated_text: str
    usage: ProviderUsage


@dataclass(frozen=True)
class PersistentJobExecutionProgress:
    completed_work_unit: PersistentWorkUnit
    completed_units: int
    total_units: int
    elapsed_seconds: float = 0.0


@dataclass(frozen=True)
class PersistentJobExecutionSummary:
    job_id: str
    job_status: PersistentTranslationJobStatus
    translated_units: int
    total_units: int
    prompt_tokens: int
    completion_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int
    total_tokens: int
    failed_work_unit_id: str | None = None


def run_next_persistent_work_unit(
    *,
    store: SQLiteTranslationJobStore,
    job_id: str,
    worker_id: str,
    source_loader: Callable[[PersistentWorkUnit], str],
    translator: PersistentWorkUnitTranslator,
    work_unit_started_callback: Callable[[PersistentWorkUnit], None] | None = None,
    usage_completed_callback: Callable[[PersistentWorkUnit], None] | None = None,
) -> PersistentWorkUnit | None:
    work_unit = store.claim_next_work_unit(job_id, worker_id=worker_id)
    if work_unit is None:
        return None
    if work_unit_started_callback is not None:
        work_unit_started_callback(work_unit)

    try:
        job_context = _job_translation_context(store, job_id)
        source_text = source_loader(work_unit)
        translation_result = _translate_work_unit_text(
            work_unit=work_unit,
            source_text=source_text,
            translator=translator,
            job_context=job_context,
        )
    except Exception as error:
        logger.exception(
            "Persistent worker failed: job_id=%s work_unit_id=%s",
            job_id,
            work_unit.id,
        )
        try:
            return store.fail_work_unit(
                work_unit.id,
                error_message=str(error),
                retry_count=work_unit.retry_count + 1,
            )
        except ValueError as stale_error:
            if _is_stale_work_unit_claim(stale_error):
                logger.warning(
                    "Ignoring stale persistent work-unit failure: "
                    "job_id=%s work_unit_id=%s",
                    job_id,
                    work_unit.id,
                )
                return None
            raise

    try:
        completed = store.complete_work_unit(
            work_unit.id,
            translated_text=translation_result.translated_text,
            prompt_tokens=translation_result.usage.prompt_tokens,
            completion_tokens=translation_result.usage.completion_tokens,
            cache_hit_tokens=translation_result.usage.prompt_cache_hit_tokens,
            cache_miss_tokens=translation_result.usage.prompt_cache_miss_tokens,
        )
        if _is_successful_completed_work_unit(completed):
            if usage_completed_callback is not None:
                usage_completed_callback(completed)
        return completed
    except ValueError as error:
        if _is_stale_work_unit_claim(error):
            logger.warning(
                "Ignoring stale persistent work-unit completion: "
                "job_id=%s work_unit_id=%s",
                job_id,
                work_unit.id,
            )
            return None
        raise


def run_stored_text_job_until_idle(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    job_id: str,
    worker_id: str,
    translator: PersistentWorkUnitTranslator,
    progress_callback: Callable[[PersistentJobExecutionProgress], None] | None = None,
    work_unit_started_callback: Callable[[PersistentWorkUnit], None] | None = None,
    usage_completed_callback: Callable[[PersistentWorkUnit], None] | None = None,
    allowed_source_object_keys: Container[str] | None = None,
    require_upload_safety_policy: bool = False,
    encoding: str = "utf-8",
) -> PersistentJobExecutionSummary:
    total_units = len(store.list_work_units(job_id))
    failed_work_unit_id: str | None = None

    while True:
        completed = run_next_stored_text_work_unit(
            store=store,
            storage=storage,
            job_id=job_id,
            worker_id=worker_id,
            translator=translator,
            work_unit_started_callback=work_unit_started_callback,
            usage_completed_callback=usage_completed_callback,
            allowed_source_object_keys=allowed_source_object_keys,
            require_upload_safety_policy=require_upload_safety_policy,
            encoding=encoding,
        )
        if completed is None:
            break

        if completed.status is PersistentWorkUnitStatus.FAILED:
            failed_work_unit_id = completed.id
            break

        if progress_callback is not None:
            progress_callback(
                PersistentJobExecutionProgress(
                    completed_work_unit=completed,
                    completed_units=_completed_work_unit_count(store, job_id),
                    total_units=total_units,
                )
            )

    return _execution_summary(
        store=store,
        job_id=job_id,
        total_units=total_units,
        failed_work_unit_id=failed_work_unit_id,
    )


def run_stored_text_job_parallel_until_idle(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    job_id: str,
    worker_id: str,
    translator: PersistentWorkUnitTranslator,
    max_parallel_units: int,
    progress_callback: Callable[[PersistentJobExecutionProgress], None] | None = None,
    work_unit_started_callback: Callable[[PersistentWorkUnit], None] | None = None,
    usage_completed_callback: Callable[[PersistentWorkUnit], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    allowed_source_object_keys: Container[str] | None = None,
    require_upload_safety_policy: bool = False,
    encoding: str = "utf-8",
) -> PersistentJobExecutionSummary:
    if max_parallel_units <= 1:
        return run_stored_text_job_until_idle(
            store=store,
            storage=storage,
            job_id=job_id,
            worker_id=worker_id,
            translator=translator,
            progress_callback=progress_callback,
            work_unit_started_callback=work_unit_started_callback,
            usage_completed_callback=usage_completed_callback,
            allowed_source_object_keys=allowed_source_object_keys,
            require_upload_safety_policy=require_upload_safety_policy,
            encoding=encoding,
        )

    total_units = len(store.list_work_units(job_id))
    failed_work_unit_id: str | None = None
    active: dict[
        Future[_WorkUnitTranslationResult],
        tuple[PersistentWorkUnit, float],
    ] = {}
    worker_sequence = 0
    job_context = _job_translation_context(store, job_id)

    with ThreadPoolExecutor(max_workers=max_parallel_units) as executor:
        while True:
            while (
                len(active) < max_parallel_units
                and failed_work_unit_id is None
                and not _should_stop(should_stop)
            ):
                worker_sequence += 1
                claimed = store.claim_next_work_unit(
                    job_id,
                    worker_id=f"{worker_id}-{worker_sequence}",
                    max_active_units_per_job=max_parallel_units,
                )
                if claimed is None:
                    break
                if work_unit_started_callback is not None:
                    work_unit_started_callback(claimed)
                future = executor.submit(
                    _translate_stored_text_work_unit,
                    storage=storage,
                    work_unit=claimed,
                    translator=translator,
                    encoding=encoding,
                    job_context=job_context,
                    allowed_source_object_keys=allowed_source_object_keys,
                    require_upload_safety_policy=require_upload_safety_policy,
                    store=store,
                )
                active[future] = (claimed, time.monotonic())

            if not active:
                break

            completed_futures, _ = wait(
                active,
                timeout=0.1 if should_stop is not None else None,
                return_when=FIRST_COMPLETED,
            )
            if not completed_futures:
                continue

            for future in completed_futures:
                work_unit, started_at = active.pop(future)
                elapsed_seconds = time.monotonic() - started_at
                try:
                    translation_result = future.result()
                except Exception as error:
                    logger.exception(
                        "Persistent parallel worker failed: job_id=%s work_unit_id=%s",
                        job_id,
                        work_unit.id,
                    )
                    try:
                        failed = store.fail_work_unit(
                            work_unit.id,
                            error_message=str(error),
                            retry_count=work_unit.retry_count + 1,
                        )
                    except ValueError as stale_error:
                        if _is_stale_work_unit_claim(stale_error):
                            logger.warning(
                                "Ignoring stale persistent work-unit failure: "
                                "job_id=%s work_unit_id=%s",
                                job_id,
                                work_unit.id,
                            )
                            continue
                        raise
                    failed_work_unit_id = failed.id
                    continue

                try:
                    completed = store.complete_work_unit(
                        work_unit.id,
                        translated_text=translation_result.translated_text,
                        prompt_tokens=translation_result.usage.prompt_tokens,
                        completion_tokens=translation_result.usage.completion_tokens,
                        cache_hit_tokens=translation_result.usage.prompt_cache_hit_tokens,
                        cache_miss_tokens=translation_result.usage.prompt_cache_miss_tokens,
                    )
                except ValueError as error:
                    if _is_stale_work_unit_claim(error):
                        logger.warning(
                            "Ignoring stale persistent work-unit completion: "
                            "job_id=%s work_unit_id=%s",
                            job_id,
                            work_unit.id,
                        )
                        continue
                    raise
                if _is_successful_completed_work_unit(completed):
                    if usage_completed_callback is not None:
                        usage_completed_callback(completed)
                if progress_callback is not None:
                    progress_callback(
                        PersistentJobExecutionProgress(
                            completed_work_unit=completed,
                            completed_units=_completed_work_unit_count(store, job_id),
                            total_units=total_units,
                            elapsed_seconds=elapsed_seconds,
                        )
                    )

            if failed_work_unit_id is not None and not active:
                break

    return _execution_summary(
        store=store,
        job_id=job_id,
        total_units=total_units,
        failed_work_unit_id=failed_work_unit_id,
    )


def run_next_stored_text_work_unit(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    job_id: str,
    worker_id: str,
    translator: PersistentWorkUnitTranslator,
    work_unit_started_callback: Callable[[PersistentWorkUnit], None] | None = None,
    usage_completed_callback: Callable[[PersistentWorkUnit], None] | None = None,
    allowed_source_object_keys: Container[str] | None = None,
    require_upload_safety_policy: bool = False,
    encoding: str = "utf-8",
) -> PersistentWorkUnit | None:
    return run_next_persistent_work_unit(
        store=store,
        job_id=job_id,
        worker_id=worker_id,
        source_loader=lambda work_unit: _load_work_unit_text(
            storage=storage,
            work_unit=work_unit,
            allowed_source_object_keys=_allowed_source_object_keys_for_work_unit(
                store=store,
                work_unit=work_unit,
                allowed_source_object_keys=allowed_source_object_keys,
                require_upload_safety_policy=require_upload_safety_policy,
            ),
            encoding=encoding,
        ),
        translator=translator,
        work_unit_started_callback=work_unit_started_callback,
        usage_completed_callback=usage_completed_callback,
    )


def run_next_scheduled_stored_text_work_unit(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    worker_id: str,
    lease_seconds: int,
    limits: SchedulerLimits,
    translator: PersistentWorkUnitTranslator,
    retry_base_delay_seconds: int = 30,
    retry_max_delay_seconds: int = 600,
    work_unit_started_callback: Callable[[PersistentWorkUnit], None] | None = None,
    usage_completed_callback: Callable[[PersistentWorkUnit], None] | None = None,
    allowed_source_object_keys: Container[str] | None = None,
    require_upload_safety_policy: bool = False,
    encoding: str = "utf-8",
) -> PersistentWorkUnit | None:
    claim = store.claim_next_scheduled_work_unit(
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        limits=limits,
    )
    if claim is None:
        return None

    work_unit = store.get_work_unit(claim.work_unit_id)
    if work_unit is None:
        raise ValueError(f"Claimed work unit does not exist: {claim.work_unit_id}")
    if work_unit_started_callback is not None:
        work_unit_started_callback(work_unit)

    try:
        source_text = load_scheduled_work_unit_text(
            storage=storage,
            work_unit=work_unit,
            allowed_source_object_keys=_allowed_source_object_keys_for_work_unit(
                store=store,
                work_unit=work_unit,
                allowed_source_object_keys=allowed_source_object_keys,
                require_upload_safety_policy=require_upload_safety_policy,
            ),
            encoding=encoding,
        )
    except FileNotFoundError as error:
        return _fail_claimed_work_unit_or_ignore_stale(
            store=store,
            claim=claim,
            failure_kind=WorkUnitFailureKind.MISSING_SOURCE_OBJECT,
            error_message=str(error),
            retry_base_delay_seconds=retry_base_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
        )
    except ValueError as error:
        return _fail_claimed_work_unit_or_ignore_stale(
            store=store,
            claim=claim,
            failure_kind=WorkUnitFailureKind.UNSUPPORTED_CONTRACT,
            error_message=str(error),
            retry_base_delay_seconds=retry_base_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
        )

    try:
        job_context = _job_translation_context(store, claim.job_id)
        translation_result = translate_claimed_scheduled_stored_text_work_unit(
            work_unit=work_unit,
            source_text=source_text,
            translator=translator,
            job_context=job_context,
        )
    except Exception:
        logger.error(
            "Scheduled worker failed safely: job_id=%s work_unit_id=%s error=%s",
            claim.job_id,
            claim.work_unit_id,
            _safe_retryable_provider_error_message(),
        )
        return _fail_claimed_work_unit_or_ignore_stale(
            store=store,
            claim=claim,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message=_safe_retryable_provider_error_message(),
            retry_base_delay_seconds=retry_base_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
        )

    try:
        completed = store.complete_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            translated_text=translation_result.translated_text,
            prompt_tokens=translation_result.usage.prompt_tokens,
            completion_tokens=translation_result.usage.completion_tokens,
            cache_hit_tokens=translation_result.usage.prompt_cache_hit_tokens,
            cache_miss_tokens=translation_result.usage.prompt_cache_miss_tokens,
        )
        if _is_successful_completed_work_unit(completed):
            if usage_completed_callback is not None:
                usage_completed_callback(completed)
        return completed
    except ValueError as error:
        if _is_stale_work_unit_claim(error):
            logger.warning(
                "Ignoring stale scheduled work-unit completion: "
                "job_id=%s work_unit_id=%s",
                claim.job_id,
                claim.work_unit_id,
            )
            return None
        raise


def translate_claimed_scheduled_stored_text_work_unit(
    *,
    work_unit: PersistentWorkUnit,
    source_text: str,
    translator: PersistentWorkUnitTranslator,
    job_context: TranslationContextMemory | None = None,
) -> _WorkUnitTranslationResult:
    return _translate_work_unit_text(
        work_unit=work_unit,
        source_text=source_text,
        translator=translator,
        job_context=job_context,
    )


def load_scheduled_work_unit_text(
    *,
    storage: LocalObjectStorage,
    work_unit: PersistentWorkUnit,
    allowed_source_object_keys: Container[str] | None = None,
    encoding: str = "utf-8",
) -> str:
    return _load_work_unit_text(
        storage=storage,
        work_unit=work_unit,
        allowed_source_object_keys=allowed_source_object_keys,
        encoding=encoding,
    )


def _fail_claimed_work_unit_or_ignore_stale(
    *,
    store: SQLiteTranslationJobStore,
    claim: SchedulerClaim,
    failure_kind: WorkUnitFailureKind,
    error_message: str,
    retry_base_delay_seconds: int,
    retry_max_delay_seconds: int,
) -> PersistentWorkUnit | None:
    try:
        return store.fail_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            failure_kind=failure_kind,
            error_message=error_message,
            retry_base_delay_seconds=retry_base_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
        )
    except ValueError as error:
        if _is_stale_work_unit_claim(error):
            logger.warning(
                "Ignoring stale scheduled work-unit failure: "
                "job_id=%s work_unit_id=%s",
                claim.job_id,
                claim.work_unit_id,
            )
            return None
        raise


def _safe_retryable_provider_error_message() -> str:
    return "retryable provider failure"


def _is_successful_completed_work_unit(work_unit: PersistentWorkUnit) -> bool:
    return work_unit.status in {
        PersistentWorkUnitStatus.TRANSLATED,
        PersistentWorkUnitStatus.CACHED,
    }


def _translate_stored_text_work_unit(
    *,
    storage: LocalObjectStorage,
    work_unit: PersistentWorkUnit,
    translator: PersistentWorkUnitTranslator,
    encoding: str,
    job_context: TranslationContextMemory | None = None,
    allowed_source_object_keys: Container[str] | None = None,
    require_upload_safety_policy: bool = False,
    store: SQLiteTranslationJobStore | None = None,
) -> _WorkUnitTranslationResult:
    source_text = _load_work_unit_text(
        storage=storage,
        work_unit=work_unit,
        allowed_source_object_keys=_allowed_source_object_keys_for_work_unit(
            store=store,
            work_unit=work_unit,
            allowed_source_object_keys=allowed_source_object_keys,
            require_upload_safety_policy=require_upload_safety_policy,
        ),
        encoding=encoding,
    )
    return _translate_work_unit_text(
        work_unit=work_unit,
        source_text=source_text,
        translator=translator,
        job_context=job_context,
    )


def assemble_translated_text_result(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    job_id: str,
    file_name: str,
    partial: bool,
    content_type: str = "text/plain; charset=utf-8",
    encoding: str = "utf-8",
) -> StoredFile:
    translated_texts = [
        work_unit.translated_text
        for work_unit in store.list_work_units(job_id)
        if work_unit.translated_text
    ]
    if not translated_texts:
        raise ValueError(f"Job has no translated work units: {job_id}")

    stored = storage.put_bytes(
        kind=StoredFileKind.PARTIAL if partial else StoredFileKind.FINAL,
        file_name=file_name,
        content_type=content_type,
        content="\n\n".join(translated_texts).encode(encoding),
    )
    store.attach_job_output(
        job_id,
        partial_object_key=stored.object_key if partial else None,
        final_object_key=None if partial else stored.object_key,
    )
    return stored


def _translate_work_unit_text(
    *,
    work_unit: PersistentWorkUnit,
    source_text: str,
    translator: PersistentWorkUnitTranslator,
    job_context: TranslationContextMemory | None = None,
) -> _WorkUnitTranslationResult:
    source_blocks = _source_blocks_for_work_unit(work_unit, source_text)
    context_memory = job_context or TranslationContextMemory()
    if len(source_blocks) <= 1:
        protected_source = protect_text(source_text)
        translated_text = translate_with_context(
            translator,
            text=protected_source.text,
            source_language=work_unit.source_language,
            target_language=work_unit.target_language,
            translation_context=context_memory,
        )
        usage = _provider_usage(translator)
        translated_text = restore_protected_text(
            _clean_translated_text(translated_text),
            protected_source.replacements,
        )
        translated_text = clean_inline_formatting_artifacts(
            translated_text,
            target_language=work_unit.target_language,
        )
        if _needs_secondary_language_retry(
            source_text=source_text,
            translated_text=translated_text,
            protected_replacements=protected_source.replacements,
            source_language=work_unit.source_language,
            target_language=work_unit.target_language,
        ):
            logger.info(
                "Retrying persistent work unit after translation QA: "
                "work_unit_id=%s reason=secondary_language_left_untranslated",
                work_unit.id,
            )
            retried = translate_with_context(
                translator,
                text=protected_source.text,
                source_language="auto",
                target_language=work_unit.target_language,
                translation_context=context_memory,
            )
            usage = _add_provider_usage(usage, _provider_usage(translator))
            translated_text = restore_protected_text(
                _clean_translated_text(retried),
                protected_source.replacements,
            )
            translated_text = clean_inline_formatting_artifacts(
                translated_text,
                target_language=work_unit.target_language,
            )
        return _WorkUnitTranslationResult(
            translated_text=translated_text,
            usage=usage,
        )

    protected_blocks = [protect_text(text) for text in source_blocks]
    source_language_hints = _source_language_hints(
        source_blocks,
        source_language=work_unit.source_language,
    )
    translated_text = translate_with_context(
        translator,
        text=_format_translation_batch(
            [protected.text for protected in protected_blocks],
            source_language_hints=source_language_hints,
        ),
        source_language=work_unit.source_language,
        target_language=work_unit.target_language,
        translation_context=context_memory,
    )
    total_usage = _provider_usage(translator)
    parsed = _parse_translation_batch(
        translated_text,
        expected_count=len(source_blocks),
        required_markers=_required_protected_markers(protected_blocks),
    )
    if parsed is None:
        parsed, fallback_usage = _translate_source_blocks_individually(
            source_blocks=source_blocks,
            translator=translator,
            source_language=work_unit.source_language,
            target_language=work_unit.target_language,
            translation_context=context_memory,
        )
        total_usage = _add_provider_usage(total_usage, fallback_usage)
    else:
        parsed = _restore_protected_texts(parsed, protected_blocks)
        parsed = [
            clean_inline_formatting_artifacts(
                translated,
                target_language=work_unit.target_language,
            )
            for translated in parsed
        ]

    for source_block, translated_block in zip(source_blocks, parsed, strict=True):
        context_memory = _updated_context_memory(
            context_memory,
            source_text=source_block,
            translated_text=translated_block,
            target_language=work_unit.target_language,
        )

    parsed, retry_usage = _retry_untranslated_secondary_source_blocks(
        source_blocks=source_blocks,
        translated_blocks=parsed,
        protected_blocks=protected_blocks,
        translator=translator,
        source_language=work_unit.source_language,
        target_language=work_unit.target_language,
        translation_context=context_memory,
    )
    total_usage = _add_provider_usage(total_usage, retry_usage)
    return _WorkUnitTranslationResult(
        translated_text="\n\n".join(parsed),
        usage=total_usage,
    )


def _source_blocks_for_work_unit(
    work_unit: PersistentWorkUnit,
    source_text: str,
) -> list[str]:
    block_ids = work_unit.source_block_ids
    if len(block_ids) <= 1:
        return [source_text]

    parts = [part.strip() for part in source_text.split("\n\n")]
    if len(parts) != len(block_ids):
        logger.warning(
            "Stored work unit source block count mismatch; falling back to raw unit "
            "translation: work_unit_id=%s source_parts=%s source_blocks=%s",
            work_unit.id,
            len(parts),
            len(block_ids),
        )
        return [source_text]
    return parts


def _translate_source_blocks_individually(
    *,
    source_blocks: list[str],
    translator: PersistentWorkUnitTranslator,
    source_language: str,
    target_language: str,
    translation_context: TranslationContextMemory | None = None,
) -> tuple[list[str], ProviderUsage]:
    translated_blocks: list[str] = []
    total_usage = ProviderUsage()
    context_memory = translation_context or TranslationContextMemory()
    for source_block in source_blocks:
        protected_source = protect_text(source_block)
        translated = translate_with_context(
            translator,
            text=protected_source.text,
            source_language=source_language,
            target_language=target_language,
            translation_context=context_memory,
        )
        total_usage = _add_provider_usage(total_usage, _provider_usage(translator))
        translated_block = clean_inline_formatting_artifacts(
            restore_protected_text(
                _clean_translated_text(translated),
                protected_source.replacements,
            ),
            target_language=target_language,
        )
        translated_blocks.append(translated_block)
        context_memory = _updated_context_memory(
            context_memory,
            source_text=source_block,
            translated_text=translated_block,
            target_language=target_language,
        )
    return translated_blocks, total_usage


def _retry_untranslated_secondary_source_blocks(
    *,
    source_blocks: list[str],
    translated_blocks: list[str],
    protected_blocks: list[ProtectedText],
    translator: PersistentWorkUnitTranslator,
    source_language: str,
    target_language: str,
    translation_context: TranslationContextMemory | None = None,
) -> tuple[list[str], ProviderUsage]:
    retry_blocks = list(translated_blocks)
    total_usage = ProviderUsage()
    for index, (source, translated, protected) in enumerate(
        zip(source_blocks, retry_blocks, protected_blocks, strict=True)
    ):
        if not _needs_secondary_language_retry(
            source_text=source,
            translated_text=translated,
            protected_replacements=protected.replacements,
            source_language=source_language,
            target_language=target_language,
        ):
            continue

        logger.info(
            "Retrying persistent block after translation QA: "
            "block_index=%s reason=secondary_language_left_untranslated",
            index,
        )
        retried = translate_with_context(
            translator,
            text=protected.text,
            source_language="auto",
            target_language=target_language,
            translation_context=translation_context,
        )
        total_usage = _add_provider_usage(total_usage, _provider_usage(translator))
        retry_blocks[index] = restore_protected_text(
            _clean_translated_text(retried),
            protected.replacements,
        )
        retry_blocks[index] = clean_inline_formatting_artifacts(
            retry_blocks[index],
            target_language=target_language,
        )

    return retry_blocks, total_usage


def _updated_context_memory(
    memory: TranslationContextMemory,
    *,
    source_text: str,
    translated_text: str,
    target_language: str,
) -> TranslationContextMemory:
    decision = detect_russian_quality_track(
        source_text,
        target_language=target_language,
    )
    return update_translation_context_memory(
        memory,
        source_text=source_text,
        translated_text=translated_text,
        quality_track=decision.track,
    )


def _needs_secondary_language_retry(
    *,
    source_text: str,
    translated_text: str,
    protected_replacements: dict[str, str],
    source_language: str,
    target_language: str,
) -> bool:
    if _has_untranslated_source_language_residue(
        source_text=source_text,
        translated_text=translated_text,
        source_language=source_language,
        target_language=target_language,
    ):
        return True

    if (
        not _target_language_uses_cjk(target_language)
        and _has_untranslated_cjk_text(
            source_text=source_text,
            translated_text=translated_text,
            protected_replacements=protected_replacements,
        )
    ):
        return True

    if _has_untranslated_rtl_text(
        source_text=source_text,
        translated_text=translated_text,
        protected_replacements=protected_replacements,
    ):
        return True

    return _has_untranslated_dutch_text(
        source_text=source_text,
        translated_text=translated_text,
        target_language=target_language,
    ) or _has_untranslated_ukrainian_text(
        source_text=source_text,
        translated_text=translated_text,
        target_language=target_language,
    ) or _has_lost_mixed_language_label(
        source_text=source_text,
        translated_text=translated_text,
        target_language=target_language,
    )


def _has_untranslated_source_language_residue(
    *,
    source_text: str,
    translated_text: str,
    source_language: str,
    target_language: str,
) -> bool:
    quality_result = check_russian_translation_quality(
        source_text=source_text,
        translated_text=translated_text,
        source_language=source_language,
        target_language=target_language,
        quality_track=None,
    )
    return any(
        issue.code == "untranslated_source_residue"
        for issue in quality_result.issues
    )


_DUTCH_RETRY_TERMS = {
    "afspraak",
    "dinsdag",
    "woensdag",
    "donderdag",
    "vrijdag",
    "kwart",
}


def _has_untranslated_dutch_text(
    *,
    source_text: str,
    translated_text: str,
    target_language: str,
) -> bool:
    if target_language.strip().lower() == "nl":
        return False

    source_terms = _dutch_terms(source_text)
    if not source_terms:
        return False
    return bool(source_terms & _dutch_terms(translated_text))


def _dutch_terms(text: str) -> set[str]:
    words = set(re.findall(r"[A-Za-zÀ-ÿ]+", text.lower()))
    return words & _DUTCH_RETRY_TERMS


def _has_untranslated_ukrainian_text(
    *,
    source_text: str,
    translated_text: str,
    target_language: str,
) -> bool:
    if target_language.strip().lower() == "uk":
        return False
    return bool(re.search(r"[іїєґ]", source_text.lower())) and bool(
        re.search(r"[іїєґ]", translated_text.lower())
    )


_LANGUAGE_LABEL_CODES = {
    "english": "en",
    "английский": "en",
    "dutch": "nl",
    "nederlands": "nl",
    "нидерландский": "nl",
    "голландский": "nl",
    "ukrainian": "uk",
    "украинский": "uk",
    "українська": "uk",
    "chinese": "zh",
    "китайский": "zh",
    "中文": "zh",
    "polish": "pl",
    "polski": "pl",
    "польский": "pl",
    "hebrew": "he",
    "иврит": "he",
    "עברית": "he",
    "arabic": "ar",
    "арабский": "ar",
    "العربية": "ar",
}


_LOCALIZED_LABEL_HINTS = {
    "ru": {
        "en": ("англий",),
        "nl": ("нидерланд", "голланд"),
        "uk": ("украин", "україн"),
        "zh": ("китай",),
        "pl": ("польск",),
        "he": ("иврит", "еврейск"),
        "ar": ("арабск",),
    },
    "uk": {
        "en": ("англій",),
        "nl": ("нідерланд", "голланд"),
        "ru": ("росій",),
        "zh": ("китай",),
        "pl": ("польськ",),
        "he": ("іврит",),
        "ar": ("арабськ",),
    },
    "en": {
        "nl": ("dutch", "netherlands"),
        "uk": ("ukrainian",),
        "zh": ("chinese",),
        "pl": ("polish",),
        "he": ("hebrew",),
        "ar": ("arabic",),
    },
}


def _has_lost_mixed_language_label(
    *,
    source_text: str,
    translated_text: str,
    target_language: str,
) -> bool:
    source_codes = _leading_language_label_codes(source_text)
    if len(source_codes) < 2:
        return False

    target = target_language.strip().lower()
    expected_hints = _LOCALIZED_LABEL_HINTS.get(target)
    if expected_hints is None:
        return False

    translated_normalized = translated_text.lower()
    for source_code in source_codes:
        hints = expected_hints.get(source_code)
        if hints and not any(hint in translated_normalized for hint in hints):
            return True
    return False


def _leading_language_label_codes(text: str) -> set[str]:
    prefix = text.split(":", 1)[0].strip().lower()
    if not prefix or len(prefix) > 80:
        return set()

    labels = re.split(r"\s*(?:\+|/|,|&|and|и)\s*", prefix)
    codes = {
        code
        for label in labels
        if (code := _LANGUAGE_LABEL_CODES.get(label.strip())) is not None
    }
    return codes if len(codes) >= 2 else set()


def _add_provider_usage(left: ProviderUsage, right: ProviderUsage) -> ProviderUsage:
    return ProviderUsage(
        prompt_tokens=left.prompt_tokens + right.prompt_tokens,
        completion_tokens=left.completion_tokens + right.completion_tokens,
        total_tokens=left.total_tokens + right.total_tokens,
        prompt_cache_hit_tokens=(
            left.prompt_cache_hit_tokens + right.prompt_cache_hit_tokens
        ),
        prompt_cache_miss_tokens=(
            left.prompt_cache_miss_tokens + right.prompt_cache_miss_tokens
        ),
    )


def _execution_summary(
    *,
    store: SQLiteTranslationJobStore,
    job_id: str,
    total_units: int,
    failed_work_unit_id: str | None,
) -> PersistentJobExecutionSummary:
    job = store.get_job(job_id)
    if job is None:
        raise ValueError(f"Translation job does not exist: {job_id}")
    usage = store.get_usage_summary(job_id)
    return PersistentJobExecutionSummary(
        job_id=job_id,
        job_status=job.status,
        translated_units=usage.translated_units,
        total_units=total_units,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cache_hit_tokens=usage.cache_hit_tokens,
        cache_miss_tokens=usage.cache_miss_tokens,
        total_tokens=usage.total_tokens,
        failed_work_unit_id=failed_work_unit_id,
    )


def _completed_work_unit_count(
    store: SQLiteTranslationJobStore,
    job_id: str,
) -> int:
    return sum(
        1
        for work_unit in store.list_work_units(job_id)
        if work_unit.status
        in {PersistentWorkUnitStatus.TRANSLATED, PersistentWorkUnitStatus.CACHED}
    )


def _should_stop(callback: Callable[[], bool] | None) -> bool:
    return callback is not None and callback()


def _provider_usage(translator: PersistentWorkUnitTranslator) -> ProviderUsage:
    usage = getattr(translator, "last_usage", None)
    if usage is None:
        return ProviderUsage()

    return ProviderUsage(
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
        prompt_cache_hit_tokens=int(
            getattr(usage, "prompt_cache_hit_tokens", 0) or 0
        ),
        prompt_cache_miss_tokens=int(
            getattr(usage, "prompt_cache_miss_tokens", 0) or 0
        ),
    )


def _load_work_unit_text(
    *,
    storage: LocalObjectStorage,
    work_unit: PersistentWorkUnit,
    encoding: str,
    allowed_source_object_keys: Container[str] | None = None,
) -> str:
    if not work_unit.source_object_key:
        raise ValueError(f"Work unit has no source object key: {work_unit.id}")
    if work_unit.source_object_key.startswith(f"{StoredFileKind.QUARANTINE.value}/"):
        raise ValueError(f"Work unit source object is quarantined: {work_unit.id}")
    if (
        allowed_source_object_keys is not None
        and work_unit.source_object_key not in allowed_source_object_keys
    ):
        raise ValueError(f"Work unit source object is not accepted: {work_unit.id}")
    return storage.get_bytes(work_unit.source_object_key).decode(encoding)


def _allowed_source_object_keys_for_work_unit(
    *,
    store: SQLiteTranslationJobStore | None,
    work_unit: PersistentWorkUnit,
    allowed_source_object_keys: Container[str] | None,
    require_upload_safety_policy: bool,
) -> Container[str] | None:
    if allowed_source_object_keys is not None:
        return allowed_source_object_keys
    if not require_upload_safety_policy:
        return None
    if store is None:
        raise ValueError(
            f"Upload safety policy cannot be verified: {work_unit.id}"
        )

    job = store.get_job(work_unit.job_id)
    if job is None:
        raise ValueError(f"Work unit job does not exist: {work_unit.job_id}")
    if not _job_has_upload_safety_policy(job):
        raise ValueError(
            f"Job source object is not accepted by upload safety policy: {job.id}"
        )

    keys = frozenset(
        unit.source_object_key
        for unit in store.list_work_units(job.id)
        if unit.source_object_key
    )
    if work_unit.source_object_key not in keys:
        raise ValueError(f"Work unit source object is not accepted: {work_unit.id}")
    return keys


def _job_has_upload_safety_policy(job) -> bool:
    if not job.source_object_key:
        return False
    if job.source_object_key.startswith(f"{StoredFileKind.QUARANTINE.value}/"):
        return False
    if not job.translation_policy:
        return False
    try:
        payload = json.loads(job.translation_policy)
    except json.JSONDecodeError:
        return False

    upload_safety = payload.get("upload_safety")
    if not isinstance(upload_safety, dict):
        return False
    return (
        upload_safety.get("source_gate") == "upload_safety_ledger"
        and bool(upload_safety.get("upload_safety_id"))
        and upload_safety.get("accepted_source_object_key") == job.source_object_key
    )


def _job_translation_context(
    store: SQLiteTranslationJobStore,
    job_id: str,
) -> TranslationContextMemory | None:
    job = store.get_job(job_id)
    if job is None or not job.translation_policy:
        return None
    try:
        payload = json.loads(job.translation_policy)
    except json.JSONDecodeError:
        logger.warning("Ignoring unreadable translation policy: job_id=%s", job_id)
        return None
    return translation_context_from_payload(payload.get("translation_context_memory"))


def open_scheduler_store(settings):
    from translator_service.persistent_job_store import open_persistent_job_store

    return open_persistent_job_store(settings)


def effective_worker_parallel_units(settings) -> int:
    from translator_service.bot.runtime import _deepseek_parallel_capacity

    return max(
        1,
        min(
            settings.translation_max_parallel_units,
            _deepseek_parallel_capacity(settings),
        ),
    )


def scheduler_limits_from_settings(
    settings,
    *,
    effective_global_capacity: int,
) -> SchedulerLimits:
    return SchedulerLimits(
        max_active_units_per_job=max(
            1,
            int(settings.scheduler_max_active_units_per_job),
        ),
        max_active_jobs_per_user=max(
            1,
            int(settings.scheduler_max_active_jobs_per_user),
        ),
        max_active_units_per_user=max(
            1,
            int(settings.scheduler_max_active_units_per_user),
        ),
        max_active_units_global=max(
            1,
            min(
                int(settings.scheduler_max_active_units_global),
                int(effective_global_capacity),
            ),
        ),
        priority_aging_seconds=max(0, int(settings.scheduler_priority_aging_seconds)),
    )


def main() -> None:
    from translator_service.bot.runtime import (
        bot_runtime_config_from_settings,
        build_beta_safety_guard,
        build_deepseek_translator,
    )
    from translator_service.config import Settings
    from translator_service.file_storage import LocalObjectStorage
    from translator_service.scheduler_runner import run_scheduler_once

    settings = Settings()
    storage = LocalObjectStorage(settings.object_storage_root)
    translator = build_deepseek_translator(settings)
    worker_parallel_units = effective_worker_parallel_units(settings)
    limits = scheduler_limits_from_settings(
        settings,
        effective_global_capacity=worker_parallel_units,
    )
    store = open_scheduler_store(settings)
    beta_safety_guard = None
    try:
        beta_safety_guard = build_beta_safety_guard(
            bot_runtime_config_from_settings(settings)
        )
        while True:
            run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker:local",
                translator=translator,
                limits=limits,
                lease_seconds=settings.scheduler_lease_seconds,
                max_parallel_units=worker_parallel_units,
                retry_base_delay_seconds=(
                    settings.scheduler_retry_base_delay_seconds
                ),
                retry_max_delay_seconds=settings.scheduler_retry_max_delay_seconds,
                beta_safety_guard=beta_safety_guard,
                translation_run_log_root=settings.translation_run_log_root,
                require_upload_safety_policy=getattr(
                    settings,
                    "require_upload_scan",
                    False,
                ),
            )
            time.sleep(settings.scheduler_poll_seconds)
    finally:
        if beta_safety_guard is not None:
            beta_safety_guard.close()
        store.close()


if __name__ == "__main__":
    main()
