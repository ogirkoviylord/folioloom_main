import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.prepared_glossary_prep_preflight import (
    APPROVED_INPUT,
    DEFAULT_PROVIDER_MODEL,
    ChatCallResult,
    PreparedGlossaryPrepLiveConfig,
    PreparedGlossaryPrepPreflightConfig,
    _fake_prepared_package,
    run_live_preparation,
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

    def test_live_preparation_validates_provider_package_and_metadata_report(self):
        with TemporaryDirectory() as temp_dir:
            provider = _PreparedPackageProvider()
            result = run_live_preparation(
                PreparedGlossaryPrepLiveConfig(
                    diagnostic_root=Path(temp_dir) / "issue-614",
                ),
                provider=provider,
                timestamp="20260615T010000Z",
                allow_test_diagnostic_root=True,
            )

            metadata_report = json.loads(
                result.metadata_report_path.read_text(encoding="utf-8")
            )
            prepared_package = json.loads(
                result.prepared_package_path.read_text(encoding="utf-8")
            )
            diagnostic = json.loads(
                (
                    result.diagnostics_dir / "live_provider_diagnostic.json"
                ).read_text(encoding="utf-8")
            )
            metadata_text = json.dumps(
                metadata_report,
                ensure_ascii=False,
                sort_keys=True,
            )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.calls_made, 1)
        self.assertEqual(result.provider_tokens_total, 123)
        self.assertEqual(result.validation_status, "ready")
        self.assertEqual(metadata_report["issue"], "614")
        self.assertEqual(metadata_report["metadata_only"], True)
        self.assertEqual(metadata_report["provider_tokens_total"], 123)
        self.assertEqual(metadata_report["live_validation"]["status"], "ready")
        self.assertTrue(prepared_package["entries"])
        self.assertEqual(diagnostic["request_payload"]["model"], DEFAULT_PROVIDER_MODEL)
        self.assertNotIn("Authorization", json.dumps(diagnostic["request_payload"]))
        self.assertNotIn("Time Traveller", metadata_text)
        self.assertNotIn("RAW PROMPT", metadata_text)
        self.assertNotIn("Bearer ", metadata_text)
        self.assertNotIn("sk-", metadata_text)

    def test_live_preparation_refuses_unapproved_diagnostic_root(self):
        with TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                ValueError,
                "issue_614_diagnostic_root_not_approved",
            ):
                run_live_preparation(
                    PreparedGlossaryPrepLiveConfig(
                        diagnostic_root=Path(temp_dir) / "issue-614",
                    ),
                    provider=_PreparedPackageProvider(),
                    timestamp="20260615T010000Z",
                )

    def test_live_preparation_reports_invalid_provider_json_metadata_only(self):
        with TemporaryDirectory() as temp_dir:
            result = run_live_preparation(
                PreparedGlossaryPrepLiveConfig(
                    diagnostic_root=Path(temp_dir) / "issue-614",
                ),
                provider=_InvalidJsonProvider(),
                timestamp="20260615T010000Z",
                allow_test_diagnostic_root=True,
            )

            metadata_report = json.loads(
                result.metadata_report_path.read_text(encoding="utf-8")
            )
            metadata_text = json.dumps(
                metadata_report,
                ensure_ascii=False,
                sort_keys=True,
            )

        self.assertEqual(result.status, "failed")
        self.assertIn("provider_response_invalid_package_json", result.reason_codes)
        self.assertEqual(metadata_report["metadata_only"], True)
        self.assertEqual(metadata_report["live_validation"]["status"], "invalid")
        self.assertNotIn("not json", metadata_text)


class _PreparedPackageProvider:
    def chat(self, *, model, system_prompt, user_prompt, max_completion_tokens):
        del system_prompt, max_completion_tokens
        prompt = json.loads(user_prompt)
        packet = prompt["packet"]
        package = _fake_prepared_package(
            config=PreparedGlossaryPrepLiveConfig(),
            packet=packet,
            reducer_signature=packet["candidate_selector_signature"],
            source_document_fingerprint=packet["source_document_fingerprint"],
        )
        package["provider_run_id"] = "unit-test-live-provider"
        return ChatCallResult(
            ok=True,
            content=json.dumps(package, ensure_ascii=False),
            usage={"prompt_tokens": 80, "completion_tokens": 43, "total_tokens": 123},
            finish_reason="stop",
            http_status=200,
            elapsed_seconds=0.25,
            request_payload={
                "model": model,
                "messages": [{"role": "user", "content": user_prompt}],
            },
            response_payload={
                "choices": [
                    {
                        "message": {"content": json.dumps(package)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 80,
                    "completion_tokens": 43,
                    "total_tokens": 123,
                },
            },
            response_text=json.dumps({"choices": [{"finish_reason": "stop"}]}),
        )


class _InvalidJsonProvider:
    def chat(self, *, model, system_prompt, user_prompt, max_completion_tokens):
        del system_prompt, user_prompt, max_completion_tokens
        return ChatCallResult(
            ok=True,
            content="not json",
            usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            finish_reason="stop",
            http_status=200,
            elapsed_seconds=0.1,
            request_payload={"model": model},
            response_payload={"choices": [{"finish_reason": "stop"}]},
            response_text='{"choices":[{"finish_reason":"stop"}]}',
        )


if __name__ == "__main__":
    unittest.main()
