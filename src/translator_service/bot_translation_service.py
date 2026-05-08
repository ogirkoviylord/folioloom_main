import logging
import time
from dataclasses import dataclass
from pathlib import PurePath
from threading import RLock
from typing import Callable

from translator_service.documents import DocumentFormat, validate_document_upload
from translator_service.extractors import (
    extract_text_from_docx,
    extract_text_from_epub,
    extract_text_from_txt,
)
from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.job_runner import (
    DocumentKind,
    InMemoryTranslationJobRepository,
    TranslationJob,
    TranslationJobStatus,
    run_translation_job,
)
from translator_service.job_store import TranslationJobStore
from translator_service.language_detection import (
    detect_languages_from_text,
    format_detected_source_languages,
)
from translator_service.order_estimates import estimate_order
from translator_service.persistent_jobs import (
    PersistentTranslationJob,
    PersistentTranslationJobStatus,
    PersistentWorkUnitStatus,
)
from translator_service.persistent_planner import create_persistent_txt_job_plan
from translator_service.pricing import PricingRules
from translator_service.translation_cache import (
    MemoryTranslationCache,
    TranslationCache,
)
from translator_service.translation_jobs import (
    CancellationToken,
    TextTranslator,
    TranslationProgress,
)
from translator_service.worker import (
    assemble_translated_text_result,
    run_next_stored_text_work_unit,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingUpload:
    user_telegram_id: int
    file_name: str
    content: bytes
    source_language: str
    document_kind: DocumentKind = DocumentKind.TXT
    source_language_display: str | None = None
    source_object_key: str | None = None


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
    estimated_seconds: int | None = None
    source_object_key: str | None = None


@dataclass(frozen=True)
class PersistentTranslationDownload:
    job_id: str
    file_name: str
    content: bytes
    content_type: str
    partial: bool


class BotTranslationService:
    def __init__(
        self,
        *,
        job_repository: InMemoryTranslationJobRepository,
        pricing_rules: PricingRules,
        max_upload_mb: int,
        max_fragment_chars: int,
        translation_cache: TranslationCache | None = None,
        file_storage: LocalObjectStorage | None = None,
        persistent_job_store: TranslationJobStore | None = None,
        translation_execution_mode: str = "inline",
    ) -> None:
        if translation_execution_mode not in {"inline", "worker"}:
            raise ValueError(
                "translation_execution_mode must be either 'inline' or 'worker'"
            )
        self._job_repository = job_repository
        self._pricing_rules = pricing_rules
        self._max_upload_mb = max_upload_mb
        self._max_fragment_chars = max_fragment_chars
        self._pending_uploads: dict[int, PendingUpload] = {}
        self._pending: dict[int, PendingTranslation] = {}
        self._interface_languages: dict[int, str] = {}
        self._progress_preview_enabled: dict[int, bool] = {}
        self._active_cancellations: dict[int, CancellationToken] = {}
        self._translation_cache = translation_cache or MemoryTranslationCache()
        self._file_storage = file_storage
        self._persistent_job_store = persistent_job_store
        self._translation_execution_mode = translation_execution_mode
        self._state_lock = RLock()

    def close(self) -> None:
        if self._persistent_job_store is not None:
            self._persistent_job_store.close()

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

        source_object_key = None
        if self._file_storage is not None:
            source_object_key = self._file_storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name=file_name,
                content_type=_content_type_for_format(upload.document_format),
                content=content,
            ).object_key

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
            source_object_key=source_object_key,
        )
        with self._state_lock:
            self._pending_uploads[user_telegram_id] = pending_upload
        return pending_upload

    def get_pending_upload(self, user_telegram_id: int) -> PendingUpload | None:
        with self._state_lock:
            return self._pending_uploads.get(user_telegram_id)

    def prepare_pending_upload(
        self,
        *,
        user_telegram_id: int,
        target_language: str,
    ) -> PendingTranslation:
        with self._state_lock:
            pending_upload = self._pending_uploads.get(user_telegram_id)
            if pending_upload is None:
                raise ValueError(
                    "No uploaded document is waiting for translation language"
                )

        pending = self.prepare_document(
            user_telegram_id=user_telegram_id,
            file_name=pending_upload.file_name,
            content=pending_upload.content,
            source_language=pending_upload.source_language,
            target_language=target_language,
            source_language_display=pending_upload.source_language_display,
            source_object_key=pending_upload.source_object_key,
        )
        with self._state_lock:
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
        source_object_key: str | None = None,
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
            estimated_seconds=estimate_translation_seconds(estimate.fragment_count),
            source_object_key=source_object_key,
        )
        with self._state_lock:
            self._pending[user_telegram_id] = pending
        return pending

    def get_pending(self, user_telegram_id: int) -> PendingTranslation | None:
        with self._state_lock:
            return self._pending.get(user_telegram_id)

    def discard_pending_translation(self, user_telegram_id: int) -> bool:
        with self._state_lock:
            removed_pending = self._pending.pop(user_telegram_id, None)
            removed_upload = self._pending_uploads.pop(user_telegram_id, None)
        return removed_pending is not None or removed_upload is not None

    def set_interface_language(self, *, user_telegram_id: int, language_code: str) -> None:
        with self._state_lock:
            self._interface_languages[user_telegram_id] = language_code

    def get_interface_language(self, user_telegram_id: int) -> str:
        with self._state_lock:
            return self._interface_languages.get(user_telegram_id, "en")

    def set_progress_preview_enabled(
        self,
        *,
        user_telegram_id: int,
        enabled: bool,
    ) -> None:
        with self._state_lock:
            self._progress_preview_enabled[user_telegram_id] = enabled

    def get_progress_preview_enabled(self, user_telegram_id: int) -> bool:
        with self._state_lock:
            return self._progress_preview_enabled.get(user_telegram_id, True)

    def cancel_translation(self, user_telegram_id: int) -> bool:
        with self._state_lock:
            token = self._active_cancellations.get(user_telegram_id)
        if token is None:
            return False

        token.cancel()
        return True

    def resume_persistent_translation(
        self,
        *,
        user_telegram_id: int,
        job_id: str,
    ) -> PersistentTranslationJob:
        job = self._require_owned_persistent_job(
            user_telegram_id=user_telegram_id,
            job_id=job_id,
        )
        return self._persistent_job_store.resume_job(job.id)

    def get_persistent_translation_download(
        self,
        *,
        user_telegram_id: int,
        job_id: str,
        partial: bool,
    ) -> PersistentTranslationDownload:
        job = self._require_owned_persistent_job(
            user_telegram_id=user_telegram_id,
            job_id=job_id,
        )
        if self._file_storage is None:
            raise RuntimeError("Persistent file storage is not configured")

        object_key = None if partial else job.final_object_key
        if object_key is None:
            if not partial and job.status is not PersistentTranslationJobStatus.READY:
                raise ValueError(f"Persistent translation job is not ready: {job_id}")
            result_file_name = _translated_file_name(
                job.file_name,
                job.target_language,
                extension=_result_extension_for_document_kind(job.document_kind),
                is_partial=partial,
            )
            stored = assemble_translated_text_result(
                store=self._persistent_job_store,
                storage=self._file_storage,
                job_id=job.id,
                file_name=result_file_name,
                partial=partial,
                content_type=_content_type_for_document_kind(job.document_kind),
            )
        else:
            stored = self._file_storage.get_metadata(object_key)

        return PersistentTranslationDownload(
            job_id=job.id,
            file_name=stored.file_name,
            content=self._file_storage.get_bytes(stored.object_key),
            content_type=stored.content_type,
            partial=partial,
        )

    def _require_owned_persistent_job(
        self,
        *,
        user_telegram_id: int,
        job_id: str,
    ) -> PersistentTranslationJob:
        if self._persistent_job_store is None:
            raise RuntimeError("Persistent translation storage is not configured")

        job = self._persistent_job_store.get_job(job_id)
        if job is None:
            raise ValueError(f"Translation job does not exist: {job_id}")
        if job.user_id != _persistent_user_id(user_telegram_id):
            raise PermissionError("Translation job belongs to another user")

        return job

    def confirm_pending_translation(
        self,
        *,
        user_telegram_id: int,
        translator: TextTranslator,
        progress_callback: Callable[[TranslationProgress], None] | None = None,
    ) -> TranslationJob:
        with self._state_lock:
            pending = self._pending.pop(user_telegram_id, None)
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

        use_persistent_txt_path = self._should_use_persistent_txt_path(
            document_kind=document_kind,
            pending=pending,
        )
        if self._translation_execution_mode == "worker" and not use_persistent_txt_path:
            with self._state_lock:
                self._pending.setdefault(user_telegram_id, pending)
            raise ValueError(
                "Worker mode currently supports queued TXT translations with "
                "persistent storage only"
            )

        if use_persistent_txt_path:
            try:
                if self._translation_execution_mode == "worker":
                    job = self._queue_persistent_txt_translation(pending=pending)
                else:
                    cancellation_token = CancellationToken()
                    with self._state_lock:
                        self._active_cancellations[user_telegram_id] = (
                            cancellation_token
                        )
                    try:
                        job = self._confirm_persistent_txt_translation(
                            pending=pending,
                            translator=translator,
                            progress_callback=progress_callback,
                            cancellation_token=cancellation_token,
                        )
                    finally:
                        with self._state_lock:
                            self._active_cancellations.pop(user_telegram_id, None)
            except Exception as error:
                logger.exception(
                    "Translation job failed: file_name=%s user_telegram_id=%s",
                    pending.file_name,
                    user_telegram_id,
                )
                with self._state_lock:
                    self._pending.setdefault(user_telegram_id, pending)
                return _failed_translation_job(
                    pending=pending,
                    document_kind=document_kind,
                    error_message=str(error),
                )

            if job.status is TranslationJobStatus.FAILED:
                with self._state_lock:
                    self._pending.setdefault(user_telegram_id, pending)
            return job

        queued_job = self._job_repository.create_job(
            document_kind=document_kind,
            user_telegram_id=user_telegram_id,
            file_name=pending.file_name,
            content=pending.content,
            source_language=pending.source_language,
            target_language=pending.target_language,
        )
        cancellation_token = CancellationToken()
        with self._state_lock:
            self._active_cancellations[user_telegram_id] = cancellation_token
        try:
            run_translation_job(
                repository=self._job_repository,
                job_id=queued_job.id,
                max_fragment_chars=self._max_fragment_chars,
                translator=translator,
                progress_callback=progress_callback,
                cancellation_token=cancellation_token,
                translation_cache=self._translation_cache,
            )
        except Exception:
            failed_job = self._job_repository.get(queued_job.id)
            logger.exception(
                "Translation job failed: job_id=%s file_name=%s user_telegram_id=%s",
                failed_job.id,
                failed_job.file_name,
                failed_job.user_telegram_id,
            )
            with self._state_lock:
                self._pending.setdefault(user_telegram_id, pending)
            return self._job_repository.get(queued_job.id)
        finally:
            with self._state_lock:
                self._active_cancellations.pop(user_telegram_id, None)

        return self._job_repository.get(queued_job.id)

    def _should_use_persistent_txt_path(
        self,
        *,
        document_kind: DocumentKind,
        pending: PendingTranslation,
    ) -> bool:
        return (
            document_kind is DocumentKind.TXT
            and self._file_storage is not None
            and self._persistent_job_store is not None
            and pending.source_object_key is not None
        )

    def _confirm_persistent_txt_translation(
        self,
        *,
        pending: PendingTranslation,
        translator: TextTranslator,
        progress_callback: Callable[[TranslationProgress], None] | None,
        cancellation_token: CancellationToken,
    ) -> TranslationJob:
        assert self._file_storage is not None
        assert self._persistent_job_store is not None
        assert pending.source_object_key is not None

        plan = self._create_persistent_txt_job_plan(pending)
        total_fragments = len(plan.work_units)

        while True:
            if cancellation_token.is_cancelled:
                self._persistent_job_store.cancel_job(plan.job.id)
                return self._build_persistent_txt_result_job(
                    pending=pending,
                    job_id=plan.job.id,
                    partial=True,
                    status=TranslationJobStatus.CANCELLED,
                )

            started_at = time.monotonic()
            completed_unit = run_next_stored_text_work_unit(
                store=self._persistent_job_store,
                storage=self._file_storage,
                job_id=plan.job.id,
                worker_id=f"telegram:{pending.user_telegram_id}",
                translator=translator,
            )
            if completed_unit is None:
                break
            elapsed_seconds = time.monotonic() - started_at
            if completed_unit.status is PersistentWorkUnitStatus.FAILED:
                return _failed_translation_job(
                    pending=pending,
                    document_kind=DocumentKind.TXT,
                    error_message=completed_unit.last_error or "Translation failed",
                    job_id=plan.job.id,
                )

            if progress_callback is not None:
                progress_callback(
                    TranslationProgress(
                        completed_fragments=_completed_persistent_units(
                            self._persistent_job_store,
                            plan.job.id,
                        ),
                        total_fragments=total_fragments,
                        source_text=_persistent_unit_source_text(
                            storage=self._file_storage,
                            source_object_key=completed_unit.source_object_key,
                        ),
                        translated_text=completed_unit.translated_text or "",
                        elapsed_seconds=elapsed_seconds,
                        prompt_tokens=completed_unit.prompt_tokens,
                        completion_tokens=completed_unit.completion_tokens,
                        total_tokens=(
                            completed_unit.prompt_tokens
                            + completed_unit.completion_tokens
                        ),
                        prompt_cache_hit_tokens=completed_unit.cache_hit_tokens,
                        prompt_cache_miss_tokens=completed_unit.cache_miss_tokens,
                    )
                )

        return self._build_persistent_txt_result_job(
            pending=pending,
            job_id=plan.job.id,
            partial=False,
            status=TranslationJobStatus.READY,
        )

    def _queue_persistent_txt_translation(
        self,
        *,
        pending: PendingTranslation,
    ) -> TranslationJob:
        plan = self._create_persistent_txt_job_plan(pending)
        return TranslationJob(
            id=plan.job.id,
            document_kind=DocumentKind.TXT,
            user_telegram_id=pending.user_telegram_id,
            file_name=pending.file_name,
            content=pending.content,
            source_language=pending.source_language,
            target_language=pending.target_language,
            status=TranslationJobStatus.QUEUED,
        )

    def _create_persistent_txt_job_plan(self, pending: PendingTranslation):
        assert self._file_storage is not None
        assert self._persistent_job_store is not None
        assert pending.source_object_key is not None

        return create_persistent_txt_job_plan(
            store=self._persistent_job_store,
            storage=self._file_storage,
            order_id=f"prototype-order-{pending.user_telegram_id}-{int(time.time())}",
            user_id=_persistent_user_id(pending.user_telegram_id),
            source_object_key=pending.source_object_key,
            file_name=pending.file_name,
            source_language=pending.source_language,
            target_language=pending.target_language,
            max_fragment_chars=self._max_fragment_chars,
        )

    def _build_persistent_txt_result_job(
        self,
        *,
        pending: PendingTranslation,
        job_id: str,
        partial: bool,
        status: TranslationJobStatus,
    ) -> TranslationJob:
        assert self._file_storage is not None
        assert self._persistent_job_store is not None

        result_file_name = _translated_file_name(
            pending.file_name,
            pending.target_language,
            extension="txt",
            is_partial=partial,
        )
        stored = assemble_translated_text_result(
            store=self._persistent_job_store,
            storage=self._file_storage,
            job_id=job_id,
            file_name=result_file_name,
            partial=partial,
        )
        return TranslationJob(
            id=job_id,
            document_kind=DocumentKind.TXT,
            user_telegram_id=pending.user_telegram_id,
            file_name=pending.file_name,
            content=pending.content,
            source_language=pending.source_language,
            target_language=pending.target_language,
            status=status,
            result_file_name=result_file_name,
            result_content=self._file_storage.get_bytes(stored.object_key),
        )


