from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from translator_service.documents import DocumentFormat
from translator_service.format_adapters.contracts import FormatAdapterPlan
from translator_service.format_adapters.docx import plan_docx_translation
from translator_service.format_adapters.epub import plan_epub_translation
from translator_service.format_adapters.txt import plan_txt_translation
from translator_service.glossary_prepared_package import (
    GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
    GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
)
from translator_service.glossary_prepared_prep_service import (
    DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL,
    PreparedGlossaryPackagePrepRequest,
    PreparedGlossaryPrepService,
    PreparedGlossaryPrepServiceConfig,
)

GLOSSARY_RUNTIME_EFFECTIVENESS_AUDIT_SCHEMA_VERSION = (
    "glossary-runtime-effectiveness-audit-v1"
)
DEFAULT_PACKAGE_CAPS = (8, 12, 16, 24)


@dataclass(frozen=True)
class RuntimeGateVariant:
    name: str
    max_source_blocks: int | None
    max_source_characters: int | None


@dataclass(frozen=True)
class RuntimeEffectivenessAuditCase:
    input_path: Path
    document_kind: str
    target_language: str
    source_language: str = "en"
    translation_mode: str = "book_manuscript"
    input_id: str | None = None


DEFAULT_RUNTIME_GATE_VARIANTS = (
    RuntimeGateVariant(
        name="current_12_blocks_2400_chars",
        max_source_blocks=12,
        max_source_characters=2_400,
    ),
    RuntimeGateVariant(
        name="relaxed_24_blocks_4800_chars",
        max_source_blocks=24,
        max_source_characters=4_800,
    ),
    RuntimeGateVariant(
        name="headroom_only_4800_chars",
        max_source_blocks=None,
        max_source_characters=4_800,
    ),
    RuntimeGateVariant(
        name="source_match_first_no_source_gate",
        max_source_blocks=None,
        max_source_characters=None,
    ),
)


def default_runtime_effectiveness_audit_cases() -> tuple[
    RuntimeEffectivenessAuditCase,
    ...,
]:
    return (
        RuntimeEffectivenessAuditCase(
            input_path=Path("test_samples/glossary_adversarial_terms.en.txt"),
            document_kind=DocumentFormat.TXT.value,
            target_language="ru",
            input_id="glossary_adversarial_terms_txt_ru",
        ),
        RuntimeEffectivenessAuditCase(
            input_path=Path("test_samples/sample_book.en.txt"),
            document_kind=DocumentFormat.TXT.value,
            target_language="ru",
            input_id="sample_book_txt_ru",
        ),
        RuntimeEffectivenessAuditCase(
            input_path=Path("test_samples/gutenberg_time_machine_noimages.en.epub"),
            document_kind=DocumentFormat.EPUB.value,
            target_language="ru",
            input_id="gutenberg_time_machine_epub_ru",
        ),
    )


def audit_glossary_runtime_effectiveness(
    *,
    cases: Sequence[RuntimeEffectivenessAuditCase] | None = None,
    archive_dir: Path | None = None,
    package_caps: Sequence[int] = DEFAULT_PACKAGE_CAPS,
    gate_variants: Sequence[RuntimeGateVariant] = DEFAULT_RUNTIME_GATE_VARIANTS,
) -> dict[str, Any]:
    normalized_caps = _normalize_caps(package_caps)
    normalized_variants = tuple(gate_variants)
    audit_cases = tuple(cases) if cases is not None else (
        default_runtime_effectiveness_audit_cases()
    )
    case_reports = [
        _audit_package_cap(
            cap=cap,
            cases=audit_cases,
            gate_variants=normalized_variants,
        )
        for cap in normalized_caps
    ]
    archive_report = _audit_archive(
        archive_dir=archive_dir,
        package_caps=normalized_caps,
        gate_variants=normalized_variants,
    )
    return {
        "schema_version": GLOSSARY_RUNTIME_EFFECTIVENESS_AUDIT_SCHEMA_VERSION,
        "metadata_only": True,
        "raw_payload_included": False,
        "ordinary_artifact_safe": True,
        "runtime_behavior_changed": False,
        "live_provider_calls_made": False,
        "package_caps": list(normalized_caps),
        "runtime_gate_variants": [
            _gate_variant_payload(variant) for variant in normalized_variants
        ],
        "archive_observation": archive_report,
        "committed_fixture_cap_audit": case_reports,
        "recommendation": _recommendation(archive_report, case_reports),
    }


