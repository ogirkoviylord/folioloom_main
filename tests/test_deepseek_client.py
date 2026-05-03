import json
import unittest

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
                },
            }
        )
        client = DeepSeekClient(
            api_key="secret-key",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            transport=transport,
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
        )

        translated = client.translate(
            text="Привет",
            source_language="ru",
            target_language="en",
        )

        self.assertEqual(translated, "Hello")
        system_prompt = transport.body["messages"][0]["content"]
        self.assertIn("professional document translator", system_prompt)
        self.assertIn("ru", system_prompt)
        self.assertIn("en", system_prompt)

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
