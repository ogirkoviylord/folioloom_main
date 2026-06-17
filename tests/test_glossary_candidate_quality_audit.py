import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.glossary_candidate_quality_audit import (
    PreparedGlossaryCandidateQualityAuditCase,
    audit_prepared_glossary_candidate_quality,
    default_candidate_quality_audit_cases,
)


class PreparedGlossaryCandidateQualityAuditTests(unittest.TestCase):
    def test_audit_report_counts_drops_and_preserved_candidates_metadata_only(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "audit-fixture.en.txt"
            path.write_text(
                "Then He walked away. Then He returned. "
                "Mr. Darcy met Alice at Pemberley. "
                "Darcy returned to Pemberley with Alice. "
                "Mr. Darcy wrote to Alice again.",
                encoding="utf-8",
            )

            report = audit_prepared_glossary_candidate_quality(
                (
                    PreparedGlossaryCandidateQualityAuditCase(
                        input_path=path,
                        document_kind="txt",
                        target_language="ru",
                        input_id="audit_fixture",
                    ),
                )
            )

        case = report["cases"][0]
        self.assertTrue(report["metadata_only"])
        self.assertFalse(report["raw_payload_included"])
        self.assertTrue(case["provider_called"])
        self.assertTrue(case["attachment_enabled"])
        self.assertGreater(
            case["prep_candidate_quality"]["dropped_candidate_count"],
            0,
        )
        self.assertGreater(
            case["prep_candidate_quality"]["selected_candidate_count"],
            0,
        )
        self.assertGreater(
            case["package_quality"]["selected_candidate_count"],
            0,
        )
        self.assertGreater(report["totals"]["low_value_candidate_rate"], 0)
        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("Then He", serialized)
        self.assertNotIn("Mr. Darcy", serialized)
        self.assertNotIn("Pemberley", serialized)

    def test_all_low_value_audit_skips_provider_with_reason_codes(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "audit-low-value.en.txt"
            path.write_text(
                "Then He walked away. Then He returned. "
                "Now He waited. Now He spoke. "
                "In God we trust. In God we wait.",
                encoding="utf-8",
            )

            report = audit_prepared_glossary_candidate_quality(
                (
                    PreparedGlossaryCandidateQualityAuditCase(
                        input_path=path,
                        document_kind="txt",
                        target_language="ru",
                        input_id="low_value_fixture",
                    ),
                )
            )

        case = report["cases"][0]
        self.assertFalse(case["attachment_enabled"])
        self.assertFalse(case["provider_called"])
        self.assertIn(
            "prepared_glossary_prep_candidate_quality_no_candidates",
            case["reason_codes"],
        )
        self.assertGreater(
            case["prep_candidate_quality"]["dropped_candidate_count"],
            0,
        )
        self.assertEqual(case["package_validation_status"], "not_run")
        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("Then He", serialized)
        self.assertNotIn("In God", serialized)

    def test_default_audit_cases_reference_committed_fixtures(self):
        cases = default_candidate_quality_audit_cases()

        self.assertGreaterEqual(len(cases), 3)
        for case in cases:
            self.assertTrue(case.input_path.exists(), case.input_path)
            self.assertIn(case.document_kind, {"txt", "epub"})
            self.assertEqual(case.source_language, "en")
            self.assertEqual(case.target_language, "ru")


if __name__ == "__main__":
    unittest.main()
