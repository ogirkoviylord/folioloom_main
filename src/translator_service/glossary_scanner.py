from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from translator_service.documents import DocumentFormat
from translator_service.format_adapters.contracts import (
    FormatAdapterPlan,
    FormatTextBlock,
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
    GlossaryStrategy,
)
from translator_service.structure_optimizer import TextBlockKind

GLOSSARY_SCANNER_VERSION = "glossary-scanner-v1"

_SUPPORTED_SCANNER_FORMATS = frozenset(
    {
        DocumentFormat.TXT,
        DocumentFormat.DOCX,
        DocumentFormat.EPUB,
    }
)
_MAX_CANDIDATE_CHARS = 80
_CAPITALIZED_WORD_RE = r"(?:[A-Z][a-z]+|[A-Z]{2,})"
_HONORIFIC_RE = r"(?:Mr|Mrs|Ms|Miss|Dr|Prof|Professor|Sir|Lady)\.?"
_CAPITALIZED_PHRASE_RE = re.compile(
    rf"\b(?:{_HONORIFIC_RE}\s+)?{_CAPITALIZED_WORD_RE}(?:\s+{_CAPITALIZED_WORD_RE}){{0,3}}\b"
)
_CAPITALIZED_TOKEN_RE = re.compile(rf"\b{_CAPITALIZED_WORD_RE}\b")
_QUOTE_RE = re.compile(r"[\"']([^\"'\n]{2,80})[\"']")
_LOWER_TERM_TOKEN_RE = re.compile(r"\b[a-z][a-z0-9_-]{3,}\b")
_SPACE_RE = re.compile(r"\s+")

_NAME_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "chapter",
        "i",
        "ii",
        "iii",
        "iv",
        "one",
        "part",
        "prologue",
        "the",
        "volume",
    }
)
_TERM_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "also",
        "because",
        "before",
        "between",
        "chapter",
        "could",
        "first",
        "from",
        "have",
        "into",
        "later",
        "little",
        "more",
        "only",
        "other",
        "over",
        "said",
        "same",
        "some",
        "than",
        "that",
        "their",
        "then",
        "there",
        "they",
        "this",
        "through",
        "under",
        "very",
        "were",
        "when",
        "with",
        "would",
    }
)
_HONORIFIC_TOKENS = frozenset({"mr", "mrs", "ms", "miss", "dr", "prof", "professor"})


class GlossaryCandidateKind(StrEnum):
    CAPITALIZED_NAME = "capitalized_name"
    QUOTED_NAME = "quoted_name"
    REPEATED_TERM = "repeated_term"


@dataclass(frozen=True)
class _BlockRef:
    unit_sequence: int
    block: FormatTextBlock


@dataclass(frozen=True)
class _Occurrence:
    candidate: str
    category: GlossaryEntryCategory
    kind: GlossaryCandidateKind
    evidence_type: GlossaryEvidenceType
    unit_sequence: int
    source_block_id: str
    source_scope: str
    surface: GlossaryEvidenceSurface
    offset_bucket: str
    start_offset: int
    token_count: int


