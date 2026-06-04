import json
import unittest

from translator_service.deepseek_client import (
    DeepSeekApiError,
    DeepSeekUnsafeModelOutputError,
)
from translator_service.deepseek_key_pool import (
    DeepSeekChannelConfig,
    DeepSeekKeyPoolTranslator,
)
from translator_service.provider_failure_diagnostics import (
    ProviderFailureCategory,
    build_provider_failure_diagnostic,
    classify_provider_failure,
)
from translator_service.provider_throttle import ProviderThrottleConfig


class ProviderFailureDiagnosticsTest(unittest.TestCase):
    def test_classifies_representative_provider_failures(self):
        cases = [
            (
                DeepSeekApiError("DeepSeek API returned HTTP 429: rate limit"),
                ProviderFailureCategory.RATE_LIMITED,
                "429",
            ),
            (
                TimeoutError("request timed out"),
                ProviderFailureCategory.TIMEOUT,
                None,
            ),
            (
                DeepSeekApiError("DeepSeek API returned HTTP 503: unavailable"),
                ProviderFailureCategory.UNAVAILABLE_5XX,
                "5xx",
            ),
            (
                DeepSeekApiError("DeepSeek API returned HTTP 401: auth failed"),
                ProviderFailureCategory.AUTH,
                "4xx",
            ),
            (
                DeepSeekApiError("DeepSeek billing quota insufficient"),
                ProviderFailureCategory.BILLING,
                None,
            ),
            (
                DeepSeekApiError("DeepSeek response was not valid JSON"),
                ProviderFailureCategory.MALFORMED_RESPONSE,
                None,
            ),
            (
                DeepSeekUnsafeModelOutputError("tool_or_execution_claim"),
                ProviderFailureCategory.UNSAFE_MODEL_OUTPUT,
                None,
            ),
            (
                DeepSeekApiError("DeepSeek API request failed: network unreachable"),
                ProviderFailureCategory.NETWORK,
                None,
            ),
            (
                DeepSeekApiError("provider adaptive circuit open"),
                ProviderFailureCategory.CIRCUIT_OPEN,
                None,
            ),
            (
                DeepSeekApiError("DeepSeek API returned HTTP 418: teapot"),
                ProviderFailureCategory.PROVIDER_OTHER,
                "4xx",
            ),
        ]

        for error, expected_category, expected_bucket in cases:
            with self.subTest(error=str(error)):
                classified = classify_provider_failure(error)

            self.assertEqual(classified.failure_category, expected_category)
            self.assertEqual(classified.http_status_bucket, expected_bucket)

    def test_builds_safe_diagnostic_from_provider_snapshots(self):
        pool = DeepSeekKeyPoolTranslator(
            channels=[DeepSeekChannelConfig(api_key="sk-private-key", label="primary")],
            client_factory=RecordingClientFactory(
                {
                    "sk-private-key": [
                        DeepSeekApiError(
                            "DeepSeek API returned HTTP 429: rate limit "
                            "for sk-private-key"
                        )
                    ],
                }
            ),
            throttle_config=ProviderThrottleConfig(
                enabled=True,
                initial_parallel=1,
                min_parallel=1,
                circuit_failure_threshold=1,
                circuit_reset_seconds=60.0,
            ),
            cooldown_seconds=30,
            clock=lambda: 100.0,
        )

        with self.assertRaises(DeepSeekApiError) as error:
            pool.translate(text="Private source text", source_language="en", target_language="uk")

        diagnostic = build_provider_failure_diagnostic(
            error.exception,
            translator=pool,
            provider_id="deepseek",
        )
        payload = diagnostic.to_safe_payload()
        payload_text = json.dumps(payload, sort_keys=True)

        self.assertEqual(payload["failure_category"], "rate_limited")
        self.assertEqual(payload["http_status_bucket"], "429")
        self.assertEqual(payload["provider_id"], "deepseek")
        self.assertEqual(payload["channel"]["error_kind"], "rate_limited")
        self.assertEqual(payload["channel"]["health"], "cooling_down")
        self.assertEqual(payload["adaptive_circuit"]["circuit_state"], "open")
        self.assertIn("channel_fingerprint", payload["channel"])
        self.assertNotIn("sk-private-key", payload_text)
        self.assertNotIn("Private source text", payload_text)


class RecordingClientFactory:
    def __init__(self, responses: dict[str, list[object]]) -> None:
        self._responses = {key: list(value) for key, value in responses.items()}

    def __call__(self, *, api_key: str, **kwargs):
        return RecordingClient(api_key=api_key, responses=self._responses[api_key])


class RecordingClient:
    last_usage = None

    def __init__(self, *, api_key: str, responses: list[object]) -> None:
        self.api_key = api_key
        self._responses = responses

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return str(response)


if __name__ == "__main__":
    unittest.main()
