import hashlib
import json
import logging
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePath
from threading import RLock
from uuid import uuid4

from translator_service.beta_access import (
    BetaAccessPolicy,
    SQLiteBackedBetaAccessPolicy,
)
from translator_service.beta_safety import (
    BetaSafetyGuard,
    BetaSafetyRates,
    JobCostEstimate,
    estimate_cost_usd,
)
from translator_service.document_sandbox import DocumentSandbox
from translator_service.document_scanner import (
    DocumentScanner,
    ScannerVerdict,
    ScanResult,
)
from translator_service.documents import (
    DocumentContentRejectedError,
    DocumentFormat,
    validate_document_content,
    validate_document_upload,
)
from translator_service.extractors import (
    TextExtractionError,
    extract_text_from_docx,
    extract_text_from_epub,
    extract_text_from_txt,
)
from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.format_adapters import (
    DOCX_ADAPTER_VERSION,
    EPUB_ADAPTER_VERSION,
    TXT_ADAPTER_VERSION,
    FormatAdapterPlan,
    FormatTextBlock,
    plan_docx_translation,
    plan_epub_translation,
    plan_txt_translation,
)
from translator_service.glossary_prepared_package import (
    validate_prepared_glossary_package,
)
from translator_service.glossary_prepared_prep_service import (
    PreparedGlossaryPackageAttachment,
    PreparedGlossaryPackageAttachmentRequest,
    PreparedGlossaryPackagePrepRequest,
)
from translator_service.job_runner import (
    DocumentKind,
    InMemoryTranslationJobRepository,
    TranslationJob,
    TranslationJobStatus,
    run_translation_job,
)
from translator_service.language_detection import (
    LANGUAGE_NAMES,
    detect_language_from_text,
    detect_languages_from_text,
    format_detected_source_languages,
)
from translator_service.order_estimates import estimate_order
from translator_service.persistent_assembly import (
    assemble_persistent_docx_result,
    assemble_persistent_epub_result,
    assemble_persistent_txt_result,
    count_unassembled_work_units,
)
from translator_service.persistent_job_store import PersistentJobStore
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    PersistentWorkUnit,
    PersistentWorkUnitStatus,
)
from translator_service.persistent_planner import (
    _translation_context_with_mode_profile,
    _translation_mode_profile_for_document_kind,
    create_persistent_docx_job_plan,
    create_persistent_epub_job_plan,
    create_persistent_txt_job_plan,
)
from translator_service.pricing import PricingRules
from translator_service.security_telemetry import (
    SecurityCooldownPolicy,
    SecurityCooldownTracker,
    SecurityEventLimiter,
    SecurityThresholdExceeded,
    SecurityThresholdPolicy,
    normalize_security_event,
)
from translator_service.structure_optimizer import TextBlockKind
from translator_service.translation_cache import (
    MemoryTranslationCache,
    TranslationCache,
)
from translator_service.translation_context import (
    build_initial_translation_context_memory,
)
from translator_service.translation_jobs import (
    CancellationToken,
    TextTranslator,
    TranslationProgress,
    translate_text_fragments,
)
from translator_service.translation_policy import (
    build_translation_policy,
    translation_policy_signature,
)
from translator_service.translation_run_logs import (
    TranslationFragmentLog,
    TranslationRunLogger,
    TranslationRunMetadata,
    finish_running_translation_runs_for_job,
)
from translator_service.translation_runner import (
    GlossaryRuntimeAdapterHookConfig,
    build_fallback_glossary_runtime_hook,
)
from translator_service.upload_safety_ledger import (
    InMemoryUploadSafetyLedger,
    UploadContainerVerdict,
    UploadSafetyLedgerError,
    UploadSafetyMetadata,
    UploadSafetyRecord,
    UploadSafetyState,
    UploadScanVerdict,
)
from translator_service.user_activity import (
    ActivityActorType,
    ActivityOutcome,
    ActivitySurface,
    SQLiteUserActivityStore,
    UserActivityEventInput,
)
from translator_service.users import SQLiteUserSettingsRepository
from translator_service.worker import (
    _provider_io_diagnostic_sink,
    run_next_stored_text_work_unit,
    run_stored_text_job_parallel_until_idle,
)

logger = logging.getLogger(__name__)
RIGHTS_CONFIRMATION_VERSION = "rights-v1"
RIGHTS_CONFIRMATION_SOURCE_TELEGRAM = "telegram_button"
UPLOAD_SAFETY_ACTIVITY_EVENT_TYPE = "security.upload_safety.summary"
PREVIEW_CANDIDATE_MAX_BLOCKS = 3
PREVIEW_CANDIDATE_MAX_CHARS = 2_000
UPLOAD_DUPLICATE_SCAN_LIMIT = 100
TRANSLATION_MODE_DOCUMENT_FORM = "document_form"
TRANSLATION_MODE_BOOK_MANUSCRIPT = "book_manuscript"
SUPPORTED_TRANSLATION_MODES = (
    TRANSLATION_MODE_DOCUMENT_FORM,
    TRANSLATION_MODE_BOOK_MANUSCRIPT,
)
GLOSSARY_MODE_WITH = "with_glossary"
GLOSSARY_MODE_WITHOUT = "without_glossary"
DEFAULT_GLOSSARY_MODE = GLOSSARY_MODE_WITH
SUPPORTED_GLOSSARY_MODES = (
    GLOSSARY_MODE_WITH,
    GLOSSARY_MODE_WITHOUT,
)
PREPARED_GLOSSARY_PREP_BETA_SAFETY_SCHEMA_VERSION = (
    "prepared-glossary-prep-beta-safety-v1"
)
_PREPARED_GLOSSARY_PREP_BASE_PROMPT_TOKENS = 1_200
_PREPARED_GLOSSARY_PREP_MAX_SOURCE_PACKET_TOKENS = 9_600
_PREPARED_GLOSSARY_PREP_COMPLETION_TOKENS = 2_400
_LANGUAGE_NAME_TO_CODE = {
    language_name.casefold(): language_code
    for language_code, language_name in LANGUAGE_NAMES.items()
}
_MY_BOOK_DETAIL_PROGRESS_STATUSES = {
    PersistentTranslationJobStatus.QUEUED.value,
    PersistentTranslationJobStatus.TRANSLATING.value,
    PersistentTranslationJobStatus.ASSEMBLING.value,
    PersistentTranslationJobStatus.CANCEL_REQUESTED.value,
    PersistentTranslationJobStatus.PAUSED.value,
    PersistentTranslationJobStatus.PARTIAL.value,
    PersistentTranslationJobStatus.CANCELLED.value,
    PersistentTranslationJobStatus.INTERRUPTED.value,
    PersistentTranslationJobStatus.FAILED.value,
}
AutomaticResultDeliveryKey = tuple[int, str, str, int, str]


class RightsConfirmationRequired(ValueError):
    """Raised when document rights have not been confirmed for processing."""


class PreviewAcceptanceRequired(ValueError):
    """Raised when full translation starts before preview acceptance."""


class TranslationModeRequired(ValueError):
    """Raised when a translation mode is required before continuing."""


class GlossaryModeRequired(ValueError):
    """Raised when legacy callers explicitly require a glossary mode."""


class SameLanguageTranslationBlocked(ValueError):
    """Raised when source and target resolve to the same language."""

    def __init__(self, *, source_language_code: str, target_language_code: str) -> None:
        self.source_language_code = source_language_code
        self.target_language_code = target_language_code
        source_language_name = LANGUAGE_NAMES.get(
            source_language_code,
            source_language_code.upper(),
        )
        super().__init__(
            f"This file already appears to be {source_language_name}. "
            "Choose a different target language or cancel this upload."
        )


class DocumentScanRejectedError(ValueError):
    """Raised with a safe user-facing message when upload scanning fails closed."""

    def __init__(
        self,
        message: str = "Document could not pass safety scanning.",
        *,
        verdict: ScannerVerdict | None = None,
        scan_result: ScanResult | None = None,
    ) -> None:
        super().__init__(message)
        self.verdict = verdict
        self.scan_result = scan_result


@dataclass(frozen=True)
class PendingUpload:
    user_telegram_id: int
    file_name: str
    content: bytes
    source_language: str
    document_kind: DocumentKind = DocumentKind.TXT
    source_language_display: str | None = None
    source_object_key: str | None = None
    rights_confirmed: bool = False
    rights_confirmed_at: str | None = None
    rights_confirmation_version: str | None = None
    rights_confirmation_source: str | None = None
    translation_mode: str | None = None
    scan_result: ScanResult | None = None
    upload_safety_id: str | None = None
    attempt_id: str | None = None


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
    rights_confirmed: bool = False
    rights_confirmed_at: str | None = None
    rights_confirmation_version: str | None = None
    rights_confirmation_source: str | None = None
    preview_id: str | None = None
    preview_shown: bool = False
    preview_accepted: bool = False
    preview_accepted_at: str | None = None
    translation_mode: str | None = None
    glossary_mode: str | None = DEFAULT_GLOSSARY_MODE
    scan_result: ScanResult | None = None
    upload_safety_id: str | None = None
    attempt_id: str | None = None


@dataclass(frozen=True)
class PreviewCandidate:
    user_telegram_id: int
    file_name: str
    document_kind: DocumentKind
    source_language: str
    target_language: str
    translation_mode: str | None
    glossary_mode: str | None
    source_text: str
    source_block_ids: tuple[str, ...]
    selected_block_count: int
    selected_unit_sequences: tuple[int, ...]
    character_count: int
    max_character_count: int
    adapter_version: str
    metadata: dict[str, object]
    attempt_id: str | None = None


@dataclass(frozen=True)
class _PreparedGlossaryPackageAttachmentResult:
    payload: dict | None
    metadata: dict[str, object]
    fail_closed: bool = False


@dataclass(frozen=True)
class _PreparedGlossaryPrepBetaSafetyReservation:
    allowed: bool
    metadata: dict[str, object]
    job_id: str | None = None
    user_id: str | None = None
    estimate: JobCostEstimate | None = None


@dataclass(frozen=True)
class PreviewTranslation:
    preview_id: str
    user_telegram_id: int
    file_name: str
    document_kind: DocumentKind
    source_language: str
    target_language: str
    text: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    beta_safety_reason_code: str | None
    metadata: dict[str, object]


class PreviewTranslationError(RuntimeError):
    """Raised with a safe user-facing message when preview generation fails."""


class DuplicatePreviewError(PreviewTranslationError):
    """Raised when the same preview was already generated for a pending request."""


@dataclass(frozen=True)
class CancelTranslationResult:
    cancelled: bool
    job: TranslationJob | None = None


@dataclass(frozen=True)
class UserBookSummary:
    job_id: str
    file_name: str
    document_kind: str
    source_language: str
    target_language: str
    status: str
    has_result: bool
    has_partial_result: bool = False
    can_resume: bool = False
    can_cancel: bool = False
    created_at: str | None = None
    updated_at: str | None = None
    progress_completed_fragments: int | None = None
    progress_total_fragments: int | None = None
    progress_percent: int | None = None


@dataclass(frozen=True)
class DuplicateUploadMatch:
    job_id: str
    file_name: str
    status: str
    has_result: bool
    can_download_existing: bool
    can_translate_again: bool
    can_open_existing: bool


@dataclass(frozen=True)
class UserQueueSummary:
    total_active: int
    queued: int
    translating: int
    items: tuple[UserBookSummary, ...]


@dataclass(frozen=True)
class UserBookProgress:
    job_id: str
    status: TranslationJobStatus
    completed_fragments: int
    total_fragments: int
    estimated_seconds: int | None = None


@dataclass(frozen=True)
class UserBookResult:
    job_id: str
    file_name: str
    content: bytes
    content_type: str


def _automatic_result_delivery_key(
    job: TranslationJob,
) -> AutomaticResultDeliveryKey | None:
    if not (job.result_file_name and job.result_content):
        return None

    return (
        job.user_telegram_id,
        job.id,
        job.result_file_name,
        len(job.result_content),
        hashlib.sha256(job.result_content).hexdigest(),
    )


