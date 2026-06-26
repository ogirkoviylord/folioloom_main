import json
import os
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
from translator_service.admin.operations import build_operations_overview
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
from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.output_contracts import format_translation_batch_contract
from translator_service.persistent_jobs import (
    SQLiteTranslationJobStore,
    WorkUnitPlan,
)
from translator_service.provider_failure_diagnostics import (
    ProviderFailureCategory,
    ProviderFailureDiagnostic,
)
from translator_service.scheduler import (
    ProviderCapacityCapDiagnostic,
    ProviderCapacityCapScope,
    ProviderCapacityDiagnostics,
    ProviderCapacitySlotDiagnostic,
    ProviderCapacitySlotDiagnosticStatus,
    SchedulerLimits,
    WorkUnitFailureKind,
)
from translator_service.translation_run_logs import (
    TranslationFragmentLog,
    TranslationRunLogger,
    TranslationRunMetadata,
    append_translation_run_event_for_job,
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


def _nav_section(page_text: str, class_name: str) -> str:
    tag = "details" if class_name == "advanced-nav" else "div"
    pattern = (
        rf'<{tag}[^>]+class="[^"]*{re.escape(class_name)}[^"]*"[^>]*>'
        rf"(.*?)</{tag}>"
    )
    match = re.search(pattern, page_text, re.DOTALL)
    if match is None:
        raise AssertionError(f"{class_name} nav section not found")
    return match.group(1)


def _advanced_nav_tag(page_text: str) -> str:
    match = re.search(
        r'<details class="[^"]*advanced-nav[^"]*"[^>]*>',
        page_text,
    )
    if match is None:
        raise AssertionError("advanced nav details not found")
    return match.group(0)


def _compact_text(page_text: str) -> str:
    return re.sub(r"\s+", " ", page_text)


def _heading_index(page_text: str, heading: str) -> int:
    match = re.search(rf">{re.escape(heading)}<", page_text)
    if match is None:
        raise AssertionError(f"Heading not found: {heading}")
    return match.start()


MASTER_KEY = urlsafe_b64encode(b"2" * 32).decode("ascii")


def _provider_capacity_diagnostic() -> ProviderCapacityDiagnostics:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    return ProviderCapacityDiagnostics(
        provider_id="deepseek",
        generated_at=now,
        capacity_state="cap_denied",
        total_slots=2,
        enabled_slots=2,
        disabled_slots=0,
        active_leases=1,
        free_slots=0,
        cap_denied_slots=1,
        expired_active_leases=0,
        recovered_expired_leases=1,
        released_leases=3,
        slots=(
            ProviderCapacitySlotDiagnostic(
                provider_id="deepseek",
                channel_id="deepseek-channel-1",
                slot_index=0,
                capacity_source="deepseek_key_pool",
                enabled=True,
                status=ProviderCapacitySlotDiagnosticStatus.LEASED,
                leased_by_job_id="job-capacity",
                leased_by_work_unit_id="unit-capacity",
                leased_by_worker_id="worker-capacity",
                acquired_at=now,
                lease_until=now,
                lease_age_seconds=20.0,
                lease_expires_in_seconds=280.0,
            ),
            ProviderCapacitySlotDiagnostic(
                provider_id="deepseek",
                channel_id="Bearer sk-capacity-secret",
                slot_index=1,
                capacity_source="secret deepseek.api_keys.key-1",
                enabled=True,
                status=ProviderCapacitySlotDiagnosticStatus.CAP_DENIED,
            ),
        ),
        caps=(
            ProviderCapacityCapDiagnostic(
                provider_id="deepseek",
                cap_id="deepseek-account-runtime sk-capacity-secret",
                scope=ProviderCapacityCapScope.ACCOUNT,
                max_parallel_requests=1,
                active_leases=1,
                available_capacity=0,
                at_limit=True,
                channel_ids=("Bearer sk-capacity-secret",),
            ),
        ),
    )


class AdminRoutesTest(unittest.TestCase):
    def setUp(self):
        self._admin_runtime_dir = TemporaryDirectory()
        self.addCleanup(self._admin_runtime_dir.cleanup)
        self.translation_run_log_root = str(
            Path(self._admin_runtime_dir.name) / "translation-runs"
        )
        settings = Settings(
            admin_owner_password="owner-pass",
            admin_session_secret="session-secret",
            translation_run_log_root=self.translation_run_log_root,
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

    def test_admin_overview_reuses_translation_run_summary_scan(self):
        from translator_service.admin.translation_logs import TranslationRunSummary

        now = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)
        summary = TranslationRunSummary(
            job_id="job-failed",
            status="failed",
            started_at=now,
            finished_at=now,
            order_id="order-failed",
            user_id="telegram:1",
            file_name="failed.txt",
            document_kind="txt",
            source_language="en",
            target_language="uk",
            translator_model="deepseek",
            result_file_name=None,
            error_message="safe metadata-only error",
            fragment_count=0,
            total_fragment_count=1,
            progress_percent=0.0,
            eta_seconds=None,
            current_stage="failed",
            last_event_at=now,
            total_tokens=0,
            elapsed_seconds=0.0,
            run_dir=str(Path(self.translation_run_log_root) / "run-failed"),
        )
        scan_calls = []

        def fake_list_translation_run_summaries(root, **filters):
            scan_calls.append((root, filters))
            return (summary,)

        self.client.post("/admin/login", data={"password": "owner-pass"})

        with patch(
            "translator_service.admin.routes.list_translation_run_summaries",
            side_effect=fake_list_translation_run_summaries,
        ), patch(
            "translator_service.admin.live.list_translation_run_summaries",
            side_effect=fake_list_translation_run_summaries,
        ):
            response = self.client.get("/admin/overview")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(scan_calls), 1)

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

    def test_action_control_helpers_render_semantic_variants_and_disabled_reasons(self):
        from translator_service.admin import views

        link = views._action_link(
            "Open <trace>",
            "/admin/logs?path=<unsafe>",
            "view",
            compact=True,
        )
        probe = views._action_button(
            "Test key",
            "probe",
            name="key_id",
            value="key-1",
            compact=True,
        )
        disabled_probe = views._action_button(
            "Test all active keys",
            "probe",
            disabled_reason="No active admin-managed keys are available to test.",
            compact=True,
        )
        danger = views._action_button("Delete", "danger", compact=True)

        html = link + probe + disabled_probe + danger
        self.assertIn('data-action-variant="view"', link)
        self.assertIn("Open &lt;trace&gt;", link)
        self.assertIn("path=&lt;unsafe&gt;", link)
        self.assertIn('data-action-variant="probe"', probe)
        self.assertIn('name="key_id"', probe)
        self.assertIn('value="key-1"', probe)
        self.assertIn('data-action-variant="probe"', disabled_probe)
        self.assertIn('data-action-state="disabled"', disabled_probe)
        self.assertIn("data-disabled-reason=", disabled_probe)
        self.assertIn(
            "No active admin-managed keys are available to test.",
            disabled_probe,
        )
        self.assertIn('data-action-variant="danger"', danger)
        self.assertNotIn("compact-action", html)

    def test_admin_log_rows_constrain_badges_actions_and_long_metadata(self):
        from translator_service.admin.translation_logs import TranslationRunSummary
        from translator_service.admin.views import logs_body

        long_file_name = (
            "very-long-authorized-translation-file-name-with-many-sections-"
            "and-safe-metadata-only.epub"
        )
        long_job_id = "job-" + ("abcdef1234567890" * 3)
        safe_error = "provider_other: safe summarized metadata only"

        html = logs_body(
            (
                TranslationRunSummary(
                    job_id=long_job_id,
                    status="failed",
                    started_at=datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
                    finished_at=None,
                    order_id="order-long",
                    user_id="telegram:42",
                    file_name=long_file_name,
                    document_kind="epub",
                    source_language="en",
                    target_language="uk",
                    translator_model="deepseek",
                    result_file_name=None,
                    error_message=safe_error,
                    fragment_count=2,
                    total_fragment_count=5,
                    progress_percent=40.0,
                    eta_seconds=None,
                    current_stage="failed",
                    last_event_at=None,
                    total_tokens=1234,
                    elapsed_seconds=2.5,
                    run_dir="/tmp/run-long-metadata",
                ),
            )
        )
        plain_text = _compact_text(html)

        self.assertIn('class="status admin-badge"', html)
        self.assertIn(f'title="{long_file_name}"', html)
        self.assertIn("admin-cell-filename", html)
        self.assertIn(f'title="{long_job_id}"', html)
        self.assertIn("admin-cell-id", html)
        self.assertIn(f'title="{safe_error}"', html)
        self.assertIn("admin-cell-error", html)
        self.assertIn("multi-file owner-only diagnostic packet", plain_text)
        self.assertIn("sanitized summary/state", plain_text)
        self.assertIn("lifecycle events", plain_text)
        self.assertIn("per-fragment/work-unit metadata", plain_text)
        self.assertIn("owner-only provider/glossary diagnostics", plain_text)
        self.assertIn("explicit archive download", plain_text)
        self.assertIn(
            'class="action-control action-control-view action-control-compact"',
            html,
        )
        self.assertNotIn("traceback", html.lower())

    def test_admin_redesign_b21_logs_diagnostics_visible_copy(self):
        """B2.1 pinned visible copy for Logs/Diagnostics slice.

        Asserts the exact pinned strings from the B2.1 spec are emitted by
        the body helpers (logs_body / translations_body) and that the
        sidebar Advanced nav exposes the renamed Logs label.
        """
        from translator_service.admin.translation_logs import TranslationRunSummary
        from translator_service.admin.views import (
            logs_body,
            translations_body,
        )

        summary = TranslationRunSummary(
            job_id="job-b21-logs-diagnostics",
            status="ready",
            started_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
            finished_at=None,
            order_id="order-b21",
            user_id="telegram:42",
            file_name="book-b21.txt",
            document_kind="txt",
            source_language="en",
            target_language="uk",
            translator_model="deepseek",
            result_file_name=None,
            error_message=None,
            fragment_count=1,
            total_fragment_count=1,
            progress_percent=100.0,
            eta_seconds=None,
            current_stage="ready",
            last_event_at=datetime(2026, 6, 26, 12, 1, tzinfo=UTC),
            total_tokens=42,
            elapsed_seconds=60.0,
            run_dir="/tmp/run-b21-logs-diagnostics",
        )

        # /admin/logs — pinned H1 and help copy.
        logs_help_sentence = (
            "Logs are run lifecycle metadata. "
            "Diagnostics here are run-scoped and owner-only "
            "where raw text or provider bodies appear."
        )
        logs_text = _compact_text(logs_body((summary,)))
        self.assertIn("Translation Logs", logs_text)
        self.assertIn(logs_help_sentence, logs_text)
        # H1 stays "Translation Logs" — sidebar label does not bleed into page body.
        self.assertNotIn("Run Logs / Diagnostics", logs_text)

        # /admin/translations — pinned helper sentence.
        translations_text = _compact_text(translations_body((summary,)))
        self.assertIn(
            "Advanced run logs and run-scoped diagnostics remain under Advanced.",
            translations_text,
        )

        # Sidebar Advanced nav exposes the renamed Logs label exactly.
        self.client.post("/admin/login", data={"password": "owner-pass"})
        overview = self.client.get("/admin/overview")
        self.assertEqual(overview.status_code, 200)
        advanced_nav = _nav_section(overview.text, "advanced-nav")
        self.assertIn(">Run Logs / Diagnostics<", advanced_nav)
        self.assertNotIn(">Logs<", advanced_nav)  # old label must be gone

        # Run detail backlink stays verbatim: "Back to run logs".
        logger = TranslationRunLogger.start(
            root=self.translation_run_log_root,
            metadata=TranslationRunMetadata(
                job_id="job-b21-detail-backlink",
                order_id="order-b21-detail",
                user_id="telegram:42",
                file_name="book-b21-detail.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                translator_model="deepseek",
                total_fragment_count=1,
            ),
        )
        logger.finish(status="ready", result_file_name="book-b21-detail.uk.txt")
        detail_page = self.client.get(f"/admin/logs/{logger.run_dir.name}")
        self.assertEqual(detail_page.status_code, 200)
        self.assertIn("Back to run logs", detail_page.text)

    def test_admin_redesign_b61a_reader_raw_diagnostics_helper_copy(self):
        """B6.1a pinned visible copy for Reader / Text Diagnostics /
        Archive-download boundary clarity.

        Asserts each surface renders the exact pinned helper sentence in a
        calm ``helper-text`` paragraph and that no WARNING prefix / icon-only
        alert is added. Also asserts the B6.1a copy does NOT leak into
        ``translation_logs.py`` (out of scope for this slice).
        """
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_root = root / "runs"
            logger = TranslationRunLogger.start(
                root=run_root,
                metadata=TranslationRunMetadata(
                    job_id="job-b61a-reader-helper",
                    order_id="order-b61a-reader-helper",
                    user_id="telegram:42",
                    file_name="book-b61a-reader-helper.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    total_fragment_count=1,
                ),
            )
            logger.record_event("job_queued", {"fragment_count": 1})
            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=str(run_root),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            detail_page = client.get(f"/admin/logs/{logger.run_dir.name}")
            diagnostics_page = client.get(
                f"/admin/logs/{logger.run_dir.name}/text-diagnostics"
            )
            reader_page = client.get(
                f"/admin/logs/{logger.run_dir.name}/reader"
            )

        self.assertEqual(detail_page.status_code, 200)
        self.assertEqual(diagnostics_page.status_code, 200)
        self.assertEqual(reader_page.status_code, 200)

        reader_helper = (
            "Reader shows the source and translated text for this run. "
            "Raw provider bodies and glossary runtime detail are not "
            "shown here; use Text Diagnostics for that."
        )
        diagnostics_helper = (
            "Text Diagnostics shows run-scoped, owner-only diagnostics "
            "for this run. Information here is bounded to this run and "
            "is not exported elsewhere."
        )
        archive_helper = (
            "Download archive produces a single file with the run "
            "output. It does not include raw provider bodies or "
            "glossary runtime detail."
        )

        # Pinned helper sentences render verbatim on each surface.
        self.assertIn(reader_helper, _compact_text(reader_page.text))
        self.assertIn(
            diagnostics_helper, _compact_text(diagnostics_page.text)
        )
        self.assertIn(archive_helper, _compact_text(detail_page.text))

        # Helper block uses the calm ``helper-text`` class — no
        # warning-panel / WARNING: prefix / icon-only alert for the
        # new pinned copy. Each sentence must live inside a calm
        # ``<p class="helper-text">`` block on its target surface.
        surfaces_with_helper = (
            (reader_page.text, reader_helper),
            (diagnostics_page.text, diagnostics_helper),
            (detail_page.text, archive_helper),
        )
        for html, sentence in surfaces_with_helper:
            compact = _compact_text(html)
            self.assertIn(sentence, compact)
            # The sentence appears inside a calm helper-text paragraph;
            # tolerant of template whitespace via _compact_text.
            self.assertIn(
                'class="helper-text"> ' + sentence[:32],
                compact,
            )

        # Negative guards: no new WARNING: prefix introduced by B6.1a
        # in the helper blocks. Existing pre-B6.1a warning-panels
        # already render without a "WARNING:" literal, so the helper
        # sentences must not introduce one either.
        for sentence in (
            reader_helper,
            diagnostics_helper,
            archive_helper,
        ):
            self.assertNotIn("WARNING:", sentence)

        # Cross-surface guard: each helper sentence is targeted at
        # exactly the surface it belongs to — it must not appear on
        # the other two surfaces (preserves boundary clarity).
        self.assertNotIn(reader_helper, _compact_text(detail_page.text))
        self.assertNotIn(
            diagnostics_helper, _compact_text(reader_page.text)
        )
        self.assertNotIn(archive_helper, _compact_text(reader_page.text))
        self.assertNotIn(
            archive_helper, _compact_text(diagnostics_page.text)
        )

        # Out-of-scope guard: B6.1a is views.py only — pinned copy must
        # not leak into translation_logs.py.
        translation_logs_source = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "translator_service"
            / "admin"
            / "translation_logs.py"
        ).read_text(encoding="utf-8")
        for sentence in (
            reader_helper,
            diagnostics_helper,
            archive_helper,
        ):
            self.assertNotIn(sentence, translation_logs_source)

    def test_translations_body_renders_primary_workflow_and_emergency_cancel(self):
        from translator_service.admin.translation_logs import TranslationRunSummary
        from translator_service.admin.views import translations_body

        long_file_name = (
            "very-long-authorized-translation-file-name-with-many-sections-"
            "and-safe-metadata-only.epub"
        )
        running = TranslationRunSummary(
            job_id="job-running-translation",
            status="running",
            started_at=datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
            finished_at=None,
            order_id="order-running",
            user_id="telegram:42",
            file_name=long_file_name,
            document_kind="epub",
            source_language="en",
            target_language="uk",
            translator_model="deepseek",
            result_file_name=None,
            error_message=(
                "Traceback with api_key=sk-translation-list-secret and raw path"
            ),
            fragment_count=2,
            total_fragment_count=5,
            progress_percent=40.0,
            eta_seconds=None,
            current_stage="translating",
            last_event_at=datetime(2026, 6, 6, 12, 3, tzinfo=UTC),
            total_tokens=1234,
            elapsed_seconds=180.0,
            run_dir="/tmp/run-running-translation",
        )
        ready = TranslationRunSummary(
            job_id="job-ready-translation",
            status="ready",
            started_at=datetime(2026, 6, 6, 11, 0, tzinfo=UTC),
            finished_at=datetime(2026, 6, 6, 11, 5, tzinfo=UTC),
            order_id="order-ready",
            user_id="telegram:99",
            file_name="ready.docx",
            document_kind="docx",
            source_language="en",
            target_language="uk",
            translator_model="deepseek",
            result_file_name="ready-uk.docx",
            error_message=None,
            fragment_count=5,
            total_fragment_count=5,
            progress_percent=100.0,
            eta_seconds=0.0,
            current_stage="ready",
            last_event_at=datetime(2026, 6, 6, 11, 5, tzinfo=UTC),
            total_tokens=4321,
            elapsed_seconds=300.0,
            run_dir="/tmp/run-ready-translation",
        )
        operations = build_operations_overview(
            jobs=[
                {"id": running.job_id, "status": "translating"},
                {"id": ready.job_id, "status": "ready"},
            ],
            job_log_hrefs={
                running.job_id: "/admin/logs/run-running-translation",
                ready.job_id: "/admin/logs/run-ready-translation",
            },
        )

        html = translations_body(
            (running, ready),
            operations=operations,
            csrf_token="csrf",
        )

        self.assertIn("<th>Format</th>", html)
        self.assertIn("format-badge-epub", html)
        self.assertIn("format-badge-docx", html)
        self.assertIn(f'title="{long_file_name}"', html)
        self.assertIn('href="/admin/translations/run-running-translation/trace"', html)
        self.assertIn("Open trace", html)
        self.assertIn('href="/admin/logs/run-running-translation"', html)
        self.assertIn("Diagnostics details", html)
        self.assertIn(
            'action="/admin/operations/jobs/job-running-translation/cancel"',
            html,
        )
        self.assertIn("stop provider work and reduce token spend", html)
        self.assertIn('name="csrf_token" value="csrf"', html)
        self.assertIn("Cancel unavailable", html)
        self.assertIn("Existing Operations state is not cancellable.", html)
        self.assertIn("error recorded; open trace", html)
        self.assertNotIn("sk-tra...cret", html)
        self.assertNotIn("Traceback with", html)
        self.assertNotIn(">Details<", html)
        self.assertNotIn(">Reader<", html)

        empty_html = translations_body((), operations=operations, csrf_token="csrf")
        empty_text = _compact_text(empty_html)
        self.assertIn("Primary run triage surface", empty_text)
        self.assertIn(
            "Open trace is the normal first troubleshooting action",
            empty_text,
        )
        self.assertIn("Refresh to read current run summaries", empty_text)
        self.assertIn(
            "No translation runs found yet. Refresh after a translation has started.",
            empty_text,
        )
        self.assertNotIn(
            "No runs match the current filters — clear filters to see all runs.",
            empty_text,
        )

    def test_translations_body_empty_state_distinguishes_true_empty_from_filters(self):
        from translator_service.admin.views import translations_body

        true_empty_copy = (
            "No translation runs found yet. Refresh after a translation has started."
        )
        filtered_empty_copy = (
            "No runs match the current filters — clear filters to see all runs."
        )

        no_filter_cases = (
            ("status-none", None, None, None),
            ("status-empty", "", None, None),
            ("status-all", "all", None, None),
        )
        for label, status, date_from, date_to in no_filter_cases:
            with self.subTest(label=label):
                empty_text = _compact_text(
                    translations_body(
                        (),
                        status=status,
                        date_from=date_from,
                        date_to=date_to,
                    )
                )

                self.assertIn(true_empty_copy, empty_text)
                self.assertNotIn(filtered_empty_copy, empty_text)

        filtered_cases = (
            ("status-failed", "failed", None, None),
            ("date-from", None, "2026-06-01", None),
            ("date-to", None, None, "2026-06-30"),
            ("status-all-with-date", "all", "2026-06-01", None),
        )
        for label, status, date_from, date_to in filtered_cases:
            with self.subTest(label=label):
                empty_text = _compact_text(
                    translations_body(
                        (),
                        status=status,
                        date_from=date_from,
                        date_to=date_to,
                    )
                )

                self.assertIn(filtered_empty_copy, empty_text)
                self.assertNotIn(true_empty_copy, empty_text)

    def test_ai_provider_actions_expose_probe_change_danger_and_refresh_variants(self):
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

            empty_keys_page = client.get("/admin/ai-providers/deepseek/keys")
            self.assertEqual(empty_keys_page.status_code, 200)
            self.assertIn('data-action-variant="probe"', empty_keys_page.text)
            self.assertIn('data-action-state="disabled"', empty_keys_page.text)
            self.assertIn(
                "No active admin-managed keys are available to test.",
                empty_keys_page.text,
            )

            csrf_token = _csrf_token(empty_keys_page.text)
            response = client.post(
                "/admin/ai-providers/deepseek/keys",
                data={
                    "csrf_token": csrf_token,
                    "value": "sk-admin-action-semantics",
                    "label": "Semantics key",
                    "weight": "1",
                    "max_parallel_requests": "1",
                },
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)

            keys_page = client.get("/admin/ai-providers/deepseek/keys")
            self.assertEqual(keys_page.status_code, 200)
            self.assertIn('data-action-variant="change"', keys_page.text)
            self.assertIn('data-action-variant="probe"', keys_page.text)
            self.assertIn('data-action-variant="danger"', keys_page.text)
            self.assertIn("Save label", keys_page.text)
            self.assertIn("Test key", keys_page.text)
            self.assertIn("Remove", keys_page.text)

            providers_page = client.get("/admin/ai-providers")
            self.assertEqual(providers_page.status_code, 200)
            self.assertIn('data-action-variant="refresh"', providers_page.text)
            self.assertIn("Refresh balance", providers_page.text)

    def test_b51_provider_surfaces_separate_status_owner_and_runtime_buckets(self):
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

            keys_page = client.get("/admin/ai-providers/deepseek/keys")
            providers_page = client.get("/admin/ai-providers")

        self.assertEqual(keys_page.status_code, 200)
        self.assertEqual(providers_page.status_code, 200)
        for html in (keys_page.text, providers_page.text):
            self.assertIn("fl-status", html)
            self.assertIn("fl-owner-action", html)
            self.assertIn("fl-runtime-action", html)
        self.assertIn('action="/admin/ai-providers/deepseek/keys"', keys_page.text)
        self.assertIn(
            'action="/admin/ai-providers/deepseek/keys/test-all"',
            keys_page.text,
        )
        self.assertIn(
            'action="/admin/ai-providers/deepseek/runtime/reload"',
            keys_page.text,
        )
        self.assertIn('href="/admin/ai-providers/deepseek/keys"', providers_page.text)
        self.assertRegex(
            providers_page.text,
            r'<form[^>]*class="[^"]*\bfl-runtime-action\b[^"]*"[^>]*'
            r'action="/admin/ai-providers/deepseek/balance/refresh"',
        )
        for forbidden in (
            "dangerous action",
            "audit-worthy",
            "audit worthy",
            "privacy warning",
            "recorded in admin audit",
            "audit guarantee",
            "production ready",
            "release ready",
            "public admin",
            "privacy compliant",
        ):
            self.assertNotIn(forbidden, (keys_page.text + providers_page.text).lower())

    def test_b51_jobs_queue_separates_status_owner_and_runtime_buckets(self):
        from translator_service.admin import views

        operations = build_operations_overview(
            jobs=[{"id": "job-b51-runtime", "status": "translating"}],
            job_log_hrefs={"job-b51-runtime": "/admin/logs/run-b51-runtime"},
        )

        html = views.operations_body(operations, csrf_token="csrf-token")

        self.assertIn("fl-status", html)
        self.assertIn("fl-owner-action", html)
        self.assertIn("fl-runtime-action", html)
        self.assertIn('href="/admin/translations/run-b51-runtime/trace"', html)
        self.assertIn('action="/admin/operations/jobs/job-b51-runtime/pause"', html)
        self.assertIn('action="/admin/operations/jobs/job-b51-runtime/cancel"', html)
        self.assertIn('action="/admin/operations/jobs/job-b51-runtime/delete"', html)
        self.assertIn('name="csrf_token" value="csrf-token"', html)
        self.assertNotIn("audit guarantee", html.lower())
        self.assertNotIn("dangerous action", html.lower())

    def test_job_actions_use_change_danger_and_disabled_reasons(self):
        from translator_service.admin import views

        actionable_job = SimpleNamespace(
            id="job-actionable",
            pausable=True,
            cancellable=True,
            deletable=True,
            retryable=False,
        )
        html = views._job_actions(actionable_job, "csrf-token")
        self.assertIn('data-action-variant="change"', html)
        self.assertGreaterEqual(html.count('data-action-variant="danger"'), 2)
        self.assertIn("fl-runtime-action", html)
        self.assertIn("Pause", html)
        self.assertIn("Cancel", html)
        self.assertIn("Delete", html)

        inactive_job = SimpleNamespace(
            id="job-inactive",
            pausable=False,
            cancellable=False,
            deletable=False,
            retryable=False,
        )
        disabled_html = views._job_actions(inactive_job, "csrf-token")
        self.assertIn('data-action-state="disabled"', disabled_html)
        self.assertIn("data-disabled-reason=", disabled_html)
        self.assertIn("This job state has no admin action available.", disabled_html)

        retryable_job = SimpleNamespace(
            id="job-retry",
            pausable=False,
            cancellable=False,
            deletable=False,
            retryable=True,
        )
        retry_html = views._job_actions(retryable_job, "csrf-token")
        self.assertIn('data-action-state="disabled"', retry_html)
        self.assertIn("Retry is not available from this console view.", retry_html)

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
        primary_nav = _nav_section(overview.text, "primary-nav")
        for label in (
            "Overview",
            "Live",
            "Translations",
            "Users",
            "Providers",
            "Safety",
            "Settings",
        ):
            self.assertIn(label, primary_nav)
        self.assertNotIn("Beta Controls", primary_nav)
        self.assertEqual(overview.headers["cache-control"], "no-store")

    def test_settings_page_consolidates_b41_ia(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        response = self.client.get("/admin/settings")

        self.assertEqual(response.status_code, 200)
        primary_nav = _nav_section(response.text, "primary-nav")
        self.assertIn('href="/admin/ai-providers"', primary_nav)
        self.assertIn(">Providers<", primary_nav)
        self.assertIn('href="/admin/settings" class="active"', primary_nav)
        self.assertIn(">Settings<", primary_nav)
        self.assertNotIn("Beta Controls", primary_nav)
        self.assertNotIn('href="/admin/beta-controls"', primary_nav)
        self.assertIn("<h1>Settings</h1>", response.text)

        section_order = [
            _heading_index(response.text, heading)
            for heading in (
                "Provider status",
                "Defaults",
                "Limits",
                "Beta controls",
            )
        ]
        self.assertEqual(section_order, sorted(section_order))
        self.assertNotIn("Danger zone", response.text)
        self.assertIn('href="/admin/ai-providers"', response.text)
        self.assertNotIn('method="post" action="/admin/ai-providers', response.text)
        self.assertNotIn('href="/admin/glossary"', response.text)
        self.assertNotIn('href="/admin/settings/glossary"', response.text)

    def test_b51_settings_separates_status_owner_and_runtime_buckets(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        response = self.client.get("/admin/settings")

        self.assertEqual(response.status_code, 200)
        self.assertIn("fl-status", response.text)
        self.assertIn("fl-owner-action", response.text)
        self.assertIn("fl-runtime-action", response.text)
        self.assertIn('action="/admin/settings/beta-safety"', response.text)
        self.assertIn('action="/admin/settings/beta-allowlist/toggle"', response.text)
        self.assertIn('action="/admin/settings/beta-allowlist/add"', response.text)
        self.assertNotIn('method="post" action="/admin/ai-providers', response.text)
        for forbidden in (
            "dangerous action",
            "audit-worthy",
            "privacy warning",
            "recorded in admin audit",
            "audit guarantee",
        ):
            self.assertNotIn(forbidden, response.text.lower())

    def test_beta_controls_route_is_preserved_as_settings_surface(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        response = self.client.get("/admin/beta-controls")

        self.assertEqual(response.status_code, 200)
        self.assertIn("<h1>Settings</h1>", response.text)
        primary_nav = _nav_section(response.text, "primary-nav")
        self.assertIn('href="/admin/settings" class="active"', primary_nav)
        self.assertNotIn("Beta Controls", primary_nav)
        self.assertIn('action="/admin/settings/beta-safety"', response.text)

    def test_admin_navigation_groups_raw_pages_under_advanced(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        overview = self.client.get("/admin/overview")

        self.assertEqual(overview.status_code, 200)
        primary_nav = _nav_section(overview.text, "primary-nav")
        advanced_nav = _nav_section(overview.text, "advanced-nav")
        self.assertIn(">Advanced<", overview.text)
        for label in (
            "Run Logs / Diagnostics",
            "Reader Explorer",
            "Activity",
            "Jobs / Queue",
            "Audit",
        ):
            self.assertNotIn(f">{label}<", primary_nav)
            self.assertIn(f">{label}<", advanced_nav)
        for href in (
            "/admin/logs",
            "/admin/internal-reader",
            "/admin/activity",
            "/admin/operations/jobs",
            "/admin/audit",
        ):
            self.assertIn(f'href="{href}"', advanced_nav)

    def test_advanced_route_marks_advanced_nav_item_active(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        page = self.client.get("/admin/operations/jobs")

        self.assertEqual(page.status_code, 200)
        primary_nav = _nav_section(page.text, "primary-nav")
        advanced_nav = _nav_section(page.text, "advanced-nav")
        self.assertIn("open", _advanced_nav_tag(page.text))
        self.assertIn("Jobs / Queue", page.text)
        self.assertIn(
            'href="/admin/operations/jobs" class="active"',
            advanced_nav,
        )
        self.assertNotIn('class="active"', primary_nav)

    def test_translations_alias_is_primary_while_raw_logs_stay_advanced(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        translations = self.client.get("/admin/translations")
        logs = self.client.get("/admin/logs")

        self.assertEqual(translations.status_code, 200)
        self.assertEqual(logs.status_code, 200)
        self.assertIn(
            'href="/admin/translations" class="active"',
            _nav_section(translations.text, "primary-nav"),
        )
        self.assertNotIn("open", _advanced_nav_tag(translations.text))
        self.assertIn(
            'href="/admin/logs" class="active"',
            _nav_section(logs.text, "advanced-nav"),
        )
        self.assertIn("open", _advanced_nav_tag(logs.text))
        self.assertIn("<th>Troubleshooting</th>", translations.text)
        self.assertNotIn("<th>Primary action</th>", translations.text)
        self.assertIn("<th>Emergency</th>", translations.text)
        self.assertNotIn("<th>Actions</th>", translations.text)
        self.assertIn("<th>Actions</th>", logs.text)
        self.assertNotEqual(translations.text, logs.text)

    def test_internal_reader_page_requires_login_and_does_not_generate_report(self):
        with patch(
            "translator_service.admin.routes.generate_txt_reader_html_from_path",
            side_effect=AssertionError("reader report should be lazy"),
        ) as generator:
            response = self.client.get(
                "/admin/internal-reader/preview",
                params={"source": "test_samples/sample_book.en.txt"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")
        generator.assert_not_called()

    def test_reader_explorer_page_lists_sample_fixtures_under_advanced_nav(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        page = self.client.get("/admin/internal-reader")

        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers["cache-control"], "no-store")
        self.assertIn("Reader Explorer", page.text)
        self.assertIn("No translation runs found.", page.text)
        self.assertIn("Local fixture reader", page.text)
        self.assertIn("test_samples/sample_book.en.txt", page.text)
        self.assertIn("test_samples/sample_book.en.docx", page.text)
        self.assertIn("test_samples/sample_book.en.epub", page.text)
        self.assertIn(
            'href="/admin/internal-reader" class="active"',
            _nav_section(page.text, "advanced-nav"),
        )
        self.assertIn("open", _advanced_nav_tag(page.text))

    def test_reader_explorer_ignores_ambient_translation_run_env(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ambient_root = root / "ambient-runs"
            isolated_root = root / "isolated-runs"
            logger = TranslationRunLogger.start(
                root=ambient_root,
                metadata=TranslationRunMetadata(
                    job_id="job-ambient-reader-explorer",
                    order_id="order-ambient-reader-explorer",
                    user_id="telegram:715",
                    file_name="ambient-reader-explorer.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    total_fragment_count=1,
                ),
            )
            logger.finish(status="ready", result_file_name="ambient.uk.txt")

            with patch.dict(
                os.environ,
                {"TRANSLATION_RUN_LOG_ROOT": str(ambient_root)},
            ):
                client = TestClient(
                    create_app(
                        settings=Settings(
                            admin_owner_password=("owner-" "pass"),
                            admin_session_secret=("session-" "secret"),
                            translation_run_log_root=str(isolated_root),
                        )
                    )
                )
                client.post("/admin/login", data={"password": "owner-pass"})
                page = client.get("/admin/internal-reader")

        self.assertEqual(page.status_code, 200)
        self.assertIn("No translation runs found.", page.text)
        self.assertIn("Local fixture reader", page.text)
        self.assertNotIn("job-ambient-reader-explorer", page.text)
        self.assertNotIn("ambient-reader-explorer.txt", page.text)

    def test_reader_explorer_lists_selected_user_runs_without_raw_text(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_root = root / "runs"
            private_source = "PRIVATE READER EXPLORER RAW SOURCE"
            private_translation = "PRIVATE READER EXPLORER RAW TRANSLATION"
            private_mark = "PRIVATE READER EXPLORER REVIEW MARK"
            long_file_name = "reader-explorer-" + ("long-name-" * 12) + ".txt"
            logger = TranslationRunLogger.start(
                root=run_root,
                metadata=TranslationRunMetadata(
                    job_id="job-reader-explorer-selected",
                    order_id="order-reader-explorer-selected",
                    user_id="telegram:42",
                    file_name=long_file_name,
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    total_fragment_count=1,
                ),
            )
            logger.record_fragment(
                TranslationFragmentLog(
                    sequence=1,
                    source_text=private_source,
                    translated_text=private_translation,
                    status="ready",
                    elapsed_seconds=1.0,
                    prompt_tokens=11,
                    completion_tokens=7,
                    total_tokens=18,
                )
            )
            logger.finish(status="ready", result_file_name="book.uk.txt")
            (Path(logger.run_dir) / "reader_review_marks.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "marks": [
                            {
                                "sequence": 1,
                                "mark": "needs_review",
                                "source_text": private_mark,
                                "translated_text": private_mark,
                                "status": "ready",
                                "source_block_ids": ["block-1"],
                                "updated_at": "2026-06-06T00:00:00+00:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            other_logger = TranslationRunLogger.start(
                root=run_root,
                metadata=TranslationRunMetadata(
                    job_id="job-reader-explorer-other",
                    order_id="order-reader-explorer-other",
                    user_id="telegram:100",
                    file_name="other-user-book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                    total_fragment_count=1,
                ),
            )
            other_logger.finish(status="ready")
            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=str(run_root),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            page = client.get(
                "/admin/internal-reader",
                params={"user_id": "telegram:42"},
            )

        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers["cache-control"], "no-store")
        self.assertIn("Reader Explorer", page.text)
        self.assertIn("telegram:42", page.text)
        self.assertIn("telegram:100", page.text)
        self.assertIn("job-reader-explorer-selected", page.text)
        self.assertIn(long_file_name, page.text)
        self.assertIn("en -&gt; uk", page.text)
        self.assertIn(f"/admin/logs/{logger.run_dir.name}/reader", page.text)
        self.assertIn(
            f"/admin/logs/{logger.run_dir.name}/text-diagnostics",
            page.text,
        )
        self.assertIn(f"/admin/logs/{logger.run_dir.name}", page.text)
        self.assertNotIn("job-reader-explorer-other", page.text)
        self.assertNotIn("other-user-book.txt", page.text)
        self.assertNotIn(private_source, page.text)
        self.assertNotIn(private_translation, page.text)
        self.assertNotIn(private_mark, page.text)
        self.assertNotIn("reader_review_marks", page.text)

    def test_internal_reader_preview_renders_txt_with_optional_mapping(self):
        with TemporaryDirectory() as temp_dir:
            mapping_path = Path(temp_dir) / "translations.json"
            mapping_path.write_text(
                json.dumps({"txt:segment:1": "Демо-переклад"}),
                encoding="utf-8",
            )
            self.client.post("/admin/login", data={"password": "owner-pass"})

            response = self.client.get(
                "/admin/internal-reader/preview",
                params={
                    "source": "test_samples/sample_book.en.txt",
                    "mapping": str(mapping_path),
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("Format: txt", response.text)
        self.assertIn("Демо-переклад", response.text)
        self.assertIn("status-done", response.text)
        self.assertIn("status-missing", response.text)

    def test_internal_reader_preview_renders_docx_and_epub_samples(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        docx = self.client.get(
            "/admin/internal-reader/preview",
            params={"source": "test_samples/sample_book.en.docx"},
        )
        epub = self.client.get(
            "/admin/internal-reader/preview",
            params={"source": "test_samples/sample_book.en.epub"},
        )

        self.assertEqual(docx.status_code, 200)
        self.assertIn("Format: docx", docx.text)
        self.assertIn("docx-structure-preview", docx.text)
        self.assertEqual(epub.status_code, 200)
        self.assertIn("Format: epub", epub.text)
        self.assertIn("chapter-previews", epub.text)
        self.assertIn('sandbox=""', epub.text)

    def test_internal_reader_preview_uses_sample_selection_before_manual_source(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        response = self.client.get(
            "/admin/internal-reader/preview",
            params={
                "source_select": "test_samples/sample_book.en.txt",
                "source": "test_samples/sample_book.en.epub",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Format: txt", response.text)

    def test_internal_reader_preview_rejects_unsupported_format_and_var_paths(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        unsupported = self.client.get(
            "/admin/internal-reader/preview",
            params={"source": "test_samples/sample_book.en.txt", "format": "pdf"},
        )
        runtime_var = self.client.get(
            "/admin/internal-reader/preview",
            params={"source": "var/sample_book.en.txt"},
        )

        self.assertEqual(unsupported.status_code, 400)
        self.assertIn("Unsupported source format", unsupported.text)
        self.assertEqual(runtime_var.status_code, 400)
        self.assertIn("runtime var/", runtime_var.text)

    def test_internal_reader_preview_reports_missing_source_file(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        response = self.client.get(
            "/admin/internal-reader/preview",
            params={"source": "test_samples/does-not-exist.epub"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Source file was not found.", response.text)
        self.assertNotIn("Format:", response.text)

    def test_internal_reader_preview_reports_invalid_mapping_without_raw_text(self):
        with TemporaryDirectory() as temp_dir:
            mapping_path = Path(temp_dir) / "translations.json"
            mapping_path.write_text("[not an object]", encoding="utf-8")
            self.client.post("/admin/login", data={"password": "owner-pass"})

            response = self.client.get(
                "/admin/internal-reader/preview",
                params={
                    "source": "test_samples/sample_book.en.txt",
                    "mapping": str(mapping_path),
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid translation mapping", response.text)
        self.assertNotIn("Format: txt", response.text)

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

            self.assertIn("Limits", page.text)
            self.assertIn("Pause all beta translations", page.text)
            self.assertIn("Global daily cost cap USD", page.text)
            self.assertIn('action="/admin/settings/beta-safety"', page.text)

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
        self.assertIn("Triage inbox", response.text)
        self.assertIn("integrations_missing", response.text)
        self.assertIn("/admin/integrations", response.text)
        self.assertIn("action-list-header", response.text)
        self.assertIn("triage-severity-badge", response.text)
        self.assertNotIn("pending actions will live here", response.text)

    def test_overview_links_failed_translation_to_trace_triage(self):
        with TemporaryDirectory() as temp_dir:
            log_root = Path(temp_dir) / "translation-runs"
            logger = TranslationRunLogger.start(
                root=log_root,
                metadata=TranslationRunMetadata(
                    job_id="job-overview-failed",
                    order_id="order-overview-failed",
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    translator_model="deepseek",
                ),
            )
            logger.finish(
                status="failed",
                error_message=(
                    "Provider failed with Bearer overview-trace-token "
                    "api_key=sk-overview-trace-secret"
                ),
            )
            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=str(log_root),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            response = client.get("/admin/overview")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Triage inbox", response.text)
        self.assertIn("Translation failed", response.text)
        self.assertIn("book.txt", response.text)
        self.assertIn("job-overview-failed", response.text)
        self.assertIn("Open trace", response.text)
        self.assertIn(
            f'href="/admin/translations/{logger.run_dir.name}/trace"',
            response.text,
        )
        self.assertNotIn("overview-trace-token", response.text)
        self.assertNotIn("sk-ove...cret", response.text)

    def test_admin_action_center_critical_severity_renders_critical_label(self):
        from translator_service.admin import views
        from translator_service.admin.action_center import ActionCenter, ActionItem

        html = views.overview_body(
            ActionCenter(
                items=(
                    ActionItem(
                        key="critical-check",
                        severity="critical",
                        title="Critical diagnostic needs owner review",
                        detail="Existing metadata crossed a critical threshold.",
                        href="/admin/live",
                    ),
                )
            )
        )

        css = views._css()
        self.assertIn("action-critical", html)
        self.assertIn(".action-critical .status", css)
        self.assertIn("background: #fff1f0", css)
        self.assertIn("Critical", html)
        self.assertNotIn("Blocked", html)

    def test_admin_action_center_blocked_severity_stays_blocked_label(self):
        from translator_service.admin.action_center import ActionCenter, ActionItem
        from translator_service.admin.views import overview_body

        html = overview_body(
            ActionCenter(
                items=(
                    ActionItem(
                        key="blocked-check",
                        severity="blocked",
                        title="Owner action is blocked",
                        detail="Existing metadata says this item is blocked.",
                        href="/admin/live",
                    ),
                )
            )
        )

        self.assertIn("action-blocked", html)
        self.assertIn("Blocked", html)
        self.assertNotIn("Critical", html)

    def test_overview_action_center_redacts_deepseek_balance_error(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})
        raw_key = "sk-ove...cret"
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
            ("/admin/translations", "Translations"),
            ("/admin/beta-controls", "Settings"),
            ("/admin/billing", "Billing"),
            ("/admin/costs", "Costs"),
            ("/admin/quality", "Quality"),
            ("/admin/live", "Live Monitor"),
            ("/admin/logs", "Logs"),
            ("/admin/settings", "Settings"),
            ("/admin/operations/jobs", "Jobs / Queue"),
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

    def test_costs_page_uses_persistent_usage_when_run_log_totals_are_zero(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_db = root / "jobs.sqlite3"
            run_root = root / "runs"
            store = SQLiteTranslationJobStore(str(job_db))
            try:
                job = _persistent_job(store, order_id="order-costs-stale")
                [unit] = _add_units(store, job.id)
                store.complete_work_unit(
                    unit.id,
                    translated_text="Translated text hidden from costs.",
                    prompt_tokens=1_500,
                    completion_tokens=500,
                    cache_hit_tokens=0,
                    cache_miss_tokens=1_500,
                )
            finally:
                store.close()
            logger = TranslationRunLogger.start(
                root=run_root,
                metadata=TranslationRunMetadata(
                    job_id=job.id,
                    order_id=job.order_id,
                    user_id=job.user_id,
                    file_name=job.file_name,
                    document_kind=job.document_kind,
                    source_language=job.source_language,
                    target_language=job.target_language,
                    translator_model="deepseek",
                ),
            )
            logger.finish(status="ready", result_file_name="book.uk.txt")
            settings = Settings(
                admin_db_path=str(root / "admin.sqlite3"),
                persistent_jobs_db_path=str(job_db),
                translation_run_log_root=str(run_root),
                admin_owner_password="owner-pass",
                admin_session_secret="session-secret",
            )
            client = TestClient(create_app(settings=settings))
            client.post("/admin/login", data={"password": "owner-pass"})

            page = client.get("/admin/costs")
            api = client.get("/admin/api/costs")

        self.assertEqual(page.status_code, 200)
        self.assertIn(job.id, page.text)
        self.assertIn("<td>1500</td>", page.text)
        self.assertIn("<td>500</td>", page.text)
        self.assertIn("<td>2000</td>", page.text)
        self.assertIn("$0.0010", page.text)
        self.assertNotIn("Translated text hidden from costs.", page.text)
        self.assertEqual(api.status_code, 200)
        payload = api.json()
        self.assertEqual(payload["tokens_today"], 2000)
        self.assertEqual(payload["top_runs"][0]["job_id"], job.id)
        self.assertEqual(payload["top_runs"][0]["prompt_tokens"], 1500)
        self.assertEqual(payload["top_runs"][0]["completion_tokens"], 500)
        self.assertEqual(payload["top_runs"][0]["total_tokens"], 2000)
        self.assertEqual(payload["top_users"][0]["total_tokens"], 2000)
        self.assertEqual(payload["unavailable_run_count"], 0)

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
                            "prompt_policy_version": "prompt-policy-v10",
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
            admin_db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteUserActivityStore(admin_db_path) as activity_store:
                activity_store.record_event(
                    UserActivityEventInput(
                        actor_type=ActivityActorType.USER,
                        actor_id="telegram:42",
                        channel="telegram",
                        channel_user_id="42",
                        surface=ActivitySurface.BOT,
                        event_type="translation.button.clicked",
                        action="continue",
                        target_type="button",
                        target_id="continue api_key=sk-trace-activity-secret",
                        outcome=ActivityOutcome.SUCCESS,
                        job_id="job-logs-1",
                        metadata={"source_text": "RAW TRACE ACTIVITY SOURCE"},
                    )
                )
            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=temp_dir,
                        admin_db_path=str(admin_db_path),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            page = client.get("/admin/logs?status=ready")
            api = client.get("/admin/api/logs?status=ready")
            trace = client.get(f"/admin/translations/{logger.run_dir.name}/trace")
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
            self.assertIn("activity: continue", trace.text)
            self.assertIn("target=button", trace.text)
            self.assertIn("target_id=continue [redacted]", trace.text)
            self.assertIn("Advanced log detail", trace.text)
            self.assertIn("Evidence packet copy/download is tracked", trace.text)
            self.assertNotIn("Chapter one", trace.text)
            self.assertNotIn("Глава первая", trace.text)
            self.assertNotIn("processing-bearer-token", trace.text)
            self.assertNotIn("sk-processing-secret-value", trace.text)
            self.assertNotIn("deepseek.api_keys.processing-key", trace.text)
            self.assertNotIn("sk-trace-activity-secret", trace.text)
            self.assertNotIn("RAW TRACE ACTIVITY SOURCE", trace.text)
            details_text = _compact_text(details.text)
            self.assertEqual(details.status_code, 200)
            self.assertIn("Translation Details", details.text)
            self.assertIn('href="/admin/translations"', details.text)
            self.assertIn("Back to translations", details.text)
            self.assertIn('href="/admin/logs"', details.text)
            self.assertIn("Back to run logs", details.text)
            self.assertNotIn("return_to", details.text)
            self.assertIn(
                "Normal detail UI/API shows bounded recent fragment and event rows",
                details_text,
            )
            self.assertIn(
                "deeper inspection through Text diagnostics, Reader, or "
                "Download archive",
                details_text,
            )
            self.assertIn(
                "Archive is generated and downloaded only after explicit owner action",
                details_text,
            )
            self.assertIn(
                "may include sensitive owner-only diagnostic material",
                details_text,
            )
            self.assertIn(
                "Do not publish archive contents to issues, PRs, support notes, "
                "or release artifacts unless explicitly approved",
                details_text,
            )
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
            self.assertEqual(api.headers["cache-control"], "no-store")
            payload = api.json()
            self.assertEqual(payload["logs"][0]["job_id"], "job-logs-1")
            self.assertEqual(payload["logs"][0]["status"], "ready")
            self.assertEqual(payload["logs"][0]["fragment_count"], 1)
            self.assertEqual(payload["logs"][0]["total_fragment_count"], 1)
            self.assertEqual(payload["logs"][0]["progress_percent"], 100.0)
            self.assertEqual(payload["logs"][0]["current_stage"], "run_finished")
            self.assertIn("last_event_at", payload["logs"][0])
            self.assertEqual(details_api.status_code, 200)
            self.assertEqual(details_api.headers["cache-control"], "no-store")
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
            self.assertNotIn("sk-pro...alue", archive_text)
            self.assertNotIn("deepseek.api_keys.processing-key", archive_text)

    def test_translation_log_detail_and_api_default_to_bounded_recent_history(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-large-log-history",
                    order_id="order-large-log-history",
                    user_id="telegram:42",
                    file_name="large-log.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                    total_fragment_count=105,
                ),
            )
            for sequence in range(1, 106):
                status = (
                    "old-status-sentinel"
                    if sequence == 1
                    else f"recent-status-{sequence}"
                )
                logger.record_fragment(
                    TranslationFragmentLog(
                        sequence=sequence,
                        source_text=f"private source {sequence}",
                        translated_text=f"private translation {sequence}",
                        status=status,
                        elapsed_seconds=1.0,
                        prompt_tokens=1,
                        completion_tokens=1,
                        total_tokens=2,
                        source_block_ids=(f"block-{sequence}",),
                    )
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

            details = client.get(f"/admin/logs/{logger.run_dir.name}")
            details_api = client.get(f"/admin/api/logs/{logger.run_dir.name}")

        self.assertEqual(details.status_code, 200)
        details_text = _compact_text(details.text)
        self.assertIn(
            "Normal detail UI/API shows bounded recent fragment rows",
            details_text,
        )
        self.assertIn("Showing latest 100 fragment rows", details_text)
        self.assertIn(
            "Use Text diagnostics, Reader, or Download archive for explicit "
            "deeper inspection.",
            details_text,
        )
        self.assertIn("recent-status-105", details.text)
        self.assertNotIn("old-status-sentinel", details.text)
        self.assertNotIn("block-1<", details.text)
        self.assertEqual(details_api.status_code, 200)
        fragments = details_api.json()["details"]["fragments"]
        events = details_api.json()["details"]["events"]
        self.assertEqual(len(fragments), 100)
        self.assertEqual(len(events), 100)
        self.assertEqual(fragments[0]["sequence"], 6)
        self.assertEqual(fragments[-1]["sequence"], 105)
        self.assertEqual(events[-1]["payload"]["sequence"], 105)
        serialized_api = json.dumps(details_api.json(), ensure_ascii=False)
        self.assertNotIn("old-status-sentinel", serialized_api)

    def test_translation_log_api_persistent_fallback_uses_bounded_recent_work_units(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_root = root / "runs"
            job_db = root / "jobs.sqlite3"
            store = SQLiteTranslationJobStore(job_db)
            try:
                job = store.create_job(
                    order_id="order-work-unit-bound",
                    user_id="telegram:42",
                    file_id="file-work-unit-bound",
                    file_name="large-work-units.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                    adapter_version="txt-adapter-v1",
                    prompt_version="plain-v1",
                    pricing_snapshot_id="pricing-1",
                )
                store.add_work_units(
                    job.id,
                    [
                        WorkUnitPlan(
                            sequence=sequence,
                            source_block_ids=(f"block-{sequence}",),
                            source_text_hash=f"hash-{sequence}",
                            prompt_tier="plain",
                            source_language="en",
                            target_language="ru",
                        )
                        for sequence in range(1, 106)
                    ],
                )
            finally:
                store.close()
            logger = TranslationRunLogger.start(
                root=run_root,
                metadata=TranslationRunMetadata(
                    job_id=job.id,
                    order_id=job.order_id,
                    user_id=job.user_id,
                    file_name=job.file_name,
                    document_kind=job.document_kind,
                    source_language=job.source_language,
                    target_language=job.target_language,
                    total_fragment_count=105,
                ),
            )
            logger.finish(status="active")
            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=str(run_root),
                        persistent_jobs_db_path=str(job_db),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            with (
                patch.object(
                    SQLiteTranslationJobStore,
                    "list_work_units",
                    side_effect=AssertionError("unbounded work unit listing"),
                ),
                patch(
                    "translator_service.admin.routes._operations_overview",
                    return_value=None,
                ),
                patch(
                    "translator_service.admin.routes._translation_work_unit_diagnostic",
                    return_value=None,
                ),
            ):
                details_api = client.get(f"/admin/api/logs/{logger.run_dir.name}")

        self.assertEqual(details_api.status_code, 200)
        fragments = details_api.json()["details"]["fragments"]
        self.assertEqual(len(fragments), 100)
        self.assertEqual(fragments[0]["sequence"], 6)
        self.assertEqual(fragments[-1]["sequence"], 105)
        source_block_ids = [
            block_id
            for fragment in fragments
            for block_id in fragment["source_block_ids"]
        ]
        self.assertNotIn("block-1", source_block_ids)

    def test_translation_log_download_uses_effective_scheduler_snapshot(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_db = root / "jobs.sqlite3"
            object_root = root / "objects"
            run_root = root / "runs"
            storage = LocalObjectStorage(object_root)
            failed_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-10.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Private source paragraph",
            )
            store = SQLiteTranslationJobStore(job_db)
            try:
                job = store.create_job(
                    order_id="order-stale-export",
                    user_id="telegram:42",
                    file_id="file-stale-export",
                    file_name="pg55-images-3.epub",
                    document_kind="epub",
                    source_language="auto",
                    target_language="ru",
                    adapter_version="epub-adapter-v1",
                    prompt_version="plain-v1",
                    pricing_snapshot_id="pricing-1",
                )
                store.add_work_units(
                    job.id,
                    [
                        WorkUnitPlan(
                            sequence=sequence,
                            source_block_ids=(f"block-{sequence}",),
                            source_text_hash=f"hash-{sequence}",
                            prompt_tier="plain",
                            source_language="auto",
                            target_language="ru",
                            source_object_key=(
                                failed_source.object_key
                                if sequence == 10
                                else None
                            ),
                        )
                        for sequence in range(1, 187)
                    ],
                )
                limits = SchedulerLimits(max_active_units_global=1)
                for _ in range(9):
                    claim = store.claim_next_scheduled_work_unit(
                        worker_id="worker-a",
                        lease_seconds=300,
                        limits=limits,
                    )
                    assert claim is not None
                    store.complete_claimed_work_unit(
                        work_unit_id=claim.work_unit_id,
                        claim_token=claim.claim_token,
                        translated_text="Translated text hidden from archive",
                        prompt_tokens=10,
                        completion_tokens=5,
                        cache_hit_tokens=2,
                        cache_miss_tokens=8,
                    )
                for _ in range(3):
                    claim = store.claim_next_scheduled_work_unit(
                        worker_id="worker-a",
                        lease_seconds=300,
                        limits=limits,
                    )
                    assert claim is not None
                    store.fail_claimed_work_unit(
                        work_unit_id=claim.work_unit_id,
                        claim_token=claim.claim_token,
                        failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
                        error_message=(
                            "provider failed on Private source paragraph "
                            "with Bearer provider-secret and "
                            "api_key=sk-provider-secret"
                        ),
                        retry_base_delay_seconds=0,
                        retry_max_delay_seconds=0,
                        provider_failure_diagnostic=ProviderFailureDiagnostic(
                            failure_category=ProviderFailureCategory.MALFORMED_RESPONSE,
                            http_status_bucket=None,
                            provider_id="deepseek",
                            channel_fingerprint="chan_test123456",
                            latency_ms=842.0,
                            adaptive_circuit_snapshot={"circuit_state": "closed"},
                        ),
                    )
            finally:
                store.close()

            logger = TranslationRunLogger.start(
                root=run_root,
                metadata=TranslationRunMetadata(
                    job_id=job.id,
                    order_id=None,
                    user_id="telegram:42",
                    file_name="pg55-images-3.epub",
                    document_kind="epub",
                    source_language="auto",
                    target_language="ru",
                    total_fragment_count=186,
                ),
            )
            logger.record_event("job_queued", {"job_id": job.id, "fragment_count": 186})
            logger.finish(
                status="failed",
                error_message="Translation failed in the background worker.",
            )
            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=str(run_root),
                        persistent_jobs_db_path=str(job_db),
                        object_storage_root=str(object_root),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            download = client.get(f"/admin/logs/{logger.run_dir.name}/download")

        self.assertEqual(download.status_code, 200)
        with ZipFile(BytesIO(download.content)) as archive:
            names = set(archive.namelist())
            self.assertIn("run.json", names)
            self.assertIn("effective_run.json", names)
            self.assertIn("work_units.json", names)
            self.assertIn("raw_text_diagnostics.json", names)
            self.assertIn("README.md", names)
            raw_run = json.loads(archive.read("run.json"))
            effective = json.loads(archive.read("effective_run.json"))
            work_units = json.loads(archive.read("work_units.json"))
            raw_text_diagnostics = json.loads(
                archive.read("raw_text_diagnostics.json")
            )
            metadata_text = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in {
                    "run.json",
                    "effective_run.json",
                    "work_units.json",
                }
            )
            archive_text = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in names
            )

        self.assertEqual(raw_run["fragment_count"], 0)
        self.assertEqual(effective["summary"]["fragment_count"], 9)
        self.assertEqual(effective["summary"]["total_fragment_count"], 186)
        self.assertEqual(effective["summary"]["status"], "interrupted")
        self.assertEqual(effective["totals"]["prompt_tokens"], 90)
        self.assertEqual(effective["totals"]["completion_tokens"], 45)
        self.assertEqual(work_units["counts_by_status"]["translated"], 9)
        self.assertEqual(work_units["counts_by_status"]["failed_terminal"], 1)
        self.assertEqual(work_units["counts_by_status"]["pending"], 176)
        self.assertEqual(work_units["attention_unit"]["sequence"], 10)
        self.assertEqual(work_units["attention_unit"]["attempt_count"], 3)
        self.assertTrue(raw_text_diagnostics["contains_raw_text"])
        self.assertEqual(raw_text_diagnostics["job_id"], job.id)
        self.assertEqual(raw_text_diagnostics["total_rows"], 186)
        attempt_rows = raw_text_diagnostics["attempts"]
        provider_failure_rows = raw_text_diagnostics["provider_failure_events"]
        self.assertEqual(
            [row["attempt_number"] for row in attempt_rows if row["sequence"] == 10],
            [1, 2, 3],
        )
        self.assertIn(
            "failed_terminal",
            {row["status"] for row in attempt_rows if row["sequence"] == 10},
        )
        self.assertTrue(
            any(row["sequence"] == 10 for row in provider_failure_rows),
        )
        raw_rows_text = json.dumps(raw_text_diagnostics, ensure_ascii=False)
        self.assertIn("Private source paragraph", raw_rows_text)
        self.assertIn("Translated text hidden from archive", raw_rows_text)
        self.assertNotIn("Private source paragraph", metadata_text)
        self.assertNotIn("Translated text hidden from archive", metadata_text)
        self.assertNotIn("provider-secret", archive_text)
        self.assertNotIn("sk-provider-secret", archive_text)

    def test_translation_log_download_includes_prepared_glossary_metadata(self):
        with TemporaryDirectory() as temp_dir:
            run_root = Path(temp_dir) / "runs"
            logger = TranslationRunLogger.start(
                root=run_root,
                metadata=TranslationRunMetadata(
                    job_id="job-prepared-glossary",
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
            append_translation_run_event_for_job(
                run_root,
                job_id="job-prepared-glossary",
                event_type="glossary_runtime_adapter",
                payload={
                    "status": "planned",
                    "fallback_reason": "none",
                    "work_unit_sequence": 1,
                    "selected_entry_ids": ["glossary-entry:v1:darcy"],
                    "cache_policy": {
                        "behavior": "bypass_glossary_injected_cache",
                    },
                    "prompt_context": {
                        "included_entry_count": 1,
                        "included_entry_ids": ["glossary-entry:v1:darcy"],
                    },
                    "prepared_package": {
                        "schema_version": "prepared-glossary-package-v1",
                        "metadata_only": True,
                        "raw_payload_included": False,
                        "status": "ready",
                        "reason_codes": ["ready"],
                        "package_id": "prepared:book:ru",
                        "package_signature": "prepared-signature",
                        "source_language": "en",
                        "target_language": "ru",
                        "provider_role_id": "deepseek-pro-glossary-prep",
                        "provider_model": "deepseek-v4-pro",
                        "entry_count": 2,
                        "ready_entry_count": 2,
                        "needs_review_entry_count": 0,
                    },
                },
            )
            logger.finish(status="completed", result_file_name="book.ru.epub")
            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=str(run_root),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            download = client.get(f"/admin/logs/{logger.run_dir.name}/download")

        self.assertEqual(download.status_code, 200)
        with ZipFile(BytesIO(download.content)) as archive:
            names = set(archive.namelist())
            self.assertIn("glossary_runtime_diagnostics.json", names)
            diagnostics = json.loads(
                archive.read("glossary_runtime_diagnostics.json")
            )
            archive_text = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in names
            )

        self.assertEqual(diagnostics["glossary_mode"], "with_glossary")
        self.assertEqual(diagnostics["summary"]["prepared_package_event_count"], 1)
        self.assertEqual(
            diagnostics["summary"]["prepared_package_statuses"],
            ["ready"],
        )
        self.assertEqual(
            diagnostics["summary"]["prepared_package_reason_codes"],
            ["ready"],
        )
        prepared_event = diagnostics["prepared_package_events"][0]
        self.assertEqual(prepared_event["package_id"], "prepared:book:ru")
        self.assertEqual(prepared_event["ready_entry_count"], 2)
        self.assertEqual(prepared_event["needs_review_entry_count"], 0)
        self.assertEqual(
            prepared_event["resolver_linkage"]["cache_behavior"],
            "bypass_glossary_injected_cache",
        )
        self.assertTrue(prepared_event["resolver_linkage"]["prompt_context_included"])
        self.assertNotIn("authorization_header", archive_text)
        self.assertNotIn("Bearer ", archive_text)

    def test_translation_log_download_summarizes_prompt_context_budget_omissions(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            run_root = Path(temp_dir) / "runs"
            logger = TranslationRunLogger.start(
                root=run_root,
                metadata=TranslationRunMetadata(
                    job_id="job-glossary-budget-omission",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.docx",
                    document_kind="docx",
                    source_language="en",
                    target_language="ru",
                    translation_policy=json.dumps(
                        {"glossary_mode": "with_glossary"},
                        ensure_ascii=False,
                    ),
                ),
            )
            append_translation_run_event_for_job(
                run_root,
                job_id="job-glossary-budget-omission",
                event_type="glossary_runtime_adapter",
                payload={
                    "status": "fallback",
                    "fallback_reason": "prompt_context_budget_exhausted",
                    "work_unit_sequence": 1,
                    "selected_entry_ids": ["glossary-entry:v1:darcy"],
                    "prompt_context": {
                        "included_entry_count": 0,
                        "included_entry_ids": [],
                        "omitted_entry_count": 1,
                        "omitted_entry_ids": ["glossary-entry:v1:darcy"],
                        "omission_reason_counts": {
                            "prompt_budget_exhausted": 1,
                        },
                        "omitted_entries": [
                            {
                                "entry_id": "glossary-entry:v1:darcy",
                                "reason": "prompt_budget_exhausted",
                                "estimated_prompt_tokens": 99,
                            }
                        ],
                    },
                },
            )
            logger.finish(status="completed", result_file_name="book.ru.docx")
            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=str(run_root),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            download = client.get(f"/admin/logs/{logger.run_dir.name}/download")

        self.assertEqual(download.status_code, 200)
        with ZipFile(BytesIO(download.content)) as archive:
            diagnostics = json.loads(
                archive.read("glossary_runtime_diagnostics.json")
            )
            archive_text = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in archive.namelist()
            )

        self.assertEqual(
            diagnostics["summary"]["prompt_context_omission_reason_counts"],
            {"prompt_budget_exhausted": 1},
        )
        prompt_context_event = diagnostics["prompt_context_events"][0]
        self.assertFalse(prompt_context_event["included"])
        self.assertEqual(prompt_context_event["omitted_entry_count"], 1)
        self.assertEqual(
            prompt_context_event["omitted_entry_ids"],
            ["glossary-entry:v1:darcy"],
        )
        self.assertEqual(
            prompt_context_event["omission_reason_counts"],
            {"prompt_budget_exhausted": 1},
        )
        self.assertNotIn("Darcy returns", archive_text)
        self.assertNotIn("Дарси", archive_text)

    def test_translation_log_download_omits_glossary_sidecar_without_adapter_event(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            run_root = Path(temp_dir) / "runs"
            logger = TranslationRunLogger.start(
                root=run_root,
                metadata=TranslationRunMetadata(
                    job_id="job-without-glossary",
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
            logger.run_dir.joinpath("provider_io_diagnostics.jsonl").write_text(
                json.dumps(
                    {
                        "request_body": {
                            "text": (
                                "<glossary_context>should not matter"
                                "</glossary_context>"
                            ),
                        },
                        "response_body": {"text": "ignored"},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            logger.finish(status="completed", result_file_name="book.ru.epub")
            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=str(run_root),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            download = client.get(f"/admin/logs/{logger.run_dir.name}/download")

        self.assertEqual(download.status_code, 200)
        with ZipFile(BytesIO(download.content)) as archive:
            names = set(archive.namelist())

        self.assertNotIn("glossary_runtime_diagnostics.json", names)

    def test_translation_log_download_redacts_prepared_glossary_secrets(self):
        with TemporaryDirectory() as temp_dir:
            run_root = Path(temp_dir) / "runs"
            logger = TranslationRunLogger.start(
                root=run_root,
                metadata=TranslationRunMetadata(
                    job_id="job-prepared-secret",
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
            append_translation_run_event_for_job(
                run_root,
                job_id="job-prepared-secret",
                event_type="glossary_runtime_adapter",
                payload={
                    "status": "fallback",
                    "fallback_reason": "persistent_epub_prepared_package_invalid",
                    "prompt_body": "RAW PROMPT SENTINEL",
                    "provider_response": "RAW PROVIDER SENTINEL",
                    "source_text": "RAW SOURCE SENTINEL",
                    "prepared_package": {
                        "schema_version": "prepared-glossary-package-v1",
                        "metadata_only": True,
                        "raw_payload_included": False,
                        "status": "invalid",
                        "reason_codes": ["prepared_glossary_package_invalid"],
                        "package_id": "sk-prepared-secret-value",
                        "package_signature": "postgres://secret:user@localhost/db",
                        "target_language": "ru",
                        "provider_model": "deepseek-v4-pro",
                        "api_key": "sk-prepared-api-secret",
                        "authorization_header": "Bearer prepared-secret",
                        "raw_source_text": "RAW PREP SOURCE SENTINEL",
                    },
                },
            )
            logger.finish(status="failed", error_message="metadata-only failure")
            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=str(run_root),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            download = client.get(f"/admin/logs/{logger.run_dir.name}/download")

        self.assertEqual(download.status_code, 200)
        with ZipFile(BytesIO(download.content)) as archive:
            diagnostics = json.loads(
                archive.read("glossary_runtime_diagnostics.json")
            )
            archive_text = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in archive.namelist()
            )

        self.assertTrue(diagnostics["secret_material_rejected"])
        self.assertGreaterEqual(diagnostics["secret_redaction_count"], 1)
        self.assertIn("[redacted]", archive_text)
        self.assertNotIn("sk-prepared-secret-value", archive_text)
        self.assertNotIn("sk-prepared-api-secret", archive_text)
        self.assertNotIn("postgres://secret:user@localhost/db", archive_text)
        self.assertNotIn("Bearer prepared-secret", archive_text)
        self.assertNotIn("RAW PROMPT SENTINEL", archive_text)
        self.assertNotIn("RAW PROVIDER SENTINEL", archive_text)
        self.assertNotIn("RAW SOURCE SENTINEL", archive_text)
        self.assertNotIn("RAW PREP SOURCE SENTINEL", archive_text)

    def test_translation_log_download_effective_run_uses_persistent_partial_result_name(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_root = root / "runs"
            job_db = root / "jobs.sqlite3"
            object_root = root / "objects"
            storage = LocalObjectStorage(object_root)
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.epub",
                content_type="application/epub+zip",
                content=b"synthetic source placeholder",
            )
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph.",
            )
            partial = storage.put_bytes(
                kind=StoredFileKind.PARTIAL,
                file_name="book.uk.partial.epub",
                content_type="application/epub+zip",
                content=b"synthetic partial placeholder",
            )
            store = SQLiteTranslationJobStore(job_db)
            try:
                job = store.create_job(
                    order_id="order-partial-export",
                    user_id="telegram:42",
                    file_id="file-partial-export",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="uk",
                    adapter_version="epub-adapter-v1",
                    prompt_version="plain-v1",
                    pricing_snapshot_id="pricing-1",
                    source_object_key=original.object_key,
                )
                store.add_work_units(
                    job.id,
                    [
                        WorkUnitPlan(
                            sequence=1,
                            source_block_ids=("epub:OPS/chapter.xhtml:1",),
                            source_text_hash="hash-1",
                            prompt_tier="plain",
                            source_language="en",
                            target_language="uk",
                            source_object_key=source.object_key,
                        )
                    ],
                )
                claim = store.claim_next_scheduled_work_unit(
                    worker_id="worker-a",
                    lease_seconds=300,
                    limits=SchedulerLimits(),
                )
                store.complete_claimed_work_unit(
                    work_unit_id=claim.work_unit_id,
                    claim_token=claim.claim_token,
                    translated_text="Translated text hidden from metadata export",
                    prompt_tokens=10,
                    completion_tokens=5,
                    cache_hit_tokens=0,
                    cache_miss_tokens=10,
                )
                store.attach_job_output(
                    job.id,
                    partial_object_key=partial.object_key,
                )
                store.mark_job_assembled(job.id, partial=True)
            finally:
                store.close()
            logger = TranslationRunLogger.start(
                root=run_root,
                metadata=TranslationRunMetadata(
                    job_id=job.id,
                    order_id=job.order_id,
                    user_id=job.user_id,
                    file_name=job.file_name,
                    document_kind=job.document_kind,
                    source_language=job.source_language,
                    target_language=job.target_language,
                    total_fragment_count=1,
                ),
            )
            logger.finish(
                status="failed",
                error_message="Translation failed in the background worker.",
            )
            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=str(run_root),
                        persistent_jobs_db_path=str(job_db),
                        object_storage_root=str(object_root),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            download = client.get(f"/admin/logs/{logger.run_dir.name}/download")

        self.assertEqual(download.status_code, 200)
        with ZipFile(BytesIO(download.content)) as archive:
            names = set(archive.namelist())
            raw_run = json.loads(archive.read("run.json"))
            effective = json.loads(archive.read("effective_run.json"))
            diagnostic_files = json.loads(
                archive.read("diagnostic_files/manifest.json")
            )
            original_file_bytes = archive.read(
                "diagnostic_files/original_file/book.epub"
            )
            translated_result_bytes = archive.read(
                "diagnostic_files/translated_result/book.uk.partial.epub"
            )
            readme = archive.read("README.md").decode("utf-8")
            metadata_text = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in {
                    "run.json",
                    "effective_run.json",
                    "work_units.json",
                }
            )

        self.assertIn("diagnostic_files/original_file/book.epub", names)
        self.assertIn(
            "diagnostic_files/translated_result/book.uk.partial.epub",
            names,
        )
        self.assertEqual(original_file_bytes, b"synthetic source placeholder")
        self.assertEqual(
            translated_result_bytes,
            b"synthetic partial placeholder",
        )
        self.assertTrue(diagnostic_files["contains_raw_file_bytes"])
        self.assertEqual(
            {
                entry["role"]: entry["object_kind"]
                for entry in diagnostic_files["files"]
            },
            {"original_file": "original", "translated_result": "partial"},
        )
        self.assertIn("original uploaded file", readme)
        self.assertIn("final or partial", readme)
        self.assertIsNone(raw_run["result_file_name"])
        self.assertEqual(effective["summary"]["status"], "partial")
        self.assertEqual(
            effective["summary"]["result_file_name"],
            "book.uk.partial.epub",
        )
        self.assertNotIn("Translated text hidden from metadata export", metadata_text)
        self.assertNotIn("synthetic source placeholder", metadata_text)
        self.assertNotIn("synthetic partial placeholder", metadata_text)

    def test_translation_log_download_counts_ready_raw_fragments_completed(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_root = root / "runs"
            job_db = root / "missing" / "jobs.sqlite3"
            logger = TranslationRunLogger.start(
                root=run_root,
                metadata=TranslationRunMetadata(
                    job_id="job-ready-raw-export",
                    order_id="order-ready-raw-export",
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    total_fragment_count=1,
                ),
            )
            logger.record_fragment(
                TranslationFragmentLog(
                    sequence=1,
                    source_text="Private source paragraph",
                    translated_text="Private translated paragraph",
                    status="ready",
                    elapsed_seconds=1.0,
                    prompt_tokens=11,
                    completion_tokens=7,
                    total_tokens=18,
                )
            )
            logger.finish(status="ready", result_file_name="book.uk.txt")
            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=str(run_root),
                        persistent_jobs_db_path=str(job_db),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            download = client.get(f"/admin/logs/{logger.run_dir.name}/download")

        self.assertEqual(download.status_code, 200)
        with ZipFile(BytesIO(download.content)) as archive:
            work_units = json.loads(archive.read("work_units.json"))
            effective = json.loads(archive.read("effective_run.json"))
            archive_text = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in archive.namelist()
            )

        self.assertEqual(effective["summary"]["fragment_count"], 1)
        self.assertEqual(effective["summary"]["total_fragment_count"], 1)
        self.assertEqual(work_units["counts_by_status"]["ready"], 1)
        self.assertEqual(work_units["completed_units"], 1)
        self.assertNotIn("Private source paragraph", archive_text)
        self.assertNotIn("Private translated paragraph", archive_text)

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

    def test_translation_logs_overlay_active_scheduler_progress(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-scheduled-progress",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="scheduled.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="uk",
                    total_fragment_count=4,
                ),
            )
            logger.record_event(
                "job_queued",
                {"job_id": "job-scheduled-progress", "fragment_count": 4},
            )
            operations = build_operations_overview(
                jobs=[
                    {
                        "id": "job-scheduled-progress",
                        "status": "translating",
                        "file_name": "scheduled.epub",
                        "document_kind": "epub",
                        "source_language": "en",
                        "target_language": "uk",
                        "created_at": datetime(2026, 5, 31, 9, 0, tzinfo=UTC),
                        "updated_at": datetime(2026, 5, 31, 9, 10, tzinfo=UTC),
                    }
                ],
                work_units_by_job_id={
                    "job-scheduled-progress": (
                        {
                            "status": "translated",
                            "prompt_tokens": 11,
                            "completion_tokens": 7,
                        },
                        {
                            "status": "translated",
                            "prompt_tokens": 13,
                            "completion_tokens": 5,
                        },
                        {"status": "translating"},
                        {"status": "pending"},
                    )
                },
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

            with patch(
                "translator_service.admin.routes._operations_overview",
                return_value=operations,
            ):
                page = client.get("/admin/logs")
                api = client.get("/admin/api/logs")
                details = client.get(f"/admin/logs/{logger.run_dir.name}")
                details_api = client.get(f"/admin/api/logs/{logger.run_dir.name}")
                trace = client.get(
                    f"/admin/translations/{logger.run_dir.name}/trace"
                )

        self.assertEqual(page.status_code, 200)
        self.assertIn("job-scheduled-progress", page.text)
        self.assertIn("2/4", page.text)
        self.assertIn(">36</td>", page.text)
        self.assertNotIn("source_text", page.text)
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.json()["logs"][0]["fragment_count"], 2)
        self.assertEqual(api.json()["logs"][0]["total_fragment_count"], 4)
        self.assertEqual(api.json()["logs"][0]["progress_percent"], 50.0)
        self.assertEqual(api.json()["logs"][0]["total_tokens"], 36)
        self.assertEqual(details.status_code, 200)
        self.assertIn("2/4", details.text)
        self.assertIn("50.0%", details.text)
        self.assertIn("36", details.text)
        self.assertEqual(details_api.status_code, 200)
        self.assertEqual(
            details_api.json()["details"]["summary"]["fragment_count"],
            2,
        )
        self.assertEqual(
            details_api.json()["details"]["summary"]["total_tokens"],
            36,
        )
        self.assertEqual(
            details_api.json()["details"]["totals"]["total_tokens"],
            36,
        )
        self.assertEqual(trace.status_code, 200)
        self.assertIn("2/4", trace.text)
        self.assertIn("36", trace.text)

    def test_admin_surfaces_use_durable_progress_snapshot_for_stale_zero_run(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            admin_db = root / "admin.sqlite3"
            job_db = root / "jobs.sqlite3"
            run_root = root / "runs"
            store = SQLiteTranslationJobStore(job_db)
            try:
                job = store.create_job(
                    order_id="order-durable-progress",
                    user_id="telegram:42",
                    file_id="file-durable-progress",
                    file_name="durable-progress.epub",
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
                            sequence=sequence,
                            source_block_ids=(f"block-{sequence}",),
                            source_text_hash=f"hash-{sequence}",
                            prompt_tier="plain",
                            source_language="en",
                            target_language="ru",
                        )
                        for sequence in range(1, 5)
                    ],
                )
                first = store.claim_next_work_unit(job.id, worker_id="worker-a")
                store.complete_work_unit(
                    first.id,
                    translated_text="PRIVATE TRANSLATED ONE",
                    prompt_tokens=10,
                    completion_tokens=5,
                    cache_hit_tokens=2,
                    cache_miss_tokens=8,
                )
                second = store.claim_next_work_unit(job.id, worker_id="worker-a")
                store.complete_work_unit(
                    second.id,
                    translated_text="PRIVATE TRANSLATED TWO",
                    prompt_tokens=20,
                    completion_tokens=7,
                    cache_hit_tokens=3,
                    cache_miss_tokens=17,
                )
                store.claim_next_work_unit(job.id, worker_id="worker-b")
            finally:
                store.close()

            logger = TranslationRunLogger.start(
                root=run_root,
                metadata=TranslationRunMetadata(
                    job_id=job.id,
                    order_id=job.order_id,
                    user_id=job.user_id,
                    file_name=job.file_name,
                    document_kind=job.document_kind,
                    source_language=job.source_language,
                    target_language=job.target_language,
                    total_fragment_count=0,
                ),
            )
            logger.record_event("job_queued", {"job_id": job.id, "fragment_count": 0})

            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_db_path=str(admin_db),
                        persistent_jobs_db_path=str(job_db),
                        translation_run_log_root=str(run_root),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            live = client.get("/admin/live")
            live_api = client.get("/admin/api/live")
            logs = client.get("/admin/logs")
            logs_api = client.get("/admin/api/logs")
            details = client.get(f"/admin/logs/{logger.run_dir.name}")
            details_api = client.get(f"/admin/api/logs/{logger.run_dir.name}")
            operations = client.get("/admin/operations/jobs")
            operations_api = client.get("/admin/api/operations/overview")
            trace = client.get(f"/admin/translations/{logger.run_dir.name}/trace")

        for response in (
            live,
            live_api,
            logs,
            logs_api,
            details,
            details_api,
            operations,
            operations_api,
            trace,
        ):
            self.assertEqual(response.status_code, 200)

        self.assertIn("2/4", live.text)
        self.assertIn("2/4", logs.text)
        self.assertIn("2/4", details.text)
        self.assertIn("2/4", operations.text)
        self.assertIn("2/4", trace.text)
        self.assertIn("worker-b", operations.text)
        self.assertIn("worker-b", trace.text)
        live_run = live_api.json()["recent_runs"][0]
        self.assertEqual(live_run["job_id"], job.id)
        self.assertEqual(live_run["fragment_count"], 2)
        self.assertEqual(live_run["total_fragment_count"], 4)
        self.assertEqual(live_run["progress_percent"], 50.0)
        self.assertEqual(live_run["total_tokens"], 42)
        log_row = logs_api.json()["logs"][0]
        self.assertEqual(log_row["fragment_count"], 2)
        self.assertEqual(log_row["total_fragment_count"], 4)
        self.assertEqual(log_row["progress_percent"], 50.0)
        self.assertEqual(log_row["total_tokens"], 42)
        detail_summary = details_api.json()["details"]["summary"]
        self.assertEqual(detail_summary["fragment_count"], 2)
        self.assertEqual(detail_summary["total_fragment_count"], 4)
        self.assertEqual(detail_summary["total_tokens"], 42)
        operation_job = operations_api.json()["overview"]["jobs"][0]
        self.assertEqual(operation_job["completed_units"], 2)
        self.assertEqual(operation_job["total_units"], 4)
        self.assertEqual(operation_job["total_tokens"], 42)
        self.assertEqual(operation_job["active_worker_ids"], ["worker-b"])

        serialized = "\n".join(
            (
                live.text,
                logs.text,
                details.text,
                operations.text,
                trace.text,
                json.dumps(live_api.json(), sort_keys=True),
                json.dumps(logs_api.json(), sort_keys=True),
                json.dumps(details_api.json(), sort_keys=True),
                json.dumps(operations_api.json(), sort_keys=True),
            )
        )
        self.assertNotIn("PRIVATE TRANSLATED ONE", serialized)
        self.assertNotIn("PRIVATE TRANSLATED TWO", serialized)

    def test_translation_logs_overlay_resumed_job_over_stale_cancelled_run(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-resumed-after-cancel",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="resumed.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    total_fragment_count=4,
                ),
            )
            logger.finish(status="cancelled", result_file_name="resumed.partial.epub")
            operations = build_operations_overview(
                jobs=[
                    {
                        "id": "job-resumed-after-cancel",
                        "status": "translating",
                        "file_name": "resumed.epub",
                        "document_kind": "epub",
                        "source_language": "en",
                        "target_language": "ru",
                        "created_at": datetime(2026, 5, 31, 9, 0, tzinfo=UTC),
                        "updated_at": datetime(2026, 5, 31, 9, 10, tzinfo=UTC),
                    }
                ],
                work_units_by_job_id={
                    "job-resumed-after-cancel": (
                        {
                            "status": "translated",
                            "prompt_tokens": 11,
                            "completion_tokens": 7,
                        },
                        {
                            "status": "translated",
                            "prompt_tokens": 13,
                            "completion_tokens": 5,
                        },
                        {"status": "translating"},
                        {"status": "pending"},
                    )
                },
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

            with patch(
                "translator_service.admin.routes._operations_overview",
                return_value=operations,
            ):
                page = client.get("/admin/logs")
                api = client.get("/admin/api/logs")
                details = client.get(f"/admin/logs/{logger.run_dir.name}")
                trace = client.get(
                    f"/admin/translations/{logger.run_dir.name}/trace"
                )

        self.assertEqual(page.status_code, 200)
        self.assertIn("job-resumed-after-cancel", page.text)
        self.assertIn("2/4", page.text)
        self.assertIn(">36</td>", page.text)
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.json()["logs"][0]["status"], "translating")
        self.assertEqual(api.json()["logs"][0]["fragment_count"], 2)
        self.assertEqual(api.json()["logs"][0]["total_fragment_count"], 4)
        self.assertEqual(api.json()["logs"][0]["progress_percent"], 50.0)
        self.assertEqual(details.status_code, 200)
        self.assertIn("2/4", details.text)
        self.assertIn("50.0%", details.text)
        self.assertEqual(trace.status_code, 200)
        self.assertIn("translating", trace.text)
        self.assertIn("2/4", trace.text)

    def test_translation_log_details_show_failed_work_unit_without_raw_text(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_db = root / "jobs.sqlite3"
            object_root = root / "objects"
            run_root = root / "runs"
            storage = LocalObjectStorage(object_root)
            source_file = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-2.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Private failing source paragraph",
            )
            store = SQLiteTranslationJobStore(job_db)
            try:
                job = store.create_job(
                    order_id="order-failed-unit",
                    user_id="telegram:42",
                    file_id="file-failed-unit",
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
                            source_block_ids=("block-1",),
                            source_text_hash="hash-1",
                            prompt_tier="plain",
                            source_language="en",
                            target_language="uk",
                        ),
                        WorkUnitPlan(
                            sequence=2,
                            source_block_ids=("block-2",),
                            source_text_hash="hash-2",
                            prompt_tier="plain",
                            source_language="en",
                            target_language="uk",
                            source_object_key=source_file.object_key,
                        ),
                    ],
                )
                first = store.claim_next_work_unit(job.id, worker_id="worker-a")
                assert first is not None
                store.complete_work_unit(
                    first.id,
                    translated_text="Translated first block",
                    prompt_tokens=11,
                    completion_tokens=7,
                    cache_hit_tokens=0,
                    cache_miss_tokens=11,
                )
                second = store.claim_next_work_unit(job.id, worker_id="worker-a")
                assert second is not None
                store.fail_work_unit(
                    second.id,
                    error_message=(
                        "provider failure on Private failing source paragraph "
                        "Bearer sk-review-secret"
                    ),
                    retry_count=3,
                )
                logger = TranslationRunLogger.start(
                    root=run_root,
                    metadata=TranslationRunMetadata(
                        job_id=job.id,
                        order_id="order-failed-unit",
                        user_id="telegram:42",
                        file_name="book.epub",
                        document_kind="epub",
                        source_language="en",
                        target_language="uk",
                        total_fragment_count=2,
                    ),
                )
                logger.record_event("job_queued", {"fragment_count": 2})
            finally:
                store.close()

            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=str(run_root),
                        persistent_jobs_db_path=str(job_db),
                        object_storage_root=str(object_root),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            details = client.get(f"/admin/logs/{logger.run_dir.name}")
            details_api = client.get(f"/admin/api/logs/{logger.run_dir.name}")

        self.assertEqual(details.status_code, 200)
        self.assertIn("Work unit needing attention", details.text)
        self.assertIn("error recorded; open text diagnostics", details.text)
        self.assertIn("sequence=2&amp;limit=1", details.text)
        self.assertNotIn("Private failing source paragraph", details.text)
        self.assertNotIn("sk-review-secret", details.text)
        self.assertEqual(details_api.status_code, 200)
        details_api_text = json.dumps(details_api.json(), ensure_ascii=False)
        self.assertNotIn("Private failing source paragraph", details_api_text)
        self.assertNotIn("sk-review-secret", details_api_text)
        diagnostic = details_api.json()["details"]["work_unit_diagnostic"]
        self.assertEqual(diagnostic["sequence"], 2)
        self.assertEqual(diagnostic["status"], "failed")
        self.assertEqual(diagnostic["source_block_ids"], ["block-2"])
        self.assertEqual(
            diagnostic["last_error"],
            "error recorded; open text diagnostics",
        )

    def test_translation_text_diagnostics_missing_store_does_not_create_db(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_db = root / "missing" / "jobs.sqlite3"
            run_root = root / "runs"
            logger = TranslationRunLogger.start(
                root=run_root,
                metadata=TranslationRunMetadata(
                    job_id="job-missing-store",
                    order_id="order-missing-store",
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    total_fragment_count=1,
                ),
            )
            logger.record_event("job_queued", {"fragment_count": 1})
            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=str(run_root),
                        persistent_jobs_db_path=str(job_db),
                        object_storage_root=str(root / "objects"),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            unauthenticated = client.get(
                f"/admin/logs/{logger.run_dir.name}/reader",
                follow_redirects=False,
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            response = client.get(f"/admin/logs/{logger.run_dir.name}/text-diagnostics")
            reader = client.get(f"/admin/logs/{logger.run_dir.name}/reader")

        self.assertEqual(unauthenticated.status_code, 303)
        self.assertEqual(unauthenticated.headers["location"], "/admin/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No work units found.", response.text)
        self.assertEqual(reader.status_code, 200)
        self.assertIn("No work units found.", reader.text)
        self.assertFalse(job_db.exists())

    def test_translation_reader_decodes_persisted_translation_batch(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_db = root / "jobs.sqlite3"
            object_root = root / "objects"
            run_root = root / "runs"
            storage = LocalObjectStorage(object_root)
            source_file = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First source paragraph.\n\nSecond source paragraph.",
            )
            store = SQLiteTranslationJobStore(job_db)
            try:
                job = store.create_job(
                    order_id="order-batch-reader",
                    user_id="telegram:42",
                    file_id="file-batch-reader",
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
                            source_block_ids=(
                                "epub:chapter.xhtml:0",
                                "epub:chapter.xhtml:1",
                            ),
                            source_text_hash="hash-1",
                            prompt_tier="plain",
                            source_language="en",
                            target_language="uk",
                            source_object_key=source_file.object_key,
                        ),
                    ],
                )
                claimed = store.claim_next_work_unit(job.id, worker_id="worker-a")
                assert claimed is not None
                translated_parts = (
                    "Перший перекладений абзац.",
                    "Другий перекладений абзац.",
                )
                store.complete_work_unit(
                    claimed.id,
                    translated_text=format_translation_batch_contract(translated_parts),
                    prompt_tokens=11,
                    completion_tokens=7,
                    cache_hit_tokens=0,
                    cache_miss_tokens=11,
                )
                logger = TranslationRunLogger.start(
                    root=run_root,
                    metadata=TranslationRunMetadata(
                        job_id=job.id,
                        order_id="order-batch-reader",
                        user_id="telegram:42",
                        file_name="book.epub",
                        document_kind="epub",
                        source_language="en",
                        target_language="uk",
                        total_fragment_count=1,
                    ),
                )
            finally:
                store.close()

            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=str(run_root),
                        persistent_jobs_db_path=str(job_db),
                        object_storage_root=str(object_root),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            reader = client.get(f"/admin/logs/{logger.run_dir.name}/reader")
            details_api = client.get(f"/admin/api/logs/{logger.run_dir.name}")

        self.assertEqual(reader.status_code, 200)
        self.assertIn("Перший перекладений абзац.", reader.text)
        self.assertIn("Другий перекладений абзац.", reader.text)
        self.assertNotIn("translation_block", reader.text)
        self.assertEqual(details_api.status_code, 200)
        fragments = details_api.json()["details"]["fragments"]
        self.assertEqual(
            fragments[0]["translated_text_chars"],
            len("\n\n".join(translated_parts)),
        )

    def test_translation_text_diagnostics_all_issues_filter(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_db = root / "jobs.sqlite3"
            object_root = root / "objects"
            run_root = root / "runs"
            storage = LocalObjectStorage(object_root)
            clean_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="clean.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Clean source.",
            )
            missing_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="missing.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Needs translation.",
            )
            indented_source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="indented.txt",
                content_type="text/plain; charset=utf-8",
                content=b"  Indented source.",
            )
            store = SQLiteTranslationJobStore(job_db)
            try:
                job = store.create_job(
                    order_id="order-issues",
                    user_id="telegram:42",
                    file_id="file-issues",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    adapter_version="txt-v1",
                    prompt_version="plain-v1",
                    pricing_snapshot_id="pricing-1",
                )
                store.add_work_units(
                    job.id,
                    [
                        WorkUnitPlan(
                            sequence=1,
                            source_block_ids=("clean",),
                            source_text_hash="hash-clean",
                            prompt_tier="plain",
                            source_language="en",
                            target_language="uk",
                            source_object_key=clean_source.object_key,
                        ),
                        WorkUnitPlan(
                            sequence=2,
                            source_block_ids=("missing",),
                            source_text_hash="hash-missing",
                            prompt_tier="plain",
                            source_language="en",
                            target_language="uk",
                            source_object_key=missing_source.object_key,
                        ),
                        WorkUnitPlan(
                            sequence=3,
                            source_block_ids=("indented",),
                            source_text_hash="hash-indented",
                            prompt_tier="plain",
                            source_language="en",
                            target_language="uk",
                            source_object_key=indented_source.object_key,
                        ),
                    ],
                )
                claimed = store.claim_next_work_unit(job.id, worker_id="worker-a")
                assert claimed is not None
                store.complete_work_unit(
                    claimed.id,
                    translated_text="Clean translation.",
                    prompt_tokens=3,
                    completion_tokens=3,
                    cache_hit_tokens=0,
                    cache_miss_tokens=3,
                )
                claimed = store.claim_next_work_unit(job.id, worker_id="worker-a")
                assert claimed is not None
                store.complete_work_unit(
                    claimed.id,
                    translated_text="",
                    prompt_tokens=3,
                    completion_tokens=0,
                    cache_hit_tokens=0,
                    cache_miss_tokens=3,
                )
                claimed = store.claim_next_work_unit(job.id, worker_id="worker-a")
                assert claimed is not None
                store.complete_work_unit(
                    claimed.id,
                    translated_text="  Indented translation.",
                    prompt_tokens=3,
                    completion_tokens=3,
                    cache_hit_tokens=0,
                    cache_miss_tokens=3,
                )
                logger = TranslationRunLogger.start(
                    root=run_root,
                    metadata=TranslationRunMetadata(
                        job_id=job.id,
                        order_id="order-issues",
                        user_id="telegram:42",
                        file_name="book.txt",
                        document_kind="txt",
                        source_language="en",
                        target_language="uk",
                        total_fragment_count=3,
                    ),
                )
                logger.record_event("job_queued", {"fragment_count": 3})
            finally:
                store.close()

            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=str(run_root),
                        persistent_jobs_db_path=str(job_db),
                        object_storage_root=str(object_root),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            diagnostics = client.get(
                f"/admin/logs/{logger.run_dir.name}/text-diagnostics?qa=issues"
            )
            reader = client.get(
                f"/admin/logs/{logger.run_dir.name}/reader"
                "?qa=issues&q=Indented&show_invisibles=1&sync=0"
                "&pane_mode=translation&indent_preview=1"
            )

        self.assertEqual(diagnostics.status_code, 200)
        self.assertIn(
            '<option value="issues" selected>All issues</option>',
            diagnostics.text,
        )
        self.assertIn("Needs translation.", diagnostics.text)
        self.assertIn("Indented source.", diagnostics.text)
        self.assertIn("Source literal indent", diagnostics.text)
        self.assertNotIn("Clean source.", diagnostics.text)
        self.assertIn("qa=issues", diagnostics.text)

        self.assertEqual(reader.status_code, 200)
        self.assertIn(
            '<option value="issues" selected>All issues</option>',
            reader.text,
        )
        self.assertIn("QA</span><strong>issues</strong>", reader.text)
        self.assertIn("Pane</span><strong>translation focus</strong>", reader.text)
        self.assertIn('name="qa" value="issues"', reader.text)
        self.assertIn("qa=issues", reader.text)
        self.assertIn("reader-qa-filter-metric is-active", reader.text)
        self.assertIn('aria-current="page"', reader.text)
        self.assertIn(
            f'href="/admin/logs/{logger.run_dir.name}/reader?sequence=1'
            "&amp;limit=100&amp;show_invisibles=1&amp;sync=0"
            "&amp;q=Indented&amp;pane_mode=translation"
            '&amp;indent_preview=1&amp;qa=issues"',
            reader.text,
        )
        self.assertIn(
            f'href="/admin/logs/{logger.run_dir.name}/reader?sequence=1'
            "&amp;limit=100&amp;show_invisibles=1&amp;sync=0"
            "&amp;q=Indented&amp;pane_mode=translation"
            '&amp;indent_preview=1&amp;qa=missing_translation"',
            reader.text,
        )
        self.assertIn(
            f'href="/admin/logs/{logger.run_dir.name}/reader?sequence=1'
            "&amp;limit=100&amp;show_invisibles=1&amp;sync=0"
            "&amp;q=Indented&amp;pane_mode=translation"
            '&amp;indent_preview=1&amp;qa=indent"',
            reader.text,
        )
        self.assertIn("Needs", reader.text)
        self.assertIn("translation.", reader.text)
        self.assertIn("Indented", reader.text)
        self.assertIn("source.", reader.text)
        self.assertIn("Missing translation", reader.text)
        self.assertIn("Source literal indent", reader.text)
        self.assertIn("Translation literal indent", reader.text)
        self.assertIn("Issues in window: 2", reader.text)
        self.assertIn('href="#reader-original-2"', reader.text)
        self.assertIn('href="#reader-original-3"', reader.text)
        self.assertIn(
            '<span class="reader-qa-issue-sequence">#3</span>',
            reader.text,
        )
        self.assertIn(
            '<span class="reader-qa-issue-labels">Source literal indent; '
            "Translation literal indent</span>",
            reader.text,
        )
        self.assertIn(
            'title="Sequence 3: translated; Source literal indent, '
            'Translation literal indent"',
            reader.text,
        )
        self.assertNotIn("Clean source.", reader.text)

    def test_translation_text_diagnostics_is_dedicated_raw_text_view(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_db = root / "jobs.sqlite3"
            object_root = root / "objects"
            run_root = root / "runs"
            storage = LocalObjectStorage(object_root)
            source_file = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=(
                    "Private source paragraph\tA\n"
                    "Next\u00a0line \u200b<script>alert(1)</script>"
                ).encode("utf-8"),
            )
            source_file_2 = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-2.txt",
                content_type="text/plain; charset=utf-8",
                content=b"  Paragraph waiting for translation.",
            )
            source_file_3 = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-3.txt",
                content_type="text/plain; charset=utf-8",
                content=b"Tiny source.",
            )
            store = SQLiteTranslationJobStore(job_db)
            try:
                job = store.create_job(
                    order_id="order-text",
                    user_id="telegram:42",
                    file_id="file-text",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    adapter_version="txt-v1",
                    prompt_version="plain-v1",
                    pricing_snapshot_id="pricing-1",
                )
                store.add_work_units(
                    job.id,
                    [
                        WorkUnitPlan(
                            sequence=1,
                            source_block_ids=("block-1",),
                            source_text_hash="hash-1",
                            prompt_tier="plain",
                            source_language="en",
                            target_language="uk",
                            source_object_key=source_file.object_key,
                        ),
                        WorkUnitPlan(
                            sequence=2,
                            source_block_ids=("block-2",),
                            source_text_hash="hash-2",
                            prompt_tier="plain",
                            source_language="en",
                            target_language="uk",
                            source_object_key=source_file_2.object_key,
                        ),
                        WorkUnitPlan(
                            sequence=3,
                            source_block_ids=("block-3",),
                            source_text_hash="hash-3",
                            prompt_tier="plain",
                            source_language="en",
                            target_language="uk",
                            source_object_key=source_file_3.object_key,
                        )
                    ],
                )
                claimed = store.claim_next_work_unit(job.id, worker_id="worker-a")
                assert claimed is not None
                store.complete_work_unit(
                    claimed.id,
                    translated_text=(
                        "  Приватний перекладений абзац\tA\n"
                        "Наступний\u00a0рядок "
                        "<img src=x onerror=alert(1)>"
                    ),
                    prompt_tokens=11,
                    completion_tokens=7,
                    cache_hit_tokens=0,
                    cache_miss_tokens=11,
                )
                claimed = store.claim_next_work_unit(job.id, worker_id="worker-a")
                assert claimed is not None
                store.complete_work_unit(
                    claimed.id,
                    translated_text="",
                    prompt_tokens=5,
                    completion_tokens=0,
                    cache_hit_tokens=0,
                    cache_miss_tokens=5,
                )
                claimed = store.claim_next_work_unit(job.id, worker_id="worker-a")
                assert claimed is not None
                store.complete_work_unit(
                    claimed.id,
                    translated_text=(
                        " ".join(["very long translated expansion"] * 5)
                        + "\n"
                        + " ".join(["very long translated expansion"] * 5)
                    ),
                    prompt_tokens=6,
                    completion_tokens=80,
                    cache_hit_tokens=0,
                    cache_miss_tokens=6,
                )
                logger = TranslationRunLogger.start(
                    root=run_root,
                    metadata=TranslationRunMetadata(
                        job_id=job.id,
                        order_id="order-text",
                        user_id="telegram:42",
                        file_name="book.txt",
                        document_kind="txt",
                        source_language="en",
                        target_language="uk",
                        total_fragment_count=1,
                    ),
                )
                logger.record_event("job_queued", {"fragment_count": 1})
            finally:
                store.close()

            client = TestClient(
                create_app(
                    settings=Settings(
                        translation_run_log_root=str(run_root),
                        persistent_jobs_db_path=str(job_db),
                        object_storage_root=str(object_root),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            logs = client.get("/admin/logs")
            details = client.get(f"/admin/logs/{logger.run_dir.name}")
            details_api = client.get(f"/admin/api/logs/{logger.run_dir.name}")
            diagnostics = client.get(
                f"/admin/logs/{logger.run_dir.name}/text-diagnostics"
            )
            reader = client.get(f"/admin/logs/{logger.run_dir.name}/reader")
            diagnostics_invisibles = client.get(
                f"/admin/logs/{logger.run_dir.name}/text-diagnostics"
                "?show_invisibles=1"
            )
            reader_unsynced = client.get(
                f"/admin/logs/{logger.run_dir.name}/reader"
                "?show_invisibles=1&sync=0"
            )
            diagnostics_search = client.get(
                f"/admin/logs/{logger.run_dir.name}/text-diagnostics"
                "?q=%3Cscript%3E"
            )
            reader_search = client.get(
                f"/admin/logs/{logger.run_dir.name}/reader"
                "?q=%3Cscript%3E&show_invisibles=1&sync=0"
            )
            reader_search_hits = client.get(
                f"/admin/logs/{logger.run_dir.name}/reader"
                "?q=%3Cscript%3E&show_invisibles=1&sync=0&search_hits=1"
            )
            diagnostics_search_hits_param = client.get(
                f"/admin/logs/{logger.run_dir.name}/text-diagnostics"
                "?q=%3Cscript%3E&search_hits=1"
            )
            reader_pane_focus = client.get(
                f"/admin/logs/{logger.run_dir.name}/reader"
                "?pane_mode=original&q=Tiny&show_invisibles=1&sync=0"
                "&search_hits=1&indent_preview=1"
            )
            reader_translation_focus = client.get(
                f"/admin/logs/{logger.run_dir.name}/reader"
                "?pane_mode=translation"
            )
            reader_invalid_pane = client.get(
                f"/admin/logs/{logger.run_dir.name}/reader?pane_mode=unknown"
            )
            diagnostics_pane_param = client.get(
                f"/admin/logs/{logger.run_dir.name}/text-diagnostics"
                "?pane_mode=translation&q=Tiny"
            )
            diagnostics_indent = client.get(
                f"/admin/logs/{logger.run_dir.name}/text-diagnostics"
                "?indent_preview=1"
            )
            reader_indent = client.get(
                f"/admin/logs/{logger.run_dir.name}/reader"
                "?indent_preview=1&q=%3Cscript%3E&show_invisibles=1&sync=0"
            )
            diagnostics_page = client.get(
                f"/admin/logs/{logger.run_dir.name}/text-diagnostics"
                "?page=2&limit=1&q=Paragraph&indent_preview=1"
            )
            reader_page = client.get(
                f"/admin/logs/{logger.run_dir.name}/reader"
                "?page=3&limit=1&q=Tiny&show_invisibles=1&sync=0"
                "&indent_preview=1"
            )
            diagnostics_missing = client.get(
                f"/admin/logs/{logger.run_dir.name}/text-diagnostics"
                "?qa=missing_translation&q=Paragraph&show_invisibles=1"
                "&indent_preview=1"
            )
            diagnostics_indent_filter = client.get(
                f"/admin/logs/{logger.run_dir.name}/text-diagnostics?qa=indent"
            )
            reader_length_filter = client.get(
                f"/admin/logs/{logger.run_dir.name}/reader"
                "?qa=length_mismatch&q=Tiny&show_invisibles=1&sync=0"
                "&indent_preview=1"
            )
            reader_paragraph_filter = client.get(
                f"/admin/logs/{logger.run_dir.name}/reader"
                "?qa=paragraph_mismatch&q=Tiny&show_invisibles=1&sync=0"
                "&indent_preview=1"
            )
            diagnostics_paragraph_filter = client.get(
                f"/admin/logs/{logger.run_dir.name}/text-diagnostics"
                "?qa=paragraph_mismatch&q=Tiny&show_invisibles=1"
            )
            reader_empty_filter = client.get(
                f"/admin/logs/{logger.run_dir.name}/reader?qa=empty_source"
            )
            reader_invalid_filter = client.get(
                f"/admin/logs/{logger.run_dir.name}/reader?qa=unknown"
            )
            download = client.get(f"/admin/logs/{logger.run_dir.name}/download")
            save_mark = client.post(
                f"/admin/logs/{logger.run_dir.name}/reader/review-mark",
                data={
                    "csrf_token": _csrf_token(reader.text),
                    "sequence": "1",
                    "mark": "needs_review",
                },
            )
            review_marks_path = Path(logger.run_dir) / "reader_review_marks.json"
            review_marks_document = json.loads(
                review_marks_path.read_text(encoding="utf-8")
            )
            reader_with_saved_mark = client.get(
                f"/admin/logs/{logger.run_dir.name}/reader"
            )
            details_after_mark = client.get(f"/admin/logs/{logger.run_dir.name}")
            details_api_after_mark = client.get(
                f"/admin/api/logs/{logger.run_dir.name}"
            )
            download_after_mark = client.get(
                f"/admin/logs/{logger.run_dir.name}/download"
            )
            clear_mark = client.post(
                f"/admin/logs/{logger.run_dir.name}/reader/review-mark",
                data={
                    "csrf_token": _csrf_token(reader_with_saved_mark.text),
                    "sequence": "1",
                    "mark": "clear",
                },
            )
            review_marks_after_clear = json.loads(
                review_marks_path.read_text(encoding="utf-8")
            )

        self.assertEqual(logs.status_code, 200)
        self.assertIn("Reader", logs.text)
        self.assertIn(f"/admin/logs/{logger.run_dir.name}/reader", logs.text)
        self.assertEqual(details.status_code, 200)
        self.assertIn("Text diagnostics", details.text)
        self.assertIn("Reader", details.text)
        self.assertIn(f"/admin/logs/{logger.run_dir.name}/reader", details.text)
        self.assertIn("block-1", details.text)
        self.assertIn("translated", details.text)
        self.assertIn("11 + 7 = 18", details.text)
        self.assertNotIn("No run-log fragment records found", details.text)
        self.assertNotIn("Private source paragraph", details.text)
        self.assertNotIn("Приватний перекладений абзац", details.text)
        self.assertEqual(details_api.status_code, 200)
        details_payload = details_api.json()["details"]
        self.assertEqual(len(details_payload["fragments"]), 3)
        self.assertEqual(details_payload["fragments"][0]["sequence"], 1)
        self.assertEqual(details_payload["fragments"][0]["status"], "translated")
        self.assertEqual(
            details_payload["fragments"][0]["source_block_ids"],
            ["block-1"],
        )
        self.assertEqual(details_payload["fragments"][0]["prompt_tokens"], 11)
        self.assertEqual(details_payload["fragments"][0]["completion_tokens"], 7)
        details_api_text = json.dumps(details_payload, ensure_ascii=False)
        self.assertNotIn("Private source paragraph", details_api_text)
        self.assertNotIn("Приватний перекладений абзац", details_api_text)
        self.assertEqual(diagnostics.status_code, 200)
        self.assertEqual(diagnostics.headers["cache-control"], "no-store")
        self.assertIn("Raw text visibility is enabled", diagnostics.text)
        self.assertIn("Private source paragraph", diagnostics.text)
        self.assertIn("Приватний перекладений абзац", diagnostics.text)
        self.assertIn("Diagnostics", diagnostics.text)
        self.assertIn("Reader", diagnostics.text)
        self.assertIn("Show special chars", diagnostics.text)
        self.assertIn('name="sequence"', diagnostics.text)
        self.assertIn('name="page"', diagnostics.text)
        self.assertIn('name="limit"', diagnostics.text)
        self.assertIn('name="qa"', diagnostics.text)
        self.assertIn('<option value="all" selected>All</option>', diagnostics.text)
        self.assertIn("Logical page 1", diagnostics.text)
        self.assertIn("sequences 1-3", diagnostics.text)
        self.assertIn("← Previous", diagnostics.text)
        self.assertIn("Next →", diagnostics.text)
        self.assertIn("Missing translation", diagnostics.text)
        self.assertIn("Translation much longer", diagnostics.text)
        self.assertIn("Source literal indent", diagnostics.text)
        self.assertIn("Translation literal indent", diagnostics.text)
        self.assertIn("Source chars", diagnostics.text)
        self.assertIn("Translation chars", diagnostics.text)
        self.assertIn("T/S ratio", diagnostics.text)
        self.assertIn("Source lines", diagnostics.text)
        self.assertIn("Translation lines", diagnostics.text)
        self.assertIn("Source blank lines", diagnostics.text)
        self.assertIn("Translation blank lines", diagnostics.text)
        self.assertIn("Paragraph/line break mismatch", diagnostics.text)
        self.assertNotIn('<section class="reader-position-bar"', diagnostics.text)
        self.assertNotIn("data-reader-keyboard-navigation", diagnostics.text)
        self.assertNotIn("data-reader-qa-step-navigation", diagnostics.text)
        self.assertNotIn("data-reader-qa-step-controls", diagnostics.text)
        self.assertNotIn("data-reader-review-controls", diagnostics.text)
        self.assertNotIn("data-reader-review-navigation", diagnostics.text)
        self.assertNotIn("data-reader-review-mark", diagnostics.text)
        self.assertNotIn("data-reader-review-panel", diagnostics.text)
        self.assertNotIn("data-reader-review-filter", diagnostics.text)
        self.assertNotIn("data-reader-review-step-controls", diagnostics.text)
        self.assertNotIn("data-reader-review-step", diagnostics.text)
        self.assertNotIn("data-reader-review-shortcuts", diagnostics.text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", diagnostics.text)
        self.assertIn(
            "&lt;img src=x onerror=alert(1)&gt;",
            diagnostics.text,
        )
        self.assertNotIn("<script>alert(1)</script>", diagnostics.text)
        self.assertNotIn("<img src=x onerror=alert(1)>", diagnostics.text)
        self.assertEqual(diagnostics_invisibles.status_code, 200)
        self.assertIn("Hide special chars", diagnostics_invisibles.text)
        self.assertIn("&middot;", diagnostics_invisibles.text)
        self.assertIn("&rarr;", diagnostics_invisibles.text)
        self.assertIn("&para;", diagnostics_invisibles.text)
        self.assertIn("&#9251;", diagnostics_invisibles.text)
        self.assertIn("ZWSP", diagnostics_invisibles.text)
        self.assertIn(
            "&lt;script&gt;alert(1)&lt;/script&gt;",
            diagnostics_invisibles.text,
        )
        self.assertNotIn("<script>alert(1)</script>", diagnostics_invisibles.text)
        self.assertEqual(diagnostics_search.status_code, 200)
        self.assertIn("Clear search", diagnostics_search.text)
        self.assertIn(
            '<mark class="reader-search-hit">&lt;script&gt;</mark>',
            diagnostics_search.text,
        )
        self.assertIn("q=%3Cscript%3E", diagnostics_search.text)
        self.assertNotIn("data-reader-search-hit-controls", diagnostics_search.text)
        self.assertNotIn("data-reader-search-hit-navigation", diagnostics_search.text)
        self.assertNotIn("<script>alert(1)</script>", diagnostics_search.text)
        self.assertEqual(diagnostics_indent.status_code, 200)
        self.assertIn("indent_preview=1", diagnostics_indent.text)
        self.assertIn("Source literal indent", diagnostics_indent.text)
        self.assertEqual(diagnostics_page.status_code, 200)
        self.assertIn("Logical page 2", diagnostics_page.text)
        self.assertIn("sequences 2-2", diagnostics_page.text)
        self.assertIn('value="2"', diagnostics_page.text)
        self.assertIn('<option value="1" selected>1</option>', diagnostics_page.text)
        self.assertIn("reader-search-hit", diagnostics_page.text)
        self.assertIn("waiting for translation", diagnostics_page.text)
        self.assertIn("q=Paragraph", diagnostics_page.text)
        self.assertIn("indent_preview=1", diagnostics_page.text)
        self.assertNotIn("Private source paragraph", diagnostics_page.text)
        self.assertEqual(diagnostics_missing.status_code, 200)
        self.assertIn(
            '<option value="missing_translation" selected>Missing translation</option>',
            diagnostics_missing.text,
        )
        self.assertIn("qa=missing_translation", diagnostics_missing.text)
        self.assertIn("show_invisibles=1", diagnostics_missing.text)
        self.assertIn("q=Paragraph", diagnostics_missing.text)
        self.assertIn("indent_preview=1", diagnostics_missing.text)
        self.assertIn("reader-search-hit", diagnostics_missing.text)
        self.assertIn("waiting", diagnostics_missing.text)
        self.assertIn("translation.", diagnostics_missing.text)
        self.assertIn("Source chars", diagnostics_missing.text)
        self.assertIn("Translation chars 0", diagnostics_missing.text)
        self.assertIn("T/S ratio 0.00", diagnostics_missing.text)
        self.assertIn("Translation lines 0", diagnostics_missing.text)
        self.assertNotIn("Private source paragraph", diagnostics_missing.text)
        self.assertNotIn("Tiny source", diagnostics_missing.text)
        self.assertEqual(diagnostics_indent_filter.status_code, 200)
        self.assertIn(
            '<option value="indent" selected>Literal indent</option>',
            diagnostics_indent_filter.text,
        )
        self.assertIn("qa=indent", diagnostics_indent_filter.text)
        self.assertIn("Private source paragraph", diagnostics_indent_filter.text)
        self.assertIn(
            "Paragraph waiting for translation",
            diagnostics_indent_filter.text,
        )
        self.assertNotIn("Tiny source", diagnostics_indent_filter.text)
        self.assertEqual(reader.status_code, 200)
        self.assertEqual(reader.headers["cache-control"], "no-store")
        self.assertIn("Translation Reader", reader.text)
        self.assertIn("data-reader-sync-pane", reader.text)
        self.assertIn("programmaticScrollLocks", reader.text)
        self.assertIn("lockProgrammaticScroll", reader.text)
        self.assertIn("isLockedProgrammaticScroll", reader.text)
        self.assertIn("Math.abs(other.scrollTop - nextScrollTop) <= 1", reader.text)
        self.assertNotIn("pendingProgrammaticScrolls", reader.text)
        self.assertIn("data-reader-keyboard-navigation", reader.text)
        self.assertIn('event.key === "ArrowLeft"', reader.text)
        self.assertIn('event.key === "ArrowRight"', reader.text)
        self.assertIn(
            "input, textarea, select, button, a, [contenteditable='true']",
            reader.text,
        )
        self.assertIn(
            f'const previousHref = "/admin/logs/{logger.run_dir.name}/reader'
            '?sequence=1&limit=100";',
            reader.text,
        )
        self.assertIn(
            f'const nextHref = "/admin/logs/{logger.run_dir.name}/reader'
            '?sequence=101&limit=100";',
            reader.text,
        )
        self.assertIn("Show special chars", reader.text)
        self.assertIn("Unsync scroll", reader.text)
        self.assertIn('name="sequence"', reader.text)
        self.assertIn('name="page"', reader.text)
        self.assertIn('name="limit"', reader.text)
        self.assertIn('name="qa"', reader.text)
        self.assertIn("Logical page 1", reader.text)
        self.assertIn("sequences 1-3", reader.text)
        self.assertIn("sequence=101&amp;limit=100", reader.text)
        self.assertIn("reader-position-bar", reader.text)
        self.assertIn("Reader current position", reader.text)
        self.assertIn("QA</span><strong>all</strong>", reader.text)
        self.assertIn("Search</span><strong>Search off</strong>", reader.text)
        self.assertIn("Pane</span><strong>split</strong>", reader.text)
        self.assertIn("Special chars</span><strong>hidden</strong>", reader.text)
        self.assertIn("Sync scroll</span><strong>on</strong>", reader.text)
        self.assertIn("Indent preview</span><strong>off</strong>", reader.text)
        self.assertIn("reader-pane-mode-split", reader.text)
        self.assertIn("Split panes", reader.text)
        self.assertIn("Focus original", reader.text)
        self.assertIn("Focus translation", reader.text)
        self.assertNotIn("pane_mode=split", reader.text)
        self.assertIn("Reader QA summary", reader.text)
        self.assertIn("Reader layout diagnostics", reader.text)
        self.assertIn("Window units", reader.text)
        self.assertIn("All issues", reader.text)
        self.assertIn("Missing translation", reader.text)
        self.assertIn("Length mismatch", reader.text)
        self.assertIn("Paragraph mismatch", reader.text)
        self.assertIn("reader-qa-filter-metric", reader.text)
        self.assertIn(
            f'href="/admin/logs/{logger.run_dir.name}/reader?sequence=1'
            '&amp;limit=100&amp;qa=issues"',
            reader.text,
        )
        self.assertIn(
            f'href="/admin/logs/{logger.run_dir.name}/reader?sequence=1'
            '&amp;limit=100&amp;qa=missing_translation"',
            reader.text,
        )
        self.assertIn(
            f'href="/admin/logs/{logger.run_dir.name}/reader?sequence=1'
            '&amp;limit=100&amp;qa=empty_source"',
            reader.text,
        )
        self.assertIn(
            f'href="/admin/logs/{logger.run_dir.name}/reader?sequence=1'
            '&amp;limit=100&amp;qa=length_mismatch"',
            reader.text,
        )
        self.assertIn(
            f'href="/admin/logs/{logger.run_dir.name}/reader?sequence=1'
            '&amp;limit=100&amp;qa=paragraph_mismatch"',
            reader.text,
        )
        self.assertIn("reader-qa-issue-nav", reader.text)
        self.assertIn("QA issues", reader.text)
        self.assertIn("data-reader-qa-step-controls", reader.text)
        self.assertIn("data-reader-qa-step-navigation", reader.text)
        self.assertIn("data-reader-qa-progress", reader.text)
        self.assertIn("Issues in window: 3", reader.text)
        self.assertIn("Issue ${index + 1} of ${issueHrefs.length}", reader.text)
        self.assertIn('data-reader-qa-step="previous"', reader.text)
        self.assertIn('data-reader-qa-step="next"', reader.text)
        self.assertIn("Previous issue", reader.text)
        self.assertIn("Next issue", reader.text)
        self.assertIn("data-reader-qa-issue-anchor", reader.text)
        self.assertIn('tabindex="-1"', reader.text)
        self.assertIn("setActiveIssue", reader.text)
        self.assertIn("is-active-qa-issue", reader.text)
        self.assertIn('aria-current", "true"', reader.text)
        self.assertIn("hashchange", reader.text)
        self.assertIn(".reader-block:target", reader.text)
        self.assertIn("scrollIntoView", reader.text)
        self.assertIn("window.history.replaceState", reader.text)
        self.assertNotIn("data-reader-search-hit-controls", reader.text)
        self.assertNotIn("data-reader-search-hit-navigation", reader.text)
        self.assertIn('href="#reader-original-1"', reader.text)
        self.assertIn('href="#reader-original-2"', reader.text)
        self.assertIn('href="#reader-original-3"', reader.text)
        self.assertIn(
            '<span class="reader-qa-issue-sequence">#1</span>',
            reader.text,
        )
        self.assertIn('<span class="reader-qa-issue-sequence">#2</span>', reader.text)
        self.assertIn('<span class="reader-qa-issue-sequence">#3</span>', reader.text)
        self.assertIn("Blocks block-3", reader.text)
        self.assertIn("Indent preview", reader.text)
        self.assertIn("Preview indents", reader.text)
        self.assertIn("Source literal indents", reader.text)
        self.assertIn("Translation literal indents", reader.text)
        self.assertIn("Style metadata", reader.text)
        self.assertIn("Unknown", reader.text)
        self.assertIn(
            f'href="/admin/logs/{logger.run_dir.name}/reader?sequence=1'
            '&amp;limit=100&amp;qa=indent"',
            reader.text,
        )
        self.assertIn("reader-outline", reader.text)
        self.assertIn('<details class="reader-outline"', reader.text)
        self.assertIn("Reader block outline", reader.text)
        self.assertIn("Block outline", reader.text)
        self.assertIn("Visible units: 3", reader.text)
        self.assertLess(
            reader.text.index("data-translation-reader"),
            reader.text.index('<details class="reader-outline"'),
        )
        self.assertIn("reader-outline-link", reader.text)
        self.assertIn("reader-outline-link has-qa-warning", reader.text)
        self.assertIn("data-reader-outline-anchor", reader.text)
        self.assertIn("data-reader-outline-navigation", reader.text)
        self.assertIn("is-active-outline-block", reader.text)
        self.assertIn("setActiveOutline", reader.text)
        self.assertIn('link.setAttribute("aria-current", "page")', reader.text)
        self.assertIn("reader:block-selected", reader.text)
        self.assertIn('new CustomEvent("reader:block-selected"', reader.text)
        self.assertIn("reader-outline-sequence", reader.text)
        self.assertIn("reader-outline-blocks", reader.text)
        self.assertIn("reader-outline-status", reader.text)
        self.assertIn("reader-outline-flags", reader.text)
        self.assertIn("data-reader-outline-sequence", reader.text)
        self.assertIn("Blocks block-1", reader.text)
        self.assertIn("Status translated", reader.text)
        self.assertIn("data-reader-review-controls", reader.text)
        self.assertIn("data-reader-review-state", reader.text)
        self.assertIn("Review mark: none", reader.text)
        self.assertIn("data-reader-review-navigation", reader.text)
        self.assertIn("data-reader-review-panel", reader.text)
        self.assertIn("data-reader-review-save-url", reader.text)
        self.assertIn("data-reader-review-csrf", reader.text)
        self.assertIn("data-reader-review-save-status", reader.text)
        self.assertIn(
            "Review marks save with marked original and translation text.",
            reader.text,
        )
        self.assertIn("Reader review marks", reader.text)
        self.assertIn("Review marks", reader.text)
        self.assertIn("data-reader-review-shortcuts", reader.text)
        self.assertIn(
            "Review shortcuts: 1 Needs review, 2 OK, 3 Ignore, 0 Clear.",
            reader.text,
        )
        self.assertIn("Review filter: all rows", reader.text)
        self.assertIn("data-reader-review-filter-status", reader.text)
        self.assertIn("data-reader-review-count", reader.text)
        self.assertIn('data-reader-review-count="marked"', reader.text)
        self.assertIn('data-reader-review-count="unmarked"', reader.text)
        self.assertIn('data-reader-review-count="needs_review"', reader.text)
        self.assertIn('data-reader-review-count="ok"', reader.text)
        self.assertIn('data-reader-review-count="ignore"', reader.text)
        self.assertIn('data-reader-review-filter="all"', reader.text)
        self.assertIn('data-reader-review-filter="unmarked"', reader.text)
        self.assertIn('data-reader-review-filter="needs_review"', reader.text)
        self.assertIn('data-reader-review-filter="ok"', reader.text)
        self.assertIn('data-reader-review-filter="ignore"', reader.text)
        self.assertIn("Unmarked", reader.text)
        self.assertIn("data-reader-review-step-controls", reader.text)
        self.assertIn("data-reader-review-step-progress", reader.text)
        self.assertIn("Marked blocks: 0", reader.text)
        self.assertIn('data-reader-review-step="previous"', reader.text)
        self.assertIn('data-reader-review-step="next"', reader.text)
        self.assertIn("Previous mark", reader.text)
        self.assertIn("Next mark", reader.text)
        self.assertIn('data-reader-review-mark="needs_review"', reader.text)
        self.assertIn('data-reader-review-mark="ok"', reader.text)
        self.assertIn('data-reader-review-mark="ignore"', reader.text)
        self.assertIn('data-reader-review-mark="clear"', reader.text)
        self.assertIn("Needs review", reader.text)
        self.assertIn("setReviewMark", reader.text)
        self.assertIn("updateReviewCounts", reader.text)
        self.assertIn("applyReviewFilter", reader.text)
        self.assertIn("savedReviewMarks", reader.text)
        self.assertIn("persistReviewMark", reader.text)
        self.assertIn("applyReviewMark", reader.text)
        self.assertIn("URLSearchParams", reader.text)
        self.assertIn("fetch(reviewSaveUrl", reader.text)
        self.assertIn('body.set("sequence", sequence)', reader.text)
        self.assertIn('body.set("mark", requestedMark)', reader.text)
        self.assertIn(
            "Review mark saved with original and translation text.",
            reader.text,
        )
        self.assertIn("Review mark save failed.", reader.text)
        self.assertIn("reviewShortcutMarks", reader.text)
        self.assertIn('"1": "needs_review"', reader.text)
        self.assertIn('"2": "ok"', reader.text)
        self.assertIn('"3": "ignore"', reader.text)
        self.assertIn('"0": "clear"', reader.text)
        self.assertIn("activeReviewSequence", reader.text)
        self.assertIn("visibleReviewSequence", reader.text)
        self.assertIn("selectedReviewSequence", reader.text)
        self.assertIn("isInteractiveTarget(event.target)", reader.text)
        self.assertIn('unmarked: "unmarked"', reader.text)
        self.assertIn("counts.marked += 1", reader.text)
        self.assertIn("counts.unmarked += 1", reader.text)
        self.assertIn('currentReviewFilter === "unmarked"', reader.text)
        self.assertIn("reviewSequences", reader.text)
        self.assertIn("currentMarkForSequence", reader.text)
        self.assertIn("markedSequencesForCurrentFilter", reader.text)
        self.assertIn("updateReviewStepProgress", reader.text)
        self.assertIn("goToReviewMark", reader.text)
        self.assertIn("currentReviewStepSequence", reader.text)
        self.assertIn(
            "Marked block ${index + 1} of ${markedSequences.length}",
            reader.text,
        )
        self.assertIn("matchingBlocks", reader.text)
        self.assertIn("matchingOutlines", reader.text)
        self.assertIn("data-reader-review-current", reader.text)
        self.assertIn("is-review-filter-hidden", reader.text)
        self.assertIn("currentReviewFilter", reader.text)
        self.assertIn("aria-pressed", reader.text)
        self.assertIn("is-review-needs-review", reader.text)
        self.assertIn("is-review-ok", reader.text)
        self.assertIn("is-review-ignore", reader.text)
        self.assertNotIn("localStorage", reader.text)
        self.assertNotIn("sessionStorage", reader.text)
        self.assertIn("reader-minimap", reader.text)
        self.assertIn(
            'title="Sequence 1: translated; Translation literal indent"',
            reader.text,
        )
        self.assertIn(
            'title="Sequence 2: translated; Missing translation, '
            'Source literal indent"',
            reader.text,
        )
        self.assertIn("reader-qa-flag-missing_translation", reader.text)
        self.assertIn("reader-qa-flag-length_mismatch", reader.text)
        self.assertIn("reader-qa-flag-paragraph_mismatch", reader.text)
        self.assertIn("reader-qa-flag-literal_source_indent", reader.text)
        self.assertIn("reader-qa-flag-literal_translation_indent", reader.text)
        self.assertIn("reader-block-metrics", reader.text)
        self.assertIn("Source chars", reader.text)
        self.assertIn("Translation chars", reader.text)
        self.assertIn("T/S ratio", reader.text)
        self.assertIn("Source lines", reader.text)
        self.assertIn("Translation lines", reader.text)
        self.assertIn("Original", reader.text)
        self.assertIn("Translation", reader.text)
        self.assertIn("Private source paragraph", reader.text)
        self.assertIn("Приватний перекладений абзац", reader.text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", reader.text)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", reader.text)
        self.assertNotIn("<script>alert(1)</script>", reader.text)
        self.assertNotIn("<img src=x onerror=alert(1)>", reader.text)
        self.assertIn("Text diagnostics", reader.text)
        self.assertEqual(reader_unsynced.status_code, 200)
        self.assertIn("Hide special chars", reader_unsynced.text)
        self.assertIn("Sync scroll", reader_unsynced.text)
        self.assertIn("data-reader-pane", reader_unsynced.text)
        self.assertNotIn("data-reader-sync-pane", reader_unsynced.text)
        self.assertNotIn("programmaticScrollLocks", reader_unsynced.text)
        self.assertNotIn("pendingProgrammaticScrolls", reader_unsynced.text)
        self.assertIn("&middot;", reader_unsynced.text)
        self.assertIn("&rarr;", reader_unsynced.text)
        self.assertIn("&para;", reader_unsynced.text)
        self.assertIn("&#9251;", reader_unsynced.text)
        self.assertIn("ZWSP", reader_unsynced.text)
        self.assertIn("show_invisibles=1", reader_unsynced.text)
        self.assertIn("sync=0", reader_unsynced.text)
        self.assertEqual(reader_search.status_code, 200)
        self.assertIn("Clear search", reader_search.text)
        self.assertIn("Show search hits only", reader_search.text)
        self.assertIn("Search hits", reader_search.text)
        self.assertIn("data-reader-search-hit-controls", reader_search.text)
        self.assertIn("data-reader-search-hit-navigation", reader_search.text)
        self.assertIn("data-reader-search-hit-progress", reader_search.text)
        self.assertIn("Search hits in window: 1", reader_search.text)
        self.assertIn("Search rows</span><strong>all rows</strong>", reader_search.text)
        self.assertIn('data-reader-search-hit-step="previous"', reader_search.text)
        self.assertIn('data-reader-search-hit-step="next"', reader_search.text)
        self.assertIn("Previous hit", reader_search.text)
        self.assertIn("Next hit", reader_search.text)
        self.assertIn("is-active-search-hit", reader_search.text)
        self.assertIn("Hit ${index + 1} of ${hits.length}", reader_search.text)
        self.assertIn(
            '<mark class="reader-search-hit">&lt;script&gt;</mark>',
            reader_search.text,
        )
        self.assertIn("q=%3Cscript%3E", reader_search.text)
        self.assertIn("search_hits=1", reader_search.text)
        self.assertNotIn("<script>alert(1)</script>", reader_search.text)
        self.assertEqual(reader_search_hits.status_code, 200)
        self.assertIn("Show all search context", reader_search_hits.text)
        self.assertIn(
            "Search rows</span><strong>matches only</strong>",
            reader_search_hits.text,
        )
        self.assertIn("search_hits=1", reader_search_hits.text)
        self.assertIn("reader-original-1", reader_search_hits.text)
        self.assertIn("Private", reader_search_hits.text)
        self.assertIn("source", reader_search_hits.text)
        self.assertIn(
            '<mark class="reader-search-hit">&lt;script&gt;</mark>',
            reader_search_hits.text,
        )
        self.assertIn("Search hits in window: 1", reader_search_hits.text)
        self.assertIn("Window units", reader_search_hits.text)
        self.assertIn("<strong>1</strong>", reader_search_hits.text)
        self.assertNotIn("Paragraph waiting for translation", reader_search_hits.text)
        self.assertNotIn("Tiny source", reader_search_hits.text)
        self.assertNotIn("<script>alert(1)</script>", reader_search_hits.text)
        self.assertEqual(diagnostics_search_hits_param.status_code, 200)
        self.assertIn(
            "Translation Text Diagnostics",
            diagnostics_search_hits_param.text,
        )
        self.assertNotIn("Show all search context", diagnostics_search_hits_param.text)
        self.assertNotIn("Show search hits only", diagnostics_search_hits_param.text)
        self.assertNotIn("search_hits=1", diagnostics_search_hits_param.text)
        self.assertIn(
            "Paragraph waiting for translation",
            diagnostics_search_hits_param.text,
        )
        self.assertIn("Tiny source", diagnostics_search_hits_param.text)
        self.assertEqual(reader_pane_focus.status_code, 200)
        self.assertIn("reader-pane-mode-original", reader_pane_focus.text)
        self.assertIn("reader-pane-mode-action is-active", reader_pane_focus.text)
        self.assertIn(
            "Pane</span><strong>original focus</strong>",
            reader_pane_focus.text,
        )
        self.assertIn("pane_mode=original", reader_pane_focus.text)
        self.assertIn('name="pane_mode" value="original"', reader_pane_focus.text)
        self.assertIn("search_hits=1", reader_pane_focus.text)
        self.assertIn("indent_preview=1", reader_pane_focus.text)
        self.assertIn("sync=0", reader_pane_focus.text)
        self.assertIn("show_invisibles=1", reader_pane_focus.text)
        self.assertIn("q=Tiny", reader_pane_focus.text)
        self.assertIn("Tiny", reader_pane_focus.text)
        self.assertNotIn("Private source paragraph", reader_pane_focus.text)
        self.assertNotIn("Paragraph waiting for translation", reader_pane_focus.text)
        self.assertIn(
            f'const previousHref = "/admin/logs/{logger.run_dir.name}/reader'
            '?sequence=1&limit=100&show_invisibles=1&sync=0&q=Tiny'
            '&search_hits=1&pane_mode=original&indent_preview=1";',
            reader_pane_focus.text,
        )
        self.assertEqual(reader_translation_focus.status_code, 200)
        self.assertIn("reader-pane-mode-translation", reader_translation_focus.text)
        self.assertIn(
            "Pane</span><strong>translation focus</strong>",
            reader_translation_focus.text,
        )
        self.assertIn("pane_mode=translation", reader_translation_focus.text)
        self.assertEqual(reader_invalid_pane.status_code, 200)
        self.assertIn("reader-pane-mode-split", reader_invalid_pane.text)
        self.assertIn("Pane</span><strong>split</strong>", reader_invalid_pane.text)
        self.assertNotIn("pane_mode=unknown", reader_invalid_pane.text)
        self.assertEqual(diagnostics_pane_param.status_code, 200)
        self.assertIn("Translation Text Diagnostics", diagnostics_pane_param.text)
        self.assertNotIn("Focus original", diagnostics_pane_param.text)
        self.assertNotIn("Focus translation", diagnostics_pane_param.text)
        self.assertNotIn("pane_mode=translation", diagnostics_pane_param.text)
        self.assertIn(
            '<mark class="reader-search-hit">Tiny</mark> source.',
            diagnostics_pane_param.text,
        )
        self.assertEqual(reader_indent.status_code, 200)
        self.assertIn("Plain indent", reader_indent.text)
        self.assertIn("has-indent-preview", reader_indent.text)
        self.assertIn("indent_preview=1", reader_indent.text)
        self.assertIn("q=%3Cscript%3E", reader_indent.text)
        self.assertIn("show_invisibles=1", reader_indent.text)
        self.assertIn("sync=0", reader_indent.text)
        self.assertEqual(reader_page.status_code, 200)
        self.assertIn("Logical page 3", reader_page.text)
        self.assertIn("sequences 3-3", reader_page.text)
        self.assertIn('<option value="1" selected>1</option>', reader_page.text)
        self.assertIn("Tiny", reader_page.text)
        self.assertIn("q=Tiny", reader_page.text)
        self.assertIn("show_invisibles=1", reader_page.text)
        self.assertIn("sync=0", reader_page.text)
        self.assertIn("indent_preview=1", reader_page.text)
        self.assertIn("reader-position-bar", reader_page.text)
        self.assertIn("Logical page 3", reader_page.text)
        self.assertIn("sequences 3-3", reader_page.text)
        self.assertIn("QA</span><strong>all</strong>", reader_page.text)
        self.assertIn(
            "Search</span><strong>Search &quot;Tiny&quot;</strong>",
            reader_page.text,
        )
        self.assertIn("Special chars</span><strong>shown</strong>", reader_page.text)
        self.assertIn("Sync scroll</span><strong>off</strong>", reader_page.text)
        self.assertIn("Indent preview</span><strong>on</strong>", reader_page.text)
        self.assertIn("data-reader-keyboard-navigation", reader_page.text)
        self.assertIn(
            f'const previousHref = "/admin/logs/{logger.run_dir.name}/reader'
            '?sequence=2&limit=1&show_invisibles=1&sync=0&q=Tiny'
            '&indent_preview=1";',
            reader_page.text,
        )
        self.assertIn(
            f'const nextHref = "/admin/logs/{logger.run_dir.name}/reader'
            '?sequence=4&limit=1&show_invisibles=1&sync=0&q=Tiny'
            '&indent_preview=1";',
            reader_page.text,
        )
        self.assertNotIn("Private source paragraph", reader_page.text)
        self.assertEqual(reader_length_filter.status_code, 200)
        self.assertIn(
            '<option value="length_mismatch" selected>Length mismatch</option>',
            reader_length_filter.text,
        )
        self.assertIn("qa=length_mismatch", reader_length_filter.text)
        self.assertIn("q=Tiny", reader_length_filter.text)
        self.assertIn("show_invisibles=1", reader_length_filter.text)
        self.assertIn("sync=0", reader_length_filter.text)
        self.assertIn("indent_preview=1", reader_length_filter.text)
        self.assertIn("Tiny", reader_length_filter.text)
        self.assertIn("Source chars 12", reader_length_filter.text)
        self.assertIn("T/S ratio", reader_length_filter.text)
        self.assertNotIn("Private source paragraph", reader_length_filter.text)
        self.assertNotIn("Paragraph waiting for translation", reader_length_filter.text)
        self.assertEqual(reader_paragraph_filter.status_code, 200)
        self.assertIn(
            '<option value="paragraph_mismatch" selected>Paragraph mismatch</option>',
            reader_paragraph_filter.text,
        )
        self.assertIn("qa=paragraph_mismatch", reader_paragraph_filter.text)
        self.assertIn("q=Tiny", reader_paragraph_filter.text)
        self.assertIn("show_invisibles=1", reader_paragraph_filter.text)
        self.assertIn("sync=0", reader_paragraph_filter.text)
        self.assertIn("indent_preview=1", reader_paragraph_filter.text)
        self.assertIn(
            "QA</span><strong>paragraph_mismatch</strong>",
            reader_paragraph_filter.text,
        )
        self.assertIn(
            "Search</span><strong>Search &quot;Tiny&quot;</strong>",
            reader_paragraph_filter.text,
        )
        self.assertIn("Tiny", reader_paragraph_filter.text)
        self.assertIn("Paragraph/line break mismatch", reader_paragraph_filter.text)
        self.assertIn("reader-qa-issue-nav", reader_paragraph_filter.text)
        self.assertIn("reader-outline", reader_paragraph_filter.text)
        self.assertIn("Visible units: 1", reader_paragraph_filter.text)
        self.assertIn("data-reader-outline-navigation", reader_paragraph_filter.text)
        self.assertIn("data-reader-outline-anchor", reader_paragraph_filter.text)
        self.assertIn(
            'title="Sequence 3: translated; Blocks block-3; '
            'Translation much longer; Paragraph/line break mismatch"',
            reader_paragraph_filter.text,
        )
        self.assertIn("reader-qa-filter-metric is-active", reader_paragraph_filter.text)
        self.assertIn('aria-current="page"', reader_paragraph_filter.text)
        self.assertIn(
            f'href="/admin/logs/{logger.run_dir.name}/reader?sequence=1'
            "&amp;limit=100&amp;show_invisibles=1&amp;sync=0"
            '&amp;q=Tiny&amp;indent_preview=1&amp;qa=paragraph_mismatch"',
            reader_paragraph_filter.text,
        )
        self.assertIn(
            f'href="/admin/logs/{logger.run_dir.name}/reader?sequence=1'
            "&amp;limit=100&amp;show_invisibles=1&amp;sync=0"
            '&amp;q=Tiny&amp;indent_preview=1&amp;qa=missing_translation"',
            reader_paragraph_filter.text,
        )
        self.assertIn('href="#reader-original-3"', reader_paragraph_filter.text)
        self.assertNotIn('href="#reader-original-2"', reader_paragraph_filter.text)
        self.assertIn("data-reader-qa-step-controls", reader_paragraph_filter.text)
        self.assertIn("data-reader-qa-step-navigation", reader_paragraph_filter.text)
        self.assertIn("data-reader-qa-progress", reader_paragraph_filter.text)
        self.assertIn("Issues in window: 1", reader_paragraph_filter.text)
        self.assertIn("Source lines 1", reader_paragraph_filter.text)
        self.assertIn("Translation lines 2", reader_paragraph_filter.text)
        self.assertIn("Source blank lines 0", reader_paragraph_filter.text)
        self.assertIn("Translation blank lines 0", reader_paragraph_filter.text)
        self.assertNotIn("Private source paragraph", reader_paragraph_filter.text)
        self.assertNotIn(
            "Paragraph waiting for translation",
            reader_paragraph_filter.text,
        )
        self.assertEqual(diagnostics_paragraph_filter.status_code, 200)
        self.assertIn(
            '<option value="paragraph_mismatch" selected>Paragraph mismatch</option>',
            diagnostics_paragraph_filter.text,
        )
        self.assertIn("qa=paragraph_mismatch", diagnostics_paragraph_filter.text)
        self.assertIn("q=Tiny", diagnostics_paragraph_filter.text)
        self.assertIn("show_invisibles=1", diagnostics_paragraph_filter.text)
        self.assertIn("Tiny", diagnostics_paragraph_filter.text)
        self.assertIn(
            "Paragraph/line break mismatch",
            diagnostics_paragraph_filter.text,
        )
        self.assertIn("Source lines 1", diagnostics_paragraph_filter.text)
        self.assertIn("Translation lines 2", diagnostics_paragraph_filter.text)
        self.assertNotIn("Private source paragraph", diagnostics_paragraph_filter.text)
        self.assertNotIn(
            "Paragraph waiting for translation",
            diagnostics_paragraph_filter.text,
        )
        self.assertEqual(reader_empty_filter.status_code, 200)
        self.assertIn(
            '<option value="empty_source" selected>Empty source</option>',
            reader_empty_filter.text,
        )
        self.assertIn("No work units match this QA filter.", reader_empty_filter.text)
        self.assertIn("No QA issues in this window.", reader_empty_filter.text)
        self.assertIn("reader-outline", reader_empty_filter.text)
        self.assertIn('<details class="reader-outline"', reader_empty_filter.text)
        self.assertIn("Visible units: 0", reader_empty_filter.text)
        self.assertIn("No blocks in this reader window.", reader_empty_filter.text)
        self.assertNotIn("data-reader-outline-navigation", reader_empty_filter.text)
        self.assertNotIn("data-reader-outline-anchor", reader_empty_filter.text)
        self.assertNotIn("data-reader-review-controls", reader_empty_filter.text)
        self.assertNotIn("data-reader-review-navigation", reader_empty_filter.text)
        self.assertNotIn("data-reader-review-mark", reader_empty_filter.text)
        self.assertNotIn("data-reader-review-panel", reader_empty_filter.text)
        self.assertNotIn("data-reader-review-filter", reader_empty_filter.text)
        self.assertNotIn("data-reader-review-step-controls", reader_empty_filter.text)
        self.assertNotIn("data-reader-review-step", reader_empty_filter.text)
        self.assertNotIn("data-reader-review-shortcuts", reader_empty_filter.text)
        self.assertNotIn("data-reader-review-save-url", reader_empty_filter.text)
        self.assertNotIn("data-reader-qa-step-controls", reader_empty_filter.text)
        self.assertNotIn("data-reader-qa-step-navigation", reader_empty_filter.text)
        self.assertNotIn("data-reader-qa-progress", reader_empty_filter.text)
        self.assertNotIn("setActiveIssue", reader_empty_filter.text)
        self.assertNotIn("Private source paragraph", reader_empty_filter.text)
        self.assertEqual(reader_invalid_filter.status_code, 200)
        self.assertIn(
            '<option value="all" selected>All</option>',
            reader_invalid_filter.text,
        )
        self.assertNotIn("qa=unknown", reader_invalid_filter.text)
        self.assertEqual(download.status_code, 200)
        with ZipFile(BytesIO(download.content)) as archive:
            raw_text_diagnostics = json.loads(
                archive.read("raw_text_diagnostics.json")
            )
            metadata_archive_text = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in {
                    "run.json",
                    "effective_run.json",
                    "work_units.json",
                    "summary.md",
                    "README.md",
                }
            )
            archive_text = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in archive.namelist()
            )
        raw_text_diagnostics_text = json.dumps(
            raw_text_diagnostics,
            ensure_ascii=False,
        )
        self.assertTrue(raw_text_diagnostics["contains_raw_text"])
        self.assertIn("Private source paragraph", raw_text_diagnostics_text)
        self.assertIn("Приватний перекладений абзац", raw_text_diagnostics_text)
        self.assertIn("Paragraph waiting for translation", raw_text_diagnostics_text)
        self.assertIn("very long translated expansion", raw_text_diagnostics_text)
        self.assertNotIn("Private source paragraph", metadata_archive_text)
        self.assertNotIn("Приватний перекладений абзац", metadata_archive_text)
        self.assertNotIn("Paragraph waiting for translation", metadata_archive_text)
        self.assertNotIn("very long translated expansion", metadata_archive_text)
        self.assertNotIn("Source chars", metadata_archive_text)
        self.assertNotIn("Source lines", metadata_archive_text)
        self.assertNotIn("Paragraph/line break mismatch", metadata_archive_text)
        self.assertNotIn("reader-qa-issue-nav", archive_text)
        self.assertNotIn("reader-position-bar", archive_text)
        self.assertNotIn("data-reader-qa-step-controls", archive_text)
        self.assertNotIn("data-reader-qa-step-navigation", archive_text)
        self.assertNotIn("data-reader-qa-progress", archive_text)
        self.assertNotIn("is-active-qa-issue", archive_text)
        self.assertNotIn("data-reader-search-hit-controls", archive_text)
        self.assertNotIn("data-reader-search-hit-navigation", archive_text)
        self.assertNotIn("is-active-search-hit", archive_text)
        self.assertNotIn("data-reader-review-controls", archive_text)
        self.assertNotIn("data-reader-review-navigation", archive_text)
        self.assertNotIn("data-reader-review-panel", archive_text)
        self.assertNotIn("data-reader-review-filter", archive_text)
        self.assertNotIn("data-reader-review-step-controls", archive_text)
        self.assertNotIn("data-reader-review-step", archive_text)
        self.assertNotIn("data-reader-review-shortcuts", archive_text)
        self.assertEqual(save_mark.status_code, 200)
        self.assertTrue(save_mark.json()["ok"])
        self.assertEqual(save_mark.json()["marks"], {"1": "needs_review"})
        self.assertTrue(review_marks_document["contains_raw_text"])
        self.assertEqual(review_marks_document["version"], 1)
        self.assertEqual(
            review_marks_document["marks"]["1"]["mark"],
            "needs_review",
        )
        self.assertEqual(
            review_marks_document["marks"]["1"]["source_text"],
            "Private source paragraph\tA\nNext\xa0line \u200b<script>alert(1)</script>",
        )
        self.assertEqual(
            review_marks_document["marks"]["1"]["translated_text"],
            "  Приватний перекладений абзац\tA\n"
            "Наступний\xa0рядок <img src=x onerror=alert(1)>",
        )
        self.assertEqual(
            review_marks_document["marks"]["1"]["source_block_ids"],
            ["block-1"],
        )
        self.assertIn(
            'const savedReviewMarks = {"1": "needs_review"};',
            reader_with_saved_mark.text,
        )
        self.assertEqual(details_after_mark.status_code, 200)
        self.assertNotIn("reader_review_marks.json", details_after_mark.text)
        self.assertEqual(details_api_after_mark.status_code, 200)
        details_after_mark_text = json.dumps(
            details_api_after_mark.json(),
            ensure_ascii=False,
        )
        self.assertNotIn("reader_review_marks", details_after_mark_text)
        self.assertNotIn("Private source paragraph", details_after_mark_text)
        self.assertEqual(download_after_mark.status_code, 200)
        with ZipFile(BytesIO(download_after_mark.content)) as archive:
            marked_archive_names = archive.namelist()
            marked_raw_text_diagnostics = json.loads(
                archive.read("raw_text_diagnostics.json")
            )
        self.assertNotIn("reader_review_marks.json", marked_archive_names)
        marked_raw_text = json.dumps(marked_raw_text_diagnostics, ensure_ascii=False)
        self.assertIn("Private source paragraph", marked_raw_text)
        self.assertIn("Приватний перекладений абзац", marked_raw_text)
        self.assertEqual(clear_mark.status_code, 200)
        self.assertEqual(clear_mark.json()["marks"], {})
        self.assertEqual(review_marks_after_clear["marks"], {})

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
                        metadata={
                            "result_file_name": "book.uk.txt",
                            "safe_long_note": "safe-note-" + ("x" * 180),
                            "source_text": "RAW ACTIVITY SOURCE",
                            "translated_text": "RAW ACTIVITY TRANSLATION",
                            "prompt": "RAW ACTIVITY PROMPT",
                            "api_key": "sk-activity-secret",
                            "traceback": "Traceback (most recent call last)",
                            "storage_path": "/var/private/activity.txt",
                        },
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
            self.assertIn("data-label=\"Metadata\"", activity_page.text)
            self.assertIn("admin-cell-error", activity_page.text)
            self.assertIn("safe_long_note: safe-note-", activity_page.text)
            self.assertNotIn("RAW ACTIVITY SOURCE", activity_page.text)
            self.assertNotIn("RAW ACTIVITY TRANSLATION", activity_page.text)
            self.assertNotIn("RAW ACTIVITY PROMPT", activity_page.text)
            self.assertNotIn("sk-activity-secret", activity_page.text)
            self.assertNotIn("Traceback", activity_page.text)
            self.assertNotIn("/var/private/activity.txt", activity_page.text)
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

    def test_user_profile_shows_safe_support_debug_translation_links(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            log_root = Path(temp_dir) / "translation-runs"
            with SQLiteUserActivityStore(db_path) as activity_store:
                activity_store.record_event(
                    UserActivityEventInput(
                        actor_type=ActivityActorType.USER,
                        actor_id="telegram:42",
                        channel="telegram",
                        channel_user_id="42",
                        surface=ActivitySurface.BOT,
                        event_type="translation.mode.selected",
                        action="select",
                        target_type="translation_mode",
                        target_id="book_manuscript",
                        outcome=ActivityOutcome.SUCCESS,
                        metadata={
                            "translation_mode": "book_manuscript",
                            "file_name": "very-long-safe-manuscript-name.txt",
                            "source_text": "RAW SOURCE SENTINEL",
                            "translated_text": "RAW TRANSLATION SENTINEL",
                            "prompt": "RAW PROMPT SENTINEL",
                            "api_key": "sk-support-secret",
                            "traceback": "Traceback (most recent call last)",
                            "object_storage_path": "/object-storage/private/book.txt",
                            "secret_id": "deepseek.api_keys.support",
                        },
                    )
                )
                activity_store.record_event(
                    UserActivityEventInput(
                        actor_type=ActivityActorType.USER,
                        actor_id="telegram:42",
                        channel="telegram",
                        channel_user_id="42",
                        surface=ActivitySurface.BOT,
                        event_type="translation.target_language.selected",
                        action="select",
                        target_type="target_language",
                        target_id="uk",
                        outcome=ActivityOutcome.SUCCESS,
                        metadata={
                            "target_language": "uk",
                            "translation_mode": "book_manuscript",
                            "file_name": "very-long-safe-manuscript-name.txt",
                        },
                    )
                )

            logger = TranslationRunLogger.start(
                root=log_root,
                metadata=TranslationRunMetadata(
                    job_id="job-support-1",
                    order_id="order-support-1",
                    user_id="telegram:42",
                    file_name="very-long-safe-manuscript-name.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    translator_model="deepseek-chat",
                    total_fragment_count=1,
                ),
            )
            logger.finish(
                status="failed",
                error_message=(
                    "Provider failed after echoing RAW SOURCE SENTINEL "
                    "RAW TRANSLATION SENTINEL RAW PROMPT SENTINEL"
                ),
            )
            run_id = Path(logger.run_dir).name
            completed_logger = TranslationRunLogger.start(
                root=log_root,
                metadata=TranslationRunMetadata(
                    job_id="job-support-2",
                    order_id="order-support-2",
                    user_id="telegram:42",
                    file_name="completed-safe-manuscript-name.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    translator_model="deepseek-chat",
                    total_fragment_count=1,
                ),
            )
            completed_logger.finish(
                status="completed",
                result_file_name="completed-safe-manuscript-name.uk.txt",
            )
            completed_run_id = Path(completed_logger.run_dir).name
            with SQLiteUserActivityStore(db_path) as activity_store:
                activity_store.record_event(
                    UserActivityEventInput(
                        actor_type=ActivityActorType.USER,
                        actor_id="telegram:42",
                        channel="telegram",
                        channel_user_id="42",
                        surface=ActivitySurface.BOT,
                        event_type="translation.failed",
                        action="failed",
                        target_type="document",
                        target_id="very-long-safe-manuscript-name.txt",
                        outcome=ActivityOutcome.FAILURE,
                        job_id="job-support-1",
                        order_id="order-support-1",
                        translation_run_dir=str(logger.run_dir),
                        metadata={
                            "file_name": "very-long-safe-manuscript-name.txt",
                            "target_language": "uk",
                            "translation_mode": "book_manuscript",
                        },
                    )
                )
                activity_store.record_event(
                    UserActivityEventInput(
                        actor_type=ActivityActorType.USER,
                        actor_id="telegram:42",
                        channel="telegram",
                        channel_user_id="42",
                        surface=ActivitySurface.BOT,
                        event_type="translation.completed",
                        action="completed",
                        target_type="document",
                        target_id="completed-safe-manuscript-name.txt",
                        outcome=ActivityOutcome.SUCCESS,
                        job_id="job-support-2",
                        order_id="order-support-2",
                        translation_run_dir=str(completed_logger.run_dir),
                        metadata={
                            "file_name": "completed-safe-manuscript-name.txt",
                            "result_file_name": (
                                "completed-safe-manuscript-name.uk.txt"
                            ),
                            "target_language": "uk",
                            "translation_mode": "book_manuscript",
                        },
                    )
                )

            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_db_path=str(db_path),
                        translation_run_log_root=str(log_root),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            response = client.get("/admin/users/telegram:42")

            self.assertEqual(response.status_code, 200)
            self.assertIn("Support profile", response.text)
            self.assertIn("Recent translations", response.text)
            self.assertIn("very-long-safe-manuscript-name.txt", response.text)
            self.assertIn("completed-safe-manuscript-name.txt", response.text)
            self.assertIn("book_manuscript", response.text)
            self.assertIn("uk", response.text)
            self.assertIn("failed", response.text)
            self.assertIn("completed", response.text)
            self.assertIn(f'/admin/translations/{run_id}/trace', response.text)
            self.assertIn(f'/admin/logs/{completed_run_id}', response.text)
            self.assertIn("Support reports", response.text)
            self.assertIn("Unknown", response.text)
            self.assertNotIn("RAW SOURCE SENTINEL", response.text)
            self.assertNotIn("RAW TRANSLATION SENTINEL", response.text)
            self.assertNotIn("RAW PROMPT SENTINEL", response.text)
            self.assertNotIn("sk-support-secret", response.text)
            self.assertNotIn(".api_keys.", response.text)
            self.assertNotIn("Traceback", response.text)
            self.assertNotIn("/object-storage/private", response.text)

    def test_user_profile_without_translation_sources_is_honest_unknown(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteUserActivityStore(db_path) as activity_store:
                activity_store.record_event(
                    UserActivityEventInput(
                        actor_type=ActivityActorType.USER,
                        actor_id="telegram:77",
                        channel="telegram",
                        channel_user_id="77",
                        surface=ActivitySurface.BOT,
                        event_type="user.interface_language.changed",
                        action="change",
                        outcome=ActivityOutcome.SUCCESS,
                        metadata={"language_code": "en"},
                    )
                )

            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_db_path=str(db_path),
                        translation_run_log_root=str(Path(temp_dir) / "runs"),
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            response = client.get("/admin/users/telegram:77")

            self.assertEqual(response.status_code, 200)
            self.assertIn("Support profile", response.text)
            self.assertIn("Support reports", response.text)
            self.assertIn("Unknown", response.text)
            self.assertIn("No linked translation runs found.", response.text)

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
            self.assertIn("Provider incident state", response.text)
            self.assertIn("Keys configured", response.text)
            self.assertIn("Runtime sees channels", response.text)
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

    def test_test_all_ai_provider_keys_ignores_stale_run_log_for_ready_job(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            jobs_path = Path(temp_dir) / "jobs.sqlite3"
            log_root = Path(temp_dir) / "translation-runs"
            store = SQLiteTranslationJobStore(jobs_path)
            try:
                ready = _persistent_job(store, order_id="order-ready")
                _add_units(store, ready.id)
                unit = store.claim_next_work_unit(ready.id, worker_id="worker-a")
                store.complete_work_unit(
                    unit.id,
                    translated_text="translated",
                    prompt_tokens=12,
                    completion_tokens=9,
                    cache_hit_tokens=0,
                    cache_miss_tokens=0,
                )
            finally:
                store.close()
            TranslationRunLogger.start(
                root=log_root,
                metadata=TranslationRunMetadata(
                    job_id=ready.id,
                    order_id=ready.order_id,
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                ),
            )
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
                return_value=AIProviderProbeResult(
                    status="provider_check_passed",
                    error=None,
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
            probe.assert_called_once()
            self.assertNotIn("sk-main-secret", tested.text)
            self.assertNotIn(".api_keys.", tested.text)

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
                                "secret_id=deepseek.api_keys.key-1 "
                                "FORBIDDEN_PROVIDER_PROMPT"
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
                            "secret_id=deepseek.api_keys.key-1 "
                            "FORBIDDEN_PROVIDER_PROMPT"
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
            self.assertIn("Provider incident state", page.text)
            self.assertIn("Read-only diagnosis", page.text)
            self.assertIn("Probe, change and", page.text)
            self.assertIn("danger actions stay below", page.text)
            self.assertIn("Keys configured", page.text)
            self.assertIn("Keys valid", page.text)
            self.assertIn("Keys enabled", page.text)
            self.assertIn("Runtime sees channels", page.text)
            self.assertIn("1 active / 1 degraded", page.text)
            self.assertIn("Safe failure categories", page.text)
            self.assertIn("rate_limit 2 / auth 1 / timeout 4", page.text)
            self.assertIn("unavailable 1", page.text)
            self.assertIn("unsafe_model_output 5", page.text)
            self.assertIn("Fallback capacity", page.text)
            self.assertIn("0 slots / 1 usable channels", page.text)
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
            self.assertNotIn("FORBIDDEN_PROVIDER_PROMPT", page.text)
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
            self.assertNotIn("FORBIDDEN_PROVIDER_PROMPT", serialized_payload)
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

    def test_ai_provider_pages_and_api_show_safe_capacity_diagnostics(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            with SQLiteAIProviderRuntimeStore(db_path) as runtime:
                runtime.record_status(
                    provider_id="deepseek",
                    source="worker",
                    status="ok",
                    reload_interval_seconds=30.0,
                    active_channels=(
                        AIProviderRuntimeChannel(
                            label="main",
                            weight=1,
                            max_parallel_requests=2,
                            active_requests=1,
                        ),
                    ),
                    provider_state=AIProviderRuntimeProviderState(
                        adaptive_enabled=True,
                        current_limit=1,
                        max_capacity=1,
                        active_requests=1,
                        available_slots=0,
                        circuit_state="open",
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

            with patch(
                "translator_service.admin.routes._ai_provider_capacity_diagnostics",
                return_value=(_provider_capacity_diagnostic(),),
            ):
                provider_page = client.get("/admin/ai-providers")
                live_page = client.get("/admin/live")
                runtime_api = client.get("/admin/api/ai-providers/runtime")

            self.assertEqual(provider_page.status_code, 200)
            self.assertEqual(live_page.status_code, 200)
            self.assertEqual(runtime_api.status_code, 200)
            self.assertIn("Provider capacity leases", provider_page.text)
            self.assertIn("Provider capacity leases", live_page.text)
            self.assertIn("cap denied", provider_page.text)
            self.assertIn("throttle denied", provider_page.text)
            self.assertIn("not which job should run next", provider_page.text)
            self.assertIn("job job-capacity", provider_page.text)
            self.assertIn("unit unit-capacity", provider_page.text)
            payload = runtime_api.json()
            capacity = payload["providers"][0]["provider_capacity"]
            self.assertEqual(capacity["diagnostic_scope"], "provider_capacity_only")
            self.assertEqual(capacity["queue_policy"], "not_in_scope")
            self.assertEqual(capacity["status"], "cap_denied")
            self.assertEqual(capacity["cap_denied_slots"], 1)
            self.assertEqual(capacity["throttle_input"]["state"], "throttle_denied")
            self.assertEqual(
                [slot["status"] for slot in capacity["slots"]],
                ["leased", "cap_denied"],
            )
            serialized = "\n".join(
                [
                    provider_page.text,
                    live_page.text,
                    json.dumps(payload, sort_keys=True),
                ]
            )
            self.assertNotIn("sk-capacity-secret", serialized)
            self.assertNotIn("Bearer", serialized)
            self.assertNotIn(".api_keys.", serialized)
            self.assertNotIn("lease-token-secret", serialized)
            self.assertNotIn("claim-token-secret", serialized)

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
            self.assertIn("Provider incident state", page.text)
            self.assertIn("Runtime sees channels", page.text)
            self.assertIn("1 active / 0 degraded", page.text)
            self.assertIn("Safe failure categories", page.text)
            self.assertIn("none", page.text)
            self.assertIn("Fallback capacity", page.text)
            self.assertIn("2 slots / 1 usable channels", page.text)
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

    def test_ai_provider_page_labels_degraded_runtime_with_active_channels(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            with SQLiteAIProviderRuntimeStore(db_path) as runtime:
                runtime.record_status(
                    provider_id="deepseek",
                    source="admin_store",
                    status="degraded",
                    reload_interval_seconds=30.0,
                    active_channels=(
                        AIProviderRuntimeChannel(
                            label="fallback",
                            weight=1,
                            max_parallel_requests=2,
                            health="healthy",
                        ),
                    ),
                    provider_state=AIProviderRuntimeProviderState(
                        adaptive_enabled=True,
                        current_limit=1,
                        max_capacity=2,
                        active_requests=0,
                        available_slots=1,
                    ),
                    error=(
                        "provider degraded Bearer sk-runtime-secret "
                        "FORBIDDEN_PROVIDER_PROMPT"
                    ),
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
            self.assertIn("Provider incident state", page.text)
            self.assertIn("Runtime sees channels", page.text)
            self.assertIn("1 active / 0 degraded / runtime degraded", page.text)
            self.assertIn("Fallback capacity", page.text)
            self.assertIn("1 slots / 1 usable channels", page.text)
            self.assertNotIn("sk-runtime-secret", page.text)
            self.assertNotIn("Bearer", page.text)
            self.assertNotIn("FORBIDDEN_PROVIDER_PROMPT", page.text)

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
