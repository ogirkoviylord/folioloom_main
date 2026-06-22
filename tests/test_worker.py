import json
import re
import threading
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from translator_service.admin.translation_logs import (
    build_effective_translation_run_archive,
    get_translation_run_details,
)
from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.glossary_candidate_reducer import GlossaryCandidateReducerCaps
from translator_service.glossary_persistent_runtime_resolver import (
    PersistentEpubGlossaryResolverConfig,
    build_persistent_epub_glossary_runtime_hook_resolver,
)
from translator_service.glossary_prepared_package import (
    GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
    GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
)
from translator_service.glossary_target_metadata_overlay import (
    GLOSSARY_TARGET_METADATA_OVERLAY_SCHEMA_VERSION,
)
from translator_service.output_contracts import format_translation_batch_contract
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    PersistentWorkUnit,
    PersistentWorkUnitStatus,
    SQLiteTranslationJobStore,
    WorkUnitPlan,
)
from translator_service.persistent_planner import (
    create_persistent_docx_job_plan,
    create_persistent_epub_job_plan,
)
from translator_service.provider_io_diagnostics import record_provider_io_exchange
from translator_service.translation_context import TranslationContextMemory
from translator_service.translation_run_logs import (
    TranslationRunLogger,
    TranslationRunMetadata,
)
from translator_service.translation_runner import GlossaryRuntimeAdapterHookConfig
from translator_service.worker import (
    ProviderUsage,
    _provider_io_diagnostic_sink,
    assemble_translated_text_result,
    effective_worker_parallel_units,
    open_scheduler_store,
    run_next_persistent_work_unit,
    run_next_scheduled_stored_text_work_unit,
    run_next_stored_text_work_unit,
    run_stored_text_job_parallel_until_idle,
    run_stored_text_job_until_idle,
    scheduler_limits_from_settings,
)


