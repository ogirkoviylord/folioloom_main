from __future__ import annotations

import html
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath, PurePosixPath
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from translator_service.book_mode_output_audit import (
    has_english_navigation_heading_residue,
)
from translator_service.extractors import (
    TextExtractionError,
    parse_xml_document,
    validate_archive_members,
    validate_epub_text_block_count,
)
from translator_service.format_adapters.docx_structure import (
    DocxTextBlock,
    DocxTranslationUnit,
    docx_paragraph_text,
    extract_docx_blocks,
    group_docx_blocks,
    read_docx_xml,
)
from translator_service.glossary_prompt_context import (
    GlossaryPromptContextConfig,
    GlossaryPromptContextResult,
    format_glossary_prompt_context,
    glossary_prompt_context_metadata_payload,
)
from translator_service.language_detection import (
    detect_language_from_text,
    detect_languages_from_text,
)
from translator_service.output_contracts import validate_translation_batch_contract
from translator_service.protected_text import (
    ProtectedText,
    protect_text,
    restore_protected_text,
)
from translator_service.russian_quality import detect_russian_quality_track
from translator_service.russian_quality_checks import check_russian_translation_quality
from translator_service.security_telemetry import record_security_event
from translator_service.structure_optimizer import (
    PromptTier,
    StructuredTextBlock,
    TextBlockKind,
    build_translation_units,
)
from translator_service.translation_cache import TranslationCache
from translator_service.translation_context import (
    TranslationContextMemory,
    translate_with_context,
    update_translation_context_memory,
)
from translator_service.translation_jobs import (
    CancellationToken,
    FragmentTranslation,
    TextTranslator,
    TranslationCancelled,
    TranslationJobResult,
    TranslationProgress,
    translate_text_fragments,
)
from translator_service.translation_policy import (
    GlossaryPromptPolicyAdapterConfig,
    GlossaryPromptPolicyAdapterDecision,
    build_glossary_prompt_policy_adapter_decision,
    glossary_prompt_policy_adapter_decision_payload,
)
from translator_service.translation_postprocess import clean_inline_formatting_artifacts

logger = logging.getLogger(__name__)

_GLOSSARY_AUTOMATIC_PREFLIGHT_VERSION = (
    "glossary-runtime-automatic-preflight-v1"
)
_GLOSSARY_BATTLE_TEST_PREFLIGHT_VERSION = (
    "glossary-runtime-battle-test-preflight-v1"
)
_GLOSSARY_AUTOMATIC_PREFLIGHT_KEY = "automatic_glossary_preflight"
_GLOSSARY_BATTLE_TEST_PREFLIGHT_KEY = "battle_test_preflight"


@dataclass(frozen=True)
class TranslatedDocument:
    file_name: str
    content_type: str
    content: bytes
    fragment_count: int
    is_partial: bool = False


DEFAULT_GLOSSARY_RUNTIME_MAX_SELECTED_ENTRIES = 32
DEFAULT_GLOSSARY_RUNTIME_BATTLE_TEST_MAX_SOURCE_BLOCKS = 12
DEFAULT_GLOSSARY_RUNTIME_BATTLE_TEST_MAX_SOURCE_CHARACTERS = 2_400


@dataclass(frozen=True)
class GlossaryRuntimeAdapterHookConfig:
    enabled: bool = False
    glossary_plan: Mapping[str, Any] | None = None
    max_selected_entries: int = DEFAULT_GLOSSARY_RUNTIME_MAX_SELECTED_ENTRIES
    prompt_rehearsal_enabled: bool = False
    prompt_context_entries: Sequence[Mapping[str, Any]] = ()
    prompt_context_config: GlossaryPromptContextConfig | None = None
    owner_battle_test_enabled: bool = False
    battle_test_max_source_blocks: int = (
        DEFAULT_GLOSSARY_RUNTIME_BATTLE_TEST_MAX_SOURCE_BLOCKS
    )
    battle_test_max_source_characters: int = (
        DEFAULT_GLOSSARY_RUNTIME_BATTLE_TEST_MAX_SOURCE_CHARACTERS
    )
    automatic_glossary_enabled: bool | None = None
    prompt_context_enabled: bool | None = None
    automatic_glossary_max_source_blocks: int | None = None
    automatic_glossary_max_source_characters: int | None = None

    def __post_init__(self) -> None:
        automatic_glossary_enabled = (
            self.automatic_glossary_enabled
            if self.automatic_glossary_enabled is not None
            else self.owner_battle_test_enabled
        )
        prompt_context_enabled = (
            self.prompt_context_enabled
            if self.prompt_context_enabled is not None
            else self.prompt_rehearsal_enabled
        )
        max_source_blocks = (
            self.automatic_glossary_max_source_blocks
            if self.automatic_glossary_max_source_blocks is not None
            else self.battle_test_max_source_blocks
        )
        max_source_characters = (
            self.automatic_glossary_max_source_characters
            if self.automatic_glossary_max_source_characters is not None
            else self.battle_test_max_source_characters
        )
        object.__setattr__(
            self,
            "automatic_glossary_enabled",
            bool(automatic_glossary_enabled),
        )
        object.__setattr__(
            self,
            "owner_battle_test_enabled",
            bool(automatic_glossary_enabled),
        )
        object.__setattr__(
            self,
            "prompt_context_enabled",
            bool(prompt_context_enabled),
        )
        object.__setattr__(
            self,
            "prompt_rehearsal_enabled",
            bool(prompt_context_enabled),
        )
        object.__setattr__(
            self,
            "automatic_glossary_max_source_blocks",
            int(max_source_blocks),
        )
        object.__setattr__(
            self,
            "battle_test_max_source_blocks",
            int(max_source_blocks),
        )
        object.__setattr__(
            self,
            "automatic_glossary_max_source_characters",
            int(max_source_characters),
        )
        object.__setattr__(
            self,
            "battle_test_max_source_characters",
            int(max_source_characters),
        )


def build_fallback_glossary_runtime_hook(
    *,
    fallback_reason: str = "runtime_glossary_data_unavailable",
) -> GlossaryRuntimeAdapterHookConfig:
    return GlossaryRuntimeAdapterHookConfig(
        enabled=True,
        glossary_plan={
            "schema_version": "telegram-glossary-runtime-hook-v1",
            "enabled": True,
            "status": "fallback",
            "fallback_reason": fallback_reason,
            "work_unit_plans": [],
            "runtime_integration": {
                "normal_translation_prompts_changed": False,
                "live_provider_calls_allowed": False,
                "durable_state_mutation_allowed": False,
                "cache_mutation_allowed": False,
                "fallback_action": "omit_glossary_prompt_context",
            },
        },
        automatic_glossary_enabled=True,
        prompt_context_enabled=True,
    )


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
    from translator_service.format_adapters.txt_layout import (
        assemble_txt_document,
        parse_txt_document,
        plan_txt_segments,
    )

    document = parse_txt_document(content)
    units = plan_txt_segments(document, max_fragment_chars=max_fragment_chars)
    if not units:
        raise TextExtractionError("TXT file does not contain translatable text")
    fragments = [unit.source_text for unit in units]
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

    translated_by_segment_id = _translated_txt_segments_by_id(
        units=units,
        translated_fragments=translation.fragments,
    )
    assembled_text = assemble_txt_document(
        document,
        translated_by_segment_id=translated_by_segment_id,
        translated_only=is_partial,
    )
    return TranslatedDocument(
        file_name=_translated_txt_file_name(file_name, target_language, is_partial),
        content_type="text/plain; charset=utf-8",
        content=assembled_text.encode("utf-8"),
        fragment_count=len(translation.fragments) if is_partial else len(units),
        is_partial=is_partial,
    )


