import html
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from translator_service.book_mode_output_audit import (
    _GUTENBERG_LEGAL_BACKMATTER_RE,
    _LEGAL_BACKMATTER_TERMS,
    BookModeAuditChunk,
)
from translator_service.content_roles import (
    ContentRoleAnnotation,
    ContentRoleEvidence,
    SourceLocator,
    content_role_metadata_pairs,
    reporting_bucket_for_annotation,
)
from translator_service.documents import DocumentFormat
from translator_service.extractors import (
    TextExtractionError,
    parse_xml_document,
    validate_archive_members,
    validate_epub_text_block_count,
)
from translator_service.format_adapters.contracts import (
    FormatAdapterPlan,
    FormatTextBlock,
    FormatTranslationUnit,
)
from translator_service.format_adapters.epub_repair import (
    normalize_epub_xml_part_for_xml,
    repair_epub_for_processing,
)
from translator_service.structure_optimizer import (
    PromptTier,
    StructuredTextBlock,
    TextBlockKind,
    build_translation_units,
    estimate_unit_input_tokens,
)
from translator_service.translation_jobs import FragmentTranslation
from translator_service.translation_postprocess import clean_inline_formatting_artifacts

EPUB_ADAPTER_VERSION = "epub-adapter-v1"
_XHTML_NAMESPACE = "http://www.w3.org/1999/xhtml"
_EPUB_NAMESPACE = "http://www.idpf.org/2007/ops"
_XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"

ElementTree.register_namespace("", _XHTML_NAMESPACE)
ElementTree.register_namespace("epub", _EPUB_NAMESPACE)


def epub_body_block_id(file_name: str, block_index: int) -> str:
    return f"epub:{file_name}:{block_index}"


def epub_aux_block_id(
    *,
    kind: str,
    file_name: str,
    local_name: str,
    index: int,
) -> str:
    return f"epub:aux:{kind}:{file_name}:{local_name}:{index}"


@dataclass(frozen=True)
class EpubTextBlock:
    index: int
    file_name: str
    block_index: int
    text: str
    kind: TextBlockKind = TextBlockKind.PLAIN
    group_id: str | None = None
    role: str = "body"


@dataclass(frozen=True)
class EpubTranslationUnit:
    blocks: list[EpubTextBlock]
    prompt_tier: PromptTier = PromptTier.PLAIN

    @property
    def text(self) -> str:
        return _format_epub_translation_batch([block.text for block in self.blocks])


def extract_epub_translation_blocks(content: bytes) -> list[EpubTextBlock]:
    return _extract_epub_blocks(content)


def group_epub_translation_blocks(
    blocks: list[EpubTextBlock],
    *,
    max_fragment_chars: int,
) -> list[EpubTranslationUnit]:
    return _group_epub_blocks(blocks, max_fragment_chars=max_fragment_chars)


def replace_epub_body_blocks(
    content: bytes,
    blocks: list[EpubTextBlock],
    translated_fragments: list[FragmentTranslation],
    target_language: str | None = None,
) -> bytes:
    return _replace_epub_blocks(
        content,
        blocks,
        translated_fragments,
        target_language=target_language,
    )


def extract_epub_book_mode_audit_chunks(
    content: bytes,
) -> tuple[BookModeAuditChunk, ...]:
    repaired = repair_epub_for_processing(content)
    chunks: list[BookModeAuditChunk] = []
    try:
        with ZipFile(BytesIO(repaired.content)) as epub:
            validate_archive_members(epub)
            _collect_epub_opf_audit_chunks(epub=epub, chunks=chunks)
            _collect_epub_ncx_audit_chunks(epub=epub, chunks=chunks)
            _collect_epub_xhtml_audit_chunks(epub=epub, chunks=chunks)
    except (BadZipFile, KeyError) as error:
        raise TextExtractionError(
            "EPUB file does not contain readable book text"
        ) from error
    return tuple(chunks)


def plan_epub_translation(
    *,
    content: bytes,
    max_fragment_chars: int,
    adapter_version: str = EPUB_ADAPTER_VERSION,
) -> FormatAdapterPlan:
    repaired = repair_epub_for_processing(content)
    content = repaired.content
    body_units = tuple(
        _epub_translation_unit(sequence=sequence, unit=unit)
        for sequence, unit in enumerate(
            group_epub_translation_blocks(
                extract_epub_translation_blocks(content),
                max_fragment_chars=max_fragment_chars,
            ),
            start=1,
        )
    )
    auxiliary_blocks = _collect_epub_auxiliary_blocks(content)
    auxiliary_units = tuple(
        _epub_auxiliary_translation_unit(
            sequence=len(body_units) + sequence,
            block=block,
        )
        for sequence, block in enumerate(auxiliary_blocks, start=1)
    )
    units = body_units + auxiliary_units
    return FormatAdapterPlan(
        document_format=DocumentFormat.EPUB,
        adapter_version=adapter_version,
        units=units,
        character_count=len(
            "\n\n".join(
                block.text
                for unit in units
                for block in unit.blocks
            ).strip()
        ),
        estimated_input_tokens=_estimate_epub_input_tokens(units),
    )


