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
from translator_service.glossary_contracts import (
    GlossaryEntry,
    GlossaryEntryCategory,
    GlossaryEntryStatus,
    GlossaryEvidenceRef,
    GlossaryEvidenceSurface,
    GlossaryEvidenceType,
    GlossaryGender,
    GlossaryLayer,
    GlossarySnapshot,
    glossary_snapshot_signature,
)
from translator_service.glossary_prepared_package import (
    PreparedGlossaryEntry,
    PreparedGlossaryPackage,
    validate_prepared_glossary_package,
)
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
PERSISTENT_GLOSSARY_RESOLVER_SCHEMA_VERSION = "persistent-glossary-runtime-resolver-v1"
PERSISTENT_GLOSSARY_RESOLVER_ADAPTER_VERSION = (
    "persistent-work-unit-glossary-adapter-v1"
)
DEFAULT_PERSISTENT_GLOSSARY_MAX_SOURCE_BLOCKS = 12
DEFAULT_PERSISTENT_GLOSSARY_MAX_SOURCE_CHARACTERS = 2_400
DEFAULT_PERSISTENT_GLOSSARY_MAX_SELECTED_ENTRIES = 32
DEFAULT_PERSISTENT_GLOSSARY_SELECTION_MAX_PROMPT_TOKENS = 320
DEFAULT_PERSISTENT_GLOSSARY_SELECTION_MAX_ENTRIES = 12
DEFAULT_PERSISTENT_GLOSSARY_SELECTION_MAX_DIAGNOSTIC_ENTRIES = 2
_SUPPORTED_PERSISTENT_GLOSSARY_DOCUMENT_FORMATS = frozenset(
    (
        DocumentFormat.TXT.value,
        DocumentFormat.DOCX.value,
        DocumentFormat.EPUB.value,
    )
)
_RISKY_ALIAS_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9']*")
_RISKY_ALIAS_TOKENS = frozenset(
    {
        "a",
        "about",
        "all",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "he",
        "her",
        "him",
        "his",
        "i",
        "in",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "she",
        "so",
        "that",
        "the",
        "their",
        "them",
        "then",
        "they",
        "this",
        "to",
        "us",
        "we",
        "with",
        "you",
        "your",
    }
)


@dataclass(frozen=True)
class _PreparedEntrySourceMatch:
    matched: bool
    canonical_present: bool
    safe_alias_present: bool
    risky_alias_only: bool


@dataclass(frozen=True)
class PersistentGlossaryResolverConfig:
    enabled: bool = False
    owner_battle_test_enabled: bool = False
    prompt_rehearsal_enabled: bool = True
    max_source_blocks: int = DEFAULT_PERSISTENT_GLOSSARY_MAX_SOURCE_BLOCKS
    max_source_characters: int = DEFAULT_PERSISTENT_GLOSSARY_MAX_SOURCE_CHARACTERS
    max_selected_entries: int = DEFAULT_PERSISTENT_GLOSSARY_MAX_SELECTED_ENTRIES
    selection_budget: GlossarySelectionBudget = field(
        default_factory=lambda: GlossarySelectionBudget(
            max_prompt_tokens=DEFAULT_PERSISTENT_GLOSSARY_SELECTION_MAX_PROMPT_TOKENS,
            max_entries=DEFAULT_PERSISTENT_GLOSSARY_SELECTION_MAX_ENTRIES,
            max_diagnostic_entries=(
                DEFAULT_PERSISTENT_GLOSSARY_SELECTION_MAX_DIAGNOSTIC_ENTRIES
            ),
        )
    )
    prompt_context_config: GlossaryPromptContextConfig = field(
        default_factory=GlossaryPromptContextConfig
    )
    reducer_caps: GlossaryCandidateReducerCaps = DEFAULT_GLOSSARY_CANDIDATE_REDUCER_CAPS
    target_metadata_overlay_config: GlossaryTargetMetadataOverlayConfig = field(
        default_factory=lambda: GlossaryTargetMetadataOverlayConfig(enabled=True)
    )
    automatic_glossary_enabled: bool | None = None
    prompt_context_enabled: bool | None = None

    def __post_init__(self) -> None:
        automatic_glossary_enabled = (
            self.automatic_glossary_enabled
            if self.automatic_glossary_enabled is not None
            else self.owner_battle_test_enabled
        )
        prompt_context_enabled = (
            self.prompt_context_enabled
            if self.prompt_context_enabled is not None
            else self.prompt_rehearsal_enabled
        )
        object.__setattr__(
            self,
            "automatic_glossary_enabled",
            bool(automatic_glossary_enabled),
        )
        object.__setattr__(
            self,
            "owner_battle_test_enabled",
            bool(automatic_glossary_enabled),
        )
        object.__setattr__(
            self,
            "prompt_context_enabled",
            bool(prompt_context_enabled),
        )
        object.__setattr__(
            self,
            "prompt_rehearsal_enabled",
            bool(prompt_context_enabled),
        )