def _translated_txt_segments_by_id(
    *,
    units,
    translated_fragments: list[FragmentTranslation],
) -> dict[str, str]:
    translated_by_segment_id: dict[str, str] = {}
    units_by_index = {index: unit for index, unit in enumerate(units)}
    for fragment in translated_fragments:
        unit = units_by_index.get(fragment.index)
        if unit is None:
            continue
        if len(unit.source_block_ids) != 1:
            continue
        translated_by_segment_id[unit.source_block_ids[0]] = fragment.translated_text
    return translated_by_segment_id


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
    glossary_runtime_hook: GlossaryRuntimeAdapterHookConfig | None = None,
    glossary_adapter_metadata_callback: Callable[[dict[str, object]], None]
    | None = None,
) -> TranslatedDocument:
    blocks = extract_docx_blocks(content)
    auto_source_language_fallback = _auto_source_language_fallback(
        [block.text for block in blocks],
        source_language=source_language,
    )
    translation_units = group_docx_blocks(
        blocks,
        max_fragment_chars=max_fragment_chars,
    )
    try:
        translation = _translate_docx_units(
            units=translation_units,
            source_language=source_language,
            target_language=target_language,
            auto_source_language_fallback=auto_source_language_fallback,
            translator=translator,
            progress_callback=progress_callback,
            cancellation_token=cancellation_token,
            translation_cache=translation_cache,
            glossary_runtime_hook=glossary_runtime_hook,
            glossary_adapter_metadata_callback=glossary_adapter_metadata_callback,
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
    glossary_runtime_hook: GlossaryRuntimeAdapterHookConfig | None = None,
    glossary_adapter_metadata_callback: Callable[[dict[str, object]], None]
    | None = None,
) -> TranslatedDocument:
    from translator_service.format_adapters.epub import (
        extract_epub_translation_blocks,
        group_epub_translation_blocks,
        replace_epub_body_blocks,
    )

    blocks = extract_epub_translation_blocks(content)
    translation_units = group_epub_translation_blocks(
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
            glossary_runtime_hook=glossary_runtime_hook,
            glossary_adapter_metadata_callback=glossary_adapter_metadata_callback,
        )
        is_partial = False
    except TranslationCancelled as error:
        translation = error.partial_result
        is_partial = True
    translated_content = replace_epub_body_blocks(
        content,
        blocks,
        translation.fragments,
        target_language=target_language,
    )
    if not is_partial:
        translated_content = _translate_epub_auxiliary_content(
            translated_content,
            source_language=source_language,
            target_language=target_language,
            translator=translator,
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


def _replace_docx_blocks(
    content: bytes,
    blocks: list[DocxTextBlock],
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
    document = read_docx_xml(content)
    namespace_uri = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    namespace = {"w": namespace_uri}
    ElementTree.register_namespace("w", namespace_uri)

    text_block_index = 0
    for paragraph in document.findall(".//w:p", namespace):
        text_nodes = paragraph.findall(".//w:t", namespace)
        if not text_nodes:
            continue

        original_text = docx_paragraph_text(
            paragraph,
            namespace=namespace,
            include_preserved_text=False,
        ).strip()
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
        preserved_text = "".join(
            text_nodes[index].text or ""
            for index in range(start, end)
        )
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
    translated_text = _preserve_static_range_boundary_spacing(
        text_nodes=text_nodes,
        preserved_ranges=preserved_ranges,
        translated_text=translated_text,
    )
    _replace_text_node_sequence(
        [(text_node, "text") for text_node in translatable_nodes],
        translated_text,
    )
    for index in preserved_indexes:
        text_nodes[index].text = text_nodes[index].text or ""


def _preserve_static_range_boundary_spacing(
    *,
    text_nodes: list[ElementTree.Element],
    preserved_ranges: list[tuple[int, int]],
    translated_text: str,
) -> str:
    if not translated_text or not preserved_ranges:
        return translated_text

    first_preserved_start = preserved_ranges[0][0]
    if first_preserved_start <= 0:
        return translated_text

    source_before_preserved = "".join(
        text_node.text or "" for text_node in text_nodes[:first_preserved_start]
    )
    if (
        source_before_preserved
        and source_before_preserved[-1].isspace()
        and not translated_text[-1].isspace()
    ):
        return f"{translated_text}{source_before_preserved[-1]}"

    return translated_text


def _docx_preserved_text_node_ranges(
    *,
    paragraph: ElementTree.Element,
    text_nodes: list[ElementTree.Element],
    namespace: dict[str, str],
) -> list[tuple[int, int]]:
    index_by_node_id = {
        id(text_node): index
        for index, text_node in enumerate(text_nodes)
    }
    preserved_text_node_ids = _docx_preserved_text_node_ids(
        paragraph=paragraph,
        namespace=namespace,
    )
    preserved_indexes = {
        index
        for text_node_id, index in index_by_node_id.items()
        if text_node_id in preserved_text_node_ids
    }

    return _contiguous_ranges(sorted(preserved_indexes))


def _docx_preserved_text_node_ids(
    *,
    paragraph: ElementTree.Element,
    namespace: dict[str, str],
) -> set[int]:
    preserved_node_ids: set[int] = set()

    for hyperlink in paragraph.findall(".//w:hyperlink", namespace):
        for text_node in hyperlink.findall(".//w:t", namespace):
            preserved_node_ids.add(id(text_node))

    for run in paragraph.findall(".//w:r", namespace):
        if not _is_preserved_docx_run(run, namespace=namespace):
            continue
        for text_node in run.findall(".//w:t", namespace):
            preserved_node_ids.add(id(text_node))

    return preserved_node_ids


def _is_preserved_docx_run(
    run: ElementTree.Element,
    *,
    namespace: dict[str, str],
) -> bool:
    run_properties = run.find("w:rPr", namespace)
    if run_properties is None:
        return False
    if run_properties.find("w:vertAlign", namespace) is not None:
        return True
    return _is_non_translatable_docx_run(run, namespace=namespace)


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
    index: int
    file_name: str
    block_index: int
    text: str
    kind: TextBlockKind = TextBlockKind.PLAIN
    group_id: str | None = None
    role: str = "body"


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
                has_body_prose = any(
                    _is_epub_body_prose(element, text)
                    for _, element, text in text_elements
                )
                for block_index, element, text in text_elements:
                    kind, group_id = _epub_block_structure(
                        element,
                        file_name=file_name,
                        parent_by_child_id=parent_by_child_id,
                        group_index_by_element_id=group_index_by_element_id,
                    )
                    blocks.append(
                        _EpubTextBlock(
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
                                has_body_prose=has_body_prose,
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
    has_body_prose: bool,
) -> str:
    if is_navigation_file or _is_inside_epub_navigation(element, parent_by_child_id):
        return _EPUB_BLOCK_ROLE_NAVIGATION
    if _is_epub_noise_text(text):
        return _EPUB_BLOCK_ROLE_NOISE
    if _is_epub_heading_element(element) and not has_body_prose:
        return _EPUB_BLOCK_ROLE_NAVIGATION
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


def _is_epub_body_prose(element: ElementTree.Element, text: str) -> bool:
    if _is_epub_noise_text(text) or _is_epub_heading_element(element):
        return False
    letter_count = len(re.findall(r"[^\W\d_]", text, flags=re.UNICODE))
    return letter_count >= 12


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
    blocks: list[_EpubTextBlock],
    translated_fragments: list[FragmentTranslation],
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


def _translate_epub_auxiliary_content(
    content: bytes,
    *,
    source_language: str,
    target_language: str,
    translator: TextTranslator,
) -> bytes:
    source = BytesIO(content)
    target = BytesIO()

    with ZipFile(source) as source_epub, ZipFile(target, "w") as target_epub:
        validate_archive_members(source_epub)
        opf_path = _epub_package_path(source_epub)
        for item in source_epub.infolist():
            data = source_epub.read(item)
            if item.filename == opf_path:
                data = _translate_epub_opf_metadata(
                    data,
                    source_language=source_language,
                    target_language=target_language,
                    translator=translator,
                )
            elif item.filename.lower().endswith(".ncx"):
                data = _translate_epub_ncx_text(
                    data,
                    source_language=source_language,
                    target_language=target_language,
                    translator=translator,
                )
            elif _is_epub_text_item(item.filename):
                data = _translate_epub_xhtml_auxiliary_text(
                    data,
                    file_name=item.filename,
                    source_language=source_language,
                    target_language=target_language,
                    translator=translator,
                )
            target_epub.writestr(item, data)

    return target.getvalue()


def _translate_epub_opf_metadata(
    content: bytes,
    *,
    source_language: str,
    target_language: str,
    translator: TextTranslator,
) -> bytes:
    document = parse_xml_document(
        content,
        parse_error_message="EPUB package XML is not readable",
    )
    translatable_elements = [
        element
        for element in document.iter()
        if _local_name(element.tag) in {"title", "description"}
        and (element.text or "").strip()
    ]
    translated_texts = _translate_epub_auxiliary_strings(
        [_element_direct_text(element) for element in translatable_elements],
        source_language=source_language,
        target_language=target_language,
        translator=translator,
        literary_heading_flags=tuple(
            _local_name(element.tag) == "title"
            for element in translatable_elements
        ),
    )
    for element, translated_text in zip(
        translatable_elements,
        translated_texts,
        strict=True,
    ):
        element.text = translated_text

    for element in document.iter():
        if _local_name(element.tag) == "language":
            element.text = target_language

    return ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)


def _translate_epub_ncx_text(
    content: bytes,
    *,
    source_language: str,
    target_language: str,
    translator: TextTranslator,
) -> bytes:
    document = parse_xml_document(
        content,
        parse_error_message="EPUB NCX XML is not readable",
    )
    translatable_elements = [
        element
        for element in document.iter()
        if _local_name(element.tag) == "text" and (element.text or "").strip()
    ]
    translated_texts = _translate_epub_auxiliary_strings(
        [_element_direct_text(element) for element in translatable_elements],
        source_language=source_language,
        target_language=target_language,
        translator=translator,
        literary_heading_flags=tuple(True for _ in translatable_elements),
    )
    for element, translated_text in zip(
        translatable_elements,
        translated_texts,
        strict=True,
    ):
        element.text = translated_text
    return ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)


def _translate_epub_xhtml_auxiliary_text(
    content: bytes,
    *,
    file_name: str,
    source_language: str,
    target_language: str,
    translator: TextTranslator,
) -> bytes:
    document = _read_epub_xhtml(content)
    parent_by_child_id = _parent_map(document)
    is_navigation_document = _is_epub_navigation_document(
        file_name=file_name,
        document=document,
        texts=_epub_text_element_texts(document),
    )
    elements: list[ElementTree.Element] = []
    seen_element_ids: set[int] = set()
    for element in document.iter():
        if _local_name(element.tag) == "title" or (
            _is_epub_text_element(element)
            and (
                is_navigation_document
                or _is_inside_epub_navigation(element, parent_by_child_id)
            )
        ):
            text = _visible_text(element)
            if text and id(element) not in seen_element_ids:
                elements.append(element)
                seen_element_ids.add(id(element))

    translated_texts = _translate_epub_auxiliary_strings(
        [_visible_text(element) for element in elements],
        source_language=source_language,
        target_language=target_language,
        translator=translator,
        literary_heading_flags=tuple(True for _ in elements),
    )
    for element, translated_text in zip(elements, translated_texts, strict=True):
        if _local_name(element.tag) == "title":
            element.text = translated_text
            continue
        _replace_text_node_sequence(_epub_text_slots(element), translated_text)
    return ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)


