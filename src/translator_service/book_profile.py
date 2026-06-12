from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from translator_service.format_adapters.contracts import (
    FormatAdapterPlan,
    FormatTextBlock,
)
from translator_service.glossary_contracts import (
    GlossaryEntryCategory,
    GlossaryEvidenceRef,
    GlossaryEvidenceSurface,
    GlossaryEvidenceType,
    GlossarySnapshot,
    GlossaryStrategy,
)
from translator_service.source_pair_profiles import source_pair_profile_signature
from translator_service.structure_optimizer import TextBlockKind
from translator_service.text_analysis import TextType, detect_text_type
from translator_service.translation_profiles import target_language_policy_signature

BOOK_PROFILE_SCHEMA_VERSION = "book-profile-v1"
PROFILE_GLOSSARY_RULE_SCHEMA_VERSION = "profile-glossary-rule-v1"
BOOK_PROFILE_DETECTOR_VERSION = "book-profile-detector-v1"

_SPACE_RE = re.compile(r"\s+")
_QUOTE_RE = re.compile(r'["“”«»]')


class BookDocumentType(StrEnum):
    BOOK_MANUSCRIPT = "book_manuscript"
    ARTICLE_OR_ESSAY = "article_or_essay"
    TECHNICAL_DOCUMENT = "technical_document"
    BUSINESS_LEGAL_DOCUMENT = "business_legal_document"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class BookProfileKind(StrEnum):
    LITERARY_FICTION = "literary_fiction"
    LITERARY_NON_FICTION = "literary_non_fiction"
    JOURNALISTIC_PUBLICISTIC = "journalistic_publicistic"
    SCIENTIFIC_ACADEMIC = "scientific_academic"
    RELIGIOUS_PHILOSOPHICAL = "religious_philosophical"
    TECHNICAL = "technical"
    BUSINESS_LEGAL_LIKE = "business_legal_like"
    EDUCATIONAL = "educational"
    MARKETING = "marketing"
    HISTORICAL = "historical"
    MEMOIR = "memoir"
    MIXED_UNKNOWN = "mixed_unknown"
    UNKNOWN = "unknown"


class Fictionality(StrEnum):
    FICTION = "fiction"
    NON_FICTION = "non_fiction"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class DialogueDensity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class BookRegister(StrEnum):
    LITERARY = "literary"
    FORMAL = "formal"
    PUBLICISTIC = "publicistic"
    ACADEMIC = "academic"
    TECHNICAL = "technical"
    NEUTRAL = "neutral"
    MARKETING = "marketing"
    UNKNOWN = "unknown"


