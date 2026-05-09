from __future__ import annotations

import unittest

import httpx

from translator_service.admin.provider_probe import validate_ai_provider_key


class AdminProviderProbeTest(unittest.TestCase):
    def test_deepseek_probe_calls_models_endpoint_with_bearer_auth(self):
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"data": []})

        result = validate_ai_provider_key(
            "deepseek",
            "sk-live-secret",
            base_url="https://deepseek.test",
            transport=httpx.MockTransport(handler),
        )

        self.assertEqual(result.status, "provider_check_passed")
        self.assertIsNone(result.error)
        self.assertEqual(str(requests[0].url), "https://deepseek.test/models")
        self.assertEqual(requests[0].headers["authorization"], "Bearer sk-live-secret")

    def test_probe_failure_does_not_include_raw_key_or_response_body(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                json={"error": {"message": "bad key sk-live-secret"}},
            )

        result = validate_ai_provider_key(
            "deepseek",
            "sk-live-secret",
            base_url="https://deepseek.test",
            transport=httpx.MockTransport(handler),
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("HTTP 401", result.error or "")
        self.assertNotIn("sk-live-secret", result.error or "")
        self.assertNotIn("bad key", result.error or "")

    def test_unknown_provider_fails_without_network(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("unknown providers should not call network")

        result = validate_ai_provider_key(
            "unknown",
            "sk-live-secret",
            transport=httpx.MockTransport(handler),
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("Unsupported provider", result.error or "")


if __name__ == "__main__":
    unittest.main()
