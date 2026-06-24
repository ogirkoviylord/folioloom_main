import json
import threading
import time
import unittest
from base64 import urlsafe_b64encode
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from translator_service.admin.ai_provider_keys import SQLiteAIProviderKeyStore
from translator_service.admin.secrets import SQLiteEncryptedSecretStore
from translator_service.beta_safety import (
    BETA_SAFETY_ALLOWED,
    BETA_SAFETY_GLOBAL_DAILY_CAP,
    BetaSafetyDecision,
    JobCostEstimate,
)
from translator_service.bot.runtime import build_deepseek_translator
from translator_service.bot_translation_service import BotTranslationService
from translator_service.config import Settings
from translator_service.deepseek_client import (
    DeepSeekApiError,
    DeepSeekClient,
    DeepSeekUnsafeModelOutputError,
)
from translator_service.deepseek_key_pool import (
    DeepSeekChannelConfig,
    DeepSeekKeyPoolTranslator,
)
from translator_service.extractors import extract_text_from_epub
from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.format_adapters import TXT_ADAPTER_VERSION
from translator_service.job_runner import InMemoryTranslationJobRepository
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    SQLiteTranslationJobStore,
    WorkUnitPlan,
)
from translator_service.persistent_planner import create_persistent_epub_job_plan
from translator_service.pricing import PricingRules
from translator_service.protected_text import protect_text
from translator_service.scheduler import (
    ProviderCapacityCap,
    ProviderCapacityCapScope,
    ProviderSlotInventoryItem,
    ProviderSlotLease,
    ProviderSlotLeaseStatus,
    SchedulerLimits,
    WorkUnitFailureKind,
)
from translator_service.scheduler_runner import assemble_due_jobs, run_scheduler_once
from translator_service.translation_run_logs import (
    TranslationRunLogger,
    TranslationRunMetadata,
)
from translator_service.worker import (
    ProviderUsage,
    _retry_untranslated_secondary_source_blocks,
)

MASTER_KEY = urlsafe_b64encode(b"5" * 32).decode("ascii")


