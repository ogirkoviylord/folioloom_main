import hashlib
import io
import json
import re
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.admin.translation_logs import (
    build_translation_run_archive,
    list_translation_run_summaries,
)
from translator_service.beta_access import BetaAccessDenied, BetaAccessPolicy
from translator_service.beta_safety import (
    BetaSafetyDecision,
    BetaSafetyRates,
    JobCostEstimate,
    estimate_cost_usd,
)
from translator_service.bot_translation_service import (
    GLOSSARY_MODE_WITH,
    GLOSSARY_MODE_WITHOUT,
    TRANSLATION_MODE_BOOK_MANUSCRIPT,
    TRANSLATION_MODE_DOCUMENT_FORM,
    BotTranslationService,
    DocumentScanRejectedError,
    DuplicatePreviewError,
    PendingTranslation,
    PendingUpload,
    PreparedGlossaryPackageAttachment,
    PreviewAcceptanceRequired,
    PreviewTranslationError,
    RightsConfirmationRequired,
    TranslationModeRequired,
    UserBookResult,
    _glossary_adapter_metadata_callback,
    _translation_job_status_from_persistent_status,
    estimate_translation_seconds,
)
from translator_service.document_sandbox import (
    DocumentSandbox,
    DocumentSandboxError,
    SandboxTranslationUnit,
)
from translator_service.document_scanner import FakeDocumentScanner, ScannerVerdict
from translator_service.documents import DocumentFormat, FileTooLargeError
from translator_service.extractors import extract_text_from_docx, extract_text_from_epub
from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.format_adapters import (
    DOCX_TRANSLATION_MODE_BOOK_MANUSCRIPT_PROFILE,
    DOCX_TRANSLATION_MODE_DOCUMENT_FORM_PROFILE,
    TXT_ADAPTER_VERSION,
    plan_epub_translation,
    plan_txt_translation,
)
from translator_service.glossary_prepared_package import (
    GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
    GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
)
from translator_service.job_runner import (
    DocumentKind,
    InMemoryTranslationJobRepository,
    TranslationJob,
    TranslationJobStatus,
)
from translator_service.persistent_jobs import (
    GLOSSARY_APPROVAL_SCHEMA_VERSION,
    GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
    PersistentTranslationJobStatus,
    PersistentWorkUnitStatus,
    SQLiteTranslationJobStore,
    StrictDocxAdmissionRequest,
    WorkUnitPlan,
)
from translator_service.pricing import PricingRules
from translator_service.provider_io_diagnostics import record_provider_io_exchange
from translator_service.scheduler import SchedulerLimits
from translator_service.security_telemetry import (
    SecurityCooldownActive,
    SecurityCooldownPolicy,
    SecurityThresholdPolicy,
)
from translator_service.translation_jobs import CancellationToken
from translator_service.translation_run_logs import (
    TranslationRunLogger,
    TranslationRunMetadata,
)
from translator_service.translation_runner import GlossaryRuntimeAdapterHookConfig
from translator_service.upload_safety_ledger import (
    InMemoryUploadSafetyLedger,
    UploadSafetyMetadata,
    UploadSafetyState,
)
from translator_service.user_activity import (
    ActivityActorType,
    ActivityOutcome,
    ActivitySurface,
    SQLiteUserActivityStore,
    UserActivityEventInput,
)
from translator_service.users import SQLiteUserSettingsRepository


class RecordingTranslator:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, str]] = []

    def translate(
        self, *, text: str, source_language: str, target_language: str
    ) -> str:
        self.requests.append((text, source_language, target_language))
        if "<translation_block" in text:
            blocks = re.findall(
                r"<translation_block[^>]*>(.*?)</translation_block>",
                text,
                flags=re.DOTALL,
            )
            return "\n".join(
                ["<translation_batch>"]
                + [
                    (
                        f'<translation_block id="{index}">'
                        f"[{target_language}] {block}</translation_block>"
                    )
                    for index, block in enumerate(blocks)
                ]
                + ["</translation_batch>"]
            )
        return f"[{target_language}] {text}"