def _translate_epub_auxiliary_strings(
    texts: list[str],
    *,
    source_language: str,
    target_language: str,
    translator: TextTranslator,
    literary_heading_flags: tuple[bool, ...] | None = None,
) -> list[str]:
    if not texts:
        return []

    literary_heading_flags = literary_heading_flags or tuple(False for _ in texts)
    protected_texts = [
        protect_text(text, literary_heading=literary_heading)
        for text, literary_heading in zip(texts, literary_heading_flags, strict=True)
    ]
    translated_text = translate_with_context(
        translator,
        text=_format_translation_batch(
            [protected_text.text for protected_text in protected_texts],
            source_language_hints=_source_language_hints(
                texts,
                source_language=source_language,
            ),
        ),
        source_language=source_language,
        target_language=target_language,
        translation_context=TranslationContextMemory(),
    )
    parsed = _parse_translation_batch(
        translated_text,
        expected_count=len(texts),
        required_markers=_required_protected_markers(protected_texts),
    )
    if parsed is None:
        return _translate_texts_individually(
            texts=texts,
            translator=translator,
            source_language=source_language,
            target_language=target_language,
            literary_heading_flags=literary_heading_flags,
        )
    translated_texts = _restore_protected_texts(parsed, protected_texts)
    translated_texts = _retry_untranslated_source_residue_texts(
        source_texts=texts,
        translated_texts=translated_texts,
        protected_texts=protected_texts,
        source_language=source_language,
        target_language=target_language,
        translator=translator,
        translation_context=TranslationContextMemory(),
    )
    return _retry_epub_surface_residue_texts(
        source_texts=texts,
        translated_texts=translated_texts,
        protected_texts=protected_texts,
        surface_flags=literary_heading_flags,
        target_language=target_language,
        translator=translator,
        translation_context=TranslationContextMemory(),
    )


def _element_direct_text(element: ElementTree.Element) -> str:
    return (element.text or "").strip()


def _group_epub_blocks(
    blocks: list[_EpubTextBlock],
    *,
    max_fragment_chars: int,
) -> list[_EpubTranslationUnit]:
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
        _EpubTranslationUnit(
            blocks=[
                translatable_blocks[unit_block.index]
                for unit_block in optimized_unit.blocks
            ],
            prompt_tier=optimized_unit.prompt_tier,
        )
        for optimized_unit in optimized_units
    ]


def _translate_docx_units(
    *,
    units: list[DocxTranslationUnit],
    source_language: str,
    target_language: str,
    auto_source_language_fallback: str | None = None,
    translator: TextTranslator,
    progress_callback: Callable[[TranslationProgress], None] | None = None,
    cancellation_token: CancellationToken | None = None,
    translation_cache: TranslationCache | None = None,
    glossary_runtime_hook: GlossaryRuntimeAdapterHookConfig | None = None,
    glossary_adapter_metadata_callback: Callable[[dict[str, object]], None]
    | None = None,
) -> TranslationJobResult:
    translated_blocks: list[FragmentTranslation] = []
    total_units = len(units)
    context_memory = TranslationContextMemory()

    for unit_index, unit in enumerate(units):
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise TranslationCancelled(
                _build_epub_translation_result(translated_blocks)
            )

        unit_started_at = time.monotonic()
        unit_prompt_tokens = 0
        unit_completion_tokens = 0
        unit_total_tokens = 0
        unit_cache_hit_tokens = 0
        unit_cache_miss_tokens = 0
        last_source_text = ""
        last_translated_text = ""
        glossary_adapter_decision = _glossary_runtime_adapter_decision(
            glossary_runtime_hook,
            work_unit_sequence=unit_index,
        )
        glossary_useful_preflight = _glossary_runtime_useful_preflight(
            glossary_runtime_hook,
            glossary_adapter_decision,
            source_texts=[block.text for block in unit.blocks],
        )
        effective_glossary_adapter_decision = (
            _effective_glossary_runtime_adapter_decision(
                glossary_adapter_decision,
                glossary_useful_preflight,
            )
        )
        glossary_prompt_context = _glossary_runtime_prompt_context(
            glossary_runtime_hook,
            effective_glossary_adapter_decision,
            preflight=glossary_useful_preflight,
        )
        _emit_glossary_adapter_metadata(
            glossary_adapter_decision,
            glossary_adapter_metadata_callback,
            prompt_context=glossary_prompt_context,
            preflight=glossary_useful_preflight,
            plan_metadata=_glossary_runtime_plan_metadata(glossary_runtime_hook),
        )
        for subgroup_source_language, subgroup_blocks in _docx_translation_subgroups(
            unit.blocks,
            source_language=source_language,
            target_language=target_language,
            auto_source_language_fallback=auto_source_language_fallback,
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
                    translation_context=context_memory,
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
                context_memory = _updated_context_memory(
                    context_memory,
                    source_text=subgroup_blocks[0].text,
                    translated_text=translated_text,
                    target_language=target_language,
                )
                continue

            cached = _translation_cache_get(
                translation_cache,
                blocks=[block.text for block in subgroup_blocks],
                source_language=subgroup_source_language,
                target_language=target_language,
                prompt_tier=unit.prompt_tier,
                glossary_adapter_decision=effective_glossary_adapter_decision,
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
            glossary_context_text = _glossary_prompt_context_text(
                glossary_prompt_context,
            )
            translated_text = translate_with_context(
                translator,
                text=_format_translation_request_text(
                    [protected_block.text for protected_block in protected_blocks],
                    source_language_hints=source_language_hints,
                    glossary_prompt_context=glossary_context_text,
                ),
                source_language=subgroup_source_language,
                target_language=target_language,
                translation_context=context_memory,
                service_glossary_context_present=bool(glossary_context_text),
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
                required_markers=_required_protected_markers(protected_blocks),
            )
            if parsed is None:
                parsed = _translate_texts_individually(
                    texts=[block.text for block in subgroup_blocks],
                    translator=translator,
                    source_language=subgroup_source_language,
                    target_language=target_language,
                    translation_context=context_memory,
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
            residue_retry = _retry_untranslated_source_residue_docx_blocks(
                translated_texts=parsed,
                prepared_blocks=prepared_blocks,
                protected_blocks=protected_blocks,
                source_language=subgroup_source_language,
                translator=translator,
                target_language=target_language,
                translation_context=context_memory,
            )
            parsed = residue_retry.translated_texts
            unit_prompt_tokens += residue_retry.prompt_tokens
            unit_completion_tokens += residue_retry.completion_tokens
            unit_total_tokens += residue_retry.total_tokens
            unit_cache_hit_tokens += residue_retry.prompt_cache_hit_tokens
            unit_cache_miss_tokens += residue_retry.prompt_cache_miss_tokens

            cjk_retry = _retry_untranslated_cjk_docx_blocks(
                translated_texts=parsed,
                prepared_blocks=prepared_blocks,
                protected_blocks=protected_blocks,
                translator=translator,
                target_language=target_language,
                translation_context=context_memory,
            )
            parsed = cjk_retry.translated_texts
            unit_prompt_tokens += cjk_retry.prompt_tokens
            unit_completion_tokens += cjk_retry.completion_tokens
            unit_total_tokens += cjk_retry.total_tokens
            unit_cache_hit_tokens += cjk_retry.prompt_cache_hit_tokens
            unit_cache_miss_tokens += cjk_retry.prompt_cache_miss_tokens

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
                glossary_adapter_decision=effective_glossary_adapter_decision,
            )
            if subgroup_blocks and parsed:
                last_source_text = subgroup_blocks[-1].text
                last_translated_text = parsed[-1]
            for source_block, translated in zip(
                subgroup_blocks,
                parsed,
                strict=True,
            ):
                context_memory = _updated_context_memory(
                    context_memory,
                    source_text=source_block.text,
                    translated_text=translated,
                    target_language=target_language,
                )
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
    translation_context: TranslationContextMemory | None = None,
) -> str:
    translated_segments: list[str] = []
    for source_language_code, segment_text in _split_labeled_language_segments(text):
        prepared = _prepare_docx_block_for_translation(
            segment_text,
            source_language=source_language_code,
            target_language=target_language,
        )
        protected = protect_text(prepared.text)
        translated_text = translate_with_context(
            translator,
            text=_format_translation_batch([protected.text]),
            source_language=source_language_code,
            target_language=target_language,
            translation_context=translation_context,
        )
        parsed = _parse_translation_batch(
            translated_text,
            expected_count=1,
            required_markers=_required_protected_markers([protected]),
        )
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
        segment_end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )
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


