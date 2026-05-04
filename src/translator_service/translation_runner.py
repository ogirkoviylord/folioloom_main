from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath, PurePosixPath
import html
from typing import Callable
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from translator_service.extractors import TextExtractionError, extract_text_from_txt
from translator_service.text_analysis import split_text_into_fragments
from translator_service.translation_jobs import (
    CancellationToken,
    FragmentTranslation,
    TextTranslator,
    TranslationCancelled,
    TranslationJobResult,
    translate_text_fragments,
)


@dataclass(frozen=True)
class TranslatedDocument:
    file_name: str
    content_type: str
    content: bytes
    fragment_count: int
    is_partial: bool = False


def translate_txt_document(
    *,
    file_name: str,
    content: bytes,
    source_language: str,
    target_language: str,
    max_fragment_chars: int,
    translator: TextTranslator,
    progress_callback: Callable[[tuple[int, int]], None] | None = None,
    cancellation_token: CancellationToken | None = None,
) -> TranslatedDocument:
    text = extract_text_from_txt(content)
    fragments = split_text_into_fragments(text, max_fragment_chars=max_fragment_chars)
    try:
        translation = translate_text_fragments(
            fragments=fragments,
            source_language=source_language,
            target_language=target_language,
            translator=translator,
            progress_callback=progress_callback,
            cancellation_token=cancellation_token,
        )
        is_partial = False
    except TranslationCancelled as error:
        translation = error.partial_result
        is_partial = True

    return TranslatedDocument(
        file_name=_translated_txt_file_name(file_name, target_language, is_partial),
        content_type="text/plain; charset=utf-8",
        content=translation.assembled_text.encode("utf-8"),
        fragment_count=len(translation.fragments),
        is_partial=is_partial,
    )


def translate_docx_document(
    *,
    file_name: str,
    content: bytes,
    source_language: str,
    target_language: str,
    translator: TextTranslator,
    max_fragment_chars: int = 4_000,
    progress_callback: Callable[[tuple[int, int]], None] | None = None,
    cancellation_token: CancellationToken | None = None,
) -> TranslatedDocument:
    paragraphs = _extract_docx_paragraphs(content)
    translation_units = _group_text_blocks(
        paragraphs,
        max_fragment_chars=max_fragment_chars,
    )
    try:
        translation = _translate_marked_text_units(
            units=translation_units,
            source_language=source_language,
            target_language=target_language,
            translator=translator,
            progress_callback=progress_callback,
            cancellation_token=cancellation_token,
        )
        is_partial = False
    except TranslationCancelled as error:
        translation = error.partial_result
        is_partial = True
    translated_content = _replace_docx_paragraphs(
        content,
        [fragment.translated_text for fragment in translation.fragments],
    )

    return TranslatedDocument(
        file_name=_translated_file_name(file_name, target_language, "docx", is_partial),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=translated_content,
        fragment_count=len(translation_units)
        if not is_partial
        else _count_translated_text_units(
            translation.fragments,
            translation_units=translation_units,
        ),
        is_partial=is_partial,
    )


def translate_epub_document(
    *,
    file_name: str,
    content: bytes,
    source_language: str,
    target_language: str,
    translator: TextTranslator,
    max_fragment_chars: int = 4_000,
    progress_callback: Callable[[tuple[int, int]], None] | None = None,
    cancellation_token: CancellationToken | None = None,
) -> TranslatedDocument:
    blocks = _extract_epub_blocks(content)
    translation_units = _group_epub_blocks(
        blocks,
        max_fragment_chars=max_fragment_chars,
    )
    try:
        translation = _translate_epub_units(
            units=translation_units,
            source_language=source_language,
            target_language=target_language,
            translator=translator,
            progress_callback=progress_callback,
            cancellation_token=cancellation_token,
        )
        is_partial = False
    except TranslationCancelled as error:
        translation = error.partial_result
        is_partial = True
    translated_content = _replace_epub_blocks(
        content,
        blocks,
        [fragment.translated_text for fragment in translation.fragments],
    )

    return TranslatedDocument(
        file_name=_translated_file_name(file_name, target_language, "epub", is_partial),
        content_type="application/epub+zip",
        content=translated_content,
        fragment_count=len(translation_units)
        if not is_partial
        else _count_translated_epub_units(
            translation.fragments,
            translation_units=translation_units,
        ),
        is_partial=is_partial,
    )


