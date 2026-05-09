import unittest
from base64 import urlsafe_b64encode
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.admin.ai_provider_keys import SQLiteAIProviderKeyStore
from translator_service.admin.provider_runtime import (
    AIProviderRuntimeChannel,
    SQLiteAIProviderRuntimeStore,
)
from translator_service.admin.secrets import SQLiteEncryptedSecretStore
from translator_service.ai_provider_runtime import load_ai_provider_runtime_keys
from translator_service.config import Settings

MASTER_KEY = urlsafe_b64encode(b"4" * 32).decode("ascii")


class AIProviderRuntimeTest(unittest.TestCase):
    def test_loads_active_admin_provider_keys_without_secret_identifiers(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    keys.add_key(
                        provider_id="deepseek",
                        label="main",
                        plaintext="sk-main-secret",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                        weight=3,
                        max_parallel_requests=2,
                    )
                    disabled = keys.add_key(
                        provider_id="deepseek",
                        label="paused",
                        plaintext="sk-paused-secret",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                    )
                    keys.set_key_enabled(
                        provider_id="deepseek",
                        key_id=disabled.key_id,
                        enabled=False,
                        actor_id="bootstrap-owner",
                        secret_describer=secrets.describe_secret,
                    )

            runtime_keys = load_ai_provider_runtime_keys(
                Settings(
                    admin_db_path=str(db_path),
                    admin_secret_master_key=MASTER_KEY,
                ),
                provider_id="deepseek",
            )

        self.assertEqual(len(runtime_keys), 1)
        self.assertEqual(runtime_keys[0].label, "main")
        self.assertEqual(runtime_keys[0].api_key, "sk-main-secret")
        self.assertEqual(runtime_keys[0].weight, 3)
        self.assertEqual(runtime_keys[0].max_parallel_requests, 2)
        self.assertNotIn("sk-main-secret", repr(runtime_keys[0]))
        self.assertNotIn(".api_keys.", repr(runtime_keys[0]))

    def test_returns_empty_tuple_when_admin_secret_store_is_unavailable(self):
        runtime_keys = load_ai_provider_runtime_keys(
            Settings(
                admin_db_path=":memory:",
                admin_secret_master_key="",
            ),
            provider_id="deepseek",
        )

        self.assertEqual(runtime_keys, ())

    def test_records_runtime_status_and_consumes_reload_request(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteAIProviderRuntimeStore(db_path) as store:
                store.record_status(
                    provider_id="deepseek",
                    source="admin_store",
                    status="ok",
                    reload_interval_seconds=30.0,
                    active_channels=(
                        AIProviderRuntimeChannel(
                            label="stable",
                            weight=3,
                            max_parallel_requests=2,
                        ),
                    ),
                    error=None,
                )
                store.request_reload(
                    provider_id="deepseek",
                    actor_id="bootstrap-owner",
                )
                pending_state = store.get_reload_state("deepseek")
                first_request = store.consume_reload_request("deepseek")
                consumed_state = store.get_reload_state("deepseek")
                second_request = store.consume_reload_request("deepseek")
                status = store.get_status("deepseek")

        self.assertIsNotNone(first_request)
        self.assertIsNone(second_request)
        self.assertIsNotNone(pending_state)
        self.assertTrue(pending_state.pending)
        self.assertEqual(pending_state.actor_id, "bootstrap-owner")
        self.assertIsNotNone(consumed_state)
        self.assertFalse(consumed_state.pending)
        self.assertIsNotNone(consumed_state.consumed_at)
        self.assertIsNotNone(status)
        self.assertEqual(status.source, "admin_store")
        self.assertEqual(status.status, "ok")
        self.assertEqual(status.active_channels[0].label, "stable")
        self.assertEqual(status.active_channels[0].weight, 3)
        self.assertNotIn(".api_keys.", repr(status))
        self.assertNotIn("sk-", repr(status))


if __name__ == "__main__":
    unittest.main()
