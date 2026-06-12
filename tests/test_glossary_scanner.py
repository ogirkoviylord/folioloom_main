import unittest

from translator_service.documents import DocumentFormat
from translator_service.format_adapters.contracts import (
    FormatAdapterPlan,
    FormatTextBlock,
    FormatTranslationUnit,
)
from translator_service.glossary_contracts import (
    GlossaryEntryCategory,
    GlossaryEntryStatus,
    GlossaryEvidenceType,
    GlossaryGender,
    glossary_snapshot_signature,
    validate_glossary_snapshot,
)
from translator_service.glossary_scanner import scan_glossary_candidates
from translator_service.structure_optimizer import PromptTier, TextBlockKind


class GlossaryScannerTest(unittest.TestCase):
    def test_scans_repeated_names_terms_and_aliases_deterministically(self):
        plan = _plan(
            (
                _unit(
                    1,
                    _block(
                        0,
                        "txt:segment:1",
                        "Elizabeth Bennet met Mr Darcy at Longbourn.",
                    ),
                ),
                _unit(
                    2,
                    _block(
                        1,
                        "txt:segment:2",
                        "Elizabeth spoke softly. Darcy answered Elizabeth.",
                    ),
                ),
                _unit(
                    3,
                    _block(
                        2,
                        "txt:segment:3",
                        "The quantum drive hummed. Another quantum drive failed.",
                    ),
                ),
            )
        )

        first = scan_glossary_candidates(
            plan,
            source_language="en",
            target_language="ru",
        )
        second = scan_glossary_candidates(
            plan,
            source_language="en",
            target_language="ru",
        )

        self.assertEqual(
            glossary_snapshot_signature(first),
            glossary_snapshot_signature(second),
        )
        self.assertTrue(validate_glossary_snapshot(first).valid)
        entries = _entries_by_source(first)
        self.assertIn("Elizabeth Bennet", entries)
        self.assertIn("Elizabeth", entries["Elizabeth Bennet"].aliases)
        elizabeth_evidence = [
            evidence
            for evidence in first.evidence
            if evidence.evidence_id in entries["Elizabeth Bennet"].evidence_refs
        ]
        self.assertIn(
            "txt:segment:2",
            {evidence.source_block_id for evidence in elizabeth_evidence},
        )
        self.assertIn("quantum drive", entries)
        self.assertEqual(
            entries["quantum drive"].category,
            GlossaryEntryCategory.TERM,
        )
        self.assertTrue(all(ref.raw_excerpt is None for ref in first.evidence))
        self.assertTrue(
            all(len(entry.evidence_refs) <= 3 for entry in first.entries),
        )

    def test_marks_ambiguous_single_token_name_as_unknown(self):
        snapshot = scan_glossary_candidates(
            _plan(
                (
                    _unit(1, _block(0, "txt:segment:1", "Sasha waited.")),
                    _unit(2, _block(1, "txt:segment:2", "Sasha answered.")),
                    _unit(3, _block(2, "txt:segment:3", "Sasha smiled.")),
                )
            ),
            source_language="en",
            target_language="uk",
        )

        entry = _entries_by_source(snapshot)["Sasha"]

        self.assertEqual(entry.status, GlossaryEntryStatus.UNCERTAIN)
        self.assertEqual(entry.grammatical_gender, GlossaryGender.UNKNOWN)
        self.assertIn("ru_uk_morphology_tbd", entry.morphology_notes)
        self.assertTrue(validate_glossary_snapshot(snapshot).valid)

    def test_scans_quoted_names_with_metadata_only_evidence(self):
        snapshot = scan_glossary_candidates(
            _plan(
                (
                    _unit(
                        1,
                        _block(
                            0,
                            "epub:body:chapter1:0",
                            '"The Silver Key" appeared in the ledger.',
                            kind=TextBlockKind.HEADING,
                            metadata=(("file_name", "EPUB/chapter1.xhtml"),),
                        ),
                    ),
                    _unit(
                        2,
                        _block(
                            1,
                            "epub:body:chapter1:1",
                            'Later "The Silver Key" opened the archive.',
                            metadata=(("file_name", "EPUB/chapter1.xhtml"),),
                        ),
                    ),
                ),
                document_format=DocumentFormat.EPUB,
            ),
            source_language="en",
            target_language="ru",
        )

        entry = _entries_by_source(snapshot)["The Silver Key"]
        evidence = [
            evidence
            for evidence in snapshot.evidence
            if evidence.evidence_id in entry.evidence_refs
        ]

        self.assertEqual(entry.category, GlossaryEntryCategory.ENTITY)
        self.assertEqual(entry.status, GlossaryEntryStatus.UNCERTAIN)
        self.assertEqual(
            evidence[0].evidence_type,
            GlossaryEvidenceType.QUOTE_ATTRIBUTION,
        )
        self.assertEqual(evidence[0].source_scope, "EPUB/chapter1.xhtml")
        self.assertTrue(all(item.raw_excerpt is None for item in evidence))
        self.assertTrue(validate_glossary_snapshot(snapshot).valid)

    def test_returns_valid_empty_snapshot_for_no_candidate_document(self):
        snapshot = scan_glossary_candidates(
            _plan(
                (
                    _unit(
                        1,
                        _block(
                            0,
                            "txt:segment:1",
                            "and the but or it is to be with that.",
                        ),
                    ),
                )
            )
        )

        self.assertEqual(snapshot.entries, ())
        self.assertEqual(snapshot.evidence, ())
        self.assertTrue(validate_glossary_snapshot(snapshot).valid)

    def test_bounds_evidence_refs_per_candidate(self):
        snapshot = scan_glossary_candidates(
            _plan(
                (
                    _unit(1, _block(0, "txt:segment:1", "Ada Lovelace wrote.")),
                    _unit(2, _block(1, "txt:segment:2", "Ada Lovelace tested.")),
                    _unit(3, _block(2, "txt:segment:3", "Ada Lovelace revised.")),
                    _unit(4, _block(3, "txt:segment:4", "Ada Lovelace shipped.")),
                )
            ),
            max_evidence_refs_per_entry=2,
        )

        entry = _entries_by_source(snapshot)["Ada Lovelace"]

        self.assertEqual(len(entry.evidence_refs), 2)
        self.assertEqual(len(snapshot.evidence), 2)
        self.assertTrue(validate_glossary_snapshot(snapshot).valid)

    def test_rejects_unsupported_plan_format(self):
        with self.assertRaisesRegex(ValueError, "Unsupported glossary scanner"):
            scan_glossary_candidates(
                _plan(
                    (
                        _unit(1, _block(0, "pdf:block:1", "Elizabeth Bennet")),
                    ),
                    document_format=DocumentFormat.PDF,
                )
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
    metadata: tuple[tuple[str, str], ...] = (),
) -> FormatTextBlock:
    return FormatTextBlock(
        index=index,
        source_block_id=source_block_id,
        text=text,
        kind=kind,
        metadata=metadata,
    )


def _entries_by_source(snapshot):
    return {entry.source_canonical: entry for entry in snapshot.entries}


if __name__ == "__main__":
    unittest.main()
