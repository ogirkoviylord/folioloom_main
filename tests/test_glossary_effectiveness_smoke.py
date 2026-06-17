import json
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.glossary_effectiveness_smoke import (
    GlossaryEffectivenessSmokeConfig,
    _fake_prepared_glossary_provider,
    run_fake_dry_preflight,
    run_live_smoke,
)
from translator_service.provider_io_diagnostics import record_provider_io_exchange


class GlossaryEffectivenessSmokeTests(unittest.TestCase):
    def test_fake_dry_selects_glossary_useful_unit_metadata_only(self):
        with TemporaryDirectory() as temp_dir:
            result = run_fake_dry_preflight(
                GlossaryEffectivenessSmokeConfig(
                    diagnostic_root=Path(temp_dir) / "issue-675",
                ),
                timestamp="20260617T000000Z",
            )
            report = json.loads(result.metadata_report_path.read_text("utf-8"))
            report_text = json.dumps(report, ensure_ascii=False, sort_keys=True)

        self.assertEqual(result.status, "ready")
        self.assertIsNotNone(result.selected_unit_sequence)
        self.assertEqual(report["metadata_only"], True)
        self.assertEqual(report["selection"]["status"], "ready")
        self.assertTrue(report["selection"]["glossary_context_rendered"])
        self.assertTrue(report["cache"]["bypass_observed"])
        self.assertEqual(
            report["selection"]["cache_policy"]["behavior"],
            "bypass_glossary_injected_cache",
        )
        self.assertNotIn("BEGIN_UNTRUSTED_DOCUMENT_CONTENT", report_text)
        self.assertNotIn("<glossary_context", report_text)
        self.assertNotIn("RAW PROMPT", report_text)
        self.assertNotIn("Authorization", report_text)
        self.assertNotIn("Bearer ", report_text)
        self.assertNotIn("sk-", report_text)

    def test_fake_dry_refuses_unapproved_input(self):
        with TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "issue_675_input_not_approved"):
                run_fake_dry_preflight(
                    GlossaryEffectivenessSmokeConfig(
                        input_path=Path("test_samples/sample_book.en.txt"),
                        diagnostic_root=Path(temp_dir),
                    ),
                    timestamp="20260617T000000Z",
                )

    def test_live_smoke_with_fake_providers_records_pass_metadata_only(self):
        with TemporaryDirectory() as temp_dir:
            translator = _FakeRuntimeTranslator()
            result = run_live_smoke(
                GlossaryEffectivenessSmokeConfig(
                    diagnostic_root=Path(temp_dir) / "issue-675",
                    provider_base_url="https://deepseek.test",
                ),
                api_key="test-only",
                timestamp="20260617T010000Z",
                allow_test_diagnostic_root=True,
                prep_provider=_fake_prepared_glossary_provider,
                runtime_translator=translator,
            )
            report = json.loads(result.metadata_report_path.read_text("utf-8"))
            provider_io = (
                result.diagnostics_dir / "provider_io_diagnostics.jsonl"
            ).read_text("utf-8")
            report_text = json.dumps(report, ensure_ascii=False, sort_keys=True)

        self.assertEqual(result.status, "pass")
        self.assertEqual(result.live_provider_calls, 0)
        self.assertEqual(report["runtime"]["status"], "ready")
        self.assertEqual(
            report["runtime"]["structural_validation"]["status"],
            "pass",
        )
        self.assertEqual(report["glossary_compliance"]["status"], "pass")
        self.assertIn("<glossary_context", provider_io)
        self.assertNotIn("BEGIN_UNTRUSTED_DOCUMENT_CONTENT", report_text)
        self.assertNotIn("<glossary_context", report_text)
        self.assertNotIn("Authorization", report_text)
        self.assertNotIn("Bearer ", report_text)
        self.assertNotIn("sk-", report_text)


@dataclass
class _Usage:
    prompt_tokens: int = 11
    completion_tokens: int = 7
    total_tokens: int = 18
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 11


class _FakeRuntimeTranslator:
    def __init__(self) -> None:
        self.last_usage = _Usage()

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
        translation_context=None,
        service_glossary_context_present: bool = False,
    ) -> str:
        request = {
            "model": "fake-runtime",
            "messages": [
                {"role": "system", "content": "fake"},
                {"role": "user", "content": text},
            ],
            "stream": False,
        }
        response_text = _response_text_for_request(text)
        response = {
            "choices": [
                {
                    "message": {"content": response_text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "total_tokens": 18,
            },
        }
        record_provider_io_exchange(
            provider_id="deepseek",
            url="https://deepseek.test/chat/completions",
            request_body=json.dumps(request).encode("utf-8"),
            http_status=200,
            response_body=json.dumps(response).encode("utf-8"),
            transport_attempt=1,
        )
        return response_text


def _response_text_for_request(text: str) -> str:
    expected_count = text.count("<translation_block")
    block_text = "ru-glossary"
    lines = ["<translation_batch>"]
    for index in range(expected_count):
        lines.append(
            f'<translation_block id="{index}">{block_text}</translation_block>'
        )
    lines.append("</translation_batch>")
    return "".join(lines)


if __name__ == "__main__":
    unittest.main()
