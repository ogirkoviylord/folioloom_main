from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


MAX_ARCHIVE_ENTRY_COUNT = 512
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 20 * 1024 * 1024
MAX_XML_BYTES = 5 * 1024 * 1024
MAX_XML_DEPTH = 80
MAX_XML_ELEMENT_COUNT = 100_000
MAX_EPUB_TEXT_BLOCKS = 20_000


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
            validate_archive_members(docx)
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
    document = parse_xml_document(
        document_xml,
        parse_error_message="DOCX document XML is not readable",
    )

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
    from translator_service.format_adapters.epub_repair import (
        repair_epub_for_processing,
    )

    repaired = repair_epub_for_processing(content)
    try:
        with ZipFile(BytesIO(repaired.content)) as epub:
            validate_archive_members(epub)
            xhtml_files = _epub_text_item_names(epub)
            blocks: list[str] = []
            for file_name in xhtml_files:
                blocks.extend(_extract_xhtml_text_blocks(epub.read(file_name)))
                validate_epub_text_block_count(len(blocks))
    except (BadZipFile, KeyError) as error:
        raise TextExtractionError(
            "EPUB file does not contain readable book text"
        ) from error

    return blocks


def validate_archive_members(archive: ZipFile) -> None:
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_ENTRY_COUNT:
        raise TextExtractionError("Document archive contains too many files")

    total_uncompressed = 0
    member_names: set[str] = set()
    for member in members:
        if member.filename in member_names:
            raise TextExtractionError("Document archive contains duplicate file names")
        member_names.add(member.filename)
        if member.file_size > MAX_ARCHIVE_MEMBER_BYTES:
            raise TextExtractionError("Document archive member is too large")
        total_uncompressed += member.file_size
        if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise TextExtractionError("Document archive is too large after extraction")


def parse_xml_document(content: bytes, *, parse_error_message: str) -> ElementTree.Element:
    validate_xml_bytes(content)
    try:
        document = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise TextExtractionError(parse_error_message) from error
    validate_xml_tree(document)
    return document


def validate_xml_bytes(content: bytes) -> None:
    if len(content) > MAX_XML_BYTES:
        raise TextExtractionError("Document XML part is too large")

    lowered = content.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise TextExtractionError("Document XML entities are not supported")


def validate_xml_tree(document: ElementTree.Element) -> None:
    element_count = 0
    stack: list[tuple[ElementTree.Element, int]] = [(document, 1)]
    while stack:
        element, depth = stack.pop()
        element_count += 1
        if element_count > MAX_XML_ELEMENT_COUNT:
            raise TextExtractionError("Document XML contains too many elements")
        if depth > MAX_XML_DEPTH:
            raise TextExtractionError("Document XML nesting is too deep")
        stack.extend((child, depth + 1) for child in list(element))


def validate_epub_text_block_count(block_count: int) -> None:
    if block_count > MAX_EPUB_TEXT_BLOCKS:
        raise TextExtractionError("EPUB file contains too many text blocks")


def _extract_xhtml_text_blocks(content: bytes) -> list[str]:
    document = parse_xml_document(
        content,
        parse_error_message="EPUB XHTML content is not readable",
    )

    blocks: list[str] = []
    for element in document.iter():
        if not _is_epub_text_element(element):
            continue

        text = _visible_text(element)
        if text:
            blocks.append(text)
            validate_epub_text_block_count(len(blocks))

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
    ordered: list[str] = []
    seen_names: set[str] = set()
    for name in spine_names:
        if name in archive_name_set and name not in seen_names:
            ordered.append(name)
            seen_names.add(name)
    for name in archive_names:
        if name not in seen_names:
            ordered.append(name)
            seen_names.add(name)
    return ordered


def _epub_spine_text_item_names(epub: ZipFile) -> list[str]:
    try:
        container = parse_xml_document(
            epub.read("META-INF/container.xml"),
            parse_error_message="EPUB container XML is not readable",
        )
    except KeyError:
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
        package = parse_xml_document(
            epub.read(opf_path),
            parse_error_message="EPUB package XML is not readable",
        )
    except KeyError:
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
