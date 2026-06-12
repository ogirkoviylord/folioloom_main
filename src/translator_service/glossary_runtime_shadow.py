from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from translator_service.book_profile import detect_book_profile
from translator_service.format_adapters.txt import plan_txt_translation
from translator_service.glossary_candidate_reducer import (
    DEFAULT_GLOSSARY_CANDIDATE_REDUCER_CAPS,
    GlossaryCandidateReducerCaps,
    GlossaryCandidateReductionResult,
    glossary_candidate_reduction_payload,
    reduce_glossary_candidates,
)
from translator_service.glossary_scanner import scan_glossary_candidates
from translator_service.glossary_selection import (
    GLOSSARY_SELECTION_POLICY_VERSION,
    GlossarySelectionBudget,
    glossary_selection_metadata_payload,
    select_glossary_subsets_for_units,
)
from translator_service.structure_optimizer import PromptTier
from translator_service.translation_contract_snapshot import (
    build_translation_contract_snapshot,
    translation_contract_snapshot_signature,
    translation_policy_signature_context_from_snapshot,
)
from translator_service.translation_policy import (
    build_translation_policy,
    translation_policy_signature_context_payload,
)

GLOSSARY_RUNTIME_SHADOW_SCHEMA_VERSION = "glossary-runtime-shadow-plan-v1"


@dataclass(frozen=True)
class GlossaryRuntimeShadowConfig:
    enabled: bool = False
    max_fragment_chars: int = 2_400
    max_work_units: int = 3
    selection_budget: GlossarySelectionBudget = GlossarySelectionBudget(
        max_prompt_tokens=320,
        max_entries=12,
        max_diagnostic_entries=2,
    )
    reducer_caps: GlossaryCandidateReducerCaps = DEFAULT_GLOSSARY_CANDIDATE_REDUCER_CAPS


def build_glossary_runtime_shadow_plan_for_txt(
    *,
    content: bytes,
    source_language: str,
    target_language: str,
    config: GlossaryRuntimeShadowConfig | None = None,
) -> dict[str, Any]:
    config = config or GlossaryRuntimeShadowConfig()
    source_language = source_language.strip().lower() or "Unknown"
    target_language = target_language.strip().lower() or "Unknown"
    if not config.enabled:
        return _disabled_payload(source_language, target_language)

    try:
        plan = plan_txt_translation(
            content=content,
            max_fragment_chars=config.max_fragment_chars,
        )
        glossary = scan_glossary_candidates(
            plan,
            source_language=source_language,
            target_language=target_language,
        )
        profile = detect_book_profile(
            plan,
            source_language=source_language,
            target_language=target_language,
            glossary_snapshot=glossary,
        )
        reduction = reduce_glossary_candidates(
            glossary,
            profile_detection=profile,
            pressure_context=_shadow_pressure_context(
                plan=plan,
                glossary_entry_count=len(glossary.entries),
                glossary_evidence_count=len(glossary.evidence),
            ),
            caps=config.reducer_caps,
        )
        if not reduction.retained_entry_ids:
            return _fallback_payload(
                source_language=source_language,
                target_language=target_language,
                fallback_reason="no_reduced_candidates",
                error_type="MissingReducedGlossaryData",
            )
        policy = build_translation_policy(
            text=_policy_sample_text(plan),
            source_language=source_language,
            target_language=target_language,
            prompt_tier=PromptTier.PLAIN,
        )
        selected_rule_ids = tuple(rule.rule_id for rule in profile.rules)
        snapshot = build_translation_contract_snapshot(
            policy,
            glossary_snapshot=reduction.retained_snapshot,
            profile_detection=profile,
            selected_rule_ids=selected_rule_ids,
            selection_policy_version=GLOSSARY_SELECTION_POLICY_VERSION,
            quality_route="shadow_only",
        )
        units = plan.units[: max(0, config.max_work_units)]
        selections = select_glossary_subsets_for_units(
            units,
            reduction.retained_snapshot,
            budget=config.selection_budget,
            profile_rule_ids=selected_rule_ids,
        )
    except Exception as error:
        return _fallback_payload(
            source_language=source_language,
            target_language=target_language,
            fallback_reason="shadow_planning_failed",
            error_type=error.__class__.__name__,
        )

    selection_payloads = tuple(
        glossary_selection_metadata_payload(selection) for selection in selections
    )
    reducer_payload = _reducer_shadow_payload(reduction)
    aggregate_selection_signature = _aggregate_selection_signature(
        selection["selection_signature"] for selection in selection_payloads
    )
    snapshot_signature = translation_contract_snapshot_signature(snapshot)
    policy_context = translation_policy_signature_context_payload(
        translation_policy_signature_context_from_snapshot(
            snapshot,
            selection_signature=aggregate_selection_signature,
        )
    )
    status, fallback_reason = _status_for_selections(selection_payloads)
    return {
        "schema_version": GLOSSARY_RUNTIME_SHADOW_SCHEMA_VERSION,
        "enabled": True,
        "status": status,
        "fallback_reason": fallback_reason,
        "source_language": source_language,
        "target_language": target_language,
        "translation_mode": "book",
        "fragment_count": plan.fragment_count,
        "planned_work_unit_count": len(selection_payloads),
        "source_glossary_signature": reducer_payload["source_glossary_signature"],
        "glossary_signature": snapshot.glossary_signature,
        "reduced_glossary_signature": reducer_payload["reduced_glossary_signature"],
        "profile_signature": snapshot.profile_signature,
        "reducer": reducer_payload,
        "translation_snapshot_signature": snapshot_signature,
        "aggregate_selection_signature": aggregate_selection_signature,
        "selected_rule_ids": list(snapshot.selected_rule_ids),
        "uncertainty_markers": list(snapshot.uncertainty_markers),
        "policy_signature_context": policy_context,
        "work_unit_plans": [
            _work_unit_shadow_payload(selection, reducer_payload=reducer_payload)
            for selection in selection_payloads
        ],
        "runtime_integration": {
            "normal_translation_prompts_changed": False,
            "live_provider_calls_allowed": False,
            "durable_state_mutation_allowed": False,
            "cache_mutation_allowed": False,
            "fallback_action": "omit_glossary_prompt_context",
        },
    }


