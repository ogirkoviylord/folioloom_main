import json
import tempfile
import unittest
from pathlib import Path

from tools.deepseek_chunked_glossary_editor_spike import (
    APPROVED_FIXTURES,
    DEFAULT_DIAGNOSTIC_ROOT,
    ISSUE_431_DIAGNOSTIC_ROOT,
    FakeChunkedProvider,
    SpikeConfig,
    _validate_config,
    build_chunk_prompt,
    render_metadata_report,
    run_spike,
    select_fixture_packets,
)
from translator_service.glossary_editor_chunk_outputs import (
    ChunkedGlossaryEditorFindingCode,
    ChunkedGlossaryEditorFindingSeverity,
    ChunkedGlossaryEditorValidationCode,
    merge_chunked_glossary_editor_outputs,
    validate_chunked_glossary_editor_output,
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
        self.assertEqual(
            payload["evidence_contract"]["allowed_evidence_ids_source"],
            "allowed_evidence_ids",
        )
        self.assertEqual(
            payload["evidence_contract"]["entry_evidence_refs_source"],
            "packet.entries[].evidence_refs",
        )
        self.assertEqual(
            payload["evidence_contract"]["packet_evidence_count"],
            len(package.packet.evidence_ids),
        )
        self.assertIn(
            "proposed_entries[].evidence_refs",
            payload["evidence_contract"]["required_paths"],
        )
        self.assertNotIn("source_canonical", json.dumps(payload["packet"]))
        self.assertIn("bounded_source_excerpt", payload)

    def test_fake_outputs_for_approved_fixtures_cite_resolvable_evidence_refs(self):
        packages = select_fixture_packets(
            SpikeConfig(
                fixture_paths=APPROVED_FIXTURES,
                diagnostic_root=DEFAULT_DIAGNOSTIC_ROOT,
                fake=True,
            ),
            repo_root=Path.cwd(),
        )

        for package in packages:
            with self.subTest(fixture=package.fixture_id):
                system_prompt, user_prompt = build_chunk_prompt(package)
                result = FakeChunkedProvider().chat(
                    model="deepseek-v4-pro",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_completion_tokens=2200,
                )
                validation = validate_chunked_glossary_editor_output(
                    result.content,
                    packet=package.packet,
                )
                document = validation.document or {}
                allowed_evidence = set(package.packet.evidence_ids)

                self.assertTrue(validation.valid)
                self.assertTrue(document["evidence_refs"])
                self.assertTrue(set(document["evidence_refs"]) <= allowed_evidence)
                for entry in document["proposed_entries"]:
                    self.assertTrue(entry["evidence_refs"])
                    self.assertTrue(set(entry["evidence_refs"]) <= allowed_evidence)

    def test_fixture_missing_evidence_refs_fail_with_structured_findings(self):
        package = select_fixture_packets(
            SpikeConfig(
                fixture_paths=APPROVED_FIXTURES[:1],
                diagnostic_root=DEFAULT_DIAGNOSTIC_ROOT,
                fake=True,
            ),
            repo_root=Path.cwd(),
        )[0]
        system_prompt, user_prompt = build_chunk_prompt(package)
        result = FakeChunkedProvider().chat(
            model="deepseek-v4-pro",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_completion_tokens=2200,
        )
        document = json.loads(result.content)
        document["evidence_refs"] = []
        document["proposed_entries"][0]["evidence_refs"] = []

        validation = validate_chunked_glossary_editor_output(
            json.dumps(document, ensure_ascii=False, sort_keys=True),
            packet=package.packet,
        )
        merge = merge_chunked_glossary_editor_outputs((validation,))
        issue_paths = {issue.path for issue in validation.issues}
        findings_by_code = {finding.code: finding for finding in merge.findings}

        self.assertFalse(validation.valid)
        self.assertIn(
            ChunkedGlossaryEditorValidationCode.MISSING_EVIDENCE,
            {issue.code for issue in validation.issues},
        )
        self.assertIn("evidence_refs", issue_paths)
        self.assertIn("proposed_entries[0].evidence_refs", issue_paths)
        self.assertEqual(merge.proposed_entries, ())
        self.assertEqual(merge.invalid_packet_ids, (package.packet.packet_id,))
        self.assertIn(
            ChunkedGlossaryEditorFindingCode.INVALID_CHUNK,
            findings_by_code,
        )
        self.assertIn(
            ChunkedGlossaryEditorFindingCode.MISSING_EVIDENCE_REFS,
            findings_by_code,
        )
        self.assertEqual(
            findings_by_code[
                ChunkedGlossaryEditorFindingCode.MISSING_EVIDENCE_REFS
            ].severity,
            ChunkedGlossaryEditorFindingSeverity.BLOCKER,
        )

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

    def test_issue_431_live_diagnostic_root_is_approved(self):
        _validate_config(
            SpikeConfig(
                fixture_paths=APPROVED_FIXTURES,
                diagnostic_root=ISSUE_431_DIAGNOSTIC_ROOT,
                fake=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
