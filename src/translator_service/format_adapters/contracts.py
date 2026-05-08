from __future__ import annotations

from dataclasses import dataclass

from translator_service.documents import DocumentFormat
from translator_service.structure_optimizer import PromptTier, TextBlockKind


@dataclass(frozen=True)
class FormatTextBlock:
    index: int
    source_block_id: str
    text: str
    kind: TextBlockKind = TextBlockKind.PLAIN
    group_id: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class FormatTranslationUnit:
    sequence: int
    blocks: tuple[FormatTextBlock, ...]
    prompt_tier: PromptTier

    @property
    def source_block_ids(self) -> tuple[str, ...]:
        return tuple(block.source_block_id for block in self.blocks)

    @property
    def source_text(self) -> str:
        return "\n\n".join(block.text for block in self.blocks)


@dataclass(frozen=True)
class FormatAdapterPlan:
    document_format: DocumentFormat
    adapter_version: str
    units: tuple[FormatTranslationUnit, ...]
    character_count: int
    estimated_input_tokens: int

    @property
    def fragment_count(self) -> int:
        return len(self.units)