def scan_glossary_candidates(
    plan: FormatAdapterPlan,
    *,
    source_language: str = "Unknown",
    target_language: str = "Unknown",
    snapshot_id: str | None = None,
    max_evidence_refs_per_entry: int = 3,
) -> GlossarySnapshot:
    """Build deterministic local glossary candidates from adapter blocks.

    The scanner emits soft or diagnostic candidates only. It records metadata
    evidence anchors and never stores raw context excerpts.
    """

    if plan.document_format not in _SUPPORTED_SCANNER_FORMATS:
        raise ValueError(
            "Unsupported glossary scanner document format: "
            f"{plan.document_format.value}"
        )
    if max_evidence_refs_per_entry <= 0:
        raise ValueError("max_evidence_refs_per_entry must be positive")

    occurrences = _collect_occurrences(plan)
    accepted = _select_candidates(occurrences)
    entries: list[GlossaryEntry] = []
    evidence_refs: list[GlossaryEvidenceRef] = []

    for candidate_key in sorted(
        accepted,
        key=lambda key: (
            _category_sort_value(accepted[key][0].category),
            accepted[key][0].candidate.casefold(),
            accepted[key][0].unit_sequence,
            accepted[key][0].source_block_id,
            accepted[key][0].start_offset,
        ),
    ):
        candidate_occurrences = _sorted_occurrences(accepted[candidate_key])
        support_occurrences = _support_occurrences_for_candidate(
            candidate_occurrences[0],
            candidate_occurrences=candidate_occurrences,
            all_occurrences=occurrences.values(),
        )
        chosen_occurrences = support_occurrences[:max_evidence_refs_per_entry]
        entry_id = _entry_id(candidate_occurrences[0])
        evidence_ids = tuple(
            _evidence_id(entry_id, occurrence, index)
            for index, occurrence in enumerate(chosen_occurrences)
        )
        evidence_refs.extend(
            _evidence_ref(evidence_id, occurrence)
            for evidence_id, occurrence in zip(
                evidence_ids,
                chosen_occurrences,
                strict=True,
            )
        )
        aliases = _aliases_for_candidate(
            candidate_occurrences[0],
            all_occurrences=occurrences.values(),
        )
        entries.append(
            _entry_from_candidate(
                candidate_occurrences[0],
                evidence_ids=evidence_ids,
                aliases=aliases,
                occurrence_count=len(support_occurrences),
            )
        )

    return GlossarySnapshot(
        snapshot_id=snapshot_id or _snapshot_id(plan),
        source_language=source_language,
        target_language=target_language,
        entries=tuple(entries),
        evidence=tuple(evidence_refs),
        policy_version=GLOSSARY_SCANNER_VERSION,
        profile_signature="book-profile:unknown",
    )


def _collect_occurrences(plan: FormatAdapterPlan) -> dict[str, list[_Occurrence]]:
    occurrences: dict[str, list[_Occurrence]] = defaultdict(list)
    for block_ref in _iter_blocks(plan):
        text = block_ref.block.text
        _collect_quoted_candidates(block_ref, text, occurrences)
        _collect_capitalized_candidates(block_ref, text, occurrences)
        _collect_repeated_term_candidates(block_ref, text, occurrences)
    return dict(occurrences)


def _iter_blocks(plan: FormatAdapterPlan) -> Iterable[_BlockRef]:
    for unit in sorted(plan.units, key=lambda item: item.sequence):
        for block in sorted(unit.blocks, key=lambda item: item.index):
            if block.text.strip():
                yield _BlockRef(unit_sequence=unit.sequence, block=block)


def _collect_quoted_candidates(
    block_ref: _BlockRef,
    text: str,
    occurrences: dict[str, list[_Occurrence]],
) -> None:
    for match in _QUOTE_RE.finditer(text):
        candidate = _normalize_candidate(match.group(1))
        if not _valid_quoted_candidate(candidate):
            continue
        occurrence = _occurrence(
            candidate=candidate,
            category=GlossaryEntryCategory.ENTITY,
            kind=GlossaryCandidateKind.QUOTED_NAME,
            evidence_type=GlossaryEvidenceType.QUOTE_ATTRIBUTION,
            block_ref=block_ref,
            start_offset=match.start(1),
            token_count=len(candidate.split()),
        )
        occurrences[_candidate_key(occurrence)].append(occurrence)


def _collect_capitalized_candidates(
    block_ref: _BlockRef,
    text: str,
    occurrences: dict[str, list[_Occurrence]],
) -> None:
    for match in _CAPITALIZED_PHRASE_RE.finditer(text):
        candidate = _normalize_candidate(match.group(0))
        if not _valid_capitalized_candidate(candidate):
            continue
        occurrence = _occurrence(
            candidate=candidate,
            category=GlossaryEntryCategory.NAME,
            kind=GlossaryCandidateKind.CAPITALIZED_NAME,
            evidence_type=_evidence_type_for_block(block_ref.block),
            block_ref=block_ref,
            start_offset=match.start(),
            token_count=len(candidate.split()),
        )
        occurrences[_candidate_key(occurrence)].append(occurrence)

    for match in _CAPITALIZED_TOKEN_RE.finditer(text):
        candidate = _normalize_candidate(match.group(0))
        if not _valid_capitalized_token(candidate):
            continue
        occurrence = _occurrence(
            candidate=candidate,
            category=GlossaryEntryCategory.NAME,
            kind=GlossaryCandidateKind.CAPITALIZED_NAME,
            evidence_type=_evidence_type_for_block(block_ref.block),
            block_ref=block_ref,
            start_offset=match.start(),
            token_count=1,
        )
        occurrences[_candidate_key(occurrence)].append(occurrence)


