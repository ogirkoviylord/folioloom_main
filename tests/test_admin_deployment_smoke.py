import sqlite3
import unittest
from base64 import urlsafe_b64encode
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from translator_service.admin.ai_provider_keys import SQLiteAIProviderKeyStore
from translator_service.admin.deployment_smoke import (
    AdminDeploymentCheckError,
    check_admin_runtime_configuration,
)
from translator_service.admin.secrets import SQLiteEncryptedSecretStore
from translator_service.config import Settings

MASTER_KEY = urlsafe_b64encode(b"6" * 32).decode("ascii")


class AdminDeploymentSmokeTest(unittest.TestCase):
    def test_rejects_missing_production_admin_configuration(self):
        with self.assertRaisesRegex(AdminDeploymentCheckError, "ADMIN_OWNER_PASSWORD"):
            check_admin_runtime_configuration(
                Settings(
                    environment="production",
                    admin_owner_password="",
                    admin_session_secret="session-secret",
                    admin_secret_master_key=MASTER_KEY,
                )
            )

    def test_rejects_invalid_admin_secret_master_key(self):
        with TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                AdminDeploymentCheckError,
                "ADMIN_SECRET_MASTER_KEY",
            ):
                check_admin_runtime_configuration(
                    Settings(
                        environment="production",
                        admin_db_path=str(Path(temp_dir) / "admin.sqlite3"),
                        admin_owner_password="long-owner-password",
                        admin_session_secret="long-session-secret-value",
                        admin_secret_master_key="not-a-valid-master-key",
                    )
                )

    def test_writes_admin_db_probe_and_reports_active_provider_keys(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    keys.add_key(
                        provider_id="deepseek",
                        label="stable",
                        plaintext="sk-admin-runtime",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                    )

            result = check_admin_runtime_configuration(
                Settings(
                    environment="production",
                    admin_db_path=str(db_path),
                    persistent_jobs_db_path=str(Path(temp_dir) / "jobs.sqlite3"),
                    admin_owner_password="long-owner-password",
                    admin_session_secret="long-session-secret-value",
                    admin_secret_master_key=MASTER_KEY,
                ),
                require_admin_provider_keys=True,
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["admin_db_path"], str(db_path))
            self.assertEqual(result["deepseek_active_key_count"], 1)
            self.assertNotIn("sk-admin-runtime", repr(result))
            connection = sqlite3.connect(db_path)
            try:
                probe_count = connection.execute(
                    "SELECT count(*) FROM admin_deployment_smoke_checks"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(probe_count, 1)

    def test_can_allow_initial_deploy_before_provider_keys_are_added(self):
        with TemporaryDirectory() as temp_dir:
            result = check_admin_runtime_configuration(
                Settings(
                    environment="production",
                    admin_db_path=str(Path(temp_dir) / "admin.sqlite3"),
                    persistent_jobs_db_path=str(Path(temp_dir) / "jobs.sqlite3"),
                    admin_owner_password="long-owner-password",
                    admin_session_secret="long-session-secret-value",
                    admin_secret_master_key=MASTER_KEY,
                ),
                require_admin_provider_keys=False,
            )

        self.assertEqual(result["deepseek_active_key_count"], 0)

    def test_existing_admin_db_mode_rejects_wrong_or_unmounted_path(self):
        with TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(AdminDeploymentCheckError, "does not exist"):
                check_admin_runtime_configuration(
                    Settings(
                        environment="production",
                        admin_db_path=str(Path(temp_dir) / "missing-admin.sqlite3"),
                        admin_owner_password="long-owner-password",
                        admin_session_secret="long-session-secret-value",
                        admin_secret_master_key=MASTER_KEY,
                    ),
                    require_existing_admin_db=True,
                )

    def test_validates_configured_scheduler_backend(self):
        with TemporaryDirectory() as temp_dir:
            fake_store = _FakeSchedulerStore()
            with patch(
                "translator_service.admin.deployment_smoke.open_persistent_job_store",
                return_value=fake_store,
            ) as open_store:
                result = check_admin_runtime_configuration(
                    Settings(
                        environment="production",
                        scheduler_backend="postgres",
                        postgres_dsn="postgresql://translator",
                        admin_db_path=str(Path(temp_dir) / "admin.sqlite3"),
                        admin_owner_password="long-owner-password",
                        admin_session_secret="long-session-secret-value",
                        admin_secret_master_key=MASTER_KEY,
                    )
                )

        open_store.assert_called_once()
        self.assertTrue(fake_store.closed)
        self.assertEqual(result["scheduler_backend"], "postgres")


class _FakeSchedulerStore:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


if __name__ == "__main__":
    unittest.main()
