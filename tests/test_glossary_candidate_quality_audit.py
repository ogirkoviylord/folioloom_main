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
        self.assertEqual(report["ordinary_artifact_safety"]["status"], "passed")
        self.assertEqual(
            report["recommendation"]["primary_recommendation"],
            "no_tuning",
        )
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

    def test_target_metadata_counts_missing_durable_candidates_without_raw_terms(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "audit-target-backed.en.txt"
            source_path.write_text(
                "Darcy met Alice at Pemberley. "
                "Darcy returned to Pemberley with Alice. "
                "Alice wrote to Darcy again.",
                encoding="utf-8",
            )
            target_path = root / "runtime-glossary-targets.json"
            target_path.write_text(
                json.dumps(
                    {
                        "targets": {
                            "ru": {
                                "entries": [
                                    {
                                        "source_canonical": "Darcy",
                                        "aliases": ["Mr Darcy"],
                                    },
                                    {
                                        "source_canonical": "Longbourn",
                                        "aliases": [],
                                    },
                                ]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            report = audit_prepared_glossary_candidate_quality(
                (
                    PreparedGlossaryCandidateQualityAuditCase(
                        input_path=source_path,
                        document_kind="txt",
                        target_language="ru",
                        input_id="target_backed_fixture",
                        target_metadata_path=target_path,
                    ),
                )
            )

        case = report["cases"][0]
        target_metadata = case["target_metadata"]
        self.assertEqual(target_metadata["status"], "checked")
        self.assertEqual(target_metadata["detection_status"], "confirmed")
        self.assertEqual(target_metadata["expected_durable_candidate_count"], 2)
        self.assertEqual(
            target_metadata["selected_expected_durable_candidate_count"],
            1,
        )
        self.assertEqual(
            target_metadata["suspected_missing_durable_candidate_count"],
            1,
        )
        self.assertEqual(
            report["totals"]["suspected_missing_durable_candidate_count"],
            1,
        )
        self.assertEqual(
            report["recommendation"]["primary_recommendation"],
            "reducer_tuning",
        )
        self.assertIn(
            "scanner_vs_reducer_attribution_for_missing_candidates",
            report["unknown_items"],
        )
        self.assertIn(
            "whether_reducer_scoring_should_change_under_issue_690",
            report["tbd_items"],
        )
        self.assertEqual(report["ordinary_artifact_safety"]["status"], "passed")
        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("Darcy", serialized)
        self.assertNotIn("Longbourn", serialized)
        self.assertNotIn("Mr Darcy", serialized)

    def test_default_audit_cases_reference_committed_fixtures(self):
        cases = default_candidate_quality_audit_cases()

        self.assertGreaterEqual(len(cases), 9)
        for case in cases:
            self.assertTrue(case.input_path.exists(), case.input_path)
            self.assertIn(case.document_kind, {"txt", "docx", "epub"})
            self.assertEqual(case.source_language, "en")
            self.assertIn(case.target_language, {"ru", "uk"})
            if case.target_metadata_path is not None:
                self.assertTrue(
                    case.target_metadata_path.exists(),
                    case.target_metadata_path,
                )


if __name__ == "__main__":
    unittest.main()
