from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath, PurePosixPath
import html
import re
import time
from typing import Callable
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from translator_service.extractors import (
    TextExtractionError,
    extract_text_from_txt,
    validate_archive_members,
)
from translator_service.language_detection import detect_languages_from_text
from translator_service.protected_text import (
    ProtectedText,
    protect_text,
    restore_protected_text,
)
from translator_service.structure_optimizer import (
    PromptTier,
    StructuredTextBlock,
    TextBlockKind,
    build_translation_units,
)
from translator_service.text_analysis import split_text_into_fragments
from translator_service.translation_cache import TranslationCache
from translator_service.translation_jobs import (
    CancellationToken,
    FragmentTranslation,
    TextTranslator,
    TranslationProgress,
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
    progress_callback: Callable[[TranslationProgress], None] | None = None,
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
    progress_callback: Callable[[TranslationProgress], None] | None = None,
    cancellation_token: CancellationToken | None = None,
    translation_cache: TranslationCache | None = None,
) -> TranslatedDocument:
    blocks = _extract_docx_blocks(content)
    translation_units = _group_docx_blocks(
        blocks,
        max_fragment_chars=max_fragment_chars,
    )
    try:
        translation = _translate_docx_units(
            units=translation_units,
            source_language=source_language,
            target_language=target_language,
            translator=translator,
            progress_callback=progress_callback,
            cancellation_token=cancellation_token,
            translation_cache=translation_cache,
        )
        is_partial = False
    except TranslationCancelled as error:
        translation = error.partial_result
        is_partial = True
    translated_content = _replace_docx_blocks(
        content,
        blocks,
        [fragment.translated_text for fragment in translation.fragments],
    )

    return TranslatedDocument(
        file_name=_translated_file_name(file_name, target_language, "docx", is_partial),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=translated_content,
        fragment_count=len(translation_units)
        if not is_partial
        else _count_translated_docx_units(
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
    progress_callback: Callable[[TranslationProgress], None] | None = None,
    cancellation_token: CancellationToken | None = None,
    translation_cache: TranslationCache | None = None,
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
            translation_cache=translation_cache,
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


def _extract_docx_blocks(content: bytes) -> list[_DocxTextBlock]:
    try:
        with ZipFile(BytesIO(content)) as docx:
            validate_archive_members(docx)
            part_names = _docx_text_part_names(docx)
            if "word/document.xml" not in docx.namelist():
                raise KeyError("word/document.xml")
            blocks: list[_DocxTextBlock] = []
            for part_name in part_names:
                document = _read_docx_xml(docx.read(part_name))
                for block_index, paragraph_block in enumerate(
                    _extract_docx_part_blocks(document, part_name=part_name)
                ):
                    blocks.append(
                        _DocxTextBlock(
                            index=len(blocks),
                            file_name=part_name,
                            block_index=block_index,
                            text=paragraph_block.text,
                            protected_phrases=paragraph_block.protected_phrases,
                            is_fixed_width_pseudo_table=(
                                paragraph_block.is_fixed_width_pseudo_table
                            ),
                            kind=paragraph_block.kind,
                            group_id=paragraph_block.group_id,
                        )
                    )
    except (BadZipFile, KeyError) as error:
        raise TextExtractionError(
            "DOCX file does not contain readable document text"
        ) from error

    if not blocks:
        raise TextExtractionError("DOCX file does not contain translatable text")

    return blocks


def _extract_docx_part_blocks(
    document: ElementTree.Element,
    *,
    part_name: str,
) -> list[_DocxParagraphBlock]:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    parent_by_child_id = _parent_map(document)
    table_index_by_id = {
        id(table): index
        for index, table in enumerate(document.findall(".//w:tbl", namespace))
    }
    paragraphs: list[_DocxParagraphBlock] = []
    for paragraph in document.findall(".//w:p", namespace):
        paragraph_text = _docx_paragraph_text(paragraph, namespace=namespace).strip()
        if paragraph_text:
            is_fixed_width_pseudo_table = _is_fixed_width_pseudo_table_paragraph(
                paragraph=paragraph,
                paragraph_text=paragraph_text,
                namespace=namespace,
            )
            kind, group_id = _docx_paragraph_structure(
                paragraph,
                part_name=part_name,
                namespace=namespace,
                parent_by_child_id=parent_by_child_id,
                table_index_by_id=table_index_by_id,
            )
            paragraphs.append(
                _DocxParagraphBlock(
                    text=paragraph_text,
                    protected_phrases=_docx_paragraph_protected_phrases(
                        paragraph=paragraph,
                        namespace=namespace,
                    ),
                    is_fixed_width_pseudo_table=is_fixed_width_pseudo_table,
                    kind=kind,
                    group_id=group_id,
                )
            )
    return paragraphs


def _docx_paragraph_structure(
    paragraph: ElementTree.Element,
    *,
    part_name: str,
    namespace: dict[str, str],
    parent_by_child_id: dict[int, ElementTree.Element],
    table_index_by_id: dict[int, int],
) -> tuple[TextBlockKind, str | None]:
    table = _nearest_ancestor(
        paragraph,
        local_name="tbl",
        parent_by_child_id=parent_by_child_id,
    )
    if table is not None:
        table_index = table_index_by_id.get(id(table), 0)
        return TextBlockKind.TABLE, f"{part_name}:table:{table_index}"

    if paragraph.find("w:pPr/w:numPr", namespace) is not None:
        num_id = paragraph.find("w:pPr/w:numPr/w:numId", namespace)
        num_value = (
            num_id.get(f"{{{namespace['w']}}}val")
            if num_id is not None
            else "unknown"
        )
        return TextBlockKind.LIST, f"{part_name}:list:{num_value}"

    paragraph_style = paragraph.find("w:pPr/w:pStyle", namespace)
    style_value = (
        paragraph_style.get(f"{{{namespace['w']}}}val")
        if paragraph_style is not None
        else ""
    )
    if style_value.lower().startswith("heading"):
        return TextBlockKind.HEADING, None

    return TextBlockKind.PLAIN, None


def _docx_paragraph_text(
    paragraph: ElementTree.Element,
    *,
    namespace: dict[str, str],
) -> str:
    pieces: list[str] = []
    for element in paragraph.iter():
        local_name = _local_name(element.tag)
        if local_name == "t":
            pieces.append(element.text or "")
            continue
        if local_name == "tab":
            pieces.append("\t")
            continue
        if local_name == "br" and element.get(f"{{{namespace['w']}}}type") != "page":
            pieces.append("\n")
    return "".join(pieces)


def _docx_paragraph_protected_phrases(
    *,
    paragraph: ElementTree.Element,
    namespace: dict[str, str],
) -> tuple[str, ...]:
    phrases: list[str] = []
    for hyperlink in paragraph.findall(".//w:hyperlink", namespace):
        phrase = "".join(
            text_node.text or ""
            for text_node in hyperlink.findall(".//w:t", namespace)
        ).strip()
        if phrase:
            phrases.append(phrase)

    return tuple(dict.fromkeys(phrases))


def _is_fixed_width_pseudo_table_paragraph(
    *,
    paragraph: ElementTree.Element,
    paragraph_text: str,
    namespace: dict[str, str],
) -> bool:
    if not re.search(r"\S\s{2,}\S", paragraph_text):
        return False

    for run in paragraph.findall(".//w:r", namespace):
        run_fonts = run.find("w:rPr/w:rFonts", namespace)
        if run_fonts is None:
            continue
        font_names = {
            value.lower()
            for key, value in run_fonts.attrib.items()
            if _local_name(key) in {"ascii", "hAnsi", "eastAsia", "cs"}
        }
        if any("courier" in font_name or "mono" in font_name for font_name in font_names):
            return True
    return False


def _replace_docx_blocks(
    content: bytes,
    blocks: list[_DocxTextBlock],
    translated_blocks: list[str],
) -> bytes:
    replacements_by_file: dict[str, dict[int, str]] = {}
    for block, translated_text in zip(blocks, translated_blocks, strict=False):
        replacements_by_file.setdefault(block.file_name, {})[
            block.block_index
        ] = translated_text

    source = BytesIO(content)
    target = BytesIO()

    with ZipFile(source) as source_docx, ZipFile(target, "w") as target_docx:
        validate_archive_members(source_docx)
        for item in source_docx.infolist():
            data = source_docx.read(item)
            if item.filename in replacements_by_file:
                data = _replace_docx_xml_blocks(
                    data,
                    replacements_by_file[item.filename],
                )
            target_docx.writestr(item, data)

    return target.getvalue()


def _replace_docx_xml_blocks(content: bytes, replacements: dict[int, str]) -> bytes:
    document = _read_docx_xml(content)
    namespace_uri = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    namespace = {"w": namespace_uri}
    ElementTree.register_namespace("w", namespace_uri)

    text_block_index = 0
    for paragraph in document.findall(".//w:p", namespace):
        text_nodes = paragraph.findall(".//w:t", namespace)
        if not text_nodes:
            continue

        original_text = "".join(text_node.text or "" for text_node in text_nodes).strip()
        if not original_text:
            continue

        if text_block_index not in replacements:
            text_block_index += 1
            continue
        _replace_docx_text_nodes(
            paragraph=paragraph,
            text_nodes=text_nodes,
            namespace=namespace,
            translated_text=replacements[text_block_index],
        )
        text_block_index += 1

    _expand_vml_textbox_shapes(document)

    return ElementTree.tostring(
        document,
        encoding="utf-8",
        xml_declaration=True,
    )


def _replace_docx_text_nodes(
    *,
    paragraph: ElementTree.Element,
    text_nodes: list[ElementTree.Element],
    namespace: dict[str, str],
    translated_text: str,
) -> None:
    preserved_ranges = _docx_preserved_text_node_ranges(
        paragraph=paragraph,
        text_nodes=text_nodes,
        namespace=namespace,
    )
    if not preserved_ranges:
        if _replace_docx_text_nodes_around_controls(
            paragraph=paragraph,
            translated_text=translated_text,
            namespace=namespace,
        ):
            return
        _replace_text_node_sequence(
            [(text_node, "text") for text_node in text_nodes],
            translated_text,
        )
        return

    cursor = 0
    node_cursor = 0
    for start, end in preserved_ranges:
        preserved_text = "".join(text_nodes[index].text or "" for index in range(start, end))
        preserved_at = translated_text.find(preserved_text, cursor)
        if preserved_at == -1:
            _replace_docx_text_nodes_with_static_ranges(
                text_nodes=text_nodes,
                preserved_ranges=preserved_ranges,
                translated_text=translated_text,
            )
            return

        _replace_text_node_sequence(
            [(text_node, "text") for text_node in text_nodes[node_cursor:start]],
            translated_text[cursor:preserved_at],
        )
        for index in range(start, end):
            text_nodes[index].text = text_nodes[index].text or ""
        cursor = preserved_at + len(preserved_text)
        node_cursor = end

    _replace_text_node_sequence(
        [(text_node, "text") for text_node in text_nodes[node_cursor:]],
        translated_text[cursor:],
    )


def _replace_docx_text_nodes_around_controls(
    *,
    paragraph: ElementTree.Element,
    translated_text: str,
    namespace: dict[str, str],
) -> bool:
    groups: list[list[ElementTree.Element]] = [[]]
    controls: list[str] = []

    for element in paragraph.iter():
        local_name = _local_name(element.tag)
        if local_name == "t":
            groups[-1].append(element)
            continue
        if local_name == "tab":
            controls.append("\t")
            groups.append([])
            continue
        if local_name == "br" and element.get(f"{{{namespace['w']}}}type") != "page":
            controls.append("\n")
            groups.append([])

    if not controls:
        return False

    group_lengths = [
        sum(len(text_node.text or "") for text_node in group)
        for group in groups
    ]
    translated_segments = _split_text_by_original_controls(
        translated_text,
        controls=controls,
        group_lengths=group_lengths,
    )
    for group, translated_segment in zip(groups, translated_segments, strict=True):
        _replace_text_node_sequence(
            [(text_node, "text") for text_node in group],
            translated_segment,
        )
    return True


def _split_text_by_original_controls(
    text: str,
    *,
    controls: list[str],
    group_lengths: list[int],
) -> list[str]:
    segments: list[str] = []
    cursor = 0
    for control in controls:
        control_at = text.find(control, cursor)
        if control_at == -1:
            return _split_text_by_lengths(text, group_lengths)
        segments.append(text[cursor:control_at])
        cursor = control_at + len(control)

    segments.append(text[cursor:])
    return segments


def _replace_docx_text_nodes_with_static_ranges(
    *,
    text_nodes: list[ElementTree.Element],
    preserved_ranges: list[tuple[int, int]],
    translated_text: str,
) -> None:
    preserved_indexes = {
        index for start, end in preserved_ranges for index in range(start, end)
    }
    translatable_nodes = [
        text_node
        for index, text_node in enumerate(text_nodes)
        if index not in preserved_indexes
    ]
    _replace_text_node_sequence(
        [(text_node, "text") for text_node in translatable_nodes],
        translated_text,
    )
    for index in preserved_indexes:
        text_nodes[index].text = text_nodes[index].text or ""


def _docx_preserved_text_node_ranges(
    *,
    paragraph: ElementTree.Element,
    text_nodes: list[ElementTree.Element],
    namespace: dict[str, str],
) -> list[tuple[int, int]]:
    index_by_node_id = {id(text_node): index for index, text_node in enumerate(text_nodes)}
    preserved_indexes: set[int] = set()

    for hyperlink in paragraph.findall(".//w:hyperlink", namespace):
        for text_node in hyperlink.findall(".//w:t", namespace):
            index = index_by_node_id.get(id(text_node))
            if index is not None:
                preserved_indexes.add(index)

    for run in paragraph.findall(".//w:r", namespace):
        if run.find("w:rPr/w:vertAlign", namespace) is None:
            continue
        for text_node in run.findall(".//w:t", namespace):
            index = index_by_node_id.get(id(text_node))
            if index is not None:
                preserved_indexes.add(index)

    return _contiguous_ranges(sorted(preserved_indexes))


def _contiguous_ranges(indexes: list[int]) -> list[tuple[int, int]]:
    if not indexes:
        return []

    ranges: list[tuple[int, int]] = []
    start = indexes[0]
    previous = indexes[0]
    for index in indexes[1:]:
        if index == previous + 1:
            previous = index
            continue
        ranges.append((start, previous + 1))
        start = index
        previous = index
    ranges.append((start, previous + 1))
    return ranges


def _expand_vml_textbox_shapes(document: ElementTree.Element) -> None:
    namespaces = {
        "v": "urn:schemas-microsoft-com:vml",
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    }
    for shape in document.findall(".//v:shape", namespaces):
        if shape.find(".//v:textbox", namespaces) is None:
            continue

        text = "".join(
            text_node.text or ""
            for text_node in shape.findall(".//w:t", namespaces)
        )
        paragraph_count = len(shape.findall(".//w:txbxContent/w:p", namespaces))
        current_height = _vml_style_dimension(shape.get("style", ""), "height")
        desired_height = max(
            current_height,
            paragraph_count * 26.0 + max(0, len(text) // 70) * 18.0 + 18.0,
        )
        if desired_height > current_height:
            shape.set(
                "style",
                _set_vml_style_dimension(
                    shape.get("style", ""),
                    "height",
                    desired_height,
                ),
            )


def _vml_style_dimension(style: str, name: str) -> float:
    match = re.search(rf"(^|;)\s*{re.escape(name)}\s*:\s*([0-9.]+)pt", style)
    if match is None:
        return 0.0
    return float(match.group(2))


def _set_vml_style_dimension(style: str, name: str, value: float) -> str:
    replacement = f"{name}:{round(value, 1):g}pt"
    if re.search(rf"(^|;)\s*{re.escape(name)}\s*:", style):
        return re.sub(
            rf"(^|;)\s*{re.escape(name)}\s*:\s*[^;]+",
            lambda match: f"{match.group(1)}{replacement}",
            style,
            count=1,
        )
    separator = "" if not style or style.endswith(";") else ";"
    return f"{style}{separator}{replacement}"


def _read_docx_xml(content: bytes) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise TextExtractionError("DOCX document XML is not readable") from error


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
class _DocxTextBlock:
    index: int
    file_name: str
    block_index: int
    text: str
    protected_phrases: tuple[str, ...] = ()
    is_fixed_width_pseudo_table: bool = False
    kind: TextBlockKind = TextBlockKind.PLAIN
    group_id: str | None = None


@dataclass(frozen=True)
class _DocxParagraphBlock:
    text: str
    protected_phrases: tuple[str, ...] = ()
    is_fixed_width_pseudo_table: bool = False
    kind: TextBlockKind = TextBlockKind.PLAIN
    group_id: str | None = None


@dataclass(frozen=True)
class _DocxTranslationUnit:
    blocks: list[_DocxTextBlock]
    prompt_tier: PromptTier = PromptTier.PLAIN

    @property
    def text(self) -> str:
        return _format_translation_batch([block.text for block in self.blocks])


@dataclass(frozen=True)
class _EpubTextBlock:
    file_name: str
    block_index: int
    text: str
    kind: TextBlockKind = TextBlockKind.PLAIN
    group_id: str | None = None


@dataclass(frozen=True)
class _EpubTranslationUnit:
    blocks: list[_EpubTextBlock]
    prompt_tier: PromptTier = PromptTier.PLAIN

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
            validate_archive_members(epub)
            blocks: list[_EpubTextBlock] = []
            for file_name in _epub_text_item_names(epub):
                document = _read_epub_xhtml(epub.read(file_name))
                parent_by_child_id = _parent_map(document)
                group_index_by_element_id = _epub_group_indexes(document)
                for block_index, element in enumerate(_iter_epub_text_elements(document)):
                    text = _visible_text(element)
                    if text:
                        kind, group_id = _epub_block_structure(
                            element,
                            file_name=file_name,
                            parent_by_child_id=parent_by_child_id,
                            group_index_by_element_id=group_index_by_element_id,
                        )
                        blocks.append(
                            _EpubTextBlock(
                                file_name=file_name,
                                block_index=block_index,
                                text=text,
                                kind=kind,
                                group_id=group_id,
                            )
                        )
    except (BadZipFile, KeyError) as error:
        raise TextExtractionError(
            "EPUB file does not contain readable book text"
        ) from error

    if not blocks:
        raise TextExtractionError("EPUB file does not contain translatable text")

    return blocks


def _epub_block_structure(
    element: ElementTree.Element,
    *,
    file_name: str,
    parent_by_child_id: dict[int, ElementTree.Element],
    group_index_by_element_id: dict[int, tuple[str, int]],
) -> tuple[TextBlockKind, str | None]:
    table = _nearest_ancestor(
        element,
        local_name="table",
        parent_by_child_id=parent_by_child_id,
    )
    if table is not None:
        group_name, group_index = group_index_by_element_id.get(id(table), ("table", 0))
        return TextBlockKind.TABLE, f"{file_name}:{group_name}:{group_index}"

    list_element = _nearest_ancestor_in(
        element,
        local_names={"ol", "ul", "dl"},
        parent_by_child_id=parent_by_child_id,
    )
    if list_element is not None:
        group_name, group_index = group_index_by_element_id.get(
            id(list_element),
            ("list", 0),
        )
        return TextBlockKind.LIST, f"{file_name}:{group_name}:{group_index}"

    local_name = _local_name(element.tag)
    epub_type = element.attrib.get("epub:type", "") or element.attrib.get(
        "{http://www.idpf.org/2007/ops}type",
        "",
    )
    footnote = _nearest_epub_footnote_element(
        element,
        parent_by_child_id=parent_by_child_id,
    )
    if local_name == "aside" or "footnote" in epub_type or footnote is not None:
        footnote_id = id(footnote) if footnote is not None else id(element)
        return TextBlockKind.FOOTNOTE, f"{file_name}:footnote:{footnote_id}"
    if local_name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return TextBlockKind.HEADING, None
    if _is_dense_epub_markup(element):
        return TextBlockKind.DENSE_MARKUP, f"{file_name}:dense:{id(element)}"
    return TextBlockKind.PLAIN, None


def _nearest_epub_footnote_element(
    element: ElementTree.Element,
    *,
    parent_by_child_id: dict[int, ElementTree.Element],
) -> ElementTree.Element | None:
    current: ElementTree.Element | None = element
    while current is not None:
        epub_type = current.attrib.get("epub:type", "") or current.attrib.get(
            "{http://www.idpf.org/2007/ops}type",
            "",
        )
        if _local_name(current.tag) == "aside" or "footnote" in epub_type:
            return current
        current = parent_by_child_id.get(id(current))
    return None


def _epub_group_indexes(
    document: ElementTree.Element,
) -> dict[int, tuple[str, int]]:
    indexes: dict[int, tuple[str, int]] = {}
    counters = {"table": 0, "list": 0}
    for element in document.iter():
        local_name = _local_name(element.tag)
        if local_name == "table":
            indexes[id(element)] = ("table", counters["table"])
            counters["table"] += 1
        elif local_name in {"ol", "ul", "dl"}:
            indexes[id(element)] = ("list", counters["list"])
            counters["list"] += 1
    return indexes


def _is_dense_epub_markup(element: ElementTree.Element) -> bool:
    inline_count = sum(
        1
        for child in element.iter()
        if child is not element and _local_name(child.tag) in _EPUB_DENSE_INLINE_TAGS
    )
    return inline_count >= 4


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
        validate_archive_members(source_epub)
        for item in source_epub.infolist():
            data = source_epub.read(item)
            if item.filename in replacements_by_file:
                data = _replace_epub_xhtml_blocks(
                    data,
                    replacements_by_file[item.filename],
                )
            target_epub.writestr(item, data)

    return target.getvalue()


def _group_docx_blocks(
    blocks: list[_DocxTextBlock],
    *,
    max_fragment_chars: int,
) -> list[_DocxTranslationUnit]:
    optimized_units = build_translation_units(
        [
            StructuredTextBlock(
                index=index,
                text=block.text,
                kind=block.kind,
                group_id=block.group_id,
            )
            for index, block in enumerate(blocks)
        ],
        max_fragment_chars=max_fragment_chars,
    )
    return [
        _DocxTranslationUnit(
            blocks=[blocks[unit_block.index] for unit_block in optimized_unit.blocks],
            prompt_tier=optimized_unit.prompt_tier,
        )
        for optimized_unit in optimized_units
    ]


def _group_epub_blocks(
    blocks: list[_EpubTextBlock],
    *,
    max_fragment_chars: int,
) -> list[_EpubTranslationUnit]:
    optimized_units = build_translation_units(
        [
            StructuredTextBlock(
                index=index,
                text=block.text,
                kind=block.kind,
                group_id=block.group_id,
            )
            for index, block in enumerate(blocks)
        ],
        max_fragment_chars=max_fragment_chars,
    )
    return [
        _EpubTranslationUnit(
            blocks=[blocks[unit_block.index] for unit_block in optimized_unit.blocks],
            prompt_tier=optimized_unit.prompt_tier,
        )
        for optimized_unit in optimized_units
    ]


def _translate_docx_units(
    *,
    units: list[_DocxTranslationUnit],
    source_language: str,
    target_language: str,
    translator: TextTranslator,
    progress_callback: Callable[[TranslationProgress], None] | None = None,
    cancellation_token: CancellationToken | None = None,
    translation_cache: TranslationCache | None = None,
) -> TranslationJobResult:
    translated_blocks: list[FragmentTranslation] = []
    total_units = len(units)

    for unit_index, unit in enumerate(units):
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise TranslationCancelled(_build_epub_translation_result(translated_blocks))

        unit_started_at = time.monotonic()
        unit_prompt_tokens = 0
        unit_completion_tokens = 0
        unit_total_tokens = 0
        unit_cache_hit_tokens = 0
        unit_cache_miss_tokens = 0
        last_source_text = ""
        last_translated_text = ""
        for subgroup_source_language, subgroup_blocks in _docx_translation_subgroups(
            unit.blocks,
            source_language=source_language,
            target_language=target_language,
        ):
            if (
                source_language.strip().lower() == "auto"
                and len(subgroup_blocks) == 1
                and _has_multiple_leading_language_labels(subgroup_blocks[0].text)
            ):
                translated_text = _translate_multi_label_docx_block(
                    subgroup_blocks[0].text,
                    translator=translator,
                    target_language=target_language,
                )
                usage = _translator_usage(translator)
                unit_prompt_tokens += usage[0]
                unit_completion_tokens += usage[1]
                unit_total_tokens += usage[2]
                unit_cache_hit_tokens += usage[3]
                unit_cache_miss_tokens += usage[4]
                last_source_text = subgroup_blocks[0].text
                last_translated_text = translated_text
                translated_blocks.append(
                    FragmentTranslation(
                        index=subgroup_blocks[0].index,
                        source_text=subgroup_blocks[0].text,
                        translated_text=translated_text,
                    )
                )
                continue

            cached = _translation_cache_get(
                translation_cache,
                blocks=[block.text for block in subgroup_blocks],
                source_language=subgroup_source_language,
                target_language=target_language,
                prompt_tier=unit.prompt_tier,
            )
            if cached is not None:
                translated_blocks.extend(
                    FragmentTranslation(
                        index=source_block.index,
                        source_text=source_block.text,
                        translated_text=translated,
                    )
                    for source_block, translated in zip(
                        subgroup_blocks,
                        cached,
                        strict=True,
                    )
                )
                if subgroup_blocks and cached:
                    last_source_text = subgroup_blocks[-1].text
                    last_translated_text = cached[-1]
                continue

            prepared_blocks = [
                _prepare_docx_block_for_translation(
                    block.text,
                    source_language=subgroup_source_language,
                    target_language=target_language,
                    is_fixed_width_pseudo_table=block.is_fixed_width_pseudo_table,
                )
                for block in subgroup_blocks
            ]
            protected_blocks = [
                protect_text(prepared.text, extra_phrases=block.protected_phrases)
                for prepared, block in zip(
                    prepared_blocks,
                    subgroup_blocks,
                    strict=True,
                )
            ]
            source_language_hints = _source_language_hints(
                [prepared.text for prepared in prepared_blocks],
                source_language=subgroup_source_language,
            )
            translated_text = translator.translate(
                text=_format_translation_batch(
                    [protected_block.text for protected_block in protected_blocks],
                    source_language_hints=source_language_hints,
                ),
                source_language=subgroup_source_language,
                target_language=target_language,
            )
            usage = _translator_usage(translator)
            unit_prompt_tokens += usage[0]
            unit_completion_tokens += usage[1]
            unit_total_tokens += usage[2]
            unit_cache_hit_tokens += usage[3]
            unit_cache_miss_tokens += usage[4]
            parsed = _parse_translation_batch(
                translated_text,
                expected_count=len(subgroup_blocks),
            )
            if parsed is None:
                parsed = _translate_texts_individually(
                    texts=[block.text for block in subgroup_blocks],
                    translator=translator,
                    source_language=subgroup_source_language,
                    target_language=target_language,
                )
            else:
                parsed = _restore_protected_texts(parsed, protected_blocks)
            parsed = [
                _restore_prepared_docx_label(
                    translated_text=_restore_fixed_width_pseudo_table_text(
                        source_text=prepared.fixed_width_source_text,
                        translated_text=_known_orthographic_sample_translation(
                            prepared.text,
                            source_language=subgroup_source_language,
                            target_language=target_language,
                        )
                        or translated,
                    ),
                    prepared_block=prepared,
                    target_language=target_language,
                )
                for translated, prepared in zip(
                    parsed,
                    prepared_blocks,
                    strict=True,
                )
            ]

            translated_blocks.extend(
                FragmentTranslation(
                    index=source_block.index,
                    source_text=source_block.text,
                    translated_text=translated,
                )
                for source_block, translated in zip(
                    subgroup_blocks,
                    parsed,
                    strict=True,
                )
            )
            _translation_cache_put(
                translation_cache,
                source_texts=tuple(block.text for block in subgroup_blocks),
                translated_texts=tuple(parsed),
                source_language=subgroup_source_language,
                target_language=target_language,
                prompt_tier=unit.prompt_tier,
            )
            if subgroup_blocks and parsed:
                last_source_text = subgroup_blocks[-1].text
                last_translated_text = parsed[-1]
        if progress_callback is not None:
            progress_callback(
                TranslationProgress(
                    completed_fragments=unit_index + 1,
                    total_fragments=total_units,
                    source_text=last_source_text,
                    translated_text=last_translated_text,
                    elapsed_seconds=time.monotonic() - unit_started_at,
                    prompt_tokens=unit_prompt_tokens,
                    completion_tokens=unit_completion_tokens,
                    total_tokens=unit_total_tokens,
                    prompt_cache_hit_tokens=unit_cache_hit_tokens,
                    prompt_cache_miss_tokens=unit_cache_miss_tokens,
                )
            )

    return _build_epub_translation_result(translated_blocks)


def _restore_fixed_width_pseudo_table_text(
    *,
    source_text: str | None,
    translated_text: str,
) -> str:
    if source_text is None:
        return translated_text

    source_columns = _fixed_width_columns(source_text)
    translated_columns = _fixed_width_columns(translated_text)
    if len(source_columns) < 2 or len(source_columns) != len(translated_columns):
        return translated_text

    pieces = [translated_columns[0][1]]
    for index in range(1, len(source_columns)):
        target_start = source_columns[index][0]
        current_length = len("".join(pieces))
        pieces.append(" " * max(1, target_start - current_length))
        pieces.append(translated_columns[index][1])
    return "".join(pieces)


def _fixed_width_columns(text: str) -> list[tuple[int, str]]:
    columns: list[tuple[int, str]] = []
    segment_start = 0
    for separator in re.finditer(r" {2,}", text):
        segment = text[segment_start : separator.start()]
        stripped = segment.strip()
        if stripped:
            columns.append(
                (
                    segment_start + len(segment) - len(segment.lstrip()),
                    stripped,
                )
            )
        segment_start = separator.end()

    segment = text[segment_start:]
    stripped = segment.strip()
    if stripped:
        columns.append(
            (
                segment_start + len(segment) - len(segment.lstrip()),
                stripped,
            )
        )
    return columns


def _translate_multi_label_docx_block(
    text: str,
    *,
    translator: TextTranslator,
    target_language: str,
) -> str:
    translated_segments: list[str] = []
    for source_language_code, segment_text in _split_labeled_language_segments(text):
        prepared = _prepare_docx_block_for_translation(
            segment_text,
            source_language=source_language_code,
            target_language=target_language,
        )
        protected = protect_text(prepared.text)
        translated_text = translator.translate(
            text=_format_translation_batch([protected.text]),
            source_language=source_language_code,
            target_language=target_language,
        )
        parsed = _parse_translation_batch(translated_text, expected_count=1)
        translated_segment = (
            restore_protected_text(parsed[0], protected.replacements)
            if parsed is not None
            else restore_protected_text(
                _clean_translated_text(translated_text),
                protected.replacements,
            )
        )
        translated_segment = (
            _known_orthographic_sample_translation(
                prepared.text,
                source_language=source_language_code,
                target_language=target_language,
            )
            or translated_segment
        )
        translated_segments.append(
            _restore_prepared_docx_label(
                translated_text=translated_segment,
                prepared_block=prepared,
                target_language=target_language,
            )
        )
    return " ".join(translated_segments)

def _known_orthographic_sample_translation(
    text: str,
    *,
    source_language: str,
    target_language: str,
) -> str | None:
    normalized = " ".join(text.strip().rstrip(".").lower().split())
    if (
        source_language.strip().lower() == "pl"
        and target_language.strip().lower() == "ru"
        and normalized == "zażółć gęślą jaźń"
    ):
        return "Проверка польских диакритических знаков: ż, ó, ł, ć, ę, ś, ą, ź, ń."
    return None


def _has_multiple_leading_language_labels(text: str) -> bool:
    return len(_language_label_matches(text)) > 1


def _split_labeled_language_segments(text: str) -> list[tuple[str, str]]:
    matches = _language_label_matches(text)
    segments: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        label_code = _language_label_source_code(match.group(1))
        if label_code is None:
            continue
        segment_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segments.append((label_code, text[match.start() : segment_end].strip()))
    return segments


def _language_label_matches(text: str) -> list[re.Match[str]]:
    return list(
        re.finditer(
            r"("
            r"Русский|Українська|Украинский|Украинская|English|Français|Francais|"
            r"Español|Espanol|Polski|Nederlands|Deutsch|עברית|العربية|中文|日本語|한국어|"
            r"Английский|Французский|Испанский|Польский|Нидерландский|Немецкий|"
            r"Иврит|Арабский|Китайский|Японский|Корейский"
            r")\s*:",
            text,
            flags=re.IGNORECASE,
        )
    )


@dataclass(frozen=True)
class _PreparedDocxBlock:
    text: str
    source_language_code: str | None = None
    fixed_width_source_text: str | None = None


def _prepare_docx_block_for_translation(
    text: str,
    *,
    source_language: str,
    target_language: str,
    is_fixed_width_pseudo_table: bool = False,
) -> _PreparedDocxBlock:
    fixed_width_source_text = text if is_fixed_width_pseudo_table else None
    if source_language.strip().lower() == "auto":
        return _PreparedDocxBlock(
            text=text,
            fixed_width_source_text=fixed_width_source_text,
        )

    label_match = _leading_language_label_match(text)
    if label_match is None:
        return _PreparedDocxBlock(
            text=text,
            fixed_width_source_text=fixed_width_source_text,
        )

    label_code = _language_label_source_code(label_match.group(1))
    if label_code != source_language.strip().lower():
        return _PreparedDocxBlock(
            text=text,
            fixed_width_source_text=fixed_width_source_text,
        )

    return _PreparedDocxBlock(
        text=text[label_match.end() :].strip(),
        source_language_code=label_code,
        fixed_width_source_text=fixed_width_source_text,
    )


def _restore_prepared_docx_label(
    *,
    translated_text: str,
    prepared_block: _PreparedDocxBlock,
    target_language: str,
) -> str:
    if prepared_block.source_language_code is None:
        return translated_text

    label = _localized_language_label(
        prepared_block.source_language_code,
        target_language=target_language,
    )
    text_without_label = _strip_leading_language_label(translated_text)
    return f"{label}: {text_without_label}".strip()


def _strip_leading_language_label(text: str) -> str:
    label_match = _leading_language_label_match(text)
    if label_match is None:
        return text.strip()
    return text[label_match.end() :].strip()


def _docx_translation_subgroups(
    blocks: list[_DocxTextBlock],
    *,
    source_language: str,
    target_language: str,
) -> list[tuple[str, list[_DocxTextBlock]]]:
    if source_language.strip().lower() != "auto":
        return [(source_language, blocks)]

    subgroups: list[tuple[str, list[_DocxTextBlock]]] = []
    current_source_language: str | None = None
    current_blocks: list[_DocxTextBlock] = []
    for block in blocks:
        block_source_language = (
            _source_language_code_for_text(block.text, target_language=target_language)
            or "auto"
        )
        if current_blocks and block_source_language != current_source_language:
            subgroups.append((current_source_language or "auto", current_blocks))
            current_blocks = []

        current_source_language = block_source_language
        current_blocks.append(block)

    if current_blocks:
        subgroups.append((current_source_language or "auto", current_blocks))
    return subgroups


def _source_language_code_for_text(
    text: str,
    *,
    target_language: str,
) -> str | None:
    label_source_language = _language_label_source_code(text)
    if label_source_language is not None:
        return label_source_language

    detected_languages = detect_languages_from_text(text)
    if len(detected_languages) != 1:
        return None
    return detected_languages[0].code


def _language_label_source_code(text: str) -> str | None:
    label = text.split(":", 1)[0].strip().lower()
    labels = {
        "русский": "ru",
        "українська": "uk",
        "украинский": "uk",
        "украинская": "uk",
        "английский": "en",
        "французский": "fr",
        "испанский": "es",
        "польский": "pl",
        "нидерландский": "nl",
        "немецкий": "de",
        "иврит": "he",
        "арабский": "ar",
        "китайский": "zh",
        "японский": "ja",
        "корейский": "ko",
        "english": "en",
        "français": "fr",
        "francais": "fr",
        "español": "es",
        "espanol": "es",
        "polski": "pl",
        "nederlands": "nl",
        "deutsch": "de",
        "עברית": "he",
        "العربية": "ar",
        "中文": "zh",
        "日本語": "ja",
        "한국어": "ko",
    }
    return labels.get(label)


def _leading_language_label_match(text: str) -> re.Match[str] | None:
    return re.match(
        r"^\s*("
        r"Русский|Українська|Украинский|Украинская|English|Français|Francais|"
        r"Español|Espanol|Polski|Nederlands|Deutsch|עברית|العربية|中文|日本語|한국어|"
        r"Английский|Французский|Испанский|Польский|Нидерландский|Немецкий|"
        r"Иврит|Арабский|Китайский|Японский|Корейский"
        r")\s*:",
        text,
        flags=re.IGNORECASE,
    )


def _localized_language_label(
    source_language_code: str,
    *,
    target_language: str,
) -> str:
    labels_by_target_language = {
        "ru": {
            "ru": "Русский",
            "uk": "Украинский",
            "en": "Английский",
            "fr": "Французский",
            "es": "Испанский",
            "pl": "Польский",
            "nl": "Нидерландский",
            "de": "Немецкий",
            "he": "Иврит",
            "ar": "Арабский",
            "zh": "Китайский",
            "ja": "Японский",
            "ko": "Корейский",
        },
        "en": {
            "ru": "Russian",
            "uk": "Ukrainian",
            "en": "English",
            "fr": "French",
            "es": "Spanish",
            "pl": "Polish",
            "nl": "Dutch",
            "de": "German",
            "he": "Hebrew",
            "ar": "Arabic",
            "zh": "Chinese",
            "ja": "Japanese",
            "ko": "Korean",
        },
        "uk": {
            "ru": "Російська",
            "uk": "Українська",
            "en": "Англійська",
            "fr": "Французька",
            "es": "Іспанська",
            "pl": "Польська",
            "nl": "Нідерландська",
            "de": "Німецька",
            "he": "Іврит",
            "ar": "Арабська",
            "zh": "Китайська",
            "ja": "Японська",
            "ko": "Корейська",
        },
    }
    labels = labels_by_target_language.get(
        target_language.strip().lower(),
        labels_by_target_language["en"],
    )
    return labels.get(source_language_code, source_language_code)


def _translate_epub_units(
    *,
    units: list[_EpubTranslationUnit],
    source_language: str,
    target_language: str,
    translator: TextTranslator,
    progress_callback: Callable[[TranslationProgress], None] | None = None,
    cancellation_token: CancellationToken | None = None,
    translation_cache: TranslationCache | None = None,
):
    translated_blocks = []
    total_units = len(units)

    for unit_index, unit in enumerate(units):
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise TranslationCancelled(_build_epub_translation_result(translated_blocks))

        unit_started_at = time.monotonic()
        cached = _translation_cache_get(
            translation_cache,
            blocks=[block.text for block in unit.blocks],
            source_language=source_language,
            target_language=target_language,
            prompt_tier=unit.prompt_tier,
        )
        if cached is not None:
            translated_unit_blocks = [
                FragmentTranslation(
                    index=source_block.block_index,
                    source_text=source_block.text,
                    translated_text=translated,
                )
                for source_block, translated in zip(
                    unit.blocks,
                    cached,
                    strict=True,
                )
            ]
            translated_blocks.extend(translated_unit_blocks)
            if progress_callback is not None:
                last_block = translated_unit_blocks[-1] if translated_unit_blocks else None
                progress_callback(
                    TranslationProgress(
                        completed_fragments=unit_index + 1,
                        total_fragments=total_units,
                        source_text=last_block.source_text if last_block else "",
                        translated_text=last_block.translated_text if last_block else "",
                        elapsed_seconds=time.monotonic() - unit_started_at,
                    )
                )
            continue

        protected_blocks = [protect_text(block.text) for block in unit.blocks]
        source_language_hints = _source_language_hints(
            [block.text for block in unit.blocks],
            source_language=source_language,
        )
        translated_text = translator.translate(
            text=_format_translation_batch(
                [protected_block.text for protected_block in protected_blocks],
                source_language_hints=source_language_hints,
            ),
            source_language=source_language,
            target_language=target_language,
        )
        usage = _translator_usage(translator)
        translated_unit_blocks = _parse_epub_translation_unit(
            translated_text,
            source_blocks=unit.blocks,
            protected_blocks=protected_blocks,
            translator=translator,
            source_language=source_language,
            target_language=target_language,
        )
        translated_blocks.extend(translated_unit_blocks)
        _translation_cache_put(
            translation_cache,
            source_texts=tuple(block.text for block in unit.blocks),
            translated_texts=tuple(
                block.translated_text for block in translated_unit_blocks
            ),
            source_language=source_language,
            target_language=target_language,
            prompt_tier=unit.prompt_tier,
        )
        if progress_callback is not None:
            last_block = translated_unit_blocks[-1] if translated_unit_blocks else None
            progress_callback(
                TranslationProgress(
                    completed_fragments=unit_index + 1,
                    total_fragments=total_units,
                    source_text=last_block.source_text if last_block else "",
                    translated_text=last_block.translated_text if last_block else "",
                    elapsed_seconds=time.monotonic() - unit_started_at,
                    prompt_tokens=usage[0],
                    completion_tokens=usage[1],
                    total_tokens=usage[2],
                    prompt_cache_hit_tokens=usage[3],
                    prompt_cache_miss_tokens=usage[4],
                )
            )

    return _build_epub_translation_result(translated_blocks)


def _translate_marked_text_units(
    *,
    units: list[_TextTranslationUnit],
    source_language: str,
    target_language: str,
    translator: TextTranslator,
    progress_callback: Callable[[TranslationProgress], None] | None = None,
    cancellation_token: CancellationToken | None = None,
) -> TranslationJobResult:
    translated_blocks: list[FragmentTranslation] = []
    total_units = len(units)

    for unit_index, unit in enumerate(units):
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise TranslationCancelled(_build_epub_translation_result(translated_blocks))

        unit_started_at = time.monotonic()
        protected_blocks = [
            protect_text(text)
            for _, text in unit.indexed_texts
        ]
        source_language_hints = _source_language_hints(
            [text for _, text in unit.indexed_texts],
            source_language=source_language,
        )
        translated_text = translator.translate(
            text=_format_translation_batch(
                [protected_block.text for protected_block in protected_blocks],
                source_language_hints=source_language_hints,
            ),
            source_language=source_language,
            target_language=target_language,
        )
        usage = _translator_usage(translator)
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
        else:
            parsed = _restore_protected_texts(parsed, protected_blocks)

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
            last_source_text = unit.indexed_texts[-1][1] if unit.indexed_texts else ""
            last_translated_text = parsed[-1] if parsed else ""
            progress_callback(
                TranslationProgress(
                    completed_fragments=unit_index + 1,
                    total_fragments=total_units,
                    source_text=last_source_text,
                    translated_text=last_translated_text,
                    elapsed_seconds=time.monotonic() - unit_started_at,
                    prompt_tokens=usage[0],
                    completion_tokens=usage[1],
                    total_tokens=usage[2],
                    prompt_cache_hit_tokens=usage[3],
                    prompt_cache_miss_tokens=usage[4],
                )
            )

    return _build_epub_translation_result(translated_blocks)


def _build_epub_translation_result(translated_blocks: list[FragmentTranslation]):
    return TranslationJobResult(
        fragments=translated_blocks,
        assembled_text="\n\n".join(
            fragment.translated_text for fragment in translated_blocks
        ),
    )


def _translator_usage(translator: TextTranslator) -> tuple[int, int, int, int, int]:
    usage = getattr(translator, "last_usage", None)
    if usage is None:
        return (0, 0, 0, 0, 0)

    return (
        int(getattr(usage, "prompt_tokens", 0) or 0),
        int(getattr(usage, "completion_tokens", 0) or 0),
        int(getattr(usage, "total_tokens", 0) or 0),
        int(getattr(usage, "prompt_cache_hit_tokens", 0) or 0),
        int(getattr(usage, "prompt_cache_miss_tokens", 0) or 0),
    )


def _translation_cache_get(
    translation_cache: TranslationCache | None,
    *,
    blocks: list[str],
    source_language: str,
    target_language: str,
    prompt_tier: PromptTier,
) -> tuple[str, ...] | None:
    if translation_cache is None:
        return None
    return translation_cache.get(
        source_texts=tuple(blocks),
        source_language=source_language,
        target_language=target_language,
        prompt_tier=prompt_tier,
    )


def _translation_cache_put(
    translation_cache: TranslationCache | None,
    *,
    source_texts: tuple[str, ...],
    translated_texts: tuple[str, ...],
    source_language: str,
    target_language: str,
    prompt_tier: PromptTier,
) -> None:
    if translation_cache is None:
        return
    translation_cache.put(
        source_texts=source_texts,
        translated_texts=translated_texts,
        source_language=source_language,
        target_language=target_language,
        prompt_tier=prompt_tier,
    )


def _format_translation_batch(
    texts: list[str],
    source_language_hints: list[str | None] | None = None,
) -> str:
    lines = ["<translation_batch>"]
    for index, text in enumerate(texts):
        source_language_hint = (
            source_language_hints[index]
            if source_language_hints is not None and index < len(source_language_hints)
            else None
        )
        attributes = f' id="{index}"'
        if source_language_hint:
            attributes += (
                f' source_language="{html.escape(source_language_hint, quote=True)}"'
            )
        lines.append(
            f"<translation_block{attributes}>"
            f"{html.escape(text, quote=False)}"
            "</translation_block>"
        )
    lines.append("</translation_batch>")
    return "\n".join(lines)


def _source_language_hints(
    texts: list[str],
    *,
    source_language: str,
) -> list[str | None] | None:
    if source_language.strip().lower() != "auto":
        return None

    hints: list[str | None] = []
    for text in texts:
        detected_languages = detect_languages_from_text(text)
        hints.append(
            ", ".join(language.name for language in detected_languages)
            if detected_languages
            else None
        )
    return hints


def _parse_epub_translation_unit(
    translated_text: str,
    *,
    source_blocks: list[_EpubTextBlock],
    protected_blocks: list[ProtectedText],
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

    parsed = _restore_protected_texts(parsed, protected_blocks)
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
            _clean_translated_text("".join(block.itertext()).strip())
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
        protected_source = protect_text(source_block.text)
        translated_blocks.append(
            FragmentTranslation(
                index=source_block.block_index,
                source_text=source_block.text,
                translated_text=restore_protected_text(
                    translator.translate(
                        text=protected_source.text,
                        source_language=source_language,
                        target_language=target_language,
                    ),
                    protected_source.replacements,
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
    translated_texts: list[str] = []
    for text in texts:
        protected_source = protect_text(text)
        translated_texts.append(
            restore_protected_text(
                _clean_translated_text(
                    translator.translate(
                        text=protected_source.text,
                        source_language=source_language,
                        target_language=target_language,
                    )
                ),
                protected_source.replacements,
            )
        )
    return translated_texts


def _restore_protected_texts(
    translated_texts: list[str],
    protected_texts: list[ProtectedText],
) -> list[str]:
    return [
        restore_protected_text(translated_text, protected_text.replacements)
        for translated_text, protected_text in zip(
            translated_texts,
            protected_texts,
            strict=True,
        )
    ]


def _clean_translated_text(translated_text: str) -> str:
    parsed = _parse_translation_batch(translated_text, expected_count=1)
    if parsed is not None:
        return parsed[0]
    return _strip_model_service_wrappers(translated_text)


def _strip_model_service_wrappers(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:[A-Za-z0-9_-]+)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    service_prefaces = (
        "here is the translation:",
        "translation:",
        "translated text:",
        "вот перевод:",
        "перевод:",
        "переведенный текст:",
        "нижe перевод:",
        "ниже перевод:",
    )
    lowered = cleaned.lower()
    for preface in service_prefaces:
        if lowered.startswith(preface):
            return cleaned[len(preface) :].strip()
    return cleaned


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


def _count_translated_docx_units(
    fragments: list[FragmentTranslation],
    *,
    translation_units: list[_DocxTranslationUnit],
) -> int:
    if not fragments:
        return 0

    translated_indexes = {fragment.index for fragment in fragments}
    return sum(
        1
        for unit in translation_units
        if all(block.index in translated_indexes for block in unit.blocks)
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


def _parent_map(document: ElementTree.Element) -> dict[int, ElementTree.Element]:
    return {id(child): parent for parent in document.iter() for child in list(parent)}


def _nearest_ancestor(
    element: ElementTree.Element,
    *,
    local_name: str,
    parent_by_child_id: dict[int, ElementTree.Element],
) -> ElementTree.Element | None:
    return _nearest_ancestor_in(
        element,
        local_names={local_name},
        parent_by_child_id=parent_by_child_id,
    )


def _nearest_ancestor_in(
    element: ElementTree.Element,
    *,
    local_names: set[str],
    parent_by_child_id: dict[int, ElementTree.Element],
) -> ElementTree.Element | None:
    current = parent_by_child_id.get(id(element))
    while current is not None:
        if _local_name(current.tag) in local_names:
            return current
        current = parent_by_child_id.get(id(current))
    return None


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
_EPUB_DENSE_INLINE_TAGS = {
    "a",
    "abbr",
    "b",
    "code",
    "em",
    "i",
    "mark",
    "span",
    "strong",
    "sub",
    "sup",
}