class WorkerTest(unittest.TestCase):
    def test_worker_main_passes_beta_safety_guard_to_scheduler_and_closes_it(self):
        from translator_service import worker
        from translator_service.scheduler import SchedulerLimits

        settings = SimpleNamespace(
            object_storage_root="objects",
            translation_run_log_root="run-logs",
            scheduler_lease_seconds=300,
            scheduler_retry_base_delay_seconds=30,
            scheduler_retry_max_delay_seconds=600,
            scheduler_poll_seconds=0,
            require_upload_scan=True,
        )
        store = _FakePostgresStore()
        guard = SimpleNamespace(closed=False)
        guard.close = lambda: setattr(guard, "closed", True)
        config = object()
        scheduler_calls = []

        def run_once(**kwargs):
            scheduler_calls.append(kwargs)

        with patch("translator_service.config.Settings", return_value=settings), patch(
            "translator_service.bot.runtime.build_deepseek_translator",
            return_value=object(),
        ), patch(
            "translator_service.bot.runtime.bot_runtime_config_from_settings",
            return_value=config,
        ) as config_from_settings, patch(
            "translator_service.bot.runtime.build_beta_safety_guard",
            return_value=guard,
        ) as build_guard, patch(
            "translator_service.worker.effective_worker_parallel_units",
            return_value=1,
        ), patch(
            "translator_service.worker.scheduler_limits_from_settings",
            return_value=SchedulerLimits(),
        ), patch(
            "translator_service.worker.open_scheduler_store",
            return_value=store,
        ), patch(
            "translator_service.scheduler_runner.run_scheduler_once",
            side_effect=run_once,
        ), patch(
            "translator_service.worker.time.sleep",
            side_effect=KeyboardInterrupt,
        ):
            with self.assertRaises(KeyboardInterrupt):
                worker.main()

        config_from_settings.assert_called_once_with(settings)
        build_guard.assert_called_once_with(config)
        self.assertEqual(scheduler_calls[0]["beta_safety_guard"], guard)
        self.assertEqual(scheduler_calls[0]["translation_run_log_root"], "run-logs")
        self.assertTrue(scheduler_calls[0]["require_upload_safety_policy"])
        self.assertTrue(guard.closed)
        self.assertTrue(store.closed)

    def test_worker_main_reruns_scheduler_after_wakeup_hint(self):
        from translator_service import worker
        from translator_service.scheduler import SchedulerLimits

        class WakeupNotifier:
            def __init__(self):
                self.waits = 0
                self.timeouts = []

            def wait_for_wakeup(self, *, timeout_seconds: float) -> bool:
                self.waits += 1
                self.timeouts.append(timeout_seconds)
                if self.waits == 1:
                    return True
                raise KeyboardInterrupt

        notifier = WakeupNotifier()
        settings = SimpleNamespace(
            object_storage_root="objects",
            translation_run_log_root="run-logs",
            scheduler_lease_seconds=300,
            scheduler_retry_base_delay_seconds=30,
            scheduler_retry_max_delay_seconds=600,
            scheduler_poll_seconds=30,
            require_upload_scan=True,
            scheduler_wakeup_notifier=notifier,
        )
        store = _FakePostgresStore()
        guard = SimpleNamespace(closed=False)
        guard.close = lambda: setattr(guard, "closed", True)
        scheduler_calls = []

        def run_once(**kwargs):
            scheduler_calls.append(kwargs)

        with patch("translator_service.config.Settings", return_value=settings), patch(
            "translator_service.bot.runtime.build_deepseek_translator",
            return_value=object(),
        ), patch(
            "translator_service.bot.runtime.bot_runtime_config_from_settings",
            return_value=object(),
        ), patch(
            "translator_service.bot.runtime.build_beta_safety_guard",
            return_value=guard,
        ), patch(
            "translator_service.worker.effective_worker_parallel_units",
            return_value=1,
        ), patch(
            "translator_service.worker.scheduler_limits_from_settings",
            return_value=SchedulerLimits(),
        ), patch(
            "translator_service.worker.open_scheduler_store",
            return_value=store,
        ), patch(
            "translator_service.scheduler_runner.run_scheduler_once",
            side_effect=run_once,
        ), patch(
            "translator_service.worker.time.sleep",
            side_effect=AssertionError("poll sleep should not run after wake-up"),
        ):
            with self.assertRaises(KeyboardInterrupt):
                worker.main()

        self.assertEqual(len(scheduler_calls), 2)
        self.assertIs(scheduler_calls[0]["store"], store)
        self.assertIs(scheduler_calls[1]["store"], store)
        self.assertEqual(notifier.timeouts, [30.0, 30.0])
        self.assertTrue(guard.closed)
        self.assertTrue(store.closed)

    def test_open_scheduler_store_returns_sqlite_store_for_sqlite_backend(self):
        from translator_service.config import Settings
        from translator_service.worker import open_scheduler_store

        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                persistent_jobs_db_path=str(Path(temp_dir) / "jobs.sqlite3"),
            )

            store = open_scheduler_store(settings)
            try:
                self.assertIsInstance(store, SQLiteTranslationJobStore)
            finally:
                store.close()

    def test_open_scheduler_store_uses_sqlite_backend(self):
        settings = _SchedulerSettings(
            scheduler_backend="sqlite",
            persistent_jobs_db_path=":memory:",
            postgres_dsn="postgresql://example",
        )

        store = open_scheduler_store(settings)
        self.addCleanup(store.close)

        self.assertIsInstance(store, SQLiteTranslationJobStore)

    def test_open_scheduler_store_uses_postgres_backend_and_initializes_schema(self):
        settings = _SchedulerSettings(
            scheduler_backend="postgres",
            persistent_jobs_db_path="ignored.sqlite3",
            postgres_dsn="postgresql://translator",
        )
        fake_store = _FakePostgresStore()

        with patch(
            "translator_service.postgres_scheduler.PostgresSchedulerStore",
            return_value=fake_store,
        ) as store_cls, patch(
            "translator_service.postgres_scheduler."
            "initialize_postgres_scheduler_schema"
        ) as initialize_schema:
            store = open_scheduler_store(settings)

        self.assertIs(store, fake_store)
        store_cls.assert_called_once_with("postgresql://translator")
        initialize_schema.assert_called_once_with(fake_store.connection)

    def test_open_scheduler_store_closes_postgres_store_when_schema_init_fails(self):
        settings = _SchedulerSettings(
            scheduler_backend="postgres",
            persistent_jobs_db_path="ignored.sqlite3",
            postgres_dsn="postgresql://translator",
        )
        fake_store = _FakePostgresStore()

        with patch(
            "translator_service.postgres_scheduler.PostgresSchedulerStore",
            return_value=fake_store,
        ), patch(
            "translator_service.postgres_scheduler."
            "initialize_postgres_scheduler_schema",
            side_effect=RuntimeError("schema init failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "schema init failed"):
                open_scheduler_store(settings)

        self.assertTrue(fake_store.closed)

    def test_open_scheduler_store_rejects_unknown_backend(self):
        settings = _SchedulerSettings(
            scheduler_backend="memory",
            persistent_jobs_db_path=":memory:",
            postgres_dsn="postgresql://example",
        )

        with self.assertRaisesRegex(
            ValueError,
            "Unsupported scheduler backend: memory",
        ):
            open_scheduler_store(settings)

    def test_effective_worker_parallel_units_is_capped_by_provider_capacity(self):
        from translator_service.config import Settings

        with patch.dict(
            "os.environ",
            {
                "TRANSLATION_MAX_PARALLEL_UNITS": "3",
                "DEEPSEEK_API_KEYS": "key-a,key-b",
                "DEEPSEEK_API_KEY": "",
                "DEEPSEEK_MAX_PARALLEL_PER_KEY": "1",
                "ADMIN_DB_PATH": ":memory:",
            },
        ):
            settings = Settings()
            effective_units = effective_worker_parallel_units(settings)

        self.assertEqual(effective_units, 2)

    def test_effective_worker_parallel_units_preserves_single_key_serial_capacity(self):
        from translator_service.config import Settings

        with patch.dict(
            "os.environ",
            {
                "TRANSLATION_MAX_PARALLEL_UNITS": "3",
                "DEEPSEEK_API_KEYS": "",
                "DEEPSEEK_API_KEY": "key-a",
                "DEEPSEEK_MAX_PARALLEL_PER_KEY": "1",
                "ADMIN_DB_PATH": ":memory:",
            },
        ):
            settings = Settings()
            effective_units = effective_worker_parallel_units(settings)

        self.assertEqual(effective_units, 1)

    def test_scheduler_limits_from_settings_uses_fairness_config(self):
        from translator_service.config import Settings

        with patch.dict(
            "os.environ",
            {
                "SCHEDULER_MAX_ACTIVE_UNITS_GLOBAL": "6",
                "SCHEDULER_MAX_ACTIVE_UNITS_PER_USER": "3",
                "SCHEDULER_MAX_ACTIVE_JOBS_PER_USER": "2",
                "SCHEDULER_MAX_ACTIVE_UNITS_PER_JOB": "4",
                "SCHEDULER_PRIORITY_AGING_SECONDS": "45",
            },
        ):
            settings = Settings()

        limits = scheduler_limits_from_settings(
            settings,
            effective_global_capacity=5,
        )

        self.assertEqual(limits.max_active_units_global, 5)
        self.assertEqual(limits.max_active_units_per_user, 3)
        self.assertEqual(limits.max_active_jobs_per_user, 2)
        self.assertEqual(limits.max_active_units_per_job, 4)
        self.assertEqual(limits.priority_aging_seconds, 45)

    def test_scheduler_limits_from_settings_preserves_provider_capacity_floor(self):
        from translator_service.config import Settings

        with patch.dict(
            "os.environ",
            {
                "SCHEDULER_MAX_ACTIVE_UNITS_GLOBAL": "6",
            },
        ):
            settings = Settings()

        limits = scheduler_limits_from_settings(
            settings,
            effective_global_capacity=0,
        )

        self.assertEqual(limits.max_active_units_global, 1)

    def test_translates_next_persistent_work_unit_and_stores_usage(self):
        store = self._store()
        job = _job_with_units(store)
        translator = RecordingTranslator()
        completed_callbacks = []

        completed = run_next_persistent_work_unit(
            store=store,
            job_id=job.id,
            worker_id="worker-a",
            source_loader=lambda unit: _source_text_for(unit),
            translator=translator,
            usage_completed_callback=completed_callbacks.append,
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
        self.assertEqual(completed_callbacks, [completed])

    def test_multiblock_work_unit_stores_translation_batch_contract(self):
        store = self._store()
        job = _job_with_stored_multi_block_unit(
            store,
            "intermediate/job-1/unit-1.txt",
            source_language="en",
            target_language="uk",
        )
        translator = RecordingTranslator()

        completed = run_next_persistent_work_unit(
            store=store,
            job_id=job.id,
            worker_id="worker-a",
            source_loader=lambda unit: "First paragraph\n\nSecond paragraph",
            translator=translator,
        )

        self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
        self.assertEqual(completed.sequence, 1)
        self.assertEqual(
            completed.translated_text,
            "<translation_batch>"
            '<translation_block id="0">[uk] First paragraph</translation_block>'
            '<translation_block id="1">[uk] Second paragraph</translation_block>'
            "</translation_batch>",
        )

    def test_epub_navigation_work_unit_uses_literary_heading_protection(self):
        store = self._store()
        job = store.create_job(
            order_id="order-1",
            user_id="user-42",
            file_id="file-1",
            file_name="book.epub",
            document_kind="epub",
            source_language="en",
            target_language="ru",
            adapter_version="epub-v1",
            prompt_version="plain-v1",
            pricing_snapshot_id="pricing-1",
        )
        store.add_work_units(
            job.id,
            [
                WorkUnitPlan(
                    sequence=1,
                    source_block_ids=(
                        "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0",
                    ),
                    source_text_hash="hash-1",
                    prompt_tier="plain",
                    source_language="en",
                    target_language="ru",
                ),
                WorkUnitPlan(
                    sequence=2,
                    source_block_ids=("epub:OPS/chapter.xhtml:0",),
                    source_text_hash="hash-2",
                    prompt_tier="plain",
                    source_language="en",
                    target_language="ru",
                ),
            ],
        )
        translator = RecordingTranslator()

        completed = run_next_persistent_work_unit(
            store=store,
            job_id=job.id,
            worker_id="worker-a",
            source_loader=lambda unit: {
                ("epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0",): (
                    "CHAPTER I API_TOKEN"
                ),
                ("epub:OPS/chapter.xhtml:0",): "BOOK ONE: 1805",
            }[unit.source_block_ids],
            translator=translator,
        )
        completed_body_heading = run_next_persistent_work_unit(
            store=store,
            job_id=job.id,
            worker_id="worker-a",
            source_loader=lambda unit: {
                ("epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0",): (
                    "CHAPTER I API_TOKEN"
                ),
                ("epub:OPS/chapter.xhtml:0",): "BOOK ONE: 1805",
            }[unit.source_block_ids],
            translator=translator,
        )

        provider_text = translator.calls[0][0]
        self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
        self.assertRegex(provider_text, r"CHAPTER ZXQPROTECTED\d+QXZ")
        self.assertNotIn("CHAPTER I API_TOKEN", provider_text)
        self.assertNotIn("API_TOKEN", provider_text)
        self.assertEqual(completed.translated_text, "[ru] CHAPTER I API_TOKEN")
        self.assertEqual(
            completed_body_heading.status,
            PersistentWorkUnitStatus.TRANSLATED,
        )
        body_heading_provider_text = translator.calls[2][0]
        self.assertIn("BOOK ONE: 1805", body_heading_provider_text)
        self.assertNotRegex(
            body_heading_provider_text,
            r"ZXQPROTECTED\d+QXZ ZXQPROTECTED\d+QXZ: 1805",
        )

    def test_single_block_epub_auxiliary_work_unit_retries_surface_residue(self):
        class SurfaceResidueRetryTranslator:
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
                if source_language == "auto":
                    return "Холодное утешение"
                return "COLD COMFORT"

        store = self._store()
        job = store.create_job(
            order_id="order-1",
            user_id="user-42",
            file_id="file-1",
            file_name="book.epub",
            document_kind="epub",
            source_language="en",
            target_language="ru",
            adapter_version="epub-v1",
            prompt_version="plain-v1",
            pricing_snapshot_id="pricing-1",
        )
        store.add_work_units(
            job.id,
            [
                WorkUnitPlan(
                    sequence=1,
                    source_block_ids=("epub:aux:ncx:OPS/toc.ncx:text:36",),
                    source_text_hash="hash-1",
                    prompt_tier="plain",
                    source_language="en",
                    target_language="ru",
                ),
            ],
        )
        translator = SurfaceResidueRetryTranslator()

        with self.assertLogs("translator_service.worker", level="INFO") as logs:
            completed = run_next_persistent_work_unit(
                store=store,
                job_id=job.id,
                worker_id="worker-a",
                source_loader=lambda unit: "COLD COMFORT",
                translator=translator,
            )

        self.assertIsNotNone(completed)
        self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
        self.assertEqual(completed.translated_text, "Холодное утешение")
        self.assertEqual([call[1] for call in translator.calls], ["en", "auto"])
        self.assertIn(
            "reason=epub_surface_navigation_heading_residue",
            "\n".join(logs.output),
        )

    def test_single_block_epub_legal_work_unit_retries_license_heading_residue(self):
        class LegalResidueRetryTranslator:
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
                    prompt_tokens=13,
                    completion_tokens=5,
                    total_tokens=18,
                    prompt_cache_hit_tokens=0,
                    prompt_cache_miss_tokens=13,
                )
                if source_language == "auto":
                    return "Лицензия Project Gutenberg"
                return "Project Gutenberg License"

        store = self._store()
        job = store.create_job(
            order_id="order-1",
            user_id="user-42",
            file_id="file-1",
            file_name="book.epub",
            document_kind="epub",
            source_language="en",
            target_language="ru",
            adapter_version="epub-v1",
            prompt_version="plain-v1",
            pricing_snapshot_id="pricing-1",
        )
        store.add_work_units(
            job.id,
            [
                WorkUnitPlan(
                    sequence=1,
                    source_block_ids=("epub:OPS/license.xhtml:0",),
                    source_text_hash="hash-1",
                    prompt_tier="plain",
                    source_language="en",
                    target_language="ru",
                ),
            ],
        )
        translator = LegalResidueRetryTranslator()

        with self.assertLogs("translator_service.worker", level="INFO") as logs:
            completed = run_next_persistent_work_unit(
                store=store,
                job_id=job.id,
                worker_id="worker-a",
                source_loader=lambda unit: "Project Gutenberg License",
                translator=translator,
            )

        self.assertIsNotNone(completed)
        if completed is None:
            self.fail("expected completed work unit")
        self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
        self.assertEqual(completed.translated_text, "Лицензия Project Gutenberg")
        self.assertEqual([call[1] for call in translator.calls], ["en", "auto"])
        self.assertIn(
            "reason=gutenberg_legal_backmatter_residue",
            "\n".join(logs.output),
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
            usage_completed_callback=lambda unit: self.fail(
                f"unexpected usage callback for {unit.id}"
            ),
        )

        self.assertIsNone(result)
        self.assertEqual(
            store.get_job(job.id).status,
            PersistentTranslationJobStatus.READY,
        )

    def test_marks_work_unit_failed_and_job_interrupted_when_translation_fails(self):
        store = self._store()
        job = _job_with_units(store)
        completed_callbacks = []

        with self.assertLogs("translator_service.worker", level="ERROR"):
            failed = run_next_persistent_work_unit(
                store=store,
                job_id=job.id,
                worker_id="worker-a",
                source_loader=lambda unit: _source_text_for(unit),
                translator=FailingTranslator(),
                usage_completed_callback=completed_callbacks.append,
            )

        self.assertEqual(failed.status, PersistentWorkUnitStatus.FAILED)
        self.assertEqual(failed.last_error, "provider read timeout")
        self.assertEqual(failed.retry_count, 1)
        self.assertEqual(
            store.get_job(job.id).status,
            PersistentTranslationJobStatus.INTERRUPTED,
        )
        self.assertEqual(completed_callbacks, [])

    def test_serial_worker_redacts_auth_material_in_persisted_failure(self):
        store = self._store()
        job = _job_with_units(store)

        with self.assertLogs("translator_service.worker", level="ERROR"):
            failed = run_next_persistent_work_unit(
                store=store,
                job_id=job.id,
                worker_id="worker-a",
                source_loader=lambda unit: _source_text_for(unit),
                translator=FailingTranslator(
                    "Provider failed: Authorization: Bearer *** "
                    "sk-abc123 api_key=secret secret_id=diagnostic-secret"
                ),
            )

        self.assertIsNotNone(failed)
        self.assertEqual(failed.status, PersistentWorkUnitStatus.FAILED)
        self.assertIn("[redacted]", failed.last_error or "")
        self.assertNotIn("sk-abc123", failed.last_error or "")
        self.assertNotIn("api_key=secret", failed.last_error or "")
        self.assertNotIn("secret_id=diagnostic-secret", failed.last_error or "")

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

    def test_stored_worker_rejects_quarantine_source_object(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.QUARANTINE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Do not translate this quarantined upload",
            )
            store = self._store()
            job = _job_with_stored_unit(store, source.object_key)
            translator = RecordingTranslator()

            with self.assertLogs("translator_service.worker", level="ERROR"):
                failed = run_next_stored_text_work_unit(
                    store=store,
                    storage=storage,
                    job_id=job.id,
                    worker_id="worker-a",
                    translator=translator,
                )

            self.assertEqual(failed.status, PersistentWorkUnitStatus.FAILED)
            self.assertEqual(
                failed.last_error,
                f"Work unit source object is quarantined: {failed.id}",
            )
            self.assertEqual(translator.calls, [])

    def test_stored_worker_rejects_unaccepted_source_object_when_gate_is_provided(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Do not translate this unaccepted upload",
            )
            store = self._store()
            job = _job_with_stored_unit(store, source.object_key)
            translator = RecordingTranslator()

            with self.assertLogs("translator_service.worker", level="ERROR"):
                failed = run_next_stored_text_work_unit(
                    store=store,
                    storage=storage,
                    job_id=job.id,
                    worker_id="worker-a",
                    translator=translator,
                    allowed_source_object_keys=frozenset(),
                )

            self.assertEqual(failed.status, PersistentWorkUnitStatus.FAILED)
            self.assertEqual(
                failed.last_error,
                f"Work unit source object is not accepted: {failed.id}",
            )
            self.assertEqual(translator.calls, [])

    def test_stored_worker_requires_upload_safety_policy_when_gate_is_enabled(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Do not translate without upload safety policy",
            )
            store = self._store()
            job = _job_with_stored_unit(store, source.object_key)
            translator = RecordingTranslator()

            with self.assertLogs("translator_service.worker", level="ERROR"):
                failed = run_next_stored_text_work_unit(
                    store=store,
                    storage=storage,
                    job_id=job.id,
                    worker_id="worker-a",
                    translator=translator,
                    require_upload_safety_policy=True,
                )

            self.assertEqual(failed.status, PersistentWorkUnitStatus.FAILED)
            self.assertEqual(
                failed.last_error,
                f"Job source object is not accepted by upload safety policy: {job.id}",
            )
            self.assertEqual(translator.calls, [])

    def test_stored_worker_accepts_upload_safety_policy_marker_when_gate_is_enabled(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.epub",
                content_type="application/epub+zip",
                content=b"accepted source",
            )
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            store = self._store()
            job = _job_with_stored_unit(
                store,
                source.object_key,
                source_object_key=original.object_key,
                translation_policy=json.dumps(
                    {
                        "upload_safety": {
                            "accepted_source_object_key": original.object_key,
                            "source_gate": "upload_safety_ledger",
                            "upload_safety_id": "upload-1",
                        }
                    }
                ),
            )
            translator = RecordingTranslator()

            completed = run_next_stored_text_work_unit(
                store=store,
                storage=storage,
                job_id=job.id,
                worker_id="worker-a",
                translator=translator,
                require_upload_safety_policy=True,
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(translator.calls, [("First paragraph", "en", "uk")])

    def test_stored_worker_threads_context_memory_between_fallback_blocks(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Alice whispered to Mark.\n\nMark opened the door.",
            )
            store = self._store()
            job = _job_with_stored_multi_block_unit(
                store,
                source.object_key,
                source_language="en",
                target_language="ru",
            )
            translator = ContextFallbackTranslator()

            completed = run_next_stored_text_work_unit(
                store=store,
                storage=storage,
                job_id=job.id,
                worker_id="worker-a",
                translator=translator,
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(
                completed.translated_text,
                format_translation_batch_contract(
                    ("Алиса прошептала Марку.", "Марк открыл дверь.")
                ),
            )
            self.assertGreaterEqual(len(translator.contexts), 3)
            self.assertEqual(translator.contexts[0], TranslationContextMemory())
            self.assertEqual(translator.contexts[1], TranslationContextMemory())
            assert translator.contexts[2] is not None
            self.assertTrue(
                any(
                    choice.source_text == "Alice" and choice.target_text == "Алиса"
                    for choice in translator.contexts[2].entity_choices
                )
            )

    def test_scheduled_worker_completes_claimed_unit_with_claim_token(self):
        from translator_service.scheduler import SchedulerLimits

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            store = self._store()
            _job_with_stored_unit(store, source.object_key)
            translator = RecordingTranslator()

            completed = run_next_scheduled_stored_text_work_unit(
                store=store,
                storage=storage,
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
                translator=translator,
            )

            self.assertEqual(completed.id, "job-1:unit-1")
            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertIsNone(completed.claim_token)
            self.assertIsNone(completed.lease_until)
            self.assertEqual(completed.translated_text, "[uk] First paragraph")

    def test_scheduled_worker_records_provider_io_diagnostics_in_run_log(self):
        from translator_service.scheduler import SchedulerLimits

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            run_logger = TranslationRunLogger.start(
                root=Path(temp_dir) / "run-logs",
                metadata=TranslationRunMetadata(
                    job_id="job-1",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                ),
            )
            store = self._store()
            _job_with_stored_unit(store, source.object_key)
            translator = ProviderIODiagnosticTranslator()

            completed = run_next_scheduled_stored_text_work_unit(
                store=store,
                storage=storage,
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
                translator=translator,
                translation_run_log_root=Path(temp_dir) / "run-logs",
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            provider_io_path = run_logger.run_dir / "provider_io_diagnostics.jsonl"
            self.assertTrue(provider_io_path.exists())
            record = json.loads(provider_io_path.read_text(encoding="utf-8"))
            self.assertEqual(record["job_id"], "job-1")
            self.assertEqual(record["work_unit_id"], "job-1:unit-1")
            self.assertEqual(record["sequence"], 1)
            self.assertEqual(record["request_body"]["text"], "request-body")
            self.assertEqual(record["response_body"]["text"], "response-body")

    def test_scheduled_worker_with_glossary_records_fallback_event_when_plan_missing(
        self,
    ):
        from translator_service.scheduler import SchedulerLimits

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Darcy returns.",
            )
            run_log_root = Path(temp_dir) / "run-logs"
            run_logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id="job-1",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=json.dumps(
                        {"glossary_mode": "with_glossary"},
                        ensure_ascii=False,
                    ),
                ),
            )
            store = self._store()
            _job_with_stored_unit(
                store,
                source.object_key,
                target_language="ru",
                translation_policy=json.dumps(
                    {"glossary_mode": "with_glossary"},
                    ensure_ascii=False,
                ),
            )
            translator = RecordingTranslator()

            completed = run_next_scheduled_stored_text_work_unit(
                store=store,
                storage=storage,
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
                translator=translator,
                translation_run_log_root=run_log_root,
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(translator.calls, [("Darcy returns.", "en", "ru")])
            event_lines = run_logger.run_dir.joinpath("events.jsonl").read_text(
                encoding="utf-8",
            )
            self.assertIn("glossary_runtime_adapter", event_lines)
            self.assertIn("runtime_glossary_data_unavailable", event_lines)
            self.assertIn("default_runtime_cache", event_lines)
            self.assertNotIn("<glossary_context", event_lines)
            self.assertNotIn("Darcy returns.", event_lines)

    def test_scheduled_worker_with_glossary_ready_hook_injects_and_bypasses_cache(
        self,
    ):
        from translator_service.scheduler import SchedulerLimits

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Darcy returns.",
            )
            run_log_root = Path(temp_dir) / "run-logs"
            run_logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id="job-1",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=json.dumps(
                        {"glossary_mode": "with_glossary"},
                        ensure_ascii=False,
                    ),
                ),
            )
            store = self._store()
            _job_with_stored_unit(
                store,
                source.object_key,
                target_language="ru",
                translation_policy=json.dumps(
                    {"glossary_mode": "with_glossary"},
                    ensure_ascii=False,
                ),
            )
            translator = RecordingTranslator()
            resolver_calls: list[tuple[str, int]] = []

            def hook_resolver(
                work_unit: PersistentWorkUnit,
            ) -> GlossaryRuntimeAdapterHookConfig:
                resolver_calls.append((work_unit.id, work_unit.sequence))
                return _ready_glossary_hook()

            completed = run_next_scheduled_stored_text_work_unit(
                store=store,
                storage=storage,
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
                translator=translator,
                translation_run_log_root=run_log_root,
                glossary_runtime_hook_resolver=hook_resolver,
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(resolver_calls, [("job-1:unit-1", 1)])
            self.assertEqual(len(translator.calls), 1)
            self.assertIn("<glossary_context", translator.calls[0][0])
            event_lines = run_logger.run_dir.joinpath("events.jsonl").read_text(
                encoding="utf-8",
            )
            self.assertIn("glossary_runtime_adapter", event_lines)
            self.assertIn("bypass_glossary_injected_cache", event_lines)
            self.assertIn("glossary-entry:v1:darcy", event_lines)
            self.assertNotIn("Darcy returns.", event_lines)

    def test_scheduled_worker_with_epub_glossary_resolver_injects_ready_context(
        self,
    ):
        from translator_service.scheduler import SchedulerLimits

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Darcy returns.",
            )
            run_log_root = Path(temp_dir) / "run-logs"
            run_logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id="job-1",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=json.dumps(
                        {"glossary_mode": "with_glossary"},
                        ensure_ascii=False,
                    ),
                ),
            )
            store = self._store()
            _job_with_stored_unit(
                store,
                source.object_key,
                target_language="ru",
                translation_policy=json.dumps(
                    {"glossary_mode": "with_glossary"},
                    ensure_ascii=False,
                ),
            )
            translator = RecordingTranslator()
            resolver = build_persistent_epub_glossary_runtime_hook_resolver(
                source_text_loader=lambda work_unit: storage.get_bytes(
                    work_unit.source_object_key
                ).decode("utf-8"),
                target_metadata_overlay_payload=_target_metadata_overlay_payload(),
                config=PersistentEpubGlossaryResolverConfig(
                    enabled=True,
                    owner_battle_test_enabled=True,
                    reducer_caps=GlossaryCandidateReducerCaps(
                        max_editor_entries=20,
                        max_diagnostic_entries=20,
                        max_estimated_editor_tokens=1000,
                        min_editor_score=1,
                        min_diagnostic_score=1,
                    ),
                ),
            )

            completed = run_next_scheduled_stored_text_work_unit(
                store=store,
                storage=storage,
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
                translator=translator,
                translation_run_log_root=run_log_root,
                glossary_runtime_hook_resolver=resolver,
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(len(translator.calls), 1)
            self.assertIn("<glossary_context", translator.calls[0][0])
            self.assertIn("Дарси", translator.calls[0][0])
            event_lines = run_logger.run_dir.joinpath("events.jsonl").read_text(
                encoding="utf-8",
            )
            self.assertIn("glossary_runtime_adapter", event_lines)
            self.assertIn("bypass_glossary_injected_cache", event_lines)
            selected_entry_ids = re.findall(
                r"glossary-scan:name:[a-f0-9]+",
                event_lines,
            )
            self.assertEqual(len(set(selected_entry_ids)), 1)
            self.assertNotIn("Darcy returns.", event_lines)
            self.assertNotIn("Дарси", event_lines)

    def test_scheduled_worker_with_prepared_package_in_policy_injects_context(
        self,
    ):
        from translator_service.scheduler import SchedulerLimits

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Darcy returns.",
            )
            policy = json.dumps(
                {
                    "glossary_mode": "with_glossary",
                    "prepared_glossary_package": _prepared_glossary_package(),
                },
                ensure_ascii=False,
            )
            run_log_root = Path(temp_dir) / "run-logs"
            run_logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id="job-1",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=policy,
                ),
            )
            store = self._store()
            _job_with_stored_unit(
                store,
                source.object_key,
                target_language="ru",
                translation_policy=policy,
            )
            translator = RecordingTranslator()

            completed = run_next_scheduled_stored_text_work_unit(
                store=store,
                storage=storage,
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
                translator=translator,
                translation_run_log_root=run_log_root,
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(len(translator.calls), 1)
            self.assertIn("<glossary_context", translator.calls[0][0])
            self.assertIn("Дарси", translator.calls[0][0])
            event_lines = run_logger.run_dir.joinpath("events.jsonl").read_text(
                encoding="utf-8",
            )
            self.assertIn("glossary_runtime_adapter", event_lines)
            self.assertIn("bypass_glossary_injected_cache", event_lines)
            self.assertIn('"prepared_package"', event_lines)
            self.assertIn('"status": "ready"', event_lines)
            self.assertNotIn("Darcy returns.", event_lines)
            self.assertNotIn("Дарси", event_lines)

    def test_scheduled_worker_with_prepared_package_ref_mismatch_injects_context(
        self,
    ):
        from translator_service.scheduler import SchedulerLimits

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Darcy returns.",
            )
            policy = json.dumps(
                {
                    "glossary_mode": "with_glossary",
                    "prepared_glossary_package": _prepared_glossary_package(
                        source_unit_refs=[99],
                        source_block_refs=["chapter-9:p9"],
                    ),
                },
                ensure_ascii=False,
            )
            run_log_root = Path(temp_dir) / "run-logs"
            run_logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id="job-1",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=policy,
                ),
            )
            store = self._store()
            _job_with_stored_unit(
                store,
                source.object_key,
                target_language="ru",
                translation_policy=policy,
            )
            translator = RecordingTranslator()

            completed = run_next_scheduled_stored_text_work_unit(
                store=store,
                storage=storage,
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
                translator=translator,
                translation_run_log_root=run_log_root,
            )
            events = [
                json.loads(line)
                for line in run_logger.run_dir.joinpath("events.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]

        self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
        self.assertEqual(len(translator.calls), 1)
        self.assertIn("<glossary_context", translator.calls[0][0])
        adapter_event = next(
            event
            for event in events
            if event["event_type"] == "glossary_runtime_adapter"
        )
        self.assertEqual(adapter_event["payload"]["status"], "ready")
        self.assertEqual(
            adapter_event["payload"]["cache_policy"]["behavior"],
            "bypass_glossary_injected_cache",
        )
        self.assertEqual(
            adapter_event["payload"]["prepared_package_runtime_bridge"][
                "source_ref_mismatch_count"
            ],
            1,
        )
        event_text = json.dumps(events, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("Darcy returns.", event_text)
        self.assertNotIn("Дарси", event_text)

    def test_prepared_package_rehearsal_archive_links_injection_metadata(self):
        from translator_service.scheduler import SchedulerLimits

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Darcy returns.",
            )
            policy = json.dumps(
                {
                    "glossary_mode": "with_glossary",
                    "prepared_glossary_package": _prepared_glossary_package(),
                },
                ensure_ascii=False,
            )
            run_log_root = Path(temp_dir) / "run-logs"
            run_logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id="job-1",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=policy,
                ),
            )
            store = self._store()
            _job_with_stored_unit(
                store,
                source.object_key,
                target_language="ru",
                translation_policy=policy,
            )
            translator = RecordingTranslator()

            completed = run_next_scheduled_stored_text_work_unit(
                store=store,
                storage=storage,
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
                translator=translator,
                translation_run_log_root=run_log_root,
            )
            details = get_translation_run_details(
                run_log_root,
                run_logger.run_dir.name,
            )
            self.assertIsNotNone(details)
            archive = build_effective_translation_run_archive(
                run_log_root,
                run_logger.run_dir.name,
                details=details,
            )

        self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
        self.assertEqual(len(translator.calls), 1)
        self.assertIn("<glossary_context", translator.calls[0][0])
        self.assertIn("Дарси", translator.calls[0][0])
        self.assertIsNotNone(archive)
        with ZipFile(BytesIO(archive.content)) as archive_zip:
            names = set(archive_zip.namelist())
            self.assertIn("glossary_runtime_diagnostics.json", names)
            diagnostics = json.loads(
                archive_zip.read("glossary_runtime_diagnostics.json")
            )
            archive_text = "\n".join(
                archive_zip.read(name).decode("utf-8", errors="ignore")
                for name in names
            )

        self.assertEqual(diagnostics["glossary_mode"], "with_glossary")
        self.assertEqual(diagnostics["summary"]["prepared_package_event_count"], 1)
        self.assertEqual(
            diagnostics["summary"]["prepared_package_statuses"],
            ["ready"],
        )
        self.assertEqual(
            diagnostics["summary"]["cache_policy_behaviors"],
            ["bypass_glossary_injected_cache"],
        )
        prepared_event = diagnostics["prepared_package_events"][0]
        self.assertEqual(prepared_event["package_id"], "prepared:worker-test:ru")
        self.assertEqual(prepared_event["ready_entry_count"], 1)
        self.assertEqual(
            prepared_event["resolver_linkage"]["runtime_status"],
            "ready",
        )
        self.assertEqual(
            prepared_event["resolver_linkage"]["fallback_reason"],
            "none",
        )
        self.assertTrue(prepared_event["resolver_linkage"]["prompt_context_included"])
        self.assertIn(
            "entry:darcy",
            "\n".join(diagnostics["summary"]["selected_entry_ids"]),
        )
        self.assertNotIn("Darcy returns.", archive_text)
        self.assertNotIn("RAW PROMPT", archive_text)
        self.assertNotIn("Bearer ", archive_text)
        self.assertNotIn("sk-", archive_text)

    def test_scheduled_worker_with_invalid_prepared_package_falls_back(self):
        from translator_service.scheduler import SchedulerLimits

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Darcy returns.",
            )
            policy = json.dumps(
                {
                    "glossary_mode": "with_glossary",
                    "prepared_glossary_package": _prepared_glossary_package(
                        target_language="uk",
                    ),
                },
                ensure_ascii=False,
            )
            run_log_root = Path(temp_dir) / "run-logs"
            run_logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id="job-1",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=policy,
                ),
            )
            store = self._store()
            _job_with_stored_unit(
                store,
                source.object_key,
                target_language="ru",
                translation_policy=policy,
            )
            translator = RecordingTranslator()

            completed = run_next_scheduled_stored_text_work_unit(
                store=store,
                storage=storage,
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
                translator=translator,
                translation_run_log_root=run_log_root,
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(translator.calls, [("Darcy returns.", "en", "ru")])
            event_lines = run_logger.run_dir.joinpath("events.jsonl").read_text(
                encoding="utf-8",
            )
            self.assertIn(
                "persistent_glossary_prepared_package_target_mismatch",
                event_lines,
            )
            self.assertIn("default_runtime_cache", event_lines)
            self.assertNotIn("<glossary_context", event_lines)
            self.assertNotIn("Darcy returns.", event_lines)
            self.assertNotIn("Дарси", event_lines)

    def test_scheduled_worker_with_malformed_prepared_package_falls_back(self):
        from translator_service.scheduler import SchedulerLimits

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Darcy returns.",
            )
            policy = json.dumps(
                {
                    "glossary_mode": "with_glossary",
                    "prepared_glossary_package": "not-a-package",
                },
                ensure_ascii=False,
            )
            run_log_root = Path(temp_dir) / "run-logs"
            run_logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id="job-1",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=policy,
                ),
            )
            store = self._store()
            _job_with_stored_unit(
                store,
                source.object_key,
                target_language="ru",
                translation_policy=policy,
            )
            translator = RecordingTranslator()

            completed = run_next_scheduled_stored_text_work_unit(
                store=store,
                storage=storage,
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
                translator=translator,
                translation_run_log_root=run_log_root,
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(translator.calls, [("Darcy returns.", "en", "ru")])
            event_lines = run_logger.run_dir.joinpath("events.jsonl").read_text(
                encoding="utf-8",
            )
            self.assertIn("persistent_glossary_prepared_package_invalid", event_lines)
            self.assertIn("prepared_glossary_package_invalid", event_lines)
            self.assertIn("default_runtime_cache", event_lines)
            self.assertNotIn("<glossary_context", event_lines)
            self.assertNotIn("Darcy returns.", event_lines)

    def test_scheduled_worker_without_glossary_blocks_global_hook_and_sidecar_event(
        self,
    ):
        from translator_service.scheduler import SchedulerLimits

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Darcy returns.",
            )
            run_log_root = Path(temp_dir) / "run-logs"
            run_logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id="job-1",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=json.dumps(
                        {"glossary_mode": "without_glossary"},
                        ensure_ascii=False,
                    ),
                ),
            )
            store = self._store()
            _job_with_stored_unit(
                store,
                source.object_key,
                target_language="ru",
                translation_policy=json.dumps(
                    {"glossary_mode": "without_glossary"},
                    ensure_ascii=False,
                ),
            )
            translator = RecordingTranslator()

            completed = run_next_scheduled_stored_text_work_unit(
                store=store,
                storage=storage,
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
                translator=translator,
                translation_run_log_root=run_log_root,
                glossary_runtime_hook=_ready_glossary_hook(),
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(translator.calls, [("Darcy returns.", "en", "ru")])
            event_lines = run_logger.run_dir.joinpath("events.jsonl").read_text(
                encoding="utf-8",
            )
            self.assertNotIn("glossary_runtime_adapter", event_lines)
            self.assertNotIn("<glossary_context", event_lines)

    def test_scheduled_worker_without_glossary_blocks_prepared_package(self):
        from translator_service.scheduler import SchedulerLimits

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Darcy returns.",
            )
            policy = json.dumps(
                {
                    "glossary_mode": "without_glossary",
                    "prepared_glossary_package": _prepared_glossary_package(),
                },
                ensure_ascii=False,
            )
            run_log_root = Path(temp_dir) / "run-logs"
            run_logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id="job-1",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=policy,
                ),
            )
            store = self._store()
            _job_with_stored_unit(
                store,
                source.object_key,
                target_language="ru",
                translation_policy=policy,
            )
            translator = RecordingTranslator()

            completed = run_next_scheduled_stored_text_work_unit(
                store=store,
                storage=storage,
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
                translator=translator,
                translation_run_log_root=run_log_root,
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(translator.calls, [("Darcy returns.", "en", "ru")])
            event_lines = run_logger.run_dir.joinpath("events.jsonl").read_text(
                encoding="utf-8",
            )
            self.assertNotIn("glossary_runtime_adapter", event_lines)
            self.assertNotIn("<glossary_context", event_lines)

    def test_in_process_parallel_worker_records_provider_io_diagnostics(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalObjectStorage(root / "objects")
            first_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            second_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-2.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Second paragraph",
            )
            run_logger = TranslationRunLogger.start(
                root=root / "run-logs",
                metadata=TranslationRunMetadata(
                    job_id="job-1",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                ),
            )
            store = self._store()
            job = _job_with_two_stored_units(
                store,
                first_source.object_key,
                second_source.object_key,
            )

            summary = run_stored_text_job_parallel_until_idle(
                store=store,
                storage=storage,
                job_id=job.id,
                worker_id="worker",
                translator=ProviderIODiagnosticTranslator(),
                max_parallel_units=2,
                provider_io_diagnostic_sink=_provider_io_diagnostic_sink(
                    root / "run-logs",
                    job_id=job.id,
                ),
            )

            self.assertEqual(summary.job_status, PersistentTranslationJobStatus.READY)
            provider_io_path = run_logger.run_dir / "provider_io_diagnostics.jsonl"
            records = [
                json.loads(line)
                for line in provider_io_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                sorted(record["sequence"] for record in records),
                [1, 2],
            )
            self.assertEqual(
                {record["request_body"]["text"] for record in records},
                {"request-body"},
            )
            self.assertEqual(
                {record["response_body"]["text"] for record in records},
                {"response-body"},
            )

    def test_scheduled_worker_ignores_stale_claim_completion(self):
        from translator_service.scheduler import SchedulerLimits

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
            translator = StaleCompletionTranslator(store, job.id)

            with self.assertLogs("translator_service.worker", level="WARNING"):
                completed = run_next_scheduled_stored_text_work_unit(
                    store=store,
                    storage=storage,
                    worker_id="worker-a",
                    lease_seconds=300,
                    limits=SchedulerLimits(),
                    translator=translator,
                    usage_completed_callback=lambda unit: self.fail(
                        f"unexpected usage callback for {unit.id}"
                    ),
                )

            self.assertIsNone(completed)
            self.assertEqual(translator.calls, [("First paragraph", "en", "uk")])
            self.assertEqual(
                store.get_job(job.id).status,
                PersistentTranslationJobStatus.ASSEMBLING,
            )

    def test_scheduled_worker_maps_missing_source_key_to_unsupported_contract(self):
        from translator_service.scheduler import SchedulerLimits, WorkUnitFailureKind

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            store = self._store()
            job = _job_with_units(store)
            translator = RecordingTranslator()

            failed = run_next_scheduled_stored_text_work_unit(
                store=store,
                storage=storage,
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
                translator=translator,
            )

            attempts = store.list_work_unit_attempts(failed.id)
            self.assertEqual(failed.status, PersistentWorkUnitStatus.FAILED_TERMINAL)
            self.assertEqual(
                failed.last_error,
                f"Work unit has no source object key: {failed.id}",
            )
            self.assertEqual(
                store.get_job(job.id).status,
                PersistentTranslationJobStatus.INTERRUPTED,
            )
            self.assertEqual(translator.calls, [])
            self.assertEqual(len(attempts), 1)
            self.assertEqual(
                attempts[0].error_code,
                WorkUnitFailureKind.UNSUPPORTED_CONTRACT.value,
            )

    def test_scheduled_worker_maps_translator_value_error_to_retryable_provider(self):
        from translator_service.scheduler import SchedulerLimits, WorkUnitFailureKind

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

            with self.assertLogs("translator_service.worker", level="ERROR") as logs:
                failed = run_next_scheduled_stored_text_work_unit(
                    store=store,
                    storage=storage,
                    worker_id="worker-a",
                    lease_seconds=300,
                    limits=SchedulerLimits(),
                    translator=ProviderValidationErrorTranslator(),
                )

            attempts = store.list_work_unit_attempts(failed.id)
            self.assertEqual(failed.status, PersistentWorkUnitStatus.FAILED_RETRYABLE)
            self.assertEqual(
                failed.last_error,
                "retryable provider failure",
            )
            self.assertEqual(
                store.get_job(job.id).status,
                PersistentTranslationJobStatus.TRANSLATING,
            )
            self.assertEqual(len(attempts), 1)
            self.assertEqual(
                attempts[0].error_message,
                "retryable provider failure",
            )
            self.assertEqual(
                attempts[0].error_code,
                WorkUnitFailureKind.RETRYABLE_PROVIDER.value,
            )
            log_output = "\n".join(logs.output)
            self.assertNotIn("provider validation failed", log_output)
            self.assertNotIn("ValueError", log_output)
            self.assertNotIn("Traceback", log_output)

    def test_scheduled_worker_records_specific_provider_failure_diagnostic(self):
        from translator_service.deepseek_client import DeepSeekApiError
        from translator_service.deepseek_key_pool import (
            DeepSeekChannelConfig,
            DeepSeekKeyPoolTranslator,
        )
        from translator_service.scheduler import SchedulerLimits

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Private source paragraph",
            )
            store = self._store()
            job = _job_with_stored_unit(store, source.object_key)
            translator = DeepSeekKeyPoolTranslator(
                channels=[
                    DeepSeekChannelConfig(
                        api_key="sk-private-provider-key",
                        label="primary",
                    )
                ],
                client_factory=_DeepSeekErrorClientFactory(
                    DeepSeekApiError(
                        "DeepSeek API returned HTTP 503: unavailable "
                        "for sk-private-provider-key"
                    )
                ),
                cooldown_seconds=30,
                clock=lambda: 100.0,
            )

            failed = run_next_scheduled_stored_text_work_unit(
                store=store,
                storage=storage,
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
                translator=translator,
                retry_base_delay_seconds=60,
                retry_max_delay_seconds=60,
            )

            attempts = store.list_work_unit_attempts(failed.id)
            events = [
                json.loads(event.payload_json)
                for event in store.list_scheduler_events(job.id)
            ]
            events_text = json.dumps(events, sort_keys=True)

            self.assertEqual(attempts[0].error_code, "unavailable_5xx")
            self.assertEqual(
                attempts[0].error_message,
                "provider failure: unavailable_5xx",
            )
            self.assertEqual(
                events[-1]["provider_failure"]["failure_category"],
                "unavailable_5xx",
            )
            self.assertEqual(
                events[-1]["provider_failure"]["http_status_bucket"],
                "5xx",
            )
            self.assertEqual(events[-1]["provider_failure"]["provider_id"], "deepseek")
            self.assertIn(
                "channel_fingerprint",
                events[-1]["provider_failure"]["channel"],
            )
            self.assertNotIn("Private source paragraph", failed.last_error or "")
            self.assertNotIn("Private source paragraph", events_text)
            self.assertNotIn("sk-private-provider-key", events_text)

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

    def test_runs_all_stored_docx_units_until_job_is_ready(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = self._store()
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
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
            )
            plan = create_persistent_docx_job_plan(
                store=store,
                storage=storage,
                order_id="order-docx",
                user_id="user-42",
                source_object_key=original.object_key,
                file_name="book.docx",
                source_language="en",
                target_language="uk",
                max_fragment_chars=1_000,
            )
            translator = RecordingTranslator()
            progress_events = []
            lifecycle_events = []
            completed_callbacks = []

            summary = run_stored_text_job_until_idle(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                worker_id="worker-a",
                translator=translator,
                work_unit_started_callback=lambda unit: lifecycle_events.append(
                    ("started", unit.sequence)
                ),
                progress_callback=progress_events.append,
                usage_completed_callback=completed_callbacks.append,
            )

            persisted_units = store.list_work_units(plan.job.id)
            self.assertEqual(summary.translated_units, 3)
            self.assertEqual(summary.failed_work_unit_id, None)
            self.assertEqual(summary.job_status, PersistentTranslationJobStatus.READY)
            self.assertEqual(summary.total_tokens, 84)
            self.assertEqual(len(progress_events), 3)
            self.assertEqual(
                lifecycle_events,
                [("started", 1), ("started", 2), ("started", 3)],
            )
            self.assertEqual(
                [unit.sequence for unit in completed_callbacks],
                [1, 2, 3],
            )
            self.assertEqual(
                [unit.translated_text for unit in persisted_units],
                [
                    "[uk] Intro paragraph.",
                    format_translation_batch_contract(
                        ("[uk] Source", "[uk] Target")
                    ),
                    "[uk] Outro paragraph.",
                ],
            )
            self.assertIn("<translation_batch>", translator.calls[1][0])
            self.assertEqual(
                [call[1:] for call in translator.calls],
                [("en", "uk"), ("en", "uk"), ("en", "uk")],
            )

    def test_stored_worker_retries_cjk_and_dutch_left_untranslated_in_batch(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=(
                    "English + Dutch: The afspraak is scheduled for dinsdag "
                    "om kwart over drie.\n\n"
                    "CJK: The label 東京-大阪 should remain readable; "
                    "Chinese example: 请保留变量 {{变量}}."
                ).encode(),
            )
            store = self._store()
            job = _job_with_stored_multi_block_unit(
                store,
                source.object_key,
                source_language="en",
                target_language="ru",
            )
            translator = SecondaryLanguageRetryTranslator()

            completed = run_next_stored_text_work_unit(
                store=store,
                storage=storage,
                job_id=job.id,
                worker_id="worker-a",
                translator=translator,
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(
                completed.translated_text,
                format_translation_batch_contract(
                    (
                        "Английский + нидерландский: Встреча назначена на вторник "
                        "в четверть четвертого.",
                        "CJK: Метка 東京-大阪 должна оставаться читаемой; "
                        "пример на китайском: сохраните переменную {{变量}}.",
                    )
                ),
            )
            self.assertEqual(
                [call[1] for call in translator.calls],
                ["en", "auto", "auto"],
            )

    def test_stored_worker_retries_lost_mixed_language_label_in_batch(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=(
                    b"English + Dutch: The afspraak is scheduled for dinsdag "
                    b"om kwart over drie.\n\n"
                    b"Plain English sentence."
                ),
            )
            store = self._store()
            job = _job_with_stored_multi_block_unit(
                store,
                source.object_key,
                source_language="en",
                target_language="ru",
            )
            translator = MixedLanguageLabelRetryTranslator()

            completed = run_next_stored_text_work_unit(
                store=store,
                storage=storage,
                job_id=job.id,
                worker_id="worker-a",
                translator=translator,
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(
                completed.translated_text,
                format_translation_batch_contract(
                    (
                        "Английский + нидерландский: встреча назначена на вторник "
                        "в четверть четвертого.",
                        "Обычное английское предложение.",
                    )
                ),
            )
            self.assertEqual(
                [call[1] for call in translator.calls],
                ["en", "auto"],
            )

    def test_stored_worker_retries_single_block_with_untranslated_ukrainian(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=(
                    "English + Ukrainian: Please translate this sentence, "
                    "але не ламай український текст у середині."
                ).encode(),
            )
            store = self._store()
            job = _job_with_stored_unit(
                store,
                source.object_key,
                source_language="en",
                target_language="ru",
            )
            translator = UkrainianRetryTranslator()

            completed = run_next_stored_text_work_unit(
                store=store,
                storage=storage,
                job_id=job.id,
                worker_id="worker-a",
                translator=translator,
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(
                completed.translated_text,
                "Английский + украинский: пожалуйста, переведите это предложение, "
                "но не ломайте украинский текст внутри.",
            )
            self.assertEqual(
                [call[1] for call in translator.calls],
                ["en", "auto"],
            )

    def test_stored_worker_retries_single_block_with_english_residue_for_russian(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"On the morning the streets of Vienna were lively.",
            )
            store = self._store()
            job = _job_with_stored_unit(
                store,
                source.object_key,
                source_language="en",
                target_language="ru",
            )
            translator = EnglishResidueRetryTranslator()

            completed = run_next_stored_text_work_unit(
                store=store,
                storage=storage,
                job_id=job.id,
                worker_id="worker-a",
                translator=translator,
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(
                completed.translated_text,
                "Утром улицы Вены оживляло шествие.",
            )
            self.assertEqual(
                [call[1] for call in translator.calls],
                ["en", "auto"],
            )

    def test_stored_worker_retries_single_block_with_untranslated_rtl(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=(
                    "עברית / العربية mixed with English 12345 and token {{RTL_TOKEN}}. "
                    "Direction and glyphs should survive."
                ).encode(),
            )
            store = self._store()
            job = _job_with_stored_unit(
                store,
                source.object_key,
                source_language="en",
                target_language="ru",
            )
            translator = RtlRetryTranslator()

            completed = run_next_stored_text_work_unit(
                store=store,
                storage=storage,
                job_id=job.id,
                worker_id="worker-a",
                translator=translator,
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertIn("Иврит / арабский", completed.translated_text)
            self.assertNotIn("עברית", completed.translated_text)
            self.assertNotIn("العربية", completed.translated_text)
            self.assertEqual(
                [call[1] for call in translator.calls],
                ["en", "auto"],
            )

    def test_stored_worker_cleans_inline_formatting_artifacts(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=(
                    b"This paragraph has subscript H2O and superscript x2."
                ),
            )
            store = self._store()
            job = _job_with_stored_unit(
                store,
                source.object_key,
                source_language="en",
                target_language="ru",
            )
            translator = InlineArtifactTranslator()

            completed = run_next_stored_text_work_unit(
                store=store,
                storage=storage,
                job_id=job.id,
                worker_id="worker-a",
                translator=translator,
            )

            self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
            self.assertEqual(
                completed.translated_text,
                "В этом абзаце нижний индекс H2O и верхний индекс x2.",
            )

    def test_runs_all_stored_epub_units_until_job_is_ready(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = self._store()
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
                            <p>First body paragraph.</p>
                            <p>Second body paragraph.</p>
                          </body>
                        </html>
                        """,
                    }
                ),
            )
            plan = create_persistent_epub_job_plan(
                store=store,
                storage=storage,
                order_id="order-epub",
                user_id="user-42",
                source_object_key=original.object_key,
                file_name="book.epub",
                source_language="en",
                target_language="uk",
                max_fragment_chars=1_000,
            )
            translator = RecordingTranslator()

            summary = run_stored_text_job_until_idle(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                worker_id="worker-a",
                translator=translator,
            )

            persisted_units = store.list_work_units(plan.job.id)
            self.assertEqual(summary.translated_units, 3)
            self.assertEqual(summary.job_status, PersistentTranslationJobStatus.READY)
            self.assertEqual(
                [unit.translated_text for unit in persisted_units],
                [
                    format_translation_batch_contract(
                        (
                            "[uk] First body paragraph.",
                            "[uk] Second body paragraph.",
                        )
                    ),
                    "[uk] Contents",
                    "[uk] Chapter 1",
                ],
            )
            self.assertIn("<translation_batch>", translator.calls[0][0])
            self.assertEqual(
                [call[1:] for call in translator.calls],
                [
                    ("en", "uk"),
                    ("en", "uk"),
                    ("auto", "uk"),
                    ("en", "uk"),
                    ("auto", "uk"),
                ],
            )

    def test_persistent_epub_units_receive_job_level_context_memory(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = self._store()
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.epub",
                content_type="application/epub+zip",
                content=_make_epub(
                    {
                        "OPS/chapter.xhtml": """
                        <html xmlns="http://www.w3.org/1999/xhtml">
                          <body>
                            <p>Alice whispered to Mark.</p>
                            <p>Mark opened the door.</p>
                          </body>
                        </html>
                        """,
                    }
                ),
            )
            plan = create_persistent_epub_job_plan(
                store=store,
                storage=storage,
                order_id="order-epub-context",
                user_id="user-42",
                source_object_key=original.object_key,
                file_name="book.epub",
                source_language="en",
                target_language="ru",
                max_fragment_chars=30,
            )
            translator = ContextFallbackTranslator()

            summary = run_stored_text_job_until_idle(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                worker_id="worker-a",
                translator=translator,
            )

            self.assertEqual(summary.translated_units, 2)
            self.assertGreaterEqual(len(translator.contexts), 2)
            second_context = translator.contexts[1]
            assert second_context is not None
            self.assertTrue(
                any(
                    choice.source_text == "Alice" and choice.target_text == "Алиса"
                    for choice in second_context.entity_choices
                )
            )
            self.assertTrue(
                any(
                    choice.source_text == "Mark" and choice.target_text == "Марк"
                    for choice in second_context.entity_choices
                )
            )

    def test_runs_stored_units_in_parallel_when_allowed(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            first_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            second_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-2.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Second paragraph",
            )
            store = self._store()
            job = _job_with_two_stored_units(
                store,
                first_source.object_key,
                second_source.object_key,
            )
            translator = BlockingParallelTranslator(expected_parallel_calls=2)
            started_sequences: list[int] = []
            completed_callbacks = []

            summary = run_stored_text_job_parallel_until_idle(
                store=store,
                storage=storage,
                job_id=job.id,
                worker_id="worker",
                translator=translator,
                max_parallel_units=2,
                work_unit_started_callback=lambda unit: started_sequences.append(
                    unit.sequence
                ),
                usage_completed_callback=completed_callbacks.append,
            )

            persisted_units = store.list_work_units(job.id)
            self.assertEqual(summary.job_status, PersistentTranslationJobStatus.READY)
            self.assertEqual(summary.translated_units, 2)
            self.assertEqual(translator.max_active_calls, 2)
            self.assertEqual(sorted(started_sequences), [1, 2])
            self.assertEqual(
                sorted(unit.sequence for unit in completed_callbacks),
                [1, 2],
            )
            self.assertEqual(
                [unit.translated_text for unit in persisted_units],
                ["[uk] First paragraph", "[uk] Second paragraph"],
            )

    def test_parallel_worker_redacts_auth_material_in_persisted_failure(self):
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

            with self.assertLogs("translator_service.worker", level="ERROR"):
                summary = run_stored_text_job_parallel_until_idle(
                    store=store,
                    storage=storage,
                    job_id=job.id,
                    worker_id="worker",
                    translator=FailingTranslator(
                        "Provider failed: Authorization: Bearer *** "
                        "sk-abc123 api_key=secret secret_id=diagnostic-secret"
                    ),
                    max_parallel_units=2,
                )

            failed_unit = store.list_work_units(job.id)[0]
            self.assertEqual(summary.failed_work_unit_id, failed_unit.id)
            self.assertEqual(failed_unit.status, PersistentWorkUnitStatus.FAILED)
            self.assertIn("[redacted]", failed_unit.last_error or "")
            self.assertNotIn("sk-abc123", failed_unit.last_error or "")
            self.assertNotIn("api_key=secret", failed_unit.last_error or "")
            self.assertNotIn(
                "secret_id=diagnostic-secret",
                failed_unit.last_error or "",
            )

    def test_parallel_usage_callback_runs_before_progress_callback_failure(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            first_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            second_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-2.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Second paragraph",
            )
            store = self._store()
            job = _job_with_two_stored_units(
                store,
                first_source.object_key,
                second_source.object_key,
            )
            translator = BlockingParallelTranslator(expected_parallel_calls=2)
            usage_callbacks = []

            def fail_progress(_progress):
                raise RuntimeError("progress sink failed")

            with self.assertRaisesRegex(RuntimeError, "progress sink failed"):
                run_stored_text_job_parallel_until_idle(
                    store=store,
                    storage=storage,
                    job_id=job.id,
                    worker_id="worker",
                    translator=translator,
                    max_parallel_units=2,
                    progress_callback=fail_progress,
                    usage_completed_callback=usage_callbacks.append,
                )

            self.assertGreaterEqual(len(usage_callbacks), 1)
            self.assertTrue(
                all(
                    unit.status is PersistentWorkUnitStatus.TRANSLATED
                    for unit in usage_callbacks
                )
            )

    def test_stored_job_executor_stops_on_failed_work_unit(self):
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

            with self.assertLogs("translator_service.worker", level="ERROR"):
                summary = run_stored_text_job_until_idle(
                    store=store,
                    storage=storage,
                    job_id=job.id,
                    worker_id="worker-a",
                    translator=FailingTranslator(),
                )

            failed_unit = store.list_work_units(job.id)[0]
            self.assertEqual(summary.translated_units, 0)
            self.assertEqual(summary.failed_work_unit_id, failed_unit.id)
            self.assertEqual(
                summary.job_status,
                PersistentTranslationJobStatus.INTERRUPTED,
            )
            self.assertEqual(failed_unit.status, PersistentWorkUnitStatus.FAILED)

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
        if "<translation_block" in text:
            blocks = re.findall(
                r"<translation_block[^>]*>(.*?)</translation_block>",
                text,
                flags=re.DOTALL,
            )
            return "\n".join(
                ["<translation_batch>"]
                + [
                    f'<translation_block id="{index}">[{target_language}] '
                    f"{block}</translation_block>"
                    for index, block in enumerate(blocks)
                ]
                + ["</translation_batch>"]
            )
        return f"[{target_language}] {text}"


class ProviderIODiagnosticTranslator(RecordingTranslator):
    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        record_provider_io_exchange(
            provider_id="deepseek",
            url="https://api.deepseek.example/chat/completions",
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


class StaleCompletionTranslator(RecordingTranslator):
    def __init__(self, store: SQLiteTranslationJobStore, job_id: str) -> None:
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
        result = super().translate(
            text=text,
            source_language=source_language,
            target_language=target_language,
        )
        unit = next(
            unit
            for unit in self._store.list_work_units(self._job_id)
            if unit.status is PersistentWorkUnitStatus.TRANSLATING
        )
        assert unit.claim_token is not None
        self._store.complete_claimed_work_unit(
            work_unit_id=unit.id,
            claim_token=unit.claim_token,
            translated_text=result,
            prompt_tokens=1,
            completion_tokens=1,
            cache_hit_tokens=0,
            cache_miss_tokens=1,
        )
        return result


class _SchedulerSettings:
    def __init__(
        self,
        *,
        scheduler_backend: str,
        persistent_jobs_db_path: str,
        postgres_dsn: str,
    ) -> None:
        self.scheduler_backend = scheduler_backend
        self.persistent_jobs_db_path = persistent_jobs_db_path
        self.postgres_dsn = postgres_dsn


class _FakePostgresStore:
    def __init__(self) -> None:
        self.connection = object()
        self.closed = False

    def close(self) -> None:
        self.closed = True


class ContextFallbackTranslator:
    def __init__(self) -> None:
        self.contexts: list[TranslationContextMemory | None] = []
        self.last_usage: ProviderUsage | None = None

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
        translation_context: TranslationContextMemory | None = None,
    ) -> str:
        self.contexts.append(translation_context)
        self.last_usage = ProviderUsage(prompt_tokens=10, completion_tokens=5)
        if "<translation_batch" in text:
            return "not a valid batch"
        if "Alice whispered to Mark" in text:
            return "Алиса прошептала Марку."
        if "Mark opened the door" in text:
            return "Марк открыл дверь."
        return f"[{target_language}] {text}"


class SecondaryLanguageRetryTranslator:
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
        self.last_usage = ProviderUsage(prompt_tokens=10, completion_tokens=5)
        markers = re.findall(r"ZXQPROTECTED\d+QXZ", text)
        prefix_marker = markers[0] if markers else "CJK:"
        variable_marker = markers[-1] if markers else "{{变量}}"
        if source_language == "auto" and "afspraak" in text:
            return (
                "Английский + нидерландский: Встреча назначена на вторник "
                "в четверть четвертого."
            )
        if source_language == "auto" and "请保留变量" in text:
            return (
                f"{prefix_marker} Метка 東京-大阪 должна оставаться читаемой; "
                f"пример на китайском: сохраните переменную {variable_marker}."
            )
        return (
            "<translation_batch>"
            '<translation_block id="0">Английский + нидерландский: '
            "Встреча назначена на dinsdag om kwart over drie."
            "</translation_block>"
            f'<translation_block id="1">{prefix_marker} Метка 東京-大阪 '
            "должна оставаться читаемой; "
            f"пример на китайском: 请保留变量 {variable_marker}.</translation_block>"
            "</translation_batch>"
        )


class MixedLanguageLabelRetryTranslator:
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
        self.last_usage = ProviderUsage(prompt_tokens=10, completion_tokens=5)
        if source_language == "auto":
            return (
                "Английский + нидерландский: встреча назначена на вторник "
                "в четверть четвертого."
            )
        return (
            "<translation_batch>"
            '<translation_block id="0">Встреча назначена на вторник '
            "в пятнадцать пятнадцать.</translation_block>"
            '<translation_block id="1">Обычное английское предложение.'
            "</translation_block>"
            "</translation_batch>"
        )


class UkrainianRetryTranslator:
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
        self.last_usage = ProviderUsage(prompt_tokens=10, completion_tokens=5)
        if source_language == "auto":
            return (
                "Английский + украинский: пожалуйста, переведите это предложение, "
                "но не ломайте украинский текст внутри."
            )
        return (
            "Английский + украинский: пожалуйста, переведите это предложение, "
            "але не ламай український текст у середині."
        )


class EnglishResidueRetryTranslator:
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
        self.last_usage = ProviderUsage(prompt_tokens=10, completion_tokens=5)
        if source_language == "auto":
            return "Утром улицы Вены оживляло шествие."
        return "ON THE утром улицы Вены оживляло шествие."


class RtlRetryTranslator:
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
        self.last_usage = ProviderUsage(prompt_tokens=10, completion_tokens=5)
        markers = re.findall(r"ZXQPROTECTED\d+QXZ", text)
        token_marker = markers[0] if markers else "{{RTL_TOKEN}}"
        if source_language == "auto":
            return (
                "Иврит / арабский вперемешку с английским 12345 "
                f"и токеном {token_marker}. Направление и глифы должны сохраниться."
            )
        return (
            "עברית / العربية вперемешку с английским 12345 "
            f"и токеном {token_marker}. Направление и глифы должны сохраниться."
        )


class InlineArtifactTranslator:
    last_usage = ProviderUsage(prompt_tokens=10, completion_tokens=5)

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        return (
            "В этом абзаце нижний индекс H2O subscript H2и "
            "верхний superscript x2индекс x2."
        )


class FailingTranslator:
    last_usage = None

    def __init__(self, message: str = "provider read timeout") -> None:
        self._message = message

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        raise RuntimeError(self._message)


class ProviderValidationErrorTranslator:
    last_usage = None

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        raise ValueError("provider validation failed")


class _DeepSeekErrorClientFactory:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def __call__(self, *, api_key: str, **kwargs):
        return _DeepSeekErrorClient(self._error)


class _DeepSeekErrorClient:
    last_usage = None

    def __init__(self, error: Exception) -> None:
        self._error = error

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        raise self._error


class BlockingParallelTranslator:
    def __init__(self, *, expected_parallel_calls: int) -> None:
        self._barrier = threading.Barrier(expected_parallel_calls)
        self._lock = threading.Lock()
        self._active_calls = 0
        self.max_active_calls = 0
        self.last_usage: ProviderUsage | None = None

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        with self._lock:
            self._active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self._active_calls)
        try:
            self._barrier.wait(timeout=5)
            self.last_usage = ProviderUsage(
                prompt_tokens=11,
                completion_tokens=3,
                total_tokens=14,
                prompt_cache_miss_tokens=11,
            )
            return f"[{target_language}] {text}"
        finally:
            with self._lock:
                self._active_calls -= 1


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


def _job_with_two_stored_units(
    store: SQLiteTranslationJobStore,
    first_source_object_key: str,
    second_source_object_key: str,
):
    job = store.create_job(
        order_id="order-1",
        user_id="user-42",
        file_id="file-1",
        file_name="book.epub",
        document_kind="epub",
        source_language="en",
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
                source_object_key=first_source_object_key,
            ),
            WorkUnitPlan(
                sequence=2,
                source_block_ids=("chapter-1:p2",),
                source_text_hash="hash-2",
                prompt_tier="plain",
                source_language="en",
                target_language="uk",
                source_object_key=second_source_object_key,
            ),
        ],
    )
    return job


def _job_with_stored_unit(
    store: SQLiteTranslationJobStore,
    work_unit_source_object_key: str,
    *,
    source_language: str = "en",
    target_language: str = "uk",
    source_object_key: str | None = None,
    translation_policy: str | None = None,
):
    job = store.create_job(
        order_id="order-1",
        user_id="user-42",
        file_id="file-1",
        file_name="book.epub",
        document_kind="epub",
        source_language=source_language,
        target_language=target_language,
        adapter_version="epub-v1",
        prompt_version="plain-v1",
        pricing_snapshot_id="pricing-1",
        source_object_key=source_object_key,
        translation_policy=translation_policy,
    )
    store.add_work_units(
        job.id,
        [
            WorkUnitPlan(
                sequence=1,
                source_block_ids=("chapter-1:p1",),
                source_text_hash="hash-1",
                prompt_tier="plain",
                source_language=source_language,
                target_language=target_language,
                source_object_key=work_unit_source_object_key,
            ),
        ],
    )
    return job


def _job_with_stored_multi_block_unit(
    store: SQLiteTranslationJobStore,
    source_object_key: str,
    *,
    source_language: str,
    target_language: str,
):
    job = store.create_job(
        order_id="order-1",
        user_id="user-42",
        file_id="file-1",
        file_name="book.docx",
        document_kind="docx",
        source_language=source_language,
        target_language=target_language,
        adapter_version="docx-v1",
        prompt_version="plain-v1",
        pricing_snapshot_id="pricing-1",
    )
    store.add_work_units(
        job.id,
        [
            WorkUnitPlan(
                sequence=1,
                source_block_ids=(
                    "docx:word/document.xml:1",
                    "docx:word/document.xml:2",
                ),
                source_text_hash="hash-1",
                prompt_tier="plain",
                source_language=source_language,
                target_language=target_language,
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


def _target_metadata_overlay_payload() -> dict[str, object]:
    return {
        "schema_version": GLOSSARY_TARGET_METADATA_OVERLAY_SCHEMA_VERSION,
        "overlay_id": "worker-resolver-test-overlay",
        "scope": "local_owner_only_real_book_battle_test",
        "owner_approved": True,
        "source_language": "en",
        "targets": {
            "ru": {
                "entries": [
                    {
                        "source_canonical": "Darcy",
                        "target_canonical": "Дарси",
                        "target_variants": ["мистер Дарси"],
                    }
                ]
            }
        },
    }


def _prepared_glossary_package(
    *,
    target_language: str = "ru",
    needs_review: bool = False,
    source_unit_refs: list[int] | None = None,
    source_block_refs: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
        "package_id": "prepared:worker-test:ru",
        "source_language": "en",
        "target_language": target_language,
        "glossary_mode": "with_glossary",
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
                "source_unit_refs": list(source_unit_refs or []),
                "source_block_refs": list(source_block_refs or []),
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
                    "work_unit_sequence": 1,
                    "source_block_ids": ["chapter-1:p1"],
                    "budget_exceeded": False,
                    "budget_status": "within_budget",
                    "fallback_reason_codes": [],
                    "selected_entry_ids": ["glossary-entry:v1:darcy"],
                    "selection_signature": "glossary-selection:v1:1",
                    "fallback_action": "shadow_metadata_only",
                }
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


def _make_docx(document_xml: str) -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr("word/document.xml", document_xml)
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


if __name__ == "__main__":
    unittest.main()
