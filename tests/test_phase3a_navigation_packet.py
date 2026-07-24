"""Focused validation for the proposed metadata-only Phase 3A navigation packet."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "proposals" / "folioloom-phase3a-navigation-source-policy.md"


class Phase3ANavigationPacketTests(unittest.TestCase):
    def test_packet_is_pinned_metadata_only_and_preregisters_fair_baseline(self) -> None:
        packet = PACKET.read_text(encoding="utf-8")

        for required in (
            "76caed68de4dc5d9f1f50f9e5507b88557f7d731",
            "https://github.com/ogirkoviylord/folioloom_main",
            "approval_state: proposed",
            "Markdown headings",
            "Python symbols and imports",
            "test identifiers",
            "DOCUMENT_INDEX.md + restricted rg",
            "Owner decision (one)",
        ):
            self.assertIn(required, packet)

        self.assertEqual(packet.count("| B0"), 1)
        self.assertEqual(packet.count("| B1"), 1)
        self.assertEqual(packet.count("| B2"), 1)
        self.assertEqual(packet.count("| B3"), 1)
        self.assertEqual(packet.count("| B4"), 1)
        self.assertEqual(packet.count("| B5"), 1)
        self.assertEqual(packet.count("| B6"), 1)

        self.assertIn(
            "B5 | Metrics/review navigation: translation metrics behavior",
            packet,
        )
        self.assertNotIn("provider_failure_diagnostics.py", packet)

        for required_path_rule in (
            "Path-only, exact allowlist; evaluate before opening or parsing a blob.",
            "docs/DECISIONS.md",
            "docs/ROADMAP.md",
            "docs/CAT_WORKFLOW_GATES.md",
            "src/translator_service/translation_jobs.py",
            "src/translator_service/glossary_effective_decision.py",
            "src/translator_service/translation_metrics.py",
            "src/translator_service/bot_translation_service.py",
            "tests/test_translation_jobs.py",
            "tests/test_translation_metrics.py",
            "tests/test_bot_translation_service.py",
            "docs/archive/",
            "docs/deployment/",
            "docs/competitive/",
            "docs/restart/",
            "docs/superpowers/",
            "All other paths are denied, including every path under a permitted root that is not listed above.",
            "3 candidate Markdown files, 4 candidate production Python files, and 3 candidate Python test files",
        ):
            self.assertIn(required_path_rule, packet)

        for required_denial in (
            "No raw source body is persisted.",
            "No source snippets are persisted.",
            "No docstrings are persisted.",
            "No comments are persisted.",
            "No literals are persisted.",
        ):
            self.assertIn(required_denial, packet)


if __name__ == "__main__":
    unittest.main()
