from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from translator_service.book_profile import (
    BookProfileDetection,
    BookProfileKind,
    detect_book_profile,
    validate_book_profile_detection,
)
from translator_service.format_adapters.contracts import FormatAdapterPlan
from translator_service.glossary_contracts import (
    GlossarySnapshot,
    glossary_snapshot_signature,
    validate_glossary_snapshot,
)
from translator_service.glossary_editor_packets import (
    DEFAULT_GLOSSARY_EDITOR_PACKET_BUDGET,
    GlossaryEditorPacketBudget,
    GlossaryEditorPacketBuildResult,
    build_glossary_editor_packets,
)
from translator_service.glossary_scanner import scan_glossary_candidates
from translator_service.translation_contract_snapshot import (
    book_profile_detection_signature,
)

GLOSSARY_PRESSURE_REPORT_SCHEMA_VERSION = "glossary-pressure-report-v1"


class GlossaryPressureFindingSeverity(StrEnum):
    WARNING = "warning"
    BLOCKER = "blocker"


class GlossaryPressureFindingCode(StrEnum):
    TOO_MANY_CANDIDATES = "too_many_candidates"
    TOO_MANY_PACKETS = "too_many_packets"
    TOTAL_TOKEN_PRESSURE = "total_token_pressure"
    PACKET_TOKEN_PRESSURE = "packet_token_pressure"
    PROFILE_UNCERTAIN = "profile_uncertain"
    PROFILE_SECONDARY_SIGNALS = "profile_secondary_signals"
    MISSING_EVIDENCE = "missing_evidence"
    INVALID_GLOSSARY = "invalid_glossary"
    INVALID_PROFILE = "invalid_profile"
    PACKET_BUILD_FAILED = "packet_build_failed"
    PACKET_DEGRADED = "packet_degraded"
    SKIPPED_ENTRIES = "skipped_entries"


@dataclass(frozen=True)
class GlossaryPressureThresholds:
    max_candidate_count: int = 160
    max_packet_count: int = 12
    max_total_reserved_prompt_tokens: int = 30000
    max_packet_budget_utilization: float = 0.9
    min_profile_confidence: float = 0.55
    max_degraded_packets: int = 0
    max_skipped_entries: int = 0


DEFAULT_GLOSSARY_PRESSURE_THRESHOLDS = GlossaryPressureThresholds()


@dataclass(frozen=True)
class GlossaryPressureFixtureMetadata:
    fixture_id: str = "Unknown"
    rights_basis: str = "Unknown"
    usage_scope: str = "local_metadata_only"
    raw_text_policy: str = "excluded_from_report"


@dataclass(frozen=True)
class GlossaryPressurePlanStats:
    document_format: str
    adapter_version: str
    unit_count: int
    block_count: int
    character_count: int
    estimated_input_tokens: int
    prompt_tier_counts: Mapping[str, int]
    block_kind_counts: Mapping[str, int]


@dataclass(frozen=True)
class GlossaryPressureCandidateStats:
    candidate_count: int
    evidence_count: int
    category_counts: Mapping[str, int]
    status_counts: Mapping[str, int]
    layer_counts: Mapping[str, int]
    confidence_bucket_counts: Mapping[str, int]
    entries_missing_evidence_count: int
    missing_evidence_ref_count: int
    max_evidence_refs_per_entry: int
    glossary_signature: str


@dataclass(frozen=True)
class GlossaryPressureProfileSummary:
    profile_id: str
    profile_signature: str
    primary_profile: str
    secondary_profiles: tuple[str, ...]
    document_type: str
    confidence: float
    evidence_count: int
    rule_count: int
    domain_hints: tuple[str, ...]
    uncertainty_note_count: int


@dataclass(frozen=True)
class GlossaryPressurePacketStats:
    packet_count: int
    ready_packet_count: int
    degraded_packet_count: int
    skipped_entry_count: int
    entry_refs_in_packets: int
    total_estimated_prompt_tokens: int
    total_reserved_prompt_tokens: int
    max_estimated_prompt_tokens: int
    max_reserved_prompt_tokens: int
    max_packet_budget_utilization: float
    status_counts: Mapping[str, int]
    degradation_counts: Mapping[str, int]
    packet_build_signature: str | None
    packet_policy_version: str | None
    packet_build_error: str | None = None


