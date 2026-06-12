import json
import unittest

from translator_service.book_profile import (
    BookDocumentType,
    BookProfile,
    BookProfileDetection,
    BookProfileKind,
    BookRegister,
    DialogueDensity,
    Fictionality,
    NamedEntityPolicy,
    ParaphraseAllowance,
    ProfileGlossaryRuleType,
    ProfileSpecificGlossaryRule,
    TerminologyStrictness,
    detect_book_profile,
)
from translator_service.book_profile_sanity import (
    BookProfileSanityReason,
    BookProfileSanityRoute,
    BookProfileSanitySeverity,
    book_profile_sanity_payload,
    check_book_profile_sanity,
    serialize_book_profile_sanity,
)
from translator_service.documents import DocumentFormat
from translator_service.format_adapters.contracts import (
    FormatAdapterPlan,
    FormatTextBlock,
    FormatTranslationUnit,
)
from translator_service.glossary_contracts import (
    GlossaryEntryCategory,
    GlossaryEvidenceRef,
    GlossaryEvidenceSurface,
    GlossaryEvidenceType,
    GlossaryStrategy,
)
from translator_service.structure_optimizer import PromptTier, TextBlockKind


class BookProfileSanityTest(unittest.TestCase):
    def test_clean_profile_passes_without_findings(self):
        detection = detect_book_profile(
            _plan(
                (
                    _unit(1, _block(0, "txt:segment:1", "Methodology")),
                    _unit(
                        2,
                        _block(
                            1,
                            "txt:segment:2",
                            (
                                "The study reports sample size and statistically "
                                "significant results. The data indicate a correlation."
                            ),
                        ),
                    ),
                    _unit(
                        3,
                        _block(
                            2,
                            "txt:segment:3",
                            (
                                "The conclusion reports methodology and "
                                "hypothesis results."
                            ),
                        ),
                    ),
                )
            ),
            source_language="en",
            target_language="ru",
        )

        result = check_book_profile_sanity(detection)

        self.assertEqual(
            detection.profile.primary_profile,
            BookProfileKind.SCIENTIFIC_ACADEMIC,
        )
        self.assertEqual(
            result.recommended_route,
            BookProfileSanityRoute.PROFILE_ACCEPTED,
        )
        self.assertEqual(result.findings, ())
        self.assertEqual(result.blocker_count, 0)
        self.assertEqual(result.morphology_status, "TBD")

    def test_strong_secondary_profiles_require_review_without_mutating_detection(self):
        detection = _detection(
            primary_profile=BookProfileKind.LITERARY_FICTION,
            secondary_profiles=(
                BookProfileKind.TECHNICAL,
                BookProfileKind.RELIGIOUS_PHILOSOPHICAL,
            ),
            confidence=0.86,
            evidence=(
                _evidence("ev:profile:1", 1, "txt:segment:1"),
                _evidence("ev:profile:2", 2, "txt:segment:2"),
                _evidence("ev:profile:3", 3, "txt:segment:3"),
            ),
        )

        result = check_book_profile_sanity(detection)
        reasons = {finding.reason for finding in result.findings}

        self.assertEqual(
            detection.profile.primary_profile,
            BookProfileKind.LITERARY_FICTION,
        )
        self.assertEqual(result.original_primary_profile, "literary_fiction")
        self.assertEqual(
            result.recommended_route,
            BookProfileSanityRoute.MIXED_NEEDS_REVIEW,
        )
        self.assertIn(BookProfileSanityReason.STRONG_SECONDARY_PROFILES, reasons)
        self.assertTrue(
            any(
                finding.severity is BookProfileSanitySeverity.BLOCKER
                for finding in result.findings
            )
        )

    def test_false_confident_legal_frontmatter_with_bookish_secondary_blocks(self):
        detection = _detection(
            primary_profile=BookProfileKind.BUSINESS_LEGAL_LIKE,
            secondary_profiles=(
                BookProfileKind.RELIGIOUS_PHILOSOPHICAL,
                BookProfileKind.LITERARY_FICTION,
            ),
            confidence=0.88,
            evidence=(
                _evidence(
                    "ev:legal:1",
                    0,
                    "epub:nav.xhtml:0",
                    source_scope="frontmatter/nav",
                    surface=GlossaryEvidenceSurface.NAV,
                ),
                _evidence(
                    "ev:legal:2",
                    0,
                    "epub:metadata.opf:0",
                    source_scope="frontmatter/metadata",
                    surface=GlossaryEvidenceSurface.METADATA,
                ),
            ),
        )

        result = check_book_profile_sanity(detection)
        reasons = {finding.reason for finding in result.findings}

        self.assertEqual(
            result.recommended_route,
            BookProfileSanityRoute.MIXED_NEEDS_REVIEW,
        )
        self.assertIn(
            BookProfileSanityReason.HIGH_CONFIDENCE_CONFLICTING_EVIDENCE,
            reasons,
        )
        self.assertIn(
            BookProfileSanityReason.FRONTMATTER_OR_NAV_DOMINATED,
            reasons,
        )
        self.assertGreaterEqual(result.blocker_count, 1)

    def test_low_evidence_count_warns_without_claiming_truth(self):
        detection = _detection(
            primary_profile=BookProfileKind.TECHNICAL,
            secondary_profiles=(),
            confidence=0.81,
            evidence=(_evidence("ev:technical:1", 1, "txt:segment:1"),),
        )

        result = check_book_profile_sanity(detection)

        self.assertEqual(
            result.recommended_route,
            BookProfileSanityRoute.PROFILE_NEEDS_REVIEW,
        )
        self.assertEqual(result.blocker_count, 0)
        self.assertIn(
            BookProfileSanityReason.LOW_EVIDENCE_COUNT,
            {finding.reason for finding in result.findings},
        )

    def test_serialized_findings_are_metadata_only(self):
        raw_excerpt = "PRIVATE_PROFILE_SENTINEL legal contract soul prayer"
        detection = _detection(
            primary_profile=BookProfileKind.BUSINESS_LEGAL_LIKE,
            secondary_profiles=(BookProfileKind.RELIGIOUS_PHILOSOPHICAL,),
            confidence=0.84,
            evidence=(
                _evidence(
                    "ev:raw:1",
                    0,
                    "epub:metadata.opf:0",
                    source_scope="frontmatter/metadata",
                    surface=GlossaryEvidenceSurface.METADATA,
                    raw_excerpt=raw_excerpt,
                ),
            ),
        )

        result = check_book_profile_sanity(
            detection,
            pressure_signals={
                "secondary_profile_count": 2,
                "profile_needs_review": True,
                "raw_note": "PRIVATE_PRESSURE_SENTINEL",
            },
        )
        serialized = serialize_book_profile_sanity(result)
        payload_text = json.dumps(
            book_profile_sanity_payload(result),
            ensure_ascii=False,
            sort_keys=True,
        )

        self.assertIn("pressure_signature", serialized)
        self.assertIn("ev:raw:1", serialized)
        self.assertNotIn(raw_excerpt, serialized)
        self.assertNotIn("PRIVATE_PROFILE_SENTINEL", serialized)
        self.assertNotIn("PRIVATE_PRESSURE_SENTINEL", serialized)
        self.assertNotIn(raw_excerpt, payload_text)

    def test_rejects_invalid_min_evidence_refs(self):
        with self.assertRaises(ValueError):
            check_book_profile_sanity(
                _detection(
                    primary_profile=BookProfileKind.TECHNICAL,
                    secondary_profiles=(),
                    confidence=0.7,
                    evidence=(),
                ),
                min_evidence_refs=-1,
            )


