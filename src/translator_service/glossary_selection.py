from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from translator_service.format_adapters.contracts import FormatTranslationUnit
from translator_service.glossary_contracts import (
    GlossaryEntry,
    GlossaryEntryCategory,
    GlossaryEvidenceRef,
    GlossaryLayer,
    GlossarySnapshot,
    glossary_snapshot_signature,
)

GLOSSARY_SELECTION_POLICY_VERSION = "glossary-selection-v1"

_WORD_RE = re.compile(r"[\w]+", flags=re.UNICODE)


class GlossarySelectionReason(StrEnum):
    HARD_CONSTRAINT = "hard_constraint"
    SOURCE_TEXT_MATCH = "source_text_match"
    ALIAS_TEXT_MATCH = "alias_text_match"
    EVIDENCE_ANCHOR_MATCH = "evidence_anchor_match"
    PROFILE_RULE_MATCH = "profile_rule_match"
    NO_RELEVANCE = "no_relevance"


class GlossaryDropReason(StrEnum):
    NOT_RELEVANT = "not_relevant"
    PROMPT_BUDGET_EXHAUSTED = "prompt_budget_exhausted"
    ENTRY_LIMIT_EXHAUSTED = "entry_limit_exhausted"
    CONFLICTS_WITH_HARD_ENTRY = "conflicts_with_hard_entry"
    CONFLICT_LOWER_PRIORITY = "conflict_lower_priority"


@dataclass(frozen=True)
class GlossarySelectionBudget:
    max_prompt_tokens: int
    max_entries: int = 32
    max_diagnostic_entries: int = 4


@dataclass(frozen=True)
class SelectedGlossaryEntry:
    entry_id: str
    layer: str
    category: str
    estimated_prompt_tokens: int
    relevance_score: int
    reasons: tuple[GlossarySelectionReason, ...]


@dataclass(frozen=True)
class DroppedGlossaryEntry:
    entry_id: str
    layer: str
    estimated_prompt_tokens: int
    relevance_score: int
    reason: GlossaryDropReason


@dataclass(frozen=True)
class WorkUnitGlossarySelection:
    work_unit_sequence: int
    source_block_ids: tuple[str, ...]
    prompt_budget_tokens: int
    estimated_prompt_tokens: int
    selected_entries: tuple[SelectedGlossaryEntry, ...]
    dropped_entries: tuple[DroppedGlossaryEntry, ...]
    glossary_signature: str
    selection_signature: str
    policy_version: str = GLOSSARY_SELECTION_POLICY_VERSION

    @property
    def selected_entry_ids(self) -> tuple[str, ...]:
        return tuple(entry.entry_id for entry in self.selected_entries)

    @property
    def dropped_entry_ids(self) -> tuple[str, ...]:
        return tuple(entry.entry_id for entry in self.dropped_entries)

    @property
    def budget_exceeded(self) -> bool:
        return self.estimated_prompt_tokens > self.prompt_budget_tokens


