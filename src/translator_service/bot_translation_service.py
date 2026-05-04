from dataclasses import dataclass
import logging
from typing import Callable

from translator_service.documents import DocumentFormat, validate_document_upload
from translator_service.extractors import (
    extract_text_from_docx,
    extract_text_from_epub,
    extract_text_from_txt,
)
from translator_service.job_runner import (
    DocumentKind,
    InMemoryTranslationJobRepository,
    TranslationJob,
    run_translation_job,
)
from translator_service.language_detection import (
    detect_language_from_text,
    format_detected_source_language,
)
from translator_service.order_estimates import estimate_order
from translator_service.pricing import PricingRules
from translator_service.translation_jobs import CancellationToken, TextTranslator


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingUpload:
    user_telegram_id: int
    file_name: str
    content: bytes
    source_language: str
    document_kind: DocumentKind = DocumentKind.TXT
    source_language_display: str | None = None


@dataclass(frozen=True)
class PendingTranslation:
    user_telegram_id: int
    file_name: str
    content: bytes
    source_language: str
    target_language: str
    price_usd: float
    fragment_count: int
    source_language_display: str | None = None


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
        self._active_cancellations: dict[int, CancellationToken] = {}

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
            source_language_display=_source_language_display(
                document_format=upload.document_format,
                content=content,
                source_language=source_language,
            ),
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
            source_language_display=pending_upload.source_language_display,
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
        source_language_display: str | None = None,
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
            source_language_display=source_language_display
            or _source_language_display(
                document_format=upload.document_format,
                content=content,
                source_language=source_language,
            ),
        )
        self._pending[user_telegram_id] = pending
        return pending

    def get_pending(self, user_telegram_id: int) -> PendingTranslation | None:
        return self._pending.get(user_telegram_id)

    def set_interface_language(self, *, user_telegram_id: int, language_code: str) -> None:
        self._interface_languages[user_telegram_id] = language_code

    def get_interface_language(self, user_telegram_id: int) -> str:
        return self._interface_languages.get(user_telegram_id, "ru")

    def cancel_translation(self, user_telegram_id: int) -> bool:
        token = self._active_cancellations.get(user_telegram_id)
        if token is None:
            return False

        token.cancel()
        return True

    def confirm_pending_translation(
        self,
        *,
        user_telegram_id: int,
        translator: TextTranslator,
        progress_callback: Callable[[tuple[int, int]], None] | None = None,
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
        cancellation_token = CancellationToken()
        self._active_cancellations[user_telegram_id] = cancellation_token
        try:
            run_translation_job(
                repository=self._job_repository,
                job_id=queued_job.id,
                max_fragment_chars=self._max_fragment_chars,
                translator=translator,
                progress_callback=progress_callback,
                cancellation_token=cancellation_token,
            )
        except Exception:
            failed_job = self._job_repository.get(queued_job.id)
            logger.exception(
                "Translation job failed: job_id=%s file_name=%s user_telegram_id=%s",
                failed_job.id,
                failed_job.file_name,
                failed_job.user_telegram_id,
            )
            return self._job_repository.get(queued_job.id)
        finally:
            self._active_cancellations.pop(user_telegram_id, None)

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


def _source_language_display(
    *,
    document_format: DocumentFormat,
    content: bytes,
    source_language: str,
) -> str:
    text = _extract_text_for_language_detection(
        document_format=document_format,
        content=content,
    )
    return format_detected_source_language(
        requested_source_language=source_language,
        detected_language=detect_language_from_text(text),
    )


def _extract_text_for_language_detection(
    *,
    document_format: DocumentFormat,
    content: bytes,
) -> str:
    if document_format is DocumentFormat.TXT:
        return extract_text_from_txt(content)
    if document_format is DocumentFormat.DOCX:
        return extract_text_from_docx(content)
    if document_format is DocumentFormat.EPUB:
        return extract_text_from_epub(content)
    return ""
