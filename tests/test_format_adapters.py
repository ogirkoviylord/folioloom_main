import unittest
from pathlib import Path

from translator_service.documents import DocumentFormat
from translator_service.extractors import TextExtractionError, extract_text_from_epub
from translator_service.format_adapters import (
    DOCX_ADAPTER_VERSION,
    DOCX_TRANSLATION_MODE_BOOK_MANUSCRIPT_PROFILE,
    DOCX_TRANSLATION_MODE_DOCUMENT_FORM_PROFILE,
    EPUB_ADAPTER_VERSION,
    TRANSLATION_MODE_BOOK_MANUSCRIPT,
    TRANSLATION_MODE_DOCUMENT_FORM,
    TXT_ADAPTER_VERSION,
    assemble_epub_content_from_block_translations,
    epub_aux_block_id,
    epub_body_block_id,
    extract_epub_book_mode_audit_chunks,
    plan_docx_translation,
    plan_epub_translation,
    plan_txt_translation,
)
from translator_service.format_adapters.epub import (
    _is_epub_gutenberg_legal_backmatter_text,
)
from translator_service.structure_optimizer import PromptTier, TextBlockKind


class TxtFormatAdapterTest(unittest.TestCase):
    def test_plans_txt_fragments_with_stable_order_and_block_ids(self):
        plan = plan_txt_translation(
            content=b"# Title\n\nKEY=value\n- First item\nBody text.",
            max_fragment_chars=100,
        )

        self.assertEqual(plan.document_format, DocumentFormat.TXT)
        self.assertEqual(plan.adapter_version, TXT_ADAPTER_VERSION)
        self.assertEqual(plan.fragment_count, 3)
        self.assertEqual(plan.character_count, len("Title\n\nFirst item\n\nBody text."))
        self.assertEqual(plan.estimated_input_tokens, 148)
        self.assertEqual([unit.sequence for unit in plan.units], [1, 2, 3])
        self.assertEqual(
            [unit.blocks[0].text for unit in plan.units],
            ["Title", "First item", "Body text."],
        )
        self.assertEqual(
            [unit.source_block_ids for unit in plan.units],
            [("txt:segment:1",), ("txt:segment:4",), ("txt:segment:5",)],
        )
        self.assertEqual(plan.units[0].blocks[0].metadata[0], ("txt_kind", "heading"))
        self.assertEqual(plan.units[1].blocks[0].metadata[0], ("txt_kind", "list"))
        self.assertEqual(plan.units[2].blocks[0].metadata[0], ("txt_kind", "prose"))
        self.assertFalse(
            any(
                key.startswith("content_role.")
                for unit in plan.units
                for block in unit.blocks
                for key, _ in block.metadata
            )
        )

    def test_rejects_raw_only_non_empty_txt(self):
        with self.assertRaisesRegex(
            TextExtractionError,
            "TXT file does not contain translatable text",
        ):
            plan_txt_translation(
                content=b"timeout: 30\nKEY=value",
                max_fragment_chars=100,
            )

    def test_rejects_txt_without_translatable_text(self):
        with self.assertRaises(TextExtractionError):
            plan_txt_translation(
                content=b" \n\n ",
                max_fragment_chars=100,
            )


class DocxFormatAdapterTest(unittest.TestCase):
    def test_docx_adapter_does_not_import_private_translation_runner_helpers(self):
        adapter_source = Path(
            "src/translator_service/format_adapters/docx.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn(
            "from translator_service.translation_runner import _",
            adapter_source,
        )
        self.assertNotRegex(
            adapter_source,
            r"from\s+translator_service\.translation_runner\s+import\s+\(?\s*_",
        )

    def test_plans_docx_blocks_with_stable_order_and_block_ids(self):
        plan = plan_docx_translation(
            content=_make_docx(
                """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body>
                    <w:p><w:r><w:t>First paragraph</w:t></w:r></w:p>
                    <w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>
                  </w:body>
                </w:document>
                """
            ),
            max_fragment_chars=100,
        )

        self.assertEqual(plan.document_format, DocumentFormat.DOCX)
        self.assertEqual(plan.adapter_version, DOCX_ADAPTER_VERSION)
        self.assertEqual(plan.fragment_count, 1)
        self.assertEqual(
            plan.character_count,
            len("First paragraph\n\nSecond paragraph"),
        )
        self.assertEqual(plan.estimated_input_tokens, 38)
        self.assertEqual([unit.sequence for unit in plan.units], [1])
        self.assertEqual(plan.units[0].prompt_tier, PromptTier.PLAIN)
        self.assertEqual(
            plan.units[0].source_block_ids,
            ("docx:word/document.xml:0", "docx:word/document.xml:1"),
        )
        self.assertEqual(
            [block.text for block in plan.units[0].blocks],
            ["First paragraph", "Second paragraph"],
        )
        self.assertFalse(
            any(
                key.startswith("content_role.")
                for unit in plan.units
                for block in unit.blocks
                for key, _ in block.metadata
            )
        )

    def test_plans_docx_table_as_strict_unit_between_plain_units(self):
        plan = plan_docx_translation(
            content=_make_docx(
                """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body>
                    <w:p><w:r><w:t>Intro paragraph.</w:t></w:r></w:p>
                    <w:tbl>
                      <w:tr>
                        <w:tc><w:p><w:r><w:t>Source</w:t></w:r></w:p></w:tc>
                        <w:tc><w:p><w:r><w:t>Target</w:t></w:r></w:p></w:tc>
                      </w:tr>
                    </w:tbl>
                    <w:p><w:r><w:t>Outro paragraph.</w:t></w:r></w:p>
                  </w:body>
                </w:document>
                """
            ),
            max_fragment_chars=1_000,
        )

        self.assertEqual(plan.fragment_count, 3)
        self.assertEqual(
            [unit.prompt_tier for unit in plan.units],
            [PromptTier.PLAIN, PromptTier.STRICT, PromptTier.PLAIN],
        )
        self.assertEqual(
            [block.kind for block in plan.units[1].blocks],
            [TextBlockKind.TABLE, TextBlockKind.TABLE],
        )

    def test_plans_docx_document_form_mode_as_strict_structure_route(self):
        plan = plan_docx_translation(
            content=_make_docx(
                """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body>
                    <w:p><w:r><w:t>Заява</w:t></w:r></w:p>
                    <w:p><w:r><w:t>Адреса: Київ</w:t></w:r></w:p>
                    <w:p><w:r><w:t>Дата: 16.05.2026</w:t></w:r></w:p>
                    <w:p><w:r><w:t>Підпис: __________</w:t></w:r></w:p>
                  </w:body>
                </w:document>
                """
            ),
            max_fragment_chars=1_000,
            translation_mode=TRANSLATION_MODE_DOCUMENT_FORM,
        )

        self.assertEqual(plan.fragment_count, 1)
        self.assertEqual(plan.units[0].prompt_tier, PromptTier.STRICT)
        self.assertEqual(
            dict(plan.units[0].blocks[0].metadata)["translation_mode"],
            TRANSLATION_MODE_DOCUMENT_FORM,
        )
        self.assertEqual(
            dict(plan.units[0].blocks[0].metadata)[
                "docx_translation_mode_profile"
            ],
            DOCX_TRANSLATION_MODE_DOCUMENT_FORM_PROFILE,
        )

    def test_plans_docx_book_manuscript_mode_with_existing_prose_route(self):
        plan = plan_docx_translation(
            content=_make_docx(
                """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body>
                    <w:p><w:r><w:t>Quiet chapter opening.</w:t></w:r></w:p>
                    <w:p><w:r><w:t>The same voice continued.</w:t></w:r></w:p>
                  </w:body>
                </w:document>
                """
            ),
            max_fragment_chars=1_000,
            translation_mode=TRANSLATION_MODE_BOOK_MANUSCRIPT,
        )

        self.assertEqual(plan.fragment_count, 1)
        self.assertEqual(plan.units[0].prompt_tier, PromptTier.PLAIN)
        self.assertEqual(
            dict(plan.units[0].blocks[0].metadata)["translation_mode"],
            TRANSLATION_MODE_BOOK_MANUSCRIPT,
        )
        self.assertEqual(
            dict(plan.units[0].blocks[0].metadata)[
                "docx_translation_mode_profile"
            ],
            DOCX_TRANSLATION_MODE_BOOK_MANUSCRIPT_PROFILE,
        )

    def test_rejects_unknown_docx_translation_mode(self):
        with self.assertRaisesRegex(ValueError, "Unsupported DOCX translation mode"):
            plan_docx_translation(
                content=_make_docx(
                    """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body>
                        <w:p><w:r><w:t>Text</w:t></w:r></w:p>
                      </w:body>
                    </w:document>
                    """
                ),
                max_fragment_chars=1_000,
                translation_mode="spreadsheet",
            )