def select_glossary_subset_for_work_unit(
    work_unit: FormatTranslationUnit,
    glossary_snapshot: GlossarySnapshot,
    *,
    budget: GlossarySelectionBudget,
    profile_rule_ids: Iterable[str] = (),
) -> WorkUnitGlossarySelection:
    if budget.max_prompt_tokens < 0:
        raise ValueError("max_prompt_tokens must be non-negative.")
    if budget.max_entries < 0:
        raise ValueError("max_entries must be non-negative.")
    if budget.max_diagnostic_entries < 0:
        raise ValueError("max_diagnostic_entries must be non-negative.")

    evidence_by_id = {item.evidence_id: item for item in glossary_snapshot.evidence}
    selected_profile_rules = frozenset(str(item) for item in profile_rule_ids)
    scored = tuple(
        _score_entry(
            entry,
            work_unit=work_unit,
            evidence_by_id=evidence_by_id,
            selected_profile_rules=selected_profile_rules,
        )
        for entry in glossary_snapshot.entries
    )

    hard_entries = tuple(
        item for item in scored if _entry_layer(item.entry) is GlossaryLayer.HARD
    )
    selected: list[_ScoredEntry] = sorted(hard_entries, key=_selected_sort_key)
    dropped: list[DroppedGlossaryEntry] = []
    selected_ids = {item.entry.entry_id for item in selected}

    hard_source_keys = {_source_key(item.entry) for item in hard_entries}
    candidates: list[_ScoredEntry] = []
    for item in scored:
        if item.entry.entry_id in selected_ids:
            continue
        source_key = _source_key(item.entry)
        if source_key in hard_source_keys:
            dropped.append(
                _drop(item, GlossaryDropReason.CONFLICTS_WITH_HARD_ENTRY),
            )
        elif item.relevance_score <= 0:
            dropped.append(_drop(item, GlossaryDropReason.NOT_RELEVANT))
        else:
            candidates.append(item)

    candidates, conflict_drops = _drop_conflicting_lower_priority(candidates)
    dropped.extend(conflict_drops)

    used_tokens = sum(item.estimated_prompt_tokens for item in selected)
    selected_count = len(selected)
    diagnostic_count = sum(
        1 for item in selected if _entry_layer(item.entry) is GlossaryLayer.DIAGNOSTIC
    )

    for item in sorted(candidates, key=_candidate_sort_key):
        layer = _entry_layer(item.entry)
        if selected_count >= budget.max_entries:
            dropped.append(_drop(item, GlossaryDropReason.ENTRY_LIMIT_EXHAUSTED))
            continue
        if (
            layer is GlossaryLayer.DIAGNOSTIC
            and diagnostic_count >= budget.max_diagnostic_entries
        ):
            dropped.append(_drop(item, GlossaryDropReason.ENTRY_LIMIT_EXHAUSTED))
            continue
        if used_tokens + item.estimated_prompt_tokens > budget.max_prompt_tokens:
            dropped.append(_drop(item, GlossaryDropReason.PROMPT_BUDGET_EXHAUSTED))
            continue
        selected.append(item)
        selected_count += 1
        used_tokens += item.estimated_prompt_tokens
        if layer is GlossaryLayer.DIAGNOSTIC:
            diagnostic_count += 1

    selected_entries = tuple(
        _selected_entry(item) for item in sorted(selected, key=_selected_sort_key)
    )
    dropped_entries = tuple(sorted(dropped, key=_dropped_sort_key))
    glossary_signature = glossary_snapshot_signature(glossary_snapshot)
    payload = _selection_payload(
        work_unit_sequence=work_unit.sequence,
        source_block_ids=work_unit.source_block_ids,
        prompt_budget_tokens=budget.max_prompt_tokens,
        estimated_prompt_tokens=sum(
            entry.estimated_prompt_tokens for entry in selected_entries
        ),
        selected_entries=selected_entries,
        dropped_entries=dropped_entries,
        glossary_signature=glossary_signature,
    )
    return WorkUnitGlossarySelection(
        work_unit_sequence=work_unit.sequence,
        source_block_ids=work_unit.source_block_ids,
        prompt_budget_tokens=budget.max_prompt_tokens,
        estimated_prompt_tokens=payload["estimated_prompt_tokens"],
        selected_entries=selected_entries,
        dropped_entries=dropped_entries,
        glossary_signature=glossary_signature,
        selection_signature=f"glossary-selection:v1:{_payload_digest(payload)}",
    )


def select_glossary_subsets_for_units(
    work_units: Sequence[FormatTranslationUnit],
    glossary_snapshot: GlossarySnapshot,
    *,
    budget: GlossarySelectionBudget,
    profile_rule_ids: Iterable[str] = (),
) -> tuple[WorkUnitGlossarySelection, ...]:
    profile_rules = tuple(profile_rule_ids)
    return tuple(
        select_glossary_subset_for_work_unit(
            work_unit,
            glossary_snapshot,
            budget=budget,
            profile_rule_ids=profile_rules,
        )
        for work_unit in work_units
    )


def glossary_selection_metadata_payload(
    selection: WorkUnitGlossarySelection,
) -> dict[str, Any]:
    return {
        **_selection_payload(
            work_unit_sequence=selection.work_unit_sequence,
            source_block_ids=selection.source_block_ids,
            prompt_budget_tokens=selection.prompt_budget_tokens,
            estimated_prompt_tokens=selection.estimated_prompt_tokens,
            selected_entries=selection.selected_entries,
            dropped_entries=selection.dropped_entries,
            glossary_signature=selection.glossary_signature,
        ),
        "selection_signature": selection.selection_signature,
        "budget_exceeded": selection.budget_exceeded,
    }