def serialize_runtime_effectiveness_audit(report: Mapping[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _audit_package_cap(
    *,
    cap: int,
    cases: Sequence[RuntimeEffectivenessAuditCase],
    gate_variants: Sequence[RuntimeGateVariant],
) -> dict[str, Any]:
    case_reports = [
        _audit_fixture_case(case, cap=cap, gate_variants=gate_variants)
        for case in cases
    ]
    totals = _fixture_totals(case_reports, gate_variants=gate_variants)
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "package_cap": cap,
        "estimated_editor_token_cap": _editor_token_cap_for_package_cap(cap),
        "case_count": len(case_reports),
        "totals": totals,
        "cases": case_reports,
    }


def _audit_fixture_case(
    case: RuntimeEffectivenessAuditCase,
    *,
    cap: int,
    gate_variants: Sequence[RuntimeGateVariant],
) -> dict[str, Any]:
    content = case.input_path.read_bytes()
    source_sha256 = hashlib.sha256(content).hexdigest()
    provider_called = False
    captured_packet: Mapping[str, Any] | None = None

    def provider(provider_request: Any) -> dict[str, Any]:
        nonlocal provider_called, captured_packet
        provider_called = True
        captured_packet = provider_request.packet
        return _fake_prepared_package_from_packet(provider_request.packet)

    config = PreparedGlossaryPrepServiceConfig(
        max_candidates=cap,
        max_estimated_editor_tokens=_editor_token_cap_for_package_cap(cap),
    )
    request = PreparedGlossaryPackagePrepRequest(
        user_telegram_id=0,
        file_name=case.input_path.name,
        document_kind=case.document_kind,
        source_language=case.source_language,
        target_language=case.target_language,
        translation_mode=case.translation_mode,
        glossary_mode="with_glossary",
        source_sha256=source_sha256,
        content=content,
    )
    attachment = PreparedGlossaryPrepService(
        provider=provider,
        config=config,
    ).prepare(request)
    plan = _build_plan(
        document_kind=case.document_kind,
        content=content,
        max_fragment_chars=config.max_fragment_chars,
        translation_mode=case.translation_mode,
    )
    entries = _prepared_entries_from_payload(attachment.payload)
    gate_reports = {
        variant.name: _simulate_runtime_gate(
            plan=plan,
            entries=entries,
            variant=variant,
        )
        for variant in gate_variants
    }
    metadata = dict(attachment.metadata)
    validation = metadata.get("validation")
    validation_metadata = dict(validation) if isinstance(validation, Mapping) else {}
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "input_id": case.input_id or case.input_path.name,
        "document_kind": case.document_kind,
        "source_language": case.source_language,
        "target_language": case.target_language,
        "source_sha256_short": source_sha256[:12],
        "unit_count": len(plan.units),
        "provider_called": provider_called,
        "prep_status": metadata.get("status", "Unknown"),
        "attachment_enabled": bool(attachment.enabled),
        "reason_codes": _string_list(attachment.reason_codes),
        "selected_candidate_count": _int_metadata(
            metadata.get("selected_candidate_count")
        ),
        "packet_candidate_count": _packet_candidate_count(captured_packet),
        "package_validation_status": validation_metadata.get("status", "not_run"),
        "ready_entry_count": _int_metadata(
            validation_metadata.get("ready_entry_count")
        ),
        "package_entry_count": len(entries),
        "package_entry_signatures": [_entry_signature(entry) for entry in entries],
        "runtime_gate_simulation": gate_reports,
    }