class EpubFormatAdapterTest(unittest.TestCase):
    _EXPECTED_NCX_TEXT_CONTENT_ROLE_METADATA = {
        "content_role.schema_version": "content-role-annotation-v1",
        "content_role.source_surface": "epub_ncx_nav",
        "content_role.source_granularity": "block",
        "content_role.role": "reader_navigation",
        "content_role.confidence": "medium",
        "content_role.reporting_bucket": "reader_visible",
        "content_role.allowed_action_envelope": (
            "shadow_report_translate_include"
        ),
        "content_role.behavior_allowed": "false",
        "content_role.raw_publication_allowed": "false",
        "content_role.risk_approval_flags": "all_false",
        "content_role.evidence_signal_families": (
            "path_class_id,structural_semantic"
        ),
        "content_role.evidence_reason_codes": (
            "epub_ncx_text_auxiliary_block,ncx_text_aux_kind"
        ),
    }
    _EXPECTED_XHTML_NAVIGATION_CONTENT_ROLE_METADATA = {
        "content_role.schema_version": "content-role-annotation-v1",
        "content_role.source_surface": "epub_xhtml_nav",
        "content_role.source_granularity": "block",
        "content_role.role": "reader_navigation",
        "content_role.confidence": "high",
        "content_role.reporting_bucket": "reader_visible",
        "content_role.allowed_action_envelope": (
            "shadow_report_translate_include"
        ),
        "content_role.behavior_allowed": "false",
        "content_role.raw_publication_allowed": "false",
        "content_role.risk_approval_flags": "all_false",
        "content_role.evidence_signal_families": (
            "path_class_id,structural_semantic"
        ),
        "content_role.evidence_reason_codes": (
            "epub_xhtml_navigation_auxiliary_block,xhtml_navigation_aux_kind"
        ),
    }
    _EXPECTED_XHTML_TITLE_CONTENT_ROLE_METADATA = {
        "content_role.schema_version": "content-role-annotation-v1",
        "content_role.source_surface": "epub_xhtml_title",
        "content_role.source_granularity": "block",
        "content_role.role": "title_heading",
        "content_role.confidence": "medium",
        "content_role.reporting_bucket": "reader_visible",
        "content_role.allowed_action_envelope": (
            "shadow_report_translate_include"
        ),
        "content_role.behavior_allowed": "false",
        "content_role.raw_publication_allowed": "false",
        "content_role.risk_approval_flags": "all_false",
        "content_role.evidence_signal_families": (
            "path_class_id,structural_semantic"
        ),
        "content_role.evidence_reason_codes": (
            "epub_xhtml_title_auxiliary_block,xhtml_title_aux_kind"
        ),
    }
    _EXPECTED_OPF_TITLE_CONTENT_ROLE_METADATA = {
        "content_role.schema_version": "content-role-annotation-v1",
        "content_role.source_surface": "epub_opf_metadata",
        "content_role.source_granularity": "block",
        "content_role.role": "title_heading",
        "content_role.confidence": "medium",
        "content_role.reporting_bucket": "reader_visible",
        "content_role.allowed_action_envelope": (
            "shadow_report_translate_include"
        ),
        "content_role.behavior_allowed": "false",
        "content_role.raw_publication_allowed": "false",
        "content_role.risk_approval_flags": "all_false",
        "content_role.evidence_signal_families": (
            "path_class_id,structural_semantic"
        ),
        "content_role.evidence_reason_codes": (
            "epub_opf_title_auxiliary_block,opf_title_aux_kind"
        ),
    }
    _EXPECTED_OPF_DESCRIPTION_CONTENT_ROLE_METADATA = {
        "content_role.schema_version": "content-role-annotation-v1",
        "content_role.source_surface": "epub_opf_metadata",
        "content_role.source_granularity": "block",
        "content_role.role": "publisher_metadata",
        "content_role.confidence": "medium",
        "content_role.reporting_bucket": "publisher_metadata_shadow",
        "content_role.allowed_action_envelope": (
            "shadow_report_translate_include"
        ),
        "content_role.behavior_allowed": "false",
        "content_role.raw_publication_allowed": "false",
        "content_role.risk_approval_flags": "all_false",
        "content_role.evidence_signal_families": (
            "path_class_id,structural_semantic"
        ),
        "content_role.evidence_reason_codes": (
            "epub_opf_description_auxiliary_block,opf_description_aux_kind"
        ),
    }

    def _assert_xhtml_navigation_content_role_metadata(self, blocks):
        for block in blocks:
            with self.subTest(source_block_id=block.source_block_id):
                metadata = dict(block.metadata)
                self.assertEqual(metadata["epub_aux_kind"], "xhtml_navigation")
                self.assertEqual(
                    {
                        key: value
                        for key, value in metadata.items()
                        if key.startswith("content_role.")
                    },
                    self._EXPECTED_XHTML_NAVIGATION_CONTENT_ROLE_METADATA,
                )

    def _assert_xhtml_title_content_role_metadata(self, blocks):
        for block in blocks:
            with self.subTest(source_block_id=block.source_block_id):
                metadata = dict(block.metadata)
                self.assertEqual(metadata["epub_aux_kind"], "xhtml_title")
                self.assertEqual(
                    {
                        key: value
                        for key, value in metadata.items()
                        if key.startswith("content_role.")
                    },
                    self._EXPECTED_XHTML_TITLE_CONTENT_ROLE_METADATA,
                )

    def _assert_ncx_text_content_role_metadata(self, blocks):
        for block in blocks:
            with self.subTest(source_block_id=block.source_block_id):
                metadata = dict(block.metadata)
                self.assertEqual(metadata["epub_aux_kind"], "ncx_text")
                self.assertEqual(
                    {
                        key: value
                        for key, value in metadata.items()
                        if key.startswith("content_role.")
                    },
                    self._EXPECTED_NCX_TEXT_CONTENT_ROLE_METADATA,
                )

    def _assert_opf_title_content_role_metadata(self, blocks):
        for block in blocks:
            with self.subTest(source_block_id=block.source_block_id):
                metadata = dict(block.metadata)
                self.assertEqual(metadata["epub_aux_kind"], "opf_title")
                self.assertEqual(
                    {
                        key: value
                        for key, value in metadata.items()
                        if key.startswith("content_role.")
                    },
                    self._EXPECTED_OPF_TITLE_CONTENT_ROLE_METADATA,
                )

    def _assert_opf_description_content_role_metadata(self, blocks):
        for block in blocks:
            with self.subTest(source_block_id=block.source_block_id):
                metadata = dict(block.metadata)
                self.assertEqual(metadata["epub_aux_kind"], "opf_description")
                self.assertEqual(
                    {
                        key: value
                        for key, value in metadata.items()
                        if key.startswith("content_role.")
                    },
                    self._EXPECTED_OPF_DESCRIPTION_CONTENT_ROLE_METADATA,
                )

    def test_epub_adapter_does_not_import_private_translation_runner_helpers(self):
        adapter_source = Path(
            "src/translator_service/format_adapters/epub.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn(
            "from translator_service.translation_runner import _",
            adapter_source,
        )
        self.assertNotRegex(
            adapter_source,
            r"from\s+translator_service\.translation_runner\s+import\s+\(?\s*_",
        )

    def test_exports_public_epub_assembly_helper(self):
        self.assertTrue(callable(assemble_epub_content_from_block_translations))

    def test_exports_public_epub_book_mode_audit_chunk_helper(self):
        self.assertTrue(callable(extract_epub_book_mode_audit_chunks))

    def test_exports_public_epub_block_id_helpers(self):
        self.assertEqual(
            epub_body_block_id("OPS/chapter.xhtml", 3),
            "epub:OPS/chapter.xhtml:3",
        )
        self.assertEqual(
            epub_aux_block_id(
                kind="opf",
                file_name="OPS/content.opf",
                local_name="title",
                index=0,
            ),
            "epub:aux:opf:OPS/content.opf:title:0",
        )

    def test_gutenberg_legal_backmatter_detection_uses_shared_terms(self):
        cases = [
            (
                "The Project Gutenberg ebook license terms apply here.",
                True,
            ),
            (
                "The Project Gutenberg Literary Archive Foundation is a non-profit.",
                True,
            ),
            ("", False),
            ("Project Gutenberg", False),
            ("This license agreement has no Gutenberg legal marker.", False),
        ]

        for text, expected in cases:
            with self.subTest(text=text):
                self.assertIs(
                    _is_epub_gutenberg_legal_backmatter_text(text),
                    expected,
                )

    def test_plans_epub_body_blocks_without_note_reference_markers(self):
        plan = plan_epub_translation(
            content=_make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body>
                        <p>Jacob's ladder<a href="notes.xhtml#n_18" title="Note">
                          <sup class="calibre12">[18]</sup>
                        </a> is unplugged.</p>
                      </body>
                    </html>
                    """
                }
            ),
            max_fragment_chars=100,
        )

        self.assertEqual(
            [block.text for unit in plan.units for block in unit.blocks],
            ["Jacob's ladder is unplugged."],
        )

    def test_plans_legacy_epub_xhtml_with_doctype_and_html_entities(self):
        plan = plan_epub_translation(
            content=_make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
                      "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <head><title>Old&nbsp;Title</title></head>
                      <body><p>First&nbsp;&mdash;&nbsp;second.</p></body>
                    </html>
                    """
                }
            ),
            max_fragment_chars=100,
        )

        self.assertEqual(
            [block.text for unit in plan.units for block in unit.blocks],
            ["First — second.", "Old\u00a0Title"],
        )

    def test_plans_epub_xhtml_with_simple_html_doctype(self):
        plan = plan_epub_translation(
            content=_make_epub(
                {
                    "OPS/cover.xhtml": """
                    <!DOCTYPE html>
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body><p>Readable cover text.</p></body>
                    </html>
                    """
                }
            ),
            max_fragment_chars=100,
        )

        self.assertEqual(
            [block.text for unit in plan.units for block in unit.blocks],
            ["Readable cover text."],
        )

    def test_plans_legacy_epub_ncx_with_external_doctype(self):
        plan = plan_epub_translation(
            content=_make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body><p>First paragraph.</p></body>
                    </html>
                    """
                },
                ncx_content="""
                <!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"
                 "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
                <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
                  <docTitle><text>Old Contents</text></docTitle>
                </ncx>
                """,
            ),
            max_fragment_chars=100,
        )

        self.assertEqual(
            [block.text for unit in plan.units for block in unit.blocks],
            ["First paragraph.", "Old Contents"],
        )

    def test_assembles_epub_preserving_note_reference_anchor_markup(self):
        from io import BytesIO
        from zipfile import ZipFile

        source_content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <p>Jacob's ladder<a href="notes.xhtml#n_18"
                      title="Note"><sup class="calibre12">[18]</sup></a>
                      is unplugged.</p>
                  </body>
                </html>
                """
            }
        )

        content = assemble_epub_content_from_block_translations(
            source_content=source_content,
            translated_by_block_id={
                "epub:OPS/chapter.xhtml:0": "Драбина Якова знеструмлена.",
            },
        )

        with ZipFile(BytesIO(content)) as epub:
            chapter = epub.read("OPS/chapter.xhtml").decode("utf-8")

        self.assertNotIn("<html:", chapter)
        self.assertIn(
            '<a href="notes.xhtml#n_18" title="Note">'
            '<sup class="calibre12">[18]</sup></a>',
            chapter,
        )
        self.assertNotIn("знеструмлена</sup>", chapter)

    def test_assembled_epub_normalizes_legacy_xhtml_output(self):
        from io import BytesIO
        from zipfile import ZipFile

        source_content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
                  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>First&nbsp;&mdash;&nbsp;second.</p></body>
                </html>
                """
            }
        )

        content = assemble_epub_content_from_block_translations(
            source_content=source_content,
            translated_by_block_id={
                "epub:OPS/chapter.xhtml:0": "Первый — второй.",
            },
        )

        with ZipFile(BytesIO(content)) as epub:
            chapter = epub.read("OPS/chapter.xhtml")

        self.assertNotIn(b"<!DOCTYPE", chapter)
        self.assertNotIn(b"&nbsp;", chapter)
        self.assertEqual(extract_text_from_epub(content), "Первый — второй.")

    def test_assembled_epub_normalizes_legacy_xhtml_without_translations(self):
        from io import BytesIO
        from zipfile import ZipFile

        source_content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
                  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>First&nbsp;&mdash;&nbsp;second.</p></body>
                </html>
                """
            }
        )

        content = assemble_epub_content_from_block_translations(
            source_content=source_content,
            translated_by_block_id={},
        )

        with ZipFile(BytesIO(content)) as epub:
            chapter = epub.read("OPS/chapter.xhtml")

        self.assertNotIn(b"<!DOCTYPE", chapter)
        self.assertNotIn(b"&nbsp;", chapter)
        self.assertEqual(extract_text_from_epub(content), "First — second.")

    def test_plans_epub_blocks_with_stable_order_and_block_ids(self):
        plan = plan_epub_translation(
            content=_make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body>
                        <h1>Title</h1>
                        <p>First paragraph.</p>
                      </body>
                    </html>
                    """
                }
            ),
            max_fragment_chars=100,
        )

        self.assertEqual(plan.document_format, DocumentFormat.EPUB)
        self.assertEqual(plan.adapter_version, EPUB_ADAPTER_VERSION)
        self.assertEqual(plan.fragment_count, 1)
        self.assertEqual(plan.character_count, len("Title\n\nFirst paragraph."))
        self.assertEqual(plan.estimated_input_tokens, 36)
        self.assertEqual([unit.sequence for unit in plan.units], [1])
        self.assertEqual(plan.units[0].prompt_tier, PromptTier.PLAIN)
        self.assertEqual(
            plan.units[0].source_block_ids,
            ("epub:OPS/chapter.xhtml:0", "epub:OPS/chapter.xhtml:1"),
        )
        self.assertEqual(
            [block.text for block in plan.units[0].blocks],
            ["Title", "First paragraph."],
        )

    def test_plans_epub_table_as_strict_unit_between_plain_units(self):
        plan = plan_epub_translation(
            content=_make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body>
                        <p>Intro paragraph.</p>
                        <table>
                          <tr><td>Source</td><td>Target</td></tr>
                        </table>
                        <p>Outro paragraph.</p>
                      </body>
                    </html>
                    """
                }
            ),
            max_fragment_chars=1_000,
        )

        self.assertEqual(plan.fragment_count, 3)
        self.assertEqual(
            [unit.prompt_tier for unit in plan.units],
            [PromptTier.PLAIN, PromptTier.STRICT, PromptTier.PLAIN],
        )
        self.assertEqual(
            [block.kind for block in plan.units[1].blocks],
            [TextBlockKind.TABLE, TextBlockKind.TABLE],
        )

    def test_plans_epub_keeps_navigation_out_of_body_units(self):
        plan = plan_epub_translation(
            content=_make_epub(
                {
                    "OPS/front.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body>
                        <h1>Contents</h1>
                        <p>Chapter 1</p>
                        <p>Chapter 2</p>
                      </body>
                    </html>
                    """,
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body>
                        <h1>Chapter 1</h1>
                        <p>* * *</p>
                        <p>First real paragraph of the book.</p>
                      </body>
                    </html>
                    """,
                }
            ),
            max_fragment_chars=60,
        )

        self.assertEqual(plan.character_count, 76)
        self.assertEqual(plan.fragment_count, 4)
        self.assertEqual(
            [
                block.source_block_id
                for unit in plan.units
                for block in unit.blocks
                if not block.source_block_id.startswith("epub:aux:")
            ],
            ["epub:OPS/chapter.xhtml:0", "epub:OPS/chapter.xhtml:2"],
        )
        navigation_blocks = [
            block
            for unit in plan.units
            for block in unit.blocks
            if dict(block.metadata).get("epub_aux_kind") == "xhtml_navigation"
        ]
        self.assertEqual(
            [block.source_block_id for block in navigation_blocks],
            [
                "epub:aux:xhtml-navigation:OPS/front.xhtml:h1:0",
                "epub:aux:xhtml-navigation:OPS/front.xhtml:p:0",
                "epub:aux:xhtml-navigation:OPS/front.xhtml:p:1",
            ],
        )
        self._assert_xhtml_navigation_content_role_metadata(navigation_blocks)

    def test_plans_plain_xhtml_contents_page_as_auxiliary_navigation_blocks(self):
        plan = plan_epub_translation(
            content=_make_epub(
                {
                    "OPS/Contents_split_000.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <head><title>Contents</title></head>
                      <body>
                        <h1>Contents</h1>
                        <p>Chapter 1</p>
                        <p>Part I</p>
                      </body>
                    </html>
                    """,
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body><p>First real paragraph of the book.</p></body>
                    </html>
                    """,
                },
            ),
            max_fragment_chars=100,
        )

        navigation_blocks = [
            block
            for unit in plan.units
            for block in unit.blocks
            if dict(block.metadata).get("epub_aux_kind") == "xhtml_navigation"
            and dict(block.metadata).get("file_name") == "OPS/Contents_split_000.xhtml"
        ]

        self.assertEqual(
            [block.source_block_id for block in navigation_blocks],
            [
                "epub:aux:xhtml-navigation:OPS/Contents_split_000.xhtml:h1:0",
                "epub:aux:xhtml-navigation:OPS/Contents_split_000.xhtml:p:0",
                "epub:aux:xhtml-navigation:OPS/Contents_split_000.xhtml:p:1",
            ],
        )
        self.assertEqual(
            [block.text for block in navigation_blocks],
            ["Contents", "Chapter 1", "Part I"],
        )
        self._assert_xhtml_navigation_content_role_metadata(navigation_blocks)
        self.assertEqual(
            [unit.source_block_ids for unit in plan.units[:1]],
            [("epub:OPS/chapter.xhtml:0",)],
        )

    def test_replaces_plain_xhtml_contents_auxiliary_navigation_blocks(self):
        source_content = _make_epub(
            {
                "OPS/Contents_split_000.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <h1>Contents</h1>
                    <p>Chapter 1</p>
                    <p>Part I</p>
                  </body>
                </html>
                """,
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>First real paragraph of the book.</p></body>
                </html>
                """,
            },
        )

        content = assemble_epub_content_from_block_translations(
            source_content=source_content,
            target_language="ru",
            translated_by_block_id={
                "epub:OPS/chapter.xhtml:0": "Первый настоящий абзац книги.",
                (
                    "epub:aux:xhtml-navigation:"
                    "OPS/Contents_split_000.xhtml:h1:0"
                ): "Содержание",
                "epub:aux:xhtml-navigation:OPS/Contents_split_000.xhtml:p:0": "Глава 1",
                "epub:aux:xhtml-navigation:OPS/Contents_split_000.xhtml:p:1": "Часть I",
            },
        )

        self.assertEqual(
            extract_text_from_epub(content),
            "Содержание\n\nГлава 1\n\nЧасть I\n\nПервый настоящий абзац книги.",
        )

    def test_assembles_epub_with_russian_front_matter_label_cleanup(self):
        source_content = _make_epub(
            {
                "OPS/front.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <p>Title: The Star</p>
                    <p>Author: Jane Smith</p>
                    <p>Illustrator: John Doe</p>
                    <p>Language: English</p>
                    <p>Credits: Project Gutenberg team</p>
                  </body>
                </html>
                """,
            },
        )

        content = assemble_epub_content_from_block_translations(
            source_content=source_content,
            target_language="ru",
            translated_by_block_id={
                "epub:OPS/front.xhtml:0": "Title: Звезда",
                "epub:OPS/front.xhtml:1": "Author: Jane Smith",
                "epub:OPS/front.xhtml:2": "Illustrator: John Doe",
                "epub:OPS/front.xhtml:3": "Language: English",
                "epub:OPS/front.xhtml:4": "Credits: Project Gutenberg team",
            },
        )

        self.assertEqual(
            extract_text_from_epub(content),
            (
                "Название: Звезда\n\n"
                "Автор: Jane Smith\n\n"
                "Иллюстратор: John Doe\n\n"
                "Язык: English\n\n"
                "Подготовка текста: Project Gutenberg team"
            ),
        )

    def test_assembles_epub_with_russian_footnotes_labels_across_surfaces(self):
        from io import BytesIO
        from zipfile import ZipFile

        source_content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><h1 id="footnotes">FOOTNOTES:</h1></body>
                </html>
                """,
                "OPS/nav.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml"
                      xmlns:epub="http://www.idpf.org/2007/ops">
                  <body>
                    <nav epub:type="toc">
                      <ol>
                        <li><a href="chapter.xhtml#footnotes">FOOTNOTES:</a></li>
                      </ol>
                    </nav>
                  </body>
                </html>
                """,
            },
            ncx_content="""
            <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
              <navMap>
                <navPoint>
                  <navLabel><text>FOOTNOTES:</text></navLabel>
                </navPoint>
              </navMap>
            </ncx>
            """,
        )

        content = assemble_epub_content_from_block_translations(
            source_content=source_content,
            target_language="ru",
            translated_by_block_id={
                "epub:OPS/chapter.xhtml:0": "FOOTNOTES:",
                "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0": "FOOTNOTES:",
                "epub:aux:ncx:OPS/toc.ncx:text:0": "FOOTNOTES:",
            },
        )

        with ZipFile(BytesIO(content)) as epub:
            chapter = epub.read("OPS/chapter.xhtml").decode()
            nav = epub.read("OPS/nav.xhtml").decode()
            toc = epub.read("OPS/toc.ncx").decode()

        for surface in (chapter, nav, toc):
            self.assertIn("Примечания:", surface)
            self.assertNotIn("FOOTNOTES:", surface)
        self.assertIn('href="chapter.xhtml#footnotes"', nav)

    def test_assembles_epub_with_russian_straight_quote_cleanup(self):
        source_content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>"Yes", he said.</p></body>
                </html>
                """,
            },
        )

        content = assemble_epub_content_from_block_translations(
            source_content=source_content,
            target_language="ru",
            translated_by_block_id={
                "epub:OPS/chapter.xhtml:0": '"Да", сказал он.',
            },
        )

        self.assertEqual(
            extract_text_from_epub(content),
            "«Да», сказал он.",
        )

    def test_extracts_epub_book_mode_audit_chunks_from_final_surface(self):
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml" lang="en"
                      xml:lang="en">
                  <head><title>Original Book Title</title></head>
                  <body><h1>Chapter 1</h1><p>Переведенный абзац.</p></body>
                </html>
                """,
                "OPS/nav.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml"
                      xmlns:epub="http://www.idpf.org/2007/ops">
                  <body>
                    <nav epub:type="toc">
                      <ol><li><a href="chapter.xhtml">Book I</a></li></ol>
                    </nav>
                  </body>
                </html>
                """,
            },
            opf_content="""
            <package xmlns:dc="http://purl.org/dc/elements/1.1/">
              <metadata>
                <dc:title>Original Book Title</dc:title>
                <dc:language>en</dc:language>
              </metadata>
            </package>
            """,
            ncx_content="""
            <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
              <navMap>
                <navPoint><navLabel><text>Chapter 1</text></navLabel></navPoint>
              </navMap>
            </ncx>
            """,
        )

        chunks = extract_epub_book_mode_audit_chunks(content)
        by_surface = {
            dict(chunk.metadata).get("surface"): chunk.translated_text
            for chunk in chunks
        }

        self.assertEqual(by_surface["opf_title"], "Original Book Title")
        self.assertEqual(by_surface["opf_language"], "en")
        self.assertEqual(by_surface["toc_ncx"], "Chapter 1")
        self.assertEqual(by_surface["xhtml_title"], "Original Book Title")
        self.assertEqual(by_surface["xhtml_navigation"], "Book I")
        self.assertEqual(by_surface["xhtml_body_heading"], "Chapter 1")

    def test_plans_epub_auxiliary_metadata_and_navigation_blocks(self):
        plan = plan_epub_translation(
            content=_make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <head><title>Chapter Metadata Title</title></head>
                      <body>
                        <h1>Chapter One</h1>
                        <p>First paragraph.</p>
                      </body>
                    </html>
                    """,
                    "OPS/nav.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml"
                          xmlns:epub="http://www.idpf.org/2007/ops">
                      <body>
                        <nav epub:type="toc">
                          <ol><li><a href="chapter.xhtml">Chapter Navigation</a></li>
                          </ol>
                        </nav>
                      </body>
                    </html>
                    """
                },
                opf_content="""
                <package xmlns:dc="http://purl.org/dc/elements/1.1/">
                  <metadata>
                    <dc:title>Book Metadata Title</dc:title>
                    <dc:description>Book description.</dc:description>
                    <dc:language>en</dc:language>
                  </metadata>
                </package>
                """,
                ncx_content="""
                <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
                  <docTitle><text>NCX Book Title</text></docTitle>
                  <navMap>
                    <navPoint><navLabel><text>NCX Chapter One</text></navLabel>
                    </navPoint>
                  </navMap>
                </ncx>
                """,
            ),
            max_fragment_chars=100,
        )

        expected_aux_ids = [
            "epub:aux:opf:OPS/content.opf:title:0",
            "epub:aux:opf:OPS/content.opf:description:0",
            "epub:aux:ncx:OPS/toc.ncx:text:0",
            "epub:aux:ncx:OPS/toc.ncx:text:1",
            "epub:aux:xhtml-title:OPS/chapter.xhtml:title:0",
            "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0",
        ]
        aux_blocks = [
            block
            for unit in plan.units
            for block in unit.blocks
            if block.source_block_id.startswith("epub:aux:")
        ]
        self.assertEqual(
            [block.source_block_id for block in aux_blocks],
            expected_aux_ids,
        )
        self.assertEqual(
            [unit.source_block_ids for unit in plan.units[:1]],
            [("epub:OPS/chapter.xhtml:0", "epub:OPS/chapter.xhtml:1")],
        )
        self.assertEqual(
            [dict(block.metadata)["epub_aux_kind"] for block in aux_blocks],
            [
                "opf_title",
                "opf_description",
                "ncx_text",
                "ncx_text",
                "xhtml_title",
                "xhtml_navigation",
            ],
        )
        source_block_ids = [
            block.source_block_id
            for unit in plan.units
            for block in unit.blocks
        ]
        self.assertEqual(len(source_block_ids), len(set(source_block_ids)))
        self.assertNotIn("epub:aux:opf:OPS/content.opf:language:0", source_block_ids)
        non_aux_blocks = [
            block
            for unit in plan.units
            for block in unit.blocks
            if not block.source_block_id.startswith("epub:aux:")
        ]
        for block in non_aux_blocks:
            self.assertFalse(
                any(key.startswith("content_role.") for key, _ in block.metadata)
            )
        for block in aux_blocks:
            metadata = dict(block.metadata)
            self.assertIn(("role", "auxiliary"), block.metadata)
            self.assertIn(("epub_aux_kind", metadata["epub_aux_kind"]), block.metadata)
            self.assertIn(("file_name", metadata["file_name"]), block.metadata)
            self.assertIn(("local_name", metadata["local_name"]), block.metadata)
            self.assertIn(("aux_index", metadata["aux_index"]), block.metadata)

        opf_description_blocks = [
            block
            for block in aux_blocks
            if dict(block.metadata).get("epub_aux_kind") == "opf_description"
        ]
        self.assertEqual(
            [block.source_block_id for block in opf_description_blocks],
            ["epub:aux:opf:OPS/content.opf:description:0"],
        )
        self._assert_opf_description_content_role_metadata(opf_description_blocks)

        unannotated_aux_blocks = [
            block
            for block in aux_blocks
            if dict(block.metadata).get("epub_aux_kind")
            not in {
                "ncx_text",
                "xhtml_navigation",
                "xhtml_title",
                "opf_title",
                "opf_description",
            }
        ]
        self.assertEqual(unannotated_aux_blocks, [])

        opf_title_blocks = [
            block
            for block in aux_blocks
            if dict(block.metadata).get("epub_aux_kind") == "opf_title"
        ]
        self.assertEqual(
            [block.source_block_id for block in opf_title_blocks],
            ["epub:aux:opf:OPS/content.opf:title:0"],
        )
        self._assert_opf_title_content_role_metadata(opf_title_blocks)

        xhtml_title_blocks = [
            block
            for block in aux_blocks
            if dict(block.metadata).get("epub_aux_kind") == "xhtml_title"
        ]
        self.assertEqual(
            [block.source_block_id for block in xhtml_title_blocks],
            ["epub:aux:xhtml-title:OPS/chapter.xhtml:title:0"],
        )
        self._assert_xhtml_title_content_role_metadata(xhtml_title_blocks)

        ncx_blocks = [
            block
            for block in aux_blocks
            if dict(block.metadata).get("epub_aux_kind") == "ncx_text"
        ]
        self.assertEqual(
            [block.source_block_id for block in ncx_blocks],
            [
                "epub:aux:ncx:OPS/toc.ncx:text:0",
                "epub:aux:ncx:OPS/toc.ncx:text:1",
            ],
        )
        self._assert_ncx_text_content_role_metadata(ncx_blocks)

        navigation_blocks = [
            block
            for block in aux_blocks
            if dict(block.metadata).get("epub_aux_kind") == "xhtml_navigation"
        ]
        self.assertEqual(
            [block.source_block_id for block in navigation_blocks],
            ["epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0"],
        )
        self._assert_xhtml_navigation_content_role_metadata(navigation_blocks)
        navigation_metadata = dict(navigation_blocks[0].metadata)
        self.assertEqual(navigation_metadata["role"], "auxiliary")
        self.assertEqual(navigation_metadata["file_name"], "OPS/nav.xhtml")
        self.assertEqual(navigation_metadata["local_name"], "a")
        self.assertEqual(navigation_metadata["aux_index"], "0")

    def test_plans_epub_xhtml_title_metadata_for_multiple_files(self):
        plan = plan_epub_translation(
            content=_make_epub(
                {
                    "OPS/chapter1.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <head><title>Chapter One Metadata Title</title></head>
                      <body><p>First paragraph.</p></body>
                    </html>
                    """,
                    "OPS/chapter2.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <head><title>Chapter Two Metadata Title</title></head>
                      <body><p>Second paragraph.</p></body>
                    </html>
                    """,
                }
            ),
            max_fragment_chars=100,
        )

        xhtml_title_blocks = [
            block
            for unit in plan.units
            for block in unit.blocks
            if dict(block.metadata).get("epub_aux_kind") == "xhtml_title"
        ]
        self.assertEqual(
            [block.source_block_id for block in xhtml_title_blocks],
            [
                "epub:aux:xhtml-title:OPS/chapter1.xhtml:title:0",
                "epub:aux:xhtml-title:OPS/chapter2.xhtml:title:0",
            ],
        )
        self.assertEqual(
            len({block.source_block_id for block in xhtml_title_blocks}),
            2,
        )
        self._assert_xhtml_title_content_role_metadata(xhtml_title_blocks)
        self.assertEqual(
            [
                {
                    key: metadata[key]
                    for key in ("role", "file_name", "local_name", "aux_index")
                }
                for metadata in (dict(block.metadata) for block in xhtml_title_blocks)
            ],
            [
                {
                    "role": "auxiliary",
                    "file_name": "OPS/chapter1.xhtml",
                    "local_name": "title",
                    "aux_index": "0",
                },
                {
                    "role": "auxiliary",
                    "file_name": "OPS/chapter2.xhtml",
                    "local_name": "title",
                    "aux_index": "0",
                },
            ],
        )

    def test_skips_empty_epub_xhtml_head_titles(self):
        plan = plan_epub_translation(
            content=_make_epub(
                {
                    "OPS/empty-title.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <head><title></title></head>
                      <body><p>First paragraph.</p></body>
                    </html>
                    """,
                    "OPS/whitespace-title.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <head><title>   </title></head>
                      <body><p>Second paragraph.</p></body>
                    </html>
                    """,
                }
            ),
            max_fragment_chars=100,
        )

        source_block_ids = [
            block.source_block_id
            for unit in plan.units
            for block in unit.blocks
        ]
        self.assertFalse(
            any(
                source_block_id.startswith("epub:aux:xhtml-title:")
                for source_block_id in source_block_ids
            )
        )
        self.assertFalse(
            any(
                dict(block.metadata).get("epub_aux_kind") == "xhtml_title"
                for unit in plan.units
                for block in unit.blocks
            )
        )

    def test_plans_nested_epub_navigation_anchor_labels(self):
        plan = plan_epub_translation(
            content=_make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body><p>First paragraph.</p></body>
                    </html>
                    """,
                    "OPS/nav.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml"
                          xmlns:epub="http://www.idpf.org/2007/ops">
                      <body>
                        <nav epub:type="toc">
                          <ol>
                            <li>
                              <a href="part.xhtml">Part I</a>
                              <ol>
                                <li><a href="chapter.xhtml">Chapter 1</a></li>
                              </ol>
                            </li>
                          </ol>
                        </nav>
                      </body>
                    </html>
                    """,
                }
            ),
            max_fragment_chars=100,
        )

        nav_blocks = [
            block
            for unit in plan.units
            for block in unit.blocks
            if dict(block.metadata).get("epub_aux_kind") == "xhtml_navigation"
        ]
        self.assertEqual(
            [block.source_block_id for block in nav_blocks],
            [
                "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0",
                "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:1",
            ],
        )
        self.assertEqual([block.text for block in nav_blocks], ["Part I", "Chapter 1"])
        self._assert_xhtml_navigation_content_role_metadata(nav_blocks)

    def test_plans_only_xhtml_head_title_as_auxiliary_title(self):
        plan = plan_epub_translation(
            content=_make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <head><title>Real Title</title></head>
                      <body>
                        <h1>Chapter One</h1>
                        <svg xmlns="http://www.w3.org/2000/svg">
                          <title>Icon label</title>
                        </svg>
                        <p>First paragraph.</p>
                      </body>
                    </html>
                    """
                }
            ),
            max_fragment_chars=100,
        )

        xhtml_title_blocks = [
            block
            for unit in plan.units
            for block in unit.blocks
            if dict(block.metadata).get("epub_aux_kind") == "xhtml_title"
        ]
        self.assertEqual(
            [block.source_block_id for block in xhtml_title_blocks],
            ["epub:aux:xhtml-title:OPS/chapter.xhtml:title:0"],
        )
        self.assertEqual(
            [block.text for block in xhtml_title_blocks],
            ["Real Title"],
        )

    def test_assembles_epub_metadata_navigation_headings_and_language_attrs(self):
        from io import BytesIO
        from xml.etree import ElementTree
        from zipfile import ZipFile

        source_content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en">
                  <head><title>Chapter Metadata Title</title></head>
                  <body>
                    <h1>Chapter One</h1>
                    <p>First paragraph.</p>
                  </body>
                </html>
                """,
                "OPS/nav.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml"
                      xmlns:epub="http://www.idpf.org/2007/ops"
                      lang="en"
                      xml:lang="en">
                  <head><title>Contents</title></head>
                  <body>
                    <nav epub:type="toc">
                      <h1>Contents</h1>
                      <ol>
                        <li><a href="chapter.xhtml">Chapter One</a></li>
                      </ol>
                    </nav>
                  </body>
                </html>
                """,
            },
            opf_content="""
            <package xmlns:dc="http://purl.org/dc/elements/1.1/"
                     lang="en"
                     xml:lang="en">
              <metadata>
                <dc:title xml:lang="en">Book Metadata Title</dc:title>
                <dc:description xml:lang="en">Book description.</dc:description>
                <dc:language>en</dc:language>
              </metadata>
            </package>
            """,
            ncx_content="""
            <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"
                 xml:lang="en">
              <docTitle><text>NCX Book Title</text></docTitle>
              <navMap>
                <navPoint>
                  <navLabel xml:lang="en"><text>NCX Chapter One</text></navLabel>
                </navPoint>
              </navMap>
            </ncx>
            """,
        )

        plan = plan_epub_translation(content=source_content, max_fragment_chars=100)
        source_block_ids = {
            block.source_block_id
            for unit in plan.units
            for block in unit.blocks
        }
        expected_aux_ids = {
            "epub:aux:opf:OPS/content.opf:title:0",
            "epub:aux:opf:OPS/content.opf:description:0",
            "epub:aux:ncx:OPS/toc.ncx:text:0",
            "epub:aux:ncx:OPS/toc.ncx:text:1",
            "epub:aux:xhtml-title:OPS/chapter.xhtml:title:0",
            "epub:aux:xhtml-title:OPS/nav.xhtml:title:0",
            "epub:aux:xhtml-navigation:OPS/nav.xhtml:h1:0",
            "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0",
        }
        self.assertTrue(expected_aux_ids.issubset(source_block_ids))

        content = assemble_epub_content_from_block_translations(
            source_content=source_content,
            target_language="ru",
            translated_by_block_id={
                "epub:OPS/chapter.xhtml:0": "Глава первая",
                "epub:OPS/chapter.xhtml:1": "Первый абзац.",
                "epub:aux:opf:OPS/content.opf:title:0": "Название книги",
                "epub:aux:opf:OPS/content.opf:description:0": "Описание книги.",
                "epub:aux:ncx:OPS/toc.ncx:text:0": "Название NCX",
                "epub:aux:ncx:OPS/toc.ncx:text:1": "Глава NCX первая",
                "epub:aux:xhtml-title:OPS/chapter.xhtml:title:0": "Название главы",
                "epub:aux:xhtml-title:OPS/nav.xhtml:title:0": "Содержание",
                "epub:aux:xhtml-navigation:OPS/nav.xhtml:h1:0": "Содержание",
                "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0": "Глава первая",
            },
        )

        with ZipFile(BytesIO(content)) as epub:
            opf = epub.read("OPS/content.opf")
            toc = epub.read("OPS/toc.ncx")
            chapter = epub.read("OPS/chapter.xhtml")
            nav = epub.read("OPS/nav.xhtml")

        self.assertIn(b"<dc:language>ru</dc:language>", opf)
        self.assertNotIn(b"<dc:language>en</dc:language>", opf)
        self.assertNotIn(b'xml:lang="en"', opf)
        self.assertNotIn(b'lang="en"', opf)
        opf_root = ElementTree.fromstring(opf)
        self.assertEqual(opf_root.attrib["lang"], "ru")
        self.assertEqual(
            opf_root.attrib["{http://www.w3.org/XML/1998/namespace}lang"],
            "ru",
        )
        opf_title = next(
            element for element in opf_root.iter() if element.tag.endswith("title")
        )
        self.assertEqual(opf_title.text, "Название книги")
        self.assertEqual(
            opf_title.attrib["{http://www.w3.org/XML/1998/namespace}lang"],
            "ru",
        )
        opf_description = next(
            element
            for element in opf_root.iter()
            if element.tag.endswith("description")
        )
        self.assertEqual(opf_description.text, "Описание книги.")
        self.assertEqual(
            opf_description.attrib["{http://www.w3.org/XML/1998/namespace}lang"],
            "ru",
        )
        self.assertIn("Название NCX".encode(), toc)
        self.assertIn("Глава NCX первая".encode(), toc)
        self.assertNotIn(b'xml:lang="en"', toc)
        ncx_root = ElementTree.fromstring(toc)
        self.assertEqual(
            ncx_root.attrib["{http://www.w3.org/XML/1998/namespace}lang"],
            "ru",
        )
        ncx_nav_label = next(
            element for element in ncx_root.iter() if element.tag.endswith("navLabel")
        )
        self.assertEqual(
            ncx_nav_label.attrib["{http://www.w3.org/XML/1998/namespace}lang"],
            "ru",
        )
        chapter_root = ElementTree.fromstring(chapter)
        nav_root = ElementTree.fromstring(nav)
        self.assertEqual(chapter_root.attrib["lang"], "ru")
        self.assertEqual(nav_root.attrib["lang"], "ru")
        self.assertEqual(
            chapter_root.attrib["{http://www.w3.org/XML/1998/namespace}lang"],
            "ru",
        )
        self.assertEqual(
            nav_root.attrib["{http://www.w3.org/XML/1998/namespace}lang"],
            "ru",
        )
        self.assertIn("Название главы".encode(), chapter)
        self.assertIn("Глава первая".encode(), chapter)
        self.assertIn("Содержание".encode(), nav)
        self.assertIn(b'href="chapter.xhtml"', nav)

    def test_rejects_epub_with_malformed_container_xml(self):
        with self.assertRaisesRegex(
            TextExtractionError,
            "EPUB container XML is not readable",
        ):
            plan_epub_translation(
                content=_make_epub(
                    {
                        "OPS/chapter.xhtml": """
                        <html xmlns="http://www.w3.org/1999/xhtml">
                          <body><p>First paragraph.</p></body>
                        </html>
                        """
                    },
                    container_content="<container",
                ),
                max_fragment_chars=100,
            )

    def test_rejects_epub_with_malformed_opf_xml(self):
        with self.assertRaisesRegex(
            TextExtractionError,
            "EPUB package XML is not readable",
        ):
            plan_epub_translation(
                content=_make_epub(
                    {
                        "OPS/chapter.xhtml": """
                        <html xmlns="http://www.w3.org/1999/xhtml">
                          <body><p>First paragraph.</p></body>
                        </html>
                        """
                    },
                    opf_content="<package",
                ),
                max_fragment_chars=100,
            )

    def test_rejects_epub_auxiliary_xhtml_entities_before_parsing(self):
        with self.assertRaisesRegex(
            TextExtractionError,
            "XML entities are not supported",
        ):
            plan_epub_translation(
                content=_make_epub(
                    {
                        "OPS/chapter.xhtml": """
                        <html xmlns="http://www.w3.org/1999/xhtml">
                          <body><p>First paragraph.</p></body>
                        </html>
                        """,
                        "OPS/nav.xhtml": """
                        <!DOCTYPE html [<!ENTITY injected "Bad">]>
                        <html xmlns="http://www.w3.org/1999/xhtml"
                              xmlns:epub="http://www.idpf.org/2007/ops">
                          <body>
                            <nav epub:type="toc">
                              <ol><li><a href="chapter.xhtml">&injected;</a></li></ol>
                            </nav>
                          </body>
                        </html>
                        """,
                    },
                ),
                max_fragment_chars=100,
            )

    def test_deduplicates_repeated_epub_spine_itemrefs(self):
        plan = plan_epub_translation(
            content=_make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <head><title>Chapter Metadata Title</title></head>
                      <body>
                        <h1>Chapter One</h1>
                        <p>First paragraph.</p>
                      </body>
                    </html>
                    """
                },
                opf_content="""
                <package xmlns="http://www.idpf.org/2007/opf">
                  <manifest>
                    <item id="chapter" href="chapter.xhtml"
                      media-type="application/xhtml+xml" />
                  </manifest>
                  <spine>
                    <itemref idref="chapter" />
                    <itemref idref="chapter" />
                  </spine>
                </package>
                """,
            ),
            max_fragment_chars=100,
        )

        source_block_ids = [
            block.source_block_id
            for unit in plan.units
            for block in unit.blocks
        ]
        self.assertEqual(len(source_block_ids), len(set(source_block_ids)))
        self.assertEqual(
            plan.units[0].source_block_ids,
            ("epub:OPS/chapter.xhtml:0", "epub:OPS/chapter.xhtml:1"),
        )
        self.assertEqual(
            [
                block.source_block_id
                for unit in plan.units
                for block in unit.blocks
                if block.source_block_id.startswith("epub:aux:xhtml-title:")
            ],
            ["epub:aux:xhtml-title:OPS/chapter.xhtml:title:0"],
        )

    def test_plans_and_assembles_realistic_legacy_epub_without_metadata_repair(self):
        from io import BytesIO
        from zipfile import ZipFile

        source_content = _make_realistic_kafka_epub()

        plan = plan_epub_translation(
            content=source_content,
            max_fragment_chars=200,
        )

        block_texts = [block.text for unit in plan.units for block in unit.blocks]
        self.assertGreater(plan.fragment_count, 0)
        self.assertIn("Amerika", block_texts)
        self.assertTrue(
            any("Karl Rossmann" in text for text in block_texts),
            block_texts,
        )

        with ZipFile(BytesIO(source_content)) as source_epub:
            self.assertIn(
                b"<dc:language>nl</dc:language>",
                source_epub.read("OPS/content.opf"),
            )

        content = assemble_epub_content_from_block_translations(
            source_content=source_content,
            target_language="ru",
            translated_by_block_id={
                "epub:OPS/Text/chapter1.xhtml:1": (
                    "Карл Россман прибыл в порт Нью-Йорка."
                ),
            },
        )

        with ZipFile(BytesIO(content)) as epub:
            first_chapter = epub.read("OPS/Text/chapter1.xhtml")
            second_chapter = epub.read("OPS/Text/chapter2.xhtml")
            toc = epub.read("OPS/toc.ncx")
            opf = epub.read("OPS/content.opf")

        for xml_part in (first_chapter, second_chapter, toc):
            self.assertNotIn(b"<!DOCTYPE", xml_part)
            self.assertNotIn(b"&nbsp;", xml_part)
        self.assertIn(b"<dc:language>ru</dc:language>", opf)
        self.assertNotIn(b"<dc:language>nl</dc:language>", opf)


