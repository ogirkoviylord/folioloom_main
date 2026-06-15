from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from translator_service.book_profile import detect_book_profile
from translator_service.documents import DocumentFormat
from translator_service.format_adapters.contracts import FormatAdapterPlan
from translator_service.format_adapters.docx import plan_docx_translation
from translator_service.format_adapters.epub import plan_epub_translation
from translator_service.format_adapters.txt import plan_txt_translation
from translator_service.glossary_candidate_reducer import (
    GlossaryCandidateDecisionStatus,
    GlossaryCandidateReducerCaps,
    reduce_glossary_candidates,
)
from translator_service.glossary_prepared_package import (
    GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
    validate_prepared_glossary_package,
)
from translator_service.glossary_scanner import scan_glossary_candidates

PREPARED_GLOSSARY_PREP_SERVICE_SCHEMA_VERSION = (
    "prepared-glossary-prep-service-v1"
)
PREPARED_GLOSSARY_PREP_PACKET_SCHEMA_VERSION = (
    "prepared-glossary-prep-packet-v1"
)
DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL = "deepseek-v4-pro"


@dataclass(frozen=True)
class PreparedGlossaryPackageAttachmentRequest:
    user_telegram_id: int
    file_name: str
    document_kind: str
    source_language: str
    target_language: str
    translation_mode: str | None
    glossary_mode: str | None
    source_sha256: str


@dataclass(frozen=True)
class PreparedGlossaryPackagePrepRequest:
    user_telegram_id: int
    file_name: str
    document_kind: str
    source_language: str
    target_language: str
    translation_mode: str | None
    glossary_mode: str | None
    source_sha256: str
    content: bytes


@dataclass(frozen=True)
class PreparedGlossaryPackageAttachment:
    payload: object | None = None
    source_sha256: str | None = None
    document_kind: str | None = None
    target_language: str | None = None
    enabled: bool = True
    reason_codes: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedGlossaryPrepServiceConfig:
    provider_model: str = DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL
    max_candidates: int = 8
    max_excerpt_chars: int = 1_200
    max_fragment_chars: int = 1_200
    max_estimated_editor_tokens: int = 2_400
    min_editor_score: int = 1
    min_diagnostic_score: int = 1


@dataclass(frozen=True)
class PreparedGlossaryProviderRequest:
    packet: Mapping[str, Any]
    metadata: Mapping[str, Any]


PreparedGlossaryPackageProvider = Callable[
    [PreparedGlossaryProviderRequest],
    Mapping[str, Any] | None,
]
PreparedGlossaryPlanBuilder = Callable[
    [DocumentFormat, bytes, int, str | None],
    FormatAdapterPlan,
]


