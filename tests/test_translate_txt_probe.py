import unittest

from translator_service.translate_txt_probe import build_success_message


class TranslateTxtProbeTest(unittest.TestCase):
    def test_builds_success_message_with_file_and_fragment_count(self):
        message = build_success_message(file_name="sample.en.txt", fragment_count=2)

        self.assertIn("sample.en.txt", message)
        self.assertIn("2", message)
        self.assertIn("готов", message.lower())


if __name__ == "__main__":
    unittest.main()
