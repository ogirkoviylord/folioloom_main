import json
import tempfile
import unittest
from pathlib import Path

from tools.deepseek_chunked_glossary_editor_spike import (
    APPROVED_FIXTURES,
    DEFAULT_DIAGNOSTIC_ROOT,
    FakeChunkedProvider,
    SpikeConfig,
    build_chunk_prompt,
    render_metadata_report,
    run_spike,
    select_fixture_packets,
)


class ChunkedDeepSeekProSpikeTest(unittest.TestCase):
    def test_fake_spike_selects_first_ready_packet_and_validates_outputs(self):
        with tempfile.TemporaryDirectory() as tempdir:
            report = run_spike(
                SpikeConfig(
                    fixture_paths=APPROVED_FIXTURES,
                    diagnostic_root=Path(tempdir) / "diagnostics",
                    fake=True,
                ),
                provider=FakeChunkedProvider(),
                repo_root=Path.cwd(),
            )

        self.assertEqual(report["calls_made"], 3)
        self.assertEqual(report["approval"]["max_calls"], 3)
        self.assertEqual(report["approval"]["max_tokens_total"], 30000)
        self.assertEqual(
            report["approval"]["packet_selection_rule"],
            "first_ready_packet_per_fixture",
        )
        self.assertTrue(
            all(call["status"] == "validated" for call in report["calls"])
        )
        self.assertEqual(
            [fixture["selected_packet_status"] for fixture in report["fixtures"]],
            ["ready", "ready", "ready"],
        )
        self.assertGreaterEqual(report["merge"]["proposed_entry_count"], 1)

    def test_metadata_report_excludes_raw_fixture_text_and_prompts(self):
        fixture_text = Path(APPROVED_FIXTURES[0]).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tempdir:
            report = run_spike(
                SpikeConfig(
                    fixture_paths=APPROVED_FIXTURES[:1],
                    diagnostic_root=Path(tempdir) / "diagnostics",
                    fake=True,
                ),
                provider=FakeChunkedProvider(),
                repo_root=Path.cwd(),
            )

        markdown = render_metadata_report(report)

        self.assertNotIn(fixture_text[:80], markdown)
        self.assertNotIn("bounded_source_excerpt", markdown)
        self.assertNotIn("system prompt", markdown.lower())
        self.assertIn("Validation Results", markdown)

    def test_diagnostics_keep_raw_prompt_inside_approved_output_directory(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir) / "diagnostics"
            report = run_spike(
                SpikeConfig(
                    fixture_paths=APPROVED_FIXTURES[:1],
                    diagnostic_root=root,
                    fake=True,
                ),
                provider=FakeChunkedProvider(),
                repo_root=Path.cwd(),
            )
            diagnostic_dir = Path(report["diagnostic_dir"])
            call_file = next(diagnostic_dir.glob("call-*.json"))
            call_payload = json.loads(call_file.read_text(encoding="utf-8"))

        self.assertTrue(diagnostic_dir.is_relative_to(root))
        self.assertIn("bounded_source_excerpt", call_payload)
        self.assertIn("request_payload", call_payload)
        self.assertNotIn("Authorization", json.dumps(call_payload))

    def test_prompt_uses_packet_refs_and_disallows_raw_output_keys(self):
        package = select_fixture_packets(
            SpikeConfig(
                fixture_paths=APPROVED_FIXTURES[:1],
                diagnostic_root=DEFAULT_DIAGNOSTIC_ROOT,
                fake=True,
            ),
            repo_root=Path.cwd(),
        )[0]

        _system_prompt, user_prompt = build_chunk_prompt(package)
        payload = json.loads(user_prompt)

        self.assertEqual(payload["packet"]["packet_id"], package.packet.packet_id)
        self.assertEqual(payload["allowed_entry_ids"], list(package.packet.entry_ids))
        self.assertNotIn("source_canonical", json.dumps(payload["packet"]))
        self.assertIn("bounded_source_excerpt", payload)

    def test_rejects_unapproved_fixture_and_over_budget_config(self):
        with self.assertRaisesRegex(ValueError, "not approved"):
            select_fixture_packets(
                SpikeConfig(
                    fixture_paths=(Path("test_samples/not-approved.txt"),),
                    diagnostic_root=DEFAULT_DIAGNOSTIC_ROOT,
                    fake=True,
                ),
                repo_root=Path.cwd(),
            )
        with self.assertRaisesRegex(ValueError, "max_calls"):
            run_spike(
                SpikeConfig(
                    fixture_paths=APPROVED_FIXTURES[:1],
                    diagnostic_root=DEFAULT_DIAGNOSTIC_ROOT,
                    max_calls=4,
                    fake=True,
                ),
                provider=FakeChunkedProvider(),
                repo_root=Path.cwd(),
            )
        with self.assertRaisesRegex(ValueError, "provider_model"):
            run_spike(
                SpikeConfig(
                    fixture_paths=APPROVED_FIXTURES[:1],
                    diagnostic_root=DEFAULT_DIAGNOSTIC_ROOT,
                    provider_model="unapproved-model",
                    fake=True,
                ),
                provider=FakeChunkedProvider(),
                repo_root=Path.cwd(),
            )
        with tempfile.TemporaryDirectory() as tempdir:
            with self.assertRaisesRegex(ValueError, "diagnostic_root"):
                run_spike(
                    SpikeConfig(
                        fixture_paths=APPROVED_FIXTURES[:1],
                        diagnostic_root=Path(tempdir) / "not-approved-live-root",
                        fake=False,
                    ),
                    provider=FakeChunkedProvider(),
                    repo_root=Path.cwd(),
                )


if __name__ == "__main__":
    unittest.main()
