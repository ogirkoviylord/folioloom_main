from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _ROOT / "tools" / "deepseek_glossary_profile_spike.py"
_SPEC = importlib.util.spec_from_file_location(
    "deepseek_glossary_profile_spike",
    _SCRIPT_PATH,
)
assert _SPEC is not None
assert _SPEC.loader is not None
spike = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = spike
_SPEC.loader.exec_module(spike)


class DeepSeekGlossaryProfileSpikeTest(unittest.TestCase):
    def test_fake_dry_run_validates_all_approved_fixture_roles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report = spike.run_spike(
                spike.SpikeConfig(
                    fixture_paths=spike.APPROVED_FIXTURES,
                    diagnostic_root=Path(temp_dir),
                    max_calls=6,
                    max_tokens_total=200_000,
                    dry_run=True,
                ),
                provider=spike.FakeProvider(),
                repo_root=_ROOT,
            )

            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["calls_made"], 6)
            self.assertLessEqual(report["reserved_tokens"], 200_000)
            self.assertTrue(
                all(
                    call["validation"]["valid"]
                    for call in report["calls"]
                    if call["status"] == "validated"
                )
            )
            diagnostic_dir = Path(report["diagnostic_dir"])
            self.assertTrue((diagnostic_dir / "manifest.json").is_file())
            self.assertEqual(len(list(diagnostic_dir.glob("call-*.json"))), 6)

    def test_rejects_unapproved_fixture_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "not approved"):
                spike.run_spike(
                    spike.SpikeConfig(
                        fixture_paths=(Path("README.md"),),
                        diagnostic_root=Path(temp_dir),
                        dry_run=True,
                    ),
                    provider=spike.FakeProvider(),
                    repo_root=_ROOT,
                )

    def test_stops_before_exceeding_token_budget(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report = spike.run_spike(
                spike.SpikeConfig(
                    fixture_paths=spike.APPROVED_FIXTURES,
                    diagnostic_root=Path(temp_dir),
                    max_calls=6,
                    max_tokens_total=1,
                    dry_run=True,
                ),
                provider=spike.FakeProvider(),
                repo_root=_ROOT,
            )

            self.assertEqual(report["calls_made"], 0)
            self.assertEqual(report["status"], "completed_with_skips")
            self.assertTrue(
                all(
                    call["status"] == "skipped_token_budget"
                    for call in report["calls"]
                )
            )

    def test_observed_provider_usage_stops_later_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report = spike.run_spike(
                spike.SpikeConfig(
                    fixture_paths=(spike.APPROVED_FIXTURES[-1],),
                    diagnostic_root=Path(temp_dir),
                    max_calls=2,
                    max_tokens_total=20_000,
                    dry_run=True,
                ),
                provider=_HighUsageFakeProvider(),
                repo_root=_ROOT,
            )

            self.assertEqual(report["calls_made"], 1)
            self.assertEqual(report["status"], "completed_with_skips")
            self.assertEqual(report["calls"][1]["status"], "skipped_token_budget")


class _HighUsageFakeProvider(spike.FakeProvider):
    def chat(self, **kwargs):
        result = super().chat(**kwargs)
        return replace(
            result,
            usage={
                "prompt_tokens": 15_000,
                "completion_tokens": 100,
                "total_tokens": 15_100,
            },
        )


if __name__ == "__main__":
    unittest.main()
