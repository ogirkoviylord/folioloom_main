from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from xml.etree import ElementTree

from translator_service.model_output_safety import validate_model_output_safety


class TranslationBatchRejectionReason(StrEnum):
    EXTERNAL_TEXT = "external_text"
    BROKEN_XML = "broken_xml"
    WRONG_ROOT = "wrong_root"
    BLOCK_COUNT_MISMATCH = "block_count_mismatch"
    UNEXPECTED_CHILD = "unexpected_child"
    UNEXPECTED_ATTRIBUTE = "unexpected_attribute"
    WRONG_BLOCK_ID = "wrong_block_id"
    MISSING_PROTECTED_MARKER = "missing_protected_marker"
    UNSAFE_MODEL_OUTPUT = "unsafe_model_output"


@dataclass(frozen=True)
class TranslationBatchValidationResult:
    translated_texts: tuple[str, ...] | None
    rejection_reason: TranslationBatchRejectionReason | None = None
    normalized_text: str | None = None


def parse_translation_batch_contract(
    translated_text: str,
    *,
    expected_count: int,
    required_markers: tuple[tuple[str, ...], ...] | None = None,
) -> tuple[str, ...] | None:
    return validate_translation_batch_contract(
        translated_text,
        expected_count=expected_count,
        required_markers=required_markers,
    ).translated_texts


def format_translation_batch_contract(translated_texts: Sequence[str]) -> str:
    lines = ["<translation_batch>"]
    for index, translated_text in enumerate(translated_texts):
        lines.append(
            f'<translation_block id="{index}">'
            f"{html.escape(translated_text, quote=False)}"
            "</translation_block>"
        )
    lines.append("</translation_batch>")
    return "".join(lines)


def validate_translation_batch_contract(
    translated_text: str,
    *,
    expected_count: int,
    required_markers: tuple[tuple[str, ...], ...] | None = None,
) -> TranslationBatchValidationResult:
    return _validate_translation_batch_contract(
        translated_text,
        expected_count=expected_count,
        required_markers=required_markers,
        allow_provider_language_metadata=False,
    )


def normalize_provider_translation_batch_contract(
    translated_text: str,
    *,
    expected_count: int,
    required_markers: tuple[tuple[str, ...], ...] | None = None,
) -> TranslationBatchValidationResult:
    return _validate_translation_batch_contract(
        translated_text,
        expected_count=expected_count,
        required_markers=required_markers,
        allow_provider_language_metadata=True,
    )