class SchedulerRunnerTest(unittest.TestCase):
    def test_persistent_epub_surface_retry_uses_final_audit_logic(self):
        class SurfaceResidueTranslator:
            def __init__(self) -> None:
                self.requests: list[tuple[str, str, str]] = []
                self.last_usage = ProviderUsage(
                    prompt_tokens=3,
                    completion_tokens=2,
                    total_tokens=5,
                )

            def translate(
                self,
                *,
                text: str,
                source_language: str,
                target_language: str,
            ) -> str:
                self.requests.append((text, source_language, target_language))
                return "По какому праву?"

        translator = SurfaceResidueTranslator()

        translated, usage = _retry_untranslated_secondary_source_blocks(
            source_blocks=["COLD COMFORT"],
            source_block_ids=("epub:aux:ncx:OPS/toc.ncx:text:36",),
            translated_blocks=["COLD COMFORT"],
            protected_blocks=[protect_text("COLD COMFORT", literary_heading=True)],
            translator=translator,
            source_language="en",
            target_language="ru",
        )

        self.assertEqual(translated, ["По какому праву?"])
        self.assertEqual([request[1] for request in translator.requests], ["auto"])
        self.assertEqual(usage.total_tokens, 5)

    def test_run_once_translates_due_unit_and_assembles_ready_txt_result(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="notes.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="notes.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version=TXT_ADAPTER_VERSION,
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=original.object_key,
            )
            store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:segment:1",),
                        source_text_hash="hash-1",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=source.object_key,
                    )
                ],
            )

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=RunnerTranslator(),
                limits=SchedulerLimits(),
                lease_seconds=300,
            )

            persisted_job = store.get_job(job.id)
            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.READY)
            self.assertIsNotNone(persisted_job.final_object_key)
            self.assertEqual(
                storage.get_bytes(persisted_job.final_object_key).decode("utf-8"),
                "[uk] First paragraph",
            )

    def test_run_once_finishes_running_run_log_when_single_unit_job_assembles(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            run_log_root = root / "translation-runs"
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="notes",
                source_text="SCHEDULED RAW SOURCE SENTINEL",
            )
            logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id=job.id,
                    order_id="order-1",
                    user_id="telegram:42",
                    file_name=job.file_name,
                    document_kind=job.document_kind,
                    source_language=job.source_language,
                    target_language=job.target_language,
                    total_fragment_count=1,
                ),
            )

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=RunnerTranslator(),
                limits=SchedulerLimits(),
                lease_seconds=300,
                translation_run_log_root=run_log_root,
            )

            snapshot = json.loads((logger.run_dir / "run.json").read_text())
            events_jsonl = (logger.run_dir / "events.jsonl").read_text()
            artifact_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (
                    logger.run_dir / "run.json",
                    logger.run_dir / "summary.md",
                    logger.run_dir / "events.jsonl",
                )
            )
            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(summary.assembled_jobs, 1)
            self.assertEqual(snapshot["status"], "ready")
            self.assertIsNotNone(snapshot["finished_at"])
            self.assertEqual(snapshot["result_file_name"], "notes.uk.txt")
            self.assertIn("run_finished", events_jsonl)
            self.assertNotIn("SCHEDULED RAW SOURCE SENTINEL", artifact_text)
            self.assertNotIn("[uk] SCHEDULED RAW SOURCE SENTINEL", artifact_text)

    def test_run_once_requires_upload_safety_policy_when_gate_is_enabled(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="Private source paragraph",
            )
            translator = HintedRunnerTranslator(available_slots=1)

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=translator,
                limits=SchedulerLimits(max_active_units_global=1),
                lease_seconds=300,
                require_upload_safety_policy=True,
            )

            [failed_unit] = store.list_work_units(job.id)
            self.assertEqual(summary.completed_units, 0)
            self.assertEqual(summary.failed_units, 1)
            self.assertEqual(summary.assembled_jobs, 0)
            self.assertEqual(failed_unit.status.value, "failed_terminal")
            self.assertEqual(
                failed_unit.last_error,
                f"Job source object is not accepted by upload safety policy: {job.id}",
            )
            self.assertEqual(translator.calls, [])

    def test_run_once_accepts_upload_safety_policy_marker_when_gate_is_enabled(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="First paragraph",
                upload_safety_id="upload-1",
            )

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=RunnerTranslator(),
                limits=SchedulerLimits(max_active_units_global=1),
                lease_seconds=300,
                require_upload_safety_policy=True,
            )

            persisted_job = store.get_job(job.id)
            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.READY)
            self.assertIsNotNone(persisted_job.final_object_key)

    def test_run_once_does_not_claim_when_beta_guard_blocks(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="First paragraph",
            )
            translator = HintedRunnerTranslator(available_slots=1)
            guard = RecordingBetaSafetyGuard(allowed=False)

            with self.assertLogs(
                "translator_service.scheduler_runner",
                level="WARNING",
            ):
                summary = run_scheduler_once(
                    store=store,
                    storage=storage,
                    worker_id="worker-a",
                    translator=translator,
                    limits=SchedulerLimits(max_active_units_global=1),
                    lease_seconds=300,
                    beta_safety_guard=guard,
                )

            self.assertEqual(summary.completed_units, 0)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(summary.assembled_jobs, 0)
            self.assertEqual(translator.calls, [])
            self.assertEqual(guard.can_start_calls, 1)
            self.assertEqual(guard.usage_calls, [])
            [unit] = store.list_work_units(job.id)
            self.assertEqual(unit.status.value, "pending")
            self.assertIsNotNone(
                store.claim_next_scheduled_work_unit(
                    worker_id="worker-b",
                    lease_seconds=300,
                    limits=SchedulerLimits(max_active_units_global=1),
                )
            )

    def test_run_once_still_assembles_due_jobs_when_beta_guard_blocks(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            due_job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-due",
                file_id="file-due",
                source_text="Ready paragraph",
            )
            due_claim = store.claim_next_scheduled_work_unit(
                worker_id="setup",
                lease_seconds=300,
                limits=SchedulerLimits(max_active_units_global=1),
            )
            store.complete_claimed_work_unit(
                work_unit_id=due_claim.work_unit_id,
                claim_token=due_claim.claim_token,
                translated_text="[uk] Ready paragraph",
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit_tokens=0,
                cache_miss_tokens=10,
            )
            pending_job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-pending",
                file_id="file-pending",
                source_text="Pending paragraph",
            )
            translator = HintedRunnerTranslator(available_slots=1)
            guard = RecordingBetaSafetyGuard(allowed=False)

            with self.assertLogs(
                "translator_service.scheduler_runner",
                level="WARNING",
            ):
                summary = run_scheduler_once(
                    store=store,
                    storage=storage,
                    worker_id="worker-a",
                    translator=translator,
                    limits=SchedulerLimits(max_active_units_global=1),
                    lease_seconds=300,
                    beta_safety_guard=guard,
                )

            persisted_due_job = store.get_job(due_job.id)
            self.assertEqual(summary.completed_units, 0)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(summary.assembled_jobs, 1)
            self.assertEqual(translator.calls, [])
            self.assertEqual(
                persisted_due_job.status,
                PersistentTranslationJobStatus.READY,
            )
            self.assertIsNotNone(persisted_due_job.final_object_key)
            self.assertEqual(
                storage.get_bytes(persisted_due_job.final_object_key).decode("utf-8"),
                "[uk] Ready paragraph",
            )
            self.assertEqual(guard.consumed_jobs, [due_job.id])
            self.assertEqual(guard.released_jobs, [])
            [pending_unit] = store.list_work_units(pending_job.id)
            self.assertEqual(pending_unit.status.value, "pending")
            self.assertIsNotNone(
                store.claim_next_scheduled_work_unit(
                    worker_id="worker-b",
                    lease_seconds=300,
                    limits=SchedulerLimits(max_active_units_global=1),
                )
            )

    def test_run_once_records_usage_after_serial_success(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                user_id="telegram:42",
                source_text="First paragraph",
            )
            guard = RecordingBetaSafetyGuard(allowed=True)

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=RunnerTranslator(),
                limits=SchedulerLimits(max_active_units_global=1),
                lease_seconds=300,
                beta_safety_guard=guard,
                max_parallel_units=1,
            )

            [unit] = store.list_work_units(job.id)
            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(guard.can_start_calls, 1)
            self.assertEqual(
                guard.usage_calls,
                [
                    UsageCall(
                        job_id=job.id,
                        user_id="telegram:42",
                        work_unit_id=unit.id,
                        prompt_tokens=10,
                        completion_tokens=5,
                    )
                ],
            )

    def test_run_once_finishes_running_run_log_when_scheduled_unit_fails_terminally(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            run_log_root = root / "translation-runs"
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                user_id="telegram:42",
                source_text="Private source paragraph",
            )
            with store._connection:
                store._connection.execute(
                    "UPDATE work_units SET max_attempts = 1 WHERE job_id = ?",
                    (job.id,),
                )
            logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id=job.id,
                    order_id="order-1",
                    user_id="telegram:42",
                    file_name=job.file_name,
                    document_kind=job.document_kind,
                    source_language=job.source_language,
                    target_language=job.target_language,
                    total_fragment_count=1,
                ),
            )
            guard = RecordingBetaSafetyGuard(allowed=True)

            with self.assertLogs("translator_service.worker", level="ERROR"):
                summary = run_scheduler_once(
                    store=store,
                    storage=storage,
                    worker_id="worker-a",
                    translator=FailingRunnerTranslator(),
                    limits=SchedulerLimits(max_active_units_global=1),
                    lease_seconds=300,
                    retry_base_delay_seconds=0,
                    retry_max_delay_seconds=0,
                    translation_run_log_root=run_log_root,
                    beta_safety_guard=guard,
                )

            snapshot = json.loads((logger.run_dir / "run.json").read_text())
            events_jsonl = (logger.run_dir / "events.jsonl").read_text()
            [unit] = store.list_work_units(job.id)
            persisted_job = store.get_job(job.id)
            self.assertEqual(summary.failed_units, 1)
            self.assertEqual(unit.status.value, "failed_terminal")
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.INTERRUPTED,
            )
            self.assertEqual(snapshot["status"], "failed")
            self.assertIsNotNone(snapshot["finished_at"])
            self.assertEqual(
                snapshot["error_message"],
                "Translation failed in the background worker.",
            )
            self.assertIn("run_failed", events_jsonl)
            self.assertNotIn("Private source paragraph", events_jsonl)
            self.assertNotIn("Private source paragraph", json.dumps(snapshot))
            self.assertNotIn("DeepSeek", events_jsonl)
            self.assertNotIn("DeepSeek", json.dumps(snapshot))
            self.assertNotIn("/var/private/source.txt", events_jsonl)
            self.assertNotIn("/var/private/source.txt", json.dumps(snapshot))
            self.assertNotIn("provider read timeout", events_jsonl)
            self.assertNotIn("provider read timeout", json.dumps(snapshot))
            self.assertEqual(guard.released_jobs, [(job.id, "terminal_failure")])
            self.assertEqual(guard.consumed_jobs, [])

    def test_run_once_records_book_mode_audit_metadata_for_scheduled_success(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            run_log_root = root / "translation-runs"
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                user_id="telegram:42",
                source_text="SCHEDULED RAW SOURCE SENTINEL",
            )
            translation_policy = json.dumps(
                {
                    "translation_mode": "book_manuscript",
                    "translation_mode_profile": "book-manuscript-v1",
                }
            )
            with store._connection:
                store._connection.execute(
                    "UPDATE translation_jobs SET translation_policy = ? WHERE id = ?",
                    (translation_policy, job.id),
                )
            logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id=job.id,
                    order_id="order-1",
                    user_id="telegram:42",
                    file_name=job.file_name,
                    document_kind=job.document_kind,
                    source_language=job.source_language,
                    target_language=job.target_language,
                    total_fragment_count=1,
                    translation_policy=translation_policy,
                ),
            )

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=BookAuditRunnerTranslator(),
                limits=SchedulerLimits(max_active_units_global=1),
                lease_seconds=300,
                translation_run_log_root=run_log_root,
            )

            snapshot = json.loads((logger.run_dir / "run.json").read_text())
            summary_md = (logger.run_dir / "summary.md").read_text(encoding="utf-8")
            artifact_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (
                    logger.run_dir / "run.json",
                    logger.run_dir / "summary.md",
                    logger.run_dir / "events.jsonl",
                )
            )

        audit = snapshot["book_mode_audit"]
        self.assertEqual(summary.completed_units, 1)
        self.assertTrue(audit["enabled"])
        self.assertEqual(audit["chunks_audited"], 1)
        self.assertEqual(audit["chunks_with_findings"], 1)
        self.assertEqual(
            audit["counts_by_code"],
            {"untranslated_source_residue": 1},
        )
        self.assertIn("## Book Mode Audit", summary_md)
        self.assertNotIn("SCHEDULED RAW SOURCE SENTINEL", artifact_text)
        self.assertNotIn("scheduled translated sentinel", artifact_text)
        self.assertNotIn("source_text", artifact_text)
        self.assertNotIn("translated_text", artifact_text)

    def test_run_once_keeps_run_log_running_when_scheduled_unit_retries(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            run_log_root = root / "translation-runs"
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                user_id="telegram:42",
                source_text="Private source paragraph",
            )
            logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id=job.id,
                    order_id="order-1",
                    user_id="telegram:42",
                    file_name=job.file_name,
                    document_kind=job.document_kind,
                    source_language=job.source_language,
                    target_language=job.target_language,
                    total_fragment_count=1,
                ),
            )
            guard = RecordingBetaSafetyGuard(allowed=True)

            with self.assertLogs("translator_service.worker", level="ERROR"):
                summary = run_scheduler_once(
                    store=store,
                    storage=storage,
                    worker_id="worker-a",
                    translator=FailingRunnerTranslator(),
                    limits=SchedulerLimits(max_active_units_global=1),
                    lease_seconds=300,
                    retry_base_delay_seconds=60,
                    retry_max_delay_seconds=60,
                    translation_run_log_root=run_log_root,
                    beta_safety_guard=guard,
                )

            [unit] = store.list_work_units(job.id)
            persisted_job = store.get_job(job.id)
            snapshot = json.loads((logger.run_dir / "run.json").read_text())
            events_jsonl = (logger.run_dir / "events.jsonl").read_text()
            self.assertEqual(summary.failed_units, 1)
            self.assertEqual(unit.status.value, "failed_retryable")
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.TRANSLATING,
            )
            self.assertEqual(snapshot["status"], "running")
            self.assertIsNone(snapshot["finished_at"])
            self.assertNotIn("run_failed", events_jsonl)
            self.assertEqual(guard.usage_calls, [])
            self.assertEqual(guard.released_jobs, [])
            self.assertEqual(guard.consumed_jobs, [])

    def test_run_once_records_real_pool_repair_fallback_usage_after_failover(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_two_block_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                user_id="telegram:42",
                source_text="First paragraph\n\nSecond paragraph",
            )
            guard = RecordingBetaSafetyGuard(allowed=True)
            factory = InstrumentedRepairFallbackClientFactory(
                final_xml=_successful_repair_fallback_xml()
            )
            translator = SchedulerDeepSeekPoolTranslator(factory=factory)

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=translator,
                limits=SchedulerLimits(max_active_units_global=1),
                lease_seconds=300,
                retry_base_delay_seconds=60,
                retry_max_delay_seconds=60,
                beta_safety_guard=guard,
            )

            [unit] = store.list_work_units(job.id)
            key_pool_channel_attempts = sum(
                snapshot.total_started_requests
                for snapshot in translator.pool.snapshot()
            )
            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(summary.assembled_jobs, 1)
            self.assertEqual(len(translator.worker_calls), 1)
            self.assertEqual(key_pool_channel_attempts, 2)
            self.assertEqual(factory.application_calls("key-a"), 1)
            self.assertEqual(factory.transport_attempts("key-a"), 3)
            self.assertEqual(factory.successful_application_calls("key-a"), 0)
            self.assertEqual(factory.application_calls("key-b"), 3)
            self.assertEqual(factory.transport_attempts("key-b"), 9)
            self.assertEqual(factory.successful_application_calls("key-b"), 3)
            self.assertEqual(unit.prompt_tokens, 41)
            self.assertEqual(unit.completion_tokens, 14)
            self.assertEqual(guard.can_start_calls, 1)
            self.assertEqual(
                guard.usage_calls,
                [
                    UsageCall(
                        job_id=job.id,
                        user_id="telegram:42",
                        work_unit_id=unit.id,
                        prompt_tokens=41,
                        completion_tokens=14,
                    )
                ],
            )
            self.assertEqual(guard.consumed_jobs, [job.id])
            self.assertEqual(guard.released_jobs, [])

    def test_run_once_does_not_record_beta_usage_for_failed_real_repair_chain(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_two_block_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                user_id="telegram:42",
                source_text="First paragraph\n\nSecond paragraph",
            )
            guard = RecordingBetaSafetyGuard(allowed=True)
            factory = InstrumentedRepairFallbackClientFactory(
                final_xml=_malformed_repair_fallback_xml()
            )
            translator = SchedulerDeepSeekPoolTranslator(factory=factory)

            with self.assertLogs("translator_service.worker", level="ERROR"):
                summary = run_scheduler_once(
                    store=store,
                    storage=storage,
                    worker_id="worker-a",
                    translator=translator,
                    limits=SchedulerLimits(max_active_units_global=1),
                    lease_seconds=300,
                    retry_base_delay_seconds=60,
                    retry_max_delay_seconds=60,
                    beta_safety_guard=guard,
                )

            [unit] = store.list_work_units(job.id)
            failed_client_usage = factory.clients_by_key["key-b"].last_usage
            if failed_client_usage is None:
                self.fail("failed repair chain must expose accumulated fake usage")
            self.assertEqual(summary.completed_units, 0)
            self.assertEqual(summary.failed_units, 1)
            self.assertEqual(unit.status.value, "failed_retryable")
            self.assertEqual(len(translator.worker_calls), 1)
            self.assertEqual(factory.application_calls("key-a"), 1)
            self.assertEqual(factory.transport_attempts("key-a"), 3)
            self.assertEqual(factory.application_calls("key-b"), 3)
            self.assertEqual(factory.transport_attempts("key-b"), 9)
            self.assertEqual(failed_client_usage.prompt_tokens, 41)
            self.assertEqual(failed_client_usage.completion_tokens, 14)
            self.assertEqual(failed_client_usage.total_tokens, 55)
            # Current owner policy for failed/retry-path provider spend is TBD:
            # even with real accumulated fake repair-chain usage above, retryable
            # failure does not persist work-unit usage and does not call the beta
            # safety guard's record_work_unit_usage hook.
            self.assertEqual(unit.prompt_tokens, 0)
            self.assertEqual(unit.completion_tokens, 0)
            self.assertEqual(guard.can_start_calls, 1)
            self.assertEqual(guard.usage_calls, [])
            self.assertEqual(guard.consumed_jobs, [])
            self.assertEqual(guard.released_jobs, [])

    def test_beta_safety_guard_preserves_capacity_one_serial_success_path(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                user_id="telegram:42",
                source_text="First paragraph",
            )
            guard = RecordingBetaSafetyGuard(allowed=True)

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=RunnerTranslator(),
                limits=SchedulerLimits(max_active_units_global=1),
                lease_seconds=300,
                beta_safety_guard=guard,
                max_parallel_units=1,
            )

            [unit] = store.list_work_units(job.id)
            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(summary.assembled_jobs, 1)
            self.assertEqual(guard.can_start_calls, 1)
            self.assertEqual(
                guard.usage_calls,
                [
                    UsageCall(
                        job_id=job.id,
                        user_id="telegram:42",
                        work_unit_id=unit.id,
                        prompt_tokens=10,
                        completion_tokens=5,
                    )
                ],
            )
            self.assertEqual(guard.consumed_jobs, [job.id])
            self.assertEqual(guard.released_jobs, [])

    def test_run_once_records_usage_after_parallel_success(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                user_id="telegram:42",
                source_text="First paragraph",
            )
            guard = RecordingBetaSafetyGuard(allowed=True)

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=RunnerTranslator(),
                limits=SchedulerLimits(max_active_units_global=1),
                lease_seconds=300,
                beta_safety_guard=guard,
                max_parallel_units=2,
            )

            [unit] = store.list_work_units(job.id)
            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(guard.can_start_calls, 1)
            self.assertEqual(
                guard.usage_calls,
                [
                    UsageCall(
                        job_id=job.id,
                        user_id="telegram:42",
                        work_unit_id=unit.id,
                        prompt_tokens=10,
                        completion_tokens=5,
                    )
                ],
            )

    def test_assemble_due_jobs_marks_ready_reservation_consumed(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="First paragraph",
            )
            claim = store.claim_next_scheduled_work_unit(
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
            )
            store.complete_claimed_work_unit(
                work_unit_id=claim.work_unit_id,
                claim_token=claim.claim_token,
                translated_text="[uk] First paragraph",
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit_tokens=0,
                cache_miss_tokens=10,
            )
            guard = RecordingBetaSafetyGuard(allowed=True)

            assembled = assemble_due_jobs(
                store=store,
                storage=storage,
                beta_safety_guard=guard,
            )

            self.assertEqual(assembled, 1)
            self.assertEqual(guard.consumed_jobs, [job.id])
            self.assertEqual(guard.released_jobs, [])

    def test_assemble_due_jobs_releases_partial_reservation(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="First paragraph",
            )
            claim = store.claim_next_scheduled_work_unit(
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
            )
            store.complete_claimed_work_unit(
                work_unit_id=claim.work_unit_id,
                claim_token=claim.claim_token,
                translated_text="[uk] First paragraph",
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit_tokens=0,
                cache_miss_tokens=10,
            )
            partial = storage.put_bytes(
                kind=StoredFileKind.PARTIAL,
                file_name="notes.uk.partial.txt",
                content_type="text/plain; charset=utf-8",
                content=b"[uk] First paragraph",
            )
            store.attach_job_output(job.id, partial_object_key=partial.object_key)
            guard = RecordingBetaSafetyGuard(allowed=True)

            assembled = assemble_due_jobs(
                store=store,
                storage=storage,
                beta_safety_guard=guard,
            )

            persisted_job = store.get_job(job.id)
            self.assertEqual(assembled, 1)
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.PARTIAL,
            )
            self.assertEqual(guard.consumed_jobs, [])
            self.assertEqual(guard.released_jobs, [(job.id, "partial_assembly")])

    def test_assemble_due_jobs_builds_partial_after_terminal_work_unit_failure(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="notes.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First.\n\nSecond.",
            )
            first = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First.",
            )
            second = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-2.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Second.",
            )
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="notes.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version=TXT_ADAPTER_VERSION,
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=original.object_key,
            )
            store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:segment:1",),
                        source_text_hash="hash-1",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=first.object_key,
                    ),
                    WorkUnitPlan(
                        sequence=2,
                        source_block_ids=("txt:segment:3",),
                        source_text_hash="hash-2",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=second.object_key,
                    ),
                ],
            )
            with store._connection:
                store._connection.execute(
                    "UPDATE work_units SET max_attempts = 1 WHERE job_id = ?",
                    (job.id,),
                )
            first_claim = store.claim_next_scheduled_work_unit(
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
            )
            store.complete_claimed_work_unit(
                work_unit_id=first_claim.work_unit_id,
                claim_token=first_claim.claim_token,
                translated_text="[uk] First.",
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit_tokens=0,
                cache_miss_tokens=10,
            )
            failed_claim = store.claim_next_scheduled_work_unit(
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
            )
            store.fail_claimed_work_unit(
                work_unit_id=failed_claim.work_unit_id,
                claim_token=failed_claim.claim_token,
                failure_kind=WorkUnitFailureKind.MALFORMED_PROVIDER_OUTPUT,
                error_message="provider failure: malformed_response",
                retry_base_delay_seconds=0,
                retry_max_delay_seconds=0,
            )
            guard = RecordingBetaSafetyGuard(allowed=True)

            assembled = assemble_due_jobs(
                store=store,
                storage=storage,
                beta_safety_guard=guard,
            )

            persisted_job = store.get_job(job.id)
            self.assertEqual(assembled, 1)
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.PARTIAL,
            )
            self.assertIsNone(persisted_job.final_object_key)
            self.assertIsNotNone(persisted_job.partial_object_key)
            self.assertEqual(
                storage.get_metadata(persisted_job.partial_object_key).file_name,
                "notes.uk.partial.txt",
            )
            self.assertEqual(
                storage.get_bytes(persisted_job.partial_object_key).decode("utf-8"),
                "[uk] First.\n\nSecond.",
            )
            self.assertEqual(guard.consumed_jobs, [])
            self.assertEqual(guard.released_jobs, [(job.id, "partial_assembly")])

            resumed = store.resume_job(job.id)
            retry_claim = store.claim_next_scheduled_work_unit(
                worker_id="worker-b",
                lease_seconds=300,
                limits=SchedulerLimits(),
            )
            store.complete_claimed_work_unit(
                work_unit_id=retry_claim.work_unit_id,
                claim_token=retry_claim.claim_token,
                translated_text="[uk] Second.",
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit_tokens=0,
                cache_miss_tokens=10,
            )
            final_assembled = assemble_due_jobs(store=store, storage=storage)

            persisted_job = store.get_job(job.id)
            self.assertEqual(resumed.status, PersistentTranslationJobStatus.QUEUED)
            self.assertEqual(retry_claim.work_unit_id, failed_claim.work_unit_id)
            self.assertEqual(final_assembled, 1)
            self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.READY)
            self.assertIsNotNone(persisted_job.final_object_key)
            self.assertEqual(
                storage.get_metadata(persisted_job.final_object_key).file_name,
                "notes.uk.txt",
            )
            self.assertEqual(
                storage.get_bytes(persisted_job.final_object_key).decode("utf-8"),
                "[uk] First.\n\n[uk] Second.",
            )

    def test_run_once_builds_epub_partial_after_terminal_failure_and_updates_run_log(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            run_log_root = root / "translation-runs"
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            plan = _create_epub_job_plan(store=store, storage=storage)
            with store._connection:
                store._connection.execute(
                    "UPDATE work_units SET max_attempts = 1 WHERE job_id = ?",
                    (plan.job.id,),
                )
            first_claim = store.claim_next_scheduled_work_unit(
                worker_id="worker-seed",
                lease_seconds=300,
                limits=SchedulerLimits(),
            )
            store.complete_claimed_work_unit(
                work_unit_id=first_claim.work_unit_id,
                claim_token=first_claim.claim_token,
                translated_text="Перший справжній абзац.",
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit_tokens=0,
                cache_miss_tokens=10,
            )
            logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id=plan.job.id,
                    order_id=plan.job.order_id,
                    user_id=plan.job.user_id,
                    file_name=plan.job.file_name,
                    document_kind=plan.job.document_kind,
                    source_language=plan.job.source_language,
                    target_language=plan.job.target_language,
                    total_fragment_count=len(plan.work_units),
                ),
            )
            guard = RecordingBetaSafetyGuard(allowed=True)

            with self.assertLogs("translator_service.worker", level="ERROR"):
                summary = run_scheduler_once(
                    store=store,
                    storage=storage,
                    worker_id="worker-a",
                    translator=FailingRunnerTranslator(),
                    limits=SchedulerLimits(max_active_units_global=1),
                    lease_seconds=300,
                    retry_base_delay_seconds=0,
                    retry_max_delay_seconds=0,
                    translation_run_log_root=run_log_root,
                    beta_safety_guard=guard,
                )

            persisted_job = store.get_job(plan.job.id)
            failed_units = [
                unit
                for unit in store.list_work_units(plan.job.id)
                if unit.status.value == "failed_terminal"
            ]
            partial_key = persisted_job.partial_object_key
            snapshot = json.loads((logger.run_dir / "run.json").read_text())
            events_jsonl = (logger.run_dir / "events.jsonl").read_text()
            partial_text = extract_text_from_epub(storage.get_bytes(partial_key))

            self.assertEqual(summary.failed_units, 1)
            self.assertEqual(summary.assembled_jobs, 1)
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.PARTIAL,
            )
            self.assertIsNone(persisted_job.final_object_key)
            self.assertIsNotNone(partial_key)
            self.assertEqual(
                storage.get_metadata(partial_key).file_name,
                "book.uk.partial.epub",
            )
            self.assertIn("Перший справжній абзац.", partial_text)
            self.assertIn("Second real paragraph.", partial_text)
            self.assertEqual(len(failed_units), 1)
            self.assertEqual(snapshot["status"], "partial")
            self.assertEqual(snapshot["result_file_name"], "book.uk.partial.epub")
            self.assertEqual(
                snapshot["error_message"],
                "Translation failed in the background worker.",
            )
            self.assertIn("run_failed", events_jsonl)
            self.assertIn("run_finished", events_jsonl)
            self.assertEqual(
                guard.released_jobs,
                [
                    (plan.job.id, "terminal_failure"),
                    (plan.job.id, "partial_assembly"),
                ],
            )
            self.assertEqual(guard.consumed_jobs, [])

    def test_assemble_due_jobs_blocks_final_book_mode_epub_navigation_residue(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            run_log_root = root / "translation-runs"
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            plan = _create_epub_surface_audit_job_plan(
                store=store,
                storage=storage,
                target_language="ru",
            )
            logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id=plan.job.id,
                    order_id=plan.job.order_id,
                    user_id=plan.job.user_id,
                    file_name=plan.job.file_name,
                    document_kind=plan.job.document_kind,
                    source_language=plan.job.source_language,
                    target_language=plan.job.target_language,
                    total_fragment_count=len(plan.work_units),
                    translation_policy=plan.job.translation_policy,
                ),
            )
            guard = RecordingBetaSafetyGuard(allowed=True)

            _complete_scheduled_units_by_block_id(
                store,
                plan.job.id,
                {
                    "epub:OPS/chapter.xhtml:0": "Chapter 1",
                    "epub:OPS/chapter.xhtml:1": "Переведенный абзац.",
                    "epub:aux:opf:OPS/content.opf:title:0": "Original Book Title",
                    "epub:aux:ncx:OPS/toc.ncx:text:0": "Original Book Title",
                    "epub:aux:ncx:OPS/toc.ncx:text:1": "Chapter 1",
                    "epub:aux:xhtml-title:OPS/chapter.xhtml:title:0": (
                        "Original Book Title"
                    ),
                    "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0": "Book I",
                },
            )

            assembled = assemble_due_jobs(
                store=store,
                storage=storage,
                beta_safety_guard=guard,
                translation_run_log_root=run_log_root,
            )

            persisted_job = store.get_job(plan.job.id)
            service = BotTranslationService(
                job_repository=InMemoryTranslationJobRepository(),
                pricing_rules=_pricing_rules(),
                max_upload_mb=20,
                max_fragment_chars=120,
                file_storage=storage,
                persistent_job_store=store,
            )
            snapshot = json.loads((logger.run_dir / "run.json").read_text())
            events_jsonl = (logger.run_dir / "events.jsonl").read_text()
            artifact_text = "\n".join(
                [
                    (logger.run_dir / "run.json").read_text(encoding="utf-8"),
                    events_jsonl,
                    (logger.run_dir / "summary.md").read_text(encoding="utf-8"),
                ]
            )
            gate = snapshot["book_mode_audit"]["final_surface_gate"]

            self.assertEqual(assembled, 1)
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.FAILED,
            )
            self.assertIsNone(persisted_job.final_object_key)
            self.assertIsNone(persisted_job.partial_object_key)
            self.assertIsNone(
                service.get_user_book_result(
                    user_telegram_id=42,
                    job_id=plan.job.id,
                )
            )
            self.assertEqual(snapshot["status"], "failed")
            self.assertEqual(
                snapshot["error_message"],
                "Final EPUB surface audit failed safely.",
            )
            self.assertEqual(gate["reason"], "english_navigation_heading_residue")
            self.assertEqual(gate["phase"], "final_epub_surface_audit")
            self.assertGreaterEqual(gate["blocking_findings"], 2)
            self.assertIn("xhtml_navigation", gate["surface_categories"])
            self.assertIn("toc_ncx", gate["surface_categories"])
            self.assertIn("xhtml_body_heading", gate["surface_categories"])
            self.assertIn("book_mode_audit_gate_failed", events_jsonl)
            self.assertIn("run_failed", events_jsonl)
            self.assertEqual(
                guard.released_jobs,
                [(plan.job.id, "final_epub_surface_audit_failed")],
            )
            self.assertEqual(guard.consumed_jobs, [])
            self.assertNotIn("Original Book Title", artifact_text)
            self.assertNotIn("Chapter 1", artifact_text)
            self.assertNotIn("Book I", artifact_text)

    def test_assemble_due_jobs_blocks_final_epub_protected_marker_residue(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            run_log_root = root / "translation-runs"
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            plan = _create_epub_surface_audit_job_plan(
                store=store,
                storage=storage,
                target_language="ru",
            )
            logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id=plan.job.id,
                    order_id=plan.job.order_id,
                    user_id=plan.job.user_id,
                    file_name=plan.job.file_name,
                    document_kind=plan.job.document_kind,
                    source_language=plan.job.source_language,
                    target_language=plan.job.target_language,
                    total_fragment_count=len(plan.work_units),
                    translation_policy=plan.job.translation_policy,
                ),
            )
            guard = RecordingBetaSafetyGuard(allowed=True)

            _complete_scheduled_units_by_block_id(
                store,
                plan.job.id,
                {
                    "epub:OPS/chapter.xhtml:0": "Глава ZXQPROTECTED0",
                    "epub:OPS/chapter.xhtml:1": "Переведенный абзац.",
                    "epub:aux:opf:OPS/content.opf:title:0": "Название книги",
                    "epub:aux:ncx:OPS/toc.ncx:text:0": "Название книги",
                    "epub:aux:ncx:OPS/toc.ncx:text:1": "ZXQ-PROTECTED-0-QXZ",
                    "epub:aux:xhtml-title:OPS/chapter.xhtml:title:0": (
                        "ZXQPROTECTED0QXZ"
                    ),
                    "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0": "Книга I",
                },
            )

            assembled = assemble_due_jobs(
                store=store,
                storage=storage,
                beta_safety_guard=guard,
                translation_run_log_root=run_log_root,
            )

            persisted_job = store.get_job(plan.job.id)
            if persisted_job is None:
                self.fail("expected persisted job")
            snapshot = json.loads((logger.run_dir / "run.json").read_text())
            events_jsonl = (logger.run_dir / "events.jsonl").read_text()
            artifact_text = "\n".join(
                [
                    (logger.run_dir / "run.json").read_text(encoding="utf-8"),
                    events_jsonl,
                    (logger.run_dir / "summary.md").read_text(encoding="utf-8"),
                ]
            )
            gate = snapshot["book_mode_audit"]["final_surface_gate"]

            self.assertEqual(assembled, 1)
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.FAILED,
            )
            self.assertIsNone(persisted_job.final_object_key)
            self.assertIsNone(persisted_job.partial_object_key)
            self.assertEqual(snapshot["status"], "failed")
            self.assertEqual(
                snapshot["error_message"],
                "Final EPUB surface audit failed safely.",
            )
            self.assertEqual(gate["reason"], "protected_marker_residue")
            self.assertEqual(gate["phase"], "final_epub_surface_audit")
            self.assertGreaterEqual(gate["blocking_findings"], 3)
            self.assertEqual(gate["counts_by_code"]["protected_marker_residue"], 3)
            self.assertEqual(gate["counts_by_category"]["protected_text"], 3)
            self.assertIn("xhtml_title", gate["surface_categories"])
            self.assertIn("toc_ncx", gate["surface_categories"])
            self.assertIn("xhtml_body_heading", gate["surface_categories"])
            self.assertIn("book_mode_audit_gate_failed", events_jsonl)
            self.assertIn("run_failed", events_jsonl)
            self.assertEqual(
                guard.released_jobs,
                [(plan.job.id, "final_epub_surface_audit_failed")],
            )
            self.assertEqual(guard.consumed_jobs, [])
            self.assertNotIn("ZXQPROTECTED0QXZ", artifact_text)
            self.assertNotIn("ZXQ-PROTECTED-0-QXZ", artifact_text)
            self.assertNotIn("ZXQPROTECTED0", artifact_text)
            self.assertNotIn("Переведенный абзац", artifact_text)

    def test_assemble_due_jobs_does_not_block_final_epub_on_navigation_url_noise(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            plan = _create_epub_surface_audit_job_plan(
                store=store,
                storage=storage,
                target_language="ru",
                content=_make_epub_with_surface_audit_frontmatter_noise(),
            )

            _complete_scheduled_units_by_block_id(
                store,
                plan.job.id,
                {
                    "epub:OPS/chapter.xhtml:0": "Глава 1",
                    "epub:OPS/chapter.xhtml:1": "Переведенный абзац.",
                    "epub:aux:opf:OPS/content.opf:title:0": "Название книги",
                    "epub:aux:ncx:OPS/toc.ncx:text:0": "Название книги",
                    "epub:aux:ncx:OPS/toc.ncx:text:1": "Глава 1",
                    "epub:aux:xhtml-title:OPS/chapter.xhtml:title:0": (
                        "Название книги"
                    ),
                    "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0": (
                        "example.org"
                    ),
                    "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:1": (
                        "example.org/ebooks/12345"
                    ),
                    "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:2": "Глава 1",
                },
            )

            assembled = assemble_due_jobs(store=store, storage=storage)

            persisted_job = store.get_job(plan.job.id)
            self.assertEqual(assembled, 1)
            self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.READY)
            self.assertIsNotNone(persisted_job.final_object_key)

    def test_assemble_due_jobs_allows_intentional_latin_title_policy(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            plan = _create_epub_surface_audit_job_plan(
                store=store,
                storage=storage,
                target_language="ru",
            )

            _complete_scheduled_units_by_block_id(
                store,
                plan.job.id,
                {
                    "epub:OPS/chapter.xhtml:0": "QUO WARRANTO?",
                    "epub:OPS/chapter.xhtml:1": "Переведенный абзац.",
                    "epub:aux:opf:OPS/content.opf:title:0": "QUO WARRANTO?",
                    "epub:aux:ncx:OPS/toc.ncx:text:0": "QUO WARRANTO?",
                    "epub:aux:ncx:OPS/toc.ncx:text:1": "QUO WARRANTO?",
                    "epub:aux:xhtml-title:OPS/chapter.xhtml:title:0": (
                        "QUO WARRANTO?"
                    ),
                    "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0": (
                        "QUO WARRANTO?"
                    ),
                },
            )

            assembled = assemble_due_jobs(store=store, storage=storage)

            persisted_job = store.get_job(plan.job.id)
            self.assertIsNotNone(persisted_job)
            self.assertEqual(assembled, 1)
            self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.READY)
            self.assertIsNotNone(persisted_job.final_object_key)

    def test_assemble_due_jobs_blocks_final_epub_gutenberg_legal_residue(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            run_log_root = root / "translation-runs"
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            plan = _create_epub_surface_audit_job_plan(
                store=store,
                storage=storage,
                target_language="ru",
            )
            logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id=plan.job.id,
                    order_id=plan.job.order_id,
                    user_id=plan.job.user_id,
                    file_name=plan.job.file_name,
                    document_kind=plan.job.document_kind,
                    source_language=plan.job.source_language,
                    target_language=plan.job.target_language,
                    total_fragment_count=len(plan.work_units),
                    translation_policy=plan.job.translation_policy,
                ),
            )

            _complete_scheduled_units_by_block_id(
                store,
                plan.job.id,
                {
                    "epub:OPS/chapter.xhtml:0": "Глава 1",
                    "epub:OPS/chapter.xhtml:1": (
                        "Project Gutenberg: этот раздел лицензии сообщает, что "
                        "you may copy and distribute this ebook under the terms "
                        "of the license agreement."
                    ),
                    "epub:aux:opf:OPS/content.opf:title:0": "Название книги",
                    "epub:aux:ncx:OPS/toc.ncx:text:0": "Название книги",
                    "epub:aux:ncx:OPS/toc.ncx:text:1": "Глава 1",
                    "epub:aux:xhtml-title:OPS/chapter.xhtml:title:0": (
                        "Название книги"
                    ),
                    "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0": "Книга I",
                },
            )

            assembled = assemble_due_jobs(
                store=store,
                storage=storage,
                translation_run_log_root=run_log_root,
            )

            persisted_job = store.get_job(plan.job.id)
            snapshot = json.loads((logger.run_dir / "run.json").read_text())
            artifact_text = "\n".join(
                [
                    (logger.run_dir / "run.json").read_text(encoding="utf-8"),
                    (logger.run_dir / "events.jsonl").read_text(encoding="utf-8"),
                    (logger.run_dir / "summary.md").read_text(encoding="utf-8"),
                ]
            )
            gate = snapshot["book_mode_audit"]["final_surface_gate"]

            self.assertEqual(assembled, 1)
            if persisted_job is None:
                self.fail("expected persisted job")
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.FAILED,
            )
            self.assertEqual(gate["reason"], "gutenberg_legal_backmatter_residue")
            self.assertEqual(gate["blocking_findings"], 1)
            self.assertIn("legal_backmatter", gate["surface_categories"])
            self.assertNotIn("copy and distribute", artifact_text)

    def test_assemble_due_jobs_blocks_final_epub_mixed_nav_residue(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            run_log_root = root / "translation-runs"
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            plan = _create_epub_surface_audit_job_plan(
                store=store,
                storage=storage,
                target_language="ru",
            )
            logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id=plan.job.id,
                    order_id=plan.job.order_id,
                    user_id=plan.job.user_id,
                    file_name=plan.job.file_name,
                    document_kind=plan.job.document_kind,
                    source_language=plan.job.source_language,
                    target_language=plan.job.target_language,
                    total_fragment_count=len(plan.work_units),
                    translation_policy=plan.job.translation_policy,
                ),
            )

            _complete_scheduled_units_by_block_id(
                store,
                plan.job.id,
                {
                    "epub:OPS/chapter.xhtml:0": "Глава: Modern Pilgrims",
                    "epub:OPS/chapter.xhtml:1": "Переведенный абзац.",
                    "epub:aux:opf:OPS/content.opf:title:0": "Название книги",
                    "epub:aux:ncx:OPS/toc.ncx:text:0": "Название книги",
                    "epub:aux:ncx:OPS/toc.ncx:text:1": "Раздел SIGNS AND WONDERS",
                    "epub:aux:xhtml-title:OPS/chapter.xhtml:title:0": (
                        "Название книги"
                    ),
                    "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0": (
                        "Глава Modern Pilgrims"
                    ),
                },
            )

            assembled = assemble_due_jobs(
                store=store,
                storage=storage,
                translation_run_log_root=run_log_root,
            )

            persisted_job = store.get_job(plan.job.id)
            self.assertIsNotNone(persisted_job)
            snapshot = json.loads((logger.run_dir / "run.json").read_text())
            artifact_text = "\n".join(
                [
                    (logger.run_dir / "run.json").read_text(encoding="utf-8"),
                    (logger.run_dir / "events.jsonl").read_text(encoding="utf-8"),
                    (logger.run_dir / "summary.md").read_text(encoding="utf-8"),
                ]
            )
            gate = snapshot["book_mode_audit"]["final_surface_gate"]

            self.assertEqual(assembled, 1)
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.FAILED,
            )
            self.assertEqual(gate["reason"], "english_navigation_heading_residue")
            self.assertGreaterEqual(gate["blocking_findings"], 2)
            self.assertIn("xhtml_navigation", gate["surface_categories"])
            self.assertIn("toc_ncx", gate["surface_categories"])
            self.assertIn("xhtml_body_heading", gate["surface_categories"])
            self.assertNotIn("Modern Pilgrims", artifact_text)
            self.assertNotIn("SIGNS AND WONDERS", artifact_text)

    def test_assemble_due_jobs_prioritizes_nav_with_combined_legal_residue(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            run_log_root = root / "translation-runs"
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            plan = _create_epub_surface_audit_job_plan(
                store=store,
                storage=storage,
                target_language="ru",
            )
            logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id=plan.job.id,
                    order_id=plan.job.order_id,
                    user_id=plan.job.user_id,
                    file_name=plan.job.file_name,
                    document_kind=plan.job.document_kind,
                    source_language=plan.job.source_language,
                    target_language=plan.job.target_language,
                    total_fragment_count=len(plan.work_units),
                    translation_policy=plan.job.translation_policy,
                ),
            )

            _complete_scheduled_units_by_block_id(
                store,
                plan.job.id,
                {
                    "epub:OPS/chapter.xhtml:0": "Глава: Modern Pilgrims",
                    "epub:OPS/chapter.xhtml:1": (
                        "Project Gutenberg: этот раздел лицензии сообщает, что "
                        "you may copy and distribute this ebook under the terms "
                        "of the license agreement."
                    ),
                    "epub:aux:opf:OPS/content.opf:title:0": "Название книги",
                    "epub:aux:ncx:OPS/toc.ncx:text:0": "Название книги",
                    "epub:aux:ncx:OPS/toc.ncx:text:1": "Раздел SIGNS AND WONDERS",
                    "epub:aux:xhtml-title:OPS/chapter.xhtml:title:0": (
                        "Название книги"
                    ),
                    "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0": (
                        "Глава Modern Pilgrims"
                    ),
                },
            )

            assembled = assemble_due_jobs(
                store=store,
                storage=storage,
                translation_run_log_root=run_log_root,
            )

            persisted_job = store.get_job(plan.job.id)
            self.assertIsNotNone(persisted_job)
            snapshot = json.loads((logger.run_dir / "run.json").read_text())
            gate = snapshot["book_mode_audit"]["final_surface_gate"]

            self.assertEqual(assembled, 1)
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.FAILED,
            )
            self.assertEqual(gate["reason"], "english_navigation_heading_residue")
            self.assertGreaterEqual(gate["blocking_findings"], 3)
            self.assertEqual(
                gate["counts_by_code"]["gutenberg_legal_backmatter_residue"],
                1,
            )
            self.assertGreaterEqual(
                gate["counts_by_code"]["english_navigation_heading_residue"],
                2,
            )
            self.assertIn("legal_backmatter", gate["surface_categories"])
            self.assertIn("xhtml_navigation", gate["surface_categories"])

    def test_assemble_due_jobs_keeps_clean_book_mode_epub_ready(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            plan = _create_epub_surface_audit_job_plan(
                store=store,
                storage=storage,
                target_language="ru",
            )

            _complete_scheduled_units_by_block_id(
                store,
                plan.job.id,
                {
                    "epub:OPS/chapter.xhtml:0": "Глава 1",
                    "epub:OPS/chapter.xhtml:1": "Переведенный абзац.",
                    "epub:aux:opf:OPS/content.opf:title:0": "Название книги",
                    "epub:aux:ncx:OPS/toc.ncx:text:0": "Название книги",
                    "epub:aux:ncx:OPS/toc.ncx:text:1": "Глава 1",
                    "epub:aux:xhtml-title:OPS/chapter.xhtml:title:0": (
                        "Название книги"
                    ),
                    "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0": "Книга I",
                },
            )

            assembled = assemble_due_jobs(store=store, storage=storage)

            persisted_job = store.get_job(plan.job.id)
            self.assertEqual(assembled, 1)
            self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.READY)
            self.assertIsNotNone(persisted_job.final_object_key)

    def test_assemble_due_jobs_skips_interrupted_job_without_translated_fragments(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="notes",
                source_text="Only source text",
            )
            with store._connection:
                store._connection.execute(
                    "UPDATE work_units SET max_attempts = 1 WHERE job_id = ?",
                    (job.id,),
                )
            claim = store.claim_next_scheduled_work_unit(
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
            )
            store.fail_claimed_work_unit(
                work_unit_id=claim.work_unit_id,
                claim_token=claim.claim_token,
                failure_kind=WorkUnitFailureKind.MALFORMED_PROVIDER_OUTPUT,
                error_message="provider failure: malformed_response",
                retry_base_delay_seconds=0,
                retry_max_delay_seconds=0,
            )

            assembled = assemble_due_jobs(store=store, storage=storage)

            persisted_job = store.get_job(job.id)
            self.assertEqual(assembled, 0)
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.INTERRUPTED,
            )
            self.assertIsNone(persisted_job.final_object_key)
            self.assertIsNone(persisted_job.partial_object_key)

    def test_assemble_due_jobs_preserves_txt_layout_from_original_source(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="notes.txt",
                content_type="text/plain; charset=utf-8",
                content=b"# Chapter\n\nKEY=value\n- First item\nBody text.\n",
            )
            chapter = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Chapter",
            )
            first_item = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-2.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First item",
            )
            body = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-3.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Body text.",
            )
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="notes.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version=TXT_ADAPTER_VERSION,
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=original.object_key,
            )
            store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:segment:1",),
                        source_text_hash="hash-1",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=chapter.object_key,
                    ),
                    WorkUnitPlan(
                        sequence=2,
                        source_block_ids=("txt:segment:4",),
                        source_text_hash="hash-2",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=first_item.object_key,
                    ),
                    WorkUnitPlan(
                        sequence=3,
                        source_block_ids=("txt:segment:5",),
                        source_text_hash="hash-3",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=body.object_key,
                    ),
                ],
            )
            for translated_text in (
                "[uk] Chapter",
                "[uk] First item",
                "[uk] Body text.",
            ):
                claim = store.claim_next_scheduled_work_unit(
                    worker_id="worker-a",
                    lease_seconds=300,
                    limits=SchedulerLimits(),
                )
                store.complete_claimed_work_unit(
                    work_unit_id=claim.work_unit_id,
                    claim_token=claim.claim_token,
                    translated_text=translated_text,
                    prompt_tokens=10,
                    completion_tokens=5,
                    cache_hit_tokens=0,
                    cache_miss_tokens=10,
                )

            assembled = assemble_due_jobs(store=store, storage=storage)

            persisted_job = store.get_job(job.id)
            self.assertEqual(assembled, 1)
            self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.READY)
            self.assertIsNotNone(persisted_job.final_object_key)
            self.assertEqual(
                storage.get_bytes(persisted_job.final_object_key).decode("utf-8"),
                "# [uk] Chapter\n\nKEY=value\n- [uk] First item\n[uk] Body text.\n",
            )

    def test_run_once_forwards_retry_delay_settings_to_scheduled_worker(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)

            with patch(
                "translator_service.scheduler_runner."
                "run_next_scheduled_stored_text_work_unit",
                return_value=None,
            ) as run_next:
                summary = run_scheduler_once(
                    store=store,
                    storage=storage,
                    worker_id="worker-a",
                    translator=RunnerTranslator(),
                    limits=SchedulerLimits(),
                    lease_seconds=300,
                    retry_base_delay_seconds=0,
                    retry_max_delay_seconds=0,
                )

            self.assertEqual(summary.completed_units, 0)
            self.assertEqual(summary.failed_units, 0)
            run_next.assert_called_once()
            self.assertEqual(
                run_next.call_args.kwargs["retry_base_delay_seconds"],
                0,
            )
            self.assertEqual(
                run_next.call_args.kwargs["retry_max_delay_seconds"],
                0,
            )

    def test_run_once_can_progress_multiple_jobs_in_parallel_when_capacity_allows(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                user_id="telegram:42",
                source_text="First paragraph",
            )
            _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-2",
                file_id="file-2",
                user_id="telegram:100",
                source_text="Second paragraph",
            )
            translator = BlockingRunnerTranslator(delay_seconds=0.05)

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=translator,
                limits=SchedulerLimits(
                    max_active_units_per_job=1,
                    max_active_units_per_user=1,
                    max_active_jobs_per_user=1,
                    max_active_units_global=2,
                ),
                lease_seconds=300,
                max_parallel_units=2,
            )

            self.assertEqual(summary.completed_units, 2)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(summary.assembled_jobs, 2)
            self.assertEqual(translator.max_active_calls, 2)
            self.assertEqual(len(set(translator.calls)), 2)

    def test_run_once_keeps_parallel_books_ready_when_runtime_status_write_fails(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            storage = LocalObjectStorage(temp_path / "objects")
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            db_path = temp_path / "admin.sqlite3"
            settings = Settings(
                admin_db_path=str(db_path),
                admin_secret_master_key=MASTER_KEY,
                deepseek_model="deepseek-test",
                admin_provider_runtime_reload_seconds=999.0,
            )
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    keys.add_key(
                        provider_id="deepseek",
                        label="stable-a",
                        plaintext="admin-key-a",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                    )
                    keys.add_key(
                        provider_id="deepseek",
                        label="stable-b",
                        plaintext="admin-key-b",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                    )
            first = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                user_id="telegram:42",
                source_text="First paragraph",
            )
            second = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-2",
                file_id="file-2",
                user_id="telegram:100",
                source_text="Second paragraph",
            )

            with (
                patch.dict(
                    "os.environ",
                    {
                        "DEEPSEEK_API_KEY": "",
                        "DEEPSEEK_API_KEYS": "",
                        "DEEPSEEK_ADAPTIVE_INITIAL_PARALLEL": "2",
                    },
                    clear=False,
                ),
                patch(
                    "translator_service.bot.runtime.DeepSeekClient",
                    _SchedulerEchoDeepSeekClient,
                ),
            ):
                translator = build_deepseek_translator(settings)
                with patch(
                    "translator_service.bot.runtime._record_deepseek_runtime_status",
                    side_effect=RuntimeError("database is locked"),
                ):
                    summary = run_scheduler_once(
                        store=store,
                        storage=storage,
                        worker_id="worker-a",
                        translator=translator,
                        limits=SchedulerLimits(
                            max_active_units_per_job=1,
                            max_active_units_per_user=1,
                            max_active_jobs_per_user=1,
                            max_active_units_global=2,
                        ),
                        lease_seconds=300,
                        max_parallel_units=2,
                    )

            first_units = store.list_work_units(first.id)
            second_units = store.list_work_units(second.id)

        self.assertEqual(summary.completed_units, 2)
        self.assertEqual(summary.failed_units, 0)
        self.assertEqual(summary.assembled_jobs, 2)
        self.assertEqual(
            store.get_job(first.id).status,
            PersistentTranslationJobStatus.READY,
        )
        self.assertEqual(
            store.get_job(second.id).status,
            PersistentTranslationJobStatus.READY,
        )
        self.assertTrue(
            all(unit.translated_text for unit in first_units + second_units)
        )

    def test_run_once_user_caps_prevent_same_user_from_filling_parallel_slots(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                user_id="telegram:42",
                source_text="First paragraph",
            )
            _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-2",
                file_id="file-2",
                user_id="telegram:42",
                source_text="Second paragraph",
            )
            translator = BlockingRunnerTranslator(delay_seconds=0.05)

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=translator,
                limits=SchedulerLimits(
                    max_active_units_per_job=1,
                    max_active_units_per_user=1,
                    max_active_jobs_per_user=1,
                    max_active_units_global=2,
                ),
                lease_seconds=300,
                max_parallel_units=2,
            )

            self.assertEqual(summary.completed_units, 2)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(summary.assembled_jobs, 2)
            self.assertEqual(translator.max_active_calls, 1)

    def test_run_once_respects_single_capacity_for_scheduled_provider_calls(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="First paragraph",
            )
            _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-2",
                file_id="file-2",
                source_text="Second paragraph",
            )
            translator = BlockingRunnerTranslator(delay_seconds=0.01)

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=translator,
                limits=SchedulerLimits(
                    max_active_units_per_job=1,
                    max_active_units_global=2,
                ),
                lease_seconds=300,
                max_parallel_units=1,
            )

            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(summary.assembled_jobs, 1)
            self.assertEqual(translator.max_active_calls, 1)

    def test_run_once_does_not_launch_units_for_cancelled_jobs_in_parallel_mode(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            cancelled = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-cancelled",
                file_id="file-cancelled",
                source_text="Do not translate",
            )
            active = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-active",
                file_id="file-active",
                source_text="Translate me",
            )
            store.cancel_job(cancelled.id)
            translator = BlockingRunnerTranslator(delay_seconds=0.01)

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=translator,
                limits=SchedulerLimits(
                    max_active_units_per_job=1,
                    max_active_units_global=2,
                ),
                lease_seconds=300,
                max_parallel_units=2,
            )

            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(translator.calls, ["Translate me"])
            self.assertEqual(
                store.get_job(cancelled.id).status,
                PersistentTranslationJobStatus.CANCELLED,
            )
            self.assertEqual(
                store.get_job(active.id).status,
                PersistentTranslationJobStatus.READY,
            )

    def test_run_once_parallel_skips_claims_when_translator_reports_zero_slots(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            first = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                user_id="telegram:42",
                source_text="First paragraph",
            )
            second = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-2",
                file_id="file-2",
                user_id="telegram:100",
                source_text="Second paragraph",
            )
            translator = HintedRunnerTranslator(available_slots=0)
            first_statuses = [
                unit.status.value for unit in store.list_work_units(first.id)
            ]
            second_statuses = [
                unit.status.value for unit in store.list_work_units(second.id)
            ]

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=translator,
                limits=SchedulerLimits(max_active_units_global=2),
                lease_seconds=300,
                max_parallel_units=2,
            )

            self.assertEqual(summary.completed_units, 0)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(summary.assembled_jobs, 0)
            self.assertEqual(translator.calls, [])
            self.assertEqual(
                [unit.status.value for unit in store.list_work_units(first.id)],
                first_statuses,
            )
            self.assertEqual(
                [unit.status.value for unit in store.list_work_units(second.id)],
                second_statuses,
            )

    def test_run_once_serial_skips_claim_when_translator_reports_zero_slots(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="First paragraph",
            )
            translator = HintedRunnerTranslator(available_slots=0)
            original_statuses = [
                unit.status.value for unit in store.list_work_units(job.id)
            ]

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=translator,
                limits=SchedulerLimits(max_active_units_global=1),
                lease_seconds=300,
                max_parallel_units=1,
            )

            self.assertEqual(summary.completed_units, 0)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(summary.assembled_jobs, 0)
            self.assertEqual(translator.calls, [])
            self.assertEqual(
                [unit.status.value for unit in store.list_work_units(job.id)],
                original_statuses,
            )

    def test_run_once_parallel_claims_when_translator_reports_positive_slots(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="First paragraph",
            )
            translator = HintedRunnerTranslator(available_slots=1)

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=translator,
                limits=SchedulerLimits(max_active_units_global=2),
                lease_seconds=300,
                max_parallel_units=2,
            )

            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(summary.assembled_jobs, 1)
            self.assertEqual(translator.calls, ["First paragraph"])

    def test_run_once_parallel_provider_failure_records_safe_retry_metadata(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            failed_job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-failing",
                file_id="file-failing",
                user_id="telegram:42",
                source_text="Private source paragraph",
            )
            completed_job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-completed",
                file_id="file-completed",
                user_id="telegram:100",
                source_text="Second paragraph",
            )

            with self.assertLogs(
                "translator_service.scheduler_runner",
                level="ERROR",
            ) as log_records:
                summary = run_scheduler_once(
                    store=store,
                    storage=storage,
                    worker_id="worker-a",
                    translator=UnsafeProviderFailureRunnerTranslator(),
                    limits=SchedulerLimits(
                        max_active_units_per_job=1,
                        max_active_units_global=2,
                    ),
                    lease_seconds=300,
                    max_parallel_units=2,
                    retry_base_delay_seconds=60,
                    retry_max_delay_seconds=60,
                )

            [failed_unit] = store.list_work_units(failed_job.id)
            [completed_unit] = store.list_work_units(completed_job.id)
            attempts = store.list_work_unit_attempts(failed_unit.id)
            scheduler_events = json.dumps(
                [
                    json.loads(event.payload_json)
                    for event in store.list_scheduler_events(failed_job.id)
                ]
            )
            unsafe_values = [
                "Private source paragraph",
                "sk-private-provider-key",
                "/var/private/source.txt",
                "raw provider traceback",
                "DeepSeek provider read timeout",
                "RuntimeError",
                "Traceback",
            ]
            logs = "\n".join(log_records.output)

            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(summary.failed_units, 1)
            self.assertEqual(summary.assembled_jobs, 1)
            self.assertEqual(failed_unit.status.value, "failed_retryable")
            self.assertEqual(
                failed_unit.last_error,
                "provider failure: timeout",
            )
            self.assertEqual(len(attempts), 1)
            self.assertEqual(
                attempts[0].error_message,
                "provider failure: timeout",
            )
            self.assertEqual(
                attempts[0].error_code,
                "timeout",
            )
            self.assertIn('"failure_category": "timeout"', scheduler_events)
            self.assertEqual(
                store.get_job(failed_job.id).status,
                PersistentTranslationJobStatus.TRANSLATING,
            )
            self.assertEqual(
                store.get_job(completed_job.id).status,
                PersistentTranslationJobStatus.READY,
            )
            self.assertEqual(completed_unit.status.value, "translated")
            for unsafe_value in unsafe_values:
                self.assertNotIn(unsafe_value, failed_unit.last_error or "")
                self.assertNotIn(unsafe_value, attempts[0].error_message or "")
                self.assertNotIn(unsafe_value, scheduler_events)
                self.assertNotIn(unsafe_value, logs)

    def test_run_once_skips_provider_call_when_provider_slot_lease_unavailable(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            base_store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(base_store.close)
            store = ProviderSlotLeaseGuardedStore(
                base_store,
                acquire_available=False,
            )
            job = _create_single_unit_txt_job(
                store=base_store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="First paragraph",
            )
            translator = ProviderSlotAwareRunnerTranslator()
            started_units = []

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=translator,
                limits=SchedulerLimits(max_active_units_global=1),
                lease_seconds=300,
                work_unit_started_callback=started_units.append,
            )

            [unit] = base_store.list_work_units(job.id)
            self.assertEqual(summary.completed_units, 0)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(summary.assembled_jobs, 0)
            self.assertEqual(translator.calls, [])
            self.assertEqual(started_units, [])
            self.assertEqual(len(store.acquire_calls), 1)
            self.assertEqual(len(store.defer_calls), 1)
            self.assertEqual(store.release_calls, [])
            self.assertEqual(unit.status.value, "pending")
            self.assertEqual(unit.attempt_count, 0)
            self.assertIsNone(unit.claim_token)
            self.assertEqual(base_store.list_work_unit_attempts(unit.id), [])

    def test_run_once_skips_provider_call_when_account_cap_denies_slot(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            base_store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(base_store.close)
            store = ProviderSlotLeaseGuardedStore(
                base_store,
                active_cap_counts={"deepseek-account-test": 1},
            )
            job = _create_single_unit_txt_job(
                store=base_store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="First paragraph",
            )
            translator = ProviderSlotAwareRunnerTranslator()

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=translator,
                limits=SchedulerLimits(max_active_units_global=1),
                lease_seconds=300,
            )

            [unit] = base_store.list_work_units(job.id)
            self.assertEqual(summary.completed_units, 0)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(translator.calls, [])
            self.assertEqual(len(store.acquire_calls), 1)
            self.assertEqual(len(store.defer_calls), 1)
            self.assertEqual(unit.status.value, "pending")
            self.assertEqual(unit.attempt_count, 0)
            self.assertEqual(base_store.list_work_unit_attempts(unit.id), [])

    def test_run_once_skips_provider_call_when_model_cap_denies_slot(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            base_store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(base_store.close)
            store = ProviderSlotLeaseGuardedStore(
                base_store,
                active_cap_counts={"deepseek-model-test": 1},
            )
            job = _create_single_unit_txt_job(
                store=base_store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="First paragraph",
            )
            translator = ProviderSlotAwareRunnerTranslator()

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=translator,
                limits=SchedulerLimits(max_active_units_global=1),
                lease_seconds=300,
            )

            [unit] = base_store.list_work_units(job.id)
            self.assertEqual(summary.completed_units, 0)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(translator.calls, [])
            self.assertEqual(len(store.acquire_calls), 1)
            self.assertEqual(len(store.defer_calls), 1)
            self.assertEqual(unit.status.value, "pending")
            self.assertEqual(unit.attempt_count, 0)
            self.assertEqual(base_store.list_work_unit_attempts(unit.id), [])

    def test_run_once_releases_provider_slot_lease_after_serial_success(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            base_store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(base_store.close)
            store = ProviderSlotLeaseGuardedStore(base_store)
            _create_single_unit_txt_job(
                store=base_store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="First paragraph",
            )
            translator = ProviderSlotAwareRunnerTranslator()

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=translator,
                limits=SchedulerLimits(max_active_units_global=1),
                lease_seconds=300,
            )

            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(translator.calls, ["First paragraph"])
            self.assertEqual(translator.channel_contexts, ["deepseek-channel-1"])
            self.assertEqual(
                [call.release_reason for call in store.release_calls],
                ["completed"],
            )

    def test_run_once_releases_provider_slot_lease_after_retryable_failure(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            base_store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(base_store.close)
            store = ProviderSlotLeaseGuardedStore(base_store)
            job = _create_single_unit_txt_job(
                store=base_store,
                storage=storage,
                order_id="order-failing",
                file_id="file-failing",
                source_text="Private source paragraph",
            )

            with self.assertLogs("translator_service.worker", level="ERROR"):
                summary = run_scheduler_once(
                    store=store,
                    storage=storage,
                    worker_id="worker-a",
                    translator=ProviderSlotAwareFailingRunnerTranslator(),
                    limits=SchedulerLimits(max_active_units_global=1),
                    lease_seconds=300,
                    retry_base_delay_seconds=60,
                    retry_max_delay_seconds=60,
                )

            [unit] = base_store.list_work_units(job.id)
            attempts = base_store.list_work_unit_attempts(unit.id)
            self.assertEqual(summary.failed_units, 1)
            self.assertEqual(unit.status.value, "failed_retryable")
            self.assertEqual(unit.last_error, "provider failure: timeout")
            self.assertEqual(attempts[0].error_code, "timeout")
            self.assertEqual(
                [call.release_reason for call in store.release_calls],
                ["retryable_failure"],
            )

    def test_run_once_releases_provider_slot_lease_after_terminal_failure(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            base_store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(base_store.close)
            store = ProviderSlotLeaseGuardedStore(base_store)
            job = _create_single_unit_txt_job(
                store=base_store,
                storage=storage,
                order_id="order-failing",
                file_id="file-failing",
                source_text="Private source paragraph",
            )
            with base_store._connection:
                base_store._connection.execute(
                    "UPDATE work_units SET max_attempts = 1 WHERE job_id = ?",
                    (job.id,),
                )

            with self.assertLogs("translator_service.worker", level="ERROR"):
                summary = run_scheduler_once(
                    store=store,
                    storage=storage,
                    worker_id="worker-a",
                    translator=ProviderSlotAwareFailingRunnerTranslator(),
                    limits=SchedulerLimits(max_active_units_global=1),
                    lease_seconds=300,
                    retry_base_delay_seconds=0,
                    retry_max_delay_seconds=0,
                )

            [unit] = base_store.list_work_units(job.id)
            self.assertEqual(summary.failed_units, 1)
            self.assertEqual(unit.status.value, "failed_terminal")
            self.assertEqual(
                [call.release_reason for call in store.release_calls],
                ["terminal_failure"],
            )

    def test_run_once_terminal_provider_contract_failures_are_classified_safely(self):
        cases = [
            (
                DeepSeekUnsafeModelOutputError("tool_or_execution_claim"),
                "unsafe_model_output",
            ),
            (
                DeepSeekApiError("DeepSeek response message content is not text"),
                "malformed_response",
            ),
        ]

        for error, expected_category in cases:
            with self.subTest(expected_category=expected_category):
                with TemporaryDirectory() as temp_dir:
                    storage = LocalObjectStorage(Path(temp_dir))
                    base_store = SQLiteTranslationJobStore(":memory:")
                    self.addCleanup(base_store.close)
                    store = ProviderSlotLeaseGuardedStore(base_store)
                    job = _create_single_unit_txt_job(
                        store=base_store,
                        storage=storage,
                        order_id=f"order-{expected_category}",
                        file_id=f"file-{expected_category}",
                        source_text="Synthetic source paragraph",
                    )
                    with base_store._connection:
                        base_store._connection.execute(
                            "UPDATE work_units SET max_attempts = 1 WHERE job_id = ?",
                            (job.id,),
                        )

                    with self.assertLogs("translator_service.worker", level="ERROR"):
                        summary = run_scheduler_once(
                            store=store,
                            storage=storage,
                            worker_id="worker-a",
                            translator=ProviderSlotAwareRaisingRunnerTranslator(error),
                            limits=SchedulerLimits(max_active_units_global=1),
                            lease_seconds=300,
                            retry_base_delay_seconds=0,
                            retry_max_delay_seconds=0,
                        )

                    [unit] = base_store.list_work_units(job.id)
                    [attempt] = base_store.list_work_unit_attempts(unit.id)
                    scheduler_events = json.dumps(
                        [
                            json.loads(event.payload_json)
                            for event in base_store.list_scheduler_events(job.id)
                        ],
                        sort_keys=True,
                    )

                    self.assertEqual(summary.failed_units, 1)
                    self.assertEqual(unit.status.value, "failed_terminal")
                    self.assertEqual(
                        unit.last_error,
                        f"provider failure: {expected_category}",
                    )
                    self.assertEqual(attempt.error_code, expected_category)
                    self.assertIn(
                        f'"failure_category": "{expected_category}"',
                        scheduler_events,
                    )
                    self.assertIn(
                        '"terminal_reason": "max_attempts_reached"',
                        scheduler_events,
                    )
                    self.assertEqual(
                        [call.release_reason for call in store.release_calls],
                        ["terminal_failure"],
                    )
                    self.assertNotIn("Synthetic source paragraph", scheduler_events)

    def test_run_once_releases_provider_slot_lease_after_cancelled_completion(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            base_store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(base_store.close)
            store = ProviderSlotLeaseGuardedStore(base_store)
            job = _create_single_unit_txt_job(
                store=base_store,
                storage=storage,
                order_id="order-cancel",
                file_id="file-cancel",
                source_text="First paragraph",
            )
            translator = ProviderSlotAwareCancellingRunnerTranslator(
                store=base_store,
                job_id=job.id,
            )

            with self.assertLogs("translator_service.worker", level="WARNING"):
                summary = run_scheduler_once(
                    store=store,
                    storage=storage,
                    worker_id="worker-a",
                    translator=translator,
                    limits=SchedulerLimits(max_active_units_global=1),
                    lease_seconds=300,
                )

            self.assertEqual(summary.completed_units, 0)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(
                base_store.get_job(job.id).status,
                PersistentTranslationJobStatus.CANCELLED,
            )
            self.assertEqual(
                [call.release_reason for call in store.release_calls],
                ["cancelled"],
            )

    def test_run_once_recovers_expired_provider_slot_leases_before_claiming(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            base_store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(base_store.close)
            store = ProviderSlotLeaseGuardedStore(base_store, expired_recovered=1)
            _create_single_unit_txt_job(
                store=base_store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="First paragraph",
            )

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=ProviderSlotAwareRunnerTranslator(),
                limits=SchedulerLimits(max_active_units_global=1),
                lease_seconds=300,
            )

            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(store.recover_expired_calls, 1)
            self.assertEqual(store.recovered_expired_total, 1)

    def test_run_once_recovers_expired_work_unit_leases_before_serial_claiming(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            base_store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(base_store.close)
            store = WorkUnitLeaseRecoveringStore(base_store)
            _create_single_unit_txt_job(
                store=base_store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="First paragraph",
            )

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=RunnerTranslator(),
                limits=SchedulerLimits(max_active_units_global=1),
                lease_seconds=300,
                retry_base_delay_seconds=17,
                retry_max_delay_seconds=43,
            )

            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(
                store.events[:2],
                ["recover_expired_leases", "claim_next_scheduled_work_unit"],
            )
            self.assertEqual(store.recover_expired_calls, 1)
            self.assertEqual(
                store.recover_expired_retry_args,
                [(17, 43)],
            )

    def test_run_once_recovers_expired_work_unit_leases_before_parallel_claiming(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            base_store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(base_store.close)
            store = WorkUnitLeaseRecoveringStore(base_store)
            _create_single_unit_txt_job(
                store=base_store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="First paragraph",
            )

            summary = run_scheduler_once(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=RunnerTranslator(),
                limits=SchedulerLimits(max_active_units_global=1),
                lease_seconds=300,
                retry_base_delay_seconds=17,
                retry_max_delay_seconds=43,
                max_parallel_units=2,
            )

            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(
                store.events[:2],
                ["recover_expired_leases", "claim_next_scheduled_work_unit"],
            )
            self.assertEqual(store.recover_expired_calls, 1)
            self.assertEqual(
                store.recover_expired_retry_args,
                [(17, 43)],
            )

    def test_assemble_due_jobs_reconciles_existing_final_output(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            final = storage.put_bytes(
                kind=StoredFileKind.FINAL,
                file_name="notes.uk.txt",
                content_type="text/plain; charset=utf-8",
                content=b"[uk] First paragraph",
            )
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="notes.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version=TXT_ADAPTER_VERSION,
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=source.object_key,
            )
            store.add_work_units(
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
            claim = store.claim_next_scheduled_work_unit(
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
            )
            store.complete_claimed_work_unit(
                work_unit_id=claim.work_unit_id,
                claim_token=claim.claim_token,
                translated_text="[uk] First paragraph",
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit_tokens=0,
                cache_miss_tokens=10,
            )
            store.attach_job_output(job.id, final_object_key=final.object_key)

            assembled = assemble_due_jobs(store=store, storage=storage)

            persisted_job = store.get_job(job.id)
            self.assertEqual(assembled, 1)
            self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.READY)
            self.assertEqual(persisted_job.final_object_key, final.object_key)

    def test_assemble_due_jobs_reassembles_when_attached_final_object_is_missing(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="First paragraph",
            )
            claim = store.claim_next_scheduled_work_unit(
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
            )
            store.complete_claimed_work_unit(
                work_unit_id=claim.work_unit_id,
                claim_token=claim.claim_token,
                translated_text="[uk] First paragraph",
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit_tokens=0,
                cache_miss_tokens=10,
            )
            final = storage.put_bytes(
                kind=StoredFileKind.FINAL,
                file_name="file-1.uk.txt",
                content_type="text/plain; charset=utf-8",
                content=b"[uk] First paragraph",
            )
            store.attach_job_output(job.id, final_object_key=final.object_key)
            storage.delete(final.object_key)

            assembled = assemble_due_jobs(store=store, storage=storage)

            persisted_job = store.get_job(job.id)
            self.assertEqual(assembled, 1)
            self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.READY)
            self.assertEqual(persisted_job.final_object_key, final.object_key)
            self.assertTrue(storage.exists(final.object_key))
            self.assertEqual(
                storage.get_bytes(final.object_key).decode("utf-8"),
                "[uk] First paragraph",
            )

    def test_assemble_due_jobs_retries_idempotently_after_attach_failure(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = _create_single_unit_txt_job(
                store=store,
                storage=storage,
                order_id="order-1",
                file_id="file-1",
                source_text="First paragraph",
            )
            claim = store.claim_next_scheduled_work_unit(
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
            )
            store.complete_claimed_work_unit(
                work_unit_id=claim.work_unit_id,
                claim_token=claim.claim_token,
                translated_text="[uk] First paragraph",
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit_tokens=0,
                cache_miss_tokens=10,
            )
            expected_key = (
                "final/"
                f"{sha256(b'[uk] First paragraph').hexdigest()[:16]}-file-1.uk.txt"
            )
            failing_store = AttachFailingStore(store)

            with self.assertRaisesRegex(RuntimeError, "synthetic attach failure"):
                assemble_due_jobs(store=failing_store, storage=storage)

            after_failure = store.get_job(job.id)
            self.assertEqual(
                after_failure.status,
                PersistentTranslationJobStatus.ASSEMBLING,
            )
            self.assertIsNone(after_failure.final_object_key)
            self.assertTrue(storage.exists(expected_key))

            assembled = assemble_due_jobs(store=store, storage=storage)

            persisted_job = store.get_job(job.id)
            self.assertEqual(assembled, 1)
            self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.READY)
            self.assertEqual(persisted_job.final_object_key, expected_key)
            self.assertEqual(
                storage.get_bytes(expected_key).decode("utf-8"),
                "[uk] First paragraph",
            )

    def test_assemble_due_jobs_reassembles_when_attached_partial_object_is_missing(self):  # noqa: E501
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="notes.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First.\n\nSecond.",
            )
            first = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First.",
            )
            second = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-2.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Second.",
            )
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="notes.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version=TXT_ADAPTER_VERSION,
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=original.object_key,
            )
            store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:segment:1",),
                        source_text_hash="hash-1",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=first.object_key,
                    ),
                    WorkUnitPlan(
                        sequence=2,
                        source_block_ids=("txt:segment:3",),
                        source_text_hash="hash-2",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=second.object_key,
                    ),
                ],
            )
            with store._connection:
                store._connection.execute(
                    "UPDATE work_units SET max_attempts = 1 WHERE job_id = ?",
                    (job.id,),
                )
            first_claim = store.claim_next_scheduled_work_unit(
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
            )
            store.complete_claimed_work_unit(
                work_unit_id=first_claim.work_unit_id,
                claim_token=first_claim.claim_token,
                translated_text="[uk] First.",
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit_tokens=0,
                cache_miss_tokens=10,
            )
            failed_claim = store.claim_next_scheduled_work_unit(
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
            )
            store.fail_claimed_work_unit(
                work_unit_id=failed_claim.work_unit_id,
                claim_token=failed_claim.claim_token,
                failure_kind=WorkUnitFailureKind.MALFORMED_PROVIDER_OUTPUT,
                error_message="provider failure: malformed_response",
                retry_base_delay_seconds=0,
                retry_max_delay_seconds=0,
            )
            partial = storage.put_bytes(
                kind=StoredFileKind.PARTIAL,
                file_name="notes.uk.partial.txt",
                content_type="text/plain; charset=utf-8",
                content=b"[uk] First.\n\nSecond.",
            )
            store.attach_job_output(job.id, partial_object_key=partial.object_key)
            storage.delete(partial.object_key)

            assembled = assemble_due_jobs(store=store, storage=storage)

            persisted_job = store.get_job(job.id)
            self.assertEqual(assembled, 1)
            if persisted_job is None:
                self.fail("expected persisted job")
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.PARTIAL,
            )
            self.assertEqual(persisted_job.partial_object_key, partial.object_key)
            self.assertTrue(storage.exists(partial.object_key))
            self.assertEqual(
                storage.get_bytes(partial.object_key).decode("utf-8"),
                "[uk] First.\n\nSecond.",
            )

    def test_assemble_due_jobs_rejects_unsupported_document_kind(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            store = SQLiteTranslationJobStore(":memory:")
            self.addCleanup(store.close)
            job = store.create_job(
                order_id="order-1",
                user_id="telegram:42",
                file_id="file-1",
                file_name="notes.pdf",
                document_kind="pdf",
                source_language="en",
                target_language="uk",
                adapter_version="pdf-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=source.object_key,
            )
            store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("pdf:0",),
                        source_text_hash="hash-1",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=source.object_key,
                    )
                ],
            )
            claim = store.claim_next_scheduled_work_unit(
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
            )
            store.complete_claimed_work_unit(
                work_unit_id=claim.work_unit_id,
                claim_token=claim.claim_token,
                translated_text="[uk] First paragraph",
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit_tokens=0,
                cache_miss_tokens=10,
            )

            with self.assertRaisesRegex(
                ValueError,
                "Unsupported document kind for assembly: pdf",
            ):
                assemble_due_jobs(store=store, storage=storage)

            persisted_job = store.get_job(job.id)
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.ASSEMBLING,
            )
            self.assertIsNone(persisted_job.final_object_key)
            self.assertIsNone(persisted_job.partial_object_key)


