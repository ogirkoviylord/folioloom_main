from dataclasses import dataclass

from translator_service.documents import DocumentFormat, DocumentUpload
from translator_service.extractors import (
    extract_text_from_txt,
)
from translator_service.pricing import PricingRules, estimate_price
from translator_service.structure_optimizer import (
    StructuredTextBlock,
    build_translation_units,
    estimate_unit_input_tokens,
)
from translator_service.text_analysis import TextAnalysis, estimate_text_volume
from translator_service.translation_runner import (
    _extract_docx_blocks,
    _extract_epub_blocks,
    _group_epub_blocks,
)


@dataclass(frozen=True)
class OrderEstimate:
    file_name: str
    document_format: DocumentFormat
    character_count: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    fragment_count: int
    price_usd: float


class DocumentEstimationNotReadyError(ValueError):
    pass


def estimate_order(
    *,
    upload: DocumentUpload,
    content: bytes,
    pricing_rules: PricingRules,
    max_fragment_chars: int,
) -> OrderEstimate:
    if upload.document_format is DocumentFormat.TXT:
        return estimate_txt_order(
            upload=upload,
            content=content,
            pricing_rules=pricing_rules,
            max_fragment_chars=max_fragment_chars,
        )
    if upload.document_format is DocumentFormat.DOCX:
        return estimate_docx_order(
            upload=upload,
            content=content,
            pricing_rules=pricing_rules,
            max_fragment_chars=max_fragment_chars,
        )
    if upload.document_format is DocumentFormat.EPUB:
        return estimate_epub_order(
            upload=upload,
            content=content,
            pricing_rules=pricing_rules,
            max_fragment_chars=max_fragment_chars,
        )

    raise DocumentEstimationNotReadyError(
        f"Estimation for {upload.document_format.value} documents is not ready yet"
    )


def estimate_txt_order(
    *,
    upload: DocumentUpload,
    content: bytes,
    pricing_rules: PricingRules,
    max_fragment_chars: int,
) -> OrderEstimate:
    if upload.document_format is not DocumentFormat.TXT:
        raise ValueError("TXT estimator can only process TXT uploads")

    text = extract_text_from_txt(content)
    return _estimate_extracted_text(
        upload=upload,
        text=text,
        pricing_rules=pricing_rules,
        max_fragment_chars=max_fragment_chars,
    )


def estimate_docx_order(
    *,
    upload: DocumentUpload,
    content: bytes,
    pricing_rules: PricingRules,
    max_fragment_chars: int,
) -> OrderEstimate:
    if upload.document_format is not DocumentFormat.DOCX:
        raise ValueError("DOCX estimator can only process DOCX uploads")

    blocks = _extract_docx_blocks(content)
    text = "\n\n".join(block.text for block in blocks)
    estimate = _estimate_structured_blocks(
        upload=upload,
        text=text,
        blocks=[
            StructuredTextBlock(
                index=index,
                text=block.text,
                kind=block.kind,
                group_id=block.group_id,
            )
            for index, block in enumerate(blocks)
        ],
        pricing_rules=pricing_rules,
        max_fragment_chars=max_fragment_chars,
    )
    return estimate


def estimate_epub_order(
    *,
    upload: DocumentUpload,
    content: bytes,
    pricing_rules: PricingRules,
    max_fragment_chars: int,
) -> OrderEstimate:
    if upload.document_format is not DocumentFormat.EPUB:
        raise ValueError("EPUB estimator can only process EPUB uploads")

    blocks = _extract_epub_blocks(content)
    translation_units = _group_epub_blocks(
        blocks,
        max_fragment_chars=max_fragment_chars,
    )
    translatable_blocks = [
        block
        for unit in translation_units
        for block in unit.blocks
    ]
    text = "\n\n".join(block.text for block in translatable_blocks)
    estimate = _estimate_structured_blocks(
        upload=upload,
        text=text,
        blocks=[
            StructuredTextBlock(
                index=index,
                text=block.text,
                kind=block.kind,
                group_id=block.group_id,
            )
            for index, block in enumerate(translatable_blocks)
        ],
        pricing_rules=pricing_rules,
        max_fragment_chars=max_fragment_chars,
    )
    return estimate


def _estimate_extracted_text(
    *,
    upload: DocumentUpload,
    text: str,
    pricing_rules: PricingRules,
    max_fragment_chars: int,
) -> OrderEstimate:
    text_analysis = estimate_text_volume(text, max_fragment_chars=max_fragment_chars)
    price_estimate = estimate_price(text_analysis, pricing_rules)

    return OrderEstimate(
        file_name=upload.file_name,
        document_format=upload.document_format,
        character_count=text_analysis.character_count,
        estimated_input_tokens=price_estimate.estimated_input_tokens,
        estimated_output_tokens=price_estimate.estimated_output_tokens,
        fragment_count=text_analysis.fragment_count,
        price_usd=price_estimate.price_usd,
    )


def _estimate_structured_blocks(
    *,
    upload: DocumentUpload,
    text: str,
    blocks: list[StructuredTextBlock],
    pricing_rules: PricingRules,
    max_fragment_chars: int,
) -> OrderEstimate:
    units = build_translation_units(blocks, max_fragment_chars=max_fragment_chars)
    normalized_text = text.strip()
    text_analysis = TextAnalysis(
        character_count=len(normalized_text),
        estimated_input_tokens=estimate_unit_input_tokens(units),
        fragment_count=len(units),
    )
    price_estimate = estimate_price(text_analysis, pricing_rules)

    return OrderEstimate(
        file_name=upload.file_name,
        document_format=upload.document_format,
        character_count=text_analysis.character_count,
        estimated_input_tokens=price_estimate.estimated_input_tokens,
        estimated_output_tokens=price_estimate.estimated_output_tokens,
        fragment_count=text_analysis.fragment_count,
        price_usd=price_estimate.price_usd,
    )