def assemble_epub_content_from_block_translations(
    *,
    source_content: bytes,
    translated_by_block_id: dict[str, str],
    target_language: str | None = None,
) -> bytes:
    repaired = repair_epub_for_processing(source_content)
    source_content = repaired.content
    blocks = extract_epub_translation_blocks(source_content)
    translated_fragments = [
        FragmentTranslation(
            index=block.index,
            source_text=block.text,
            translated_text=translated_text,
        )
        for block in blocks
        if (
            translated_text := translated_by_block_id.get(
                epub_body_block_id(block.file_name, block.block_index)
            )
        )
        is not None
    ]
    content = replace_epub_body_blocks(
        source_content,
        blocks,
        translated_fragments,
        target_language=target_language,
    )
    if not (
        target_language
        or _has_auxiliary_translations(translated_by_block_id)
    ):
        return content
    return _replace_epub_auxiliary_content(
        content,
        translated_by_block_id=translated_by_block_id,
        target_language=target_language,
    )


def _epub_translation_unit(*, sequence: int, unit) -> FormatTranslationUnit:
    return FormatTranslationUnit(
        sequence=sequence,
        blocks=tuple(_epub_text_block(block) for block in unit.blocks),
        prompt_tier=unit.prompt_tier,
    )


def _epub_text_block(block) -> FormatTextBlock:
    return FormatTextBlock(
        index=block.index,
        source_block_id=epub_body_block_id(block.file_name, block.block_index),
        text=block.text,
        kind=block.kind,
        group_id=block.group_id,
        metadata=(
            ("file_name", block.file_name),
            ("block_index", str(block.block_index)),
            ("role", block.role),
        ),
    )


def _epub_auxiliary_translation_unit(
    *,
    sequence: int,
    block: FormatTextBlock,
) -> FormatTranslationUnit:
    return FormatTranslationUnit(
        sequence=sequence,
        blocks=(block,),
        prompt_tier=PromptTier.PLAIN,
    )


def _extract_epub_blocks(content: bytes) -> list[EpubTextBlock]:
    try:
        with ZipFile(BytesIO(content)) as epub:
            validate_archive_members(epub)
            blocks: list[EpubTextBlock] = []
            for file_name in _epub_text_item_names(epub):
                document = _read_epub_xhtml(epub.read(file_name))
                parent_by_child_id = _parent_map(document)
                group_index_by_element_id = _epub_group_indexes(document)
                extracted_elements = [
                    (block_index, element, _visible_text(element))
                    for block_index, element in enumerate(
                        _iter_epub_text_elements(document)
                    )
                ]
                text_elements = [
                    (block_index, element, text)
                    for block_index, element, text in extracted_elements
                    if text
                ]
                is_navigation_file = _is_epub_navigation_document(
                    file_name=file_name,
                    document=document,
                    texts=[text for _, _, text in text_elements],
                )
                for block_index, element, text in text_elements:
                    kind, group_id = _epub_block_structure(
                        element,
                        file_name=file_name,
                        parent_by_child_id=parent_by_child_id,
                        group_index_by_element_id=group_index_by_element_id,
                    )
                    blocks.append(
                        EpubTextBlock(
                            index=len(blocks),
                            file_name=file_name,
                            block_index=block_index,
                            text=text,
                            kind=kind,
                            group_id=group_id,
                            role=_epub_block_role(
                                element=element,
                                text=text,
                                parent_by_child_id=parent_by_child_id,
                                is_navigation_file=is_navigation_file,
                            ),
                        )
                    )
                    validate_epub_text_block_count(len(blocks))
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
    epub_type = _epub_type(element)
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
        epub_type = _epub_type(current)
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


def _is_epub_navigation_document(
    *,
    file_name: str,
    document: ElementTree.Element,
    texts: list[str],
) -> bool:
    lowered_file_name = file_name.lower()
    if any(part in lowered_file_name for part in ("nav", "toc", "contents")):
        return True
    if any(_local_name(element.tag) == "nav" for element in document.iter()):
        return True
    if _looks_like_epub_contents_heading(texts[0] if texts else ""):
        following_texts = texts[1:]
        if following_texts and (
            sum(
                1
                for text in following_texts
                if _is_epub_noise_text(text) or _looks_like_epub_navigation_entry(text)
            )
            / len(following_texts)
            >= 0.5
        ):
            return True
    if len(texts) < 20:
        return False

    navigation_like_count = sum(
        1
        for text in texts
        if _is_epub_noise_text(text) or _looks_like_epub_navigation_entry(text)
    )
    return navigation_like_count / len(texts) >= 0.65


def _epub_block_role(
    *,
    element: ElementTree.Element,
    text: str,
    parent_by_child_id: dict[int, ElementTree.Element],
    is_navigation_file: bool,
) -> str:
    if is_navigation_file or _is_inside_epub_navigation(element, parent_by_child_id):
        return _EPUB_BLOCK_ROLE_NAVIGATION
    if _is_epub_noise_text(text):
        return _EPUB_BLOCK_ROLE_NOISE
    return _EPUB_BLOCK_ROLE_BODY


