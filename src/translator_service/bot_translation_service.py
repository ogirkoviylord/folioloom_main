from dataclasses import dataclass

from translator_service.documents import DocumentFormat, validate_document_upload
from translator_service.job_runner import (
    InMemoryTranslationJobRepository,
    TranslationJob,
    run_txt_translation_job,
)
from translator_service.order_estimates import estimate_order
from translator_service.pricing import PricingRules
from translator_service.translation_jobs import TextTranslator


@dataclass(frozen=True)
class PendingTranslation:
    user_telegram_id: int
    file_name: str
    content: bytes
    source_language: str
    target_language: str
    price_usd: float
    fragment_count: int


class BotTranslationService:
    def __init__(
        self,
        *,
        job_repository: InMemoryTranslationJobRepository,
        pricing_rules: PricingRules,
        max_upload_mb: int,
        max_fragment_chars: int,
    ) -> None:
        self._job_repository = job_repository
        self._pricing_rules = pricing_rules
        self._max_upload_mb = max_upload_mb
        self._max_fragment_chars = max_fragment_chars
        self._pending: dict[int, PendingTranslation] = {}
        self._target_languages: dict[int, str] = {}

    def prepare_document(
        self,
        *,
        user_telegram_id: int,
        file_name: str,
        content: bytes,
        source_language: str,
        target_language: str,
    ) -> PendingTranslation:
        upload = validate_document_upload(
            file_name=file_name,
            size_bytes=len(content),
            max_upload_mb=self._max_upload_mb,
        )
        if upload.document_format is not DocumentFormat.TXT:
            raise ValueError("Prototype bot currently supports TXT translation only")

        estimate = estimate_order(
            upload=upload,
            content=content,
            pricing_rules=self._pricing_rules,
            max_fragment_chars=self._max_fragment_chars,
        )
        pending = PendingTranslation(
            user_telegram_id=user_telegram_id,
            file_name=file_name,
            content=content,
            source_language=source_language,
            target_language=target_language,
            price_usd=estimate.price_usd,
            fragment_count=estimate.fragment_count,
        )
        self._pending[user_telegram_id] = pending
        return pending

    def get_pending(self, user_telegram_id: int) -> PendingTranslation | None:
        return self._pending.get(user_telegram_id)

    def set_target_language(self, *, user_telegram_id: int, target_language: str) -> None:
        self._target_languages[user_telegram_id] = target_language

    def get_target_language(self, user_telegram_id: int) -> str:
        return self._target_languages.get(user_telegram_id, "en")

    def confirm_pending_translation(
        self,
        *,
        user_telegram_id: int,
        translator: TextTranslator,
    ) -> TranslationJob:
        pending = self._pending.get(user_telegram_id)
        if pending is None:
            raise ValueError("No pending translation for this user")

        upload = validate_document_upload(
            file_name=pending.file_name,
            size_bytes=len(pending.content),
            max_upload_mb=self._max_upload_mb,
        )
        if upload.document_format is not DocumentFormat.TXT:
            raise ValueError("Only TXT confirmation is supported in the prototype")

        queued_job = self._job_repository.create_txt_job(
            user_telegram_id=user_telegram_id,
            file_name=pending.file_name,
            content=pending.content,
            source_language=pending.source_language,
            target_language=pending.target_language,
        )
        run_txt_translation_job(
            repository=self._job_repository,
            job_id=queued_job.id,
            max_fragment_chars=self._max_fragment_chars,
            translator=translator,
        )
        self._pending.pop(user_telegram_id, None)
        return self._job_repository.get(queued_job.id)