class TerminologyStrictness(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class ParaphraseAllowance(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class NamedEntityPolicy(StrEnum):
    CONTEXTUAL = "contextual"
    PRESERVE_OFFICIAL_NAMES = "preserve_official_names"
    PRESERVE_EXACT = "preserve_exact"
    TRANSLITERATE_PERSON_NAMES = "transliterate_person_names"
    UNKNOWN = "unknown"


class ProfileGlossaryRuleType(StrEnum):
    NAMED_ENTITY_STRATEGY = "named_entity_strategy"
    TERMINOLOGY_STRATEGY = "terminology_strategy"
    STYLE_CONSTRAINT = "style_constraint"
    FALLBACK = "fallback"


class BookProfileValidationCode(StrEnum):
    MISSING_FIELD = "missing_field"
    INVALID_ENUM = "invalid_enum"
    INVALID_CONFIDENCE = "invalid_confidence"
    INVALID_SOURCE_ANCHOR = "invalid_source_anchor"
    MISSING_EVIDENCE = "missing_evidence"
    DUPLICATE_ID = "duplicate_id"
    INVALID_SCHEMA_VERSION = "invalid_schema_version"
    RAW_TEXT_NOT_ALLOWED = "raw_text_not_allowed"


@dataclass(frozen=True)
class BookProfile:
    profile_id: str
    source_language: str
    target_language: str
    primary_profile: BookProfileKind | str
    document_type: BookDocumentType | str
    fictionality: Fictionality | str
    dialogue_density: DialogueDensity | str
    register: BookRegister | str
    confidence: float
    evidence_refs: tuple[str, ...]
    schema_version: str = BOOK_PROFILE_SCHEMA_VERSION
    secondary_profiles: tuple[BookProfileKind | str, ...] = ()
    domain_hints: tuple[str, ...] = ()
    terminology_strictness: TerminologyStrictness | str = TerminologyStrictness.UNKNOWN
    paraphrase_allowance: ParaphraseAllowance | str = ParaphraseAllowance.UNKNOWN
    named_entity_policy: NamedEntityPolicy | str = NamedEntityPolicy.UNKNOWN
    source_pair_policy: str = "source-pair:none"
    target_language_policy: str = "target-profile:default-v1"
    uncertainty_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfileSpecificGlossaryRule:
    rule_id: str
    rule_type: ProfileGlossaryRuleType | str
    applies_to_profiles: tuple[BookProfileKind | str, ...]
    scope_category: GlossaryEntryCategory | str
    target_languages: tuple[str, ...]
    glossary_strategy: GlossaryStrategy | str
    terminology_strictness: TerminologyStrictness | str
    paraphrase_allowance: ParaphraseAllowance | str
    named_entity_policy: NamedEntityPolicy | str
    fallback_strategy: GlossaryStrategy | str
    evidence_refs: tuple[str, ...]
    schema_version: str = PROFILE_GLOSSARY_RULE_SCHEMA_VERSION
    requires_review: bool = False


@dataclass(frozen=True)
class BookProfileDetection:
    profile: BookProfile
    rules: tuple[ProfileSpecificGlossaryRule, ...]
    evidence: tuple[GlossaryEvidenceRef, ...]
    detector_version: str = BOOK_PROFILE_DETECTOR_VERSION


@dataclass(frozen=True)
class BookProfileValidationIssue:
    code: BookProfileValidationCode
    path: str
    message: str


@dataclass(frozen=True)
class BookProfileValidationResult:
    issues: tuple[BookProfileValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class _BlockRef:
    unit_sequence: int
    block: FormatTextBlock


@dataclass(frozen=True)
class _Signal:
    profile: BookProfileKind
    domain_hint: str
    evidence_type: GlossaryEvidenceType
    unit_sequence: int
    source_block_id: str
    source_scope: str
    surface: GlossaryEvidenceSurface
    offset_bucket: str
    start_offset: int


_MARKER_PROFILES: tuple[tuple[BookProfileKind, str, tuple[str, ...]], ...] = (
    (
        BookProfileKind.SCIENTIFIC_ACADEMIC,
        "science",
        (
            "methodology",
            "hypothesis",
            "sample size",
            "statistically",
            "citation",
            "results suggest",
            "data indicate",
            "conclusion",
        ),
    ),
    (
        BookProfileKind.TECHNICAL,
        "technical",
        (
            "api",
            "endpoint",
            "json",
            "xml",
            "function",
            "callback",
            "database",
            "server",
            "command",
            "token",
        ),
    ),
    (
        BookProfileKind.BUSINESS_LEGAL_LIKE,
        "legal",
        (
            "agreement",
            "contract",
            "shall",
            "obligation",
            "liability",
            "party",
            "terms and conditions",
        ),
    ),
    (
        BookProfileKind.JOURNALISTIC_PUBLICISTIC,
        "publicistic",
        (
            "according to",
            "officials said",
            "reported",
            "statement",
            "minister",
            "government",
            "policy",
        ),
    ),
    (
        BookProfileKind.RELIGIOUS_PHILOSOPHICAL,
        "religious_philosophical",
        (
            "doctrine",
            "scripture",
            "prayer",
            "soul",
            "faith",
            "virtue",
            "metaphysics",
            "ethics",
        ),
    ),
    (
        BookProfileKind.EDUCATIONAL,
        "educational",
        (
            "lesson",
            "exercise",
            "students",
            "chapter explains",
            "learning objective",
        ),
    ),
    (
        BookProfileKind.MARKETING,
        "marketing",
        (
            "limited offer",
            "subscribe",
            "customers love",
            "guarantee",
            "benefits",
        ),
    ),
    (
        BookProfileKind.HISTORICAL,
        "historical",
        (
            "century",
            "empire",
            "archive",
            "chronicle",
            "kingdom",
        ),
    ),
    (
        BookProfileKind.MEMOIR,
        "memoir",
        (
            "i remember",
            "my childhood",
            "diary",
            "memoir",
        ),
    ),
    (
        BookProfileKind.LITERARY_FICTION,
        "literary",
        (
            "whispered",
            "silence",
            "heart",
            "window",
            "narrator",
            "voice",
        ),
    ),
)

_TEXT_TYPE_PROFILE_MAP = {
    TextType.LITERARY_FICTION: BookProfileKind.LITERARY_FICTION,
    TextType.LITERARY_NON_FICTION: BookProfileKind.LITERARY_NON_FICTION,
    TextType.JOURNALISTIC_PUBLICISTIC: BookProfileKind.JOURNALISTIC_PUBLICISTIC,
    TextType.SCIENTIFIC_ACADEMIC: BookProfileKind.SCIENTIFIC_ACADEMIC,
    TextType.TECHNICAL: BookProfileKind.TECHNICAL,
    TextType.BUSINESS_LEGAL_LIKE: BookProfileKind.BUSINESS_LEGAL_LIKE,
    TextType.EDUCATIONAL: BookProfileKind.EDUCATIONAL,
    TextType.MARKETING: BookProfileKind.MARKETING,
}


def detect_book_profile(
    plan: FormatAdapterPlan,
    *,
    source_language: str,
    target_language: str,
    glossary_snapshot: GlossarySnapshot | None = None,
) -> BookProfileDetection:
    blocks = tuple(_iter_blocks(plan))
    joined_text = "\n\n".join(block_ref.block.text for block_ref in blocks)
    signals = _collect_signals(blocks)
    scores = _score_profiles(
        joined_text,
        signals=signals,
        glossary_snapshot=glossary_snapshot,
    )
    primary_profile, secondary_profiles = _select_profile(scores)
    dialogue_density = _dialogue_density(blocks)
    domain_hints = _domain_hints(signals, primary_profile=primary_profile)
    evidence = _profile_evidence(signals, primary_profile=primary_profile)
    evidence_refs = tuple(item.evidence_id for item in evidence)
    confidence = _profile_confidence(
        primary_profile,
        scores=scores,
        evidence_count=len(evidence_refs),
    )
    uncertainty_notes = _uncertainty_notes(
        primary_profile=primary_profile,
        confidence=confidence,
    )
    profile = BookProfile(
        profile_id=_profile_id(
            primary_profile=primary_profile,
            source_language=source_language,
            target_language=target_language,
            evidence_refs=evidence_refs,
        ),
        source_language=source_language,
        target_language=target_language,
        primary_profile=primary_profile,
        secondary_profiles=secondary_profiles,
        document_type=_document_type(primary_profile),
        fictionality=_fictionality(primary_profile, dialogue_density),
        dialogue_density=dialogue_density,
        register=_register(primary_profile),
        domain_hints=domain_hints,
        terminology_strictness=_terminology_strictness(primary_profile),
        paraphrase_allowance=_paraphrase_allowance(primary_profile),
        named_entity_policy=_named_entity_policy(primary_profile),
        confidence=confidence,
        evidence_refs=evidence_refs,
        source_pair_policy=source_pair_profile_signature(
            source_language,
            target_language,
        ),
        target_language_policy=target_language_policy_signature(target_language),
        uncertainty_notes=uncertainty_notes,
    )
    return BookProfileDetection(
        profile=profile,
        rules=select_profile_glossary_rules(profile),
        evidence=evidence,
    )


def select_profile_glossary_rules(
    profile: BookProfile,
) -> tuple[ProfileSpecificGlossaryRule, ...]:
    primary_profile = _profile_enum_value(profile.primary_profile)
    evidence_refs = profile.evidence_refs
    target_language = _language_root(profile.target_language)
    if primary_profile in {BookProfileKind.UNKNOWN, BookProfileKind.MIXED_UNKNOWN}:
        return (
            _fallback_rule_for_profile(
                primary_profile,
                target_language,
                evidence_refs,
                shared_unknown=True,
            ),
        )
    rule = _rule_for_profile(primary_profile, target_language, evidence_refs)
    if rule is None:
        rule = _fallback_rule_for_profile(
            primary_profile,
            target_language,
            evidence_refs,
        )
    return (rule,)


def validate_book_profile_detection(
    detection: BookProfileDetection,
) -> BookProfileValidationResult:
    issues: list[BookProfileValidationIssue] = []
    if detection.detector_version != BOOK_PROFILE_DETECTOR_VERSION:
        _add_issue(
            issues,
            BookProfileValidationCode.INVALID_SCHEMA_VERSION,
            "detector_version",
            f"detector_version must be {BOOK_PROFILE_DETECTOR_VERSION}.",
        )

    evidence_ids: set[str] = set()
    for index, evidence in enumerate(detection.evidence):
        path = f"evidence[{index}]"
        if not _non_empty_text(evidence.evidence_id):
            _add_issue(
                issues,
                BookProfileValidationCode.MISSING_FIELD,
                f"{path}.evidence_id",
                "evidence_id is required.",
            )
        elif evidence.evidence_id in evidence_ids:
            _add_issue(
                issues,
                BookProfileValidationCode.DUPLICATE_ID,
                f"{path}.evidence_id",
                "evidence_id must be unique.",
            )
        else:
            evidence_ids.add(evidence.evidence_id)
        _validate_evidence_ref(evidence, issues=issues, path=path)

    _validate_profile(
        detection.profile,
        evidence_ids=evidence_ids,
        issues=issues,
    )
    _validate_rules(
        detection.rules,
        evidence_ids=evidence_ids,
        issues=issues,
    )
    return BookProfileValidationResult(issues=tuple(issues))


def _iter_blocks(plan: FormatAdapterPlan) -> Iterable[_BlockRef]:
    for unit in sorted(plan.units, key=lambda item: item.sequence):
        for block in sorted(unit.blocks, key=lambda item: item.index):
            if block.text.strip():
                yield _BlockRef(unit_sequence=unit.sequence, block=block)


def _collect_signals(blocks: tuple[_BlockRef, ...]) -> list[_Signal]:
    signals: list[_Signal] = []
    for block_ref in blocks:
        normalized = _normalize_text(block_ref.block.text)
        for profile, domain_hint, markers in _MARKER_PROFILES:
            for marker in markers:
                start_offset = normalized.find(marker)
                if start_offset < 0:
                    continue
                signals.append(
                    _signal(
                        profile=profile,
                        domain_hint=domain_hint,
                        evidence_type=_evidence_type_for_block(block_ref.block),
                        block_ref=block_ref,
                        start_offset=start_offset,
                    )
                )
        if block_ref.block.kind is TextBlockKind.HEADING:
            heading = normalized
            if any(term in heading for term in ("chapter", "prologue", "scene")):
                signals.append(
                    _signal(
                        profile=BookProfileKind.LITERARY_FICTION,
                        domain_hint="literary",
                        evidence_type=GlossaryEvidenceType.HEADING,
                        block_ref=block_ref,
                        start_offset=0,
                    )
                )
            if any(term in heading for term in ("method", "results", "study")):
                signals.append(
                    _signal(
                        profile=BookProfileKind.SCIENTIFIC_ACADEMIC,
                        domain_hint="science",
                        evidence_type=GlossaryEvidenceType.HEADING,
                        block_ref=block_ref,
                        start_offset=0,
                    )
                )
    return signals


def _score_profiles(
    text: str,
    *,
    signals: list[_Signal],
    glossary_snapshot: GlossarySnapshot | None,
) -> Counter[BookProfileKind]:
    scores: Counter[BookProfileKind] = Counter()
    text_type = detect_text_type(text)
    if text_type in _TEXT_TYPE_PROFILE_MAP:
        scores[_TEXT_TYPE_PROFILE_MAP[text_type]] += 2
    for signal in signals:
        scores[signal.profile] += 1
    if glossary_snapshot is not None:
        name_count = sum(
            1
            for entry in glossary_snapshot.entries
            if entry.category == GlossaryEntryCategory.NAME
        )
        term_count = sum(
            1
            for entry in glossary_snapshot.entries
            if entry.category == GlossaryEntryCategory.TERM
        )
        if name_count >= 2:
            scores[BookProfileKind.LITERARY_FICTION] += 1
        if term_count >= 2:
            scores[BookProfileKind.TECHNICAL] += 1
            scores[BookProfileKind.SCIENTIFIC_ACADEMIC] += 1
    if _QUOTE_RE.findall(text) and len(_QUOTE_RE.findall(text)) >= 4:
        scores[BookProfileKind.LITERARY_FICTION] += 2
    return scores


def _select_profile(
    scores: Counter[BookProfileKind],
) -> tuple[BookProfileKind, tuple[BookProfileKind, ...]]:
    if not scores:
        return BookProfileKind.UNKNOWN, ()
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0].value))
    primary, primary_score = ranked[0]
    secondary = tuple(profile for profile, score in ranked[1:3] if score > 0)
    if primary_score <= 1:
        return BookProfileKind.UNKNOWN, secondary
    if len(ranked) > 1 and ranked[1][1] == primary_score:
        return BookProfileKind.MIXED_UNKNOWN, tuple(
            profile for profile, _ in ranked[:3]
        )
    return primary, secondary