@dataclass(frozen=True)
class GlossaryPressureFinding:
    severity: GlossaryPressureFindingSeverity
    code: GlossaryPressureFindingCode
    actual: int | float | bool | str | None
    threshold: int | float | str | None
    message: str


@dataclass(frozen=True)
class GlossaryPressureReport:
    schema_version: str
    fixture_metadata: GlossaryPressureFixtureMetadata
    source_language: str
    target_language: str
    plan: GlossaryPressurePlanStats
    candidates: GlossaryPressureCandidateStats
    profile: GlossaryPressureProfileSummary
    packets: GlossaryPressurePacketStats
    findings: tuple[GlossaryPressureFinding, ...]
    report_signature: str

    @property
    def blocker_count(self) -> int:
        return sum(
            1
            for finding in self.findings
            if finding.severity is GlossaryPressureFindingSeverity.BLOCKER
        )


def build_glossary_pressure_report(
    plan: FormatAdapterPlan,
    *,
    source_language: str,
    target_language: str,
    fixture_metadata: GlossaryPressureFixtureMetadata | None = None,
    glossary_snapshot: GlossarySnapshot | None = None,
    profile_detection: BookProfileDetection | None = None,
    packet_budget: GlossaryEditorPacketBudget = DEFAULT_GLOSSARY_EDITOR_PACKET_BUDGET,
    thresholds: GlossaryPressureThresholds = DEFAULT_GLOSSARY_PRESSURE_THRESHOLDS,
) -> GlossaryPressureReport:
    """Build local metadata-only glossary pressure diagnostics.

    The report aggregates adapter-plan, scanner, profile, and packetizer
    metadata. It intentionally excludes source text, raw excerpts, prompts,
    provider responses, translated text, secrets, and semantic truth claims.
    """

    glossary = glossary_snapshot or scan_glossary_candidates(
        plan,
        source_language=source_language,
        target_language=target_language,
    )
    profile = profile_detection or detect_book_profile(
        plan,
        source_language=source_language,
        target_language=target_language,
        glossary_snapshot=glossary,
    )
    packet_result, packet_error = _try_build_packets(
        glossary,
        profile,
        packet_budget=packet_budget,
    )
    candidates = _candidate_stats(glossary)
    profile_summary = _profile_summary(profile)
    packets = _packet_stats(packet_result, packet_error=packet_error)
    findings = _findings(
        glossary,
        profile,
        candidates=candidates,
        packets=packets,
        thresholds=thresholds,
    )
    report_without_signature = {
        "schema_version": GLOSSARY_PRESSURE_REPORT_SCHEMA_VERSION,
        "fixture_metadata": _fixture_metadata_payload(
            fixture_metadata or GlossaryPressureFixtureMetadata()
        ),
        "source_language": source_language,
        "target_language": target_language,
        "plan": _plan_stats_payload(_plan_stats(plan)),
        "candidates": _candidate_stats_payload(candidates),
        "profile": _profile_summary_payload(profile_summary),
        "packets": _packet_stats_payload(packets),
        "findings": [_finding_payload(finding) for finding in findings],
    }
    return GlossaryPressureReport(
        schema_version=GLOSSARY_PRESSURE_REPORT_SCHEMA_VERSION,
        fixture_metadata=fixture_metadata or GlossaryPressureFixtureMetadata(),
        source_language=source_language,
        target_language=target_language,
        plan=_plan_stats(plan),
        candidates=candidates,
        profile=profile_summary,
        packets=packets,
        findings=findings,
        report_signature=(
            "glossary-pressure-report:v1:"
            f"{_payload_digest(report_without_signature)}"
        ),
    )


