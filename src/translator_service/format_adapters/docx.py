from dataclasses import dataclass

from translator_service.documents import DocumentFormat
from translator_service.format_adapters.contracts import (
    FormatAdapterPlan,
    FormatTextBlock,
    FormatTranslationUnit,
)
from translator_service.format_adapters.docx_structure import (
    extract_docx_blocks,
    group_docx_blocks,
)
from translator_service.structure_optimizer import (
    PromptTier,
    estimate_unit_input_tokens,
)

DOCX_ADAPTER_VERSION = "docx-adapter-v1"
TRANSLATION_MODE_DOCUMENT_FORM = "document_form"
TRANSLATION_MODE_BOOK_MANUSCRIPT = "book_manuscript"
DOCX_TRANSLATION_MODE_DOCUMENT_FORM_PROFILE = "docx-document-form-v1"
DOCX_TRANSLATION_MODE_BOOK_MANUSCRIPT_PROFILE = "docx-book-manuscript-v1"


def plan_docx_translation(
    *,
    content: bytes,
    max_fragment_chars: int,
    adapter_version: str = DOCX_ADAPTER_VERSION,
    translation_mode: str | None = None,
) -> FormatAdapterPlan:
    normalized_mode = _normalize_docx_translation_mode(translation_mode)
    blocks = extract_docx_blocks(content)
    units = tuple(
        _docx_translation_unit(
            sequence=sequence,
            unit=unit,
            translation_mode=normalized_mode,
        )
        for sequence, unit in enumerate(
            group_docx_blocks(blocks, max_fragment_chars=max_fragment_chars),
            start=1,
        )
    )
    return FormatAdapterPlan(
        document_format=DocumentFormat.DOCX,
        adapter_version=adapter_version,
        units=units,
        character_count=len("\n\n".join(block.text for block in blocks).strip()),
        estimated_input_tokens=_estimate_docx_input_tokens(units),
    )


def _docx_translation_unit(
    *,
    sequence: int,
    unit,
    translation_mode: str | None,
) -> FormatTranslationUnit:
    return FormatTranslationUnit(
        sequence=sequence,
        blocks=tuple(
            _docx_text_block(block, translation_mode=translation_mode)
            for block in unit.blocks
        ),
        prompt_tier=_docx_prompt_tier(
            unit.prompt_tier,
            translation_mode=translation_mode,
        ),
    )


def _docx_text_block(block, *, translation_mode: str | None) -> FormatTextBlock:
    metadata = [
        ("file_name", block.file_name),
        ("block_index", str(block.block_index)),
        ("fixed_width_pseudo_table", str(block.is_fixed_width_pseudo_table)),
    ]
    if translation_mode is not None:
        metadata.extend(
            (
                ("translation_mode", translation_mode),
                (
                    "docx_translation_mode_profile",
                    docx_translation_mode_profile_signature(translation_mode),
                ),
            )
        )
    return FormatTextBlock(
        index=block.index,
        source_block_id=f"docx:{block.file_name}:{block.block_index}",
        text=block.text,
        kind=block.kind,
        group_id=block.group_id,
        metadata=tuple(metadata),
    )


def _docx_prompt_tier(
    prompt_tier: PromptTier,
    *,
    translation_mode: str | None,
) -> PromptTier:
    if translation_mode == TRANSLATION_MODE_DOCUMENT_FORM:
        return PromptTier.STRICT
    return prompt_tier


def docx_translation_mode_profile_signature(translation_mode: str | None) -> str | None:
    normalized_mode = _normalize_docx_translation_mode(translation_mode)
    if normalized_mode == TRANSLATION_MODE_DOCUMENT_FORM:
        return DOCX_TRANSLATION_MODE_DOCUMENT_FORM_PROFILE
    if normalized_mode == TRANSLATION_MODE_BOOK_MANUSCRIPT:
        return DOCX_TRANSLATION_MODE_BOOK_MANUSCRIPT_PROFILE
    return None


def _normalize_docx_translation_mode(translation_mode: str | None) -> str | None:
    if translation_mode is None:
        return None
    normalized = translation_mode.strip().lower()
    if normalized in {
        TRANSLATION_MODE_DOCUMENT_FORM,
        TRANSLATION_MODE_BOOK_MANUSCRIPT,
    }:
        return normalized
    raise ValueError("Unsupported DOCX translation mode")


def _estimate_docx_input_tokens(units: tuple[FormatTranslationUnit, ...]) -> int:
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