def _profile_evidence(
    signals: list[_Signal],
    *,
    primary_profile: BookProfileKind,
    max_refs: int = 6,
) -> tuple[GlossaryEvidenceRef, ...]:
    matching = [
        signal
        for signal in signals
        if signal.profile is primary_profile
        or primary_profile is BookProfileKind.MIXED_UNKNOWN
    ]
    evidence: list[GlossaryEvidenceRef] = []
    seen: set[tuple[int, str, int, BookProfileKind]] = set()
    for signal in sorted(
        matching,
        key=lambda item: (
            item.unit_sequence,
            item.source_block_id,
            item.start_offset,
            item.profile.value,
        ),
    ):
        identity = (
            signal.unit_sequence,
            signal.source_block_id,
            signal.start_offset,
            signal.profile,
        )
        if identity in seen:
            continue
        seen.add(identity)
        evidence_id = _evidence_id(signal, len(evidence))
        evidence.append(
            GlossaryEvidenceRef(
                evidence_id=evidence_id,
                evidence_type=signal.evidence_type,
                unit_sequence=signal.unit_sequence,
                source_block_id=signal.source_block_id,
                source_scope=signal.source_scope,
                surface=signal.surface,
                offset_bucket=signal.offset_bucket,
                occurrence_count=1,
                raw_excerpt=None,
            )
        )
        if len(evidence) >= max_refs:
            break
    return tuple(evidence)


