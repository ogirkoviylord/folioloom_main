import unittest

from translator_service.book_mode_output_audit import (
    BookModeAuditChunk,
    BookModeAuditFinding,
    audit_book_mode_output,
)


class BookModeOutputAuditTest(unittest.TestCase):
    def test_reports_mixed_english_residue_for_russian_book_output(self):
        result = audit_book_mode_output(
            chunks=(
                BookModeAuditChunk(
                    block_id="epub:OPS/chapter.xhtml:1",
                    block_kind="plain",
                    translated_text=(
                        "Комната затихла, but he had reliable information that "
                        "Mussolini had died of a serious disease."
                    ),
                ),
            ),
            target_language="ru",
            expected_latin_terms=("Mussolini",),
        )

        self.assertEqual(
            [finding.code for finding in result.findings],
            ["untranslated_source_residue"],
        )
        self.assertFalse(result.passed)
        self.assertNotIn("Комната затихла", repr(result))
        self.assertNotIn("serious disease", repr(result))

    def test_reports_mixed_english_residue_for_ukrainian_book_output(self):
        result = audit_book_mode_output(
            chunks=(
                BookModeAuditChunk(
                    block_id="epub:OPS/chapter.xhtml:2",
                    block_kind="plain",
                    translated_text=(
                        "Кімната стихла, but she could not remember where "
                        "Virginia had hidden the letter."
                    ),
                ),
            ),
            target_language="uk",
            expected_latin_terms=("Virginia",),
        )

        self.assertEqual(
            [finding.code for finding in result.findings],
            ["untranslated_source_residue"],
        )
        self.assertNotIn("Кімната стихла", repr(result))
        self.assertNotIn("hidden the letter", repr(result))

    def test_reports_english_navigation_heading_residue_for_cyrillic_target(self):
        result = audit_book_mode_output(
            chunks=(
                BookModeAuditChunk(
                    block_id="epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0",
                    translated_text="Chapter One",
                    metadata=(("epub_aux_kind", "xhtml_navigation"),),
                ),
                BookModeAuditChunk(
                    block_id="docx:word/document.xml:7",
                    block_kind="heading",
                    translated_text="The Night Falls",
                ),
            ),
            target_language="uk-UA",
        )

        self.assertEqual(
            [finding.code for finding in result.findings],
            [
                "english_navigation_heading_residue",
                "english_navigation_heading_residue",
            ],
        )
        self.assertTrue(
            all(finding.category == "navigation_heading" for finding in result.findings)
        )

    def test_reports_navigation_labels_with_numbers_for_cyrillic_target(self):
        result = audit_book_mode_output(
            chunks=(
                BookModeAuditChunk(
                    block_id="epub:surface-xhtml-navigation:OPS/nav.xhtml:a:0",
                    translated_text="Chapter 1",
                    block_kind="navigation",
                ),
                BookModeAuditChunk(
                    block_id="epub:surface-ncx:OPS/toc.ncx:text:1",
                    translated_text="Book I",
                    block_kind="navigation",
                ),
            ),
            target_language="ru",
        )

        self.assertEqual(
            [finding.code for finding in result.findings],
            [
                "english_navigation_heading_residue",
                "english_navigation_heading_residue",
            ],
        )

    def test_reports_provider_commentary_wrapper_without_raw_text(self):
        result = audit_book_mode_output(
            chunks=(
                BookModeAuditChunk(
                    block_id="txt:segment:1",
                    block_kind="plain",
                    translated_text=(
                        "Here is the translation: Кімната затамувала подих."
                    ),
                ),
            ),
            target_language="uk",
        )

        self.assertEqual(
            [finding.code for finding in result.findings],
            ["provider_commentary_wrapper"],
        )
        self.assertNotIn("Кімната", repr(result.findings[0]))
        self.assertNotIn("Here is the translation", repr(result.findings[0]))

    def test_reports_suspicious_all_english_chunks_for_russian_output(self):
        result = audit_book_mode_output(
            chunks=(
                BookModeAuditChunk(
                    block_id="epub:OPS/chapter.xhtml:4",
                    block_kind="plain",
                    translated_text="The room held its breath in silence.",
                ),
            ),
            target_language="ru",
        )

        self.assertEqual(
            [finding.code for finding in result.findings],
            ["suspicious_all_english_chunk"],
        )

    def test_allows_safe_latin_spans_without_false_failures(self):
        result = audit_book_mode_output(
            chunks=(
                BookModeAuditChunk(
                    block_id="txt:segment:2",
                    block_kind="plain",
                    translated_text=(
                        "https://example.com/v1/items ORD-2026-05 API_TOKEN "
                        "ZXQPROTECTED0QXZ `print(\"Hello World\")` "
                        "Winston Churchill and OpenAI."
                    ),
                ),
            ),
            target_language="ru",
            expected_latin_terms=("Winston Churchill", "OpenAI"),
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.findings, ())

    def test_reports_language_metadata_mismatch_without_text_payload(self):
        result = audit_book_mode_output(
            chunks=(
                BookModeAuditChunk(
                    block_id="epub:aux:opf:OPS/content.opf:dc:title:0",
                    block_kind="plain",
                    translated_text="Назва книги",
                    metadata=(("xml:lang", "en-US"),),
                ),
            ),
            target_language="ru",
        )

        self.assertEqual(
            [finding.code for finding in result.findings],
            ["language_metadata_mismatch"],
        )
        self.assertEqual(
            result.findings[0].details,
            (
                ("language_key", "xml:lang"),
                ("observed_language_root", "en"),
                ("expected_language_root", "ru"),
            ),
        )
        self.assertNotIn("Назва книги", repr(result))

    def test_skips_cyrillic_audit_for_non_cyrillic_targets(self):
        result = audit_book_mode_output(
            chunks=(
                BookModeAuditChunk(
                    block_id="txt:segment:3",
                    block_kind="plain",
                    translated_text="The room held its breath in silence.",
                ),
            ),
            target_language="de",
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.findings, ())

    def test_finding_objects_are_stable_metadata_only_value_objects(self):
        finding = BookModeAuditFinding(
            code="suspicious_all_english_chunk",
            message="Metadata-only finding.",
            target_language="ru",
            chunk_id="txt:segment:4",
            chunk_kind="plain",
            category="language_mix",
            latin_word_count=7,
            cyrillic_word_count=0,
            protected_marker_count=1,
        )

        self.assertEqual(finding.code, "suspicious_all_english_chunk")
        self.assertEqual(finding.target_language, "ru")
        self.assertEqual(finding.protected_marker_count, 1)


if __name__ == "__main__":
    unittest.main()