def _collect_repeated_term_candidates(
    block_ref: _BlockRef,
    text: str,
    occurrences: dict[str, list[_Occurrence]],
) -> None:
    tokens = [
        match
        for match in _LOWER_TERM_TOKEN_RE.finditer(text)
        if match.group(0) not in _TERM_STOPWORDS
    ]
    for left, right in zip(tokens, tokens[1:], strict=False):
        if _sentence_gap(text[left.end() : right.start()]):
            continue
        candidate = f"{left.group(0)} {right.group(0)}"
        occurrence = _occurrence(
            candidate=candidate,
            category=GlossaryEntryCategory.TERM,
            kind=GlossaryCandidateKind.REPEATED_TERM,
            evidence_type=GlossaryEvidenceType.EXACT_REPEAT,
            block_ref=block_ref,
            start_offset=left.start(),
            token_count=2,
        )
        occurrences[_candidate_key(occurrence)].append(occurrence)


def _select_candidates(
    occurrences: dict[str, list[_Occurrence]],
) -> dict[str, list[_Occurrence]]:
    selected: dict[str, list[_Occurrence]] = {}
    for key, candidate_occurrences in occurrences.items():
        sorted_occurrences = _sorted_occurrences(candidate_occurrences)
        first = sorted_occurrences[0]
        if first.kind is GlossaryCandidateKind.QUOTED_NAME:
            selected[key] = sorted_occurrences
            continue
        if first.kind is GlossaryCandidateKind.REPEATED_TERM:
            if len(sorted_occurrences) >= 2:
                selected[key] = sorted_occurrences
            continue
        if first.kind is GlossaryCandidateKind.CAPITALIZED_NAME:
            if len(sorted_occurrences) >= 2 or _has_repeated_alias(
                first,
                occurrences,
            ):
                selected[key] = sorted_occurrences
    return _drop_alias_only_name_candidates(selected)


def _entry_from_candidate(
    occurrence: _Occurrence,
    *,
    evidence_ids: tuple[str, ...],
    aliases: tuple[str, ...],
    occurrence_count: int,
) -> GlossaryEntry:
    status = GlossaryEntryStatus.AUTO_DETECTED
    confidence = 0.5 + min(0.3, occurrence_count * 0.08)
    if occurrence.kind is GlossaryCandidateKind.QUOTED_NAME:
        status = GlossaryEntryStatus.UNCERTAIN
        confidence = 0.55 + min(0.2, occurrence_count * 0.05)
    if (
        occurrence.category is GlossaryEntryCategory.NAME
        and occurrence.token_count == 1
    ):
        status = GlossaryEntryStatus.UNCERTAIN
        confidence = min(confidence, 0.62)
    if occurrence.category is GlossaryEntryCategory.TERM:
        confidence = 0.58 + min(0.22, occurrence_count * 0.06)

    return GlossaryEntry(
        entry_id=_entry_id(occurrence),
        category=occurrence.category,
        layer=GlossaryLayer.SOFT,
        status=status,
        source_canonical=occurrence.candidate,
        aliases=aliases,
        evidence_refs=evidence_ids,
        confidence=round(confidence, 4),
        strategy=GlossaryStrategy.UNKNOWN,
        grammatical_gender=(
            GlossaryGender.UNKNOWN
            if occurrence.category is GlossaryEntryCategory.NAME
            else GlossaryGender.NOT_APPLICABLE
        ),
        morphology_notes=(
            "local_scanner_gender_unknown",
            "ru_uk_morphology_tbd",
        )
        if occurrence.category is GlossaryEntryCategory.NAME
        else (),
    )


def _evidence_ref(evidence_id: str, occurrence: _Occurrence) -> GlossaryEvidenceRef:
    return GlossaryEvidenceRef(
        evidence_id=evidence_id,
        evidence_type=occurrence.evidence_type,
        unit_sequence=occurrence.unit_sequence,
        source_block_id=occurrence.source_block_id,
        source_scope=occurrence.source_scope,
        surface=occurrence.surface,
        offset_bucket=occurrence.offset_bucket,
        occurrence_count=1,
        raw_excerpt=None,
    )


def _occurrence(
    *,
    candidate: str,
    category: GlossaryEntryCategory,
    kind: GlossaryCandidateKind,
    evidence_type: GlossaryEvidenceType,
    block_ref: _BlockRef,
    start_offset: int,
    token_count: int,
) -> _Occurrence:
    return _Occurrence(
        candidate=candidate,
        category=category,
        kind=kind,
        evidence_type=evidence_type,
        unit_sequence=block_ref.unit_sequence,
        source_block_id=block_ref.block.source_block_id,
        source_scope=_source_scope(block_ref.block),
        surface=_surface_for_block(block_ref.block),
        offset_bucket=_offset_bucket(start_offset, len(block_ref.block.text)),
        start_offset=start_offset,
        token_count=token_count,
    )


