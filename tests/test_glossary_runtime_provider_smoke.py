import json
import tempfile
import unittest
from pathlib import Path

from tools.glossary_runtime_provider_smoke import (
    APPROVED_INPUT_TARGETS,
    DEFAULT_DIAGNOSTIC_ROOT,
    DEFAULT_MODEL,
    FakeRuntimeProvider,
    RuntimeSmokePackage,
    SmokeConfig,
    build_runtime_package,
    build_runtime_pressure_summary,
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
            self.assertIn("Runtime Pressure Summary", rendered)
            pressure = report["calls"][0]["pressure_summary"]
            self.assertFalse(pressure["raw_payload_included"])
            self.assertEqual(
                pressure["cache_policy"]["behavior"],
                "bypass_glossary_injected_cache",
            )
            self.assertNotIn(
                source_text[:40],
                json.dumps(pressure, ensure_ascii=False, sort_keys=True),
            )
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

    def test_pressure_summary_distinguishes_epub_shape_without_raw_text(self):
        raw_source = "RAW SOURCE SENTENCE MUST NOT SERIALIZE"
        package = RuntimeSmokePackage(
            input_path=Path("/tmp/synthetic.epub"),
            input_id="synthetic-epub-ru",
            target_language="ru",
            document_format="epub",
            fragment_count=1,
            character_count=12_000,
            unit_sequence=1,
            source_block_ids=tuple(f"block:v1:{index}" for index in range(58)),
            source_text=raw_source,
            protected_text="{{PH_1}} {{PH_2}}",
            required_markers=(("{{PH_1}}",), ("{{PH_2}}",)),
            glossary_plan={
                "status": "planned",
                "fallback_reason": "none",
                "work_unit_plans": [
                    {
                        "work_unit_sequence": 1,
                        "fallback_reason_codes": ["prompt_budget_exhausted"],
                    }
                ],
            },
            adapter_metadata={
                "status": "ready",
                "selected_entry_ids": ["entry-1", "entry-2"],
                "cache_policy": {
                    "behavior": "bypass_glossary_injected_cache",
                    "cache_get_allowed": False,
                    "cache_put_allowed": False,
                },
                "work_unit_selection_signature": "selection:v1:test",
            },
            prompt_context_text="<glossary_context>redacted</glossary_context>",
            prompt_context_metadata={
                "included_entry_ids": ["entry-1", "entry-2"],
                "omitted_entries": [
                    {"entry_id": "entry-3", "reason": "prompt_budget_exhausted"}
                ],
                "estimated_prompt_tokens": 837,
            },
            selection_metadata={
                "dropped_entries": [
                    {"entry_id": "entry-3", "reason": "prompt_budget_exhausted"}
                ],
                "budget_exceeded": False,
                "estimated_prompt_tokens": 360,
            },
            glossary_entry_count=12,
            glossary_evidence_count=34,
            reducer_metadata={"diagnostic_count": 3, "dropped_count": 91},
        )

        summary = build_runtime_pressure_summary(
            package,
            config=SmokeConfig(fake=True),
            estimated_prompt_tokens=4_500,
            reserved_tokens=10_800,
        )

        self.assertEqual(summary["unit"]["source_block_id_count"], 58)
        self.assertEqual(summary["unit"]["protected_marker_count"], 2)
        self.assertEqual(summary["unit"]["source_character_count"], len(raw_source))
        self.assertEqual(summary["glossary"]["selected_entry_count"], 2)
        self.assertEqual(summary["tokens"]["estimated_request_prompt_tokens"], 4_500)
        self.assertEqual(summary["tokens"]["reserved_request_tokens"], 10_800)
        self.assertEqual(
            summary["output_contract"]["risk_category"],
            "epub_multi_block_with_protected_markers",
        )
        self.assertIn(
            "prompt_budget_exhausted",
            summary["fallback"]["work_unit_fallback_reason_codes"],
        )
        serialized = json.dumps(summary, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(raw_source, serialized)
        self.assertNotIn("{{PH_1}}", serialized)
        self.assertNotIn("<glossary_context", serialized)

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
