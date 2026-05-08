import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    PersistentWorkUnit,
    PersistentWorkUnitStatus,
    SQLiteTranslationJobStore,
    WorkUnitPlan,
)
from translator_service.worker import (
    ProviderUsage,
    assemble_translated_text_result,
    run_next_persistent_work_unit,
    run_next_stored_text_work_unit,
    run_worker_tick,
)


class WorkerTest(unittest.TestCase):
    def test_translates_next_persistent_work_unit_and_stores_usage(self):
        store = self._store()
        job = _job_with_units(store)
        translator = RecordingTranslator()

        completed = run_next_persistent_work_unit(
            store=store,
            job_id=job.id,
            worker_id="worker-a",
            source_loader=lambda unit: _source_text_for(unit),
            translator=translator,
        )

        self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
        self.assertEqual(completed.sequence, 1)
        self.assertEqual(completed.translated_text, "[uk] First paragraph")
        self.assertEqual(completed.prompt_tokens, 21)
        self.assertEqual(completed.completion_tokens, 7)
        self.assertEqual(completed.cache_hit_tokens, 4)
        self.assertEqual(completed.cache_miss_tokens, 17)
        self.assertEqual(
            store.get_job(job.id).status,
            PersistentTranslationJobStatus.TRANSLATING,
        )
        self.assertEqual(
            translator.calls,
            [("First paragraph", "en", "uk")],
        )

    def test_returns_none_when_no_pending_work_units_exist(self):
        store = self._store()
        job = _job_with_units(store)
        first = store.claim_next_work_unit(job.id, worker_id="setup")
        store.complete_work_unit(
            first.id,
            translated_text="Done one",
            prompt_tokens=1,
            completion_tokens=1,
            cache_hit_tokens=0,
            cache_miss_tokens=1,
        )
        second = store.claim_next_work_unit(job.id, worker_id="setup")
        store.complete_work_unit(
            second.id,
            translated_text="Done two",
            prompt_tokens=1,
            completion_tokens=1,
            cache_hit_tokens=0,
            cache_miss_tokens=1,
        )

        result = run_next_persistent_work_unit(
            store=store,
            job_id=job.id,
            worker_id="worker-a",
            source_loader=lambda unit: _source_text_for(unit),
            translator=RecordingTranslator(),
        )

        self.assertIsNone(result)
        self.assertEqual(
            store.get_job(job.id).status,
            PersistentTranslationJobStatus.READY,
        )

    def test_marks_work_unit_failed_and_job_interrupted_when_translation_fails(self):
        store = self._store()
        job = _job_with_units(store)

        with self.assertLogs("translator_service.worker", level="ERROR"):
            failed = run_next_persistent_work_unit(
                store=store,
                job_id=job.id,
                worker_id="worker-a",
                source_loader=lambda unit: _source_text_for(unit),
                translator=FailingTranslator(),
            )

        self.assertEqual(failed.status, PersistentWorkUnitStatus.FAILED)
        self.assertEqual(failed.last_error, "provider read timeout")
        self.assertEqual(failed.retry_count, 1)
        self.assertEqual(
            store.get_job(job.id).status,
            PersistentTranslationJobStatus.INTERRUPTED,
        )

    def test_stored_worker_loads_source_text_from_object_storage(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            store = self._store()
            job = _job_with_stored_unit(store, source.object_key)
            translator = RecordingTranslator()

            completed = run_next_stored_text_work_unit(
                store=store,
                storage=storage,
                job_id=job.id,
                worker_id="worker-a",
                translator=translator,
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(completed.translated_text, "[uk] First paragraph")
            self.assertEqual(
                translator.calls,
                [("First paragraph", "en", "uk")],
            )

    def test_worker_tick_processes_one_unit_from_first_claimable_job(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            first_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="first.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            second_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="second.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Second paragraph",
            )
            store = self._store()
            first_job = _job_with_stored_unit(store, first_source.object_key)
            second_job = _job_with_stored_unit(store, second_source.object_key)
            translator = RecordingTranslator()

            processed = run_worker_tick(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=translator,
            )

            self.assertEqual(processed, 1)
            self.assertEqual(
                translator.calls,
                [("First paragraph", "en", "uk")],
            )
            self.assertEqual(
                store.list_work_units(first_job.id)[0].status,
                PersistentWorkUnitStatus.TRANSLATED,
            )
            self.assertEqual(
                store.list_work_units(second_job.id)[0].status,
                PersistentWorkUnitStatus.PENDING,
            )

    def test_worker_tick_skips_claimable_job_with_active_unit(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            blocked_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="blocked.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Blocked paragraph",
            )
            next_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="next.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Next paragraph",
            )
            store = self._store()
            blocked_job = _job_with_stored_unit(store, blocked_source.object_key)
            next_job = _job_with_stored_unit(store, next_source.object_key)
            store.claim_next_work_unit(blocked_job.id, worker_id="worker-busy")
            translator = RecordingTranslator()

            processed = run_worker_tick(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=translator,
            )

            self.assertEqual(processed, 1)
            self.assertEqual(translator.calls, [("Next paragraph", "en", "uk")])
            self.assertEqual(
                store.list_work_units(blocked_job.id)[0].status,
                PersistentWorkUnitStatus.TRANSLATING,
            )
            self.assertEqual(
                store.list_work_units(next_job.id)[0].status,
                PersistentWorkUnitStatus.TRANSLATED,
            )

    def test_worker_tick_reclaims_expired_active_unit_before_processing(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="stale.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Stale paragraph",
            )
            store = self._store()
            job = _job_with_stored_unit(store, source.object_key)
            stale = store.claim_next_work_unit(job.id, worker_id="worker-crashed")
            translator = RecordingTranslator()

            processed = run_worker_tick(
                store=store,
                storage=storage,
                worker_id="worker-a",
                translator=translator,
                lease_seconds=0,
            )

            completed = store.list_work_units(job.id)[0]
            self.assertEqual(processed, 1)
            self.assertEqual(completed.id, stale.id)
            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(completed.worker_id, "worker-a")
            self.assertEqual(translator.calls, [("Stale paragraph", "en", "uk")])

    def test_assembles_translated_text_result_into_object_storage(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = self._store()
            job = _job_with_units(store)
            first = store.claim_next_work_unit(job.id, worker_id="setup")
            store.complete_work_unit(
                first.id,
                translated_text="Перший абзац.",
                prompt_tokens=1,
                completion_tokens=1,
                cache_hit_tokens=0,
                cache_miss_tokens=1,
            )
            second = store.claim_next_work_unit(job.id, worker_id="setup")
            store.complete_work_unit(
                second.id,
                translated_text="Другий абзац.",
                prompt_tokens=1,
                completion_tokens=1,
                cache_hit_tokens=0,
                cache_miss_tokens=1,
            )

            stored = assemble_translated_text_result(
                store=store,
                storage=storage,
                job_id=job.id,
                file_name="book.uk.txt",
                partial=False,
            )

            persisted_job = store.get_job(job.id)
            self.assertEqual(stored.kind, StoredFileKind.FINAL)
            self.assertEqual(
                storage.get_bytes(stored.object_key).decode("utf-8"),
                "Перший абзац.\n\nДругий абзац.",
            )
            self.assertEqual(persisted_job.final_object_key, stored.object_key)

    def _store(self) -> SQLiteTranslationJobStore:
        store = SQLiteTranslationJobStore(":memory:")
        self.addCleanup(store.close)
        return store


class RecordingTranslator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.last_usage: ProviderUsage | None = None

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        self.calls.append((text, source_language, target_language))
        self.last_usage = ProviderUsage(
            prompt_tokens=21,
            completion_tokens=7,
            total_tokens=28,
            prompt_cache_hit_tokens=4,
            prompt_cache_miss_tokens=17,
        )
        return f"[{target_language}] {text}"


class FailingTranslator:
    last_usage = None

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        raise RuntimeError("provider read timeout")


def _job_with_units(store: SQLiteTranslationJobStore):
    job = store.create_job(
        order_id="order-1",
        user_id="user-42",
        file_id="file-1",
        file_name="book.epub",
        document_kind="epub",
        source_language="auto",
        target_language="uk",
        adapter_version="epub-v1",
        prompt_version="plain-v1",
        pricing_snapshot_id="pricing-1",
    )
    store.add_work_units(
        job.id,
        [
            WorkUnitPlan(
                sequence=1,
                source_block_ids=("chapter-1:p1",),
                source_text_hash="hash-1",
                prompt_tier="plain",
                source_language="en",
                target_language="uk",
            ),
            WorkUnitPlan(
                sequence=2,
                source_block_ids=("chapter-1:p2",),
                source_text_hash="hash-2",
                prompt_tier="plain",
                source_language="en",
                target_language="uk",
            ),
        ],
    )
    return job


def _job_with_stored_unit(store: SQLiteTranslationJobStore, source_object_key: str):
    job = store.create_job(
        order_id="order-1",
        user_id="user-42",
        file_id="file-1",
        file_name="book.epub",
        document_kind="epub",
        source_language="auto",
        target_language="uk",
        adapter_version="epub-v1",
        prompt_version="plain-v1",
        pricing_snapshot_id="pricing-1",
    )
    store.add_work_units(
        job.id,
        [
            WorkUnitPlan(
                sequence=1,
                source_block_ids=("chapter-1:p1",),
                source_text_hash="hash-1",
                prompt_tier="plain",
                source_language="en",
                target_language="uk",
                source_object_key=source_object_key,
            ),
        ],
    )
    return job


def _source_text_for(work_unit: PersistentWorkUnit) -> str:
    return {
        ("chapter-1:p1",): "First paragraph",
        ("chapter-1:p2",): "Second paragraph",
    }[work_unit.source_block_ids]


if __name__ == "__main__":
    unittest.main()