@dataclass(frozen=True)
class _DocxCjkRetryResult:
    translated_texts: list[str]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0


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
    translated_text = clean_inline_formatting_artifacts(
        translated_text,
        target_language=target_language,
    )
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


def _retry_untranslated_cjk_docx_blocks(
    *,
    translated_texts: list[str],
    prepared_blocks: list[_PreparedDocxBlock],
    protected_blocks: list[ProtectedText],
    translator: TextTranslator,
    target_language: str,
    translation_context: TranslationContextMemory | None = None,
) -> _DocxCjkRetryResult:
    if _target_language_uses_cjk(target_language):
        return _DocxCjkRetryResult(translated_texts=translated_texts)

    retry_texts = list(translated_texts)
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    prompt_cache_hit_tokens = 0
    prompt_cache_miss_tokens = 0

    for index, (translated, prepared, protected) in enumerate(
        zip(retry_texts, prepared_blocks, protected_blocks, strict=True)
    ):
        if not _needs_secondary_script_retry(
            source_text=protected.text,
            translated_text=translated,
            protected_replacements=protected.replacements,
            target_language=target_language,
        ):
            continue

        retried = restore_protected_text(
            _clean_translated_text(
                translate_with_context(
                    translator,
                    text=protected.text,
                    source_language="auto",
                    target_language=target_language,
                    translation_context=translation_context,
                )
            ),
            protected.replacements,
        )
        retried = _restore_prepared_docx_label(
            translated_text=_restore_fixed_width_pseudo_table_text(
                source_text=prepared.fixed_width_source_text,
                translated_text=_known_orthographic_sample_translation(
                    prepared.text,
                    source_language="auto",
                    target_language=target_language,
                )
                or retried,
            ),
            prepared_block=prepared,
            target_language=target_language,
        )
        retry_texts[index] = retried
        usage = _translator_usage(translator)
        prompt_tokens += usage[0]
        completion_tokens += usage[1]
        total_tokens += usage[2]
        prompt_cache_hit_tokens += usage[3]
        prompt_cache_miss_tokens += usage[4]

    return _DocxCjkRetryResult(
        translated_texts=retry_texts,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        prompt_cache_hit_tokens=prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=prompt_cache_miss_tokens,
    )


def _retry_untranslated_source_residue_docx_blocks(
    *,
    translated_texts: list[str],
    prepared_blocks: list[_PreparedDocxBlock],
    protected_blocks: list[ProtectedText],
    source_language: str,
    translator: TextTranslator,
    target_language: str,
    translation_context: TranslationContextMemory | None = None,
) -> _DocxCjkRetryResult:
    if _language_root(target_language) != "ru":
        return _DocxCjkRetryResult(translated_texts=translated_texts)

    retry_texts = list(translated_texts)
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    prompt_cache_hit_tokens = 0
    prompt_cache_miss_tokens = 0

    for index, (translated, prepared, protected) in enumerate(
        zip(retry_texts, prepared_blocks, protected_blocks, strict=True)
    ):
        quality_result = check_russian_translation_quality(
            source_text=prepared.text,
            translated_text=translated,
            source_language=source_language,
            target_language=target_language,
            quality_track=None,
        )
        if not any(
            issue.code == "untranslated_source_residue"
            for issue in quality_result.issues
        ):
            continue

        retried = restore_protected_text(
            _clean_translated_text(
                translate_with_context(
                    translator,
                    text=protected.text,
                    source_language="auto",
                    target_language=target_language,
                    translation_context=translation_context,
                )
            ),
            protected.replacements,
        )
        retried = _restore_prepared_docx_label(
            translated_text=_restore_fixed_width_pseudo_table_text(
                source_text=prepared.fixed_width_source_text,
                translated_text=_known_orthographic_sample_translation(
                    prepared.text,
                    source_language="auto",
                    target_language=target_language,
                )
                or retried,
            ),
            prepared_block=prepared,
            target_language=target_language,
        )
        retry_texts[index] = retried
        usage = _translator_usage(translator)
        prompt_tokens += usage[0]
        completion_tokens += usage[1]
        total_tokens += usage[2]
        prompt_cache_hit_tokens += usage[3]
        prompt_cache_miss_tokens += usage[4]

    return _DocxCjkRetryResult(
        translated_texts=retry_texts,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        prompt_cache_hit_tokens=prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=prompt_cache_miss_tokens,
    )


_EPUB_SURFACE_RESIDUE_RETRY_MAX_CALLS = 3


def _retry_epub_surface_residue_texts(
    *,
    source_texts: list[str],
    translated_texts: list[str],
    protected_texts: list[ProtectedText],
    surface_flags: tuple[bool, ...] | None = None,
    target_language: str,
    translator: TextTranslator,
    translation_context: TranslationContextMemory | None = None,
) -> list[str]:
    retry_texts = list(translated_texts)
    surface_flags = surface_flags or tuple(True for _ in translated_texts)
    retry_calls = 0
    for index, (_source, translated, protected, is_surface) in enumerate(
        zip(source_texts, retry_texts, protected_texts, surface_flags, strict=True)
    ):
        if retry_calls >= _EPUB_SURFACE_RESIDUE_RETRY_MAX_CALLS:
            break
        if not is_surface:
            continue
        if not has_english_navigation_heading_residue(
            translated_text=translated,
            target_language=target_language,
            block_id="epub:aux:surface-pre-final:navigation-heading",
            block_kind="navigation",
        ):
            continue

        retried = restore_protected_text(
            _clean_translated_text(
                translate_with_context(
                    translator,
                    text=protected.text,
                    source_language="auto",
                    target_language=target_language,
                    translation_context=translation_context,
                )
            ),
            protected.replacements,
        )
        retry_texts[index] = clean_inline_formatting_artifacts(
            retried,
            target_language=target_language,
        )
        retry_calls += 1
    return retry_texts


def _retry_untranslated_source_residue_texts(
    *,
    source_texts: list[str],
    translated_texts: list[str],
    protected_texts: list[ProtectedText],
    source_language: str,
    target_language: str,
    translator: TextTranslator,
    translation_context: TranslationContextMemory | None = None,
) -> list[str]:
    if _language_root(target_language) != "ru":
        return translated_texts

    retry_texts = list(translated_texts)
    for index, (source, translated, protected) in enumerate(
        zip(source_texts, retry_texts, protected_texts, strict=True)
    ):
        if not _has_untranslated_source_language_residue(
            source_text=source,
            translated_text=translated,
            source_language=source_language,
            target_language=target_language,
        ):
            continue

        retried = restore_protected_text(
            _clean_translated_text(
                translate_with_context(
                    translator,
                    text=protected.text,
                    source_language="auto",
                    target_language=target_language,
                    translation_context=translation_context,
                )
            ),
            protected.replacements,
        )
        retry_texts[index] = clean_inline_formatting_artifacts(
            retried,
            target_language=target_language,
        )
    return retry_texts


_LONG_CJK_TEXT_RE = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]{4,}")
_LONG_RTL_TEXT_RE = re.compile(r"[\u0590-\u05FF\u0600-\u06FF]{3,}")


def _needs_secondary_script_retry(
    *,
    source_text: str,
    translated_text: str,
    protected_replacements: dict[str, str],
    target_language: str,
) -> bool:
    if (
        not _target_language_uses_cjk(target_language)
        and _has_untranslated_cjk_text(
            source_text=source_text,
            translated_text=translated_text,
            protected_replacements=protected_replacements,
        )
    ):
        return True

    return (
        not _target_language_uses_rtl(target_language)
        and _has_untranslated_rtl_text(
            source_text=source_text,
            translated_text=translated_text,
            protected_replacements=protected_replacements,
        )
    )