def _document_kind_from_format(document_format: DocumentFormat) -> DocumentKind | None:
    if document_format is DocumentFormat.TXT:
        return DocumentKind.TXT
    if document_format is DocumentFormat.DOCX:
        return DocumentKind.DOCX
    if document_format is DocumentFormat.EPUB:
        return DocumentKind.EPUB
    return None


def _failed_translation_job(
    *,
    pending: PendingTranslation,
    document_kind: DocumentKind,
    error_message: str,
    job_id: str = "job-failed",
) -> TranslationJob:
    return TranslationJob(
        id=job_id,
        document_kind=document_kind,
        user_telegram_id=pending.user_telegram_id,
        file_name=pending.file_name,
        content=pending.content,
        source_language=pending.source_language,
        target_language=pending.target_language,
        status=TranslationJobStatus.FAILED,
        error_message=error_message,
    )


def _persistent_user_id(user_telegram_id: int) -> str:
    return f"telegram:{user_telegram_id}"


def _completed_persistent_units(
    store: TranslationJobStore,
    job_id: str,
) -> int:
    return sum(
        1
        for unit in store.list_work_units(job_id)
        if unit.status
        in {PersistentWorkUnitStatus.TRANSLATED, PersistentWorkUnitStatus.CACHED}
    )


def _persistent_unit_source_text(
    *,
    storage: LocalObjectStorage,
    source_object_key: str | None,
) -> str:
    if source_object_key is None:
        return ""
    return storage.get_bytes(source_object_key).decode("utf-8")


