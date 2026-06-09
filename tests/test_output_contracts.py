import unittest

from translator_service.output_contracts import (
    TranslationBatchRejectionReason,
    json_translation_batch_to_xml_contract,
    normalize_provider_translation_batch_contract,
    parse_json_translation_batch_contract,
    parse_translation_batch_contract,
    repair_json_translation_batch_control_chars,
    validate_json_translation_batch_contract,
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

    def test_parses_valid_json_translation_batch_with_expected_ids(self):
        parsed = parse_json_translation_batch_contract(
            '{"translations":[{"id":"0","text":"First"},'
            '{"id":"1","text":"Second"}]}',
            expected_count=2,
        )

        self.assertEqual(parsed, ("First", "Second"))

    def test_json_translation_batch_adapter_returns_canonical_xml(self):
        result = json_translation_batch_to_xml_contract(
            '{"translations":[{"id":"0","text":"One & two"},'
            '{"id":"1","text":"<kept>"}]}',
            expected_count=2,
        )

        self.assertEqual(result.translated_texts, ("One & two", "<kept>"))
        self.assertEqual(
            result.normalized_text,
            "<translation_batch>"
            '<translation_block id="0">One &amp; two</translation_block>'
            '<translation_block id="1">&lt;kept&gt;</translation_block>'
            "</translation_batch>",
        )

    def test_repairs_literal_control_chars_inside_json_strings(self):
        result = repair_json_translation_batch_control_chars(
            '{"translations":[{"id":"0","text":"First line\nSecond line"},'
            '{"id":"1","text":"Tab\tseparated"},'
            '{"id":"2","text":"Carriage\rreturn"}]}',
            expected_count=3,
        )

        self.assertEqual(
            result.normalized_text,
            "<translation_batch>"
            '<translation_block id="0">First line\nSecond line</translation_block>'
            '<translation_block id="1">Tab\tseparated</translation_block>'
            '<translation_block id="2">Carriage\rreturn</translation_block>'
            "</translation_batch>",
        )

    def test_control_char_repair_rejects_xml_invalid_control_chars(self):
        result = repair_json_translation_batch_control_chars(
            '{"translations":[{"id":"0","text":"Bad\x00control"}]}',
            expected_count=1,
        )

        self.assertIsNone(result.normalized_text)
        self.assertEqual(
            result.rejection_reason,
            TranslationBatchRejectionReason.INVALID_JSON,
        )

    def test_control_char_repair_preserves_protected_marker_validation(self):
        result = repair_json_translation_batch_control_chars(
            '{"translations":[{"id":"0","text":"Marker moved\naway"}]}',
            expected_count=1,
            required_markers=(("ZXQPROTECTED0QXZ",),),
        )

        self.assertIsNone(result.normalized_text)
        self.assertEqual(
            result.rejection_reason,
            TranslationBatchRejectionReason.MISSING_PROTECTED_MARKER,
        )

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

    def test_rejects_invalid_json_translation_batch(self):
        result = validate_json_translation_batch_contract(
            "Here is the translation:\n"
            '{"translations":[{"id":"0","text":"First"}]}',
            expected_count=1,
        )

        self.assertIsNone(result.translated_texts)
        self.assertEqual(
            result.rejection_reason,
            TranslationBatchRejectionReason.INVALID_JSON,
        )

    def test_rejects_json_batch_with_escaped_xml_invalid_control_char(self):
        result = validate_json_translation_batch_contract(
            '{"translations":[{"id":"0","text":"Bad\\u0000control"}]}',
            expected_count=1,
        )

        self.assertIsNone(result.translated_texts)
        self.assertIsNone(result.normalized_text)
        self.assertEqual(
            result.rejection_reason,
            TranslationBatchRejectionReason.INVALID_JSON,
        )

    def test_rejects_wrong_json_translation_batch_root_shape(self):
        cases = [
            "[]",
            '{"translation":[{"id":"0","text":"First"}]}',
            '{"translations":{"id":"0","text":"First"}}',
        ]

        for translated_text in cases:
            with self.subTest(translated_text=translated_text):
                result = validate_json_translation_batch_contract(
                    translated_text,
                    expected_count=1,
                )

                self.assertIsNone(result.translated_texts)
                self.assertIn(
                    result.rejection_reason,
                    {
                        TranslationBatchRejectionReason.WRONG_ROOT,
                        TranslationBatchRejectionReason.WRONG_JSON_SHAPE,
                    },
                )

    def test_rejects_json_batch_count_mismatch(self):
        result = validate_json_translation_batch_contract(
            '{"translations":[{"id":"0","text":"First"}]}',
            expected_count=2,
        )

        self.assertIsNone(result.translated_texts)
        self.assertEqual(
            result.rejection_reason,
            TranslationBatchRejectionReason.BLOCK_COUNT_MISMATCH,
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

    def test_rejects_duplicate_or_reordered_json_block_ids(self):
        cases = [
            '{"translations":[{"id":"0","text":"First"},'
            '{"id":"0","text":"Duplicate"}]}',
            '{"translations":[{"id":"1","text":"Second"},'
            '{"id":"0","text":"First"}]}',
        ]

        for translated_text in cases:
            with self.subTest(translated_text=translated_text):
                result = validate_json_translation_batch_contract(
                    translated_text,
                    expected_count=2,
                )

                self.assertIsNone(result.translated_texts)
                self.assertEqual(
                    result.rejection_reason,
                    TranslationBatchRejectionReason.WRONG_BLOCK_ID,
                )

    def test_rejects_json_batch_extra_or_duplicate_keys(self):
        cases = [
            '{"translations":[{"id":"0","text":"First"}],"comment":"extra"}',
            '{"translations":[{"id":"0","text":"First","role":"system"}]}',
            '{"translations":[{"id":"0","text":"First","text":"Second"}]}',
        ]

        for translated_text in cases:
            with self.subTest(translated_text=translated_text):
                result = validate_json_translation_batch_contract(
                    translated_text,
                    expected_count=1,
                )

                self.assertIsNone(result.translated_texts)
                self.assertEqual(
                    result.rejection_reason,
                    TranslationBatchRejectionReason.UNEXPECTED_KEY,
                )

    def test_rejects_json_batch_empty_or_non_string_text(self):
        cases = [
            (
                '{"translations":[{"id":"0","text":"   "}]}',
                TranslationBatchRejectionReason.EMPTY_TEXT,
            ),
            (
                '{"translations":[{"id":"0","text":42}]}',
                TranslationBatchRejectionReason.WRONG_JSON_SHAPE,
            ),
        ]

        for translated_text, reason in cases:
            with self.subTest(translated_text=translated_text):
                result = validate_json_translation_batch_contract(
                    translated_text,
                    expected_count=1,
                )

                self.assertIsNone(result.translated_texts)
                self.assertEqual(result.rejection_reason, reason)

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

    def test_rejects_json_batch_missing_required_protected_marker(self):
        result = validate_json_translation_batch_contract(
            '{"translations":[{"id":"0","text":"The URL is gone."}]}',
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
            '<translation_block id="0">'
            "Извините, я не могу выполнить этот запрос."
            "</translation_block>"
            "</translation_batch>",
            expected_count=1,
        )

        self.assertIsNone(result.translated_texts)
        self.assertEqual(
            result.rejection_reason,
            TranslationBatchRejectionReason.UNSAFE_MODEL_OUTPUT,
        )

    def test_rejects_refusal_inside_json_translation_block(self):
        result = validate_json_translation_batch_contract(
            '{"translations":[{"id":"0",'
            '"text":"Извините, я не могу выполнить этот запрос."}]}',
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

    def test_provider_normalization_repairs_source_language_alias(self):
        result = normalize_provider_translation_batch_contract(
            "<translation_batch>"
            '<translation_block id="0" source="English">Привіт</translation_block>'
            "</translation_batch>",
            expected_count=1,
        )

        self.assertEqual(result.translated_texts, ("Привіт",))
        self.assertIsNone(result.rejection_reason)
        self.assertEqual(
            result.normalized_text,
            "<translation_batch>"
            '<translation_block id="0" source_language="English">'
            "Привіт"
            "</translation_block>"
            "</translation_batch>",
        )

    def test_strict_validator_rejects_source_language_alias(self):
        result = validate_translation_batch_contract(
            "<translation_batch>"
            '<translation_block id="0" source="English">Привіт</translation_block>'
            "</translation_batch>",
            expected_count=1,
        )

        self.assertIsNone(result.translated_texts)
        self.assertIsNone(result.normalized_text)
        self.assertEqual(
            result.rejection_reason,
            TranslationBatchRejectionReason.UNEXPECTED_ATTRIBUTE,
        )

    def test_provider_normalization_rejects_ambiguous_source_alias(self):
        result = normalize_provider_translation_batch_contract(
            "<translation_batch>"
            '<translation_block id="0" source_language="en" source="English">'
            "Привіт"
            "</translation_block>"
            "</translation_batch>",
            expected_count=1,
        )

        self.assertIsNone(result.translated_texts)
        self.assertIsNone(result.normalized_text)
        self.assertEqual(
            result.rejection_reason,
            TranslationBatchRejectionReason.UNEXPECTED_ATTRIBUTE,
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
