"""Pure DOCX-only manual glossary authorization preflight.

This caller-supplied structural observation validates an exact approved snapshot,
then exercises selection, prompt rendering, the glossary policy decision, and the
same ready/non-ready effective-decision rule used by the DOCX runner. It performs
no document-byte work, translation, cache, provider, job, persistence, or UI work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from translator_service.format_adapters.contracts import FormatTranslationUnit
from translator_service.glossary_contracts import (
    GlossarySnapshot,
    validate_glossary_snapshot,
)
from translator_service.glossary_effective_decision import (
    effective_glossary_runtime_adapter_decision,
)
from translator_service.glossary_prompt_context import GlossaryPromptContextConfig
from translator_service.glossary_selection import GlossarySelectionBudget
from translator_service.manual_glossary_rehearsal import (
    ManualGlossaryApproval,
    ManualGlossaryRehearsalBoundaryError,
    ManualGlossaryRehearsalFailure,
    ManualGlossaryRehearsalResult,
    rehearse_manual_glossary_approval,
)
from translator_service.translation_policy import (
    GlossaryPromptPolicyAdapterConfig,
    build_glossary_prompt_policy_adapter_decision,
)

DenialReason = Literal[
    "unsupported_document_kind",
    "invalid_snapshot",
    "missing_approval",
    "document_ref_mismatch",
    "signature_mismatch",
    "required_hard_entry_omitted",
    "effective_decision_not_ready",
]

__all__ = [
    "DocxGlossaryPreflightApproved",
    "DocxGlossaryPreflightDenied",
    "preflight_docx_manual_glossary_approval",
]


@dataclass(frozen=True)
class DocxGlossaryPreflightDenied:
    status: Literal["denied"]
    reason: DenialReason
    message: str


@dataclass(frozen=True)
class DocxGlossaryPreflightApproved:
    status: Literal["approved"]
    message: Literal["DOCX glossary effective-decision observed structurally."]
    document_ref: str
    glossary_signature: str
    snapshot_id: str
    selection_signature: str
    selected_entry_count: int
    included_entry_count: int
    effective_decision_status: Literal["effective_observed"]


def preflight_docx_manual_glossary_approval(
    *,
    document_kind: str,
    document_ref: str,
    snapshot: GlossarySnapshot,
    approval: ManualGlossaryApproval | None,
    work_unit: FormatTranslationUnit,
    selection_budget: GlossarySelectionBudget,
    prompt_config: GlossaryPromptContextConfig | None = None,
) -> DocxGlossaryPreflightApproved | DocxGlossaryPreflightDenied:
    """Observe the DOCX glossary decision seam without executing a document job.

    Validation order is fixed: document kind, snapshot validity with raw
    diagnostics disallowed, then exact approval validation/selection/rendering.
    Expected boundary failures map to fixed denials; unexpected errors propagate.
    """
    if document_kind != "docx":
        return _deny(
            "unsupported_document_kind",
            "Only DOCX is supported by this preflight.",
        )
    if not validate_glossary_snapshot(snapshot, allow_raw_diagnostics=False).valid:
        return _deny(
            "invalid_snapshot",
            "Glossary snapshot is invalid for this preflight.",
        )

    try:
        rehearsal = rehearse_manual_glossary_approval(
            document_ref,
            approval,
            snapshot,
            work_unit,
            selection_budget=selection_budget,
            prompt_config=prompt_config,
        )
    except ManualGlossaryRehearsalBoundaryError as error:
        boundary_reason = {
            "missing_approval": "missing_approval",
            "document_ref_mismatch": "document_ref_mismatch",
            "signature_mismatch": "signature_mismatch",
        }.get(error.reason)
        if boundary_reason is None:
            raise
        return _deny(
            cast(DenialReason, boundary_reason),
            "Exact manual glossary approval was not accepted.",
        )

    if isinstance(rehearsal, ManualGlossaryRehearsalFailure):
        return _deny(
            "required_hard_entry_omitted",
            "A required hard glossary entry was omitted.",
        )

    decision = build_glossary_prompt_policy_adapter_decision(
        _runner_compatible_plan(rehearsal, snapshot),
        config=GlossaryPromptPolicyAdapterConfig(enabled=True, work_unit_sequence=0),
    )
    effective = effective_glossary_runtime_adapter_decision(
        decision,
        _structural_preflight(rehearsal),
    )
    if effective is None:
        return _deny(
            "effective_decision_not_ready",
            "Glossary effective decision was not ready.",
        )
    return DocxGlossaryPreflightApproved(
        status="approved",
        message="DOCX glossary effective-decision observed structurally.",
        document_ref=rehearsal.document_ref,
        glossary_signature=rehearsal.glossary_signature,
        snapshot_id=rehearsal.snapshot_id,
        selection_signature=rehearsal.selection_signature,
        selected_entry_count=rehearsal.selected_entry_count,
        included_entry_count=rehearsal.included_entry_count,
        effective_decision_status="effective_observed",
    )


def _structural_preflight(
    rehearsal: ManualGlossaryRehearsalResult,
) -> dict[str, str | int | bool]:
    """Build the metadata-only effective-decision input for this observation."""
    return {
        "status": "ready" if rehearsal.included_entry_count else "skipped",
        "metadata_only": True,
        "selected_entry_count": rehearsal.selected_entry_count,
        "included_entry_count": rehearsal.included_entry_count,
    }


def _runner_compatible_plan(
    rehearsal: ManualGlossaryRehearsalResult,
    snapshot: GlossarySnapshot,
) -> dict[str, object]:
    return {
        "enabled": True,
        "status": "planned",
        "policy_signature_context": {
            "context_version": "translation-policy-signature-context-v1",
            "glossary_signature": rehearsal.glossary_signature,
            "profile_signature": snapshot.profile_signature,
            "translation_snapshot_signature": (
                "translation-contract-snapshot:v1:manual-preflight"
            ),
            "selection_signature": rehearsal.selection_signature,
            "selected_rule_ids": [],
            "prompt_contract_version": "prompt-contract:v1",
        },
        "work_unit_plans": [
            {
                "work_unit_sequence": 0,
                "budget_exceeded": False,
                "budget_status": "within_budget",
                "fallback_reason_codes": [],
                "selected_entry_ids": list(rehearsal.selected_entry_ids),
                "selection_signature": rehearsal.selection_signature,
            }
        ],
    }


def _deny(reason: DenialReason, message: str) -> DocxGlossaryPreflightDenied:
    return DocxGlossaryPreflightDenied(status="denied", reason=reason, message=message)