def _aliases_for_candidate(
    occurrence: _Occurrence,
    *,
    all_occurrences: Iterable[list[_Occurrence]],
) -> tuple[str, ...]:
    if occurrence.category is not GlossaryEntryCategory.NAME:
        return ()
    tokens = occurrence.candidate.split()
    if len(tokens) < 2:
        return ()

    normalized_aliases: dict[str, str] = {}
    normalized_tokens = _alias_tokens_for_name(occurrence)
    for candidate_occurrences in all_occurrences:
        candidate = candidate_occurrences[0].candidate
        if candidate == occurrence.candidate:
            continue
        candidate_tokens = candidate.split()
        if len(candidate_tokens) != 1 or len(candidate_occurrences) < 2:
            continue
        alias_key = _normalize_alias_token(candidate)
        if alias_key in normalized_tokens:
            normalized_aliases[alias_key] = candidate
    return tuple(
        normalized_aliases[key]
        for key in sorted(normalized_aliases, key=lambda item: item.casefold())
    )


def _support_occurrences_for_candidate(
    occurrence: _Occurrence,
    *,
    candidate_occurrences: list[_Occurrence],
    all_occurrences: Iterable[list[_Occurrence]],
) -> list[_Occurrence]:
    support = list(candidate_occurrences)
    if occurrence.category is not GlossaryEntryCategory.NAME:
        return _sorted_occurrences(support)
    alias_tokens = _alias_tokens_for_name(occurrence)
    if not alias_tokens:
        return _sorted_occurrences(support)

    canonical_locations = {
        (item.source_block_id, item.start_offset) for item in candidate_occurrences
    }
    seen = {
        (item.candidate, item.source_block_id, item.start_offset) for item in support
    }
    for alias_occurrences in all_occurrences:
        alias = alias_occurrences[0]
        if alias.token_count != 1:
            continue
        if _normalize_alias_token(alias.candidate) not in alias_tokens:
            continue
        if len(alias_occurrences) < 2:
            continue
        for alias_occurrence in alias_occurrences:
            location = (alias_occurrence.source_block_id, alias_occurrence.start_offset)
            identity = (
                alias_occurrence.candidate,
                alias_occurrence.source_block_id,
                alias_occurrence.start_offset,
            )
            if location in canonical_locations or identity in seen:
                continue
            support.append(alias_occurrence)
            seen.add(identity)
    return _sorted_occurrences(support)


def _alias_tokens_for_name(occurrence: _Occurrence) -> set[str]:
    tokens = occurrence.candidate.split()
    if len(tokens) < 2:
        return set()
    alias_tokens = {_normalize_alias_token(tokens[-1])}
    first_token = _normalize_alias_token(tokens[0])
    if first_token not in _HONORIFIC_TOKENS:
        alias_tokens.add(first_token)
    return alias_tokens


def _drop_alias_only_name_candidates(
    selected: dict[str, list[_Occurrence]],
) -> dict[str, list[_Occurrence]]:
    alias_tokens: set[str] = set()
    for candidate_occurrences in selected.values():
        occurrence = candidate_occurrences[0]
        if occurrence.category is not GlossaryEntryCategory.NAME:
            continue
        tokens = occurrence.candidate.split()
        if len(tokens) < 2:
            continue
        alias_tokens.add(_normalize_alias_token(tokens[0]))
        alias_tokens.add(_normalize_alias_token(tokens[-1]))

    if not alias_tokens:
        return selected

    return {
        key: candidate_occurrences
        for key, candidate_occurrences in selected.items()
        if not (
            candidate_occurrences[0].category is GlossaryEntryCategory.NAME
            and candidate_occurrences[0].token_count == 1
            and _normalize_alias_token(candidate_occurrences[0].candidate)
            in alias_tokens
        )
    }


def _has_repeated_alias(
    occurrence: _Occurrence,
    occurrences: dict[str, list[_Occurrence]],
) -> bool:
    alias_tokens = _alias_tokens_for_name(occurrence)
    if not alias_tokens:
        return False
    return any(
        len(candidate_occurrences) >= 2
        and candidate_occurrences[0].token_count == 1
        and _normalize_alias_token(candidate_occurrences[0].candidate) in alias_tokens
        for candidate_occurrences in occurrences.values()
    )