def _validate_translation_batch_contract(
    translated_text: str,
    *,
    expected_count: int,
    required_markers: tuple[tuple[str, ...], ...] | None,
    allow_provider_language_metadata: bool,
) -> TranslationBatchValidationResult:
    stripped = translated_text.strip()
    if not (
        stripped.startswith("<translation_batch")
        and stripped.endswith("</translation_batch>")
    ):
        return TranslationBatchValidationResult(
            translated_texts=None,
            rejection_reason=TranslationBatchRejectionReason.EXTERNAL_TEXT,
        )

    try:
        document = ElementTree.fromstring(stripped)
    except ElementTree.ParseError:
        return TranslationBatchValidationResult(
            translated_texts=None,
            rejection_reason=TranslationBatchRejectionReason.BROKEN_XML,
        )

    if _local_name(document.tag) != "translation_batch":
        return TranslationBatchValidationResult(
            translated_texts=None,
            rejection_reason=TranslationBatchRejectionReason.WRONG_ROOT,
        )

    normalized = False
    if _unexpected_root_attributes(
        document.attrib,
        allow_provider_language_metadata=allow_provider_language_metadata,
    ):
        return TranslationBatchValidationResult(
            translated_texts=None,
            rejection_reason=TranslationBatchRejectionReason.UNEXPECTED_ATTRIBUTE,
        )
    if document.attrib:
        normalized = True

    if _has_non_whitespace_text(document.text):
        return TranslationBatchValidationResult(
            translated_texts=None,
            rejection_reason=TranslationBatchRejectionReason.EXTERNAL_TEXT,
        )

    blocks = list(document)
    if len(blocks) != expected_count:
        return TranslationBatchValidationResult(
            translated_texts=None,
            rejection_reason=TranslationBatchRejectionReason.BLOCK_COUNT_MISMATCH,
        )

    parsed: list[str] = []
    source_language_hints: list[str | None] = []
    for expected_index, block in enumerate(blocks):
        if _local_name(block.tag) != "translation_block":
            return TranslationBatchValidationResult(
                translated_texts=None,
                rejection_reason=TranslationBatchRejectionReason.UNEXPECTED_CHILD,
            )
        if (
            allow_provider_language_metadata
            and "source" in block.attrib
            and "source_language" not in block.attrib
        ):
            block.attrib["source_language"] = block.attrib.pop("source")
            normalized = True
        if _unexpected_block_attributes(
            block.attrib,
            allow_provider_language_metadata=allow_provider_language_metadata,
        ):
            return TranslationBatchValidationResult(
                translated_texts=None,
                rejection_reason=TranslationBatchRejectionReason.UNEXPECTED_ATTRIBUTE,
            )
        if set(block.attrib) - {"id", "source_language"}:
            normalized = True
        if block.attrib.get("id") != str(expected_index):
            return TranslationBatchValidationResult(
                translated_texts=None,
                rejection_reason=TranslationBatchRejectionReason.WRONG_BLOCK_ID,
            )
        if list(block):
            return TranslationBatchValidationResult(
                translated_texts=None,
                rejection_reason=TranslationBatchRejectionReason.UNEXPECTED_CHILD,
            )
        if _has_non_whitespace_text(block.tail):
            return TranslationBatchValidationResult(
                translated_texts=None,
                rejection_reason=TranslationBatchRejectionReason.EXTERNAL_TEXT,
            )
        translated_block_text = "".join(block.itertext()).strip()
        safety = validate_model_output_safety(translated_block_text)
        if safety.reason is not None:
            return TranslationBatchValidationResult(
                translated_texts=None,
                rejection_reason=TranslationBatchRejectionReason.UNSAFE_MODEL_OUTPUT,
            )
        if not _contains_required_markers(
            translated_block_text,
            required_markers=_markers_for_index(required_markers, expected_index),
        ):
            return TranslationBatchValidationResult(
                translated_texts=None,
                rejection_reason=TranslationBatchRejectionReason.MISSING_PROTECTED_MARKER,
            )
        parsed.append(translated_block_text)
        source_language_hints.append(block.attrib.get("source_language"))

    return TranslationBatchValidationResult(
        translated_texts=tuple(parsed),
        normalized_text=(
            _format_normalized_translation_batch(
                parsed,
                source_language_hints=source_language_hints,
            )
            if normalized
            else None
        ),
    )


def _unexpected_root_attributes(
    attributes: dict[str, str],
    *,
    allow_provider_language_metadata: bool,
) -> set[str]:
    allowed = (
        _PROVIDER_LANGUAGE_METADATA_ATTRIBUTES
        if allow_provider_language_metadata
        else set()
    )
    return set(attributes) - allowed


def _unexpected_block_attributes(
    attributes: dict[str, str],
    *,
    allow_provider_language_metadata: bool,
) -> set[str]:
    allowed = {"id", "source_language"}
    if allow_provider_language_metadata:
        allowed = allowed | _PROVIDER_LANGUAGE_METADATA_ATTRIBUTES
    return set(attributes) - allowed


def _format_normalized_translation_batch(
    translated_texts: list[str],
    *,
    source_language_hints: list[str | None],
) -> str:
    lines = ["<translation_batch>"]
    for index, translated_text in enumerate(translated_texts):
        attributes = [f'id="{index}"']
        source_language = source_language_hints[index]
        if source_language:
            attributes.append(
                f'source_language="{html.escape(source_language, quote=True)}"'
            )
        lines.append(
            f"<translation_block {' '.join(attributes)}>"
            f"{html.escape(translated_text, quote=False)}"
            "</translation_block>"
        )
    lines.append("</translation_batch>")
    return "".join(lines)


def _markers_for_index(
    required_markers: tuple[tuple[str, ...], ...] | None,
    index: int,
) -> tuple[str, ...]:
    if required_markers is None or index >= len(required_markers):
        return ()
    return required_markers[index]


def _contains_required_markers(
    translated_text: str,
    *,
    required_markers: tuple[str, ...],
) -> bool:
    return all(marker in translated_text for marker in required_markers)


def _has_non_whitespace_text(text: str | None) -> bool:
    return bool(text and text.strip())


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


_XML_LANG_ATTRIBUTE = "{http://www.w3.org/XML/1998/namespace}lang"
_PROVIDER_LANGUAGE_METADATA_ATTRIBUTES = {
    "target_language",
    "lang",
    _XML_LANG_ATTRIBUTE,
}
