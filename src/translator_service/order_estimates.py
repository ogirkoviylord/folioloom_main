from dataclasses import dataclass

from translator_service.document_sandbox import DocumentSandbox
from translator_service.documents import DocumentFormat, DocumentUpload
from translator_service.format_adapters import (
    plan_docx_translation,
    plan_epub_translation,
    plan_txt_translation,
)
from translator_service.format_adapters.contracts import FormatAdapterPlan
from translator_service.pricing import PricingRules, estimate_price
from translator_service.text_analysis import TextAnalysis


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
    document_sandbox: DocumentSandbox | None = None,
    translation_mode: str | None = None,
) -> OrderEstimate:
    if document_sandbox is not None and upload.document_format in {
        DocumentFormat.TXT,
        DocumentFormat.DOCX,
        DocumentFormat.EPUB,
    }:
        return _estimate_adapter_plan_from_plan(
            upload=upload,
            plan=document_sandbox.plan_translation(
                document_format=upload.document_format,
                content=content,
                max_fragment_chars=max_fragment_chars,
                translation_mode=translation_mode,
            ),
            pricing_rules=pricing_rules,
        )

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
            translation_mode=translation_mode,
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

    plan = plan_txt_translation(
        content=content,
        max_fragment_chars=max_fragment_chars,
    )
    return _estimate_adapter_plan(
        upload=upload,
        character_count=plan.character_count,
        estimated_input_tokens=plan.estimated_input_tokens,
        fragment_count=plan.fragment_count,
        pricing_rules=pricing_rules,
    )


def estimate_docx_order(
    *,
    upload: DocumentUpload,
    content: bytes,
    pricing_rules: PricingRules,
    max_fragment_chars: int,
    translation_mode: str | None = None,
) -> OrderEstimate:
    if upload.document_format is not DocumentFormat.DOCX:
        raise ValueError("DOCX estimator can only process DOCX uploads")

    plan = plan_docx_translation(
        content=content,
        max_fragment_chars=max_fragment_chars,
        translation_mode=translation_mode,
    )
    return _estimate_adapter_plan(
        upload=upload,
        character_count=plan.character_count,
        estimated_input_tokens=plan.estimated_input_tokens,
        fragment_count=plan.fragment_count,
        pricing_rules=pricing_rules,
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

    plan = plan_epub_translation(
        content=content,
        max_fragment_chars=max_fragment_chars,
    )
    return _estimate_adapter_plan(
        upload=upload,
        character_count=plan.character_count,
        estimated_input_tokens=plan.estimated_input_tokens,
        fragment_count=plan.fragment_count,
        pricing_rules=pricing_rules,
    )


def _estimate_adapter_plan(
    *,
    upload: DocumentUpload,
    character_count: int,
    estimated_input_tokens: int,
    fragment_count: int,
    pricing_rules: PricingRules,
) -> OrderEstimate:
    text_analysis = TextAnalysis(
        character_count=character_count,
        estimated_input_tokens=estimated_input_tokens,
        fragment_count=fragment_count,
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


def _estimate_adapter_plan_from_plan(
    *,
    upload: DocumentUpload,
    plan: FormatAdapterPlan,
    pricing_rules: PricingRules,
) -> OrderEstimate:
    return _estimate_adapter_plan(
        upload=upload,
        character_count=plan.character_count,
        estimated_input_tokens=plan.estimated_input_tokens,
        fragment_count=plan.fragment_count,
        pricing_rules=pricing_rules,
    )
