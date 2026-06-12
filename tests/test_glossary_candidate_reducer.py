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
)
from translator_service.glossary_candidate_reducer import (
    GlossaryCandidateDecisionStatus,
    GlossaryCandidateReducerCaps,
    GlossaryCandidateReductionReason,
    glossary_candidate_reduction_payload,
    reduce_glossary_candidates,
    serialize_glossary_candidate_reduction,
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
    validate_glossary_snapshot,
)


class GlossaryCandidateReducerTest(unittest.TestCase):
    def test_retains_repeated_names_terms_and_preserves_refs(self):
        glossary = _glossary(
            (
                _entry(
                    "entry:elizabeth",
                    "Elizabeth Bennet",
                    evidence_refs=("ev:elizabeth:1", "ev:elizabeth:2"),
                    confidence=0.82,
                ),
                _entry(
                    "entry:quantum-drive",
                    "quantum drive",
                    category=GlossaryEntryCategory.TERM,
                    evidence_refs=("ev:term:1",),
                    confidence=0.86,
                ),
                _entry(
                    "entry:noisy-single",
                    "Appendix",
                    evidence_refs=("ev:noisy:1",),
                    confidence=0.42,
                ),
            ),
            evidence=(
                _evidence("ev:elizabeth:1", 1, "txt:segment:1"),
                _evidence("ev:elizabeth:2", 4, "txt:segment:4"),
                _evidence("ev:term:1", 2, "txt:segment:2", occurrence_count=3),
                _evidence(
                    "ev:noisy:1",
                    0,
                    "epub:nav.xhtml:0",
                    source_scope="frontmatter/nav",
                    surface=GlossaryEvidenceSurface.NAV,
                ),
            ),
        )

        result = reduce_glossary_candidates(
            glossary,
            profile_detection=_profile_detection(),
        )

        self.assertIn("entry:elizabeth", result.retained_entry_ids)
        self.assertIn("entry:quantum-drive", result.retained_entry_ids)
        self.assertNotIn("entry:noisy-single", result.retained_entry_ids)
        elizabeth = _decision(result, "entry:elizabeth")
        self.assertEqual(
            elizabeth.evidence_refs,
            ("ev:elizabeth:1", "ev:elizabeth:2"),
        )
        self.assertIn(
            GlossaryCandidateReductionReason.REPEATED_NAME,
            elizabeth.reasons,
        )
        self.assertIn(
            GlossaryCandidateReductionReason.PROFILE_RELEVANT,
            elizabeth.reasons,
        )
        self.assertIn(
            GlossaryCandidateReductionReason.REPEATED_TERM,
            _decision(result, "entry:quantum-drive").reasons,
        )
        self.assertEqual(
            {evidence.evidence_id for evidence in result.retained_snapshot.evidence},
            {"ev:elizabeth:1", "ev:elizabeth:2", "ev:term:1"},
        )
        self.assertTrue(validate_glossary_snapshot(result.retained_snapshot).valid)

    def test_marks_quoted_uncertain_and_frontmatter_noise_as_not_editor_ready(self):
        glossary = _glossary(
            (
                _entry(
                    "entry:quoted-title",
                    "The Watcher",
                    status=GlossaryEntryStatus.UNCERTAIN,
                    evidence_refs=("ev:quote:1",),
                    confidence=0.45,
                ),
                _entry(
                    "entry:gutenberg",
                    "Project Gutenberg",
                    evidence_refs=("ev:frontmatter:1",),
                    confidence=0.55,
                ),
            ),
            evidence=(
                _evidence(
                    "ev:quote:1",
                    3,
                    "txt:segment:3",
                    evidence_type=GlossaryEvidenceType.QUOTE_ATTRIBUTION,
                ),
                _evidence(
                    "ev:frontmatter:1",
                    0,
                    "epub:metadata:0",
                    source_scope="frontmatter/metadata",
                    surface=GlossaryEvidenceSurface.METADATA,
                ),
            ),
        )

        result = reduce_glossary_candidates(glossary)

        quoted = _decision(result, "entry:quoted-title")
        frontmatter = _decision(result, "entry:gutenberg")
        self.assertIsNot(
            quoted.status,
            GlossaryCandidateDecisionStatus.RETAINED_FOR_EDITOR,
        )
        self.assertIsNot(
            frontmatter.status,
            GlossaryCandidateDecisionStatus.RETAINED_FOR_EDITOR,
        )
        self.assertIn(
            GlossaryCandidateReductionReason.UNCERTAIN_ENTITY,
            quoted.reasons,
        )
        self.assertIn(
            GlossaryCandidateReductionReason.FRONTMATTER_OR_NAV_NOISE,
            frontmatter.reasons,
        )

    def test_caps_budget_and_deterministic_signature(self):
        entries = tuple(
            _entry(
                f"entry:term:{index:02d}",
                f"shared technical term {index}",
                category=GlossaryEntryCategory.TERM,
                evidence_refs=(f"ev:term:{index:02d}",),
                confidence=0.8 + index / 1000,
            )
            for index in range(10)
        )
        glossary = _glossary(
            entries,
            evidence=tuple(
                _evidence(
                    f"ev:term:{index:02d}",
                    index + 1,
                    f"txt:segment:{index + 1}",
                    occurrence_count=2,
                )
                for index in range(10)
            ),
        )
        caps = GlossaryCandidateReducerCaps(
            max_editor_entries=3,
            max_diagnostic_entries=2,
            max_estimated_editor_tokens=10_000,
            min_editor_score=220,
            min_diagnostic_score=80,
        )
        pressure_context = {
            "candidate_count": 10,
            "total_reserved_tokens": 25000,
            "raw_like_debug_text": "PRIVATE_PRESSURE_SENTINEL",
        }

        first = reduce_glossary_candidates(
            glossary,
            pressure_context=pressure_context,
            caps=caps,
        )
        second = reduce_glossary_candidates(
            glossary,
            pressure_context=pressure_context,
            caps=caps,
        )

        self.assertEqual(first.reducer_signature, second.reducer_signature)
        self.assertEqual(first.retained_entry_ids, second.retained_entry_ids)
        self.assertEqual(len(first.retained_entry_ids), 3)
        self.assertEqual(len(first.diagnostic_entry_ids), 2)
        self.assertTrue(
            any(
                GlossaryCandidateReductionReason.EDITOR_ENTRY_CAP_EXHAUSTED
                in decision.reasons
                for decision in first.decisions
            )
        )
        self.assertTrue(
            any(
                GlossaryCandidateReductionReason.DIAGNOSTIC_CAP_EXHAUSTED
                in decision.reasons
                for decision in first.decisions
            )
        )
        token_limited = reduce_glossary_candidates(
            glossary,
            caps=GlossaryCandidateReducerCaps(
                max_editor_entries=10,
                max_diagnostic_entries=10,
                max_estimated_editor_tokens=1,
                min_editor_score=220,
                min_diagnostic_score=80,
            ),
        )
        self.assertEqual(token_limited.retained_entry_ids, ())
        self.assertTrue(
            any(
                GlossaryCandidateReductionReason.TOKEN_BUDGET_EXHAUSTED
                in decision.reasons
                for decision in token_limited.decisions
            )
        )

    def test_serialized_reduction_excludes_raw_text(self):
        raw_source = "PRIVATE_SOURCE_SENTINEL Elizabeth Bennet"
        raw_target = "PRIVATE_TARGET_SENTINEL Elizabeth translation"
        glossary = _glossary(
            (
                _entry(
                    "entry:safe-id",
                    raw_source,
                    aliases=(raw_source,),
                    target=raw_target,
                    evidence_refs=("ev:raw:1",),
                    confidence=0.9,
                ),
            ),
            evidence=(
                _evidence(
                    "ev:raw:1",
                    1,
                    "txt:segment:1",
                    occurrence_count=3,
                    raw_excerpt=raw_source,
                ),
            ),
        )

        result = reduce_glossary_candidates(
            glossary,
            pressure_context={"raw_context": "PRIVATE_PRESSURE_SENTINEL"},
        )
        self.assertTrue(validate_glossary_snapshot(result.retained_snapshot).valid)
        self.assertTrue(
            all(
                evidence.raw_excerpt is None
                for evidence in result.retained_snapshot.evidence
            )
        )
        serialized = serialize_glossary_candidate_reduction(result)
        payload_text = json.dumps(
            glossary_candidate_reduction_payload(result),
            ensure_ascii=False,
            sort_keys=True,
        )

        self.assertIn("entry:safe-id", serialized)
        self.assertIn("source_digest", serialized)
        self.assertIn("pressure_signature", serialized)
        for forbidden in (
            raw_source,
            raw_target,
            "PRIVATE_SOURCE_SENTINEL",
            "PRIVATE_TARGET_SENTINEL",
            "PRIVATE_PRESSURE_SENTINEL",
        ):
            self.assertNotIn(forbidden, serialized)
            self.assertNotIn(forbidden, payload_text)

    def test_rejects_invalid_caps(self):
        with self.assertRaises(ValueError):
            reduce_glossary_candidates(
                _glossary((), evidence=()),
                caps=GlossaryCandidateReducerCaps(max_editor_entries=-1),
            )


