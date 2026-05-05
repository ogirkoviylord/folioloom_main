from dataclasses import dataclass

from translator_service.documents import DocumentFormat, DocumentUpload
from translator_service.extractors import (
    extract_docx_text_blocks,
    extract_epub_text_blocks,
    extract_text_from_txt,
)
from translator_service.pricing import PricingRules, estimate_price
from translator_service.text_analysis import estimate_text_volume


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

    blocks = extract_docx_text_blocks(content)
    text = "\n\n".join(blocks)
    estimate = _estimate_extracted_text(
        upload=upload,
        text=text,
        pricing_rules=pricing_rules,
        max_fragment_chars=max_fragment_chars,
    )
    return OrderEstimate(
        file_name=estimate.file_name,
        document_format=estimate.document_format,
        character_count=estimate.character_count,
        estimated_input_tokens=estimate.estimated_input_tokens,
        estimated_output_tokens=estimate.estimated_output_tokens,
        fragment_count=_count_grouped_text_blocks(
            blocks,
            max_fragment_chars=max_fragment_chars,
        ),
        price_usd=estimate.price_usd,
    )


def estimate_epub_order(
    *,
    upload: DocumentUpload,
    content: bytes,
    pricing_rules: PricingRules,
    max_fragment_chars: int,
) -> OrderEstimate:
    if upload.document_format is not DocumentFormat.EPUB:
        raise ValueError("EPUB estimator can only process EPUB uploads")

    blocks = extract_epub_text_blocks(content)
    text = "\n\n".join(blocks)
    estimate = _estimate_extracted_text(
        upload=upload,
        text=text,
        pricing_rules=pricing_rules,
        max_fragment_chars=max_fragment_chars,
    )
    return OrderEstimate(
        file_name=estimate.file_name,
        document_format=estimate.document_format,
        character_count=estimate.character_count,
        estimated_input_tokens=estimate.estimated_input_tokens,
        estimated_output_tokens=estimate.estimated_output_tokens,
        fragment_count=estimate.fragment_count,
        price_usd=estimate.price_usd,
    )


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


def _count_grouped_text_blocks(blocks: list[str], *, max_fragment_chars: int) -> int:
    grouped_count = 0
    current_length = 0
    for text in blocks:
        text_length = len(text)
        separator_length = 2 if current_length else 0
        candidate_length = current_length + separator_length + text_length
        if current_length and candidate_length > max_fragment_chars:
            grouped_count += 1
            current_length = text_length
            continue
        current_length = candidate_length

    if current_length:
        grouped_count += 1
    return grouped_count
