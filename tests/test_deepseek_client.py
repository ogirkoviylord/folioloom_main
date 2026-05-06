import json
import ssl
import unittest
from urllib.error import URLError

from translator_service.deepseek_client import (
    DeepSeekApiError,
    DeepSeekChatResult,
    DeepSeekClient,
    DeepSeekUsage,
)


class DeepSeekClientTest(unittest.TestCase):
    def test_sends_chat_completion_request_to_deepseek(self):
        transport = RecordingTransport(
            response={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Hello world",
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "total_tokens": 14,
                    "prompt_cache_hit_tokens": 6,
                    "prompt_cache_miss_tokens": 4,
                },
            }
        )
        client = DeepSeekClient(
            api_key="secret-key",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            transport=transport,
            retry_attempts=1,
        )

        result = client.create_chat_completion(
            system_prompt="Translate accurately.",
            user_text="Привет мир",
        )

        self.assertEqual(
            result,
            DeepSeekChatResult(
                content="Hello world",
                usage=DeepSeekUsage(
                    prompt_tokens=10,
                    completion_tokens=4,
                    total_tokens=14,
                    prompt_cache_hit_tokens=6,
                    prompt_cache_miss_tokens=4,
                ),
            ),
        )
        self.assertEqual(transport.url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(transport.headers["Authorization"], "Bearer secret-key")
        self.assertEqual(transport.headers["Content-Type"], "application/json")
        self.assertEqual(
            transport.body,
            {
                "model": "deepseek-v4-flash",
                "messages": [
                    {"role": "system", "content": "Translate accurately."},
                    {"role": "user", "content": "Привет мир"},
                ],
                "stream": False,
                "thinking": {"type": "disabled"},
                "temperature": 0.2,
            },
        )

    def test_translate_builds_translation_prompt(self):
        transport = RecordingTransport(
            response={
                "choices": [{"message": {"content": "Hello"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 2, "total_tokens": 13},
            }
        )
        client = DeepSeekClient(
            api_key="secret-key",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            transport=transport,
            retry_attempts=1,
        )

        translated = client.translate(
            text="Привет",
            source_language="ru",
            target_language="en",
        )

        self.assertEqual(translated, "Hello")
        system_prompt = transport.body["messages"][0]["content"]
        self.assertIn("professional document translator", system_prompt)
        self.assertIn("Russian", system_prompt)
        self.assertIn("English", system_prompt)

    def test_translate_expands_uk_language_code_to_ukrainian(self):
        transport = RecordingTransport(
            response={
                "choices": [{"message": {"content": "Привіт"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 2, "total_tokens": 13},
            }
        )
        client = DeepSeekClient(
            api_key="secret-key",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            transport=transport,
        )

        client.translate(
            text="Привет",
            source_language="ru",
            target_language="uk",
        )

        system_prompt = transport.body["messages"][0]["content"]
        self.assertIn("Russian", system_prompt)
        self.assertIn("Ukrainian", system_prompt)
        self.assertNotIn(" to uk.", system_prompt)

    def test_auto_source_prompt_translates_every_human_language(self):
        transport = RecordingTransport(
            response={
                "choices": [{"message": {"content": "Переклад"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 2, "total_tokens": 13},
            }
        )
        client = DeepSeekClient(
            api_key="secret-key",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            transport=transport,
        )

        client.translate(
            text="Русский. English. Polski. Nederlands.",
            source_language="auto",
            target_language="uk",
        )

        system_prompt = transport.body["messages"][0]["content"]
        self.assertIn("Translate every human language", system_prompt)
        self.assertIn("Ukrainian", system_prompt)
        self.assertIn("Do not leave", system_prompt)
        self.assertIn("source_language", system_prompt)
        self.assertIn("Never include notes", system_prompt)
        self.assertIn("Do not transliterate", system_prompt)
        self.assertIn("pangram", system_prompt)

    def test_raises_api_error_for_non_200_response(self):
        transport = RecordingTransport(
            status=429,
            response={"error": {"message": "rate limit"}},
        )
        client = DeepSeekClient(
            api_key="secret-key",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            transport=transport,
        )

        with self.assertRaises(DeepSeekApiError) as error:
            client.create_chat_completion(
                system_prompt="Translate accurately.",
                user_text="Привет",
            )

        self.assertIn("429", str(error.exception))
        self.assertIn("rate limit", str(error.exception))

    def test_raises_api_error_when_response_has_no_content(self):
        transport = RecordingTransport(response={"choices": []})
        client = DeepSeekClient(
            api_key="secret-key",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            transport=transport,
        )

        with self.assertRaises(DeepSeekApiError):
            client.create_chat_completion(
                system_prompt="Translate accurately.",
                user_text="Привет",
            )

    def test_raises_actionable_error_for_local_ssl_certificate_problem(self):
        def failing_transport(
            *,
            url: str,
            headers: dict[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> tuple[int, bytes]:
            raise URLError(
                ssl.SSLCertVerificationError(
                    "certificate verify failed: unable to get local issuer certificate"
                )
            )

        client = DeepSeekClient(
            api_key="secret-key",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            transport=failing_transport,
        )

        with self.assertRaises(DeepSeekApiError) as error:
            client.create_chat_completion(
                system_prompt="Translate accurately.",
                user_text="Привет",
            )

        self.assertIn("local Python SSL certificates", str(error.exception))
        self.assertIn("Install Certificates.command", str(error.exception))

    def test_retries_transient_network_error_before_succeeding(self):
        class FlakyTransport:
            def __init__(self) -> None:
                self.calls = 0

            def __call__(
                self,
                *,
                url: str,
                headers: dict[str, str],
                body: bytes,
                timeout_seconds: float,
            ) -> tuple[int, bytes]:
                self.calls += 1
                if self.calls == 1:
                    raise TimeoutError("timed out while reading response")
                return (
                    200,
                    json.dumps(
                        {
                            "choices": [{"message": {"content": "Привіт"}}],
                            "usage": {
                                "prompt_tokens": 3,
                                "completion_tokens": 2,
                                "total_tokens": 5,
                            },
                        }
                    ).encode("utf-8"),
                )

        transport = FlakyTransport()
        client = DeepSeekClient(
            api_key="secret-key",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            transport=transport,
            retry_delay_seconds=0,
        )

        result = client.create_chat_completion(
            system_prompt="Translate accurately.",
            user_text="Привет",
        )

        self.assertEqual(result.content, "Привіт")
        self.assertEqual(transport.calls, 2)

    def test_retries_temporary_http_error_before_succeeding(self):
        class FlakyHttpTransport:
            def __init__(self) -> None:
                self.calls = 0

            def __call__(
                self,
                *,
                url: str,
                headers: dict[str, str],
                body: bytes,
                timeout_seconds: float,
            ) -> tuple[int, bytes]:
                self.calls += 1
                if self.calls == 1:
                    return 503, json.dumps({"error": {"message": "busy"}}).encode("utf-8")
                return (
                    200,
                    json.dumps(
                        {
                            "choices": [{"message": {"content": "Hola"}}],
                            "usage": {
                                "prompt_tokens": 3,
                                "completion_tokens": 2,
                                "total_tokens": 5,
                            },
                        }
                    ).encode("utf-8"),
                )

        transport = FlakyHttpTransport()
        client = DeepSeekClient(
            api_key="secret-key",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            transport=transport,
            retry_delay_seconds=0,
        )

        result = client.create_chat_completion(
            system_prompt="Translate accurately.",
            user_text="Привет",
        )

        self.assertEqual(result.content, "Hola")
        self.assertEqual(transport.calls, 2)

    def test_raises_api_error_after_retries_are_exhausted(self):
        class FailingTransport:
            def __init__(self) -> None:
                self.calls = 0

            def __call__(
                self,
                *,
                url: str,
                headers: dict[str, str],
                body: bytes,
                timeout_seconds: float,
            ) -> tuple[int, bytes]:
                self.calls += 1
                raise TimeoutError("timed out while reading response")

        transport = FailingTransport()
        client = DeepSeekClient(
            api_key="secret-key",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            transport=transport,
            retry_attempts=2,
            retry_delay_seconds=0,
        )

        with self.assertRaises(DeepSeekApiError) as error:
            client.create_chat_completion(
                system_prompt="Translate accurately.",
                user_text="Привет",
            )

        self.assertEqual(transport.calls, 2)
        self.assertIn("after 2 attempts", str(error.exception))


class RecordingTransport:
    def __init__(self, *, response: dict, status: int = 200) -> None:
        self.response = response
        self.status = status
        self.url: str | None = None
        self.headers: dict[str, str] = {}
        self.body: dict | None = None

    def __call__(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> tuple[int, bytes]:
        self.url = url
        self.headers = headers
        self.body = json.loads(body.decode("utf-8"))
        return self.status, json.dumps(self.response).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