class RunnerTranslator:
    def __init__(self) -> None:
        self.last_usage = ProviderUsage(prompt_tokens=10, completion_tokens=5)

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        return f"[{target_language}] {text}"


class WorkUnitLeaseRecoveringStore:
    def __init__(self, store: SQLiteTranslationJobStore) -> None:
        self._store = store
        self.events: list[str] = []
        self.recover_expired_calls = 0
        self.recover_expired_retry_args: list[tuple[int, int]] = []

    def __getattr__(self, name: str):
        return getattr(self._store, name)

    def recover_expired_leases(
        self,
        *,
        now: datetime,
        retry_base_delay_seconds: int,
        retry_max_delay_seconds: int,
    ) -> int:
        self.events.append("recover_expired_leases")
        self.recover_expired_calls += 1
        self.recover_expired_retry_args.append(
            (retry_base_delay_seconds, retry_max_delay_seconds)
        )
        return 0

    def claim_next_scheduled_work_unit(self, **kwargs):
        self.events.append("claim_next_scheduled_work_unit")
        return self._store.claim_next_scheduled_work_unit(**kwargs)


@dataclass(frozen=True)
class ProviderSlotReleaseCall:
    lease_token: str
    work_unit_claim_token: str
    release_reason: str


class ProviderSlotLeaseGuardedStore:
    def __init__(
        self,
        store: SQLiteTranslationJobStore,
        *,
        acquire_available: bool = True,
        expired_recovered: int = 0,
        active_cap_counts: dict[str, int] | None = None,
    ) -> None:
        self._store = store
        self.acquire_available = acquire_available
        self.expired_recovered = expired_recovered
        self.active_cap_counts = dict(active_cap_counts or {})
        self.recover_expired_calls = 0
        self.recovered_expired_total = 0
        self.inventory: list[ProviderSlotInventoryItem] = []
        self.acquire_calls: list[dict[str, object]] = []
        self.defer_calls: list[tuple[str, str]] = []
        self.release_calls: list[ProviderSlotReleaseCall] = []
        self._leases: dict[str, ProviderSlotLease] = {}

    def __getattr__(self, name: str):
        return getattr(self._store, name)

    def recover_expired_provider_slot_leases(self, *, now: datetime) -> int:
        self.recover_expired_calls += 1
        self.recovered_expired_total += self.expired_recovered
        return self.expired_recovered

    def upsert_provider_slot_inventory(
        self,
        *,
        provider_id: str,
        channel_id: str,
        max_parallel_requests: int,
        capacity_source: str | None = None,
    ) -> list[ProviderSlotInventoryItem]:
        item = ProviderSlotInventoryItem(
            provider_id=provider_id,
            channel_id=channel_id,
            max_parallel_requests=max_parallel_requests,
            capacity_source=capacity_source,
        )
        self.inventory.append(item)
        return [item]

    def acquire_provider_slot_lease(
        self,
        *,
        provider_id: str,
        job_id: str,
        work_unit_id: str,
        worker_id: str,
        work_unit_claim_token: str,
        lease_seconds: int,
        channel_id: str | None = None,
        capacity_caps: list[ProviderCapacityCap] | None = None,
    ) -> ProviderSlotLease | None:
        self.acquire_calls.append(
            {
                "provider_id": provider_id,
                "job_id": job_id,
                "work_unit_id": work_unit_id,
                "worker_id": worker_id,
                "work_unit_claim_token": work_unit_claim_token,
                "lease_seconds": lease_seconds,
                "channel_id": channel_id,
                "capacity_caps": list(capacity_caps or []),
            }
        )
        if not self.acquire_available:
            return None
        for cap in capacity_caps or []:
            if self.active_cap_counts.get(cap.cap_id, 0) >= cap.max_parallel_requests:
                return None
        now = datetime.now(UTC)
        lease_token = f"slot-token-{len(self._leases) + 1}"
        lease = ProviderSlotLease(
            lease_id=f"lease-{len(self._leases) + 1}",
            lease_token=lease_token,
            provider_id=provider_id,
            channel_id=channel_id or "deepseek-channel-1",
            slot_index=0,
            job_id=job_id,
            work_unit_id=work_unit_id,
            worker_id=worker_id,
            work_unit_claim_token=work_unit_claim_token,
            status=ProviderSlotLeaseStatus.ACTIVE,
            acquired_at=now,
            lease_until=now + timedelta(seconds=max(1, lease_seconds)),
            released_at=None,
            release_reason=None,
        )
        self._leases[lease_token] = lease
        return lease

    def release_provider_slot_lease(
        self,
        *,
        lease_token: str,
        work_unit_claim_token: str,
        release_reason: str = "released",
    ) -> ProviderSlotLease | None:
        lease = self._leases.get(lease_token)
        if lease is None or lease.work_unit_claim_token != work_unit_claim_token:
            return None
        if lease.status is not ProviderSlotLeaseStatus.ACTIVE:
            return lease
        self.release_calls.append(
            ProviderSlotReleaseCall(
                lease_token=lease_token,
                work_unit_claim_token=work_unit_claim_token,
                release_reason=release_reason,
            )
        )
        released = replace(
            lease,
            status=ProviderSlotLeaseStatus.RELEASED,
            released_at=datetime.now(UTC),
            release_reason=release_reason,
        )
        self._leases[lease_token] = released
        return released

    def defer_claimed_work_unit_for_provider_capacity(
        self,
        *,
        work_unit_id: str,
        claim_token: str,
    ):
        self.defer_calls.append((work_unit_id, claim_token))
        with self._store._connection:
            self._store._connection.execute(
                """
                UPDATE work_units
                SET status = ?, worker_id = NULL, claim_token = NULL,
                    lease_until = NULL, attempt_count = MAX(0, attempt_count - 1),
                    started_at = NULL, updated_at = ?, available_at = ?
                WHERE id = ? AND claim_token = ? AND status = ?
                """,
                (
                    "pending",
                    datetime.now(UTC).isoformat(),
                    datetime.now(UTC).isoformat(),
                    work_unit_id,
                    claim_token,
                    "translating",
                ),
            )
        return self._store.get_work_unit(work_unit_id)