def _is_inside_epub_navigation(
    element: ElementTree.Element,
    parent_by_child_id: dict[int, ElementTree.Element],
) -> bool:
    current: ElementTree.Element | None = element
    while current is not None:
        local_name = _local_name(current.tag)
        epub_type = _epub_type(current)
        if local_name == "nav" or any(
            token in epub_type for token in ("toc", "landmarks", "page-list")
        ):
            return True
        current = parent_by_child_id.get(id(current))
    return False


def _epub_type(element: ElementTree.Element) -> str:
    return (
        element.attrib.get("epub:type", "")
        or element.attrib.get("{http://www.idpf.org/2007/ops}type", "")
    ).lower()


def _is_epub_heading_element(element: ElementTree.Element) -> bool:
    return _local_name(element.tag) in {"h1", "h2", "h3", "h4", "h5", "h6"}


def _is_epub_noise_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if re.fullmatch(r"[\*\s•·—–-]+", stripped):
        return True
    if re.fullmatch(r"\d+", stripped):
        return True
    if stripped.lower() in {"notes", "note", "примечания", "примітки"}:
        return True
    return False


def _looks_like_epub_navigation_entry(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) > 80:
        return False
    return bool(
        re.match(
            r"^(annotation|contents|notes|chapter|part|глава|часть|розділ|частина|"
            r"благодарности|подяки|об авторе|про автора|примечания|примітки)"
            r"(\b|\s|\d)",
            stripped,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_epub_contents_heading(text: str) -> bool:
    return text.strip().lower() in {
        "contents",
        "table of contents",
        "оглавление",
        "содержание",
        "зміст",
    }


def _replace_epub_blocks(
    content: bytes,
    blocks: list[EpubTextBlock],
    translated_fragments: list[FragmentTranslation],
    target_language: str | None,
) -> bytes:
    translated_by_block_index = {
        fragment.index: fragment.translated_text for fragment in translated_fragments
    }
    replacements_by_file: dict[str, dict[int, str]] = {}
    for block in blocks:
        translated_text = translated_by_block_index.get(block.index)
        if translated_text is None:
            continue
        replacements_by_file.setdefault(block.file_name, {})[
            block.block_index
        ] = _clean_epub_translated_text(
            translated_text,
            target_language=target_language,
        )

    source = BytesIO(content)
    target = BytesIO()

    with ZipFile(source) as source_epub, ZipFile(target, "w") as target_epub:
        validate_archive_members(source_epub)
        for item in source_epub.infolist():
            data = source_epub.read(item)
            if _is_epub_text_item(item.filename):
                data = _replace_epub_xhtml_blocks(
                    data,
                    replacements_by_file.get(item.filename, {}),
                )
            elif item.filename.lower().endswith(".ncx"):
                data = normalize_epub_xml_part_for_xml(data)
            target_epub.writestr(item, data)

    return target.getvalue()


def _group_epub_blocks(
    blocks: list[EpubTextBlock],
    *,
    max_fragment_chars: int,
) -> list[EpubTranslationUnit]:
    translatable_blocks = [
        block
        for block in blocks
        if block.role == _EPUB_BLOCK_ROLE_BODY
    ]
    optimized_units = build_translation_units(
        [
            StructuredTextBlock(
                index=index,
                text=block.text,
                kind=block.kind,
                group_id=block.group_id,
            )
            for index, block in enumerate(translatable_blocks)
        ],
        max_fragment_chars=max_fragment_chars,
    )
    return [
        EpubTranslationUnit(
            blocks=[
                translatable_blocks[unit_block.index]
                for unit_block in optimized_unit.blocks
            ],
            prompt_tier=optimized_unit.prompt_tier,
        )
        for optimized_unit in optimized_units
    ]


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


def _epub_text_slots(
    element: ElementTree.Element,
) -> list[tuple[ElementTree.Element, str]]:
    if (
        _local_name(element.tag) in _EPUB_IGNORED_TAGS
        or _is_epub_atomic_inline_text(element)
    ):
        return []

    slots = [(element, "text")]
    for child in list(element):
        if not _is_epub_atomic_inline_text(child):
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
    for index, _length in enumerate(lengths):
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


def _iter_epub_text_elements(document: ElementTree.Element):
    for element in document.iter():
        if _is_epub_text_element(element):
            yield element


def _visible_text(element: ElementTree.Element) -> str:
    pieces = list(_iter_visible_text(element))
    return " ".join("".join(pieces).split())


def _epub_text_element_texts(document: ElementTree.Element) -> list[str]:
    texts: list[str] = []
    for element in _iter_epub_text_elements(document):
        text = _visible_text(element)
        if text:
            texts.append(text)
    return texts


def _iter_visible_text(element: ElementTree.Element):
    if (
        _local_name(element.tag) in _EPUB_IGNORED_TAGS
        or _is_epub_atomic_inline_text(element)
    ):
        return

    if element.text:
        yield element.text

    for child in list(element):
        if not _is_epub_atomic_inline_text(child):
            yield from _iter_visible_text(child)
        if child.tail:
            yield child.tail


def _is_epub_atomic_inline_text(element: ElementTree.Element) -> bool:
    return _is_epub_note_reference(element)


def _is_epub_note_reference(element: ElementTree.Element) -> bool:
    if _local_name(element.tag) != "a":
        return False

    epub_type = _epub_type(element)
    if "noteref" in epub_type:
        return True

    href = element.attrib.get("href", "")
    if not href:
        return False
    if _EPUB_NOTE_HREF_PATTERN.search(href):
        return True

    return any(
        _local_name(descendant.tag) == "sup"
        and _looks_like_epub_note_marker("".join(descendant.itertext()))
        for descendant in element.iter()
    )


def _looks_like_epub_note_marker(text: str) -> bool:
    return bool(re.fullmatch(r"[\[\(]?\d{1,4}[\]\)]?", text.strip()))


def _element_direct_text(element: ElementTree.Element) -> str:
    return (element.text or "").strip()


def _collect_epub_auxiliary_blocks(content: bytes) -> tuple[FormatTextBlock, ...]:
    try:
        with ZipFile(BytesIO(content)) as epub:
            validate_archive_members(epub)
            blocks: list[FormatTextBlock] = []
            _collect_epub_opf_auxiliary_blocks(epub=epub, blocks=blocks)
            _collect_epub_ncx_auxiliary_blocks(epub=epub, blocks=blocks)
            _collect_epub_xhtml_auxiliary_blocks(epub=epub, blocks=blocks)
            return tuple(blocks)
    except (BadZipFile, KeyError) as error:
        raise TextExtractionError(
            "EPUB file does not contain readable book text"
        ) from error


def _replace_epub_auxiliary_content(
    content: bytes,
    *,
    translated_by_block_id: dict[str, str],
    target_language: str | None,
) -> bytes:
    source = BytesIO(content)
    target = BytesIO()

    with ZipFile(source) as source_epub, ZipFile(target, "w") as target_epub:
        validate_archive_members(source_epub)
        opf_path = _epub_package_path(source_epub)
        for item in source_epub.infolist():
            data = source_epub.read(item)
            if item.filename == opf_path and _has_opf_auxiliary_replacements(
                file_name=item.filename,
                translated_by_block_id=translated_by_block_id,
                target_language=target_language,
            ):
                data = _replace_epub_opf_auxiliary_text(
                    data,
                    file_name=item.filename,
                    translated_by_block_id=translated_by_block_id,
                    target_language=target_language,
                )
            elif item.filename.lower().endswith(".ncx"):
                if target_language or _has_auxiliary_translation_for_file(
                    translated_by_block_id,
                    kind="ncx",
                    file_name=item.filename,
                ):
                    data = _replace_epub_ncx_auxiliary_text(
                        data,
                        file_name=item.filename,
                        translated_by_block_id=translated_by_block_id,
                        target_language=target_language,
                    )
                else:
                    data = normalize_epub_xml_part_for_xml(data)
            elif _is_epub_text_item(item.filename) and (
                target_language
                or _has_auxiliary_translation_for_file(
                    translated_by_block_id,
                    kind="xhtml-title",
                    file_name=item.filename,
                )
                or _has_auxiliary_translation_for_file(
                    translated_by_block_id,
                    kind="xhtml-navigation",
                    file_name=item.filename,
                )
            ):
                data = _replace_epub_xhtml_auxiliary_text(
                    data,
                    file_name=item.filename,
                    translated_by_block_id=translated_by_block_id,
                    target_language=target_language,
                )
            target_epub.writestr(item, data)

    return target.getvalue()


def _has_auxiliary_translations(translated_by_block_id: dict[str, str]) -> bool:
    return any(
        block_id.startswith("epub:aux:") and bool(translated_text)
        for block_id, translated_text in translated_by_block_id.items()
    )


def _has_opf_auxiliary_replacements(
    *,
    file_name: str,
    translated_by_block_id: dict[str, str],
    target_language: str | None,
) -> bool:
    return bool(target_language) or _has_auxiliary_translation_for_file(
        translated_by_block_id,
        kind="opf",
        file_name=file_name,
    )


def _has_auxiliary_translation_for_file(
    translated_by_block_id: dict[str, str],
    *,
    kind: str,
    file_name: str,
) -> bool:
    prefix = f"epub:aux:{kind}:{file_name}:"
    return any(
        block_id.startswith(prefix) and bool(translated_text)
        for block_id, translated_text in translated_by_block_id.items()
    )


def _replace_epub_opf_auxiliary_text(
    content: bytes,
    *,
    file_name: str,
    translated_by_block_id: dict[str, str],
    target_language: str | None,
) -> bytes:
    document = parse_xml_document(
        content,
        parse_error_message="EPUB package XML is not readable",
    )
    if target_language:
        _set_existing_epub_language_attrs(document, target_language)
    counters = {"title": 0, "description": 0}
    for element in document.iter():
        local_name = _local_name(element.tag)
        if local_name == "language" and target_language:
            element.text = target_language
            continue
        if local_name not in counters or not _element_direct_text(element):
            continue
        index = counters[local_name]
        counters[local_name] += 1
        translated_text = _translated_auxiliary_text(
            translated_by_block_id,
            kind="opf",
            file_name=file_name,
            local_name=local_name,
            index=index,
        )
        if translated_text:
            element.text = _clean_epub_translated_text(
                translated_text,
                target_language=target_language,
            )
    return ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)


def _replace_epub_ncx_auxiliary_text(
    content: bytes,
    *,
    file_name: str,
    translated_by_block_id: dict[str, str],
    target_language: str | None,
) -> bytes:
    document = parse_xml_document(
        normalize_epub_xml_part_for_xml(content),
        parse_error_message="EPUB NCX XML is not readable",
    )
    if target_language:
        _set_existing_epub_language_attrs(document, target_language)
    index = 0
    for element in document.iter():
        if _local_name(element.tag) != "text" or not _element_direct_text(element):
            continue
        translated_text = _translated_auxiliary_text(
            translated_by_block_id,
            kind="ncx",
            file_name=file_name,
            local_name="text",
            index=index,
        )
        if translated_text:
            element.text = _clean_epub_translated_text(
                translated_text,
                target_language=target_language,
            )
        index += 1
    return ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)