PersistentEpubGlossaryResolverConfig = PersistentGlossaryResolverConfig


def build_persistent_glossary_runtime_hook_resolver(
    *,
    source_text_loader: Callable[[PersistentWorkUnit], str],
    target_metadata_overlay_payload: Mapping[str, Any] | None,
    document_kind_resolver: Callable[[PersistentWorkUnit], str | None],
    config: PersistentGlossaryResolverConfig | None = None,
) -> Callable[[PersistentWorkUnit], GlossaryRuntimeAdapterHookConfig | None]:
    config = config or PersistentGlossaryResolverConfig()

    def resolve(work_unit: PersistentWorkUnit) -> GlossaryRuntimeAdapterHookConfig:
        try:
            source_text = source_text_loader(work_unit)
        except Exception:
            return _fallback_hook("persistent_glossary_source_text_unavailable")
        return build_persistent_glossary_runtime_hook(
            work_unit=work_unit,
            source_text=source_text,
            target_metadata_overlay_payload=target_metadata_overlay_payload,
            document_kind=document_kind_resolver(work_unit),
            config=config,
        )

    return resolve


def build_persistent_epub_glossary_runtime_hook_resolver(
    *,
    source_text_loader: Callable[[PersistentWorkUnit], str],
    target_metadata_overlay_payload: Mapping[str, Any] | None,
    document_kind_resolver: Callable[[PersistentWorkUnit], str | None] | None = None,
    config: PersistentGlossaryResolverConfig | None = None,
) -> Callable[[PersistentWorkUnit], GlossaryRuntimeAdapterHookConfig | None]:
    config = config or PersistentGlossaryResolverConfig()

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


def build_persistent_glossary_runtime_hook(
    *,
    work_unit: PersistentWorkUnit,
    source_text: str,
    target_metadata_overlay_payload: Mapping[str, Any] | None,
    document_kind: str | None,
    config: PersistentGlossaryResolverConfig | None = None,
) -> GlossaryRuntimeAdapterHookConfig:
    return _build_persistent_glossary_runtime_hook(
        work_unit=work_unit,
        source_text=source_text,
        target_metadata_overlay_payload=target_metadata_overlay_payload,
        document_kind=document_kind,
        config=config or PersistentGlossaryResolverConfig(),
        schema_version=PERSISTENT_GLOSSARY_RESOLVER_SCHEMA_VERSION,
        adapter_version=PERSISTENT_GLOSSARY_RESOLVER_ADAPTER_VERSION,
        reason_prefix="persistent_glossary",
        disabled_reason_code="persistent_glossary_resolver_disabled",
        supported_document_formats=_SUPPORTED_PERSISTENT_GLOSSARY_DOCUMENT_FORMATS,
        quality_route="automatic_glossary",
    )


def build_persistent_epub_glossary_runtime_hook(
    *,
    work_unit: PersistentWorkUnit,
    source_text: str,
    target_metadata_overlay_payload: Mapping[str, Any] | None,
    document_kind: str | None = DocumentFormat.EPUB.value,
    config: PersistentGlossaryResolverConfig | None = None,
) -> GlossaryRuntimeAdapterHookConfig:
    return _build_persistent_glossary_runtime_hook(
        work_unit=work_unit,
        source_text=source_text,
        target_metadata_overlay_payload=target_metadata_overlay_payload,
        document_kind=document_kind,
        config=config or PersistentGlossaryResolverConfig(),
        schema_version=PERSISTENT_EPUB_GLOSSARY_RESOLVER_SCHEMA_VERSION,
        adapter_version=PERSISTENT_EPUB_GLOSSARY_RESOLVER_ADAPTER_VERSION,
        reason_prefix="persistent_epub",
        disabled_reason_code="persistent_epub_glossary_resolver_disabled",
        supported_document_formats=frozenset((DocumentFormat.EPUB.value,)),
        quality_route="owner_battle_test",
    )


