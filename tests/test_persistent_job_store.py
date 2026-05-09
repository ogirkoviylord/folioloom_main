import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from translator_service.config import Settings
from translator_service.persistent_job_store import open_persistent_job_store
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
            finally:
                store.close()

    def test_opens_postgres_store_and_initializes_schema(self):
        settings = Settings(
            scheduler_backend="postgres",
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
            store = open_persistent_job_store(settings)

        self.assertIs(store, fake_store)
        store_cls.assert_called_once_with("postgresql://translator")
        initialize_schema.assert_called_once_with(fake_store.connection)

    def test_closes_postgres_store_when_schema_initialization_fails(self):
        settings = Settings(
            scheduler_backend="postgres",
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
                open_persistent_job_store(settings)

        self.assertTrue(fake_store.closed)


class _FakePostgresStore:
    connection = object()

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


if __name__ == "__main__":
    unittest.main()