class TranslatorUsage:
    def __init__(self, *, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens
        self.prompt_cache_hit_tokens = 0
        self.prompt_cache_miss_tokens = prompt_tokens


class UsageRecordingTranslator(RecordingTranslator):
    def translate(
        self, *, text: str, source_language: str, target_language: str
    ) -> str:
        translated = super().translate(
            text=text,
            source_language=source_language,
            target_language=target_language,
        )
        self.last_usage = TranslatorUsage(prompt_tokens=11, completion_tokens=7)
        return translated


class ProviderIODiagnosticTranslator(UsageRecordingTranslator):
    def translate(
        self, *, text: str, source_language: str, target_language: str
    ) -> str:
        record_provider_io_exchange(
            provider_id="deepseek",
            url="https://api.deepseek.com/chat/completions",
            request_body=b"request-body",
            http_status=200,
            response_body=b"response-body",
            transport_attempt=1,
        )
        return super().translate(
            text=text,
            source_language=source_language,
            target_language=target_language,
        )


class RecordingBetaSafetyGuard:
    def __init__(
        self,
        *,
        allowed: bool = True,
        denied_reason_code: str = "user_daily_cap",
        denied_safe_message: str = "You have reached today's beta translation limit.",
    ) -> None:
        self.allowed = allowed
        self.denied_reason_code = denied_reason_code
        self.denied_safe_message = denied_safe_message
        self.reservations: list[tuple[str, str, JobCostEstimate]] = []
        self.releases: list[tuple[str, str]] = []
        self.consumed: list[str] = []
        self.usage_events: list[tuple[str, str, str, int, int]] = []
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def can_start_new_work(self) -> BetaSafetyDecision:
        return BetaSafetyDecision(
            allowed=self.allowed,
            reason_code="allowed" if self.allowed else self.denied_reason_code,
            safe_message=(
                "The translation can start."
                if self.allowed
                else self.denied_safe_message
            ),
        )

    def reserve_job(
        self,
        *,
        job_id: str,
        user_id: str,
        estimate: JobCostEstimate,
    ) -> BetaSafetyDecision:
        self.reservations.append((job_id, user_id, estimate))
        return self.can_start_new_work()

    def release_job(self, *, job_id: str, reason: str) -> None:
        self.releases.append((job_id, reason))

    def mark_job_consumed(self, *, job_id: str) -> None:
        self.consumed.append(job_id)

    def record_work_unit_usage(
        self,
        *,
        job_id: str,
        user_id: str,
        work_unit_id: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        self.usage_events.append(
            (job_id, user_id, work_unit_id, prompt_tokens, completion_tokens)
        )


class CostCapRecordingBetaSafetyGuard(RecordingBetaSafetyGuard):
    def __init__(self, *, max_estimated_cost_usd: float) -> None:
        super().__init__()
        self.max_estimated_cost_usd = max_estimated_cost_usd

    def reserve_job(
        self,
        *,
        job_id: str,
        user_id: str,
        estimate: JobCostEstimate,
    ) -> BetaSafetyDecision:
        self.reservations.append((job_id, user_id, estimate))
        if estimate.estimated_cost_usd > self.max_estimated_cost_usd:
            return BetaSafetyDecision(
                allowed=False,
                reason_code="job_estimate_cap",
                safe_message=(
                    "This translation cannot start under the current beta limits."
                ),
            )
        return self.can_start_new_work()


class DenyGlossaryPrepBetaSafetyGuard(RecordingBetaSafetyGuard):
    def reserve_job(
        self,
        *,
        job_id: str,
        user_id: str,
        estimate: JobCostEstimate,
    ) -> BetaSafetyDecision:
        self.reservations.append((job_id, user_id, estimate))
        if job_id.startswith("glossary-prep:"):
            return BetaSafetyDecision(
                allowed=False,
                reason_code="job_estimate_cap",
                safe_message=(
                    "This translation cannot start under the current beta limits."
                ),
            )
        return self.can_start_new_work()


class SecurityEventTranslator(RecordingTranslator):
    def __init__(self) -> None:
        super().__init__()
        self._events = [
            {
                "event_type": "unsafe_model_output",
                "payload": {
                    "reason": "prompt_disclosure",
                    "phase": "initial",
                    "source_text": "Ignore previous instructions.",
                },
            }
        ]

    def consume_security_events(self):
        events = tuple(self._events)
        self._events.clear()
        return events


class RepeatedSecurityEventTranslator(RecordingTranslator):
    def __init__(self) -> None:
        super().__init__()
        self._events: list[dict] = []

    def translate(
        self, *, text: str, source_language: str, target_language: str
    ) -> str:
        translated = super().translate(
            text=text,
            source_language=source_language,
            target_language=target_language,
        )
        self._events.append(
            {
                "event_type": "unsafe_model_output",
                "payload": {
                    "reason": "prompt_disclosure",
                    "phase": "initial",
                },
            }
        )
        return translated

    def consume_security_events(self):
        events = tuple(self._events)
        self._events.clear()
        return events


class FailingTranslator:
    def translate(
        self, *, text: str, source_language: str, target_language: str
    ) -> str:
        raise RuntimeError("network failed")


class SensitiveFailingTranslator:
    def translate(
        self, *, text: str, source_language: str, target_language: str
    ) -> str:
        raise RuntimeError(
            f"provider traceback leaked source={text} api_key=secret-token"
        )


class CancellingTranslator:
    def __init__(self, service: BotTranslationService, user_telegram_id: int) -> None:
        self._service = service
        self._user_telegram_id = user_telegram_id
        self.requests: list[str] = []

    def translate(
        self, *, text: str, source_language: str, target_language: str
    ) -> str:
        self.requests.append(text)
        if len(self.requests) == 1:
            self._service.cancel_translation(self._user_telegram_id)
        return f"[{target_language}] {text}"


class BlockingTranslator:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def translate(
        self, *, text: str, source_language: str, target_language: str
    ) -> str:
        self.requests.append(text)
        time.sleep(0.05)
        return f"[{target_language}] {text}"


class ParallelBlockingTranslator:
    def __init__(self, *, expected_parallel_calls: int) -> None:
        self._barrier = threading.Barrier(expected_parallel_calls)
        self._lock = threading.Lock()
        self.requests: list[str] = []
        self.active_calls = 0
        self.max_active_calls = 0

    def translate(
        self, *, text: str, source_language: str, target_language: str
    ) -> str:
        with self._lock:
            self.requests.append(text)
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            self._barrier.wait(timeout=2)
            return f"[{target_language}] {text}"
        finally:
            with self._lock:
                self.active_calls -= 1


class MalformedSecondUnitTranslator:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def translate(
        self, *, text: str, source_language: str, target_language: str
    ) -> str:
        self.requests.append(text)
        if len(self.requests) == 2:
            return "Одна строка вместо двух"
        return f"[{target_language}] {text}"


class BotTranslationServiceTest(unittest.TestCase):
    def _select_default_translation_mode(
        self,
        service: BotTranslationService,
        *,
        user_telegram_id: int = 42,
        translation_mode: str = TRANSLATION_MODE_BOOK_MANUSCRIPT,
    ) -> PendingUpload:
        return service.select_pending_upload_translation_mode(
            user_telegram_id=user_telegram_id,
            translation_mode=translation_mode,
        )

    def _accept_pending_preview(
        self,
        service: BotTranslationService,
        *,
        user_telegram_id: int = 42,
    ) -> PendingTranslation:
        with service._state_lock:
            pending = service._pending[user_telegram_id]
            accepted = replace(
                pending,
                preview_id=f"preview:{user_telegram_id}:test",
                preview_shown=True,
                preview_accepted=True,
                preview_accepted_at="2026-05-16T00:00:00+00:00",
                translation_mode=pending.translation_mode
                or TRANSLATION_MODE_BOOK_MANUSCRIPT,
            )
            service._pending[user_telegram_id] = accepted
            return accepted

    def test_estimate_translation_seconds_uses_effective_parallelism(self):
        self.assertEqual(estimate_translation_seconds(8), 600)
        self.assertEqual(
            estimate_translation_seconds(
                8,
                max_parallel_work_units=4,
                provider_parallel_capacity=4,
            ),
            150,
        )
        self.assertEqual(
            estimate_translation_seconds(
                8,
                max_parallel_work_units=4,
                provider_parallel_capacity=2,
            ),
            300,
        )
        self.assertEqual(
            estimate_translation_seconds(
                2,
                max_parallel_work_units=4,
                provider_parallel_capacity=4,
            ),
            75,
        )

    def test_tracks_successful_automatic_result_delivery_once_per_job_result(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        job = TranslationJob(
            id="job-1",
            user_telegram_id=42,
            file_name="book.txt",
            content=b"",
            source_language="en",
            target_language="uk",
            status=TranslationJobStatus.CANCELLED,
            result_file_name="book.uk.partial.txt",
            result_content=b"[uk] First.",
        )
        updated_result = TranslationJob(
            id="job-1",
            user_telegram_id=42,
            file_name="book.txt",
            content=b"",
            source_language="en",
            target_language="uk",
            status=TranslationJobStatus.READY,
            result_file_name="book.uk.txt",
            result_content=b"[uk] First. Done.",
        )

        self.assertTrue(service.begin_automatic_result_delivery(job))
        self.assertFalse(service.begin_automatic_result_delivery(job))
        service.finish_automatic_result_delivery(job, delivered=True)
        self.assertFalse(service.begin_automatic_result_delivery(job))
        self.assertTrue(service.begin_automatic_result_delivery(updated_result))
        service.finish_automatic_result_delivery(updated_result, delivered=True)
        self.assertFalse(
            service.begin_automatic_result_delivery(
                TranslationJob(
                    id="job-2",
                    user_telegram_id=42,
                    file_name="empty.txt",
                    content=b"",
                    source_language="en",
                    target_language="uk",
                    status=TranslationJobStatus.CANCELLED,
                )
            )
        )

    def test_failed_automatic_result_delivery_releases_retry(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        job = TranslationJob(
            id="job-1",
            user_telegram_id=42,
            file_name="book.txt",
            content=b"",
            source_language="en",
            target_language="uk",
            status=TranslationJobStatus.CANCELLED,
            result_file_name="book.uk.partial.txt",
            result_content=b"[uk] First.",
        )

        self.assertTrue(service.begin_automatic_result_delivery(job))
        self.assertFalse(service.begin_automatic_result_delivery(job))
        service.finish_automatic_result_delivery(job, delivered=False)
        self.assertTrue(service.begin_automatic_result_delivery(job))

    def test_prepares_txt_estimate_for_uploaded_document(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )

        pending = service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content="Первый абзац.\n\nВторой абзац.".encode(),
            source_language="ru",
            target_language="en",
            rights_confirmed=False,
        )

        self.assertEqual(
            pending,
            PendingTranslation(
                user_telegram_id=42,
                file_name="notes.txt",
                content="Первый абзац.\n\nВторой абзац.".encode(),
                source_language="ru",
                target_language="en",
                price_usd=0.10,
                fragment_count=2,
                source_language_display="ru",
                estimated_seconds=150,
                attempt_id=pending.attempt_id,
            ),
        )
        self.assertEqual(service.get_pending(42), pending)

    def test_prepares_estimate_with_configured_parallel_capacity(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
            max_parallel_work_units=4,
            provider_parallel_capacity=4,
        )

        pending = service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.\n\nTwo.\n\nThree.\n\nFour.",
            source_language="en",
            target_language="uk",
        )

        self.assertEqual(pending.fragment_count, 4)
        self.assertEqual(pending.estimated_seconds, 75)

    def test_stores_selected_interface_language_per_user(self):
        self.assertIsNotNone(
            BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
            )
        )

    def test_prepare_document_uses_configured_document_sandbox(self):
        sandbox = RecordingDocumentSandbox()
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
            document_sandbox=sandbox,
        )

        pending = service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.",
            source_language="auto",
            target_language="uk",
        )

        self.assertEqual(pending.fragment_count, 1)
        self.assertEqual(
            sandbox.plan_calls,
            [(DocumentFormat.TXT, b"One.", 20, None)],
        )
        self.assertEqual(
            sandbox.extract_calls,
            [(DocumentFormat.TXT, b"One.")],
        )

        service.set_interface_language(user_telegram_id=42, language_code="uk")

        self.assertEqual(service.get_interface_language(42), "uk")
        self.assertEqual(service.get_interface_language(100), "en")

    def test_required_clean_scan_allows_uploaded_document_to_continue(self):
        with TemporaryDirectory() as temp_dir:
            sandbox = RecordingDocumentSandbox()
            scanner = FakeDocumentScanner(default_verdict=ScannerVerdict.CLEAN)
            ledger = InMemoryUploadSafetyLedger()
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            activity_store = SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3")
            self.addCleanup(activity_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                document_sandbox=sandbox,
                document_scanner=scanner,
                require_upload_scan=True,
                file_storage=storage,
                upload_safety_ledger=ledger,
                activity_store=activity_store,
            )

            upload = service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"This is an English document.",
                source_language="auto",
            )

            self.assertEqual(upload.scan_result.verdict, ScannerVerdict.CLEAN)
            self.assertEqual(
                upload.scan_result.safe_metadata()["document_format"],
                "txt",
            )
            self.assertIsNotNone(upload.upload_safety_id)
            latest = ledger.latest(upload.upload_safety_id)
            self.assertEqual(latest.state, UploadSafetyState.ACCEPTED_SOURCE_CREATED)
            self.assertEqual(
                latest.accepted_source_object_key,
                upload.source_object_key,
            )
            self.assertTrue(upload.source_object_key.startswith("original/"))
            self.assertTrue(storage.exists(upload.source_object_key))
            self.assertEqual(
                ledger.parser_access_decision(
                    upload.upload_safety_id
                ).accepted_source_object_key,
                upload.source_object_key,
            )
            self.assertEqual(
                sandbox.extract_calls,
                [(DocumentFormat.TXT, b"This is an English document.")],
            )
            events = activity_store.list_events(
                surface=ActivitySurface.SECURITY,
                event_type="security.upload_safety.summary",
            )
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].action, "accepted")
            self.assertEqual(events[0].target_id, upload.upload_safety_id)
            self.assertEqual(events[0].metadata["final_action"], "accepted")
            self.assertEqual(events[0].metadata["av_verdict"], "clean")
            self.assertEqual(
                events[0].metadata["sanitized_original_filename"],
                "notes.txt",
            )
            upload_digest_prefix = upload.upload_safety_id.split(":")[2][:8]
            self.assertEqual(events[0].metadata["short_hash"], upload_digest_prefix)
            self.assertNotIn(
                "This is an English document",
                json.dumps(events[0].metadata),
            )
            self.assertNotIn("original/", json.dumps(events[0].metadata))
            self.assertEqual(service.get_pending_upload(42), upload)

    def test_required_blocked_scan_records_upload_safety_activity_metadata(self):
        with TemporaryDirectory() as temp_dir:
            sandbox = RecordingDocumentSandbox()
            scanner = FakeDocumentScanner(default_verdict=ScannerVerdict.INFECTED)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            activity_store = SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3")
            self.addCleanup(activity_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                document_sandbox=sandbox,
                document_scanner=scanner,
                require_upload_scan=True,
                file_storage=storage,
                activity_store=activity_store,
            )

            with self.assertRaises(DocumentScanRejectedError):
                service.store_uploaded_document(
                    user_telegram_id=42,
                    file_name="notes.txt",
                    content=b"Private source text must not leak.",
                    source_language="auto",
                )

            events = activity_store.list_events(
                surface=ActivitySurface.SECURITY,
                event_type="security.upload_safety.summary",
            )
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].action, "blocked")
            self.assertEqual(events[0].outcome, ActivityOutcome.BLOCKED.value)
            self.assertEqual(events[0].metadata["final_action"], "blocked")
            self.assertEqual(events[0].metadata["reason_code"], "infected")
            self.assertEqual(events[0].metadata["av_verdict"], "infected")
            self.assertEqual(
                events[0].metadata["sanitized_original_filename"],
                "notes.txt",
            )
            self.assertFalse(events[0].metadata["parser_access_granted"])
            self.assertFalse(events[0].metadata["worker_access_granted"])
            serialized_metadata = json.dumps(events[0].metadata)
            self.assertNotIn("Private source text", serialized_metadata)
            self.assertNotIn("quarantine/", serialized_metadata)

    def test_required_missing_scan_fails_before_parser_or_pending_upload(self):
        sandbox = RecordingDocumentSandbox()
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
            document_sandbox=sandbox,
            require_upload_scan=True,
        )

        with self.assertRaises(DocumentScanRejectedError) as error:
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"Private source text must not leak.",
                source_language="auto",
            )

        self.assertEqual(error.exception.verdict, None)
        self.assertNotIn("Private source text", str(error.exception))
        self.assertEqual(sandbox.extract_calls, [])
        self.assertIsNone(service.get_pending_upload(42))

    def test_oversized_upload_fails_before_scan_or_accepted_source_object(self):
        with TemporaryDirectory() as temp_dir:
            sandbox = RecordingDocumentSandbox()
            scanner = FakeDocumentScanner(default_verdict=ScannerVerdict.CLEAN)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=1,
                max_fragment_chars=20,
                document_sandbox=sandbox,
                document_scanner=scanner,
                require_upload_scan=True,
                file_storage=storage,
            )
            self.addCleanup(service.close)

            with self.assertRaises(FileTooLargeError):
                service.store_uploaded_document(
                    user_telegram_id=42,
                    file_name="large.txt",
                    content=(2 * 1024 * 1024) * b"x",
                    source_language="auto",
                )

            self.assertEqual(sandbox.extract_calls, [])
            self.assertEqual(scanner.calls, [])
            self.assertIsNone(service.get_pending_upload(42))
            self.assertFalse((Path(temp_dir) / "objects" / "original").exists())
            self.assertFalse((Path(temp_dir) / "objects" / "quarantine").exists())

    def test_failed_scan_verdicts_do_not_reach_parser_or_translation_workers(self):
        fail_closed_verdicts = (
            ScannerVerdict.INFECTED,
            ScannerVerdict.SCANNER_TIMEOUT,
            ScannerVerdict.SCANNER_UNAVAILABLE,
            ScannerVerdict.SCANNER_ERROR,
            ScannerVerdict.UNSUPPORTED,
            ScannerVerdict.SUSPICIOUS_CONTAINER,
        )

        for verdict in fail_closed_verdicts:
            with self.subTest(verdict=verdict.value), TemporaryDirectory() as temp_dir:
                sandbox = RecordingDocumentSandbox()
                scanner = FakeDocumentScanner(default_verdict=verdict)
                storage = LocalObjectStorage(Path(temp_dir) / "objects")
                persistent_store = SQLiteTranslationJobStore(
                    Path(temp_dir) / "jobs.sqlite3"
                )
                self.addCleanup(persistent_store.close)
                service = BotTranslationService(
                    job_repository=InMemoryTranslationJobRepository(),
                    pricing_rules=_pricing_rules(),
                    max_upload_mb=50,
                    max_fragment_chars=20,
                    document_sandbox=sandbox,
                    document_scanner=scanner,
                    require_upload_scan=True,
                    file_storage=storage,
                    persistent_job_store=persistent_store,
                    defer_persistent_jobs_to_worker=True,
                )

                with self.assertRaises(DocumentScanRejectedError) as error:
                    service.store_uploaded_document(
                        user_telegram_id=42,
                        file_name="notes.txt",
                        content=b"Private source text must not leak.",
                        source_language="auto",
                    )

                self.assertEqual(error.exception.verdict, verdict)
                self.assertNotIn("Private source text", str(error.exception))
                self.assertEqual(sandbox.extract_calls, [])
                self.assertIsNone(service.get_pending_upload(42))
                self.assertEqual(persistent_store.list_jobs_for_user("telegram:42"), [])
                self.assertTrue((Path(temp_dir) / "objects" / "quarantine").exists())
                self.assertFalse((Path(temp_dir) / "objects" / "original").exists())

    def test_clean_scanned_container_mismatch_fails_before_parser_or_original_source(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            sandbox = RecordingDocumentSandbox()
            scanner = FakeDocumentScanner(default_verdict=ScannerVerdict.CLEAN)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            ledger = InMemoryUploadSafetyLedger()
            activity_store = SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(activity_store.close)
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                document_sandbox=sandbox,
                document_scanner=scanner,
                require_upload_scan=True,
                file_storage=storage,
                upload_safety_ledger=ledger,
                activity_store=activity_store,
                persistent_job_store=persistent_store,
                defer_persistent_jobs_to_worker=True,
            )

            with self.assertRaises(DocumentScanRejectedError) as error:
                service.store_uploaded_document(
                    user_telegram_id=42,
                    file_name="book.docx",
                    content=b"plain text masquerading as docx",
                    source_language="auto",
                )

            self.assertNotIn("plain text", str(error.exception))
            self.assertEqual(sandbox.extract_calls, [])
            self.assertEqual(sandbox.plan_calls, [])
            self.assertIsNone(service.get_pending_upload(42))
            self.assertEqual(persistent_store.list_jobs_for_user("telegram:42"), [])
            self.assertTrue((Path(temp_dir) / "objects" / "quarantine").exists())
            self.assertFalse((Path(temp_dir) / "objects" / "original").exists())
            ((history),) = ledger.histories()
            self.assertEqual(
                [record.state for record in history],
                [
                    UploadSafetyState.RECEIVED,
                    UploadSafetyState.QUARANTINED,
                    UploadSafetyState.SCAN_STARTED,
                    UploadSafetyState.SCAN_CLEAN,
                    UploadSafetyState.CONTAINER_STARTED,
                    UploadSafetyState.CONTAINER_FAILED,
                    UploadSafetyState.REJECTED,
                ],
            )
            self.assertEqual(
                history[-2].metadata.safe_error_class,
                "zip_invalid_signature",
            )
            events = activity_store.list_events(
                surface=ActivitySurface.SECURITY,
                event_type="security.upload_safety.summary",
            )
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].metadata["av_verdict"], "clean")
            self.assertEqual(
                events[0].metadata["container_verdict"],
                "container_failed",
            )
            self.assertEqual(events[0].metadata["reason_code"], "zip_invalid_signature")
            serialized_metadata = json.dumps(events[0].metadata)
            self.assertEqual(
                events[0].metadata["sanitized_original_filename"],
                "book.docx",
            )
            self.assertNotIn("plain text", serialized_metadata)
            self.assertNotIn("quarantine/", serialized_metadata)

    def test_clean_scanned_unsafe_zip_container_records_metadata_only_block(self):
        with TemporaryDirectory() as temp_dir:
            sandbox = RecordingDocumentSandbox()
            scanner = FakeDocumentScanner(default_verdict=ScannerVerdict.CLEAN)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            activity_store = SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3")
            self.addCleanup(activity_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                document_sandbox=sandbox,
                document_scanner=scanner,
                require_upload_scan=True,
                file_storage=storage,
                activity_store=activity_store,
            )

            with self.assertRaises(DocumentScanRejectedError):
                service.store_uploaded_document(
                    user_telegram_id=42,
                    file_name="book.docx",
                    content=_make_docx_with_member("../private/source.xml", b"secret"),
                    source_language="auto",
                )

            self.assertEqual(sandbox.extract_calls, [])
            self.assertIsNone(service.get_pending_upload(42))
            self.assertFalse((Path(temp_dir) / "objects" / "original").exists())
            events = activity_store.list_events(
                surface=ActivitySurface.SECURITY,
                event_type="security.upload_safety.summary",
            )
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].action, "blocked")
            self.assertEqual(events[0].metadata["reason_code"], "unsafe_archive_path")
            serialized_metadata = json.dumps(events[0].metadata)
            self.assertNotIn("../private/source.xml", serialized_metadata)
            self.assertNotIn("secret", serialized_metadata)

    def test_clean_scanned_executable_archive_member_fails_before_parser_or_worker(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            sandbox = RecordingDocumentSandbox()
            scanner = FakeDocumentScanner(default_verdict=ScannerVerdict.CLEAN)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            activity_store = SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(activity_store.close)
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                document_sandbox=sandbox,
                document_scanner=scanner,
                require_upload_scan=True,
                file_storage=storage,
                activity_store=activity_store,
                persistent_job_store=persistent_store,
                defer_persistent_jobs_to_worker=True,
            )

            with self.assertRaises(DocumentScanRejectedError):
                service.store_uploaded_document(
                    user_telegram_id=42,
                    file_name="book.docx",
                    content=_make_docx_with_member(
                        "word/media/payload.exe",
                        b"MZ private payload",
                    ),
                    source_language="auto",
                )

            self.assertEqual(sandbox.extract_calls, [])
            self.assertEqual(sandbox.plan_calls, [])
            self.assertIsNone(service.get_pending_upload(42))
            self.assertEqual(persistent_store.list_jobs_for_user("telegram:42"), [])
            self.assertFalse((Path(temp_dir) / "objects" / "original").exists())
            events = activity_store.list_events(
                surface=ActivitySurface.SECURITY,
                event_type="security.upload_safety.summary",
            )
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].action, "blocked")
            self.assertFalse(events[0].metadata["parser_access_granted"])
            self.assertFalse(events[0].metadata["worker_access_granted"])
            self.assertEqual(
                events[0].metadata["reason_code"],
                "executable_archive_member",
            )
            serialized_metadata = json.dumps(events[0].metadata)
            self.assertNotIn("word/media/payload.exe", serialized_metadata)
            self.assertNotIn("MZ private payload", serialized_metadata)

    def test_unaccepted_ledger_source_cannot_reach_estimate_or_preview(self):
        with TemporaryDirectory() as temp_dir:
            content = b"This is an English document."
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            quarantine = storage.put_bytes(
                kind=StoredFileKind.QUARANTINE,
                file_name="notes.txt",
                content_type="text/plain; charset=utf-8",
                content=content,
            )
            ledger = InMemoryUploadSafetyLedger()
            upload_id = "upload-bypass"
            ledger.create_received(
                UploadSafetyMetadata(
                    upload_id=upload_id,
                    user_id="telegram:42",
                    quarantine_object_key=quarantine.object_key,
                    original_file_name="notes.txt",
                    document_format="txt",
                    size_bytes=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                )
            )
            ledger.transition(upload_id, UploadSafetyState.QUARANTINED)
            sandbox = RecordingDocumentSandbox()
            scanner = FakeDocumentScanner(default_verdict=ScannerVerdict.CLEAN)
            scan_result = scanner.scan(
                file_name="notes.txt",
                content=content,
                document_format=DocumentFormat.TXT,
            )
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                document_sandbox=sandbox,
                document_scanner=scanner,
                require_upload_scan=True,
                file_storage=storage,
                upload_safety_ledger=ledger,
            )
            with service._state_lock:
                service._pending_uploads[42] = PendingUpload(
                    user_telegram_id=42,
                    file_name="notes.txt",
                    content=content,
                    source_language="auto",
                    source_object_key=quarantine.object_key,
                    rights_confirmed=True,
                    translation_mode=TRANSLATION_MODE_BOOK_MANUSCRIPT,
                    scan_result=scan_result,
                    upload_safety_id=upload_id,
                )

            with self.assertRaises(DocumentScanRejectedError):
                service.prepare_pending_upload(
                    user_telegram_id=42,
                    target_language="uk",
                )
            self.assertEqual(sandbox.plan_calls, [])
            self.assertIsNone(service.get_pending(42))

            with service._state_lock:
                service._pending[42] = PendingTranslation(
                    user_telegram_id=42,
                    file_name="notes.txt",
                    content=content,
                    source_language="auto",
                    target_language="uk",
                    price_usd=0.0,
                    fragment_count=1,
                    source_object_key=quarantine.object_key,
                    rights_confirmed=True,
                    translation_mode=TRANSLATION_MODE_BOOK_MANUSCRIPT,
                    scan_result=scan_result,
                    upload_safety_id=upload_id,
                )
            with self.assertRaises(DocumentScanRejectedError):
                service.select_preview_candidate(user_telegram_id=42)
            self.assertEqual(sandbox.plan_calls, [])

    def test_restored_pending_upload_preserves_upload_safety_id(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            ledger = InMemoryUploadSafetyLedger()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                document_scanner=FakeDocumentScanner(
                    default_verdict=ScannerVerdict.CLEAN
                ),
                require_upload_scan=True,
                file_storage=storage,
                upload_safety_ledger=ledger,
            )
            uploaded = service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"This is an English document.",
                source_language="auto",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )

            restored = service.restore_pending_translation_upload(
                user_telegram_id=42
            )

            self.assertEqual(restored.upload_safety_id, uploaded.upload_safety_id)
            self.assertEqual(restored.source_object_key, uploaded.source_object_key)

    def test_unaccepted_persistent_resume_fails_closed_when_scan_gate_required(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="notes.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph.",
            )
            unit_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph.",
            )
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id=original.object_key,
                file_name="notes.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version=TXT_ADAPTER_VERSION,
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=original.object_key,
            )
            persistent_store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:1",),
                        source_text_hash=hashlib.sha256(
                            b"First paragraph."
                        ).hexdigest(),
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=unit_source.object_key,
                    )
                ],
            )
            persistent_store.pause_job(job.id)
            translator = RecordingTranslator()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                document_scanner=FakeDocumentScanner(
                    default_verdict=ScannerVerdict.CLEAN
                ),
                require_upload_scan=True,
                file_storage=storage,
                persistent_job_store=persistent_store,
                upload_safety_ledger=InMemoryUploadSafetyLedger(),
            )

            result = service.resume_user_book_translation(
                user_telegram_id=42,
                job_id=job.id,
                translator=translator,
            )
            summary = service.resume_user_book(user_telegram_id=42, job_id=job.id)

            self.assertIsNone(result)
            self.assertEqual(translator.requests, [])
            self.assertEqual(
                summary.status,
                PersistentTranslationJobStatus.PAUSED.value,
            )
            self.assertEqual(
                persistent_store.get_job(job.id).status,
                PersistentTranslationJobStatus.PAUSED,
            )

    def test_accepted_persistent_resume_keeps_ledger_binding(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            ledger = InMemoryUploadSafetyLedger()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                document_scanner=FakeDocumentScanner(
                    default_verdict=ScannerVerdict.CLEAN
                ),
                require_upload_scan=True,
                file_storage=storage,
                persistent_job_store=persistent_store,
                upload_safety_ledger=ledger,
            )
            uploaded = service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"First paragraph.",
                source_language="en",
            )
            unit_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph.",
            )
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id=uploaded.source_object_key,
                file_name="notes.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version=TXT_ADAPTER_VERSION,
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=uploaded.source_object_key,
            )
            persistent_store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:1",),
                        source_text_hash=hashlib.sha256(
                            b"First paragraph."
                        ).hexdigest(),
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=unit_source.object_key,
                    )
                ],
            )
            persistent_store.pause_job(job.id)

            result = service.resume_user_book_translation(
                user_telegram_id=42,
                job_id=job.id,
                translator=RecordingTranslator(),
            )

            self.assertEqual(result.status, TranslationJobStatus.READY)
            self.assertEqual(
                ledger.upload_id_for_accepted_source(uploaded.source_object_key),
                uploaded.upload_safety_id,
            )

    def test_persistent_resume_defaults_missing_glossary_mode_to_without_glossary(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            ledger = InMemoryUploadSafetyLedger()
            run_log_root = Path(temp_dir) / "runs"
            seen_glossary_modes: list[str | None] = []

            def hook_builder(pending: PendingTranslation, document_kind: DocumentKind):
                seen_glossary_modes.append(pending.glossary_mode)
                return None

            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                document_scanner=FakeDocumentScanner(
                    default_verdict=ScannerVerdict.CLEAN
                ),
                require_upload_scan=True,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
                upload_safety_ledger=ledger,
                glossary_runtime_hook_builder=hook_builder,
            )
            uploaded = service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"First paragraph.",
                source_language="en",
            )
            unit_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph.",
            )
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id=uploaded.source_object_key,
                file_name="notes.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version=TXT_ADAPTER_VERSION,
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=uploaded.source_object_key,
            )
            persistent_store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:1",),
                        source_text_hash=hashlib.sha256(
                            b"First paragraph."
                        ).hexdigest(),
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=unit_source.object_key,
                    )
                ],
            )
            persistent_store.pause_job(job.id)

            result = service.resume_user_book_translation(
                user_telegram_id=42,
                job_id=job.id,
                translator=RecordingTranslator(),
            )

            self.assertEqual(result.status, TranslationJobStatus.READY)
            self.assertEqual(seen_glossary_modes, [])
            run_json_paths = list(run_log_root.glob("*/run.json"))
            self.assertEqual(len(run_json_paths), 1)
            run_snapshot = json.loads(run_json_paths[0].read_text(encoding="utf-8"))
            run_policy = json.loads(run_snapshot["translation_policy"])
            self.assertEqual(run_policy["glossary_mode"], GLOSSARY_MODE_WITHOUT)

    def test_persistent_resume_preserves_explicit_without_glossary(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            ledger = InMemoryUploadSafetyLedger()
            run_log_root = Path(temp_dir) / "runs"
            seen_glossary_modes: list[str | None] = []

            def hook_builder(pending: PendingTranslation, document_kind: DocumentKind):
                seen_glossary_modes.append(pending.glossary_mode)
                return None

            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                document_scanner=FakeDocumentScanner(
                    default_verdict=ScannerVerdict.CLEAN
                ),
                require_upload_scan=True,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
                upload_safety_ledger=ledger,
                glossary_runtime_hook_builder=hook_builder,
            )
            uploaded = service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"First paragraph.",
                source_language="en",
            )
            unit_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph.",
            )
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id=uploaded.source_object_key,
                file_name="notes.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version=TXT_ADAPTER_VERSION,
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=uploaded.source_object_key,
                translation_policy=json.dumps(
                    {"glossary_mode": GLOSSARY_MODE_WITHOUT},
                    ensure_ascii=False,
                ),
            )
            persistent_store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:1",),
                        source_text_hash=hashlib.sha256(
                            b"First paragraph."
                        ).hexdigest(),
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=unit_source.object_key,
                    )
                ],
            )
            persistent_store.pause_job(job.id)

            result = service.resume_user_book_translation(
                user_telegram_id=42,
                job_id=job.id,
                translator=RecordingTranslator(),
            )

            self.assertEqual(result.status, TranslationJobStatus.READY)
            self.assertEqual(seen_glossary_modes, [])
            run_json_paths = list(run_log_root.glob("*/run.json"))
            self.assertEqual(len(run_json_paths), 1)
            run_snapshot = json.loads(run_json_paths[0].read_text(encoding="utf-8"))
            run_policy = json.loads(run_snapshot["translation_policy"])
            self.assertEqual(run_policy["glossary_mode"], GLOSSARY_MODE_WITHOUT)

    def test_uses_persistent_user_settings_when_repository_is_configured(self):
        with TemporaryDirectory() as temp_dir:
            settings = SQLiteUserSettingsRepository(Path(temp_dir) / "settings.sqlite3")
            self.addCleanup(settings.close)
            first = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                user_settings_repository=settings,
            )

            first.set_interface_language(user_telegram_id=42, language_code="fr")
            first.set_progress_preview_enabled(user_telegram_id=42, enabled=False)

            second = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                user_settings_repository=settings,
            )

            self.assertEqual(second.get_interface_language(42), "fr")
            self.assertFalse(second.get_progress_preview_enabled(42))

    def test_reset_user_settings_clears_language_and_preview_preference(self):
        with TemporaryDirectory() as temp_dir:
            settings = SQLiteUserSettingsRepository(Path(temp_dir) / "settings.sqlite3")
            self.addCleanup(settings.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                user_settings_repository=settings,
            )
            service.set_interface_language(user_telegram_id=42, language_code="uk")
            service.set_progress_preview_enabled(user_telegram_id=42, enabled=False)

            service.reset_user_settings(42)

            self.assertFalse(service.has_interface_language(42))
            self.assertEqual(service.get_interface_language(42), "en")
            self.assertTrue(service.get_progress_preview_enabled(42))

    def test_discarding_pending_translation_keeps_interface_language(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.set_interface_language(user_telegram_id=42, language_code="ru")
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.",
            source_language="en",
            target_language="uk",
        )

        service.discard_pending_translation(42)

        self.assertEqual(service.get_interface_language(42), "ru")

    def test_stores_progress_preview_preference_per_user(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )

        self.assertTrue(service.get_progress_preview_enabled(42))

        service.set_progress_preview_enabled(
            user_telegram_id=42,
            enabled=False,
        )

        self.assertFalse(service.get_progress_preview_enabled(42))
        self.assertTrue(service.get_progress_preview_enabled(100))

    def test_upload_waits_for_translation_language_before_estimate(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )

        upload = service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"This is an English document.",
            source_language="auto",
        )

        self.assertEqual(
            upload,
            PendingUpload(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"This is an English document.",
                source_language="auto",
                source_language_display="English",
                attempt_id=upload.attempt_id,
            ),
        )
        self.assertEqual(service.get_pending_upload(42), upload)

    def test_upload_requires_rights_confirmation_before_language_choice(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"This is an English document.",
            source_language="auto",
        )

        with self.assertRaises(RightsConfirmationRequired):
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )

        self.assertIsNotNone(service.get_pending_upload(42))
        self.assertIsNone(service.get_pending(42))

    def test_rights_confirmation_allows_mode_choice_and_is_idempotent(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"This is an English document.",
            source_language="auto",
        )

        first = service.confirm_pending_upload_rights(user_telegram_id=42)
        second = service.confirm_pending_upload_rights(user_telegram_id=42)
        selected = self._select_default_translation_mode(service)
        pending = service.prepare_pending_upload(
            user_telegram_id=42,
            target_language="uk",
        )

        self.assertEqual(first, second)
        self.assertEqual(selected.translation_mode, TRANSLATION_MODE_BOOK_MANUSCRIPT)
        self.assertTrue(pending.rights_confirmed)
        self.assertEqual(pending.translation_mode, TRANSLATION_MODE_BOOK_MANUSCRIPT)
        self.assertEqual(pending.rights_confirmation_version, "rights-v1")
        self.assertEqual(pending.rights_confirmation_source, "telegram_button")
        self.assertIsNotNone(pending.rights_confirmed_at)

    def test_rights_confirmation_records_activity_metadata_only(self):
        with TemporaryDirectory() as temp_dir:
            activity_store = SQLiteUserActivityStore(
                Path(temp_dir) / "activity.sqlite3"
            )
            self.addCleanup(activity_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                activity_store=activity_store,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"This is an English document.",
                source_language="auto",
            )

            confirmed = service.confirm_pending_upload_rights(user_telegram_id=42)

            events = activity_store.list_events(
                actor_id="telegram:42",
                event_type="document.rights_confirmed",
            )
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(event.action, "confirmed")
            self.assertEqual(event.target_type, "document")
            self.assertEqual(event.target_id, "notes.txt")
            self.assertIsNotNone(event.created_at)
            self.assertEqual(
                event.metadata,
                {
                    "confirmed": True,
                    "source": confirmed.rights_confirmation_source,
                    "version": confirmed.rights_confirmation_version,
                },
            )
            self.assertNotIn("This is an English document", json.dumps(event.metadata))

    def test_translation_mode_is_required_before_language_choice(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"This is an English document.",
            source_language="auto",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)

        with self.assertRaises(TranslationModeRequired):
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )

        self.assertIsNotNone(service.get_pending_upload(42))
        self.assertIsNone(service.get_pending(42))

    def test_translation_mode_requires_rights_confirmation(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"This is an English document.",
            source_language="auto",
        )

        with self.assertRaises(RightsConfirmationRequired):
            self._select_default_translation_mode(service)

    def test_translation_mode_rejects_unsupported_identifier(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"This is an English document.",
            source_language="auto",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)

        with self.assertRaises(ValueError):
            service.select_pending_upload_translation_mode(
                user_telegram_id=42,
                translation_mode="provider_magic",
            )

    def test_unselected_glossary_mode_defaults_to_automatic_before_preview(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=200,
        )
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One meaningful paragraph for preview.",
            source_language="en",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        self._select_default_translation_mode(service)
        service.prepare_pending_upload(
            user_telegram_id=42,
            target_language="uk",
            glossary_mode=None,
        )

        preview = service.generate_preview_translation(
            user_telegram_id=42,
            translator=RecordingTranslator(),
        )

        self.assertEqual(preview.metadata["glossary_mode"], GLOSSARY_MODE_WITH)
        pending = service.get_pending(42)
        self.assertIsNotNone(pending)
        self.assertEqual(pending.glossary_mode, GLOSSARY_MODE_WITH)

    def test_select_pending_translation_glossary_mode_records_safe_metadata(self):
        with TemporaryDirectory() as temp_dir:
            activity_store = SQLiteUserActivityStore(
                Path(temp_dir) / "activity.sqlite3"
            )
            self.addCleanup(activity_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=200,
                activity_store=activity_store,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One meaningful paragraph for preview.",
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
                glossary_mode=GLOSSARY_MODE_WITHOUT,
            )

            selected = service.select_pending_translation_glossary_mode(
                user_telegram_id=42,
                glossary_mode=GLOSSARY_MODE_WITH,
            )

            self.assertEqual(selected.glossary_mode, GLOSSARY_MODE_WITH)
            self.assertFalse(selected.preview_shown)
            self.assertFalse(selected.preview_accepted)
            events = activity_store.list_events(actor_id="telegram:42")
            glossary_events = [
                event
                for event in events
                if event.event_type == "translation.glossary_mode.selected"
            ]
            self.assertEqual(len(glossary_events), 1)
            metadata = glossary_events[0].metadata
            self.assertEqual(metadata["glossary_mode"], GLOSSARY_MODE_WITH)
            serialized = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
            self.assertNotIn("One meaningful paragraph", serialized)
            self.assertNotIn("translation_batch", serialized)

    def test_can_restore_pending_translation_to_language_selection(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"This is an English document.",
            source_language="auto",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        self._select_default_translation_mode(service)
        service.prepare_pending_upload(
            user_telegram_id=42,
            target_language="uk",
        )

        restored = service.restore_pending_translation_upload(user_telegram_id=42)

        self.assertIsNotNone(restored)
        self.assertIsNone(service.get_pending(42))
        self.assertIsNotNone(service.get_pending_upload(42))
        self.assertTrue(restored.rights_confirmed)
        self.assertEqual(restored.translation_mode, TRANSLATION_MODE_BOOK_MANUSCRIPT)
        self.assertEqual(restored.file_name, "notes.txt")

    def test_upload_can_be_persisted_to_object_storage_before_estimate(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                file_storage=storage,
            )

            upload = service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"This is an English document.",
                source_language="auto",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            pending = service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )

            self.assertIsNotNone(upload.source_object_key)
            self.assertEqual(upload.source_object_key, pending.source_object_key)
            self.assertEqual(
                storage.get_bytes(upload.source_object_key), upload.content
            )
            self.assertEqual(
                storage.get_metadata(upload.source_object_key).kind,
                StoredFileKind.ORIGINAL,
            )

    def test_auto_language_display_lists_mixed_document_languages(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=200,
        )

        upload = service.store_uploaded_document(
            user_telegram_id=42,
            file_name="mixed.txt",
            content=(
                "Русский текст документа. Это большая часть книги, "
                "русский язык здесь основной, это документ для перевода.\n"
                "English: The quick brown fox jumps over the lazy dog.\n"
                "Polski: Zażółć gęślą jaźń.\n"
                "Nederlands: Ik fiets vandaag naar Zwolle."
            ).encode(),
            source_language="auto",
        )

        self.assertEqual(
            upload.source_language_display,
            "Russian (admixtures: English, Polish, Dutch)",
        )

    def test_same_language_auto_display_with_admixtures_is_blocked_before_preview(self):
        guard = RecordingBetaSafetyGuard()
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=200,
            beta_safety_guard=guard,
        )
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="mixed.txt",
            content=(
                "Русский текст документа. Это большая часть книги, "
                "русский язык здесь основной, это документ для перевода.\n"
                "English: The quick brown fox jumps over the lazy dog."
            ).encode(),
            source_language="auto",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        self._select_default_translation_mode(service)

        with self.assertRaisesRegex(ValueError, "already.*Russian"):
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="ru",
            )

        self.assertIsNotNone(service.get_pending_upload(42))
        self.assertIsNone(service.get_pending(42))
        self.assertEqual(guard.reservations, [])
        self.assertEqual(guard.usage_events, [])
        self.assertEqual(guard.consumed, [])

    def test_prepares_estimate_from_pending_upload_after_translation_language_choice(
        self,
    ):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"This is an English document.",
            source_language="auto",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        self._select_default_translation_mode(service)

        pending = service.prepare_pending_upload(
            user_telegram_id=42,
            target_language="uk",
        )

        self.assertEqual(pending.target_language, "uk")
        self.assertEqual(pending.source_language_display, "English")
        self.assertIsNone(service.get_pending_upload(42))
        self.assertEqual(service.get_pending(42), pending)

    def test_selects_bounded_txt_preview_candidate_without_creating_job(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=80,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=(
                    b"# Contents\n\n"
                    b"First meaningful paragraph for preview quality.\n\n"
                    b"Second meaningful paragraph for language.\n\n"
                    b"Third meaningful paragraph for parameters.\n\n"
                    b"Fourth paragraph stays outside the preview candidate."
                ),
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(user_telegram_id=42, target_language="uk")

            candidate = service.select_preview_candidate(user_telegram_id=42)

            self.assertEqual(candidate.document_kind, DocumentKind.TXT)
            self.assertEqual(candidate.target_language, "uk")
            self.assertEqual(candidate.selected_block_count, 3)
            self.assertEqual(
                candidate.translation_mode,
                TRANSLATION_MODE_BOOK_MANUSCRIPT,
            )
            self.assertEqual(
                candidate.metadata["translation_mode"],
                TRANSLATION_MODE_BOOK_MANUSCRIPT,
            )
            self.assertEqual(candidate.character_count, len(candidate.source_text))
            self.assertLessEqual(
                candidate.character_count,
                candidate.max_character_count,
            )
            self.assertIn("First meaningful paragraph", candidate.source_text)
            self.assertNotIn("Contents", candidate.source_text)
            self.assertNotIn("Fourth paragraph", candidate.source_text)
            self.assertEqual(
                persistent_store.list_jobs_for_user("telegram:42"),
                [],
            )

    def test_selects_docx_preview_candidate(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=1_000,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="contract.docx",
            content=_make_docx(
                """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body>
                    <w:p><w:r>
                      <w:t>First meaningful contract paragraph.</w:t>
                    </w:r></w:p>
                    <w:p><w:r>
                      <w:t>Second meaningful contract paragraph.</w:t>
                    </w:r></w:p>
                  </w:body>
                </w:document>
                """
            ),
            source_language="en",
            target_language="uk",
        )

        candidate = service.select_preview_candidate(user_telegram_id=42)

        self.assertEqual(candidate.document_kind, DocumentKind.DOCX)
        self.assertEqual(
            candidate.source_block_ids,
            ("docx:word/document.xml:0", "docx:word/document.xml:1"),
        )
        self.assertIn("First meaningful contract paragraph.", candidate.source_text)
        self.assertIsNone(candidate.translation_mode)
        self.assertNotIn("translation_mode", candidate.metadata)

    def test_docx_preview_candidate_uses_selected_document_form_mode(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=1_000,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="application.docx",
            content=_make_docx(
                """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body>
                    <w:p><w:r>
                      <w:t>Structured application text for preview.</w:t>
                    </w:r></w:p>
                  </w:body>
                </w:document>
                """
            ),
            source_language="uk",
            target_language="ru",
            translation_mode=TRANSLATION_MODE_DOCUMENT_FORM,
        )

        candidate = service.select_preview_candidate(user_telegram_id=42)

        self.assertEqual(candidate.translation_mode, TRANSLATION_MODE_DOCUMENT_FORM)
        self.assertEqual(
            candidate.metadata["translation_mode"],
            TRANSLATION_MODE_DOCUMENT_FORM,
        )
        self.assertEqual(
            candidate.metadata["docx_translation_mode_profile"],
            DOCX_TRANSLATION_MODE_DOCUMENT_FORM_PROFILE,
        )

    def test_docx_preview_candidate_uses_selected_book_manuscript_mode(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=1_000,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="chapter.docx",
            content=_make_docx(
                """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body>
                    <w:p><w:r>
                      <w:t>Natural prose paragraph text for preview.</w:t>
                    </w:r></w:p>
                  </w:body>
                </w:document>
                """
            ),
            source_language="uk",
            target_language="ru",
            translation_mode=TRANSLATION_MODE_BOOK_MANUSCRIPT,
        )

        candidate = service.select_preview_candidate(user_telegram_id=42)

        self.assertEqual(candidate.translation_mode, TRANSLATION_MODE_BOOK_MANUSCRIPT)
        self.assertEqual(
            candidate.metadata["translation_mode"],
            TRANSLATION_MODE_BOOK_MANUSCRIPT,
        )
        self.assertEqual(
            candidate.metadata["docx_translation_mode_profile"],
            DOCX_TRANSLATION_MODE_BOOK_MANUSCRIPT_PROFILE,
        )

    def test_docx_preview_candidate_passes_selected_mode_to_sandbox(self):
        sandbox = RecordingDocumentSandbox()
        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r>
                  <w:t>Structured application text for sandbox preview.</w:t>
                </w:r></w:p>
              </w:body>
            </w:document>
            """
        )
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=1_000,
            document_sandbox=sandbox,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="application.docx",
            content=content,
            source_language="uk",
            target_language="ru",
            translation_mode=TRANSLATION_MODE_DOCUMENT_FORM,
        )

        service.select_preview_candidate(user_telegram_id=42)

        self.assertEqual(
            sandbox.plan_calls,
            [
                (
                    DocumentFormat.DOCX,
                    content,
                    1_000,
                    TRANSLATION_MODE_DOCUMENT_FORM,
                ),
                (
                    DocumentFormat.DOCX,
                    content,
                    1_000,
                    TRANSLATION_MODE_DOCUMENT_FORM,
                ),
            ],
        )

    def test_selects_epub_preview_candidate_after_navigation(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=1_000,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="book.epub",
            content=_make_epub(
                {
                    "OPS/nav.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body><nav><p>Contents</p><p>Chapter 1</p></nav></body>
                    </html>
                    """,
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body>
                        <h1>Chapter 1</h1>
                        <p>First meaningful book paragraph for preview.</p>
                        <p>Second meaningful book paragraph for preview.</p>
                      </body>
                    </html>
                    """,
                }
            ),
            source_language="en",
            target_language="uk",
        )

        candidate = service.select_preview_candidate(user_telegram_id=42)

        self.assertEqual(candidate.document_kind, DocumentKind.EPUB)
        self.assertIn("First meaningful book paragraph", candidate.source_text)
        self.assertNotIn("Contents", candidate.source_text)
        self.assertFalse(
            any(
                block_id.startswith("epub:aux:")
                for block_id in candidate.source_block_ids
            )
        )

    def test_selects_epub_preview_candidate_after_front_matter(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=1_000,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="book.epub",
            content=_make_epub(
                {
                    "OPS/title.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body>
                        <h1>Title Page</h1>
                        <p>Folio Loom Press</p>
                        <p>Copyright © 2026 Folio Loom Press</p>
                        <p>ISBN 978-1-4028-9462-6</p>
                        <p>12 Example Street, Kyiv 01001</p>
                        <p>https://publisher.example/books</p>
                        <p>contact@publisher.example</p>
                      </body>
                    </html>
                    """,
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body>
                        <h1>Chapter 1</h1>
                        <p>The first real chapter opened with a quiet room.</p>
                        <p>The second paragraph gave the reader a voice.</p>
                      </body>
                    </html>
                    """,
                }
            ),
            source_language="en",
            target_language="uk",
        )

        candidate = service.select_preview_candidate(user_telegram_id=42)

        self.assertEqual(candidate.document_kind, DocumentKind.EPUB)
        self.assertIn("The first real chapter", candidate.source_text)
        self.assertNotIn("Folio Loom Press", candidate.source_text)
        self.assertNotIn("Copyright", candidate.source_text)
        self.assertNotIn("ISBN", candidate.source_text)
        self.assertNotIn("Example Street", candidate.source_text)
        self.assertNotIn("publisher.example", candidate.source_text)
        self.assertNotIn("contact@", candidate.source_text)

    def test_preview_candidate_requires_pending_translation(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )

        with self.assertRaisesRegex(
            ValueError,
            "No uploaded document is waiting for preview selection",
        ):
            service.select_preview_candidate(user_telegram_id=42)

    def test_preview_candidate_requires_rights_confirmation(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"First meaningful paragraph.",
            source_language="en",
            target_language="uk",
            rights_confirmed=False,
        )

        with self.assertRaises(RightsConfirmationRequired):
            service.select_preview_candidate(user_telegram_id=42)

    def test_preview_candidate_rejects_no_previewable_text(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"# Contents\n\n- Chapter 1",
            source_language="en",
            target_language="uk",
        )

        with self.assertRaisesRegex(
            ValueError,
            "Document does not contain text suitable for a preview",
        ):
            service.select_preview_candidate(user_telegram_id=42)

    def test_preview_candidate_metadata_does_not_include_raw_text(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"Secret preview sentence stays in payload only.",
            source_language="en",
            target_language="uk",
        )

        candidate = service.select_preview_candidate(user_telegram_id=42)

        self.assertIn("Secret preview sentence", candidate.source_text)
        self.assertNotIn(
            "Secret preview sentence",
            json.dumps(candidate.metadata, ensure_ascii=False),
        )

    def test_run_log_policy_book_profile_excludes_entity_context_text(self):
        from zipfile import ZipFile

        with TemporaryDirectory() as temp_dir:
            run_log_root = Path(temp_dir) / "translation-runs"
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=80,
                translation_run_log_root=run_log_root,
            )
            pending = PendingTranslation(
                user_telegram_id=42,
                file_name="chapter.txt",
                content=(
                    b"Alice met Bob in Paris. "
                    b"Quiet chapter opening kept the narrator voice."
                ),
                source_language="en",
                target_language="uk",
                price_usd=0.0,
                fragment_count=1,
                rights_confirmed=True,
                translation_mode=TRANSLATION_MODE_BOOK_MANUSCRIPT,
            )

            logger = service._start_translation_run_logger(
                pending=pending,
                document_kind=DocumentKind.TXT,
                job_id="job-policy-redaction",
                translator=RecordingTranslator(),
            )

            self.assertIsNotNone(logger)
            run_text = (logger.run_dir / "run.json").read_text(encoding="utf-8")
            archive = build_translation_run_archive(run_log_root, logger.run_dir.name)
            self.assertIsNotNone(archive)
            with ZipFile(io.BytesIO(archive.content)) as archive_file:
                archive_text = "\n".join(
                    archive_file.read(name).decode("utf-8", errors="ignore")
                    for name in archive_file.namelist()
                )

        for artifact_text in (run_text, archive_text):
            self.assertIn("book_manuscript", artifact_text)
            self.assertIn("book-manuscript-v1", artifact_text)
            self.assertNotIn("Book/manuscript mode", artifact_text)
            self.assertNotIn("Alice", artifact_text)
            self.assertNotIn("Bob", artifact_text)
            self.assertNotIn("Paris", artifact_text)
            self.assertNotIn("translation_context_memory", artifact_text)
            self.assertNotIn("entity_choices", artifact_text)
            self.assertNotIn("source_text", artifact_text)
            self.assertNotIn("target_text", artifact_text)

    def test_generates_preview_translation_with_beta_safety_accounting(self):
        with TemporaryDirectory() as temp_dir:
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            activity_store = SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3")
            self.addCleanup(persistent_store.close)
            self.addCleanup(activity_store.close)
            guard = RecordingBetaSafetyGuard()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=80,
                persistent_job_store=persistent_store,
                activity_store=activity_store,
                translation_run_log_root=Path(temp_dir) / "translation-runs",
                beta_safety_guard=guard,
            )
            service.prepare_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"Secret preview source is only for Telegram preview.",
                source_language="en",
                target_language="uk",
            )
            events_before_preview = activity_store.list_events(actor_id="telegram:42")

            preview = service.generate_preview_translation(
                user_telegram_id=42,
                translator=UsageRecordingTranslator(),
            )

            self.assertEqual(
                preview.text,
                "[uk] Secret preview source is only for Telegram preview.",
            )
            self.assertTrue(preview.preview_id.startswith("preview:42:"))
            self.assertEqual(preview.prompt_tokens, 11)
            self.assertEqual(preview.completion_tokens, 7)
            self.assertEqual(len(guard.reservations), 1)
            self.assertEqual(guard.reservations[0][0], preview.preview_id)
            self.assertEqual(guard.reservations[0][1], "telegram:42")
            self.assertEqual(guard.usage_events[0][0], preview.preview_id)
            self.assertEqual(guard.usage_events[0][1], "telegram:42")
            self.assertEqual(guard.usage_events[0][2], f"{preview.preview_id}:preview")
            self.assertEqual(guard.usage_events[0][3:], (11, 7))
            self.assertEqual(guard.consumed, [preview.preview_id])
            self.assertEqual(persistent_store.list_jobs_for_user("telegram:42"), [])
            self.assertFalse((Path(temp_dir) / "translation-runs").exists())
            self.assertEqual(
                activity_store.list_events(actor_id="telegram:42"),
                events_before_preview,
            )
            self.assertNotIn(
                "Secret preview source",
                json.dumps(preview.metadata, ensure_ascii=False),
            )

    def test_preview_translation_metadata_includes_selected_mode(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=80,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"Meaningful preview source for selected mode.",
            source_language="en",
            target_language="uk",
            translation_mode=TRANSLATION_MODE_BOOK_MANUSCRIPT,
        )

        preview = service.generate_preview_translation(
            user_telegram_id=42,
            translator=UsageRecordingTranslator(),
        )

        self.assertEqual(
            preview.metadata["translation_mode"],
            TRANSLATION_MODE_BOOK_MANUSCRIPT,
        )

    def test_preview_translation_blocks_beta_safety_denial_before_provider_call(self):
        guard = RecordingBetaSafetyGuard(
            allowed=False,
            denied_reason_code="kill_switch",
            denied_safe_message="Translations are temporarily paused.",
        )
        translator = RecordingTranslator()
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=80,
            beta_safety_guard=guard,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"Preview source should not reach provider.",
            source_language="en",
            target_language="uk",
        )

        with self.assertRaisesRegex(
            PreviewTranslationError,
            "Translations are temporarily paused.",
        ):
            service.generate_preview_translation(
                user_telegram_id=42,
                translator=translator,
            )

        self.assertEqual(translator.requests, [])
        self.assertEqual(guard.reservations, [])
        self.assertEqual(guard.usage_events, [])

    def test_preview_translation_requires_beta_access(self):
        translator = RecordingTranslator()
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=80,
            beta_access_policy=BetaAccessPolicy.from_telegram_ids(
                (42,),
                enabled=True,
            ),
        )
        pending = service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"First meaningful paragraph.",
            source_language="en",
            target_language="uk",
        )
        service._pending[100] = pending

        with self.assertRaises(BetaAccessDenied):
            service.generate_preview_translation(
                user_telegram_id=100,
                translator=translator,
            )

        self.assertEqual(translator.requests, [])

    def test_preview_translation_blocks_duplicate_retry_for_same_pending_document(self):
        guard = RecordingBetaSafetyGuard()
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=80,
            beta_safety_guard=guard,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One meaningful preview paragraph.",
            source_language="en",
            target_language="uk",
        )

        first = service.generate_preview_translation(
            user_telegram_id=42,
            translator=RecordingTranslator(),
        )
        with self.assertRaisesRegex(
            DuplicatePreviewError,
            "Preview has already been generated",
        ):
            service.generate_preview_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

        self.assertEqual(len(guard.reservations), 1)
        self.assertEqual(guard.reservations[0][0], first.preview_id)
        self.assertEqual(len(guard.usage_events), 1)

    def test_repeated_preview_after_translation_uses_fresh_attempt_id(self):
        guard = RecordingBetaSafetyGuard()
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=80,
            beta_safety_guard=guard,
        )
        content = b"One meaningful preview paragraph."
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=content,
            source_language="en",
            target_language="uk",
            translation_mode=TRANSLATION_MODE_BOOK_MANUSCRIPT,
        )
        first_preview = service.generate_preview_translation(
            user_telegram_id=42,
            translator=RecordingTranslator(),
        )
        service.mark_pending_translation_preview_shown(
            user_telegram_id=42,
            preview_id=first_preview.preview_id,
        )
        service.accept_pending_translation_preview(user_telegram_id=42)
        completed = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=RecordingTranslator(),
        )
        self.assertEqual(completed.status, TranslationJobStatus.READY)

        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=content,
            source_language="en",
            target_language="uk",
            translation_mode=TRANSLATION_MODE_BOOK_MANUSCRIPT,
        )
        next_preview = service.generate_preview_translation(
            user_telegram_id=42,
            translator=RecordingTranslator(),
        )

        self.assertNotEqual(next_preview.preview_id, first_preview.preview_id)
        self.assertEqual(len(guard.reservations), 2)
        self.assertEqual(guard.reservations[0][0], first_preview.preview_id)
        self.assertEqual(guard.reservations[1][0], next_preview.preview_id)
        self.assertEqual(len(guard.usage_events), 2)

    def test_ready_duplicate_match_is_same_user_and_does_not_reserve_preview(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            guard = RecordingBetaSafetyGuard()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                file_storage=storage,
                persistent_job_store=persistent_store,
                beta_safety_guard=guard,
            )
            content = b"One meaningful paragraph for duplicate detection."
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            first_pending = service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            first_preview = service.generate_preview_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )
            service.mark_pending_translation_preview_shown(
                user_telegram_id=42,
                preview_id=first_preview.preview_id,
            )
            service.accept_pending_translation_preview(user_telegram_id=42)
            completed = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )
            self.assertEqual(completed.status, TranslationJobStatus.READY)

            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="copy.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            second_pending = service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            reservations_before_duplicate_lookup = list(guard.reservations)

            match = service.find_pending_translation_duplicate(user_telegram_id=42)

            self.assertIsNotNone(match)
            self.assertEqual(match.job_id, completed.id)
            self.assertEqual(match.status, "ready")
            self.assertTrue(match.can_download_existing)
            self.assertTrue(match.can_translate_again)
            self.assertEqual(
                guard.reservations,
                reservations_before_duplicate_lookup,
            )
            self.assertNotEqual(first_pending.attempt_id, second_pending.attempt_id)

            service.store_uploaded_document(
                user_telegram_id=100,
                file_name="copy.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=100)
            self._select_default_translation_mode(service, user_telegram_id=100)
            service.prepare_pending_upload(user_telegram_id=100, target_language="uk")

            self.assertIsNone(
                service.find_pending_translation_duplicate(user_telegram_id=100)
            )

    def test_duplicate_match_requires_approved_identity_fields(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            content = b"One meaningful paragraph for duplicate identity."
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(
                service,
                translation_mode=TRANSLATION_MODE_BOOK_MANUSCRIPT,
            )
            service.prepare_pending_upload(user_telegram_id=42, target_language="uk")
            preview = service.generate_preview_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )
            service.mark_pending_translation_preview_shown(
                user_telegram_id=42,
                preview_id=preview.preview_id,
            )
            service.accept_pending_translation_preview(user_telegram_id=42)
            service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(
                service,
                translation_mode=TRANSLATION_MODE_DOCUMENT_FORM,
            )
            service.prepare_pending_upload(user_telegram_id=42, target_language="uk")

            self.assertIsNone(
                service.find_pending_translation_duplicate(user_telegram_id=42)
            )

            service.discard_pending_translation(42)
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=content,
                source_language="auto",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(
                service,
                translation_mode=TRANSLATION_MODE_BOOK_MANUSCRIPT,
            )
            service.prepare_pending_upload(user_telegram_id=42, target_language="uk")

            self.assertIsNone(
                service.find_pending_translation_duplicate(user_telegram_id=42)
            )

    def test_duplicate_lookup_skips_missing_source_and_legacy_policy(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            content = b"One meaningful paragraph for metadata edge cases."
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(user_telegram_id=42, target_language="uk")
            preview = service.generate_preview_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )
            service.mark_pending_translation_preview_shown(
                user_telegram_id=42,
                preview_id=preview.preview_id,
            )
            service.accept_pending_translation_preview(user_telegram_id=42)
            completed = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )
            original_policy = persistent_store.get_job(completed.id).translation_policy

            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="copy.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(user_telegram_id=42, target_language="uk")
            self.assertIsNotNone(
                service.find_pending_translation_duplicate(user_telegram_id=42)
            )

            persistent_store._connection.execute(
                "UPDATE translation_jobs SET translation_policy = NULL WHERE id = ?",
                (completed.id,),
            )
            self.assertIsNone(
                service.find_pending_translation_duplicate(user_telegram_id=42)
            )

            persistent_store._connection.execute(
                "UPDATE translation_jobs SET translation_policy = ? WHERE id = ?",
                (original_policy, completed.id),
            )
            service.discard_pending_translation(42)
            original_job = persistent_store.get_job(completed.id)
            self.assertTrue(storage.delete(original_job.source_object_key))
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="copy.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(user_telegram_id=42, target_language="uk")

            self.assertIsNone(
                service.find_pending_translation_duplicate(user_telegram_id=42)
            )

    def test_active_duplicate_does_not_allow_concurrent_translate_again(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                file_storage=storage,
                persistent_job_store=persistent_store,
                defer_persistent_jobs_to_worker=True,
            )
            content = b"One meaningful paragraph for active duplicate."
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(user_telegram_id=42, target_language="uk")
            preview = service.generate_preview_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )
            service.mark_pending_translation_preview_shown(
                user_telegram_id=42,
                preview_id=preview.preview_id,
            )
            service.accept_pending_translation_preview(user_telegram_id=42)
            queued = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )
            self.assertEqual(queued.status, TranslationJobStatus.QUEUED)

            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="copy.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(user_telegram_id=42, target_language="uk")

            match = service.find_pending_translation_duplicate(user_telegram_id=42)

            self.assertIsNotNone(match)
            self.assertEqual(match.status, "queued")
            self.assertFalse(match.can_translate_again)
            self.assertTrue(match.can_open_existing)

            service.discard_pending_translation(42)
            persistent_store.mark_job_interrupted(queued.id)
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="copy.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(user_telegram_id=42, target_language="uk")

            recoverable_match = service.find_pending_translation_duplicate(
                user_telegram_id=42
            )

            self.assertIsNotNone(recoverable_match)
            self.assertEqual(recoverable_match.status, "interrupted")
            self.assertTrue(recoverable_match.can_translate_again)
            self.assertTrue(recoverable_match.can_open_existing)

    def test_preview_translation_uses_estimate_when_provider_usage_is_missing(self):
        guard = RecordingBetaSafetyGuard()
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=80,
            beta_safety_guard=guard,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One meaningful preview paragraph.",
            source_language="en",
            target_language="uk",
        )

        preview = service.generate_preview_translation(
            user_telegram_id=42,
            translator=RecordingTranslator(),
        )

        _job_id, _user_id, estimate = guard.reservations[0]
        self.assertGreater(estimate.prompt_tokens, 0)
        self.assertEqual(preview.prompt_tokens, estimate.prompt_tokens)
        self.assertEqual(preview.completion_tokens, estimate.completion_tokens)
        self.assertEqual(
            guard.usage_events[0][3:],
            (estimate.prompt_tokens, estimate.completion_tokens),
        )
        self.assertEqual(guard.consumed, [preview.preview_id])

    def test_preview_failure_returns_safe_error_and_releases_reservation(self):
        guard = RecordingBetaSafetyGuard()
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=80,
            beta_safety_guard=guard,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"Secret source text must not leak.",
            source_language="en",
            target_language="uk",
        )

        with self.assertRaises(PreviewTranslationError) as raised:
            service.generate_preview_translation(
                user_telegram_id=42,
                translator=SensitiveFailingTranslator(),
            )

        message = str(raised.exception)
        self.assertEqual(message, "Preview translation failed.")
        self.assertNotIn("Secret source text", message)
        self.assertNotIn("secret-token", message)
        self.assertEqual(len(guard.reservations), 1)
        self.assertEqual(guard.releases, [(guard.reservations[0][0], "preview_failed")])
        self.assertEqual(guard.usage_events, [])
        self.assertEqual(guard.consumed, [])

    def test_preview_translation_requires_rights_confirmation(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=80,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"First meaningful paragraph.",
            source_language="en",
            target_language="uk",
            rights_confirmed=False,
        )

        with self.assertRaises(RightsConfirmationRequired):
            service.generate_preview_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

    def test_confirm_pending_translation_requires_translation_mode(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
        )
        pending = service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.",
            source_language="en",
            target_language="uk",
        )
        translator = RecordingTranslator()

        with self.assertRaises(TranslationModeRequired):
            service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

        self.assertEqual(translator.requests, [])
        self.assertEqual(service.get_pending(42), pending)

    def test_confirm_pending_translation_requires_preview_acceptance(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
        )
        pending = service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.",
            source_language="en",
            target_language="uk",
            translation_mode=TRANSLATION_MODE_BOOK_MANUSCRIPT,
        )
        translator = RecordingTranslator()

        with self.assertRaises(PreviewAcceptanceRequired):
            service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

        self.assertEqual(translator.requests, [])
        self.assertEqual(service.get_pending(42), pending)

    def test_generated_preview_must_be_shown_before_acceptance(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=80,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One meaningful paragraph.",
            source_language="en",
            target_language="uk",
            translation_mode=TRANSLATION_MODE_BOOK_MANUSCRIPT,
        )
        preview = service.generate_preview_translation(
            user_telegram_id=42,
            translator=RecordingTranslator(),
        )

        with self.assertRaises(PreviewAcceptanceRequired):
            service.accept_pending_translation_preview(user_telegram_id=42)

        service.mark_pending_translation_preview_shown(
            user_telegram_id=42,
            preview_id=preview.preview_id,
        )
        accepted = service.accept_pending_translation_preview(user_telegram_id=42)
        accepted_again = service.accept_pending_translation_preview(user_telegram_id=42)

        self.assertTrue(accepted.preview_accepted)
        self.assertEqual(accepted_again, accepted)

    def test_confirm_pending_translation_requires_rights_confirmation(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
        )
        pending = service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.",
            source_language="en",
            target_language="uk",
            rights_confirmed=False,
        )
        translator = RecordingTranslator()

        with self.assertRaises(RightsConfirmationRequired):
            service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

        self.assertEqual(translator.requests, [])
        self.assertEqual(service.get_pending(42), pending)

    def test_confirms_pending_txt_translation_and_runs_job(self):
        repository = InMemoryTranslationJobRepository()
        service = BotTranslationService(
            job_repository=repository,
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.\n\nTwo.",
            source_language="en",
            target_language="uk",
        )
        self._accept_pending_preview(service)

        job = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=RecordingTranslator(),
        )

        self.assertEqual(job.status, TranslationJobStatus.READY)
        self.assertEqual(job.result_file_name, "notes.uk.txt")
        self.assertEqual(job.result_content.decode("utf-8"), "[uk] One.\n\n[uk] Two.")
        self.assertIsNone(service.get_pending(42))

    def test_beta_allowlist_blocks_unlisted_uploads_before_pending_state(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
            beta_access_policy=BetaAccessPolicy.from_telegram_ids(
                (42,),
                enabled=True,
            ),
        )

        with self.assertRaises(BetaAccessDenied):
            service.store_uploaded_document(
                user_telegram_id=100,
                file_name="notes.txt",
                content=b"One.",
                source_language="en",
            )

        self.assertIsNone(service.get_pending_upload(100))

    def test_beta_allowlist_blocks_unlisted_users_before_rights_confirmation(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
            beta_access_policy=BetaAccessPolicy.from_telegram_ids(
                (42,),
                enabled=True,
            ),
        )

        with self.assertRaises(BetaAccessDenied):
            service.confirm_pending_upload_rights(user_telegram_id=100)

    def test_beta_allowlist_blocks_unlisted_confirmation_and_keeps_pending(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
            beta_access_policy=BetaAccessPolicy.from_telegram_ids(
                (42,),
                enabled=True,
            ),
        )
        pending = service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.",
            source_language="en",
            target_language="uk",
        )
        service._pending[100] = pending

        with self.assertRaises(BetaAccessDenied):
            service.confirm_pending_translation(
                user_telegram_id=100,
                translator=RecordingTranslator(),
            )

        self.assertIsNotNone(service.get_pending(100))

    def test_translation_lifecycle_writes_user_activity_events(self):
        with TemporaryDirectory() as temp_dir:
            activity_store = SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3")
            self.addCleanup(activity_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                translation_run_log_root=Path(temp_dir) / "translation-runs",
                activity_store=activity_store,
            )
            service.prepare_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One.\n\nTwo.",
                source_language="en",
                target_language="uk",
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

            events = activity_store.list_events(actor_id="telegram:42")
            event_types = [event.event_type for event in events]
            completed = next(
                event for event in events if event.event_type == "translation.completed"
            )
            profile = activity_store.get_user_profile("telegram:42")

        self.assertEqual(job.status, TranslationJobStatus.READY)
        self.assertIn("document.estimated", event_types)
        self.assertIn("translation.confirmed", event_types)
        self.assertIn("translation.started", event_types)
        self.assertIn("translation.completed", event_types)
        self.assertEqual(completed.job_id, "job-1")
        self.assertEqual(completed.channel_user_id, "42")
        self.assertIsNotNone(completed.translation_run_dir)
        self.assertEqual(completed.metadata["result_file_name"], "notes.uk.txt")
        self.assertNotIn("source_text", completed.metadata)
        self.assertEqual(profile.last_target_language, "uk")

    def test_admin_deleted_activity_becomes_user_visible_deleted_job(self):
        with TemporaryDirectory() as temp_dir:
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            activity_store = SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3")
            self.addCleanup(activity_store.close)
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="book.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
            )
            persistent_store.delete_job(job.id)
            activity_store.record_event(
                UserActivityEventInput(
                    actor_type=ActivityActorType.ADMIN,
                    actor_id="bootstrap-owner",
                    surface=ActivitySurface.ADMIN,
                    event_type="translation.admin_deleted",
                    action="delete",
                    outcome=ActivityOutcome.SUCCESS,
                    channel="telegram",
                    channel_user_id="42",
                    target_type="translation_job",
                    target_id=job.id,
                    job_id=job.id,
                    order_id=job.order_id,
                    metadata={
                        "file_name": job.file_name,
                        "document_kind": job.document_kind,
                        "source_language": job.source_language,
                        "target_language": job.target_language,
                    },
                )
            )
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                persistent_job_store=persistent_store,
                activity_store=activity_store,
            )

            deleted = service.get_user_book_translation_job(
                user_telegram_id=42,
                job_id=job.id,
            )

            self.assertIsNotNone(deleted)
            self.assertEqual(deleted.status, TranslationJobStatus.DELETED)
            self.assertEqual(deleted.file_name, "book.txt")

    def test_confirmed_translation_writes_privacy_safe_automatic_run_log(self):
        with TemporaryDirectory() as temp_dir:
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                translation_run_log_root=Path(temp_dir) / "translation-runs",
            )
            service.prepare_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One.",
                source_language="en",
                target_language="uk",
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

            run_dirs = list((Path(temp_dir) / "translation-runs").iterdir())
            self.assertEqual(len(run_dirs), 1)
            run_dir = run_dirs[0]
            fragment = json.loads(
                (run_dir / "fragments" / "0001.json").read_text(encoding="utf-8")
            )
            snapshot = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

            self.assertEqual(job.status, TranslationJobStatus.READY)
            self.assertNotIn("source_text", fragment)
            self.assertNotIn("translated_text", fragment)
            self.assertEqual(
                fragment["source_text_hash"],
                hashlib.sha256(b"One.").hexdigest(),
            )
            self.assertEqual(
                fragment["translated_text_hash"],
                hashlib.sha256(b"[uk] One.").hexdigest(),
            )
            self.assertEqual(fragment["source_text_chars"], 4)
            self.assertEqual(fragment["translated_text_chars"], 9)
            self.assertEqual(snapshot["status"], "ready")
            self.assertEqual(snapshot["file_name"], "notes.txt")
            self.assertEqual(snapshot["result_file_name"], "notes.uk.txt")

    def test_confirmed_translation_run_log_records_translation_policy_snapshot(self):
        with TemporaryDirectory() as temp_dir:
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=80,
                translation_run_log_root=Path(temp_dir) / "translation-runs",
            )
            service.prepare_document(
                user_telegram_id=42,
                file_name="api-notes.txt",
                content=b"Set the API endpoint and pass the placeholder token.",
                source_language="en",
                target_language="ru",
            )
            self._accept_pending_preview(service)

            service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

            run_dir = next((Path(temp_dir) / "translation-runs").iterdir())
            snapshot = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            translation_policy = json.loads(snapshot["translation_policy"])
            summary = (run_dir / "summary.md").read_text(encoding="utf-8")

            self.assertEqual(
                translation_policy["target_language_policy"],
                "target-profile:ru:russian-v2",
            )
            self.assertEqual(
                translation_policy["russian_quality_track"],
                "russian-quality:precision-v1",
            )
            self.assertEqual(translation_policy["text_type"], "technical")
            self.assertEqual(translation_policy["target_language"], "ru")
            self.assertEqual(translation_policy["source_language"], "en")
            self.assertEqual(snapshot["adapter_version"], "txt-adapter-v2")
            self.assertEqual(snapshot["prompt_version"], "plain-v1")
            self.assertEqual(
                snapshot["translation_stack"],
                {
                    "schema_version": "translation-stack-v1",
                    "adapter": {
                        "document_kind": "txt",
                        "name": "txt",
                        "version": "txt-adapter-v2",
                    },
                    "prompt": {
                        "run_prompt_version": "plain-v1",
                        "prompt_policy_version": "prompt-policy-v10",
                        "protection_policy_version": "protection-policy-v2",
                        "adapter_policy_version": "generic-adapter-v2",
                        "output_contract": "plain-text-v1",
                    },
                    "language_profiles": {
                        "target_language": {
                            "language": "ru",
                            "signature": "target-profile:ru:russian-v2",
                            "version": "russian-v2",
                        },
                        "source_pair": {
                            "source_language": "en",
                            "target_language": "ru",
                            "signature": "source-pair:en-ru:v1",
                            "version": "v1",
                        },
                        "quality_track": {
                            "signature": "russian-quality:precision-v1",
                            "track": "precision",
                            "version": "v1",
                        },
                    },
                    "text": {
                        "source_language": "en",
                        "target_language": "ru",
                        "text_type": "technical",
                        "prompt_tier": "plain",
                    },
                },
            )
            self.assertIn("## Translation Stack", summary)
            self.assertIn(
                "Target language profile: `target-profile:ru:russian-v2`", summary
            )
            self.assertIn("Source-pair profile: `source-pair:en-ru:v1`", summary)

    def test_confirmed_translation_run_log_records_security_events(self):
        with TemporaryDirectory() as temp_dir:
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                translation_run_log_root=Path(temp_dir) / "translation-runs",
            )
            service.prepare_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One.",
                source_language="en",
                target_language="uk",
            )
            self._accept_pending_preview(service)

            service.confirm_pending_translation(
                user_telegram_id=42,
                translator=SecurityEventTranslator(),
            )

            run_dir = next((Path(temp_dir) / "translation-runs").iterdir())
            snapshot = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            events_jsonl = (run_dir / "events.jsonl").read_text(encoding="utf-8")

            self.assertEqual(snapshot["security"]["unsafe_model_outputs"], 1)
            self.assertIn("security_event", events_jsonl)
            self.assertIn("prompt_disclosure", events_jsonl)
            self.assertNotIn("Ignore previous instructions", events_jsonl)

    def test_security_threshold_fails_job_without_restoring_pending(self):
        with TemporaryDirectory() as temp_dir:
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                translation_run_log_root=Path(temp_dir) / "translation-runs",
                security_threshold_policy=SecurityThresholdPolicy(
                    max_unsafe_model_outputs_per_run=1
                ),
            )
            service.prepare_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One.\n\nTwo.",
                source_language="en",
                target_language="uk",
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RepeatedSecurityEventTranslator(),
            )

            run_dir = next((Path(temp_dir) / "translation-runs").iterdir())
            snapshot = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            events_jsonl = (run_dir / "events.jsonl").read_text(encoding="utf-8")

            self.assertEqual(job.status, TranslationJobStatus.FAILED)
            self.assertIn("Security threshold exceeded", job.error_message)
            self.assertIsNone(service.get_pending(42))
            self.assertEqual(snapshot["security"]["security_threshold_exceeded"], 1)
            self.assertIn("security_threshold_exceeded", events_jsonl)
            self.assertNotIn("One.", events_jsonl)

    def test_repeated_security_threshold_starts_user_cooldown(self):
        with TemporaryDirectory() as temp_dir:
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                translation_run_log_root=Path(temp_dir) / "translation-runs",
                security_threshold_policy=SecurityThresholdPolicy(
                    max_unsafe_model_outputs_per_run=1
                ),
                security_cooldown_policy=SecurityCooldownPolicy(
                    max_thresholds_per_window=1,
                    cooldown_seconds=300,
                ),
            )
            service.prepare_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One.\n\nTwo.",
                source_language="en",
                target_language="uk",
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RepeatedSecurityEventTranslator(),
            )
            run_dir = next((Path(temp_dir) / "translation-runs").iterdir())
            events_jsonl = (run_dir / "events.jsonl").read_text(encoding="utf-8")

            self.assertEqual(job.status, TranslationJobStatus.FAILED)
            self.assertIn("security_user_cooldown_started", events_jsonl)
            with self.assertRaises(SecurityCooldownActive) as error:
                service.prepare_document(
                    user_telegram_id=42,
                    file_name="other.txt",
                    content=b"Safe text.",
                    source_language="en",
                    target_language="uk",
                )
            self.assertEqual(error.exception.user_id, "telegram:42")
            self.assertGreater(error.exception.remaining_seconds, 0)

            other_pending = service.prepare_document(
                user_telegram_id=100,
                file_name="other.txt",
                content=b"Safe text.",
                source_language="en",
                target_language="uk",
            )
            self.assertEqual(other_pending.user_telegram_id, 100)

    def test_persistent_txt_confirmation_uses_stored_work_units(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "jobs.sqlite3"
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(db_path)
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=Path(temp_dir) / "translation-runs",
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"# Chapter\n\nKEY=value\n- First item\nBody text.\n",
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(
                service,
                translation_mode=TRANSLATION_MODE_DOCUMENT_FORM,
            )
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

            persisted_job = persistent_store.get_job(job.id)
            translation_policy = json.loads(persisted_job.translation_policy)
            work_units = persistent_store.list_work_units(job.id)
            self.assertEqual(job.status, TranslationJobStatus.READY)
            self.assertEqual(job.result_file_name, "notes.uk.txt")
            self.assertEqual(
                job.result_content.decode("utf-8"),
                "# [uk] Chapter\n\nKEY=value\n- [uk] First item\n[uk] Body text.\n",
            )
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.READY,
            )
            self.assertIsNotNone(persisted_job.final_object_key)
            self.assertEqual(
                storage.get_bytes(persisted_job.final_object_key),
                job.result_content,
            )
            self.assertEqual(
                translation_policy["rights_confirmation"],
                {
                    "confirmed": True,
                    "source": "telegram_button",
                    "version": "rights-v1",
                },
            )
            self.assertEqual(
                translation_policy["translation_mode"],
                TRANSLATION_MODE_DOCUMENT_FORM,
            )
            reopened_store = SQLiteTranslationJobStore(db_path)
            self.addCleanup(reopened_store.close)
            reopened_job = reopened_store.get_job(job.id)
            self.assertEqual(
                json.loads(reopened_job.translation_policy)["translation_mode"],
                TRANSLATION_MODE_DOCUMENT_FORM,
            )
            self.assertEqual(
                [unit.status for unit in work_units],
                [
                    PersistentWorkUnitStatus.TRANSLATED,
                    PersistentWorkUnitStatus.TRANSLATED,
                    PersistentWorkUnitStatus.TRANSLATED,
                ],
            )
            run_dirs = list((Path(temp_dir) / "translation-runs").iterdir())
            self.assertEqual(len(run_dirs), 1)
            fragment = json.loads(
                (run_dirs[0] / "fragments" / "0001.json").read_text(encoding="utf-8")
            )
            snapshot = json.loads(
                (run_dirs[0] / "run.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("source_text", fragment)
            self.assertNotIn("translated_text", fragment)
            self.assertEqual(
                fragment["source_text_hash"],
                hashlib.sha256(b"Chapter").hexdigest(),
            )
            self.assertEqual(
                fragment["translated_text_hash"],
                hashlib.sha256(b"[uk] Chapter").hexdigest(),
            )
            self.assertEqual(fragment["source_text_chars"], 7)
            self.assertEqual(fragment["translated_text_chars"], 12)
            self.assertEqual(snapshot["status"], "ready")
            self.assertEqual(snapshot["job_id"], job.id)
            self.assertEqual(
                json.loads(snapshot["translation_policy"])["rights_confirmation"],
                {
                    "confirmed": True,
                    "source": "telegram_button",
                    "version": "rights-v1",
                },
            )
            self.assertEqual(
                json.loads(snapshot["translation_policy"])["translation_mode"],
                TRANSLATION_MODE_DOCUMENT_FORM,
            )

    def test_persistent_txt_scan_gate_records_upload_safety_policy_marker(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "jobs.sqlite3"
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(db_path)
            self.addCleanup(persistent_store.close)
            ledger = InMemoryUploadSafetyLedger()
            activity_store = SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3")
            self.addCleanup(activity_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=Path(temp_dir) / "translation-runs",
                document_scanner=FakeDocumentScanner(
                    default_verdict=ScannerVerdict.CLEAN
                ),
                require_upload_scan=True,
                upload_safety_ledger=ledger,
                activity_store=activity_store,
            )
            uploaded = service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"First paragraph.",
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(
                service,
                translation_mode=TRANSLATION_MODE_DOCUMENT_FORM,
            )
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

            persisted_job = persistent_store.get_job(job.id)
            translation_policy = json.loads(persisted_job.translation_policy)
            run_dir = next((Path(temp_dir) / "translation-runs").iterdir())
            run_snapshot = json.loads(
                (run_dir / "run.json").read_text(encoding="utf-8")
            )
            run_policy = json.loads(run_snapshot["translation_policy"])
            activity_events = activity_store.list_events(
                event_type="security.upload_safety.summary"
            )
            self.assertEqual(
                translation_policy["upload_safety"],
                {
                    "accepted_source_object_key": uploaded.source_object_key,
                    "source_gate": "upload_safety_ledger",
                    "upload_safety_id": uploaded.upload_safety_id,
                },
            )
            self.assertEqual(
                run_policy["upload_safety"],
                {
                    "source_gate": "upload_safety_ledger",
                    "upload_safety_id": uploaded.upload_safety_id,
                },
            )
            self.assertNotIn("accepted_source_object_key", run_policy["upload_safety"])
            self.assertEqual(activity_events[0].job_id, job.id)
            self.assertEqual(
                activity_events[0].translation_run_dir,
                str(run_dir),
            )

    def test_persistent_confirmation_reserves_beta_safety_before_deferred_queue(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            guard = RecordingBetaSafetyGuard()
            translator = RecordingTranslator()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
                defer_persistent_jobs_to_worker=True,
                beta_safety_guard=guard,
            )
            content = b"One.\n\nTwo."
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

            persisted = persistent_store.get_job(job.id)
            self.assertEqual(job.status, TranslationJobStatus.QUEUED)
            self.assertEqual(translator.requests, [])
            self.assertEqual(len(guard.reservations), 1)
            reserved_job_id, reserved_user_id, estimate = guard.reservations[0]
            self.assertEqual(reserved_job_id, job.id)
            self.assertEqual(reserved_user_id, persisted.user_id)
            planned = plan_txt_translation(
                content=content,
                max_fragment_chars=5,
            )
            self.assertEqual(estimate.prompt_tokens, planned.estimated_input_tokens)
            self.assertEqual(
                estimate.completion_tokens,
                planned.estimated_input_tokens,
            )
            self.assertEqual(guard.releases, [])

    def test_persistent_epub_beta_safety_uses_planned_tokens_not_fragment_capacity(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            max_fragment_chars = 4000
            body = "".join(
                (
                    "<p><span>a</span><span>b</span>"
                    f"<span>c</span><span>d</span> unit {index}</p>"
                )
                for index in range(1500)
            )
            content = _make_epub(
                {
                    "OPS/chapter.xhtml": (
                        '<html xmlns="http://www.w3.org/1999/xhtml">'
                        f"<body>{body}</body></html>"
                    ),
                }
            )
            planned = plan_epub_translation(
                content=content,
                max_fragment_chars=max_fragment_chars,
            )
            rates = BetaSafetyRates()
            old_capacity_tokens = (
                planned.fragment_count * max_fragment_chars + 3
            ) // 4
            old_capacity_cost = estimate_cost_usd(
                prompt_tokens=old_capacity_tokens,
                completion_tokens=old_capacity_tokens,
                rates=rates,
            )
            planned_cost = estimate_cost_usd(
                prompt_tokens=planned.estimated_input_tokens,
                completion_tokens=planned.estimated_input_tokens,
                rates=rates,
            )
            self.assertGreater(planned.fragment_count, 1000)
            self.assertGreater(old_capacity_cost, 2.0)
            self.assertLessEqual(planned_cost, 2.0)

            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            guard = CostCapRecordingBetaSafetyGuard(max_estimated_cost_usd=2.0)
            translator = RecordingTranslator()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=max_fragment_chars,
                file_storage=storage,
                persistent_job_store=persistent_store,
                defer_persistent_jobs_to_worker=True,
                beta_safety_guard=guard,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="many-small-units.epub",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

            self.assertEqual(job.status, TranslationJobStatus.QUEUED)
            self.assertEqual(translator.requests, [])
            self.assertEqual(len(guard.reservations), 1)
            _, _, estimate = guard.reservations[0]
            self.assertEqual(estimate.prompt_tokens, planned.estimated_input_tokens)
            self.assertEqual(
                estimate.completion_tokens,
                planned.estimated_input_tokens,
            )
            self.assertLessEqual(estimate.estimated_cost_usd, 2.0)
            self.assertEqual(
                len(persistent_store.list_work_units(job.id)),
                planned.fragment_count,
            )
            self.assertEqual(guard.releases, [])

    def test_repeated_persistent_translation_creates_distinct_attempt_jobs(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            guard = RecordingBetaSafetyGuard()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=80,
                file_storage=storage,
                persistent_job_store=persistent_store,
                beta_safety_guard=guard,
            )
            content = b"Alpha beta repeated attempt fixture."

            def translate_once() -> tuple[str, str, str]:
                upload = service.store_uploaded_document(
                    user_telegram_id=42,
                    file_name="notes.txt",
                    content=content,
                    source_language="en",
                )
                service.confirm_pending_upload_rights(user_telegram_id=42)
                self._select_default_translation_mode(service)
                service.prepare_pending_upload(
                    user_telegram_id=42,
                    target_language="uk",
                )
                preview = service.generate_preview_translation(
                    user_telegram_id=42,
                    translator=RecordingTranslator(),
                )
                service.mark_pending_translation_preview_shown(
                    user_telegram_id=42,
                    preview_id=preview.preview_id,
                )
                service.accept_pending_translation_preview(user_telegram_id=42)
                job = service.confirm_pending_translation(
                    user_telegram_id=42,
                    translator=RecordingTranslator(),
                )
                self.assertEqual(job.status, TranslationJobStatus.READY)
                return preview.preview_id, job.id, upload.source_object_key

            first_preview_id, first_job_id, _first_source_key = translate_once()
            second_preview_id, second_job_id, _second_source_key = translate_once()

            self.assertNotEqual(second_preview_id, first_preview_id)
            self.assertNotEqual(second_job_id, first_job_id)
            self.assertEqual(
                [job.job_id for job in service.list_user_books(user_telegram_id=42)],
                [second_job_id, first_job_id],
            )
            self.assertIsNotNone(
                service.get_user_book_result(
                    user_telegram_id=42,
                    job_id=first_job_id,
                )
            )
            self.assertIsNotNone(
                service.get_user_book_result(
                    user_telegram_id=42,
                    job_id=second_job_id,
                )
            )
            self.assertEqual(
                [reservation[0] for reservation in guard.reservations],
                [first_preview_id, first_job_id, second_preview_id, second_job_id],
            )
            self.assertEqual(
                guard.consumed,
                [first_preview_id, first_job_id, second_preview_id, second_job_id],
            )
            self.assertEqual(len(guard.releases), 0)

    def test_persistent_confirmation_denied_by_beta_safety_fails_safely(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            guard = RecordingBetaSafetyGuard(allowed=False)
            translator = RecordingTranslator()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
                beta_safety_guard=guard,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"Secret source text.",
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

            persisted = persistent_store.get_job(job.id)
            self.assertEqual(job.status, TranslationJobStatus.FAILED)
            self.assertEqual(
                job.error_message,
                "You have reached today's beta translation limit.",
            )
            self.assertNotIn("Secret source text", job.error_message)
            self.assertEqual(translator.requests, [])
            self.assertEqual(
                persisted.status,
                PersistentTranslationJobStatus.INTERRUPTED,
            )
            self.assertEqual(len(guard.reservations), 1)
            self.assertEqual(guard.releases, [])
            self.assertIsNone(service.get_pending(42))

    def test_successful_inline_persistent_confirmation_records_beta_usage(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            guard = RecordingBetaSafetyGuard()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
                beta_safety_guard=guard,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One.\n\nTwo.",
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

            work_unit_ids = {
                unit.id for unit in persistent_store.list_work_units(job.id)
            }
            self.assertEqual(job.status, TranslationJobStatus.READY)
            self.assertEqual(len(guard.usage_events), 2)
            self.assertEqual({event[0] for event in guard.usage_events}, {job.id})
            self.assertEqual(
                {event[1] for event in guard.usage_events}, {"telegram:42"}
            )
            self.assertEqual({event[2] for event in guard.usage_events}, work_unit_ids)
            self.assertEqual(guard.releases, [])
            self.assertEqual(guard.consumed, [job.id])

    def test_user_book_detail_shows_download_and_resume_state(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=Path(temp_dir) / "translation-runs",
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One.\n\nTwo.",
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            self._accept_pending_preview(service)
            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=CancellingTranslator(service, 42),
            )

            detail = service.get_user_book_detail(
                user_telegram_id=42,
                job_id=job.id,
            )
            other_user_detail = service.get_user_book_detail(
                user_telegram_id=100,
                job_id=job.id,
            )

            self.assertIsNone(other_user_detail)
            self.assertEqual(detail.job_id, job.id)
            self.assertEqual(detail.file_name, "notes.txt")
            self.assertEqual(detail.status, "cancelled")
            self.assertTrue(detail.has_result)
            self.assertTrue(detail.has_partial_result)
            self.assertTrue(detail.can_resume)

    def test_user_book_detail_includes_active_work_unit_progress(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="active.txt",
                content_type="text/plain; charset=utf-8",
                content=b"One.\n\nTwo.\n\nThree.\n\nFour.\n\nFive.",
            )
            unit_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="active-unit.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Unit",
            )
            job = persistent_store.create_job(
                order_id="order-progress",
                user_id="telegram:42",
                file_id=original.object_key,
                file_name="active.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=original.object_key,
            )
            persistent_store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=sequence,
                        source_block_ids=(f"txt:{sequence}",),
                        source_object_key=unit_source.object_key,
                        source_text_hash=f"hash-{sequence}",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                    )
                    for sequence in range(1, 6)
                ],
            )
            for index in range(1, 3):
                unit = persistent_store.claim_next_work_unit(
                    job.id,
                    worker_id=f"worker-{index}",
                )
                self.assertIsNotNone(unit)
                persistent_store.complete_work_unit(
                    unit.id,
                    translated_text=f"Translated {index}",
                    prompt_tokens=1,
                    completion_tokens=1,
                    cache_hit_tokens=0,
                    cache_miss_tokens=1,
                )

            detail = service.get_user_book_detail(
                user_telegram_id=42,
                job_id=job.id,
            )

            self.assertEqual(detail.status, "translating")
            self.assertEqual(detail.progress_completed_fragments, 2)
            self.assertEqual(detail.progress_total_fragments, 5)
            self.assertEqual(detail.progress_percent, 40)

    def test_user_book_detail_resume_visibility_follows_recoverable_state_matrix(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.txt",
                content_type="text/plain",
                content=b"Original",
            )
            partial = storage.put_bytes(
                kind=StoredFileKind.PARTIAL,
                file_name="book.uk.partial.txt",
                content_type="text/plain",
                content=b"Partial",
            )
            final = storage.put_bytes(
                kind=StoredFileKind.FINAL,
                file_name="book.uk.txt",
                content_type="text/plain",
                content=b"Final",
            )
            recoverable_statuses = {
                PersistentTranslationJobStatus.CANCELLED,
                PersistentTranslationJobStatus.FAILED,
                PersistentTranslationJobStatus.INTERRUPTED,
                PersistentTranslationJobStatus.PARTIAL,
                PersistentTranslationJobStatus.PAUSED,
            }
            cancellable_statuses = {
                PersistentTranslationJobStatus.QUEUED,
                PersistentTranslationJobStatus.TRANSLATING,
                PersistentTranslationJobStatus.ASSEMBLING,
                PersistentTranslationJobStatus.CANCEL_REQUESTED,
            }

            for status in PersistentTranslationJobStatus:
                with self.subTest(status=status.value):
                    job = persistent_store.create_job(
                        order_id=f"order-{status.value}",
                        user_id="telegram:42",
                        file_id=source.object_key,
                        file_name=f"{status.value}.txt",
                        document_kind="txt",
                        source_language="en",
                        target_language="uk",
                        adapter_version="txt-v1",
                        prompt_version="plain-v1",
                        pricing_snapshot_id="pricing-1",
                        source_object_key=source.object_key,
                    )
                    if status is PersistentTranslationJobStatus.PARTIAL:
                        persistent_store.attach_job_output(
                            job.id,
                            partial_object_key=partial.object_key,
                        )
                    elif status is PersistentTranslationJobStatus.READY:
                        persistent_store.attach_job_output(
                            job.id,
                            final_object_key=final.object_key,
                        )
                    with persistent_store._connection:
                        persistent_store._update_job_status(
                            job.id,
                            status,
                            now=datetime.now(UTC),
                        )

                    detail = service.get_user_book_detail(
                        user_telegram_id=42,
                        job_id=job.id,
                    )

                    self.assertEqual(
                        detail.can_resume,
                        status in recoverable_statuses,
                    )
                    self.assertEqual(
                        detail.can_cancel,
                        status in cancellable_statuses,
                    )
                    self.assertEqual(
                        detail.has_partial_result,
                        status is PersistentTranslationJobStatus.PARTIAL,
                    )

    def test_persistent_cancel_requested_maps_to_runtime_cancel_requested(self):
        self.assertEqual(
            _translation_job_status_from_persistent_status(
                PersistentTranslationJobStatus.CANCEL_REQUESTED
            ),
            TranslationJobStatus.CANCEL_REQUESTED,
        )

    def test_active_cancel_marks_persistent_job_cancel_requested(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.txt",
                content_type="text/plain",
                content=b"Original",
            )
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id=source.object_key,
                file_name="book.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=source.object_key,
            )
            persistent_store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:0",),
                        source_text_hash="hash-1",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=source.object_key,
                    )
                ],
            )
            persistent_store.claim_next_work_unit(job.id, worker_id="worker-a")
            token = CancellationToken()
            service._set_active_translation(
                user_telegram_id=42,
                cancellation_token=token,
                job_id=job.id,
                total_fragments=1,
            )

            result = service.cancel_translation_with_result(42)

            persisted = persistent_store.get_job(job.id)
            self.assertTrue(result.cancelled)
            self.assertTrue(token.is_cancelled)
            self.assertEqual(
                persisted.status,
                PersistentTranslationJobStatus.CANCEL_REQUESTED,
            )

    def test_external_worker_cancel_marks_active_job_cancel_requested(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.txt",
                content_type="text/plain",
                content=b"Original",
            )
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id=source.object_key,
                file_name="book.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=source.object_key,
            )
            persistent_store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:0",),
                        source_text_hash="hash-1",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=source.object_key,
                    )
                ],
            )
            claimed = persistent_store.claim_next_scheduled_work_unit(
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
            )

            result = service.cancel_translation_with_result(42)

            persisted = persistent_store.get_job(job.id)
            [work_unit] = persistent_store.list_work_units(job.id)
            self.assertTrue(result.cancelled)
            self.assertIsNotNone(result.job)
            self.assertEqual(result.job.status, TranslationJobStatus.CANCEL_REQUESTED)
            self.assertEqual(
                persisted.status,
                PersistentTranslationJobStatus.CANCEL_REQUESTED,
            )
            self.assertEqual(work_unit.id, claimed.work_unit_id)
            self.assertEqual(work_unit.status, PersistentWorkUnitStatus.TRANSLATING)

    def test_cancel_user_book_marks_active_external_job_cancel_requested(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.txt",
                content_type="text/plain",
                content=b"Original",
            )
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id=source.object_key,
                file_name="book.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=source.object_key,
            )
            persistent_store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:0",),
                        source_text_hash="hash-1",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=source.object_key,
                    )
                ],
            )
            claimed = persistent_store.claim_next_scheduled_work_unit(
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
            )

            cancelled = service.cancel_user_book(user_telegram_id=42, job_id=job.id)

            persisted = persistent_store.get_job(job.id)
            [work_unit] = persistent_store.list_work_units(job.id)
            detail = service.get_user_book_detail(user_telegram_id=42, job_id=job.id)
            self.assertTrue(cancelled)
            self.assertEqual(
                persisted.status,
                PersistentTranslationJobStatus.CANCEL_REQUESTED,
            )
            self.assertEqual(work_unit.id, claimed.work_unit_id)
            self.assertEqual(work_unit.status, PersistentWorkUnitStatus.TRANSLATING)
            self.assertEqual(detail.status, "cancel_requested")
            self.assertFalse(detail.has_partial_result)
            self.assertTrue(detail.can_cancel)

    def test_user_book_detail_hides_resume_when_source_object_is_missing(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            job = persistent_store.create_job(
                order_id="order-missing-source",
                user_id="telegram:42",
                file_id="original/missing.txt",
                file_name="missing.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key="original/missing.txt",
            )
            with persistent_store._connection:
                persistent_store._update_job_status(
                    job.id,
                    PersistentTranslationJobStatus.FAILED,
                    now=datetime.now(UTC),
                )

            detail = service.get_user_book_detail(
                user_telegram_id=42,
                job_id=job.id,
            )

            self.assertFalse(detail.can_resume)

    def test_resume_user_book_translation_runs_remaining_work_units(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One.\nTwo.\n",
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            self._accept_pending_preview(service)
            cancelled = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=CancellingTranslator(service, 42),
            )

            resumed = service.resume_user_book_translation(
                user_telegram_id=42,
                job_id=cancelled.id,
                translator=RecordingTranslator(),
            )

            persisted_job = persistent_store.get_job(cancelled.id)
            detail = service.get_user_book_detail(
                user_telegram_id=42,
                job_id=cancelled.id,
            )
            self.assertIsNone(
                service.resume_user_book_translation(
                    user_telegram_id=100,
                    job_id=cancelled.id,
                    translator=RecordingTranslator(),
                )
            )
            self.assertEqual(resumed.status, TranslationJobStatus.READY)
            self.assertEqual(resumed.result_file_name, "notes.uk.txt")
            self.assertEqual(
                resumed.result_content.decode("utf-8"),
                "[uk] One.\n[uk] Two.\n",
            )
            self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.READY)
            self.assertIsNotNone(persisted_job.final_object_key)
            self.assertTrue(detail.has_result)
            self.assertFalse(detail.has_partial_result)
            self.assertFalse(detail.can_resume)
            self.assertEqual(detail.status, "ready")

    def test_persistent_confirmation_uses_scheduler_runner_for_stored_work(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            guard = RecordingBetaSafetyGuard()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
                use_scheduler_runner=True,
                beta_safety_guard=guard,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"# Chapter\n\nKEY=value\n- First item\nBody text.\n",
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

            persisted_job = persistent_store.get_job(job.id)
            self.assertEqual(job.status, TranslationJobStatus.READY)
            self.assertIsNotNone(persisted_job.final_object_key)
            self.assertEqual(
                job.result_content.decode("utf-8"),
                "# [uk] Chapter\n\nKEY=value\n- [uk] First item\n[uk] Body text.\n",
            )
            self.assertEqual(guard.consumed, [job.id])

    def test_glossary_adapter_callback_redacts_nested_raw_secret_metadata(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-glossary-callback-redaction",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="uk",
                ),
            )
            callback = _glossary_adapter_metadata_callback(logger)
            if callback is None:
                self.fail("expected glossary adapter metadata callback")

            callback(
                {
                    "status": "fallback",
                    "adapter_metadata": {
                        "safe_count": 2,
                        "nested": {
                            "raw_source_text": "RAW SOURCE SHOULD NOT LEAK",
                            "provider_response_body": (
                                "RAW PROVIDER BODY SHOULD NOT LEAK"
                            ),
                            "headers": {
                                "authorization": "Bearer UNIT_TEST_TOKEN_VALUE"
                            },
                            "package_signature": "postgres://unit:secret@localhost/db",
                            "custom_api_token": "UNIT_TEST_API_TOKEN",
                            "safe_label": "safe metadata",
                        },
                        "items": [{"password": "UNIT_TEST_PASSWORD"}],
                    },
                }
            )

            events = [
                json.loads(line)
                for line in logger.run_dir.joinpath("events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            payload = events[-1]["payload"]
            nested = payload["adapter_metadata"]["nested"]
            serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            self.assertEqual(payload["status"], "fallback")
            self.assertEqual(payload["adapter_metadata"]["safe_count"], 2)
            self.assertEqual(nested["safe_label"], "safe metadata")
            self.assertEqual(nested["raw_source_text"], "[redacted]")
            self.assertEqual(nested["provider_response_body"], "[redacted]")
            self.assertEqual(nested["headers"]["authorization"], "[redacted]")
            self.assertEqual(nested["package_signature"], "[redacted]")
            self.assertEqual(nested["custom_api_token"], "[redacted]")
            self.assertEqual(
                payload["adapter_metadata"]["items"][0]["password"],
                "[redacted]",
            )
            self.assertNotIn("RAW SOURCE SHOULD NOT LEAK", serialized)
            self.assertNotIn("RAW PROVIDER BODY SHOULD NOT LEAK", serialized)
            self.assertNotIn("Bearer UNIT_TEST_TOKEN_VALUE", serialized)
            self.assertNotIn("postgres://unit:secret@localhost/db", serialized)
            self.assertNotIn("UNIT_TEST_API_TOKEN", serialized)
            self.assertNotIn("UNIT_TEST_PASSWORD", serialized)

    def test_epub_with_glossary_scheduler_runner_uses_hook_metadata_only(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            persistent_store = SQLiteTranslationJobStore(root / "jobs.sqlite3")
            run_log_root = root / "translation-runs"
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=200,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
                use_scheduler_runner=True,
                glossary_runtime_hook_builder=lambda pending, document_kind: (
                    _ready_glossary_hook()
                ),
            )
            content = _make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body><p>Darcy returns.</p></body>
                    </html>
                    """
                }
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="book.epub",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="ru",
                glossary_mode=GLOSSARY_MODE_WITH,
            )
            self._accept_pending_preview(service)
            translator = RecordingTranslator()

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

            self.assertEqual(job.status, TranslationJobStatus.READY)
            self.assertEqual(
                extract_text_from_epub(job.result_content),
                "[ru] Darcy returns.",
            )
            self.assertEqual(len(translator.requests), 1)
            self.assertIn("<glossary_context", translator.requests[0][0])
            run_dir = next(run_log_root.iterdir())
            event_lines = run_dir.joinpath("events.jsonl").read_text()
            self.assertIn("glossary_runtime_adapter", event_lines)
            self.assertIn("bypass_glossary_injected_cache", event_lines)
            self.assertNotIn("Darcy returns.", event_lines)

    def test_epub_with_glossary_attaches_prepared_package_and_injects_context(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            persistent_store = SQLiteTranslationJobStore(root / "jobs.sqlite3")
            run_log_root = root / "translation-runs"
            self.addCleanup(persistent_store.close)
            content = _make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body><p>Darcy returns.</p></body>
                    </html>
                    """
                }
            )
            source_sha256 = hashlib.sha256(content).hexdigest()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=200,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
                use_scheduler_runner=True,
                prepared_glossary_package_resolver=lambda request: (
                    PreparedGlossaryPackageAttachment(
                        payload=_prepared_glossary_package(),
                        source_sha256=source_sha256,
                        document_kind="epub",
                        target_language="ru",
                    )
                ),
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="book.epub",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="ru",
                glossary_mode=GLOSSARY_MODE_WITH,
            )
            self._accept_pending_preview(service)
            translator = RecordingTranslator()

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

            self.assertEqual(job.status, TranslationJobStatus.READY)
            self.assertEqual(len(translator.requests), 1)
            self.assertIn("<glossary_context", translator.requests[0][0])
            self.assertIn("Дарси", translator.requests[0][0])
            persisted = persistent_store.get_job(job.id)
            policy = json.loads(persisted.translation_policy)
            self.assertEqual(policy["glossary_mode"], GLOSSARY_MODE_WITH)
            self.assertIn("prepared_glossary_package", policy)
            self.assertEqual(
                policy["prepared_glossary_package"]["package_id"],
                "prepared:bot-test:ru",
            )
            run_dir = next(run_log_root.iterdir())
            event_lines = run_dir.joinpath("events.jsonl").read_text()
            self.assertIn("prepared_glossary_package_attachment", event_lines)
            self.assertIn('"attachment_status": "attached"', event_lines)
            self.assertIn(
                '"glossary_effective_status": "effective_observed"',
                event_lines,
            )
            self.assertIn('"diagnostic_severity": "info"', event_lines)
            self.assertIn("bypass_glossary_injected_cache", event_lines)
            self.assertNotIn("Darcy returns.", event_lines)

    def test_txt_and_docx_with_glossary_prepared_package_inject_context(self):
        cases = (
            ("txt", "notes.txt", b"Darcy returns."),
            (
                "docx",
                "notes.docx",
                _make_docx(
                    """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body>
                        <w:p><w:r><w:t>Darcy returns.</w:t></w:r></w:p>
                      </w:body>
                    </w:document>
                    """
                ),
            ),
        )
        for document_kind, file_name, content in cases:
            with self.subTest(document_kind=document_kind):
                with TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    storage = LocalObjectStorage(root / "objects")
                    persistent_store = SQLiteTranslationJobStore(
                        root / "jobs.sqlite3"
                    )
                    run_log_root = root / "translation-runs"
                    self.addCleanup(persistent_store.close)
                    source_sha256 = hashlib.sha256(content).hexdigest()

                    def prepared_package_resolver(
                        request,
                        *,
                        expected_source_sha256=source_sha256,
                    ):
                        return PreparedGlossaryPackageAttachment(
                            payload=_prepared_glossary_package(),
                            source_sha256=expected_source_sha256,
                            document_kind=request.document_kind,
                            target_language=request.target_language,
                        )

                    service = BotTranslationService(
                        job_repository=InMemoryTranslationJobRepository(),
                        pricing_rules=_pricing_rules(),
                        max_upload_mb=50,
                        max_fragment_chars=200,
                        file_storage=storage,
                        persistent_job_store=persistent_store,
                        translation_run_log_root=run_log_root,
                        use_scheduler_runner=True,
                        prepared_glossary_package_resolver=prepared_package_resolver,
                    )
                    service.store_uploaded_document(
                        user_telegram_id=42,
                        file_name=file_name,
                        content=content,
                        source_language="en",
                    )
                    service.confirm_pending_upload_rights(user_telegram_id=42)
                    self._select_default_translation_mode(service)
                    service.prepare_pending_upload(
                        user_telegram_id=42,
                        target_language="ru",
                        glossary_mode=GLOSSARY_MODE_WITH,
                    )
                    self._accept_pending_preview(service)
                    translator = RecordingTranslator()

                    job = service.confirm_pending_translation(
                        user_telegram_id=42,
                        translator=translator,
                    )

                    self.assertEqual(job.status, TranslationJobStatus.READY)
                    self.assertGreaterEqual(len(translator.requests), 1)
                    self.assertTrue(
                        any(
                            "<glossary_context" in request[0]
                            for request in translator.requests
                        ),
                    )
                    self.assertTrue(
                        any("Дарси" in request[0] for request in translator.requests),
                    )
                    policy = json.loads(
                        persistent_store.get_job(job.id).translation_policy
                    )
                    self.assertEqual(policy["glossary_mode"], GLOSSARY_MODE_WITH)
                    self.assertEqual(
                        policy["prepared_glossary_package"]["package_id"],
                        "prepared:bot-test:ru",
                    )
                    run_dir = next(run_log_root.iterdir())
                    event_lines = run_dir.joinpath("events.jsonl").read_text()
                    self.assertIn(
                        '"document_format": "' + document_kind + '"',
                        event_lines,
                    )
                    self.assertIn("prepared_glossary_package_attachment", event_lines)
                    self.assertIn('"attachment_status": "attached"', event_lines)
                    self.assertIn("bypass_glossary_injected_cache", event_lines)
                    self.assertNotIn("Darcy returns.", event_lines)
                    self.assertNotIn("sk-", event_lines)

    def test_epub_with_glossary_prep_resolver_attaches_ready_package(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            persistent_store = SQLiteTranslationJobStore(root / "jobs.sqlite3")
            run_log_root = root / "translation-runs"
            self.addCleanup(persistent_store.close)
            content = _make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body><p>Darcy returns.</p></body>
                    </html>
                    """
                }
            )
            source_sha256 = hashlib.sha256(content).hexdigest()
            prep_requests = []
            guard = RecordingBetaSafetyGuard()

            def prep_resolver(request):
                prep_requests.append(request)
                return PreparedGlossaryPackageAttachment(
                    payload=_prepared_glossary_package(),
                    source_sha256=request.source_sha256,
                    document_kind=request.document_kind,
                    target_language=request.target_language,
                )

            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=200,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
                use_scheduler_runner=True,
                prepared_glossary_package_prep_resolver=prep_resolver,
                beta_safety_guard=guard,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="book.epub",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="ru",
                glossary_mode=GLOSSARY_MODE_WITH,
            )
            self._accept_pending_preview(service)
            translator = RecordingTranslator()

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

            self.assertEqual(job.status, TranslationJobStatus.READY)
            self.assertEqual(len(prep_requests), 1)
            self.assertEqual(prep_requests[0].source_sha256, source_sha256)
            self.assertEqual(prep_requests[0].content, content)
            self.assertEqual(len(translator.requests), 1)
            self.assertIn("<glossary_context", translator.requests[0][0])
            policy = json.loads(persistent_store.get_job(job.id).translation_policy)
            self.assertIn("prepared_glossary_package", policy)
            event_lines = next(run_log_root.iterdir()).joinpath(
                "events.jsonl"
            ).read_text()
            self.assertIn('"attachment_source": "prep"', event_lines)
            self.assertIn('"attachment_status": "attached"', event_lines)
            self.assertIn('"reservation_status": "consumed"', event_lines)
            self.assertIn(
                '"accounting_usage_source": "estimate_when_provider_usage_unknown"',
                event_lines,
            )
            self.assertIn(
                "prepared_glossary_prep_provider_usage_unknown_estimate_accounted",
                event_lines,
            )
            self.assertIn('"provider_reported_usage_status": "Unknown"', event_lines)
            self.assertIn("bypass_glossary_injected_cache", event_lines)
            self.assertNotIn("Darcy returns.", event_lines)
            self.assertNotIn("sk-", event_lines)
            self.assertTrue(guard.reservations[0][0].startswith("glossary-prep:"))
            self.assertEqual(guard.usage_events[0][0], guard.reservations[0][0])
            self.assertEqual(
                guard.usage_events[0][2],
                f"{guard.reservations[0][0]}:prepared_glossary_prep",
            )

    def test_glossary_prep_beta_safety_denial_skips_prep_and_continues(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            persistent_store = SQLiteTranslationJobStore(root / "jobs.sqlite3")
            run_log_root = root / "translation-runs"
            self.addCleanup(persistent_store.close)
            content = b"Darcy returns."
            prep_requests = []
            guard = DenyGlossaryPrepBetaSafetyGuard()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=200,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
                use_scheduler_runner=True,
                prepared_glossary_package_prep_resolver=lambda request: (
                    prep_requests.append(request) or None
                ),
                beta_safety_guard=guard,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="ru",
                glossary_mode=GLOSSARY_MODE_WITH,
            )
            self._accept_pending_preview(service)
            translator = RecordingTranslator()

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

            self.assertEqual(job.status, TranslationJobStatus.READY)
            self.assertEqual(prep_requests, [])
            self.assertEqual(len(translator.requests), 1)
            self.assertNotIn("<glossary_context", translator.requests[0][0])
            policy = json.loads(persistent_store.get_job(job.id).translation_policy)
            self.assertEqual(policy["glossary_mode"], GLOSSARY_MODE_WITH)
            self.assertNotIn("prepared_glossary_package", policy)
            event_lines = next(run_log_root.iterdir()).joinpath(
                "events.jsonl"
            ).read_text()
            self.assertIn(
                "prepared_glossary_prep_beta_safety_reservation_denied",
                event_lines,
            )
            self.assertIn("beta_safety_job_estimate_cap", event_lines)
            self.assertNotIn("Darcy returns.", event_lines)
            self.assertTrue(guard.reservations[0][0].startswith("glossary-prep:"))
            self.assertTrue(
                any(
                    reservation[0] == job.id
                    for reservation in guard.reservations
                )
            )

    def test_glossary_prep_provider_usage_metadata_records_actual_usage(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            persistent_store = SQLiteTranslationJobStore(root / "jobs.sqlite3")
            run_log_root = root / "translation-runs"
            self.addCleanup(persistent_store.close)
            content = b"Darcy returns."
            guard = RecordingBetaSafetyGuard()

            def prep_resolver(request):
                return PreparedGlossaryPackageAttachment(
                    payload=_prepared_glossary_package(),
                    source_sha256=request.source_sha256,
                    document_kind=request.document_kind,
                    target_language=request.target_language,
                    metadata={
                        "provider_usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 5,
                        }
                    },
                )

            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=200,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
                use_scheduler_runner=True,
                prepared_glossary_package_prep_resolver=prep_resolver,
                beta_safety_guard=guard,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="ru",
                glossary_mode=GLOSSARY_MODE_WITH,
            )
            self._accept_pending_preview(service)

            service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

            self.assertEqual(guard.usage_events[0][3:], (10, 5))
            event_lines = next(run_log_root.iterdir()).joinpath(
                "events.jsonl"
            ).read_text()
            self.assertIn('"accounting_usage_source": "provider_reported"', event_lines)
            self.assertIn('"provider_reported_usage_status": "reported"', event_lines)
            self.assertNotIn("Darcy returns.", event_lines)

    def test_without_glossary_does_not_attach_prepared_package(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            persistent_store = SQLiteTranslationJobStore(root / "jobs.sqlite3")
            run_log_root = root / "translation-runs"
            self.addCleanup(persistent_store.close)
            content = b"Darcy returns."
            prep_requests = []
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=200,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
                use_scheduler_runner=True,
                prepared_glossary_package_resolver=lambda request: (
                    PreparedGlossaryPackageAttachment(
                        payload=_prepared_glossary_package(),
                        source_sha256=hashlib.sha256(content).hexdigest(),
                        document_kind="txt",
                        target_language="ru",
                    )
                ),
                prepared_glossary_package_prep_resolver=lambda request: (
                    prep_requests.append(request) or None
                ),
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="ru",
                glossary_mode=GLOSSARY_MODE_WITHOUT,
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

            policy = json.loads(persistent_store.get_job(job.id).translation_policy)
            self.assertEqual(policy["glossary_mode"], GLOSSARY_MODE_WITHOUT)
            self.assertNotIn("prepared_glossary_package", policy)
            event_lines = next(run_log_root.iterdir()).joinpath(
                "events.jsonl"
            ).read_text()
            self.assertNotIn("prepared_glossary_package_attachment", event_lines)
            self.assertEqual(prep_requests, [])

    def test_with_glossary_missing_attachment_records_not_effective_metadata(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            persistent_store = SQLiteTranslationJobStore(root / "jobs.sqlite3")
            run_log_root = root / "translation-runs"
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=200,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
                use_scheduler_runner=True,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"Darcy returns.",
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="ru",
                glossary_mode=GLOSSARY_MODE_WITH,
            )
            self._accept_pending_preview(service)
            translator = RecordingTranslator()

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

            self.assertEqual(job.status, TranslationJobStatus.READY)
            policy = json.loads(persistent_store.get_job(job.id).translation_policy)
            self.assertNotIn("prepared_glossary_package", policy)
            self.assertNotIn("<glossary_context", translator.requests[0][0])
            event_lines = next(run_log_root.iterdir()).joinpath(
                "events.jsonl"
            ).read_text()
            self.assertIn(
                "prepared_glossary_package_attachment_disabled",
                event_lines,
            )
            self.assertIn(
                "prepared_glossary_package_required_for_with_glossary",
                event_lines,
            )
            self.assertIn('"diagnostic_severity": "error"', event_lines)
            self.assertIn('"glossary_effective_status": "not_effective"', event_lines)
            self.assertNotIn("Darcy returns.", event_lines)

    def test_with_glossary_prep_missing_fails_closed_before_queueing(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            persistent_store = SQLiteTranslationJobStore(root / "jobs.sqlite3")
            run_log_root = root / "translation-runs"
            self.addCleanup(persistent_store.close)
            content = b"Darcy returns."
            prep_requests = []
            guard = RecordingBetaSafetyGuard()

            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=200,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
                use_scheduler_runner=True,
                prepared_glossary_package_prep_resolver=lambda request: (
                    prep_requests.append(request) or None
                ),
                beta_safety_guard=guard,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="ru",
                glossary_mode=GLOSSARY_MODE_WITH,
            )
            self._accept_pending_preview(service)
            translator = RecordingTranslator()

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

            self.assertEqual(job.status, TranslationJobStatus.FAILED)
            self.assertIn(
                "prepared_glossary_package_prep_missing",
                job.error_message,
            )
            self.assertEqual(len(prep_requests), 1)
            self.assertEqual(prep_requests[0].content, content)
            self.assertEqual(translator.requests, [])
            self.assertEqual(
                persistent_store.list_jobs_for_user("telegram:42"),
                [],
            )
            self.assertFalse(run_log_root.exists())
            self.assertTrue(guard.reservations[0][0].startswith("glossary-prep:"))
            self.assertEqual(guard.consumed, [guard.reservations[0][0]])

    def test_with_glossary_invalid_prepared_package_is_not_attached(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            persistent_store = SQLiteTranslationJobStore(root / "jobs.sqlite3")
            run_log_root = root / "translation-runs"
            self.addCleanup(persistent_store.close)
            content = b"Darcy returns."
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=200,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
                use_scheduler_runner=True,
                prepared_glossary_package_resolver=lambda request: (
                    PreparedGlossaryPackageAttachment(
                        payload=_prepared_glossary_package(target_language="uk"),
                        source_sha256=hashlib.sha256(content).hexdigest(),
                        document_kind="txt",
                        target_language="ru",
                    )
                ),
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="ru",
                glossary_mode=GLOSSARY_MODE_WITH,
            )
            self._accept_pending_preview(service)
            translator = RecordingTranslator()

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

            policy = json.loads(persistent_store.get_job(job.id).translation_policy)
            self.assertNotIn("prepared_glossary_package", policy)
            self.assertNotIn("<glossary_context", translator.requests[0][0])
            event_lines = next(run_log_root.iterdir()).joinpath(
                "events.jsonl"
            ).read_text()
            self.assertIn("prepared_glossary_package_target_mismatch", event_lines)

    def test_with_glossary_non_matching_prepared_package_is_not_attached(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            persistent_store = SQLiteTranslationJobStore(root / "jobs.sqlite3")
            run_log_root = root / "translation-runs"
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=200,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
                use_scheduler_runner=True,
                prepared_glossary_package_resolver=lambda request: (
                    PreparedGlossaryPackageAttachment(
                        payload=_prepared_glossary_package(),
                        source_sha256="not-the-uploaded-document",
                        document_kind="txt",
                        target_language="ru",
                    )
                ),
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"Darcy returns.",
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="ru",
                glossary_mode=GLOSSARY_MODE_WITH,
            )
            self._accept_pending_preview(service)
            translator = RecordingTranslator()

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

            policy = json.loads(persistent_store.get_job(job.id).translation_policy)
            self.assertNotIn("prepared_glossary_package", policy)
            self.assertNotIn("<glossary_context", translator.requests[0][0])
            event_lines = next(run_log_root.iterdir()).joinpath(
                "events.jsonl"
            ).read_text()
            self.assertIn(
                "prepared_glossary_package_attachment_source_mismatch",
                event_lines,
            )

    def test_persistent_confirmation_records_provider_io_without_scheduler_runner(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            persistent_store = SQLiteTranslationJobStore(root / "jobs.sqlite3")
            self.addCleanup(persistent_store.close)
            run_log_root = root / "translation-runs"
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=500,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"First item\nBody text.\n",
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=ProviderIODiagnosticTranslator(),
            )

            self.assertEqual(job.status, TranslationJobStatus.READY)
            provider_io_paths = list(
                run_log_root.glob("*/provider_io_diagnostics.jsonl")
            )
            self.assertEqual(len(provider_io_paths), 1)
            records = [
                json.loads(line)
                for line in provider_io_paths[0]
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertGreaterEqual(len(records), 1)
            self.assertEqual({record["job_id"] for record in records}, {job.id})
            self.assertIn(1, {record["sequence"] for record in records})
            self.assertEqual(
                {record["request_body"]["text"] for record in records},
                {"request-body"},
            )
            self.assertEqual(
                {record["response_body"]["text"] for record in records},
                {"response-body"},
            )

    def test_persistent_confirmation_records_provider_io_with_scheduler_runner(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            persistent_store = SQLiteTranslationJobStore(root / "jobs.sqlite3")
            self.addCleanup(persistent_store.close)
            run_log_root = root / "translation-runs"
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=500,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
                use_scheduler_runner=True,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"First item\nBody text.\n",
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=ProviderIODiagnosticTranslator(),
            )

            self.assertEqual(job.status, TranslationJobStatus.READY)
            provider_io_paths = list(
                run_log_root.glob("*/provider_io_diagnostics.jsonl")
            )
            self.assertEqual(len(provider_io_paths), 1)
            records = [
                json.loads(line)
                for line in provider_io_paths[0]
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertGreaterEqual(len(records), 1)
            self.assertEqual({record["job_id"] for record in records}, {job.id})
            self.assertIn(1, {record["sequence"] for record in records})
            self.assertEqual(
                {record["request_body"]["text"] for record in records},
                {"request-body"},
            )
            self.assertEqual(
                {record["response_body"]["text"] for record in records},
                {"response-body"},
            )

    def test_persistent_confirmation_can_defer_work_to_external_worker(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            run_log_root = Path(temp_dir) / "translation-runs"
            translator = RecordingTranslator()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
                use_scheduler_runner=True,
                defer_persistent_jobs_to_worker=True,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"First item\nBody text.\n",
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

            persisted_job = persistent_store.get_job(job.id)
            work_units = persistent_store.list_work_units(job.id)
            self.assertEqual(job.status, TranslationJobStatus.QUEUED)
            self.assertEqual(
                persisted_job.status, PersistentTranslationJobStatus.QUEUED
            )
            self.assertTrue(work_units)
            self.assertTrue(
                all(
                    unit.status is PersistentWorkUnitStatus.PENDING
                    for unit in work_units
                )
            )
            self.assertEqual(translator.requests, [])
            runs = list_translation_run_summaries(run_log_root)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0].job_id, job.id)
            self.assertEqual(runs[0].status, "running")
            self.assertEqual(runs[0].file_name, "notes.txt")
            self.assertEqual(runs[0].total_fragment_count, len(work_units))

    def test_persistent_txt_confirmation_can_run_work_units_in_parallel(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            guard = RecordingBetaSafetyGuard()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
                max_parallel_work_units=2,
                beta_safety_guard=guard,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One.\n\nTwo.",
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            self._accept_pending_preview(service)
            translator = ParallelBlockingTranslator(expected_parallel_calls=2)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

            self.assertEqual(job.status, TranslationJobStatus.READY)
            self.assertEqual(translator.max_active_calls, 2)
            self.assertEqual(
                job.result_content.decode("utf-8"),
                "[uk] One.\n\n[uk] Two.",
            )
            self.assertEqual(guard.consumed, [job.id])

    def test_persistent_txt_cancellation_returns_partial_result(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            guard = RecordingBetaSafetyGuard()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
                beta_safety_guard=guard,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"One.\nTwo.\n",
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="uk",
            )
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=CancellingTranslator(service, 42),
            )

            persisted_job = persistent_store.get_job(job.id)
            self.assertEqual(job.status, TranslationJobStatus.CANCELLED)
            self.assertEqual(job.result_file_name, "notes.uk.partial.txt")
            self.assertEqual(job.result_content.decode("utf-8"), "[uk] One.\nTwo.\n")
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.CANCELLED,
            )
            self.assertEqual(guard.releases, [(job.id, "cancelled")])
            self.assertIsNotNone(persisted_job.partial_object_key)
            self.assertEqual(
                storage.get_bytes(persisted_job.partial_object_key),
                job.result_content,
            )

    def test_persistent_docx_confirmation_assembles_stored_work_units(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=8,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="contract.docx",
                content=_make_docx(
                    """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body>
                        <w:p><w:r><w:t>Alpha one.</w:t></w:r></w:p>
                        <w:p><w:r><w:t>Beta two.</w:t></w:r></w:p>
                      </w:body>
                    </w:document>
                    """
                ),
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(user_telegram_id=42, target_language="uk")
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

            persisted_job = persistent_store.get_job(job.id)
            self.assertEqual(job.status, TranslationJobStatus.READY)
            self.assertEqual(job.document_kind, DocumentKind.DOCX)
            self.assertEqual(job.result_file_name, "contract.uk.docx")
            self.assertIsNotNone(persisted_job)
            self.assertEqual(
                extract_text_from_docx(job.result_content),
                "[uk] Alpha one.\n\n[uk] Beta two.",
            )
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.READY,
            )
            self.assertIsNotNone(persisted_job.final_object_key)
            self.assertEqual(
                storage.get_bytes(persisted_job.final_object_key),
                job.result_content,
            )

    def test_persistent_docx_confirmation_assembles_with_document_sandbox(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            sandbox = RecordingDocumentSandbox()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=8,
                file_storage=storage,
                persistent_job_store=persistent_store,
                document_sandbox=sandbox,
            )
            source_content = _make_docx(
                """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body>
                    <w:p><w:r><w:t>Alpha one.</w:t></w:r></w:p>
                    <w:p><w:r><w:t>Beta two.</w:t></w:r></w:p>
                  </w:body>
                </w:document>
                """
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="contract.docx",
                content=source_content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(user_telegram_id=42, target_language="uk")
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

            self.assertEqual(job.status, TranslationJobStatus.READY)
            self.assertEqual(
                extract_text_from_docx(job.result_content),
                "[uk] Alpha one.\n\n[uk] Beta two.",
            )
            self.assertEqual(len(sandbox.assemble_calls), 1)
            document_format, content, translated_units = sandbox.assemble_calls[0]
            self.assertEqual(document_format, DocumentFormat.DOCX)
            self.assertEqual(content, source_content)
            self.assertEqual(
                translated_units,
                [
                    SandboxTranslationUnit(
                        source_block_ids=("docx:word/document.xml:0",),
                        translated_text="[uk] Alpha one.",
                    ),
                    SandboxTranslationUnit(
                        source_block_ids=("docx:word/document.xml:1",),
                        translated_text="[uk] Beta two.",
                    ),
                ],
            )

    def test_persistent_docx_confirmation_fails_closed_when_sandbox_assembly_fails(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=8,
                file_storage=storage,
                persistent_job_store=persistent_store,
                document_sandbox=FailingAssemblyDocumentSandbox(),
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="contract.docx",
                content=_make_docx(
                    """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body><w:p><w:r><w:t>Alpha one.</w:t></w:r></w:p></w:body>
                    </w:document>
                    """
                ),
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(user_telegram_id=42, target_language="uk")
            self._accept_pending_preview(service)

            with self.assertLogs(
                "translator_service.bot_translation_service",
                level="ERROR",
            ):
                job = service.confirm_pending_translation(
                    user_telegram_id=42,
                    translator=RecordingTranslator(),
                )

            persisted_job = persistent_store.get_job(job.id)
            self.assertEqual(job.status, TranslationJobStatus.FAILED)
            self.assertIsNone(job.result_content)
            self.assertIn("assembly sandbox failed", job.error_message)
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.INTERRUPTED,
            )

    def test_persistent_docx_confirmation_recovers_when_batch_output_is_malformed(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=1_000,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="contract.docx",
                content=_make_docx(
                    """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body>
                        <w:p><w:r><w:t>Intro paragraph.</w:t></w:r></w:p>
                        <w:tbl>
                          <w:tr>
                            <w:tc><w:p><w:r><w:t>Source</w:t></w:r></w:p></w:tc>
                            <w:tc><w:p><w:r><w:t>Target</w:t></w:r></w:p></w:tc>
                          </w:tr>
                        </w:tbl>
                        <w:p><w:r><w:t>Outro paragraph.</w:t></w:r></w:p>
                      </w:body>
                    </w:document>
                    """
                ),
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(user_telegram_id=42, target_language="uk")
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=MalformedSecondUnitTranslator(),
            )

            persisted_job = persistent_store.get_job(job.id)
            self.assertEqual(job.status, TranslationJobStatus.READY)
            self.assertEqual(job.result_file_name, "contract.uk.docx")
            self.assertEqual(
                extract_text_from_docx(job.result_content),
                "[uk] Intro paragraph.\n\n[uk] Source\n\n[uk] Target\n\n"
                "[uk] Outro paragraph.",
            )
            self.assertIsNotNone(persisted_job.final_object_key)

    def test_persistent_epub_cancellation_assembles_partial_result(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=8,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="book.epub",
                content=_make_epub(
                    {
                        "OPS/chapter.xhtml": """
                        <html xmlns="http://www.w3.org/1999/xhtml">
                          <body>
                            <p>First body paragraph.</p>
                            <p>Second body paragraph.</p>
                          </body>
                        </html>
                        """
                    }
                ),
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(user_telegram_id=42, target_language="uk")
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=CancellingTranslator(service, 42),
            )

            persisted_job = persistent_store.get_job(job.id)
            self.assertEqual(job.status, TranslationJobStatus.CANCELLED)
            self.assertEqual(job.document_kind, DocumentKind.EPUB)
            self.assertEqual(job.result_file_name, "book.uk.partial.epub")
            partial_text = extract_text_from_epub(job.result_content)
            self.assertIn("[uk] First body paragraph.", partial_text)
            self.assertIn("Second body paragraph.", partial_text)
            self.assertIsNotNone(persisted_job)
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.CANCELLED,
            )
            self.assertIsNotNone(persisted_job.partial_object_key)
            self.assertEqual(
                storage.get_bytes(persisted_job.partial_object_key),
                job.result_content,
            )

    def test_persistent_epub_confirmation_assembles_with_document_sandbox(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            sandbox = RecordingDocumentSandbox()
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=8,
                file_storage=storage,
                persistent_job_store=persistent_store,
                document_sandbox=sandbox,
            )
            source_content = _make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body>
                        <p>Alpha one.</p>
                        <p>Beta two.</p>
                      </body>
                    </html>
                    """
                }
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="book.epub",
                content=source_content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(user_telegram_id=42, target_language="uk")
            self._accept_pending_preview(service)

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

            self.assertEqual(job.status, TranslationJobStatus.READY)
            result_text = extract_text_from_epub(job.result_content)
            self.assertIn("[uk] Alpha one.", result_text)
            self.assertIn("[uk] Beta two.", result_text)
            self.assertEqual(len(sandbox.assemble_calls), 1)
            document_format, content, translated_units = sandbox.assemble_calls[0]
            self.assertEqual(document_format, DocumentFormat.EPUB)
            self.assertEqual(content, source_content)
            self.assertEqual(
                translated_units,
                [
                    SandboxTranslationUnit(
                        source_block_ids=("epub:OPS/chapter.xhtml:0",),
                        translated_text="[uk] Alpha one.",
                    ),
                    SandboxTranslationUnit(
                        source_block_ids=("epub:OPS/chapter.xhtml:1",),
                        translated_text="[uk] Beta two.",
                    ),
                ],
            )

    def test_lists_persistent_books_for_user(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=Path(temp_dir) / "translation-runs",
            )
            self.addCleanup(service.close)
            first = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="first.epub",
                document_kind="epub",
                source_language="en",
                target_language="uk",
                adapter_version="epub-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key="original/first.epub",
            )
            second = persistent_store.create_job(
                order_id="order-2",
                user_id="telegram:42",
                file_id="file-2",
                file_name="second.docx",
                document_kind="docx",
                source_language="auto",
                target_language="ru",
                adapter_version="docx-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key="original/second.docx",
            )
            persistent_store.create_job(
                order_id="order-3",
                user_id="telegram:100",
                file_id="file-3",
                file_name="other.txt",
                document_kind="txt",
                source_language="en",
                target_language="fr",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key="original/other.txt",
            )

            books = service.list_user_books(user_telegram_id=42)

            self.assertEqual(
                [
                    (
                        book.job_id,
                        book.file_name,
                        book.document_kind,
                        book.source_language,
                        book.target_language,
                        book.status,
                        book.has_result,
                    )
                    for book in books[:2]
                ],
                [
                    (second.id, "second.docx", "docx", "auto", "ru", "queued", False),
                    (first.id, "first.epub", "epub", "en", "uk", "queued", False),
                ],
            )
            self.assertIsNotNone(books[0].created_at)
            self.assertIsNotNone(books[0].updated_at)

    def test_loads_latest_persistent_book_result(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            self.addCleanup(service.close)
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="book.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key="original/book.txt",
            )
            stored = storage.put_bytes(
                kind=StoredFileKind.FINAL,
                file_name="book.uk.txt",
                content_type="text/plain; charset=utf-8",
                content=b"translated",
            )
            persistent_store.attach_job_output(
                job.id, final_object_key=stored.object_key
            )

            result = service.get_latest_user_book_result(user_telegram_id=42)

            self.assertEqual(
                result,
                UserBookResult(
                    job_id=job.id,
                    file_name="book.uk.txt",
                    content=b"translated",
                    content_type="text/plain; charset=utf-8",
                ),
            )

    def test_persistent_book_summary_is_not_download_ready_when_object_is_missing(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            self.addCleanup(service.close)
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="book.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key="original/book.txt",
            )
            stored = storage.put_bytes(
                kind=StoredFileKind.FINAL,
                file_name="book.uk.txt",
                content_type="text/plain; charset=utf-8",
                content=b"translated",
            )
            persistent_store.attach_job_output(
                job.id, final_object_key=stored.object_key
            )
            persistent_store.mark_job_assembled(job.id, partial=False)
            storage.delete(stored.object_key)

            books = service.list_user_books(user_telegram_id=42)
            detail = service.get_user_book_detail(
                user_telegram_id=42,
                job_id=job.id,
            )
            result = service.get_user_book_result(
                user_telegram_id=42,
                job_id=job.id,
            )

            self.assertEqual(len(books), 1)
            self.assertFalse(books[0].has_result)
            self.assertFalse(books[0].has_partial_result)
            self.assertIsNotNone(detail)
            self.assertFalse(detail.has_result)
            self.assertIsNone(result)

    def test_persistent_book_summary_shows_partial_when_final_object_is_missing(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            self.addCleanup(service.close)
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="book.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key="original/book.txt",
            )
            partial = storage.put_bytes(
                kind=StoredFileKind.PARTIAL,
                file_name="book.uk.partial.txt",
                content_type="text/plain; charset=utf-8",
                content=b"partial translated",
            )
            final = storage.put_bytes(
                kind=StoredFileKind.FINAL,
                file_name="book.uk.txt",
                content_type="text/plain; charset=utf-8",
                content=b"translated",
            )
            persistent_store.attach_job_output(
                job.id,
                partial_object_key=partial.object_key,
                final_object_key=final.object_key,
            )
            persistent_store.mark_job_assembled(job.id, partial=True)
            storage.delete(final.object_key)

            books = service.list_user_books(user_telegram_id=42)
            detail = service.get_user_book_detail(
                user_telegram_id=42,
                job_id=job.id,
            )
            result = service.get_user_book_result(
                user_telegram_id=42,
                job_id=job.id,
            )

            self.assertEqual(len(books), 1)
            self.assertTrue(books[0].has_result)
            self.assertTrue(books[0].has_partial_result)
            self.assertIsNotNone(detail)
            self.assertTrue(detail.has_result)
            self.assertTrue(detail.has_partial_result)
            self.assertEqual(
                result,
                UserBookResult(
                    job_id=job.id,
                    file_name="book.uk.partial.txt",
                    content=b"partial translated",
                    content_type="text/plain; charset=utf-8",
                ),
            )

    def test_persistent_book_summary_hides_partial_when_final_exists(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            self.addCleanup(service.close)
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="book.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key="original/book.txt",
            )
            partial = storage.put_bytes(
                kind=StoredFileKind.PARTIAL,
                file_name="book.uk.partial.txt",
                content_type="text/plain; charset=utf-8",
                content=b"partial translated",
            )
            final = storage.put_bytes(
                kind=StoredFileKind.FINAL,
                file_name="book.uk.txt",
                content_type="text/plain; charset=utf-8",
                content=b"translated",
            )
            persistent_store.attach_job_output(
                job.id,
                partial_object_key=partial.object_key,
                final_object_key=final.object_key,
            )
            persistent_store.mark_job_assembled(job.id, partial=False)

            books = service.list_user_books(user_telegram_id=42)
            detail = service.get_user_book_detail(
                user_telegram_id=42,
                job_id=job.id,
            )
            result = service.get_user_book_result(
                user_telegram_id=42,
                job_id=job.id,
            )

            self.assertEqual(len(books), 1)
            self.assertTrue(books[0].has_result)
            self.assertFalse(books[0].has_partial_result)
            self.assertIsNotNone(detail)
            self.assertTrue(detail.has_result)
            self.assertFalse(detail.has_partial_result)
            self.assertEqual(
                result,
                UserBookResult(
                    job_id=job.id,
                    file_name="book.uk.txt",
                    content=b"translated",
                    content_type="text/plain; charset=utf-8",
                ),
            )

    def test_loads_specific_persistent_book_result_for_owner(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=20,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            self.addCleanup(service.close)
            first = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="first.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key="original/first.txt",
            )
            second = persistent_store.create_job(
                order_id="order-2",
                user_id="telegram:42",
                file_id="file-2",
                file_name="second.txt",
                document_kind="txt",
                source_language="en",
                target_language="ru",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key="original/second.txt",
            )
            other_user = persistent_store.create_job(
                order_id="order-3",
                user_id="telegram:100",
                file_id="file-3",
                file_name="other.txt",
                document_kind="txt",
                source_language="en",
                target_language="fr",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key="original/other.txt",
            )
            first_stored = storage.put_bytes(
                kind=StoredFileKind.FINAL,
                file_name="first.uk.txt",
                content_type="text/plain; charset=utf-8",
                content=b"first translated",
            )
            second_stored = storage.put_bytes(
                kind=StoredFileKind.FINAL,
                file_name="second.ru.txt",
                content_type="text/plain; charset=utf-8",
                content=b"second translated",
            )
            other_stored = storage.put_bytes(
                kind=StoredFileKind.FINAL,
                file_name="other.fr.txt",
                content_type="text/plain; charset=utf-8",
                content=b"other translated",
            )
            persistent_store.attach_job_output(
                first.id,
                final_object_key=first_stored.object_key,
            )
            persistent_store.attach_job_output(
                second.id,
                final_object_key=second_stored.object_key,
            )
            persistent_store.attach_job_output(
                other_user.id,
                final_object_key=other_stored.object_key,
            )

            result = service.get_user_book_result(
                user_telegram_id=42,
                job_id=first.id,
            )

            self.assertEqual(
                result,
                UserBookResult(
                    job_id=first.id,
                    file_name="first.uk.txt",
                    content=b"first translated",
                    content_type="text/plain; charset=utf-8",
                ),
            )
            self.assertIsNone(
                service.get_user_book_result(
                    user_telegram_id=42,
                    job_id=other_user.id,
                )
            )

    def test_deletes_user_book_and_stored_files_for_owner(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            run_log_root = Path(temp_dir) / "translation-runs"
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
            )
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.txt",
                content_type="text/plain",
                content=b"Original",
            )
            partial = storage.put_bytes(
                kind=StoredFileKind.PARTIAL,
                file_name="book.uk.partial.txt",
                content_type="text/plain",
                content=b"Partial",
            )
            final = storage.put_bytes(
                kind=StoredFileKind.FINAL,
                file_name="book.uk.txt",
                content_type="text/plain",
                content=b"Final",
            )
            unit_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="book-unit-1.txt",
                content_type="text/plain",
                content=b"Unit",
            )
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id=original.object_key,
                source_object_key=original.object_key,
                file_name="book.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="v1",
                prompt_version="v1",
                pricing_snapshot_id="pricing-v1",
            )
            persistent_store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:0",),
                        source_object_key=unit_source.object_key,
                        source_text_hash="hash-1",
                        prompt_tier="default",
                        source_language="en",
                        target_language="uk",
                    )
                ],
            )
            persistent_store.attach_job_output(
                job.id,
                partial_object_key=partial.object_key,
                final_object_key=final.object_key,
            )
            run_logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id=job.id,
                    order_id="order-1",
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                ),
            )

            self.assertFalse(
                service.delete_user_book(user_telegram_id=100, job_id=job.id)
            )
            self.assertIsNotNone(persistent_store.get_job(job.id))

            self.assertTrue(
                service.delete_user_book(user_telegram_id=42, job_id=job.id)
            )

            self.assertIsNone(persistent_store.get_job(job.id))
            for object_key in (
                original.object_key,
                partial.object_key,
                final.object_key,
                unit_source.object_key,
            ):
                self.assertFalse(storage.exists(object_key))
            run_snapshot = json.loads((run_logger.run_dir / "run.json").read_text())
            self.assertEqual(run_snapshot["status"], "cancelled")
            self.assertEqual(run_snapshot["error_message"], "Book deleted by user.")

    def test_delete_user_book_keeps_strict_job_source_and_run(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            run_log_root = Path(temp_dir) / "translation-runs"
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"strict-source",
            )
            approval_payload = b"strict-approval"
            approval = persistent_store.create_glossary_approval(
                snapshot_payload=approval_payload,
                snapshot_digest=hashlib.sha256(approval_payload).hexdigest(),
                snapshot_schema_version=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
                approval_schema_version=GLOSSARY_APPROVAL_SCHEMA_VERSION,
            )
            admitted = persistent_store.admit_strict_docx_job(
                StrictDocxAdmissionRequest(
                    approval_id=approval.approval_id,
                    order_id="order-strict-delete",
                    user_id="telegram:42",
                    file_id=source.object_key,
                    file_name="book.docx",
                    document_kind="docx",
                    source_object_key=source.object_key,
                    source_language="en",
                    target_language="uk",
                    adapter_version="docx-v1",
                    prompt_version="plain-v1",
                    pricing_snapshot_id="pricing-1",
                    translation_policy=None,
                    work_units=[
                        WorkUnitPlan(
                            sequence=1,
                            source_block_ids=("docx:1",),
                            source_text_hash="hash-1",
                            prompt_tier="plain",
                            source_language="en",
                            target_language="uk",
                            source_object_key=source.object_key,
                        )
                    ],
                )
            )
            if admitted.job is None:
                self.fail("strict job admission unexpectedly denied")
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
            )
            run_logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id=admitted.job.id,
                    order_id="order-strict-delete",
                    user_id="telegram:42",
                    file_name="book.docx",
                    document_kind="docx",
                    source_language="en",
                    target_language="uk",
                ),
            )

            self.assertFalse(
                service.delete_user_book(
                    user_telegram_id=42,
                    job_id=admitted.job.id,
                )
            )

            self.assertIsNotNone(persistent_store.get_job(admitted.job.id))
            self.assertEqual(len(persistent_store.list_work_units(admitted.job.id)), 1)
            self.assertTrue(storage.exists(source.object_key))
            self.assertIsNotNone(
                persistent_store.read_approved_glossary_snapshot(
                    approval_id=approval.approval_id
                )
            )
            run_snapshot = json.loads((run_logger.run_dir / "run.json").read_text())
            self.assertEqual(run_snapshot["status"], "running")

    def test_concurrent_confirm_claims_pending_translation_once(self):
        repository = InMemoryTranslationJobRepository()
        service = BotTranslationService(
            job_repository=repository,
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.",
            source_language="en",
            target_language="uk",
        )
        self._accept_pending_preview(service)
        translator = BlockingTranslator()

        def confirm():
            return service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(confirm), pool.submit(confirm)]
            results = []
            errors = []
            for future in futures:
                try:
                    results.append(future.result(timeout=5))
                except ValueError as error:
                    errors.append(str(error))

        self.assertEqual([job.id for job in results], ["job-1"])
        self.assertEqual(errors, ["No pending translation for this user"])
        self.assertEqual(len(translator.requests), 1)

    def test_failed_translation_returns_failed_job_and_keeps_pending_retry(self):
        repository = InMemoryTranslationJobRepository()
        service = BotTranslationService(
            job_repository=repository,
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.",
            source_language="en",
            target_language="uk",
        )
        pending = self._accept_pending_preview(service)

        with self.assertLogs(
            "translator_service.bot_translation_service", level="ERROR"
        ) as logs:
            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=FailingTranslator(),
            )

        self.assertEqual(job.status, TranslationJobStatus.FAILED)
        self.assertEqual(job.error_message, "network failed")
        self.assertEqual(service.get_pending(42), pending)
        self.assertIn("Translation job failed", logs.output[0])
        self.assertIn("notes.txt", logs.output[0])
        self.assertIn("job-1", logs.output[0])

    def test_cancel_translation_requests_active_job_cancellation(self):
        repository = InMemoryTranslationJobRepository()
        service = BotTranslationService(
            job_repository=repository,
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.\n\nTwo.",
            source_language="en",
            target_language="uk",
        )
        self._accept_pending_preview(service)

        output = io.StringIO()
        with redirect_stdout(output):
            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=CancellingTranslator(service, 42),
            )

        self.assertEqual(job.status, TranslationJobStatus.CANCELLED)
        self.assertEqual(job.result_file_name, "notes.uk.partial.txt")
        self.assertEqual(job.result_content.decode("utf-8"), "[uk] One.")
        self.assertIsNone(service.get_pending(42))
        self.assertIn("CANCEL REQUESTED", output.getvalue())
        self.assertIn("user=telegram:42", output.getvalue())
        self.assertIn("job=job-1", output.getvalue())
        self.assertIn("completed=0/2", output.getvalue())

    def test_cancel_translation_returns_false_without_active_job(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=5,
        )

        self.assertFalse(service.cancel_translation(42))

    def test_cancel_translation_falls_back_to_active_persistent_job_after_restart(self):
        with TemporaryDirectory() as temp_dir:
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="book.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key="original/book.txt",
            )
            persistent_store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:0",),
                        source_text_hash="hash-1",
                        prompt_tier="default",
                        source_language="en",
                        target_language="uk",
                    )
                ],
            )
            claimed = persistent_store.claim_next_work_unit(
                job.id,
                worker_id="worker-before-restart",
            )
            restarted_service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                persistent_job_store=persistent_store,
            )
            self.addCleanup(restarted_service.close)

            self.assertTrue(restarted_service.cancel_translation(42))

            cancelled = persistent_store.get_job(job.id)
            recovered_unit = persistent_store.get_work_unit(claimed.id)
            self.assertEqual(
                cancelled.status,
                PersistentTranslationJobStatus.CANCELLED,
            )
            self.assertEqual(
                recovered_unit.status,
                PersistentWorkUnitStatus.PENDING,
            )

    def test_cancel_translation_after_restart_assembles_existing_partial(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            run_log_root = Path(temp_dir) / "translation-runs"
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First.\n\nSecond.",
            )
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="book.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version=TXT_ADAPTER_VERSION,
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=source.object_key,
            )
            units = persistent_store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:segment:1",),
                        source_text_hash="hash-1",
                        prompt_tier="default",
                        source_language="en",
                        target_language="uk",
                    ),
                    WorkUnitPlan(
                        sequence=2,
                        source_block_ids=("txt:segment:3",),
                        source_text_hash="hash-2",
                        prompt_tier="default",
                        source_language="en",
                        target_language="uk",
                    ),
                ],
            )
            persistent_store.claim_next_work_unit(
                job.id,
                worker_id="worker-before-restart",
            )
            persistent_store.complete_work_unit(
                units[0].id,
                translated_text="[uk] First.",
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit_tokens=0,
                cache_miss_tokens=10,
            )
            run_logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id=job.id,
                    order_id="order-1",
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                ),
            )
            restarted_service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
            )
            self.addCleanup(restarted_service.close)

            cancel_result = restarted_service.cancel_translation_with_result(42)

            cancelled = persistent_store.get_job(job.id)
            result = restarted_service.get_user_book_translation_job(
                user_telegram_id=42,
                job_id=job.id,
            )
            self.assertTrue(cancel_result.cancelled)
            self.assertIsNotNone(cancel_result.job)
            self.assertEqual(
                cancelled.status,
                PersistentTranslationJobStatus.CANCELLED,
            )
            self.assertIsNotNone(cancelled.partial_object_key)
            self.assertEqual(result.status, TranslationJobStatus.CANCELLED)
            self.assertEqual(result.result_file_name, "book.uk.partial.txt")
            self.assertEqual(
                result.result_content.decode("utf-8"),
                "[uk] First.\n\nSecond.",
            )
            self.assertEqual(
                storage.get_bytes(cancelled.partial_object_key),
                result.result_content,
            )
            self.assertEqual(
                cancel_result.job.result_file_name,
                "book.uk.partial.txt",
            )
            run_snapshot = json.loads((run_logger.run_dir / "run.json").read_text())
            self.assertEqual(run_snapshot["status"], "cancelled")
            self.assertEqual(
                run_snapshot["result_file_name"],
                "book.uk.partial.txt",
            )
            self.assertEqual(run_snapshot["error_message"], "Book cancelled by user.")

    def test_cancel_translation_after_restart_without_fragments_keeps_result_empty(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First.\n\nSecond.",
            )
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="book.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version=TXT_ADAPTER_VERSION,
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=source.object_key,
            )
            units = persistent_store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:segment:1",),
                        source_text_hash="hash-1",
                        prompt_tier="default",
                        source_language="en",
                        target_language="uk",
                    )
                ],
            )
            persistent_store.claim_next_work_unit(
                job.id,
                worker_id="worker-before-restart",
            )
            restarted_service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
            )
            self.addCleanup(restarted_service.close)

            self.assertTrue(restarted_service.cancel_translation(42))

            cancelled = persistent_store.get_job(job.id)
            recovered_unit = persistent_store.get_work_unit(units[0].id)
            result = restarted_service.get_user_book_translation_job(
                user_telegram_id=42,
                job_id=job.id,
            )
            self.assertEqual(
                cancelled.status,
                PersistentTranslationJobStatus.CANCELLED,
            )
            self.assertIsNone(cancelled.partial_object_key)
            self.assertEqual(
                recovered_unit.status,
                PersistentWorkUnitStatus.PENDING,
            )
            self.assertEqual(result.status, TranslationJobStatus.CANCELLED)
            self.assertIsNone(result.result_file_name)
            self.assertIsNone(result.result_content)

    def test_cancels_specific_persistent_book_for_owner(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            run_log_root = Path(temp_dir) / "translation-runs"
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
            )
            self.addCleanup(service.close)
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.txt",
                content_type="text/plain",
                content=b"Original",
            )
            job = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id=source.object_key,
                file_name="book.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=source.object_key,
            )
            persistent_store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:0",),
                        source_text_hash="hash-1",
                        prompt_tier="default",
                        source_language="en",
                        target_language="uk",
                    )
                ],
            )
            persistent_store.claim_next_work_unit(
                job.id,
                worker_id="worker-before-restart",
            )
            run_logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id=job.id,
                    order_id="order-1",
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                ),
            )

            self.assertFalse(
                service.cancel_user_book(user_telegram_id=100, job_id=job.id)
            )
            self.assertTrue(
                service.cancel_user_book(user_telegram_id=42, job_id=job.id)
            )
            detail = service.get_user_book_detail(user_telegram_id=42, job_id=job.id)

            self.assertEqual(detail.status, "cancelled")
            self.assertTrue(detail.can_resume)
            self.assertFalse(detail.can_cancel)
            run_snapshot = json.loads((run_logger.run_dir / "run.json").read_text())
            self.assertEqual(run_snapshot["status"], "cancelled")
            self.assertIsNone(run_snapshot["result_file_name"])
            self.assertEqual(run_snapshot["error_message"], "Book cancelled by user.")

    def test_user_queue_summary_counts_active_books(self):
        with TemporaryDirectory() as temp_dir:
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=5,
                persistent_job_store=persistent_store,
            )
            queued = persistent_store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="queued.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
            )
            ready = persistent_store.create_job(
                order_id="order-2",
                user_id="telegram:42",
                file_id="file-2",
                file_name="ready.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version="txt-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
            )
            persistent_store.mark_job_assembled(ready.id, partial=False)

            summary = service.get_user_queue_summary(user_telegram_id=42)

            self.assertEqual(summary.total_active, 1)
            self.assertEqual(summary.queued, 1)
            self.assertEqual(summary.translating, 0)
            self.assertEqual(summary.items[0].job_id, queued.id)

    def test_discard_pending_translation_clears_unconfirmed_order(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"Some text",
            source_language="en",
            target_language="uk",
        )

        self.assertTrue(service.discard_pending_translation(42))
        self.assertIsNone(service.get_pending(42))
        self.assertFalse(service.discard_pending_translation(42))

    def test_confirm_without_pending_translation_is_rejected(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )

        with self.assertRaises(ValueError):
            service.confirm_pending_translation(
                user_telegram_id=42,
                translator=RecordingTranslator(),
            )

    def test_bot_prototype_rejects_pdf_before_confirmation(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )

        with self.assertRaises(ValueError) as error:
            service.prepare_document(
                user_telegram_id=42,
                file_name="scan.pdf",
                content=b"%PDF-1.4 fake",
                source_language="en",
                target_language="uk",
            )

        self.assertIn("TXT, DOCX, and EPUB", str(error.exception))

    def test_accepts_docx_upload_and_runs_docx_translation(self):
        repository = InMemoryTranslationJobRepository()
        service = BotTranslationService(
            job_repository=repository,
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="contract.docx",
            content=_make_docx(
                """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body>
                </w:document>
                """
            ),
            source_language="en",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        self._select_default_translation_mode(service)
        service.prepare_pending_upload(user_telegram_id=42, target_language="fr")
        self._accept_pending_preview(service)

        job = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=RecordingTranslator(),
        )

        self.assertEqual(job.document_kind, DocumentKind.DOCX)
        self.assertEqual(job.result_file_name, "contract.fr.docx")

    def test_docx_translation_memory_is_used_through_bot_service(self):
        repository = InMemoryTranslationJobRepository()
        service = BotTranslationService(
            job_repository=repository,
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        translator = RecordingTranslator()
        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Repeated sentence.</w:t></w:r></w:p></w:body>
            </w:document>
            """
        )

        service.prepare_document(
            user_telegram_id=42,
            file_name="first.docx",
            content=content,
            source_language="en",
            target_language="uk",
        )
        self._accept_pending_preview(service)
        first_job = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=translator,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="second.docx",
            content=content,
            source_language="en",
            target_language="uk",
        )
        self._accept_pending_preview(service)
        second_job = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=translator,
        )

        self.assertEqual(first_job.status, TranslationJobStatus.READY)
        self.assertEqual(second_job.status, TranslationJobStatus.READY)
        self.assertEqual(len(translator.requests), 1)

    def test_accepts_epub_upload_and_runs_epub_translation(self):
        repository = InMemoryTranslationJobRepository()
        service = BotTranslationService(
            job_repository=repository,
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=20,
        )
        service.store_uploaded_document(
            user_telegram_id=42,
            file_name="book.epub",
            content=_make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body><p>Hello book</p></body>
                    </html>
                    """
                }
            ),
            source_language="en",
        )
        service.confirm_pending_upload_rights(user_telegram_id=42)
        self._select_default_translation_mode(service)
        service.prepare_pending_upload(user_telegram_id=42, target_language="es")
        self._accept_pending_preview(service)

        job = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=RecordingTranslator(),
        )

        self.assertEqual(job.document_kind, DocumentKind.EPUB)
        self.assertEqual(job.result_file_name, "book.es.epub")

    def test_epub_translation_memory_is_used_through_bot_service(self):
        repository = InMemoryTranslationJobRepository()
        service = BotTranslationService(
            job_repository=repository,
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=200,
        )
        translator = RecordingTranslator()
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>Repeated book sentence.</p></body>
                </html>
                """
            }
        )

        service.prepare_document(
            user_telegram_id=42,
            file_name="first.epub",
            content=content,
            source_language="en",
            target_language="uk",
        )
        self._accept_pending_preview(service)
        first_job = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=translator,
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="second.epub",
            content=content,
            source_language="en",
            target_language="uk",
        )
        self._accept_pending_preview(service)
        second_job = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=translator,
        )

        self.assertEqual(first_job.status, TranslationJobStatus.READY)
        self.assertEqual(second_job.status, TranslationJobStatus.READY)
        self.assertEqual(len(translator.requests), 1)

    def test_epub_without_glossary_does_not_build_runtime_hook(self):
        hook_calls: list[tuple[str, str]] = []

        def hook_builder(pending: PendingTranslation, document_kind: DocumentKind):
            hook_calls.append((pending.file_name, document_kind.value))
            return _ready_glossary_hook()

        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=200,
            glossary_runtime_hook_builder=hook_builder,
        )
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>Darcy returns.</p></body>
                </html>
                """
            }
        )
        service.prepare_document(
            user_telegram_id=42,
            file_name="without.epub",
            content=content,
            source_language="en",
            target_language="ru",
            glossary_mode=GLOSSARY_MODE_WITHOUT,
        )
        self._accept_pending_preview(service)
        translator = RecordingTranslator()

        job = service.confirm_pending_translation(
            user_telegram_id=42,
            translator=translator,
        )

        self.assertEqual(job.status, TranslationJobStatus.READY)
        self.assertEqual(hook_calls, [])
        self.assertEqual(len(translator.requests), 1)
        self.assertNotIn("<glossary_context", translator.requests[0][0])

    def test_epub_with_glossary_in_memory_uses_hook_and_bypasses_cache(self):
        service = BotTranslationService(
            job_repository=InMemoryTranslationJobRepository(),
            pricing_rules=_pricing_rules(),
            max_upload_mb=50,
            max_fragment_chars=200,
            glossary_runtime_hook_builder=lambda pending, document_kind: (
                _ready_glossary_hook()
            ),
        )
        translator = RecordingTranslator()
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>Darcy returns.</p></body>
                </html>
                """
            }
        )

        for file_name in ("first.epub", "second.epub"):
            service.prepare_document(
                user_telegram_id=42,
                file_name=file_name,
                content=content,
                source_language="en",
                target_language="ru",
                glossary_mode=GLOSSARY_MODE_WITH,
            )
            self._accept_pending_preview(service)
            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )
            self.assertEqual(job.status, TranslationJobStatus.READY)
            self.assertEqual(
                extract_text_from_epub(job.result_content),
                "[ru] Darcy returns.",
            )

        self.assertEqual(len(translator.requests), 2)
        self.assertTrue(
            all("<glossary_context" in request[0] for request in translator.requests)
        )
        self.assertTrue(
            all(
                "role=\"untrusted_reference_data\"" in request[0]
                for request in translator.requests
            )
        )

    def test_epub_with_glossary_persistent_worker_uses_hook_metadata_only(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            persistent_store = SQLiteTranslationJobStore(
                Path(temp_dir) / "jobs.sqlite3"
            )
            run_log_root = Path(temp_dir) / "translation-runs"
            self.addCleanup(persistent_store.close)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=50,
                max_fragment_chars=200,
                file_storage=storage,
                persistent_job_store=persistent_store,
                translation_run_log_root=run_log_root,
                glossary_runtime_hook_builder=lambda pending, document_kind: (
                    _ready_glossary_hook()
                ),
            )
            content = _make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body><p>Darcy returns.</p></body>
                    </html>
                    """
                }
            )
            service.store_uploaded_document(
                user_telegram_id=42,
                file_name="book.epub",
                content=content,
                source_language="en",
            )
            service.confirm_pending_upload_rights(user_telegram_id=42)
            self._select_default_translation_mode(service)
            service.prepare_pending_upload(
                user_telegram_id=42,
                target_language="ru",
                glossary_mode=GLOSSARY_MODE_WITH,
            )
            self._accept_pending_preview(service)
            translator = RecordingTranslator()

            job = service.confirm_pending_translation(
                user_telegram_id=42,
                translator=translator,
            )

            self.assertEqual(job.status, TranslationJobStatus.READY)
            self.assertEqual(
                extract_text_from_epub(job.result_content),
                "[ru] Darcy returns.",
            )
            self.assertEqual(len(translator.requests), 1)
            self.assertIn("<glossary_context", translator.requests[0][0])
            persisted = persistent_store.get_job(job.id)
            self.assertIsNotNone(persisted)
            policy = json.loads(persisted.translation_policy)
            self.assertEqual(policy["glossary_mode"], GLOSSARY_MODE_WITH)
            run_dir = next(run_log_root.iterdir())
            run_snapshot = json.loads(run_dir.joinpath("run.json").read_text())
            serialized = json.dumps(run_snapshot, ensure_ascii=False, sort_keys=True)
            event_lines = run_dir.joinpath("events.jsonl").read_text()
            self.assertIn("glossary_runtime_adapter", event_lines)
            self.assertIn("bypass_glossary_injected_cache", event_lines)
            self.assertNotIn("Darcy returns.", serialized)
            self.assertNotIn("<translation_batch", serialized)
            self.assertNotIn("Darcy returns.", event_lines)
            self.assertNotIn("<translation_batch", event_lines)


def _pricing_rules() -> PricingRules:
    return PricingRules(
        deepseek_input_usd_per_million_tokens=0.28,
        expected_output_multiplier=1.2,
        service_markup_multiplier=3.0,
        minimum_price_usd=0.10,
    )


def _ready_glossary_hook() -> GlossaryRuntimeAdapterHookConfig:
    return GlossaryRuntimeAdapterHookConfig(
        enabled=True,
        glossary_plan={
            "schema_version": "glossary-runtime-shadow-plan-v1",
            "enabled": True,
            "status": "planned",
            "fallback_reason": "none",
            "source_language": "en",
            "target_language": "ru",
            "policy_signature_context": {
                "context_version": "translation-policy-signature-context-v1",
                "glossary_signature": "glossary-snapshot:v1:test",
                "profile_signature": "book-profile:v1:test",
                "translation_snapshot_signature": (
                    "translation-contract-snapshot:v1:test"
                ),
                "selection_signature": "glossary-shadow-selection:v1:test",
                "selected_rule_ids": ["profile-rule:literary-fiction:names-v1"],
                "prompt_contract_version": "prompt-contract:v1",
            },
            "work_unit_plans": [
                {
                    "work_unit_sequence": sequence,
                    "source_block_ids": ["block:v1:0"],
                    "budget_exceeded": False,
                    "budget_status": "within_budget",
                    "fallback_reason_codes": [],
                    "selected_entry_ids": ["glossary-entry:v1:darcy"],
                    "selection_signature": f"glossary-selection:v1:{sequence}",
                    "fallback_action": "shadow_metadata_only",
                }
                for sequence in (0, 1)
            ],
            "runtime_integration": {
                "normal_translation_prompts_changed": False,
                "live_provider_calls_allowed": False,
                "durable_state_mutation_allowed": False,
                "cache_mutation_allowed": False,
                "fallback_action": "omit_glossary_prompt_context",
            },
        },
        prompt_rehearsal_enabled=True,
        prompt_context_entries=(
            {
                "entry_id": "glossary-entry:v1:darcy",
                "category": "name",
                "layer": "hard",
                "status": "validator_accepted",
                "source_canonical": "Darcy",
                "target_canonical": "Дарси",
                "aliases": ["Mr. Darcy"],
                "target_variants": [],
                "forbidden_variants": ["Дэрси"],
                "confidence": 0.98,
                "strategy": "transcribe",
                "grammatical_gender": "unknown",
                "morphology_notes": [],
                "profile_rule_ids": ["profile-rule:literary-fiction:names-v1"],
            },
        ),
        owner_battle_test_enabled=True,
    )


def _prepared_glossary_package(
    *,
    target_language: str = "ru",
    needs_review: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
        "package_id": f"prepared:bot-test:{target_language}",
        "source_language": "en",
        "target_language": target_language,
        "glossary_mode": GLOSSARY_MODE_WITH,
        "provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
        "provider_model": "deepseek-v4-pro",
        "provider_run_id": "provider-run:fake",
        "candidate_selector_signature": "selector:fake",
        "owner_approved": True,
        "entries": [
            {
                "source_entry_id": "entry:darcy",
                "source_canonical": "Darcy",
                "aliases": ["Mr. Darcy"],
                "evidence_refs": ["evidence:darcy"],
                "target_canonical": "Дарси",
                "target_variants": ["мистер Дарси"],
                "forbidden_variants": ["Дэрси"],
                "strategy": "transcribe",
                "confidence": 0.91,
                "needs_review": needs_review,
                "reason_codes": ["needs_human_review"] if needs_review else [],
            }
        ],
    }


class RecordingDocumentSandbox(DocumentSandbox):
    def __init__(self) -> None:
        self.plan_calls: list[tuple[DocumentFormat, bytes, int, str | None]] = []
        self.extract_calls: list[tuple[DocumentFormat, bytes]] = []
        self.assemble_calls: list[
            tuple[DocumentFormat, bytes, list[SandboxTranslationUnit]]
        ] = []

    def plan_translation(
        self,
        *,
        document_format: DocumentFormat,
        content: bytes,
        max_fragment_chars: int,
        translation_mode: str | None = None,
    ):
        self.plan_calls.append(
            (document_format, content, max_fragment_chars, translation_mode)
        )
        from translator_service.format_adapters import (
            plan_docx_translation,
            plan_epub_translation,
            plan_txt_translation,
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
        raise AssertionError(f"Unsupported format: {document_format}")

    def extract_text(
        self,
        *,
        document_format: DocumentFormat,
        content: bytes,
    ) -> str:
        self.extract_calls.append((document_format, content))
        return "English text."

    def assemble_document(
        self,
        *,
        document_format: DocumentFormat,
        content: bytes,
        translated_units: list[SandboxTranslationUnit],
    ) -> bytes:
        self.assemble_calls.append((document_format, content, translated_units))
        texts = [unit.translated_text for unit in translated_units]
        if document_format is DocumentFormat.DOCX:
            body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in texts)
            return _make_docx(
                f"""
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body>{body}</w:body>
                </w:document>
                """
            )
        if document_format is DocumentFormat.EPUB:
            return _make_epub(
                {
                    "OPS/chapter.xhtml": "".join(
                        [
                            '<html xmlns="http://www.w3.org/1999/xhtml"><body>',
                            *[f"<p>{text}</p>" for text in texts],
                            "</body></html>",
                        ]
                    )
                }
            )
        raise AssertionError(f"Unsupported format: {document_format}")


class FailingAssemblyDocumentSandbox(RecordingDocumentSandbox):
    def assemble_document(
        self,
        *,
        document_format: DocumentFormat,
        content: bytes,
        translated_units: list[SandboxTranslationUnit],
    ) -> bytes:
        raise DocumentSandboxError("assembly sandbox failed")


if __name__ == "__main__":
    unittest.main()


def _make_docx(document_xml: str) -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr("word/document.xml", document_xml)
    return archive.getvalue()


def _make_docx_with_member(member_name: str, content: bytes) -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr("word/document.xml", b"<w:document />")
        docx.writestr(member_name, content)
    return archive.getvalue()


def _make_epub(xhtml_items: dict[str, str]) -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr("META-INF/container.xml", "<container />")
        for file_name, content in xhtml_items.items():
            epub.writestr(file_name, content)
    return archive.getvalue()
