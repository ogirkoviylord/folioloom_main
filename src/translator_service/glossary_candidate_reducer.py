from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from translator_service.book_profile import BookProfileDetection
from translator_service.digest_utils import payload_digest, text_digest
from translator_service.glossary_contracts import (
    GlossaryEntry,
    GlossaryEntryCategory,
    GlossaryEntryStatus,
    GlossaryEvidenceRef,
    GlossaryEvidenceSurface,
    GlossaryLayer,
    GlossarySnapshot,
    glossary_snapshot_signature,
)
from translator_service.translation_contract_snapshot import (
    book_profile_detection_signature,
)

GLOSSARY_CANDIDATE_REDUCER_POLICY_VERSION = "glossary-candidate-reducer-v1"


class GlossaryCandidateDecisionStatus(StrEnum):
    RETAINED_FOR_EDITOR = "retained_for_editor"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    DROPPED_FROM_EDITOR = "dropped_from_editor"


class GlossaryCandidateReductionReason(StrEnum):
    HARD_OR_PINNED = "hard_or_pinned"
    REPEATED_NAME = "repeated_name"
    REPEATED_TERM = "repeated_term"
    HIGH_CONFIDENCE = "high_confidence"
    PROFILE_RELEVANT = "profile_relevant"
    EVIDENCE_SPREAD = "evidence_spread"
    UNCERTAIN_ENTITY = "uncertain_entity"
    LOW_CONFIDENCE = "low_confidence"
    LOW_EVIDENCE = "low_evidence"
    FRONTMATTER_OR_NAV_NOISE = "frontmatter_or_nav_noise"
    REJECTED_STATUS = "rejected_status"
    EDITOR_ENTRY_CAP_EXHAUSTED = "editor_entry_cap_exhausted"
    DIAGNOSTIC_CAP_EXHAUSTED = "diagnostic_cap_exhausted"
    TOKEN_BUDGET_EXHAUSTED = "token_budget_exhausted"
    MISSING_EVIDENCE = "missing_evidence"


@dataclass(frozen=True)
class GlossaryCandidateReducerCaps:
    max_editor_entries: int = 40
    max_diagnostic_entries: int = 80
    max_estimated_editor_tokens: int = 9000
    min_editor_score: int = 220
    min_diagnostic_score: int = 80


DEFAULT_GLOSSARY_CANDIDATE_REDUCER_CAPS = GlossaryCandidateReducerCaps()


@dataclass(frozen=True)
class GlossaryCandidateReductionDecision:
    entry_id: str
    status: GlossaryCandidateDecisionStatus
    reasons: tuple[GlossaryCandidateReductionReason, ...]
    evidence_refs: tuple[str, ...]
    score: int
    estimated_prompt_tokens: int
    category: str
    layer: str
    original_status: str
    confidence: float
    source_digest: str
    source_char_count: int


@dataclass(frozen=True)
class GlossaryCandidateReductionResult:
    policy_version: str
    source_glossary_signature: str
    reduced_glossary_signature: str
    profile_signature: str
    pressure_signature: str
    reducer_signature: str
    retained_snapshot: GlossarySnapshot
    decisions: tuple[GlossaryCandidateReductionDecision, ...]
    caps: GlossaryCandidateReducerCaps

    @property
    def retained_entry_ids(self) -> tuple[str, ...]:
        return tuple(
            decision.entry_id
            for decision in self.decisions
            if decision.status is GlossaryCandidateDecisionStatus.RETAINED_FOR_EDITOR
        )

    @property
    def diagnostic_entry_ids(self) -> tuple[str, ...]:
        return tuple(
            decision.entry_id
            for decision in self.decisions
            if decision.status is GlossaryCandidateDecisionStatus.DIAGNOSTIC_ONLY
        )

    @property
    def dropped_entry_ids(self) -> tuple[str, ...]:
        return tuple(
            decision.entry_id
            for decision in self.decisions
            if decision.status is GlossaryCandidateDecisionStatus.DROPPED_FROM_EDITOR
        )


