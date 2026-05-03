import unittest

from translator_service.deepseek_probe import build_probe_result_message


class DeepSeekProbeTest(unittest.TestCase):
    def test_builds_probe_result_message_without_leaking_secret(self):
        message = build_probe_result_message("Hello", prompt_tokens=12, total_tokens=15)

        self.assertIn("DeepSeek API ответил", message)
        self.assertIn("Hello", message)
        self.assertIn("15", message)
        self.assertNotIn("sk-", message)


if __name__ == "__main__":
    unittest.main()