def _rule_for_profile(
    profile: BookProfileKind,
    target_language: str,
    evidence_refs: tuple[str, ...],
) -> ProfileSpecificGlossaryRule | None:
    if profile is BookProfileKind.LITERARY_FICTION:
        return ProfileSpecificGlossaryRule(
            rule_id="profile-rule:literary-fiction:names-v1",
            rule_type=ProfileGlossaryRuleType.NAMED_ENTITY_STRATEGY,
            applies_to_profiles=(BookProfileKind.LITERARY_FICTION,),
            scope_category=GlossaryEntryCategory.NAME,
            target_languages=(target_language,),
            glossary_strategy=GlossaryStrategy.CONTEXTUAL,
            terminology_strictness=TerminologyStrictness.MEDIUM,
            paraphrase_allowance=ParaphraseAllowance.MEDIUM,
            named_entity_policy=NamedEntityPolicy.CONTEXTUAL,
            fallback_strategy=GlossaryStrategy.TRANSLITERATE,
            evidence_refs=evidence_refs[:2],
            requires_review=False,
        )
    if profile is BookProfileKind.SCIENTIFIC_ACADEMIC:
        return ProfileSpecificGlossaryRule(
            rule_id="profile-rule:scientific-academic:terms-v1",
            rule_type=ProfileGlossaryRuleType.TERMINOLOGY_STRATEGY,
            applies_to_profiles=(BookProfileKind.SCIENTIFIC_ACADEMIC,),
            scope_category=GlossaryEntryCategory.TERM,
            target_languages=(target_language,),
            glossary_strategy=GlossaryStrategy.PRESERVE_OFFICIAL,
            terminology_strictness=TerminologyStrictness.HIGH,
            paraphrase_allowance=ParaphraseAllowance.LOW,
            named_entity_policy=NamedEntityPolicy.PRESERVE_OFFICIAL_NAMES,
            fallback_strategy=GlossaryStrategy.TRANSLATE_MEANING,
            evidence_refs=evidence_refs[:2],
            requires_review=False,
        )
    if profile in {BookProfileKind.TECHNICAL, BookProfileKind.BUSINESS_LEGAL_LIKE}:
        return ProfileSpecificGlossaryRule(
            rule_id=f"profile-rule:{profile.value}:exact-entities-v1",
            rule_type=ProfileGlossaryRuleType.TERMINOLOGY_STRATEGY,
            applies_to_profiles=(profile,),
            scope_category=GlossaryEntryCategory.ENTITY,
            target_languages=(target_language,),
            glossary_strategy=GlossaryStrategy.PRESERVE_EXACT,
            terminology_strictness=TerminologyStrictness.HIGH,
            paraphrase_allowance=ParaphraseAllowance.LOW,
            named_entity_policy=NamedEntityPolicy.PRESERVE_OFFICIAL_NAMES,
            fallback_strategy=GlossaryStrategy.PRESERVE_EXACT,
            evidence_refs=evidence_refs[:2],
            requires_review=False,
        )
    if profile is BookProfileKind.JOURNALISTIC_PUBLICISTIC:
        return ProfileSpecificGlossaryRule(
            rule_id="profile-rule:journalistic:attribution-v1",
            rule_type=ProfileGlossaryRuleType.STYLE_CONSTRAINT,
            applies_to_profiles=(BookProfileKind.JOURNALISTIC_PUBLICISTIC,),
            scope_category=GlossaryEntryCategory.ENTITY,
            target_languages=(target_language,),
            glossary_strategy=GlossaryStrategy.PRESERVE_OFFICIAL,
            terminology_strictness=TerminologyStrictness.MEDIUM,
            paraphrase_allowance=ParaphraseAllowance.MEDIUM,
            named_entity_policy=NamedEntityPolicy.PRESERVE_OFFICIAL_NAMES,
            fallback_strategy=GlossaryStrategy.CONTEXTUAL,
            evidence_refs=evidence_refs[:2],
            requires_review=False,
        )
    if profile is BookProfileKind.RELIGIOUS_PHILOSOPHICAL:
        return ProfileSpecificGlossaryRule(
            rule_id="profile-rule:religious-philosophical:terms-v1",
            rule_type=ProfileGlossaryRuleType.TERMINOLOGY_STRATEGY,
            applies_to_profiles=(BookProfileKind.RELIGIOUS_PHILOSOPHICAL,),
            scope_category=GlossaryEntryCategory.TERM,
            target_languages=(target_language,),
            glossary_strategy=GlossaryStrategy.CONTEXTUAL,
            terminology_strictness=TerminologyStrictness.HIGH,
            paraphrase_allowance=ParaphraseAllowance.LOW,
            named_entity_policy=NamedEntityPolicy.CONTEXTUAL,
            fallback_strategy=GlossaryStrategy.UNKNOWN,
            evidence_refs=evidence_refs[:2],
            requires_review=True,
        )
    return None


