from __future__ import annotations

import unittest
from decimal import Decimal

import httpx

from translator_service.admin.provider_balance import fetch_deepseek_balance


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


if __name__ == "__main__":
    unittest.main()