class PreparedGlossaryPrepService:
    """Local/fake prepared-package service for automatic glossary job setup."""

    def __init__(
        self,
        *,
        provider: PreparedGlossaryPackageProvider | None = None,
        config: PreparedGlossaryPrepServiceConfig | None = None,
        plan_builder: PreparedGlossaryPlanBuilder | None = None,
    ) -> None:
        self._provider = provider
        self._config = config or PreparedGlossaryPrepServiceConfig()
        self._plan_builder = plan_builder or _default_plan_builder

    def prepare(
        self,
        request: PreparedGlossaryPackagePrepRequest,
    ) -> PreparedGlossaryPackageAttachment:
        config = self._config
        if request.glossary_mode != "with_glossary":
            return _disabled_attachment(
                request=request,
                status="disabled",
                reason_codes=("prepared_glossary_prep_not_requested",),
                config=config,
            )
        if self._provider is None:
            return _disabled_attachment(
                request=request,
                status="skipped",
                reason_codes=("prepared_glossary_prep_provider_missing",),
                config=config,
            )
        source_sha256 = hashlib.sha256(request.content).hexdigest()
        if source_sha256 != request.source_sha256:
            return _disabled_attachment(
                request=request,
                status="skipped",
                reason_codes=("prepared_glossary_prep_source_mismatch",),
                config=config,
                source_sha256=source_sha256,
            )
        try:
            document_format = DocumentFormat(request.document_kind)
        except ValueError:
            return _disabled_attachment(
                request=request,
                status="skipped",
                reason_codes=("prepared_glossary_prep_document_kind_unsupported",),
                config=config,
            )
        try:
            plan = self._plan_builder(
                document_format,
                request.content,
                config.max_fragment_chars,
                request.translation_mode,
            )
            snapshot = scan_glossary_candidates(
                plan,
                source_language=request.source_language,
                target_language=request.target_language,
                snapshot_id=f"prepared-glossary-prep:{source_sha256[:16]}",
            )
            profile = detect_book_profile(
                plan,
                source_language=request.source_language,
                target_language=request.target_language,
                glossary_snapshot=snapshot,
            )
            reduction = reduce_glossary_candidates(
                snapshot,
                profile_detection=profile,
                pressure_context={
                    "scope": "prepared_glossary_prep_service",
                    "document_kind": request.document_kind,
                    "target_language": request.target_language,
                    "max_candidates": config.max_candidates,
                    "metadata_only": True,
                },
                caps=GlossaryCandidateReducerCaps(
                    max_editor_entries=config.max_candidates,
                    max_diagnostic_entries=config.max_candidates,
                    max_estimated_editor_tokens=config.max_estimated_editor_tokens,
                    min_editor_score=config.min_editor_score,
                    min_diagnostic_score=config.min_diagnostic_score,
                ),
            )
        except Exception:
            return _disabled_attachment(
                request=request,
                status="skipped",
                reason_codes=("prepared_glossary_prep_local_planning_failed",),
                config=config,
            )

        candidates = _selected_candidates(
            reduction.retained_snapshot.entries,
            reduction.decisions,
            limit=config.max_candidates,
        )
        if not candidates:
            return _disabled_attachment(
                request=request,
                status="skipped",
                reason_codes=("prepared_glossary_prep_no_candidates",),
                config=config,
                candidate_selector_signature=reduction.reducer_signature,
                selected_candidate_count=0,
            )

        packet = _prep_packet(
            request=request,
            config=config,
            source_sha256=source_sha256,
            candidate_selector_signature=reduction.reducer_signature,
            candidates=candidates,
            plan_block_text_by_id=_plan_block_text_by_id(plan),
            evidence_by_id={
                evidence.evidence_id: evidence
                for evidence in reduction.retained_snapshot.evidence
            },
        )
        provider_metadata = _metadata(
            request=request,
            config=config,
            status="provider_requested",
            reason_codes=(),
            source_sha256=source_sha256,
            candidate_selector_signature=reduction.reducer_signature,
            selected_candidate_count=len(candidates),
        )
        try:
            payload = self._provider(
                PreparedGlossaryProviderRequest(
                    packet=packet,
                    metadata=provider_metadata,
                )
            )
        except Exception:
            return _disabled_attachment(
                request=request,
                status="skipped",
                reason_codes=("prepared_glossary_prep_provider_failed",),
                config=config,
                source_sha256=source_sha256,
                candidate_selector_signature=reduction.reducer_signature,
                selected_candidate_count=len(candidates),
            )
        if payload is None:
            return _disabled_attachment(
                request=request,
                status="skipped",
                reason_codes=("prepared_glossary_prep_provider_empty",),
                config=config,
                source_sha256=source_sha256,
                candidate_selector_signature=reduction.reducer_signature,
                selected_candidate_count=len(candidates),
            )

        validation = validate_prepared_glossary_package(
            payload,
            target_language=request.target_language,
        )
        metadata = _metadata(
            request=request,
            config=config,
            status="ready" if validation.ready else "skipped",
            reason_codes=validation.reason_codes,
            source_sha256=source_sha256,
            candidate_selector_signature=reduction.reducer_signature,
            selected_candidate_count=len(candidates),
            validation_metadata=validation.metadata,
        )
        if not validation.ready:
            return PreparedGlossaryPackageAttachment(
                enabled=False,
                reason_codes=tuple(validation.reason_codes),
                source_sha256=source_sha256,
                document_kind=request.document_kind,
                target_language=request.target_language,
                metadata=metadata,
            )
        return PreparedGlossaryPackageAttachment(
            payload=dict(payload),
            source_sha256=source_sha256,
            document_kind=request.document_kind,
            target_language=request.target_language,
            metadata=metadata,
        )


def _default_plan_builder(
    document_format: DocumentFormat,
    content: bytes,
    max_fragment_chars: int,
    translation_mode: str | None,
) -> FormatAdapterPlan:
    if document_format is DocumentFormat.TXT:
        return plan_txt_translation(
            content=content,
            max_fragment_chars=max_fragment_chars,
        )
    if document_format is DocumentFormat.DOCX:
        return plan_docx_translation(
            content=content,
            max_fragment_chars=max_fragment_chars,
            translation_mode=translation_mode,
        )
    if document_format is DocumentFormat.EPUB:
        return plan_epub_translation(
            content=content,
            max_fragment_chars=max_fragment_chars,
        )
    raise ValueError("prepared_glossary_prep_document_kind_unsupported")


def _selected_candidates(
    entries: Sequence[Any],
    decisions: Sequence[Any],
    *,
    limit: int,
) -> tuple[Any, ...]:
    retained_ids = {
        decision.entry_id
        for decision in decisions
        if decision.status is GlossaryCandidateDecisionStatus.RETAINED_FOR_EDITOR
    }
    return tuple(entry for entry in entries if entry.entry_id in retained_ids)[:limit]


