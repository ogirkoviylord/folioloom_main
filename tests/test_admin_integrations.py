from __future__ import annotations

import unittest
from dataclasses import asdict
from datetime import UTC, datetime

from translator_service.admin.integrations import (
    DEFAULT_AI_PROVIDER_REGISTRY,
    DEFAULT_INTEGRATION_REGISTRY,
    IntegrationCategory,
    IntegrationRegistry,
    IntegrationState,
)
from translator_service.admin.secrets import SecretMetadata, SecretNotFound


class AdminIntegrationsTest(unittest.TestCase):
    def test_registry_includes_mvp_integrations(self):
        definitions = {
            definition.integration_id: definition
            for definition in DEFAULT_INTEGRATION_REGISTRY.list_definitions()
        }

        self.assertEqual(
            set(definitions),
            {
                "telegram",
                "whatsapp",
                "instagram",
                "discord",
                "website_widget",
                "webhooks",
            },
        )
        self.assertEqual(
            definitions["telegram"].category,
            IntegrationCategory.MESSENGER_BOT_CHANNEL,
        )
        self.assertEqual(
            definitions["website_widget"].category,
            IntegrationCategory.WEBSITE_WIDGET,
        )

    def test_ai_providers_are_separate_from_integrations(self):
        integration_ids = {
            definition.integration_id
            for definition in DEFAULT_INTEGRATION_REGISTRY.list_definitions()
        }
        provider_ids = {
            definition.integration_id
            for definition in DEFAULT_AI_PROVIDER_REGISTRY.list_definitions()
        }

        self.assertNotIn("deepseek", integration_ids)
        self.assertNotIn("stripe", integration_ids)
        self.assertEqual(provider_ids, {"deepseek"})
        self.assertEqual(
            DEFAULT_AI_PROVIDER_REGISTRY.get_definition("deepseek").category,
            IntegrationCategory.AI_PROVIDER,
        )

    def test_missing_required_secrets_produce_missing_secret_state(self):
        summaries = {
            summary.integration_id: summary
            for summary in DEFAULT_AI_PROVIDER_REGISTRY.list_summaries(
                secret_describer=lambda secret_id: (_ for _ in ()).throw(
                    SecretNotFound(secret_id)
                )
            )
        }

        self.assertEqual(
            summaries["deepseek"].state,
            IntegrationState.MISSING_SECRET,
        )
        self.assertFalse(summaries["deepseek"].secrets[0].configured)
        self.assertEqual(summaries["deepseek"].secrets[0].secret_id, "deepseek.api_key")

    def test_secret_projection_uses_metadata_without_plaintext(self):
        plaintext = "sk-plain-secret"
        metadata = SecretMetadata(
            secret_id="deepseek.api_key",
            label="DeepSeek API key",
            kind="api_key",
            fingerprint="abc123fingerprint",
            masked_value="sk-****cret",
            version=7,
            disabled=False,
            created_at=datetime(2026, 5, 8, tzinfo=UTC),
            updated_at=datetime(2026, 5, 8, tzinfo=UTC),
        )
        summaries = {
            summary.integration_id: summary
            for summary in DEFAULT_AI_PROVIDER_REGISTRY.list_summaries(
                secret_describer=lambda secret_id: metadata
            )
        }

        deepseek = summaries["deepseek"]
        self.assertEqual(deepseek.state, IntegrationState.CONFIGURED)
        self.assertEqual(deepseek.secrets[0].masked_value, "sk-****cret")
        self.assertEqual(deepseek.secrets[0].fingerprint, "abc123fingerprint")
        self.assertEqual(deepseek.secrets[0].version, 7)
        self.assertNotIn(plaintext, repr(deepseek))
        self.assertNotIn(plaintext, repr(asdict(deepseek)))

    def test_unknown_integration_id_raises_key_error(self):
        registry = IntegrationRegistry([])

        with self.assertRaises(KeyError):
            registry.get_definition("missing")


if __name__ == "__main__":
    unittest.main()
