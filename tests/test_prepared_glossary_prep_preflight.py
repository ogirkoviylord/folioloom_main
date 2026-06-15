import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.prepared_glossary_prep_preflight import (
    APPROVED_INPUT,
    PreparedGlossaryPrepPreflightConfig,
    run_preflight,
)
from translator_service.glossary_prepared_package import (
    validate_prepared_glossary_package,
)


class PreparedGlossaryPrepPreflightTests(unittest.TestCase):
    def test_fake_preflight_builds_ready_package_and_metadata_report(self):
        with TemporaryDirectory() as temp_dir:
            result = run_preflight(
                PreparedGlossaryPrepPreflightConfig(
                    diagnostic_root=Path(temp_dir) / "issue-619",
                ),
                timestamp="20260615T000000Z",
            )

            metadata_report = json.loads(
                result.metadata_report_path.read_text(encoding="utf-8")
            )
            prepared_package = json.loads(
                result.prepared_package_path.read_text(encoding="utf-8")
            )
            validation = validate_prepared_glossary_package(
                prepared_package,
                target_language="ru",
            )
            metadata_text = json.dumps(
                metadata_report,
                ensure_ascii=False,
                sort_keys=True,
            )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.validation_status, "ready")
        self.assertGreater(result.selected_candidate_count, 0)
        self.assertLessEqual(result.selected_candidate_count, 8)
        self.assertTrue(validation.ready)
        self.assertEqual(metadata_report["metadata_only"], True)
        self.assertEqual(metadata_report["live_provider_calls"], 0)
        self.assertEqual(metadata_report["provider_tokens_total"], 0)
        self.assertEqual(metadata_report["validation"]["status"], "ready")
        self.assertNotIn("Time Traveller", metadata_text)
        self.assertNotIn("RAW PROMPT", metadata_text)
        self.assertNotIn("Bearer ", metadata_text)
        self.assertNotIn("sk-", metadata_text)

    def test_fake_preflight_refuses_unapproved_input(self):
        with TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "issue_619_input_not_approved"):
                run_preflight(
                    PreparedGlossaryPrepPreflightConfig(
                        input_path=Path("test_samples/sample_book.en.epub"),
                        diagnostic_root=Path(temp_dir),
                    ),
                    timestamp="20260615T000000Z",
                )

    def test_fake_preflight_refuses_unapproved_target(self):
        with TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "issue_619_target_not_approved"):
                run_preflight(
                    PreparedGlossaryPrepPreflightConfig(
                        input_path=APPROVED_INPUT,
                        target_language="uk",
                        diagnostic_root=Path(temp_dir),
                    ),
                    timestamp="20260615T000000Z",
                )


if __name__ == "__main__":
    unittest.main()