def _translated_txt_file_name(
    file_name: str,
    target_language: str,
    is_partial: bool = False,
) -> str:
    return _translated_file_name(file_name, target_language, "txt", is_partial)


def _translated_file_name(
    file_name: str,
    target_language: str,
    extension: str,
    is_partial: bool = False,
) -> str:
    path = PurePath(file_name)
    stem = path.stem if path.suffix else file_name
    partial = ".partial" if is_partial else ""
    return f"{stem}.{target_language}{partial}.{extension}"


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

        translated_text = next(translated_iter, None)
        if translated_text is None:
            continue
        _replace_text_node_sequence(
            [(text_node, "text") for text_node in text_nodes],
            translated_text,
        )

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


def _group_text_blocks(
    blocks: list[str],
    *,
    max_fragment_chars: int,
) -> list[_TextTranslationUnit]:
    if not blocks:
        return []

    units: list[_TextTranslationUnit] = []
    current: list[tuple[int, str]] = []
    current_length = 0

    for index, text in enumerate(blocks):
        text_length = len(text)
        separator_length = 2 if current else 0
        candidate_length = current_length + separator_length + text_length
        if current and candidate_length > max_fragment_chars:
            units.append(_TextTranslationUnit(indexed_texts=current))
            current = [(index, text)]
            current_length = text_length
            continue

        current.append((index, text))
        current_length = candidate_length

    if current:
        units.append(_TextTranslationUnit(indexed_texts=current))

    return units


@dataclass(frozen=True)
class _EpubTextBlock:
    file_name: str
    block_index: int
    text: str


@dataclass(frozen=True)
class _EpubTranslationUnit:
    blocks: list[_EpubTextBlock]

    @property
    def text(self) -> str:
        return _format_translation_batch([block.text for block in self.blocks])


@dataclass(frozen=True)
class _TextTranslationUnit:
    indexed_texts: list[tuple[int, str]]

    @property
    def text(self) -> str:
        return _format_translation_batch([text for _, text in self.indexed_texts])