def _replace_epub_xhtml_auxiliary_text(
    content: bytes,
    *,
    file_name: str,
    translated_by_block_id: dict[str, str],
    target_language: str | None,
) -> bytes:
    document = _read_epub_xhtml(content)
    if target_language:
        _set_epub_xhtml_language_attrs(document, target_language)
    parent_by_child_id = _parent_map(document)
    is_navigation_document = _is_epub_navigation_document(
        file_name=file_name,
        document=document,
        texts=_epub_text_element_texts(document),
    )
    title_index = 0
    navigation_index_by_local_name: dict[str, int] = {}
    seen_element_ids: set[int] = set()
    for element in document.iter():
        local_name = _local_name(element.tag)
        if _is_xhtml_head_title(element, parent_by_child_id):
            if not _element_direct_text(element):
                continue
            translated_text = _translated_auxiliary_text(
                translated_by_block_id,
                kind="xhtml-title",
                file_name=file_name,
                local_name=local_name,
                index=title_index,
            )
            if translated_text:
                element.text = _clean_epub_translated_text(
                    translated_text,
                    target_language=target_language,
                )
            title_index += 1
            continue

        if not _is_epub_navigation_auxiliary_element(
            element,
            parent_by_child_id,
            is_navigation_document=is_navigation_document,
        ):
            continue
        text = _visible_text(element)
        if not text or id(element) in seen_element_ids:
            continue
        seen_element_ids.add(id(element))
        index = navigation_index_by_local_name.get(local_name, 0)
        navigation_index_by_local_name[local_name] = index + 1
        translated_text = _translated_auxiliary_text(
            translated_by_block_id,
            kind="xhtml-navigation",
            file_name=file_name,
            local_name=local_name,
            index=index,
        )
        if translated_text:
            _replace_text_node_sequence(
                _epub_text_slots(element),
                _clean_epub_translated_text(
                    translated_text,
                    target_language=target_language,
                ),
            )
    return ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)