class AttachFailingStore:
    def __init__(self, store: SQLiteTranslationJobStore) -> None:
        self._store = store

    def __getattr__(self, name: str):
        return getattr(self._store, name)

    def attach_job_output(self, *args, **kwargs):
        raise RuntimeError("synthetic attach failure")


class ProviderSlotAwareRunnerTranslator(RunnerTranslator):
    provider_id = "deepseek"

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []
        self.channel_contexts: list[str] = []

    def provider_slot_inventory(self) -> list[ProviderSlotInventoryItem]:
        return [
            ProviderSlotInventoryItem(
                provider_id="deepseek",
                channel_id="deepseek-channel-1",
                max_parallel_requests=1,
                capacity_source="test",
            )
        ]

    def provider_capacity_caps(self) -> list[ProviderCapacityCap]:
        return [
            ProviderCapacityCap(
                provider_id="deepseek",
                cap_id="deepseek-account-test",
                scope=ProviderCapacityCapScope.ACCOUNT,
                max_parallel_requests=1,
                channel_ids=("deepseek-channel-1",),
            ),
            ProviderCapacityCap(
                provider_id="deepseek",
                cap_id="deepseek-model-test",
                scope=ProviderCapacityCapScope.MODEL,
                max_parallel_requests=1,
                channel_ids=("deepseek-channel-1",),
            ),
        ]

    @contextmanager
    def provider_slot_channel_lease(self, channel_id: str):
        self.channel_contexts.append(channel_id)
        yield

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        self.calls.append(text)
        return super().translate(
            text=text,
            source_language=source_language,
            target_language=target_language,
        )


