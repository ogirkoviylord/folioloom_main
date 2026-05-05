from io import BytesIO
from pathlib import PurePosixPath
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
    paragraphs = extract_docx_text_blocks(content)
    text = "\n\n".join(paragraphs)
    if not text.strip():
        raise TextExtractionError("DOCX file does not contain translatable text")

    return text


def extract_docx_text_blocks(content: bytes) -> list[str]:
    try:
        with ZipFile(BytesIO(content)) as docx:
            part_names = _docx_text_part_names(docx)
            if "word/document.xml" not in docx.namelist():
                raise KeyError("word/document.xml")
            paragraphs: list[str] = []
            for part_name in part_names:
                paragraphs.extend(_extract_docx_part_text_blocks(docx.read(part_name)))
    except (BadZipFile, KeyError) as error:
        raise TextExtractionError(
            "DOCX file does not contain readable document text"
        ) from error

    if not paragraphs:
        raise TextExtractionError("DOCX file does not contain translatable text")

    return paragraphs


def _extract_docx_part_text_blocks(document_xml: bytes) -> list[str]:
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

    return paragraphs


def _docx_text_part_names(docx: ZipFile) -> list[str]:
    names = set(docx.namelist())
    ordered: list[str] = []
    if "word/document.xml" in names:
        ordered.append("word/document.xml")
    ordered.extend(_sorted_docx_numbered_parts(names, "word/header", ".xml"))
    ordered.extend(_sorted_docx_numbered_parts(names, "word/footer", ".xml"))
    for optional_part in (
        "word/footnotes.xml",
        "word/endnotes.xml",
        "word/comments.xml",
    ):
        if optional_part in names:
            ordered.append(optional_part)
    return ordered


def _sorted_docx_numbered_parts(
    names: set[str],
    prefix: str,
    suffix: str,
) -> list[str]:
    def sort_key(name: str) -> tuple[int, str]:
        number = name.removeprefix(prefix).removesuffix(suffix)
        return (int(number) if number.isdigit() else 0, name)

    return sorted(
        (
            name
            for name in names
            if name.startswith(prefix) and name.endswith(suffix)
        ),
        key=sort_key,
    )


def extract_text_from_epub(content: bytes) -> str:
    blocks = extract_epub_text_blocks(content)
    text = "\n\n".join(blocks)
    if not text.strip():
        raise TextExtractionError("EPUB file does not contain translatable text")

    return text


def extract_epub_text_blocks(content: bytes) -> list[str]:
    try:
        with ZipFile(BytesIO(content)) as epub:
            xhtml_files = _epub_text_item_names(epub)
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
        if not _is_epub_text_element(element):
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


def _epub_text_item_names(epub: ZipFile) -> list[str]:
    archive_names = [
        item.filename
        for item in epub.infolist()
        if _is_epub_text_item(item.filename)
    ]
    spine_names = _epub_spine_text_item_names(epub)
    if not spine_names:
        return archive_names

    archive_name_set = set(archive_names)
    ordered = [name for name in spine_names if name in archive_name_set]
    ordered.extend(name for name in archive_names if name not in set(ordered))
    return ordered


def _epub_spine_text_item_names(epub: ZipFile) -> list[str]:
    try:
        container = ElementTree.fromstring(epub.read("META-INF/container.xml"))
    except (KeyError, ElementTree.ParseError):
        return []

    rootfile = next(
        (
            element
            for element in container.iter()
            if _local_name(element.tag) == "rootfile"
        ),
        None,
    )
    if rootfile is None:
        return []

    opf_path = rootfile.attrib.get("full-path")
    if not opf_path:
        return []

    try:
        package = ElementTree.fromstring(epub.read(opf_path))
    except (KeyError, ElementTree.ParseError):
        return []

    manifest = {
        item.attrib.get("id"): item.attrib.get("href")
        for item in package.iter()
        if _local_name(item.tag) == "item"
    }
    base_path = PurePosixPath(opf_path).parent
    if str(base_path) == ".":
        base_path = PurePosixPath("")

    names: list[str] = []
    for itemref in package.iter():
        if _local_name(itemref.tag) != "itemref":
            continue
        href = manifest.get(itemref.attrib.get("idref"))
        if not href:
            continue
        file_name = _resolve_epub_href(base_path=base_path, href=href, epub=epub)
        if _is_epub_text_item(file_name):
            names.append(file_name)
    return names


def _resolve_epub_href(*, base_path: PurePosixPath, href: str, epub: ZipFile) -> str:
    candidate = str(base_path / href)
    if candidate in epub.namelist():
        return candidate
    return href


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _is_epub_text_element(element: ElementTree.Element) -> bool:
    if _local_name(element.tag) not in _EPUB_TEXT_BLOCK_TAGS:
        return False

    return not any(
        _local_name(descendant.tag) in _EPUB_TEXT_BLOCK_TAGS
        for child in list(element)
        for descendant in child.iter()
    )


_EPUB_TEXT_BLOCK_TAGS = {
    "article",
    "aside",
    "blockquote",
    "caption",
    "dd",
    "div",
    "dt",
    "figcaption",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "p",
    "section",
    "td",
    "th",
}
_EPUB_IGNORED_TAGS = {"head", "script", "style", "svg"}
