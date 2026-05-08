import unittest
from unittest.mock import patch

from translator_service.config import Settings


class SettingsTest(unittest.TestCase):
    def test_settings_have_safe_development_defaults(self):
        settings = Settings()

        self.assertEqual(settings.service_name, "DeepSeek Document Translator")
        self.assertEqual(settings.environment, "development")
        self.assertEqual(settings.max_upload_mb, 50)
        self.assertEqual(settings.deepseek_model, "deepseek-v4-flash")
        self.assertEqual(settings.object_storage_root, "var/object-storage")
        self.assertEqual(settings.persistent_jobs_db_path, "var/jobs.sqlite3")
        self.assertEqual(settings.user_settings_db_path, "var/user-settings.sqlite3")
        self.assertEqual(settings.translation_run_log_root, "var/translation-runs")
        self.assertEqual(settings.translation_max_parallel_units, 1)
        self.assertEqual(settings.security_max_events_per_run, 20)
        self.assertEqual(settings.security_max_unsafe_model_outputs_per_run, 3)
        self.assertEqual(settings.security_max_repair_failures_per_run, 1)
        self.assertEqual(settings.security_user_cooldown_thresholds_per_window, 2)
        self.assertEqual(settings.security_user_cooldown_window_seconds, 3600)
        self.assertEqual(settings.security_user_cooldown_seconds, 900)
        self.assertEqual(settings.admin_db_path, "var/admin.sqlite3")
        self.assertEqual(settings.admin_session_secret, "")
        self.assertEqual(settings.admin_owner_password, "")
        self.assertEqual(settings.admin_secret_master_key, "")

    def test_translation_run_log_root_can_be_configured_from_environment(self):
        with patch.dict(
            "os.environ",
            {"TRANSLATION_RUN_LOG_ROOT": "var/custom-translation-runs"},
        ):
            settings = Settings()

        self.assertEqual(
            settings.translation_run_log_root,
            "var/custom-translation-runs",
        )

    def test_translation_max_parallel_units_can_be_configured_from_environment(self):
        with patch.dict(
            "os.environ",
            {"TRANSLATION_MAX_PARALLEL_UNITS": "3"},
        ):
            settings = Settings()

        self.assertEqual(settings.translation_max_parallel_units, 3)

    def test_security_thresholds_can_be_configured_from_environment(self):
        with patch.dict(
            "os.environ",
            {
                "SECURITY_MAX_EVENTS_PER_RUN": "7",
                "SECURITY_MAX_UNSAFE_MODEL_OUTPUTS_PER_RUN": "2",
                "SECURITY_MAX_REPAIR_FAILURES_PER_RUN": "1",
            },
        ):
            settings = Settings()

        self.assertEqual(settings.security_max_events_per_run, 7)
        self.assertEqual(settings.security_max_unsafe_model_outputs_per_run, 2)
        self.assertEqual(settings.security_max_repair_failures_per_run, 1)

    def test_security_cooldown_can_be_configured_from_environment(self):
        with patch.dict(
            "os.environ",
            {
                "SECURITY_USER_COOLDOWN_THRESHOLDS_PER_WINDOW": "3",
                "SECURITY_USER_COOLDOWN_WINDOW_SECONDS": "120",
                "SECURITY_USER_COOLDOWN_SECONDS": "45",
            },
        ):
            settings = Settings()

        self.assertEqual(settings.security_user_cooldown_thresholds_per_window, 3)
        self.assertEqual(settings.security_user_cooldown_window_seconds, 120)
        self.assertEqual(settings.security_user_cooldown_seconds, 45)

    def test_scheduler_settings_have_safe_defaults(self):
        settings = Settings()

        self.assertEqual(settings.scheduler_backend, "sqlite")
        self.assertEqual(
            settings.postgres_dsn,
            "postgresql://translator:translator@localhost:5432/translator",
        )
        self.assertEqual(settings.scheduler_lease_seconds, 300)
        self.assertEqual(settings.scheduler_poll_seconds, 2.0)
        self.assertEqual(settings.scheduler_retry_base_delay_seconds, 30)
        self.assertEqual(settings.scheduler_retry_max_delay_seconds, 600)

    def test_admin_settings_can_be_configured_from_environment(self):
        with patch.dict(
            "os.environ",
            {
                "ADMIN_DB_PATH": "var/custom-admin.sqlite3",
                "ADMIN_SESSION_SECRET": "session-secret",
                "ADMIN_OWNER_PASSWORD": "owner-pass",
                "ADMIN_SECRET_MASTER_KEY": "secret-master-key",
            },
        ):
            settings = Settings()

        self.assertEqual(settings.admin_db_path, "var/custom-admin.sqlite3")
        self.assertEqual(settings.admin_session_secret, "session-secret")
        self.assertEqual(settings.admin_owner_password, "owner-pass")
        self.assertEqual(settings.admin_secret_master_key, "secret-master-key")


if __name__ == "__main__":
    unittest.main()
