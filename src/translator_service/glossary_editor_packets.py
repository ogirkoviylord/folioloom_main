from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from translator_service.book_profile import (
    BookProfileDetection,
    validate_book_profile_detection,
)
from translator_service.glossary_candidate_reducer import (
    GlossaryCandidateReductionDecision,
    GlossaryCandidateReductionResult,
)
from translator_service.glossary_contracts import (
    GlossaryEntry,
    GlossaryEvidenceRef,
    GlossaryLayer,
    GlossarySnapshot,
    glossary_snapshot_signature,
    validate_glossary_snapshot,
)
from translator_service.translation_contract_snapshot import (
    book_profile_detection_signature,
)

GLOSSARY_EDITOR_PACKET_SCHEMA_VERSION = "glossary-editor-packet-v1"
GLOSSARY_EDITOR_PACKET_POLICY_VERSION = "glossary-editor-packetizer-v1"


class GlossaryEditorPacketStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"


class GlossaryEditorPacketDegradationReason(StrEnum):
    EVIDENCE_REF_LIMIT_EXHAUSTED = "evidence_ref_limit_exhausted"
    ENTRY_LIMIT_EXHAUSTED = "entry_limit_exhausted"
    TOKEN_BUDGET_EXHAUSTED = "token_budget_exhausted"
    ENTRY_BUDGET_EXCEEDED = "entry_budget_exceeded"


@dataclass(frozen=True)
class GlossaryEditorPacketBudget:
    max_entries_per_packet: int = 24
    max_evidence_refs_per_entry: int = 3
    max_estimated_prompt_tokens: int = 1600
    reservation_multiplier: float = 2.0
    reservation_padding_tokens: int = 96
    max_reserved_prompt_tokens: int = 3600


DEFAULT_GLOSSARY_EDITOR_PACKET_BUDGET = GlossaryEditorPacketBudget()


@dataclass(frozen=True)
class GlossaryEditorPacketEntryRef:
    entry_id: str
    category: str
    layer: str
    status: str
    strategy: str
    grammatical_gender: str
    confidence: float
    source_digest: str
    source_char_count: int
    alias_digests: tuple[str, ...]
    target_digest: str | None
    target_variant_digests: tuple[str, ...]
    forbidden_variant_digests: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    profile_rule_ids: tuple[str, ...]
    estimated_prompt_tokens: int
    needs_review: bool
    reducer_decision_status: str | None = None
    reducer_decision_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class GlossaryEditorPacketReducerContext:
    policy_version: str
    reducer_signature: str
    source_glossary_signature: str
    reduced_glossary_signature: str
    profile_signature: str
    pressure_signature: str
    retained_count: int
    diagnostic_count: int
    dropped_count: int


@dataclass(frozen=True)
class GlossaryEditorPacketEvidenceRef:
    evidence_id: str
    evidence_source: str
    evidence_type: str
    unit_sequence: int
    source_block_id: str
    source_scope: str
    surface: str
    occurrence_count: int
    offset_bucket: str


@dataclass(frozen=True)
class GlossaryEditorPacketDegradation:
    reason: GlossaryEditorPacketDegradationReason
    entry_id: str | None
    evidence_refs: tuple[str, ...]
    estimated_prompt_tokens: int | None
    reserved_prompt_tokens: int | None


@dataclass(frozen=True)
class SkippedGlossaryEditorEntry:
    entry_id: str
    reason: GlossaryEditorPacketDegradationReason
    evidence_refs: tuple[str, ...]
    estimated_prompt_tokens: int
    reserved_prompt_tokens: int


@dataclass(frozen=True)
class GlossaryEditorPacket:
    packet_id: str
    packet_signature: str
    packet_index: int
    schema_version: str
    policy_version: str
    status: GlossaryEditorPacketStatus
    source_language: str
    target_language: str
    glossary_snapshot_id: str
    glossary_signature: str
    profile_id: str
    profile_signature: str
    selected_rule_ids: tuple[str, ...]
    profile_evidence_refs: tuple[str, ...]
    entries: tuple[GlossaryEditorPacketEntryRef, ...]
    evidence_refs: tuple[GlossaryEditorPacketEvidenceRef, ...]
    estimated_prompt_tokens: int
    reserved_prompt_tokens: int
    max_estimated_prompt_tokens: int
    max_reserved_prompt_tokens: int
    degradations: tuple[GlossaryEditorPacketDegradation, ...] = ()
    reducer_context: GlossaryEditorPacketReducerContext | None = None

    @property
    def entry_ids(self) -> tuple[str, ...]:
        return tuple(entry.entry_id for entry in self.entries)

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(evidence.evidence_id for evidence in self.evidence_refs)