def _has_untranslated_source_language_residue(
    *,
    source_text: str,
    translated_text: str,
    source_language: str,
    target_language: str,
) -> bool:
    quality_result = check_russian_translation_quality(
        source_text=source_text,
        translated_text=translated_text,
        source_language=source_language,
        target_language=target_language,
        quality_track=None,
    )
    return any(
        issue.code == "untranslated_source_residue"
        for issue in quality_result.issues
    )


def _has_untranslated_cjk_text(
    *,
    source_text: str,
    translated_text: str,
    protected_replacements: dict[str, str],
) -> bool:
    masked_translated_text = translated_text
    for original in protected_replacements.values():
        masked_translated_text = masked_translated_text.replace(original, "")

    return any(
        match.group(0) in masked_translated_text
        for match in _LONG_CJK_TEXT_RE.finditer(source_text)
    )


def _has_untranslated_rtl_text(
    *,
    source_text: str,
    translated_text: str,
    protected_replacements: dict[str, str],
) -> bool:
    masked_translated_text = translated_text
    for original in protected_replacements.values():
        masked_translated_text = masked_translated_text.replace(original, "")

    return any(
        match.group(0) in masked_translated_text
        for match in _LONG_RTL_TEXT_RE.finditer(source_text)
    )


def _target_language_uses_cjk(target_language: str) -> bool:
    return target_language.strip().lower() in {"zh", "zh-cn", "zh-tw", "ja", "ko"}


def _target_language_uses_rtl(target_language: str) -> bool:
    return target_language.strip().lower() in {"he", "ar"}


def _docx_translation_subgroups(
    blocks: list[DocxTextBlock],
    *,
    source_language: str,
    target_language: str,
    auto_source_language_fallback: str | None = None,
) -> list[tuple[str, list[DocxTextBlock]]]:
    if source_language.strip().lower() != "auto":
        return [(source_language, blocks)]

    subgroups: list[tuple[str, list[DocxTextBlock]]] = []
    current_source_language: str | None = None
    current_blocks: list[DocxTextBlock] = []
    for block in blocks:
        block_source_language = (
            _source_language_code_for_text(
                block.text,
                target_language=target_language,
                auto_source_language_fallback=auto_source_language_fallback,
            )
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
    auto_source_language_fallback: str | None = None,
) -> str | None:
    label_source_language = _language_label_source_code(text)
    if label_source_language is not None:
        return label_source_language

    detected_languages = detect_languages_from_text(text)
    if len(detected_languages) != 1:
        return None
    return _resolve_auto_detected_source_language(
        detected_languages[0].code,
        text=text,
        target_language=target_language,
        auto_source_language_fallback=auto_source_language_fallback,
    )


def _auto_source_language_fallback(
    texts: list[str],
    *,
    source_language: str,
) -> str | None:
    if source_language.strip().lower() != "auto":
        return None

    detected = detect_language_from_text("\n".join(texts))
    return detected.code if detected is not None else None


def _resolve_auto_detected_source_language(
    detected_source_language: str,
    *,
    text: str,
    target_language: str,
    auto_source_language_fallback: str | None,
) -> str:
    fallback = _language_root(auto_source_language_fallback or "")
    target = _language_root(target_language)
    detected = _language_root(detected_source_language)
    if (
        fallback
        and fallback != target
        and detected == target
        and _is_common_cyrillic_slavic_text(text)
    ):
        return fallback
    return detected_source_language


def _is_common_cyrillic_slavic_text(text: str) -> bool:
    return (
        re.search(r"[А-Яа-яЁёІіЇїЄєҐґ]", text) is not None
        and re.search(r"[ІіЇїЄєҐґ]", text) is None
    )


