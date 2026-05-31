import unittest
from io import BytesIO
from zipfile import ZipFile

from translator_service.extractors import TextExtractionError
from translator_service.format_adapters.epub_repair import repair_epub_for_processing


def _make_epub(
    members: dict[str, bytes | str],
    *,
    ncx_content: bytes | str | None = None,
) -> bytes:
    archive = BytesIO()
    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        for file_name, content in members.items():
            epub.writestr(file_name, content)
        if ncx_content is not None:
            epub.writestr("OPS/toc.ncx", ncx_content)
    return archive.getvalue()


class EpubRepairTests(unittest.TestCase):
    def test_repairs_xhtml_and_ncx_doctype_and_named_entities(self):
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
                  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>One&nbsp;&mdash;&nbsp;two.</p></body>
                </html>
                """,
            },
            ncx_content="""
            <!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"
              "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
            <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
              <docTitle><text>Old&nbsp;TOC</text></docTitle>
            </ncx>
            """,
        )

        repaired = repair_epub_for_processing(content)

        self.assertTrue(repaired.report.repaired)
        action_kinds = {action.kind for action in repaired.report.actions}
        self.assertIn("strip_external_doctype", action_kinds)
        self.assertIn("replace_named_entities", action_kinds)
        with ZipFile(BytesIO(repaired.content)) as epub:
            chapter = epub.read("OPS/chapter.xhtml")
            toc = epub.read("OPS/toc.ncx")
        self.assertNotIn(b"<!DOCTYPE", chapter)
        self.assertNotIn(b"<!DOCTYPE", toc)
        self.assertNotIn(b"&nbsp;", chapter)
        self.assertNotIn(b"&nbsp;", toc)
        self.assertIn(b"&#160;", chapter)
        self.assertIn(b"&#8212;", chapter)

    def test_rejects_custom_entity_definitions(self):
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <!DOCTYPE html [<!ENTITY injected "boom">]>
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>&injected;</p></body>
                </html>
                """,
            }
        )

        with self.assertRaisesRegex(
            TextExtractionError,
            "XML entities are not supported",
        ):
            repair_epub_for_processing(content)

    def test_strips_simple_html_doctype(self):
        content = _make_epub(
            {
                "OPS/cover.xhtml": """
                <!DOCTYPE html>
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>Cover</p></body>
                </html>
                """,
            }
        )

        repaired = repair_epub_for_processing(content)

        action_kinds = {action.kind for action in repaired.report.actions}
        self.assertIn("strip_simple_doctype", action_kinds)
        with ZipFile(BytesIO(repaired.content)) as epub:
            cover = epub.read("OPS/cover.xhtml")
        self.assertNotIn(b"<!DOCTYPE", cover)
        self.assertIn(b"<p>Cover</p>", cover)

    def test_rejects_epub_zip_path_traversal_members(self):
        archive = BytesIO()
        with ZipFile(archive, "w") as epub:
            epub.writestr("mimetype", "application/epub+zip")
            epub.writestr("../OPS/chapter.xhtml", "<html />")

        with self.assertRaisesRegex(TextExtractionError, "unsafe file path"):
            repair_epub_for_processing(archive.getvalue())

    def test_preserves_binary_resources(self):
        image_bytes = b"\x89PNG\r\n\x1a\nbinary-image-content"
        content = _make_epub(
            {
                "OPS/chapter.xhtml": "<html xmlns=\"http://www.w3.org/1999/xhtml\" />",
                "OPS/image.png": image_bytes,
            }
        )

        repaired = repair_epub_for_processing(content)

        with ZipFile(BytesIO(repaired.content)) as epub:
            self.assertEqual(image_bytes, epub.read("OPS/image.png"))

    def test_noop_report_when_no_repairs_needed(self):
        chapter = b'<html xmlns="http://www.w3.org/1999/xhtml"><body /></html>'
        content = _make_epub({"OPS/chapter.xhtml": chapter})

        repaired = repair_epub_for_processing(content)

        self.assertFalse(repaired.report.repaired)
        with ZipFile(BytesIO(repaired.content)) as epub:
            self.assertEqual(chapter, epub.read("OPS/chapter.xhtml"))


if __name__ == "__main__":
    unittest.main()
