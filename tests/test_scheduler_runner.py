import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.format_adapters import TXT_ADAPTER_VERSION
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    SQLiteTranslationJobStore,
    WorkUnitPlan,
)
from translator_service.scheduler import SchedulerLimits
from translator_service.scheduler_runner import assemble_due_jobs, run_scheduler_once
from translator_service.worker import ProviderUsage


class SchedulerRunnerTest(unittest.TestCase):
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


def _create_single_unit_txt_job(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    order_id: str,
    file_id: str,
    user_id: str = "telegram:42",
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


if __name__ == "__main__":
    unittest.main()
