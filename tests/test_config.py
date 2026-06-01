import unittest
from unittest.mock import patch

from translator_service.config import Settings


class SettingsTest(unittest.TestCase):
    def test_settings_have_safe_development_defaults(self):
        settings = Settings()

        self.assertEqual(settings.service_name, "DeepSeek Document Translator")
        self.assertEqual(settings.environment, "development")
        self.assertEqual(settings.max_upload_mb, 50)
        self.assertFalse(settings.require_upload_scan)
        self.assertEqual(settings.upload_scanner_backend, "none")
        self.assertEqual(settings.upload_scan_max_concurrency, 1)
        self.assertEqual(settings.upload_scan_backpressure_timeout_seconds, 1.0)
        self.assertEqual(settings.clamd_host, "127.0.0.1")
        self.assertEqual(settings.clamd_port, 3310)
        self.assertEqual(settings.clamd_timeout_seconds, 10.0)
        self.assertEqual(settings.clamd_chunk_size_bytes, 65536)
        self.assertEqual(settings.clamd_response_limit_bytes, 4096)
        self.assertEqual(settings.deepseek_model, "deepseek-v4-flash")
        self.assertEqual(settings.object_storage_root, "var/object-storage")
        self.assertEqual(settings.persistent_jobs_db_path, "var/jobs.sqlite3")
        self.assertEqual(settings.user_settings_db_path, "var/user-settings.sqlite3")
        self.assertEqual(settings.translation_run_log_root, "var/translation-runs")
        self.assertEqual(settings.translation_max_parallel_units, 1)
        self.assertFalse(settings.bot_defer_persistent_jobs_to_worker)
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
        self.assertFalse(settings.admin_cookie_secure)

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

    def test_bot_can_defer_persistent_jobs_to_worker_from_environment(self):
        with patch.dict(
            "os.environ",
            {"BOT_DEFER_PERSISTENT_JOBS_TO_WORKER": "true"},
        ):
            settings = Settings()

        self.assertTrue(settings.bot_defer_persistent_jobs_to_worker)

    def test_upload_scan_gate_can_be_required_from_environment(self):
        with patch.dict(
            "os.environ",
            {
                "REQUIRE_UPLOAD_SCAN": "true",
                "UPLOAD_SCANNER_BACKEND": "clamd",
                "UPLOAD_SCAN_MAX_CONCURRENCY": "2",
                "UPLOAD_SCAN_BACKPRESSURE_TIMEOUT_SECONDS": "0.5",
                "CLAMD_HOST": "clamd",
                "CLAMD_PORT": "3310",
                "CLAMD_TIMEOUT_SECONDS": "2.5",
                "CLAMD_CHUNK_SIZE_BYTES": "8192",
                "CLAMD_RESPONSE_LIMIT_BYTES": "1024",
            },
        ):
            settings = Settings()

        self.assertTrue(settings.require_upload_scan)
        self.assertEqual(settings.upload_scanner_backend, "clamd")
        self.assertEqual(settings.upload_scan_max_concurrency, 2)
        self.assertEqual(settings.upload_scan_backpressure_timeout_seconds, 0.5)
        self.assertEqual(settings.clamd_host, "clamd")
        self.assertEqual(settings.clamd_port, 3310)
        self.assertEqual(settings.clamd_timeout_seconds, 2.5)
        self.assertEqual(settings.clamd_chunk_size_bytes, 8192)
        self.assertEqual(settings.clamd_response_limit_bytes, 1024)

    def test_production_runtime_defaults_to_fail_closed_clamd_scanning(self):
        with patch.dict(
            "os.environ",
            {
                "ENVIRONMENT": "production",
            },
            clear=True,
        ):
            settings = Settings()

        self.assertTrue(settings.require_upload_scan)
        self.assertEqual(settings.upload_scanner_backend, "clamd")
        self.assertEqual(settings.clamd_host, "clamd")
        self.assertEqual(settings.clamd_port, 3310)

    def test_server_beta_runtime_defaults_to_fail_closed_clamd_scanning(self):
        with patch.dict(
            "os.environ",
            {
                "ENVIRONMENT": "server-beta",
            },
            clear=True,
        ):
            settings = Settings()

        self.assertEqual(settings.environment, "server-beta")
        self.assertTrue(settings.require_upload_scan)
        self.assertEqual(settings.upload_scanner_backend, "clamd")
        self.assertEqual(settings.clamd_host, "clamd")
        self.assertEqual(settings.clamd_port, 3310)

    def test_blank_production_scanner_env_uses_fail_closed_clamd_defaults(self):
        with patch.dict(
            "os.environ",
            {
                "ENVIRONMENT": "production",
                "REQUIRE_UPLOAD_SCAN": "",
                "UPLOAD_SCANNER_BACKEND": "",
                "CLAMD_HOST": "",
            },
            clear=True,
        ):
            settings = Settings()

        self.assertTrue(settings.require_upload_scan)
        self.assertEqual(settings.upload_scanner_backend, "clamd")
        self.assertEqual(settings.clamd_host, "clamd")

    def test_blank_server_beta_scanner_env_uses_fail_closed_clamd_defaults(self):
        with patch.dict(
            "os.environ",
            {
                "ENVIRONMENT": "server-beta",
                "REQUIRE_UPLOAD_SCAN": "",
                "UPLOAD_SCANNER_BACKEND": "",
                "CLAMD_HOST": "",
            },
            clear=True,
        ):
            settings = Settings()

        self.assertTrue(settings.require_upload_scan)
        self.assertEqual(settings.upload_scanner_backend, "clamd")
        self.assertEqual(settings.clamd_host, "clamd")

    def test_explicit_production_scanner_deferral_overrides_default(self):
        with patch.dict(
            "os.environ",
            {
                "ENVIRONMENT": "production",
                "REQUIRE_UPLOAD_SCAN": "false",
                "UPLOAD_SCANNER_BACKEND": "none",
            },
            clear=True,
        ):
            settings = Settings()

        self.assertFalse(settings.require_upload_scan)
        self.assertEqual(settings.upload_scanner_backend, "none")

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
        self.assertEqual(settings.scheduler_max_active_units_global, 2)
        self.assertEqual(settings.scheduler_max_active_units_per_user, 1)
        self.assertEqual(settings.scheduler_max_active_jobs_per_user, 1)
        self.assertEqual(settings.scheduler_max_active_units_per_job, 1)
        self.assertEqual(settings.scheduler_priority_aging_seconds, 1800)

    def test_scheduler_fairness_settings_can_be_configured_from_environment(self):
        with patch.dict(
            "os.environ",
            {
                "SCHEDULER_MAX_ACTIVE_UNITS_GLOBAL": "5",
                "SCHEDULER_MAX_ACTIVE_UNITS_PER_USER": "3",
                "SCHEDULER_MAX_ACTIVE_JOBS_PER_USER": "2",
                "SCHEDULER_MAX_ACTIVE_UNITS_PER_JOB": "4",
                "SCHEDULER_PRIORITY_AGING_SECONDS": "60",
            },
        ):
            settings = Settings()

        self.assertEqual(settings.scheduler_max_active_units_global, 5)
        self.assertEqual(settings.scheduler_max_active_units_per_user, 3)
        self.assertEqual(settings.scheduler_max_active_jobs_per_user, 2)
        self.assertEqual(settings.scheduler_max_active_units_per_job, 4)
        self.assertEqual(settings.scheduler_priority_aging_seconds, 60)

    def test_scheduler_fairness_settings_are_clamped_to_safe_minimums(self):
        with patch.dict(
            "os.environ",
            {
                "SCHEDULER_MAX_ACTIVE_UNITS_GLOBAL": "0",
                "SCHEDULER_MAX_ACTIVE_UNITS_PER_USER": "0",
                "SCHEDULER_MAX_ACTIVE_JOBS_PER_USER": "0",
                "SCHEDULER_MAX_ACTIVE_UNITS_PER_JOB": "0",
                "SCHEDULER_PRIORITY_AGING_SECONDS": "-1",
            },
        ):
            settings = Settings()

        self.assertEqual(settings.scheduler_max_active_units_global, 1)
        self.assertEqual(settings.scheduler_max_active_units_per_user, 1)
        self.assertEqual(settings.scheduler_max_active_jobs_per_user, 1)
        self.assertEqual(settings.scheduler_max_active_units_per_job, 1)
        self.assertEqual(settings.scheduler_priority_aging_seconds, 0)

    def test_admin_settings_can_be_configured_from_environment(self):
        with patch.dict(
            "os.environ",
            {
                "ADMIN_DB_PATH": "var/custom-admin.sqlite3",
                "ADMIN_SESSION_SECRET": "session-secret",
                "ADMIN_OWNER_PASSWORD": "owner-pass",
                "ADMIN_SECRET_MASTER_KEY": "secret-master-key",
                "ADMIN_COOKIE_SECURE": "true",
            },
        ):
            settings = Settings()

        self.assertEqual(settings.admin_db_path, "var/custom-admin.sqlite3")
        self.assertEqual(settings.admin_session_secret, "session-secret")
        self.assertEqual(settings.admin_owner_password, "owner-pass")
        self.assertEqual(settings.admin_secret_master_key, "secret-master-key")
        self.assertTrue(settings.admin_cookie_secure)

    def test_beta_safety_defaults_are_safe_for_closed_beta(self):
        with patch.dict(
            "os.environ",
            {
                "BETA_TRANSLATIONS_PAUSED": "",
                "BETA_GLOBAL_DAILY_COST_CAP_USD": "",
                "BETA_GLOBAL_MONTHLY_COST_CAP_USD": "",
                "BETA_USER_DAILY_COST_CAP_USD": "",
                "BETA_USER_MONTHLY_COST_CAP_USD": "",
                "BETA_USER_DAILY_JOB_LIMIT": "",
                "BETA_MAX_JOB_ESTIMATED_COST_USD": "",
                "BETA_COST_INPUT_USD_PER_MILLION": "",
                "BETA_COST_OUTPUT_USD_PER_MILLION": "",
                "BETA_COST_WARNING_FRACTION": "",
            },
        ):
            settings = Settings()

        self.assertFalse(settings.beta_translations_paused)
        self.assertEqual(settings.beta_global_daily_cost_cap_usd, 5.0)
        self.assertEqual(settings.beta_global_monthly_cost_cap_usd, 50.0)
        self.assertEqual(settings.beta_user_daily_cost_cap_usd, 1.0)
        self.assertEqual(settings.beta_user_monthly_cost_cap_usd, 10.0)
        self.assertEqual(settings.beta_user_daily_job_limit, 3)
        self.assertEqual(settings.beta_max_job_estimated_cost_usd, 2.0)
        self.assertEqual(settings.beta_cost_input_usd_per_million, 0.28)
        self.assertEqual(settings.beta_cost_output_usd_per_million, 1.10)
        self.assertEqual(settings.beta_cost_warning_fraction, 0.8)

    def test_beta_safety_settings_can_be_configured_from_environment(self):
        with patch.dict(
            "os.environ",
            {
                "BETA_TRANSLATIONS_PAUSED": "true",
                "BETA_GLOBAL_DAILY_COST_CAP_USD": "7.5",
                "BETA_GLOBAL_MONTHLY_COST_CAP_USD": "75",
                "BETA_USER_DAILY_COST_CAP_USD": "1.5",
                "BETA_USER_MONTHLY_COST_CAP_USD": "15",
                "BETA_USER_DAILY_JOB_LIMIT": "4",
                "BETA_MAX_JOB_ESTIMATED_COST_USD": "3.5",
                "BETA_COST_INPUT_USD_PER_MILLION": "0.30",
                "BETA_COST_OUTPUT_USD_PER_MILLION": "1.20",
                "BETA_COST_WARNING_FRACTION": "0.65",
            },
        ):
            settings = Settings()

        self.assertTrue(settings.beta_translations_paused)
        self.assertEqual(settings.beta_global_daily_cost_cap_usd, 7.5)
        self.assertEqual(settings.beta_global_monthly_cost_cap_usd, 75.0)
        self.assertEqual(settings.beta_user_daily_cost_cap_usd, 1.5)
        self.assertEqual(settings.beta_user_monthly_cost_cap_usd, 15.0)
        self.assertEqual(settings.beta_user_daily_job_limit, 4)
        self.assertEqual(settings.beta_max_job_estimated_cost_usd, 3.5)
        self.assertEqual(settings.beta_cost_input_usd_per_million, 0.30)
        self.assertEqual(settings.beta_cost_output_usd_per_million, 1.20)
        self.assertEqual(settings.beta_cost_warning_fraction, 0.65)

    def test_beta_safety_settings_are_clamped_to_safe_ranges(self):
        with patch.dict(
            "os.environ",
            {
                "BETA_USER_DAILY_JOB_LIMIT": "-1",
                "BETA_COST_WARNING_FRACTION": "1.5",
            },
        ):
            high_warning = Settings()
        with patch.dict("os.environ", {"BETA_COST_WARNING_FRACTION": "-0.2"}):
            low_warning = Settings()

        self.assertEqual(high_warning.beta_user_daily_job_limit, 0)
        self.assertEqual(high_warning.beta_cost_warning_fraction, 1.0)
        self.assertEqual(low_warning.beta_cost_warning_fraction, 0.0)


if __name__ == "__main__":
    unittest.main()