@dataclass(frozen=True)
class GlossaryEditorPacketBuildResult:
    packets: tuple[GlossaryEditorPacket, ...]
    skipped_entries: tuple[SkippedGlossaryEditorEntry, ...]
    build_signature: str
    glossary_signature: str
    profile_signature: str
    policy_version: str = GLOSSARY_EDITOR_PACKET_POLICY_VERSION
    reducer_context: GlossaryEditorPacketReducerContext | None = None


def build_glossary_editor_packets(
    glossary_snapshot: GlossarySnapshot,
    profile_detection: BookProfileDetection,
    *,
    budget: GlossaryEditorPacketBudget = DEFAULT_GLOSSARY_EDITOR_PACKET_BUDGET,
    candidate_reduction: GlossaryCandidateReductionResult | None = None,
) -> GlossaryEditorPacketBuildResult:
    _validate_budget(budget)
    _validate_inputs(glossary_snapshot, profile_detection)

    profile_signature = book_profile_detection_signature(profile_detection)
    effective_glossary_snapshot = glossary_snapshot
    reducer_context = None
    reducer_decisions_by_entry_id: Mapping[str, GlossaryCandidateReductionDecision] = {}
    if candidate_reduction is not None:
        _validate_candidate_reduction(
            glossary_snapshot,
            profile_signature=profile_signature,
            candidate_reduction=candidate_reduction,
        )
        effective_glossary_snapshot = candidate_reduction.retained_snapshot
        _validate_inputs(effective_glossary_snapshot, profile_detection)
        reducer_context = _reducer_context(candidate_reduction)
        reducer_decisions_by_entry_id = {
            decision.entry_id: decision for decision in candidate_reduction.decisions
        }

    glossary_signature = glossary_snapshot_signature(effective_glossary_snapshot)
    selected_rule_ids = tuple(sorted(rule.rule_id for rule in profile_detection.rules))
    profile_evidence_refs = tuple(
        sorted(evidence.evidence_id for evidence in profile_detection.evidence)
    )

    evidence_by_id = {
        evidence.evidence_id: evidence
        for evidence in effective_glossary_snapshot.evidence
    }
    packet_states: list[_PacketState] = []
    current = _PacketState()
    skipped: list[SkippedGlossaryEditorEntry] = []

    for entry in sorted(effective_glossary_snapshot.entries, key=_entry_sort_key):
        entry_ref, entry_degradations = _entry_ref(
            entry,
            evidence_by_id=evidence_by_id,
            budget=budget,
            reducer_decision=reducer_decisions_by_entry_id.get(entry.entry_id),
        )
        single_entry_state = _PacketState().with_entry(
            entry_ref,
            degradations=entry_degradations,
            evidence_by_id=evidence_by_id,
        )
        if not _packet_state_within_budget(
            single_entry_state,
            glossary_snapshot=effective_glossary_snapshot,
            profile_detection=profile_detection,
            budget=budget,
            reducer_context=reducer_context,
        ):
            single_entry_estimate = _packet_estimated_prompt_tokens(
                single_entry_state,
                glossary_snapshot=effective_glossary_snapshot,
                profile_detection=profile_detection,
                reducer_context=reducer_context,
            )
            skipped.append(
                SkippedGlossaryEditorEntry(
                    entry_id=entry.entry_id,
                    reason=GlossaryEditorPacketDegradationReason.ENTRY_BUDGET_EXCEEDED,
                    evidence_refs=entry_ref.evidence_refs,
                    estimated_prompt_tokens=single_entry_estimate,
                    reserved_prompt_tokens=_reserve_tokens(
                        single_entry_estimate,
                        budget=budget,
                    ),
                )
            )
            continue

        candidate = current.with_entry(
            entry_ref,
            degradations=entry_degradations,
            evidence_by_id=evidence_by_id,
        )
        if _packet_state_within_budget(
            candidate,
            glossary_snapshot=effective_glossary_snapshot,
            profile_detection=profile_detection,
            budget=budget,
            reducer_context=reducer_context,
        ):
            current = candidate
            continue

        if current.entries:
            packet_states.append(current)
            current = single_entry_state
            continue

    if current.entries:
        packet_states.append(current)

    packets = tuple(
        _packet_from_state(
            state,
            packet_index=index,
            glossary_snapshot=effective_glossary_snapshot,
            profile_detection=profile_detection,
            glossary_signature=glossary_signature,
            profile_signature=profile_signature,
            selected_rule_ids=selected_rule_ids,
            profile_evidence_refs=profile_evidence_refs,
            budget=budget,
            reducer_context=reducer_context,
        )
        for index, state in enumerate(packet_states)
    )
    build_payload = {
        "policy_version": GLOSSARY_EDITOR_PACKET_POLICY_VERSION,
        "glossary_signature": glossary_signature,
        "profile_signature": profile_signature,
        "packet_signatures": [packet.packet_signature for packet in packets],
        "skipped_entries": [
            _skipped_entry_payload(entry) for entry in sorted(skipped, key=_skipped_key)
        ],
    }
    if reducer_context is not None:
        build_payload["reducer_context"] = _reducer_context_payload(reducer_context)
    return GlossaryEditorPacketBuildResult(
        packets=packets,
        skipped_entries=tuple(sorted(skipped, key=_skipped_key)),
        build_signature=f"glossary-editor-packets:v1:{_payload_digest(build_payload)}",
        glossary_signature=glossary_signature,
        profile_signature=profile_signature,
        reducer_context=reducer_context,
    )


