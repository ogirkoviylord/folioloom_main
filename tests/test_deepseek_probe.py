import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from translator_service.deepseek_probe import build_probe_result_message, main


class DeepSeekProbeTest(unittest.TestCase):
    def test_builds_probe_result_message_without_leaking_secret(self):
        message = build_probe_result_message("Hello", prompt_tokens=12, total_tokens=15)

        self.assertIn("DeepSeek API ответил", message)
        self.assertIn("Hello", message)
        self.assertIn("15", message)
        self.assertNotIn("sk-", message)

    def test_builds_probe_result_message_includes_input_tokens(self):
        message = build_probe_result_message(
            "Hi", prompt_tokens=100, total_tokens=200
        )
        self.assertIn("100", message)
        self.assertIn("Input tokens", message)


class DeepSeekProbeMainTest(unittest.TestCase):
    def test_main_raises_when_api_key_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                main()

    @patch("translator_service.deepseek_probe.DeepSeekClient")
    def test_main_calls_api_and_prints_result(self, mock_client_cls):
        mock_result = SimpleNamespace(
            content="Hello",
            usage=SimpleNamespace(prompt_tokens=10, total_tokens=20),
        )
        mock_client = MagicMock()
        mock_client.create_chat_completion.return_value = mock_result
        mock_client_cls.return_value = mock_client

        with patch.dict(
            os.environ,
            {"DEEPSEEK_API_KEY": "test-key"},
            clear=True,
        ):
            main()

        mock_client_cls.assert_called_once()
        init_kwargs = mock_client_cls.call_args
        self.assertEqual(init_kwargs.kwargs["api_key"], "test-key")
        mock_client.create_chat_completion.assert_called_once()

    @patch("translator_service.deepseek_probe.DeepSeekClient")
    def test_main_uses_custom_base_url(self, mock_client_cls):
        mock_result = SimpleNamespace(
            content="Hello",
            usage=SimpleNamespace(prompt_tokens=10, total_tokens=20),
        )
        mock_client = MagicMock()
        mock_client.create_chat_completion.return_value = mock_result
        mock_client_cls.return_value = mock_client

        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "test-key",
                "DEEPSEEK_BASE_URL": "https://custom.api.example",
            },
            clear=True,
        ):
            main()

        init_kwargs = mock_client_cls.call_args
        self.assertEqual(
            init_kwargs.kwargs["base_url"], "https://custom.api.example"
        )


if __name__ == "__main__":
    unittest.main()