def _set_epub_xhtml_language_attrs(
    document: ElementTree.Element,
    target_language: str,
) -> None:
    _set_existing_epub_language_attrs(document, target_language)
    if _local_name(document.tag) != "html":
        return
    document.attrib["lang"] = target_language
    document.attrib[f"{{{_XML_NAMESPACE}}}lang"] = target_language


def _set_existing_epub_language_attrs(
    document: ElementTree.Element,
    target_language: str,
) -> None:
    xml_lang_key = f"{{{_XML_NAMESPACE}}}lang"
    for element in document.iter():
        if "lang" in element.attrib:
            element.attrib["lang"] = target_language
        if xml_lang_key in element.attrib:
            element.attrib[xml_lang_key] = target_language


def _clean_epub_translated_text(
    translated_text: str,
    *,
    target_language: str | None,
) -> str:
    if not target_language:
        return translated_text
    return clean_inline_formatting_artifacts(
        translated_text,
        target_language=target_language,
    )


def _translated_auxiliary_text(
    translated_by_block_id: dict[str, str],
    *,
    kind: str,
    file_name: str,
    local_name: str,
    index: int,
) -> str | None:
    return translated_by_block_id.get(
        epub_aux_block_id(
            kind=kind,
            file_name=file_name,
            local_name=local_name,
            index=index,
        )
    )


def _collect_epub_opf_auxiliary_blocks(
    *,
    epub: ZipFile,
    blocks: list[FormatTextBlock],
) -> None:
    opf_path = _epub_package_path(epub)
    if not opf_path:
        return

    document = parse_xml_document(
        epub.read(opf_path),
        parse_error_message="EPUB package XML is not readable",
    )
    counters = {"title": 0, "description": 0}
    for element in document.iter():
        local_name = _local_name(element.tag)
        if local_name not in counters:
            continue
        text = _element_direct_text(element)
        if not text:
            continue
        index = counters[local_name]
        counters[local_name] += 1
        blocks.append(
            _epub_auxiliary_text_block(
                block_index=len(blocks),
                id_kind="opf",
                file_name=opf_path,
                local_name=local_name,
                aux_index=index,
                text=text,
                aux_kind=f"opf_{local_name}",
            )
        )
        validate_epub_text_block_count(len(blocks))