def _detection(
    *,
    primary_profile: BookProfileKind,
    secondary_profiles: tuple[BookProfileKind, ...],
    confidence: float,
    evidence: tuple[GlossaryEvidenceRef, ...],
    target_language: str = "ru",
) -> BookProfileDetection:
    evidence_refs = tuple(item.evidence_id for item in evidence)
    profile = BookProfile(
        profile_id=f"book-profile:{primary_profile.value}:test",
        source_language="en",
        target_language=target_language,
        primary_profile=primary_profile,
        secondary_profiles=secondary_profiles,
        document_type=_document_type(primary_profile),
        fictionality=_fictionality(primary_profile),
        dialogue_density=DialogueDensity.MEDIUM,
        register=_register(primary_profile),
        confidence=confidence,
        evidence_refs=evidence_refs,
        domain_hints=(primary_profile.value,),
        terminology_strictness=TerminologyStrictness.MEDIUM,
        paraphrase_allowance=ParaphraseAllowance.MEDIUM,
        named_entity_policy=NamedEntityPolicy.CONTEXTUAL,
        source_pair_policy=f"source-pair:en-{target_language}:v1",
        target_language_policy=f"target-profile:{target_language}:test-v1",
        uncertainty_notes=("ru_uk_morphology_tbd",),
    )
    return BookProfileDetection(
        profile=profile,
        rules=(_rule(primary_profile, evidence_refs, target_language),),
        evidence=evidence,
    )