def _extract_epub_blocks(content: bytes) -> list[_EpubTextBlock]:
    try:
        with ZipFile(BytesIO(content)) as epub:
            blocks: list[_EpubTextBlock] = []
            for file_name in _epub_text_item_names(epub):
                document = _read_epub_xhtml(epub.read(file_name))
                for block_index, element in enumerate(_iter_epub_text_elements(document)):
                    text = _visible_text(element)
                    if text:
                        blocks.append(
                            _EpubTextBlock(
                                file_name=file_name,
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
    for block, translated_text in zip(blocks, translated_blocks, strict=False):
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


def _group_epub_blocks(
    blocks: list[_EpubTextBlock],
    *,
    max_fragment_chars: int,
) -> list[_EpubTranslationUnit]:
    if not blocks:
        return []

    units: list[_EpubTranslationUnit] = []
    current: list[_EpubTextBlock] = []
    current_length = 0

    for block in blocks:
        block_length = len(block.text)
        separator_length = 2 if current else 0
        candidate_length = current_length + separator_length + block_length
        if current and candidate_length > max_fragment_chars:
            units.append(_EpubTranslationUnit(blocks=current))
            current = [block]
            current_length = block_length
            continue

        current.append(block)
        current_length = candidate_length

    if current:
        units.append(_EpubTranslationUnit(blocks=current))

    return units


def _translate_epub_units(
    *,
    units: list[_EpubTranslationUnit],
    source_language: str,
    target_language: str,
    translator: TextTranslator,
    progress_callback: Callable[[tuple[int, int]], None] | None = None,
    cancellation_token: CancellationToken | None = None,
):
    translated_blocks = []
    total_units = len(units)

    for unit_index, unit in enumerate(units):
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise TranslationCancelled(_build_epub_translation_result(translated_blocks))

        translated_text = translator.translate(
            text=unit.text,
            source_language=source_language,
            target_language=target_language,
        )
        translated_unit_blocks = _parse_epub_translation_unit(
            translated_text,
            source_blocks=unit.blocks,
            translator=translator,
            source_language=source_language,
            target_language=target_language,
        )
        translated_blocks.extend(translated_unit_blocks)
        if progress_callback is not None:
            progress_callback((unit_index + 1, total_units))

    return _build_epub_translation_result(translated_blocks)


def _translate_marked_text_units(
    *,
    units: list[_TextTranslationUnit],
    source_language: str,
    target_language: str,
    translator: TextTranslator,
    progress_callback: Callable[[tuple[int, int]], None] | None = None,
    cancellation_token: CancellationToken | None = None,
) -> TranslationJobResult:
    translated_blocks: list[FragmentTranslation] = []
    total_units = len(units)

    for unit_index, unit in enumerate(units):
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise TranslationCancelled(_build_epub_translation_result(translated_blocks))

        translated_text = translator.translate(
            text=unit.text,
            source_language=source_language,
            target_language=target_language,
        )
        parsed = _parse_translation_batch(
            translated_text,
            expected_count=len(unit.indexed_texts),
        )
        if parsed is None:
            parsed = _translate_texts_individually(
                texts=[text for _, text in unit.indexed_texts],
                translator=translator,
                source_language=source_language,
                target_language=target_language,
            )

        translated_blocks.extend(
            FragmentTranslation(
                index=source_index,
                source_text=source_text,
                translated_text=translated,
            )
            for (source_index, source_text), translated in zip(
                unit.indexed_texts,
                parsed,
                strict=True,
            )
        )
        if progress_callback is not None:
            progress_callback((unit_index + 1, total_units))

    return _build_epub_translation_result(translated_blocks)


def _build_epub_translation_result(translated_blocks: list[FragmentTranslation]):
    return TranslationJobResult(
        fragments=translated_blocks,
        assembled_text="\n\n".join(
            fragment.translated_text for fragment in translated_blocks
        ),
    )


def _format_translation_batch(texts: list[str]) -> str:
    lines = ["<translation_batch>"]
    for index, text in enumerate(texts):
        lines.append(
            f'<translation_block id="{index}">'
            f"{html.escape(text, quote=False)}"
            "</translation_block>"
        )
    lines.append("</translation_batch>")
    return "\n".join(lines)


def _parse_epub_translation_unit(
    translated_text: str,
    *,
    source_blocks: list[_EpubTextBlock],
    translator: TextTranslator,
    source_language: str,
    target_language: str,
) -> list[FragmentTranslation]:
    parsed = _parse_translation_batch(
        translated_text,
        expected_count=len(source_blocks),
    )
    if parsed is None:
        return _translate_epub_blocks_individually(
            source_blocks=source_blocks,
            translator=translator,
            source_language=source_language,
            target_language=target_language,
        )

    return [
        FragmentTranslation(
            index=source_block.block_index,
            source_text=source_block.text,
            translated_text=translated,
        )
        for source_block, translated in zip(source_blocks, parsed, strict=True)
    ]


def _parse_translation_batch(
    translated_text: str,
    *,
    expected_count: int,
) -> list[str] | None:
    try:
        document = ElementTree.fromstring(_extract_translation_batch(translated_text))
        parsed = [
            "".join(block.itertext()).strip()
            for block in document
            if _local_name(block.tag) == "translation_block"
        ]
    except ElementTree.ParseError:
        return None

    if len(parsed) != expected_count:
        return None
    return parsed


def _extract_translation_batch(translated_text: str) -> str:
    start = translated_text.find("<translation_batch")
    end = translated_text.rfind("</translation_batch>")
    if start == -1 or end == -1:
        return translated_text
    return translated_text[start : end + len("</translation_batch>")]


def _translate_epub_blocks_individually(
    *,
    source_blocks: list[_EpubTextBlock],
    translator: TextTranslator,
    source_language: str,
    target_language: str,
) -> list[FragmentTranslation]:
    translated_blocks: list[FragmentTranslation] = []
    for source_block in source_blocks:
        translated_blocks.append(
            FragmentTranslation(
                index=source_block.block_index,
                source_text=source_block.text,
                translated_text=translator.translate(
                    text=source_block.text,
                    source_language=source_language,
                    target_language=target_language,
                ),
            )
        )
    return translated_blocks


def _translate_texts_individually(
    *,
    texts: list[str],
    translator: TextTranslator,
    source_language: str,
    target_language: str,
) -> list[str]:
    return [
        _clean_translated_text(
            translator.translate(
                text=text,
                source_language=source_language,
                target_language=target_language,
            )
        )
        for text in texts
    ]


def _clean_translated_text(translated_text: str) -> str:
    parsed = _parse_translation_batch(translated_text, expected_count=1)
    if parsed is not None:
        return parsed[0]
    return translated_text.strip()


def _count_translated_epub_units(
    fragments: list[FragmentTranslation],
    *,
    translation_units: list[_EpubTranslationUnit],
) -> int:
    if not fragments:
        return 0

    translated_indexes = {fragment.index for fragment in fragments}
    return sum(
        1
        for unit in translation_units
        if all(block.block_index in translated_indexes for block in unit.blocks)
    )


def _count_translated_text_units(
    fragments: list[FragmentTranslation],
    *,
    translation_units: list[_TextTranslationUnit],
) -> int:
    if not fragments:
        return 0

    translated_indexes = {fragment.index for fragment in fragments}
    return sum(
        1
        for unit in translation_units
        if all(index in translated_indexes for index, _ in unit.indexed_texts)
    )


def _replace_epub_xhtml_blocks(content: bytes, replacements: dict[int, str]) -> bytes:
    document = _read_epub_xhtml(content)

    for block_index, element in enumerate(_iter_epub_text_elements(document)):
        if block_index not in replacements:
            continue

        _replace_text_node_sequence(
            _epub_text_slots(element),
            replacements[block_index],
        )

    return ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)


def _epub_text_slots(element: ElementTree.Element) -> list[tuple[ElementTree.Element, str]]:
    if _local_name(element.tag) in _EPUB_IGNORED_TAGS:
        return []

    slots = [(element, "text")]
    for child in list(element):
        slots.extend(_epub_text_slots(child))
        slots.append((child, "tail"))
    return [
        (slot_element, attribute)
        for slot_element, attribute in slots
        if getattr(slot_element, attribute)
    ]


def _replace_text_node_sequence(
    slots: list[tuple[ElementTree.Element, str]],
    translated_text: str,
) -> None:
    if not slots:
        return

    original_lengths = [
        len(getattr(element, attribute) or "") for element, attribute in slots
    ]
    translated_parts = _split_text_by_lengths(translated_text, original_lengths)
    for (element, attribute), text_part in zip(slots, translated_parts, strict=True):
        setattr(element, attribute, text_part)


def _split_text_by_lengths(text: str, lengths: list[int]) -> list[str]:
    if not lengths:
        return []
    if len(lengths) == 1:
        return [text]

    total_length = sum(lengths)
    if total_length <= 0:
        return [text] + [""] * (len(lengths) - 1)

    parts: list[str] = []
    consumed = 0
    for index, length in enumerate(lengths):
        if index == len(lengths) - 1:
            parts.append(text[consumed:])
            break

        target_end = round(len(text) * sum(lengths[: index + 1]) / total_length)
        split_at = _nearest_word_boundary(text, target_end, minimum=consumed)
        parts.append(text[consumed:split_at])
        consumed = split_at

    return parts


def _nearest_word_boundary(text: str, target: int, *, minimum: int) -> int:
    target = max(minimum, min(len(text), target))
    if target in {minimum, len(text)}:
        return target

    left = text.rfind(" ", minimum, target + 1)
    right = text.find(" ", target)
    if left == -1 and right == -1:
        return target
    if left == -1:
        return right + 1
    if right == -1:
        return left + 1
    if target - left <= right - target:
        return left + 1
    return right + 1


def _read_epub_xhtml(content: bytes) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise TextExtractionError("EPUB XHTML content is not readable") from error


def _iter_epub_text_elements(document: ElementTree.Element):
    for element in document.iter():
        if _is_epub_text_element(element):
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