class ProviderSlotAwareFailingRunnerTranslator(ProviderSlotAwareRunnerTranslator):
    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        self.calls.append(text)
        raise RuntimeError(
            "DeepSeek provider read timeout for Private source paragraph "
            "with sk-private-provider-key at /var/private/source.txt"
        )


class ProviderSlotAwareRaisingRunnerTranslator(ProviderSlotAwareRunnerTranslator):
    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        self.calls.append(text)
        raise self.error


class ProviderSlotAwareCancellingRunnerTranslator(ProviderSlotAwareRunnerTranslator):
    def __init__(self, *, store: SQLiteTranslationJobStore, job_id: str) -> None:
        super().__init__()
        self._store = store
        self._job_id = job_id

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        self.calls.append(text)
        self._store.cancel_job(self._job_id)
        return f"[{target_language}] {text}"


class BookAuditRunnerTranslator(RunnerTranslator):
    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        return (
            "Кімната стихла, but she could not remember where the "
            "scheduled translated sentinel was hidden."
        )


class FailingRunnerTranslator:
    last_usage = None

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        raise RuntimeError(
            "DeepSeek provider read timeout for Private source paragraph "
            "at /var/private/source.txt"
        )


class InstrumentedRepairFallbackClientFactory:
    def __init__(self, *, final_xml: str) -> None:
        self.final_xml = final_xml
        self.transports_by_key: dict[str, InstrumentedRepairFallbackTransport] = {}
        self.clients_by_key: dict[str, DeepSeekClient] = {}

    def __call__(self, *, api_key: str):
        transport = InstrumentedRepairFallbackTransport(
            api_key=api_key,
            final_xml=self.final_xml,
        )
        client = DeepSeekClient(
            api_key=api_key,
            model="fake-model",
            base_url="https://fake-deepseek.local",
            transport=transport,
            retry_delay_seconds=0,
        )
        self.transports_by_key[api_key] = transport
        self.clients_by_key[api_key] = client
        return client

    def application_calls(self, api_key: str) -> int:
        return len(self.transports_by_key[api_key].attempts_by_body)

    def successful_application_calls(self, api_key: str) -> int:
        return len(self.transports_by_key[api_key].successful_bodies)

    def transport_attempts(self, api_key: str) -> int:
        return sum(self.transports_by_key[api_key].attempts_by_body.values())