def _fallback_rule_for_profile(
    profile: BookProfileKind,
    target_language: str,
    evidence_refs: tuple[str, ...],
    *,
    shared_unknown: bool = False,
) -> ProfileSpecificGlossaryRule:
    applies_to_profiles = (profile,)
    rule_id = f"profile-rule:{profile.value}:review-fallback-v1"
    if shared_unknown:
        applies_to_profiles = (
            BookProfileKind.UNKNOWN,
            BookProfileKind.MIXED_UNKNOWN,
        )
        rule_id = "profile-rule:base-conservative:v1"
    return ProfileSpecificGlossaryRule(
        rule_id=rule_id,
        rule_type=ProfileGlossaryRuleType.FALLBACK,
        applies_to_profiles=applies_to_profiles,
        scope_category=GlossaryEntryCategory.TERM,
        target_languages=(target_language,),
        glossary_strategy=GlossaryStrategy.UNKNOWN,
        terminology_strictness=TerminologyStrictness.UNKNOWN,
        paraphrase_allowance=ParaphraseAllowance.UNKNOWN,
        named_entity_policy=NamedEntityPolicy.UNKNOWN,
        fallback_strategy=GlossaryStrategy.UNKNOWN,
        evidence_refs=evidence_refs[:1],
        requires_review=True,
    )


def _profile_confidence(
    primary_profile: BookProfileKind,
    *,
    scores: Counter[BookProfileKind],
    evidence_count: int,
) -> float:
    if primary_profile in {BookProfileKind.UNKNOWN, BookProfileKind.MIXED_UNKNOWN}:
        return 0.25 if primary_profile is BookProfileKind.UNKNOWN else 0.45
    score = scores.get(primary_profile, 0)
    return round(min(0.9, 0.45 + score * 0.08 + evidence_count * 0.02), 4)


def _document_type(profile: BookProfileKind) -> BookDocumentType:
    if profile in {
        BookProfileKind.LITERARY_FICTION,
        BookProfileKind.LITERARY_NON_FICTION,
        BookProfileKind.HISTORICAL,
        BookProfileKind.MEMOIR,
        BookProfileKind.RELIGIOUS_PHILOSOPHICAL,
    }:
        return BookDocumentType.BOOK_MANUSCRIPT
    if profile is BookProfileKind.TECHNICAL:
        return BookDocumentType.TECHNICAL_DOCUMENT
    if profile is BookProfileKind.BUSINESS_LEGAL_LIKE:
        return BookDocumentType.BUSINESS_LEGAL_DOCUMENT
    if profile in {
        BookProfileKind.SCIENTIFIC_ACADEMIC,
        BookProfileKind.JOURNALISTIC_PUBLICISTIC,
        BookProfileKind.EDUCATIONAL,
        BookProfileKind.MARKETING,
    }:
        return BookDocumentType.ARTICLE_OR_ESSAY
    if profile is BookProfileKind.MIXED_UNKNOWN:
        return BookDocumentType.MIXED
    return BookDocumentType.UNKNOWN


