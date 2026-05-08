from dataclasses import dataclass

from translator_service.documents import DocumentFormat
from translator_service.format_adapters.contracts import (
    FormatAdapterPlan,
    FormatTextBlock,
    FormatTranslationUnit,
)
from translator_service.structure_optimizer import PromptTier, estimate_unit_input_tokens
from translator_service.translation_runner import _extract_docx_blocks, _group_docx_blocks


DOCX_ADAPTER_VERSION = "docx-adapter-v1"


def plan_docx_translation(
    *,
    content: bytes,
    max_fragment_chars: int,
    adapter_version: str = DOCX_ADAPTER_VERSION,
) -> FormatAdapterPlan:
    blocks = _extract_docx_blocks(content)
    units = tuple(
        _docx_translation_unit(sequence=sequence, unit=unit)
        for sequence, unit in enumerate(
            _group_docx_blocks(blocks, max_fragment_chars=max_fragment_chars),
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


def _docx_translation_unit(*, sequence: int, unit) -> FormatTranslationUnit:
    return FormatTranslationUnit(
        sequence=sequence,
        blocks=tuple(_docx_text_block(block) for block in unit.blocks),
        prompt_tier=unit.prompt_tier,
    )


def _docx_text_block(block) -> FormatTextBlock:
    return FormatTextBlock(
        index=block.index,
        source_block_id=f"docx:{block.file_name}:{block.block_index}",
        text=block.text,
        kind=block.kind,
        group_id=block.group_id,
        metadata=(
            ("file_name", block.file_name),
            ("block_index", str(block.block_index)),
            ("fixed_width_pseudo_table", str(block.is_fixed_width_pseudo_table)),
        ),
    )


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
