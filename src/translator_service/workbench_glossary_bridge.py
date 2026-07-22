"""UI-neutral bridge for the pure manual glossary approval rehearsal.

This module intentionally forwards caller-owned opaque inputs to the completed
Stage-1 rehearsal seam without creating or refreshing approval, deriving a
document identity, or invoking runtime services. The returned Stage-1
structural observation or fail-closed result is preserved unchanged.
"""

from __future__ import annotations

from translator_service.format_adapters.contracts import FormatTranslationUnit
from translator_service.glossary_contracts import GlossarySnapshot
from translator_service.glossary_prompt_context import GlossaryPromptContextConfig
from translator_service.glossary_selection import GlossarySelectionBudget
from translator_service.manual_glossary_rehearsal import (
    ManualGlossaryApproval,
    ManualGlossaryRehearsalFailure,
    ManualGlossaryRehearsalResult,
    rehearse_manual_glossary_approval,
)

__all__ = ["rehearse_workbench_glossary"]


def rehearse_workbench_glossary(
    document_ref: str,
    approval: ManualGlossaryApproval | None,
    snapshot: GlossarySnapshot,
    work_unit: FormatTranslationUnit,
    *,
    selection_budget: GlossarySelectionBudget,
    prompt_config: GlossaryPromptContextConfig | None = None,
) -> ManualGlossaryRehearsalResult | ManualGlossaryRehearsalFailure:
    """Delegate one caller-authorized rehearsal without altering its outcome.

    ``document_ref`` remains opaque: this bridge does not parse, replace, or
    derive it. ``approval`` is forwarded exactly as supplied, allowing the
    Stage-1 boundary to fail closed for a missing or mismatched approval.
    """
    return rehearse_manual_glossary_approval(
        document_ref,
        approval,
        snapshot,
        work_unit,
        selection_budget=selection_budget,
        prompt_config=prompt_config,
    )
