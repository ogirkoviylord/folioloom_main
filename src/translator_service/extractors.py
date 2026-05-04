from io import BytesIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


class TextExtractionError(ValueError):
    pass


def extract_text_from_txt(content: bytes) -> str:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise TextExtractionError("TXT file must contain UTF-8 text") from error

    if not text.strip():
        raise TextExtractionError("TXT file does not contain translatable text")

    return text


def extract_text_from_docx(content: bytes) -> str:
    try:
        with ZipFile(BytesIO(content)) as docx:
            document_xml = docx.read("word/document.xml")
    except (BadZipFile, KeyError) as error:
        raise TextExtractionError(
            "DOCX file does not contain readable document text"
        ) from error

    try:
        document = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as error:
        raise TextExtractionError("DOCX document XML is not readable") from error

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []

    for paragraph in document.findall(".//w:p", namespace):
        pieces = [
            text_node.text or ""
            for text_node in paragraph.findall(".//w:t", namespace)
        ]
        paragraph_text = "".join(pieces).strip()
        if paragraph_text:
            paragraphs.append(paragraph_text)

    text = "\n\n".join(paragraphs)
    if not text.strip():
        raise TextExtractionError("DOCX file does not contain translatable text")

    return text


def extract_text_from_epub(content: bytes) -> str:
    blocks = extract_epub_text_blocks(content)
    text = "\n\n".join(blocks)
    if not text.strip():
        raise TextExtractionError("EPUB file does not contain translatable text")

    return text


def extract_epub_text_blocks(content: bytes) -> list[str]:
    try:
        with ZipFile(BytesIO(content)) as epub:
            xhtml_files = [
                item.filename
                for item in epub.infolist()
                if _is_epub_text_item(item.filename)
            ]
            blocks: list[str] = []
            for file_name in xhtml_files:
                blocks.extend(_extract_xhtml_text_blocks(epub.read(file_name)))
    except (BadZipFile, KeyError) as error:
        raise TextExtractionError(
            "EPUB file does not contain readable book text"
        ) from error

    return blocks


def _extract_xhtml_text_blocks(content: bytes) -> list[str]:
    try:
        document = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise TextExtractionError("EPUB XHTML content is not readable") from error

    blocks: list[str] = []
    for element in document.iter():
        if _local_name(element.tag) not in _EPUB_TEXT_BLOCK_TAGS:
            continue

        text = _visible_text(element)
        if text:
            blocks.append(text)

    return blocks


def _visible_text(element: ElementTree.Element) -> str:
    pieces = list(_iter_visible_text(element))
    return " ".join("".join(pieces).split())


def _iter_visible_text(element: ElementTree.Element):
    if _local_name(element.tag) in _EPUB_IGNORED_TAGS:
        return

    if element.text:
        yield element.text

    for child in list(element):
        yield from _iter_visible_text(child)
        if child.tail:
            yield child.tail


def _is_epub_text_item(file_name: str) -> bool:
    lowered = file_name.lower()
    return lowered.endswith((".xhtml", ".html", ".htm"))


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


_EPUB_TEXT_BLOCK_TAGS = {
    "blockquote",
    "caption",
    "dd",
    "dt",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "p",
    "td",
    "th",
}
_EPUB_IGNORED_TAGS = {"head", "script", "style", "svg"}
