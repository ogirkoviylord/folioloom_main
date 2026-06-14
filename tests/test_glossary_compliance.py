import json
import unittest

from translator_service.glossary_compliance import validate_glossary_compliance


def _entry(
    entry_id: str,
    *,
    source: str,
    target: str | None = None,
    aliases: tuple[str, ...] = (),
    target_variants: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "entry_id": entry_id,
        "source_canonical": source,
        "aliases": aliases,
        "target_canonical": target,
        "target_variants": target_variants,
    }


class GlossaryComplianceTest(unittest.TestCase):
    def test_full_hit_uses_source_terms_and_aliases(self):
        result = validate_glossary_compliance(
            [
                _entry("entry-north", source="North Door", target="Северница"),
                _entry(
                    "entry-salt",
                    source="Salt Thread",
                    aliases=("Thread-of-Salt",),
                    target_variants=("Солевязь",),
                ),
            ],
            selected_entry_ids=("entry-north", "entry-salt"),
            included_entry_ids=("entry-north", "entry-salt"),
            source_text="The North Door and Thread-of-Salt were marked.",
            translated_text="Северница и Солевязь были отмечены.",
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["checked_entry_count"], 2)
        self.assertEqual(result["target_form_present_count"], 2)
        self.assertEqual(result["target_form_missing_count"], 0)
        self.assertEqual(result["skipped_entry_count"], 0)
        self.assertEqual(
            result["target_form_present_entry_ids"],
            ["entry-north", "entry-salt"],
        )
        self.assertIn("morphology_policy_tbd", result["uncertainty_reason_codes"])

    def test_partial_and_zero_hits_are_findings_without_structural_failure(self):
        entries = [
            _entry("entry-north", source="North Door", target="Северница"),
            _entry("entry-salt", source="Salt Thread", target="Солевязь"),
        ]
        partial = validate_glossary_compliance(
            entries,
            selected_entry_ids=("entry-north", "entry-salt"),
            included_entry_ids=("entry-north", "entry-salt"),
            source_text="North Door and Salt Thread.",
            translated_text="Северница была на месте, но второго термина нет.",
        )
        zero = validate_glossary_compliance(
            entries,
            selected_entry_ids=("entry-north", "entry-salt"),
            included_entry_ids=("entry-north", "entry-salt"),
            source_text="North Door and Salt Thread.",
            translated_text="Ни одного настроенного термина тут нет.",
        )

        self.assertEqual(partial["status"], "findings")
        self.assertEqual(partial["target_form_present_entry_ids"], ["entry-north"])
        self.assertEqual(partial["target_form_missing_entry_ids"], ["entry-salt"])
        self.assertIn("target_form_missing", partial["reason_codes"])
        self.assertEqual(zero["status"], "findings")
        self.assertEqual(zero["target_form_present_count"], 0)
        self.assertEqual(zero["target_form_missing_count"], 2)

    def test_skip_reasons_and_structural_failure_are_metadata_only(self):
        entries = [
            _entry("entry-absent", source="Absent Term", target="Отсутствует"),
            _entry("entry-no-target", source="No Target"),
            _entry("entry-omitted", source="Omitted Term", target="Пропуск"),
        ]

        result = validate_glossary_compliance(
            entries,
            selected_entry_ids=("entry-absent", "entry-no-target", "entry-omitted"),
            included_entry_ids=("entry-absent", "entry-no-target"),
            source_text="No Target and Omitted Term are present.",
            translated_text="Пропуск.",
        )
        structural_fail = validate_glossary_compliance(
            entries,
            selected_entry_ids=("entry-absent",),
            included_entry_ids=("entry-absent",),
            source_text="Absent Term.",
            translated_text=None,
            structural_validation_passed=False,
        )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["checked_entry_count"], 0)
        self.assertEqual(result["skipped_entry_count"], 3)
        self.assertIn("source_term_absent", result["reason_codes"])
        self.assertIn("target_metadata_missing", result["reason_codes"])
        self.assertIn("glossary_context_omitted", result["reason_codes"])
        self.assertEqual(structural_fail["status"], "skipped")
        self.assertIn("structural_validation_failed", structural_fail["reason_codes"])

    def test_metadata_payload_excludes_raw_source_target_and_translation_text(self):
        raw_source = "RAW SOURCE MUST NOT SERIALIZE"
        raw_target = "RAW TARGET MUST NOT SERIALIZE"
        raw_translation = "RAW TRANSLATION MUST NOT SERIALIZE"

        result = validate_glossary_compliance(
            [_entry("entry-safe", source=raw_source, target=raw_target)],
            selected_entry_ids=("entry-safe",),
            included_entry_ids=("entry-safe",),
            source_text=f"{raw_source} appears here.",
            translated_text=f"{raw_translation} appears here.",
        )

        serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(raw_source, serialized)
        self.assertNotIn(raw_target, serialized)
        self.assertNotIn(raw_translation, serialized)
        self.assertTrue(result["metadata_only"])
        self.assertFalse(result["raw_payload_included"])
        self.assertFalse(result["semantic_quality_claim_made"])


if __name__ == "__main__":
    unittest.main()