def _decision(result, entry_id: str):
    for decision in result.decisions:
        if decision.entry_id == entry_id:
            return decision
    raise AssertionError(f"Missing reducer decision for {entry_id}.")


def _glossary(
    entries: tuple[GlossaryEntry, ...],
    *,
    evidence: tuple[GlossaryEvidenceRef, ...],
) -> GlossarySnapshot:
    return GlossarySnapshot(
        snapshot_id="glossary-snapshot:test",
        source_language="en",
        target_language="ru",
        entries=entries,
        evidence=evidence,
    )


def _entry(
    entry_id: str,
    source: str,
    *,
    category: GlossaryEntryCategory = GlossaryEntryCategory.NAME,
    layer: GlossaryLayer = GlossaryLayer.SOFT,
    status: GlossaryEntryStatus = GlossaryEntryStatus.AUTO_DETECTED,
    target: str | None = None,
    aliases: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...],
    confidence: float = 0.7,
    profile_rule_ids: tuple[str, ...] = (),
) -> GlossaryEntry:
    return GlossaryEntry(
        entry_id=entry_id,
        category=category,
        layer=layer,
        status=status,
        source_canonical=source,
        aliases=aliases,
        target_canonical=target,
        evidence_refs=evidence_refs,
        confidence=confidence,
        strategy=GlossaryStrategy.TRANSLITERATE,
        grammatical_gender=GlossaryGender.UNKNOWN,
        profile_rule_ids=profile_rule_ids,
    )