def _candidate_key(occurrence: _Occurrence) -> str:
    return f"{occurrence.category.value}:{occurrence.candidate.casefold()}"


def _entry_id(occurrence: _Occurrence) -> str:
    digest = _digest(
        "|".join(
            (
                occurrence.category.value,
                occurrence.kind.value,
                occurrence.candidate.casefold(),
            )
        )
    )
    return f"glossary-scan:{occurrence.category.value}:{digest}"


def _evidence_id(entry_id: str, occurrence: _Occurrence, index: int) -> str:
    digest = _digest(
        "|".join(
            (
                entry_id,
                occurrence.source_block_id,
                str(occurrence.unit_sequence),
                str(occurrence.start_offset),
                str(index),
            )
        )
    )
    return f"{entry_id}:ev:{digest}"


def _snapshot_id(plan: FormatAdapterPlan) -> str:
    digest = _digest(
        "|".join(
            (
                plan.document_format.value,
                plan.adapter_version,
                *(
                    f"{unit.sequence}:{block.source_block_id}:{_digest(block.text)}"
                    for unit in plan.units
                    for block in unit.blocks
                ),
            )
        )
    )
    return f"glossary-scan-snapshot:{plan.document_format.value}:{digest}"


def _sorted_occurrences(occurrences: list[_Occurrence]) -> list[_Occurrence]:
    return sorted(
        occurrences,
        key=lambda occurrence: (
            occurrence.unit_sequence,
            occurrence.source_block_id,
            occurrence.start_offset,
            occurrence.candidate.casefold(),
        ),
    )


def _category_sort_value(category: GlossaryEntryCategory) -> int:
    order = {
        GlossaryEntryCategory.NAME: 0,
        GlossaryEntryCategory.ENTITY: 1,
        GlossaryEntryCategory.TERM: 2,
    }
    return order.get(category, 99)


def _valid_quoted_candidate(candidate: str) -> bool:
    return (
        1 < len(candidate) <= _MAX_CANDIDATE_CHARS
        and not candidate.endswith((".", ",", ";", ":"))
        and any(character.isalpha() for character in candidate)
    )


def _valid_capitalized_candidate(candidate: str) -> bool:
    tokens = candidate.split()
    if not tokens or len(candidate) > _MAX_CANDIDATE_CHARS:
        return False
    if tokens[0].casefold().rstrip(".") in _NAME_STOPWORDS:
        return False
    if all(token.casefold().rstrip(".") in _NAME_STOPWORDS for token in tokens):
        return False
    return True


def _valid_capitalized_token(candidate: str) -> bool:
    return (
        _valid_capitalized_candidate(candidate)
        and len(candidate) > 2
        and candidate.casefold() not in _NAME_STOPWORDS
    )


def _normalize_candidate(candidate: str) -> str:
    return _SPACE_RE.sub(" ", candidate.strip(" \t\r\n.,;:!?()[]{}")).strip()


def _normalize_alias_token(candidate: str) -> str:
    return candidate.casefold().rstrip(".")


def _sentence_gap(text: str) -> bool:
    return any(character in ".!?\n" for character in text)


def _evidence_type_for_block(block: FormatTextBlock) -> GlossaryEvidenceType:
    if block.kind is TextBlockKind.HEADING:
        return GlossaryEvidenceType.HEADING
    return GlossaryEvidenceType.EXACT_REPEAT


def _surface_for_block(block: FormatTextBlock) -> GlossaryEvidenceSurface:
    if block.kind is TextBlockKind.HEADING:
        return GlossaryEvidenceSurface.HEADING
    if block.kind is TextBlockKind.FOOTNOTE:
        return GlossaryEvidenceSurface.FOOTNOTE
    return GlossaryEvidenceSurface.BODY


def _source_scope(block: FormatTextBlock) -> str:
    metadata = dict(block.metadata)
    if "file_name" in metadata:
        return metadata["file_name"]
    if block.group_id:
        return block.group_id
    return "global"


def _offset_bucket(start_offset: int, text_length: int) -> str:
    if text_length <= 0:
        return "unknown"
    ratio = start_offset / text_length
    if ratio < 0.34:
        return "early"
    if ratio < 0.67:
        return "middle"
    return "late"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
