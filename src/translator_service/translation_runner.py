from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from typing import Callable
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from translator_service.extractors import TextExtractionError, extract_text_from_txt
from translator_service.text_analysis import split_text_into_fragments
from translator_service.translation_jobs import TextTranslator, translate_text_fragments


@dataclass(frozen=True)
class TranslatedDocument:
    file_name: str
    content_type: str
    content: bytes
    fragment_count: int


def translate_txt_document(
    *,
    file_name: str,
    content: bytes,
    source_language: str,
    target_language: str,
    max_fragment_chars: int,
    translator: TextTranslator,
    progress_callback: Callable[[tuple[int, int]], None] | None = None,
) -> TranslatedDocument:
    text = extract_text_from_txt(content)
    fragments = split_text_into_fragments(text, max_fragment_chars=max_fragment_chars)
    translation = translate_text_fragments(
        fragments=fragments,
        source_language=source_language,
        target_language=target_language,
        translator=translator,
        progress_callback=progress_callback,
    )

    return TranslatedDocument(
        file_name=_translated_txt_file_name(file_name, target_language),
        content_type="text/plain; charset=utf-8",
        content=translation.assembled_text.encode("utf-8"),
        fragment_count=len(translation.fragments),
    )


def translate_docx_document(
    *,
    file_name: str,
    content: bytes,
    source_language: str,
    target_language: str,
    translator: TextTranslator,
    progress_callback: Callable[[tuple[int, int]], None] | None = None,
) -> TranslatedDocument:
    paragraphs = _extract_docx_paragraphs(content)
    translation = translate_text_fragments(
        fragments=paragraphs,
        source_language=source_language,
        target_language=target_language,
        translator=translator,
        progress_callback=progress_callback,
    )
    translated_content = _replace_docx_paragraphs(
        content,
        [fragment.translated_text for fragment in translation.fragments],
    )

    return TranslatedDocument(
        file_name=_translated_file_name(file_name, target_language, "docx"),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=translated_content,
        fragment_count=len(translation.fragments),
    )


def translate_epub_document(
    *,
    file_name: str,
    content: bytes,
    source_language: str,
    target_language: str,
    translator: TextTranslator,
    progress_callback: Callable[[tuple[int, int]], None] | None = None,
) -> TranslatedDocument:
    blocks = _extract_epub_blocks(content)
    translation = translate_text_fragments(
        fragments=[block.text for block in blocks],
        source_language=source_language,
        target_language=target_language,
        translator=translator,
        progress_callback=progress_callback,
    )
    translated_content = _replace_epub_blocks(
        content,
        blocks,
        [fragment.translated_text for fragment in translation.fragments],
    )

    return TranslatedDocument(
        file_name=_translated_file_name(file_name, target_language, "epub"),
        content_type="application/epub+zip",
        content=translated_content,
        fragment_count=len(translation.fragments),
    )


def _translated_txt_file_name(file_name: str, target_language: str) -> str:
    return _translated_file_name(file_name, target_language, "txt")


def _translated_file_name(file_name: str, target_language: str, extension: str) -> str:
    path = PurePath(file_name)
    stem = path.stem if path.suffix else file_name
    return f"{stem}.{target_language}.{extension}"


def _extract_docx_paragraphs(content: bytes) -> list[str]:
    document = _read_docx_document_xml(content)
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

    if not paragraphs:
        raise TextExtractionError("DOCX file does not contain translatable text")

    return paragraphs


def _replace_docx_paragraphs(content: bytes, translated_paragraphs: list[str]) -> bytes:
    document = _read_docx_document_xml(content)
    namespace_uri = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    namespace = {"w": namespace_uri}
    ElementTree.register_namespace("w", namespace_uri)
    translated_iter = iter(translated_paragraphs)

    for paragraph in document.findall(".//w:p", namespace):
        text_nodes = paragraph.findall(".//w:t", namespace)
        if not text_nodes:
            continue

        original_text = "".join(text_node.text or "" for text_node in text_nodes).strip()
        if not original_text:
            continue

        translated_text = next(translated_iter)
        text_nodes[0].text = translated_text
        for text_node in text_nodes[1:]:
            text_node.text = ""

    document_xml = ElementTree.tostring(
        document,
        encoding="utf-8",
        xml_declaration=True,
    )
    return _replace_docx_file(content, "word/document.xml", document_xml)


def _read_docx_document_xml(content: bytes) -> ElementTree.Element:
    try:
        with ZipFile(BytesIO(content)) as docx:
            document_xml = docx.read("word/document.xml")
    except Exception as error:
        raise TextExtractionError(
            "DOCX file does not contain readable document text"
        ) from error

    try:
        return ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as error:
        raise TextExtractionError("DOCX document XML is not readable") from error


def _replace_docx_file(content: bytes, file_name: str, replacement: bytes) -> bytes:
    source = BytesIO(content)
    target = BytesIO()

    with ZipFile(source) as source_docx, ZipFile(target, "w") as target_docx:
        for item in source_docx.infolist():
            data = replacement if item.filename == file_name else source_docx.read(item)
            target_docx.writestr(item, data)

    return target.getvalue()


@dataclass(frozen=True)
class _EpubTextBlock:
    file_name: str
    block_index: int
    text: str


def _extract_epub_blocks(content: bytes) -> list[_EpubTextBlock]:
    try:
        with ZipFile(BytesIO(content)) as epub:
            blocks: list[_EpubTextBlock] = []
            for item in epub.infolist():
                if not _is_epub_text_item(item.filename):
                    continue
                document = _read_epub_xhtml(epub.read(item.filename))
                for block_index, element in enumerate(_iter_epub_text_elements(document)):
                    text = _visible_text(element)
                    if text:
                        blocks.append(
                            _EpubTextBlock(
                                file_name=item.filename,
                                block_index=block_index,
                                text=text,
                            )
                        )
    except (BadZipFile, KeyError) as error:
        raise TextExtractionError(
            "EPUB file does not contain readable book text"
        ) from error

    if not blocks:
        raise TextExtractionError("EPUB file does not contain translatable text")

    return blocks


def _replace_epub_blocks(
    content: bytes,
    blocks: list[_EpubTextBlock],
    translated_blocks: list[str],
) -> bytes:
    replacements_by_file: dict[str, dict[int, str]] = {}
    for block, translated_text in zip(blocks, translated_blocks, strict=True):
        replacements_by_file.setdefault(block.file_name, {})[
            block.block_index
        ] = translated_text

    source = BytesIO(content)
    target = BytesIO()

    with ZipFile(source) as source_epub, ZipFile(target, "w") as target_epub:
        for item in source_epub.infolist():
            data = source_epub.read(item)
            if item.filename in replacements_by_file:
                data = _replace_epub_xhtml_blocks(
                    data,
                    replacements_by_file[item.filename],
                )
            target_epub.writestr(item, data)

    return target.getvalue()


def _replace_epub_xhtml_blocks(content: bytes, replacements: dict[int, str]) -> bytes:
    document = _read_epub_xhtml(content)

    for block_index, element in enumerate(_iter_epub_text_elements(document)):
        if block_index not in replacements:
            continue

        element.text = replacements[block_index]
        for child in list(element):
            child.text = ""
            child.tail = ""

    return ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)


def _read_epub_xhtml(content: bytes) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise TextExtractionError("EPUB XHTML content is not readable") from error


def _iter_epub_text_elements(document: ElementTree.Element):
    for element in document.iter():
        if _local_name(element.tag) in _EPUB_TEXT_BLOCK_TAGS:
            yield element


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
