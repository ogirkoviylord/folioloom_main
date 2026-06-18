import json
import unittest
from types import SimpleNamespace

from translator_service.glossary_candidate_quality import (
    filter_prepared_glossary_candidates,
)
from translator_service.glossary_contracts import (
    GlossaryEntry,
    GlossaryEntryCategory,
    GlossaryEntryStatus,
    GlossaryLayer,
)


class PreparedGlossaryCandidateQualityTests(unittest.TestCase):
    def test_drops_pronoun_function_and_boilerplate_phrases(self):
        entries = (
            _entry("Then He", aliases=("Then", "He")),
            _entry("In God", aliases=("God",)),
            _entry("Chapter I", aliases=("Chapter",)),
        )

        result = filter_prepared_glossary_candidates(
            entries,
            upstream_selector_signature="reducer:test",
            source_language="en",
        )

        self.assertEqual(result.entries, ())
        self.assertEqual(result.metadata["input_candidate_count"], 3)
        self.assertEqual(result.metadata["selected_candidate_count"], 0)
        self.assertEqual(result.metadata["dropped_candidate_count"], 3)
        self.assertIn(
            "candidate_quality_pronoun_phrase",
            result.metadata["reason_codes"],
        )
        self.assertIn(
            "candidate_quality_common_phrase",
            result.metadata["reason_codes"],
        )
        self.assertIn(
            "candidate_quality_boilerplate_source",
            result.metadata["reason_codes"],
        )
        metadata_text = json.dumps(result.metadata, ensure_ascii=False)
        self.assertNotIn("Then He", metadata_text)
        self.assertNotIn("In God", metadata_text)

    def test_preserves_durable_candidates_and_prunes_low_value_aliases(self):
        entries = (
            _entry("Mr Darcy", aliases=("Darcy", "Mr", "He", "Then")),
            _entry(
                "quantum drive",
                category=GlossaryEntryCategory.TERM,
                aliases=("drive", "it"),
            ),
            _entry(
                "The Silver Key",
                category=GlossaryEntryCategory.ENTITY,
                aliases=("Silver Key", "the"),
            ),
            _entry("The Shire", aliases=("Shire", "the")),
        )

        result = filter_prepared_glossary_candidates(
            entries,
            upstream_selector_signature="reducer:test",
            source_language="en",
        )

        self.assertEqual([entry.source_canonical for entry in result.entries], [
            "Mr Darcy",
            "quantum drive",
            "The Silver Key",
            "The Shire",
        ])
        self.assertEqual(result.entries[0].aliases, ("Darcy",))
        self.assertEqual(result.entries[1].aliases, ("drive",))
        self.assertEqual(result.entries[2].aliases, ("Silver Key",))
        self.assertEqual(result.entries[3].aliases, ("Shire",))
        self.assertEqual(result.metadata["dropped_candidate_count"], 0)
        self.assertEqual(result.metadata["alias_omitted_count"], 6)
        self.assertIn(
            "candidate_quality_alias_pruned",
            result.metadata["reason_codes"],
        )

    def test_drops_low_value_repeated_term_phrases_without_dropping_durable_terms(self):
        entries = (
            _entry(
                "came upon",
                category=GlossaryEntryCategory.TERM,
            ),
            _entry(
                "work work",
                category=GlossaryEntryCategory.TERM,
            ),
            _entry(
                "these people",
                category=GlossaryEntryCategory.TERM,
            ),
            _entry(
                "strange thing",
                category=GlossaryEntryCategory.TERM,
            ),
            _entry(
                "three dimensions",
                category=GlossaryEntryCategory.TERM,
            ),
            _entry(
                "time travelling",
                category=GlossaryEntryCategory.TERM,
            ),
            _entry(
                "bronze doors",
                category=GlossaryEntryCategory.TERM,
            ),
            _entry(
                "great hall",
                category=GlossaryEntryCategory.TERM,
            ),
        )

        result = filter_prepared_glossary_candidates(
            entries,
            upstream_selector_signature="reducer:test",
            source_language="en",
        )

        self.assertEqual([entry.source_canonical for entry in result.entries], [
            "three dimensions",
            "time travelling",
            "bronze doors",
            "great hall",
        ])
        self.assertEqual(result.metadata["input_candidate_count"], 8)
        self.assertEqual(result.metadata["selected_candidate_count"], 4)
        self.assertEqual(result.metadata["dropped_candidate_count"], 4)
        self.assertIn(
            "candidate_quality_low_value_repeated_term_phrase",
            result.metadata["reason_codes"],
        )
        metadata_text = json.dumps(result.metadata, ensure_ascii=False)
        self.assertNotIn("came upon", metadata_text)
        self.assertNotIn("three dimensions", metadata_text)

    def test_selection_cap_omits_extra_quality_candidates_without_raw_metadata(self):
        entries = (
            _entry(
                "three dimensions",
                category=GlossaryEntryCategory.TERM,
            ),
            _entry(
                "time travelling",
                category=GlossaryEntryCategory.TERM,
            ),
            _entry(
                "bronze doors",
                category=GlossaryEntryCategory.TERM,
            ),
        )

        result = filter_prepared_glossary_candidates(
            entries,
            upstream_selector_signature="reducer:test",
            source_language="en",
            max_selected_candidates=2,
        )

        self.assertEqual([entry.source_canonical for entry in result.entries], [
            "three dimensions",
            "time travelling",
        ])
        self.assertEqual(result.metadata["input_candidate_count"], 3)
        self.assertEqual(result.metadata["selected_candidate_count"], 2)
        self.assertEqual(result.metadata["dropped_candidate_count"], 0)
        self.assertEqual(result.metadata["omitted_candidate_count"], 1)
        self.assertIn(
            "candidate_quality_selection_cap_exhausted",
            result.metadata["reason_codes"],
        )
        metadata_text = json.dumps(result.metadata, ensure_ascii=False)
        self.assertNotIn("bronze doors", metadata_text)

    def test_selector_signature_changes_with_quality_decisions(self):
        clean = filter_prepared_glossary_candidates(
            (_entry("Mr Darcy", aliases=("Darcy",)),),
            upstream_selector_signature="reducer:test",
            source_language="en",
        )
        pruned = filter_prepared_glossary_candidates(
            (_entry("Mr Darcy", aliases=("Darcy", "He")),),
            upstream_selector_signature="reducer:test",
            source_language="en",
        )

        self.assertNotEqual(clean.selector_signature, pruned.selector_signature)
        self.assertTrue(
            clean.selector_signature.startswith(
                "prepared-glossary-candidate-quality:v1:"
            )
        )

    def test_quality_decisions_use_source_entry_id_when_entry_id_is_absent(self):
        entry = SimpleNamespace(
            source_entry_id="entry:prepared-darcy",
            source_canonical="Darcy",
            aliases=(),
        )

        result = filter_prepared_glossary_candidates(
            (entry,),
            upstream_selector_signature="reducer:test",
            source_language="en",
        )

        self.assertEqual(result.decisions[0].entry_id, "entry:prepared-darcy")
        self.assertEqual(result.entries, (entry,))


def _entry(
    source_canonical: str,
    *,
    category: GlossaryEntryCategory = GlossaryEntryCategory.NAME,
    aliases: tuple[str, ...] = (),
) -> GlossaryEntry:
    return GlossaryEntry(
        entry_id=f"entry:{source_canonical.casefold().replace(' ', '-')}",
        category=category,
        layer=GlossaryLayer.SOFT,
        status=GlossaryEntryStatus.AUTO_DETECTED,
        source_canonical=source_canonical,
        aliases=aliases,
        evidence_refs=("ev:1",),
        confidence=0.8,
    )


if __name__ == "__main__":
    unittest.main()
