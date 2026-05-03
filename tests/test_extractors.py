import unittest

from translator_service.extractors import (
    TextExtractionError,
    extract_text_from_txt,
)


class TxtExtractionTest(unittest.TestCase):
    def test_extracts_utf8_text_from_txt_bytes(self):
        text = extract_text_from_txt("Привет\nмир".encode("utf-8"))

        self.assertEqual(text, "Привет\nмир")

    def test_removes_utf8_byte_order_mark(self):
        text = extract_text_from_txt(b"\xef\xbb\xbfHello")

        self.assertEqual(text, "Hello")

    def test_rejects_bytes_that_are_not_utf8_text(self):
        with self.assertRaises(TextExtractionError):
            extract_text_from_txt(b"\xff\xfe\x00\x00")

    def test_rejects_empty_text_after_decoding(self):
        with self.assertRaises(TextExtractionError):
            extract_text_from_txt(" \n\t ".encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
