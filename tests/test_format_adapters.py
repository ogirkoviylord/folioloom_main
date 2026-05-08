import unittest
from pathlib import Path

from translator_service.documents import DocumentFormat
from translator_service.extractors import TextExtractionError, extract_text_from_epub
from translator_service.format_adapters import (
    DOCX_ADAPTER_VERSION,
    EPUB_ADAPTER_VERSION,
    TXT_ADAPTER_VERSION,
    assemble_epub_content_from_block_translations,
    epub_aux_block_id,
    epub_body_block_id,
    plan_docx_translation,
    plan_epub_translation,
    plan_txt_translation,
)
from translator_service.structure_optimizer import PromptTier, TextBlockKind


class TxtFormatAdapterTest(unittest.TestCase):
    def test_plans_txt_fragments_with_stable_order_and_block_ids(self):
        plan = plan_txt_translation(
            content="# Title\n\nKEY=value\n- First item\nBody text.".encode("utf-8"),
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


class EpubFormatAdapterTest(unittest.TestCase):
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
                    <p>Jacob's ladder<a href="notes.xhtml#n_18" title="Note"><sup class="calibre12">[18]</sup></a> is unplugged.</p>
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
            '<a href="notes.xhtml#n_18" title="Note"><sup class="calibre12">[18]</sup></a>',
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
        self.assertEqual(
            [
                block.source_block_id
                for unit in plan.units
                for block in unit.blocks
                if dict(block.metadata).get("epub_aux_kind") == "xhtml_navigation"
            ],
            [
                "epub:aux:xhtml-navigation:OPS/front.xhtml:h1:0",
                "epub:aux:xhtml-navigation:OPS/front.xhtml:p:0",
                "epub:aux:xhtml-navigation:OPS/front.xhtml:p:1",
            ],
        )

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
                "epub:aux:xhtml-navigation:OPS/Contents_split_000.xhtml:h1:0": "Содержание",
                "epub:aux:xhtml-navigation:OPS/Contents_split_000.xhtml:p:0": "Глава 1",
                "epub:aux:xhtml-navigation:OPS/Contents_split_000.xhtml:p:1": "Часть I",
            },
        )

        self.assertEqual(
            extract_text_from_epub(content),
            "Содержание\n\nГлава 1\n\nЧасть I\n\nПервый настоящий абзац книги.",
        )

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
                          <ol><li><a href="chapter.xhtml">Chapter Navigation</a></li></ol>
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
                    <navPoint><navLabel><text>NCX Chapter One</text></navLabel></navPoint>
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
        for block in aux_blocks:
            metadata = dict(block.metadata)
            self.assertIn(("role", "auxiliary"), block.metadata)
            self.assertIn(("epub_aux_kind", metadata["epub_aux_kind"]), block.metadata)
            self.assertIn(("file_name", metadata["file_name"]), block.metadata)
            self.assertIn(("local_name", metadata["local_name"]), block.metadata)
            self.assertIn(("aux_index", metadata["aux_index"]), block.metadata)

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
                    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml" />
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
                "epub:OPS/Text/chapter1.xhtml:1": "Карл Россман прибыл в порт Нью-Йорка.",
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