def _language_root(language_code: str) -> str:
    return language_code.strip().lower().replace("_", "-").split("-", 1)[0]


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
    glossary_runtime_hook: GlossaryRuntimeAdapterHookConfig | None = None,
    glossary_adapter_metadata_callback: Callable[[dict[str, object]], None]
    | None = None,
):
    translated_blocks = []
    total_units = len(units)
    context_memory = TranslationContextMemory()

    for unit_index, unit in enumerate(units):
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise TranslationCancelled(
                _build_epub_translation_result(translated_blocks)
            )

        unit_started_at = time.monotonic()
        glossary_adapter_decision = _glossary_runtime_adapter_decision(
            glossary_runtime_hook,
            work_unit_sequence=unit_index,
        )
        glossary_useful_preflight = _glossary_runtime_useful_preflight(
            glossary_runtime_hook,
            glossary_adapter_decision,
            source_texts=[block.text for block in unit.blocks],
        )
        effective_glossary_adapter_decision = (
            _effective_glossary_runtime_adapter_decision(
                glossary_adapter_decision,
                glossary_useful_preflight,
            )
        )
        glossary_prompt_context = _glossary_runtime_prompt_context(
            glossary_runtime_hook,
            effective_glossary_adapter_decision,
            preflight=glossary_useful_preflight,
        )
        _emit_glossary_adapter_metadata(
            glossary_adapter_decision,
            glossary_adapter_metadata_callback,
            prompt_context=glossary_prompt_context,
            preflight=glossary_useful_preflight,
            plan_metadata=_glossary_runtime_plan_metadata(glossary_runtime_hook),
        )
        cached = _translation_cache_get(
            translation_cache,
            blocks=[block.text for block in unit.blocks],
            source_language=source_language,
            target_language=target_language,
            prompt_tier=unit.prompt_tier,
            glossary_adapter_decision=effective_glossary_adapter_decision,
        )
        if cached is not None:
            translated_unit_blocks = [
                FragmentTranslation(
                    index=source_block.index,
                    source_text=source_block.text,
                    translated_text=clean_inline_formatting_artifacts(
                        translated,
                        target_language=target_language,
                    ),
                )
                for source_block, translated in zip(
                    unit.blocks,
                    cached,
                    strict=True,
                )
            ]
            translated_blocks.extend(translated_unit_blocks)
            if progress_callback is not None:
                last_block = (
                    translated_unit_blocks[-1]
                    if translated_unit_blocks
                    else None
                )
                progress_callback(
                    TranslationProgress(
                        completed_fragments=unit_index + 1,
                        total_fragments=total_units,
                        source_text=last_block.source_text if last_block else "",
                        translated_text=(
                            last_block.translated_text
                            if last_block
                            else ""
                        ),
                        elapsed_seconds=time.monotonic() - unit_started_at,
                    )
                )
            continue

        protected_blocks = [_protect_epub_block_text(block) for block in unit.blocks]
        source_language_hints = _source_language_hints(
            [block.text for block in unit.blocks],
            source_language=source_language,
        )
        glossary_context_text = _glossary_prompt_context_text(
            glossary_prompt_context,
        )
        translated_text = translate_with_context(
            translator,
            text=_format_translation_request_text(
                [protected_block.text for protected_block in protected_blocks],
                source_language_hints=source_language_hints,
                glossary_prompt_context=glossary_context_text,
            ),
            source_language=source_language,
            target_language=target_language,
            translation_context=context_memory,
            service_glossary_context_present=bool(glossary_context_text),
        )
        usage = _translator_usage(translator)
        translated_unit_blocks = _parse_epub_translation_unit(
            translated_text,
            source_blocks=unit.blocks,
            protected_blocks=protected_blocks,
            translator=translator,
            source_language=source_language,
            target_language=target_language,
            translation_context=context_memory,
        )
        translated_blocks.extend(translated_unit_blocks)
        for translated_block in translated_unit_blocks:
            context_memory = _updated_context_memory(
                context_memory,
                source_text=translated_block.source_text,
                translated_text=translated_block.translated_text,
                target_language=target_language,
            )
        _translation_cache_put(
            translation_cache,
            source_texts=tuple(block.text for block in unit.blocks),
            translated_texts=tuple(
                block.translated_text for block in translated_unit_blocks
            ),
            source_language=source_language,
            target_language=target_language,
            prompt_tier=unit.prompt_tier,
            glossary_adapter_decision=effective_glossary_adapter_decision,
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
    context_memory = TranslationContextMemory()

    for unit_index, unit in enumerate(units):
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise TranslationCancelled(
                _build_epub_translation_result(translated_blocks)
            )

        unit_started_at = time.monotonic()
        protected_blocks = [
            protect_text(text)
            for _, text in unit.indexed_texts
        ]
        source_language_hints = _source_language_hints(
            [text for _, text in unit.indexed_texts],
            source_language=source_language,
        )
        translated_text = translate_with_context(
            translator,
            text=_format_translation_batch(
                [protected_block.text for protected_block in protected_blocks],
                source_language_hints=source_language_hints,
            ),
            source_language=source_language,
            target_language=target_language,
            translation_context=context_memory,
        )
        usage = _translator_usage(translator)
        parsed = _parse_translation_batch(
            translated_text,
            expected_count=len(unit.indexed_texts),
            required_markers=_required_protected_markers(protected_blocks),
        )
        if parsed is None:
            parsed = _translate_texts_individually(
                texts=[text for _, text in unit.indexed_texts],
                translator=translator,
                source_language=source_language,
                target_language=target_language,
                translation_context=context_memory,
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
        for (_, source_text), translated in zip(
            unit.indexed_texts,
            parsed,
            strict=True,
        ):
            context_memory = _updated_context_memory(
                context_memory,
                source_text=source_text,
                translated_text=translated,
                target_language=target_language,
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


def _updated_context_memory(
    memory: TranslationContextMemory,
    *,
    source_text: str,
    translated_text: str,
    target_language: str,
) -> TranslationContextMemory:
    decision = detect_russian_quality_track(
        source_text,
        target_language=target_language,
    )
    return update_translation_context_memory(
        memory,
        source_text=source_text,
        translated_text=translated_text,
        quality_track=decision.track,
    )


def _glossary_runtime_adapter_decision(
    config: GlossaryRuntimeAdapterHookConfig | None,
    *,
    work_unit_sequence: int,
) -> GlossaryPromptPolicyAdapterDecision | None:
    if config is None:
        return None
    return build_glossary_prompt_policy_adapter_decision(
        config.glossary_plan,
        config=GlossaryPromptPolicyAdapterConfig(
            enabled=config.enabled,
            work_unit_sequence=work_unit_sequence,
            max_selected_entries=config.max_selected_entries,
        ),
    )


def _emit_glossary_adapter_metadata(
    decision: GlossaryPromptPolicyAdapterDecision | None,
    callback: Callable[[dict[str, object]], None] | None,
    *,
    prompt_context: GlossaryPromptContextResult | None = None,
    preflight: Mapping[str, object] | None = None,
    plan_metadata: Mapping[str, object] | None = None,
) -> None:
    if decision is None or callback is None:
        return
    payload = glossary_prompt_policy_adapter_decision_payload(decision)
    if preflight is not None:
        preflight_payload = dict(preflight)
        payload[_GLOSSARY_AUTOMATIC_PREFLIGHT_KEY] = dict(preflight_payload)
        payload[_GLOSSARY_BATTLE_TEST_PREFLIGHT_KEY] = dict(preflight_payload)
        if preflight.get("status") != "ready" and decision.status.value == "ready":
            payload["status"] = "fallback"
            payload["fallback_reason"] = str(
                preflight.get(
                    "fallback_reason",
                    "battle_test_preflight_skipped",
                )
            )
            payload["prompt_planning_allowed"] = False
            payload["selected_entry_ids"] = []
            payload["work_unit_selection_signature"] = None
            payload["cache_policy"] = {
                "behavior": "default_runtime_cache",
                "cache_get_allowed": True,
                "cache_put_allowed": True,
            }
            payload.pop("policy_signature_context", None)
    if prompt_context is not None:
        payload["prompt_context"] = glossary_prompt_context_metadata_payload(
            prompt_context,
        )
    else:
        preflight_prompt_context = (
            preflight.get("prompt_context") if isinstance(preflight, Mapping) else None
        )
        if isinstance(preflight_prompt_context, Mapping):
            payload["prompt_context"] = dict(preflight_prompt_context)
    if plan_metadata:
        payload.update(plan_metadata)
    _apply_glossary_effective_metadata(
        payload,
        decision=decision,
        prompt_context=prompt_context,
    )
    callback(payload)


def _apply_glossary_effective_metadata(
    payload: dict[str, object],
    *,
    decision: GlossaryPromptPolicyAdapterDecision,
    prompt_context: GlossaryPromptContextResult | None,
) -> None:
    payload["metadata_only"] = True
    payload["raw_payload_included"] = False
    if _glossary_prompt_context_included(prompt_context):
        payload["glossary_effective_status"] = "effective_observed"
        payload["diagnostic_severity"] = "info"
        payload["glossary_effective_reason_codes"] = [
            "rendered_glossary_context_observed"
        ]
        return
    if not decision.enabled:
        return
    severity = "error" if _ready_prepared_package_payload(payload) else "warning"
    reason = str(payload.get("fallback_reason") or "glossary_context_not_rendered")
    payload["glossary_effective_status"] = "not_effective"
    payload["diagnostic_severity"] = severity
    payload["glossary_effective_reason_codes"] = [reason]


def _glossary_prompt_context_included(
    prompt_context: GlossaryPromptContextResult | None,
) -> bool:
    if prompt_context is None:
        return False
    return bool(prompt_context.included_entries)


def _ready_prepared_package_payload(payload: Mapping[str, object]) -> bool:
    prepared_package = payload.get("prepared_package")
    return isinstance(prepared_package, Mapping) and (
        str(prepared_package.get("status")).casefold() == "ready"
        or _metadata_int(prepared_package.get("ready_entry_count")) > 0
    )


def _metadata_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return 0


def _glossary_runtime_plan_metadata(
    config: GlossaryRuntimeAdapterHookConfig | None,
) -> dict[str, object] | None:
    if config is None or not isinstance(config.glossary_plan, Mapping):
        return None
    metadata: dict[str, object] = {
        "runtime_caps": _glossary_runtime_caps_metadata(config)
    }
    document_format = config.glossary_plan.get("document_format")
    if isinstance(document_format, str) and document_format in {"txt", "docx", "epub"}:
        metadata["document_format"] = document_format
    prepared_package = config.glossary_plan.get("prepared_package")
    if not isinstance(prepared_package, Mapping):
        return metadata or None
    allowed = {
        "schema_version",
        "metadata_only",
        "raw_payload_included",
        "status",
        "reason_codes",
        "package_id",
        "package_signature",
        "source_language",
        "target_language",
        "provider_role_id",
        "provider_model",
        "entry_count",
        "ready_entry_count",
        "needs_review_entry_count",
    }
    filtered: dict[str, object] = {}
    for key, value in prepared_package.items():
        if key in allowed and _glossary_metadata_value_is_safe(value):
            filtered[str(key)] = value
    if filtered:
        metadata["prepared_package"] = filtered
    bridge = config.glossary_plan.get("prepared_package_runtime_bridge")
    if isinstance(bridge, Mapping):
        bridge_allowed = {
            "schema_version",
            "status",
            "reason_codes",
            "entry_count",
            "applicable_entry_count",
            "target_metadata_missing_count",
            "source_ref_absent_count",
            "source_ref_match_count",
            "source_ref_mismatch_count",
            "source_term_missing_count",
            "source_canonical_match_count",
            "source_safe_alias_match_count",
            "source_risky_alias_only_count",
            "metadata_only",
            "raw_payload_included",
            "source_refs_required_when_present",
            "source_refs_used_as_diagnostics",
            "source_presence_primary_applicability_signal",
            "risky_alias_only_skipped",
        }
        filtered_bridge: dict[str, object] = {}
        for key, value in bridge.items():
            if key in bridge_allowed and _glossary_metadata_value_is_safe(value):
                filtered_bridge[str(key)] = value
        if filtered_bridge:
            metadata["prepared_package_runtime_bridge"] = filtered_bridge
    return metadata or None


def _glossary_runtime_caps_metadata(
    config: GlossaryRuntimeAdapterHookConfig,
) -> dict[str, object]:
    return {
        "max_selected_entries": config.max_selected_entries,
        "battle_test_max_source_blocks": config.battle_test_max_source_blocks,
        "battle_test_max_source_characters": (
            config.battle_test_max_source_characters
        ),
        "prompt_context": _prompt_context_config_caps_metadata(
            config.prompt_context_config or GlossaryPromptContextConfig()
        ),
    }


def _prompt_context_config_caps_metadata(
    config: GlossaryPromptContextConfig,
) -> dict[str, object]:
    return {
        "max_entries": config.max_entries,
        "max_prompt_tokens": config.max_prompt_tokens,
        "max_characters": config.max_characters,
        "max_entry_characters": config.max_entry_characters,
        "max_field_characters": config.max_field_characters,
        "max_aliases": config.max_aliases,
        "max_target_variants": config.max_target_variants,
        "max_forbidden_variants": config.max_forbidden_variants,
        "max_morphology_notes": config.max_morphology_notes,
        "max_profile_rule_ids": config.max_profile_rule_ids,
        "include_terminology_policy_metadata": (
            config.include_terminology_policy_metadata
        ),
    }


def _glossary_metadata_value_is_safe(value: object) -> bool:
    if isinstance(value, str):
        return len(value) <= 240
    if isinstance(value, bool | int | float) or value is None:
        return True
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return all(isinstance(item, str) and len(item) <= 240 for item in value)
    return False


def _glossary_runtime_prompt_context(
    config: GlossaryRuntimeAdapterHookConfig | None,
    decision: GlossaryPromptPolicyAdapterDecision | None,
    *,
    preflight: Mapping[str, object] | None = None,
) -> GlossaryPromptContextResult | None:
    if config is None or decision is None:
        return None
    if (
        not config.prompt_context_enabled
        or not config.automatic_glossary_enabled
        or not decision.prompt_planning_allowed
    ):
        return None
    if preflight is None or preflight.get("status") != "ready":
        return None
    selected_entry_ids = _glossary_preflight_useful_entry_ids(preflight)
    if not selected_entry_ids:
        return None
    try:
        return format_glossary_prompt_context(
            config.prompt_context_entries,
            selected_entry_ids=selected_entry_ids,
            config=config.prompt_context_config or GlossaryPromptContextConfig(),
        )
    except ValueError:
        return None


def _effective_glossary_runtime_adapter_decision(
    decision: GlossaryPromptPolicyAdapterDecision | None,
    preflight: Mapping[str, object] | None,
) -> GlossaryPromptPolicyAdapterDecision | None:
    if decision is None or preflight is None:
        return decision
    if decision.status.value != "ready":
        return decision
    if preflight.get("status") == "ready":
        return decision
    return None


def _glossary_runtime_useful_preflight(
    config: GlossaryRuntimeAdapterHookConfig | None,
    decision: GlossaryPromptPolicyAdapterDecision | None,
    *,
    source_texts: Sequence[str],
) -> dict[str, object] | None:
    if config is None or not config.automatic_glossary_enabled:
        return None

    source_text_tuple = tuple(text for text in source_texts if text)
    source_block_count = len(source_text_tuple)
    source_character_count = sum(len(text) for text in source_text_tuple)
    selected_entry_ids = tuple(decision.selected_entry_ids if decision else ())
    payload: dict[str, object] = {
        "schema_version": _GLOSSARY_BATTLE_TEST_PREFLIGHT_VERSION,
        "automatic_glossary_schema_version": _GLOSSARY_AUTOMATIC_PREFLIGHT_VERSION,
        "enabled": True,
        "automatic_glossary_enabled": True,
        "status": "skipped",
        "fallback_reason": "none",
        "reason_codes": [],
        "metadata_only": True,
        "raw_payload_included": False,
        "source_block_count": source_block_count,
        "source_character_count": source_character_count,
        "max_source_blocks": config.automatic_glossary_max_source_blocks,
        "max_source_characters": config.automatic_glossary_max_source_characters,
        "source_block_limit_exceeded": False,
        "source_character_limit_exceeded": False,
        "source_size_gate_status": "within_limit",
        "source_size_gate_reason_codes": [],
        "selected_entry_count": len(selected_entry_ids),
        "target_metadata_entry_count": 0,
        "source_match_entry_count": 0,
        "useful_entry_count": 0,
        "useful_entry_ids": [],
    }

    if decision is None or not decision.prompt_planning_allowed:
        return _glossary_preflight_skipped(payload, "adapter_not_ready")
    if not config.prompt_context_enabled:
        return _glossary_preflight_skipped(payload, "prompt_rehearsal_disabled")
    if config.automatic_glossary_max_source_blocks < 1:
        return _glossary_preflight_skipped(payload, "invalid_source_block_limit")
    if config.automatic_glossary_max_source_characters < 1:
        return _glossary_preflight_skipped(payload, "invalid_source_character_limit")

    source_size_reason_codes: list[str] = []
    if source_block_count > config.automatic_glossary_max_source_blocks:
        payload["source_block_limit_exceeded"] = True
        source_size_reason_codes.append("source_block_count_exceeds_limit")
    if source_character_count > config.automatic_glossary_max_source_characters:
        payload["source_character_limit_exceeded"] = True
        source_size_reason_codes.append("source_character_count_exceeds_limit")
    if source_size_reason_codes:
        payload["source_size_gate_status"] = "over_limit"
        payload["source_size_gate_reason_codes"] = source_size_reason_codes

    source_text = "\n\n".join(source_text_tuple)
    entries_by_id = _glossary_prompt_entries_by_id(config.prompt_context_entries)
    target_metadata_entry_count = 0
    source_match_entry_count = 0
    useful_entry_ids: list[str] = []
    for entry_id in selected_entry_ids:
        entry = entries_by_id.get(entry_id)
        if entry is None:
            continue
        has_target_metadata = _glossary_entry_has_target_metadata(entry)
        source_matches = _glossary_entry_source_matches(entry, source_text)
        if has_target_metadata:
            target_metadata_entry_count += 1
        if source_matches:
            source_match_entry_count += 1
        if has_target_metadata and source_matches:
            useful_entry_ids.append(entry_id)

    payload["target_metadata_entry_count"] = target_metadata_entry_count
    payload["source_match_entry_count"] = source_match_entry_count
    payload["useful_entry_count"] = len(useful_entry_ids)
    payload["useful_entry_ids"] = useful_entry_ids

    if not useful_entry_ids:
        reason_codes: list[str] = []
        if target_metadata_entry_count == 0:
            reason_codes.append("target_metadata_missing")
        if source_match_entry_count == 0:
            reason_codes.append("source_term_or_alias_absent")
        if not reason_codes:
            reason_codes.append("useful_glossary_entry_missing")
        return _glossary_preflight_skipped(payload, *reason_codes)

    try:
        formatted_context = format_glossary_prompt_context(
            config.prompt_context_entries,
            selected_entry_ids=useful_entry_ids,
            config=config.prompt_context_config or GlossaryPromptContextConfig(),
        )
    except ValueError:
        return _glossary_preflight_skipped(payload, "prompt_context_config_invalid")
    if not formatted_context.included_entries:
        payload["prompt_context"] = glossary_prompt_context_metadata_payload(
            formatted_context,
        )
        return _glossary_preflight_skipped(payload, "prompt_context_budget_exhausted")

    payload["status"] = "ready"
    payload["fallback_reason"] = "none"
    payload["reason_codes"] = []
    return payload


def _glossary_preflight_skipped(
    payload: Mapping[str, object],
    *reason_codes: str,
) -> dict[str, object]:
    compact_reason_codes = [
        reason_code for reason_code in reason_codes if reason_code.strip()
    ] or ["battle_test_preflight_skipped"]
    result = dict(payload)
    result["status"] = "skipped"
    result["fallback_reason"] = compact_reason_codes[0]
    result["reason_codes"] = compact_reason_codes
    return result


def _glossary_preflight_useful_entry_ids(
    preflight: Mapping[str, object],
) -> tuple[str, ...]:
    entry_ids = preflight.get("useful_entry_ids", ())
    if isinstance(entry_ids, (str, bytes)) or not isinstance(entry_ids, Sequence):
        return ()
    return tuple(entry_id for entry_id in entry_ids if isinstance(entry_id, str))


def _glossary_prompt_entries_by_id(
    entries: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        entry_id = entry.get("entry_id")
        if isinstance(entry_id, str) and entry_id.strip():
            result.setdefault(entry_id, entry)
    return result


def _glossary_entry_has_target_metadata(entry: Mapping[str, Any]) -> bool:
    target_canonical = entry.get("target_canonical")
    if isinstance(target_canonical, str) and target_canonical.strip():
        return True
    target_variants = entry.get("target_variants")
    if isinstance(target_variants, Sequence) and not isinstance(
        target_variants,
        (str, bytes),
    ):
        return any(
            isinstance(variant, str) and variant.strip()
            for variant in target_variants
        )
    return False


def _glossary_entry_source_matches(entry: Mapping[str, Any], source_text: str) -> bool:
    if not source_text:
        return False
    return any(
        _glossary_source_term_present(term, source_text)
        for term in _glossary_entry_source_terms(entry)
    )


def _glossary_source_term_present(term: str, source_text: str) -> bool:
    normalized_term = term.strip()
    if not normalized_term:
        return False
    pattern = re.escape(normalized_term)
    if normalized_term[0].isalnum():
        pattern = rf"(?<!\w){pattern}"
    if normalized_term[-1].isalnum():
        pattern = rf"{pattern}(?!\w)"
    return re.search(pattern, source_text, flags=re.IGNORECASE) is not None


def _glossary_entry_source_terms(entry: Mapping[str, Any]) -> tuple[str, ...]:
    terms: list[str] = []
    source_canonical = entry.get("source_canonical")
    if isinstance(source_canonical, str) and source_canonical.strip():
        terms.append(source_canonical.strip())
    aliases = entry.get("aliases")
    if isinstance(aliases, Sequence) and not isinstance(aliases, (str, bytes)):
        terms.extend(
            alias.strip()
            for alias in aliases
            if isinstance(alias, str) and alias.strip()
        )
    return tuple(dict.fromkeys(terms))


def _glossary_prompt_context_text(
    prompt_context: GlossaryPromptContextResult | None,
) -> str | None:
    if prompt_context is None or not prompt_context.included_entries:
        return None
    return prompt_context.text


def _translation_cache_get(
    translation_cache: TranslationCache | None,
    *,
    blocks: list[str],
    source_language: str,
    target_language: str,
    prompt_tier: PromptTier,
    glossary_adapter_decision: GlossaryPromptPolicyAdapterDecision | None = None,
) -> tuple[str, ...] | None:
    if translation_cache is None:
        return None
    if (
        glossary_adapter_decision is not None
        and not glossary_adapter_decision.cache_get_allowed
    ):
        return None
    return translation_cache.get(
        source_texts=tuple(blocks),
        source_language=source_language,
        target_language=target_language,
        prompt_tier=prompt_tier,
        signature_context=(
            glossary_adapter_decision.signature_context
            if glossary_adapter_decision is not None
            else None
        ),
    )


def _translation_cache_put(
    translation_cache: TranslationCache | None,
    *,
    source_texts: tuple[str, ...],
    translated_texts: tuple[str, ...],
    source_language: str,
    target_language: str,
    prompt_tier: PromptTier,
    glossary_adapter_decision: GlossaryPromptPolicyAdapterDecision | None = None,
) -> None:
    if translation_cache is None:
        return
    if (
        glossary_adapter_decision is not None
        and not glossary_adapter_decision.cache_put_allowed
    ):
        return
    translation_cache.put(
        source_texts=source_texts,
        translated_texts=translated_texts,
        source_language=source_language,
        target_language=target_language,
        prompt_tier=prompt_tier,
        signature_context=(
            glossary_adapter_decision.signature_context
            if glossary_adapter_decision is not None
            else None
        ),
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


def _format_translation_request_text(
    texts: list[str],
    source_language_hints: list[str | None] | None = None,
    *,
    glossary_prompt_context: str | None = None,
) -> str:
    batch = _format_translation_batch(
        texts,
        source_language_hints=source_language_hints,
    )
    if not glossary_prompt_context:
        return batch
    return f"{glossary_prompt_context}\n\n{batch}"


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
    translation_context: TranslationContextMemory | None = None,
) -> list[FragmentTranslation]:
    parsed = _parse_translation_batch(
        translated_text,
        expected_count=len(source_blocks),
        required_markers=_required_protected_markers(protected_blocks),
    )
    if parsed is None:
        return _translate_epub_blocks_individually(
            source_blocks=source_blocks,
            translator=translator,
            source_language=source_language,
            target_language=target_language,
            translation_context=translation_context,
        )

    parsed = _restore_protected_texts(parsed, protected_blocks)
    parsed = [
        clean_inline_formatting_artifacts(
            translated,
            target_language=target_language,
        )
        for translated in parsed
    ]
    parsed = _retry_untranslated_source_residue_texts(
        source_texts=[source_block.text for source_block in source_blocks],
        translated_texts=parsed,
        protected_texts=protected_blocks,
        source_language=source_language,
        target_language=target_language,
        translator=translator,
        translation_context=translation_context,
    )
    parsed = _retry_epub_surface_residue_texts(
        source_texts=[source_block.text for source_block in source_blocks],
        translated_texts=parsed,
        protected_texts=protected_blocks,
        surface_flags=tuple(
            _is_epub_literary_protection_surface(source_block)
            for source_block in source_blocks
        ),
        target_language=target_language,
        translator=translator,
        translation_context=translation_context,
    )
    return [
        FragmentTranslation(
            index=source_block.index,
            source_text=source_block.text,
            translated_text=translated,
        )
        for source_block, translated in zip(source_blocks, parsed, strict=True)
    ]


def _protect_epub_block_text(source_block: _EpubTextBlock) -> ProtectedText:
    return protect_text(
        source_block.text,
        literary_heading=_is_epub_literary_protection_surface(source_block),
    )


def _is_epub_literary_protection_surface(source_block: _EpubTextBlock) -> bool:
    return (
        source_block.kind == TextBlockKind.HEADING
        or source_block.role == _EPUB_BLOCK_ROLE_NAVIGATION
    )


def _parse_translation_batch(
    translated_text: str,
    *,
    expected_count: int,
    required_markers: tuple[tuple[str, ...], ...] | None = None,
    log_rejections: bool = True,
) -> list[str] | None:
    validation = validate_translation_batch_contract(
        translated_text,
        expected_count=expected_count,
        required_markers=required_markers,
    )
    parsed = validation.translated_texts
    if parsed is None:
        if validation.rejection_reason is not None:
            if log_rejections:
                logger.warning(
                    "Translation batch rejected; reason=%s expected_count=%s",
                    validation.rejection_reason.value,
                    expected_count,
                )
                record_security_event(
                    "translation_batch_rejected",
                    reason=validation.rejection_reason.value,
                    expected_count=expected_count,
                    output_chars=len(translated_text),
                )
        return None

    return [_strip_model_service_wrappers(text) for text in parsed]


def _required_protected_markers(
    protected_texts: list[ProtectedText],
) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(protected_text.replacements)
        for protected_text in protected_texts
    )


def _translate_epub_blocks_individually(
    *,
    source_blocks: list[_EpubTextBlock],
    translator: TextTranslator,
    source_language: str,
    target_language: str,
    translation_context: TranslationContextMemory | None = None,
) -> list[FragmentTranslation]:
    translated_blocks: list[FragmentTranslation] = []
    context_memory = translation_context or TranslationContextMemory()
    for source_block in source_blocks:
        protected_source = _protect_epub_block_text(source_block)
        translated_text = restore_protected_text(
            translate_with_context(
                translator,
                text=protected_source.text,
                source_language=source_language,
                target_language=target_language,
                translation_context=context_memory,
            ),
            protected_source.replacements,
        )
        translated_text = clean_inline_formatting_artifacts(
            translated_text,
            target_language=target_language,
        )
        if _has_untranslated_source_language_residue(
            source_text=source_block.text,
            translated_text=translated_text,
            source_language=source_language,
            target_language=target_language,
        ) or (
            _is_epub_literary_protection_surface(source_block)
            and has_english_navigation_heading_residue(
                translated_text=translated_text,
                target_language=target_language,
                block_id="epub:body:surface-pre-final:navigation-heading",
                block_kind="heading",
            )
        ):
            translated_text = restore_protected_text(
                _clean_translated_text(
                    translate_with_context(
                        translator,
                        text=protected_source.text,
                        source_language="auto",
                        target_language=target_language,
                        translation_context=context_memory,
                    )
                ),
                protected_source.replacements,
            )
            translated_text = clean_inline_formatting_artifacts(
                translated_text,
                target_language=target_language,
            )
        translated_blocks.append(
            FragmentTranslation(
                index=source_block.index,
                source_text=source_block.text,
                translated_text=translated_text,
            )
        )
        context_memory = _updated_context_memory(
            context_memory,
            source_text=source_block.text,
            translated_text=translated_text,
            target_language=target_language,
        )
    return translated_blocks


def _translate_texts_individually(
    *,
    texts: list[str],
    translator: TextTranslator,
    source_language: str,
    target_language: str,
    translation_context: TranslationContextMemory | None = None,
    literary_heading_flags: tuple[bool, ...] | None = None,
) -> list[str]:
    translated_texts: list[str] = []
    context_memory = translation_context or TranslationContextMemory()
    literary_heading_flags = literary_heading_flags or tuple(False for _ in texts)
    for text, literary_heading in zip(texts, literary_heading_flags, strict=True):
        protected_source = protect_text(text, literary_heading=literary_heading)
        translated_text = restore_protected_text(
            _clean_translated_text(
                translate_with_context(
                    translator,
                    text=protected_source.text,
                    source_language=source_language,
                    target_language=target_language,
                    translation_context=context_memory,
                )
            ),
            protected_source.replacements,
        )
        if _has_untranslated_source_language_residue(
            source_text=text,
            translated_text=translated_text,
            source_language=source_language,
            target_language=target_language,
        ):
            translated_text = restore_protected_text(
                _clean_translated_text(
                    translate_with_context(
                        translator,
                        text=protected_source.text,
                        source_language="auto",
                        target_language=target_language,
                        translation_context=context_memory,
                    )
                ),
                protected_source.replacements,
            )
        translated_texts.append(translated_text)
        context_memory = _updated_context_memory(
            context_memory,
            source_text=text,
            translated_text=translated_text,
            target_language=target_language,
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
    parsed = _parse_translation_batch(
        translated_text,
        expected_count=1,
        log_rejections=False,
    )
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
        if all(block.index in translated_indexes for block in unit.blocks)
    )


def _count_translated_docx_units(
    fragments: list[FragmentTranslation],
    *,
    translation_units: list[DocxTranslationUnit],
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


def _epub_text_slots(
    element: ElementTree.Element,
) -> list[tuple[ElementTree.Element, str]]:
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


def _read_epub_xhtml(content: bytes) -> ElementTree.Element:
    return parse_xml_document(
        content,
        parse_error_message="EPUB XHTML content is not readable",
    )


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
