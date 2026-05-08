import re
import unittest
from base64 import urlsafe_b64encode
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from translator_service.admin.secrets import SQLiteEncryptedSecretStore
from translator_service.api import create_app
from translator_service.config import Settings
from translator_service.translation_run_logs import (
    TranslationRunLogger,
    TranslationRunMetadata,
)
from translator_service.user_activity import (
    ActivityActorType,
    ActivityOutcome,
    ActivitySurface,
    SQLiteUserActivityStore,
    UserActivityEventInput,
)

MASTER_KEY = urlsafe_b64encode(b"2" * 32).decode("ascii")


class AdminRoutesTest(unittest.TestCase):
    def setUp(self):
        settings = Settings(
            admin_owner_password="owner-pass",
            admin_session_secret="session-secret",
        )
        self.client = TestClient(create_app(settings=settings))

    def test_admin_pages_require_login(self):
        response = self.client.get("/admin/overview", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_owner_can_login_and_open_admin_shell(self):
        login = self.client.post(
            "/admin/login",
            data={"password": "owner-pass"},
            follow_redirects=False,
        )

        self.assertEqual(login.status_code, 303)
        self.assertEqual(login.headers["location"], "/admin/overview")
        self.assertIn("folioloom_admin_session", login.headers["set-cookie"])

        overview = self.client.get("/admin/overview")

        self.assertEqual(overview.status_code, 200)
        self.assertIn("Overview", overview.text)
        self.assertIn("Integrations", overview.text)
        self.assertIn("AI Providers", overview.text)
        self.assertIn("Billing", overview.text)
        self.assertIn("Live", overview.text)
        self.assertIn("Settings", overview.text)
        self.assertEqual(overview.headers["cache-control"], "no-store")

    def test_invalid_login_is_rejected(self):
        response = self.client.post("/admin/login", data={"password": "wrong-pass"})

        self.assertEqual(response.status_code, 401)

    def test_core_console_sections_are_available_after_login(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        for path, label in (
            ("/admin/integrations", "Integrations"),
            ("/admin/ai-providers", "AI Providers"),
            ("/admin/billing", "Billing"),
            ("/admin/live", "Live Monitor"),
            ("/admin/logs", "Logs"),
            ("/admin/settings", "Settings"),
            ("/admin/operations/jobs", "Operations"),
            ("/admin/security/events", "Security"),
            ("/admin/audit", "Audit"),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 200)
                self.assertIn(label, response.text)

    def test_integrations_page_and_api_show_registry(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        page = self.client.get("/admin/integrations")
        api = self.client.get("/admin/api/integrations")

        self.assertEqual(page.status_code, 200)
        self.assertIn("Telegram", page.text)
        self.assertIn("Website Widget", page.text)
        self.assertNotIn("DeepSeek", page.text)
        self.assertNotIn("Stripe", page.text)
        self.assertEqual(api.status_code, 200)
        payload = api.json()
        integration_ids = {
            integration["integration_id"] for integration in payload["integrations"]
        }
        self.assertIn("telegram", integration_ids)
        self.assertIn("website_widget", integration_ids)
        self.assertNotIn("deepseek", integration_ids)
        self.assertNotIn("stripe", integration_ids)
        self.assertIn("connections", payload)

    def test_owner_can_add_and_remove_integration_connection_rows(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_db_path=db_path,
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                        admin_secret_master_key=MASTER_KEY,
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})
            page = client.get("/admin/integrations")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
            self.assertIsNotNone(csrf)

            stable = client.post(
                "/admin/integrations/telegram/connections",
                data={
                    "csrf_token": csrf.group(1),
                    "label": "stable",
                    "secret:telegram.bot_token": "111:stable-token",
                },
                follow_redirects=False,
            )
            dev = client.post(
                "/admin/integrations/telegram/connections",
                data={
                    "csrf_token": csrf.group(1),
                    "label": "dev",
                    "secret:telegram.bot_token": "222:dev-token",
                },
                follow_redirects=False,
            )

            self.assertEqual(stable.status_code, 303)
            self.assertEqual(dev.status_code, 303)
            updated = client.get("/admin/integrations")
            self.assertIn("<strong>stable</strong>", updated.text)
            self.assertIn("<strong>dev</strong>", updated.text)
            self.assertIn("111****oken", updated.text)
            self.assertNotIn("111:stable-token", updated.text)

            connection_ids = re.findall(
                r'name="connection_id"\s+value="([^"]+)"',
                updated.text,
            )
            self.assertEqual(len(connection_ids), 2)
            remove = client.post(
                "/admin/integrations/telegram/connections/remove",
                data={
                    "csrf_token": csrf.group(1),
                    "connection_id": connection_ids[0],
                },
                follow_redirects=False,
            )

            self.assertEqual(remove.status_code, 303)
            after_remove = client.get("/admin/integrations")
            self.assertNotIn("<strong>stable</strong>", after_remove.text)
            self.assertIn("<strong>dev</strong>", after_remove.text)

    def test_ai_providers_page_and_api_are_separate_from_integrations(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        page = self.client.get("/admin/ai-providers")
        api = self.client.get("/admin/api/ai-providers")

        self.assertEqual(page.status_code, 200)
        self.assertIn("DeepSeek", page.text)
        self.assertNotIn("Telegram bot token", page.text)
        self.assertEqual(api.status_code, 200)
        provider_ids = {
            provider["integration_id"] for provider in api.json()["providers"]
        }
        self.assertEqual(provider_ids, {"deepseek"})
        self.assertIn(
            'action="/admin/ai-providers/deepseek/keys"',
            page.text,
        )
        self.assertIn("Add key", page.text)

    def test_billing_shell_is_separate_from_integrations(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        response = self.client.get("/admin/billing")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Billing", response.text)
        self.assertIn("Payment providers", response.text)

    def test_operations_page_and_api_show_empty_overview(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        page = self.client.get("/admin/operations/jobs")
        api = self.client.get("/admin/api/operations/overview")

        self.assertEqual(page.status_code, 200)
        self.assertIn("Queue depth", page.text)
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.json()["overview"]["total_queue_depth"], 0)

    def test_translation_logs_page_and_api_filter_runs(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-logs-1",
                    order_id="order-1",
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                    translator_model="deepseek",
                ),
            )
            logger.finish(status="ready", result_file_name="book.ru.txt")
            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=temp_dir,
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            page = client.get("/admin/logs?status=ready")
            api = client.get("/admin/api/logs?status=ready")

            self.assertEqual(page.status_code, 200)
            self.assertIn("Translation Logs", page.text)
            self.assertIn("job-logs-1", page.text)
            self.assertIn("book.txt", page.text)
            self.assertIn("ready", page.text)
            self.assertNotIn("source_text", page.text)
            self.assertEqual(api.status_code, 200)
            payload = api.json()
            self.assertEqual(payload["logs"][0]["job_id"], "job-logs-1")
            self.assertEqual(payload["logs"][0]["status"], "ready")

    def test_activity_users_and_security_pages_show_user_events(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteUserActivityStore(db_path) as activity_store:
                activity_store.record_event(
                    UserActivityEventInput(
                        actor_type=ActivityActorType.USER,
                        actor_id="telegram:42",
                        channel="telegram",
                        channel_user_id="42",
                        surface=ActivitySurface.BOT,
                        event_type="translation.completed",
                        action="ready",
                        target_type="document",
                        target_id="book.txt",
                        outcome=ActivityOutcome.SUCCESS,
                        job_id="job-activity-1",
                        metadata={"result_file_name": "book.uk.txt"},
                    )
                )
                activity_store.record_event(
                    UserActivityEventInput(
                        actor_type=ActivityActorType.USER,
                        actor_id="telegram:42",
                        channel="telegram",
                        channel_user_id="42",
                        surface=ActivitySurface.SECURITY,
                        event_type="security.user_cooldown_started",
                        action="blocked",
                        outcome=ActivityOutcome.BLOCKED,
                        metadata={"security_state": "limited"},
                    )
                )
            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_db_path=str(db_path),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            activity_page = client.get("/admin/activity?job_id=job-activity-1")
            users_page = client.get("/admin/users")
            user_page = client.get("/admin/users/telegram:42")
            security_page = client.get("/admin/security/events")
            activity_api = client.get("/admin/api/activity?job_id=job-activity-1")
            users_api = client.get("/admin/api/users")

            self.assertEqual(activity_page.status_code, 200)
            self.assertIn("Activity", activity_page.text)
            self.assertIn("translation.completed", activity_page.text)
            self.assertIn("job-activity-1", activity_page.text)
            self.assertEqual(users_page.status_code, 200)
            self.assertIn("telegram:42", users_page.text)
            self.assertIn("limited", users_page.text)
            self.assertEqual(user_page.status_code, 200)
            self.assertIn("book.txt", user_page.text)
            self.assertEqual(security_page.status_code, 200)
            self.assertIn("security.user_cooldown_started", security_page.text)
            self.assertNotIn("translation.completed", security_page.text)
            self.assertEqual(activity_api.status_code, 200)
            self.assertEqual(
                activity_api.json()["events"][0]["job_id"],
                "job-activity-1",
            )
            self.assertEqual(users_api.status_code, 200)
            self.assertEqual(users_api.json()["users"][0]["user_id"], "telegram:42")

    def test_live_monitor_page_and_api_show_snapshot(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-live-1",
                    order_id="order-1",
                    user_id="telegram:42",
                    file_name="live-book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                ),
            )
            logger.finish(status="ready", result_file_name="live-book.ru.txt")
            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=temp_dir,
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            page = client.get("/admin/live")
            api = client.get("/admin/api/live")

            self.assertEqual(page.status_code, 200)
            self.assertIn("Live Monitor", page.text)
            self.assertIn("Active translations", page.text)
            self.assertIn("Tokens today", page.text)
            self.assertIn("Server health", page.text)
            self.assertEqual(api.status_code, 200)
            payload = api.json()
            self.assertEqual(payload["active_translations"], 0)
            self.assertEqual(payload["recent_runs"][0]["job_id"], "job-live-1")
            self.assertFalse(payload["server"]["available"])

    def test_owner_can_store_ai_provider_secret_with_csrf(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_db_path=db_path,
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                        admin_secret_master_key=MASTER_KEY,
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})
            overview = client.get("/admin/overview")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', overview.text)
            self.assertIsNotNone(csrf)

            response = client.post(
                "/admin/api/ai-providers/deepseek/secrets/deepseek.api_key",
                data={
                    "csrf_token": csrf.group(1),
                    "value": "sk-live-secret-value",
                },
            )

            self.assertEqual(response.status_code, 200)
            secret = response.json()["secret"]
            self.assertEqual(secret["secret_id"], "deepseek.api_key")
            self.assertEqual(secret["masked_value"], "sk-****alue")
            self.assertNotIn("sk-live-secret-value", str(response.json()))
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as store:
                self.assertEqual(
                store.get_secret_value("deepseek.api_key"),
                    "sk-live-secret-value",
                )

    def test_secret_json_endpoint_returns_masked_value(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_db_path=db_path,
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                        admin_secret_master_key=MASTER_KEY,
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})
            overview = client.get("/admin/overview")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', overview.text)
            self.assertIsNotNone(csrf)

            save = client.post(
                "/admin/api/ai-providers/deepseek/secrets/deepseek.api_key",
                data={
                    "csrf_token": csrf.group(1),
                    "value": "sk-live-secret-value",
                },
            )

            self.assertEqual(save.status_code, 200)
            self.assertEqual(save.json()["secret"]["masked_value"], "sk-****alue")
            self.assertNotIn("sk-live-secret-value", str(save.json()))

    def test_owner_can_add_and_remove_ai_provider_key_rows(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_db_path=db_path,
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                        admin_secret_master_key=MASTER_KEY,
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})
            page = client.get("/admin/ai-providers")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
            self.assertIsNotNone(csrf)

            first = client.post(
                "/admin/ai-providers/deepseek/keys",
                data={
                    "csrf_token": csrf.group(1),
                    "label": "main",
                    "value": "sk-main-secret",
                    "weight": "3",
                    "max_parallel_requests": "2",
                },
                follow_redirects=False,
            )
            second = client.post(
                "/admin/ai-providers/deepseek/keys",
                data={
                    "csrf_token": csrf.group(1),
                    "label": "backup",
                    "value": "sk-backup-secret",
                    "weight": "1",
                    "max_parallel_requests": "1",
                },
                follow_redirects=False,
            )

            self.assertEqual(first.status_code, 303)
            self.assertEqual(second.status_code, 303)
            updated = client.get("/admin/ai-providers")
            self.assertIn("<strong>main</strong>", updated.text)
            self.assertIn("<strong>backup</strong>", updated.text)
            self.assertIn("sk-****cret", updated.text)
            self.assertNotIn("sk-main-secret", updated.text)

            key_ids = re.findall(r'name="key_id" value="([^"]+)"', updated.text)
            self.assertEqual(len(key_ids), 2)
            remove = client.post(
                "/admin/ai-providers/deepseek/keys/remove",
                data={"csrf_token": csrf.group(1), "key_id": key_ids[0]},
                follow_redirects=False,
            )

            self.assertEqual(remove.status_code, 303)
            after_remove = client.get("/admin/ai-providers")
            self.assertNotIn("<strong>main</strong>", after_remove.text)
            self.assertIn("<strong>backup</strong>", after_remove.text)

    def test_mutating_actions_require_csrf(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        missing = self.client.post("/admin/logout", follow_redirects=False)

        self.assertEqual(missing.status_code, 403)

        overview = self.client.get("/admin/overview")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', overview.text)
        self.assertIsNotNone(csrf)

        logged_out = self.client.post(
            "/admin/logout",
            data={"csrf_token": csrf.group(1)},
            follow_redirects=False,
        )

        self.assertEqual(logged_out.status_code, 303)
        self.assertEqual(logged_out.headers["location"], "/admin/login")


if __name__ == "__main__":
    unittest.main()
