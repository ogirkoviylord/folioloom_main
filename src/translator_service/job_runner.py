from dataclasses import dataclass, replace
from enum import StrEnum

from translator_service.translation_jobs import TextTranslator
from translator_service.translation_runner import TranslatedDocument, translate_txt_document


class TranslationJobStatus(StrEnum):
    QUEUED = "queued"
    TRANSLATING = "translating"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True)
class TranslationJob:
    id: str
    user_telegram_id: int
    file_name: str
    content: bytes
    source_language: str
    target_language: str
    status: TranslationJobStatus
    result_file_name: str | None = None
    result_content: bytes | None = None
    error_message: str | None = None


class InMemoryTranslationJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[str, TranslationJob] = {}
        self._next_id = 1

    def create_txt_job(
        self,
        *,
        user_telegram_id: int,
        file_name: str,
        content: bytes,
        source_language: str,
        target_language: str,
    ) -> TranslationJob:
        job = TranslationJob(
            id=f"job-{self._next_id}",
            user_telegram_id=user_telegram_id,
            file_name=file_name,
            content=content,
            source_language=source_language,
            target_language=target_language,
            status=TranslationJobStatus.QUEUED,
        )
        self._next_id += 1
        return self.save(job)

    def get(self, job_id: str) -> TranslationJob:
        return self._jobs[job_id]

    def save(self, job: TranslationJob) -> TranslationJob:
        self._jobs[job.id] = job
        return job


def run_txt_translation_job(
    *,
    repository: InMemoryTranslationJobRepository,
    job_id: str,
    max_fragment_chars: int,
    translator: TextTranslator,
) -> TranslatedDocument:
    job = repository.get(job_id)
    repository.save(replace(job, status=TranslationJobStatus.TRANSLATING))

    try:
        result = translate_txt_document(
            file_name=job.file_name,
            content=job.content,
            source_language=job.source_language,
            target_language=job.target_language,
            max_fragment_chars=max_fragment_chars,
            translator=translator,
        )
    except Exception as error:
        repository.save(
            replace(
                job,
                status=TranslationJobStatus.FAILED,
                error_message=str(error),
            )
        )
        raise

    repository.save(
        replace(
            job,
            status=TranslationJobStatus.READY,
            result_file_name=result.file_name,
            result_content=result.content,
            error_message=None,
        )
    )
    return result

