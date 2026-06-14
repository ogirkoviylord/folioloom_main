from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from translator_service.book_profile import detect_book_profile
from translator_service.documents import DocumentFormat
from translator_service.format_adapters.contracts import (
    FormatAdapterPlan,
    FormatTextBlock,
    FormatTranslationUnit,
)
from translator_service.glossary_candidate_reducer import (
    DEFAULT_GLOSSARY_CANDIDATE_REDUCER_CAPS,
    GlossaryCandidateReducerCaps,
    reduce_glossary_candidates,
)
from translator_service.glossary_contracts import GlossaryEntry, GlossarySnapshot
from translator_service.glossary_prompt_context import (
    GlossaryPromptContextConfig,
    format_glossary_prompt_context,
)
from translator_service.glossary_scanner import scan_glossary_candidates
from translator_service.glossary_selection import (
    GLOSSARY_SELECTION_POLICY_VERSION,
    GlossarySelectionBudget,
    glossary_selection_metadata_payload,
    select_glossary_subset_for_work_unit,
)
from translator_service.glossary_target_metadata_overlay import (
    GlossaryTargetMetadataOverlayConfig,
    apply_glossary_target_metadata_overlay,
)
from translator_service.persistent_jobs import PersistentWorkUnit
from translator_service.structure_optimizer import PromptTier, TextBlockKind
from translator_service.translation_contract_snapshot import (
    build_translation_contract_snapshot,
    translation_contract_snapshot_signature,
    translation_policy_signature_context_from_snapshot,
)
from translator_service.translation_policy import (
    build_translation_policy,
    translation_policy_signature_context_payload,
)
from translator_service.translation_runner import (
    GlossaryRuntimeAdapterHookConfig,
    build_fallback_glossary_runtime_hook,
)

PERSISTENT_EPUB_GLOSSARY_RESOLVER_SCHEMA_VERSION = (
    "persistent-epub-glossary-runtime-resolver-v1"
)
PERSISTENT_EPUB_GLOSSARY_RESOLVER_ADAPTER_VERSION = (
    "persistent-epub-work-unit-glossary-adapter-v1"
)


@dataclass(frozen=True)
class PersistentEpubGlossaryResolverConfig:
    enabled: bool = False
    owner_battle_test_enabled: bool = False
    prompt_rehearsal_enabled: bool = True
    max_source_blocks: int = 12
    max_source_characters: int = 2_400
    max_selected_entries: int = 32
    selection_budget: GlossarySelectionBudget = field(
        default_factory=lambda: GlossarySelectionBudget(
            max_prompt_tokens=320,
            max_entries=12,
            max_diagnostic_entries=2,
        )
    )
    prompt_context_config: GlossaryPromptContextConfig = field(
        default_factory=GlossaryPromptContextConfig
    )
    reducer_caps: GlossaryCandidateReducerCaps = DEFAULT_GLOSSARY_CANDIDATE_REDUCER_CAPS
    target_metadata_overlay_config: GlossaryTargetMetadataOverlayConfig = field(
        default_factory=lambda: GlossaryTargetMetadataOverlayConfig(enabled=True)
    )


def build_persistent_epub_glossary_runtime_hook_resolver(
    *,
    source_text_loader: Callable[[PersistentWorkUnit], str],
    target_metadata_overlay_payload: Mapping[str, Any] | None,
    document_kind_resolver: Callable[[PersistentWorkUnit], str | None] | None = None,
    config: PersistentEpubGlossaryResolverConfig | None = None,
) -> Callable[[PersistentWorkUnit], GlossaryRuntimeAdapterHookConfig | None]:
    config = config or PersistentEpubGlossaryResolverConfig()

    def resolve(work_unit: PersistentWorkUnit) -> GlossaryRuntimeAdapterHookConfig:
        try:
            source_text = source_text_loader(work_unit)
        except Exception:
            return _fallback_hook("persistent_epub_source_text_unavailable")
        document_kind = (
            document_kind_resolver(work_unit)
            if document_kind_resolver is not None
            else DocumentFormat.EPUB.value
        )
        return build_persistent_epub_glossary_runtime_hook(
            work_unit=work_unit,
            source_text=source_text,
            target_metadata_overlay_payload=target_metadata_overlay_payload,
            document_kind=document_kind,
            config=config,
        )

    return resolve


