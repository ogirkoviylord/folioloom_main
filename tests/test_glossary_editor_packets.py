import json
import unittest
from pathlib import Path

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
from translator_service.format_adapters.txt import plan_txt_translation
from translator_service.glossary_candidate_reducer import (
    GlossaryCandidateReducerCaps,
    reduce_glossary_candidates,
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
from translator_service.glossary_editor_packets import (
    DEFAULT_GLOSSARY_EDITOR_PACKET_BUDGET,
    DEFAULT_REDUCED_GLOSSARY_EDITOR_PACKET_BUDGET,
    GlossaryEditorPacketBudget,
    GlossaryEditorPacketDegradationReason,
    GlossaryEditorPacketStatus,
    build_glossary_editor_packets,
    glossary_editor_packet_payload,
    serialize_glossary_editor_packet,
)
from translator_service.glossary_scanner import scan_glossary_candidates


class GlossaryEditorPacketTest(unittest.TestCase):
    def test_builds_stable_packets_with_reference_payload(self):
        glossary = _glossary_snapshot()
        profile = _profile_detection()

        first = build_glossary_editor_packets(glossary, profile)
        reordered = build_glossary_editor_packets(
            glossary.__class__(
                **{
                    **glossary.__dict__,
                    "entries": tuple(reversed(glossary.entries)),
                    "evidence": tuple(reversed(glossary.evidence)),
                }
            ),
            profile,
        )

        self.assertEqual(first.build_signature, reordered.build_signature)
        self.assertEqual(len(first.packets), 1)
        packet = first.packets[0]
        self.assertEqual(packet.status, GlossaryEditorPacketStatus.READY)
        self.assertEqual(
            packet.entry_ids,
            ("entry:darcy", "entry:elizabeth", "entry:quantum-drive"),
        )
        self.assertLessEqual(
            packet.estimated_prompt_tokens,
            packet.max_estimated_prompt_tokens,
        )
        self.assertLessEqual(
            packet.reserved_prompt_tokens,
            packet.max_reserved_prompt_tokens,
        )

        payload = serialize_glossary_editor_packet(packet)
        self.assertIn("source_digest", payload)
        self.assertIn("entry:elizabeth", payload)
        self.assertNotIn("Elizabeth Bennet", payload)
        self.assertNotIn("raw_excerpt", payload)
        self.assertNotIn("raw source text", payload)
        self.assertNotIn("reducer_context", payload)
        self.assertNotIn("reducer_decision_status", payload)
        self.assertNotIn("split_reason_codes", payload)

    def test_reduced_candidates_build_packets_with_reducer_metadata(self):
        glossary = _high_noise_glossary_snapshot(noisy_count=18)
        profile = _profile_detection()
        budget = GlossaryEditorPacketBudget(max_entries_per_packet=4)
        full = build_glossary_editor_packets(glossary, profile, budget=budget)
        reduction = reduce_glossary_candidates(
            glossary,
            profile_detection=profile,
            caps=GlossaryCandidateReducerCaps(max_editor_entries=8),
        )

        reduced = build_glossary_editor_packets(
            glossary,
            profile,
            budget=budget,
            candidate_reduction=reduction,
        )
        repeated = build_glossary_editor_packets(
            glossary,
            profile,
            budget=budget,
            candidate_reduction=reduction,
        )

        self.assertLess(len(reduced.packets), len(full.packets))
        self.assertEqual(reduced.build_signature, repeated.build_signature)
        self.assertIsNotNone(reduced.reducer_context)
        self.assertEqual(
            reduced.reducer_context.reducer_signature,
            reduction.reducer_signature,
        )
        self.assertEqual(
            reduced.reducer_context.retained_count,
            len(reduction.retained_entry_ids),
        )
        self.assertEqual(
            reduced.glossary_signature,
            reduction.reduced_glossary_signature,
        )
        retained_ids = set(reduction.retained_entry_ids)
        self.assertTrue(retained_ids)
        self.assertTrue(
            all(
                entry_id in retained_ids
                for packet in reduced.packets
                for entry_id in packet.entry_ids
            )
        )

        packet_payload = glossary_editor_packet_payload(reduced.packets[0])
        self.assertIn("reducer_context", packet_payload)
        self.assertIn("reducer_decision_status", packet_payload["entries"][0])
        self.assertEqual(
            packet_payload["reducer_context"]["reducer_signature"],
            reduction.reducer_signature,
        )
        serialized = "\n".join(
            serialize_glossary_editor_packet(packet) for packet in reduced.packets
        )
        self.assertIn("retained_for_editor", serialized)
        self.assertNotIn("Frontmatter Noise", serialized)
        self.assertNotIn("raw_excerpt", serialized)

    def test_rejects_reduction_from_different_source_snapshot(self):
        glossary = _high_noise_glossary_snapshot(noisy_count=4)
        profile = _profile_detection()
        reduction = reduce_glossary_candidates(
            glossary,
            profile_detection=profile,
        )
        mismatched = reduction.__class__(
            **{
                **reduction.__dict__,
                "source_glossary_signature": "glossary-snapshot:v1:mismatch",
            }
        )

        with self.assertRaisesRegex(ValueError, "source glossary signature mismatch"):
            build_glossary_editor_packets(
                glossary,
                profile,
                candidate_reduction=mismatched,
            )

    def test_caps_evidence_refs_and_records_degradation(self):
        glossary = _glossary_snapshot(extra_evidence_count=5)
        profile = _profile_detection()

        result = build_glossary_editor_packets(
            glossary,
            profile,
            budget=GlossaryEditorPacketBudget(max_evidence_refs_per_entry=2),
        )

        packet = result.packets[0]
        elizabeth = {
            entry.entry_id: entry for entry in packet.entries
        }["entry:elizabeth"]
        self.assertEqual(len(elizabeth.evidence_refs), 2)
        self.assertEqual(packet.status, GlossaryEditorPacketStatus.DEGRADED)
        self.assertIn(
            GlossaryEditorPacketDegradationReason.EVIDENCE_REF_LIMIT_EXHAUSTED,
            {degradation.reason for degradation in packet.degradations},
        )
        self.assertTrue(
            all(
                evidence_id in {evidence.evidence_id for evidence in glossary.evidence}
                for evidence_id in elizabeth.evidence_refs
            )
        )

    def test_skips_unpacketable_entry_with_metadata(self):
        long_source = "VeryLongCandidate " * 900
        glossary = GlossarySnapshot(
            snapshot_id="glossary-snapshot:test",
            source_language="en",
            target_language="ru",
            entries=(
                GlossaryEntry(
                    entry_id="entry:oversized",
                    category=GlossaryEntryCategory.TERM,
                    layer=GlossaryLayer.SOFT,
                    status=GlossaryEntryStatus.UNCERTAIN,
                    source_canonical=long_source,
                    evidence_refs=("ev:oversized",),
                    confidence=0.5,
                    strategy=GlossaryStrategy.UNKNOWN,
                    grammatical_gender=GlossaryGender.NOT_APPLICABLE,
                ),
            ),
            evidence=(
                _evidence("ev:oversized", 1, "txt:segment:1"),
            ),
        )

        result = build_glossary_editor_packets(
            glossary,
            _profile_detection(),
            budget=GlossaryEditorPacketBudget(max_estimated_prompt_tokens=200),
        )

        self.assertEqual(result.packets, ())
        self.assertEqual(len(result.skipped_entries), 1)
        self.assertEqual(
            result.skipped_entries[0].reason,
            GlossaryEditorPacketDegradationReason.ENTRY_BUDGET_EXCEEDED,
        )
        skipped_payload = json.dumps(
            result.skipped_entries[0].__dict__,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        self.assertNotIn("VeryLongCandidate", skipped_payload)

    def test_skips_single_entry_packet_when_evidence_overhead_exceeds_budget(self):
        beta_evidence_refs = tuple(f"ev:beta:{index}" for index in range(4))
        glossary = GlossarySnapshot(
            snapshot_id="glossary-snapshot:test",
            source_language="en",
            target_language="ru",
            entries=(
                _entry("entry:alpha", "Alpha", evidence_refs=("ev:alpha:1",)),
                _entry("entry:beta", "Beta", evidence_refs=beta_evidence_refs),
            ),
            evidence=(
                _evidence("ev:alpha:1", 1, "txt:segment:1"),
                *(
                    _evidence(
                        f"ev:beta:{index}",
                        index + 2,
                        f"txt:segment:{index + 2}",
                    )
                    for index in range(4)
                ),
            ),
        )

        result = build_glossary_editor_packets(
            glossary,
            _profile_detection(),
            budget=GlossaryEditorPacketBudget(
                max_entries_per_packet=1,
                max_evidence_refs_per_entry=4,
                max_estimated_prompt_tokens=140,
            ),
        )

        self.assertEqual([packet.entry_ids for packet in result.packets], [
            ("entry:alpha",),
        ])
        self.assertTrue(
            all(
                packet.estimated_prompt_tokens <= packet.max_estimated_prompt_tokens
                for packet in result.packets
            )
        )
        self.assertEqual(len(result.skipped_entries), 1)
        self.assertEqual(result.skipped_entries[0].entry_id, "entry:beta")
        self.assertEqual(
            result.skipped_entries[0].reason,
            GlossaryEditorPacketDegradationReason.ENTRY_BUDGET_EXCEEDED,
        )

    def test_fixture_packets_split_large_regression_samples(self):
        fixture_expectations = {
            "test_samples/russian_profile_regression.en-ru.txt": ("ru", 2),
            "test_samples/ukrainian_profile_regression.en-uk.txt": ("uk", 2),
            "test_samples/sample_book.en.txt": ("ru", 1),
        }

        for fixture, (target_language, minimum_packets) in fixture_expectations.items():
            with self.subTest(fixture=fixture):
                result = _pack_fixture(fixture, target_language)
                self.assertGreaterEqual(len(result.packets), minimum_packets)
                self.assertEqual(result.skipped_entries, ())
                signatures = [packet.packet_signature for packet in result.packets]
                self.assertEqual(len(signatures), len(set(signatures)))
                for packet in result.packets:
                    self.assertLessEqual(
                        packet.estimated_prompt_tokens,
                        packet.max_estimated_prompt_tokens,
                    )
                    self.assertLessEqual(
                        packet.reserved_prompt_tokens,
                        packet.max_reserved_prompt_tokens,
                    )
                    self.assertGreater(packet.entry_ids, ())
                    self.assertTrue(
                        set(packet.evidence_ids).issuperset(
                            evidence_ref
                            for entry in packet.entries
                            for evidence_ref in entry.evidence_refs
                        )
                    )
                    serialized = serialize_glossary_editor_packet(packet)
                    self.assertNotIn("raw_excerpt", serialized)

    def test_reduced_fixture_packets_use_hardened_budget_and_split_metadata(self):
        fixture_expectations = {
            "test_samples/russian_profile_regression.en-ru.txt": ("ru", 10),
            "test_samples/ukrainian_profile_regression.en-uk.txt": ("uk", 10),
            "test_samples/sample_book.en.txt": ("ru", 1),
        }

        for fixture, expectation in fixture_expectations.items():
            target_language, expected_packets = expectation
            with self.subTest(fixture=fixture):
                full = _pack_fixture(fixture, target_language)
                reduced = _pack_reduced_fixture(fixture, target_language)

                self.assertEqual(
                    full.packets[0].max_estimated_prompt_tokens,
                    DEFAULT_GLOSSARY_EDITOR_PACKET_BUDGET.max_estimated_prompt_tokens,
                )
                self.assertEqual(len(reduced.packets), expected_packets)
                self.assertEqual(reduced.skipped_entries, ())
                self.assertIsNotNone(reduced.reducer_context)
                for packet in reduced.packets:
                    self.assertEqual(
                        packet.max_estimated_prompt_tokens,
                        DEFAULT_REDUCED_GLOSSARY_EDITOR_PACKET_BUDGET
                        .max_estimated_prompt_tokens,
                    )
                    self.assertLessEqual(
                        len(packet.entries),
                        DEFAULT_REDUCED_GLOSSARY_EDITOR_PACKET_BUDGET.max_entries_per_packet,
                    )
                    self.assertLessEqual(
                        packet.estimated_prompt_tokens,
                        packet.max_estimated_prompt_tokens,
                    )
                    self.assertLessEqual(
                        packet.reserved_prompt_tokens,
                        packet.max_reserved_prompt_tokens,
                    )
                    self.assertEqual(packet.status, GlossaryEditorPacketStatus.READY)
                    self.assertTrue(
                        set(packet.evidence_ids).issuperset(
                            evidence_ref
                            for entry in packet.entries
                            for evidence_ref in entry.evidence_refs
                        )
                    )
                    payload = glossary_editor_packet_payload(packet)
                    if packet.split_reason_codes:
                        self.assertEqual(
                            payload["split_reason_codes"],
                            list(packet.split_reason_codes),
                        )
                    else:
                        self.assertNotIn("split_reason_codes", payload)
                    self.assertIn("reducer_context", payload)
                    self.assertEqual(
                        payload["reducer_context"]["retained_count"],
                        reduced.reducer_context.retained_count,
                    )

                split_reasons = {
                    reason
                    for packet in reduced.packets
                    for reason in packet.split_reason_codes
                }
                if expected_packets > 1:
                    self.assertIn(
                        GlossaryEditorPacketDegradationReason.ENTRY_LIMIT_EXHAUSTED.value,
                        split_reasons,
                    )

    def test_fixture_packet_payload_is_metadata_only_for_document_text(self):
        fixture = "test_samples/russian_profile_regression.en-ru.txt"
        fixture_text = Path(fixture).read_text(encoding="utf-8")
        result = _pack_fixture(fixture, "ru")
        payloads = "\n".join(
            serialize_glossary_editor_packet(packet) for packet in result.packets
        )

        self.assertNotEqual(fixture_text.strip(), "")
        self.assertNotIn(fixture_text[:80], payloads)
        self.assertNotIn("system prompt", payloads.lower())
        self.assertIn("source_digest", payloads)

    def test_rejects_mismatched_profile_language(self):
        glossary = _glossary_snapshot()
        profile = _profile_detection(target_language="uk")

        with self.assertRaisesRegex(ValueError, "target_language mismatch"):
            build_glossary_editor_packets(glossary, profile)


def _pack_fixture(fixture: str, target_language: str):
    content = Path(fixture).read_bytes()
    plan = plan_txt_translation(content=content, max_fragment_chars=2400)
    glossary = scan_glossary_candidates(
        plan,
        source_language="en",
        target_language=target_language,
    )
    profile = detect_book_profile(
        plan,
        source_language="en",
        target_language=target_language,
        glossary_snapshot=glossary,
    )
    return build_glossary_editor_packets(glossary, profile)


def _pack_reduced_fixture(fixture: str, target_language: str):
    content = Path(fixture).read_bytes()
    plan = plan_txt_translation(content=content, max_fragment_chars=2400)
    glossary = scan_glossary_candidates(
        plan,
        source_language="en",
        target_language=target_language,
    )
    profile = detect_book_profile(
        plan,
        source_language="en",
        target_language=target_language,
        glossary_snapshot=glossary,
    )
    reduction = reduce_glossary_candidates(
        glossary,
        profile_detection=profile,
    )
    return build_glossary_editor_packets(
        glossary,
        profile,
        candidate_reduction=reduction,
    )


def _glossary_snapshot(*, extra_evidence_count: int = 0) -> GlossarySnapshot:
    entries = (
        _entry(
            "entry:darcy",
            "Darcy",
            evidence_refs=("ev:darcy:1",),
        ),
        _entry(
            "entry:quantum-drive",
            "quantum drive",
            category=GlossaryEntryCategory.TERM,
            evidence_refs=("ev:term:1",),
            grammatical_gender=GlossaryGender.NOT_APPLICABLE,
        ),
        _entry(
            "entry:elizabeth",
            "Elizabeth Bennet",
            aliases=("Elizabeth",),
            evidence_refs=tuple(
                ["ev:elizabeth:1", "ev:elizabeth:2"]
                + [
                    f"ev:elizabeth:extra:{index}"
                    for index in range(extra_evidence_count)
                ]
            ),
        ),
    )
    evidence = (
        _evidence("ev:darcy:1", 2, "txt:segment:2"),
        _evidence("ev:term:1", 3, "txt:segment:3"),
        _evidence("ev:elizabeth:1", 1, "txt:segment:1"),
        _evidence("ev:elizabeth:2", 2, "txt:segment:2"),
        *(
            _evidence(
                f"ev:elizabeth:extra:{index}",
                index + 4,
                f"txt:segment:{index + 4}",
            )
            for index in range(extra_evidence_count)
        ),
    )
    return GlossarySnapshot(
        snapshot_id="glossary-snapshot:test",
        source_language="en",
        target_language="ru",
        entries=entries,
        evidence=evidence,
    )


def _high_noise_glossary_snapshot(*, noisy_count: int) -> GlossarySnapshot:
    important_entries = (
        GlossaryEntry(
            entry_id="entry:elizabeth",
            category=GlossaryEntryCategory.NAME,
            layer=GlossaryLayer.SOFT,
            status=GlossaryEntryStatus.AUTO_DETECTED,
            source_canonical="Elizabeth Bennet",
            aliases=("Elizabeth",),
            evidence_refs=("ev:elizabeth:1", "ev:elizabeth:2"),
            confidence=0.84,
            strategy=GlossaryStrategy.TRANSLITERATE,
            grammatical_gender=GlossaryGender.UNKNOWN,
        ),
        GlossaryEntry(
            entry_id="entry:quantum-drive",
            category=GlossaryEntryCategory.TERM,
            layer=GlossaryLayer.SOFT,
            status=GlossaryEntryStatus.AUTO_DETECTED,
            source_canonical="quantum drive",
            evidence_refs=("ev:term:1",),
            confidence=0.88,
            strategy=GlossaryStrategy.PRESERVE_OFFICIAL,
            grammatical_gender=GlossaryGender.NOT_APPLICABLE,
        ),
    )
    noisy_entries = tuple(
        GlossaryEntry(
            entry_id=f"entry:noise:{index:02d}",
            category=GlossaryEntryCategory.NAME,
            layer=GlossaryLayer.SOFT,
            status=GlossaryEntryStatus.UNCERTAIN,
            source_canonical=f"Frontmatter Noise {index}",
            evidence_refs=(f"ev:noise:{index:02d}",),
            confidence=0.41,
            strategy=GlossaryStrategy.UNKNOWN,
            grammatical_gender=GlossaryGender.UNKNOWN,
        )
        for index in range(noisy_count)
    )
    evidence = (
        _evidence("ev:elizabeth:1", 1, "txt:segment:1"),
        _evidence("ev:elizabeth:2", 3, "txt:segment:3"),
        _evidence("ev:term:1", 2, "txt:segment:2", occurrence_count=3),
        *(
            _evidence(
                f"ev:noise:{index:02d}",
                0,
                f"epub:nav.xhtml:{index}",
                source_scope="frontmatter/nav",
                surface=GlossaryEvidenceSurface.NAV,
            )
            for index in range(noisy_count)
        ),
    )
    return GlossarySnapshot(
        snapshot_id="glossary-snapshot:noisy-test",
        source_language="en",
        target_language="ru",
        entries=(*important_entries, *noisy_entries),
        evidence=evidence,
    )


def _entry(
    entry_id: str,
    source: str,
    *,
    category: GlossaryEntryCategory = GlossaryEntryCategory.NAME,
    evidence_refs: tuple[str, ...],
    grammatical_gender: GlossaryGender = GlossaryGender.UNKNOWN,
    aliases: tuple[str, ...] = (),
) -> GlossaryEntry:
    return GlossaryEntry(
        entry_id=entry_id,
        category=category,
        layer=GlossaryLayer.SOFT,
        status=GlossaryEntryStatus.UNCERTAIN,
        source_canonical=source,
        aliases=aliases,
        target_canonical=None,
        evidence_refs=evidence_refs,
        confidence=0.72,
        strategy=GlossaryStrategy.UNKNOWN,
        grammatical_gender=grammatical_gender,
    )


def _evidence(
    evidence_id: str,
    unit_sequence: int,
    source_block_id: str,
    *,
    occurrence_count: int = 1,
    source_scope: str = "chapter-1",
    surface: GlossaryEvidenceSurface = GlossaryEvidenceSurface.BODY,
) -> GlossaryEvidenceRef:
    return GlossaryEvidenceRef(
        evidence_id=evidence_id,
        evidence_type=GlossaryEvidenceType.EXACT_REPEAT,
        unit_sequence=unit_sequence,
        source_block_id=source_block_id,
        source_scope=source_scope,
        surface=surface,
        occurrence_count=occurrence_count,
        raw_excerpt=None,
    )


def _profile_detection(*, target_language: str = "ru") -> BookProfileDetection:
    evidence = GlossaryEvidenceRef(
        evidence_id="ev:profile:1",
        evidence_type=GlossaryEvidenceType.HEADING,
        unit_sequence=1,
        source_block_id="txt:segment:1",
        source_scope="chapter-1",
        surface=GlossaryEvidenceSurface.HEADING,
        raw_excerpt=None,
    )
    profile = BookProfile(
        profile_id=f"book-profile:literary-fiction:{target_language}:test",
        source_language="en",
        target_language=target_language,
        primary_profile=BookProfileKind.LITERARY_FICTION,
        document_type=BookDocumentType.BOOK_MANUSCRIPT,
        fictionality=Fictionality.FICTION,
        dialogue_density=DialogueDensity.MEDIUM,
        register=BookRegister.LITERARY,
        confidence=0.77,
        evidence_refs=("ev:profile:1",),
        terminology_strictness=TerminologyStrictness.MEDIUM,
        paraphrase_allowance=ParaphraseAllowance.MEDIUM,
        named_entity_policy=NamedEntityPolicy.CONTEXTUAL,
        source_pair_policy=f"source-pair:en-{target_language}:v1",
        target_language_policy=f"target-profile:{target_language}:test-v1",
    )
    rule = ProfileSpecificGlossaryRule(
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
        evidence_refs=("ev:profile:1",),
    )
    return BookProfileDetection(profile=profile, rules=(rule,), evidence=(evidence,))


if __name__ == "__main__":
    unittest.main()
