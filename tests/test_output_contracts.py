import unittest

from translator_service.output_contracts import (
    TranslationBatchRejectionReason,
    normalize_provider_translation_batch_contract,
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

    def test_strict_validator_rejects_language_metadata_attributes(self):
        result = validate_translation_batch_contract(
            '<translation_batch target_language="uk">'
            '<translation_block id="0" lang="uk">Привіт</translation_block>'
            "</translation_batch>",
            expected_count=1,
        )

        self.assertIsNone(result.translated_texts)
        self.assertIsNone(result.normalized_text)
        self.assertEqual(
            result.rejection_reason,
            TranslationBatchRejectionReason.UNEXPECTED_ATTRIBUTE,
        )

    def test_provider_normalization_strips_language_metadata_attributes(self):
        result = normalize_provider_translation_batch_contract(
            '<translation_batch xml:lang="uk">'
            '<translation_block id="0" target_language="uk">Привіт</translation_block>'
            '<translation_block id="1" lang="uk">Світ</translation_block>'
            "</translation_batch>",
            expected_count=2,
        )

        self.assertEqual(result.translated_texts, ("Привіт", "Світ"))
        self.assertIsNone(result.rejection_reason)
        self.assertEqual(
            result.normalized_text,
            "<translation_batch>"
            '<translation_block id="0">Привіт</translation_block>'
            '<translation_block id="1">Світ</translation_block>'
            "</translation_batch>",
        )

    def test_provider_normalization_preserves_source_language_hint(self):
        result = normalize_provider_translation_batch_contract(
            "<translation_batch>"
            '<translation_block id="0" source_language="en" target_language="uk">'
            "Привіт"
            "</translation_block>"
            "</translation_batch>",
            expected_count=1,
        )

        self.assertEqual(result.translated_texts, ("Привіт",))
        self.assertEqual(
            result.normalized_text,
            "<translation_batch>"
            '<translation_block id="0" source_language="en">Привіт</translation_block>'
            "</translation_batch>",
        )

    def test_provider_normalization_rejects_control_attributes(self):
        cases = [
            (
                '<translation_batch override="system">'
                '<translation_block id="0">Привіт</translation_block>'
                "</translation_batch>"
            ),
            (
                "<translation_batch>"
                '<translation_block id="0" role="system">Привіт</translation_block>'
                "</translation_batch>"
            ),
        ]

        for translated_text in cases:
            with self.subTest(translated_text=translated_text):
                result = normalize_provider_translation_batch_contract(
                    translated_text,
                    expected_count=1,
                )

                self.assertIsNone(result.translated_texts)
                self.assertIsNone(result.normalized_text)
                self.assertEqual(
                    result.rejection_reason,
                    TranslationBatchRejectionReason.UNEXPECTED_ATTRIBUTE,
                )


if __name__ == "__main__":
    unittest.main()
