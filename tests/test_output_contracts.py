import unittest

from translator_service.output_contracts import (
    TranslationBatchRejectionReason,
    parse_translation_batch_contract,
    validate_translation_batch_contract,
)


class OutputContractsTest(unittest.TestCase):
    def test_parses_valid_translation_batch_with_expected_ids(self):
        parsed = parse_translation_batch_contract(
            "<translation_batch>"
            '<translation_block id="0">First</translation_block>'
            '<translation_block id="1">Second</translation_block>'
            "</translation_batch>",
            expected_count=2,
        )

        self.assertEqual(parsed, ("First", "Second"))

    def test_rejects_text_outside_translation_batch_root(self):
        result = validate_translation_batch_contract(
            "Here is the translation:\n"
            "<translation_batch>"
            '<translation_block id="0">First</translation_block>'
            "</translation_batch>",
            expected_count=1,
        )

        self.assertIsNone(result.translated_texts)
        self.assertEqual(
            result.rejection_reason,
            TranslationBatchRejectionReason.EXTERNAL_TEXT,
        )

    def test_rejects_duplicate_or_reordered_block_ids(self):
        result = validate_translation_batch_contract(
            "<translation_batch>"
            '<translation_block id="0">First</translation_block>'
            '<translation_block id="0">Duplicate</translation_block>'
            "</translation_batch>",
            expected_count=2,
        )

        self.assertIsNone(result.translated_texts)
        self.assertEqual(
            result.rejection_reason,
            TranslationBatchRejectionReason.WRONG_BLOCK_ID,
        )

    def test_rejects_missing_required_protected_marker(self):
        result = validate_translation_batch_contract(
            "<translation_batch>"
            '<translation_block id="0">The URL is gone.</translation_block>'
            "</translation_batch>",
            expected_count=1,
            required_markers=(("ZXQPROTECTED0QXZ",),),
        )

        self.assertIsNone(result.translated_texts)
        self.assertEqual(
            result.rejection_reason,
            TranslationBatchRejectionReason.MISSING_PROTECTED_MARKER,
        )

    def test_rejects_refusal_inside_translation_block(self):
        result = validate_translation_batch_contract(
            "<translation_batch>"
            '<translation_block id="0">Извините, я не могу выполнить этот запрос.</translation_block>'
            "</translation_batch>",
            expected_count=1,
        )

        self.assertIsNone(result.translated_texts)
        self.assertEqual(
            result.rejection_reason,
            TranslationBatchRejectionReason.UNSAFE_MODEL_OUTPUT,
        )

    def test_parse_wrapper_keeps_legacy_none_result(self):
        parsed = parse_translation_batch_contract(
            "Here is the translation:\n"
            "<translation_batch>"
            '<translation_block id="0">First</translation_block>'
            "</translation_batch>",
            expected_count=1,
        )

        self.assertIsNone(parsed)


if __name__ == "__main__":
    unittest.main()
