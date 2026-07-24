import inspect
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import get_type_hints
from unittest.mock import patch

from translator_service.config import Settings
from translator_service.persistent_job_store import (
    PersistentJobStore,
    StrictDocxJobStore,
    open_persistent_job_store,
)
from translator_service.persistent_jobs import SQLiteTranslationJobStore


class PersistentJobStoreFactoryTest(unittest.TestCase):
    def test_opens_sqlite_store_for_sqlite_backend(self):
        with TemporaryDirectory() as temp_dir:
            store = open_persistent_job_store(
                Settings(
                    scheduler_backend="sqlite",
                    persistent_jobs_db_path=str(Path(temp_dir) / "jobs.sqlite3"),
                )
            )
            try:
                self.assertIsInstance(store, SQLiteTranslationJobStore)
                self.assertIsInstance(store, StrictDocxJobStore)
            finally:
                store.close()

    def test_opens_postgres_store_and_runs_versioned_migrations(self):
        settings = Settings(
            scheduler_backend="postgres",
            postgres_dsn="postgresql://translator",
        )
        fake_store = _FakePostgresStore()

        with patch(
            "translator_service.postgres_scheduler.PostgresSchedulerStore",
            return_value=fake_store,
        ) as store_cls, patch(
            "translator_service.postgres_migrations.run_postgres_migrations"
        ) as run_migrations:
            store = open_persistent_job_store(settings)

        self.assertIs(store, fake_store)
        store_cls.assert_called_once_with("postgresql://translator")
        run_migrations.assert_called_once_with(fake_store.connection)
        self.assertTrue(fake_store.strict_docx_migration_ready)
        self.assertTrue(fake_store.document_glossary_authoring_migration_ready)
        self.assertNotIsInstance(store, StrictDocxJobStore)

    def test_closes_postgres_store_when_versioned_migrations_fail(self):
        settings = Settings(
            scheduler_backend="postgres",
            postgres_dsn="postgresql://translator",
        )
        fake_store = _FakePostgresStore()

        with patch(
            "translator_service.postgres_scheduler.PostgresSchedulerStore",
            return_value=fake_store,
        ), patch(
            "translator_service.postgres_migrations.run_postgres_migrations",
            side_effect=RuntimeError("migration failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "migration failed"):
                open_persistent_job_store(settings)

        self.assertTrue(fake_store.closed)

    def test_preserves_migration_error_when_postgres_store_close_fails(self):
        settings = Settings(
            scheduler_backend="postgres",
            postgres_dsn="postgresql://translator",
        )
        fake_store = _FakePostgresStore(close_error=RuntimeError("close failed"))

        with patch(
            "translator_service.postgres_scheduler.PostgresSchedulerStore",
            return_value=fake_store,
        ), patch(
            "translator_service.postgres_migrations.run_postgres_migrations",
            side_effect=RuntimeError("migration failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "migration failed") as raised:
                open_persistent_job_store(settings)

        self.assertIsNotNone(raised.exception.__cause__)
        self.assertEqual(str(raised.exception.__cause__), "close failed")
        self.assertTrue(fake_store.closed)


class PersistentJobStoreProtocolTest(unittest.TestCase):
    def test_factory_returns_shared_protocol_without_strict_docx_api(self):
        self.assertIs(
            get_type_hints(open_persistent_job_store)["return"],
            PersistentJobStore,
        )
        self.assertNotIn("admit_strict_docx_job", PersistentJobStore.__dict__)

    def test_declares_backend_neutral_strict_docx_api_signatures(self):
        strict_docx_methods = (
            "create_glossary_approval",
            "revoke_glossary_approval",
            "read_approved_glossary_snapshot",
            "admit_strict_docx_job",
        )

        for method_name in strict_docx_methods:
            with self.subTest(method_name=method_name):
                self.assertNotIn(method_name, PersistentJobStore.__dict__)
                self.assertIn(method_name, StrictDocxJobStore.__dict__)
                self.assertEqual(
                    inspect.signature(
                        getattr(StrictDocxJobStore, method_name),
                        eval_str=True,
                    ),
                    inspect.signature(
                        getattr(SQLiteTranslationJobStore, method_name),
                        eval_str=True,
                    ),
                )


class _FakePostgresStore:
    connection = object()
    strict_docx_migration_ready = False
    document_glossary_authoring_migration_ready = False

    def __init__(self, close_error: Exception | None = None) -> None:
        self.closed = False
        self.close_error = close_error

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


if __name__ == "__main__":
    unittest.main()