def _disabled_payload(source_language: str, target_language: str) -> dict[str, Any]:
    return {
        "schema_version": GLOSSARY_RUNTIME_SHADOW_SCHEMA_VERSION,
        "enabled": False,
        "status": "disabled",
        "fallback_reason": "shadow_planning_disabled_by_default",
        "source_language": source_language,
        "target_language": target_language,
        "work_unit_plans": [],
        "runtime_integration": {
            "normal_translation_prompts_changed": False,
            "live_provider_calls_allowed": False,
            "durable_state_mutation_allowed": False,
            "cache_mutation_allowed": False,
            "fallback_action": "use_existing_translation_path",
        },
    }


def _fallback_payload(
    *,
    source_language: str,
    target_language: str,
    fallback_reason: str,
    error_type: str,
) -> dict[str, Any]:
    return {
        "schema_version": GLOSSARY_RUNTIME_SHADOW_SCHEMA_VERSION,
        "enabled": True,
        "status": "fallback",
        "fallback_reason": fallback_reason,
        "error_type": error_type,
        "source_language": source_language,
        "target_language": target_language,
        "work_unit_plans": [],
        "runtime_integration": {
            "normal_translation_prompts_changed": False,
            "live_provider_calls_allowed": False,
            "durable_state_mutation_allowed": False,
            "cache_mutation_allowed": False,
            "fallback_action": "use_existing_translation_path",
        },
    }