def _audit_archive(
    *,
    archive_dir: Path | None,
    package_caps: Sequence[int],
    gate_variants: Sequence[RuntimeGateVariant],
) -> dict[str, Any]:
    if archive_dir is None:
        return _archive_unavailable("archive_dir_not_supplied")
    diagnostics_path = archive_dir / "glossary_runtime_diagnostics.json"
    if not diagnostics_path.exists():
        return _archive_unavailable("glossary_runtime_diagnostics_missing")
    try:
        diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _archive_unavailable("glossary_runtime_diagnostics_unreadable")
    if not isinstance(diagnostics, Mapping):
        return _archive_unavailable("glossary_runtime_diagnostics_invalid")

    adapter_events = _mapping_sequence(diagnostics.get("adapter_events"))
    prompt_context_events = _mapping_sequence(diagnostics.get("prompt_context_events"))
    prepared_events = _mapping_sequence(diagnostics.get("prepared_package_events"))
    summary = diagnostics.get("summary")
    summary_mapping = dict(summary) if isinstance(summary, Mapping) else {}
    preflights = [_preflight_from_event(event) for event in adapter_events]
    preflights = [item for item in preflights if item]
    fallback_counts = Counter(
        reason
        for reason in (_fallback_reason_from_event(event) for event in adapter_events)
        if reason
    )
    prompt_omission_counts = Counter(
        reason
        for event in prompt_context_events
        for reason in _string_list(event.get("omission_reasons"))
    )
    attached_entry_counts = sorted(
        {
            _int_metadata(package.get("entry_count"))
            for package in (_prepared_from_event(event) for event in prepared_events)
            if package
        }
    )
    gate_observations = {
        variant.name: _archive_gate_observation(
            preflights=preflights,
            variant=variant,
        )
        for variant in gate_variants
    }
    rendered_count = _int_metadata(summary_mapping.get("rendered_prompt_context_count"))
    included_count = _int_metadata(
        summary_mapping.get("prompt_context_included_event_count")
    )
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "status": "available",
        "archive_id": _archive_id(archive_dir),
        "document_kind": str(diagnostics.get("document_kind") or "Unknown"),
        "source_language": str(diagnostics.get("source_language") or "Unknown"),
        "target_language": str(diagnostics.get("target_language") or "Unknown"),
        "adapter_event_count": len(adapter_events),
        "prepared_package_event_count": len(prepared_events),
        "prompt_context_event_count": len(prompt_context_events),
        "prompt_context_included_event_count": included_count,
        "rendered_prompt_context_count": rendered_count,
        "compliance_summary_count": _int_metadata(
            summary_mapping.get("compliance_summary_count")
        ),
        "prepared_package_statuses": _string_list(
            summary_mapping.get("prepared_package_statuses")
        ),
        "attachment_statuses": _string_list(summary_mapping.get("attachment_statuses")),
        "cache_policy_behaviors": _string_list(
            summary_mapping.get("cache_policy_behaviors")
        ),
        "fallback_reason_counts": dict(sorted(fallback_counts.items())),
        "prompt_context_omission_reason_counts": dict(
            sorted(prompt_omission_counts.items())
        ),
        "attached_entry_counts": attached_entry_counts,
        "zero_render_observed": rendered_count == 0 and included_count == 0,
        "package_cap_comparison": [
            _archive_package_cap_observation(cap, attached_entry_counts)
            for cap in package_caps
        ],
        "runtime_gate_observations": gate_observations,
        "unknowns": _archive_unknowns(attached_entry_counts),
    }


def _simulate_runtime_gate(
    *,
    plan: FormatAdapterPlan,
    entries: Sequence[Mapping[str, Any]],
    variant: RuntimeGateVariant,
) -> dict[str, Any]:
    eligible_sequences: list[int] = []
    source_present_sequences: list[int] = []
    applicable_sequences: list[int] = []
    over_gate_sequences: list[int] = []
    applicable_entry_hit_count = 0
    for unit in plan.units:
        source_text = unit.source_text
        source_block_count = len(unit.source_block_ids)
        source_character_count = len(source_text)
        source_present_entries = [
            entry for entry in entries if _entry_source_matches(entry, source_text)
        ]
        if source_present_entries:
            source_present_sequences.append(unit.sequence)
        if not _unit_under_gate(
            source_block_count=source_block_count,
            source_character_count=source_character_count,
            variant=variant,
        ):
            over_gate_sequences.append(unit.sequence)
            continue
        eligible_sequences.append(unit.sequence)
        applicable_entries = [
            entry
            for entry in source_present_entries
            if _entry_has_target_metadata(entry) and _entry_refs_match(entry, unit)
        ]
        if applicable_entries:
            applicable_sequences.append(unit.sequence)
            applicable_entry_hit_count += len(applicable_entries)
    unit_count = len(plan.units)
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "eligible_unit_count": len(eligible_sequences),
        "eligible_unit_rate": _rate(len(eligible_sequences), unit_count),
        "source_present_unit_count": len(source_present_sequences),
        "source_present_unit_rate": _rate(len(source_present_sequences), unit_count),
        "applicable_unit_count": len(applicable_sequences),
        "applicable_unit_rate": _rate(len(applicable_sequences), unit_count),
        "applicable_entry_hit_count": applicable_entry_hit_count,
        "over_source_gate_unit_count": len(over_gate_sequences),
        "context_render_upper_bound_count": len(applicable_sequences),
        "first_eligible_unit_sequences": eligible_sequences[:20],
        "first_applicable_unit_sequences": applicable_sequences[:20],
    }