@dataclass
class _ActiveTranslationCancellation:
    token: CancellationToken
    user_id: str
    job_id: str | None = None
    completed_fragments: int = 0
    total_fragments: int = 0
    cancel_requested: bool = False

    def cancel(self) -> None:
        self.cancel_requested = True
        self.token.cancel()


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
        persistent_job_store: PersistentJobStore | None = None,
        translation_run_log_root: str | Path | None = None,
        user_settings_repository: SQLiteUserSettingsRepository | None = None,
        max_parallel_work_units: int = 1,
        provider_parallel_capacity: int = 1,
        use_scheduler_runner: bool = False,
        defer_persistent_jobs_to_worker: bool = False,
        document_sandbox: DocumentSandbox | None = None,
        security_threshold_policy: SecurityThresholdPolicy | None = None,
        security_cooldown_policy: SecurityCooldownPolicy | None = None,
        document_scanner: DocumentScanner | None = None,
        require_upload_scan: bool = False,
        upload_safety_ledger: InMemoryUploadSafetyLedger | None = None,
        activity_store: SQLiteUserActivityStore | None = None,
        beta_access_policy: (
            BetaAccessPolicy | SQLiteBackedBetaAccessPolicy | None
        ) = None,
        beta_safety_guard: BetaSafetyGuard | None = None,
        beta_safety_rates: BetaSafetyRates | None = None,
        beta_safety_guard_owned: bool = False,
        glossary_runtime_hook_builder: Callable[
            [PendingTranslation, DocumentKind],
            GlossaryRuntimeAdapterHookConfig | None,
        ]
        | None = None,
        prepared_glossary_package_resolver: Callable[
            [PreparedGlossaryPackageAttachmentRequest],
            PreparedGlossaryPackageAttachment | None,
        ]
        | None = None,
        prepared_glossary_package_prep_resolver: Callable[
            [PreparedGlossaryPackagePrepRequest],
            PreparedGlossaryPackageAttachment | None,
        ]
        | None = None,
    ) -> None:
        self._job_repository = job_repository
        self._pricing_rules = pricing_rules
        self._max_upload_mb = max_upload_mb
        self._max_fragment_chars = max_fragment_chars
        self._pending_uploads: dict[int, PendingUpload] = {}
        self._pending: dict[int, PendingTranslation] = {}
        self._interface_languages: dict[int, str] = {}
        self._progress_preview_enabled: dict[int, bool] = {}
        self._active_cancellations: dict[int, _ActiveTranslationCancellation] = {}
        self._translation_cache = translation_cache or MemoryTranslationCache()
        self._file_storage = file_storage
        self._persistent_job_store = persistent_job_store
        self._translation_run_log_root = (
            Path(translation_run_log_root)
            if translation_run_log_root is not None
            else None
        )
        self._user_settings_repository = user_settings_repository
        self._max_parallel_work_units = max(1, max_parallel_work_units)
        self._provider_parallel_capacity = max(1, provider_parallel_capacity)
        self._use_scheduler_runner = use_scheduler_runner
        self._defer_persistent_jobs_to_worker = defer_persistent_jobs_to_worker
        self._document_sandbox = document_sandbox
        self._document_scanner = document_scanner
        self._require_upload_scan = require_upload_scan
        self._upload_safety_ledger = (
            upload_safety_ledger or InMemoryUploadSafetyLedger()
        )
        self._security_threshold_policy = (
            security_threshold_policy or SecurityThresholdPolicy()
        )
        self._security_cooldown_tracker = SecurityCooldownTracker(
            security_cooldown_policy
        )
        self._activity_store = activity_store
        self._beta_access_policy = (
            beta_access_policy or BetaAccessPolicy.from_telegram_ids((), enabled=False)
        )
        self._beta_safety_guard = beta_safety_guard
        self._beta_safety_rates = beta_safety_rates or BetaSafetyRates()
        self._beta_safety_guard_owned = beta_safety_guard_owned
        self._glossary_runtime_hook_builder = glossary_runtime_hook_builder
        self._prepared_glossary_package_resolver = (
            prepared_glossary_package_resolver
        )
        self._prepared_glossary_package_prep_resolver = (
            prepared_glossary_package_prep_resolver
        )
        self._beta_safety_denied_job_ids: set[str] = set()
        self._generated_preview_ids: set[str] = set()
        self._automatic_result_delivered_keys: set[AutomaticResultDeliveryKey] = set()
        self._automatic_result_delivery_in_flight: set[
            AutomaticResultDeliveryKey
        ] = set()
        self._state_lock = RLock()

    def close(self) -> None:
        if self._persistent_job_store is not None:
            self._persistent_job_store.close()
        if self._user_settings_repository is not None:
            self._user_settings_repository.close()
        if self._activity_store is not None:
            self._activity_store.close()
        if self._beta_safety_guard_owned and self._beta_safety_guard is not None:
            close = getattr(self._beta_safety_guard, "close", None)
            if close is not None:
                close()

    def record_user_activity(
        self,
        *,
        user_telegram_id: int,
        event_type: str,
        action: str,
        surface: ActivitySurface | str = ActivitySurface.BOT,
        outcome: ActivityOutcome | str = ActivityOutcome.SUCCESS,
        target_type: str | None = None,
        target_id: str | None = None,
        job_id: str | None = None,
        order_id: str | None = None,
        translation_run_dir: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self._record_activity_for_user(
            user_telegram_id=user_telegram_id,
            event_type=event_type,
            action=action,
            surface=surface,
            outcome=outcome,
            target_type=target_type,
            target_id=target_id,
            job_id=job_id,
            order_id=order_id,
            translation_run_dir=translation_run_dir,
            metadata=metadata,
        )

    def _record_activity_for_user(
        self,
        *,
        user_telegram_id: int,
        event_type: str,
        action: str,
        surface: ActivitySurface | str = ActivitySurface.BOT,
        outcome: ActivityOutcome | str = ActivityOutcome.SUCCESS,
        target_type: str | None = None,
        target_id: str | None = None,
        job_id: str | None = None,
        order_id: str | None = None,
        translation_run_dir: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        if self._activity_store is None:
            return
        try:
            self._activity_store.record_event(
                UserActivityEventInput(
                    actor_type=ActivityActorType.USER,
                    actor_id=f"telegram:{user_telegram_id}",
                    channel="telegram",
                    channel_user_id=str(user_telegram_id),
                    surface=surface,
                    event_type=event_type,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    outcome=outcome,
                    job_id=job_id,
                    order_id=order_id,
                    translation_run_dir=translation_run_dir,
                    metadata=metadata or {},
                )
            )
        except Exception:
            logger.exception(
                "Failed to record user activity: event_type=%s user_telegram_id=%s",
                event_type,
                user_telegram_id,
            )

    def _record_upload_safety_activity(
        self,
        *,
        user_telegram_id: int,
        upload_safety_id: str,
        job_id: str | None = None,
        translation_run_dir: str | None = None,
    ) -> None:
        if self._activity_store is None:
            return
        history = self._upload_safety_ledger.history(upload_safety_id)
        if not history:
            return
        latest = history[-1]
        final_action = _upload_safety_final_action(history)
        metadata = latest.metadata
        parser_access_granted = False
        worker_access_granted = False
        try:
            parser_access_granted = self._upload_safety_ledger.parser_access_decision(
                upload_safety_id
            ).allowed
            worker_access_granted = self._upload_safety_ledger.worker_access_decision(
                upload_safety_id
            ).allowed
        except UploadSafetyLedgerError:
            parser_access_granted = False
            worker_access_granted = False

        self._record_activity_for_user(
            user_telegram_id=user_telegram_id,
            event_type=UPLOAD_SAFETY_ACTIVITY_EVENT_TYPE,
            action=final_action,
            surface=ActivitySurface.SECURITY,
            outcome=_upload_safety_activity_outcome(final_action),
            target_type="upload_safety",
            target_id=upload_safety_id,
            job_id=job_id,
            translation_run_dir=translation_run_dir,
            metadata={
                "upload_id": upload_safety_id,
                "declared_format": metadata.document_format,
                "detected_format": metadata.document_format,
                "size_bytes": metadata.size_bytes,
                "sanitized_original_filename": _safe_upload_filename(
                    metadata.original_file_name
                ),
                "av_verdict": _upload_safety_latest_value(history, "scan_verdict")
                or "not_checked",
                "container_verdict": _upload_safety_latest_value(
                    history,
                    "container_verdict",
                )
                or "not_checked",
                "final_action": final_action,
                "reason_code": _upload_safety_reason_code(history, latest),
                "parser_access_granted": parser_access_granted,
                "worker_access_granted": worker_access_granted,
                "timeline": [
                    {
                        "state": record.state.value,
                        "reason_code": record.metadata.safe_error_class,
                    }
                    for record in history
                ],
                "scanner_health": "unknown",
                "scanner_name": metadata.scanner_name,
                "scanner_version": metadata.scanner_version,
                "signature_database_version": metadata.signature_database_version,
                "signature_database_age_seconds": None,
                "short_hash": _short_upload_hash(metadata.sha256),
            },
        )

    def is_beta_allowed(self, user_telegram_id: int) -> bool:
        return self._beta_access_policy.is_allowed(user_telegram_id)

    def _assert_beta_access_allows(self, user_telegram_id: int) -> None:
        self._beta_access_policy.assert_allowed(user_telegram_id)

    def _assert_security_cooldown_allows(self, user_telegram_id: int) -> None:
        self._security_cooldown_tracker.assert_allowed(
            _security_user_id(user_telegram_id)
        )

    def _record_security_threshold_for_user(
        self,
        *,
        user_telegram_id: int,
        run_logger: TranslationRunLogger | None,
    ) -> None:
        cooldown = self._security_cooldown_tracker.record_threshold_exceeded(
            _security_user_id(user_telegram_id)
        )
        if cooldown is None or run_logger is None:
            return
        run_logger.record_security_event(
            "security_user_cooldown_started",
            {
                "cooldown_seconds": cooldown.remaining_seconds,
                "cooldown_remaining_seconds": cooldown.remaining_seconds,
            },
        )
        self._record_activity_for_user(
            user_telegram_id=user_telegram_id,
            surface=ActivitySurface.SECURITY,
            event_type="security.user_cooldown_started",
            action="blocked",
            outcome=ActivityOutcome.BLOCKED,
            translation_run_dir=str(run_logger.run_dir),
            metadata={
                "cooldown_seconds": cooldown.remaining_seconds,
                "cooldown_remaining_seconds": cooldown.remaining_seconds,
                "security_state": "limited",
            },
        )

    def store_uploaded_document(
        self,
        *,
        user_telegram_id: int,
        file_name: str,
        content: bytes,
        source_language: str,
    ) -> PendingUpload:
        self._assert_beta_access_allows(user_telegram_id)
        self._assert_security_cooldown_allows(user_telegram_id)
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
        upload_safety_id = None
        if self._requires_ledger_backed_upload_gate():
            source_object_key, scan_result, upload_safety_id = (
                self._create_accepted_source_or_raise(
                    user_telegram_id=user_telegram_id,
                    file_name=file_name,
                    content=content,
                    document_format=upload.document_format,
                )
            )
        else:
            scan_result = self._scan_upload_or_raise(
                file_name=file_name,
                content=content,
                document_format=upload.document_format,
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
                document_sandbox=self._document_sandbox,
            ),
            source_object_key=source_object_key,
            scan_result=scan_result,
            upload_safety_id=upload_safety_id,
            attempt_id=_translation_attempt_id(user_telegram_id),
        )
        with self._state_lock:
            self._pending_uploads[user_telegram_id] = pending_upload
        return pending_upload

    def _requires_ledger_backed_upload_gate(self) -> bool:
        return self._require_upload_scan

    def _create_accepted_source_or_raise(
        self,
        *,
        user_telegram_id: int,
        file_name: str,
        content: bytes,
        document_format: DocumentFormat,
    ) -> tuple[str, ScanResult, str]:
        if self._file_storage is None:
            raise DocumentScanRejectedError()

        digest = hashlib.sha256(content).hexdigest()
        upload_safety_id = _upload_safety_id(
            user_telegram_id=user_telegram_id,
            digest=digest,
        )
        try:
            quarantine = self._file_storage.put_bytes(
                kind=StoredFileKind.QUARANTINE,
                file_name=file_name,
                content_type=_content_type_for_format(document_format),
                content=content,
            )
        except Exception as error:
            raise DocumentScanRejectedError() from error
        try:
            self._upload_safety_ledger.create_received(
                UploadSafetyMetadata(
                    upload_id=upload_safety_id,
                    user_id=f"telegram:{user_telegram_id}",
                    quarantine_object_key=quarantine.object_key,
                    original_file_name=PurePath(file_name).name,
                    document_format=document_format.value,
                    size_bytes=len(content),
                    sha256=digest,
                )
            )
            self._upload_safety_ledger.transition(
                upload_safety_id,
                UploadSafetyState.QUARANTINED,
            )
            scan_result = self._scan_upload_with_ledger_or_raise(
                user_telegram_id=user_telegram_id,
                upload_safety_id=upload_safety_id,
                file_name=file_name,
                content=content,
                document_format=document_format,
            )
            self._upload_safety_ledger.transition(
                upload_safety_id,
                UploadSafetyState.CONTAINER_STARTED,
            )
            self._validate_upload_container_with_ledger_or_raise(
                user_telegram_id=user_telegram_id,
                upload_safety_id=upload_safety_id,
                file_name=file_name,
                content=content,
                document_format=document_format,
            )
            self._upload_safety_ledger.transition(
                upload_safety_id,
                UploadSafetyState.CONTAINER_CLEAN,
                container_verdict=UploadContainerVerdict.CLEAN,
            )
        except UploadSafetyLedgerError as error:
            raise DocumentScanRejectedError() from error

        try:
            accepted = self._file_storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name=file_name,
                content_type=_content_type_for_format(document_format),
                content=content,
            )
        except Exception as error:
            raise DocumentScanRejectedError() from error
        try:
            self._upload_safety_ledger.create_accepted_source(
                upload_safety_id,
                accepted_source_object_key=accepted.object_key,
            )
        except UploadSafetyLedgerError as error:
            self._file_storage.delete(accepted.object_key)
            raise DocumentScanRejectedError() from error

        decision = self._upload_safety_ledger.parser_access_decision(upload_safety_id)
        if (
            not decision.allowed
            or decision.accepted_source_object_key != accepted.object_key
        ):
            self._file_storage.delete(accepted.object_key)
            raise DocumentScanRejectedError()
        self._record_upload_safety_activity(
            user_telegram_id=user_telegram_id,
            upload_safety_id=upload_safety_id,
        )
        return accepted.object_key, scan_result, upload_safety_id

    def _scan_upload_with_ledger_or_raise(
        self,
        *,
        user_telegram_id: int,
        upload_safety_id: str,
        file_name: str,
        content: bytes,
        document_format: DocumentFormat,
    ) -> ScanResult:
        try:
            self._upload_safety_ledger.transition(
                upload_safety_id,
                UploadSafetyState.SCAN_STARTED,
            )
            result = self._scan_upload_or_raise(
                file_name=file_name,
                content=content,
                document_format=document_format,
            )
            assert result is not None
            self._upload_safety_ledger.transition(
                upload_safety_id,
                UploadSafetyState.SCAN_CLEAN,
                scan_verdict=UploadScanVerdict.CLEAN,
            )
            return result
        except DocumentScanRejectedError as error:
            result = error.scan_result
            failed_state = (
                UploadSafetyState.SCAN_BLOCKED
                if error.verdict is ScannerVerdict.INFECTED
                else UploadSafetyState.SCAN_FAILED
            )
            try:
                self._upload_safety_ledger.transition(
                    upload_safety_id,
                    failed_state,
                    scan_verdict=_upload_scan_verdict(error.verdict),
                    safe_error_class=(
                        result.safe_error_class
                        if result is not None
                        else _safe_scan_error_class(error.verdict)
                    ),
                )
                self._upload_safety_ledger.transition(
                    upload_safety_id,
                    UploadSafetyState.REJECTED,
                )
            except UploadSafetyLedgerError:
                pass
            self._record_upload_safety_activity(
                user_telegram_id=user_telegram_id,
                upload_safety_id=upload_safety_id,
            )
            raise

    def _scan_upload_or_raise(
        self,
        *,
        file_name: str,
        content: bytes,
        document_format: DocumentFormat,
    ) -> ScanResult | None:
        if self._document_scanner is None:
            if self._require_upload_scan:
                raise DocumentScanRejectedError()
            return None

        try:
            result = self._document_scanner.scan(
                file_name=file_name,
                content=content,
                document_format=document_format,
            )
        except Exception as error:
            digest = hashlib.sha256(content).hexdigest()
            result = ScanResult(
                verdict=ScannerVerdict.SCANNER_ERROR,
                scanner_name=self._document_scanner.__class__.__name__,
                scanner_version=None,
                signature_database_version=None,
                content_sha256=digest,
                size_bytes=len(content),
                document_format=document_format,
                safe_error_class=error.__class__.__name__,
            )
            raise DocumentScanRejectedError(
                verdict=result.verdict,
                scan_result=result,
            ) from error

        if result.verdict is not ScannerVerdict.CLEAN:
            raise DocumentScanRejectedError(
                verdict=result.verdict,
                scan_result=result,
            )
        return result

    def _validate_upload_container_with_ledger_or_raise(
        self,
        *,
        user_telegram_id: int,
        upload_safety_id: str,
        file_name: str,
        content: bytes,
        document_format: DocumentFormat,
    ) -> None:
        try:
            validate_document_content(
                file_name=file_name,
                content=content,
                document_format=document_format,
            )
        except DocumentContentRejectedError as error:
            failed_state = (
                UploadSafetyState.CONTAINER_FAILED
                if error.container_failed
                else UploadSafetyState.CONTAINER_BLOCKED
            )
            verdict = (
                UploadContainerVerdict.FAILED
                if error.container_failed
                else UploadContainerVerdict.SUSPICIOUS
            )
            try:
                self._upload_safety_ledger.transition(
                    upload_safety_id,
                    failed_state,
                    container_verdict=verdict,
                    safe_error_class=error.safe_error_class,
                )
                self._upload_safety_ledger.transition(
                    upload_safety_id,
                    UploadSafetyState.REJECTED,
                )
            except UploadSafetyLedgerError:
                pass
            self._record_upload_safety_activity(
                user_telegram_id=user_telegram_id,
                upload_safety_id=upload_safety_id,
            )
            raise DocumentScanRejectedError(
                verdict=ScannerVerdict.SUSPICIOUS_CONTAINER,
            ) from error

    def _assert_parser_access_allowed(
        self,
        *,
        upload_safety_id: str | None,
        source_object_key: str | None,
    ) -> None:
        if not self._requires_ledger_backed_upload_gate():
            return
        if upload_safety_id is None or source_object_key is None:
            raise DocumentScanRejectedError()
        decision = self._upload_safety_ledger.parser_access_decision(upload_safety_id)
        if (
            not decision.allowed
            or decision.accepted_source_object_key != source_object_key
        ):
            raise DocumentScanRejectedError()

    def _assert_worker_access_allowed(
        self,
        *,
        upload_safety_id: str | None,
        source_object_key: str | None,
    ) -> None:
        if not self._requires_ledger_backed_upload_gate():
            return
        if upload_safety_id is None or source_object_key is None:
            raise DocumentScanRejectedError()
        decision = self._upload_safety_ledger.worker_access_decision(upload_safety_id)
        if (
            not decision.allowed
            or decision.accepted_source_object_key != source_object_key
        ):
            raise DocumentScanRejectedError()

    def _upload_safety_id_for_accepted_source(
        self,
        source_object_key: str | None,
    ) -> str | None:
        if not self._requires_ledger_backed_upload_gate():
            return None
        if source_object_key is None:
            raise DocumentScanRejectedError()
        upload_safety_id = self._upload_safety_ledger.upload_id_for_accepted_source(
            source_object_key
        )
        self._assert_worker_access_allowed(
            upload_safety_id=upload_safety_id,
            source_object_key=source_object_key,
        )
        return upload_safety_id

    def get_pending_upload(self, user_telegram_id: int) -> PendingUpload | None:
        with self._state_lock:
            return self._pending_uploads.get(user_telegram_id)

    def confirm_pending_upload_rights(
        self,
        *,
        user_telegram_id: int,
        source: str = RIGHTS_CONFIRMATION_SOURCE_TELEGRAM,
    ) -> PendingUpload:
        self._assert_beta_access_allows(user_telegram_id)
        self._assert_security_cooldown_allows(user_telegram_id)
        with self._state_lock:
            pending_upload = self._pending_uploads.get(user_telegram_id)
            if pending_upload is None:
                raise ValueError(
                    "No uploaded document is waiting for rights confirmation"
                )
            if pending_upload.rights_confirmed:
                return pending_upload
            confirmed = replace(
                pending_upload,
                rights_confirmed=True,
                rights_confirmed_at=_now_iso(),
                rights_confirmation_version=RIGHTS_CONFIRMATION_VERSION,
                rights_confirmation_source=source,
            )
            self._pending_uploads[user_telegram_id] = confirmed

        self._record_activity_for_user(
            user_telegram_id=user_telegram_id,
            event_type="document.rights_confirmed",
            action="confirmed",
            target_type="document",
            target_id=confirmed.file_name,
            metadata=_rights_confirmation_payload(confirmed),
        )
        return confirmed

    def select_pending_upload_translation_mode(
        self,
        *,
        user_telegram_id: int,
        translation_mode: str,
    ) -> PendingUpload:
        self._assert_beta_access_allows(user_telegram_id)
        self._assert_security_cooldown_allows(user_telegram_id)
        normalized_mode = _normalize_translation_mode(translation_mode)
        with self._state_lock:
            pending_upload = self._pending_uploads.get(user_telegram_id)
            if pending_upload is None:
                raise ValueError(
                    "No uploaded document is waiting for translation mode"
                )
            if not pending_upload.rights_confirmed:
                raise RightsConfirmationRequired(
                    "Document rights must be confirmed before choosing "
                    "translation mode"
                )
            if pending_upload.translation_mode == normalized_mode:
                return pending_upload
            selected = replace(pending_upload, translation_mode=normalized_mode)
            self._pending_uploads[user_telegram_id] = selected

        self._record_activity_for_user(
            user_telegram_id=user_telegram_id,
            event_type="translation.mode.selected",
            action="selected",
            target_type="translation_mode",
            target_id=normalized_mode,
            metadata={
                "translation_mode": normalized_mode,
                "file_name": selected.file_name,
                "document_kind": selected.document_kind.value,
            },
        )
        return selected

    def prepare_pending_upload(
        self,
        *,
        user_telegram_id: int,
        target_language: str,
        glossary_mode: str | None = DEFAULT_GLOSSARY_MODE,
    ) -> PendingTranslation:
        self._assert_beta_access_allows(user_telegram_id)
        self._assert_security_cooldown_allows(user_telegram_id)
        with self._state_lock:
            pending_upload = self._pending_uploads.get(user_telegram_id)
            if pending_upload is None:
                raise ValueError(
                    "No uploaded document is waiting for translation language"
                )
            if not pending_upload.rights_confirmed:
                raise RightsConfirmationRequired(
                    "Document rights must be confirmed before choosing "
                    "translation language"
                )
            if pending_upload.translation_mode is None:
                raise TranslationModeRequired(
                    "Choose how this document should be translated before "
                    "choosing translation language"
                )

        pending = self.prepare_document(
            user_telegram_id=user_telegram_id,
            file_name=pending_upload.file_name,
            content=pending_upload.content,
            source_language=pending_upload.source_language,
            target_language=target_language,
            source_language_display=pending_upload.source_language_display,
            source_object_key=pending_upload.source_object_key,
            rights_confirmed=pending_upload.rights_confirmed,
            rights_confirmed_at=pending_upload.rights_confirmed_at,
            rights_confirmation_version=pending_upload.rights_confirmation_version,
            rights_confirmation_source=pending_upload.rights_confirmation_source,
            translation_mode=pending_upload.translation_mode,
            glossary_mode=glossary_mode,
            scan_result=pending_upload.scan_result,
            upload_safety_id=pending_upload.upload_safety_id,
            attempt_id=pending_upload.attempt_id,
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
        rights_confirmed: bool = True,
        rights_confirmed_at: str | None = None,
        rights_confirmation_version: str | None = None,
        rights_confirmation_source: str | None = None,
        translation_mode: str | None = None,
        glossary_mode: str | None = DEFAULT_GLOSSARY_MODE,
        scan_result: ScanResult | None = None,
        upload_safety_id: str | None = None,
        attempt_id: str | None = None,
    ) -> PendingTranslation:
        self._assert_beta_access_allows(user_telegram_id)
        self._assert_security_cooldown_allows(user_telegram_id)
        normalized_mode = (
            _normalize_translation_mode(translation_mode)
            if translation_mode is not None
            else None
        )
        normalized_glossary_mode = _normalize_glossary_mode(
            glossary_mode or DEFAULT_GLOSSARY_MODE
        )
        upload = validate_document_upload(
            file_name=file_name,
            size_bytes=len(content),
            max_upload_mb=self._max_upload_mb,
        )
        if upload.document_format is not DocumentFormat.TXT:
            document_kind = _document_kind_from_format(upload.document_format)
            if document_kind is None:
                raise ValueError(
                    "Prototype bot currently supports TXT, DOCX, and EPUB "
                    "translation only"
                )
        if self._requires_ledger_backed_upload_gate() and upload_safety_id is None:
            source_object_key, resolved_scan_result, upload_safety_id = (
                self._create_accepted_source_or_raise(
                    user_telegram_id=user_telegram_id,
                    file_name=file_name,
                    content=content,
                    document_format=upload.document_format,
                )
            )
        else:
            resolved_scan_result = scan_result or self._scan_upload_or_raise(
                file_name=file_name,
                content=content,
                document_format=upload.document_format,
            )
            self._assert_parser_access_allowed(
                upload_safety_id=upload_safety_id,
                source_object_key=source_object_key,
            )

        estimate = estimate_order(
            upload=upload,
            content=content,
            pricing_rules=self._pricing_rules,
            max_fragment_chars=self._max_fragment_chars,
            document_sandbox=self._document_sandbox,
            translation_mode=normalized_mode,
        )
        resolved_source_language_display = source_language_display or (
            _source_language_display(
                document_format=upload.document_format,
                content=content,
                source_language=source_language,
                document_sandbox=self._document_sandbox,
            )
        )
        _raise_if_same_language_translation(
            source_language=source_language,
            source_language_display=resolved_source_language_display,
            target_language=target_language,
        )
        pending = PendingTranslation(
            user_telegram_id=user_telegram_id,
            file_name=file_name,
            content=content,
            source_language=source_language,
            target_language=target_language,
            price_usd=estimate.price_usd,
            fragment_count=estimate.fragment_count,
            source_language_display=resolved_source_language_display,
            estimated_seconds=estimate_translation_seconds(
                estimate.fragment_count,
                max_parallel_work_units=self._max_parallel_work_units,
                provider_parallel_capacity=self._provider_parallel_capacity,
            ),
            source_object_key=source_object_key,
            rights_confirmed=rights_confirmed,
            rights_confirmed_at=rights_confirmed_at
            or (_now_iso() if rights_confirmed else None),
            rights_confirmation_version=(
                rights_confirmation_version
                or (RIGHTS_CONFIRMATION_VERSION if rights_confirmed else None)
            ),
            rights_confirmation_source=(
                rights_confirmation_source
                or (RIGHTS_CONFIRMATION_SOURCE_TELEGRAM if rights_confirmed else None)
            ),
            translation_mode=normalized_mode,
            glossary_mode=normalized_glossary_mode,
            scan_result=resolved_scan_result,
            upload_safety_id=upload_safety_id,
            attempt_id=attempt_id or _translation_attempt_id(user_telegram_id),
        )
        with self._state_lock:
            self._pending[user_telegram_id] = pending
        self._record_activity_for_user(
            user_telegram_id=user_telegram_id,
            event_type="translation.target_language.selected",
            action="selected",
            target_type="language",
            target_id=target_language,
            metadata={
                "target_language": target_language,
                "file_name": file_name,
                "source_language": source_language,
                "translation_mode": normalized_mode,
                "glossary_mode": normalized_glossary_mode,
            },
        )
        self._record_activity_for_user(
            user_telegram_id=user_telegram_id,
            event_type="document.estimated",
            action="estimated",
            target_type="document",
            target_id=file_name,
            metadata={
                "file_name": file_name,
                "document_kind": _document_kind_from_format(
                    upload.document_format
                ).value,
                "source_language": source_language,
                "target_language": target_language,
                "translation_mode": pending.translation_mode,
                "glossary_mode": pending.glossary_mode,
                "source_language_display": pending.source_language_display,
                "fragment_count": pending.fragment_count,
                "price_usd": pending.price_usd,
                "estimated_seconds": pending.estimated_seconds,
            },
        )
        return pending

    def get_pending(self, user_telegram_id: int) -> PendingTranslation | None:
        with self._state_lock:
            return self._pending.get(user_telegram_id)

    def select_pending_translation_glossary_mode(
        self,
        *,
        user_telegram_id: int,
        glossary_mode: str,
    ) -> PendingTranslation:
        self._assert_beta_access_allows(user_telegram_id)
        self._assert_security_cooldown_allows(user_telegram_id)
        normalized_mode = _normalize_glossary_mode(glossary_mode)
        with self._state_lock:
            pending = self._pending.get(user_telegram_id)
            if pending is None:
                raise ValueError("No pending translation is waiting for glossary mode")
            if not pending.rights_confirmed:
                raise RightsConfirmationRequired(
                    "Document rights must be confirmed before choosing glossary mode"
                )
            if pending.translation_mode is None:
                raise TranslationModeRequired(
                    "Choose how this document should be translated before "
                    "choosing glossary mode"
                )
            if pending.glossary_mode == normalized_mode:
                return pending
            selected = replace(
                pending,
                glossary_mode=normalized_mode,
                preview_id=None,
                preview_shown=False,
                preview_accepted=False,
                preview_accepted_at=None,
            )
            self._pending[user_telegram_id] = selected

        self._record_activity_for_user(
            user_telegram_id=user_telegram_id,
            event_type="translation.glossary_mode.selected",
            action="selected",
            target_type="glossary_mode",
            target_id=normalized_mode,
            metadata={
                "glossary_mode": normalized_mode,
                "file_name": selected.file_name,
                "target_language": selected.target_language,
                "translation_mode": selected.translation_mode,
            },
        )
        return selected

    def select_preview_candidate(self, *, user_telegram_id: int) -> PreviewCandidate:
        self._assert_beta_access_allows(user_telegram_id)
        self._assert_security_cooldown_allows(user_telegram_id)
        with self._state_lock:
            pending = self._pending.get(user_telegram_id)
            if pending is None:
                raise ValueError(
                    "No uploaded document is waiting for preview selection"
                )
            if not pending.rights_confirmed:
                raise RightsConfirmationRequired(
                    "Document rights must be confirmed before preview selection"
                )
            if pending.glossary_mode is None:
                pending = replace(
                    pending,
                    glossary_mode=DEFAULT_GLOSSARY_MODE,
                )
                self._pending[user_telegram_id] = pending
            self._assert_parser_access_allowed(
                upload_safety_id=pending.upload_safety_id,
                source_object_key=pending.source_object_key,
            )

        upload = validate_document_upload(
            file_name=pending.file_name,
            size_bytes=len(pending.content),
            max_upload_mb=self._max_upload_mb,
        )
        document_kind = _document_kind_from_format(upload.document_format)
        if document_kind is None:
            raise ValueError("Preview is available for TXT, DOCX, and EPUB only")

        plan = _preview_adapter_plan(
            document_format=upload.document_format,
            content=pending.content,
            max_fragment_chars=self._max_fragment_chars,
            document_sandbox=self._document_sandbox,
            translation_mode=pending.translation_mode,
        )
        selected = _select_preview_blocks(plan)
        if not selected:
            raise ValueError(
                "Document does not contain text suitable for a preview"
            )

        source_text = _bounded_preview_text(
            [block.text for _sequence, block in selected],
            max_chars=PREVIEW_CANDIDATE_MAX_CHARS,
        )
        if not source_text.strip():
            raise ValueError(
                "Document does not contain text suitable for a preview"
            )

        source_block_ids = tuple(block.source_block_id for _sequence, block in selected)
        unit_sequences = tuple(dict.fromkeys(sequence for sequence, _block in selected))
        metadata: dict[str, object] = {
            "document_kind": document_kind.value,
            "document_format": upload.document_format.value,
            "adapter_version": plan.adapter_version,
            "source_block_ids": list(source_block_ids),
            "selected_block_count": len(selected),
            "selected_unit_sequences": list(unit_sequences),
            "character_count": len(source_text),
            "max_character_count": PREVIEW_CANDIDATE_MAX_CHARS,
            "sampling_policy": "first_meaningful_translatable_blocks",
        }
        metadata.update(
            _preview_translation_mode_metadata(
                selected=selected,
                translation_mode=pending.translation_mode,
            )
        )
        metadata["glossary_mode"] = pending.glossary_mode
        return PreviewCandidate(
            user_telegram_id=user_telegram_id,
            file_name=pending.file_name,
            document_kind=document_kind,
            source_language=pending.source_language,
            target_language=pending.target_language,
            translation_mode=pending.translation_mode,
            glossary_mode=pending.glossary_mode,
            source_text=source_text,
            source_block_ids=source_block_ids,
            selected_block_count=len(selected),
            selected_unit_sequences=unit_sequences,
            character_count=len(source_text),
            max_character_count=PREVIEW_CANDIDATE_MAX_CHARS,
            adapter_version=plan.adapter_version,
            metadata=metadata,
            attempt_id=pending.attempt_id,
        )

    def generate_preview_translation(
        self,
        *,
        user_telegram_id: int,
        translator: TextTranslator,
    ) -> PreviewTranslation:
        candidate = self.select_preview_candidate(user_telegram_id=user_telegram_id)
        preview_id = _preview_id(candidate)
        estimate = _estimate_preview_cost(
            candidate=candidate,
            rates=self._beta_safety_rates,
        )
        beta_safety_reason_code = self._reserve_beta_safety_for_preview(
            preview_id=preview_id,
            user_id=f"telegram:{user_telegram_id}",
            estimate=estimate,
        )
        progress: list[TranslationProgress] = []

        try:
            result = translate_text_fragments(
                fragments=[candidate.source_text],
                source_language=candidate.source_language,
                target_language=candidate.target_language,
                translator=translator,
                progress_callback=progress.append,
            )
            translated_text = result.assembled_text.strip()
            if not translated_text:
                raise PreviewTranslationError("Preview translation failed.")

            usage = progress[-1] if progress else None
            prompt_tokens = usage.prompt_tokens if usage is not None else 0
            completion_tokens = usage.completion_tokens if usage is not None else 0
            if prompt_tokens <= 0 and completion_tokens <= 0:
                prompt_tokens = estimate.prompt_tokens
                completion_tokens = estimate.completion_tokens
            self._record_beta_safety_preview_usage(
                preview_id=preview_id,
                user_id=f"telegram:{user_telegram_id}",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            self._mark_beta_safety_reservation_consumed(job_id=preview_id)
            metadata = {
                **candidate.metadata,
                "preview_id": preview_id,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "estimated_cost_usd": estimate.estimated_cost_usd,
                "beta_safety_reason_code": beta_safety_reason_code,
            }
            preview = PreviewTranslation(
                preview_id=preview_id,
                user_telegram_id=user_telegram_id,
                file_name=candidate.file_name,
                document_kind=candidate.document_kind,
                source_language=candidate.source_language,
                target_language=candidate.target_language,
                text=translated_text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost_usd=estimate.estimated_cost_usd,
                beta_safety_reason_code=beta_safety_reason_code,
                metadata=metadata,
            )
            with self._state_lock:
                pending = self._pending.get(user_telegram_id)
                if pending is not None:
                    self._pending[user_telegram_id] = replace(
                        pending,
                        preview_id=preview_id,
                        preview_shown=False,
                        preview_accepted=False,
                        preview_accepted_at=None,
                    )
            return preview
        except PreviewTranslationError:
            self._release_beta_safety_reservation(
                job_id=preview_id,
                reason="preview_failed",
            )
            raise
        except Exception as exc:
            self._release_beta_safety_reservation(
                job_id=preview_id,
                reason="preview_failed",
            )
            raise PreviewTranslationError("Preview translation failed.") from exc

    def mark_pending_translation_preview_shown(
        self,
        *,
        user_telegram_id: int,
        preview_id: str,
    ) -> PendingTranslation:
        with self._state_lock:
            pending = self._pending.get(user_telegram_id)
            if pending is None:
                raise ValueError("No pending translation for this user")
            if pending.preview_id != preview_id:
                raise PreviewAcceptanceRequired(
                    "Review the translation preview before continuing."
                )
            if pending.preview_shown:
                return pending
            shown = replace(pending, preview_shown=True)
            self._pending[user_telegram_id] = shown
            return shown

    def accept_pending_translation_preview(
        self,
        *,
        user_telegram_id: int,
    ) -> PendingTranslation:
        with self._state_lock:
            pending = self._pending.get(user_telegram_id)
            if pending is None:
                raise ValueError("No pending translation for this user")
            if not pending.rights_confirmed:
                raise RightsConfirmationRequired(
                    "Document rights must be confirmed before translation starts"
                )
            if pending.translation_mode is None:
                raise TranslationModeRequired(
                    "Choose how this document should be translated before "
                    "translation starts"
                )
            if pending.glossary_mode is None:
                pending = replace(
                    pending,
                    glossary_mode=DEFAULT_GLOSSARY_MODE,
                )
                self._pending[user_telegram_id] = pending
            if not pending.preview_id or not pending.preview_shown:
                raise PreviewAcceptanceRequired(
                    "Review the translation preview before continuing."
                )
            if pending.preview_accepted:
                return pending
            accepted = replace(
                pending,
                preview_accepted=True,
                preview_accepted_at=_now_iso(),
            )
            self._pending[user_telegram_id] = accepted
            return accepted

    def discard_pending_translation(self, user_telegram_id: int) -> bool:
        with self._state_lock:
            removed_pending = self._pending.pop(user_telegram_id, None)
            removed_upload = self._pending_uploads.pop(user_telegram_id, None)
        return removed_pending is not None or removed_upload is not None

    def restore_pending_translation_upload(
        self,
        *,
        user_telegram_id: int,
    ) -> PendingUpload | None:
        with self._state_lock:
            pending = self._pending.pop(user_telegram_id, None)
            if pending is None:
                return None
            upload_info = validate_document_upload(
                file_name=pending.file_name,
                size_bytes=len(pending.content),
                max_upload_mb=self._max_upload_mb,
            )
            upload = PendingUpload(
                user_telegram_id=pending.user_telegram_id,
                file_name=pending.file_name,
                content=pending.content,
                source_language=pending.source_language,
                document_kind=(
                    _document_kind_from_format(upload_info.document_format)
                    or DocumentKind.TXT
                ),
                source_language_display=pending.source_language_display,
                source_object_key=pending.source_object_key,
                rights_confirmed=pending.rights_confirmed,
                rights_confirmed_at=pending.rights_confirmed_at,
                rights_confirmation_version=pending.rights_confirmation_version,
                rights_confirmation_source=pending.rights_confirmation_source,
                translation_mode=pending.translation_mode,
                scan_result=pending.scan_result,
                upload_safety_id=pending.upload_safety_id,
                attempt_id=pending.attempt_id,
            )
            self._pending_uploads[user_telegram_id] = upload
            return upload

    def set_interface_language(
        self, *, user_telegram_id: int, language_code: str
    ) -> None:
        if self._user_settings_repository is not None:
            self._user_settings_repository.set_interface_language(
                telegram_id=user_telegram_id,
                language_code=language_code,
            )
            self._record_activity_for_user(
                user_telegram_id=user_telegram_id,
                event_type="user.interface_language.changed",
                action="changed",
                target_type="setting",
                target_id="interface_language",
                metadata={"language_code": language_code},
            )
            return

        with self._state_lock:
            self._interface_languages[user_telegram_id] = language_code
        self._record_activity_for_user(
            user_telegram_id=user_telegram_id,
            event_type="user.interface_language.changed",
            action="changed",
            target_type="setting",
            target_id="interface_language",
            metadata={"language_code": language_code},
        )

    def get_interface_language(self, user_telegram_id: int) -> str:
        if self._user_settings_repository is not None:
            return (
                self._user_settings_repository.get(user_telegram_id).interface_language
                or "en"
            )

        with self._state_lock:
            return self._interface_languages.get(user_telegram_id, "en")

    def has_interface_language(self, user_telegram_id: int) -> bool:
        if self._user_settings_repository is not None:
            return self._user_settings_repository.has_interface_language(
                user_telegram_id
            )

        with self._state_lock:
            return user_telegram_id in self._interface_languages

    def set_progress_preview_enabled(
        self,
        *,
        user_telegram_id: int,
        enabled: bool,
    ) -> None:
        if self._user_settings_repository is not None:
            self._user_settings_repository.set_progress_preview_enabled(
                telegram_id=user_telegram_id,
                enabled=enabled,
            )
            self._record_activity_for_user(
                user_telegram_id=user_telegram_id,
                event_type="user.setting.changed",
                action="changed",
                target_type="setting",
                target_id="progress_preview_enabled",
                metadata={
                    "setting_key": "progress_preview_enabled",
                    "new_value": enabled,
                },
            )
            return

        with self._state_lock:
            self._progress_preview_enabled[user_telegram_id] = enabled
        self._record_activity_for_user(
            user_telegram_id=user_telegram_id,
            event_type="user.setting.changed",
            action="changed",
            target_type="setting",
            target_id="progress_preview_enabled",
            metadata={"setting_key": "progress_preview_enabled", "new_value": enabled},
        )

    def get_progress_preview_enabled(self, user_telegram_id: int) -> bool:
        if self._user_settings_repository is not None:
            return self._user_settings_repository.get(
                user_telegram_id
            ).progress_preview_enabled

        with self._state_lock:
            return self._progress_preview_enabled.get(user_telegram_id, True)

    def reset_user_settings(self, user_telegram_id: int) -> None:
        if self._user_settings_repository is not None:
            self._user_settings_repository.reset(user_telegram_id)
            self._record_activity_for_user(
                user_telegram_id=user_telegram_id,
                event_type="user.settings.reset",
                action="reset",
                target_type="settings",
                target_id="user_preferences",
            )
            return

        with self._state_lock:
            self._interface_languages.pop(user_telegram_id, None)
            self._progress_preview_enabled.pop(user_telegram_id, None)
        self._record_activity_for_user(
            user_telegram_id=user_telegram_id,
            event_type="user.settings.reset",
            action="reset",
            target_type="settings",
            target_id="user_preferences",
        )

    def list_user_books(
        self,
        *,
        user_telegram_id: int,
        limit: int = 5,
    ) -> list[UserBookSummary]:
        if self._persistent_job_store is None:
            return []

        return [
            self._book_summary_from_job(job)
            for job in self._persistent_job_store.list_jobs_for_user(
                f"telegram:{user_telegram_id}",
                limit=limit,
            )
        ]

    def get_user_queue_summary(
        self,
        *,
        user_telegram_id: int,
        limit: int = 5,
    ) -> UserQueueSummary:
        if self._persistent_job_store is None:
            return UserQueueSummary(total_active=0, queued=0, translating=0, items=())

        active_statuses = {
            PersistentTranslationJobStatus.QUEUED,
            PersistentTranslationJobStatus.TRANSLATING,
            PersistentTranslationJobStatus.ASSEMBLING,
            PersistentTranslationJobStatus.CANCEL_REQUESTED,
        }
        active_jobs = [
            job
            for job in self._persistent_job_store.list_jobs_for_user(
                f"telegram:{user_telegram_id}",
                limit=100,
            )
            if job.status in active_statuses
        ]
        queued = sum(
            1
            for job in active_jobs
            if job.status is PersistentTranslationJobStatus.QUEUED
        )
        translating = len(active_jobs) - queued
        return UserQueueSummary(
            total_active=len(active_jobs),
            queued=queued,
            translating=translating,
            items=tuple(
                self._book_summary_from_job(job) for job in active_jobs[:limit]
            ),
        )

    def get_user_book_detail(
        self,
        *,
        user_telegram_id: int,
        job_id: str,
    ) -> UserBookSummary | None:
        if self._persistent_job_store is None:
            return None

        job = self._persistent_job_store.get_job(job_id)
        if job is None or job.user_id != f"telegram:{user_telegram_id}":
            return None

        return self._book_summary_from_job(
            job,
            progress=self._book_progress_from_job(job),
        )

    def find_pending_translation_duplicate(
        self,
        *,
        user_telegram_id: int,
    ) -> DuplicateUploadMatch | None:
        if self._persistent_job_store is None or self._file_storage is None:
            return None

        with self._state_lock:
            pending = self._pending.get(user_telegram_id)
        if pending is None:
            return None

        pending_source_sha256 = _pending_source_sha256(
            pending=pending,
            storage=self._file_storage,
        )
        if pending_source_sha256 is None:
            return None

        pending_identity = _duplicate_identity_for_pending(
            pending=pending,
            source_sha256=pending_source_sha256,
            max_upload_mb=self._max_upload_mb,
            max_fragment_chars=self._max_fragment_chars,
            document_sandbox=self._document_sandbox,
        )
        if pending_identity is None:
            return None

        for job in self._persistent_job_store.list_jobs_for_user(
            f"telegram:{user_telegram_id}",
            limit=UPLOAD_DUPLICATE_SCAN_LIMIT,
        ):
            job_source_sha256 = _job_source_sha256(
                job=job,
                storage=self._file_storage,
            )
            if job_source_sha256 is None:
                continue
            job_identity = _duplicate_identity_for_job(
                job=job,
                source_sha256=job_source_sha256,
            )
            if job_identity != pending_identity:
                continue
            return self._duplicate_upload_match_from_job(job)

        return None

    def get_user_book_progress(
        self,
        *,
        user_telegram_id: int,
        job_id: str,
    ) -> UserBookProgress | None:
        if self._persistent_job_store is None:
            return None

        job = self._persistent_job_store.get_job(job_id)
        if job is None or job.user_id != f"telegram:{user_telegram_id}":
            return None
        work_units = self._persistent_job_store.list_work_units(job_id)
        total_fragments = len(work_units)
        return UserBookProgress(
            job_id=job.id,
            status=_translation_job_status_from_persistent_status(job.status),
            completed_fragments=sum(
                1
                for unit in work_units
                if unit.status
                in {
                    PersistentWorkUnitStatus.TRANSLATED,
                    PersistentWorkUnitStatus.CACHED,
                }
            ),
            total_fragments=total_fragments,
            estimated_seconds=estimate_translation_seconds(
                total_fragments,
                max_parallel_work_units=self._max_parallel_work_units,
                provider_parallel_capacity=self._provider_parallel_capacity,
            ),
        )

    def get_user_book_translation_job(
        self,
        *,
        user_telegram_id: int,
        job_id: str,
    ) -> TranslationJob | None:
        if self._persistent_job_store is None:
            return None

        job = self._persistent_job_store.get_job(job_id)
        if job is None:
            return self._admin_deleted_translation_job(
                user_telegram_id=user_telegram_id,
                job_id=job_id,
            )
        if job.user_id != f"telegram:{user_telegram_id}":
            return None
        return self._translation_job_from_persistent_job(
            user_telegram_id=user_telegram_id,
            job=job,
        )

    def _admin_deleted_translation_job(
        self,
        *,
        user_telegram_id: int,
        job_id: str,
    ) -> TranslationJob | None:
        if self._activity_store is None:
            return None
        events = self._activity_store.list_events(job_id=job_id, limit=10)
        deleted_event = next(
            (
                event
                for event in events
                if event.event_type == "translation.admin_deleted"
                and event.channel_user_id == str(user_telegram_id)
            ),
            None,
        )
        if deleted_event is None:
            return None
        metadata = deleted_event.metadata
        return TranslationJob(
            id=job_id,
            document_kind=DocumentKind(str(metadata.get("document_kind") or "txt")),
            user_telegram_id=user_telegram_id,
            file_name=str(metadata.get("file_name") or "deleted translation"),
            content=b"",
            source_language=str(metadata.get("source_language") or "auto"),
            target_language=str(metadata.get("target_language") or "unknown"),
            status=TranslationJobStatus.DELETED,
            error_message=str(
                metadata.get("notification_message")
                or "Translation was deleted by an admin."
            ),
        )

    def resume_user_book(
        self,
        *,
        user_telegram_id: int,
        job_id: str,
    ) -> UserBookSummary | None:
        if self._persistent_job_store is None:
            return None

        job = self._persistent_job_store.get_job(job_id)
        if job is None or job.user_id != f"telegram:{user_telegram_id}":
            return None
        if not self._persistent_job_can_resume(job):
            return self._book_summary_from_job(job)

        return self._book_summary_from_job(
            self._persistent_job_store.resume_job(job_id)
        )

    def resume_user_book_translation(
        self,
        *,
        user_telegram_id: int,
        job_id: str,
        translator: TextTranslator,
        progress_callback: Callable[[TranslationProgress], None] | None = None,
    ) -> TranslationJob | None:
        self._assert_beta_access_allows(user_telegram_id)
        self._assert_security_cooldown_allows(user_telegram_id)
        if self._persistent_job_store is None or self._file_storage is None:
            return None

        job = self._persistent_job_store.get_job(job_id)
        if job is None or job.user_id != f"telegram:{user_telegram_id}":
            return None
        if not self._persistent_job_can_resume(job):
            return None
        upload_safety_id = self._upload_safety_id_for_accepted_source(
            job.source_object_key
        )
        policy_payload = _translation_policy_payload(job.translation_policy)

        document_kind = DocumentKind(job.document_kind)
        source_content = (
            self._file_storage.get_bytes(job.source_object_key)
            if self._file_storage.exists(job.source_object_key)
            else b""
        )
        pending = PendingTranslation(
            user_telegram_id=user_telegram_id,
            file_name=job.file_name,
            content=source_content,
            source_language=job.source_language,
            target_language=job.target_language,
            price_usd=0.0,
            fragment_count=len(self._persistent_job_store.list_work_units(job_id)),
            source_object_key=job.source_object_key,
            upload_safety_id=upload_safety_id,
            translation_mode=(
                str(policy_payload.get("translation_mode"))
                if policy_payload.get("translation_mode")
                else None
            ),
            glossary_mode=(
                str(policy_payload.get("glossary_mode"))
                if policy_payload.get("glossary_mode")
                else GLOSSARY_MODE_WITHOUT
            ),
        )
        resumed = self._persistent_job_store.resume_job(job_id)
        work_units = self._persistent_job_store.list_work_units(job_id)
        total_fragments = len(work_units)
        allowed_source_object_keys = _allowed_persistent_work_unit_source_keys(
            work_units=work_units,
            require_upload_scan=self._requires_ledger_backed_upload_gate(),
        )
        if self._defer_persistent_jobs_to_worker:
            self._record_activity_for_user(
                user_telegram_id=user_telegram_id,
                event_type="translation.queued",
                action="queued",
                target_type="document",
                target_id=pending.file_name,
                job_id=resumed.id,
                metadata={
                    "file_name": pending.file_name,
                    "document_kind": document_kind.value,
                    "source_language": pending.source_language,
                    "target_language": pending.target_language,
                    "fragment_count": total_fragments,
                    "persistent": True,
                    "resumed": True,
                },
            )
            return _queued_translation_job(
                pending=pending,
                document_kind=document_kind,
                job_id=resumed.id,
            )

        run_logger = self._start_translation_run_logger(
            pending=pending,
            document_kind=document_kind,
            job_id=resumed.id,
            translator=translator,
            adapter_version=resumed.adapter_version,
            prompt_version=resumed.prompt_version,
            total_fragment_count=total_fragments,
        )
        if run_logger is not None:
            run_logger.record_event(
                "job_resumed",
                {
                    "job_id": resumed.id,
                    "fragment_count": total_fragments,
                    "source_object_key": resumed.source_object_key,
                },
            )

        security_limiter = SecurityEventLimiter(self._security_threshold_policy)
        progress_with_logging = _progress_callback_with_run_logging(
            run_logger=run_logger,
            progress_callback=progress_callback,
            translator=translator,
            security_limiter=security_limiter,
        )
        glossary_runtime_hook = self._glossary_runtime_hook_for_pending(
            pending=pending,
            document_kind=document_kind,
        )
        glossary_adapter_metadata_callback = _glossary_adapter_metadata_callback(
            run_logger,
        )
        cancellation_token = CancellationToken()
        self._set_active_translation(
            user_telegram_id=user_telegram_id,
            cancellation_token=cancellation_token,
            job_id=resumed.id,
            total_fragments=total_fragments,
        )
        try:
            if self._use_scheduler_runner:
                return self._run_scheduler_backed_persistent_translation(
                    document_kind=document_kind,
                    pending=pending,
                    translator=translator,
                    progress_callback=self._track_active_progress(
                        user_telegram_id=user_telegram_id,
                        progress_callback=progress_with_logging,
                    ),
                    cancellation_token=cancellation_token,
                    job_id=resumed.id,
                    total_fragments=total_fragments,
                    run_logger=run_logger,
                    security_limiter=security_limiter,
                    allowed_source_object_keys=allowed_source_object_keys,
                    glossary_runtime_hook=glossary_runtime_hook,
                    glossary_adapter_metadata_callback=glossary_adapter_metadata_callback,
                )

            return self._run_parallel_persistent_translation(
                document_kind=document_kind,
                pending=pending,
                translator=translator,
                progress_callback=self._track_active_progress(
                    user_telegram_id=user_telegram_id,
                    progress_callback=progress_with_logging,
                ),
                cancellation_token=cancellation_token,
                job_id=resumed.id,
                total_fragments=total_fragments,
                run_logger=run_logger,
                security_limiter=security_limiter,
                allowed_source_object_keys=allowed_source_object_keys,
                glossary_runtime_hook=glossary_runtime_hook,
                glossary_adapter_metadata_callback=glossary_adapter_metadata_callback,
            )
        except Exception as error:
            logger.exception(
                "Resumed translation job failed: job_id=%s user_telegram_id=%s",
                job_id,
                user_telegram_id,
            )
            if isinstance(error, SecurityThresholdExceeded):
                self._record_security_threshold_for_user(
                    user_telegram_id=user_telegram_id,
                    run_logger=run_logger,
                )
            else:
                self._persistent_job_store.mark_job_interrupted(job_id)
            failed_job = _failed_translation_job(
                pending=pending,
                document_kind=document_kind,
                error_message=str(error),
                job_id=job_id,
            )
            _finish_run_logger(
                run_logger,
                status=failed_job.status.value,
                result_file_name=failed_job.result_file_name,
                error_message=failed_job.error_message,
            )
            return failed_job
        finally:
            with self._state_lock:
                self._active_cancellations.pop(user_telegram_id, None)

    def get_latest_user_book_result(
        self,
        *,
        user_telegram_id: int,
    ) -> UserBookResult | None:
        if self._persistent_job_store is None or self._file_storage is None:
            return None

        for job in self._persistent_job_store.list_jobs_for_user(
            f"telegram:{user_telegram_id}",
            limit=10,
        ):
            result = self._book_result_from_object_key(job)
            if result is not None:
                return result

        return None

    def get_user_book_result(
        self,
        *,
        user_telegram_id: int,
        job_id: str,
    ) -> UserBookResult | None:
        if self._persistent_job_store is None or self._file_storage is None:
            return None

        job = self._persistent_job_store.get_job(job_id)
        if job is None or job.user_id != f"telegram:{user_telegram_id}":
            return None

        return self._book_result_from_object_key(job)

    def begin_automatic_result_delivery(self, job: TranslationJob) -> bool:
        key = _automatic_result_delivery_key(job)
        if key is None:
            return False

        with self._state_lock:
            if (
                key in self._automatic_result_delivered_keys
                or key in self._automatic_result_delivery_in_flight
            ):
                return False
            self._automatic_result_delivery_in_flight.add(key)
            return True

    def finish_automatic_result_delivery(
        self,
        job: TranslationJob,
        *,
        delivered: bool,
    ) -> None:
        key = _automatic_result_delivery_key(job)
        if key is None:
            return

        with self._state_lock:
            self._automatic_result_delivery_in_flight.discard(key)
            if delivered:
                self._automatic_result_delivered_keys.add(key)

    def delete_user_book(
        self,
        *,
        user_telegram_id: int,
        job_id: str,
    ) -> bool:
        if self._persistent_job_store is None:
            return False

        job = self._persistent_job_store.get_job(job_id)
        if job is None or job.user_id != f"telegram:{user_telegram_id}":
            return False

        with self._state_lock:
            token = self._active_cancellations.get(user_telegram_id)
        if token is not None:
            token.cancel()

        object_keys = {
            key
            for key in (
                job.source_object_key,
                job.partial_object_key,
                job.final_object_key,
            )
            if key
        }
        object_keys.update(
            unit.source_object_key
            for unit in self._persistent_job_store.list_work_units(job_id)
            if unit.source_object_key
        )

        deleted = self._persistent_job_store.delete_job(job_id)
        if not deleted:
            return False

        if self._translation_run_log_root is not None:
            finish_running_translation_runs_for_job(
                self._translation_run_log_root,
                job_id=job_id,
                status="cancelled",
                error_message="Book deleted by user.",
            )

        if self._file_storage is not None:
            for object_key in object_keys:
                self._file_storage.delete(object_key)
        return True

    def cancel_user_book(
        self,
        *,
        user_telegram_id: int,
        job_id: str,
    ) -> bool:
        if self._persistent_job_store is None:
            return False

        job = self._persistent_job_store.get_job(job_id)
        if job is None or job.user_id != f"telegram:{user_telegram_id}":
            return False
        if not _can_cancel_persistent_job(job.status.value):
            return False

        if self._persistent_job_has_active_units(job.id):
            self._persistent_job_store.request_cancel_job(job.id)
            return True

        cancelled_job = self._cancel_persistent_job_with_partial_if_available(
            job=job,
            user_telegram_id=user_telegram_id,
        )
        if self._translation_run_log_root is not None:
            finish_running_translation_runs_for_job(
                self._translation_run_log_root,
                job_id=job_id,
                status="cancelled",
                result_file_name=(
                    cancelled_job.result_file_name
                    if cancelled_job is not None
                    else None
                ),
                error_message="Book cancelled by user.",
            )
        return True

    def _book_result_from_object_key(self, job) -> UserBookResult | None:
        if self._file_storage is None:
            return None

        object_key = job.final_object_key or job.partial_object_key
        if object_key is None or not self._file_storage.exists(object_key):
            return None

        metadata = self._file_storage.get_metadata(object_key)
        return UserBookResult(
            job_id=job.id,
            file_name=metadata.file_name,
            content=self._file_storage.get_bytes(object_key),
            content_type=metadata.content_type,
        )

    def _translation_job_from_persistent_job(
        self,
        *,
        user_telegram_id: int,
        job,
    ) -> TranslationJob:
        source_content = b""
        if (
            self._file_storage is not None
            and job.source_object_key
            and self._file_storage.exists(job.source_object_key)
        ):
            source_content = self._file_storage.get_bytes(job.source_object_key)
        result = self._book_result_from_object_key(job)
        return TranslationJob(
            id=job.id,
            document_kind=DocumentKind(job.document_kind),
            user_telegram_id=user_telegram_id,
            file_name=job.file_name,
            content=source_content,
            source_language=job.source_language,
            target_language=job.target_language,
            status=_translation_job_status_from_persistent_status(job.status),
            result_file_name=result.file_name if result is not None else None,
            result_content=result.content if result is not None else None,
        )

    def _book_summary_from_job(
        self,
        job,
        *,
        progress: UserBookProgress | None = None,
    ) -> UserBookSummary:
        progress_percent = None
        if progress is not None and progress.total_fragments > 0:
            progress_percent = min(
                100,
                round(
                    progress.completed_fragments
                    / max(progress.total_fragments, 1)
                    * 100
                ),
            )
        return UserBookSummary(
            job_id=job.id,
            file_name=job.file_name,
            document_kind=job.document_kind,
            source_language=job.source_language,
            target_language=job.target_language,
            status=job.status.value,
            has_result=bool(job.final_object_key or job.partial_object_key),
            has_partial_result=bool(
                job.partial_object_key and not job.final_object_key
            ),
            can_resume=self._persistent_job_can_resume(job),
            can_cancel=_can_cancel_persistent_job(job.status.value),
            created_at=job.created_at.isoformat(timespec="minutes"),
            updated_at=job.updated_at.isoformat(timespec="minutes"),
            progress_completed_fragments=(
                progress.completed_fragments if progress is not None else None
            ),
            progress_total_fragments=(
                progress.total_fragments if progress is not None else None
            ),
            progress_percent=progress_percent,
        )

    def _book_progress_from_job(self, job) -> UserBookProgress | None:
        if self._persistent_job_store is None:
            return None
        if job.status.value not in _MY_BOOK_DETAIL_PROGRESS_STATUSES:
            return None
        work_units = self._persistent_job_store.list_work_units(job.id)
        total_fragments = len(work_units)
        if total_fragments <= 0:
            return None
        completed_fragments = sum(
            1
            for unit in work_units
            if unit.status
            in {
                PersistentWorkUnitStatus.TRANSLATED,
                PersistentWorkUnitStatus.CACHED,
            }
        )
        return UserBookProgress(
            job_id=job.id,
            status=_translation_job_status_from_persistent_status(job.status),
            completed_fragments=min(completed_fragments, total_fragments),
            total_fragments=total_fragments,
            estimated_seconds=estimate_translation_seconds(
                total_fragments,
                max_parallel_work_units=self._max_parallel_work_units,
                provider_parallel_capacity=self._provider_parallel_capacity,
            ),
        )

    def _persistent_job_can_resume(self, job) -> bool:
        if not _can_resume_persistent_job(job.status.value):
            return False
        if (
            self._file_storage is None
            or not job.source_object_key
            or not self._file_storage.exists(job.source_object_key)
        ):
            return False
        try:
            self._upload_safety_id_for_accepted_source(job.source_object_key)
        except DocumentScanRejectedError:
            return False
        return True

    def _duplicate_upload_match_from_job(self, job) -> DuplicateUploadMatch:
        status = job.status.value
        result = self._book_result_from_object_key(job)
        active_statuses = {
            PersistentTranslationJobStatus.QUEUED.value,
            PersistentTranslationJobStatus.TRANSLATING.value,
            PersistentTranslationJobStatus.ASSEMBLING.value,
            PersistentTranslationJobStatus.CANCEL_REQUESTED.value,
        }
        can_translate_again = status not in active_statuses
        return DuplicateUploadMatch(
            job_id=job.id,
            file_name=job.file_name,
            status=status,
            has_result=bool(job.final_object_key or job.partial_object_key),
            can_download_existing=result is not None,
            can_translate_again=can_translate_again,
            can_open_existing=True,
        )

    def cancel_translation(self, user_telegram_id: int) -> bool:
        return self.cancel_translation_with_result(user_telegram_id).cancelled

    def cancel_translation_with_result(
        self,
        user_telegram_id: int,
    ) -> CancelTranslationResult:
        with self._state_lock:
            active = self._active_cancellations.get(user_telegram_id)
            if active is not None:
                active.cancel()
                snapshot = _ActiveTranslationCancellation(
                    token=active.token,
                    user_id=active.user_id,
                    job_id=active.job_id,
                    completed_fragments=active.completed_fragments,
                    total_fragments=active.total_fragments,
                    cancel_requested=True,
                )
        if active is None:
            job = self._cancel_latest_persistent_translation(user_telegram_id)
            return CancelTranslationResult(cancelled=job is not None, job=job)

        if active.job_id is not None and self._persistent_job_store is not None:
            try:
                self._persistent_job_store.request_cancel_job(active.job_id)
            except Exception as error:
                logger.warning(
                    "Unable to mark persistent translation cancel requested: "
                    "job_id=%s error_type=%s",
                    active.job_id,
                    type(error).__name__,
                )
        _print_translation_cancel_requested(snapshot)
        return CancelTranslationResult(cancelled=True)

    def _cancel_latest_persistent_translation(
        self,
        user_telegram_id: int,
    ) -> TranslationJob | None:
        if self._persistent_job_store is None:
            return None

        for job in self._persistent_job_store.list_jobs_for_user(
            f"telegram:{user_telegram_id}",
            limit=10,
        ):
            if _can_cancel_persistent_job(job.status.value):
                if self._persistent_job_has_active_units(job.id):
                    requested_job = self._persistent_job_store.request_cancel_job(
                        job.id
                    )
                    return self._translation_job_from_persistent_job(
                        user_telegram_id=user_telegram_id,
                        job=requested_job,
                    )
                cancelled_job = self._cancel_persistent_job_with_partial_if_available(
                    job=job,
                    user_telegram_id=user_telegram_id,
                )
                if self._translation_run_log_root is not None:
                    finish_running_translation_runs_for_job(
                        self._translation_run_log_root,
                        job_id=job.id,
                        status="cancelled",
                        result_file_name=(
                            cancelled_job.result_file_name
                            if cancelled_job is not None
                            else None
                        ),
                        error_message="Book cancelled by user.",
                    )
                return cancelled_job

        return None

    def _persistent_job_has_active_units(self, job_id: str) -> bool:
        if self._persistent_job_store is None:
            return False
        now = datetime.now(UTC)
        return any(
            unit.status is PersistentWorkUnitStatus.TRANSLATING
            and (
                unit.claim_token is not None
                and (unit.lease_until is None or unit.lease_until > now)
            )
            for unit in self._persistent_job_store.list_work_units(job_id)
        )

    def _cancel_persistent_job_with_partial_if_available(
        self,
        *,
        job,
        user_telegram_id: int,
    ) -> TranslationJob | None:
        assert self._persistent_job_store is not None
        cancelled = self._persistent_job_store.cancel_job(job.id)
        if cancelled.final_object_key or cancelled.partial_object_key:
            return self._translation_job_from_persistent_job(
                user_telegram_id=user_telegram_id,
                job=cancelled,
            )
        if self._file_storage is None:
            return self._translation_job_from_persistent_job(
                user_telegram_id=user_telegram_id,
                job=cancelled,
            )
        if not (
            cancelled.source_object_key
            and self._file_storage.exists(cancelled.source_object_key)
        ):
            return self._translation_job_from_persistent_job(
                user_telegram_id=user_telegram_id,
                job=cancelled,
            )

        if not self._persistent_job_has_partial_units(cancelled.id):
            return self._translation_job_from_persistent_job(
                user_telegram_id=user_telegram_id,
                job=cancelled,
            )

        work_units = self._persistent_job_store.list_work_units(cancelled.id)
        pending = PendingTranslation(
            user_telegram_id=user_telegram_id,
            file_name=cancelled.file_name,
            content=self._file_storage.get_bytes(cancelled.source_object_key),
            source_language=cancelled.source_language,
            target_language=cancelled.target_language,
            price_usd=0,
            fragment_count=len(work_units),
            source_object_key=cancelled.source_object_key,
            rights_confirmed=True,
        )
        return self._build_persistent_result_job_or_fail(
            document_kind=DocumentKind(cancelled.document_kind),
            pending=pending,
            job_id=cancelled.id,
            partial=True,
            status=TranslationJobStatus.CANCELLED,
        )

    def _build_cancelled_persistent_result_if_available(
        self,
        *,
        document_kind: DocumentKind,
        pending: PendingTranslation,
        job_id: str,
        run_logger: TranslationRunLogger | None = None,
    ) -> TranslationJob:
        assert self._persistent_job_store is not None
        if not self._persistent_job_has_partial_units(job_id):
            return TranslationJob(
                id=job_id,
                document_kind=document_kind,
                user_telegram_id=pending.user_telegram_id,
                file_name=pending.file_name,
                content=pending.content,
                source_language=pending.source_language,
                target_language=pending.target_language,
                status=TranslationJobStatus.CANCELLED,
            )
        return self._build_persistent_result_job_or_fail(
            document_kind=document_kind,
            pending=pending,
            job_id=job_id,
            partial=True,
            status=TranslationJobStatus.CANCELLED,
            run_logger=run_logger,
        )

    def _persistent_job_has_partial_units(self, job_id: str) -> bool:
        assert self._persistent_job_store is not None
        return _has_persistent_partial_units(
            self._persistent_job_store.list_work_units(job_id)
        )

    def _cancel_persistent_job_with_partial_if_available(
        self,
        *,
        job,
        user_telegram_id: int,
    ) -> TranslationJob | None:
        assert self._persistent_job_store is not None
        cancelled = self._persistent_job_store.cancel_job(job.id)
        if cancelled.final_object_key or cancelled.partial_object_key:
            return self._translation_job_from_persistent_job(
                user_telegram_id=user_telegram_id,
                job=cancelled,
            )
        if self._file_storage is None:
            return self._translation_job_from_persistent_job(
                user_telegram_id=user_telegram_id,
                job=cancelled,
            )
        if not (
            cancelled.source_object_key
            and self._file_storage.exists(cancelled.source_object_key)
        ):
            return self._translation_job_from_persistent_job(
                user_telegram_id=user_telegram_id,
                job=cancelled,
            )

        if not self._persistent_job_has_partial_units(cancelled.id):
            return self._translation_job_from_persistent_job(
                user_telegram_id=user_telegram_id,
                job=cancelled,
            )

        work_units = self._persistent_job_store.list_work_units(cancelled.id)
        pending = PendingTranslation(
            user_telegram_id=user_telegram_id,
            file_name=cancelled.file_name,
            content=self._file_storage.get_bytes(cancelled.source_object_key),
            source_language=cancelled.source_language,
            target_language=cancelled.target_language,
            price_usd=0,
            fragment_count=len(work_units),
            source_object_key=cancelled.source_object_key,
            rights_confirmed=True,
        )
        return self._build_persistent_result_job_or_fail(
            document_kind=DocumentKind(cancelled.document_kind),
            pending=pending,
            job_id=cancelled.id,
            partial=True,
            status=TranslationJobStatus.CANCELLED,
        )

    def _build_cancelled_persistent_result_if_available(
        self,
        *,
        document_kind: DocumentKind,
        pending: PendingTranslation,
        job_id: str,
        run_logger: TranslationRunLogger | None = None,
    ) -> TranslationJob:
        assert self._persistent_job_store is not None
        if not self._persistent_job_has_partial_units(job_id):
            return TranslationJob(
                id=job_id,
                document_kind=document_kind,
                user_telegram_id=pending.user_telegram_id,
                file_name=pending.file_name,
                content=pending.content,
                source_language=pending.source_language,
                target_language=pending.target_language,
                status=TranslationJobStatus.CANCELLED,
            )
        return self._build_persistent_result_job_or_fail(
            document_kind=document_kind,
            pending=pending,
            job_id=job_id,
            partial=True,
            status=TranslationJobStatus.CANCELLED,
            run_logger=run_logger,
        )

    def _persistent_job_has_partial_units(self, job_id: str) -> bool:
        assert self._persistent_job_store is not None
        return _has_persistent_partial_units(
            self._persistent_job_store.list_work_units(job_id)
        )

    def is_translation_cancelling(self, user_telegram_id: int) -> bool:
        with self._state_lock:
            active = self._active_cancellations.get(user_telegram_id)
            return bool(active and active.cancel_requested)

    def _set_active_translation(
        self,
        *,
        user_telegram_id: int,
        cancellation_token: CancellationToken,
        job_id: str | None = None,
        total_fragments: int = 0,
    ) -> None:
        with self._state_lock:
            self._active_cancellations[user_telegram_id] = (
                _ActiveTranslationCancellation(
                    token=cancellation_token,
                    user_id=f"telegram:{user_telegram_id}",
                    job_id=job_id,
                    total_fragments=total_fragments,
                )
            )

    def _mark_active_translation_job(
        self,
        *,
        user_telegram_id: int,
        job_id: str,
        total_fragments: int,
    ) -> None:
        with self._state_lock:
            active = self._active_cancellations.get(user_telegram_id)
            if active is None:
                return
            active.job_id = job_id
            active.total_fragments = total_fragments

    def _update_active_translation_progress(
        self,
        *,
        user_telegram_id: int,
        completed_fragments: int,
        total_fragments: int,
    ) -> None:
        with self._state_lock:
            active = self._active_cancellations.get(user_telegram_id)
            if active is None:
                return
            active.completed_fragments = completed_fragments
            active.total_fragments = total_fragments

    def _track_active_progress(
        self,
        *,
        user_telegram_id: int,
        progress_callback: Callable[[TranslationProgress], None] | None,
    ) -> Callable[[TranslationProgress], None] | None:
        if progress_callback is None:
            return None

        def report(progress: TranslationProgress) -> None:
            self._update_active_translation_progress(
                user_telegram_id=user_telegram_id,
                completed_fragments=progress.completed_fragments,
                total_fragments=progress.total_fragments,
            )
            progress_callback(progress)

        return report

    def confirm_pending_translation(
        self,
        *,
        user_telegram_id: int,
        translator: TextTranslator,
        progress_callback: Callable[[TranslationProgress], None] | None = None,
    ) -> TranslationJob:
        self._assert_beta_access_allows(user_telegram_id)
        self._assert_security_cooldown_allows(user_telegram_id)
        with self._state_lock:
            pending = self._pending.get(user_telegram_id)
            if pending is None:
                raise ValueError("No pending translation for this user")
            if not pending.rights_confirmed:
                raise RightsConfirmationRequired(
                    "Document rights must be confirmed before translation starts"
                )
            if pending.translation_mode is None:
                raise TranslationModeRequired(
                    "Choose how this document should be translated before "
                    "translation starts"
                )
            if pending.glossary_mode is None:
                pending = replace(
                    pending,
                    glossary_mode=DEFAULT_GLOSSARY_MODE,
                )
                self._pending[user_telegram_id] = pending
            if not pending.preview_accepted:
                raise PreviewAcceptanceRequired(
                    "Review the translation preview before continuing."
                )
            pending = self._pending.pop(user_telegram_id)

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
        self._record_activity_for_user(
            user_telegram_id=user_telegram_id,
            event_type="translation.confirmed",
            action="confirmed",
            target_type="document",
            target_id=pending.file_name,
            metadata={
                "file_name": pending.file_name,
                "document_kind": document_kind.value,
                "source_language": pending.source_language,
                "target_language": pending.target_language,
                "translation_mode": pending.translation_mode,
                "glossary_mode": pending.glossary_mode,
                "fragment_count": pending.fragment_count,
                "rights_confirmation": _rights_confirmation_payload(pending),
            },
        )

        if self._should_use_persistent_document_path(
            document_kind=document_kind,
            pending=pending,
        ):
            cancellation_token = CancellationToken()
            self._set_active_translation(
                user_telegram_id=user_telegram_id,
                cancellation_token=cancellation_token,
                total_fragments=pending.fragment_count,
            )
            try:
                job = self._confirm_persistent_translation(
                    document_kind=document_kind,
                    pending=pending,
                    translator=translator,
                    progress_callback=self._track_active_progress(
                        user_telegram_id=user_telegram_id,
                        progress_callback=progress_callback,
                    ),
                    cancellation_token=cancellation_token,
                )
            except Exception as error:
                logger.exception(
                    "Translation job failed: file_name=%s user_telegram_id=%s",
                    pending.file_name,
                    user_telegram_id,
                )
                if not isinstance(error, SecurityThresholdExceeded):
                    with self._state_lock:
                        self._pending.setdefault(user_telegram_id, pending)
                self._record_activity_for_user(
                    user_telegram_id=user_telegram_id,
                    event_type="translation.failed",
                    action="failed",
                    outcome=(
                        ActivityOutcome.BLOCKED
                        if isinstance(error, SecurityThresholdExceeded)
                        else ActivityOutcome.FAILURE
                    ),
                    target_type="document",
                    target_id=pending.file_name,
                    metadata={
                        "file_name": pending.file_name,
                        "document_kind": document_kind.value,
                        "source_language": pending.source_language,
                        "target_language": pending.target_language,
                        "error_type": error.__class__.__name__,
                        "error_message": str(error),
                    },
                )
                return _failed_translation_job(
                    pending=pending,
                    document_kind=document_kind,
                    error_message=str(error),
                )
            finally:
                with self._state_lock:
                    self._active_cancellations.pop(user_telegram_id, None)

            if (
                job.status is TranslationJobStatus.FAILED
                and not _is_security_threshold_error(job.error_message)
                and job.id not in self._beta_safety_denied_job_ids
            ):
                with self._state_lock:
                    self._pending.setdefault(user_telegram_id, pending)
            self._record_activity_for_user(
                user_telegram_id=user_telegram_id,
                event_type=(
                    "translation.completed"
                    if job.status is TranslationJobStatus.READY
                    else (
                        "translation.cancelled"
                        if job.status is TranslationJobStatus.CANCELLED
                        else (
                            "translation.queued"
                            if job.status is TranslationJobStatus.QUEUED
                            else "translation.failed"
                        )
                    )
                ),
                action=job.status.value,
                outcome=(
                    ActivityOutcome.SUCCESS
                    if job.status
                    in {TranslationJobStatus.READY, TranslationJobStatus.QUEUED}
                    else (
                        ActivityOutcome.IGNORED
                        if job.status is TranslationJobStatus.CANCELLED
                        else ActivityOutcome.FAILURE
                    )
                ),
                target_type="document",
                target_id=pending.file_name,
                job_id=job.id,
                metadata={
                    "file_name": pending.file_name,
                    "document_kind": document_kind.value,
                    "source_language": pending.source_language,
                    "target_language": pending.target_language,
                    "translation_mode": pending.translation_mode,
                    "glossary_mode": pending.glossary_mode,
                    "result_file_name": job.result_file_name,
                    "status": job.status.value,
                    "error_message": job.error_message,
                },
            )
            return job

        queued_job = self._job_repository.create_job(
            document_kind=document_kind,
            user_telegram_id=user_telegram_id,
            file_name=pending.file_name,
            content=pending.content,
            source_language=pending.source_language,
            target_language=pending.target_language,
        )
        run_logger = self._start_translation_run_logger(
            pending=pending,
            document_kind=document_kind,
            job_id=queued_job.id,
            translator=translator,
            total_fragment_count=pending.fragment_count,
        )
        if run_logger is not None:
            run_logger.record_event("job_created", {"job_id": queued_job.id})
        self._record_activity_for_user(
            user_telegram_id=user_telegram_id,
            event_type="translation.started",
            action="started",
            target_type="document",
            target_id=pending.file_name,
            job_id=queued_job.id,
            translation_run_dir=str(run_logger.run_dir) if run_logger else None,
            metadata={
                "file_name": pending.file_name,
                "document_kind": document_kind.value,
                "source_language": pending.source_language,
                "target_language": pending.target_language,
                "translation_mode": pending.translation_mode,
                "glossary_mode": pending.glossary_mode,
                "fragment_count": pending.fragment_count,
            },
        )
        security_limiter = SecurityEventLimiter(self._security_threshold_policy)
        progress_with_logging = _progress_callback_with_run_logging(
            run_logger=run_logger,
            progress_callback=progress_callback,
            translator=translator,
            security_limiter=security_limiter,
        )
        glossary_runtime_hook = self._glossary_runtime_hook_for_pending(
            pending=pending,
            document_kind=document_kind,
        )
        glossary_adapter_metadata_callback = _glossary_adapter_metadata_callback(
            run_logger,
        )
        cancellation_token = CancellationToken()
        self._set_active_translation(
            user_telegram_id=user_telegram_id,
            cancellation_token=cancellation_token,
            job_id=queued_job.id,
            total_fragments=pending.fragment_count,
        )
        try:
            run_translation_job(
                repository=self._job_repository,
                job_id=queued_job.id,
                max_fragment_chars=self._max_fragment_chars,
                translator=translator,
                progress_callback=self._track_active_progress(
                    user_telegram_id=user_telegram_id,
                    progress_callback=progress_with_logging,
                ),
                cancellation_token=cancellation_token,
                translation_cache=self._translation_cache,
                glossary_runtime_hook=glossary_runtime_hook,
                glossary_adapter_metadata_callback=(
                    glossary_adapter_metadata_callback
                ),
            )
        except Exception as error:
            failed_job = self._job_repository.get(queued_job.id)
            if isinstance(error, SecurityThresholdExceeded):
                logger.warning(
                    "Translation stopped by security threshold: "
                    "job_id=%s file_name=%s user_telegram_id=%s reason=%s",
                    failed_job.id,
                    failed_job.file_name,
                    failed_job.user_telegram_id,
                    error,
                )
            else:
                logger.exception(
                    "Translation job failed: "
                    "job_id=%s file_name=%s user_telegram_id=%s",
                    failed_job.id,
                    failed_job.file_name,
                    failed_job.user_telegram_id,
                )
            _record_translator_security_events(
                run_logger,
                translator,
                security_limiter=security_limiter,
                phase="failure",
            )
            if isinstance(error, SecurityThresholdExceeded):
                self._record_security_threshold_for_user(
                    user_telegram_id=user_telegram_id,
                    run_logger=run_logger,
                )
            else:
                with self._state_lock:
                    self._pending.setdefault(user_telegram_id, pending)
            _finish_run_logger(
                run_logger,
                status=failed_job.status.value,
                result_file_name=failed_job.result_file_name,
                error_message=failed_job.error_message,
            )
            self._record_activity_for_user(
                user_telegram_id=user_telegram_id,
                event_type="translation.failed",
                action="failed",
                outcome=(
                    ActivityOutcome.BLOCKED
                    if isinstance(error, SecurityThresholdExceeded)
                    else ActivityOutcome.FAILURE
                ),
                target_type="document",
                target_id=pending.file_name,
                job_id=queued_job.id,
                translation_run_dir=str(run_logger.run_dir) if run_logger else None,
                metadata={
                    "file_name": pending.file_name,
                    "document_kind": document_kind.value,
                    "source_language": pending.source_language,
                    "target_language": pending.target_language,
                    "translation_mode": pending.translation_mode,
                    "glossary_mode": pending.glossary_mode,
                    "error_type": error.__class__.__name__,
                    "error_message": failed_job.error_message,
                },
            )
            return self._job_repository.get(queued_job.id)
        finally:
            with self._state_lock:
                self._active_cancellations.pop(user_telegram_id, None)

        completed_job = self._job_repository.get(queued_job.id)
        _finish_run_logger(
            run_logger,
            status=completed_job.status.value,
            result_file_name=completed_job.result_file_name,
            error_message=completed_job.error_message,
        )
        self._record_activity_for_user(
            user_telegram_id=user_telegram_id,
            event_type=(
                "translation.completed"
                if completed_job.status is TranslationJobStatus.READY
                else "translation.finished"
            ),
            action=completed_job.status.value,
            outcome=(
                ActivityOutcome.SUCCESS
                if completed_job.status is TranslationJobStatus.READY
                else ActivityOutcome.FAILURE
            ),
            target_type="document",
            target_id=pending.file_name,
            job_id=completed_job.id,
            translation_run_dir=str(run_logger.run_dir) if run_logger else None,
            metadata={
                "file_name": pending.file_name,
                "document_kind": document_kind.value,
                "source_language": pending.source_language,
                "target_language": pending.target_language,
                "translation_mode": pending.translation_mode,
                "glossary_mode": pending.glossary_mode,
                "result_file_name": completed_job.result_file_name,
                "status": completed_job.status.value,
                "error_message": completed_job.error_message,
            },
        )
        return completed_job

    def _start_translation_run_logger(
        self,
        *,
        pending: PendingTranslation,
        document_kind: DocumentKind,
        job_id: str,
        translator: TextTranslator,
        adapter_version: str | None = None,
        prompt_version: str | None = None,
        total_fragment_count: int | None = None,
        prepared_glossary_package: dict | None = None,
    ) -> TranslationRunLogger | None:
        if self._translation_run_log_root is None:
            return None
        resolved_adapter_version = (
            adapter_version or _adapter_version_for_document_kind(document_kind)
        )
        resolved_prompt_version = prompt_version or "plain-v1"
        translation_policy = _translation_policy_snapshot_for_pending(
            pending=pending,
            document_kind=document_kind,
            document_sandbox=self._document_sandbox,
            prepared_glossary_package=prepared_glossary_package,
        )
        return TranslationRunLogger.start(
            root=self._translation_run_log_root,
            metadata=TranslationRunMetadata(
                job_id=job_id,
                order_id=None,
                user_id=f"telegram:{pending.user_telegram_id}",
                file_name=pending.file_name,
                document_kind=document_kind.value,
                source_language=pending.source_language,
                target_language=pending.target_language,
                translator_model=_translator_model(translator),
                prompt_version=resolved_prompt_version,
                adapter_version=resolved_adapter_version,
                detected_source_language=pending.source_language_display,
                total_fragment_count=total_fragment_count,
                translation_policy=translation_policy,
                translation_stack=_translation_stack_snapshot(
                    translation_policy=translation_policy,
                    document_kind=document_kind,
                    adapter_version=resolved_adapter_version,
                    prompt_version=resolved_prompt_version,
                ),
            ),
        )

    def _should_use_persistent_document_path(
        self,
        *,
        document_kind: DocumentKind,
        pending: PendingTranslation,
    ) -> bool:
        return (
            document_kind in {DocumentKind.TXT, DocumentKind.DOCX, DocumentKind.EPUB}
            and self._file_storage is not None
            and self._persistent_job_store is not None
            and pending.source_object_key is not None
        )

    def _reserve_beta_safety_for_persistent_job(
        self,
        *,
        job_id: str,
        user_id: str,
        estimated_input_tokens: int,
    ):
        if self._beta_safety_guard is None:
            return None
        return self._beta_safety_guard.reserve_job(
            job_id=job_id,
            user_id=user_id,
            estimate=_estimate_persistent_job_cost(
                estimated_input_tokens=estimated_input_tokens,
                rates=self._beta_safety_rates,
            ),
        )

    def _glossary_runtime_hook_for_pending(
        self,
        *,
        pending: PendingTranslation,
        document_kind: DocumentKind,
    ) -> GlossaryRuntimeAdapterHookConfig | None:
        if pending.glossary_mode != GLOSSARY_MODE_WITH:
            return None
        if self._glossary_runtime_hook_builder is None:
            return _fallback_glossary_runtime_hook()
        try:
            hook = self._glossary_runtime_hook_builder(pending, document_kind)
        except Exception:
            logger.exception(
                "Glossary runtime hook builder failed safely: "
                "file_name=%s document_kind=%s user_telegram_id=%s",
                pending.file_name,
                document_kind.value,
                pending.user_telegram_id,
            )
            return _fallback_glossary_runtime_hook()
        return hook or _fallback_glossary_runtime_hook()

    def _prepared_glossary_package_attachment_for_pending(
        self,
        *,
        pending: PendingTranslation,
        document_kind: DocumentKind,
    ) -> _PreparedGlossaryPackageAttachmentResult:
        if pending.glossary_mode != GLOSSARY_MODE_WITH:
            return _prepared_glossary_package_attachment_result(
                status="disabled",
                reason_codes=("prepared_glossary_package_attachment_not_requested",),
            )
        request = PreparedGlossaryPackageAttachmentRequest(
            user_telegram_id=pending.user_telegram_id,
            file_name=pending.file_name,
            document_kind=document_kind.value,
            source_language=pending.source_language,
            target_language=pending.target_language,
            translation_mode=pending.translation_mode,
            glossary_mode=pending.glossary_mode,
            source_sha256=hashlib.sha256(pending.content).hexdigest(),
        )

        resolver_result: _PreparedGlossaryPackageAttachmentResult | None = None
        if self._prepared_glossary_package_resolver is not None:
            try:
                attachment = self._prepared_glossary_package_resolver(request)
            except Exception:
                logger.exception(
                    "Prepared glossary package resolver failed safely: "
                    "file_name=%s document_kind=%s user_telegram_id=%s",
                    pending.file_name,
                    document_kind.value,
                    pending.user_telegram_id,
                )
                resolver_result = _prepared_glossary_package_attachment_result(
                    status="skipped",
                    reason_codes=(
                        "prepared_glossary_package_attachment_resolver_failed",
                    ),
                    request=request,
                    source="resolver",
                )
            else:
                resolver_result = _prepared_glossary_package_attachment_result_from(
                    attachment,
                    request=request,
                    source="resolver",
                    missing_reason_code="prepared_glossary_package_attachment_missing",
                )
            if resolver_result.payload is not None:
                return resolver_result

        if self._prepared_glossary_package_prep_resolver is None:
            return resolver_result or _prepared_glossary_package_attachment_result(
                status="skipped",
                reason_codes=("prepared_glossary_package_attachment_disabled",),
                request=request,
                source="resolver",
            )

        prep_request = PreparedGlossaryPackagePrepRequest(
            user_telegram_id=request.user_telegram_id,
            file_name=request.file_name,
            document_kind=request.document_kind,
            source_language=request.source_language,
            target_language=request.target_language,
            translation_mode=request.translation_mode,
            glossary_mode=request.glossary_mode,
            source_sha256=request.source_sha256,
            content=pending.content,
        )
        prep_beta_safety = (
            self._reserve_beta_safety_for_prepared_glossary_prep(
                pending=pending,
                request=request,
            )
        )
        if not prep_beta_safety.allowed:
            return _prepared_glossary_package_attachment_result(
                status="skipped",
                reason_codes=tuple(
                    prep_beta_safety.metadata.get("reason_codes", ())
                )
                or ("prepared_glossary_prep_beta_safety_blocked",),
                request=request,
                source="prep",
                extra_metadata={
                    "glossary_prep_beta_safety": prep_beta_safety.metadata,
                },
            )
        try:
            prep_attachment = self._prepared_glossary_package_prep_resolver(
                prep_request
            )
        except Exception:
            logger.exception(
                "Prepared glossary package prep resolver failed safely: "
                "file_name=%s document_kind=%s user_telegram_id=%s",
                pending.file_name,
                document_kind.value,
                pending.user_telegram_id,
            )
            prep_result = _prepared_glossary_package_attachment_result(
                status="skipped",
                reason_codes=("prepared_glossary_package_prep_resolver_failed",),
                request=request,
                source="prep",
                fail_closed=True,
                extra_metadata={
                    "glossary_prep_beta_safety": (
                        self._consume_prepared_glossary_prep_beta_safety(
                            reservation=prep_beta_safety,
                            attachment=None,
                        )
                    )
                },
            )
        else:
            prep_beta_safety_metadata = (
                self._consume_prepared_glossary_prep_beta_safety(
                    reservation=prep_beta_safety,
                    attachment=prep_attachment,
                )
            )
            prep_result = _prepared_glossary_package_attachment_result_from(
                prep_attachment,
                request=request,
                source="prep",
                missing_reason_code="prepared_glossary_package_prep_missing",
                disabled_reason_code="prepared_glossary_package_prep_disabled",
                fail_closed_when_not_ready=True,
                extra_metadata={
                    "glossary_prep_beta_safety": prep_beta_safety_metadata,
                },
            )
        return prep_result

    def _reserve_beta_safety_for_prepared_glossary_prep(
        self,
        *,
        pending: PendingTranslation,
        request: PreparedGlossaryPackageAttachmentRequest,
    ) -> _PreparedGlossaryPrepBetaSafetyReservation:
        estimate = _estimate_prepared_glossary_prep_cost(
            content=pending.content,
            rates=self._beta_safety_rates,
        )
        job_id = _prepared_glossary_prep_beta_safety_job_id(
            pending=pending,
            request=request,
        )
        user_id = f"telegram:{pending.user_telegram_id}"
        metadata = _prepared_glossary_prep_beta_safety_metadata(
            status="not_reserved",
            reason_codes=(),
            job_id=job_id,
            estimate=estimate,
            provider_reported_usage_status="Unknown",
        )
        if self._beta_safety_guard is None:
            return _PreparedGlossaryPrepBetaSafetyReservation(
                allowed=False,
                job_id=job_id,
                user_id=user_id,
                estimate=estimate,
                metadata={
                    **metadata,
                    "reservation_status": "blocked",
                    "reason_codes": [
                        "prepared_glossary_prep_beta_safety_guard_missing"
                    ],
                },
            )

        start_decision = self._beta_safety_guard.can_start_new_work()
        if not start_decision.allowed:
            return _PreparedGlossaryPrepBetaSafetyReservation(
                allowed=False,
                job_id=job_id,
                user_id=user_id,
                estimate=estimate,
                metadata={
                    **metadata,
                    "reservation_status": "blocked",
                    "reason_codes": _beta_safety_reason_codes(
                        "prepared_glossary_prep_beta_safety_start_blocked",
                        start_decision.reason_code,
                    ),
                    "beta_safety_reason_code": start_decision.reason_code,
                },
            )

        reservation_decision = self._beta_safety_guard.reserve_job(
            job_id=job_id,
            user_id=user_id,
            estimate=estimate,
        )
        if not reservation_decision.allowed:
            return _PreparedGlossaryPrepBetaSafetyReservation(
                allowed=False,
                job_id=job_id,
                user_id=user_id,
                estimate=estimate,
                metadata={
                    **metadata,
                    "reservation_status": "blocked",
                    "reason_codes": _beta_safety_reason_codes(
                        "prepared_glossary_prep_beta_safety_reservation_denied",
                        reservation_decision.reason_code,
                    ),
                    "beta_safety_reason_code": reservation_decision.reason_code,
                },
            )

        return _PreparedGlossaryPrepBetaSafetyReservation(
            allowed=True,
            job_id=job_id,
            user_id=user_id,
            estimate=estimate,
            metadata={
                **metadata,
                "reservation_status": "reserved",
                "reason_codes": [],
                "beta_safety_reason_code": reservation_decision.reason_code,
            },
        )

    def _consume_prepared_glossary_prep_beta_safety(
        self,
        *,
        reservation: _PreparedGlossaryPrepBetaSafetyReservation,
        attachment: PreparedGlossaryPackageAttachment | None,
    ) -> dict[str, object]:
        metadata = dict(reservation.metadata)
        if (
            self._beta_safety_guard is None
            or not reservation.allowed
            or reservation.job_id is None
            or reservation.user_id is None
            or reservation.estimate is None
        ):
            return metadata

        provider_usage = _prepared_glossary_provider_usage_from_attachment(
            attachment,
        )
        if provider_usage is None:
            prompt_tokens = reservation.estimate.prompt_tokens
            completion_tokens = reservation.estimate.completion_tokens
            usage_source = "estimate_when_provider_usage_unknown"
            provider_reported_usage_status = "Unknown"
            metadata["reason_codes"] = list(
                _unique_texts(
                    tuple(metadata.get("reason_codes", ()))
                    + (
                        "prepared_glossary_prep_provider_usage_unknown_"
                        "estimate_accounted",
                    )
                )
            )
        else:
            prompt_tokens, completion_tokens = provider_usage
            usage_source = "provider_reported"
            provider_reported_usage_status = "reported"

        try:
            self._beta_safety_guard.record_work_unit_usage(
                job_id=reservation.job_id,
                user_id=reservation.user_id,
                work_unit_id=f"{reservation.job_id}:prepared_glossary_prep",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            self._mark_beta_safety_reservation_consumed(job_id=reservation.job_id)
        except Exception:
            logger.exception(
                "Prepared glossary prep beta safety usage recording failed safely: "
                "job_id=%s user_id=%s",
                reservation.job_id,
                reservation.user_id,
            )
            metadata["reservation_status"] = "usage_record_failed"
            metadata["reason_codes"] = list(
                _unique_texts(
                    tuple(metadata.get("reason_codes", ()))
                    + ("prepared_glossary_prep_beta_safety_usage_record_failed",)
                )
            )
            return metadata

        metadata.update(
            {
                "reservation_status": "consumed",
                "accounting_usage_source": usage_source,
                "accounted_prompt_tokens": prompt_tokens,
                "accounted_completion_tokens": completion_tokens,
                "provider_reported_usage_status": provider_reported_usage_status,
            }
        )
        return metadata

    def _release_beta_safety_reservation(self, *, job_id: str, reason: str) -> None:
        if self._beta_safety_guard is None:
            return
        self._beta_safety_guard.release_job(job_id=job_id, reason=reason)

    def _mark_beta_safety_reservation_consumed(self, *, job_id: str) -> None:
        if self._beta_safety_guard is None:
            return
        mark_job_consumed = getattr(
            self._beta_safety_guard,
            "mark_job_consumed",
            None,
        )
        if mark_job_consumed is not None:
            mark_job_consumed(job_id=job_id)

    def _beta_safety_usage_completed_callback(
        self,
    ) -> Callable[[PersistentWorkUnit], None] | None:
        if self._beta_safety_guard is None:
            return None
        assert self._persistent_job_store is not None

        def record_usage(work_unit: PersistentWorkUnit) -> None:
            assert self._persistent_job_store is not None
            job = self._persistent_job_store.get_job(work_unit.job_id)
            if job is None:
                raise ValueError(f"Work unit job does not exist: {work_unit.job_id}")
            assert self._beta_safety_guard is not None
            self._beta_safety_guard.record_work_unit_usage(
                job_id=work_unit.job_id,
                user_id=job.user_id,
                work_unit_id=work_unit.id,
                prompt_tokens=work_unit.prompt_tokens,
                completion_tokens=work_unit.completion_tokens,
            )

        return record_usage

    def _reserve_beta_safety_for_preview(
        self,
        *,
        preview_id: str,
        user_id: str,
        estimate: JobCostEstimate,
    ) -> str | None:
        with self._state_lock:
            if preview_id in self._generated_preview_ids:
                raise DuplicatePreviewError(
                    "Preview has already been generated for this document."
                )

        if self._beta_safety_guard is not None:
            start_decision = self._beta_safety_guard.can_start_new_work()
            if not start_decision.allowed:
                raise PreviewTranslationError(start_decision.safe_message)
            reservation_decision = self._beta_safety_guard.reserve_job(
                job_id=preview_id,
                user_id=user_id,
                estimate=estimate,
            )
            if not reservation_decision.allowed:
                raise PreviewTranslationError(reservation_decision.safe_message)
            reason_code: str | None = reservation_decision.reason_code
        else:
            reason_code = None

        with self._state_lock:
            if preview_id in self._generated_preview_ids:
                if self._beta_safety_guard is not None:
                    self._beta_safety_guard.release_job(
                        job_id=preview_id,
                        reason="duplicate_preview",
                    )
                raise DuplicatePreviewError(
                    "Preview has already been generated for this document."
                )
            self._generated_preview_ids.add(preview_id)
        return reason_code

    def _record_beta_safety_preview_usage(
        self,
        *,
        preview_id: str,
        user_id: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        if self._beta_safety_guard is None:
            return
        self._beta_safety_guard.record_work_unit_usage(
            job_id=preview_id,
            user_id=user_id,
            work_unit_id=f"{preview_id}:preview",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def _confirm_persistent_translation(
        self,
        *,
        document_kind: DocumentKind,
        pending: PendingTranslation,
        translator: TextTranslator,
        progress_callback: Callable[[TranslationProgress], None] | None,
        cancellation_token: CancellationToken,
    ) -> TranslationJob:
        assert self._file_storage is not None
        assert self._persistent_job_store is not None
        assert pending.source_object_key is not None
        self._assert_worker_access_allowed(
            upload_safety_id=pending.upload_safety_id,
            source_object_key=pending.source_object_key,
        )
        prepared_glossary_package_attachment = (
            self._prepared_glossary_package_attachment_for_pending(
                pending=pending,
                document_kind=document_kind,
            )
        )
        if prepared_glossary_package_attachment.fail_closed:
            return _failed_translation_job(
                pending=pending,
                document_kind=document_kind,
                error_message=_prepared_glossary_package_fail_closed_message(
                    prepared_glossary_package_attachment.metadata
                ),
            )

        plan = _create_persistent_job_plan(
            document_kind=document_kind,
            store=self._persistent_job_store,
            storage=self._file_storage,
            pending=pending,
            max_fragment_chars=self._max_fragment_chars,
            prepared_glossary_package=prepared_glossary_package_attachment.payload,
        )
        total_fragments = len(plan.work_units)
        allowed_source_object_keys = _allowed_persistent_work_unit_source_keys(
            work_units=plan.work_units,
            require_upload_scan=self._requires_ledger_backed_upload_gate(),
        )
        reservation_decision = self._reserve_beta_safety_for_persistent_job(
            job_id=plan.job.id,
            user_id=plan.job.user_id,
            estimated_input_tokens=plan.estimated_input_tokens,
        )
        if reservation_decision is not None and not reservation_decision.allowed:
            self._beta_safety_denied_job_ids.add(plan.job.id)
            self._persistent_job_store.mark_job_interrupted(plan.job.id)
            return _failed_translation_job(
                pending=pending,
                document_kind=document_kind,
                error_message=reservation_decision.safe_message,
                job_id=plan.job.id,
            )
        self._mark_active_translation_job(
            user_telegram_id=pending.user_telegram_id,
            job_id=plan.job.id,
            total_fragments=total_fragments,
        )
        run_logger = self._start_translation_run_logger(
            pending=pending,
            document_kind=document_kind,
            job_id=plan.job.id,
            translator=translator,
            adapter_version=plan.job.adapter_version,
            prompt_version=plan.job.prompt_version,
            total_fragment_count=total_fragments,
            prepared_glossary_package=prepared_glossary_package_attachment.payload,
        )
        if run_logger is not None:
            if pending.glossary_mode == GLOSSARY_MODE_WITH:
                run_logger.record_event(
                    "prepared_glossary_package_attachment",
                    prepared_glossary_package_attachment.metadata,
                )
            run_logger.record_event(
                "job_created",
                {
                    "job_id": plan.job.id,
                    "fragment_count": total_fragments,
                    "source_object_key": plan.job.source_object_key,
                    "translation_mode": pending.translation_mode,
                    "glossary_mode": pending.glossary_mode,
                },
            )
        glossary_runtime_hook = self._glossary_runtime_hook_for_pending(
            pending=pending,
            document_kind=document_kind,
        )
        glossary_adapter_metadata_callback = _glossary_adapter_metadata_callback(
            run_logger,
        )
        if pending.upload_safety_id is not None:
            self._record_upload_safety_activity(
                user_telegram_id=pending.user_telegram_id,
                upload_safety_id=pending.upload_safety_id,
                job_id=plan.job.id,
                translation_run_dir=str(run_logger.run_dir) if run_logger else None,
            )
        if self._defer_persistent_jobs_to_worker:
            if run_logger is not None:
                run_logger.record_event(
                    "job_queued",
                    {
                        "job_id": plan.job.id,
                        "fragment_count": total_fragments,
                        "persistent": True,
                        "worker_mode": "external",
                    },
                )
            self._record_activity_for_user(
                user_telegram_id=pending.user_telegram_id,
                event_type="translation.queued",
                action="queued",
                target_type="document",
                target_id=pending.file_name,
                job_id=plan.job.id,
                translation_run_dir=str(run_logger.run_dir) if run_logger else None,
                metadata={
                    "file_name": pending.file_name,
                    "document_kind": document_kind.value,
                    "source_language": pending.source_language,
                    "target_language": pending.target_language,
                    "translation_mode": pending.translation_mode,
                    "glossary_mode": pending.glossary_mode,
                    "fragment_count": total_fragments,
                    "persistent": True,
                },
            )
            return _queued_translation_job(
                pending=pending,
                document_kind=document_kind,
                job_id=plan.job.id,
            )
        self._record_activity_for_user(
            user_telegram_id=pending.user_telegram_id,
            event_type="translation.started",
            action="started",
            target_type="document",
            target_id=pending.file_name,
            job_id=plan.job.id,
            translation_run_dir=str(run_logger.run_dir) if run_logger else None,
            metadata={
                "file_name": pending.file_name,
                "document_kind": document_kind.value,
                "source_language": pending.source_language,
                "target_language": pending.target_language,
                "translation_mode": pending.translation_mode,
                "glossary_mode": pending.glossary_mode,
                "fragment_count": total_fragments,
                "persistent": True,
            },
        )
        security_limiter = SecurityEventLimiter(self._security_threshold_policy)
        progress_with_logging = _progress_callback_with_run_logging(
            run_logger=run_logger,
            progress_callback=progress_callback,
            translator=translator,
            security_limiter=security_limiter,
        )

        if self._use_scheduler_runner:
            return self._run_scheduler_backed_persistent_translation(
                document_kind=document_kind,
                pending=pending,
                translator=translator,
                progress_callback=progress_with_logging,
                cancellation_token=cancellation_token,
                job_id=plan.job.id,
                total_fragments=total_fragments,
                run_logger=run_logger,
                security_limiter=security_limiter,
                allowed_source_object_keys=allowed_source_object_keys,
                glossary_runtime_hook=glossary_runtime_hook,
                glossary_adapter_metadata_callback=glossary_adapter_metadata_callback,
            )

        if self._max_parallel_work_units > 1:
            return self._run_parallel_persistent_translation(
                document_kind=document_kind,
                pending=pending,
                translator=translator,
                progress_callback=progress_with_logging,
                cancellation_token=cancellation_token,
                job_id=plan.job.id,
                total_fragments=total_fragments,
                run_logger=run_logger,
                security_limiter=security_limiter,
                allowed_source_object_keys=allowed_source_object_keys,
                glossary_runtime_hook=glossary_runtime_hook,
                glossary_adapter_metadata_callback=(
                    glossary_adapter_metadata_callback
                ),
            )

        while True:
            if cancellation_token.is_cancelled:
                self._persistent_job_store.cancel_job(plan.job.id)
                self._release_beta_safety_reservation(
                    job_id=plan.job.id,
                    reason="cancelled",
                )
                cancelled_job = self._build_cancelled_persistent_result_if_available(
                    document_kind=document_kind,
                    pending=pending,
                    job_id=plan.job.id,
                    run_logger=run_logger,
                )
                _finish_run_logger(
                    run_logger,
                    status=cancelled_job.status.value,
                    result_file_name=cancelled_job.result_file_name,
                    error_message=cancelled_job.error_message,
                )
                return cancelled_job

            started_at = time.monotonic()
            completed_unit = run_next_stored_text_work_unit(
                store=self._persistent_job_store,
                storage=self._file_storage,
                job_id=plan.job.id,
                worker_id=f"telegram:{pending.user_telegram_id}",
                translator=translator,
                work_unit_started_callback=_work_unit_started_callback(
                    run_logger=run_logger,
                    total_units=total_fragments,
                ),
                usage_completed_callback=self._beta_safety_usage_completed_callback(),
                allowed_source_object_keys=allowed_source_object_keys,
                provider_io_diagnostic_sink=_provider_io_diagnostic_sink(
                    self._translation_run_log_root,
                    job_id=plan.job.id,
                ),
                glossary_runtime_hook=glossary_runtime_hook,
                glossary_adapter_metadata_callback=glossary_adapter_metadata_callback,
            )
            if completed_unit is None:
                break
            elapsed_seconds = time.monotonic() - started_at
            if completed_unit.status is PersistentWorkUnitStatus.FAILED:
                _record_translator_security_events(
                    run_logger,
                    translator,
                    security_limiter=security_limiter,
                    phase="work_unit_failure",
                    work_unit_id=completed_unit.id,
                )
                failed_job = _failed_translation_job(
                    pending=pending,
                    document_kind=document_kind,
                    error_message=completed_unit.last_error or "Translation failed",
                    job_id=plan.job.id,
                )
                self._release_beta_safety_reservation(
                    job_id=plan.job.id,
                    reason="failed_before_completion",
                )
                _finish_run_logger(
                    run_logger,
                    status=failed_job.status.value,
                    result_file_name=failed_job.result_file_name,
                    error_message=failed_job.error_message,
                )
                return failed_job

            if progress_with_logging is not None:
                try:
                    progress_with_logging(
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
                except SecurityThresholdExceeded as error:
                    return self._fail_persistent_translation_after_security_threshold(
                        document_kind=document_kind,
                        pending=pending,
                        job_id=plan.job.id,
                        run_logger=run_logger,
                        error=error,
                    )

        has_unassembled_units = (
            count_unassembled_work_units(
                self._persistent_job_store.list_work_units(plan.job.id)
            )
            > 0
        )
        result_job = self._build_persistent_result_job_or_fail(
            document_kind=document_kind,
            pending=pending,
            job_id=plan.job.id,
            partial=has_unassembled_units,
            status=(
                TranslationJobStatus.PARTIAL
                if has_unassembled_units
                else TranslationJobStatus.READY
            ),
            run_logger=run_logger,
        )
        if result_job.status is TranslationJobStatus.PARTIAL:
            self._release_beta_safety_reservation(
                job_id=plan.job.id,
                reason="failed_before_completion",
            )
        elif result_job.status is TranslationJobStatus.READY:
            self._mark_beta_safety_reservation_consumed(job_id=plan.job.id)
        _finish_run_logger(
            run_logger,
            status=result_job.status.value,
            result_file_name=result_job.result_file_name,
            error_message=result_job.error_message,
        )
        return result_job

    def _run_scheduler_backed_persistent_translation(
        self,
        *,
        document_kind: DocumentKind,
        pending: PendingTranslation,
        translator: TextTranslator,
        progress_callback: Callable[[TranslationProgress], None] | None,
        cancellation_token: CancellationToken,
        job_id: str,
        total_fragments: int,
        run_logger: TranslationRunLogger | None,
        security_limiter: SecurityEventLimiter,
        allowed_source_object_keys: frozenset[str] | None,
        glossary_runtime_hook: GlossaryRuntimeAdapterHookConfig | None = None,
        glossary_adapter_metadata_callback: Callable[[dict[str, object]], None]
        | None = None,
    ) -> TranslationJob:
        assert self._file_storage is not None
        assert self._persistent_job_store is not None
        from translator_service.scheduler import SchedulerLimits
        from translator_service.scheduler_runner import run_scheduler_once

        while True:
            if cancellation_token.is_cancelled:
                self._persistent_job_store.cancel_job(job_id)
                break
            summary = run_scheduler_once(
                store=self._persistent_job_store,
                storage=self._file_storage,
                worker_id=f"telegram:{pending.user_telegram_id}",
                translator=translator,
                limits=SchedulerLimits(
                    max_active_units_per_job=self._max_parallel_work_units,
                ),
                lease_seconds=300,
                max_parallel_units=min(
                    self._max_parallel_work_units,
                    self._provider_parallel_capacity,
                ),
                work_unit_started_callback=_work_unit_started_callback(
                    run_logger=run_logger,
                    total_units=total_fragments,
                ),
                beta_safety_guard=self._beta_safety_guard,
                translation_run_log_root=self._translation_run_log_root,
                allowed_source_object_keys=allowed_source_object_keys,
                glossary_runtime_hook=glossary_runtime_hook,
                glossary_adapter_metadata_callback=glossary_adapter_metadata_callback,
            )
            try:
                _record_translator_security_events(
                    run_logger,
                    translator,
                    security_limiter=security_limiter,
                    phase="scheduler",
                    completed_units=summary.completed_units,
                    total_units=total_fragments,
                )
            except SecurityThresholdExceeded as error:
                return self._fail_persistent_translation_after_security_threshold(
                    document_kind=document_kind,
                    pending=pending,
                    job_id=job_id,
                    run_logger=run_logger,
                    error=error,
                )
            if summary.completed_units == 0 and summary.failed_units == 0:
                break

        persisted = self._persistent_job_store.get_job(job_id)
        if persisted is None:
            raise ValueError(f"Persistent translation job does not exist: {job_id}")

        partial = persisted.status is not PersistentTranslationJobStatus.READY
        if cancellation_token.is_cancelled:
            result_status = TranslationJobStatus.CANCELLED
        elif partial:
            result_status = TranslationJobStatus.PARTIAL
        else:
            result_status = TranslationJobStatus.READY

        if result_status is TranslationJobStatus.CANCELLED:
            result_job = self._build_cancelled_persistent_result_if_available(
                document_kind=document_kind,
                pending=pending,
                job_id=job_id,
                run_logger=run_logger,
            )
        else:
            result_job = self._build_persistent_result_job_or_fail(
                document_kind=document_kind,
                pending=pending,
                job_id=job_id,
                partial=partial,
                status=result_status,
                run_logger=run_logger,
            )
        if result_job.status is TranslationJobStatus.CANCELLED:
            self._release_beta_safety_reservation(
                job_id=job_id,
                reason="cancelled",
            )
        elif result_job.status is not TranslationJobStatus.READY:
            self._release_beta_safety_reservation(
                job_id=job_id,
                reason="failed_before_completion",
            )
        _finish_run_logger(
            run_logger,
            status=result_job.status.value,
            result_file_name=result_job.result_file_name,
            error_message=result_job.error_message,
        )
        return result_job

    def _run_parallel_persistent_translation(
        self,
        *,
        document_kind: DocumentKind,
        pending: PendingTranslation,
        translator: TextTranslator,
        progress_callback: Callable[[TranslationProgress], None] | None,
        cancellation_token: CancellationToken,
        job_id: str,
        total_fragments: int,
        run_logger: TranslationRunLogger | None,
        security_limiter: SecurityEventLimiter,
        allowed_source_object_keys: frozenset[str] | None,
        glossary_runtime_hook: GlossaryRuntimeAdapterHookConfig | None = None,
        glossary_adapter_metadata_callback: Callable[[dict[str, object]], None]
        | None = None,
    ) -> TranslationJob:
        assert self._file_storage is not None
        assert self._persistent_job_store is not None

        def report_progress(progress) -> None:
            completed_unit = progress.completed_work_unit
            if progress_callback is None:
                return
            progress_callback(
                TranslationProgress(
                    completed_fragments=progress.completed_units,
                    total_fragments=progress.total_units,
                    source_text=_persistent_unit_source_text(
                        storage=self._file_storage,
                        source_object_key=completed_unit.source_object_key,
                    ),
                    translated_text=completed_unit.translated_text or "",
                    elapsed_seconds=progress.elapsed_seconds,
                    prompt_tokens=completed_unit.prompt_tokens,
                    completion_tokens=completed_unit.completion_tokens,
                    total_tokens=(
                        completed_unit.prompt_tokens + completed_unit.completion_tokens
                    ),
                    prompt_cache_hit_tokens=completed_unit.cache_hit_tokens,
                    prompt_cache_miss_tokens=completed_unit.cache_miss_tokens,
                )
            )

        try:
            summary = run_stored_text_job_parallel_until_idle(
                store=self._persistent_job_store,
                storage=self._file_storage,
                job_id=job_id,
                worker_id=f"telegram:{pending.user_telegram_id}",
                translator=translator,
                max_parallel_units=self._max_parallel_work_units,
                progress_callback=report_progress,
                work_unit_started_callback=_work_unit_started_callback(
                    run_logger=run_logger,
                    total_units=total_fragments,
                ),
                should_stop=lambda: cancellation_token.is_cancelled,
                usage_completed_callback=self._beta_safety_usage_completed_callback(),
                allowed_source_object_keys=allowed_source_object_keys,
                provider_io_diagnostic_sink=_provider_io_diagnostic_sink(
                    self._translation_run_log_root,
                    job_id=job_id,
                ),
                glossary_runtime_hook=glossary_runtime_hook,
                glossary_adapter_metadata_callback=glossary_adapter_metadata_callback,
            )
        except SecurityThresholdExceeded as error:
            return self._fail_persistent_translation_after_security_threshold(
                document_kind=document_kind,
                pending=pending,
                job_id=job_id,
                run_logger=run_logger,
                error=error,
            )

        if cancellation_token.is_cancelled:
            self._persistent_job_store.cancel_job(job_id)
            self._release_beta_safety_reservation(
                job_id=job_id,
                reason="cancelled",
            )
            cancelled_job = self._build_cancelled_persistent_result_if_available(
                document_kind=document_kind,
                pending=pending,
                job_id=job_id,
                run_logger=run_logger,
            )
            _finish_run_logger(
                run_logger,
                status=cancelled_job.status.value,
                result_file_name=cancelled_job.result_file_name,
                error_message=cancelled_job.error_message,
            )
            return cancelled_job

        if summary.failed_work_unit_id is not None:
            _record_translator_security_events(
                run_logger,
                translator,
                security_limiter=security_limiter,
                phase="work_unit_failure",
                work_unit_id=summary.failed_work_unit_id,
            )
            failed_unit = next(
                (
                    unit
                    for unit in self._persistent_job_store.list_work_units(job_id)
                    if unit.id == summary.failed_work_unit_id
                ),
                None,
            )
            failed_job = _failed_translation_job(
                pending=pending,
                document_kind=document_kind,
                error_message=(
                    failed_unit.last_error
                    if failed_unit is not None and failed_unit.last_error
                    else "Translation failed"
                ),
                job_id=job_id,
            )
            self._release_beta_safety_reservation(
                job_id=job_id,
                reason="failed_before_completion",
            )
            _finish_run_logger(
                run_logger,
                status=failed_job.status.value,
                result_file_name=failed_job.result_file_name,
                error_message=failed_job.error_message,
            )
            return failed_job

        has_unassembled_units = (
            count_unassembled_work_units(
                self._persistent_job_store.list_work_units(job_id)
            )
            > 0
        )
        result_job = self._build_persistent_result_job_or_fail(
            document_kind=document_kind,
            pending=pending,
            job_id=job_id,
            partial=has_unassembled_units,
            status=(
                TranslationJobStatus.PARTIAL
                if has_unassembled_units
                else TranslationJobStatus.READY
            ),
            run_logger=run_logger,
        )
        if result_job.status is TranslationJobStatus.PARTIAL:
            self._release_beta_safety_reservation(
                job_id=job_id,
                reason="failed_before_completion",
            )
        elif result_job.status is TranslationJobStatus.READY:
            self._mark_beta_safety_reservation_consumed(job_id=job_id)
        _finish_run_logger(
            run_logger,
            status=result_job.status.value,
            result_file_name=result_job.result_file_name,
            error_message=result_job.error_message,
        )
        return result_job

    def _fail_persistent_translation_after_security_threshold(
        self,
        *,
        document_kind: DocumentKind,
        pending: PendingTranslation,
        job_id: str,
        run_logger: TranslationRunLogger | None,
        error: SecurityThresholdExceeded,
    ) -> TranslationJob:
        assert self._persistent_job_store is not None
        self._record_security_threshold_for_user(
            user_telegram_id=pending.user_telegram_id,
            run_logger=run_logger,
        )
        self._persistent_job_store.mark_job_interrupted(job_id)
        self._release_beta_safety_reservation(
            job_id=job_id,
            reason="security_threshold",
        )
        failed_job = _failed_translation_job(
            pending=pending,
            document_kind=document_kind,
            error_message=str(error),
            job_id=job_id,
        )
        _finish_run_logger(
            run_logger,
            status=failed_job.status.value,
            result_file_name=failed_job.result_file_name,
            error_message=failed_job.error_message,
        )
        return failed_job

    def _build_persistent_result_job_or_fail(
        self,
        *,
        document_kind: DocumentKind,
        pending: PendingTranslation,
        job_id: str,
        partial: bool,
        status: TranslationJobStatus,
        run_logger: TranslationRunLogger | None = None,
    ) -> TranslationJob:
        assert self._persistent_job_store is not None
        try:
            return self._build_persistent_result_job(
                document_kind=document_kind,
                pending=pending,
                job_id=job_id,
                partial=partial,
                status=status,
            )
        except TextExtractionError as error:
            if run_logger is not None:
                run_logger.record_security_event(
                    "document_assembly_failed",
                    {
                        "document_format": document_kind.value,
                        "phase": "assembly",
                        "error_type": error.__class__.__name__,
                    },
                )
            logger.exception(
                "Persistent document assembly failed: job_id=%s file_name=%s",
                job_id,
                pending.file_name,
            )
            self._persistent_job_store.mark_job_interrupted(job_id)
            self._release_beta_safety_reservation(
                job_id=job_id,
                reason="assembly_failed",
            )
            return _failed_translation_job(
                pending=pending,
                document_kind=document_kind,
                error_message=f"Document assembly failed: {error}",
                job_id=job_id,
            )

    def _build_persistent_result_job(
        self,
        *,
        document_kind: DocumentKind,
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
            extension=document_kind.value,
            is_partial=partial,
        )
        stored = _assemble_persistent_result(
            document_kind=document_kind,
            store=self._persistent_job_store,
            storage=self._file_storage,
            job_id=job_id,
            file_name=result_file_name,
            partial=partial,
            document_sandbox=self._document_sandbox,
        )
        return TranslationJob(
            id=job_id,
            document_kind=document_kind,
            user_telegram_id=pending.user_telegram_id,
            file_name=pending.file_name,
            content=pending.content,
            source_language=pending.source_language,
            target_language=pending.target_language,
            status=status,
            result_file_name=result_file_name,
            result_content=self._file_storage.get_bytes(stored.object_key),
        )


def _create_persistent_job_plan(
    *,
    document_kind: DocumentKind,
    store: PersistentJobStore,
    storage: LocalObjectStorage,
    pending: PendingTranslation,
    max_fragment_chars: int,
    prepared_glossary_package: dict | None = None,
):
    common = {
        "store": store,
        "storage": storage,
        "order_id": f"prototype-order-{pending.user_telegram_id}-{int(time.time())}",
        "user_id": f"telegram:{pending.user_telegram_id}",
        "source_object_key": pending.source_object_key,
        "file_name": pending.file_name,
        "source_language": pending.source_language,
        "target_language": pending.target_language,
        "max_fragment_chars": max_fragment_chars,
        "rights_confirmation": _rights_confirmation_payload(pending),
        "translation_mode": pending.translation_mode,
        "glossary_mode": pending.glossary_mode,
        "prepared_glossary_package": prepared_glossary_package,
        "upload_safety_id": pending.upload_safety_id,
    }
    if document_kind is DocumentKind.TXT:
        return create_persistent_txt_job_plan(**common)
    if document_kind is DocumentKind.DOCX:
        return create_persistent_docx_job_plan(**common)
    if document_kind is DocumentKind.EPUB:
        return create_persistent_epub_job_plan(**common)
    raise ValueError(f"Unsupported persistent document kind: {document_kind}")


def _allowed_persistent_work_unit_source_keys(
    *,
    work_units,
    require_upload_scan: bool,
) -> frozenset[str] | None:
    if not require_upload_scan:
        return None
    keys = frozenset(
        unit.source_object_key for unit in work_units if unit.source_object_key
    )
    if len(keys) != len(work_units):
        raise DocumentScanRejectedError()
    return keys


def _preview_adapter_plan(
    *,
    document_format: DocumentFormat,
    content: bytes,
    max_fragment_chars: int,
    document_sandbox: DocumentSandbox | None,
    translation_mode: str | None,
) -> FormatAdapterPlan:
    if document_sandbox is not None:
        return document_sandbox.plan_translation(
            document_format=document_format,
            content=content,
            max_fragment_chars=max_fragment_chars,
            translation_mode=translation_mode,
        )
    if document_format is DocumentFormat.TXT:
        return plan_txt_translation(
            content=content,
            max_fragment_chars=max_fragment_chars,
        )
    if document_format is DocumentFormat.DOCX:
        return plan_docx_translation(
            content=content,
            max_fragment_chars=max_fragment_chars,
            translation_mode=translation_mode,
        )
    if document_format is DocumentFormat.EPUB:
        return plan_epub_translation(
            content=content,
            max_fragment_chars=max_fragment_chars,
        )
    raise ValueError("Preview is available for TXT, DOCX, and EPUB only")


def _select_preview_blocks(
    plan: FormatAdapterPlan,
) -> tuple[tuple[int, FormatTextBlock], ...]:
    selected: list[tuple[int, FormatTextBlock]] = []
    for unit in plan.units:
        for block in unit.blocks:
            if not _is_meaningful_preview_block(block):
                continue
            selected.append((unit.sequence, block))
            if len(selected) >= PREVIEW_CANDIDATE_MAX_BLOCKS:
                return tuple(selected)
    return tuple(selected)


def _preview_translation_mode_metadata(
    *,
    selected: tuple[tuple[int, FormatTextBlock], ...],
    translation_mode: str | None,
) -> dict[str, object]:
    if translation_mode is None:
        return {}

    metadata: dict[str, object] = {"translation_mode": translation_mode}
    docx_profiles = {
        dict(block.metadata).get("docx_translation_mode_profile")
        for _sequence, block in selected
    }
    docx_profiles.discard(None)
    if len(docx_profiles) == 1:
        metadata["docx_translation_mode_profile"] = next(iter(docx_profiles))
    return metadata


def _is_meaningful_preview_block(block: FormatTextBlock) -> bool:
    text = block.text.strip()
    if not text:
        return False
    if block.source_block_id.startswith("epub:aux:"):
        return False
    if block.kind is not TextBlockKind.PLAIN:
        return False
    if _looks_like_preview_boilerplate(text):
        return False
    if block.source_block_id.startswith("epub:") and _looks_like_epub_front_matter(
        text
    ):
        return False
    return _letter_count(text) >= 12


def _bounded_preview_text(texts: list[str], *, max_chars: int) -> str:
    parts: list[str] = []
    remaining = max_chars
    for text in texts:
        normalized = text.strip()
        if not normalized or remaining <= 0:
            continue
        separator = "\n\n" if parts else ""
        available = remaining - len(separator)
        if available <= 0:
            break
        if len(normalized) > available:
            normalized = normalized[:available].rstrip()
        parts.append(f"{separator}{normalized}")
        remaining = max_chars - sum(len(part) for part in parts)
    return "".join(parts).strip()


def _letter_count(text: str) -> int:
    return sum(1 for character in text if character.isalpha())


def _looks_like_preview_boilerplate(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    if normalized in {
        "contents",
        "table of contents",
        "оглавление",
        "содержание",
        "зміст",
        "title page",
    }:
        return True
    if len(normalized) <= 80 and normalized.startswith(
        (
            "chapter ",
            "part ",
            "глава ",
            "часть ",
            "розділ ",
            "частина ",
        )
    ):
        return True
    return False


def _looks_like_epub_front_matter(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    is_short_metadata_line = len(normalized) <= 180
    if is_short_metadata_line and re.search(
        r"\b(?:https?://|www\.)\S+", normalized
    ):
        return True
    if is_short_metadata_line and re.search(
        r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", normalized
    ):
        return True
    if re.search(r"\bisbn(?:-1[03])?\b", normalized):
        return True
    if (
        "©" in text
        or "copyright" in normalized
        or "all rights reserved" in normalized
    ):
        return True
    if is_short_metadata_line and re.search(
        r"\b\d{1,6}\s+[\w .'-]+"
        r"(?:street|st\.|road|rd\.|avenue|ave\.|lane|drive|dr\.|"
        r"boulevard|blvd\.|square|sq\.)\b",
        normalized,
    ):
        return True
    if len(normalized) <= 100 and (
        normalized.endswith(" press")
        or " published by " in f" {normalized} "
        or " publisher" in normalized
        or " publishing" in normalized
        or " imprint" in normalized
    ):
        return True
    return False


def _progress_callback_with_run_logging(
    *,
    run_logger: TranslationRunLogger | None,
    progress_callback: Callable[[TranslationProgress], None] | None,
    translator: TextTranslator | None = None,
    security_limiter: SecurityEventLimiter | None = None,
) -> Callable[[TranslationProgress], None] | None:
    if run_logger is None and progress_callback is None and security_limiter is None:
        return progress_callback

    def report(progress: TranslationProgress) -> None:
        if run_logger is not None:
            run_logger.record_fragment(_fragment_log_from_progress(progress))
        if translator is not None:
            _record_translator_security_events(
                run_logger,
                translator,
                security_limiter=security_limiter,
                phase="translation",
                fragment_sequence=progress.completed_fragments,
                total_units=progress.total_fragments,
            )
        if progress_callback is not None:
            progress_callback(progress)

    return report


def _work_unit_started_callback(
    *,
    run_logger: TranslationRunLogger | None,
    total_units: int,
) -> Callable[[PersistentWorkUnit], None] | None:
    if run_logger is None:
        return None

    def record(work_unit: PersistentWorkUnit) -> None:
        run_logger.record_event(
            "work_unit_started",
            {
                "sequence": work_unit.sequence,
                "work_unit_id": work_unit.id,
                "total_units": total_units,
                "source_block_ids": list(work_unit.source_block_ids),
            },
        )

    return record


def _glossary_adapter_metadata_callback(
    run_logger: TranslationRunLogger | None,
) -> Callable[[dict[str, object]], None] | None:
    if run_logger is None:
        return None

    def record(payload: dict[str, object]) -> None:
        run_logger.record_event(
            "glossary_runtime_adapter",
            _safe_glossary_adapter_metadata(payload),
        )

    return record


_GLOSSARY_METADATA_RAW_KEYS = {
    "api_key",
    "auth",
    "auth_material",
    "prompt",
    "prompt_body",
    "provider_response",
    "raw",
    "raw_prompt",
    "raw_response",
    "raw_source",
    "source_text",
    "source_texts",
    "translated_text",
    "translation",
}


def _safe_glossary_adapter_metadata(value):
    if isinstance(value, dict):
        safe_payload = {}
        for key, item in value.items():
            if str(key).lower() in _GLOSSARY_METADATA_RAW_KEYS:
                safe_payload[key] = "[redacted]"
                continue
            safe_payload[key] = _safe_glossary_adapter_metadata(item)
        return safe_payload
    if isinstance(value, list):
        return [_safe_glossary_adapter_metadata(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_safe_glossary_adapter_metadata(item) for item in value)
    return value


def _fallback_glossary_runtime_hook() -> GlossaryRuntimeAdapterHookConfig:
    return build_fallback_glossary_runtime_hook()


def _print_translation_cancel_requested(active: _ActiveTranslationCancellation) -> None:
    total = active.total_fragments if active.total_fragments > 0 else "?"
    message = (
        "CANCEL REQUESTED "
        f"user={active.user_id} "
        f"job={active.job_id or '-'} "
        f"completed={active.completed_fragments}/{total} "
        "stopping=active_requests"
    )
    logger.info(message)
    print(message, flush=True)


def _record_translator_security_events(
    run_logger: TranslationRunLogger | None,
    translator: TextTranslator,
    security_limiter: SecurityEventLimiter | None = None,
    **context,
) -> None:
    events = _consume_translator_security_events(translator)
    if run_logger is None and security_limiter is None:
        return
    for event in events:
        payload = {
            **context,
            **event["payload"],
        }
        if run_logger is not None:
            run_logger.record_security_event(event["event_type"], payload)
        if security_limiter is None:
            continue
        try:
            security_limiter.observe(
                {"event_type": event["event_type"], "payload": payload}
            )
        except SecurityThresholdExceeded as error:
            _record_security_threshold_exceeded(run_logger, error)
            raise


def _record_security_threshold_exceeded(
    run_logger: TranslationRunLogger | None,
    error: SecurityThresholdExceeded,
) -> None:
    if run_logger is None:
        return
    run_logger.record_security_event(
        "security_threshold_exceeded",
        {
            "blocked_security_event_type": error.event_type,
            "reason": error.reason,
            "count": error.count,
            "limit": error.limit,
        },
    )


def _consume_translator_security_events(
    translator: TextTranslator,
) -> tuple[dict, ...]:
    consume = getattr(translator, "consume_security_events", None)
    if callable(consume):
        raw_events = consume()
    else:
        raw_events = getattr(translator, "last_security_events", ())
        if hasattr(translator, "_last_security_events"):
            try:
                translator._last_security_events.value = ()
            except Exception:
                pass
    events = []
    for raw_event in raw_events or ():
        event = normalize_security_event(raw_event)
        if event is not None:
            events.append(event)
    return tuple(events)


def _fragment_log_from_progress(
    progress: TranslationProgress,
) -> TranslationFragmentLog:
    return TranslationFragmentLog(
        sequence=progress.completed_fragments,
        source_text=progress.source_text,
        translated_text=progress.translated_text,
        status="translated" if progress.success else "failed",
        elapsed_seconds=progress.elapsed_seconds,
        prompt_tokens=progress.prompt_tokens,
        completion_tokens=progress.completion_tokens,
        total_tokens=progress.total_tokens,
        prompt_cache_hit_tokens=progress.prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=progress.prompt_cache_miss_tokens,
    )


def _translation_policy_snapshot_for_pending(
    *,
    pending: PendingTranslation,
    document_kind: DocumentKind,
    document_sandbox: DocumentSandbox | None = None,
    prepared_glossary_package: dict | None = None,
) -> str | None:
    try:
        source_text = _extract_policy_source_text(
            content=pending.content,
            document_kind=document_kind,
            document_sandbox=document_sandbox,
        )
    except TextExtractionError as error:
        logger.warning(
            "Could not build translation policy snapshot: file_name=%s reason=%s",
            pending.file_name,
            error,
        )
        return None

    translation_mode_profile = _translation_mode_profile_for_document_kind(
        pending.translation_mode,
        document_kind=document_kind.value,
    )
    translation_context = None
    if translation_mode_profile is not None:
        translation_context = _translation_context_with_mode_profile(
            translation_context,
            translation_mode_profile,
        )
    policy = build_translation_policy(
        text=source_text,
        source_language=pending.source_language,
        target_language=pending.target_language,
        translation_context=translation_context,
    )
    return _translation_policy_with_rights_confirmation(
        translation_policy_signature(policy),
        rights_confirmation=_rights_confirmation_payload(pending),
        translation_mode=pending.translation_mode,
        glossary_mode=pending.glossary_mode,
        prepared_glossary_package=prepared_glossary_package,
        translation_mode_profile=translation_mode_profile.signature
        if translation_mode_profile is not None
        else None,
        upload_safety=_upload_safety_run_policy_marker(pending),
    )


def _translation_stack_snapshot(
    *,
    translation_policy: str | None,
    document_kind: DocumentKind,
    adapter_version: str,
    prompt_version: str,
) -> dict:
    policy = _translation_policy_payload(translation_policy)
    target_language_policy = _policy_value(policy, "target_language_policy")
    source_pair_policy = _policy_value(policy, "source_pair_policy")
    quality_track = _policy_value(policy, "russian_quality_track")
    return {
        "schema_version": "translation-stack-v1",
        "adapter": {
            "document_kind": document_kind.value,
            "name": document_kind.value,
            "version": adapter_version,
        },
        "prompt": {
            "run_prompt_version": prompt_version,
            "prompt_policy_version": _policy_value(policy, "prompt_policy_version"),
            "protection_policy_version": _policy_value(
                policy,
                "protection_policy_version",
            ),
            "adapter_policy_version": _policy_value(policy, "adapter_policy_version"),
            "output_contract": _policy_value(policy, "output_contract"),
        },
        "language_profiles": {
            "target_language": _target_language_profile_snapshot(
                target_language_policy
            ),
            "source_pair": _source_pair_profile_snapshot(source_pair_policy),
            "quality_track": _quality_track_snapshot(quality_track),
        },
        "text": {
            "source_language": _policy_value(policy, "source_language"),
            "target_language": _policy_value(policy, "target_language"),
            "text_type": _policy_value(policy, "text_type"),
            "prompt_tier": _policy_value(policy, "prompt_tier"),
        },
    }


def _translation_policy_payload(translation_policy: str | None) -> dict:
    if not translation_policy:
        return {}
    try:
        payload = json.loads(translation_policy)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _estimate_prepared_glossary_prep_cost(
    *,
    content: bytes,
    rates: BetaSafetyRates,
) -> JobCostEstimate:
    source_packet_tokens = min(
        _PREPARED_GLOSSARY_PREP_MAX_SOURCE_PACKET_TOKENS,
        max(1, math.ceil(len(content) / 4)),
    )
    prompt_tokens = (
        _PREPARED_GLOSSARY_PREP_BASE_PROMPT_TOKENS + source_packet_tokens
    )
    completion_tokens = _PREPARED_GLOSSARY_PREP_COMPLETION_TOKENS
    return JobCostEstimate(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=estimate_cost_usd(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            rates=rates,
        ),
    )


def _prepared_glossary_prep_beta_safety_job_id(
    *,
    pending: PendingTranslation,
    request: PreparedGlossaryPackageAttachmentRequest,
) -> str:
    attempt_ref = (
        pending.attempt_id
        or pending.preview_id
        or request.source_sha256[:12]
    )
    return (
        "glossary-prep:"
        f"{_safe_identifier(attempt_ref)}:"
        f"{request.source_sha256[:12]}:"
        f"{_safe_identifier(request.document_kind)}:"
        f"{_safe_identifier(request.target_language)}"
    )


def _safe_identifier(value: object) -> str:
    text = str(value or "Unknown")
    safe = re.sub(r"[^A-Za-z0-9_.:-]+", "_", text).strip("_")
    return safe[:80] or "Unknown"


def _prepared_glossary_prep_beta_safety_metadata(
    *,
    status: str,
    reason_codes: tuple[str, ...],
    job_id: str,
    estimate: JobCostEstimate,
    provider_reported_usage_status: str,
) -> dict[str, object]:
    return {
        "schema_version": PREPARED_GLOSSARY_PREP_BETA_SAFETY_SCHEMA_VERSION,
        "metadata_only": True,
        "raw_payload_included": False,
        "reservation_status": status,
        "reason_codes": list(_unique_texts(reason_codes)),
        "reservation_job_id": job_id,
        "estimated_prompt_tokens": estimate.prompt_tokens,
        "estimated_completion_tokens": estimate.completion_tokens,
        "estimated_cost_usd": estimate.estimated_cost_usd,
        "provider_reported_usage_status": provider_reported_usage_status,
        "accounting_usage_source": "Unknown",
    }


def _beta_safety_reason_codes(
    base_reason_code: str,
    beta_safety_reason_code: str,
) -> list[str]:
    return list(
        _unique_texts(
            (
                base_reason_code,
                f"beta_safety_{beta_safety_reason_code or 'Unknown'}",
            )
        )
    )


def _prepared_glossary_provider_usage_from_attachment(
    attachment: PreparedGlossaryPackageAttachment | None,
) -> tuple[int, int] | None:
    if attachment is None or not isinstance(attachment.metadata, Mapping):
        return None
    usage = _mapping_value(attachment.metadata, "provider_usage")
    if usage is None:
        usage = _mapping_value(attachment.metadata, "usage")
    if usage is None:
        usage = _mapping_value(attachment.metadata, "provider_reported_usage")
    if usage is None:
        return None
    prompt_tokens = _int_usage_value(
        usage,
        ("prompt_tokens", "input_tokens", "provider_reported_prompt_tokens"),
    )
    completion_tokens = _int_usage_value(
        usage,
        (
            "completion_tokens",
            "output_tokens",
            "provider_reported_completion_tokens",
        ),
    )
    total_tokens = _int_usage_value(
        usage,
        ("total_tokens", "provider_reported_total_tokens"),
    )
    if completion_tokens is None and prompt_tokens is not None and total_tokens:
        completion_tokens = max(0, total_tokens - prompt_tokens)
    if prompt_tokens is None or completion_tokens is None:
        return None
    return prompt_tokens, completion_tokens


def _mapping_value(
    value: Mapping[str, object],
    key: str,
) -> Mapping[str, object] | None:
    raw = value.get(key)
    return raw if isinstance(raw, Mapping) else None


def _int_usage_value(
    usage: Mapping[str, object],
    keys: tuple[str, ...],
) -> int | None:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return max(0, value)
        if isinstance(value, float) and value.is_integer():
            return max(0, int(value))
    return None


def _prepared_glossary_package_attachment_result(
    *,
    status: str,
    reason_codes: tuple[str, ...],
    request: PreparedGlossaryPackageAttachmentRequest | None = None,
    source: str = "resolver",
    fail_closed: bool = False,
    extra_metadata: Mapping[str, object] | None = None,
) -> _PreparedGlossaryPackageAttachmentResult:
    metadata: dict[str, object] = {
        "schema_version": "prepared-glossary-package-attachment-v1",
        "attachment_status": status,
        "attachment_reason_codes": list(_unique_texts(reason_codes)),
        "attachment_source": source,
        "fail_closed": fail_closed,
        "metadata_only": True,
        "raw_payload_included": False,
    }
    if request is not None:
        metadata.update(
            {
                "document_kind": request.document_kind,
                "source_language": request.source_language,
                "target_language": request.target_language,
                "translation_mode": request.translation_mode or "Unknown",
                "glossary_mode": request.glossary_mode or "Unknown",
                "source_sha256_short": request.source_sha256[:12],
            }
        )
    if extra_metadata is not None:
        metadata.update(dict(extra_metadata))
    return _PreparedGlossaryPackageAttachmentResult(
        payload=None,
        metadata=metadata,
        fail_closed=fail_closed,
    )


def _prepared_glossary_package_attachment_result_from(
    attachment: PreparedGlossaryPackageAttachment | None,
    *,
    request: PreparedGlossaryPackageAttachmentRequest,
    source: str,
    missing_reason_code: str,
    disabled_reason_code: str = "prepared_glossary_package_attachment_disabled",
    fail_closed_when_not_ready: bool = False,
    extra_metadata: Mapping[str, object] | None = None,
) -> _PreparedGlossaryPackageAttachmentResult:
    if attachment is None:
        return _prepared_glossary_package_attachment_result(
            status="skipped",
            reason_codes=(missing_reason_code,),
            request=request,
            source=source,
            fail_closed=fail_closed_when_not_ready,
            extra_metadata=extra_metadata,
        )
    if not attachment.enabled:
        return _prepared_glossary_package_attachment_result(
            status="skipped",
            reason_codes=attachment.reason_codes or (disabled_reason_code,),
            request=request,
            source=source,
            fail_closed=fail_closed_when_not_ready,
            extra_metadata=extra_metadata,
        )

    match_reasons = _prepared_glossary_package_attachment_match_reasons(
        attachment,
        request=request,
    )
    if match_reasons:
        return _prepared_glossary_package_attachment_result(
            status="skipped",
            reason_codes=match_reasons,
            request=request,
            source=source,
            fail_closed=fail_closed_when_not_ready,
            extra_metadata=extra_metadata,
        )
    if not isinstance(attachment.payload, Mapping):
        return _prepared_glossary_package_attachment_result(
            status="invalid",
            reason_codes=("prepared_glossary_package_attachment_payload_invalid",),
            request=request,
            source=source,
            fail_closed=fail_closed_when_not_ready,
            extra_metadata=extra_metadata,
        )

    validation = validate_prepared_glossary_package(
        attachment.payload,
        target_language=request.target_language,
    )
    metadata = dict(validation.metadata)
    fail_closed = fail_closed_when_not_ready and not validation.ready
    metadata.update(
        {
            "attachment_status": "attached" if validation.ready else "skipped",
            "attachment_reason_codes": list(validation.reason_codes),
            "attachment_source": source,
            "fail_closed": fail_closed,
            "metadata_only": True,
            "raw_payload_included": False,
        }
    )
    if extra_metadata is not None:
        metadata.update(dict(extra_metadata))
    if not validation.ready:
        return _PreparedGlossaryPackageAttachmentResult(
            payload=None,
            metadata=metadata,
            fail_closed=fail_closed,
        )
    return _PreparedGlossaryPackageAttachmentResult(
        payload=dict(attachment.payload),
        metadata=metadata,
    )


def _prepared_glossary_package_attachment_match_reasons(
    attachment: PreparedGlossaryPackageAttachment,
    *,
    request: PreparedGlossaryPackageAttachmentRequest,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if attachment.source_sha256 != request.source_sha256:
        reasons.append("prepared_glossary_package_attachment_source_mismatch")
    if attachment.document_kind != request.document_kind:
        reasons.append("prepared_glossary_package_attachment_document_kind_mismatch")
    if attachment.target_language != request.target_language:
        reasons.append("prepared_glossary_package_attachment_target_mismatch")
    return _unique_texts(reasons)


def _unique_texts(values) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return tuple(result)


def _translation_policy_with_rights_confirmation(
    translation_policy: str | None,
    *,
    rights_confirmation: dict,
    translation_mode: str | None = None,
    glossary_mode: str | None = None,
    prepared_glossary_package: dict | None = None,
    translation_mode_profile: str | None = None,
    upload_safety: dict | None = None,
) -> str | None:
    if not translation_policy:
        return None
    payload = _translation_policy_payload(translation_policy)
    if not payload:
        return translation_policy
    payload["rights_confirmation"] = rights_confirmation
    if translation_mode is not None:
        payload["translation_mode"] = translation_mode
    if glossary_mode is not None:
        payload["glossary_mode"] = glossary_mode
    if prepared_glossary_package is not None:
        payload["prepared_glossary_package"] = prepared_glossary_package
    if translation_mode_profile is not None:
        payload["translation_mode_profile"] = translation_mode_profile
    if upload_safety is not None:
        payload["upload_safety"] = upload_safety
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _upload_safety_run_policy_marker(pending: PendingTranslation) -> dict | None:
    if pending.upload_safety_id is None:
        return None
    return {
        "source_gate": "upload_safety_ledger",
        "upload_safety_id": pending.upload_safety_id,
    }


def _safe_upload_filename(file_name: str | None) -> str | None:
    if not file_name:
        return None
    safe_name = PurePath(file_name.replace("\\", "/")).name.strip()
    return safe_name or None


def _rights_confirmation_payload(
    pending: PendingUpload | PendingTranslation,
) -> dict:
    return {
        "confirmed": bool(pending.rights_confirmed),
        "source": pending.rights_confirmation_source,
        "version": pending.rights_confirmation_version,
    }


def _normalize_translation_mode(translation_mode: str) -> str:
    normalized = translation_mode.strip().lower()
    if normalized not in SUPPORTED_TRANSLATION_MODES:
        raise ValueError("Unsupported translation mode")
    return normalized


def _normalize_glossary_mode(glossary_mode: str) -> str:
    normalized = glossary_mode.strip().lower()
    if normalized not in SUPPORTED_GLOSSARY_MODES:
        raise ValueError("Unsupported glossary mode")
    return normalized


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _policy_value(policy: dict, key: str) -> str | None:
    value = policy.get(key)
    return value if isinstance(value, str) and value else None


def _target_language_profile_snapshot(signature: str | None) -> dict:
    if signature is None:
        return {"language": None, "signature": None, "version": None}
    parts = signature.split(":")
    if len(parts) == 3 and parts[0] == "target-profile":
        return {
            "language": parts[1],
            "signature": signature,
            "version": parts[2],
        }
    return {"language": None, "signature": signature, "version": _last_part(parts)}


def _source_pair_profile_snapshot(signature: str | None) -> dict:
    if signature is None:
        return {
            "source_language": None,
            "target_language": None,
            "signature": None,
            "version": None,
        }
    parts = signature.split(":")
    if len(parts) == 3 and parts[0] == "source-pair":
        source_target = parts[1].split("-", 1)
        return {
            "source_language": source_target[0] if source_target else None,
            "target_language": source_target[1] if len(source_target) > 1 else None,
            "signature": signature,
            "version": parts[2],
        }
    return {
        "source_language": None,
        "target_language": None,
        "signature": signature,
        "version": _last_part(parts),
    }


def _quality_track_snapshot(signature: str | None) -> dict:
    if signature is None:
        return {"signature": None, "track": None, "version": None}
    parts = signature.split(":")
    if len(parts) == 2 and parts[0] == "russian-quality":
        track_version = parts[1].rsplit("-", 1)
        return {
            "signature": signature,
            "track": track_version[0],
            "version": track_version[1] if len(track_version) > 1 else None,
        }
    return {"signature": signature, "track": None, "version": _last_part(parts)}


def _last_part(parts: list[str]) -> str | None:
    return parts[-1] if parts else None


def _adapter_version_for_document_kind(document_kind: DocumentKind) -> str:
    if document_kind is DocumentKind.TXT:
        return TXT_ADAPTER_VERSION
    if document_kind is DocumentKind.DOCX:
        return DOCX_ADAPTER_VERSION
    if document_kind is DocumentKind.EPUB:
        return EPUB_ADAPTER_VERSION
    return f"{document_kind.value}-adapter-unknown"


def _extract_policy_source_text(
    *,
    content: bytes,
    document_kind: DocumentKind,
    document_sandbox: DocumentSandbox | None = None,
) -> str:
    if document_sandbox is not None:
        document_format = _document_format_from_kind(document_kind)
        if document_format is not None:
            return document_sandbox.extract_text(
                document_format=document_format,
                content=content,
            )

    if document_kind is DocumentKind.TXT:
        return extract_text_from_txt(content)
    if document_kind is DocumentKind.DOCX:
        return extract_text_from_docx(content)
    if document_kind is DocumentKind.EPUB:
        return extract_text_from_epub(content)
    raise TextExtractionError(f"Unsupported document kind: {document_kind}")


def _finish_run_logger(
    run_logger: TranslationRunLogger | None,
    *,
    status: str,
    result_file_name: str | None,
    error_message: str | None,
) -> None:
    if run_logger is None:
        return
    run_logger.finish(
        status=status,
        result_file_name=result_file_name,
        error_message=error_message,
    )


def _translator_model(translator: TextTranslator) -> str | None:
    model = getattr(translator, "_model", None)
    if isinstance(model, str) and model:
        return model
    public_model = getattr(translator, "model", None)
    if isinstance(public_model, str) and public_model:
        return public_model
    return translator.__class__.__name__


def _assemble_persistent_result(
    *,
    document_kind: DocumentKind,
    store: PersistentJobStore,
    storage: LocalObjectStorage,
    job_id: str,
    file_name: str,
    partial: bool,
    document_sandbox: DocumentSandbox | None = None,
):
    if document_kind is DocumentKind.TXT:
        return assemble_persistent_txt_result(
            store=store,
            storage=storage,
            job_id=job_id,
            file_name=file_name,
            partial=partial,
        )
    if document_kind is DocumentKind.DOCX:
        return assemble_persistent_docx_result(
            store=store,
            storage=storage,
            job_id=job_id,
            file_name=file_name,
            partial=partial,
            document_sandbox=document_sandbox,
        )
    if document_kind is DocumentKind.EPUB:
        return assemble_persistent_epub_result(
            store=store,
            storage=storage,
            job_id=job_id,
            file_name=file_name,
            partial=partial,
            document_sandbox=document_sandbox,
        )
    raise ValueError(f"Unsupported persistent document kind: {document_kind}")


def _document_kind_from_format(document_format: DocumentFormat) -> DocumentKind | None:
    if document_format is DocumentFormat.TXT:
        return DocumentKind.TXT
    if document_format is DocumentFormat.DOCX:
        return DocumentKind.DOCX
    if document_format is DocumentFormat.EPUB:
        return DocumentKind.EPUB
    return None


def _estimate_persistent_job_cost(
    *,
    estimated_input_tokens: int,
    rates: BetaSafetyRates,
) -> JobCostEstimate:
    estimated_tokens = max(0, estimated_input_tokens)
    return JobCostEstimate(
        prompt_tokens=estimated_tokens,
        completion_tokens=estimated_tokens,
        estimated_cost_usd=estimate_cost_usd(
            prompt_tokens=estimated_tokens,
            completion_tokens=estimated_tokens,
            rates=rates,
        ),
    )


def _preview_id(candidate: PreviewCandidate) -> str:
    digest = hashlib.sha256()
    digest.update(str(candidate.user_telegram_id).encode("utf-8"))
    digest.update(b"\0")
    digest.update((candidate.attempt_id or "").encode("utf-8", errors="replace"))
    digest.update(b"\0")
    digest.update(candidate.file_name.encode("utf-8", errors="replace"))
    digest.update(b"\0")
    digest.update(candidate.source_language.encode("utf-8", errors="replace"))
    digest.update(b"\0")
    digest.update(candidate.target_language.encode("utf-8", errors="replace"))
    digest.update(b"\0")
    digest.update((candidate.translation_mode or "").encode("utf-8", errors="replace"))
    digest.update(b"\0")
    digest.update((candidate.glossary_mode or "").encode("utf-8", errors="replace"))
    digest.update(b"\0")
    digest.update(candidate.source_text.encode("utf-8", errors="replace"))
    return f"preview:{candidate.user_telegram_id}:{digest.hexdigest()[:24]}"


def _translation_attempt_id(user_telegram_id: int) -> str:
    return f"attempt:{user_telegram_id}:{uuid4().hex}"


@dataclass(frozen=True)
class _DuplicateIdentity:
    source_sha256: str
    document_kind: str
    source_language: str
    target_language: str
    translation_mode: str | None
    glossary_mode: str | None
    adapter_version: str
    prompt_version: str
    policy_signature: str


def _pending_source_sha256(
    *,
    pending: PendingTranslation,
    storage: LocalObjectStorage,
) -> str | None:
    if pending.source_object_key is None:
        return None
    try:
        if not storage.exists(pending.source_object_key):
            return None
        return storage.get_metadata(pending.source_object_key).sha256
    except (FileNotFoundError, ValueError):
        return None


def _job_source_sha256(*, job, storage: LocalObjectStorage) -> str | None:
    try:
        if not job.source_object_key or not storage.exists(job.source_object_key):
            return None
        return storage.get_metadata(job.source_object_key).sha256
    except (FileNotFoundError, ValueError):
        return None


def _duplicate_identity_for_pending(
    *,
    pending: PendingTranslation,
    source_sha256: str,
    max_upload_mb: int,
    max_fragment_chars: int,
    document_sandbox: DocumentSandbox | None,
) -> _DuplicateIdentity | None:
    upload = validate_document_upload(
        file_name=pending.file_name,
        size_bytes=len(pending.content),
        max_upload_mb=max_upload_mb,
    )
    document_kind = _document_kind_from_format(upload.document_format)
    if document_kind is None:
        return None
    plan = _preview_adapter_plan(
        document_format=upload.document_format,
        content=pending.content,
        max_fragment_chars=max_fragment_chars,
        document_sandbox=document_sandbox,
        translation_mode=pending.translation_mode,
    )
    if not plan.units:
        return None
    policy_signature = _duplicate_policy_signature_for_units(
        units=plan.units,
        source_language=pending.source_language,
        target_language=pending.target_language,
        translation_mode=pending.translation_mode,
        glossary_mode=pending.glossary_mode,
        document_kind=document_kind,
    )
    return _DuplicateIdentity(
        source_sha256=source_sha256,
        document_kind=document_kind.value,
        source_language=pending.source_language,
        target_language=pending.target_language,
        translation_mode=pending.translation_mode,
        glossary_mode=pending.glossary_mode,
        adapter_version=plan.adapter_version,
        prompt_version="plain-v1",
        policy_signature=policy_signature,
    )


def _duplicate_identity_for_job(*, job, source_sha256: str) -> _DuplicateIdentity:
    policy_payload = _policy_payload(job.translation_policy)
    return _DuplicateIdentity(
        source_sha256=source_sha256,
        document_kind=job.document_kind,
        source_language=job.source_language,
        target_language=job.target_language,
        translation_mode=(
            str(policy_payload.get("translation_mode"))
            if policy_payload is not None and policy_payload.get("translation_mode")
            else None
        ),
        glossary_mode=(
            str(policy_payload.get("glossary_mode"))
            if policy_payload is not None and policy_payload.get("glossary_mode")
            else None
        ),
        adapter_version=job.adapter_version,
        prompt_version=job.prompt_version,
        policy_signature=_normalized_duplicate_policy_signature(
            job.translation_policy
        ),
    )


def _duplicate_policy_signature_for_units(
    *,
    units,
    source_language: str,
    target_language: str,
    translation_mode: str | None,
    glossary_mode: str | None,
    document_kind: DocumentKind,
) -> str:
    source_text = "\n\n".join(unit.source_text for unit in units if unit.source_text)
    translation_context = build_initial_translation_context_memory(
        source_text,
        target_language=target_language,
    )
    translation_mode_profile = _translation_mode_profile_for_document_kind(
        translation_mode,
        document_kind=document_kind.value,
    )
    if translation_mode_profile is not None:
        translation_context = _translation_context_with_mode_profile(
            translation_context,
            translation_mode_profile,
        )
    policy = build_translation_policy(
        text=source_text,
        source_language=source_language,
        target_language=target_language,
        translation_context=translation_context,
    )
    payload = json.loads(translation_policy_signature(policy))
    if translation_mode is not None:
        payload["translation_mode"] = translation_mode
    if glossary_mode is not None:
        payload["glossary_mode"] = glossary_mode
    if translation_mode_profile is not None:
        payload["translation_mode_profile"] = translation_mode_profile.signature
    return _safe_duplicate_policy_signature(payload)


def _normalized_duplicate_policy_signature(translation_policy: str | None) -> str:
    payload = _policy_payload(translation_policy)
    if payload is None:
        return "__translation_policy_none__"
    return _safe_duplicate_policy_signature(payload)


def _policy_payload(translation_policy: str | None) -> dict | None:
    if translation_policy is None:
        return None
    try:
        payload = json.loads(translation_policy)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _safe_duplicate_policy_signature(payload: dict) -> str:
    safe_keys = (
        "prompt_policy_version",
        "protection_policy_version",
        "adapter_policy_version",
        "source_language",
        "target_language",
        "target_language_policy",
        "source_pair_policy",
        "text_type",
        "prompt_tier",
        "output_contract",
        "translation_mode",
        "glossary_mode",
        "translation_mode_profile",
    )
    safe_payload = {key: payload.get(key) for key in safe_keys if key in payload}
    return json.dumps(safe_payload, ensure_ascii=False, sort_keys=True)


def _estimate_preview_cost(
    *,
    candidate: PreviewCandidate,
    rates: BetaSafetyRates,
) -> JobCostEstimate:
    estimated_tokens = math.ceil(max(1, candidate.character_count) / 4)
    return JobCostEstimate(
        prompt_tokens=estimated_tokens,
        completion_tokens=estimated_tokens,
        estimated_cost_usd=estimate_cost_usd(
            prompt_tokens=estimated_tokens,
            completion_tokens=estimated_tokens,
            rates=rates,
        ),
    )


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


def _prepared_glossary_package_fail_closed_message(
    metadata: Mapping[str, object],
) -> str:
    raw_reasons = metadata.get("attachment_reason_codes")
    reason_codes: list[str] = []
    if isinstance(raw_reasons, list):
        reason_codes = [str(reason) for reason in raw_reasons if str(reason)]
    reason_summary = ",".join(_unique_texts(reason_codes)) or "Unknown"
    return (
        "Prepared glossary data is not READY for this with_glossary "
        f"owner/test run. reason_codes={reason_summary}"
    )


def _queued_translation_job(
    *,
    pending: PendingTranslation,
    document_kind: DocumentKind,
    job_id: str,
) -> TranslationJob:
    return TranslationJob(
        id=job_id,
        document_kind=document_kind,
        user_telegram_id=pending.user_telegram_id,
        file_name=pending.file_name,
        content=pending.content,
        source_language=pending.source_language,
        target_language=pending.target_language,
        status=TranslationJobStatus.QUEUED,
    )


def _is_security_threshold_error(error_message: str | None) -> bool:
    return bool(
        error_message and error_message.startswith("Security threshold exceeded:")
    )


def _security_user_id(user_telegram_id: int) -> str:
    return f"telegram:{user_telegram_id}"


def _completed_persistent_units(
    store: PersistentJobStore,
    job_id: str,
) -> int:
    return sum(
        1
        for unit in store.list_work_units(job_id)
        if unit.status
        in {PersistentWorkUnitStatus.TRANSLATED, PersistentWorkUnitStatus.CACHED}
    )


def _has_persistent_partial_units(work_units: list[PersistentWorkUnit]) -> bool:
    return any(
        unit.status
        in {PersistentWorkUnitStatus.TRANSLATED, PersistentWorkUnitStatus.CACHED}
        and bool(unit.translated_text)
        for unit in work_units
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


def _upload_safety_id(*, user_telegram_id: int, digest: str) -> str:
    return f"telegram:{user_telegram_id}:{digest[:16]}:{time.time_ns()}"


def _upload_scan_verdict(
    scanner_verdict: ScannerVerdict | None,
) -> UploadScanVerdict | None:
    if scanner_verdict is ScannerVerdict.CLEAN:
        return UploadScanVerdict.CLEAN
    if scanner_verdict is ScannerVerdict.INFECTED:
        return UploadScanVerdict.INFECTED
    if scanner_verdict is ScannerVerdict.SCANNER_TIMEOUT:
        return UploadScanVerdict.SCANNER_TIMEOUT
    if scanner_verdict is ScannerVerdict.SCANNER_UNAVAILABLE:
        return UploadScanVerdict.SCANNER_UNAVAILABLE
    if scanner_verdict is ScannerVerdict.UNSUPPORTED:
        return UploadScanVerdict.UNSUPPORTED
    if scanner_verdict is ScannerVerdict.SCANNER_ERROR:
        return UploadScanVerdict.SCANNER_ERROR
    return None


def _safe_scan_error_class(scanner_verdict: ScannerVerdict | None) -> str:
    if scanner_verdict is None:
        return "scanner_missing"
    return scanner_verdict.value


def _upload_safety_latest_value(
    history: tuple[UploadSafetyRecord, ...],
    field_name: str,
) -> str | None:
    for record in reversed(history):
        value = getattr(record, field_name)
        if value is not None:
            return value.value
    return None


def _upload_safety_final_action(history: tuple[UploadSafetyRecord, ...]) -> str:
    states = tuple(record.state for record in history)
    latest = states[-1]
    if latest == UploadSafetyState.ACCEPTED_SOURCE_CREATED:
        return "accepted"
    if any(
        state in {
            UploadSafetyState.SCAN_FAILED,
            UploadSafetyState.CONTAINER_FAILED,
        }
        for state in states
    ):
        return "failed_closed"
    if any(
        state in {
            UploadSafetyState.SCAN_BLOCKED,
            UploadSafetyState.CONTAINER_BLOCKED,
        }
        for state in states
    ):
        return "blocked"
    if latest in {
        UploadSafetyState.QUARANTINE_EXPIRED,
        UploadSafetyState.QUARANTINE_DELETED,
    }:
        return "deleted_by_ttl"
    if latest == UploadSafetyState.REJECTED:
        return "rejected"
    return "quarantined"


def _upload_safety_reason_code(
    history: tuple[UploadSafetyRecord, ...],
    latest: UploadSafetyRecord,
) -> str:
    if latest.metadata.safe_error_class:
        return latest.metadata.safe_error_class
    for state in reversed(tuple(record.state for record in history)):
        if state in {
            UploadSafetyState.SCAN_FAILED,
            UploadSafetyState.CONTAINER_FAILED,
            UploadSafetyState.SCAN_BLOCKED,
            UploadSafetyState.CONTAINER_BLOCKED,
        }:
            return state.value
    return latest.state.value


def _upload_safety_activity_outcome(final_action: str) -> ActivityOutcome:
    if final_action == "accepted":
        return ActivityOutcome.SUCCESS
    if final_action == "blocked":
        return ActivityOutcome.BLOCKED
    return ActivityOutcome.FAILURE


def _short_upload_hash(value: str) -> str:
    return value[:8] if len(value) >= 8 else "n/a"


def estimate_translation_seconds(
    fragment_count: int,
    *,
    max_parallel_work_units: int = 1,
    provider_parallel_capacity: int = 1,
) -> int:
    if fragment_count <= 0:
        return 0

    effective_parallelism = min(
        fragment_count,
        max(1, max_parallel_work_units),
        max(1, provider_parallel_capacity),
    )
    return max(20, math.ceil(fragment_count * 75 / effective_parallelism))


def _can_resume_persistent_job(status: str) -> bool:
    return status in {
        "cancelled",
        "paused",
        "interrupted",
        "failed",
        "partial",
    }


def _can_cancel_persistent_job(status: str) -> bool:
    return status in {
        "queued",
        "translating",
        "assembling",
        "cancel_requested",
    }


def _translation_job_status_from_persistent_status(
    status: PersistentTranslationJobStatus,
) -> TranslationJobStatus:
    if status is PersistentTranslationJobStatus.QUEUED:
        return TranslationJobStatus.QUEUED
    if status is PersistentTranslationJobStatus.PAUSED:
        return TranslationJobStatus.PAUSED
    if status is PersistentTranslationJobStatus.CANCEL_REQUESTED:
        return TranslationJobStatus.CANCEL_REQUESTED
    if status in {
        PersistentTranslationJobStatus.TRANSLATING,
        PersistentTranslationJobStatus.ASSEMBLING,
    }:
        return TranslationJobStatus.TRANSLATING
    if status is PersistentTranslationJobStatus.READY:
        return TranslationJobStatus.READY
    if status is PersistentTranslationJobStatus.PARTIAL:
        return TranslationJobStatus.PARTIAL
    if status is PersistentTranslationJobStatus.CANCELLED:
        return TranslationJobStatus.CANCELLED
    return TranslationJobStatus.FAILED


def _source_language_display(
    *,
    document_format: DocumentFormat,
    content: bytes,
    source_language: str,
    document_sandbox: DocumentSandbox | None = None,
) -> str:
    text = _extract_text_for_language_detection(
        document_format=document_format,
        content=content,
        document_sandbox=document_sandbox,
    )
    return format_detected_source_languages(
        requested_source_language=source_language,
        detected_languages=detect_languages_from_text(text),
        primary_language=detect_language_from_text(text),
    )


def _raise_if_same_language_translation(
    *,
    source_language: str,
    source_language_display: str | None,
    target_language: str,
) -> None:
    source_code = _resolved_source_language_code(
        source_language=source_language,
        source_language_display=source_language_display,
    )
    target_code = _normalized_language_code(target_language)
    if source_code is not None and source_code == target_code:
        raise SameLanguageTranslationBlocked(
            source_language_code=source_code,
            target_language_code=target_code,
        )


def _resolved_source_language_code(
    *,
    source_language: str,
    source_language_display: str | None,
) -> str | None:
    normalized_source = _normalized_language_code(source_language)
    if normalized_source != "auto":
        return normalized_source
    if not source_language_display:
        return None
    primary_display = source_language_display.split("(", 1)[0].split(";", 1)[0].strip()
    if not primary_display or primary_display.casefold().startswith("auto"):
        return None
    return _LANGUAGE_NAME_TO_CODE.get(primary_display.casefold())


def _normalized_language_code(language: str) -> str:
    return language.strip().lower()


def _extract_text_for_language_detection(
    *,
    document_format: DocumentFormat,
    content: bytes,
    document_sandbox: DocumentSandbox | None = None,
) -> str:
    if document_sandbox is not None:
        return document_sandbox.extract_text(
            document_format=document_format,
            content=content,
        )

    if document_format is DocumentFormat.TXT:
        return extract_text_from_txt(content)
    if document_format is DocumentFormat.DOCX:
        return extract_text_from_docx(content)
    if document_format is DocumentFormat.EPUB:
        return extract_text_from_epub(content)
    return ""


def _document_format_from_kind(document_kind: DocumentKind) -> DocumentFormat | None:
    if document_kind is DocumentKind.TXT:
        return DocumentFormat.TXT
    if document_kind is DocumentKind.DOCX:
        return DocumentFormat.DOCX
    if document_kind is DocumentKind.EPUB:
        return DocumentFormat.EPUB
    return None