def _collect_epub_ncx_auxiliary_blocks(
    *,
    epub: ZipFile,
    blocks: list[FormatTextBlock],
) -> None:
    for item in epub.infolist():
        file_name = item.filename
        if not file_name.lower().endswith(".ncx"):
            continue
        document = parse_xml_document(
            normalize_epub_xml_part_for_xml(epub.read(file_name)),
            parse_error_message="EPUB NCX XML is not readable",
        )
        index = 0
        for element in document.iter():
            local_name = _local_name(element.tag)
            if local_name != "text":
                continue
            text = _element_direct_text(element)
            if not text:
                continue
            blocks.append(
                _epub_auxiliary_text_block(
                    block_index=len(blocks),
                    id_kind="ncx",
                    file_name=file_name,
                    local_name=local_name,
                    aux_index=index,
                    text=text,
                    aux_kind="ncx_text",
                )
            )
            index += 1
            validate_epub_text_block_count(len(blocks))


def _collect_epub_xhtml_auxiliary_blocks(
    *,
    epub: ZipFile,
    blocks: list[FormatTextBlock],
) -> None:
    for file_name in _epub_text_item_names(epub):
        document = _read_epub_xhtml(epub.read(file_name))
        parent_by_child_id = _parent_map(document)
        is_navigation_document = _is_epub_navigation_document(
            file_name=file_name,
            document=document,
            texts=_epub_text_element_texts(document),
        )
        title_index = 0
        navigation_index_by_local_name: dict[str, int] = {}
        seen_element_ids: set[int] = set()
        for element in document.iter():
            local_name = _local_name(element.tag)
            if _is_xhtml_head_title(element, parent_by_child_id):
                text = _element_direct_text(element)
                if not text:
                    continue
                blocks.append(
                    _epub_auxiliary_text_block(
                        block_index=len(blocks),
                        id_kind="xhtml-title",
                        file_name=file_name,
                        local_name=local_name,
                        aux_index=title_index,
                        text=text,
                        aux_kind="xhtml_title",
                    )
                )
                title_index += 1
                validate_epub_text_block_count(len(blocks))
                continue

            if not _is_epub_navigation_auxiliary_element(
                element,
                parent_by_child_id,
                is_navigation_document=is_navigation_document,
            ):
                continue
            text = _visible_text(element)
            if not text or id(element) in seen_element_ids:
                continue
            seen_element_ids.add(id(element))
            index = navigation_index_by_local_name.get(local_name, 0)
            navigation_index_by_local_name[local_name] = index + 1
            blocks.append(
                _epub_auxiliary_text_block(
                    block_index=len(blocks),
                    id_kind="xhtml-navigation",
                    file_name=file_name,
                    local_name=local_name,
                    aux_index=index,
                    text=text,
                    aux_kind="xhtml_navigation",
                    extra_metadata=_epub_xhtml_navigation_content_role_metadata(
                        source_block_id=epub_aux_block_id(
                            kind="xhtml-navigation",
                            file_name=file_name,
                            local_name=local_name,
                            index=index,
                        )
                    ),
                )
            )
            validate_epub_text_block_count(len(blocks))


def _collect_epub_opf_audit_chunks(
    *,
    epub: ZipFile,
    chunks: list[BookModeAuditChunk],
) -> None:
    opf_path = _epub_package_path(epub)
    if not opf_path:
        return
    document = parse_xml_document(
        epub.read(opf_path),
        parse_error_message="EPUB package XML is not readable",
    )
    counters = {"title": 0, "language": 0}
    for element in document.iter():
        local_name = _local_name(element.tag)
        if local_name not in counters:
            continue
        text = _element_direct_text(element)
        if not text:
            continue
        index = counters[local_name]
        counters[local_name] += 1
        metadata = _element_language_metadata(element)
        if local_name == "language":
            metadata += (("dc:language", text),)
        chunks.append(
            BookModeAuditChunk(
                block_id=epub_aux_block_id(
                    kind="surface-opf",
                    file_name=opf_path,
                    local_name=local_name,
                    index=index,
                ),
                translated_text=text,
                block_kind="title" if local_name == "title" else "metadata",
                metadata=metadata + (("surface", f"opf_{local_name}"),),
            )
        )