def _archive_gate_observation(
    *,
    preflights: Sequence[Mapping[str, Any]],
    variant: RuntimeGateVariant,
) -> dict[str, Any]:
    eligible_sequences = []
    eligible_event_indexes = []
    over_gate = []
    sequence_available = False
    for index, preflight in enumerate(preflights):
        sequence = preflight.get("work_unit_sequence")
        if isinstance(sequence, int):
            sequence_available = True
        source_block_count = _int_metadata(preflight.get("source_block_count"))
        source_character_count = _int_metadata(
            preflight.get("source_character_count")
        )
        if _unit_under_gate(
            source_block_count=source_block_count,
            source_character_count=source_character_count,
            variant=variant,
        ):
            if isinstance(sequence, int):
                eligible_sequences.append(sequence)
            else:
                eligible_event_indexes.append(index + 1)
        else:
            over_gate.append(index + 1)
    eligible_count = len(eligible_sequences) + len(eligible_event_indexes)
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "observable_unit_count": len(preflights),
        "work_unit_sequence_available": sequence_available,
        "eligible_unit_count": eligible_count,
        "eligible_unit_rate": _rate(eligible_count, len(preflights)),
        "over_source_gate_unit_count": len(over_gate),
        "first_eligible_work_unit_sequences": eligible_sequences[:20],
        "first_eligible_event_indexes": eligible_event_indexes[:20],
        "context_render_upper_bound_count": "Unknown",
        "unknown_reason": (
            "prepared_package_entries_and_source_refs_not_present_in_archive_sidecar"
        ),
    }


def _fake_prepared_package_from_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    target_language = str(packet.get("target_language") or "Unknown")
    entries = []
    for index, candidate in enumerate(_mapping_sequence(packet.get("candidates"))):
        target = f"audit-target-{index + 1}"
        entries.append(
            {
                "source_entry_id": candidate.get("source_entry_id", "Unknown"),
                "source_canonical": candidate.get("source_canonical", "Unknown"),
                "aliases": _string_list(candidate.get("aliases")),
                "evidence_refs": _string_list(candidate.get("evidence_refs")),
                "source_unit_refs": _int_list(candidate.get("source_unit_refs")),
                "source_block_refs": _string_list(candidate.get("source_block_refs")),
                "target_canonical": target,
                "target_variants": [target],
                "forbidden_variants": [],
                "strategy": "metadata_only_runtime_effectiveness_fake_provider",
                "confidence": 0.9,
                "needs_review": False,
                "reason_codes": [],
            }
        )
    return {
        "schema_version": GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
        "package_id": f"prepared:runtime-effectiveness-audit:{target_language}",
        "source_language": packet.get("source_language", "Unknown"),
        "target_language": target_language,
        "glossary_mode": "with_glossary",
        "provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
        "provider_model": packet.get(
            "provider_model",
            DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL,
        ),
        "provider_run_id": "provider-run:runtime-effectiveness-audit-fake",
        "source_document_fingerprint": packet.get(
            "source_document_fingerprint",
            "Unknown",
        ),
        "candidate_selector_signature": packet.get(
            "candidate_selector_signature",
            "Unknown",
        ),
        "owner_approved": True,
        "entries": entries,
    }


def _build_plan(
    *,
    document_kind: str,
    content: bytes,
    max_fragment_chars: int,
    translation_mode: str | None,
) -> FormatAdapterPlan:
    document_format = DocumentFormat(document_kind)
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
    raise ValueError("glossary_runtime_effectiveness_document_kind_unsupported")


