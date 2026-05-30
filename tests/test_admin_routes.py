import json
import re
import sqlite3
import unittest
from base64 import urlsafe_b64encode
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient

from translator_service.admin.audit import SQLiteAdminAuditLog
from translator_service.admin.costs import (
    CostAnalytics,
    CostRunSummary,
    CostUserSummary,
)
from translator_service.admin.provider_probe import AIProviderProbeResult
from translator_service.admin.provider_runtime import (
    AIProviderRuntimeChannel,
    AIProviderRuntimeProviderState,
    SQLiteAIProviderRuntimeStore,
)
from translator_service.admin.provider_validation import SQLiteAIProviderValidationStore
from translator_service.admin.secrets import SQLiteEncryptedSecretStore
from translator_service.api import create_app
from translator_service.beta_access import (
    BETA_ALLOWLIST_ENABLED_SETTING,
    BETA_ALLOWLIST_SETTING,
)
from translator_service.beta_safety import (
    BetaSafetyLimits,
    BetaSafetyRates,
    JobCostEstimate,
)
from translator_service.beta_safety_store import SQLiteBetaSafetyStore
from translator_service.config import Settings
from translator_service.persistent_jobs import SQLiteTranslationJobStore, WorkUnitPlan
from translator_service.translation_run_logs import (
    TranslationFragmentLog,
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


def _csrf_token(page_text: str) -> str:
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page_text)
    if csrf is None:
        raise AssertionError("CSRF token not found")
    return csrf.group(1)