def glossary_editor_packet_payload(packet: GlossaryEditorPacket) -> dict[str, Any]:
    payload = {
        "packet_id": packet.packet_id,
        "packet_signature": packet.packet_signature,
        "packet_index": packet.packet_index,
        "schema_version": packet.schema_version,
        "policy_version": packet.policy_version,
        "status": packet.status.value,
        "source_language": packet.source_language,
        "target_language": packet.target_language,
        "glossary_snapshot_id": packet.glossary_snapshot_id,
        "glossary_signature": packet.glossary_signature,
        "profile_id": packet.profile_id,
        "profile_signature": packet.profile_signature,
        "selected_rule_ids": list(packet.selected_rule_ids),
        "profile_evidence_refs": list(packet.profile_evidence_refs),
        "entries": [_entry_ref_payload(entry) for entry in packet.entries],
        "evidence_refs": [
            _packet_evidence_payload(evidence) for evidence in packet.evidence_refs
        ],
        "estimated_prompt_tokens": packet.estimated_prompt_tokens,
        "reserved_prompt_tokens": packet.reserved_prompt_tokens,
        "max_estimated_prompt_tokens": packet.max_estimated_prompt_tokens,
        "max_reserved_prompt_tokens": packet.max_reserved_prompt_tokens,
        "degradations": [
            _degradation_payload(degradation) for degradation in packet.degradations
        ],
    }
    if packet.reducer_context is not None:
        payload["reducer_context"] = _reducer_context_payload(packet.reducer_context)
    return payload