@dataclass(frozen=True)
class _ScoredEntry:
    entry: GlossaryEntry
    estimated_prompt_tokens: int
    relevance_score: int
    reasons: tuple[GlossarySelectionReason, ...]


def _score_entry(
    entry: GlossaryEntry,
    *,
    work_unit: FormatTranslationUnit,
    evidence_by_id: Mapping[str, GlossaryEvidenceRef],
    selected_profile_rules: frozenset[str],
) -> _ScoredEntry:
    layer = _entry_layer(entry)
    reasons: list[GlossarySelectionReason] = []
    score = 0
    if layer is GlossaryLayer.HARD:
        reasons.append(GlossarySelectionReason.HARD_CONSTRAINT)
        score += 10_000

    unit_terms = _normalized_terms(work_unit.source_text)
    source_text = _normalize_text(entry.source_canonical)
    if source_text and source_text in unit_terms.full_text:
        reasons.append(GlossarySelectionReason.SOURCE_TEXT_MATCH)
        score += 700
    elif source_text and _token_overlap(source_text, unit_terms.tokens):
        reasons.append(GlossarySelectionReason.SOURCE_TEXT_MATCH)
        score += 160

    for alias in entry.aliases:
        alias_text = _normalize_text(alias)
        if alias_text and alias_text in unit_terms.full_text:
            reasons.append(GlossarySelectionReason.ALIAS_TEXT_MATCH)
            score += 320
            break

    if _has_evidence_anchor_match(entry, work_unit, evidence_by_id):
        reasons.append(GlossarySelectionReason.EVIDENCE_ANCHOR_MATCH)
        score += 520

    if selected_profile_rules.intersection(
        str(item) for item in entry.profile_rule_ids
    ):
        reasons.append(GlossarySelectionReason.PROFILE_RULE_MATCH)
        score += 180

    if not reasons:
        reasons.append(GlossarySelectionReason.NO_RELEVANCE)
    else:
        score += _confidence_points(entry.confidence)

    return _ScoredEntry(
        entry=entry,
        estimated_prompt_tokens=_estimate_prompt_tokens(entry),
        relevance_score=score,
        reasons=tuple(dict.fromkeys(reasons)),
    )


@dataclass(frozen=True)
class _NormalizedTerms:
    full_text: str
    tokens: frozenset[str]


def _normalized_terms(text: str) -> _NormalizedTerms:
    normalized = _normalize_text(text)
    return _NormalizedTerms(
        full_text=normalized,
        tokens=frozenset(_WORD_RE.findall(normalized)),
    )


def _has_evidence_anchor_match(
    entry: GlossaryEntry,
    work_unit: FormatTranslationUnit,
    evidence_by_id: Mapping[str, GlossaryEvidenceRef],
) -> bool:
    source_block_ids = frozenset(work_unit.source_block_ids)
    for evidence_id in entry.evidence_refs:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            continue
        if evidence.unit_sequence == work_unit.sequence:
            return True
        if evidence.source_block_id in source_block_ids:
            return True
    return False


def _drop_conflicting_lower_priority(
    candidates: Sequence[_ScoredEntry],
) -> tuple[list[_ScoredEntry], list[DroppedGlossaryEntry]]:
    by_source: dict[str, list[_ScoredEntry]] = {}
    for item in candidates:
        by_source.setdefault(_source_key(item.entry), []).append(item)

    kept: list[_ScoredEntry] = []
    dropped: list[DroppedGlossaryEntry] = []
    for items in by_source.values():
        if len(items) == 1 or not _has_conflict(items):
            kept.extend(items)
            continue
        winner = sorted(items, key=_candidate_sort_key)[0]
        kept.append(winner)
        for item in items:
            if item is not winner:
                dropped.append(_drop(item, GlossaryDropReason.CONFLICT_LOWER_PRIORITY))
    return kept, dropped


def _has_conflict(items: Sequence[_ScoredEntry]) -> bool:
    targets = {
        (
            _normalize_text(item.entry.target_canonical or ""),
            str(item.entry.strategy),
        )
        for item in items
    }
    return len(targets) > 1


