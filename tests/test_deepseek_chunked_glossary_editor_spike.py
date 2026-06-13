from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _ROOT / "tools" / "deepseek_chunked_glossary_editor_spike.py"
_SPEC = importlib.util.spec_from_file_location(
    "deepseek_chunked_glossary_editor_spike",
    _SCRIPT_PATH,
)
assert _SPEC is not None
assert _SPEC.loader is not None
spike = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = spike
_SPEC.loader.exec_module(spike)


class DeepSeekChunkedGlossaryEditorSpikeTest(unittest.TestCase):
    def test_issue_449_fake_run_uses_reduced_packets_and_metadata_only_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "metadata-report.md"
            report = spike.run_spike(
                spike.SpikeConfig(
                    fixture_paths=spike.APPROVED_FIXTURES,
                    diagnostic_root=Path(temp_dir),
                    max_calls=3,
                    max_tokens_total=40_000,
                    max_packets_total=3,
                    packet_selection_rule=spike.ISSUE_449_PACKET_SELECTION_RULE,
                    reduced_packets=True,
                    fake=True,
                ),
                provider=spike.FakeChunkedProvider(),
                repo_root=_ROOT,
                metadata_report_path=report_path,
            )

            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["calls_made"], 3)
            self.assertLessEqual(report["reserved_tokens"], 40_000)
            self.assertTrue(
                all(
                    fixture["reduced_packets"]
                    for fixture in report["fixtures"]
                )
            )
            self.assertTrue(
                all(fixture["reducer"] for fixture in report["fixtures"])
            )
            self.assertTrue(
                all(
                    fixture["selected_packet_entry_count"] <= 4
                    for fixture in report["fixtures"]
                )
            )
            self.assertTrue(
                all(
                    fixture["selected_packet_estimated_prompt_tokens"] <= 1000
                    for fixture in report["fixtures"]
                )
            )
            self.assertTrue(
                all(
                    call["validation"]["valid"]
                    for call in report["calls"]
                    if call["status"] == "validated"
                )
            )

            diagnostic_dir = Path(report["diagnostic_dir"])
            selected_packets = json.loads(
                (diagnostic_dir / "selected-packets.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn(
                "reducer_context",
                selected_packets[0]["packet"],
            )
            self.assertIn(
                "entry_limit_exhausted",
                selected_packets[0]["packet"]["split_reason_codes"],
            )
            self.assertNotIn(
                "raw_excerpt",
                report_path.read_text(encoding="utf-8"),
            )

    def test_issue_449_rejects_unapproved_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "not approved for issue #449"):
                spike.run_spike(
                    spike.SpikeConfig(
                        fixture_paths=(Path("README.md"),),
                        diagnostic_root=Path(temp_dir),
                        packet_selection_rule=spike.ISSUE_449_PACKET_SELECTION_RULE,
                        reduced_packets=True,
                        fake=True,
                    ),
                    provider=spike.FakeChunkedProvider(),
                    repo_root=_ROOT,
                )

    def test_issue_449_live_config_requires_approved_root_and_caps(self):
        with self.assertRaisesRegex(ValueError, "diagnostic_root"):
            spike.run_spike(
                spike.SpikeConfig(
                    fixture_paths=(spike.APPROVED_FIXTURES[-1],),
                    diagnostic_root=Path("outputs/not-approved"),
                    max_calls=4,
                    max_tokens_total=40_000,
                    max_packets_total=4,
                    packet_selection_rule=spike.ISSUE_449_PACKET_SELECTION_RULE,
                    reduced_packets=True,
                    fake=False,
                ),
                provider=spike.FakeChunkedProvider(),
                repo_root=_ROOT,
            )

        with self.assertRaisesRegex(ValueError, "max_calls"):
            spike.run_spike(
                spike.SpikeConfig(
                    fixture_paths=(spike.APPROVED_FIXTURES[-1],),
                    diagnostic_root=spike.ISSUE_449_DIAGNOSTIC_ROOT,
                    max_calls=5,
                    max_tokens_total=40_000,
                    max_packets_total=4,
                    packet_selection_rule=spike.ISSUE_449_PACKET_SELECTION_RULE,
                    reduced_packets=True,
                    fake=True,
                ),
                provider=spike.FakeChunkedProvider(),
                repo_root=_ROOT,
            )

        with self.assertRaisesRegex(ValueError, "reduced_packets=True"):
            spike.run_spike(
                spike.SpikeConfig(
                    fixture_paths=(spike.APPROVED_FIXTURES[-1],),
                    diagnostic_root=spike.ISSUE_449_DIAGNOSTIC_ROOT,
                    max_calls=3,
                    max_tokens_total=30_000,
                    max_packets_total=3,
                    reduced_packets=False,
                    fake=False,
                ),
                provider=spike.FakeChunkedProvider(),
                repo_root=_ROOT,
            )

    def test_issue_464_live_config_requires_its_own_boundary(self):
        spike._validate_config(
            spike.SpikeConfig(
                fixture_paths=(spike.APPROVED_FIXTURES[-1],),
                diagnostic_root=spike.ISSUE_464_DIAGNOSTIC_ROOT,
                max_calls=4,
                max_tokens_total=40_000,
                max_packets_total=4,
                packet_selection_rule=spike.ISSUE_464_PACKET_SELECTION_RULE,
                reduced_packets=True,
                fake=False,
                issue_id="464",
            )
        )

        with self.assertRaisesRegex(ValueError, "issue #464"):
            spike._validate_config(
                spike.SpikeConfig(
                    fixture_paths=(spike.APPROVED_FIXTURES[-1],),
                    diagnostic_root=spike.ISSUE_449_DIAGNOSTIC_ROOT,
                    max_calls=4,
                    max_tokens_total=40_000,
                    max_packets_total=4,
                    packet_selection_rule=spike.ISSUE_464_PACKET_SELECTION_RULE,
                    reduced_packets=True,
                    fake=False,
                    issue_id="464",
                )
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "not approved for issue #464"):
                spike.run_spike(
                    spike.SpikeConfig(
                        fixture_paths=(Path("README.md"),),
                        diagnostic_root=Path(temp_dir),
                        packet_selection_rule=spike.ISSUE_464_PACKET_SELECTION_RULE,
                        reduced_packets=True,
                        fake=True,
                        issue_id="464",
                    ),
                    provider=spike.FakeChunkedProvider(),
                    repo_root=_ROOT,
                )

    def test_issue_464_approval_payload_records_issue_id(self):
        payload = spike._approval_payload(
            spike.SpikeConfig(
                fixture_paths=(spike.APPROVED_FIXTURES[-1],),
                diagnostic_root=spike.ISSUE_464_DIAGNOSTIC_ROOT,
                packet_selection_rule=spike.ISSUE_464_PACKET_SELECTION_RULE,
                reduced_packets=True,
                issue_id="464",
            )
        )

        self.assertEqual(payload["issue_id"], "464")
        self.assertEqual(
            payload["diagnostic_storage"],
            str(spike.ISSUE_464_DIAGNOSTIC_ROOT),
        )

    def test_external_approved_path_display_does_not_require_repo_relative_path(self):
        external = Path("/Users/yuriimedvediev/Downloads/pg78824-images-3.epub")

        self.assertEqual(
            spike._display_path(external, repo_root=_ROOT),
            str(external),
        )

    def test_provider_timeout_returns_metadata_failure(self):
        provider = spike.OpenAICompatibleProvider(
            api_key="synthetic-key",
            base_url="https://example.invalid",
            timeout_seconds=0.01,
        )

        with patch.object(spike, "urlopen", side_effect=TimeoutError):
            result = provider.chat(
                model=spike.DEFAULT_MODEL,
                system_prompt="system",
                user_prompt='{"packet": {"entries": []}}',
                max_completion_tokens=10,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "TimeoutError")
        self.assertEqual(result.error_message, "provider_response_timeout")
        self.assertEqual(result.content, "")
        self.assertEqual(result.usage, {})

    def test_length_truncated_output_is_metadata_only_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "metadata-report.md"
            report = _run_single_fake_failure(
                provider=_LengthTruncatedJsonProvider(),
                temp_dir=Path(temp_dir),
                report_path=report_path,
            )

            self.assertEqual(report["status"], "completed_with_failures")
            self.assertEqual(report["observed_tokens"], "Unknown")
            self.assertIn(
                "provider-reported token usage is Unknown for one or more calls",
                report["unknown"],
            )
            self.assertIn(
                "one or more chunk outputs did not validate",
                report["unknown"],
            )
            self.assertEqual(report["calls"][0]["finish_reason"], "length")
            self.assertEqual(report["calls"][0]["usage"], {})
            self.assertFalse(report["calls"][0]["validation"]["valid"])
            self.assertEqual(
                report["calls"][0]["validation"]["issues"][0]["code"],
                "invalid_json",
            )
            metadata = report_path.read_text(encoding="utf-8")
            self.assertIn("| length |", metadata)
            self.assertIn("| Unknown |", metadata)
            self.assertNotIn('{"output_schema_version":', metadata)
            self.assertNotIn("provider_response", metadata)
            self.assertNotIn("Traceback", metadata)

    def test_timeout_report_is_metadata_only_failure_without_traceback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "metadata-report.md"
            report = _run_single_fake_failure(
                provider=_TimeoutFailureProvider(),
                temp_dir=Path(temp_dir),
                report_path=report_path,
            )

            self.assertEqual(report["status"], "completed_with_failures")
            self.assertEqual(report["observed_tokens"], "Unknown")
            self.assertEqual(report["calls"][0]["error_type"], "TimeoutError")
            self.assertEqual(
                report["calls"][0]["error_message"],
                "provider_response_timeout",
            )
            self.assertFalse(report["calls"][0]["validation"]["valid"])
            metadata = report_path.read_text(encoding="utf-8")
            self.assertNotIn("Traceback", metadata)
            self.assertNotIn("provider_response", metadata)
            self.assertNotIn("response_payload", metadata)

    def test_missing_usage_metadata_remains_unknown_for_valid_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "metadata-report.md"
            report = _run_single_fake_failure(
                provider=_ValidMissingUsageProvider(),
                temp_dir=Path(temp_dir),
                report_path=report_path,
            )

            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["observed_tokens"], "Unknown")
            self.assertTrue(report["calls"][0]["validation"]["valid"])
            self.assertEqual(report["calls"][0]["usage"], {})
            self.assertIn(
                "provider-reported token usage is Unknown for one or more calls",
                report["unknown"],
            )
            self.assertIn("| Unknown |", report_path.read_text(encoding="utf-8"))