def glossary_pressure_report_payload(
    report: GlossaryPressureReport,
) -> dict[str, Any]:
    return {
        "schema_version": report.schema_version,
        "report_signature": report.report_signature,
        "source_language": report.source_language,
        "target_language": report.target_language,
        "blocker_count": report.blocker_count,
        "fixture_metadata": _fixture_metadata_payload(report.fixture_metadata),
        "plan": _plan_stats_payload(report.plan),
        "candidates": _candidate_stats_payload(report.candidates),
        "profile": _profile_summary_payload(report.profile),
        "packets": _packet_stats_payload(report.packets),
        "findings": [_finding_payload(finding) for finding in report.findings],
    }


def serialize_glossary_pressure_report(report: GlossaryPressureReport) -> str:
    return json.dumps(
        glossary_pressure_report_payload(report),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _try_build_packets(
    glossary: GlossarySnapshot,
    profile: BookProfileDetection,
    *,
    packet_budget: GlossaryEditorPacketBudget,
) -> tuple[GlossaryEditorPacketBuildResult | None, str | None]:
    try:
        return (
            build_glossary_editor_packets(
                glossary,
                profile,
                budget=packet_budget,
            ),
            None,
        )
    except ValueError:
        return None, "invalid_inputs"


def _plan_stats(plan: FormatAdapterPlan) -> GlossaryPressurePlanStats:
    return GlossaryPressurePlanStats(
        document_format=plan.document_format.value,
        adapter_version=plan.adapter_version,
        unit_count=len(plan.units),
        block_count=sum(len(unit.blocks) for unit in plan.units),
        character_count=plan.character_count,
        estimated_input_tokens=plan.estimated_input_tokens,
        prompt_tier_counts=_sorted_counter(
            _enum_value(unit.prompt_tier) for unit in plan.units
        ),
        block_kind_counts=_sorted_counter(
            _enum_value(block.kind) for unit in plan.units for block in unit.blocks
        ),
    )


def _candidate_stats(glossary: GlossarySnapshot) -> GlossaryPressureCandidateStats:
    evidence_ids = {evidence.evidence_id for evidence in glossary.evidence}
    missing_refs = [
        evidence_ref
        for entry in glossary.entries
        for evidence_ref in entry.evidence_refs
        if evidence_ref not in evidence_ids
    ]
    entries_missing_evidence = sum(
        1
        for entry in glossary.entries
        if not entry.evidence_refs
        or any(evidence_ref not in evidence_ids for evidence_ref in entry.evidence_refs)
    )
    return GlossaryPressureCandidateStats(
        candidate_count=len(glossary.entries),
        evidence_count=len(glossary.evidence),
        category_counts=_sorted_counter(
            _enum_value(entry.category) for entry in glossary.entries
        ),
        status_counts=_sorted_counter(
            _enum_value(entry.status) for entry in glossary.entries
        ),
        layer_counts=_sorted_counter(
            _enum_value(entry.layer) for entry in glossary.entries
        ),
        confidence_bucket_counts=_confidence_bucket_counts(glossary),
        entries_missing_evidence_count=entries_missing_evidence,
        missing_evidence_ref_count=len(set(missing_refs)),
        max_evidence_refs_per_entry=max(
            (len(entry.evidence_refs) for entry in glossary.entries),
            default=0,
        ),
        glossary_signature=glossary_snapshot_signature(glossary),
    )


def _profile_summary(
    detection: BookProfileDetection,
) -> GlossaryPressureProfileSummary:
    profile = detection.profile
    return GlossaryPressureProfileSummary(
        profile_id=profile.profile_id,
        profile_signature=book_profile_detection_signature(detection),
        primary_profile=_enum_value(profile.primary_profile),
        secondary_profiles=tuple(
            sorted(_enum_value(profile) for profile in profile.secondary_profiles)
        ),
        document_type=_enum_value(profile.document_type),
        confidence=round(float(profile.confidence), 4),
        evidence_count=len(profile.evidence_refs),
        rule_count=len(detection.rules),
        domain_hints=tuple(sorted(str(hint) for hint in profile.domain_hints)),
        uncertainty_note_count=len(profile.uncertainty_notes),
    )


def _packet_stats(
    result: GlossaryEditorPacketBuildResult | None,
    *,
    packet_error: str | None,
) -> GlossaryPressurePacketStats:
    if result is None:
        return GlossaryPressurePacketStats(
            packet_count=0,
            ready_packet_count=0,
            degraded_packet_count=0,
            skipped_entry_count=0,
            entry_refs_in_packets=0,
            total_estimated_prompt_tokens=0,
            total_reserved_prompt_tokens=0,
            max_estimated_prompt_tokens=0,
            max_reserved_prompt_tokens=0,
            max_packet_budget_utilization=0.0,
            status_counts={},
            degradation_counts={},
            packet_build_signature=None,
            packet_policy_version=None,
            packet_build_error=packet_error,
        )
    packets = result.packets
    max_reserved_limit = max(
        (packet.max_reserved_prompt_tokens for packet in packets),
        default=0,
    )
    max_reserved = max((packet.reserved_prompt_tokens for packet in packets), default=0)
    return GlossaryPressurePacketStats(
        packet_count=len(packets),
        ready_packet_count=sum(
            1 for packet in packets if _enum_value(packet.status) == "ready"
        ),
        degraded_packet_count=sum(
            1 for packet in packets if _enum_value(packet.status) == "degraded"
        ),
        skipped_entry_count=len(result.skipped_entries),
        entry_refs_in_packets=sum(len(packet.entries) for packet in packets),
        total_estimated_prompt_tokens=sum(
            packet.estimated_prompt_tokens for packet in packets
        ),
        total_reserved_prompt_tokens=sum(
            packet.reserved_prompt_tokens for packet in packets
        ),
        max_estimated_prompt_tokens=max(
            (packet.estimated_prompt_tokens for packet in packets),
            default=0,
        ),
        max_reserved_prompt_tokens=max_reserved,
        max_packet_budget_utilization=_rate(max_reserved, max_reserved_limit),
        status_counts=_sorted_counter(_enum_value(packet.status) for packet in packets),
        degradation_counts=_sorted_counter(
            _enum_value(degradation.reason)
            for packet in packets
            for degradation in packet.degradations
        ),
        packet_build_signature=result.build_signature,
        packet_policy_version=result.policy_version,
        packet_build_error=None,
    )


def _findings(
    glossary: GlossarySnapshot,
    profile: BookProfileDetection,
    *,
    candidates: GlossaryPressureCandidateStats,
    packets: GlossaryPressurePacketStats,
    thresholds: GlossaryPressureThresholds,
) -> tuple[GlossaryPressureFinding, ...]:
    findings: list[GlossaryPressureFinding] = []
    glossary_result = validate_glossary_snapshot(glossary)
    profile_result = validate_book_profile_detection(profile)
    if not glossary_result.valid:
        findings.append(
            _finding(
                GlossaryPressureFindingSeverity.BLOCKER,
                GlossaryPressureFindingCode.INVALID_GLOSSARY,
                len(glossary_result.issues),
                0,
                "Glossary snapshot validation issues block pressure readiness.",
            )
        )
    if not profile_result.valid:
        findings.append(
            _finding(
                GlossaryPressureFindingSeverity.BLOCKER,
                GlossaryPressureFindingCode.INVALID_PROFILE,
                len(profile_result.issues),
                0,
                "Book profile validation issues block pressure readiness.",
            )
        )
    if candidates.candidate_count > thresholds.max_candidate_count:
        findings.append(
            _finding(
                GlossaryPressureFindingSeverity.BLOCKER,
                GlossaryPressureFindingCode.TOO_MANY_CANDIDATES,
                candidates.candidate_count,
                thresholds.max_candidate_count,
                "Wide scan produced more candidates than the advisory editor cap.",
            )
        )
    if candidates.missing_evidence_ref_count:
        findings.append(
            _finding(
                GlossaryPressureFindingSeverity.BLOCKER,
                GlossaryPressureFindingCode.MISSING_EVIDENCE,
                candidates.missing_evidence_ref_count,
                0,
                "Candidate evidence references must resolve before editor use.",
            )
        )
    if packets.packet_count > thresholds.max_packet_count:
        findings.append(
            _finding(
                GlossaryPressureFindingSeverity.BLOCKER,
                GlossaryPressureFindingCode.TOO_MANY_PACKETS,
                packets.packet_count,
                thresholds.max_packet_count,
                "Packet count is too high for the advisory provider retry shape.",
            )
        )
    if (
        packets.total_reserved_prompt_tokens
        > thresholds.max_total_reserved_prompt_tokens
    ):
        findings.append(
            _finding(
                GlossaryPressureFindingSeverity.BLOCKER,
                GlossaryPressureFindingCode.TOTAL_TOKEN_PRESSURE,
                packets.total_reserved_prompt_tokens,
                thresholds.max_total_reserved_prompt_tokens,
                "Total reserved prompt tokens exceed the advisory pressure cap.",
            )
        )
    if packets.max_packet_budget_utilization > thresholds.max_packet_budget_utilization:
        findings.append(
            _finding(
                GlossaryPressureFindingSeverity.WARNING,
                GlossaryPressureFindingCode.PACKET_TOKEN_PRESSURE,
                packets.max_packet_budget_utilization,
                thresholds.max_packet_budget_utilization,
                "At least one packet is close to its local reserved-token budget.",
            )
        )
    if profile.profile.confidence < thresholds.min_profile_confidence or _enum_value(
        profile.profile.primary_profile
    ) in {BookProfileKind.UNKNOWN.value, BookProfileKind.MIXED_UNKNOWN.value}:
        findings.append(
            _finding(
                GlossaryPressureFindingSeverity.WARNING,
                GlossaryPressureFindingCode.PROFILE_UNCERTAIN,
                round(float(profile.profile.confidence), 4),
                thresholds.min_profile_confidence,
                "Profile confidence is uncertain and must not be treated as truth.",
            )
        )
    if profile.profile.secondary_profiles:
        findings.append(
            _finding(
                GlossaryPressureFindingSeverity.WARNING,
                GlossaryPressureFindingCode.PROFILE_SECONDARY_SIGNALS,
                len(profile.profile.secondary_profiles),
                0,
                "Secondary profile signals are present and may need sanity review.",
            )
        )
    if packets.packet_build_error:
        findings.append(
            _finding(
                GlossaryPressureFindingSeverity.BLOCKER,
                GlossaryPressureFindingCode.PACKET_BUILD_FAILED,
                packets.packet_build_error,
                None,
                "Packet build failed from metadata validation; inspect local inputs.",
            )
        )
    if packets.degraded_packet_count > thresholds.max_degraded_packets:
        findings.append(
            _finding(
                GlossaryPressureFindingSeverity.WARNING,
                GlossaryPressureFindingCode.PACKET_DEGRADED,
                packets.degraded_packet_count,
                thresholds.max_degraded_packets,
                "Degraded packets indicate evidence or budget pressure.",
            )
        )
    if packets.skipped_entry_count > thresholds.max_skipped_entries:
        findings.append(
            _finding(
                GlossaryPressureFindingSeverity.BLOCKER,
                GlossaryPressureFindingCode.SKIPPED_ENTRIES,
                packets.skipped_entry_count,
                thresholds.max_skipped_entries,
                "Skipped entries mean some candidates cannot reach editor packets.",
            )
        )
    return tuple(findings)


def _finding(
    severity: GlossaryPressureFindingSeverity,
    code: GlossaryPressureFindingCode,
    actual: int | float | bool | str | None,
    threshold: int | float | str | None,
    message: str,
) -> GlossaryPressureFinding:
    return GlossaryPressureFinding(
        severity=severity,
        code=code,
        actual=actual,
        threshold=threshold,
        message=message,
    )


def _fixture_metadata_payload(
    metadata: GlossaryPressureFixtureMetadata,
) -> dict[str, Any]:
    return {
        "fixture_id": metadata.fixture_id,
        "rights_basis": metadata.rights_basis,
        "usage_scope": metadata.usage_scope,
        "raw_text_policy": metadata.raw_text_policy,
    }


def _plan_stats_payload(stats: GlossaryPressurePlanStats) -> dict[str, Any]:
    return {
        "document_format": stats.document_format,
        "adapter_version": stats.adapter_version,
        "unit_count": stats.unit_count,
        "block_count": stats.block_count,
        "character_count": stats.character_count,
        "estimated_input_tokens": stats.estimated_input_tokens,
        "prompt_tier_counts": dict(stats.prompt_tier_counts),
        "block_kind_counts": dict(stats.block_kind_counts),
    }


def _candidate_stats_payload(stats: GlossaryPressureCandidateStats) -> dict[str, Any]:
    return {
        "candidate_count": stats.candidate_count,
        "evidence_count": stats.evidence_count,
        "category_counts": dict(stats.category_counts),
        "status_counts": dict(stats.status_counts),
        "layer_counts": dict(stats.layer_counts),
        "confidence_bucket_counts": dict(stats.confidence_bucket_counts),
        "entries_missing_evidence_count": stats.entries_missing_evidence_count,
        "missing_evidence_ref_count": stats.missing_evidence_ref_count,
        "max_evidence_refs_per_entry": stats.max_evidence_refs_per_entry,
        "glossary_signature": stats.glossary_signature,
    }


def _profile_summary_payload(stats: GlossaryPressureProfileSummary) -> dict[str, Any]:
    return {
        "profile_id": stats.profile_id,
        "profile_signature": stats.profile_signature,
        "primary_profile": stats.primary_profile,
        "secondary_profiles": list(stats.secondary_profiles),
        "document_type": stats.document_type,
        "confidence": stats.confidence,
        "evidence_count": stats.evidence_count,
        "rule_count": stats.rule_count,
        "domain_hints": list(stats.domain_hints),
        "uncertainty_note_count": stats.uncertainty_note_count,
    }


def _packet_stats_payload(stats: GlossaryPressurePacketStats) -> dict[str, Any]:
    return {
        "packet_count": stats.packet_count,
        "ready_packet_count": stats.ready_packet_count,
        "degraded_packet_count": stats.degraded_packet_count,
        "skipped_entry_count": stats.skipped_entry_count,
        "entry_refs_in_packets": stats.entry_refs_in_packets,
        "total_estimated_prompt_tokens": stats.total_estimated_prompt_tokens,
        "total_reserved_prompt_tokens": stats.total_reserved_prompt_tokens,
        "max_estimated_prompt_tokens": stats.max_estimated_prompt_tokens,
        "max_reserved_prompt_tokens": stats.max_reserved_prompt_tokens,
        "max_packet_budget_utilization": stats.max_packet_budget_utilization,
        "status_counts": dict(stats.status_counts),
        "degradation_counts": dict(stats.degradation_counts),
        "packet_build_signature": stats.packet_build_signature,
        "packet_policy_version": stats.packet_policy_version,
        "packet_build_error": stats.packet_build_error,
    }


def _finding_payload(finding: GlossaryPressureFinding) -> dict[str, Any]:
    return {
        "severity": finding.severity.value,
        "code": finding.code.value,
        "actual": finding.actual,
        "threshold": finding.threshold,
        "message": finding.message,
    }


def _confidence_bucket_counts(
    glossary: GlossarySnapshot,
) -> dict[str, int]:
    return _sorted_counter(
        _confidence_bucket(entry.confidence) for entry in glossary.entries
    )


def _confidence_bucket(value: float) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "invalid"
    if not math.isfinite(float(value)):
        return "invalid"
    if value < 0.5:
        return "0.00-0.49"
    if value < 0.7:
        return "0.50-0.69"
    if value < 0.85:
        return "0.70-0.84"
    return "0.85-1.00"


def _sorted_counter(values) -> dict[str, int]:
    counter = Counter(str(value) for value in values)
    return {key: counter[key] for key in sorted(counter)}


def _enum_value(value: Any) -> str:
    if isinstance(value, StrEnum):
        return value.value
    return str(value)


def _rate(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 0.0
    return round(float(numerator) / float(denominator), 6)


def _payload_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]
