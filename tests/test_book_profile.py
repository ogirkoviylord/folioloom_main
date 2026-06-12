import unittest

from translator_service.book_profile import (
    BookDocumentType,
    BookProfileKind,
    BookProfileValidationCode,
    DialogueDensity,
    Fictionality,
    NamedEntityPolicy,
    ParaphraseAllowance,
    ProfileGlossaryRuleType,
    TerminologyStrictness,
    detect_book_profile,
    validate_book_profile_detection,
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
)
from translator_service.glossary_scanner import scan_glossary_candidates
from translator_service.structure_optimizer import PromptTier, TextBlockKind


class BookProfileTest(unittest.TestCase):
    def test_detects_literary_fiction_with_profile_specific_name_rule(self):
        plan = _plan(
            (
                _unit(
                    1,
                    _block(
                        0,
                        "txt:segment:1",
                        "Chapter One",
                        kind=TextBlockKind.HEADING,
                    ),
                ),
                _unit(
                    2,
                    _block(
                        1,
                        "txt:segment:2",
                        '"Where are you going?" Elizabeth whispered.',
                    ),
                ),
                _unit(
                    3,
                    _block(
                        2,
                        "txt:segment:3",
                        '"I am staying," Darcy answered Elizabeth.',
                    ),
                ),
            )
        )
        glossary = scan_glossary_candidates(
            plan,
            source_language="en",
            target_language="ru",
        )

        detection = detect_book_profile(
            plan,
            source_language="en",
            target_language="ru",
            glossary_snapshot=glossary,
        )

        self.assertEqual(
            detection.profile.primary_profile,
            BookProfileKind.LITERARY_FICTION,
        )
        self.assertEqual(detection.profile.fictionality, Fictionality.FICTION)
        self.assertEqual(detection.profile.dialogue_density, DialogueDensity.HIGH)
        self.assertEqual(
            detection.profile.target_language_policy,
            "target-profile:ru:russian-v2",
        )
        self.assertEqual(detection.rules[0].scope_category, GlossaryEntryCategory.NAME)
        self.assertEqual(
            detection.rules[0].named_entity_policy,
            NamedEntityPolicy.CONTEXTUAL,
        )
        self.assertTrue(
            all(evidence.raw_excerpt is None for evidence in detection.evidence)
        )
        self.assertTrue(validate_book_profile_detection(detection).valid)

    def test_detects_scientific_academic_profile_and_strict_term_rule(self):
        plan = _plan(
            (
                _unit(
                    1,
                    _block(
                        0,
                        "docx:word/document.xml:0",
                        "Methodology",
                        kind=TextBlockKind.HEADING,
                        metadata=(("file_name", "word/document.xml"),),
                    ),
                ),
                _unit(
                    2,
                    _block(
                        1,
                        "docx:word/document.xml:1",
                        (
                            "The study reports sample size and statistically "
                            "significant results. The data indicate a correlation."
                        ),
                        metadata=(("file_name", "word/document.xml"),),
                    ),
                ),
            ),
            document_format=DocumentFormat.DOCX,
        )

        detection = detect_book_profile(
            plan,
            source_language="en",
            target_language="uk",
        )

        self.assertEqual(
            detection.profile.primary_profile,
            BookProfileKind.SCIENTIFIC_ACADEMIC,
        )
        self.assertEqual(detection.profile.fictionality, Fictionality.NON_FICTION)
        self.assertIn("science", detection.profile.domain_hints)
        self.assertEqual(
            detection.profile.terminology_strictness,
            TerminologyStrictness.HIGH,
        )
        self.assertEqual(
            detection.profile.paraphrase_allowance,
            ParaphraseAllowance.LOW,
        )
        self.assertEqual(
            detection.rules[0].terminology_strictness,
            TerminologyStrictness.HIGH,
        )
        self.assertEqual(detection.evidence[0].source_scope, "word/document.xml")
        self.assertTrue(validate_book_profile_detection(detection).valid)

    def test_ambiguous_document_stays_unknown_with_review_rule(self):
        detection = detect_book_profile(
            _plan(
                (
                    _unit(
                        1,
                        _block(0, "txt:segment:1", "A short neutral paragraph."),
                    ),
                )
            ),
            source_language="auto",
            target_language="ru",
        )

        self.assertEqual(detection.profile.primary_profile, BookProfileKind.UNKNOWN)
        self.assertLess(detection.profile.confidence, 0.5)
        self.assertIn("profile_unknown_or_mixed", detection.profile.uncertainty_notes)
        self.assertEqual(detection.rules[0].requires_review, True)
        self.assertTrue(validate_book_profile_detection(detection).valid)

    def test_recognized_profile_without_specific_strategy_gets_review_rule(self):
        detection = detect_book_profile(
            _plan(
                (
                    _unit(
                        1,
                        _block(
                            0,
                            "txt:segment:1",
                            "Limited offer benefits customers love. Subscribe now.",
                        ),
                    ),
                )
            ),
            source_language="en",
            target_language="ru",
        )

        self.assertEqual(detection.profile.primary_profile, BookProfileKind.MARKETING)
        self.assertEqual(
            detection.profile.document_type,
            BookDocumentType.ARTICLE_OR_ESSAY,
        )
        self.assertEqual(detection.rules[0].rule_type, ProfileGlossaryRuleType.FALLBACK)
        self.assertEqual(
            detection.rules[0].applies_to_profiles,
            (BookProfileKind.MARKETING,),
        )
        self.assertTrue(detection.rules[0].requires_review)
        self.assertTrue(validate_book_profile_detection(detection).valid)

    def test_validation_rejects_invalid_profile_and_rule_contracts(self):
        detection = detect_book_profile(
            _plan(
                (
                    _unit(
                        1,
                        _block(0, "txt:segment:1", "Methodology and results."),
                    ),
                )
            ),
            source_language="en",
            target_language="ru",
        )
        bad_profile = detection.profile.__class__(
            **{
                **detection.profile.__dict__,
                "primary_profile": "unsupported",
                "confidence": 1.4,
                "evidence_refs": ("missing-evidence",),
            }
        )
        bad_rule = detection.rules[0].__class__(
            **{
                **detection.rules[0].__dict__,
                "rule_id": "",
                "scope_category": "bad-category",
                "evidence_refs": ("missing-evidence",),
            }
        )
        bad_evidence = GlossaryEvidenceRef(
            evidence_id="bad-evidence",
            evidence_type="bad-evidence-type",
            unit_sequence=-1,
            source_block_id="",
            source_scope="",
            raw_excerpt="raw source text",
        )
        bad_detection = detection.__class__(
            profile=bad_profile,
            rules=(bad_rule,),
            evidence=(bad_evidence,),
        )

        result = validate_book_profile_detection(bad_detection)
        codes = {issue.code for issue in result.issues}

        self.assertFalse(result.valid)
        self.assertIn(BookProfileValidationCode.INVALID_ENUM, codes)
        self.assertIn(BookProfileValidationCode.INVALID_CONFIDENCE, codes)
        self.assertIn(BookProfileValidationCode.INVALID_SOURCE_ANCHOR, codes)
        self.assertIn(BookProfileValidationCode.MISSING_EVIDENCE, codes)
        self.assertIn(BookProfileValidationCode.MISSING_FIELD, codes)
        self.assertIn(BookProfileValidationCode.RAW_TEXT_NOT_ALLOWED, codes)


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
    metadata: tuple[tuple[str, str], ...] = (),
) -> FormatTextBlock:
    return FormatTextBlock(
        index=index,
        source_block_id=source_block_id,
        text=text,
        kind=kind,
        metadata=metadata,
    )


if __name__ == "__main__":
    unittest.main()
