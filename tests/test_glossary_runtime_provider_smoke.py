import json
import tempfile
import unittest
from pathlib import Path

from tools.glossary_runtime_provider_smoke import (
    APPROVED_INPUT_TARGETS,
    DEFAULT_DIAGNOSTIC_ROOT,
    DEFAULT_MODEL,
    FakeRuntimeProvider,
    SmokeConfig,
    build_runtime_package,
    build_runtime_prompt,
    run_smoke,
    validate_runtime_response,
)


class GlossaryRuntimeProviderSmokeTest(unittest.TestCase):
    def test_fake_smoke_writes_metadata_report_without_raw_prompt_text(self):
        fixture = Path("test_samples/sample_book.en.txt")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.md"
            config = SmokeConfig(
                input_targets=((fixture, "ru"),),
                diagnostic_root=tmp_path / "diagnostics",
                fake=True,
            )

            report = run_smoke(
                config,
                provider=FakeRuntimeProvider(),
                repo_root=Path.cwd(),
                metadata_report_path=report_path,
            )

            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["calls_made"], 1)
            self.assertEqual(report["calls"][0]["status"], "validated")
            self.assertTrue(report_path.is_file())
            rendered = report_path.read_text(encoding="utf-8")
            source_text = fixture.read_text(encoding="utf-8")
            self.assertNotIn(source_text[:40], rendered)
            self.assertNotIn("BEGIN_UNTRUSTED_DOCUMENT_CONTENT", rendered)
            self.assertNotIn("provider_response", rendered)
            self.assertIn("Validation issue codes", rendered)
            self.assertIn("| none |", rendered)
            diagnostic_dir = Path(report["diagnostic_dir"])
            self.assertTrue((diagnostic_dir / "manifest.json").is_file())
            call_files = sorted(diagnostic_dir.glob("call-*.json"))
            self.assertEqual(len(call_files), 1)
            diagnostic = json.loads(call_files[0].read_text(encoding="utf-8"))
            self.assertIn("user_prompt", diagnostic)
            self.assertIn("response_text", diagnostic)
            self.assertFalse(
                diagnostic["access_boundary"]["github_issue_or_pr_allowed"]
            )

    def test_rejects_unapproved_caps_and_targets_for_live_boundary(self):
        with self.assertRaises(ValueError):
            run_smoke(
                SmokeConfig(max_calls=6, fake=True),
                provider=FakeRuntimeProvider(),
                repo_root=Path.cwd(),
            )
        with self.assertRaises(ValueError):
            run_smoke(
                SmokeConfig(
                    input_targets=((Path("test_samples/sample_book.en.txt"), "uk"),),
                    fake=True,
                ),
                provider=FakeRuntimeProvider(),
                repo_root=Path.cwd(),
            )
        with self.assertRaises(ValueError):
            run_smoke(
                SmokeConfig(provider_base_url="https://example.invalid", fake=True),
                provider=FakeRuntimeProvider(),
                repo_root=Path.cwd(),
            )

    def test_live_boundary_defaults_match_approved_issue_values(self):
        config = SmokeConfig()

        self.assertEqual(config.input_targets, APPROVED_INPUT_TARGETS)
        self.assertEqual(config.diagnostic_root, DEFAULT_DIAGNOSTIC_ROOT)
        self.assertEqual(config.provider_model, DEFAULT_MODEL)
        self.assertEqual(config.max_calls, 5)
        self.assertEqual(config.max_tokens_total, 50_000)
        self.assertTrue(config.raw_text_capture)

    def test_package_builds_glossary_injected_runtime_prompt(self):
        package = build_runtime_package(
            Path("test_samples/sample_book.en.txt"),
            "ru",
            config=SmokeConfig(
                input_targets=((Path("test_samples/sample_book.en.txt"), "ru"),),
                fake=True,
            ),
            repo_root=Path.cwd(),
        )
        system_prompt, user_prompt, request_text = build_runtime_prompt(package)

        self.assertEqual(package.adapter_metadata["status"], "ready")
        self.assertEqual(
            package.adapter_metadata["cache_policy"]["behavior"],
            "bypass_glossary_injected_cache",
        )
        self.assertIn("<glossary_context", request_text)
        self.assertIn("<translation_batch>", request_text)
        self.assertIn("BEGIN_UNTRUSTED_DOCUMENT_CONTENT", user_prompt)
        self.assertIn("professional document translator", system_prompt)

    def test_validation_rejects_malformed_provider_output(self):
        package = build_runtime_package(
            Path("test_samples/sample_book.en.txt"),
            "ru",
            config=SmokeConfig(
                input_targets=((Path("test_samples/sample_book.en.txt"), "ru"),),
                fake=True,
            ),
            repo_root=Path.cwd(),
        )
        result = FakeRuntimeProvider().chat(
            model="deepseek-v4-pro",
            system_prompt="system",
            user_prompt=(
                '<translation_batch><translation_block id="0">x'
                "</translation_block></translation_batch>"
            ),
            max_completion_tokens=100,
        )
        malformed = type(result)(
            ok=True,
            content="not xml",
            usage=result.usage,
            finish_reason="stop",
            http_status=200,
            elapsed_seconds=0,
            request_payload=result.request_payload,
        )

        validation = validate_runtime_response(malformed, package=package)

        self.assertFalse(validation["valid"])
        self.assertIn("external_text", validation["issue_codes"])


if __name__ == "__main__":
    unittest.main()
