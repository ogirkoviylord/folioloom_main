from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import ceil


class TextBlockKind(StrEnum):
    PLAIN = "plain"
    HEADING = "heading"
    LIST = "list"
    TABLE = "table"
    FOOTNOTE = "footnote"
    DENSE_MARKUP = "dense_markup"


class PromptTier(StrEnum):
    PLAIN = "plain"
    STRUCTURED = "structured"
    STRICT = "strict"


@dataclass(frozen=True)
class StructuredTextBlock:
    index: int
    text: str
    kind: TextBlockKind = TextBlockKind.PLAIN
    group_id: str | None = None


@dataclass(frozen=True)
class TranslationUnit:
    blocks: list[StructuredTextBlock]
    prompt_tier: PromptTier

    @property
    def character_count(self) -> int:
        return sum(len(block.text) for block in self.blocks)


@dataclass(frozen=True)
class DocumentStructureProfile:
    block_count: int
    unit_count: int
    table_block_count: int
    list_block_count: int
    dense_block_count: int
    strict_unit_count: int
    structured_unit_count: int


def build_translation_units(
    blocks: list[StructuredTextBlock],
    *,
    max_fragment_chars: int,
) -> list[TranslationUnit]:
    units: list[TranslationUnit] = []
    plain_batch: list[StructuredTextBlock] = []

    index = 0
    while index < len(blocks):
        block = blocks[index]
        if _is_plain_batchable(block):
            plain_batch = _append_plain_block(
                block,
                current=plain_batch,
                units=units,
                max_fragment_chars=max_fragment_chars,
            )
            index += 1
            continue

        if plain_batch:
            units.append(_unit_from_blocks(plain_batch))
            plain_batch = []

        group_blocks, index = _consume_structured_group(blocks, index)
        units.extend(
            _split_group_blocks(
                group_blocks,
                max_fragment_chars=max_fragment_chars,
            )
        )

    if plain_batch:
        units.append(_unit_from_blocks(plain_batch))

    return units


def profile_translation_units(
    blocks: list[StructuredTextBlock],
    *,
    max_fragment_chars: int,
) -> DocumentStructureProfile:
    units = build_translation_units(blocks, max_fragment_chars=max_fragment_chars)
    return DocumentStructureProfile(
        block_count=len(blocks),
        unit_count=len(units),
        table_block_count=sum(1 for block in blocks if block.kind is TextBlockKind.TABLE),
        list_block_count=sum(1 for block in blocks if block.kind is TextBlockKind.LIST),
        dense_block_count=sum(
            1 for block in blocks if block.kind is TextBlockKind.DENSE_MARKUP
        ),
        strict_unit_count=sum(1 for unit in units if unit.prompt_tier is PromptTier.STRICT),
        structured_unit_count=sum(
            1 for unit in units if unit.prompt_tier is PromptTier.STRUCTURED
        ),
    )


def estimate_unit_input_tokens(units: list[TranslationUnit]) -> int:
    return sum(
        ceil(unit.character_count / 4) + _prompt_overhead_tokens(unit.prompt_tier)
        for unit in units
    )


def _append_plain_block(
    block: StructuredTextBlock,
    *,
    current: list[StructuredTextBlock],
    units: list[TranslationUnit],
    max_fragment_chars: int,
) -> list[StructuredTextBlock]:
    block_length = len(block.text)
    separator_length = 2 if current else 0
    current_length = _joined_text_length(current)
    candidate_length = current_length + separator_length + block_length
    if current and candidate_length > max_fragment_chars:
        units.append(_unit_from_blocks(current))
        return [block]
    return [*current, block]


def _joined_text_length(blocks: list[StructuredTextBlock]) -> int:
    if not blocks:
        return 0
    return sum(len(block.text) for block in blocks) + 2 * (len(blocks) - 1)


def _consume_structured_group(
    blocks: list[StructuredTextBlock],
    index: int,
) -> tuple[list[StructuredTextBlock], int]:
    first = blocks[index]
    if first.group_id is None:
        return [first], index + 1

    group_blocks = [first]
    index += 1
    while index < len(blocks):
        block = blocks[index]
        if block.group_id != first.group_id or block.kind != first.kind:
            break
        group_blocks.append(block)
        index += 1
    return group_blocks, index


def _split_group_blocks(
    blocks: list[StructuredTextBlock],
    *,
    max_fragment_chars: int,
) -> list[TranslationUnit]:
    units: list[TranslationUnit] = []
    current: list[StructuredTextBlock] = []
    current_length = 0

    for block in blocks:
        block_length = len(block.text)
        separator_length = 2 if current else 0
        candidate_length = current_length + separator_length + block_length
        if current and candidate_length > max_fragment_chars:
            units.append(_unit_from_blocks(current))
            current = [block]
            current_length = block_length
            continue

        current.append(block)
        current_length = candidate_length

    if current:
        units.append(_unit_from_blocks(current))
    return units


def _unit_from_blocks(blocks: list[StructuredTextBlock]) -> TranslationUnit:
    return TranslationUnit(
        blocks=blocks,
        prompt_tier=_prompt_tier_for_blocks(blocks),
    )


def _prompt_tier_for_blocks(blocks: list[StructuredTextBlock]) -> PromptTier:
    kinds = {block.kind for block in blocks}
    if TextBlockKind.TABLE in kinds or TextBlockKind.DENSE_MARKUP in kinds:
        return PromptTier.STRICT
    if TextBlockKind.LIST in kinds or TextBlockKind.FOOTNOTE in kinds:
        return PromptTier.STRUCTURED
    return PromptTier.PLAIN


def _is_plain_batchable(block: StructuredTextBlock) -> bool:
    return block.kind in {TextBlockKind.PLAIN, TextBlockKind.HEADING}


def _prompt_overhead_tokens(prompt_tier: PromptTier) -> int:
    if prompt_tier is PromptTier.STRICT:
        return 140
    if prompt_tier is PromptTier.STRUCTURED:
        return 80
    return 30