def reduce_glossary_candidates(
    glossary_snapshot: GlossarySnapshot,
    *,
    profile_detection: BookProfileDetection | None = None,
    pressure_context: Mapping[str, Any] | None = None,
    caps: GlossaryCandidateReducerCaps = DEFAULT_GLOSSARY_CANDIDATE_REDUCER_CAPS,
) -> GlossaryCandidateReductionResult:
    """Reduce wide glossary scan candidates to editor-ready metadata decisions."""

    _validate_caps(caps)
    source_signature = glossary_snapshot_signature(glossary_snapshot)
    profile_signature = (
        book_profile_detection_signature(profile_detection)
        if profile_detection is not None
        else "book-profile:none"
    )
    pressure_signature = _pressure_context_signature(pressure_context)
    evidence_by_id = {
        evidence.evidence_id: evidence for evidence in glossary_snapshot.evidence
    }
    profile_rule_ids = (
        frozenset(rule.rule_id for rule in profile_detection.rules)
        if profile_detection is not None
        else frozenset()
    )
    profile_categories = (
        frozenset(_enum_value(rule.scope_category) for rule in profile_detection.rules)
        if profile_detection is not None
        else frozenset()
    )
    scored = tuple(
        _score_entry(
            entry,
            evidence_by_id=evidence_by_id,
            profile_rule_ids=profile_rule_ids,
            profile_categories=profile_categories,
        )
        for entry in glossary_snapshot.entries
    )

    retained: list[GlossaryEntry] = []
    diagnostic_count = 0
    used_editor_tokens = 0
    decisions: list[GlossaryCandidateReductionDecision] = []

    for item in sorted(scored, key=_scored_sort_key):
        status, cap_reasons = _decision_status(
            item,
            retained_count=len(retained),
            diagnostic_count=diagnostic_count,
            used_editor_tokens=used_editor_tokens,
            caps=caps,
        )
        reasons = tuple(dict.fromkeys((*item.reasons, *cap_reasons)))
        decisions.append(
            _decision(
                item,
                status=status,
                reasons=reasons,
            )
        )
        if status is GlossaryCandidateDecisionStatus.RETAINED_FOR_EDITOR:
            retained.append(item.entry)
            used_editor_tokens += item.estimated_prompt_tokens
        elif status is GlossaryCandidateDecisionStatus.DIAGNOSTIC_ONLY:
            diagnostic_count += 1

    retained_snapshot = _retained_snapshot(
        glossary_snapshot,
        retained_entries=tuple(retained),
        source_signature=source_signature,
    )
    payload = _reduction_payload(
        policy_version=GLOSSARY_CANDIDATE_REDUCER_POLICY_VERSION,
        source_glossary_signature=source_signature,
        reduced_glossary_signature=glossary_snapshot_signature(retained_snapshot),
        profile_signature=profile_signature,
        pressure_signature=pressure_signature,
        decisions=tuple(decisions),
        caps=caps,
    )
    return GlossaryCandidateReductionResult(
        policy_version=GLOSSARY_CANDIDATE_REDUCER_POLICY_VERSION,
        source_glossary_signature=source_signature,
        reduced_glossary_signature=payload["reduced_glossary_signature"],
        profile_signature=profile_signature,
        pressure_signature=pressure_signature,
        reducer_signature=f"glossary-candidate-reducer:v1:{payload_digest(payload)}",
        retained_snapshot=retained_snapshot,
        decisions=tuple(decisions),
        caps=caps,
    )


def glossary_candidate_reduction_payload(
    result: GlossaryCandidateReductionResult,
) -> dict[str, Any]:
    return {
        **_reduction_payload(
            policy_version=result.policy_version,
            source_glossary_signature=result.source_glossary_signature,
            reduced_glossary_signature=result.reduced_glossary_signature,
            profile_signature=result.profile_signature,
            pressure_signature=result.pressure_signature,
            decisions=result.decisions,
            caps=result.caps,
        ),
        "reducer_signature": result.reducer_signature,
    }


