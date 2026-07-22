"""Pure glossary effective-decision rule shared by runtime and preflight callers."""

from __future__ import annotations

from collections.abc import Mapping

from translator_service.translation_policy import (
    GlossaryPromptPolicyAdapterDecision,
)

__all__ = ["effective_glossary_runtime_adapter_decision"]


def effective_glossary_runtime_adapter_decision(
    decision: GlossaryPromptPolicyAdapterDecision | None,
    preflight: Mapping[str, object] | None,
) -> GlossaryPromptPolicyAdapterDecision | None:
    """Return the decision allowed by the existing runtime preflight rule."""
    if decision is None or preflight is None:
        return decision
    if decision.status.value != "ready":
        return decision
    if preflight.get("status") == "ready":
        return decision
    return None
