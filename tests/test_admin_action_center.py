import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from translator_service.admin.action_center import (
    ActionCenter,
    ActionItem,
    build_action_center,
)
from translator_service.admin.bootstrap_config import AdminBootstrapConfig
from translator_service.admin.integration_connections import (
    IntegrationConnectionSummary,
)
from translator_service.admin.integrations import (
    DEFAULT_INTEGRATION_REGISTRY,
    IntegrationSecretSummary,
)
from translator_service.admin.provider_balance import (
    ProviderBalanceAmount,
    ProviderBalanceSnapshot,
)
from translator_service.admin.provider_runtime import (
    AIProviderRuntimeChannel,
    AIProviderRuntimeReloadRequest,
    AIProviderRuntimeStatus,
)
from translator_service.admin.views import overview_body


class AdminActionCenterTest(unittest.TestCase):
    def test_flags_missing_required_integration_connections_failed_jobs_and_high_disk(
        self,
    ):
        center = build_action_center(
            integration_summaries=DEFAULT_INTEGRATION_REGISTRY.list_summaries(),
            integration_connections={},
            failed_today=3,
            tokens_today=250_000,
            disk_percent=91.0,
            deepseek_key_count=1,
        )

        keys = {item.key for item in center.items}

        self.assertIn("integrations_missing", keys)
        self.assertIn("failed_translations", keys)
        self.assertIn("token_spend_high", keys)
        self.assertIn("disk_high", keys)

    def test_empty_state_when_everything_is_healthy(self):
        center = build_action_center(
            integration_summaries=(),
            integration_connections={},
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=1,
        )

        self.assertEqual(center.items, ())

    def test_healthy_connection_row_satisfies_missing_legacy_secret(self):
        center = build_action_center(
            integration_summaries=DEFAULT_INTEGRATION_REGISTRY.list_summaries(),
            integration_connections={
                "telegram": (
                    _connection_summary(
                        integration_id="telegram",
                        configured=True,
                    ),
                )
            },
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=1,
        )

        keys = {item.key for item in center.items}

        self.assertNotIn("integrations_missing", keys)

    def test_connection_row_with_missing_required_secret_is_missing(self):
        center = build_action_center(
            integration_summaries=DEFAULT_INTEGRATION_REGISTRY.list_summaries(),
            integration_connections={
                "telegram": (
                    _connection_summary(
                        integration_id="telegram",
                        configured=False,
                    ),
                )
            },
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=1,
        )

        keys = {item.key for item in center.items}

        self.assertIn("integrations_missing", keys)

    def test_connection_row_with_disabled_required_secret_is_missing(self):
        center = build_action_center(
            integration_summaries=DEFAULT_INTEGRATION_REGISTRY.list_summaries(),
            integration_connections={
                "telegram": (
                    _connection_summary(
                        integration_id="telegram",
                        configured=True,
                        disabled=True,
                    ),
                )
            },
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=1,
        )

        keys = {item.key for item in center.items}

        self.assertIn("integrations_missing", keys)

    def test_connection_row_without_required_secret_values_is_missing(self):
        center = build_action_center(
            integration_summaries=DEFAULT_INTEGRATION_REGISTRY.list_summaries(),
            integration_connections={
                "telegram": (
                    _connection_summary(
                        integration_id="telegram",
                        configured=True,
                        include_secret=False,
                    ),
                )
            },
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=1,
        )

        keys = {item.key for item in center.items}

        self.assertIn("integrations_missing", keys)

    def test_no_deepseek_keys_creates_ai_provider_missing(self):
        center = build_action_center(
            integration_summaries=(),
            integration_connections={},
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=0,
        )

        self.assertEqual(
            [item.key for item in center.items],
            ["ai_provider_missing"],
        )
        self.assertEqual(center.items[0].href, "/admin/ai-providers")

    def test_env_deepseek_keys_satisfy_ai_provider_missing_action(self):
        center = build_action_center(
            integration_summaries=(),
            integration_connections={},
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=0,
            bootstrap_config=AdminBootstrapConfig(
                deepseek_key_count=2,
                telegram_configured=False,
            ),
        )

        keys = {item.key for item in center.items}

        self.assertNotIn("ai_provider_missing", keys)

    def test_secret_safety_issues_create_settings_action(self):
        center = build_action_center(
            integration_summaries=(),
            integration_connections={},
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=1,
            secret_safety_issue_count=2,
        )

        self.assertEqual(
            [item.key for item in center.items],
            ["secret_safety_issues"],
        )
        self.assertEqual(center.items[0].href, "/admin/settings")

    def test_runtime_alerts_surface_stale_pending_and_missing_channels(self):
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        center = build_action_center(
            integration_summaries=(),
            integration_connections={},
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=1,
            runtime_statuses=(
                AIProviderRuntimeStatus(
                    provider_id="deepseek",
                    source="admin_store",
                    status="missing_keys",
                    reload_interval_seconds=30.0,
                    last_reloaded_at=now - timedelta(minutes=10),
                    active_channels=(),
                    error="No active DeepSeek admin keys.",
                ),
            ),
            runtime_reload_states=(
                AIProviderRuntimeReloadRequest(
                    request_id="reload-1",
                    provider_id="deepseek",
                    actor_id="bootstrap-owner",
                    requested_at=now - timedelta(minutes=5),
                ),
            ),
            now=now,
        )

        keys = [item.key for item in center.items]

        self.assertIn("ai_provider_runtime_stale", keys)
        self.assertIn("ai_provider_runtime_reload_pending", keys)
        self.assertIn("ai_provider_runtime_missing_channels", keys)
        self.assertNotIn("ai_provider_runtime_degraded", keys)
        missing_item = next(
            item
            for item in center.items
            if item.key == "ai_provider_runtime_missing_channels"
        )
        self.assertEqual(missing_item.href, "/admin/ai-providers")
        self.assertEqual(missing_item.title, "DeepSeek runtime has no active channels")

    def test_degraded_runtime_with_channels_gets_distinct_action(self):
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        center = build_action_center(
            integration_summaries=(),
            integration_connections={},
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=1,
            runtime_statuses=(
                AIProviderRuntimeStatus(
                    provider_id="deepseek",
                    source="admin_store",
                    status="degraded",
                    reload_interval_seconds=30.0,
                    last_reloaded_at=now,
                    active_channels=(
                        AIProviderRuntimeChannel(
                            label="main",
                            weight=1,
                            max_parallel_requests=2,
                            health="degraded",
                            error_kind="provider_error",
                        ),
                    ),
                ),
            ),
            now=now,
        )

        by_key = {item.key: item for item in center.items}

        self.assertIn("ai_provider_runtime_degraded", by_key)
        self.assertNotIn("ai_provider_runtime_missing_channels", by_key)
        self.assertEqual(
            by_key["ai_provider_runtime_degraded"].title,
            "DeepSeek runtime is degraded",
        )
        self.assertIn(
            "active DeepSeek channels",
            by_key["ai_provider_runtime_degraded"].detail,
        )

    def test_runtime_not_reporting_is_action_when_keys_exist(self):
        center = build_action_center(
            integration_summaries=(),
            integration_connections={},
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=1,
            runtime_statuses=(),
        )

        self.assertEqual(
            [item.key for item in center.items],
            ["ai_provider_runtime_not_reporting"],
        )
        self.assertEqual(center.items[0].href, "/admin/ai-providers")

    def test_degraded_runtime_with_active_channels_creates_distinct_action(self):
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        raw_secret = "sk-runtime-secret"
        raw_prompt = "Translate this private source text"
        center = build_action_center(
            integration_summaries=(),
            integration_connections={},
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=1,
            runtime_statuses=(
                AIProviderRuntimeStatus(
                    provider_id="deepseek",
                    source="admin_store",
                    status="degraded",
                    reload_interval_seconds=30.0,
                    last_reloaded_at=now,
                    active_channels=(
                        AIProviderRuntimeChannel(
                            label="stable",
                            weight=1,
                            max_parallel_requests=1,
                            health="cooling_down",
                            error_kind="provider_error",
                            last_error_excerpt=f"{raw_secret} {raw_prompt}",
                        ),
                    ),
                    error=f"{raw_secret} {raw_prompt}",
                ),
            ),
            now=now,
        )

        self.assertEqual(
            [item.key for item in center.items],
            ["ai_provider_runtime_degraded"],
        )
        item = center.items[0]
        rendered_action_text = f"{item.title} {item.detail}"
        self.assertEqual(item.href, "/admin/ai-providers")
        self.assertEqual(item.title, "DeepSeek runtime is degraded")
        self.assertIn("active DeepSeek channels", item.detail)
        self.assertNotIn("DeepSeek runtime has no active channels", rendered_action_text)
        self.assertNotIn(raw_secret, rendered_action_text)
        self.assertNotIn(raw_prompt, rendered_action_text)

    def test_healthy_runtime_does_not_create_action(self):
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        center = build_action_center(
            integration_summaries=(),
            integration_connections={},
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=1,
            runtime_statuses=(
                AIProviderRuntimeStatus(
                    provider_id="deepseek",
                    source="admin_store",
                    status="ok",
                    reload_interval_seconds=30.0,
                    last_reloaded_at=now,
                    active_channels=(
                        AIProviderRuntimeChannel(
                            label="stable",
                            weight=1,
                            max_parallel_requests=1,
                        ),
                    ),
                ),
            ),
            now=now,
        )

        self.assertEqual(center.items, ())

    def test_low_deepseek_balance_creates_action(self):
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        center = build_action_center(
            integration_summaries=(),
            integration_connections={},
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=1,
            deepseek_balance_snapshot=ProviderBalanceSnapshot(
                provider_id="deepseek",
                status="available",
                is_available=True,
                balances=(
                    ProviderBalanceAmount(
                        currency="USD",
                        total_balance=Decimal("1.25"),
                        granted_balance=Decimal("0"),
                        topped_up_balance=Decimal("1.25"),
                    ),
                ),
                last_checked_at=now,
                last_success_at=now,
            ),
            deepseek_low_balance_threshold=Decimal("5.00"),
            deepseek_low_balance_currency="USD",
            deepseek_balance_stale_seconds=300,
            now=now,
        )

        self.assertIn("deepseek_balance_low", [item.key for item in center.items])

    def test_unavailable_and_stale_deepseek_balance_create_actions(self):
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        center = build_action_center(
            integration_summaries=(),
            integration_connections={},
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=1,
            deepseek_balance_snapshot=ProviderBalanceSnapshot(
                provider_id="deepseek",
                status="unavailable",
                is_available=False,
                balances=(),
                last_checked_at=now - timedelta(minutes=10),
                last_success_at=now - timedelta(minutes=10),
            ),
            deepseek_low_balance_threshold=Decimal("5.00"),
            deepseek_low_balance_currency="USD",
            deepseek_balance_stale_seconds=300,
            now=now,
        )

        keys = [item.key for item in center.items]
        self.assertIn("deepseek_balance_unavailable", keys)
        self.assertIn("deepseek_balance_stale", keys)

    def test_overview_body_escapes_action_items(self):
        html = overview_body(
            ActionCenter(
                items=(
                    ActionItem(
                        key="unsafe",
                        severity="bad severity",
                        title="<script>alert(1)</script>",
                        detail="Use <admin> & check",
                        href="javascript:alert(1)",
                    ),
                )
            )
        )

        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("Use &lt;admin&gt; &amp; check", html)
        self.assertIn("action-info", html)
        self.assertIn('href="/admin/overview"', html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("javascript:", html)


def _connection_summary(
    *,
    integration_id: str,
    configured: bool,
    disabled: bool = False,
    enabled: bool = True,
    include_secret: bool = True,
) -> IntegrationConnectionSummary:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return IntegrationConnectionSummary(
        integration_id=integration_id,
        connection_id=f"{integration_id}-connection",
        label="stable",
        enabled=enabled,
        secret_values=_connection_secrets(
            integration_id=integration_id,
            configured=configured,
            disabled=disabled,
            include_secret=include_secret,
        ),
        created_at=now,
        updated_at=now,
    )


def _connection_secrets(
    *,
    integration_id: str,
    configured: bool,
    disabled: bool,
    include_secret: bool,
) -> tuple[IntegrationSecretSummary, ...]:
    if not include_secret:
        return ()
    return (
        IntegrationSecretSummary(
            secret_id=f"{integration_id}.bot_token",
            label="Bot token",
            kind="bot_token",
            required=True,
            configured=configured,
            disabled=disabled,
        ),
    )


if __name__ == "__main__":
    unittest.main()