def build_persistent_epub_glossary_runtime_hook(
    *,
    work_unit: PersistentWorkUnit,
    source_text: str,
    target_metadata_overlay_payload: Mapping[str, Any] | None,
    document_kind: str | None = DocumentFormat.EPUB.value,
    config: PersistentEpubGlossaryResolverConfig | None = None,
) -> GlossaryRuntimeAdapterHookConfig:
    config = config or PersistentEpubGlossaryResolverConfig()
    if not config.enabled:
        return _fallback_hook("persistent_epub_glossary_resolver_disabled")
    if not config.owner_battle_test_enabled:
        return _fallback_hook("persistent_epub_owner_battle_test_not_enabled")
    if _normalized_document_kind(document_kind) != DocumentFormat.EPUB.value:
        return _fallback_hook("persistent_epub_unsupported_document_kind")
    if not isinstance(target_metadata_overlay_payload, Mapping):
        return _fallback_hook("persistent_epub_target_metadata_missing")

    source_blocks = _source_blocks_for_work_unit(work_unit, source_text)
    source_character_count = sum(len(block.text) for block in source_blocks)
    if not source_blocks or source_character_count == 0:
        return _fallback_hook("persistent_epub_source_text_empty")
    if len(source_blocks) > config.max_source_blocks:
        return _fallback_hook("persistent_epub_source_block_limit_exceeded")
    if source_character_count > config.max_source_characters:
        return _fallback_hook("persistent_epub_source_character_limit_exceeded")

    unit = FormatTranslationUnit(
        sequence=work_unit.sequence,
        blocks=tuple(source_blocks),
        prompt_tier=_prompt_tier(work_unit.prompt_tier),
    )
    plan = FormatAdapterPlan(
        document_format=DocumentFormat.EPUB,
        adapter_version=PERSISTENT_EPUB_GLOSSARY_RESOLVER_ADAPTER_VERSION,
        units=(unit,),
        character_count=source_character_count,
        estimated_input_tokens=max(1, source_character_count // 4),
    )

    try:
        scanned = scan_glossary_candidates(
            plan,
            source_language=work_unit.source_language,
            target_language=work_unit.target_language,
            snapshot_id=_snapshot_id(work_unit, source_character_count),
        )
        profile = detect_book_profile(
            plan,
            source_language=work_unit.source_language,
            target_language=work_unit.target_language,
            glossary_snapshot=scanned,
        )
        reduction = reduce_glossary_candidates(
            scanned,
            profile_detection=profile,
            pressure_context=_pressure_context(
                work_unit,
                source_character_count=source_character_count,
                scanned_entry_count=len(scanned.entries),
            ),
            caps=config.reducer_caps,
        )
    except Exception:
        return _fallback_hook("persistent_epub_local_glossary_planning_failed")

    if not reduction.retained_entry_ids:
        return _fallback_hook("persistent_epub_no_retained_glossary_entries")

    overlay_result = apply_glossary_target_metadata_overlay(
        reduction.retained_snapshot,
        target_metadata_overlay_payload,
        target_language=work_unit.target_language,
        config=config.target_metadata_overlay_config,
    )
    if overlay_result.status != "applied":
        return _fallback_hook(
            _fallback_reason_from_overlay_status(overlay_result.status),
        )

    selection = select_glossary_subset_for_work_unit(
        unit,
        overlay_result.snapshot,
        budget=config.selection_budget,
        profile_rule_ids=tuple(rule.rule_id for rule in profile.rules),
    )
    selection_payload = glossary_selection_metadata_payload(selection)
    useful_entry_ids = _useful_selected_entry_ids(
        selection_payload.get("selected_entries", ()),
        overlay_result.snapshot,
        source_text=unit.source_text,
    )
    if not useful_entry_ids:
        return _fallback_hook("persistent_epub_no_useful_glossary_entries")

    prompt_context_result = format_glossary_prompt_context(
        _prompt_context_entries(overlay_result.snapshot),
        selected_entry_ids=useful_entry_ids,
        config=config.prompt_context_config,
    )
    if not prompt_context_result.included_entries:
        return _fallback_hook("persistent_epub_prompt_context_budget_exhausted")

    policy = build_translation_policy(
        text=unit.source_text,
        source_language=work_unit.source_language,
        target_language=work_unit.target_language,
        prompt_tier=unit.prompt_tier,
    )
    selected_rule_ids = tuple(rule.rule_id for rule in profile.rules)
    snapshot = build_translation_contract_snapshot(
        policy,
        glossary_snapshot=overlay_result.snapshot,
        profile_detection=profile,
        selected_rule_ids=selected_rule_ids,
        selection_policy_version=GLOSSARY_SELECTION_POLICY_VERSION,
        quality_route="owner_battle_test",
    )
    policy_context = translation_policy_signature_context_payload(
        translation_policy_signature_context_from_snapshot(
            snapshot,
            selection_signature=str(selection_payload["selection_signature"]),
        )
    )
    work_unit_plan = _work_unit_plan_payload(
        selection_payload,
        selected_entry_ids=useful_entry_ids,
    )
    return GlossaryRuntimeAdapterHookConfig(
        enabled=True,
        glossary_plan={
            "schema_version": PERSISTENT_EPUB_GLOSSARY_RESOLVER_SCHEMA_VERSION,
            "enabled": True,
            "status": "planned",
            "fallback_reason": "none",
            "source_language": work_unit.source_language,
            "target_language": work_unit.target_language,
            "document_format": DocumentFormat.EPUB.value,
            "translation_mode": "book",
            "source_glossary_signature": reduction.source_glossary_signature,
            "glossary_signature": snapshot.glossary_signature,
            "reduced_glossary_signature": reduction.reduced_glossary_signature,
            "profile_signature": snapshot.profile_signature,
            "translation_snapshot_signature": (
                translation_contract_snapshot_signature(snapshot)
            ),
            "aggregate_selection_signature": selection_payload[
                "selection_signature"
            ],
            "policy_signature_context": policy_context,
            "selected_rule_ids": list(selected_rule_ids),
            "target_metadata_overlay": overlay_result.metadata,
            "work_unit_plans": [work_unit_plan],
            "runtime_integration": _runtime_integration_payload(),
        },
        max_selected_entries=config.max_selected_entries,
        prompt_rehearsal_enabled=config.prompt_rehearsal_enabled,
        prompt_context_entries=_prompt_context_entries(overlay_result.snapshot),
        prompt_context_config=config.prompt_context_config,
        owner_battle_test_enabled=config.owner_battle_test_enabled,
        battle_test_max_source_blocks=config.max_source_blocks,
        battle_test_max_source_characters=config.max_source_characters,
    )


def _fallback_hook(fallback_reason: str) -> GlossaryRuntimeAdapterHookConfig:
    return build_fallback_glossary_runtime_hook(
        fallback_reason=_compact_reason(fallback_reason),
    )


def _work_unit_plan_payload(
    selection_payload: Mapping[str, Any],
    *,
    selected_entry_ids: Sequence[str],
) -> dict[str, Any]:
    selected = tuple(dict.fromkeys(selected_entry_ids))
    estimated_tokens = sum(
        int(entry.get("estimated_prompt_tokens", 0))
        for entry in selection_payload.get("selected_entries", ())
        if isinstance(entry, Mapping) and entry.get("entry_id") in selected
    )
    return {
        "work_unit_sequence": selection_payload["work_unit_sequence"],
        "source_block_ids": list(selection_payload["source_block_ids"]),
        "prompt_budget_tokens": selection_payload["prompt_budget_tokens"],
        "estimated_prompt_tokens": estimated_tokens,
        "budget_exceeded": False,
        "budget_status": "within_budget",
        "fallback_reason_codes": [],
        "selected_entry_ids": list(selected),
        "dropped_entry_ids": [
            str(entry.get("entry_id"))
            for entry in selection_payload.get("dropped_entries", ())
            if isinstance(entry, Mapping) and entry.get("entry_id")
        ],
        "selection_signature": selection_payload["selection_signature"],
        "policy_version": selection_payload["policy_version"],
        "fallback_action": "shadow_metadata_only",
    }


def _useful_selected_entry_ids(
    selected_entries: Any,
    snapshot: GlossarySnapshot,
    *,
    source_text: str,
) -> tuple[str, ...]:
    if isinstance(selected_entries, (str, bytes)) or not isinstance(
        selected_entries,
        Sequence,
    ):
        return ()
    by_id = {entry.entry_id: entry for entry in snapshot.entries}
    useful: list[str] = []
    for selected in selected_entries:
        if not isinstance(selected, Mapping):
            continue
        entry_id = selected.get("entry_id")
        if not isinstance(entry_id, str):
            continue
        entry = by_id.get(entry_id)
        if entry is None:
            continue
        if not _entry_has_target_metadata(entry):
            continue
        if not _entry_source_matches(entry, source_text):
            continue
        useful.append(entry_id)
    return tuple(dict.fromkeys(useful))


def _entry_has_target_metadata(entry: GlossaryEntry) -> bool:
    return bool(
        (entry.target_canonical and entry.target_canonical.strip())
        or any(variant.strip() for variant in entry.target_variants)
    )


def _entry_source_matches(entry: GlossaryEntry, source_text: str) -> bool:
    return any(
        _source_term_present(term, source_text)
        for term in (entry.source_canonical, *entry.aliases)
        if term.strip()
    )


def _source_term_present(term: str, source_text: str) -> bool:
    normalized_term = term.strip()
    pattern = re.escape(normalized_term)
    if normalized_term[0].isalnum():
        pattern = rf"(?<!\w){pattern}"
    if normalized_term[-1].isalnum():
        pattern = rf"{pattern}(?!\w)"
    return re.search(pattern, source_text, flags=re.IGNORECASE) is not None


def _prompt_context_entries(snapshot: GlossarySnapshot) -> tuple[dict[str, Any], ...]:
    return tuple(_prompt_context_entry(entry) for entry in snapshot.entries)


def _prompt_context_entry(entry: GlossaryEntry) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "category": str(entry.category),
        "layer": str(entry.layer),
        "status": str(entry.status),
        "source_canonical": entry.source_canonical,
        "target_canonical": entry.target_canonical,
        "aliases": list(entry.aliases),
        "target_variants": list(entry.target_variants),
        "forbidden_variants": list(entry.forbidden_variants),
        "confidence": entry.confidence,
        "strategy": str(entry.strategy),
        "grammatical_gender": str(entry.grammatical_gender),
        "morphology_notes": list(entry.morphology_notes),
        "profile_rule_ids": list(entry.profile_rule_ids),
    }


