"""Generate original, deterministic long-form EPUB regression material."""
from html import escape
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_STORED, ZIP_DEFLATED

TARGET_TEXT_LENGTH = 357401
PARAGRAPH = (
    "Mira Lark and Captain Stone examine three dimensions at Copper Harbor. "
    "The Silver Compass records each measurement in the Field Ledger. "
    "Then He checks the labels while the group compares the drawing with the physical model. "
    "Their notes describe a fictional experiment created solely for document-processing tests. "
)

def generate(destination: Path) -> None:
    # Repetition tests large-document handling without distributing a third-party book.
    paragraphs = []
    names = ["Mira Lark", "Oren Vale", "Tessa Reed", "Nola Finch", "Arin Moss", "Lena Grove", "Kira Brook", "Sera Pine", "Dara Fern", "Rina Marsh", "Ira Field", "Neri Stone", "Tarin Cove", "Vela Frost", "Kora Ash", "Nira Wren", "Eren Leaf", "Sila Shore", "Rori Dune", "Lira Elm"]
    for index in range(1800):
        name = names[index % len(names)]
        measurement = "three dimensions" if index % 20 == 0 else "a numbered measurement"
        paragraphs.append(f"{name} examines {measurement} in the workshop. Then He checks the labels while the group compares the drawing with the physical model. Their notes describe a fictional experiment created solely for document-processing tests, with original text and recurring names. The group records the result before moving to the next part of the model.")
    text = "\n\n".join(paragraphs)[:TARGET_TEXT_LENGTH]
    container = '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
    package = '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">synthetic-glossary-control</dc:identifier><dc:title>Synthetic Glossary Control</dc:title><dc:language>en</dc:language></metadata><manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="chapter"/></spine></package>'
    chapter = '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Synthetic Glossary Control</title></head><body><p>' + '</p><p>'.join(escape(p) for p in text.split('\n\n')) + '</p></body></html>'
    with ZipFile(destination, 'w') as archive:
        for name, content in [('mimetype', 'application/epub+zip'), ('META-INF/container.xml', container), ('OPS/content.opf', package), ('OPS/chapter.xhtml', chapter)]:
            info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED if name == 'mimetype' else ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)

if __name__ == '__main__':
    generate(Path(__file__).resolve().parents[1] / 'test_samples/synthetic_glossary_control.en.epub')
