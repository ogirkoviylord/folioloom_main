from __future__ import annotations

import unittest
from datetime import UTC, datetime

from translator_service.admin.ai_provider_keys import AIProviderKeySummary
from translator_service.admin.integrations import (
    IntegrationCategory,
    IntegrationSecretSummary,
    IntegrationState,
    IntegrationSummary,
)
from translator_service.admin.provider_health import ProviderHealthSummary
from translator_service.admin.secret_safety import build_secret_safety_report
from translator_service.admin.views import settings_body


class AdminSecretSafetyTest(unittest.TestCase):
    def test_report_flags_missing_integration_secret_without_exposing_secret_id(self):
        report = build_secret_safety_report(
            integration_summaries=(_integration_summary(),),
            integration_connections={},
            ai_provider_key_pools={},
            provider_health_summaries=(),
        )

        self.assertEqual(report.total_count, 1)
        self.assertEqual(report.missing_count, 1)
        self.assertEqual(report.issue_count, 1)
        self.assertEqual(report.items[0].status, "missing")
        self.assertEqual(report.items[0].owner_label, "Telegram")
        serialized = str(report)
        self.assertIn("Bot token", serialized)
        self.assertNotIn("telegram.bot_token", serialized)

    def test_report_tracks_ai_provider_keys_that_need_validation(self):
        report = build_secret_safety_report(
            integration_summaries=(),
            integration_connections={},
            ai_provider_key_pools={"deepseek": (_provider_key(label="main"),)},
            provider_health_summaries=(
                _provider_health(
                    status="healthy",
                    last_validation_status="not checked",
                ),
            ),
        )

        self.assertEqual(report.needs_check_count, 1)
        self.assertEqual(report.issue_count, 1)
        self.assertEqual(report.items[0].status, "needs_check")
        self.assertEqual(report.items[0].label, "main")
        self.assertIn("/admin/ai-providers", report.items[0].href)

    def test_report_tracks_failed_provider_validation_without_raw_secret_material(self):
        report = build_secret_safety_report(
            integration_summaries=(),
            integration_connections={},
            ai_provider_key_pools={"deepseek": (_provider_key(label="main"),)},
            provider_health_summaries=(
                _provider_health(
                    status="degraded",
                    last_validation_status="failed",
                    last_error_excerpt="value=[redacted]",
                ),
            ),
        )

        self.assertEqual(report.failed_count, 1)
        self.assertEqual(report.items[0].status, "failed")
        serialized = str(report)
        self.assertIn("[redacted]", serialized)
        self.assertNotIn("sk-raw-secret", serialized)
        self.assertNotIn("deepseek.api_keys", serialized)

    def test_settings_body_escapes_report_items(self):
        report = build_secret_safety_report(
            integration_summaries=(
                _integration_summary(
                    label="<script>alert(1)</script>",
                    secret_label="Use <token>",
                ),
            ),
            integration_connections={},
            ai_provider_key_pools={},
            provider_health_summaries=(),
        )

        html = settings_body(report)

        self.assertIn("Secret &amp; Config Safety", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("Use &lt;token&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("telegram.bot_token", html)


def _integration_summary(
    *,
    label: str = "Telegram",
    secret_label: str = "Bot token",
) -> IntegrationSummary:
    return IntegrationSummary(
        integration_id="telegram",
        label=label,
        category=IntegrationCategory.MESSENGER_BOT_CHANNEL,
        description="Telegram channel.",
        state=IntegrationState.MISSING_SECRET,
        secrets=(
            IntegrationSecretSummary(
                secret_id="telegram.bot_token",
                label=secret_label,
                kind="bot_token",
                required=True,
                configured=False,
            ),
        ),
    )


def _provider_key(*, label: str) -> AIProviderKeySummary:
    now = datetime(2026, 5, 9, tzinfo=UTC)
    return AIProviderKeySummary(
        provider_id="deepseek",
        key_id="key-1",
        secret_id="deepseek.api_keys.key-1",
        label=label,
        enabled=True,
        weight=1,
        max_parallel_requests=1,
        masked_value="sk-****cret",
        fingerprint="fingerprint",
        version=1,
        disabled=False,
        created_at=now,
        updated_at=now,
    )


def _provider_health(
    *,
    status: str,
    last_validation_status: str,
    last_error_excerpt: str = "n/a",
) -> ProviderHealthSummary:
    return ProviderHealthSummary(
        provider_id="deepseek",
        label="DeepSeek",
        active_key_count=1,
        disabled_key_count=0,
        total_key_count=1,
        status=status,
        last_validation_status=last_validation_status,
        last_error_excerpt=last_error_excerpt,
        can_test=True,
    )


if __name__ == "__main__":
    unittest.main()
