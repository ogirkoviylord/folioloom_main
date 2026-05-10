from __future__ import annotations

import json
import unittest
from dataclasses import asdict
from datetime import UTC, datetime

from translator_service.admin.ai_provider_keys import AIProviderKeySummary
from translator_service.admin.integrations import (
    IntegrationCategory,
    IntegrationState,
    IntegrationSummary,
)
from translator_service.admin.provider_health import build_provider_health
from translator_service.admin.provider_runtime import (
    AIProviderRuntimeChannel,
    AIProviderRuntimeProviderState,
    AIProviderRuntimeStatus,
)


class AdminProviderHealthTest(unittest.TestCase):
    def test_provider_without_keys_is_marked_missing(self):
        health = build_provider_health((_provider(),), {})

        self.assertEqual(len(health), 1)
        self.assertEqual(health[0].provider_id, "deepseek")
        self.assertEqual(health[0].label, "DeepSeek")
        self.assertEqual(health[0].active_key_count, 0)
        self.assertEqual(health[0].disabled_key_count, 0)
        self.assertEqual(health[0].total_key_count, 0)
        self.assertEqual(health[0].status, "missing_keys")
        self.assertEqual(health[0].last_validation_status, "not checked")
        self.assertEqual(health[0].last_error_excerpt, "n/a")
        self.assertFalse(health[0].can_test)

    def test_missing_runtime_keys_keep_provider_missing_instead_of_degraded(self):
        health = build_provider_health(
            (_provider(),),
            {},
            runtime_statuses=(
                AIProviderRuntimeStatus(
                    provider_id="deepseek",
                    source="admin_store",
                    status="missing_keys",
                    reload_interval_seconds=30.0,
                    last_reloaded_at=datetime(2026, 5, 9, tzinfo=UTC),
                    active_channels=(),
                    error="No active DeepSeek admin provider keys are set",
                ),
            ),
        )

        self.assertEqual(health[0].status, "missing_keys")
        self.assertEqual(health[0].last_validation_status, "not checked")
        self.assertFalse(health[0].can_test)

    def test_active_keys_make_provider_healthy(self):
        health = build_provider_health(
            (_provider(),),
            {"deepseek": (_key(label="main"), _key(label="backup"))},
        )

        self.assertEqual(health[0].active_key_count, 2)
        self.assertEqual(health[0].disabled_key_count, 0)
        self.assertEqual(health[0].total_key_count, 2)
        self.assertEqual(health[0].status, "healthy")
        self.assertTrue(health[0].can_test)

    def test_disabled_or_removed_keys_are_counted_separately(self):
        health = build_provider_health(
            (_provider(),),
            {
                "deepseek": (
                    _key(label="main"),
                    _key(label="removed", enabled=False, disabled=True),
                    _key(label="disabled-secret", disabled=True),
                )
            },
        )

        self.assertEqual(health[0].active_key_count, 1)
        self.assertEqual(health[0].disabled_key_count, 2)
        self.assertEqual(health[0].total_key_count, 3)
        self.assertEqual(health[0].status, "healthy")

    def test_validation_error_or_cooldown_degrades_provider(self):
        health = build_provider_health(
            (_provider(),),
            {"deepseek": (_key(),)},
            validation_metadata={
                "deepseek": {
                    "last_validation_status": "cooldown",
                    "last_error": "HTTP 429 while using Bearer sk-live-secret-value",
                }
            },
        )

        self.assertEqual(health[0].status, "degraded")
        self.assertEqual(health[0].last_validation_status, "cooldown")
        self.assertIn("[redacted]", health[0].last_error_excerpt)
        self.assertNotIn("sk-live-secret-value", health[0].last_error_excerpt)
        self.assertNotIn("Bearer", health[0].last_error_excerpt)

    def test_error_excerpt_is_redacted_and_truncated(self):
        health = build_provider_health(
            (_provider(),),
            {"deepseek": (_key(),)},
            validation_metadata={
                "deepseek": {
                    "last_validation_status": "error",
                    "last_error": (
                        "api_key=sk-super-secret-token "
                        + ("downstream validation failed " * 20)
                    ),
                }
            },
        )

        self.assertLessEqual(len(health[0].last_error_excerpt), 120)
        self.assertIn("[redacted]", health[0].last_error_excerpt)
        self.assertNotIn("sk-super-secret-token", health[0].last_error_excerpt)
        self.assertTrue(health[0].last_error_excerpt.endswith("..."))

    def test_serialized_health_does_not_expose_raw_key_or_secret_id(self):
        health = build_provider_health(
            (_provider(),),
            {
                "deepseek": (
                    _key(
                        key_id="key-1",
                        secret_id="deepseek.api_keys.key-1",
                        masked_value="sk-****cret",
                    ),
                )
            },
            validation_metadata={
                "deepseek": {
                    "last_validation_status": "error",
                    "last_error": (
                        "secret_id=deepseek.api_keys.key-1 value=sk-raw-secret"
                    ),
                }
            },
        )

        serialized = json.dumps(asdict(health[0]), sort_keys=True)
        self.assertNotIn("sk-raw-secret", serialized)
        self.assertNotIn("deepseek.api_keys.key-1", serialized)
        self.assertNotIn("secret_id", serialized)
        self.assertNotIn("masked_value", serialized)

    def test_runtime_cooldown_degrades_provider_without_exposing_secret_text(self):
        health = build_provider_health(
            (_provider(),),
            {"deepseek": (_key(),)},
            runtime_statuses=(
                AIProviderRuntimeStatus(
                    provider_id="deepseek",
                    source="bot_runtime",
                    status="ok",
                    reload_interval_seconds=30.0,
                    last_reloaded_at=datetime(2026, 5, 9, tzinfo=UTC),
                    active_channels=(
                        AIProviderRuntimeChannel(
                            label="main",
                            weight=1,
                            max_parallel_requests=2,
                            health="cooling_down",
                            cooldown_remaining_seconds=12.0,
                            error_kind="rate_limit",
                            last_error_excerpt=(
                                "HTTP 429 for Bearer sk-runtime-secret "
                                "secret_id=deepseek.api_keys.key-1"
                            ),
                        ),
                    ),
                    error=None,
                ),
            ),
        )

        self.assertEqual(health[0].status, "degraded")
        self.assertEqual(health[0].last_validation_status, "runtime degraded")
        self.assertIn("main", health[0].last_error_excerpt)
        self.assertIn("rate_limit", health[0].last_error_excerpt)
        self.assertIn("[redacted]", health[0].last_error_excerpt)
        self.assertNotIn("sk-runtime-secret", health[0].last_error_excerpt)
        self.assertNotIn("Bearer", health[0].last_error_excerpt)
        self.assertNotIn(".api_keys.", health[0].last_error_excerpt)

    def test_open_provider_circuit_degrades_provider_without_exposing_secret_text(self):
        health = build_provider_health(
            (_provider(),),
            {"deepseek": (_key(),)},
            runtime_statuses=(
                AIProviderRuntimeStatus(
                    provider_id="deepseek",
                    source="bot_runtime",
                    status="ok",
                    reload_interval_seconds=30.0,
                    last_reloaded_at=datetime(2026, 5, 9, tzinfo=UTC),
                    active_channels=(),
                    provider_state=AIProviderRuntimeProviderState(
                        adaptive_enabled=True,
                        current_limit=1,
                        max_capacity=4,
                        available_slots=0,
                        circuit_state="open",
                        circuit_open_remaining_seconds=90.0,
                        last_reason="billing sk-runtime-secret .api_keys.deepseek",
                    ),
                    error=None,
                ),
            ),
        )

        self.assertEqual(health[0].status, "degraded")
        self.assertEqual(health[0].last_validation_status, "runtime degraded")
        self.assertIn("provider circuit open", health[0].last_error_excerpt)
        self.assertIn("[redacted]", health[0].last_error_excerpt)
        self.assertNotIn("sk-runtime-secret", health[0].last_error_excerpt)
        self.assertNotIn(".api_keys.", health[0].last_error_excerpt)


def _provider(
    provider_id: str = "deepseek",
    label: str = "DeepSeek",
) -> IntegrationSummary:
    return IntegrationSummary(
        integration_id=provider_id,
        label=label,
        category=IntegrationCategory.AI_PROVIDER,
        description="Provider used for translation.",
        state=IntegrationState.MISSING_SECRET,
    )


def _key(
    *,
    provider_id: str = "deepseek",
    key_id: str = "key-1",
    secret_id: str = "secret-1",
    label: str = "main",
    enabled: bool = True,
    disabled: bool = False,
    masked_value: str | None = "sk-****cret",
) -> AIProviderKeySummary:
    now = datetime(2026, 5, 9, tzinfo=UTC)
    return AIProviderKeySummary(
        provider_id=provider_id,
        key_id=key_id,
        secret_id=secret_id,
        label=label,
        enabled=enabled,
        weight=1,
        max_parallel_requests=1,
        masked_value=masked_value,
        fingerprint="fingerprint",
        version=1,
        disabled=disabled,
        created_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    unittest.main()
