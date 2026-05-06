from __future__ import annotations

from html import escape
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from translator_service.russian_regression_samples import (
    format_russian_regression_sample_pack,
    russian_regression_samples,
)


ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = ROOT / "test_samples"
STABLE_ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def main() -> None:
    SAMPLES_DIR.mkdir(exist_ok=True)
    _write_txt()
    _write_russian_regression_txt()
    _write_docx()
    _write_russian_regression_docx()
    _write_epub()
    _write_russian_regression_epub()
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


def _write_russian_regression_txt() -> None:
    (SAMPLES_DIR / "russian_profile_regression.en-ru.txt").write_text(
        format_russian_regression_sample_pack(),
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
        _zip_writestr(docx, "[Content_Types].xml", content_types)
        _zip_writestr(docx, "_rels/.rels", relationships)
        _zip_writestr(docx, "word/document.xml", document_xml)
        _zip_writestr(docx, "word/header1.xml", _docx_part_xml("Sample header text"))
        _zip_writestr(docx, "word/footer1.xml", _docx_part_xml("Sample footer text"))
        _zip_writestr(docx, "word/footnotes.xml", _docx_part_xml("Sample footnote text"))
        _zip_writestr(docx, "word/endnotes.xml", _docx_part_xml("Sample endnote text"))
        _zip_writestr(docx, "word/comments.xml", _docx_part_xml("Sample comment text"))


def _write_russian_regression_docx() -> None:
    with ZipFile(SAMPLES_DIR / "russian_profile_regression.en-ru.docx", "w", ZIP_DEFLATED) as docx:
        _zip_writestr(docx, "[Content_Types].xml", _docx_content_types_xml())
        _zip_writestr(docx, "_rels/.rels", _docx_relationships_xml())
        _zip_writestr(docx, "word/document.xml", _russian_regression_docx_document_xml())
        _zip_writestr(
            docx,
            "word/header1.xml",
            _docx_part_xml("Russian profile regression header"),
        )
        _zip_writestr(
            docx,
            "word/footer1.xml",
            _docx_part_xml("Russian profile regression footer"),
        )
        _zip_writestr(
            docx,
            "word/footnotes.xml",
            _docx_part_xml("Footnote: preserve API endpoint terminology."),
        )
        _zip_writestr(
            docx,
            "word/endnotes.xml",
            _docx_part_xml("Endnote: preserve mixed-language labels where useful."),
        )
        _zip_writestr(
            docx,
            "word/comments.xml",
            _docx_part_xml("Comment: check Russian naturalness and protected text."),
        )


def _russian_regression_docx_document_xml() -> str:
    samples = russian_regression_samples()
    paragraphs = [
        _docx_paragraph("Russian Profile Regression"),
        _docx_paragraph("Manual QA sample for English and mixed-source translation into Russian."),
    ]
    for sample in samples[:6]:
        paragraphs.append(_docx_paragraph(f"{sample.sample_id}: {sample.source_text}"))
    rows = [
        ("Category", "Source text"),
        *[(sample.category, sample.source_text) for sample in samples[6:]],
    ]
    table_rows = []
    for left, right in rows:
        table_rows.append(
            "      <w:tr>\n"
            f"        <w:tc>{_docx_paragraph(left)}</w:tc>\n"
            f"        <w:tc>{_docx_paragraph(right)}</w:tc>\n"
            "      </w:tr>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        "  <w:body>\n"
        + "\n".join(f"    {paragraph}" for paragraph in paragraphs)
        + "\n    <w:tbl>\n"
        + "\n".join(table_rows)
        + "\n    </w:tbl>\n"
        "  </w:body>\n"
        "</w:document>\n"
    )


def _docx_paragraph(text: str) -> str:
    return f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>"


def _docx_part_xml(text: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{_docx_paragraph(text)}</w:body>
</w:document>
"""


def _docx_content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""


def _docx_relationships_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
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
        _zip_writestr(epub, "mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        _zip_writestr(epub, "META-INF/container.xml", container_xml)
        _zip_writestr(epub, "OPS/content.opf", content_opf)
        _zip_writestr(
            epub,
            "OPS/style.css",
            "body { font-family: serif; line-height: 1.45; } .body-text { margin: 1em 0; }",
        )
        _zip_writestr(epub, "OPS/chapter1.xhtml", chapter1)
        _zip_writestr(epub, "OPS/chapter2.xhtml", chapter2)


def _write_russian_regression_epub() -> None:
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
    <dc:identifier id="bookid">russian-profile-regression</dc:identifier>
    <dc:title>Russian Profile Regression</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="chapter1" href="ru-profile-1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter2" href="ru-profile-2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter1"/>
    <itemref idref="chapter2"/>
  </spine>
</package>
"""
    with ZipFile(SAMPLES_DIR / "russian_profile_regression.en-ru.epub", "w") as epub:
        _zip_writestr(epub, "mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        _zip_writestr(epub, "META-INF/container.xml", container_xml)
        _zip_writestr(epub, "OPS/content.opf", content_opf)
        for name, content in _russian_regression_epub_chapters().items():
            _zip_writestr(epub, name, content)


def _russian_regression_epub_chapters() -> dict[str, str]:
    samples = russian_regression_samples()
    chapter_one = _russian_regression_epub_chapter(
        title="Russian Profile Regression",
        samples=samples[:5],
        include_inline=True,
    )
    chapter_two = _russian_regression_epub_chapter(
        title="Mixed, Named Entities, And Protected Text",
        samples=samples[5:],
        include_inline=False,
    )
    return {
        "OPS/ru-profile-1.xhtml": chapter_one,
        "OPS/ru-profile-2.xhtml": chapter_two,
    }


def _russian_regression_epub_chapter(
    *,
    title: str,
    samples,
    include_inline: bool,
) -> str:
    paragraphs = []
    for sample in samples:
        source = escape(sample.source_text)
        if include_inline and sample.category == "technical":
            source = source.replace("API endpoint", "<strong>API endpoint</strong>")
        paragraphs.append(
            f'      <section id="{escape(sample.sample_id)}">\n'
            f"        <h2>{escape(sample.category)}</h2>\n"
            f"        <p>{source}</p>\n"
            f"        <p><em>{escape(sample.expected_text_type.value)}</em></p>\n"
            "      </section>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        f"  <head><title>{escape(title)}</title></head>\n"
        "  <body>\n"
        f"    <h1>{escape(title)}</h1>\n"
        + "\n".join(paragraphs)
        + "\n  </body>\n"
        "</html>\n"
    )


def _zip_writestr(
    archive: ZipFile,
    name: str,
    content: str,
    *,
    compress_type: int = ZIP_DEFLATED,
) -> None:
    info = ZipInfo(name, date_time=STABLE_ZIP_TIMESTAMP)
    info.compress_type = compress_type
    archive.writestr(info, content)


if __name__ == "__main__":
    main()
