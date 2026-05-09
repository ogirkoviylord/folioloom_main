import unittest
from datetime import UTC, datetime

from translator_service.admin.ai_provider_keys import AIProviderKeySummary
from translator_service.admin.bootstrap_config import (
    apply_ai_provider_key_bootstrap,
    apply_integration_connection_bootstrap,
    env_bootstrap_config,
)


class AdminBootstrapConfigTest(unittest.TestCase):
    def test_detects_deepseek_key_count_and_telegram_token_without_secret_values(self):
        config = env_bootstrap_config(
            {
                "DEEPSEEK_API_KEY": "sk-single-secret",
                "DEEPSEEK_API_KEYS": "sk-first-secret, sk-second-secret",
                "TELEGRAM_BOT_TOKEN": "telegram-raw-secret",
            }
        )

        self.assertEqual(config.deepseek_key_count, 2)
        self.assertTrue(config.telegram_configured)
        serialized = str(config)
        self.assertIn("deepseek_key_count=2", serialized)
        self.assertNotIn("sk-single-secret", serialized)
        self.assertNotIn("sk-first-secret", serialized)
        self.assertNotIn("telegram-raw-secret", serialized)

    def test_falls_back_to_single_deepseek_key_when_key_list_is_empty(self):
        config = env_bootstrap_config(
            {
                "DEEPSEEK_API_KEY": "sk-single-secret",
                "DEEPSEEK_API_KEYS": " ",
            }
        )

        self.assertEqual(config.deepseek_key_count, 1)

    def test_adds_env_telegram_connection_without_raw_secret_value(self):
        config = env_bootstrap_config(
            {
                "TELEGRAM_BOT_TOKEN": "telegram-raw-secret",
            }
        )

        groups = apply_integration_connection_bootstrap({}, config)

        telegram_connections = groups["telegram"]
        self.assertEqual(len(telegram_connections), 1)
        self.assertEqual(telegram_connections[0].connection_id, "env-fallback")
        self.assertEqual(telegram_connections[0].label, "server .env")
        self.assertTrue(telegram_connections[0].enabled)
        self.assertTrue(telegram_connections[0].secret_values[0].configured)
        self.assertEqual(
            telegram_connections[0].secret_values[0].masked_value,
            "server .env",
        )
        self.assertNotIn("telegram-raw-secret", str(telegram_connections[0]))

    def test_env_deepseek_row_remains_visible_with_admin_keys(self):
        config = env_bootstrap_config(
            {
                "DEEPSEEK_API_KEYS": "sk-first-secret, sk-second-secret",
            }
        )
        pools = apply_ai_provider_key_bootstrap(
            {"deepseek": (_admin_key_summary(),)},
            config,
        )

        keys = pools["deepseek"]

        self.assertEqual([key.label for key in keys], ["admin", "server .env"])
        self.assertEqual(keys[1].masked_value, "server .env (2 keys)")
        self.assertNotIn("sk-first-secret", str(keys))


def _admin_key_summary() -> AIProviderKeySummary:
    now = datetime(2026, 5, 10, tzinfo=UTC)
    return AIProviderKeySummary(
        provider_id="deepseek",
        key_id="admin-key",
        secret_id="deepseek.api_keys.admin-key",
        label="admin",
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


if __name__ == "__main__":
    unittest.main()