if __name__ == "__main__":
    unittest.main()


def _make_docx(document_xml: str) -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr("word/document.xml", document_xml)
    return archive.getvalue()


def _make_epub(
    xhtml_items: dict[str, str],
    *,
    container_content: str | None = None,
    opf_content: str | None = None,
    ncx_content: str | None = None,
) -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        if container_content is not None:
            epub.writestr("META-INF/container.xml", container_content)
        elif opf_content is None:
            epub.writestr("META-INF/container.xml", "<container />")
        else:
            epub.writestr(
                "META-INF/container.xml",
                """
                <container>
                  <rootfiles>
                    <rootfile full-path="OPS/content.opf" />
                  </rootfiles>
                </container>
                """,
            )
            epub.writestr("OPS/content.opf", opf_content)
        if ncx_content is not None:
            epub.writestr("OPS/toc.ncx", ncx_content)
        for file_name, content in xhtml_items.items():
            epub.writestr(file_name, content)
    return archive.getvalue()


def _make_realistic_kafka_epub() -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """
            <container version="1.0"
              xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles>
                <rootfile full-path="OPS/content.opf"
                  media-type="application/oebps-package+xml" />
              </rootfiles>
            </container>
            """,
        )
        epub.writestr(
            "OPS/content.opf",
            """
            <package version="2.0" unique-identifier="bookid"
              xmlns="http://www.idpf.org/2007/opf"
              xmlns:dc="http://purl.org/dc/elements/1.1/">
              <metadata>
                <dc:title>Amerika</dc:title>
                <dc:creator>Franz Kafka</dc:creator>
                <dc:language>nl</dc:language>
              </metadata>
              <manifest>
                <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml" />
                <item id="chapter1" href="Text/chapter1.xhtml"
                  media-type="application/xhtml+xml" />
                <item id="chapter2" href="Text/chapter2.xhtml"
                  media-type="application/xhtml+xml" />
              </manifest>
              <spine toc="ncx">
                <itemref idref="chapter1" />
                <itemref idref="chapter2" />
              </spine>
            </package>
            """,
        )
        epub.writestr(
            "OPS/toc.ncx",
            """
            <!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"
              "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
            <ncx version="2005-1"
              xmlns="http://www.daisy.org/z3986/2005/ncx/">
              <head>
                <meta name="dtb:uid" content="kafka-amerika" />
              </head>
              <docTitle><text>Amerika</text></docTitle>
              <navMap>
                <navPoint id="nav-1" playOrder="1">
                  <navLabel><text>De stoker</text></navLabel>
                  <content src="Text/chapter1.xhtml" />
                </navPoint>
                <navPoint id="nav-2" playOrder="2">
                  <navLabel><text>De oom</text></navLabel>
                  <content src="Text/chapter2.xhtml" />
                </navPoint>
              </navMap>
            </ncx>
            """,
        )
        epub.writestr(
            "OPS/Text/chapter1.xhtml",
            """
            <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
              "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
            <html xmlns="http://www.w3.org/1999/xhtml">
              <head><title>Amerika</title></head>
              <body>
                <h1>Amerika</h1>
                <p>Karl&nbsp;Rossmann arrived in the port of New York.</p>
              </body>
            </html>
            """,
        )
        epub.writestr(
            "OPS/Text/chapter2.xhtml",
            """
            <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
              "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
            <html xmlns="http://www.w3.org/1999/xhtml">
              <head><title>The Uncle</title></head>
              <body>
                <h1>The Uncle</h1>
                <p>The&nbsp;corridors of the hotel were bright and crowded.</p>
              </body>
            </html>
            """,
        )
    return archive.getvalue()