def _admin_setting_row(db_path: str, key: str):
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(
            "SELECT value FROM admin_settings WHERE key = ?",
            (key,),
        ).fetchone()
    finally:
        connection.close()

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

    def test_admin_overview_does_not_build_action_center_without_login(self):
        with patch(
            "translator_service.admin.routes._overview_action_center",
            side_effect=AssertionError("overview action center should be lazy"),
        ):
            response = self.client.get("/admin/overview", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_admin_operations_does_not_build_overview_without_login(self):
        with patch(
            "translator_service.admin.routes._operations_overview",
            side_effect=AssertionError("operations overview should be lazy"),
        ):
            response = self.client.get(
                "/admin/operations/jobs",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_admin_live_does_not_build_snapshot_without_login(self):
        with patch(
            "translator_service.admin.routes._live_snapshot",
            side_effect=AssertionError("live snapshot should be lazy"),
        ):
            response = self.client.get("/admin/live", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_admin_logs_do_not_read_runs_without_login(self):
        with patch(
            "translator_service.admin.routes.list_translation_run_summaries",
            side_effect=AssertionError("translation logs should be lazy"),
        ):
            response = self.client.get("/admin/logs", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_admin_translation_trace_does_not_read_run_without_login(self):
        with patch(
            "translator_service.admin.routes.get_translation_run_details",
            side_effect=AssertionError("translation trace should be lazy"),
        ):
            response = self.client.get(
                "/admin/translations/run-1/trace",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_admin_translation_evidence_does_not_read_run_without_login(self):
        with patch(
            "translator_service.admin.routes.get_translation_run_details",
            side_effect=AssertionError("translation evidence should be lazy"),
        ):
            response = self.client.get(
                "/admin/translations/run-1/evidence",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_admin_activity_users_and_security_do_not_read_activity_without_login(self):
        for path in (
            "/admin/activity",
            "/admin/users",
            "/admin/users/telegram:42",
            "/admin/security/events",
        ):
            with self.subTest(path=path):
                with patch(
                    "translator_service.admin.routes._activity_store",
                    side_effect=AssertionError("activity store should be lazy"),
                ):
                    response = self.client.get(path, follow_redirects=False)

                self.assertEqual(response.status_code, 303)
                self.assertEqual(response.headers["location"], "/admin/login")

    def test_admin_costs_does_not_build_analytics_without_login(self):
        with patch(
            "translator_service.admin.routes._cost_analytics",
            side_effect=AssertionError("cost analytics should be lazy"),
        ):
            response = self.client.get("/admin/costs", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_admin_costs_api_does_not_build_analytics_without_login(self):
        with patch(
            "translator_service.admin.routes._cost_analytics",
            side_effect=AssertionError("cost analytics should be lazy"),
        ) as analytics:
            response = self.client.get("/admin/api/costs")

        self.assertEqual(response.status_code, 401)
        analytics.assert_not_called()

    def test_admin_balance_api_requires_login(self):
        with patch(
            "translator_service.admin.routes._deepseek_balance_snapshot",
            side_effect=AssertionError("balance snapshot should be lazy"),
        ) as snapshot:
            response = self.client.get("/admin/api/ai-providers/deepseek/balance")

        self.assertEqual(response.status_code, 401)
        snapshot.assert_not_called()

    def test_deepseek_keys_page_does_not_build_inventory_without_login(self):
        with patch(
            "translator_service.admin.routes._ai_provider_key_pools",
            side_effect=AssertionError("key inventory should be lazy"),
        ):
            response = self.client.get(
                "/admin/ai-providers/deepseek/keys",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_owner_can_read_cached_deepseek_balance(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        with patch(
            "translator_service.admin.routes._deepseek_balance_payload",
            return_value={"provider_id": "deepseek", "status": "not_configured"},
        ):
            response = self.client.get("/admin/api/ai-providers/deepseek/balance")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["balance"]["status"], "not_configured")

    def test_refresh_deepseek_balance_requires_csrf(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        response = self.client.post(
            "/admin/ai-providers/deepseek/balance/refresh",
            data={"csrf_token": "bad"},
        )

        self.assertEqual(response.status_code, 403)

    def test_owner_can_refresh_deepseek_balance(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})
        page = self.client.get("/admin/ai-providers")
        csrf = _csrf_token(page.text)

        with patch(
            "translator_service.admin.routes.refresh_deepseek_balance",
        ) as refresh:
            refresh.return_value = SimpleNamespace(
                provider_id="deepseek",
                status="available",
                is_available=True,
                balances=(SimpleNamespace(currency="USD"),),
                last_checked_at=datetime(2026, 5, 9, tzinfo=UTC),
                last_success_at=datetime(2026, 5, 9, tzinfo=UTC),
                error_code=None,
                error_message=None,
            )
            response = self.client.post(
                "/admin/ai-providers/deepseek/balance/refresh",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/ai-providers")
        refresh.assert_called_once()

    def test_ai_providers_page_renders_deepseek_balance_panel(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        with patch(
            "translator_service.admin.routes._deepseek_balance_snapshot",
        ) as snapshot:
            snapshot.return_value = SimpleNamespace(
                provider_id="deepseek",
                status="available",
                is_available=True,
                balances=(
                    SimpleNamespace(
                        currency="USD",
                        total_balance=Decimal("8.50"),
                        granted_balance=Decimal("0"),
                        topped_up_balance=Decimal("8.50"),
                    ),
                ),
                last_checked_at=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
                last_success_at=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
                error_code=None,
                error_message=None,
            )
            response = self.client.get("/admin/ai-providers")
            api = self.client.get("/admin/api/ai-providers/deepseek/balance")

        self.assertEqual(response.status_code, 200)
        self.assertIn("DeepSeek account balance", response.text)
        self.assertIn("8.50", response.text)
        self.assertIn("Refresh balance", response.text)
        self.assertNotIn("sk-", response.text)
        self.assertEqual(api.status_code, 200)
        self.assertIsNone(api.json()["balance"]["error_message"])

    def test_deepseek_balance_error_is_redacted_in_admin_output(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})
        raw_key = "sk-balance-secret-value"
        raw_bearer = "Bearer balance-bearer-token-value"
        raw_secret_id = "deepseek.api_keys.balance-key"

        with patch(
            "translator_service.admin.routes._deepseek_balance_snapshot",
        ) as snapshot:
            snapshot.return_value = SimpleNamespace(
                provider_id="deepseek",
                status="provider_error",
                is_available=None,
                balances=(),
                last_checked_at=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
                last_success_at=None,
                error_code="provider_error",
                error_message=(
                    f"DeepSeek rejected {raw_bearer}; api_key={raw_key}; "
                    f"secret_id={raw_secret_id}"
                ),
            )
            page = self.client.get("/admin/ai-providers")
            api = self.client.get("/admin/api/ai-providers/deepseek/balance")

        serialized = page.text + api.text
        self.assertEqual(page.status_code, 200)
        self.assertEqual(api.status_code, 200)
        self.assertIn("[redacted]", serialized)
        self.assertNotIn(raw_key, serialized)
        self.assertNotIn(raw_bearer, serialized)
        self.assertNotIn(raw_secret_id, serialized)
        self.assertNotIn(".api_keys.", serialized)

    def test_deepseek_keys_page_renders_key_management_surface(self):
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

            response = client.get("/admin/ai-providers/deepseek/keys")

        self.assertEqual(response.status_code, 200)
        self.assertIn("DeepSeek Keys", response.text)
        self.assertIn('action="/admin/ai-providers/deepseek/keys"', response.text)
        self.assertIn("Add admin-managed key", response.text)
        self.assertIn("Field guide", response.text)
        self.assertIn("Ready admin keys", response.text)
        self.assertIn("Paused admin keys", response.text)
        self.assertIn("Read-only env keys", response.text)
        self.assertIn("Max parallel requests", response.text)
        self.assertIn("stored encrypted", response.text)
        self.assertIn("Test all active keys", response.text)
        self.assertIn("Reload DeepSeek runtime", response.text)

    def test_admin_quality_does_not_build_summary_without_login(self):
        with patch(
            "translator_service.admin.routes._quality_run_summary",
            side_effect=AssertionError("quality summary should be lazy"),
        ):
            response = self.client.get("/admin/quality", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_admin_quality_api_does_not_build_summary_without_login(self):
        with patch(
            "translator_service.admin.routes._quality_run_summary",
            side_effect=AssertionError("quality summary should be lazy"),
        ) as quality:
            response = self.client.get("/admin/api/quality")

        self.assertEqual(response.status_code, 401)
        quality.assert_not_called()

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
        self.assertIn("Costs", overview.text)
        self.assertIn("Quality", overview.text)
        self.assertIn("Live", overview.text)
        self.assertIn("Settings", overview.text)
        self.assertEqual(overview.headers["cache-control"], "no-store")

    def test_owner_can_add_view_and_remove_beta_allowlist_ids_from_settings(self):
        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                admin_db_path=str(Path(temp_dir) / "admin.sqlite3"),
                admin_owner_password="owner-pass",
                admin_session_secret="session-secret",
            )
            client = TestClient(create_app(settings=settings))
            client.post("/admin/login", data={"password": "owner-pass"})
            page = client.get("/admin/settings")
            csrf = _csrf_token(page.text)

            add_response = client.post(
                "/admin/settings/beta-allowlist/add",
                data={
                    "csrf_token": csrf,
                    "telegram_id": "42",
                },
                follow_redirects=False,
            )

            self.assertEqual(add_response.status_code, 303)
            self.assertEqual(add_response.headers["location"], "/admin/settings")
            listing = client.get("/admin/settings")
            self.assertIn("Allowlist enforcement: off", listing.text)
            self.assertIn("Allowed Telegram IDs", listing.text)
            self.assertIn("<code>42</code>", listing.text)
            self.assertNotIn("<textarea", listing.text)

            remove_csrf = _csrf_token(listing.text)
            remove_response = client.post(
                "/admin/settings/beta-allowlist/remove",
                data={
                    "csrf_token": remove_csrf,
                    "telegram_id": "42",
                },
                follow_redirects=False,
            )

            self.assertEqual(remove_response.status_code, 303)
            self.assertEqual(remove_response.headers["location"], "/admin/settings")
            row = _admin_setting_row(settings.admin_db_path, BETA_ALLOWLIST_SETTING.key)

        self.assertEqual(row[0], "")

    def test_owner_can_toggle_beta_allowlist_enforcement(self):
        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                admin_db_path=str(Path(temp_dir) / "admin.sqlite3"),
                admin_owner_password="owner-pass",
                admin_session_secret="session-secret",
            )
            client = TestClient(create_app(settings=settings))
            client.post("/admin/login", data={"password": "owner-pass"})
            page = client.get("/admin/settings")
            csrf = _csrf_token(page.text)

            enable = client.post(
                "/admin/settings/beta-allowlist/toggle",
                data={"csrf_token": csrf, "enabled": "true"},
                follow_redirects=False,
            )
            enabled_listing = client.get("/admin/settings")
            disable_csrf = _csrf_token(enabled_listing.text)
            disable = client.post(
                "/admin/settings/beta-allowlist/toggle",
                data={"csrf_token": disable_csrf, "enabled": "false"},
                follow_redirects=False,
            )
            row = _admin_setting_row(
                settings.admin_db_path,
                BETA_ALLOWLIST_ENABLED_SETTING.key,
            )

        self.assertEqual(enable.status_code, 303)
        self.assertIn("Allowlist enforcement: on", enabled_listing.text)
        self.assertEqual(disable.status_code, 303)
        self.assertEqual(row[0], "false")

    def test_owner_cannot_add_invalid_beta_allowlist_id(self):
        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                admin_db_path=str(Path(temp_dir) / "admin.sqlite3"),
                admin_owner_password="owner-pass",
                admin_session_secret="session-secret",
            )
            client = TestClient(create_app(settings=settings))
            client.post("/admin/login", data={"password": "owner-pass"})
            csrf = _csrf_token(client.get("/admin/settings").text)

            response = client.post(
                "/admin/settings/beta-allowlist/add",
                data={
                    "csrf_token": csrf,
                    "telegram_id": "not-a-number",
                },
            )

        self.assertEqual(response.status_code, 400)

    def test_settings_page_renders_and_updates_beta_safety_controls(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            settings = Settings(
                admin_db_path=db_path,
                admin_owner_password="owner-pass",
                admin_session_secret="session-secret",
            )
            client = TestClient(create_app(settings=settings))
            client.post("/admin/login", data={"password": "owner-pass"})
            page = client.get("/admin/settings")

            self.assertIn("Beta Safety Controls", page.text)
            self.assertIn("Pause all beta translations", page.text)
            self.assertIn("Global daily cost cap USD", page.text)

            response = client.post(
                "/admin/settings/beta-safety",
                data={
                    "csrf_token": _csrf_token(page.text),
                    "BETA_TRANSLATIONS_PAUSED": "true",
                    "BETA_GLOBAL_DAILY_COST_CAP_USD": "3.25",
                    "BETA_GLOBAL_MONTHLY_COST_CAP_USD": "33.00",
                    "BETA_USER_DAILY_COST_CAP_USD": "0.75",
                    "BETA_USER_MONTHLY_COST_CAP_USD": "7.50",
                    "BETA_USER_DAILY_JOB_LIMIT": "2",
                    "BETA_MAX_JOB_ESTIMATED_COST_USD": "1.25",
                    "BETA_COST_WARNING_FRACTION": "0.60",
                },
                follow_redirects=False,
            )
            updated = client.get("/admin/settings")

            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/admin/settings")
            self.assertIn('name="BETA_TRANSLATIONS_PAUSED" checked', updated.text)
            self.assertIn(
                'name="BETA_GLOBAL_DAILY_COST_CAP_USD" type="number" value="3.25"',
                updated.text,
            )
            self.assertEqual(
                _admin_setting_row(db_path, "BETA_TRANSLATIONS_PAUSED")[0],
                "true",
            )

            unpause = client.post(
                "/admin/settings/beta-safety",
                data={
                    "csrf_token": _csrf_token(updated.text),
                    "BETA_GLOBAL_DAILY_COST_CAP_USD": "4.00",
                    "BETA_GLOBAL_MONTHLY_COST_CAP_USD": "44.00",
                    "BETA_USER_DAILY_COST_CAP_USD": "0.80",
                    "BETA_USER_MONTHLY_COST_CAP_USD": "8.00",
                    "BETA_USER_DAILY_JOB_LIMIT": "3",
                    "BETA_MAX_JOB_ESTIMATED_COST_USD": "1.50",
                    "BETA_COST_WARNING_FRACTION": "0.70",
                },
                follow_redirects=False,
            )

            self.assertEqual(unpause.status_code, 303)
            self.assertEqual(
                _admin_setting_row(db_path, "BETA_TRANSLATIONS_PAUSED")[0],
                "false",
            )

    def test_invalid_beta_safety_settings_do_not_partially_save(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_db_path=db_path,
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})
            page = client.get("/admin/settings")

            response = client.post(
                "/admin/settings/beta-safety",
                data={
                    "csrf_token": _csrf_token(page.text),
                    "BETA_TRANSLATIONS_PAUSED": "true",
                    "BETA_GLOBAL_DAILY_COST_CAP_USD": "-1.00",
                    "BETA_GLOBAL_MONTHLY_COST_CAP_USD": "50.00",
                    "BETA_USER_DAILY_COST_CAP_USD": "1.00",
                    "BETA_USER_MONTHLY_COST_CAP_USD": "10.00",
                    "BETA_USER_DAILY_JOB_LIMIT": "3",
                    "BETA_MAX_JOB_ESTIMATED_COST_USD": "2.00",
                    "BETA_COST_WARNING_FRACTION": "0.80",
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIsNone(
                _admin_setting_row(db_path, "BETA_TRANSLATIONS_PAUSED")
            )
            with SQLiteAdminAuditLog(db_path) as audit:
                events = audit.list_events(limit=5)
            self.assertNotIn(
                "settings.beta_safety.updated",
                {event.action for event in events},
            )

    def test_incomplete_beta_safety_settings_do_not_reset_existing_values(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_db_path=db_path,
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})
            page = client.get("/admin/settings")
            complete = client.post(
                "/admin/settings/beta-safety",
                data={
                    "csrf_token": _csrf_token(page.text),
                    "BETA_TRANSLATIONS_PAUSED": "true",
                    "BETA_GLOBAL_DAILY_COST_CAP_USD": "3.25",
                    "BETA_GLOBAL_MONTHLY_COST_CAP_USD": "33.00",
                    "BETA_USER_DAILY_COST_CAP_USD": "0.75",
                    "BETA_USER_MONTHLY_COST_CAP_USD": "7.50",
                    "BETA_USER_DAILY_JOB_LIMIT": "2",
                    "BETA_MAX_JOB_ESTIMATED_COST_USD": "1.25",
                    "BETA_COST_WARNING_FRACTION": "0.60",
                },
            )
            self.assertEqual(complete.status_code, 200)
            updated = client.get("/admin/settings")

            incomplete = client.post(
                "/admin/settings/beta-safety",
                data={
                    "csrf_token": _csrf_token(updated.text),
                    "BETA_TRANSLATIONS_PAUSED": "false",
                    "BETA_GLOBAL_DAILY_COST_CAP_USD": "4.00",
                },
            )

            self.assertEqual(incomplete.status_code, 400)
            self.assertEqual(
                _admin_setting_row(db_path, "BETA_TRANSLATIONS_PAUSED")[0],
                "true",
            )
            self.assertEqual(
                _admin_setting_row(db_path, "BETA_GLOBAL_DAILY_COST_CAP_USD")[0],
                "3.25",
            )

    def test_login_cookie_can_be_marked_secure_for_deployment(self):
        client = TestClient(
            create_app(
                settings=Settings(
                    admin_owner_password="owner-pass",
                    admin_session_secret="session-secret",
                    admin_cookie_secure=True,
                )
            )
        )

        login = client.post(
            "/admin/login",
            data={"password": "owner-pass"},
            follow_redirects=False,
        )

        self.assertEqual(login.status_code, 303)
        self.assertIn("Secure", login.headers["set-cookie"])

    def test_admin_shell_shows_environment_badge(self):
        client = TestClient(
            create_app(
                settings=Settings(
                    environment="stable",
                    admin_owner_password="owner-pass",
                    admin_session_secret="session-secret",
                )
            )
        )
        client.post("/admin/login", data={"password": "owner-pass"})

        response = client.get("/admin/overview")

        self.assertEqual(response.status_code, 200)
        self.assertIn("stable", response.text)
        self.assertIn("environment-badge", response.text)

    def test_overview_renders_action_center(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        response = self.client.get("/admin/overview")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Action Center", response.text)
        self.assertIn("integrations_missing", response.text)
        self.assertIn("/admin/integrations", response.text)
        self.assertNotIn("pending actions will live here", response.text)

    def test_overview_action_center_redacts_deepseek_balance_error(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})
        raw_key = "sk-overview-balance-secret"
        raw_bearer = "Bearer overview-bearer-token"
        raw_secret_id = "deepseek.api_keys.overview-key"

        with patch(
            "translator_service.admin.routes._deepseek_balance_snapshot",
        ) as snapshot:
            snapshot.return_value = SimpleNamespace(
                provider_id="deepseek",
                status="failed",
                is_available=None,
                balances=(),
                last_checked_at=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
                last_success_at=None,
                error_code="provider_error",
                error_message=(
                    f"DeepSeek rejected {raw_bearer}; api_key={raw_key}; "
                    f"secret_id={raw_secret_id}"
                ),
            )
            response = self.client.get("/admin/overview")

        self.assertEqual(response.status_code, 200)
        self.assertIn("DeepSeek balance check failed", response.text)
        self.assertIn("[redacted]", response.text)
        self.assertNotIn(raw_key, response.text)
        self.assertNotIn(raw_bearer, response.text)
        self.assertNotIn(raw_secret_id, response.text)
        self.assertNotIn(".api_keys.", response.text)

    def test_overview_flags_runtime_not_reporting_when_keys_exist(self):
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
            add = client.post(
                "/admin/ai-providers/deepseek/keys",
                data={
                    "csrf_token": csrf.group(1),
                    "label": "main",
                    "value": "sk-main-secret",
                    "weight": "1",
                    "max_parallel_requests": "1",
                },
                follow_redirects=False,
            )
            self.assertEqual(add.status_code, 303)

            overview = client.get("/admin/overview")

            self.assertIn("DeepSeek runtime is not reporting", overview.text)
            self.assertNotIn("sk-main-secret", overview.text)

    def test_invalid_login_is_rejected(self):
        response = self.client.post("/admin/login", data={"password": "wrong-pass"})

        self.assertEqual(response.status_code, 401)

    def test_core_console_sections_are_available_after_login(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        for path, label in (
            ("/admin/integrations", "Integrations"),
            ("/admin/ai-providers", "AI Providers"),
            ("/admin/billing", "Billing"),
            ("/admin/costs", "Costs"),
            ("/admin/quality", "Quality"),
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

    def test_quality_page_and_api_show_empty_state_without_run_file(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        page = self.client.get("/admin/quality")
        api = self.client.get("/admin/api/quality")

        self.assertEqual(page.status_code, 200)
        self.assertIn("Translation Quality", page.text)
        self.assertIn("No quality run found", page.text)
        self.assertIn("Russian (ru)", page.text)
        self.assertIn("Ukrainian (uk)", page.text)
        self.assertNotIn("translated_text", page.text)
        self.assertNotIn("reference_translation", page.text)
        self.assertEqual(api.status_code, 200)
        payload = api.json()["quality"]
        self.assertFalse(payload["found"])
        self.assertGreaterEqual(payload["total_reference_samples"], 5)
        self.assertNotIn("translated_text", api.text)
        self.assertNotIn("reference_translation", api.text)

    def test_quality_page_can_start_quality_run(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})
        page = self.client.get("/admin/quality")
        csrf = _csrf_token(page.text)

        with patch(
            "translator_service.admin.routes._run_quality_check",
        ) as quality_run:
            quality_run.return_value = SimpleNamespace(
                candidate_path="var/quality-runs/latest.jsonl",
                total_samples=5,
                translated_samples=5,
                failed_samples=0,
            )
            response = self.client.post(
                "/admin/quality/run",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/quality")
        quality_run.assert_called_once()

    def test_quality_run_rejects_invalid_csrf(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        with patch(
            "translator_service.admin.routes._run_quality_check",
            side_effect=AssertionError("should not run"),
        ):
            response = self.client.post(
                "/admin/quality/run",
                data={"csrf_token": "bad"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 403)

    def test_settings_page_renders_secret_safety_center(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        response = self.client.get("/admin/settings")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Secret &amp; Config Safety", response.text)
        self.assertIn("Safety summary", response.text)
        self.assertIn("Missing", response.text)
        self.assertIn("Needs check", response.text)
        self.assertIn("Telegram", response.text)
        self.assertNotIn("telegram.bot_token", response.text)
        self.assertNotIn("deepseek.api_keys", response.text)

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
        self.assertIn("Provider health", page.text)
        self.assertIn("Processing summary", page.text)
        self.assertIn("Read-only diagnostics", page.text)
        self.assertIn("Active key channels", page.text)
        self.assertIn("Available capacity slots", page.text)
        self.assertIn("Provider warning counts", page.text)
        self.assertIn("Unknown", page.text)
        self.assertIn("Active keys", page.text)
        self.assertIn("Disabled keys", page.text)
        self.assertIn("Last validation", page.text)
        self.assertIn("Test key", page.text)
        self.assertIn("Add key", page.text)

    def test_ai_providers_overview_links_to_deepseek_key_management(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        response = self.client.get("/admin/ai-providers")

        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/admin/ai-providers/deepseek/keys"', response.text)
        self.assertIn("Manage DeepSeek keys", response.text)
        self.assertNotIn("Last validation: not checked", response.text)

    def test_env_bootstrap_secrets_are_visible_without_raw_secret_values(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            with patch.dict(
                "os.environ",
                {
                    "DEEPSEEK_API_KEYS": "sk-env-first, sk-env-second",
                    "TELEGRAM_BOT_TOKEN": "telegram-env-token",
                },
            ):
                client = TestClient(
                    create_app(
                        settings=Settings(
                            admin_db_path=db_path,
                            admin_owner_password="owner-pass",
                            admin_session_secret="session-secret",
                        )
                    )
                )
                client.post("/admin/login", data={"password": "owner-pass"})

                overview = client.get("/admin/overview")
                integrations = client.get("/admin/integrations")
                ai_providers = client.get("/admin/ai-providers")
                deepseek_keys = client.get("/admin/ai-providers/deepseek/keys")
                settings = client.get("/admin/settings")

            for response in (
                overview,
                integrations,
                ai_providers,
                deepseek_keys,
                settings,
            ):
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("sk-env-first", response.text)
                self.assertNotIn("sk-env-second", response.text)
                self.assertNotIn("telegram-env-token", response.text)
            self.assertNotIn("DeepSeek keys missing", overview.text)
            self.assertNotIn("Required integrations need setup", overview.text)
            self.assertNotIn("env fallback", integrations.text)
            self.assertIn("server .env", integrations.text)
            self.assertIn("1 active connection", integrations.text)
            self.assertIn("read-only", integrations.text)
            self.assertIn("server .env (2 keys)", ai_providers.text)
            self.assertIn("Read-only env keys", deepseek_keys.text)
            self.assertIn("read-only server environment key", deepseek_keys.text)
            self.assertIn("Read-only metadata", deepseek_keys.text)
            self.assertIn("Max parallel requests", deepseek_keys.text)
            self.assertIn("server .env", settings.text)
            self.assertIn("<td>DeepSeek</td>", settings.text)
            self.assertIn("<td>Telegram / server .env</td>", settings.text)

    def test_billing_shell_is_separate_from_integrations(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        response = self.client.get("/admin/billing")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Billing", response.text)
        self.assertIn("Payment providers", response.text)

    def test_costs_page_and_api_show_token_spend(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        with patch(
            "translator_service.admin.routes._cost_analytics",
            return_value=_cost_analytics_fixture(),
        ):
            page = self.client.get("/admin/costs")
            api = self.client.get("/admin/api/costs")

        self.assertEqual(page.status_code, 200)
        self.assertIn("Token Spend", page.text)
        self.assertIn("Top users (all time)", page.text)
        self.assertIn("job-costs-1", page.text)
        self.assertIn("telegram:42", page.text)
        self.assertIn("$0.0025", page.text)
        self.assertNotIn("source_text", page.text)
        self.assertNotIn("https://example.test/logs", page.text)
        self.assertIn('href="/admin/logs"', page.text)
        self.assertEqual(api.status_code, 200)
        payload = api.json()
        self.assertEqual(payload["tokens_today"], 3000)
        self.assertEqual(payload["tokens_last_7_days"], 3000)
        self.assertEqual(payload["tokens_month_to_date"], 3000)
        self.assertEqual(payload["estimated_cost_today_usd"], 0.00248)
        self.assertEqual(payload["top_runs"][0]["job_id"], "job-costs-1")
        self.assertEqual(payload["top_runs"][0]["estimated_cost_usd"], 0.00248)
        self.assertEqual(payload["top_users"][0]["user_id"], "telegram:42")
        self.assertEqual(payload["top_users"][0]["estimated_cost_usd"], 0.00248)

    def test_costs_page_and_api_include_beta_safety_summary(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            settings = Settings(
                admin_db_path=db_path,
                translation_run_log_root=str(Path(temp_dir) / "runs"),
                admin_owner_password="owner-pass",
                admin_session_secret="session-secret",
            )
            now = datetime.now(UTC)
            with SQLiteBetaSafetyStore(db_path) as store:
                store.reserve_job(
                    "job-reserved",
                    "telegram:42",
                    JobCostEstimate(
                        prompt_tokens=100,
                        completion_tokens=100,
                        estimated_cost_usd=0.8,
                    ),
                    BetaSafetyLimits(),
                    BetaSafetyRates(),
                    now=now,
                )
                store.record_work_unit_usage(
                    "job-consumed",
                    "telegram:77",
                    "unit-1",
                    prompt_tokens=1_000_000,
                    completion_tokens=0,
                    rates=BetaSafetyRates(input_usd_per_million=0.2),
                    now=now,
                )
            client = TestClient(create_app(settings=settings))
            client.post("/admin/login", data={"password": "owner-pass"})

            page = client.get("/admin/costs")
            api = client.get("/admin/api/costs")

            self.assertEqual(page.status_code, 200)
            self.assertIn("Beta safety budget", page.text)
            self.assertIn("Translations paused", page.text)
            self.assertEqual(api.status_code, 200)
            payload = api.json()["beta_safety"]
            self.assertEqual(payload["global_daily_cap_usd"], 5.0)
            self.assertEqual(payload["global_daily_reserved_usd"], 0.8)
            self.assertEqual(payload["global_daily_consumed_usd"], 0.2)
            self.assertEqual(payload["global_daily_remaining_usd"], 4.0)
            self.assertFalse(payload["translations_paused"])
            self.assertFalse(payload["warning"])

    def test_beta_safety_admin_views_and_api_do_not_expose_raw_document_text(self):
        raw_text = "SECRET RAW DOCUMENT TEXT SHOULD NOT APPEAR"
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            settings = Settings(
                admin_db_path=db_path,
                translation_run_log_root=str(Path(temp_dir) / "runs"),
                admin_owner_password="owner-pass",
                admin_session_secret="session-secret",
            )
            with SQLiteBetaSafetyStore(db_path) as store:
                store.reserve_job(
                    "job-secret",
                    "telegram:42",
                    JobCostEstimate(
                        prompt_tokens=100,
                        completion_tokens=100,
                        estimated_cost_usd=0.1,
                    ),
                    BetaSafetyLimits(),
                    BetaSafetyRates(),
                    now=datetime.now(UTC),
                )
            client = TestClient(create_app(settings=settings))
            client.post("/admin/login", data={"password": "owner-pass"})

            costs_page = client.get("/admin/costs")
            live_page = client.get("/admin/live")
            costs_api = client.get("/admin/api/costs")

            self.assertEqual(costs_page.status_code, 200)
            self.assertEqual(live_page.status_code, 200)
            self.assertEqual(costs_api.status_code, 200)
            self.assertNotIn(raw_text, costs_page.text)
            self.assertNotIn(raw_text, live_page.text)
            self.assertNotIn(raw_text, costs_api.text)
            self.assertNotIn("source_text", costs_api.text)
            self.assertNotIn("translated_text", costs_api.text)

    def test_operations_page_and_api_show_empty_overview(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        page = self.client.get("/admin/operations/jobs")
        api = self.client.get("/admin/api/operations/overview")

        self.assertEqual(page.status_code, 200)
        self.assertIn("Queue depth", page.text)
        self.assertIn("Oldest pending", page.text)
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.json()["overview"]["total_queue_depth"], 0)
        self.assertIsNone(api.json()["overview"]["oldest_pending_age_seconds"])

    def test_operations_page_and_api_show_persistent_jobs_and_logs(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "jobs.sqlite3"
            log_root = Path(temp_dir) / "translation-runs"
            store = SQLiteTranslationJobStore(db_path)
            queued = _persistent_job(store, order_id="order-queued")
            running = _persistent_job(store, order_id="order-running")
            ready = _persistent_job(store, order_id="order-ready")
            _add_units(store, queued.id)
            _add_units(store, running.id)
            _add_units(store, ready.id)
            store.claim_next_work_unit(running.id, worker_id="worker-a")
            ready_unit = store.claim_next_work_unit(ready.id, worker_id="worker-ready")
            store.complete_work_unit(
                ready_unit.id,
                translated_text="translated",
                prompt_tokens=12,
                completion_tokens=9,
                cache_hit_tokens=0,
                cache_miss_tokens=0,
            )
            store.close()
            logger = TranslationRunLogger.start(
                root=log_root,
                metadata=TranslationRunMetadata(
                    job_id=ready.id,
                    order_id=ready.order_id,
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    translator_model="deepseek",
                ),
            )
            logger.finish(status="ready", result_file_name="book.uk.txt")
            client = TestClient(
                create_app(
                    settings=Settings(
                        persistent_jobs_db_path=str(db_path),
                        translation_run_log_root=str(log_root),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            page = client.get("/admin/operations/jobs")
            api = client.get("/admin/api/operations/overview")

            self.assertEqual(page.status_code, 200)
            self.assertIn("order-queued", page.text)
            self.assertIn("worker-a", page.text)
            self.assertIn("21", page.text)
            self.assertIn(
                f'href="/admin/translations/{logger.run_dir.name}/trace"',
                page.text,
            )
            self.assertIn("Pause", page.text)
            self.assertIn("Cancel", page.text)
            self.assertIn("Delete", page.text)
            self.assertIn("Queue depth", page.text)
            self.assertIn("Oldest pending", page.text)
            self.assertNotIn("source_text", page.text)
            self.assertNotIn("translated", page.text)
            self.assertNotIn("sk-live-secret-value", page.text)
            self.assertEqual(api.status_code, 200)
            self.assertNotIn("translated", api.text)
            self.assertEqual(api.json()["overview"]["total_queue_depth"], 1)
            self.assertIsNotNone(api.json()["overview"]["oldest_pending_age_seconds"])
            jobs = api.json()["overview"]["jobs"]
            by_order = {job["order_id"]: job for job in jobs}
            self.assertEqual(
                by_order["order-running"]["active_worker_ids"],
                ["worker-a"],
            )
            self.assertEqual(by_order["order-ready"]["total_tokens"], 21)
            self.assertEqual(
                by_order["order-ready"]["log_href"],
                f"/admin/logs/{logger.run_dir.name}",
            )

    def test_operations_page_and_api_include_cancelled_and_expired_jobs(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "jobs.sqlite3"
            store = SQLiteTranslationJobStore(db_path)
            cancelled = _persistent_job(store, order_id="order-cancelled")
            expired = _persistent_job(store, order_id="order-expired")
            store.cancel_job(cancelled.id)
            store._connection.execute(
                "UPDATE translation_jobs SET status = ? WHERE id = ?",
                ("expired", expired.id),
            )
            store._connection.commit()
            store.close()
            client = TestClient(
                create_app(
                    settings=Settings(
                        persistent_jobs_db_path=str(db_path),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            page = client.get("/admin/operations/jobs")
            api = client.get("/admin/api/operations/overview")

            self.assertEqual(page.status_code, 200)
            self.assertIn("order-cancelled", page.text)
            self.assertIn("order-expired", page.text)
            by_order = {job["order_id"]: job for job in api.json()["overview"]["jobs"]}
            self.assertEqual(by_order["order-cancelled"]["state"], "cancelled")
            self.assertEqual(by_order["order-expired"]["state"], "failed")

    def test_admin_can_pause_cancel_and_delete_active_translation_jobs(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "jobs.sqlite3"
            admin_db_path = Path(temp_dir) / "admin.sqlite3"
            store = SQLiteTranslationJobStore(db_path)
            paused_job = _persistent_job(store, order_id="order-pause")
            cancelled_job = _persistent_job(store, order_id="order-cancel")
            deleted_job = _persistent_job(store, order_id="order-delete")
            _add_units(store, paused_job.id)
            _add_units(store, cancelled_job.id)
            _add_units(store, deleted_job.id)
            store.claim_next_work_unit(paused_job.id, worker_id="worker-pause")
            store.claim_next_work_unit(cancelled_job.id, worker_id="worker-cancel")
            store.claim_next_work_unit(deleted_job.id, worker_id="worker-delete")
            store.close()
            client = TestClient(
                create_app(
                    settings=Settings(
                        persistent_jobs_db_path=str(db_path),
                        admin_db_path=str(admin_db_path),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})
            page = client.get("/admin/operations/jobs")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)

            pause = client.post(
                f"/admin/operations/jobs/{paused_job.id}/pause",
                data={"csrf_token": csrf.group(1)},
                follow_redirects=False,
            )
            cancel = client.post(
                f"/admin/operations/jobs/{cancelled_job.id}/cancel",
                data={"csrf_token": csrf.group(1)},
                follow_redirects=False,
            )
            delete = client.post(
                f"/admin/operations/jobs/{deleted_job.id}/delete",
                data={"csrf_token": csrf.group(1)},
                follow_redirects=False,
            )

            self.assertEqual(pause.status_code, 303)
            self.assertEqual(cancel.status_code, 303)
            self.assertEqual(delete.status_code, 303)
            reopened = SQLiteTranslationJobStore(db_path)
            self.addCleanup(reopened.close)
            self.assertEqual(reopened.get_job(paused_job.id).status.value, "paused")
            self.assertEqual(
                reopened.get_job(cancelled_job.id).status.value,
                "cancelled",
            )
            self.assertIsNone(reopened.get_job(deleted_job.id))
            with SQLiteUserActivityStore(admin_db_path) as activity:
                events = activity.list_events(channel_user_id="42")
            event_types = {event.event_type for event in events}
            self.assertIn("translation.admin_paused", event_types)
            self.assertIn("translation.admin_cancelled", event_types)
            self.assertIn("translation.admin_deleted", event_types)

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
                    prompt_version="prompt-v1",
                    adapter_version="txt-adapter-v1",
                    total_fragment_count=1,
                    translation_policy=json.dumps(
                        {
                            "adapter_policy_version": "generic-adapter-v2",
                            "prompt_policy_version": "prompt-policy-v9",
                            "source_language": "auto",
                            "target_language": "ru",
                        }
                    ),
                    translation_stack={
                        "adapter": {"name": "txt", "version": "txt-adapter-v1"},
                        "language_profiles": {
                            "target_language": {"signature": "ru-profile-v1"}
                        },
                    },
                ),
            )
            logger.record_fragment(
                TranslationFragmentLog(
                    sequence=1,
                    source_text="Chapter one",
                    translated_text="Глава первая",
                    status="ready",
                    elapsed_seconds=0.5,
                    prompt_tokens=10,
                    completion_tokens=12,
                    total_tokens=22,
                    source_block_ids=("block-1",),
                    error_message=(
                        "Provider failed for Chapter one -> Глава первая "
                        "with Bearer processing-bearer-token and "
                        "api_key=sk-processing-secret-value "
                        "secret_id=deepseek.api_keys.processing-key"
                    ),
                )
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
            trace = client.get(f"/admin/translations/{logger.run_dir.name}/trace")
            evidence = client.get(
                f"/admin/translations/{logger.run_dir.name}/evidence"
            )
            details = client.get(f"/admin/logs/{logger.run_dir.name}")
            details_api = client.get(f"/admin/api/logs/{logger.run_dir.name}")
            download = client.get(f"/admin/logs/{logger.run_dir.name}/download")

            self.assertEqual(page.status_code, 200)
            self.assertIn("Translation Logs", page.text)
            self.assertIn("job-logs-1", page.text)
            self.assertIn("book.txt", page.text)
            self.assertIn("ready", page.text)
            self.assertIn(
                f"/admin/translations/{logger.run_dir.name}/trace",
                page.text,
            )
            self.assertIn(
                f'/admin/logs/{logger.run_dir.name}"',
                page.text,
            )
            self.assertNotIn("source_text", page.text)
            self.assertEqual(trace.status_code, 200)
            self.assertIn("Translation Failure Trace", trace.text)
            self.assertIn("job-logs-1", trace.text)
            self.assertIn("book.txt", trace.text)
            self.assertIn("Not failed", trace.text)
            self.assertIn("Advanced log detail", trace.text)
            self.assertIn("Copy evidence", trace.text)
            self.assertIn("Metadata-only packet for Codex", trace.text)
            self.assertNotIn("Chapter one", trace.text)
            self.assertNotIn("Глава первая", trace.text)
            self.assertNotIn("processing-bearer-token", trace.text)
            self.assertNotIn("sk-processing-secret-value", trace.text)
            self.assertNotIn("deepseek.api_keys.processing-key", trace.text)
            self.assertEqual(evidence.status_code, 200)
            self.assertIn("text/markdown", evidence.headers["content-type"])
            self.assertIn("attachment;", evidence.headers["content-disposition"])
            self.assertIn("FolioLoom Translation Evidence Packet", evidence.text)
            self.assertIn("Metadata only: yes", evidence.text)
            self.assertIn("Format version: 1", evidence.text)
            self.assertIn("job-logs-1", evidence.text)
            self.assertIn("book.txt", evidence.text)
            self.assertIn("Not failed", evidence.text)
            self.assertIn("Provider: Unknown", evidence.text)
            self.assertIn("Runtime status: Unknown", evidence.text)
            self.assertNotIn("Chapter one", evidence.text)
            self.assertNotIn("Глава первая", evidence.text)
            self.assertNotIn("processing-bearer-token", evidence.text)
            self.assertNotIn("sk-processing-secret-value", evidence.text)
            self.assertNotIn("deepseek.api_keys.processing-key", evidence.text)
            self.assertEqual(details.status_code, 200)
            self.assertIn("Translation Details", details.text)
            self.assertIn("Progress", details.text)
            self.assertIn("ETA", details.text)
            self.assertIn('class="progress-bar"', details.text)
            self.assertIn('data-detail-progress-bar="progress"', details.text)
            self.assertIn("job-logs-1", details.text)
            self.assertIn("prompt-v1", details.text)
            self.assertIn("txt-adapter-v1", details.text)
            self.assertIn("ru-profile-v1", details.text)
            self.assertIn('class="detail-json"', details.text)
            self.assertIn("adapter_policy_version", details.text)
            self.assertIn("generic-adapter-v2", details.text)
            self.assertIn("run_started", details.text)
            self.assertIn("block-1", details.text)
            self.assertIn("22", details.text)
            self.assertNotIn("Chapter one", details.text)
            self.assertNotIn("Глава первая", details.text)
            self.assertNotIn("processing-bearer-token", details.text)
            self.assertNotIn("sk-processing-secret-value", details.text)
            self.assertNotIn("deepseek.api_keys.processing-key", details.text)
            self.assertEqual(api.status_code, 200)
            payload = api.json()
            self.assertEqual(payload["logs"][0]["job_id"], "job-logs-1")
            self.assertEqual(payload["logs"][0]["status"], "ready")
            self.assertEqual(payload["logs"][0]["fragment_count"], 1)
            self.assertEqual(payload["logs"][0]["total_fragment_count"], 1)
            self.assertEqual(payload["logs"][0]["progress_percent"], 100.0)
            self.assertEqual(payload["logs"][0]["current_stage"], "run_finished")
            self.assertIn("last_event_at", payload["logs"][0])
            self.assertEqual(details_api.status_code, 200)
            details_api_text = details_api.text
            self.assertIn("[redacted]", details_api_text)
            self.assertNotIn("Chapter one", details_api_text)
            self.assertNotIn("Глава первая", details_api_text)
            self.assertNotIn("processing-bearer-token", details_api_text)
            self.assertNotIn("sk-processing-secret-value", details_api_text)
            self.assertNotIn("deepseek.api_keys.processing-key", details_api_text)
            self.assertEqual(
                details_api.json()["details"]["summary"]["job_id"],
                "job-logs-1",
            )
            self.assertEqual(
                details_api.json()["details"]["summary"]["progress_percent"],
                100.0,
            )
            self.assertEqual(
                details_api.json()["details"]["summary"]["current_stage"],
                "run_finished",
            )
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.headers["content-type"], "application/zip")
            self.assertIn(
                "attachment;",
                download.headers["content-disposition"],
            )
            with ZipFile(BytesIO(download.content)) as archive:
                names = set(archive.namelist())
                self.assertIn("run.json", names)
                self.assertIn("summary.md", names)
                self.assertIn("events.jsonl", names)
                archive_text = "\n".join(
                    archive.read(name).decode("utf-8", errors="ignore")
                    for name in names
                )
            self.assertIn("[redacted]", archive_text)
            self.assertNotIn("Chapter one", archive_text)
            self.assertNotIn("Глава первая", archive_text)
            self.assertNotIn("processing-bearer-token", archive_text)
            self.assertNotIn("sk-processing-secret-value", archive_text)
            self.assertNotIn("deepseek.api_keys.processing-key", archive_text)

    def test_translation_logs_page_passes_safe_limit_filter(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})
        with patch(
            "translator_service.admin.routes.list_translation_run_summaries",
            return_value=(),
        ) as summaries:
            self.client.get("/admin/logs?limit=200")
            self.client.get("/admin/logs?limit=999")

        self.assertEqual(summaries.call_args_list[0].kwargs["limit"], 200)
        self.assertEqual(summaries.call_args_list[1].kwargs["limit"], 500)

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
            _logger = TranslationRunLogger.start(
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
            self.assertIn("Active processing", page.text)
            self.assertIn("Jobs currently running or translating.", page.text)
            self.assertIn("Queued translations", page.text)
            self.assertIn("Jobs waiting for worker or provider capacity.", page.text)
            self.assertIn("Tokens today", page.text)
            self.assertIn("Provider token usage from runs started today.", page.text)
            self.assertIn("Server health", page.text)
            self.assertIn("CPU", page.text)
            self.assertIn("Memory", page.text)
            self.assertIn("Disk", page.text)
            self.assertIn("Uptime", page.text)
            self.assertIn("What needs attention", page.text)
            self.assertIn("Queue growing while active processing stays flat", page.text)
            self.assertIn("no provider slots point to", page.text)
            self.assertIn("provider capacity.", page.text)
            self.assertIn(
                "Failures today above zero need a recent run check",
                page.text,
            )
            self.assertIn("Recent rows are metadata-only.", page.text)
            self.assertIn("Progress", page.text)
            self.assertIn("ETA", page.text)
            self.assertIn("Stage", page.text)
            self.assertIn('class="progress-mini"', page.text)
            self.assertEqual(api.status_code, 200)
            payload = api.json()
            self.assertEqual(payload["active_translations"], 1)
            self.assertEqual(payload["recent_runs"][0]["job_id"], "job-live-1")
            self.assertIn("progress_percent", payload["recent_runs"][0])
            self.assertIn("eta_seconds", payload["recent_runs"][0])
            self.assertIn("current_stage", payload["recent_runs"][0])
            self.assertIn("available", payload["server"])
            self.assertIn("cpu_percent", payload["server"])
            self.assertIn("memory_percent", payload["server"])
            self.assertIn("disk_percent", payload["server"])

    def test_live_and_action_center_warn_when_beta_safety_is_paused(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_db_path=db_path,
                        translation_run_log_root=str(Path(temp_dir) / "runs"),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})
            settings_page = client.get("/admin/settings")
            client.post(
                "/admin/settings/beta-safety",
                data={
                    "csrf_token": _csrf_token(settings_page.text),
                    "BETA_TRANSLATIONS_PAUSED": "true",
                    "BETA_GLOBAL_DAILY_COST_CAP_USD": "5.00",
                    "BETA_GLOBAL_MONTHLY_COST_CAP_USD": "50.00",
                    "BETA_USER_DAILY_COST_CAP_USD": "1.00",
                    "BETA_USER_MONTHLY_COST_CAP_USD": "10.00",
                    "BETA_USER_DAILY_JOB_LIMIT": "3",
                    "BETA_MAX_JOB_ESTIMATED_COST_USD": "2.00",
                    "BETA_COST_WARNING_FRACTION": "0.80",
                },
            )

            live = client.get("/admin/live")
            overview = client.get("/admin/overview")

            self.assertIn("Beta translations are paused", live.text)
            self.assertIn("Beta translations are paused", overview.text)

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

    def test_deepseek_keys_page_shows_masked_values_without_raw_keys(self):
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
            page = client.get("/admin/ai-providers/deepseek/keys")
            response = client.post(
                "/admin/ai-providers/deepseek/keys",
                data={
                    "csrf_token": _csrf_token(page.text),
                    "label": "main",
                    "value": "sk-raw-secret-value",
                    "weight": "2",
                    "max_parallel_requests": "1",
                },
                follow_redirects=False,
            )

            updated = client.get("/admin/ai-providers/deepseek/keys")

            self.assertEqual(response.status_code, 303)
            self.assertEqual(
                response.headers["location"],
                "/admin/ai-providers/deepseek/keys",
            )
            self.assertIn("<strong>main</strong>", updated.text)
            self.assertIn("sk-****alue", updated.text)
            self.assertIn("Admin-managed key is enabled", updated.text)
            self.assertIn("Weight 2", updated.text)
            self.assertIn("Max parallel requests 1", updated.text)
            self.assertNotIn("sk-raw-secret-value", updated.text)
            self.assertNotIn(".api_keys.", updated.text)

    def test_deepseek_key_mutations_mark_runtime_reload_pending(self):
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
            page = client.get("/admin/ai-providers/deepseek/keys")
            client.post(
                "/admin/ai-providers/deepseek/keys",
                data={
                    "csrf_token": _csrf_token(page.text),
                    "label": "main",
                    "value": "sk-reload-secret",
                    "weight": "1",
                    "max_parallel_requests": "1",
                },
            )

            after_add = client.get("/admin/ai-providers/deepseek/keys")
            runtime_api = client.get("/admin/api/ai-providers/runtime")

            self.assertIn("DeepSeek runtime reload pending", after_add.text)
            payload = runtime_api.json()
            deepseek = next(
                item
                for item in payload["providers"]
                if item["provider_id"] == "deepseek"
            )
            self.assertTrue(deepseek["reload_pending"])
            self.assertIsNotNone(deepseek["reload_requested_at"])

    def test_deepseek_keys_page_shows_safe_validation_status(self):
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
            page = client.get("/admin/ai-providers/deepseek/keys")
            client.post(
                "/admin/ai-providers/deepseek/keys",
                data={
                    "csrf_token": _csrf_token(page.text),
                    "label": "main",
                    "value": "sk-validation-secret",
                    "weight": "1",
                    "max_parallel_requests": "1",
                },
            )
            updated = client.get("/admin/ai-providers/deepseek/keys")
            key_id = re.search(r'name="key_id" value="([^"]+)"', updated.text)
            self.assertIsNotNone(key_id)
            with SQLiteAIProviderValidationStore(db_path) as validations:
                validations.record_result(
                    provider_id="deepseek",
                    key_id=key_id.group(1),
                    status="auth_failed",
                    error="auth failed for sk-validation-secret",
                    actor_id="owner",
                )

            response = client.get("/admin/ai-providers/deepseek/keys")

            self.assertIn("auth_failed", response.text)
            self.assertIn("auth failed for [redacted]", response.text)
            self.assertNotIn("sk-validation-secret", response.text)

            rotated = client.post(
                "/admin/ai-providers/deepseek/keys/rotate",
                data={
                    "csrf_token": _csrf_token(response.text),
                    "key_id": key_id.group(1),
                    "value": "sk-validation-secret-rotated",
                },
                follow_redirects=False,
            )
            after_rotate = client.get("/admin/ai-providers/deepseek/keys")

            self.assertEqual(rotated.status_code, 303)
            self.assertIn("Last validation: not checked", after_rotate.text)
            self.assertNotIn("auth_failed", after_rotate.text)
            self.assertNotIn("sk-validation-secret", after_rotate.text)
            self.assertNotIn("sk-validation-secret-rotated", after_rotate.text)

    def test_deepseek_key_management_never_exposes_raw_secret_or_secret_id(self):
        raw_secret = "sk-never-show-this-secret"
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
            page = client.get("/admin/ai-providers/deepseek/keys")
            client.post(
                "/admin/ai-providers/deepseek/keys",
                data={
                    "csrf_token": _csrf_token(page.text),
                    "label": "main",
                    "value": raw_secret,
                    "weight": "1",
                    "max_parallel_requests": "1",
                },
            )

            outputs = [
                client.get("/admin/ai-providers").text,
                client.get("/admin/ai-providers/deepseek/keys").text,
                json.dumps(client.get("/admin/api/ai-providers").json()),
                json.dumps(client.get("/admin/api/ai-providers/runtime").json()),
            ]
            with SQLiteAdminAuditLog(db_path) as audit:
                outputs.extend(
                    f"{event.action} {event.target_id} {event.metadata_json}"
                    for event in audit.list_events(limit=20)
                )

            serialized = "\n".join(outputs)
            self.assertNotIn(raw_secret, serialized)
            self.assertNotIn("deepseek.api_keys.", serialized)
            self.assertNotIn("source_text", serialized)
            self.assertNotIn("translated_text", serialized)

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
            self.assertIn("Provider health", updated.text)
            self.assertIn("Active keys", updated.text)
            self.assertIn("Disabled keys", updated.text)
            self.assertIn("Last validation", updated.text)
            self.assertIn("Test key", updated.text)

            key_ids = list(
                dict.fromkeys(
                    re.findall(r'name="key_id" value="([^"]+)"', updated.text)
                )
            )
            self.assertEqual(len(key_ids), 2)
            remove = client.post(
                "/admin/ai-providers/deepseek/keys/remove",
                data={"csrf_token": csrf.group(1), "key_id": key_ids[0]},
                follow_redirects=False,
            )

            self.assertEqual(remove.status_code, 303)
            self.assertEqual(
                remove.headers["location"],
                "/admin/ai-providers/deepseek/keys",
            )
            after_remove = client.get("/admin/ai-providers")
            self.assertNotIn("<strong>main</strong>", after_remove.text)
            self.assertIn("<strong>backup</strong>", after_remove.text)
            settings = client.get("/admin/settings")
            self.assertIn("disabled", settings.text)
            self.assertNotIn(".api_keys.", settings.text)
            with SQLiteAdminAuditLog(db_path) as audit:
                events = audit.list_events(limit=3)
            serialized_events = "\n".join(
                f"{event.action} {event.target_id} {event.metadata_json}"
                for event in events
            )
            self.assertNotIn(".api_keys.", serialized_events)
            self.assertIn(key_ids[0], serialized_events)

    def test_ai_provider_page_handles_missing_backing_secret(self):
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
            add = client.post(
                "/admin/ai-providers/deepseek/keys",
                data={
                    "csrf_token": csrf.group(1),
                    "label": "orphaned",
                    "value": "sk-orphaned-secret",
                    "weight": "1",
                    "max_parallel_requests": "1",
                },
                follow_redirects=False,
            )
            self.assertEqual(add.status_code, 303)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute("DELETE FROM admin_secrets")
                connection.commit()
            finally:
                connection.close()

            response = client.get("/admin/ai-providers")

            self.assertEqual(response.status_code, 200)
            self.assertIn("Provider health", response.text)
            self.assertIn("0 active keys", response.text)
            self.assertIn("missing keys", response.text)
            self.assertIn("<code>missing</code>", response.text)

    def test_owner_can_test_ai_provider_key_and_see_health_result(self):
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
            add = client.post(
                "/admin/ai-providers/deepseek/keys",
                data={
                    "csrf_token": csrf.group(1),
                    "label": "main",
                    "value": "sk-testable-secret",
                    "weight": "1",
                    "max_parallel_requests": "1",
                },
                follow_redirects=False,
            )
            self.assertEqual(add.status_code, 303)
            updated = client.get("/admin/ai-providers")
            key_id = re.search(r'name="key_id" value="([^"]+)"', updated.text)
            self.assertIsNotNone(key_id)
            self.assertIn("not checked", updated.text)
            self.assertIn(
                'action="/admin/ai-providers/deepseek/keys/test"',
                updated.text,
            )
            self.assertIn(
                'action="/admin/ai-providers/deepseek/keys/test-all"',
                updated.text,
            )

            with patch(
                "translator_service.admin.routes.validate_ai_provider_key",
                return_value=AIProviderProbeResult(
                    status="provider_check_passed",
                    error=None,
                ),
            ) as probe:
                tested = client.post(
                    "/admin/ai-providers/deepseek/keys/test",
                    data={"csrf_token": csrf.group(1), "key_id": key_id.group(1)},
                    follow_redirects=False,
                )

            self.assertEqual(tested.status_code, 303)
            self.assertEqual(
                tested.headers["location"],
                "/admin/ai-providers/deepseek/keys",
            )
            probe.assert_called_once_with(
                "deepseek",
                "sk-testable-secret",
                base_url="https://api.deepseek.com",
                timeout_seconds=10.0,
            )
            after_test = client.get("/admin/ai-providers")
            self.assertIn("provider_check_passed", after_test.text)
            self.assertIn("n/a", after_test.text)
            self.assertNotIn("sk-testable-secret", after_test.text)
            self.assertNotIn(".api_keys.", after_test.text)
            with SQLiteAdminAuditLog(db_path) as audit:
                event = next(
                    event
                    for event in audit.list_events(limit=10)
                    if event.action == "ai_provider.key.tested"
                )
            self.assertEqual(event.outcome.value, "success")
            self.assertIn('"status": "provider_check_passed"', event.metadata_json)

    def test_owner_can_test_all_active_ai_provider_keys(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            jobs_path = Path(temp_dir) / "jobs.sqlite3"
            log_root = Path(temp_dir) / "runs"
            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_db_path=db_path,
                        persistent_jobs_db_path=str(jobs_path),
                        translation_run_log_root=str(log_root),
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
            for label, value in (
                ("main", "sk-main-secret"),
                ("backup", "sk-backup-secret"),
            ):
                added = client.post(
                    "/admin/ai-providers/deepseek/keys",
                    data={
                        "csrf_token": csrf.group(1),
                        "label": label,
                        "value": value,
                        "weight": "1",
                        "max_parallel_requests": "1",
                    },
                    follow_redirects=False,
                )
                self.assertEqual(added.status_code, 303)

            with patch(
                "translator_service.admin.routes.validate_ai_provider_key",
                side_effect=(
                    AIProviderProbeResult(
                        status="provider_check_passed",
                        error=None,
                    ),
                    AIProviderProbeResult(
                        status="failed",
                        error="Provider health check returned HTTP 401.",
                    ),
                ),
            ) as probe:
                tested = client.post(
                    "/admin/ai-providers/deepseek/keys/test-all",
                    data={"csrf_token": csrf.group(1)},
                    follow_redirects=False,
                )

            self.assertEqual(tested.status_code, 303)
            self.assertEqual(
                tested.headers["location"],
                "/admin/ai-providers/deepseek/keys",
            )
            self.assertEqual(probe.call_count, 2)
            self.assertEqual(
                [call.args[1] for call in probe.call_args_list],
                ["sk-main-secret", "sk-backup-secret"],
            )
            after_test = client.get("/admin/ai-providers")
            self.assertIn("failed", after_test.text)
            self.assertIn("HTTP 401", after_test.text)
            self.assertNotIn("sk-main-secret", after_test.text)
            self.assertNotIn("sk-backup-secret", after_test.text)
            self.assertNotIn(".api_keys.", after_test.text)
            with SQLiteAdminAuditLog(db_path) as audit:
                event = next(
                    event
                    for event in audit.list_events(limit=10)
                    if event.action == "ai_provider.keys.tested"
                )
            self.assertEqual(event.target_id, "deepseek")
            self.assertEqual(event.outcome.value, "failure")
            self.assertIn('"passed": 1', event.metadata_json)
            self.assertIn('"failed": 1', event.metadata_json)
            self.assertNotIn("sk-main-secret", event.metadata_json)
            self.assertNotIn(".api_keys.", event.metadata_json)

    def test_test_all_ai_provider_keys_pauses_during_active_provider_capacity(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            jobs_path = Path(temp_dir) / "jobs.sqlite3"
            log_root = Path(temp_dir) / "runs"
            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_db_path=db_path,
                        persistent_jobs_db_path=str(jobs_path),
                        translation_run_log_root=str(log_root),
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
            added = client.post(
                "/admin/ai-providers/deepseek/keys",
                data={
                    "csrf_token": csrf.group(1),
                    "label": "main",
                    "value": "sk-main-secret",
                    "weight": "1",
                    "max_parallel_requests": "1",
                },
                follow_redirects=False,
            )
            self.assertEqual(added.status_code, 303)
            with SQLiteAIProviderRuntimeStore(db_path) as runtime:
                runtime.record_status(
                    provider_id="deepseek",
                    source="admin_store",
                    status="ok",
                    reload_interval_seconds=30.0,
                    active_channels=(
                        AIProviderRuntimeChannel(
                            label="main",
                            weight=1,
                            max_parallel_requests=1,
                            active_requests=1,
                        ),
                    ),
                    provider_state=AIProviderRuntimeProviderState(
                        adaptive_enabled=True,
                        current_limit=2,
                        max_capacity=3,
                        active_requests=1,
                        available_slots=1,
                    ),
                    error=None,
                )

            with patch(
                "translator_service.admin.routes.validate_ai_provider_key",
                side_effect=AssertionError("test-all should pause before probes"),
            ) as probe:
                tested = client.post(
                    "/admin/ai-providers/deepseek/keys/test-all",
                    data={"csrf_token": csrf.group(1)},
                    follow_redirects=False,
                )

            self.assertEqual(tested.status_code, 409)
            self.assertIn("paused while translations or provider", tested.text)
            self.assertIn("Active translations: 0", tested.text)
            self.assertIn("active provider requests: 1", tested.text)
            self.assertIn("available provider slots: 1", tested.text)
            probe.assert_not_called()
            self.assertNotIn("sk-main-secret", tested.text)
            self.assertNotIn(".api_keys.", tested.text)
            with SQLiteAIProviderValidationStore(db_path) as validations:
                self.assertEqual(validations.latest_by_key("deepseek"), {})
            with SQLiteAdminAuditLog(db_path) as audit:
                event = next(
                    event
                    for event in audit.list_events(limit=10)
                    if event.action == "ai_provider.keys.tested"
                )
            self.assertEqual(event.target_id, "deepseek")
            self.assertEqual(event.outcome.value, "failure")
            self.assertIn('"status": "paused"', event.metadata_json)
            self.assertIn('"active_translations": 0', event.metadata_json)
            self.assertIn('"active_translation_state": "known"', event.metadata_json)
            self.assertIn('"active_provider_requests": 1', event.metadata_json)
            self.assertNotIn("sk-main-secret", event.metadata_json)
            self.assertNotIn(".api_keys.", event.metadata_json)

    def test_test_all_ai_provider_keys_pauses_during_active_translation(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            jobs_path = Path(temp_dir) / "jobs.sqlite3"
            log_root = Path(temp_dir) / "translation-runs"
            store = SQLiteTranslationJobStore(jobs_path)
            try:
                running = _persistent_job(store, order_id="order-running")
                _add_units(store, running.id)
                store.claim_next_work_unit(running.id, worker_id="worker-a")
            finally:
                store.close()
            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_db_path=db_path,
                        persistent_jobs_db_path=str(jobs_path),
                        translation_run_log_root=str(log_root),
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
            added = client.post(
                "/admin/ai-providers/deepseek/keys",
                data={
                    "csrf_token": csrf.group(1),
                    "label": "main",
                    "value": "sk-main-secret",
                    "weight": "1",
                    "max_parallel_requests": "1",
                },
                follow_redirects=False,
            )
            self.assertEqual(added.status_code, 303)
            with SQLiteAIProviderRuntimeStore(db_path) as runtime:
                runtime.record_status(
                    provider_id="deepseek",
                    source="admin_store",
                    status="ok",
                    reload_interval_seconds=30.0,
                    active_channels=(
                        AIProviderRuntimeChannel(
                            label="main",
                            weight=1,
                            max_parallel_requests=1,
                            active_requests=0,
                        ),
                    ),
                    provider_state=AIProviderRuntimeProviderState(
                        adaptive_enabled=True,
                        current_limit=2,
                        max_capacity=3,
                        active_requests=0,
                        available_slots=2,
                    ),
                    error=None,
                )

            with patch(
                "translator_service.admin.routes.validate_ai_provider_key",
                side_effect=AssertionError("test-all should pause before probes"),
            ) as probe:
                tested = client.post(
                    "/admin/ai-providers/deepseek/keys/test-all",
                    data={"csrf_token": csrf.group(1)},
                    follow_redirects=False,
                )

            self.assertEqual(tested.status_code, 409)
            self.assertIn("Active translations: 1", tested.text)
            self.assertIn("active provider requests: 0", tested.text)
            probe.assert_not_called()
            self.assertNotIn("sk-main-secret", tested.text)
            self.assertNotIn(".api_keys.", tested.text)
            with SQLiteAIProviderValidationStore(db_path) as validations:
                self.assertEqual(validations.latest_by_key("deepseek"), {})
            with SQLiteAdminAuditLog(db_path) as audit:
                event = next(
                    event
                    for event in audit.list_events(limit=10)
                    if event.action == "ai_provider.keys.tested"
                )
            self.assertEqual(event.target_id, "deepseek")
            self.assertEqual(event.outcome.value, "failure")
            self.assertIn('"status": "paused"', event.metadata_json)
            self.assertIn('"active_translations": 1', event.metadata_json)
            self.assertIn('"active_translation_state": "known"', event.metadata_json)
            self.assertIn('"active_provider_requests": 0', event.metadata_json)
            self.assertNotIn("sk-main-secret", event.metadata_json)
            self.assertNotIn(".api_keys.", event.metadata_json)

    def test_test_all_ai_provider_keys_skips_disabled_keys(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_db_path=db_path,
                        persistent_jobs_db_path=str(Path(temp_dir) / "jobs.sqlite3"),
                        translation_run_log_root=str(Path(temp_dir) / "runs"),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                        admin_secret_master_key=MASTER_KEY,
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})
            page = client.get("/admin/ai-providers/deepseek/keys")
            csrf_token = _csrf_token(page.text)
            for label, value in (
                ("main", "sk-active-secret"),
                ("backup", "sk-disabled-secret"),
            ):
                added = client.post(
                    "/admin/ai-providers/deepseek/keys",
                    data={
                        "csrf_token": csrf_token,
                        "label": label,
                        "value": value,
                        "weight": "1",
                        "max_parallel_requests": "1",
                    },
                    follow_redirects=False,
                )
                self.assertEqual(added.status_code, 303)
            updated = client.get("/admin/ai-providers/deepseek/keys")
            key_ids = list(
                dict.fromkeys(
                    re.findall(r'name="key_id" value="([^"]+)"', updated.text)
                )
            )
            self.assertEqual(len(key_ids), 2)
            disabled = client.post(
                "/admin/ai-providers/deepseek/keys/disable",
                data={"csrf_token": csrf_token, "key_id": key_ids[1]},
                follow_redirects=False,
            )
            self.assertEqual(disabled.status_code, 303)

            with patch(
                "translator_service.admin.routes.validate_ai_provider_key",
                return_value=AIProviderProbeResult(
                    status="provider_check_passed",
                    error=None,
                ),
            ) as probe:
                tested = client.post(
                    "/admin/ai-providers/deepseek/keys/test-all",
                    data={"csrf_token": csrf_token},
                    follow_redirects=False,
                )

            self.assertEqual(tested.status_code, 303)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(probe.call_args.args[1], "sk-active-secret")
            after_test = client.get("/admin/ai-providers/deepseek/keys")
            self.assertIn("provider_check_passed", after_test.text)
            self.assertNotIn("Key is disabled or unavailable.", after_test.text)
            self.assertNotIn("sk-active-secret", after_test.text)
            self.assertNotIn("sk-disabled-secret", after_test.text)

    def test_owner_can_update_disable_and_enable_ai_provider_key(self):
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
            add = client.post(
                "/admin/ai-providers/deepseek/keys",
                data={
                    "csrf_token": csrf.group(1),
                    "label": "main",
                    "value": "sk-editable-secret",
                    "weight": "1",
                    "max_parallel_requests": "1",
                },
                follow_redirects=False,
            )
            self.assertEqual(add.status_code, 303)
            updated = client.get("/admin/ai-providers")
            key_id = re.search(r'name="key_id" value="([^"]+)"', updated.text)
            self.assertIsNotNone(key_id)

            saved = client.post(
                "/admin/ai-providers/deepseek/keys/update",
                data={
                    "csrf_token": csrf.group(1),
                    "key_id": key_id.group(1),
                    "label": "primary",
                    "weight": "4",
                    "max_parallel_requests": "2",
                },
                follow_redirects=False,
            )
            disabled = client.post(
                "/admin/ai-providers/deepseek/keys/disable",
                data={"csrf_token": csrf.group(1), "key_id": key_id.group(1)},
                follow_redirects=False,
            )

            self.assertEqual(saved.status_code, 303)
            self.assertEqual(
                saved.headers["location"],
                "/admin/ai-providers/deepseek/keys",
            )
            self.assertEqual(disabled.status_code, 303)
            self.assertEqual(
                disabled.headers["location"],
                "/admin/ai-providers/deepseek/keys",
            )
            after_disable = client.get("/admin/ai-providers")
            self.assertIn("<strong>primary</strong>", after_disable.text)
            self.assertIn("0 active keys", after_disable.text)
            self.assertIn("disabled", after_disable.text)
            self.assertIn("Enable", after_disable.text)
            self.assertNotIn("sk-editable-secret", after_disable.text)
            with SQLiteEncryptedSecretStore(
                db_path,
                master_key=MASTER_KEY,
            ) as secrets:
                self.assertEqual(
                    secrets.get_secret_value(f"deepseek.api_keys.{key_id.group(1)}"),
                    "sk-editable-secret",
                )

            enabled = client.post(
                "/admin/ai-providers/deepseek/keys/enable",
                data={"csrf_token": csrf.group(1), "key_id": key_id.group(1)},
                follow_redirects=False,
            )

            self.assertEqual(enabled.status_code, 303)
            self.assertEqual(
                enabled.headers["location"],
                "/admin/ai-providers/deepseek/keys",
            )
            after_enable = client.get("/admin/ai-providers")
            self.assertIn("1 active keys", after_enable.text)
            self.assertIn("Weight 4", after_enable.text)
            self.assertIn("Max parallel requests 2", after_enable.text)
            with SQLiteAdminAuditLog(db_path) as audit:
                events = audit.list_events(limit=10)
            serialized_events = "\n".join(
                f"{event.action} {event.target_id} {event.metadata_json}"
                for event in events
            )
            self.assertIn("ai_provider.key.updated", serialized_events)
            self.assertIn("ai_provider.key.disabled", serialized_events)
            self.assertIn("ai_provider.key.enabled", serialized_events)
            self.assertNotIn("sk-editable-secret", serialized_events)
            self.assertNotIn(".api_keys.", serialized_events)

    def test_owner_can_rotate_ai_provider_key_without_changing_key_id(self):
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
            page = client.get("/admin/ai-providers/deepseek/keys")
            client.post(
                "/admin/ai-providers/deepseek/keys",
                data={
                    "csrf_token": _csrf_token(page.text),
                    "label": "main",
                    "value": "sk-old-secret-value",
                    "weight": "1",
                    "max_parallel_requests": "1",
                },
            )
            updated = client.get("/admin/ai-providers/deepseek/keys")
            key_id = re.search(r'name="key_id" value="([^"]+)"', updated.text)
            self.assertIsNotNone(key_id)

            rotate = client.post(
                "/admin/ai-providers/deepseek/keys/rotate",
                data={
                    "csrf_token": _csrf_token(updated.text),
                    "key_id": key_id.group(1),
                    "value": "sk-new-secret-value",
                },
                follow_redirects=False,
            )
            after_rotate = client.get("/admin/ai-providers/deepseek/keys")

            self.assertEqual(rotate.status_code, 303)
            self.assertEqual(
                rotate.headers["location"],
                "/admin/ai-providers/deepseek/keys",
            )
            self.assertIn(f'name="key_id" value="{key_id.group(1)}"', after_rotate.text)
            self.assertIn("sk-****alue", after_rotate.text)
            self.assertNotIn("sk-old-secret-value", after_rotate.text)
            self.assertNotIn("sk-new-secret-value", after_rotate.text)
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                self.assertEqual(
                    secrets.get_secret_value(f"deepseek.api_keys.{key_id.group(1)}"),
                    "sk-new-secret-value",
                )
            with SQLiteAdminAuditLog(db_path) as audit:
                events = audit.list_events(limit=10)
            serialized_events = "\n".join(
                f"{event.action} {event.target_id} {event.metadata_json}"
                for event in events
            )
            self.assertIn("ai_provider.key.rotated", serialized_events)
            self.assertNotIn("sk-old-secret-value", serialized_events)
            self.assertNotIn("sk-new-secret-value", serialized_events)
            self.assertNotIn(".api_keys.", serialized_events)

    def test_rotate_ai_provider_key_requires_non_empty_secret_value(self):
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
            page = client.get("/admin/ai-providers/deepseek/keys")

            response = client.post(
                "/admin/ai-providers/deepseek/keys/rotate",
                data={
                    "csrf_token": _csrf_token(page.text),
                    "key_id": "missing",
                    "value": "   ",
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("Key value is required", response.text)

    def test_ai_provider_page_shows_runtime_status_and_requests_reload(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            with SQLiteAIProviderRuntimeStore(db_path) as runtime:
                runtime.record_status(
                    provider_id="deepseek",
                    source="admin_store",
                    status="ok",
                    reload_interval_seconds=30.0,
                    active_channels=(
                        AIProviderRuntimeChannel(
                            label="stable",
                            weight=3,
                            max_parallel_requests=2,
                            active_requests=1,
                            health="cooling_down",
                            cooldown_remaining_seconds=9.0,
                            total_started_requests=11,
                            total_successful_requests=7,
                            total_temporary_failures=3,
                            total_permanent_failures=1,
                            total_rate_limit_failures=2,
                            total_unavailable_failures=1,
                            total_timeout_failures=4,
                            total_auth_failures=1,
                            total_billing_failures=0,
                            total_unsafe_model_output_failures=5,
                            average_latency_ms=123.45,
                            last_latency_ms=150.0,
                            error_kind="rate_limit",
                            last_error_excerpt=(
                                "HTTP 429 Bearer sk-runtime-secret "
                                "secret_id=deepseek.api_keys.key-1"
                            ),
                        ),
                    ),
                    provider_state=AIProviderRuntimeProviderState(
                        adaptive_enabled=True,
                        current_limit=1,
                        max_capacity=3,
                        active_requests=1,
                        available_slots=0,
                        circuit_state="open",
                        circuit_open_remaining_seconds=90.0,
                        last_reason=(
                            "billing Bearer sk-runtime-secret "
                            "secret_id=deepseek.api_keys.key-1"
                        ),
                        total_ramp_ups=2,
                        total_decreases=3,
                        total_circuit_opened=1,
                    ),
                    error=None,
                )
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

            self.assertIn("Runtime status", page.text)
            self.assertIn("Processing summary", page.text)
            self.assertIn("Read-only diagnostics", page.text)
            self.assertIn("they are not controls", page.text)
            self.assertIn("production readiness guarantees", page.text)
            self.assertIn("Active key channels", page.text)
            self.assertIn("Available capacity slots", page.text)
            self.assertIn("Adaptive limit", page.text)
            self.assertIn("1/3 (on)", page.text)
            self.assertIn("Cooling/degraded channels", page.text)
            self.assertIn("Unsafe model outputs", page.text)
            self.assertIn("these do not mean a provider key is broken", page.text)
            self.assertIn("Provider warning counts", page.text)
            self.assertIn("429 2 / auth 1 / billing 0 / timeout 4", page.text)
            self.assertIn("admin_store", page.text)
            self.assertIn("30s", page.text)
            self.assertIn("fresh", page.text)
            self.assertIn("stable", page.text)
            self.assertIn("weight 3", page.text)
            self.assertIn("parallel 2", page.text)
            self.assertIn("cooling_down", page.text)
            self.assertIn("active 1/2", page.text)
            self.assertIn("cooldown 9s", page.text)
            self.assertIn("latency 150.0ms", page.text)
            self.assertIn("started/ok/temp/perm 11/7/3/1", page.text)
            self.assertIn("429/503/timeout/auth/billing/unsafe 2/1/4/1/0/5", page.text)
            self.assertIn("rate_limit", page.text)
            self.assertIn("Adaptive throttle", page.text)
            self.assertIn("circuit open", page.text)
            self.assertIn("limit 1/3", page.text)
            self.assertIn("available 0", page.text)
            self.assertIn("open for 90s", page.text)
            self.assertIn("ramp/decrease/open 2/3/1", page.text)
            self.assertIn("[redacted]", page.text)
            self.assertIn(
                'action="/admin/ai-providers/deepseek/runtime/reload"',
                page.text,
            )
            self.assertNotIn("sk-runtime-secret", page.text)
            self.assertNotIn("Bearer", page.text)
            self.assertNotIn(".api_keys.", page.text)
            reload_response = client.post(
                "/admin/ai-providers/deepseek/runtime/reload",
                data={"csrf_token": csrf.group(1)},
                follow_redirects=False,
            )

            self.assertEqual(reload_response.status_code, 303)
            with SQLiteAIProviderRuntimeStore(db_path) as runtime:
                request = runtime.get_reload_state("deepseek")
            self.assertIsNotNone(request)
            self.assertTrue(request.pending)
            pending_page = client.get("/admin/ai-providers")
            runtime_api = client.get("/admin/api/ai-providers/runtime")
            live_page = client.get("/admin/live")

            self.assertIn("Reload requested", pending_page.text)
            self.assertIn("Waiting for runtime", pending_page.text)
            self.assertEqual(runtime_api.status_code, 200)
            payload = runtime_api.json()
            self.assertTrue(payload["providers"][0]["reload_pending"])
            self.assertEqual(payload["providers"][0]["freshness"], "fresh")
            channel_payload = payload["providers"][0]["active_channels"][0]
            self.assertEqual(channel_payload["health"], "cooling_down")
            self.assertEqual(channel_payload["active_requests"], 1)
            self.assertEqual(channel_payload["cooldown_remaining_seconds"], 9.0)
            self.assertEqual(channel_payload["total_started_requests"], 11)
            self.assertEqual(channel_payload["total_successful_requests"], 7)
            self.assertEqual(channel_payload["total_temporary_failures"], 3)
            self.assertEqual(channel_payload["total_permanent_failures"], 1)
            self.assertEqual(channel_payload["total_rate_limit_failures"], 2)
            self.assertEqual(channel_payload["total_unavailable_failures"], 1)
            self.assertEqual(channel_payload["total_timeout_failures"], 4)
            self.assertEqual(channel_payload["total_auth_failures"], 1)
            self.assertEqual(channel_payload["total_billing_failures"], 0)
            self.assertEqual(channel_payload["total_unsafe_model_output_failures"], 5)
            self.assertEqual(channel_payload["average_latency_ms"], 123.45)
            self.assertEqual(channel_payload["last_latency_ms"], 150.0)
            self.assertEqual(channel_payload["error_kind"], "rate_limit")
            self.assertIn("[redacted]", channel_payload["last_error_excerpt"])
            provider_state = payload["providers"][0]["provider_state"]
            self.assertTrue(provider_state["adaptive_enabled"])
            self.assertEqual(provider_state["current_limit"], 1)
            self.assertEqual(provider_state["max_capacity"], 3)
            self.assertEqual(provider_state["active_requests"], 1)
            self.assertEqual(provider_state["available_slots"], 0)
            self.assertEqual(provider_state["circuit_state"], "open")
            self.assertEqual(provider_state["circuit_open_remaining_seconds"], 90.0)
            self.assertIn("[redacted]", provider_state["last_reason"])
            self.assertEqual(provider_state["total_ramp_ups"], 2)
            self.assertEqual(provider_state["total_decreases"], 3)
            self.assertEqual(provider_state["total_circuit_opened"], 1)
            serialized_payload = json.dumps(payload, sort_keys=True)
            self.assertNotIn("sk-runtime-secret", serialized_payload)
            self.assertNotIn("Bearer", serialized_payload)
            self.assertNotIn(".api_keys.", serialized_payload)
            self.assertIn("DeepSeek runtime", live_page.text)
            self.assertIn("admin_store", live_page.text)
            self.assertIn("Reload pending", live_page.text)
            self.assertIn("Degraded channels", live_page.text)
            self.assertIn("Unsafe model outputs", live_page.text)
            self.assertIn("429 count", live_page.text)
            self.assertIn("Timeout count", live_page.text)
            self.assertIn("Adaptive limit", live_page.text)
            self.assertIn("Provider circuit", live_page.text)
            self.assertIn("Available provider slots", live_page.text)
            with SQLiteAdminAuditLog(db_path) as audit:
                event = next(
                    event
                    for event in audit.list_events(limit=10)
                    if event.action == "ai_provider.runtime.reload_requested"
                )
            self.assertEqual(event.target_id, "deepseek")
            self.assertEqual(event.outcome.value, "success")
            self.assertNotIn(".api_keys.", event.metadata_json)

    def test_ai_provider_page_summarizes_healthy_runtime_read_only(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            with SQLiteAIProviderRuntimeStore(db_path) as runtime:
                runtime.record_status(
                    provider_id="deepseek",
                    source="admin_store",
                    status="ok",
                    reload_interval_seconds=30.0,
                    active_channels=(
                        AIProviderRuntimeChannel(
                            label="main",
                            weight=1,
                            max_parallel_requests=2,
                            active_requests=0,
                            health="healthy",
                        ),
                    ),
                    provider_state=AIProviderRuntimeProviderState(
                        adaptive_enabled=True,
                        current_limit=2,
                        max_capacity=2,
                        active_requests=0,
                        available_slots=2,
                    ),
                    error=None,
                )
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

            self.assertEqual(page.status_code, 200)
            self.assertIn("Processing summary", page.text)
            self.assertIn("Active key channels", page.text)
            self.assertIn("Configured DeepSeek channels currently available", page.text)
            self.assertIn("Available capacity slots", page.text)
            self.assertIn(
                "Open request slots after current adaptive throttling",
                page.text,
            )
            self.assertIn("2/2 (on)", page.text)
            self.assertIn("Cooling/degraded channels", page.text)
            self.assertIn("Unsafe model outputs", page.text)
            self.assertIn("Provider warning counts", page.text)
            self.assertIn("429 0 / auth 0 / billing 0 / timeout 0", page.text)
            self.assertIn("not controls", page.text)
            self.assertIn("production readiness guarantees", page.text)

    def test_failed_ai_provider_key_test_is_recorded_as_audit_failure(self):
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
            add = client.post(
                "/admin/ai-providers/deepseek/keys",
                data={
                    "csrf_token": csrf.group(1),
                    "label": "disabled",
                    "value": "sk-disabled-secret",
                    "weight": "1",
                    "max_parallel_requests": "1",
                },
                follow_redirects=False,
            )
            self.assertEqual(add.status_code, 303)
            updated = client.get("/admin/ai-providers")
            key_id = re.search(r'name="key_id" value="([^"]+)"', updated.text)
            self.assertIsNotNone(key_id)
            remove = client.post(
                "/admin/ai-providers/deepseek/keys/remove",
                data={"csrf_token": csrf.group(1), "key_id": key_id.group(1)},
                follow_redirects=False,
            )
            self.assertEqual(remove.status_code, 303)

            tested = client.post(
                "/admin/ai-providers/deepseek/keys/test",
                data={"csrf_token": csrf.group(1), "key_id": key_id.group(1)},
                follow_redirects=False,
            )

            self.assertEqual(tested.status_code, 400)
            with SQLiteAdminAuditLog(db_path) as audit:
                event = next(
                    event
                    for event in audit.list_events(limit=10)
                    if event.action == "ai_provider.key.tested"
                )
            self.assertEqual(event.action, "ai_provider.key.tested")
            self.assertEqual(event.target_id, key_id.group(1))
            self.assertEqual(event.outcome.value, "failure")
            self.assertIn('"status": "failed"', event.metadata_json)
            self.assertNotIn("sk-disabled-secret", event.metadata_json)
            self.assertNotIn(".api_keys.", event.metadata_json)

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


def _persistent_job(store: SQLiteTranslationJobStore, *, order_id: str):
    return store.create_job(
        order_id=order_id,
        user_id="telegram:42",
        file_id=f"{order_id}-file",
        file_name="book.txt",
        document_kind="txt",
        source_language="en",
        target_language="uk",
        adapter_version="txt-v1",
        prompt_version="plain-v1",
        pricing_snapshot_id="pricing-1",
    )


def _add_units(store: SQLiteTranslationJobStore, job_id: str):
    return store.add_work_units(
        job_id,
        [
            WorkUnitPlan(
                sequence=1,
                source_block_ids=("block-1",),
                source_text_hash=f"{job_id}-hash-1",
                prompt_tier="plain",
                source_language="en",
                target_language="uk",
            )
        ],
    )


def _cost_analytics_fixture() -> CostAnalytics:
    return CostAnalytics(
        tokens_today=3000,
        tokens_last_7_days=3000,
        tokens_month_to_date=3000,
        estimated_cost_today_usd=0.00248,
        estimated_cost_last_7_days_usd=0.00248,
        estimated_cost_month_to_date_usd=0.00248,
        top_runs=(
            CostRunSummary(
                job_id="job-costs-1",
                order_id="order-costs-1",
                user_id="telegram:42",
                file_name="costs.txt",
                started_at=datetime(2026, 5, 9, 9, 0, tzinfo=UTC),
                prompt_tokens=1000,
                completion_tokens=2000,
                total_tokens=3000,
                estimated_cost_usd=0.00248,
                log_href="https://example.test/logs",
            ),
        ),
        top_users=(
            CostUserSummary(
                user_id="telegram:42",
                prompt_tokens=1000,
                completion_tokens=2000,
                total_tokens=3000,
                estimated_cost_usd=0.00248,
            ),
        ),
    )


if __name__ == "__main__":
    unittest.main()
