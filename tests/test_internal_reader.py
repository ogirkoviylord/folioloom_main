import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from translator_service.internal_reader import (
    READER_STATUS_DONE,
    READER_STATUS_MISSING,
    build_txt_reader_document,
    generate_txt_reader_html_from_path,
    load_translation_mapping,
    reject_runtime_var_path,
    render_reader_html,
)


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


if __name__ == "__main__":
    unittest.main()