def _prepared_entries_from_payload(
    payload: object | None,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(payload, Mapping):
        return ()
    return tuple(_mapping_sequence(payload.get("entries")))


def _fixture_totals(
    cases: Sequence[Mapping[str, Any]],
    *,
    gate_variants: Sequence[RuntimeGateVariant],
) -> dict[str, Any]:
    selected_candidate_count = sum(
        _int_metadata(case.get("selected_candidate_count")) for case in cases
    )
    ready_entry_count = sum(
        _int_metadata(case.get("ready_entry_count")) for case in cases
    )
    reason_codes: list[str] = []
    for case in cases:
        reason_codes.extend(_string_list(case.get("reason_codes")))
    gate_totals = {}
    for variant in gate_variants:
        applicable = 0
        upper_bound = 0
        eligible = 0
        source_present = 0
        unit_count = 0
        for case in cases:
            simulation = case.get("runtime_gate_simulation")
            if not isinstance(simulation, Mapping):
                continue
            gate = simulation.get(variant.name)
            if not isinstance(gate, Mapping):
                continue
            unit_count += _int_metadata(case.get("unit_count"))
            eligible += _int_metadata(gate.get("eligible_unit_count"))
            source_present += _int_metadata(gate.get("source_present_unit_count"))
            applicable += _int_metadata(gate.get("applicable_unit_count"))
            upper_bound += _int_metadata(gate.get("context_render_upper_bound_count"))
        gate_totals[variant.name] = {
            "metadata_only": True,
            "raw_payload_included": False,
            "eligible_unit_count": eligible,
            "eligible_unit_rate": _rate(eligible, unit_count),
            "source_present_unit_count": source_present,
            "source_present_unit_rate": _rate(source_present, unit_count),
            "applicable_unit_count": applicable,
            "applicable_unit_rate": _rate(applicable, unit_count),
            "context_render_upper_bound_count": upper_bound,
        }
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "selected_candidate_count": selected_candidate_count,
        "ready_entry_count": ready_entry_count,
        "ready_case_count": sum(1 for case in cases if case.get("attachment_enabled")),
        "provider_called_case_count": sum(
            1 for case in cases if case.get("provider_called")
        ),
        "reason_codes": list(dict.fromkeys(reason_codes)),
        "runtime_gate_totals": gate_totals,
    }


def _recommendation(
    archive_report: Mapping[str, Any],
    case_reports: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    zero_render = archive_report.get("zero_render_observed") is True
    current_fixture_applicable = _cap_current_fixture_applicable(case_reports)
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "status": "recommend_follow_up_threshold_rebalance",
        "summary": (
            "Relax runtime applicability before increasing package caps broadly."
            if zero_render and current_fixture_applicable > 0
            else "Use #672/#674 to choose defaults from the recorded metadata."
        ),
        "suggested_next_issue": (
            "#672 for runtime applicability; #674 for cap rebalance"
        ),
        "observed_zero_render": zero_render,
        "current_fixture_applicable_unit_count": current_fixture_applicable,
        "human_decisions": ["TBD"],
    }


def _cap_current_fixture_applicable(case_reports: Sequence[Mapping[str, Any]]) -> int:
    for cap_report in case_reports:
        if _int_metadata(cap_report.get("package_cap")) != DEFAULT_PACKAGE_CAPS[0]:
            continue
        totals = cap_report.get("totals")
        if not isinstance(totals, Mapping):
            continue
        gate_totals = totals.get("runtime_gate_totals")
        if not isinstance(gate_totals, Mapping):
            continue
        current = gate_totals.get("current_12_blocks_2400_chars")
        if isinstance(current, Mapping):
            return _int_metadata(current.get("applicable_unit_count"))
    return 0


def _unit_under_gate(
    *,
    source_block_count: int,
    source_character_count: int,
    variant: RuntimeGateVariant,
) -> bool:
    if (
        variant.max_source_blocks is not None
        and source_block_count > variant.max_source_blocks
    ):
        return False
    return not (
        variant.max_source_characters is not None
        and source_character_count > variant.max_source_characters
    )


def _entry_has_target_metadata(entry: Mapping[str, Any]) -> bool:
    target_canonical = str(entry.get("target_canonical") or "").strip()
    return bool(target_canonical or _string_list(entry.get("target_variants")))


def _entry_refs_match(entry: Mapping[str, Any], unit: Any) -> bool:
    unit_refs = tuple(_int_list(entry.get("source_unit_refs")))
    block_refs = tuple(_string_list(entry.get("source_block_refs")))
    if not unit_refs and not block_refs:
        return True
    if unit.sequence in unit_refs:
        return True
    unit_block_ids = frozenset(str(item) for item in unit.source_block_ids)
    return any(block_id in unit_block_ids for block_id in block_refs)


def _entry_source_matches(entry: Mapping[str, Any], source_text: str) -> bool:
    return any(
        _source_term_present(term, source_text)
        for term in (
            str(entry.get("source_canonical") or ""),
            *_string_list(entry.get("aliases")),
        )
        if term.strip()
    )


def _source_term_present(term: str, source_text: str) -> bool:
    normalized_term = term.strip()
    if not normalized_term:
        return False
    pattern = re.escape(normalized_term)
    if normalized_term[0].isalnum():
        pattern = rf"(?<!\w){pattern}"
    if normalized_term[-1].isalnum():
        pattern = rf"{pattern}(?!\w)"
    return re.search(pattern, source_text, flags=re.IGNORECASE) is not None