def _fictionality(
    profile: BookProfileKind,
    dialogue_density: DialogueDensity,
) -> Fictionality:
    if profile is BookProfileKind.LITERARY_FICTION:
        return Fictionality.FICTION
    if profile is BookProfileKind.MIXED_UNKNOWN:
        return Fictionality.MIXED
    if profile in {
        BookProfileKind.SCIENTIFIC_ACADEMIC,
        BookProfileKind.TECHNICAL,
        BookProfileKind.BUSINESS_LEGAL_LIKE,
        BookProfileKind.JOURNALISTIC_PUBLICISTIC,
        BookProfileKind.EDUCATIONAL,
        BookProfileKind.MARKETING,
    }:
        return Fictionality.NON_FICTION
    if dialogue_density is DialogueDensity.HIGH:
        return Fictionality.FICTION
    return Fictionality.UNKNOWN


def _register(profile: BookProfileKind) -> BookRegister:
    mapping = {
        BookProfileKind.LITERARY_FICTION: BookRegister.LITERARY,
        BookProfileKind.LITERARY_NON_FICTION: BookRegister.LITERARY,
        BookProfileKind.JOURNALISTIC_PUBLICISTIC: BookRegister.PUBLICISTIC,
        BookProfileKind.SCIENTIFIC_ACADEMIC: BookRegister.ACADEMIC,
        BookProfileKind.TECHNICAL: BookRegister.TECHNICAL,
        BookProfileKind.BUSINESS_LEGAL_LIKE: BookRegister.FORMAL,
        BookProfileKind.MARKETING: BookRegister.MARKETING,
    }
    return mapping.get(profile, BookRegister.UNKNOWN)


def _terminology_strictness(profile: BookProfileKind) -> TerminologyStrictness:
    if profile in {
        BookProfileKind.SCIENTIFIC_ACADEMIC,
        BookProfileKind.TECHNICAL,
        BookProfileKind.BUSINESS_LEGAL_LIKE,
        BookProfileKind.RELIGIOUS_PHILOSOPHICAL,
    }:
        return TerminologyStrictness.HIGH
    if profile in {
        BookProfileKind.LITERARY_FICTION,
        BookProfileKind.JOURNALISTIC_PUBLICISTIC,
    }:
        return TerminologyStrictness.MEDIUM
    return TerminologyStrictness.UNKNOWN


def _paraphrase_allowance(profile: BookProfileKind) -> ParaphraseAllowance:
    if profile in {
        BookProfileKind.SCIENTIFIC_ACADEMIC,
        BookProfileKind.TECHNICAL,
        BookProfileKind.BUSINESS_LEGAL_LIKE,
        BookProfileKind.RELIGIOUS_PHILOSOPHICAL,
    }:
        return ParaphraseAllowance.LOW
    if profile in {
        BookProfileKind.LITERARY_FICTION,
        BookProfileKind.JOURNALISTIC_PUBLICISTIC,
    }:
        return ParaphraseAllowance.MEDIUM
    return ParaphraseAllowance.UNKNOWN


def _named_entity_policy(profile: BookProfileKind) -> NamedEntityPolicy:
    if profile is BookProfileKind.LITERARY_FICTION:
        return NamedEntityPolicy.CONTEXTUAL
    if profile in {
        BookProfileKind.SCIENTIFIC_ACADEMIC,
        BookProfileKind.TECHNICAL,
        BookProfileKind.BUSINESS_LEGAL_LIKE,
        BookProfileKind.JOURNALISTIC_PUBLICISTIC,
    }:
        return NamedEntityPolicy.PRESERVE_OFFICIAL_NAMES
    return NamedEntityPolicy.UNKNOWN


def _dialogue_density(blocks: tuple[_BlockRef, ...]) -> DialogueDensity:
    if not blocks:
        return DialogueDensity.UNKNOWN
    quoted_blocks = sum(
        1 for block_ref in blocks if _QUOTE_RE.search(block_ref.block.text)
    )
    ratio = quoted_blocks / len(blocks)
    if ratio >= 0.35:
        return DialogueDensity.HIGH
    if ratio >= 0.12:
        return DialogueDensity.MEDIUM
    return DialogueDensity.LOW


def _domain_hints(
    signals: list[_Signal],
    *,
    primary_profile: BookProfileKind,
) -> tuple[str, ...]:
    hints = sorted(
        {
            signal.domain_hint
            for signal in signals
            if signal.profile is primary_profile
            or primary_profile is BookProfileKind.MIXED_UNKNOWN
        }
    )
    return tuple(hints[:5])


def _uncertainty_notes(
    *,
    primary_profile: BookProfileKind,
    confidence: float,
) -> tuple[str, ...]:
    notes: list[str] = []
    if primary_profile in {BookProfileKind.UNKNOWN, BookProfileKind.MIXED_UNKNOWN}:
        notes.append("profile_unknown_or_mixed")
    if confidence < 0.7:
        notes.append("low_confidence_profile")
    notes.append("ru_uk_morphology_tbd")
    return tuple(notes)


