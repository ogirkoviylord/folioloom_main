from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Protocol

from translator_service.file_storage import (
    LocalObjectStorage,
    StoredFile,
    StoredFileKind,
)
from translator_service.persistent_jobs import (
    PersistentWorkUnit,
    SQLiteTranslationJobStore,
)


logger = logging.getLogger(__name__)


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


def run_next_persistent_work_unit(
    *,
    store: SQLiteTranslationJobStore,
    job_id: str,
    worker_id: str,
    source_loader: Callable[[PersistentWorkUnit], str],
    translator: PersistentWorkUnitTranslator,
) -> PersistentWorkUnit | None:
    work_unit = store.claim_next_work_unit(job_id, worker_id=worker_id)
    if work_unit is None:
        return None

    try:
        source_text = source_loader(work_unit)
        translated_text = translator.translate(
            text=source_text,
            source_language=work_unit.source_language,
            target_language=work_unit.target_language,
        )
    except Exception as error:
        logger.exception(
            "Persistent worker failed: job_id=%s work_unit_id=%s",
            job_id,
            work_unit.id,
        )
        return store.fail_work_unit(
            work_unit.id,
            error_message=str(error),
            retry_count=work_unit.retry_count + 1,
        )

    usage = _provider_usage(translator)
    return store.complete_work_unit(
        work_unit.id,
        translated_text=translated_text,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cache_hit_tokens=usage.prompt_cache_hit_tokens,
        cache_miss_tokens=usage.prompt_cache_miss_tokens,
    )


def run_next_stored_text_work_unit(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    job_id: str,
    worker_id: str,
    translator: PersistentWorkUnitTranslator,
    encoding: str = "utf-8",
) -> PersistentWorkUnit | None:
    return run_next_persistent_work_unit(
        store=store,
        job_id=job_id,
        worker_id=worker_id,
        source_loader=lambda work_unit: _load_work_unit_text(
            storage=storage,
            work_unit=work_unit,
            encoding=encoding,
        ),
        translator=translator,
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
) -> str:
    if not work_unit.source_object_key:
        raise ValueError(f"Work unit has no source object key: {work_unit.id}")
    return storage.get_bytes(work_unit.source_object_key).decode(encoding)


def main() -> None:
    print("Worker placeholder is ready.")


if __name__ == "__main__":
    main()