def _work_unit_shadow_payload(
    selection: Mapping[str, Any],
    *,
    reducer_payload: Mapping[str, Any],
) -> dict[str, Any]:
    drop_reasons = sorted(
        {entry["reason"] for entry in selection["dropped_entries"]}
    )
    fallback_reasons = _fallback_reason_codes(selection, drop_reasons=drop_reasons)
    return {
        "work_unit_sequence": selection["work_unit_sequence"],
        "source_block_ids": list(selection["source_block_ids"]),
        "source_glossary_signature": reducer_payload["source_glossary_signature"],
        "reduced_glossary_signature": reducer_payload["reduced_glossary_signature"],
        "reducer_signature": reducer_payload["reducer_signature"],
        "prompt_budget_tokens": selection["prompt_budget_tokens"],
        "estimated_prompt_tokens": selection["estimated_prompt_tokens"],
        "budget_exceeded": selection["budget_exceeded"],
        "budget_status": (
            "fallback_omitted" if fallback_reasons else "within_budget"
        ),
        "fallback_reason_codes": fallback_reasons,
        "selected_entry_ids": [
            entry["entry_id"] for entry in selection["selected_entries"]
        ],
        "dropped_entry_ids": [
            entry["entry_id"] for entry in selection["dropped_entries"]
        ],
        "drop_reasons": drop_reasons,
        "selection_signature": selection["selection_signature"],
        "policy_version": selection["policy_version"],
        "fallback_action": (
            "omit_glossary_prompt_context"
            if fallback_reasons
            else "shadow_metadata_only"
        ),
    }


def _status_for_selections(
    selections: tuple[Mapping[str, Any], ...],
) -> tuple[str, str]:
    if not selections:
        return "fallback", "no_work_units_planned"
    if any(selection["budget_exceeded"] for selection in selections):
        return "planned_with_budget_fallback", "selection_budget_exceeded"
    if any(
        "prompt_budget_exhausted" in {
            entry["reason"] for entry in selection["dropped_entries"]
        }
        for selection in selections
    ):
        return "planned_with_budget_fallback", "prompt_budget_exhausted"
    if any(selection["dropped_entries"] for selection in selections):
        return "planned_with_drops", "some_entries_omitted"
    return "planned", "none"


def _fallback_reason_codes(
    selection: Mapping[str, Any],
    *,
    drop_reasons: list[str],
) -> list[str]:
    reasons: list[str] = []
    if selection["budget_exceeded"]:
        reasons.append("selection_budget_exceeded")
    if "prompt_budget_exhausted" in drop_reasons:
        reasons.append("prompt_budget_exhausted")
    return sorted(dict.fromkeys(reasons))


def _reducer_shadow_payload(
    reduction: GlossaryCandidateReductionResult,
) -> dict[str, Any]:
    payload = glossary_candidate_reduction_payload(reduction)
    return {
        "policy_version": payload["policy_version"],
        "reducer_signature": payload["reducer_signature"],
        "source_glossary_signature": payload["source_glossary_signature"],
        "reduced_glossary_signature": payload["reduced_glossary_signature"],
        "profile_signature": payload["profile_signature"],
        "pressure_signature": payload["pressure_signature"],
        "retained_count": len(reduction.retained_entry_ids),
        "diagnostic_count": len(reduction.diagnostic_entry_ids),
        "dropped_count": len(reduction.dropped_entry_ids),
        "caps": payload["caps"],
    }


def _shadow_pressure_context(
    *,
    plan: Any,
    glossary_entry_count: int,
    glossary_evidence_count: int,
) -> Mapping[str, Any]:
    return {
        "document_format": getattr(
            plan.document_format,
            "value",
            str(plan.document_format),
        ),
        "fragment_count": plan.fragment_count,
        "character_count": plan.character_count,
        "glossary_entry_count": glossary_entry_count,
        "glossary_evidence_count": glossary_evidence_count,
        "selection_policy_version": GLOSSARY_SELECTION_POLICY_VERSION,
        "shadow_schema_version": GLOSSARY_RUNTIME_SHADOW_SCHEMA_VERSION,
    }


def _aggregate_selection_signature(selection_signatures: Any) -> str:
    payload = {
        "schema_version": GLOSSARY_RUNTIME_SHADOW_SCHEMA_VERSION,
        "selection_signatures": sorted(str(item) for item in selection_signatures),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return f"glossary-shadow-selection:v1:{digest}"


def _policy_sample_text(plan: Any) -> str:
    parts: list[str] = []
    remaining = 2_000
    for unit in plan.units:
        text = unit.source_text.strip()
        if not text:
            continue
        if len(text) > remaining:
            parts.append(text[:remaining])
            break
        parts.append(text)
        remaining -= len(text) + 2
        if remaining <= 0:
            break
    return "\n\n".join(parts) or "Unknown"
