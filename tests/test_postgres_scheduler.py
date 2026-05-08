import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.format_adapters import TXT_ADAPTER_VERSION
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    WorkUnitPlan,
)
from translator_service.postgres_scheduler import (
    PostgresSchedulerStore,
    initialize_postgres_scheduler_schema,
)
from translator_service.scheduler import SchedulerLimits, WorkUnitFailureKind


POSTGRES_DSN = os.getenv("TEST_POSTGRES_DSN")


class PostgresSchedulerContractTest(unittest.TestCase):
    def test_store_exposes_scheduler_runtime_methods(self):
        expected_methods = [
            "complete_claimed_work_unit",
            "fail_claimed_work_unit",
            "attach_job_output",
            "list_jobs_by_status",
            "mark_job_assembled",
            "list_work_unit_attempts",
            "list_scheduler_events",
            "record_worker_heartbeat",
            "get_worker_heartbeat",
            "recover_expired_leases",
        ]

        for method_name in expected_methods:
            self.assertTrue(
                callable(getattr(PostgresSchedulerStore, method_name, None)),
                method_name,
            )


@unittest.skipUnless(POSTGRES_DSN, "TEST_POSTGRES_DSN is not set")
class PostgresSchedulerStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = PostgresSchedulerStore(POSTGRES_DSN)
        initialize_postgres_scheduler_schema(self.store.connection)
        self.store.clear_for_tests()

    def tearDown(self):
        self.store.close()

    def _create_txt_job_with_unit(self, *, order_id="order-1", file_id="file-1"):
        job = self.store.create_job(
            order_id=order_id,
            user_id="telegram:42",
            file_id=file_id,
            file_name="notes.txt",
            document_kind="txt",
            source_language="en",
            target_language="uk",
            adapter_version=TXT_ADAPTER_VERSION,
            prompt_version="plain-v1",
            pricing_snapshot_id="pricing-1",
            source_object_key="intermediate/job-1/unit-1.txt",
        )
        self.store.add_work_units(
            job.id,
            [
                WorkUnitPlan(
                    sequence=1,
                    source_block_ids=("txt:0",),
                    source_text_hash="hash-1",
                    prompt_tier="plain",
                    source_language="en",
                    target_language="uk",
                    source_object_key="intermediate/job-1/unit-1.txt",
                )
            ],
        )
        return job

    def _create_txt_job_with_units(self, *, unit_count=3):
        job = self._create_txt_job_with_unit()
        if unit_count <= 1:
            return job
        self.store.add_work_units(
            job.id,
            [
                WorkUnitPlan(
                    sequence=sequence,
                    source_block_ids=(f"txt:{sequence - 1}",),
                    source_text_hash=f"hash-{sequence}",
                    prompt_tier="plain",
                    source_language="en",
                    target_language="uk",
                    source_object_key=f"intermediate/job-1/unit-{sequence}.txt",
                )
                for sequence in range(2, unit_count + 1)
            ],
        )
        return job

    def test_two_workers_do_not_claim_same_unit(self):
        self._create_txt_job_with_unit()

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_per_job_limit_of_one_preserves_unit_ordering(self):
        job = self._create_txt_job_with_units()

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(max_active_units_per_job=1),
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(max_active_units_per_job=1),
        )

        self.assertEqual(first.work_unit_id, f"{job.id}:unit-1")
        self.assertIsNone(second)

    def test_per_job_limit_allows_later_units_up_to_limit(self):
        job = self._create_txt_job_with_units()
        limits = SchedulerLimits(
            max_active_units_per_job=2,
            max_active_units_global=10,
        )

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )
        third = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-c",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.work_unit_id, f"{job.id}:unit-1")
        self.assertEqual(second.work_unit_id, f"{job.id}:unit-2")
        self.assertIsNone(third)

    def test_global_limit_blocks_second_job_sequentially(self):
        first_job = self._create_txt_job_with_unit(order_id="order-1", file_id="file-1")
        self._create_txt_job_with_unit(order_id="order-2", file_id="file-2")
        limits = SchedulerLimits(max_active_units_global=1)

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.job_id, first_job.id)
        self.assertIsNone(second)

    def test_legacy_failed_unit_is_retryable_for_claiming(self):
        job = self._create_txt_job_with_unit()
        with self.store.connection.transaction():
            self.store.connection.execute(
                """
                UPDATE work_units
                SET status = 'failed', available_at = now() - interval '1 second'
                WHERE id = %(work_unit_id)s
                """,
                {"work_unit_id": f"{job.id}:unit-1"},
            )

        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        self.assertIsNotNone(claim)
        self.assertEqual(claim.work_unit_id, f"{job.id}:unit-1")

    def test_complete_claimed_unit_moves_job_to_assembling(self):
        job = self._create_txt_job_with_unit()
        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        completed = self.store.complete_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            translated_text="[uk] First paragraph",
            prompt_tokens=10,
            completion_tokens=5,
            cache_hit_tokens=1,
            cache_miss_tokens=9,
        )

        persisted_job = self.store.get_job(job.id)
        events = self.store.list_scheduler_events(job.id)
        self.assertEqual(completed.status.value, "translated")
        self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.ASSEMBLING)
        self.assertEqual(events[-1].event_type, "work_unit_completed")

    def test_retryable_failure_records_attempt_and_releases_claim(self):
        job = self._create_txt_job_with_unit()
        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        failed = self.store.fail_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message="provider timeout",
            retry_base_delay_seconds=30,
            retry_max_delay_seconds=600,
        )

        attempts = self.store.list_work_unit_attempts(claim.work_unit_id)
        events = self.store.list_scheduler_events(job.id)
        self.assertEqual(failed.status.value, "failed_retryable")
        self.assertIsNone(failed.claim_token)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(events[-1].event_type, "work_unit_retry_scheduled")

    def test_stale_completion_with_wrong_token_leaves_claim_intact(self):
        self._create_txt_job_with_unit()
        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        with self.assertRaises(ValueError):
            self.store.complete_claimed_work_unit(
                work_unit_id=claim.work_unit_id,
                claim_token="wrong-token",
                translated_text="[uk] stale",
                prompt_tokens=1,
                completion_tokens=1,
                cache_hit_tokens=0,
                cache_miss_tokens=1,
            )

        work_unit = self.store.get_work_unit(claim.work_unit_id)
        self.assertEqual(work_unit.claim_token, claim.claim_token)
        self.assertEqual(work_unit.status.value, "translating")

    def test_worker_heartbeat_is_upserted(self):
        self.store.record_worker_heartbeat(
            worker_id="worker-a",
            worker_kind="translation",
            status="idle",
            active_job_id=None,
            active_work_unit_id=None,
        )
        self.store.record_worker_heartbeat(
            worker_id="worker-a",
            worker_kind="translation",
            status="busy",
            active_job_id="job-1",
            active_work_unit_id="job-1:unit-1",
        )

        heartbeat = self.store.get_worker_heartbeat("worker-a")

        self.assertEqual(heartbeat.worker_id, "worker-a")
        self.assertEqual(heartbeat.status, "busy")
        self.assertEqual(heartbeat.active_job_id, "job-1")

    def test_scheduler_runner_translates_and_assembles_txt_job(self):
        from translator_service.scheduler_runner import run_scheduler_once

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
            job = self.store.create_job(
                order_id="order-runtime-smoke",
                user_id="telegram:42",
                file_id="file-runtime-smoke",
                file_name="notes.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version=TXT_ADAPTER_VERSION,
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=original.object_key,
            )
            self.store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:segment:1",),
                        source_text_hash="hash-runtime-smoke",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=source.object_key,
                    )
                ],
            )

            summary = run_scheduler_once(
                store=self.store,
                storage=storage,
                worker_id="postgres-smoke-worker",
                translator=PostgresSmokeTranslator(),
                limits=SchedulerLimits(),
                lease_seconds=300,
            )

            persisted_job = self.store.get_job(job.id)
            events = self.store.list_scheduler_events(job.id)
            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(summary.assembled_jobs, 1)
            self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.READY)
            self.assertIsNotNone(persisted_job.final_object_key)
            self.assertEqual(
                storage.get_bytes(persisted_job.final_object_key).decode("utf-8"),
                "[uk] First paragraph",
            )
            self.assertEqual(
                [event.event_type for event in events],
                ["work_unit_claimed", "work_unit_completed"],
            )


class PostgresSmokeTranslator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.last_usage: _ProviderUsage | None = None

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
        translation_context=None,
    ) -> str:
        self.calls.append((text, source_language, target_language))
        self.last_usage = _ProviderUsage(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            prompt_cache_hit_tokens=2,
            prompt_cache_miss_tokens=8,
        )
        return f"[{target_language}] {text}"


class _ProviderUsage:
    def __init__(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        prompt_cache_hit_tokens: int,
        prompt_cache_miss_tokens: int,
    ) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.prompt_cache_hit_tokens = prompt_cache_hit_tokens
        self.prompt_cache_miss_tokens = prompt_cache_miss_tokens


if __name__ == "__main__":
    unittest.main()
