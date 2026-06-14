import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from translator_service.translate_txt_probe import build_success_message, main


class TranslateTxtProbeTest(unittest.TestCase):
    def test_builds_success_message_with_file_and_fragment_count(self):
        message = build_success_message(file_name="sample.en.txt", fragment_count=2)

        self.assertIn("sample.en.txt", message)
        self.assertIn("2", message)
        self.assertIn("готов", message.lower())


class TranslateTxtProbeMainTest(unittest.TestCase):
    def test_main_raises_when_api_key_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                main()

    @patch("translator_service.translate_txt_probe.DeepSeekClient")
    @patch("translator_service.translate_txt_probe.translate_txt_document")
    def test_main_translates_and_writes_output(
        self, mock_translate, mock_client_cls
    ):
        mock_translate.return_value = SimpleNamespace(
            file_name="sample.en.txt",
            content=b"Hello translated",
            fragment_count=1,
        )
        mock_client_cls.return_value = MagicMock()

        with patch.dict(
            os.environ,
            {"DEEPSEEK_API_KEY": "test-key"},
            clear=True,
        ):
            with patch("sys.argv", ["prog"]):
                with patch("builtins.open", unittest.mock.mock_open()):
                    main()

        mock_client_cls.assert_called_once()
        mock_translate.assert_called_once()
        call_kwargs = mock_translate.call_args
        self.assertEqual(call_kwargs.kwargs["file_name"], "sample.txt")
        self.assertEqual(call_kwargs.kwargs["source_language"], "ru")
        self.assertEqual(call_kwargs.kwargs["target_language"], "en")

    @patch("translator_service.translate_txt_probe.DeepSeekClient")
    @patch("translator_service.translate_txt_probe.translate_txt_document")
    def test_main_uses_argv_text(self, mock_translate, mock_client_cls):
        mock_translate.return_value = SimpleNamespace(
            file_name="sample.en.txt",
            content=b"Translated",
            fragment_count=1,
        )
        mock_client_cls.return_value = MagicMock()

        with patch.dict(
            os.environ,
            {"DEEPSEEK_API_KEY": "test-key"},
            clear=True,
        ):
            with patch("sys.argv", ["prog", "Custom", "text"]):
                with patch("builtins.open", unittest.mock.mock_open()):
                    main()

        call_kwargs = mock_translate.call_args
        self.assertEqual(
            call_kwargs.kwargs["content"],
            b"Custom text",
        )


if __name__ == "__main__":
    unittest.main()