def _validate_profile(
    profile: BookProfile,
    *,
    evidence_ids: set[str],
    issues: list[BookProfileValidationIssue],
) -> None:
    if profile.schema_version != BOOK_PROFILE_SCHEMA_VERSION:
        _add_issue(
            issues,
            BookProfileValidationCode.INVALID_SCHEMA_VERSION,
            "profile.schema_version",
            f"schema_version must be {BOOK_PROFILE_SCHEMA_VERSION}.",
        )
    for path, value in (
        ("profile.profile_id", profile.profile_id),
        ("profile.source_language", profile.source_language),
        ("profile.target_language", profile.target_language),
        ("profile.source_pair_policy", profile.source_pair_policy),
        ("profile.target_language_policy", profile.target_language_policy),
    ):
        if not _non_empty_text(value):
            _add_issue(
                issues,
                BookProfileValidationCode.MISSING_FIELD,
                path,
                f"{path} is required.",
            )
    _validate_enum(
        profile.primary_profile,
        BookProfileKind,
        issues,
        "profile.primary_profile",
    )
    _validate_enum(
        profile.document_type,
        BookDocumentType,
        issues,
        "profile.document_type",
    )
    _validate_enum(profile.fictionality, Fictionality, issues, "profile.fictionality")
    _validate_enum(
        profile.dialogue_density,
        DialogueDensity,
        issues,
        "profile.dialogue_density",
    )
    _validate_enum(profile.register, BookRegister, issues, "profile.register")
    _validate_enum(
        profile.terminology_strictness,
        TerminologyStrictness,
        issues,
        "profile.terminology_strictness",
    )
    _validate_enum(
        profile.paraphrase_allowance,
        ParaphraseAllowance,
        issues,
        "profile.paraphrase_allowance",
    )
    _validate_enum(
        profile.named_entity_policy,
        NamedEntityPolicy,
        issues,
        "profile.named_entity_policy",
    )
    for index, secondary_profile in enumerate(profile.secondary_profiles):
        _validate_enum(
            secondary_profile,
            BookProfileKind,
            issues,
            f"profile.secondary_profiles[{index}]",
        )
    if not _valid_confidence(profile.confidence):
        _add_issue(
            issues,
            BookProfileValidationCode.INVALID_CONFIDENCE,
            "profile.confidence",
            "confidence must be a finite number from 0.0 through 1.0.",
        )
    for evidence_ref in profile.evidence_refs:
        if evidence_ref not in evidence_ids:
            _add_issue(
                issues,
                BookProfileValidationCode.MISSING_EVIDENCE,
                "profile.evidence_refs",
                f"evidence reference {evidence_ref!r} is not defined.",
            )


def _validate_evidence_ref(
    evidence: GlossaryEvidenceRef,
    *,
    issues: list[BookProfileValidationIssue],
    path: str,
) -> None:
    _validate_enum(
        evidence.evidence_type,
        GlossaryEvidenceType,
        issues,
        f"{path}.evidence_type",
    )
    _validate_enum(
        evidence.surface,
        GlossaryEvidenceSurface,
        issues,
        f"{path}.surface",
    )
    if (
        not isinstance(evidence.unit_sequence, int)
        or isinstance(evidence.unit_sequence, bool)
        or evidence.unit_sequence < 0
    ):
        _add_issue(
            issues,
            BookProfileValidationCode.INVALID_SOURCE_ANCHOR,
            f"{path}.unit_sequence",
            "unit_sequence must be a non-negative integer.",
        )
    for field_name, value in (
        ("source_block_id", evidence.source_block_id),
        ("source_scope", evidence.source_scope),
        ("offset_bucket", evidence.offset_bucket),
    ):
        if not _non_empty_text(value):
            _add_issue(
                issues,
                BookProfileValidationCode.INVALID_SOURCE_ANCHOR,
                f"{path}.{field_name}",
                f"{field_name} is required.",
            )
    if (
        not isinstance(evidence.occurrence_count, int)
        or isinstance(evidence.occurrence_count, bool)
        or evidence.occurrence_count < 1
    ):
        _add_issue(
            issues,
            BookProfileValidationCode.INVALID_SOURCE_ANCHOR,
            f"{path}.occurrence_count",
            "occurrence_count must be a positive integer.",
        )
    if evidence.raw_excerpt is not None:
        _add_issue(
            issues,
            BookProfileValidationCode.RAW_TEXT_NOT_ALLOWED,
            f"{path}.raw_excerpt",
            "raw excerpts require an approved owner-only diagnostic artifact.",
        )


def _validate_rules(
    rules: tuple[ProfileSpecificGlossaryRule, ...],
    *,
    evidence_ids: set[str],
    issues: list[BookProfileValidationIssue],
) -> None:
    if not rules:
        _add_issue(
            issues,
            BookProfileValidationCode.MISSING_FIELD,
            "rules",
            "at least one profile glossary rule is required.",
        )
        return
    rule_ids: set[str] = set()
    for index, rule in enumerate(rules):
        path = f"rules[{index}]"
        if rule.schema_version != PROFILE_GLOSSARY_RULE_SCHEMA_VERSION:
            _add_issue(
                issues,
                BookProfileValidationCode.INVALID_SCHEMA_VERSION,
                f"{path}.schema_version",
                f"schema_version must be {PROFILE_GLOSSARY_RULE_SCHEMA_VERSION}.",
            )
        if not _non_empty_text(rule.rule_id):
            _add_issue(
                issues,
                BookProfileValidationCode.MISSING_FIELD,
                f"{path}.rule_id",
                "rule_id is required.",
            )
        elif rule.rule_id in rule_ids:
            _add_issue(
                issues,
                BookProfileValidationCode.DUPLICATE_ID,
                f"{path}.rule_id",
                "rule_id must be unique.",
            )
        else:
            rule_ids.add(rule.rule_id)
        _validate_rule(rule, path=path, evidence_ids=evidence_ids, issues=issues)


