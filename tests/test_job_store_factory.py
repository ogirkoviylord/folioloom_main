import unittest
from unittest.mock import patch

from translator_service.config import Settings
from translator_service.job_store_factory import create_translation_job_store
from translator_service.persistent_jobs import SQLiteTranslationJobStore


class JobStoreFactoryTests(unittest.TestCase):
    def test_creates_sqlite_store_for_local_development(self):
        settings = Settings(
            job_store_backend="sqlite",
            persistent_jobs_db_path=":memory:",
        )

        store = create_translation_job_store(settings)
        self.addCleanup(store.close)

        self.assertIsInstance(store, SQLiteTranslationJobStore)

    def test_creates_postgres_store_for_server_backend(self):
        settings = Settings(
            job_store_backend="postgres",
            postgres_dsn="postgresql://translator:translator@postgres:5432/translator",
        )

        with patch(
            "translator_service.job_store_factory.PostgreSQLTranslationJobStore"
        ) as cls:
            create_translation_job_store(settings)

        cls.assert_called_once_with(settings.postgres_dsn)

    def test_rejects_unsupported_backend(self):
        settings = Settings(job_store_backend="memory")

        with self.assertRaisesRegex(
            ValueError,
            "Unsupported JOB_STORE_BACKEND: memory",
        ):
            create_translation_job_store(settings)


if __name__ == "__main__":
    unittest.main()