def _prep_packet(
    *,
    request: PreparedGlossaryPackagePrepRequest,
    config: PreparedGlossaryPrepServiceConfig,
    source_sha256: str,
    candidate_selector_signature: str,
    candidates: Sequence[Any],
    plan_block_text_by_id: Mapping[str, str],
    evidence_by_id: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": PREPARED_GLOSSARY_PREP_PACKET_SCHEMA_VERSION,
        "source_language": request.source_language,
        "target_language": request.target_language,
        "document_kind": request.document_kind,
        "provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
        "provider_model": config.provider_model,
        "source_document_fingerprint": f"sha256:{source_sha256}",
        "candidate_selector_signature": candidate_selector_signature,
        "max_candidates": config.max_candidates,
        "max_excerpt_chars": config.max_excerpt_chars,
        "candidates": [
            _candidate_payload(
                entry,
                plan_block_text_by_id=plan_block_text_by_id,
                evidence_by_id=evidence_by_id,
                max_excerpt_chars=config.max_excerpt_chars,
            )
            for entry in candidates
        ],
    }


def _candidate_payload(
    entry: Any,
    *,
    plan_block_text_by_id: Mapping[str, str],
    evidence_by_id: Mapping[str, Any],
    max_excerpt_chars: int,
) -> dict[str, Any]:
    evidence_payloads = []
    for evidence_id in entry.evidence_refs:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            continue
        source_text = plan_block_text_by_id.get(evidence.source_block_id, "")
        evidence_payloads.append(
            {
                "evidence_id": evidence.evidence_id,
                "unit_sequence": evidence.unit_sequence,
                "source_block_id": evidence.source_block_id,
                "bounded_excerpt": source_text[:max_excerpt_chars],
            }
        )
    return {
        "source_entry_id": entry.entry_id,
        "source_canonical": entry.source_canonical,
        "aliases": list(entry.aliases),
        "evidence_refs": list(entry.evidence_refs),
        "source_unit_refs": sorted(
            {
                item["unit_sequence"]
                for item in evidence_payloads
                if "unit_sequence" in item
            }
        ),
        "source_block_refs": [
            item["source_block_id"]
            for item in evidence_payloads
            if "source_block_id" in item
        ],
        "evidence": evidence_payloads,
        "confidence": entry.confidence,
        "category": str(entry.category),
    }


def _plan_block_text_by_id(plan: FormatAdapterPlan) -> dict[str, str]:
    result: dict[str, str] = {}
    for unit in plan.units:
        for block in unit.blocks:
            result[block.source_block_id] = block.text
    return result


def _disabled_attachment(
    *,
    request: PreparedGlossaryPackagePrepRequest,
    status: str,
    reason_codes: Sequence[str],
    config: PreparedGlossaryPrepServiceConfig,
    source_sha256: str | None = None,
    candidate_selector_signature: str = "Unknown",
    selected_candidate_count: int = 0,
) -> PreparedGlossaryPackageAttachment:
    return PreparedGlossaryPackageAttachment(
        enabled=False,
        reason_codes=tuple(dict.fromkeys(str(code) for code in reason_codes)),
        source_sha256=source_sha256 or request.source_sha256,
        document_kind=request.document_kind,
        target_language=request.target_language,
        metadata=_metadata(
            request=request,
            config=config,
            status=status,
            reason_codes=reason_codes,
            source_sha256=source_sha256 or request.source_sha256,
            candidate_selector_signature=candidate_selector_signature,
            selected_candidate_count=selected_candidate_count,
        ),
    )


def _metadata(
    *,
    request: PreparedGlossaryPackagePrepRequest,
    config: PreparedGlossaryPrepServiceConfig,
    status: str,
    reason_codes: Sequence[str],
    source_sha256: str,
    candidate_selector_signature: str = "Unknown",
    selected_candidate_count: int = 0,
    validation_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "schema_version": PREPARED_GLOSSARY_PREP_SERVICE_SCHEMA_VERSION,
        "metadata_only": True,
        "raw_payload_included": False,
        "status": status,
        "reason_codes": list(dict.fromkeys(str(code) for code in reason_codes)),
        "document_kind": request.document_kind,
        "source_language": request.source_language,
        "target_language": request.target_language,
        "translation_mode": request.translation_mode or "Unknown",
        "glossary_mode": request.glossary_mode or "Unknown",
        "source_sha256_short": source_sha256[:12],
        "provider_model": config.provider_model,
        "provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
        "candidate_selector_signature": candidate_selector_signature,
        "selected_candidate_count": selected_candidate_count,
    }
    if validation_metadata is not None:
        metadata["validation"] = dict(validation_metadata)
    return metadata
