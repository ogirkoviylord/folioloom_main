from __future__ import annotations

import unittest
from base64 import urlsafe_b64encode
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from translator_service.admin.ai_provider_keys import SQLiteAIProviderKeyStore
from translator_service.admin.provider_balance import (
    ProviderBalanceAmount,
    ProviderBalanceSnapshot,
    SQLiteProviderBalanceStore,
    fetch_deepseek_balance,
    refresh_deepseek_balance,
)
from translator_service.admin.secrets import SQLiteEncryptedSecretStore
from translator_service.config import Settings


class AdminProviderBalanceTest(unittest.TestCase):
    def test_fetches_deepseek_balance_with_bearer_auth(self):
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "is_available": True,
                    "balance_infos": [
                        {
                            "currency": "USD",
                            "total_balance": "12.34",
                            "granted_balance": "2.00",
                            "topped_up_balance": "10.34",
                        }
                    ],
                },
            )

        result = fetch_deepseek_balance(
            "deepseek",
            "sk-live-secret",
            base_url="https://deepseek.test",
            transport=httpx.MockTransport(handler),
        )

        self.assertEqual(result.status, "ok")
        self.assertTrue(result.is_available)
        self.assertEqual(result.balances[0].currency, "USD")
        self.assertEqual(result.balances[0].total_balance, Decimal("12.34"))
        self.assertEqual(str(requests[0].url), "https://deepseek.test/user/balance")
        self.assertEqual(requests[0].headers["authorization"], "Bearer sk-live-secret")

    def test_failure_does_not_include_raw_key_or_response_body(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                json={"error": {"message": "bad key sk-live-secret"}},
            )

        result = fetch_deepseek_balance(
            "deepseek",
            "sk-live-secret",
            base_url="https://deepseek.test",
            transport=httpx.MockTransport(handler),
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "http_401")
        self.assertIn("HTTP 401", result.error_message or "")
        self.assertNotIn("sk-live-secret", result.error_message or "")
        self.assertNotIn("bad key", result.error_message or "")

    def test_malformed_response_is_safe_failure(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"is_available": True})

        result = fetch_deepseek_balance(
            "deepseek",
            "sk-live-secret",
            base_url="https://deepseek.test",
            transport=httpx.MockTransport(handler),
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "malformed_response")
        self.assertEqual(result.balances, ())

    def test_store_round_trips_balance_snapshot(self):
        checked_at = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteProviderBalanceStore(db_path) as store:
                store.save_snapshot(
                    ProviderBalanceSnapshot(
                        provider_id="deepseek",
                        status="ok",
                        is_available=True,
                        balances=(
                            ProviderBalanceAmount(
                                currency="USD",
                                total_balance=Decimal("12.34"),
                                granted_balance=Decimal("2.00"),
                                topped_up_balance=Decimal("10.34"),
                            ),
                        ),
                        last_checked_at=checked_at,
                        last_success_at=checked_at,
                    )
                )
                loaded = store.get_snapshot("deepseek")

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.status, "ok")
        self.assertEqual(loaded.balances[0].total_balance, Decimal("12.34"))

    def test_failed_snapshot_preserves_previous_success_time(self):
        success_at = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        failed_at = datetime(2026, 5, 9, 12, 5, tzinfo=UTC)
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteProviderBalanceStore(db_path) as store:
                store.save_snapshot(
                    ProviderBalanceSnapshot(
                        provider_id="deepseek",
                        status="ok",
                        is_available=True,
                        balances=(),
                        last_checked_at=success_at,
                        last_success_at=success_at,
                    )
                )
                store.save_snapshot(
                    ProviderBalanceSnapshot(
                        provider_id="deepseek",
                        status="failed",
                        is_available=None,
                        balances=(),
                        last_checked_at=failed_at,
                        error_code="timeout",
                        error_message="Provider balance check timed out.",
                    )
                )
                loaded = store.get_snapshot("deepseek")

        self.assertEqual(loaded.status, "failed")
        self.assertEqual(loaded.last_success_at, success_at)

    def test_refresh_service_uses_first_enabled_key_and_saves_snapshot(self):
        master_key = urlsafe_b64encode(b"4" * 32).decode("ascii")
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "is_available": True,
                    "balance_infos": [
                        {
                            "currency": "USD",
                            "total_balance": "8.50",
                            "granted_balance": "0",
                            "topped_up_balance": "8.50",
                        }
                    ],
                },
            )

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            settings = Settings(
                admin_db_path=str(db_path),
                admin_secret_master_key=master_key,
                deepseek_base_url="https://deepseek.test",
            )
            with SQLiteEncryptedSecretStore(db_path, master_key=master_key) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    keys.add_key(
                        provider_id="deepseek",
                        label="main",
                        plaintext="sk-main-secret",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                    )
            snapshot = refresh_deepseek_balance(
                settings,
                transport=httpx.MockTransport(handler),
            )
            with SQLiteProviderBalanceStore(db_path) as store:
                loaded = store.get_snapshot("deepseek")

        self.assertEqual(snapshot.status, "available")
        self.assertEqual(loaded.status, "available")
        self.assertEqual(requests[0].headers["authorization"], "Bearer sk-main-secret")


if __name__ == "__main__":
    unittest.main()