def _selected_entry(item: _ScoredEntry) -> SelectedGlossaryEntry:
    return SelectedGlossaryEntry(
        entry_id=item.entry.entry_id,
        layer=_entry_layer(item.entry).value,
        category=_entry_category(item.entry),
        estimated_prompt_tokens=item.estimated_prompt_tokens,
        relevance_score=item.relevance_score,
        reasons=item.reasons,
    )


def _drop(item: _ScoredEntry, reason: GlossaryDropReason) -> DroppedGlossaryEntry:
    return DroppedGlossaryEntry(
        entry_id=item.entry.entry_id,
        layer=_entry_layer(item.entry).value,
        estimated_prompt_tokens=item.estimated_prompt_tokens,
        relevance_score=item.relevance_score,
        reason=reason,
    )


def _selection_payload(
    *,
    work_unit_sequence: int,
    source_block_ids: Iterable[str],
    prompt_budget_tokens: int,
    estimated_prompt_tokens: int,
    selected_entries: Iterable[SelectedGlossaryEntry],
    dropped_entries: Iterable[DroppedGlossaryEntry],
    glossary_signature: str,
) -> dict[str, Any]:
    return {
        "policy_version": GLOSSARY_SELECTION_POLICY_VERSION,
        "work_unit_sequence": work_unit_sequence,
        "source_block_ids": sorted(str(item) for item in source_block_ids),
        "prompt_budget_tokens": prompt_budget_tokens,
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "glossary_signature": glossary_signature,
        "selected_entries": [
            {
                "entry_id": item.entry_id,
                "layer": item.layer,
                "category": item.category,
                "estimated_prompt_tokens": item.estimated_prompt_tokens,
                "relevance_score": item.relevance_score,
                "reasons": sorted(reason.value for reason in item.reasons),
            }
            for item in selected_entries
        ],
        "dropped_entries": [
            {
                "entry_id": item.entry_id,
                "layer": item.layer,
                "estimated_prompt_tokens": item.estimated_prompt_tokens,
                "relevance_score": item.relevance_score,
                "reason": item.reason.value,
            }
            for item in dropped_entries
        ],
    }


def _estimate_prompt_tokens(entry: GlossaryEntry) -> int:
    compact_text = " ".join(
        str(value)
        for value in (
            entry.entry_id,
            entry.category,
            entry.layer,
            entry.status,
            entry.source_canonical,
            " ".join(entry.aliases),
            entry.target_canonical or "",
            " ".join(entry.target_variants),
            " ".join(entry.forbidden_variants),
            entry.strategy,
            entry.grammatical_gender,
            " ".join(entry.profile_rule_ids),
        )
    )
    return max(1, math.ceil(len(compact_text) / 4))


def _candidate_sort_key(item: _ScoredEntry) -> tuple[int, int, int, str]:
    return (
        _layer_priority(_entry_layer(item.entry)),
        -item.relevance_score,
        item.estimated_prompt_tokens,
        item.entry.entry_id,
    )


def _selected_sort_key(item: _ScoredEntry) -> tuple[int, str]:
    return (_layer_priority(_entry_layer(item.entry)), item.entry.entry_id)


def _dropped_sort_key(item: DroppedGlossaryEntry) -> tuple[str, str]:
    return (item.reason.value, item.entry_id)


def _entry_layer(entry: GlossaryEntry) -> GlossaryLayer:
    if isinstance(entry.layer, GlossaryLayer):
        return entry.layer
    return GlossaryLayer(str(entry.layer))


def _entry_category(entry: GlossaryEntry) -> str:
    if isinstance(entry.category, GlossaryEntryCategory):
        return entry.category.value
    return str(entry.category)


def _layer_priority(layer: GlossaryLayer) -> int:
    if layer is GlossaryLayer.HARD:
        return 0
    if layer is GlossaryLayer.SOFT:
        return 1
    return 2


def _source_key(entry: GlossaryEntry) -> str:
    return _normalize_text(entry.source_canonical)


def _normalize_text(value: str) -> str:
    return " ".join(str(value).casefold().split())


def _token_overlap(text: str, tokens: frozenset[str]) -> bool:
    text_tokens = frozenset(_WORD_RE.findall(text))
    if not text_tokens:
        return False
    return bool(text_tokens.intersection(tokens))


def _confidence_points(value: float) -> int:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return 0
    if not math.isfinite(float(value)):
        return 0
    return max(0, min(100, round(float(value) * 100)))


def _payload_digest(payload: Mapping[str, Any] | Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]
