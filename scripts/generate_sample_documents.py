from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = ROOT / "test_samples"


def main() -> None:
    SAMPLES_DIR.mkdir(exist_ok=True)
    _write_txt()
    _write_docx()
    _write_epub()
    print(f"Sample documents written to {SAMPLES_DIR}")


def _write_txt() -> None:
    (SAMPLES_DIR / "sample_book.en.txt").write_text(
        "\n\n".join(
            [
                "Chapter 1",
                "This is the first paragraph of a sample book. It has enough text to look like a real paragraph.",
                "The second paragraph mentions a term: neural translation. The term should stay meaningful after translation.",
                "Chapter 2",
                "A short list follows:\n- First item\n- Second item\n- Third item",
            ]
        ),
        encoding="utf-8",
    )


def _write_docx() -> None:
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Chapter 1</w:t></w:r></w:p>
    <w:p>
      <w:r><w:t>This DOCX paragraph has </w:t></w:r>
      <w:r><w:rPr><w:b /></w:rPr><w:t>bold text</w:t></w:r>
      <w:r><w:t> in a separate styled run.</w:t></w:r>
    </w:p>
    <w:p><w:r><w:t>Second paragraph with a named term: neural translation.</w:t></w:r></w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Source</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Target</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>World</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>
"""
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    relationships = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""

    with ZipFile(SAMPLES_DIR / "sample_book.en.docx", "w", ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", relationships)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/header1.xml", _docx_part_xml("Sample header text"))
        docx.writestr("word/footer1.xml", _docx_part_xml("Sample footer text"))
        docx.writestr("word/footnotes.xml", _docx_part_xml("Sample footnote text"))
        docx.writestr("word/endnotes.xml", _docx_part_xml("Sample endnote text"))
        docx.writestr("word/comments.xml", _docx_part_xml("Sample comment text"))


def _docx_part_xml(text: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>
</w:document>
"""


def _write_epub() -> None:
    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    content_opf = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">sample-book</dc:identifier>
    <dc:title>Sample Book</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="style" href="style.css" media-type="text/css"/>
    <item id="chapter1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter2" href="chapter2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter1"/>
    <itemref idref="chapter2"/>
  </spine>
</package>
"""
    chapter1 = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Chapter 1</title><link rel="stylesheet" href="style.css" /></head>
  <body>
    <section class="chapter">
      <h1>Chapter 1</h1>
      <div class="body-text">This line is intentionally stored in a div, not a paragraph.</div>
      <p>This paragraph contains <strong>bold text</strong>, <em>emphasis</em> and a <a href="#note1">note link</a>.</p>
      <ul>
        <li>First list item</li>
        <li>Second list item</li>
      </ul>
    </section>
  </body>
</html>
"""
    chapter2 = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Chapter 2</title><link rel="stylesheet" href="style.css" /></head>
  <body>
    <section class="chapter">
      <h1>Chapter 2</h1>
      <table>
        <tr><th>Term</th><th>Meaning</th></tr>
        <tr><td>Context</td><td>Surrounding text that affects translation.</td></tr>
      </table>
      <p id="note1">Footnote text should also be translated.</p>
    </section>
  </body>
</html>
"""

    with ZipFile(SAMPLES_DIR / "sample_book.en.epub", "w") as epub:
        epub.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        epub.writestr("META-INF/container.xml", container_xml, compress_type=ZIP_DEFLATED)
        epub.writestr("OPS/content.opf", content_opf, compress_type=ZIP_DEFLATED)
        epub.writestr(
            "OPS/style.css",
            "body { font-family: serif; line-height: 1.45; } .body-text { margin: 1em 0; }",
            compress_type=ZIP_DEFLATED,
        )
        epub.writestr("OPS/chapter1.xhtml", chapter1, compress_type=ZIP_DEFLATED)
        epub.writestr("OPS/chapter2.xhtml", chapter2, compress_type=ZIP_DEFLATED)


if __name__ == "__main__":
    main()