def _build_persistent_glossary_runtime_hook(
    *,
    work_unit: PersistentWorkUnit,
    source_text: str,
    target_metadata_overlay_payload: Mapping[str, Any] | None,
    document_kind: str | None,
    config: PersistentGlossaryResolverConfig,
    schema_version: str,
    adapter_version: str,
    reason_prefix: str,
    disabled_reason_code: str,
    supported_document_formats: frozenset[str],
    quality_route: str,
) -> GlossaryRuntimeAdapterHookConfig:
    if not config.enabled:
        return _fallback_hook(disabled_reason_code)
    if not config.automatic_glossary_enabled:
        return _fallback_hook(f"{reason_prefix}_owner_battle_test_not_enabled")
    document_format = _document_format_for_kind(document_kind)
    if (
        document_format is None
        or document_format.value not in supported_document_formats
    ):
        return _fallback_hook(f"{reason_prefix}_unsupported_document_kind")
    if not isinstance(target_metadata_overlay_payload, Mapping):
        return _fallback_hook(f"{reason_prefix}_target_metadata_missing")

    source_blocks = _source_blocks_for_work_unit(work_unit, source_text)
    source_character_count = sum(len(block.text) for block in source_blocks)
    if not source_blocks or source_character_count == 0:
        return _fallback_hook(f"{reason_prefix}_source_text_empty")
    if len(source_blocks) > config.max_source_blocks:
        return _fallback_hook(f"{reason_prefix}_source_block_limit_exceeded")
    if source_character_count > config.max_source_characters:
        return _fallback_hook(f"{reason_prefix}_source_character_limit_exceeded")

    unit = FormatTranslationUnit(
        sequence=work_unit.sequence,
        blocks=tuple(source_blocks),
        prompt_tier=_prompt_tier(work_unit.prompt_tier),
    )
    plan = FormatAdapterPlan(
        document_format=document_format,
        adapter_version=adapter_version,
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
                schema_version=schema_version,
                document_format=document_format,
                source_character_count=source_character_count,
                scanned_entry_count=len(scanned.entries),
            ),
            caps=config.reducer_caps,
        )
    except Exception:
        return _fallback_hook(f"{reason_prefix}_local_glossary_planning_failed")

    if not reduction.retained_entry_ids:
        return _fallback_hook(f"{reason_prefix}_no_retained_glossary_entries")

    overlay_result = apply_glossary_target_metadata_overlay(
        reduction.retained_snapshot,
        target_metadata_overlay_payload,
        target_language=work_unit.target_language,
        config=config.target_metadata_overlay_config,
    )
    if overlay_result.status != "applied":
        return _fallback_hook(
            _fallback_reason_from_overlay_status(
                overlay_result.status,
                reason_prefix=reason_prefix,
            ),
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
        return _fallback_hook(f"{reason_prefix}_no_useful_glossary_entries")

    prompt_context_result = format_glossary_prompt_context(
        _prompt_context_entries(overlay_result.snapshot),
        selected_entry_ids=useful_entry_ids,
        config=config.prompt_context_config,
    )
    if not prompt_context_result.included_entries:
        return _fallback_hook(f"{reason_prefix}_prompt_context_budget_exhausted")

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
        quality_route=quality_route,
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
            "schema_version": schema_version,
            "enabled": True,
            "status": "planned",
            "fallback_reason": "none",
            "source_language": work_unit.source_language,
            "target_language": work_unit.target_language,
            "document_format": document_format.value,
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
            "resolver_caps": _resolver_caps_metadata(config),
            "runtime_integration": _runtime_integration_payload(),
        },
        max_selected_entries=config.max_selected_entries,
        prompt_context_enabled=config.prompt_context_enabled,
        prompt_context_entries=_prompt_context_entries(overlay_result.snapshot),
        prompt_context_config=config.prompt_context_config,
        automatic_glossary_enabled=config.automatic_glossary_enabled,
        automatic_glossary_max_source_blocks=config.max_source_blocks,
        automatic_glossary_max_source_characters=config.max_source_characters,
    )


def build_persistent_glossary_runtime_hook_from_prepared_package(
    *,
    work_unit: PersistentWorkUnit,
    source_text: str,
    prepared_package_payload: object | None,
    document_kind: str | None,
    config: PersistentGlossaryResolverConfig | None = None,
) -> GlossaryRuntimeAdapterHookConfig:
    return _build_persistent_glossary_runtime_hook_from_prepared_package(
        work_unit=work_unit,
        source_text=source_text,
        prepared_package_payload=prepared_package_payload,
        document_kind=document_kind,
        config=config
        or PersistentGlossaryResolverConfig(
            enabled=True,
            automatic_glossary_enabled=True,
        ),
        reason_prefix="persistent_glossary",
    )


def build_persistent_epub_glossary_runtime_hook_from_prepared_package(
    *,
    work_unit: PersistentWorkUnit,
    source_text: str,
    prepared_package_payload: object | None,
    document_kind: str | None = DocumentFormat.EPUB.value,
    config: PersistentGlossaryResolverConfig | None = None,
) -> GlossaryRuntimeAdapterHookConfig:
    return _build_persistent_glossary_runtime_hook_from_prepared_package(
        work_unit=work_unit,
        source_text=source_text,
        prepared_package_payload=prepared_package_payload,
        document_kind=document_kind,
        config=config
        or PersistentGlossaryResolverConfig(
            enabled=True,
            automatic_glossary_enabled=True,
        ),
        reason_prefix="persistent_epub",
    )


