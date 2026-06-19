from __future__ import annotations

import html
import re
from dataclasses import dataclass
from io import BytesIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from translator_service.extractors import (
    TextExtractionError,
    parse_xml_document,
    validate_archive_members,
)
from translator_service.structure_optimizer import (
    PromptTier,
    StructuredTextBlock,
    TextBlockKind,
    build_translation_units,
)


@dataclass(frozen=True)
class DocxTextBlock:
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
class DocxTranslationUnit:
    blocks: list[DocxTextBlock]
    prompt_tier: PromptTier = PromptTier.PLAIN

    @property
    def text(self) -> str:
        return _format_translation_batch([block.text for block in self.blocks])


def extract_docx_blocks(content: bytes) -> list[DocxTextBlock]:
    try:
        with ZipFile(BytesIO(content)) as docx:
            validate_archive_members(docx)
            part_names = _docx_text_part_names(docx)
            if "word/document.xml" not in docx.namelist():
                raise KeyError("word/document.xml")
            blocks: list[DocxTextBlock] = []
            for part_name in part_names:
                document = read_docx_xml(docx.read(part_name))
                for block_index, paragraph_block in enumerate(
                    _extract_docx_part_blocks(document, part_name=part_name)
                ):
                    blocks.append(
                        DocxTextBlock(
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


def group_docx_blocks(
    blocks: list[DocxTextBlock],
    *,
    max_fragment_chars: int,
) -> list[DocxTranslationUnit]:
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
        DocxTranslationUnit(
            blocks=[blocks[unit_block.index] for unit_block in optimized_unit.blocks],
            prompt_tier=optimized_unit.prompt_tier,
        )
        for optimized_unit in optimized_units
    ]


def read_docx_xml(content: bytes) -> ElementTree.Element:
    return parse_xml_document(
        content,
        parse_error_message="DOCX document XML is not readable",
    )


def docx_paragraph_text(
    paragraph: ElementTree.Element,
    *,
    namespace: dict[str, str],
    include_preserved_text: bool = True,
) -> str:
    preserved_text_node_ids = (
        set()
        if include_preserved_text
        else _docx_non_translatable_text_node_ids(
            paragraph=paragraph,
            namespace=namespace,
        )
    )
    pieces: list[str] = []
    for element in paragraph.iter():
        local_name = _local_name(element.tag)
        if local_name == "t":
            if id(element) in preserved_text_node_ids:
                continue
            pieces.append(element.text or "")
            continue
        if local_name == "tab":
            pieces.append("\t")
            continue
        if local_name == "br" and element.get(f"{{{namespace['w']}}}type") != "page":
            pieces.append("\n")
    return "".join(pieces)


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
        paragraph_text = docx_paragraph_text(
            paragraph,
            namespace=namespace,
            include_preserved_text=False,
        ).strip()
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
    ) or ""
    if style_value.lower().startswith("heading"):
        return TextBlockKind.HEADING, None

    return TextBlockKind.PLAIN, None


def _docx_paragraph_protected_phrases(
    *,
    paragraph: ElementTree.Element,
    namespace: dict[str, str],
) -> tuple[str, ...]:
    phrases: list[str] = []
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
        if any(
            "courier" in font_name or "mono" in font_name
            for font_name in font_names
        ):
            return True
    return False


def _docx_non_translatable_text_node_ids(
    *,
    paragraph: ElementTree.Element,
    namespace: dict[str, str],
) -> set[int]:
    preserved_node_ids: set[int] = set()

    for hyperlink in paragraph.findall(".//w:hyperlink", namespace):
        for text_node in hyperlink.findall(".//w:t", namespace):
            preserved_node_ids.add(id(text_node))

    for run in paragraph.findall(".//w:r", namespace):
        if not _is_non_translatable_docx_run(run, namespace=namespace):
            continue
        for text_node in run.findall(".//w:t", namespace):
            preserved_node_ids.add(id(text_node))

    return preserved_node_ids


def _is_non_translatable_docx_run(
    run: ElementTree.Element,
    *,
    namespace: dict[str, str],
) -> bool:
    run_properties = run.find("w:rPr", namespace)
    if run_properties is None:
        return False
    if run_properties.find("w:vanish", namespace) is not None:
        return True

    run_style = run_properties.find("w:rStyle", namespace)
    if run_style is not None:
        style_value = (
            run_style.get(f"{{{namespace['w']}}}val")
            or run_style.get("val")
            or ""
        )
        if "donottranslate" in style_value.lower():
            return True

    color = run_properties.find("w:color", namespace)
    if color is not None:
        color_value = (
            color.get(f"{{{namespace['w']}}}val")
            or color.get("val")
            or ""
        ).strip().lower()
        if color_value in {"fff", "ffffff", "white"}:
            return True

    return False


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