def _entry_signature(entry: Mapping[str, Any]) -> str:
    payload = {
        "source_entry_id": entry.get("source_entry_id", "Unknown"),
        "source_canonical": entry.get("source_canonical", "Unknown"),
        "aliases": _string_list(entry.get("aliases")),
        "target_metadata": bool(_entry_has_target_metadata(entry)),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"entry-signature:{digest}"


def _archive_unavailable(reason_code: str) -> dict[str, Any]:
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "status": "unavailable",
        "reason_codes": [reason_code],
        "unknowns": [reason_code],
    }


def _archive_package_cap_observation(
    cap: int,
    attached_entry_counts: Sequence[int],
) -> dict[str, Any]:
    attached_entry_count = max(attached_entry_counts) if attached_entry_counts else 0
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "package_cap": cap,
        "attached_entry_count": attached_entry_count,
        "within_cap": (
            attached_entry_count <= cap if attached_entry_count else "Unknown"
        ),
        "would_truncate_attached_package": (
            attached_entry_count > cap if attached_entry_count else "Unknown"
        ),
        "candidate_pool_entry_count": "Unknown",
        "cap_effect_on_rendered_context_count": "Unknown",
        "unknown_reason": (
            "archive_sidecar_has_package_metadata_but_not_raw_entries_or_candidate_pool"
        ),
    }


def _archive_unknowns(attached_entry_counts: Sequence[int]) -> list[str]:
    unknowns = [
        "prepared_package_entries_absent_from_archive_sidecar",
        "upstream_candidate_pool_absent_from_archive_sidecar",
        "package_cap_effect_on_real_archive_rendering_unknown",
    ]
    if not attached_entry_counts:
        unknowns.append("attached_entry_count_unknown")
    return unknowns


def _preflight_from_event(event: Mapping[str, Any]) -> Mapping[str, Any] | None:
    direct = event.get("battle_test_preflight")
    if isinstance(direct, Mapping):
        return direct
    payload = event.get("payload")
    if isinstance(payload, Mapping) and isinstance(
        payload.get("battle_test_preflight"),
        Mapping,
    ):
        return payload["battle_test_preflight"]
    return None


def _fallback_reason_from_event(event: Mapping[str, Any]) -> str | None:
    direct = event.get("fallback_reason")
    if isinstance(direct, str) and direct:
        return direct
    payload = event.get("payload")
    if isinstance(payload, Mapping):
        fallback = payload.get("fallback_reason")
        if isinstance(fallback, str) and fallback:
            return fallback
    return None


def _prepared_from_event(event: Mapping[str, Any]) -> Mapping[str, Any] | None:
    direct = event.get("prepared_package")
    if isinstance(direct, Mapping):
        return direct
    if "entry_count" in event or "status" in event:
        return event
    payload = event.get("payload")
    if isinstance(payload, Mapping) and isinstance(
        payload.get("prepared_package"),
        Mapping,
    ):
        return payload["prepared_package"]
    return None


def _gate_variant_payload(variant: RuntimeGateVariant) -> dict[str, Any]:
    return {
        "name": variant.name,
        "max_source_blocks": (
            variant.max_source_blocks
            if variant.max_source_blocks is not None
            else "unbounded"
        ),
        "max_source_characters": (
            variant.max_source_characters
            if variant.max_source_characters is not None
            else "unbounded"
        ),
    }


def _editor_token_cap_for_package_cap(cap: int) -> int:
    return max(2_400, cap * 300)


def _archive_id(archive_dir: Path) -> str:
    return f"archive:{hashlib.sha256(str(archive_dir).encode()).hexdigest()[:12]}"


def _normalize_caps(caps: Sequence[int]) -> tuple[int, ...]:
    normalized = []
    for cap in caps:
        if isinstance(cap, bool):
            continue
        try:
            value = int(cap)
        except (TypeError, ValueError):
            continue
        if value > 0:
            normalized.append(value)
    return tuple(dict.fromkeys(normalized)) or DEFAULT_PACKAGE_CAPS


def _packet_candidate_count(packet: Mapping[str, Any] | None) -> int:
    if not isinstance(packet, Mapping):
        return 0
    return len(_mapping_sequence(packet.get("candidates")))


def _mapping_sequence(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _int_list(value: Any) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result = []
    for item in value:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            result.append(item)
    return result


def _int_metadata(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    return 0


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)