class InstrumentedRepairFallbackTransport:
    def __init__(self, *, api_key: str, final_xml: str) -> None:
        self.api_key = api_key
        self.attempts_by_body: dict[bytes, int] = {}
        self.successful_bodies: list[dict[str, object]] = []
        self.responses = [
            _broken_json_batch_response(prompt_tokens=11, completion_tokens=4),
            _broken_json_batch_response(prompt_tokens=13, completion_tokens=4),
            _xml_batch_response(
                final_xml,
                prompt_tokens=17,
                completion_tokens=6,
            ),
        ]

    def __call__(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> tuple[int, bytes]:
        self.attempts_by_body[body] = self.attempts_by_body.get(body, 0) + 1
        if self.api_key == "key-a" or self.attempts_by_body[body] < 3:
            return 429, json.dumps({"error": {"message": "rate limit"}}).encode(
                "utf-8"
            )
        self.successful_bodies.append(json.loads(body.decode("utf-8")))
        response = self.responses[len(self.successful_bodies) - 1]
        return 200, json.dumps(response).encode("utf-8")


class SchedulerDeepSeekPoolTranslator:
    def __init__(self, *, factory: InstrumentedRepairFallbackClientFactory) -> None:
        self.pool = DeepSeekKeyPoolTranslator(
            channels=[
                DeepSeekChannelConfig(api_key="key-a", label="a"),
                DeepSeekChannelConfig(api_key="key-b", label="b"),
            ],
            client_factory=factory,
            cooldown_seconds=0,
            clock=lambda: 100.0,
        )
        self.worker_calls: list[str] = []

    @property
    def last_usage(self):
        return self.pool.last_usage

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
        translation_context=None,
        service_glossary_context_present: bool = False,
    ) -> str:
        self.worker_calls.append(text)
        return self.pool.translate(
            text=text,
            source_language=source_language,
            target_language=target_language,
            translation_context=translation_context,
            service_glossary_context_present=service_glossary_context_present,
        )


