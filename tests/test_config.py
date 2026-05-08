import os
import unittest
from unittest.mock import patch


from translator_service.config import Settings, validate_server_settings


class SettingsTest(unittest.TestCase):
    def test_settings_have_safe_development_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()

        self.assertEqual(settings.service_name, "DeepSeek Document Translator")
        self.assertEqual(settings.environment, "development")
        self.assertEqual(settings.max_upload_mb, 50)
        self.assertEqual(settings.deepseek_model, "deepseek-v4-flash")
        self.assertEqual(settings.object_storage_root, "var/object-storage")
        self.assertEqual(settings.persistent_jobs_db_path, "var/jobs.sqlite3")


class BackendSettingsTests(unittest.TestCase):
    def test_reads_backend_settings_from_environment(self):
        env = {
            "JOB_STORE_BACKEND": "postgres",
            "POSTGRES_DSN": "postgresql://translator:secret@postgres:5432/translator",
            "TRANSLATION_EXECUTION_MODE": "worker",
            "WORKER_POLL_SECONDS": "2.5",
            "WORK_UNIT_LEASE_SECONDS": "900",
            "WORKER_ID": "worker-beta-1",
            "OBJECT_STORAGE_ROOT": "/data/object-storage",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()

        self.assertEqual(settings.job_store_backend, "postgres")
        self.assertEqual(
            settings.postgres_dsn,
            "postgresql://translator:secret@postgres:5432/translator",
        )
        self.assertEqual(settings.translation_execution_mode, "worker")
        self.assertEqual(settings.worker_poll_seconds, 2.5)
        self.assertEqual(settings.work_unit_lease_seconds, 900)
        self.assertEqual(settings.worker_id, "worker-beta-1")
        self.assertEqual(settings.object_storage_root, "/data/object-storage")

    def test_postgres_dsn_falls_back_to_database_url(self):
        env = {
            "DATABASE_URL": "postgresql://translator:fallback@postgres:5432/translator",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()

        self.assertEqual(
            settings.postgres_dsn,
            "postgresql://translator:fallback@postgres:5432/translator",
        )

    def test_server_validation_requires_postgres_for_worker_mode(self):
        settings = Settings(
            job_store_backend="sqlite",
            translation_execution_mode="worker",
        )

        with self.assertRaisesRegex(ValueError, "JOB_STORE_BACKEND=postgres"):
            validate_server_settings(settings)

    def test_server_validation_accepts_postgres_worker_mode(self):
        settings = Settings(
            job_store_backend="postgres",
            translation_execution_mode="worker",
            postgres_dsn="postgresql://translator:secret@postgres:5432/translator",
            object_storage_root="/data/object-storage",
        )

        validate_server_settings(settings)


if __name__ == "__main__":
    unittest.main()
