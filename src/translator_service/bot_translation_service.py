import hashlib
import json
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePath
from threading import RLock

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
from translator_service.documents import DocumentFormat, validate_document_upload
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
from translator_service.job_runner import (
    DocumentKind,
    InMemoryTranslationJobRepository,
    TranslationJob,
    TranslationJobStatus,
    run_translation_job,
)
from translator_service.language_detection import (
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
from translator_service.user_activity import (
    ActivityActorType,
    ActivityOutcome,
    ActivitySurface,
    SQLiteUserActivityStore,
    UserActivityEventInput,
)
from translator_service.users import SQLiteUserSettingsRepository
from translator_service.worker import (
    run_next_stored_text_work_unit,
    run_stored_text_job_parallel_until_idle,
)

logger = logging.getLogger(__name__)
RIGHTS_CONFIRMATION_VERSION = "rights-v1"
RIGHTS_CONFIRMATION_SOURCE_TELEGRAM = "telegram_button"
PREVIEW_CANDIDATE_MAX_BLOCKS = 3
PREVIEW_CANDIDATE_MAX_CHARS = 2_000
AutomaticResultDeliveryKey = tuple[int, str, str, int, str]


class RightsConfirmationRequired(ValueError):
    """Raised when document rights have not been confirmed for processing."""


class PreviewAcceptanceRequired(ValueError):
    """Raised when full translation starts before preview acceptance."""


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


@dataclass(frozen=True)
class PreviewCandidate:
    user_telegram_id: int
    file_name: str
    document_kind: DocumentKind
    source_language: str
    target_language: str
    source_text: str
    source_block_ids: tuple[str, ...]
    selected_block_count: int
    selected_unit_sequences: tuple[int, ...]
    character_count: int
    max_character_count: int
    adapter_version: str
    metadata: dict[str, object]


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
        activity_store: SQLiteUserActivityStore | None = None,
        beta_access_policy: (
            BetaAccessPolicy | SQLiteBackedBetaAccessPolicy | None
        ) = None,
        beta_safety_guard: BetaSafetyGuard | None = None,
        beta_safety_rates: BetaSafetyRates | None = None,
        beta_safety_guard_owned: bool = False,
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
        )
        with self._state_lock:
            self._pending_uploads[user_telegram_id] = pending_upload
        return pending_upload

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

    def prepare_pending_upload(
        self,
        *,
        user_telegram_id: int,
        target_language: str,
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
    ) -> PendingTranslation:
        self._assert_beta_access_allows(user_telegram_id)
        self._assert_security_cooldown_allows(user_telegram_id)
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

        estimate = estimate_order(
            upload=upload,
            content=content,
            pricing_rules=self._pricing_rules,
            max_fragment_chars=self._max_fragment_chars,
            document_sandbox=self._document_sandbox,
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
                document_sandbox=self._document_sandbox,
            ),
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
        return PreviewCandidate(
            user_telegram_id=user_telegram_id,
            file_name=pending.file_name,
            document_kind=document_kind,
            source_language=pending.source_language,
            target_language=pending.target_language,
            source_text=source_text,
            source_block_ids=source_block_ids,
            selected_block_count=len(selected),
            selected_unit_sequences=unit_sequences,
            character_count=len(source_text),
            max_character_count=PREVIEW_CANDIDATE_MAX_CHARS,
            adapter_version=plan.adapter_version,
            metadata=metadata,
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

        return self._book_summary_from_job(job)

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
        if not _can_resume_persistent_job(job.status.value):
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
        if not _can_resume_persistent_job(job.status.value):
            return None

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
        )
        resumed = self._persistent_job_store.resume_job(job_id)
        total_fragments = len(self._persistent_job_store.list_work_units(job_id))
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

    def _book_summary_from_job(self, job) -> UserBookSummary:
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
            can_resume=_can_resume_persistent_job(job.status.value),
            can_cancel=_can_cancel_persistent_job(job.status.value),
            created_at=job.created_at.isoformat(timespec="minutes"),
            updated_at=job.updated_at.isoformat(timespec="minutes"),
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
        total_fragments: int,
    ):
        if self._beta_safety_guard is None:
            return None
        return self._beta_safety_guard.reserve_job(
            job_id=job_id,
            user_id=user_id,
            estimate=_estimate_persistent_job_cost(
                total_fragments=total_fragments,
                max_fragment_chars=self._max_fragment_chars,
                rates=self._beta_safety_rates,
            ),
        )

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
                raise PreviewTranslationError(
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
                raise PreviewTranslationError(
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

        plan = _create_persistent_job_plan(
            document_kind=document_kind,
            store=self._persistent_job_store,
            storage=self._file_storage,
            pending=pending,
            max_fragment_chars=self._max_fragment_chars,
        )
        total_fragments = len(plan.work_units)
        reservation_decision = self._reserve_beta_safety_for_persistent_job(
            job_id=plan.job.id,
            user_id=plan.job.user_id,
            total_fragments=total_fragments,
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
        )
        if run_logger is not None:
            run_logger.record_event(
                "job_created",
                {
                    "job_id": plan.job.id,
                    "fragment_count": total_fragments,
                    "source_object_key": plan.job.source_object_key,
                },
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
    }
    if document_kind is DocumentKind.TXT:
        return create_persistent_txt_job_plan(**common)
    if document_kind is DocumentKind.DOCX:
        return create_persistent_docx_job_plan(**common)
    if document_kind is DocumentKind.EPUB:
        return create_persistent_epub_job_plan(**common)
    raise ValueError(f"Unsupported persistent document kind: {document_kind}")


def _preview_adapter_plan(
    *,
    document_format: DocumentFormat,
    content: bytes,
    max_fragment_chars: int,
    document_sandbox: DocumentSandbox | None,
) -> FormatAdapterPlan:
    if document_sandbox is not None:
        return document_sandbox.plan_translation(
            document_format=document_format,
            content=content,
            max_fragment_chars=max_fragment_chars,
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

    policy = build_translation_policy(
        text=source_text,
        source_language=pending.source_language,
        target_language=pending.target_language,
    )
    return _translation_policy_with_rights_confirmation(
        translation_policy_signature(policy),
        rights_confirmation=_rights_confirmation_payload(pending),
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


def _translation_policy_with_rights_confirmation(
    translation_policy: str | None,
    *,
    rights_confirmation: dict,
) -> str | None:
    if not translation_policy:
        return None
    payload = _translation_policy_payload(translation_policy)
    if not payload:
        return translation_policy
    payload["rights_confirmation"] = rights_confirmation
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _rights_confirmation_payload(
    pending: PendingUpload | PendingTranslation,
) -> dict:
    return {
        "confirmed": bool(pending.rights_confirmed),
        "source": pending.rights_confirmation_source,
        "version": pending.rights_confirmation_version,
    }


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
    total_fragments: int,
    max_fragment_chars: int,
    rates: BetaSafetyRates,
) -> JobCostEstimate:
    estimated_tokens = math.ceil(
        max(0, total_fragments) * max(1, max_fragment_chars) / 4
    )
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
    digest.update(candidate.file_name.encode("utf-8", errors="replace"))
    digest.update(b"\0")
    digest.update(candidate.source_language.encode("utf-8", errors="replace"))
    digest.update(b"\0")
    digest.update(candidate.target_language.encode("utf-8", errors="replace"))
    digest.update(b"\0")
    digest.update(candidate.source_text.encode("utf-8", errors="replace"))
    return f"preview:{candidate.user_telegram_id}:{digest.hexdigest()[:24]}"


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
    if status in {
        PersistentTranslationJobStatus.TRANSLATING,
        PersistentTranslationJobStatus.ASSEMBLING,
        PersistentTranslationJobStatus.CANCEL_REQUESTED,
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
