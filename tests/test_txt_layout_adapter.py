import unittest

from translator_service.format_adapters.txt_layout import (
    TxtAssemblyPolicy,
    TxtSegmentKind,
    assemble_txt_document,
    parse_txt_document,
)


class TxtLayoutParserTest(unittest.TestCase):
    def test_parses_crlf_blank_lines_and_trailing_newline(self):
        document = parse_txt_document(b"Title\r\n\r\n  - First item\r\n")

        self.assertEqual(document.encoding, "utf-8")
        self.assertEqual(document.newline_style, "\r\n")
        self.assertFalse(document.has_bom)
        self.assertTrue(document.trailing_newline)
        self.assertEqual([segment.original_text for segment in document.segments], ["Title", "", "  - First item"])
        self.assertEqual(document.segments[0].kind, TxtSegmentKind.HEADING)
        self.assertEqual(document.segments[0].assembly_policy, TxtAssemblyPolicy.REPLACE)
        self.assertEqual(document.segments[1].kind, TxtSegmentKind.BLANK)
        self.assertEqual(document.segments[1].assembly_policy, TxtAssemblyPolicy.RAW)
        self.assertEqual(document.segments[2].kind, TxtSegmentKind.LIST)
        self.assertEqual(document.segments[2].assembly_policy, TxtAssemblyPolicy.PREFIXED_LINE)

    def test_records_utf8_bom_without_returning_bom_in_text(self):
        document = parse_txt_document(b"\xef\xbb\xbfHello\n")

        self.assertTrue(document.has_bom)
        self.assertEqual(document.segments[0].original_text, "Hello")

    def test_assemble_replays_untranslated_document_exactly(self):
        document = parse_txt_document(b"Title\r\n\r\n  - First item\r\n")

        assembled = assemble_txt_document(document, translated_by_segment_id={})

        self.assertEqual(assembled, "Title\r\n\r\n  - First item\r\n")

    def test_assemble_translated_only_stops_after_last_translated_segment(self):
        document = parse_txt_document(b"# Title\n\nBody text.\n")

        assembled = assemble_txt_document(
            document,
            translated_by_segment_id={document.segments[0].id: "Назва"},
            translated_only=True,
        )

        self.assertEqual(assembled, "# Назва")

    def test_assemble_replays_utf8_bom(self):
        document = parse_txt_document(b"\xef\xbb\xbfHello\n")

        assembled = assemble_txt_document(document, translated_by_segment_id={})

        self.assertEqual(assembled, "\ufeffHello\n")

    def test_classifies_headings_lists_fixed_width_and_config(self):
        document = parse_txt_document(
            "\n".join(
                [
                    "# Chapter One",
                    "  - Install dependencies",
                    "NAME      VALUE",
                    "timeout: 30",
                    "The room held its breath.",
                ]
            ).encode("utf-8")
        )

        self.assertEqual(
            [segment.kind for segment in document.segments],
            [
                TxtSegmentKind.HEADING,
                TxtSegmentKind.LIST,
                TxtSegmentKind.FIXED_WIDTH,
                TxtSegmentKind.CODE_CONFIG,
                TxtSegmentKind.PROSE,
            ],
        )
        self.assertEqual(document.segments[0].translatable_text, "Chapter One")
        self.assertEqual(document.segments[0].line_prefix, "# ")
        self.assertEqual(document.segments[1].translatable_text, "Install dependencies")
        self.assertEqual(document.segments[1].line_prefix, "  - ")
        self.assertFalse(document.segments[2].is_translatable)
        self.assertFalse(document.segments[3].is_translatable)

    def test_treats_fenced_code_block_as_raw(self):
        from translator_service.format_adapters.txt_layout import plan_txt_segments

        document = parse_txt_document(
            b'```python\nprint("Hello")\n```\nTranslate this.\n'
        )
        units = plan_txt_segments(document, max_fragment_chars=100)

        self.assertEqual(
            [segment.kind for segment in document.segments[:3]],
            [
                TxtSegmentKind.CODE_CONFIG,
                TxtSegmentKind.CODE_CONFIG,
                TxtSegmentKind.CODE_CONFIG,
            ],
        )
        self.assertEqual([unit.source_text for unit in units], ["Translate this."])

    def test_preserves_markdown_checkbox_marker_as_list_prefix(self):
        document = parse_txt_document(b"- [ ] Install dependencies\n- [x] Ship it\n")

        self.assertEqual(document.segments[0].kind, TxtSegmentKind.LIST)
        self.assertEqual(document.segments[0].line_prefix, "- [ ] ")
        self.assertEqual(document.segments[0].translatable_text, "Install dependencies")
        self.assertEqual(document.segments[1].line_prefix, "- [x] ")
        assembled = assemble_txt_document(
            document,
            translated_by_segment_id={
                document.segments[0].id: "Установить зависимости",
                document.segments[1].id: "Отправить",
            },
        )
        self.assertEqual(assembled, "- [ ] Установить зависимости\n- [x] Отправить\n")

    def test_keeps_ordinary_prose_translatable(self):
        document = parse_txt_document(
            "\n".join(
                [
                    "Note: translate this sentence",
                    "Chapter 1: Arrival",
                    "Use https://example.com for help",
                    "I can help you today",
                    "This  has two spaces",
                    "This  has  two spaces",
                    "title: Arrival",
                    "note: yes",
                    "chapter: arrival",
                ]
            ).encode("utf-8")
        )

        for segment in document.segments:
            self.assertEqual(segment.kind, TxtSegmentKind.PROSE)
            self.assertTrue(segment.is_translatable)

    def test_assembles_prefixed_segments_without_losing_markers(self):
        document = parse_txt_document(b"# Chapter One\n  - Install dependencies\n")

        assembled = assemble_txt_document(
            document,
            translated_by_segment_id={
                document.segments[0].id: "Глава первая",
                document.segments[1].id: "Установите зависимости",
            },
        )

        self.assertEqual(assembled, "# Глава первая\n  - Установите зависимости\n")

    def test_plans_only_translatable_segments(self):
        from translator_service.format_adapters.txt_layout import plan_txt_segments

        document = parse_txt_document(b"# Chapter\n\nKEY=value\n- First item\nBody text.")
        units = plan_txt_segments(document, max_fragment_chars=100)

        self.assertEqual(document.segments[2].kind, TxtSegmentKind.CODE_CONFIG)
        self.assertFalse(document.segments[2].is_translatable)
        self.assertEqual(len(units), 3)
        self.assertEqual(
            [unit.blocks[0].text for unit in units],
            ["Chapter", "First item", "Body text."],
        )
        self.assertEqual(
            [unit.source_block_ids[0] for unit in units],
            ["txt:segment:1", "txt:segment:4", "txt:segment:5"],
        )

    def test_plans_one_unit_per_translatable_segment_even_when_over_fragment_limit(self):
        from translator_service.format_adapters.txt_layout import plan_txt_segments

        document = parse_txt_document(b"This is one deliberately long line.")
        units = plan_txt_segments(document, max_fragment_chars=5)

        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].source_text, "This is one deliberately long line.")