def _build_persistent_glossary_runtime_hook_from_prepared_package(
    *,
    work_unit: PersistentWorkUnit,
    source_text: str,
    prepared_package_payload: object | None,
    document_kind: str | None,
    config: PersistentGlossaryResolverConfig,
    reason_prefix: str,
) -> GlossaryRuntimeAdapterHookConfig:
    if not isinstance(prepared_package_payload, Mapping):
        reason_code = (
            "prepared_glossary_package_missing"
            if prepared_package_payload is None
            else "prepared_glossary_package_invalid"
        )
        fallback_reason = (
            f"{reason_prefix}_prepared_package_missing"
            if prepared_package_payload is None
            else f"{reason_prefix}_prepared_package_invalid"
        )
        return _fallback_hook(
            fallback_reason,
            prepared_package_metadata={
                "metadata_only": True,
                "raw_payload_included": False,
                "status": "invalid",
                "reason_codes": [reason_code],
                "target_language": work_unit.target_language,
            },
        )

    validation = validate_prepared_glossary_package(
        prepared_package_payload,
        target_language=work_unit.target_language,
    )
    prepared_metadata = validation.metadata
    if not validation.ready or validation.package is None:
        return _fallback_hook(
            _prepared_package_fallback_reason(
                validation.reason_codes,
                reason_prefix=reason_prefix,
            ),
            prepared_package_metadata=prepared_metadata,
        )

    hook = _build_persistent_glossary_runtime_hook_from_prepared_entries(
        work_unit=work_unit,
        source_text=source_text,
        prepared_package=validation.package,
        document_kind=document_kind,
        config=config,
        reason_prefix=reason_prefix,
        schema_version=(
            PERSISTENT_EPUB_GLOSSARY_RESOLVER_SCHEMA_VERSION
            if reason_prefix == "persistent_epub"
            else PERSISTENT_GLOSSARY_RESOLVER_SCHEMA_VERSION
        ),
        adapter_version=(
            PERSISTENT_EPUB_GLOSSARY_RESOLVER_ADAPTER_VERSION
            if reason_prefix == "persistent_epub"
            else PERSISTENT_GLOSSARY_RESOLVER_ADAPTER_VERSION
        ),
        supported_document_formats=(
            frozenset((DocumentFormat.EPUB.value,))
            if reason_prefix == "persistent_epub"
            else _SUPPORTED_PERSISTENT_GLOSSARY_DOCUMENT_FORMATS
        ),
        quality_route=(
            "owner_battle_test"
            if reason_prefix == "persistent_epub"
            else "automatic_glossary"
        ),
    )
    return _hook_with_prepared_package_metadata(hook, prepared_metadata)