def serialize_glossary_candidate_reduction(
    result: GlossaryCandidateReductionResult,
) -> str:
    return json.dumps(
        glossary_candidate_reduction_payload(result),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class _ScoredCandidate:
    entry: GlossaryEntry
    score: int
    estimated_prompt_tokens: int
    reasons: tuple[GlossaryCandidateReductionReason, ...]
    evidence_refs: tuple[str, ...]
    evidence_spread: int
    noisy_surface_count: int
    missing_evidence_count: int


def _score_entry(
    entry: GlossaryEntry,
    *,
    evidence_by_id: Mapping[str, GlossaryEvidenceRef],
    profile_rule_ids: frozenset[str],
    profile_categories: frozenset[str],
) -> _ScoredCandidate:
    evidence_refs = tuple(
        sorted(str(evidence_id) for evidence_id in entry.evidence_refs)
    )
    evidence = tuple(
        evidence_by_id[evidence_id]
        for evidence_id in evidence_refs
        if evidence_id in evidence_by_id
    )
    missing_evidence_count = len(evidence_refs) - len(evidence)
    occurrence_count = sum(evidence_ref.occurrence_count for evidence_ref in evidence)
    evidence_spread = len({item.source_block_id for item in evidence})
    noisy_surface_count = sum(1 for item in evidence if _is_noisy_surface(item))
    reasons: list[GlossaryCandidateReductionReason] = []
    score = 0

    layer = _entry_layer(entry)
    original_status = _entry_status(entry)
    category = _entry_category(entry)
    if layer is GlossaryLayer.HARD or original_status in {
        GlossaryEntryStatus.OWNER_PINNED,
        GlossaryEntryStatus.LOCKED,
        GlossaryEntryStatus.VALIDATOR_ACCEPTED,
    }:
        reasons.append(GlossaryCandidateReductionReason.HARD_OR_PINNED)
        score += 10_000
    if original_status is GlossaryEntryStatus.REJECTED:
        reasons.append(GlossaryCandidateReductionReason.REJECTED_STATUS)
        score -= 1_000
    if missing_evidence_count:
        reasons.append(GlossaryCandidateReductionReason.MISSING_EVIDENCE)
        score -= 1_000

    if category is GlossaryEntryCategory.NAME:
        score += 120
        if occurrence_count >= 2 or evidence_spread >= 2:
            reasons.append(GlossaryCandidateReductionReason.REPEATED_NAME)
            score += 180
    elif category is GlossaryEntryCategory.TERM:
        score += 110
        if occurrence_count >= 2 or evidence_spread >= 2:
            reasons.append(GlossaryCandidateReductionReason.REPEATED_TERM)
            score += 160
    elif category is GlossaryEntryCategory.ENTITY:
        score += 50
    else:
        score += 40
    if original_status is GlossaryEntryStatus.UNCERTAIN:
        reasons.append(GlossaryCandidateReductionReason.UNCERTAIN_ENTITY)
        score -= 70 if category is GlossaryEntryCategory.ENTITY else 40

    if evidence_spread >= 2:
        reasons.append(GlossaryCandidateReductionReason.EVIDENCE_SPREAD)
        score += min(120, evidence_spread * 30)
    if occurrence_count <= 1:
        reasons.append(GlossaryCandidateReductionReason.LOW_EVIDENCE)
        score -= 60
    if noisy_surface_count:
        reasons.append(GlossaryCandidateReductionReason.FRONTMATTER_OR_NAV_NOISE)
        score -= min(180, noisy_surface_count * 90)

    confidence = _confidence(entry.confidence)
    score += math.floor(confidence * 100)
    if confidence >= 0.75:
        reasons.append(GlossaryCandidateReductionReason.HIGH_CONFIDENCE)
        score += 60
    elif confidence < 0.6:
        reasons.append(GlossaryCandidateReductionReason.LOW_CONFIDENCE)
        score -= 40

    entry_profile_rules = frozenset(str(rule_id) for rule_id in entry.profile_rule_ids)
    if entry_profile_rules.intersection(profile_rule_ids) or _enum_value(
        entry.category
    ) in profile_categories:
        reasons.append(GlossaryCandidateReductionReason.PROFILE_RELEVANT)
        score += 80

    return _ScoredCandidate(
        entry=entry,
        score=score,
        estimated_prompt_tokens=_estimate_prompt_tokens(
            entry,
            evidence_refs=evidence_refs,
        ),
        reasons=tuple(dict.fromkeys(reasons)),
        evidence_refs=evidence_refs,
        evidence_spread=evidence_spread,
        noisy_surface_count=noisy_surface_count,
        missing_evidence_count=missing_evidence_count,
    )


def _decision_status(
    item: _ScoredCandidate,
    *,
    retained_count: int,
    diagnostic_count: int,
    used_editor_tokens: int,
    caps: GlossaryCandidateReducerCaps,
) -> tuple[
    GlossaryCandidateDecisionStatus,
    tuple[GlossaryCandidateReductionReason, ...],
]:
    entry = item.entry
    cap_reasons: list[GlossaryCandidateReductionReason] = []
    if (
        _entry_status(entry) is GlossaryEntryStatus.REJECTED
        or item.missing_evidence_count
    ):
        return (
            GlossaryCandidateDecisionStatus.DROPPED_FROM_EDITOR,
            tuple(cap_reasons),
        )

    forced_retain = GlossaryCandidateReductionReason.HARD_OR_PINNED in item.reasons
    noisy_uncertain_entity = (
        _entry_category(entry) is GlossaryEntryCategory.ENTITY
        and _entry_status(entry) is GlossaryEntryStatus.UNCERTAIN
    )
    noisy_frontmatter = (
        item.noisy_surface_count
        and item.evidence_spread <= 1
        and item.score < caps.min_editor_score
    )

    if forced_retain or (
        item.score >= caps.min_editor_score
        and not noisy_uncertain_entity
        and not noisy_frontmatter
    ):
        if retained_count >= caps.max_editor_entries and not forced_retain:
            cap_reasons.append(
                GlossaryCandidateReductionReason.EDITOR_ENTRY_CAP_EXHAUSTED
            )
        elif (
            used_editor_tokens + item.estimated_prompt_tokens
            > caps.max_estimated_editor_tokens
            and not forced_retain
        ):
            cap_reasons.append(GlossaryCandidateReductionReason.TOKEN_BUDGET_EXHAUSTED)
        else:
            return (
                GlossaryCandidateDecisionStatus.RETAINED_FOR_EDITOR,
                tuple(cap_reasons),
            )

    if item.score >= caps.min_diagnostic_score and not noisy_frontmatter:
        if diagnostic_count >= caps.max_diagnostic_entries:
            return (
                GlossaryCandidateDecisionStatus.DROPPED_FROM_EDITOR,
                (
                    *cap_reasons,
                    GlossaryCandidateReductionReason.DIAGNOSTIC_CAP_EXHAUSTED,
                ),
            )
        return (
            GlossaryCandidateDecisionStatus.DIAGNOSTIC_ONLY,
            tuple(cap_reasons),
        )

    return (GlossaryCandidateDecisionStatus.DROPPED_FROM_EDITOR, tuple(cap_reasons))


def _decision(
    item: _ScoredCandidate,
    *,
    status: GlossaryCandidateDecisionStatus,
    reasons: tuple[GlossaryCandidateReductionReason, ...],
) -> GlossaryCandidateReductionDecision:
    entry = item.entry
    return GlossaryCandidateReductionDecision(
        entry_id=entry.entry_id,
        status=status,
        reasons=tuple(sorted(reasons, key=lambda reason: reason.value)),
        evidence_refs=item.evidence_refs,
        score=item.score,
        estimated_prompt_tokens=item.estimated_prompt_tokens,
        category=_enum_value(entry.category),
        layer=_enum_value(entry.layer),
        original_status=_enum_value(entry.status),
        confidence=round(_confidence(entry.confidence), 4),
        source_digest=text_digest(entry.source_canonical),
        source_char_count=len(entry.source_canonical),
    )


def _retained_snapshot(
    glossary_snapshot: GlossarySnapshot,
    *,
    retained_entries: tuple[GlossaryEntry, ...],
    source_signature: str,
) -> GlossarySnapshot:
    retained_evidence_ids = {
        evidence_id for entry in retained_entries for evidence_id in entry.evidence_refs
    }
    retained_evidence = tuple(
        _metadata_only_evidence(evidence)
        for evidence in glossary_snapshot.evidence
        if evidence.evidence_id in retained_evidence_ids
    )
    retained_payload = {
        "source_signature": source_signature,
        "retained_entry_ids": sorted(entry.entry_id for entry in retained_entries),
        "retained_evidence_ids": sorted(
            evidence.evidence_id for evidence in retained_evidence
        ),
        "policy_version": GLOSSARY_CANDIDATE_REDUCER_POLICY_VERSION,
    }
    return GlossarySnapshot(
        snapshot_id=f"glossary-reduced-snapshot:v1:{payload_digest(retained_payload)}",
        source_language=glossary_snapshot.source_language,
        target_language=glossary_snapshot.target_language,
        entries=tuple(sorted(retained_entries, key=lambda entry: entry.entry_id)),
        evidence=retained_evidence,
        policy_version=(
            f"{glossary_snapshot.policy_version}+"
            f"{GLOSSARY_CANDIDATE_REDUCER_POLICY_VERSION}"
        ),
        profile_signature=glossary_snapshot.profile_signature,
    )


def _reduction_payload(
    *,
    policy_version: str,
    source_glossary_signature: str,
    reduced_glossary_signature: str,
    profile_signature: str,
    pressure_signature: str,
    decisions: Sequence[GlossaryCandidateReductionDecision],
    caps: GlossaryCandidateReducerCaps,
) -> dict[str, Any]:
    status_counts = {
        status.value: sum(1 for decision in decisions if decision.status is status)
        for status in GlossaryCandidateDecisionStatus
    }
    return {
        "policy_version": policy_version,
        "source_glossary_signature": source_glossary_signature,
        "reduced_glossary_signature": reduced_glossary_signature,
        "profile_signature": profile_signature,
        "pressure_signature": pressure_signature,
        "decision_count": len(decisions),
        "status_counts": status_counts,
        "caps": {
            "max_editor_entries": caps.max_editor_entries,
            "max_diagnostic_entries": caps.max_diagnostic_entries,
            "max_estimated_editor_tokens": caps.max_estimated_editor_tokens,
            "min_editor_score": caps.min_editor_score,
            "min_diagnostic_score": caps.min_diagnostic_score,
        },
        "decisions": [_decision_payload(decision) for decision in decisions],
    }


def _decision_payload(decision: GlossaryCandidateReductionDecision) -> dict[str, Any]:
    return {
        "entry_id": decision.entry_id,
        "status": decision.status.value,
        "reasons": [reason.value for reason in decision.reasons],
        "evidence_refs": list(decision.evidence_refs),
        "score": decision.score,
        "estimated_prompt_tokens": decision.estimated_prompt_tokens,
        "category": decision.category,
        "layer": decision.layer,
        "original_status": decision.original_status,
        "confidence": decision.confidence,
        "source_digest": decision.source_digest,
        "source_char_count": decision.source_char_count,
    }


def _scored_sort_key(item: _ScoredCandidate) -> tuple[int, int, int, str]:
    return (
        -_priority_bucket(item),
        -item.score,
        item.estimated_prompt_tokens,
        item.entry.entry_id,
    )


def _priority_bucket(item: _ScoredCandidate) -> int:
    if GlossaryCandidateReductionReason.HARD_OR_PINNED in item.reasons:
        return 4
    if _entry_category(item.entry) in {
        GlossaryEntryCategory.NAME,
        GlossaryEntryCategory.TERM,
    }:
        return 3
    if _entry_category(item.entry) is GlossaryEntryCategory.ENTITY:
        return 2
    return 1


def _entry_category(entry: GlossaryEntry) -> GlossaryEntryCategory | None:
    if isinstance(entry.category, GlossaryEntryCategory):
        return entry.category
    try:
        return GlossaryEntryCategory(str(entry.category))
    except ValueError:
        return None


def _entry_layer(entry: GlossaryEntry) -> GlossaryLayer | None:
    if isinstance(entry.layer, GlossaryLayer):
        return entry.layer
    try:
        return GlossaryLayer(str(entry.layer))
    except ValueError:
        return None


def _entry_status(entry: GlossaryEntry) -> GlossaryEntryStatus | None:
    if isinstance(entry.status, GlossaryEntryStatus):
        return entry.status
    try:
        return GlossaryEntryStatus(str(entry.status))
    except ValueError:
        return None


def _is_noisy_surface(evidence: GlossaryEvidenceRef) -> bool:
    surface = _enum_value(evidence.surface)
    source_scope = evidence.source_scope.casefold()
    return surface in {
        GlossaryEvidenceSurface.NAV.value,
        GlossaryEvidenceSurface.TOC.value,
        GlossaryEvidenceSurface.METADATA.value,
    } or any(
        marker in source_scope
        for marker in ("frontmatter", "toc", "nav", "cover", "titlepage", "metadata")
    )


def _metadata_only_evidence(evidence: GlossaryEvidenceRef) -> GlossaryEvidenceRef:
    if evidence.raw_excerpt is None:
        return evidence
    return replace(evidence, raw_excerpt=None)


def _estimate_prompt_tokens(
    entry: GlossaryEntry,
    *,
    evidence_refs: Sequence[str],
) -> int:
    compact = " ".join(
        str(value)
        for value in (
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
            f"{_confidence(entry.confidence):.4f}",
            " ".join(evidence_refs),
            " ".join(entry.profile_rule_ids),
        )
    )
    return max(12, math.ceil(len(compact) / 4) + 12)


def _validate_caps(caps: GlossaryCandidateReducerCaps) -> None:
    if caps.max_editor_entries < 0:
        raise ValueError("max_editor_entries must be non-negative.")
    if caps.max_diagnostic_entries < 0:
        raise ValueError("max_diagnostic_entries must be non-negative.")
    if caps.max_estimated_editor_tokens < 0:
        raise ValueError("max_estimated_editor_tokens must be non-negative.")
    if caps.min_editor_score < 0:
        raise ValueError("min_editor_score must be non-negative.")
    if caps.min_diagnostic_score < 0:
        raise ValueError("min_diagnostic_score must be non-negative.")


def _pressure_context_signature(
    pressure_context: Mapping[str, Any] | None,
) -> str:
    if not pressure_context:
        return "glossary-pressure:none"
    pressure_digest = payload_digest(_metadata_digest_payload(pressure_context))
    return f"glossary-pressure:v1:{pressure_digest}"


def _metadata_digest_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _metadata_digest_payload(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_metadata_digest_payload(item) for item in value]
    if isinstance(value, set):
        return sorted(_metadata_digest_payload(item) for item in value)
    if isinstance(value, str):
        return {"text_digest": text_digest(value), "text_char_count": len(value)}
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return f"{value:.6f}" if math.isfinite(value) else str(value)
    return {"repr_digest": text_digest(repr(value)), "type": type(value).__name__}


def _confidence(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(float(value)):
            return min(1.0, max(0.0, float(value)))
    return 0.0


def _enum_value(value: Any) -> str:
    if isinstance(value, StrEnum):
        return value.value
    return str(value)



