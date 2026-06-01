import json
import tempfile
import unittest
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from translator_service.documents import DocumentFormat
from translator_service.format_adapters.contracts import (
    FormatAdapterPlan,
    FormatTextBlock,
    FormatTranslationUnit,
)
from translator_service.internal_reader import (
    READER_STATUS_DONE,
    READER_STATUS_MISSING,
    build_epub_reader_document,
    build_reader_document,
    build_txt_reader_document,
    generate_epub_reader_html_from_path,
    generate_txt_reader_html_from_path,
    load_translation_mapping,
    reject_runtime_var_path,
    render_reader_html,
)
from translator_service.structure_optimizer import PromptTier, TextBlockKind


class InternalReaderTest(unittest.TestCase):
    def test_builds_txt_reader_document_with_stable_blocks_and_missing_status(self):
        document = build_txt_reader_document(
            content=b"# Title\n\n- First item\nBody text.",
            source_name="sample.txt",
            generated_at=datetime(2026, 6, 1, tzinfo=UTC),
        )

        self.assertEqual(document.document_format, "txt")
        self.assertEqual(document.source_name, "sample.txt")
        self.assertEqual(len(document.sections), 1)
        blocks = document.sections[0].blocks
        self.assertEqual(
            [block.source_block_id for block in blocks],
            ["txt:segment:1", "txt:segment:3", "txt:segment:4"],
        )
        self.assertEqual(
            [block.status for block in blocks],
            [READER_STATUS_MISSING] * 3,
        )
        self.assertEqual(dict(blocks[0].metadata)["txt_kind"], "heading")
        self.assertEqual(dict(blocks[1].metadata)["start_line"], "3")

    def test_marks_supplied_translations_as_done(self):
        document = build_txt_reader_document(
            content=b"# Title\n\nBody text.",
            translated_by_block_id={
                "txt:segment:1": "Заголовок",
            },
            generated_at=datetime(2026, 6, 1, tzinfo=UTC),
        )

        blocks = document.sections[0].blocks
        self.assertEqual(blocks[0].translated_text, "Заголовок")
        self.assertEqual(blocks[0].status, READER_STATUS_DONE)
        self.assertIsNone(blocks[1].translated_text)
        self.assertEqual(blocks[1].status, READER_STATUS_MISSING)

    def test_maps_docx_adapter_plan_to_file_section_and_preserves_metadata(self):
        plan = FormatAdapterPlan(
            document_format=DocumentFormat.DOCX,
            adapter_version="docx-adapter-test",
            character_count=27,
            estimated_input_tokens=12,
            units=(
                FormatTranslationUnit(
                    sequence=1,
                    prompt_tier=PromptTier.STRICT,
                    blocks=(
                        FormatTextBlock(
                            index=0,
                            source_block_id="docx:word/document.xml:0",
                            text="First paragraph",
                            kind=TextBlockKind.PLAIN,
                            metadata=(
                                ("file_name", "word/document.xml"),
                                ("block_index", "0"),
                            ),
                        ),
                        FormatTextBlock(
                            index=1,
                            source_block_id="docx:word/document.xml:1",
                            text="Table cell",
                            kind=TextBlockKind.TABLE,
                            group_id="word/document.xml:table:0",
                            metadata=(
                                ("file_name", "word/document.xml"),
                                ("block_index", "1"),
                                ("fixed_width_pseudo_table", "False"),
                            ),
                        ),
                    ),
                ),
            ),
        )

        document = build_reader_document(
            plan=plan,
            translated_by_block_id={
                "docx:word/document.xml:0": "Первый абзац",
            },
            source_name="sample.docx",
            generated_at=datetime(2026, 6, 1, tzinfo=UTC),
        )

        self.assertEqual(document.document_format, "docx")
        self.assertEqual(document.adapter_version, "docx-adapter-test")
        self.assertEqual([section.source_file_name for section in document.sections], [
            "word/document.xml",
        ])
        blocks = document.sections[0].blocks
        self.assertEqual(
            [block.source_block_id for block in blocks],
            ["docx:word/document.xml:0", "docx:word/document.xml:1"],
        )
        self.assertEqual([block.sequence for block in blocks], [1, 2])
        self.assertEqual([block.kind for block in blocks], ["plain", "table"])
        self.assertEqual(blocks[1].group_id, "word/document.xml:table:0")
        self.assertEqual(
            dict(blocks[1].metadata)["fixed_width_pseudo_table"],
            "False",
        )
        self.assertEqual([block.status for block in blocks], [
            READER_STATUS_DONE,
            READER_STATUS_MISSING,
        ])

    def test_maps_epub_adapter_plan_to_ordered_sections_with_roles(self):
        plan = FormatAdapterPlan(
            document_format=DocumentFormat.EPUB,
            adapter_version="epub-adapter-test",
            character_count=55,
            estimated_input_tokens=20,
            units=(
                FormatTranslationUnit(
                    sequence=1,
                    prompt_tier=PromptTier.PLAIN,
                    blocks=(
                        FormatTextBlock(
                            index=0,
                            source_block_id="epub:OPS/chapter.xhtml:0",
                            text="Chapter title",
                            kind=TextBlockKind.HEADING,
                            metadata=(
                                ("file_name", "OPS/chapter.xhtml"),
                                ("block_index", "0"),
                                ("role", "body"),
                            ),
                        ),
                        FormatTextBlock(
                            index=1,
                            source_block_id="epub:OPS/chapter.xhtml:1",
                            text="First paragraph.",
                            kind=TextBlockKind.PLAIN,
                            metadata=(
                                ("file_name", "OPS/chapter.xhtml"),
                                ("block_index", "1"),
                                ("role", "body"),
                            ),
                        ),
                    ),
                ),
                FormatTranslationUnit(
                    sequence=2,
                    prompt_tier=PromptTier.STRICT,
                    blocks=(
                        FormatTextBlock(
                            index=2,
                            source_block_id="epub:OPS/notes.xhtml:0",
                            text="Footnote body.",
                            kind=TextBlockKind.FOOTNOTE,
                            group_id="OPS/notes.xhtml:footnote:1",
                            metadata=(
                                ("file_name", "OPS/notes.xhtml"),
                                ("block_index", "0"),
                                ("role", "body"),
                            ),
                        ),
                    ),
                ),
                FormatTranslationUnit(
                    sequence=3,
                    prompt_tier=PromptTier.PLAIN,
                    blocks=(
                        FormatTextBlock(
                            index=3,
                            source_block_id=(
                                "epub:aux:opf:OPS/content.opf:title:0"
                            ),
                            text="Metadata title",
                            kind=TextBlockKind.PLAIN,
                            metadata=(
                                ("role", "auxiliary"),
                                ("file_name", "OPS/content.opf"),
                                ("epub_aux_kind", "opf_title"),
                                ("local_name", "title"),
                                ("aux_index", "0"),
                            ),
                        ),
                    ),
                ),
            ),
        )

        document = build_reader_document(
            plan=plan,
            translated_by_block_id={
                "epub:aux:opf:OPS/content.opf:title:0": "Назва metadata",
            },
            source_name="sample.epub",
            generated_at=datetime(2026, 6, 1, tzinfo=UTC),
        )

        self.assertEqual(document.document_format, "epub")
        self.assertEqual([section.source_file_name for section in document.sections], [
            "OPS/chapter.xhtml",
            "OPS/notes.xhtml",
            "OPS/content.opf",
        ])
        blocks = [
            block
            for section in document.sections
            for block in section.blocks
        ]
        self.assertEqual(
            [block.source_block_id for block in blocks],
            [
                "epub:OPS/chapter.xhtml:0",
                "epub:OPS/chapter.xhtml:1",
                "epub:OPS/notes.xhtml:0",
                "epub:aux:opf:OPS/content.opf:title:0",
            ],
        )
        self.assertEqual([block.sequence for block in blocks], [1, 2, 3, 4])
        self.assertEqual(dict(blocks[0].metadata)["role"], "body")
        self.assertEqual(blocks[2].group_id, "OPS/notes.xhtml:footnote:1")
        self.assertEqual(dict(blocks[3].metadata)["role"], "auxiliary")
        self.assertEqual(dict(blocks[3].metadata)["epub_aux_kind"], "opf_title")
        self.assertEqual(blocks[3].status, READER_STATUS_DONE)

    def test_builds_epub_reader_document_from_spine_ordered_chapters(self):
        document = build_epub_reader_document(
            content=_make_epub(
                {
                    "OPS/chapter1.xhtml": """
                        <html xmlns="http://www.w3.org/1999/xhtml">
                          <body><h1>Chapter One</h1><p>First chapter body.</p></body>
                        </html>
                    """,
                    "OPS/chapter2.xhtml": """
                        <html xmlns="http://www.w3.org/1999/xhtml">
                          <body><h1>Chapter Two</h1><p>Second chapter body.</p></body>
                        </html>
                    """,
                },
                spine=("chapter2", "chapter1"),
            ),
            translated_by_block_id={
                "epub:OPS/chapter2.xhtml:0": "Глава вторая",
            },
            source_name="sample.epub",
            generated_at=datetime(2026, 6, 1, tzinfo=UTC),
        )

        self.assertEqual(document.document_format, "epub")
        self.assertEqual(document.source_name, "sample.epub")
        self.assertEqual(
            [section.source_file_name for section in document.sections[:2]],
            ["OPS/chapter2.xhtml", "OPS/chapter1.xhtml"],
        )
        chapter_two_blocks = document.sections[0].blocks
        self.assertEqual(
            [block.source_block_id for block in chapter_two_blocks],
            ["epub:OPS/chapter2.xhtml:0", "epub:OPS/chapter2.xhtml:1"],
        )
        self.assertEqual(chapter_two_blocks[0].status, READER_STATUS_DONE)
        self.assertEqual(chapter_two_blocks[1].status, READER_STATUS_MISSING)
        self.assertEqual(dict(chapter_two_blocks[0].metadata)["role"], "body")
        auxiliary_blocks = [
            block
            for section in document.sections
            for block in section.blocks
            if dict(block.metadata).get("role") == "auxiliary"
        ]
        self.assertTrue(auxiliary_blocks)
        self.assertEqual(
            dict(auxiliary_blocks[0].metadata)["epub_aux_kind"],
            "opf_title",
        )

    def test_generate_epub_reader_html_from_path_rejects_runtime_var_paths(self):
        repo_root = Path(__file__).resolve().parents[1]
        var_path = repo_root / "var" / "internal-reader-test.epub"

        with self.assertRaisesRegex(ValueError, "runtime var"):
            generate_epub_reader_html_from_path(source_path=var_path)

    def test_render_html_escapes_text_metadata_and_translation(self):
        document = build_txt_reader_document(
            content=b"# <script>alert(1)</script>",
            translated_by_block_id={
                "txt:segment:1": "<b>Translated</b>",
            },
            source_name='bad "name".txt',
            generated_at=datetime(2026, 6, 1, tzinfo=UTC),
        )

        rendered = render_reader_html(document)

        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertIn("&lt;b&gt;Translated&lt;/b&gt;", rendered)
        self.assertIn("bad &quot;name&quot;.txt", rendered)
        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertNotIn("<b>Translated</b>", rendered)

    def test_load_translation_mapping_requires_json_object_with_string_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "translations.json"
            path.write_text(
                json.dumps({"txt:segment:1": "Заголовок"}),
                encoding="utf-8",
            )

            self.assertEqual(
                load_translation_mapping(path),
                {"txt:segment:1": "Заголовок"},
            )

            path.write_text(json.dumps(["not", "object"]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be an object"):
                load_translation_mapping(path)

            path.write_text(json.dumps({"txt:segment:1": 123}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "keys and values must be strings"):
                load_translation_mapping(path)

    def test_generate_txt_reader_html_rejects_runtime_var_paths(self):
        repo_root = Path(__file__).resolve().parents[1]
        var_path = repo_root / "var" / "internal-reader-test.txt"

        with self.assertRaisesRegex(ValueError, "runtime var"):
            generate_txt_reader_html_from_path(source_path=var_path)

        with self.assertRaisesRegex(ValueError, "runtime var"):
            reject_runtime_var_path(var_path)


def _make_epub(
    xhtml_items: dict[str, str],
    *,
    spine: tuple[str, ...],
) -> bytes:
    archive = BytesIO()
    manifest_items_by_file = {
        file_name: Path(file_name).stem for file_name in xhtml_items
    }

    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
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
        manifest = "\n".join(
            f'<item id="{item_id}" href="{Path(file_name).name}" '
            f'media-type="application/xhtml+xml" />'
            for file_name, item_id in manifest_items_by_file.items()
        )
        spine_items = "\n".join(f'<itemref idref="{item_id}" />' for item_id in spine)
        epub.writestr(
            "OPS/content.opf",
            f"""
            <package xmlns="http://www.idpf.org/2007/opf"
              xmlns:dc="http://purl.org/dc/elements/1.1/">
              <metadata>
                <dc:title>Reader Test</dc:title>
                <dc:language>en</dc:language>
              </metadata>
              <manifest>{manifest}</manifest>
              <spine>{spine_items}</spine>
            </package>
            """,
        )
        for file_name, content in xhtml_items.items():
            epub.writestr(file_name, content)
    return archive.getvalue()


if __name__ == "__main__":
    unittest.main()