def serialize_glossary_editor_packet(packet: GlossaryEditorPacket) -> str:
    return json.dumps(
        glossary_editor_packet_payload(packet),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class _PacketState:
    entries: tuple[GlossaryEditorPacketEntryRef, ...] = ()
    evidence_refs: tuple[GlossaryEditorPacketEvidenceRef, ...] = ()
    degradations: tuple[GlossaryEditorPacketDegradation, ...] = ()

    def with_entry(
        self,
        entry: GlossaryEditorPacketEntryRef,
        *,
        degradations: Sequence[GlossaryEditorPacketDegradation],
        evidence_by_id: Mapping[str, GlossaryEvidenceRef],
    ) -> _PacketState:
        evidence_by_packet_id = {item.evidence_id: item for item in self.evidence_refs}
        for evidence_id in entry.evidence_refs:
            if evidence_id not in evidence_by_packet_id:
                evidence_by_packet_id[evidence_id] = _packet_evidence_ref(
                    evidence_by_id[evidence_id],
                    evidence_source="glossary",
                )
        return _PacketState(
            entries=(*self.entries, entry),
            evidence_refs=tuple(
                sorted(evidence_by_packet_id.values(), key=_evidence_sort_key)
            ),
            degradations=(*self.degradations, *degradations),
        )

def _packet_from_state(
    state: _PacketState,
    *,
    packet_index: int,
    glossary_snapshot: GlossarySnapshot,
    profile_detection: BookProfileDetection,
    glossary_signature: str,
    profile_signature: str,
    selected_rule_ids: tuple[str, ...],
    profile_evidence_refs: tuple[str, ...],
    budget: GlossaryEditorPacketBudget,
    reducer_context: GlossaryEditorPacketReducerContext | None,
) -> GlossaryEditorPacket:
    evidence_refs = tuple(sorted(state.evidence_refs, key=_evidence_sort_key))
    estimated_prompt_tokens = _packet_estimated_prompt_tokens(
        _PacketState(
            entries=state.entries,
            evidence_refs=evidence_refs,
            degradations=state.degradations,
        ),
        glossary_snapshot=glossary_snapshot,
        profile_detection=profile_detection,
        reducer_context=reducer_context,
    )
    reserved_prompt_tokens = _reserve_tokens(estimated_prompt_tokens, budget=budget)
    status = (
        GlossaryEditorPacketStatus.DEGRADED
        if state.degradations
        else GlossaryEditorPacketStatus.READY
    )
    body_payload = _packet_body_payload(
        packet_index=packet_index,
        status=status.value,
        source_language=glossary_snapshot.source_language,
        target_language=glossary_snapshot.target_language,
        glossary_snapshot_id=glossary_snapshot.snapshot_id,
        glossary_signature=glossary_signature,
        profile_id=profile_detection.profile.profile_id,
        profile_signature=profile_signature,
        selected_rule_ids=selected_rule_ids,
        profile_evidence_refs=profile_evidence_refs,
        entries=state.entries,
        evidence_refs=evidence_refs,
        estimated_prompt_tokens=estimated_prompt_tokens,
        reserved_prompt_tokens=reserved_prompt_tokens,
        budget=budget,
        degradations=state.degradations,
        reducer_context=reducer_context,
    )
    packet_id = f"glossary-editor-packet:v1:{_payload_digest(body_payload)}"
    signature_payload = {"packet_id": packet_id, **body_payload}
    packet_signature = (
        f"glossary-editor-packet-signature:v1:{_payload_digest(signature_payload)}"
    )
    return GlossaryEditorPacket(
        packet_id=packet_id,
        packet_signature=packet_signature,
        packet_index=packet_index,
        schema_version=GLOSSARY_EDITOR_PACKET_SCHEMA_VERSION,
        policy_version=GLOSSARY_EDITOR_PACKET_POLICY_VERSION,
        status=status,
        source_language=glossary_snapshot.source_language,
        target_language=glossary_snapshot.target_language,
        glossary_snapshot_id=glossary_snapshot.snapshot_id,
        glossary_signature=glossary_signature,
        profile_id=profile_detection.profile.profile_id,
        profile_signature=profile_signature,
        selected_rule_ids=selected_rule_ids,
        profile_evidence_refs=profile_evidence_refs,
        entries=state.entries,
        evidence_refs=evidence_refs,
        estimated_prompt_tokens=estimated_prompt_tokens,
        reserved_prompt_tokens=reserved_prompt_tokens,
        max_estimated_prompt_tokens=budget.max_estimated_prompt_tokens,
        max_reserved_prompt_tokens=budget.max_reserved_prompt_tokens,
        degradations=state.degradations,
        reducer_context=reducer_context,
    )


def _entry_ref(
    entry: GlossaryEntry,
    *,
    evidence_by_id: Mapping[str, GlossaryEvidenceRef],
    budget: GlossaryEditorPacketBudget,
    reducer_decision: GlossaryCandidateReductionDecision | None = None,
) -> tuple[GlossaryEditorPacketEntryRef, tuple[GlossaryEditorPacketDegradation, ...]]:
    sorted_evidence_refs = tuple(
        sorted(
            (str(evidence_id) for evidence_id in entry.evidence_refs),
            key=lambda evidence_id: _evidence_sort_key(
                _packet_evidence_ref(
                    evidence_by_id[evidence_id],
                    evidence_source="glossary",
                )
            ),
        )
    )
    kept_evidence_refs = sorted_evidence_refs[: budget.max_evidence_refs_per_entry]
    degradations: list[GlossaryEditorPacketDegradation] = []
    estimated_prompt_tokens = _estimate_entry_prompt_tokens(
        entry,
        evidence_refs=kept_evidence_refs,
        reducer_decision=reducer_decision,
    )
    if len(kept_evidence_refs) < len(sorted_evidence_refs):
        degradations.append(
            GlossaryEditorPacketDegradation(
                reason=GlossaryEditorPacketDegradationReason.EVIDENCE_REF_LIMIT_EXHAUSTED,
                entry_id=entry.entry_id,
                evidence_refs=tuple(
                    sorted_evidence_refs[budget.max_evidence_refs_per_entry :]
                ),
                estimated_prompt_tokens=estimated_prompt_tokens,
                reserved_prompt_tokens=_reserve_tokens(
                    estimated_prompt_tokens,
                    budget=budget,
                ),
            )
        )
    return (
        GlossaryEditorPacketEntryRef(
            entry_id=entry.entry_id,
            category=_enum_value(entry.category),
            layer=_enum_value(entry.layer),
            status=_enum_value(entry.status),
            strategy=_enum_value(entry.strategy),
            grammatical_gender=_enum_value(entry.grammatical_gender),
            confidence=float(entry.confidence),
            source_digest=_text_digest(entry.source_canonical),
            source_char_count=len(entry.source_canonical),
            alias_digests=tuple(sorted(_text_digest(alias) for alias in entry.aliases)),
            target_digest=_optional_text_digest(entry.target_canonical),
            target_variant_digests=tuple(
                sorted(_text_digest(item) for item in entry.target_variants)
            ),
            forbidden_variant_digests=tuple(
                sorted(_text_digest(item) for item in entry.forbidden_variants)
            ),
            evidence_refs=kept_evidence_refs,
            profile_rule_ids=tuple(
                sorted(str(item) for item in entry.profile_rule_ids)
            ),
            estimated_prompt_tokens=estimated_prompt_tokens,
            needs_review=_entry_needs_review(entry),
            reducer_decision_status=(
                reducer_decision.status.value if reducer_decision is not None else None
            ),
            reducer_decision_reasons=(
                tuple(reason.value for reason in reducer_decision.reasons)
                if reducer_decision is not None
                else ()
            ),
        ),
        tuple(degradations),
    )


def _packet_state_within_budget(
    state: _PacketState,
    *,
    glossary_snapshot: GlossarySnapshot,
    profile_detection: BookProfileDetection,
    budget: GlossaryEditorPacketBudget,
    reducer_context: GlossaryEditorPacketReducerContext | None,
) -> bool:
    if len(state.entries) > budget.max_entries_per_packet:
        return False
    estimated = _packet_estimated_prompt_tokens(
        state,
        glossary_snapshot=glossary_snapshot,
        profile_detection=profile_detection,
        reducer_context=reducer_context,
    )
    if estimated > budget.max_estimated_prompt_tokens:
        return False
    return (
        _reserve_tokens(estimated, budget=budget)
        <= budget.max_reserved_prompt_tokens
    )


def _packet_estimated_prompt_tokens(
    state: _PacketState,
    *,
    glossary_snapshot: GlossarySnapshot,
    profile_detection: BookProfileDetection,
    reducer_context: GlossaryEditorPacketReducerContext | None,
) -> int:
    return (
        _base_packet_tokens(
            glossary_snapshot,
            profile_detection,
            reducer_context=reducer_context,
        )
        + sum(entry.estimated_prompt_tokens for entry in state.entries)
        + sum(
            _estimate_evidence_prompt_tokens(evidence)
            for evidence in state.evidence_refs
        )
        + len(state.degradations) * 18
    )


def _base_packet_tokens(
    glossary_snapshot: GlossarySnapshot,
    profile_detection: BookProfileDetection,
    *,
    reducer_context: GlossaryEditorPacketReducerContext | None,
) -> int:
    values = [
        GLOSSARY_EDITOR_PACKET_SCHEMA_VERSION,
        GLOSSARY_EDITOR_PACKET_POLICY_VERSION,
        glossary_snapshot.source_language,
        glossary_snapshot.target_language,
        glossary_snapshot.snapshot_id,
        profile_detection.profile.profile_id,
        _enum_value(profile_detection.profile.primary_profile),
        " ".join(rule.rule_id for rule in profile_detection.rules),
        " ".join(profile_detection.profile.evidence_refs),
    ]
    if reducer_context is not None:
        values.extend(
            (
                reducer_context.policy_version,
                reducer_context.reducer_signature,
                reducer_context.source_glossary_signature,
                reducer_context.reduced_glossary_signature,
                reducer_context.pressure_signature,
            )
        )
    compact = " ".join(values)
    return max(48, math.ceil(len(compact) / 4) + 32)


def _estimate_entry_prompt_tokens(
    entry: GlossaryEntry,
    *,
    evidence_refs: Sequence[str],
    reducer_decision: GlossaryCandidateReductionDecision | None,
) -> int:
    values = [
        entry.entry_id,
        _enum_value(entry.category),
        _enum_value(entry.layer),
        _enum_value(entry.status),
        entry.source_canonical,
        " ".join(entry.aliases),
        entry.target_canonical or "",
        " ".join(entry.target_variants),
        " ".join(entry.forbidden_variants),
        _enum_value(entry.strategy),
        _enum_value(entry.grammatical_gender),
        f"{float(entry.confidence):.4f}",
        " ".join(evidence_refs),
        " ".join(entry.profile_rule_ids),
    ]
    if reducer_decision is not None:
        values.extend(
            (
                reducer_decision.status.value,
                " ".join(reason.value for reason in reducer_decision.reasons),
            )
        )
    compact = " ".join(str(value) for value in values)
    return max(12, math.ceil(len(compact) / 4) + 12)


def _estimate_evidence_prompt_tokens(evidence: GlossaryEditorPacketEvidenceRef) -> int:
    compact = " ".join(
        str(value)
        for value in (
            evidence.evidence_id,
            evidence.evidence_source,
            evidence.evidence_type,
            evidence.unit_sequence,
            evidence.source_block_id,
            evidence.source_scope,
            evidence.surface,
            evidence.occurrence_count,
            evidence.offset_bucket,
        )
    )
    return max(6, math.ceil(len(compact) / 4))


def _reserve_tokens(
    estimated_prompt_tokens: int,
    *,
    budget: GlossaryEditorPacketBudget,
) -> int:
    return math.ceil(
        estimated_prompt_tokens * budget.reservation_multiplier
        + budget.reservation_padding_tokens
    )


def _validate_inputs(
    glossary_snapshot: GlossarySnapshot,
    profile_detection: BookProfileDetection,
) -> None:
    glossary_result = validate_glossary_snapshot(glossary_snapshot)
    if not glossary_result.valid:
        messages = "; ".join(issue.message for issue in glossary_result.issues[:3])
        raise ValueError(f"glossary_snapshot is invalid: {messages}")
    profile_result = validate_book_profile_detection(profile_detection)
    if not profile_result.valid:
        messages = "; ".join(issue.message for issue in profile_result.issues[:3])
        raise ValueError(f"profile_detection is invalid: {messages}")
    if glossary_snapshot.source_language != profile_detection.profile.source_language:
        raise ValueError("glossary/profile source_language mismatch.")
    if glossary_snapshot.target_language != profile_detection.profile.target_language:
        raise ValueError("glossary/profile target_language mismatch.")


def _validate_candidate_reduction(
    glossary_snapshot: GlossarySnapshot,
    *,
    profile_signature: str,
    candidate_reduction: GlossaryCandidateReductionResult,
) -> None:
    source_signature = glossary_snapshot_signature(glossary_snapshot)
    if candidate_reduction.source_glossary_signature != source_signature:
        raise ValueError("candidate_reduction source glossary signature mismatch.")
    reduced_signature = glossary_snapshot_signature(
        candidate_reduction.retained_snapshot
    )
    if candidate_reduction.reduced_glossary_signature != reduced_signature:
        raise ValueError("candidate_reduction reduced glossary signature mismatch.")
    if candidate_reduction.profile_signature not in {
        "book-profile:none",
        profile_signature,
    }:
        raise ValueError("candidate_reduction profile signature mismatch.")
    if (
        glossary_snapshot.source_language
        != candidate_reduction.retained_snapshot.source_language
    ):
        raise ValueError("candidate_reduction source_language mismatch.")
    if (
        glossary_snapshot.target_language
        != candidate_reduction.retained_snapshot.target_language
    ):
        raise ValueError("candidate_reduction target_language mismatch.")
    retained_ids = {
        entry.entry_id for entry in candidate_reduction.retained_snapshot.entries
    }
    retained_decision_ids = set(candidate_reduction.retained_entry_ids)
    if retained_ids != retained_decision_ids:
        raise ValueError("candidate_reduction retained decision ids mismatch.")


def _reducer_context(
    candidate_reduction: GlossaryCandidateReductionResult,
) -> GlossaryEditorPacketReducerContext:
    return GlossaryEditorPacketReducerContext(
        policy_version=candidate_reduction.policy_version,
        reducer_signature=candidate_reduction.reducer_signature,
        source_glossary_signature=candidate_reduction.source_glossary_signature,
        reduced_glossary_signature=candidate_reduction.reduced_glossary_signature,
        profile_signature=candidate_reduction.profile_signature,
        pressure_signature=candidate_reduction.pressure_signature,
        retained_count=len(candidate_reduction.retained_entry_ids),
        diagnostic_count=len(candidate_reduction.diagnostic_entry_ids),
        dropped_count=len(candidate_reduction.dropped_entry_ids),
    )


def _validate_budget(budget: GlossaryEditorPacketBudget) -> None:
    if budget.max_entries_per_packet <= 0:
        raise ValueError("max_entries_per_packet must be positive.")
    if budget.max_evidence_refs_per_entry <= 0:
        raise ValueError("max_evidence_refs_per_entry must be positive.")
    if budget.max_estimated_prompt_tokens <= 0:
        raise ValueError("max_estimated_prompt_tokens must be positive.")
    if budget.max_reserved_prompt_tokens <= 0:
        raise ValueError("max_reserved_prompt_tokens must be positive.")
    if budget.reservation_multiplier < 1.0 or not math.isfinite(
        budget.reservation_multiplier
    ):
        raise ValueError("reservation_multiplier must be finite and at least 1.0.")
    if budget.reservation_padding_tokens < 0:
        raise ValueError("reservation_padding_tokens must be non-negative.")


def _packet_evidence_ref(
    evidence: GlossaryEvidenceRef,
    *,
    evidence_source: str,
) -> GlossaryEditorPacketEvidenceRef:
    return GlossaryEditorPacketEvidenceRef(
        evidence_id=evidence.evidence_id,
        evidence_source=evidence_source,
        evidence_type=_enum_value(evidence.evidence_type),
        unit_sequence=evidence.unit_sequence,
        source_block_id=evidence.source_block_id,
        source_scope=evidence.source_scope,
        surface=_enum_value(evidence.surface),
        occurrence_count=evidence.occurrence_count,
        offset_bucket=evidence.offset_bucket,
    )


def _packet_body_payload(
    *,
    packet_index: int,
    status: str,
    source_language: str,
    target_language: str,
    glossary_snapshot_id: str,
    glossary_signature: str,
    profile_id: str,
    profile_signature: str,
    selected_rule_ids: tuple[str, ...],
    profile_evidence_refs: tuple[str, ...],
    entries: Sequence[GlossaryEditorPacketEntryRef],
    evidence_refs: Sequence[GlossaryEditorPacketEvidenceRef],
    estimated_prompt_tokens: int,
    reserved_prompt_tokens: int,
    budget: GlossaryEditorPacketBudget,
    degradations: Sequence[GlossaryEditorPacketDegradation],
    reducer_context: GlossaryEditorPacketReducerContext | None,
) -> dict[str, Any]:
    payload = {
        "schema_version": GLOSSARY_EDITOR_PACKET_SCHEMA_VERSION,
        "policy_version": GLOSSARY_EDITOR_PACKET_POLICY_VERSION,
        "packet_index": packet_index,
        "status": status,
        "source_language": source_language,
        "target_language": target_language,
        "glossary_snapshot_id": glossary_snapshot_id,
        "glossary_signature": glossary_signature,
        "profile_id": profile_id,
        "profile_signature": profile_signature,
        "selected_rule_ids": list(selected_rule_ids),
        "profile_evidence_refs": list(profile_evidence_refs),
        "entries": [_entry_ref_payload(entry) for entry in entries],
        "evidence_refs": [_packet_evidence_payload(item) for item in evidence_refs],
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "reserved_prompt_tokens": reserved_prompt_tokens,
        "max_estimated_prompt_tokens": budget.max_estimated_prompt_tokens,
        "max_reserved_prompt_tokens": budget.max_reserved_prompt_tokens,
        "degradations": [_degradation_payload(item) for item in degradations],
    }
    if reducer_context is not None:
        payload["reducer_context"] = _reducer_context_payload(reducer_context)
    return payload


def _entry_ref_payload(entry: GlossaryEditorPacketEntryRef) -> dict[str, Any]:
    payload = {
        "entry_id": entry.entry_id,
        "category": entry.category,
        "layer": entry.layer,
        "status": entry.status,
        "strategy": entry.strategy,
        "grammatical_gender": entry.grammatical_gender,
        "confidence": entry.confidence,
        "source_digest": entry.source_digest,
        "source_char_count": entry.source_char_count,
        "alias_digests": list(entry.alias_digests),
        "target_digest": entry.target_digest,
        "target_variant_digests": list(entry.target_variant_digests),
        "forbidden_variant_digests": list(entry.forbidden_variant_digests),
        "evidence_refs": list(entry.evidence_refs),
        "profile_rule_ids": list(entry.profile_rule_ids),
        "estimated_prompt_tokens": entry.estimated_prompt_tokens,
        "needs_review": entry.needs_review,
    }
    if entry.reducer_decision_status is not None:
        payload["reducer_decision_status"] = entry.reducer_decision_status
        payload["reducer_decision_reasons"] = list(entry.reducer_decision_reasons)
    return payload


def _reducer_context_payload(
    context: GlossaryEditorPacketReducerContext,
) -> dict[str, Any]:
    return {
        "policy_version": context.policy_version,
        "reducer_signature": context.reducer_signature,
        "source_glossary_signature": context.source_glossary_signature,
        "reduced_glossary_signature": context.reduced_glossary_signature,
        "profile_signature": context.profile_signature,
        "pressure_signature": context.pressure_signature,
        "retained_count": context.retained_count,
        "diagnostic_count": context.diagnostic_count,
        "dropped_count": context.dropped_count,
    }


def _packet_evidence_payload(
    evidence: GlossaryEditorPacketEvidenceRef,
) -> dict[str, Any]:
    return {
        "evidence_id": evidence.evidence_id,
        "evidence_source": evidence.evidence_source,
        "evidence_type": evidence.evidence_type,
        "unit_sequence": evidence.unit_sequence,
        "source_block_id": evidence.source_block_id,
        "source_scope": evidence.source_scope,
        "surface": evidence.surface,
        "occurrence_count": evidence.occurrence_count,
        "offset_bucket": evidence.offset_bucket,
    }


def _degradation_payload(
    degradation: GlossaryEditorPacketDegradation,
) -> dict[str, Any]:
    return {
        "reason": degradation.reason.value,
        "entry_id": degradation.entry_id,
        "evidence_refs": list(degradation.evidence_refs),
        "estimated_prompt_tokens": degradation.estimated_prompt_tokens,
        "reserved_prompt_tokens": degradation.reserved_prompt_tokens,
    }


def _skipped_entry_payload(entry: SkippedGlossaryEditorEntry) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "reason": entry.reason.value,
        "evidence_refs": list(entry.evidence_refs),
        "estimated_prompt_tokens": entry.estimated_prompt_tokens,
        "reserved_prompt_tokens": entry.reserved_prompt_tokens,
    }