def _validate_rule(
    rule: ProfileSpecificGlossaryRule,
    *,
    path: str,
    evidence_ids: set[str],
    issues: list[BookProfileValidationIssue],
) -> None:
    _validate_enum(
        rule.rule_type,
        ProfileGlossaryRuleType,
        issues,
        f"{path}.rule_type",
    )
    _validate_enum(
        rule.scope_category,
        GlossaryEntryCategory,
        issues,
        f"{path}.scope_category",
    )
    _validate_enum(rule.glossary_strategy, GlossaryStrategy, issues, f"{path}.strategy")
    _validate_enum(
        rule.terminology_strictness,
        TerminologyStrictness,
        issues,
        f"{path}.terminology_strictness",
    )
    _validate_enum(
        rule.paraphrase_allowance,
        ParaphraseAllowance,
        issues,
        f"{path}.paraphrase_allowance",
    )
    _validate_enum(
        rule.named_entity_policy,
        NamedEntityPolicy,
        issues,
        f"{path}.named_entity_policy",
    )
    _validate_enum(
        rule.fallback_strategy,
        GlossaryStrategy,
        issues,
        f"{path}.fallback_strategy",
    )
    for profile_index, profile in enumerate(rule.applies_to_profiles):
        _validate_enum(
            profile,
            BookProfileKind,
            issues,
            f"{path}.applies_to_profiles[{profile_index}]",
        )
    if not rule.target_languages:
        _add_issue(
            issues,
            BookProfileValidationCode.MISSING_FIELD,
            f"{path}.target_languages",
            "at least one target language is required.",
        )
    for evidence_ref in rule.evidence_refs:
        if evidence_ref not in evidence_ids:
            _add_issue(
                issues,
                BookProfileValidationCode.MISSING_EVIDENCE,
                f"{path}.evidence_refs",
                f"evidence reference {evidence_ref!r} is not defined.",
            )


def _signal(
    *,
    profile: BookProfileKind,
    domain_hint: str,
    evidence_type: GlossaryEvidenceType,
    block_ref: _BlockRef,
    start_offset: int,
) -> _Signal:
    return _Signal(
        profile=profile,
        domain_hint=domain_hint,
        evidence_type=evidence_type,
        unit_sequence=block_ref.unit_sequence,
        source_block_id=block_ref.block.source_block_id,
        source_scope=_source_scope(block_ref.block),
        surface=_surface_for_block(block_ref.block),
        offset_bucket=_offset_bucket(start_offset, len(block_ref.block.text)),
        start_offset=start_offset,
    )


def _evidence_id(signal: _Signal, index: int) -> str:
    digest = _digest(
        "|".join(
            (
                signal.profile.value,
                signal.source_block_id,
                str(signal.unit_sequence),
                str(signal.start_offset),
                str(index),
            )
        )
    )
    return f"book-profile:{signal.profile.value}:ev:{digest}"


def _profile_id(
    *,
    primary_profile: BookProfileKind,
    source_language: str,
    target_language: str,
    evidence_refs: tuple[str, ...],
) -> str:
    digest = _digest(
        "|".join(
            (
                BOOK_PROFILE_SCHEMA_VERSION,
                primary_profile.value,
                source_language.strip().lower(),
                target_language.strip().lower(),
                *evidence_refs,
            )
        )
    )
    return f"book-profile:{primary_profile.value}:{digest}"


def _profile_enum_value(value: BookProfileKind | str) -> BookProfileKind:
    if isinstance(value, BookProfileKind):
        return value
    try:
        return BookProfileKind(str(value))
    except ValueError:
        return BookProfileKind.UNKNOWN


def _validate_enum(
    value: Any,
    enum_type: type[StrEnum],
    issues: list[BookProfileValidationIssue],
    path: str,
) -> None:
    if isinstance(value, enum_type):
        return
    if isinstance(value, str):
        try:
            enum_type(value)
            return
        except ValueError:
            pass
    _add_issue(
        issues,
        BookProfileValidationCode.INVALID_ENUM,
        path,
        f"{path} must be one of: {', '.join(item.value for item in enum_type)}.",
    )


def _add_issue(
    issues: list[BookProfileValidationIssue],
    code: BookProfileValidationCode,
    path: str,
    message: str,
) -> None:
    issues.append(BookProfileValidationIssue(code=code, path=path, message=message))


def _valid_confidence(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0.0 <= float(value) <= 1.0
    )


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalize_text(text: str) -> str:
    return _SPACE_RE.sub(" ", text.casefold())


def _source_scope(block: FormatTextBlock) -> str:
    metadata = dict(block.metadata)
    if "file_name" in metadata:
        return metadata["file_name"]
    if block.group_id:
        return block.group_id
    return "global"


def _evidence_type_for_block(block: FormatTextBlock) -> GlossaryEvidenceType:
    if block.kind is TextBlockKind.HEADING:
        return GlossaryEvidenceType.HEADING
    return GlossaryEvidenceType.SOURCE_ANCHOR


def _surface_for_block(block: FormatTextBlock) -> GlossaryEvidenceSurface:
    if block.kind is TextBlockKind.HEADING:
        return GlossaryEvidenceSurface.HEADING
    if block.kind is TextBlockKind.FOOTNOTE:
        return GlossaryEvidenceSurface.FOOTNOTE
    return GlossaryEvidenceSurface.BODY


def _offset_bucket(start_offset: int, text_length: int) -> str:
    if text_length <= 0:
        return "unknown"
    ratio = start_offset / text_length
    if ratio < 0.34:
        return "early"
    if ratio < 0.67:
        return "middle"
    return "late"


def _language_root(language_code: str) -> str:
    return language_code.strip().lower().replace("_", "-").split("-", 1)[0]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