def _rule(
    profile: BookProfileKind,
    evidence_refs: tuple[str, ...],
    target_language: str,
) -> ProfileSpecificGlossaryRule:
    return ProfileSpecificGlossaryRule(
        rule_id=f"profile-rule:{profile.value}:test-v1",
        rule_type=ProfileGlossaryRuleType.NAMED_ENTITY_STRATEGY,
        applies_to_profiles=(profile,),
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


def _evidence(
    evidence_id: str,
    unit_sequence: int,
    source_block_id: str,
    *,
    source_scope: str = "chapter-1",
    surface: GlossaryEvidenceSurface = GlossaryEvidenceSurface.BODY,
    raw_excerpt: str | None = None,
) -> GlossaryEvidenceRef:
    return GlossaryEvidenceRef(
        evidence_id=evidence_id,
        evidence_type=GlossaryEvidenceType.SOURCE_ANCHOR,
        unit_sequence=unit_sequence,
        source_block_id=source_block_id,
        source_scope=source_scope,
        surface=surface,
        raw_excerpt=raw_excerpt,
    )


def _plan(
    units: tuple[FormatTranslationUnit, ...],
    *,
    document_format: DocumentFormat = DocumentFormat.TXT,
) -> FormatAdapterPlan:
    return FormatAdapterPlan(
        document_format=document_format,
        adapter_version=f"{document_format.value}-adapter-test",
        units=units,
        character_count=sum(len(block.text) for unit in units for block in unit.blocks),
        estimated_input_tokens=1,
    )


def _unit(sequence: int, *blocks: FormatTextBlock) -> FormatTranslationUnit:
    return FormatTranslationUnit(
        sequence=sequence,
        blocks=blocks,
        prompt_tier=PromptTier.PLAIN,
    )


def _block(
    index: int,
    source_block_id: str,
    text: str,
    *,
    kind: TextBlockKind = TextBlockKind.PLAIN,
) -> FormatTextBlock:
    return FormatTextBlock(
        index=index,
        source_block_id=source_block_id,
        text=text,
        kind=kind,
    )


def _document_type(profile: BookProfileKind) -> BookDocumentType:
    if profile is BookProfileKind.BUSINESS_LEGAL_LIKE:
        return BookDocumentType.BUSINESS_LEGAL_DOCUMENT
    return BookDocumentType.BOOK_MANUSCRIPT


def _fictionality(profile: BookProfileKind) -> Fictionality:
    if profile is BookProfileKind.LITERARY_FICTION:
        return Fictionality.FICTION
    if profile in {
        BookProfileKind.BUSINESS_LEGAL_LIKE,
        BookProfileKind.TECHNICAL,
    }:
        return Fictionality.NON_FICTION
    return Fictionality.UNKNOWN


def _register(profile: BookProfileKind) -> BookRegister:
    if profile is BookProfileKind.BUSINESS_LEGAL_LIKE:
        return BookRegister.FORMAL
    if profile is BookProfileKind.TECHNICAL:
        return BookRegister.TECHNICAL
    if profile is BookProfileKind.LITERARY_FICTION:
        return BookRegister.LITERARY
    return BookRegister.UNKNOWN


if __name__ == "__main__":
    unittest.main()