def _source_blocks_for_work_unit(
    work_unit: PersistentWorkUnit,
    source_text: str,
) -> tuple[FormatTextBlock, ...]:
    block_ids = work_unit.source_block_ids or (f"work-unit:{work_unit.sequence}:0",)
    parts = tuple(part for part in source_text.split("\n\n") if part)
    if len(parts) != len(block_ids):
        parts = (source_text,)
        block_ids = (block_ids[0],)
    return tuple(
        FormatTextBlock(
            index=index,
            source_block_id=block_id,
            text=parts[index],
            kind=TextBlockKind.PLAIN,
        )
        for index, block_id in enumerate(block_ids)
    )


def _prompt_tier(value: str) -> PromptTier:
    try:
        return PromptTier(value)
    except ValueError:
        return PromptTier.PLAIN


def _snapshot_id(
    work_unit: PersistentWorkUnit,
    source_character_count: int,
) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "job_id": work_unit.job_id,
                "work_unit_sequence": work_unit.sequence,
                "source_block_ids": list(work_unit.source_block_ids),
                "source_text_hash": work_unit.source_text_hash,
                "source_character_count": source_character_count,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:24]
    return f"persistent-epub-glossary-snapshot:v1:{digest}"


def _pressure_context(
    work_unit: PersistentWorkUnit,
    *,
    source_character_count: int,
    scanned_entry_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": PERSISTENT_EPUB_GLOSSARY_RESOLVER_SCHEMA_VERSION,
        "document_format": DocumentFormat.EPUB.value,
        "work_unit_sequence": work_unit.sequence,
        "source_block_count": len(work_unit.source_block_ids),
        "source_character_count": source_character_count,
        "scanned_entry_count": scanned_entry_count,
        "metadata_only": True,
        "raw_payload_included": False,
    }


def _runtime_integration_payload() -> dict[str, object]:
    return {
        "normal_translation_prompts_changed": False,
        "live_provider_calls_allowed": False,
        "durable_state_mutation_allowed": False,
        "cache_mutation_allowed": False,
        "fallback_action": "omit_glossary_prompt_context",
    }


def _fallback_reason_from_overlay_status(status: str) -> str:
    return f"persistent_epub_target_metadata_overlay_{_compact_reason(status)}"


def _normalized_document_kind(document_kind: str | None) -> str:
    return (document_kind or "Unknown").strip().lower() or "Unknown"


def _compact_reason(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        value = "persistent_epub_glossary_fallback"
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    return (
        re.sub(r"[^a-z0-9_]+", "_", normalized).strip("_")[:96]
        or "persistent_epub_glossary_fallback"
    )
