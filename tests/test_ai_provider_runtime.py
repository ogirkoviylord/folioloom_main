import sqlite3
import unittest
from base64 import urlsafe_b64encode
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.admin.ai_provider_keys import SQLiteAIProviderKeyStore
from translator_service.admin.provider_runtime import (
    AIProviderRuntimeChannel,
    AIProviderRuntimeProviderState,
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

    def test_runtime_status_roundtrips_channel_telemetry(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteAIProviderRuntimeStore(db_path) as store:
                recorded = store.record_status(
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
                            cooldown_remaining_seconds=12.5,
                            total_started_requests=10,
                            total_successful_requests=7,
                            total_temporary_failures=2,
                            total_permanent_failures=1,
                            total_rate_limit_failures=1,
                            total_unavailable_failures=1,
                            total_timeout_failures=1,
                            total_malformed_response_failures=1,
                            total_auth_failures=1,
                            total_billing_failures=1,
                            total_other_provider_failures=1,
                            total_unsafe_model_output_failures=2,
                            average_latency_ms=123.4,
                            last_latency_ms=234.5,
                            error_kind="temporary",
                            last_error_excerpt="provider rejected sk-secret .api_keys.deepseek",
                        ),
                    ),
                    error=None,
                )
                fetched = store.get_status("deepseek")

        self.assertIsNotNone(fetched)
        self.assertEqual(recorded.active_channels, fetched.active_channels)
        channel = fetched.active_channels[0]
        self.assertEqual(channel.health, "cooling_down")
        self.assertEqual(channel.active_requests, 1)
        self.assertEqual(channel.cooldown_remaining_seconds, 12.5)
        self.assertEqual(channel.total_started_requests, 10)
        self.assertEqual(channel.total_successful_requests, 7)
        self.assertEqual(channel.total_temporary_failures, 2)
        self.assertEqual(channel.total_permanent_failures, 1)
        self.assertEqual(channel.total_rate_limit_failures, 1)
        self.assertEqual(channel.total_unavailable_failures, 1)
        self.assertEqual(channel.total_timeout_failures, 1)
        self.assertEqual(channel.total_malformed_response_failures, 1)
        self.assertEqual(channel.total_auth_failures, 1)
        self.assertEqual(channel.total_billing_failures, 1)
        self.assertEqual(channel.total_other_provider_failures, 1)
        self.assertEqual(channel.total_unsafe_model_output_failures, 2)
        self.assertEqual(channel.average_latency_ms, 123.4)
        self.assertEqual(channel.last_latency_ms, 234.5)
        self.assertEqual(channel.error_kind, "temporary")
        self.assertEqual(
            channel.last_error_excerpt,
            "provider rejected sk-secret .api_keys.deepseek",
        )
        self.assertNotIn("sk-", repr(channel))
        self.assertNotIn(".api_keys.", repr(channel))
        self.assertNotIn("sk-", repr(fetched))
        self.assertNotIn(".api_keys.", repr(fetched))

    def test_runtime_status_roundtrips_provider_state(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteAIProviderRuntimeStore(db_path) as store:
                provider_state = AIProviderRuntimeProviderState(
                    adaptive_enabled=True,
                    current_limit=2,
                    max_capacity=5,
                    active_requests=1,
                    available_slots=1,
                    circuit_state="open",
                    circuit_open_remaining_seconds=42.5,
                    last_reason="provider rejected sk-secret .api_keys.deepseek",
                    total_ramp_ups=3,
                    total_decreases=4,
                    total_circuit_opened=5,
                )
                recorded = store.record_status(
                    provider_id="deepseek",
                    source="admin_store",
                    status="ok",
                    reload_interval_seconds=30.0,
                    active_channels=(),
                    provider_state=provider_state,
                    error=None,
                )
                fetched = store.get_status("deepseek")

        self.assertIsNotNone(fetched)
        self.assertEqual(recorded.provider_state, provider_state)
        self.assertEqual(fetched.provider_state, provider_state)
        self.assertNotIn("sk-", repr(fetched.provider_state))
        self.assertNotIn(".api_keys.", repr(fetched.provider_state))
        self.assertNotIn("sk-", repr(fetched))
        self.assertNotIn(".api_keys.", repr(fetched))

    def test_runtime_status_reads_legacy_provider_state_with_defaults(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteAIProviderRuntimeStore(db_path) as store:
                with store._connection:
                    store._connection.execute(
                        """
                        INSERT INTO admin_ai_provider_runtime_status (
                            provider_id, source, status, reload_interval_seconds,
                            active_channels_json, error, last_reloaded_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "deepseek",
                            "admin_store",
                            "ok",
                            30.0,
                            "[]",
                            None,
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                status = store.get_status("deepseek")

        self.assertIsNotNone(status)
        self.assertEqual(status.provider_state, AIProviderRuntimeProviderState())

    def test_runtime_status_migrates_database_without_provider_state_column(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            connection = sqlite3.connect(db_path)
            with connection:
                connection.execute(
                    """
                    CREATE TABLE admin_ai_provider_runtime_status (
                        provider_id TEXT PRIMARY KEY,
                        source TEXT NOT NULL,
                        status TEXT NOT NULL,
                        reload_interval_seconds REAL NOT NULL,
                        active_channels_json TEXT NOT NULL,
                        error TEXT,
                        last_reloaded_at TEXT NOT NULL
                    )
                    """
                )
            connection.close()

            with SQLiteAIProviderRuntimeStore(db_path) as store:
                columns = {
                    row["name"]
                    for row in store._connection.execute(
                        "PRAGMA table_info(admin_ai_provider_runtime_status)"
                    ).fetchall()
                }
                store.record_status(
                    provider_id="deepseek",
                    source="admin_store",
                    status="ok",
                    reload_interval_seconds=30.0,
                    active_channels=(),
                    provider_state=AIProviderRuntimeProviderState(
                        current_limit=3,
                        available_slots=2,
                    ),
                    error=None,
                )
                status = store.get_status("deepseek")

        self.assertIn("provider_state_json", columns)
        self.assertIsNotNone(status)
        self.assertEqual(status.provider_state.current_limit, 3)
        self.assertEqual(status.provider_state.available_slots, 2)

    def test_runtime_status_reads_legacy_channel_json_with_defaults(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteAIProviderRuntimeStore(db_path) as store:
                with store._connection:
                    store._connection.execute(
                        """
                        INSERT INTO admin_ai_provider_runtime_status (
                            provider_id, source, status, reload_interval_seconds,
                            active_channels_json, error, last_reloaded_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "deepseek",
                            "admin_store",
                            "ok",
                            30.0,
                            '[{"label": "legacy", "weight": 2, "max_parallel_requests": 3}]',
                            None,
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                status = store.get_status("deepseek")

        self.assertIsNotNone(status)
        channel = status.active_channels[0]
        self.assertEqual(channel.label, "legacy")
        self.assertEqual(channel.weight, 2)
        self.assertEqual(channel.max_parallel_requests, 3)
        self.assertEqual(channel.active_requests, 0)
        self.assertEqual(channel.health, "healthy")
        self.assertEqual(channel.cooldown_remaining_seconds, 0.0)
        self.assertEqual(channel.total_started_requests, 0)
        self.assertEqual(channel.total_successful_requests, 0)
        self.assertEqual(channel.total_temporary_failures, 0)
        self.assertIsNone(channel.average_latency_ms)
        self.assertIsNone(channel.last_latency_ms)
        self.assertIsNone(channel.error_kind)
        self.assertIsNone(channel.last_error_excerpt)


if __name__ == "__main__":
    unittest.main()