def _evidence(
    evidence_id: str,
    unit_sequence: int,
    source_block_id: str,
    *,
    evidence_type: GlossaryEvidenceType = GlossaryEvidenceType.SOURCE_ANCHOR,
    source_scope: str = "chapter-1",
    surface: GlossaryEvidenceSurface = GlossaryEvidenceSurface.BODY,
    occurrence_count: int = 1,
    raw_excerpt: str | None = None,
) -> GlossaryEvidenceRef:
    return GlossaryEvidenceRef(
        evidence_id=evidence_id,
        evidence_type=evidence_type,
        unit_sequence=unit_sequence,
        source_block_id=source_block_id,
        source_scope=source_scope,
        surface=surface,
        occurrence_count=occurrence_count,
        raw_excerpt=raw_excerpt,
    )


def _profile_detection() -> BookProfileDetection:
    evidence = GlossaryEvidenceRef(
        evidence_id="ev:profile:1",
        evidence_type=GlossaryEvidenceType.HEADING,
        unit_sequence=1,
        source_block_id="txt:segment:1",
        source_scope="chapter-1",
        surface=GlossaryEvidenceSurface.HEADING,
    )
    profile = BookProfile(
        profile_id="book-profile:literary-fiction:test",
        source_language="en",
        target_language="ru",
        primary_profile=BookProfileKind.LITERARY_FICTION,
        document_type=BookDocumentType.BOOK_MANUSCRIPT,
        fictionality=Fictionality.FICTION,
        dialogue_density=DialogueDensity.MEDIUM,
        register=BookRegister.LITERARY,
        confidence=0.82,
        evidence_refs=("ev:profile:1",),
        terminology_strictness=TerminologyStrictness.MEDIUM,
        paraphrase_allowance=ParaphraseAllowance.MEDIUM,
        named_entity_policy=NamedEntityPolicy.CONTEXTUAL,
        source_pair_policy="source-pair:en-ru:v1",
        target_language_policy="target-profile:ru:russian-v2",
    )
    rule = ProfileSpecificGlossaryRule(
        rule_id="profile-rule:literary-fiction:names-v1",
        rule_type=ProfileGlossaryRuleType.NAMED_ENTITY_STRATEGY,
        applies_to_profiles=(BookProfileKind.LITERARY_FICTION,),
        scope_category=GlossaryEntryCategory.NAME,
        target_languages=("ru",),
        glossary_strategy=GlossaryStrategy.CONTEXTUAL,
        terminology_strictness=TerminologyStrictness.MEDIUM,
        paraphrase_allowance=ParaphraseAllowance.MEDIUM,
        named_entity_policy=NamedEntityPolicy.CONTEXTUAL,
        fallback_strategy=GlossaryStrategy.TRANSLITERATE,
        evidence_refs=("ev:profile:1",),
    )
    return BookProfileDetection(profile=profile, rules=(rule,), evidence=(evidence,))


if __name__ == "__main__":
    unittest.main()