def _broken_json_batch_response(
    *,
    prompt_tokens: int,
    completion_tokens: int,
) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"translations":[{"id":"0","text":"Первая строка\\n'
                        'Вторая строка с "неэкранированной цитатой"},'
                        '{"id":"1","text":"Готово"}]}'
                    )
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _xml_batch_response(
    content: str,
    *,
    prompt_tokens: int,
    completion_tokens: int,
) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {"content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _successful_repair_fallback_xml() -> str:
    return (
        "<translation_batch>"
        '<translation_block id="0">Перший абзац</translation_block>'
        '<translation_block id="1">Другий абзац</translation_block>'
        "</translation_batch>"
    )


def _malformed_repair_fallback_xml() -> str:
    return (
        "<translation_batch>"
        '<translation_block id="0">Тільки один абзац</translation_block>'
        "</translation_batch>"
    )


class UnsafeProviderFailureRunnerTranslator(RunnerTranslator):
    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        if text == "Private source paragraph":
            raise RuntimeError(
                "DeepSeek provider read timeout for Private source paragraph "
                "with sk-private-provider-key at /var/private/source.txt "
                "raw provider traceback"
            )
        return super().translate(
            text=text,
            source_language=source_language,
            target_language=target_language,
        )


class _SchedulerEchoDeepSeekClient:
    def __init__(self, *, api_key: str, **kwargs) -> None:
        self.api_key = api_key
        self.last_usage = ProviderUsage(prompt_tokens=10, completion_tokens=5)

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        return f"[{target_language}] {text}"


class HintedRunnerTranslator(RunnerTranslator):
    def __init__(self, *, available_slots: int) -> None:
        super().__init__()
        self.available_slots = available_slots
        self.calls: list[str] = []

    def available_parallel_slots(self) -> int:
        return self.available_slots

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        self.calls.append(text)
        return super().translate(
            text=text,
            source_language=source_language,
            target_language=target_language,
        )


class BlockingRunnerTranslator:
    def __init__(self, *, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.last_usage = ProviderUsage(prompt_tokens=10, completion_tokens=5)
        self.calls: list[str] = []
        self.active_calls = 0
        self.max_active_calls = 0
        self._lock = threading.Lock()

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        with self._lock:
            self.calls.append(text)
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        time.sleep(self.delay_seconds)
        with self._lock:
            self.active_calls -= 1
        return f"[{target_language}] {text}"


@dataclass(frozen=True)
class UsageCall:
    job_id: str
    user_id: str
    work_unit_id: str
    prompt_tokens: int
    completion_tokens: int


class RecordingBetaSafetyGuard:
    def __init__(self, *, allowed: bool) -> None:
        self.allowed = allowed
        self.can_start_calls = 0
        self.usage_calls: list[UsageCall] = []
        self.consumed_jobs: list[str] = []
        self.released_jobs: list[tuple[str, str]] = []

    def can_start_new_work(self) -> BetaSafetyDecision:
        self.can_start_calls += 1
        if self.allowed:
            return BetaSafetyDecision(
                allowed=True,
                reason_code=BETA_SAFETY_ALLOWED,
                safe_message="allowed",
            )
        return BetaSafetyDecision(
            allowed=False,
            reason_code=BETA_SAFETY_GLOBAL_DAILY_CAP,
            safe_message="blocked",
        )

    def reserve_job(
        self,
        *,
        job_id: str,
        user_id: str,
        estimate: JobCostEstimate,
    ) -> BetaSafetyDecision:
        return self.can_start_new_work()

    def record_work_unit_usage(
        self,
        *,
        job_id: str,
        user_id: str,
        work_unit_id: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        self.usage_calls.append(
            UsageCall(
                job_id=job_id,
                user_id=user_id,
                work_unit_id=work_unit_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )

    def release_job(self, *, job_id: str, reason: str) -> None:
        self.released_jobs.append((job_id, reason))

    def mark_job_consumed(self, *, job_id: str) -> None:
        self.consumed_jobs.append(job_id)


def _create_single_unit_txt_job(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    order_id: str,
    file_id: str,
    user_id: str = "telegram:42",
    source_text: str,
    upload_safety_id: str | None = None,
):
    original = storage.put_bytes(
        kind=StoredFileKind.ORIGINAL,
        file_name=f"{file_id}.txt",
        content_type="text/plain; charset=utf-8",
        content=source_text.encode("utf-8"),
    )
    source = storage.put_bytes(
        kind=StoredFileKind.INTERMEDIATE,
        file_name=f"{file_id}-unit-1.txt",
        content_type="text/plain; charset=utf-8",
        content=source_text.encode("utf-8"),
    )
    job = store.create_job(
        order_id=order_id,
        user_id=user_id,
        file_id=file_id,
        file_name=f"{file_id}.txt",
        document_kind="txt",
        source_language="en",
        target_language="uk",
        adapter_version=TXT_ADAPTER_VERSION,
        prompt_version="plain-v1",
        pricing_snapshot_id="pricing-1",
        source_object_key=original.object_key,
        translation_policy=(
            json.dumps(
                {
                    "upload_safety": {
                        "accepted_source_object_key": original.object_key,
                        "source_gate": "upload_safety_ledger",
                        "upload_safety_id": upload_safety_id,
                    }
                }
            )
            if upload_safety_id is not None
            else None
        ),
    )
    store.add_work_units(
        job.id,
        [
            WorkUnitPlan(
                sequence=1,
                source_block_ids=("txt:segment:1",),
                source_text_hash=f"hash-{file_id}",
                prompt_tier="plain",
                source_language="en",
                target_language="uk",
                source_object_key=source.object_key,
            )
        ],
    )
    return job


def _create_two_block_txt_job(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    order_id: str,
    file_id: str,
    user_id: str,
    source_text: str,
):
    original = storage.put_bytes(
        kind=StoredFileKind.ORIGINAL,
        file_name=f"{file_id}.txt",
        content_type="text/plain; charset=utf-8",
        content=source_text.encode("utf-8"),
    )
    source = storage.put_bytes(
        kind=StoredFileKind.INTERMEDIATE,
        file_name=f"{file_id}-unit-1.txt",
        content_type="text/plain; charset=utf-8",
        content=source_text.encode("utf-8"),
    )
    job = store.create_job(
        order_id=order_id,
        user_id=user_id,
        file_id=file_id,
        file_name=f"{file_id}.txt",
        document_kind="txt",
        source_language="en",
        target_language="uk",
        adapter_version=TXT_ADAPTER_VERSION,
        prompt_version="plain-v1",
        pricing_snapshot_id="pricing-1",
        source_object_key=original.object_key,
    )
    store.add_work_units(
        job.id,
        [
            WorkUnitPlan(
                sequence=1,
                source_block_ids=("txt:segment:1", "txt:segment:2"),
                source_text_hash=f"hash-{file_id}",
                prompt_tier="plain",
                source_language="en",
                target_language="uk",
                source_object_key=source.object_key,
            )
        ],
    )
    return job


def _create_epub_job_plan(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
):
    original = storage.put_bytes(
        kind=StoredFileKind.ORIGINAL,
        file_name="book.epub",
        content_type="application/epub+zip",
        content=_make_epub(
            {
                "OPS/front.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <h1>Contents</h1>
                    <p>Chapter 1</p>
                  </body>
                </html>
                """,
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <h1>Chapter 1</h1>
                    <p>* * *</p>
                    <p>First real paragraph.</p>
                    <p>Second real paragraph.</p>
                  </body>
                </html>
                """,
            },
        ),
    )
    return create_persistent_epub_job_plan(
        store=store,
        storage=storage,
        order_id="order-epub",
        user_id="telegram:42",
        source_object_key=original.object_key,
        file_name="book.epub",
        source_language="en",
        target_language="uk",
        max_fragment_chars=30,
    )


def _create_epub_surface_audit_job_plan(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    target_language: str,
    content: bytes | None = None,
):
    original = storage.put_bytes(
        kind=StoredFileKind.ORIGINAL,
        file_name="book.epub",
        content_type="application/epub+zip",
        content=content or _make_epub_with_surface_audit_content(),
    )
    return create_persistent_epub_job_plan(
        store=store,
        storage=storage,
        order_id="order-epub-surface",
        user_id="telegram:42",
        source_object_key=original.object_key,
        file_name="book.epub",
        source_language="en",
        target_language=target_language,
        max_fragment_chars=120,
        translation_mode="book_manuscript",
    )


def _complete_scheduled_units_by_block_id(
    store: SQLiteTranslationJobStore,
    job_id: str,
    translated_by_block_id: dict[str, str],
) -> None:
    while claim := store.claim_next_scheduled_work_unit(
        worker_id="worker-seed",
        lease_seconds=300,
        limits=SchedulerLimits(),
    ):
        work_unit = store.get_work_unit(claim.work_unit_id)
        if work_unit.job_id != job_id:
            raise AssertionError(f"Unexpected claimed job: {work_unit.job_id}")
        translated_text = "\n\n".join(
            translated_by_block_id[block_id]
            for block_id in work_unit.source_block_ids
        )
        store.complete_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            translated_text=translated_text,
            prompt_tokens=10,
            completion_tokens=5,
            cache_hit_tokens=0,
            cache_miss_tokens=10,
        )


def _pricing_rules() -> PricingRules:
    return PricingRules(
        deepseek_input_usd_per_million_tokens=0.28,
        expected_output_multiplier=1.2,
        service_markup_multiplier=3.0,
        minimum_price_usd=0.10,
    )


def _make_epub(xhtml_items: dict[str, str]) -> bytes:
    archive = BytesIO()
    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr("META-INF/container.xml", "<container />")
        for file_name, content in xhtml_items.items():
            epub.writestr(file_name, content)
    return archive.getvalue()


def _make_epub_with_surface_audit_content() -> bytes:
    archive = BytesIO()
    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """
            <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles><rootfile full-path="OPS/content.opf" /></rootfiles>
            </container>
            """,
        )
        epub.writestr(
            "OPS/content.opf",
            """
            <package xmlns="http://www.idpf.org/2007/opf"
                     xmlns:dc="http://purl.org/dc/elements/1.1/">
              <metadata>
                <dc:title>Original Book Title</dc:title>
                <dc:language>en</dc:language>
              </metadata>
              <manifest>
                <item id="chapter" href="chapter.xhtml"
                      media-type="application/xhtml+xml" />
                <item id="nav" href="nav.xhtml"
                      media-type="application/xhtml+xml" properties="nav" />
                <item id="ncx" href="toc.ncx"
                      media-type="application/x-dtbncx+xml" />
              </manifest>
              <spine toc="ncx"><itemref idref="chapter" /></spine>
            </package>
            """,
        )
        epub.writestr(
            "OPS/toc.ncx",
            """
            <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
              <docTitle><text>Original Book Title</text></docTitle>
              <navMap>
                <navPoint><navLabel><text>Chapter 1</text></navLabel></navPoint>
              </navMap>
            </ncx>
            """,
        )
        epub.writestr(
            "OPS/chapter.xhtml",
            """
            <html xmlns="http://www.w3.org/1999/xhtml">
              <head><title>Original Book Title</title></head>
              <body><h1>Chapter 1</h1><p>First paragraph.</p></body>
            </html>
            """,
        )
        epub.writestr(
            "OPS/nav.xhtml",
            """
            <html xmlns="http://www.w3.org/1999/xhtml"
                  xmlns:epub="http://www.idpf.org/2007/ops">
              <body>
                <nav epub:type="toc">
                  <ol><li><a href="chapter.xhtml">Book I</a></li></ol>
                </nav>
              </body>
            </html>
            """,
        )
    return archive.getvalue()


def _make_epub_with_surface_audit_frontmatter_noise() -> bytes:
    archive = BytesIO()
    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """
            <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles><rootfile full-path="OPS/content.opf" /></rootfiles>
            </container>
            """,
        )
        epub.writestr(
            "OPS/content.opf",
            """
            <package xmlns="http://www.idpf.org/2007/opf"
                     xmlns:dc="http://purl.org/dc/elements/1.1/">
              <metadata>
                <dc:title>Original Book Title</dc:title>
                <dc:language>en</dc:language>
              </metadata>
              <manifest>
                <item id="chapter" href="chapter.xhtml"
                      media-type="application/xhtml+xml" />
                <item id="nav" href="nav.xhtml"
                      media-type="application/xhtml+xml" properties="nav" />
                <item id="ncx" href="toc.ncx"
                      media-type="application/x-dtbncx+xml" />
              </manifest>
              <spine toc="ncx"><itemref idref="chapter" /></spine>
            </package>
            """,
        )
        epub.writestr(
            "OPS/toc.ncx",
            """
            <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
              <docTitle><text>Original Book Title</text></docTitle>
              <navMap>
                <navPoint><navLabel><text>Chapter 1</text></navLabel></navPoint>
              </navMap>
            </ncx>
            """,
        )
        epub.writestr(
            "OPS/chapter.xhtml",
            """
            <html xmlns="http://www.w3.org/1999/xhtml">
              <head><title>Original Book Title</title></head>
              <body><h1>Chapter 1</h1><p>First paragraph.</p></body>
            </html>
            """,
        )
        epub.writestr(
            "OPS/nav.xhtml",
            """
            <html xmlns="http://www.w3.org/1999/xhtml"
                  xmlns:epub="http://www.idpf.org/2007/ops">
              <body>
                <nav epub:type="toc">
                  <ol>
                    <li><a href="https://example.org">example.org</a></li>
                    <li>
                      <a href="https://example.org/ebooks/12345">
                        example.org/ebooks/12345
                      </a>
                    </li>
                    <li><a href="chapter.xhtml">Chapter 1</a></li>
                  </ol>
                </nav>
              </body>
            </html>
            """,
        )
    return archive.getvalue()


if __name__ == "__main__":
    unittest.main()
