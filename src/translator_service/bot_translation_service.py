from dataclasses import dataclass

from translator_service.documents import DocumentFormat, validate_document_upload
from translator_service.job_runner import (
    DocumentKind,
    InMemoryTranslationJobRepository,
    TranslationJob,
    run_translation_job,
)
from translator_service.order_estimates import estimate_order
from translator_service.pricing import PricingRules
from translator_service.translation_jobs import TextTranslator


@dataclass(frozen=True)
class PendingUpload:
    user_telegram_id: int
    file_name: str
    content: bytes
    source_language: str
    document_kind: DocumentKind = DocumentKind.TXT


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
        self._pending_uploads: dict[int, PendingUpload] = {}
        self._pending: dict[int, PendingTranslation] = {}
        self._interface_languages: dict[int, str] = {}

    def store_uploaded_document(
        self,
        *,
        user_telegram_id: int,
        file_name: str,
        content: bytes,
        source_language: str,
    ) -> PendingUpload:
        upload = validate_document_upload(
            file_name=file_name,
            size_bytes=len(content),
            max_upload_mb=self._max_upload_mb,
        )
        document_kind = _document_kind_from_format(upload.document_format)
        if document_kind is None:
            raise ValueError(
                "Prototype bot currently supports TXT, DOCX, and EPUB translation only"
            )

        pending_upload = PendingUpload(
            user_telegram_id=user_telegram_id,
            file_name=file_name,
            content=content,
            source_language=source_language,
            document_kind=document_kind,
        )
        self._pending_uploads[user_telegram_id] = pending_upload
        return pending_upload

    def get_pending_upload(self, user_telegram_id: int) -> PendingUpload | None:
        return self._pending_uploads.get(user_telegram_id)

    def prepare_pending_upload(
        self,
        *,
        user_telegram_id: int,
        target_language: str,
    ) -> PendingTranslation:
        pending_upload = self._pending_uploads.get(user_telegram_id)
        if pending_upload is None:
            raise ValueError("No uploaded document is waiting for translation language")

        pending = self.prepare_document(
            user_telegram_id=user_telegram_id,
            file_name=pending_upload.file_name,
            content=pending_upload.content,
            source_language=pending_upload.source_language,
            target_language=target_language,
        )
        self._pending_uploads.pop(user_telegram_id, None)
        return pending

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
            document_kind = _document_kind_from_format(upload.document_format)
            if document_kind is None:
                raise ValueError(
                    "Prototype bot currently supports TXT, DOCX, and EPUB translation only"
                )

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

    def set_interface_language(self, *, user_telegram_id: int, language_code: str) -> None:
        self._interface_languages[user_telegram_id] = language_code

    def get_interface_language(self, user_telegram_id: int) -> str:
        return self._interface_languages.get(user_telegram_id, "ru")

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
        document_kind = _document_kind_from_format(upload.document_format)
        if document_kind is None:
            raise ValueError(
                "Only TXT, DOCX, and EPUB confirmation is supported in the prototype"
            )

        queued_job = self._job_repository.create_job(
            document_kind=document_kind,
            user_telegram_id=user_telegram_id,
            file_name=pending.file_name,
            content=pending.content,
            source_language=pending.source_language,
            target_language=pending.target_language,
        )
        try:
            run_translation_job(
                repository=self._job_repository,
                job_id=queued_job.id,
                max_fragment_chars=self._max_fragment_chars,
                translator=translator,
            )
        except Exception:
            return self._job_repository.get(queued_job.id)

        self._pending.pop(user_telegram_id, None)
        return self._job_repository.get(queued_job.id)


def _document_kind_from_format(document_format: DocumentFormat) -> DocumentKind | None:
    if document_format is DocumentFormat.TXT:
        return DocumentKind.TXT
    if document_format is DocumentFormat.DOCX:
        return DocumentKind.DOCX
    if document_format is DocumentFormat.EPUB:
        return DocumentKind.EPUB
    return None