def _build_persistent_glossary_runtime_hook_from_prepared_entries(
    *,
    work_unit: PersistentWorkUnit,
    source_text: str,
    prepared_package: PreparedGlossaryPackage,
    document_kind: str | None,
    config: PersistentGlossaryResolverConfig,
    reason_prefix: str,
    schema_version: str,
    adapter_version: str,
    supported_document_formats: frozenset[str],
    quality_route: str,
) -> GlossaryRuntimeAdapterHookConfig:
    if not config.enabled:
        return _fallback_hook(f"{reason_prefix}_resolver_disabled")
    if not config.automatic_glossary_enabled:
        return _fallback_hook(f"{reason_prefix}_owner_battle_test_not_enabled")
    document_format = _document_format_for_kind(document_kind)
    if (
        document_format is None
        or document_format.value not in supported_document_formats
    ):
        return _fallback_hook(f"{reason_prefix}_unsupported_document_kind")

    source_blocks = _source_blocks_for_work_unit(work_unit, source_text)
    source_character_count = sum(len(block.text) for block in source_blocks)
    if not source_blocks or source_character_count == 0:
        return _fallback_hook(f"{reason_prefix}_source_text_empty")

    unit = FormatTranslationUnit(
        sequence=work_unit.sequence,
        blocks=tuple(source_blocks),
        prompt_tier=_prompt_tier(work_unit.prompt_tier),
    )
    plan = FormatAdapterPlan(
        document_format=document_format,
        adapter_version=adapter_version,
        units=(unit,),
        character_count=source_character_count,
        estimated_input_tokens=max(1, source_character_count // 4),
    )
    package_snapshot, bridge_metadata = _prepared_package_snapshot_for_work_unit(
        prepared_package,
        work_unit=work_unit,
        source_text=unit.source_text,
        snapshot_id=_snapshot_id(work_unit, source_character_count),
    )
    if not package_snapshot.entries:
        return _hook_with_plan_metadata(
            _fallback_hook(f"{reason_prefix}_prepared_package_no_applicable_entries"),
            "prepared_package_runtime_bridge",
            bridge_metadata,
        )

    try:
        profile = detect_book_profile(
            plan,
            source_language=work_unit.source_language,
            target_language=work_unit.target_language,
            glossary_snapshot=package_snapshot,
        )
    except Exception:
        return _fallback_hook(f"{reason_prefix}_local_glossary_planning_failed")

    selection = select_glossary_subset_for_work_unit(
        unit,
        package_snapshot,
        budget=config.selection_budget,
        profile_rule_ids=tuple(rule.rule_id for rule in profile.rules),
    )
    selection_payload = glossary_selection_metadata_payload(selection)
    useful_entry_ids = _useful_selected_entry_ids(
        selection_payload.get("selected_entries", ()),
        package_snapshot,
        source_text=unit.source_text,
    )
    if not useful_entry_ids:
        return _hook_with_plan_metadata(
            _fallback_hook(f"{reason_prefix}_no_useful_glossary_entries"),
            "prepared_package_runtime_bridge",
            bridge_metadata,
        )

    prompt_context_result = format_glossary_prompt_context(
        _prompt_context_entries(package_snapshot),
        selected_entry_ids=useful_entry_ids,
        config=config.prompt_context_config,
    )
    if not prompt_context_result.included_entries:
        return _hook_with_plan_metadata(
            _fallback_hook(f"{reason_prefix}_prompt_context_budget_exhausted"),
            "prepared_package_runtime_bridge",
            bridge_metadata,
        )

    policy = build_translation_policy(
        text=unit.source_text,
        source_language=work_unit.source_language,
        target_language=work_unit.target_language,
        prompt_tier=unit.prompt_tier,
    )
    selected_rule_ids = tuple(rule.rule_id for rule in profile.rules)
    snapshot = build_translation_contract_snapshot(
        policy,
        glossary_snapshot=package_snapshot,
        profile_detection=profile,
        selected_rule_ids=selected_rule_ids,
        selection_policy_version=GLOSSARY_SELECTION_POLICY_VERSION,
        quality_route=quality_route,
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
    package_snapshot_signature = glossary_snapshot_signature(package_snapshot)
    return GlossaryRuntimeAdapterHookConfig(
        enabled=True,
        glossary_plan={
            "schema_version": schema_version,
            "enabled": True,
            "status": "planned",
            "fallback_reason": "none",
            "source_language": work_unit.source_language,
            "target_language": work_unit.target_language,
            "document_format": document_format.value,
            "translation_mode": "book",
            "source_glossary_signature": package_snapshot_signature,
            "glossary_signature": snapshot.glossary_signature,
            "reduced_glossary_signature": package_snapshot_signature,
            "profile_signature": snapshot.profile_signature,
            "translation_snapshot_signature": (
                translation_contract_snapshot_signature(snapshot)
            ),
            "aggregate_selection_signature": selection_payload[
                "selection_signature"
            ],
            "policy_signature_context": policy_context,
            "selected_rule_ids": list(selected_rule_ids),
            "prepared_package_runtime_bridge": bridge_metadata,
            "work_unit_plans": [work_unit_plan],
            "resolver_caps": _resolver_caps_metadata(config),
            "runtime_integration": _runtime_integration_payload(),
        },
        max_selected_entries=config.max_selected_entries,
        prompt_context_enabled=config.prompt_context_enabled,
        prompt_context_entries=_prompt_context_entries(package_snapshot),
        prompt_context_config=config.prompt_context_config,
        automatic_glossary_enabled=config.automatic_glossary_enabled,
        automatic_glossary_max_source_blocks=config.max_source_blocks,
        automatic_glossary_max_source_characters=config.max_source_characters,
    )


def _fallback_hook(
    fallback_reason: str,
    *,
    prepared_package_metadata: Mapping[str, Any] | None = None,
) -> GlossaryRuntimeAdapterHookConfig:
    hook = build_fallback_glossary_runtime_hook(
        fallback_reason=_compact_reason(fallback_reason),
    )
    if prepared_package_metadata is None:
        return hook
    return _hook_with_prepared_package_metadata(hook, prepared_package_metadata)


def _hook_with_prepared_package_metadata(
    hook: GlossaryRuntimeAdapterHookConfig,
    prepared_package_metadata: Mapping[str, Any],
) -> GlossaryRuntimeAdapterHookConfig:
    glossary_plan = dict(hook.glossary_plan or {})
    glossary_plan["prepared_package"] = dict(prepared_package_metadata)
    return GlossaryRuntimeAdapterHookConfig(
        enabled=hook.enabled,
        glossary_plan=glossary_plan,
        max_selected_entries=hook.max_selected_entries,
        prompt_context_enabled=hook.prompt_context_enabled,
        prompt_context_entries=hook.prompt_context_entries,
        prompt_context_config=hook.prompt_context_config,
        automatic_glossary_enabled=hook.automatic_glossary_enabled,
        automatic_glossary_max_source_blocks=hook.automatic_glossary_max_source_blocks,
        automatic_glossary_max_source_characters=(
            hook.automatic_glossary_max_source_characters
        ),
    )


def _hook_with_plan_metadata(
    hook: GlossaryRuntimeAdapterHookConfig,
    key: str,
    metadata: Mapping[str, Any],
) -> GlossaryRuntimeAdapterHookConfig:
    glossary_plan = dict(hook.glossary_plan or {})
    glossary_plan[key] = dict(metadata)
    return GlossaryRuntimeAdapterHookConfig(
        enabled=hook.enabled,
        glossary_plan=glossary_plan,
        max_selected_entries=hook.max_selected_entries,
        prompt_context_enabled=hook.prompt_context_enabled,
        prompt_context_entries=hook.prompt_context_entries,
        prompt_context_config=hook.prompt_context_config,
        automatic_glossary_enabled=hook.automatic_glossary_enabled,
        automatic_glossary_max_source_blocks=hook.automatic_glossary_max_source_blocks,
        automatic_glossary_max_source_characters=(
            hook.automatic_glossary_max_source_characters
        ),
    )


def _prepared_package_fallback_reason(
    reason_codes: Sequence[str],
    *,
    reason_prefix: str,
) -> str:
    if "prepared_glossary_package_target_mismatch" in reason_codes:
        return f"{reason_prefix}_prepared_package_target_mismatch"
    if "prepared_glossary_package_needs_review" in reason_codes:
        return f"{reason_prefix}_prepared_package_not_ready"
    if any(
        "secret" in reason_code or "raw" in reason_code
        for reason_code in reason_codes
    ):
        return f"{reason_prefix}_prepared_package_rejected"
    return f"{reason_prefix}_prepared_package_invalid"


def _prepared_package_snapshot_for_work_unit(
    package: PreparedGlossaryPackage,
    *,
    work_unit: PersistentWorkUnit,
    source_text: str,
    snapshot_id: str,
) -> tuple[GlossarySnapshot, dict[str, Any]]:
    entries: list[GlossaryEntry] = []
    evidence_refs: list[GlossaryEvidenceRef] = []
    seen_evidence_ids: set[str] = set()
    counts = {
        "entry_count": len(package.entries),
        "applicable_entry_count": 0,
        "target_metadata_missing_count": 0,
        "source_ref_absent_count": 0,
        "source_ref_match_count": 0,
        "source_ref_mismatch_count": 0,
        "source_term_missing_count": 0,
        "source_canonical_match_count": 0,
        "source_safe_alias_match_count": 0,
        "source_risky_alias_only_count": 0,
    }
    for entry_index, prepared_entry in enumerate(package.entries):
        if not _prepared_entry_has_target_metadata(prepared_entry):
            counts["target_metadata_missing_count"] += 1
            continue
        source_match = _prepared_entry_source_match(prepared_entry, source_text)
        if not source_match.matched:
            counts["source_term_missing_count"] += 1
            continue
        if source_match.risky_alias_only:
            counts["source_risky_alias_only_count"] += 1
            continue
        if source_match.canonical_present:
            counts["source_canonical_match_count"] += 1
        if source_match.safe_alias_present:
            counts["source_safe_alias_match_count"] += 1
        if not prepared_entry.source_unit_refs and not prepared_entry.source_block_refs:
            counts["source_ref_absent_count"] += 1
        elif _prepared_entry_refs_match(prepared_entry, work_unit):
            counts["source_ref_match_count"] += 1
        else:
            counts["source_ref_mismatch_count"] += 1
        entry_evidence_ids: list[str] = []
        for evidence_index, evidence_id in enumerate(prepared_entry.evidence_refs):
            unique_id = _unique_prepared_evidence_id(
                evidence_id,
                entry_index=entry_index,
                evidence_index=evidence_index,
                seen_evidence_ids=seen_evidence_ids,
            )
            entry_evidence_ids.append(unique_id)
            evidence_refs.append(
                GlossaryEvidenceRef(
                    evidence_id=unique_id,
                    evidence_type=GlossaryEvidenceType.SOURCE_ANCHOR,
                    unit_sequence=work_unit.sequence,
                    source_block_id=_prepared_evidence_source_block_id(
                        prepared_entry,
                        work_unit=work_unit,
                        evidence_index=evidence_index,
                    ),
                    source_scope="work_unit",
                    surface=GlossaryEvidenceSurface.BODY,
                    occurrence_count=1,
                    raw_excerpt=None,
                )
            )
        entries.append(
            GlossaryEntry(
                entry_id=prepared_entry.source_entry_id,
                category=GlossaryEntryCategory.TERM,
                layer=GlossaryLayer.HARD,
                status=GlossaryEntryStatus.VALIDATOR_ACCEPTED,
                source_canonical=prepared_entry.source_canonical,
                aliases=prepared_entry.aliases,
                target_canonical=prepared_entry.target_canonical,
                target_variants=prepared_entry.target_variants,
                forbidden_variants=prepared_entry.forbidden_variants,
                evidence_refs=tuple(entry_evidence_ids),
                confidence=prepared_entry.confidence,
                strategy=prepared_entry.strategy,
                grammatical_gender=GlossaryGender.UNKNOWN,
                morphology_notes=(),
                profile_rule_ids=("prepared-glossary-package:v1",),
            )
        )
    counts["applicable_entry_count"] = len(entries)
    snapshot = GlossarySnapshot(
        snapshot_id=snapshot_id,
        source_language=package.source_language,
        target_language=package.target_language,
        entries=tuple(entries),
        evidence=tuple(evidence_refs),
        policy_version="prepared-glossary-package-runtime-bridge-v1",
        profile_signature="book-profile:prepared-package",
    )
    metadata = {
        "schema_version": "prepared-glossary-package-runtime-bridge-v1",
        "status": "applied" if entries else "skipped",
        "reason_codes": _prepared_package_runtime_bridge_reason_codes(
            entries=entries,
            source_risky_alias_only_count=counts["source_risky_alias_only_count"],
        ),
        **counts,
        "metadata_only": True,
        "raw_payload_included": False,
        "source_refs_required_when_present": False,
        "source_refs_used_as_diagnostics": True,
        "source_presence_primary_applicability_signal": True,
        "risky_alias_only_skipped": counts["source_risky_alias_only_count"] > 0,
        "normal_translation_prompts_changed": False,
        "live_provider_calls_allowed": False,
        "durable_state_mutation_allowed": False,
        "cache_mutation_allowed": False,
    }
    return snapshot, metadata


def _prepared_package_runtime_bridge_reason_codes(
    *,
    entries: Sequence[GlossaryEntry],
    source_risky_alias_only_count: int,
) -> list[str]:
    reason_codes: list[str] = []
    if not entries:
        reason_codes.append("prepared_package_runtime_bridge_no_applicable_entries")
    if source_risky_alias_only_count > 0:
        reason_codes.append("prepared_package_runtime_bridge_risky_alias_only")
    return reason_codes


def _prepared_entry_has_target_metadata(entry: PreparedGlossaryEntry) -> bool:
    return bool(
        (entry.target_canonical and entry.target_canonical.strip())
        or any(variant.strip() for variant in entry.target_variants)
    )


def _prepared_entry_refs_match(
    entry: PreparedGlossaryEntry,
    work_unit: PersistentWorkUnit,
) -> bool:
    has_unit_refs = bool(entry.source_unit_refs)
    has_block_refs = bool(entry.source_block_refs)
    if not has_unit_refs and not has_block_refs:
        return True
    if work_unit.sequence in entry.source_unit_refs:
        return True
    work_unit_block_ids = frozenset(work_unit.source_block_ids)
    return any(block_id in work_unit_block_ids for block_id in entry.source_block_refs)


def _prepared_entry_source_matches(
    entry: PreparedGlossaryEntry,
    source_text: str,
) -> bool:
    return _prepared_entry_source_match(entry, source_text).matched


def _prepared_entry_source_match(
    entry: PreparedGlossaryEntry,
    source_text: str,
) -> _PreparedEntrySourceMatch:
    canonical_present = _source_term_present(entry.source_canonical, source_text)
    alias_matches = tuple(
        alias
        for alias in entry.aliases
        if alias.strip() and _source_term_present(alias, source_text)
    )
    safe_alias_present = any(
        not _source_alias_is_risky(
            alias,
            source_canonical=entry.source_canonical,
        )
        for alias in alias_matches
    )
    risky_alias_only = (
        bool(alias_matches)
        and not canonical_present
        and not safe_alias_present
    )
    return _PreparedEntrySourceMatch(
        matched=canonical_present or safe_alias_present or risky_alias_only,
        canonical_present=canonical_present,
        safe_alias_present=safe_alias_present,
        risky_alias_only=risky_alias_only,
    )


def _source_alias_is_risky(alias: str, *, source_canonical: str = "") -> bool:
    normalized = alias.strip()
    if len(normalized) < 4:
        return True
    tokens = tuple(
        match.group(0).casefold()
        for match in _RISKY_ALIAS_TOKEN_RE.finditer(normalized)
    )
    if tokens and all(token in _RISKY_ALIAS_TOKENS for token in tokens):
        return True
    if len(tokens) == 1 and normalized.islower() and len(normalized) <= 5:
        return True
    return _source_alias_is_ambiguous_canonical_token(
        tokens,
        source_canonical=source_canonical,
    )


def _source_alias_is_ambiguous_canonical_token(
    alias_tokens: Sequence[str],
    *,
    source_canonical: str,
) -> bool:
    if len(alias_tokens) != 1:
        return False
    if not source_canonical or not any(char.isspace() for char in source_canonical):
        return False
    canonical_tokens = tuple(
        match.group(0).casefold()
        for match in _RISKY_ALIAS_TOKEN_RE.finditer(source_canonical)
    )
    if len(canonical_tokens) <= 1:
        return False
    # Local applicability is limited to the current work unit: when the
    # canonical term is absent, a single canonical component (for example a
    # first name from a full-name term) is not enough evidence to inject the
    # full prepared hard glossary entry for this unit.
    return alias_tokens[0] in canonical_tokens


def _unique_prepared_evidence_id(
    evidence_id: str,
    *,
    entry_index: int,
    evidence_index: int,
    seen_evidence_ids: set[str],
) -> str:
    if evidence_id not in seen_evidence_ids:
        seen_evidence_ids.add(evidence_id)
        return evidence_id
    unique_id = f"{evidence_id}:prepared-{entry_index}-{evidence_index}"
    while unique_id in seen_evidence_ids:
        unique_id = f"{unique_id}-1"
    seen_evidence_ids.add(unique_id)
    return unique_id


def _prepared_evidence_source_block_id(
    entry: PreparedGlossaryEntry,
    *,
    work_unit: PersistentWorkUnit,
    evidence_index: int,
) -> str:
    work_unit_block_ids = tuple(work_unit.source_block_ids)
    matching_block_refs = tuple(
        block_id
        for block_id in entry.source_block_refs
        if block_id in work_unit_block_ids
    )
    if matching_block_refs:
        return matching_block_refs[min(evidence_index, len(matching_block_refs) - 1)]
    if work_unit_block_ids:
        return work_unit_block_ids[min(evidence_index, len(work_unit_block_ids) - 1)]
    return f"work-unit:{work_unit.sequence}:0"


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
    schema_version: str,
    document_format: DocumentFormat,
    source_character_count: int,
    scanned_entry_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "document_format": document_format.value,
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


def _resolver_caps_metadata(config: PersistentGlossaryResolverConfig) -> dict[str, Any]:
    return {
        "max_source_blocks": config.max_source_blocks,
        "max_source_characters": config.max_source_characters,
        "max_selected_entries": config.max_selected_entries,
        "selection_budget": {
            "max_prompt_tokens": config.selection_budget.max_prompt_tokens,
            "max_entries": config.selection_budget.max_entries,
            "max_diagnostic_entries": config.selection_budget.max_diagnostic_entries,
        },
        "prompt_context": {
            "max_entries": config.prompt_context_config.max_entries,
            "max_prompt_tokens": config.prompt_context_config.max_prompt_tokens,
            "max_characters": config.prompt_context_config.max_characters,
            "max_entry_characters": (
                config.prompt_context_config.max_entry_characters
            ),
            "max_field_characters": (
                config.prompt_context_config.max_field_characters
            ),
            "max_aliases": config.prompt_context_config.max_aliases,
            "max_target_variants": config.prompt_context_config.max_target_variants,
            "max_forbidden_variants": (
                config.prompt_context_config.max_forbidden_variants
            ),
            "max_morphology_notes": (
                config.prompt_context_config.max_morphology_notes
            ),
            "max_profile_rule_ids": (
                config.prompt_context_config.max_profile_rule_ids
            ),
            "include_terminology_policy_metadata": (
                config.prompt_context_config.include_terminology_policy_metadata
            ),
        },
        "candidate_reducer": {
            "max_editor_entries": config.reducer_caps.max_editor_entries,
            "max_diagnostic_entries": config.reducer_caps.max_diagnostic_entries,
            "max_estimated_editor_tokens": (
                config.reducer_caps.max_estimated_editor_tokens
            ),
            "min_editor_score": config.reducer_caps.min_editor_score,
            "min_diagnostic_score": config.reducer_caps.min_diagnostic_score,
        },
        "target_metadata_overlay": {
            "enabled": config.target_metadata_overlay_config.enabled,
            "max_entries_per_target": (
                config.target_metadata_overlay_config.max_entries_per_target
            ),
            "max_aliases": config.target_metadata_overlay_config.max_aliases,
            "max_target_variants": (
                config.target_metadata_overlay_config.max_target_variants
            ),
            "max_forbidden_variants": (
                config.target_metadata_overlay_config.max_forbidden_variants
            ),
            "max_morphology_notes": (
                config.target_metadata_overlay_config.max_morphology_notes
            ),
            "max_field_chars": config.target_metadata_overlay_config.max_field_chars,
        },
    }


def _fallback_reason_from_overlay_status(
    status: str,
    *,
    reason_prefix: str,
) -> str:
    return f"{reason_prefix}_target_metadata_overlay_{_compact_reason(status)}"


def _normalized_document_kind(document_kind: str | None) -> str:
    return (document_kind or "Unknown").strip().lower() or "Unknown"


def _document_format_for_kind(document_kind: str | None) -> DocumentFormat | None:
    normalized = _normalized_document_kind(document_kind)
    try:
        return DocumentFormat(normalized)
    except ValueError:
        return None


def _compact_reason(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        value = "persistent_glossary_fallback"
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    return (
        re.sub(r"[^a-z0-9_]+", "_", normalized).strip("_")[:96]
        or "persistent_glossary_fallback"
    )