def _collect_epub_ncx_audit_chunks(
    *,
    epub: ZipFile,
    chunks: list[BookModeAuditChunk],
) -> None:
    for item in epub.infolist():
        file_name = item.filename
        if not file_name.lower().endswith(".ncx"):
            continue
        document = parse_xml_document(
            normalize_epub_xml_part_for_xml(epub.read(file_name)),
            parse_error_message="EPUB NCX XML is not readable",
        )
        index = 0
        for element in document.iter():
            if _local_name(element.tag) != "text":
                continue
            text = _element_direct_text(element)
            if not text:
                continue
            chunks.append(
                BookModeAuditChunk(
                    block_id=epub_aux_block_id(
                        kind="surface-ncx",
                        file_name=file_name,
                        local_name="text",
                        index=index,
                    ),
                    translated_text=text,
                    block_kind="navigation",
                    metadata=(("surface", "toc_ncx"),),
                )
            )
            index += 1


def _collect_epub_xhtml_audit_chunks(
    *,
    epub: ZipFile,
    chunks: list[BookModeAuditChunk],
) -> None:
    for file_name in _epub_text_item_names(epub):
        document = _read_epub_xhtml(epub.read(file_name))
        parent_by_child_id = _parent_map(document)
        is_navigation_document = _is_epub_navigation_document(
            file_name=file_name,
            document=document,
            texts=_epub_text_element_texts(document),
        )
        title_index = 0
        navigation_index_by_local_name: dict[str, int] = {}
        heading_index = 0
        legal_backmatter_index = 0
        seen_element_ids: set[int] = set()
        document_language_metadata = _element_language_metadata(document)
        for element in document.iter():
            local_name = _local_name(element.tag)
            if _is_xhtml_head_title(element, parent_by_child_id):
                text = _element_direct_text(element)
                if not text:
                    continue
                chunks.append(
                    BookModeAuditChunk(
                        block_id=epub_aux_block_id(
                            kind="surface-xhtml-title",
                            file_name=file_name,
                            local_name=local_name,
                            index=title_index,
                        ),
                        translated_text=text,
                        block_kind="title",
                        metadata=(
                            document_language_metadata
                            + _element_language_metadata(element)
                            + (("surface", "xhtml_title"),)
                        ),
                    )
                )
                title_index += 1
                continue

            if _is_epub_navigation_auxiliary_element(
                element,
                parent_by_child_id,
                is_navigation_document=is_navigation_document,
            ):
                text = _visible_text(element)
                if not text or id(element) in seen_element_ids:
                    continue
                seen_element_ids.add(id(element))
                index = navigation_index_by_local_name.get(local_name, 0)
                navigation_index_by_local_name[local_name] = index + 1
                chunks.append(
                    BookModeAuditChunk(
                        block_id=epub_aux_block_id(
                            kind="surface-xhtml-navigation",
                            file_name=file_name,
                            local_name=local_name,
                            index=index,
                        ),
                        translated_text=text,
                        block_kind="navigation",
                        metadata=(("surface", "xhtml_navigation"),),
                    )
                )
                continue

            if _is_epub_heading_element(element):
                text = _visible_text(element)
                if not text:
                    continue
                chunks.append(
                    BookModeAuditChunk(
                        block_id=epub_body_block_id(file_name, heading_index),
                        translated_text=text,
                        block_kind="heading",
                        metadata=(("surface", "xhtml_body_heading"),),
                    )
                )
                heading_index += 1
                continue

            text = _visible_text(element)
            if (
                _is_epub_text_element(element)
                and _is_epub_gutenberg_legal_backmatter_text(text)
            ):
                chunks.append(
                    BookModeAuditChunk(
                        block_id=epub_aux_block_id(
                            kind="surface-xhtml-legal-backmatter",
                            file_name=file_name,
                            local_name=local_name,
                            index=legal_backmatter_index,
                        ),
                        translated_text=text,
                        block_kind="plain",
                        metadata=(("surface", "xhtml_legal_backmatter"),),
                    )
                )
                legal_backmatter_index += 1
                continue