def _entry_sort_key(entry: GlossaryEntry) -> tuple[int, str, str, str]:
    return (
        _layer_priority(_entry_layer(entry)),
        _enum_value(entry.category),
        _normalize_text(entry.source_canonical),
        entry.entry_id,
    )


def _evidence_sort_key(
    evidence: GlossaryEditorPacketEvidenceRef,
) -> tuple[str, int, str, str]:
    return (
        evidence.evidence_source,
        evidence.unit_sequence,
        evidence.source_block_id,
        evidence.evidence_id,
    )


def _skipped_key(entry: SkippedGlossaryEditorEntry) -> tuple[str, str]:
    return (entry.reason.value, entry.entry_id)


def _entry_needs_review(entry: GlossaryEntry) -> bool:
    return _enum_value(entry.layer) == "diagnostic" or _enum_value(entry.status) in {
        "uncertain",
        "unknown",
        "rejected",
    }


def _entry_layer(entry: GlossaryEntry) -> GlossaryLayer:
    if isinstance(entry.layer, GlossaryLayer):
        return entry.layer
    return GlossaryLayer(str(entry.layer))


def _layer_priority(layer: GlossaryLayer) -> int:
    if layer is GlossaryLayer.HARD:
        return 0
    if layer is GlossaryLayer.SOFT:
        return 1
    return 2


def _enum_value(value: Any) -> str:
    if isinstance(value, StrEnum):
        return value.value
    return str(value)


def _normalize_text(value: str) -> str:
    return " ".join(str(value).casefold().split())


def _optional_text_digest(value: str | None) -> str | None:
    if value is None:
        return None
    return _text_digest(value)


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _payload_digest(payload: Mapping[str, Any] | Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]