def _translated_file_name(
    file_name: str,
    target_language: str,
    *,
    extension: str,
    is_partial: bool,
) -> str:
    path = PurePath(file_name)
    stem = path.stem if path.suffix else file_name
    partial = ".partial" if is_partial else ""
    return f"{stem}.{target_language}{partial}.{extension}"


def _content_type_for_format(document_format: DocumentFormat) -> str:
    if document_format is DocumentFormat.TXT:
        return "text/plain; charset=utf-8"
    if document_format is DocumentFormat.DOCX:
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if document_format is DocumentFormat.EPUB:
        return "application/epub+zip"
    return "application/octet-stream"


def _content_type_for_document_kind(document_kind: str) -> str:
    if document_kind == DocumentKind.TXT.value:
        return "text/plain; charset=utf-8"
    if document_kind == DocumentKind.DOCX.value:
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if document_kind == DocumentKind.EPUB.value:
        return "application/epub+zip"
    return "application/octet-stream"


def _result_extension_for_document_kind(document_kind: str) -> str:
    if document_kind == DocumentKind.TXT.value:
        return "txt"
    if document_kind == DocumentKind.DOCX.value:
        return "docx"
    if document_kind == DocumentKind.EPUB.value:
        return "epub"
    return PurePath(document_kind).suffix.lstrip(".") or document_kind


def estimate_translation_seconds(fragment_count: int) -> int:
    if fragment_count <= 0:
        return 0

    return max(20, fragment_count * 12)


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
    return format_detected_source_languages(
        requested_source_language=source_language,
        detected_languages=detect_languages_from_text(text),
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