def _run_single_fake_failure(
    *,
    provider,
    temp_dir: Path,
    report_path: Path,
):
    return spike.run_spike(
        spike.SpikeConfig(
            fixture_paths=(spike.APPROVED_FIXTURES[0],),
            diagnostic_root=temp_dir,
            max_calls=1,
            max_tokens_total=40_000,
            max_packets_total=1,
            packet_selection_rule=spike.ISSUE_449_PACKET_SELECTION_RULE,
            reduced_packets=True,
            raw_text_capture=True,
            fake=True,
        ),
        provider=provider,
        repo_root=_ROOT,
        metadata_report_path=report_path,
    )


class _LengthTruncatedJsonProvider:
    def chat(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_completion_tokens: int,
    ):
        return spike.ChatCallResult(
            ok=True,
            content='{"output_schema_version":',
            usage={},
            finish_reason="length",
            http_status=200,
            elapsed_seconds=1.25,
            request_payload={"model": model},
            response_payload={"choices": [{"finish_reason": "length"}]},
            response_text='{"choices":[{"finish_reason":"length"}]}',
        )


class _TimeoutFailureProvider:
    def chat(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_completion_tokens: int,
    ):
        return spike.ChatCallResult(
            ok=False,
            content="",
            usage={},
            finish_reason=None,
            http_status=None,
            elapsed_seconds=9.5,
            request_payload={"model": model},
            error_type="TimeoutError",
            error_message="provider_response_timeout",
        )


class _ValidMissingUsageProvider:
    def chat(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_completion_tokens: int,
    ):
        result = spike.FakeChunkedProvider().chat(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_completion_tokens=max_completion_tokens,
        )
        return spike.ChatCallResult(
            ok=result.ok,
            content=result.content,
            usage={},
            finish_reason=result.finish_reason,
            http_status=result.http_status,
            elapsed_seconds=result.elapsed_seconds,
            request_payload=result.request_payload,
            response_payload=result.response_payload,
            response_text=result.response_text,
        )


if __name__ == "__main__":
    unittest.main()
