from __future__ import annotations

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


def validate_translation_batch_contract(
    translated_text: str,
    *,
    expected_count: int,
    required_markers: tuple[tuple[str, ...], ...] | None = None,
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

    if document.attrib:
        return TranslationBatchValidationResult(
            translated_texts=None,
            rejection_reason=TranslationBatchRejectionReason.UNEXPECTED_ATTRIBUTE,
        )

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
    for expected_index, block in enumerate(blocks):
        if _local_name(block.tag) != "translation_block":
            return TranslationBatchValidationResult(
                translated_texts=None,
                rejection_reason=TranslationBatchRejectionReason.UNEXPECTED_CHILD,
            )
        if set(block.attrib) - {"id", "source_language"}:
            return TranslationBatchValidationResult(
                translated_texts=None,
                rejection_reason=TranslationBatchRejectionReason.UNEXPECTED_ATTRIBUTE,
            )
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

    return TranslationBatchValidationResult(translated_texts=tuple(parsed))


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
