from dataclasses import dataclass

from translator_service.documents import DocumentFormat
from translator_service.extractors import TextExtractionError
from translator_service.format_adapters.contracts import FormatAdapterPlan, FormatTranslationUnit
from translator_service.format_adapters.txt_layout import parse_txt_document, plan_txt_segments
from translator_service.structure_optimizer import PromptTier, estimate_unit_input_tokens


TXT_ADAPTER_VERSION = "txt-adapter-v2"


def plan_txt_translation(
    *,
    content: bytes,
    max_fragment_chars: int,
    adapter_version: str = TXT_ADAPTER_VERSION,
) -> FormatAdapterPlan:
    document = parse_txt_document(content)
    units = plan_txt_segments(document, max_fragment_chars=max_fragment_chars)
    if not units:
        raise TextExtractionError("TXT file does not contain translatable text")
    character_count = len(
        "\n\n".join(
            block.text
            for unit in units
            for block in unit.blocks
        ).strip()
    )
    return FormatAdapterPlan(
        document_format=DocumentFormat.TXT,
        adapter_version=adapter_version,
        units=units,
        character_count=character_count,
        estimated_input_tokens=_estimate_txt_input_tokens(units),
    )


def _estimate_txt_input_tokens(units: tuple[FormatTranslationUnit, ...]) -> int:
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