def _is_epub_gutenberg_legal_backmatter_text(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return False
    if not _GUTENBERG_LEGAL_BACKMATTER_RE.search(normalized):
        return False
    return any(
        re.search(rf"\b{re.escape(term)}\b", normalized)
        for term in _LEGAL_BACKMATTER_TERMS
    )


def _element_language_metadata(
    element: ElementTree.Element,
) -> tuple[tuple[str, str], ...]:
    metadata: list[tuple[str, str]] = []
    for key in ("lang", f"{{{_XML_NAMESPACE}}}lang"):
        value = element.attrib.get(key)
        if value:
            metadata.append(("xml:lang" if key.startswith("{") else key, value))
    return tuple(metadata)


def _is_xhtml_head_title(
    element,
    parent_by_child_id: dict[int, object],
) -> bool:
    if _local_name(element.tag) != "title":
        return False
    parent = parent_by_child_id.get(id(element))
    return parent is not None and _local_name(parent.tag) == "head"


def _is_epub_navigation_auxiliary_element(
    element,
    parent_by_child_id: dict[int, object],
    *,
    is_navigation_document: bool = False,
) -> bool:
    if _is_inside_epub_navigation(element, parent_by_child_id):
        if _is_epub_navigation_label_element(element, parent_by_child_id):
            return True
        return (
            _is_epub_text_element(element)
            and not _has_epub_navigation_label_descendant(element)
        )
    if not is_navigation_document:
        return False
    if _is_epub_navigation_label_element(element, parent_by_child_id):
        return True
    return (
        _is_epub_text_element(element)
        and not _has_epub_navigation_label_descendant(element)
    )


def _is_epub_navigation_label_element(
    element,
    parent_by_child_id: dict[int, object],
) -> bool:
    if _local_name(element.tag) not in _EPUB_NAVIGATION_LABEL_TAGS:
        return False

    current = parent_by_child_id.get(id(element))
    while current is not None:
        if _local_name(current.tag) in _EPUB_NAVIGATION_LABEL_TAGS:
            return False
        current = parent_by_child_id.get(id(current))
    return True


def _has_epub_navigation_label_descendant(element) -> bool:
    return any(
        descendant is not element
        and _local_name(descendant.tag) in _EPUB_NAVIGATION_LABEL_TAGS
        for descendant in element.iter()
    )


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


def _epub_package_path(epub: ZipFile) -> str | None:
    try:
        container = parse_xml_document(
            epub.read("META-INF/container.xml"),
            parse_error_message="EPUB container XML is not readable",
        )
    except KeyError:
        return None

    rootfile = next(
        (
            element
            for element in container.iter()
            if _local_name(element.tag) == "rootfile"
        ),
        None,
    )
    if rootfile is None:
        return None
    return rootfile.attrib.get("full-path")


def _epub_spine_text_item_names(epub: ZipFile) -> list[str]:
    opf_path = _epub_package_path(epub)
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


def _is_epub_text_item(file_name: str) -> bool:
    return file_name.lower().endswith((".xhtml", ".html", ".htm"))


def _read_epub_xhtml(content: bytes):
    return parse_xml_document(
        normalize_epub_xml_part_for_xml(content),
        parse_error_message="EPUB XHTML content is not readable",
    )


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


def _epub_auxiliary_text_block(
    *,
    block_index: int,
    id_kind: str,
    file_name: str,
    local_name: str,
    aux_index: int,
    text: str,
    aux_kind: str,
    extra_metadata: tuple[tuple[str, str], ...] = (),
) -> FormatTextBlock:
    return FormatTextBlock(
        index=block_index,
        source_block_id=epub_aux_block_id(
            kind=id_kind,
            file_name=file_name,
            local_name=local_name,
            index=aux_index,
        ),
        text=text,
        kind=TextBlockKind.PLAIN,
        group_id=None,
        metadata=(
            (
                ("role", "auxiliary"),
                ("file_name", file_name),
                ("epub_aux_kind", aux_kind),
                ("local_name", local_name),
                ("aux_index", str(aux_index)),
            )
            + extra_metadata
        ),
    )


def _epub_xhtml_navigation_content_role_metadata(
    *,
    source_block_id: str,
) -> tuple[tuple[str, str], ...]:
    return content_role_metadata_pairs(
        ContentRoleAnnotation(
            locator=SourceLocator(
                surface="epub_xhtml_nav",
                source_path_or_chunk_id=source_block_id,
                granularity="block",
                structure_hints=("xhtml-navigation", "reader-navigation"),
                position_hint="auxiliary",
            ),
            role="reader_navigation",
            confidence="high",
            evidence=(
                ContentRoleEvidence(
                    signal_family="structural_semantic",
                    strength="strong",
                    metadata_value_kind="xhtml_nav_element",
                    reason_code="epub_xhtml_navigation_auxiliary_block",
                ),
                ContentRoleEvidence(
                    signal_family="path_class_id",
                    strength="medium",
                    metadata_value_kind="epub_aux_kind",
                    reason_code="xhtml_navigation_aux_kind",
                ),
            ),
            reporting_bucket=reporting_bucket_for_annotation(
                role="reader_navigation",
                granularity="block",
            ),
        )
    )


def _estimate_epub_input_tokens(units: tuple[FormatTranslationUnit, ...]) -> int:
    return estimate_unit_input_tokens(
        [
            _UnitTokenEstimate(
                character_count=sum(len(block.text) for block in unit.blocks),
                prompt_tier=unit.prompt_tier,
            )
            for unit in units
        ]
    )


@dataclass(frozen=True)
class _UnitTokenEstimate:
    character_count: int
    prompt_tier: PromptTier


def _format_epub_translation_batch(texts: list[str]) -> str:
    lines = ["<translation_batch>"]
    for index, text in enumerate(texts):
        lines.append(
            f'<translation_block id="{index}">'
            f"{html.escape(text, quote=False)}"
            "</translation_block>"
        )
    lines.append("</translation_batch>")
    return "\n".join(lines)


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
_EPUB_BLOCK_ROLE_BODY = "body"
_EPUB_BLOCK_ROLE_NAVIGATION = "navigation"
_EPUB_BLOCK_ROLE_NOISE = "noise"
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
_EPUB_NAVIGATION_LABEL_TAGS = {"a", "span"}
_EPUB_NOTE_HREF_PATTERN = re.compile(
    r"(?:^|[#/_-])(?:n|note|noteref|fn|footnote)[_-]?\d+\b",
    flags=re.IGNORECASE,
)
