import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.glossary_runtime_effectiveness_audit import (
    DEFAULT_PACKAGE_CAPS,
    RuntimeEffectivenessAuditCase,
    RuntimeGateVariant,
    audit_glossary_runtime_effectiveness,
    serialize_runtime_effectiveness_audit,
)


class GlossaryRuntimeEffectivenessAuditTests(unittest.TestCase):
    def test_fixture_cap_audit_is_metadata_only_and_compares_caps(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fixture.en.txt"
            path.write_text(
                "Mr. Darcy visited Pemberley. "
                "Alice saw Mr. Darcy near Pemberley. "
                "The chrono-loom hummed while Alice waited.",
                encoding="utf-8",
            )

            report = audit_glossary_runtime_effectiveness(
                cases=(
                    RuntimeEffectivenessAuditCase(
                        input_path=path,
                        document_kind="txt",
                        target_language="ru",
                        input_id="synthetic_fixture",
                    ),
                ),
                package_caps=DEFAULT_PACKAGE_CAPS,
                gate_variants=(
                    RuntimeGateVariant(
                        name="current_12_blocks_2400_chars",
                        max_source_blocks=12,
                        max_source_characters=2400,
                    ),
                    RuntimeGateVariant(
                        name="source_match_first_no_source_gate",
                        max_source_blocks=None,
                        max_source_characters=None,
                    ),
                ),
            )

        self.assertTrue(report["metadata_only"])
        self.assertFalse(report["raw_payload_included"])
        self.assertFalse(report["live_provider_calls_made"])
        self.assertIn(
            "local fake provider callback",
            report["provider_called_field_meaning"],
        )
        self.assertEqual(report["package_caps"], [8, 12, 16, 24])
        cap_reports = report["committed_fixture_cap_audit"]
        self.assertEqual([item["package_cap"] for item in cap_reports], [8, 12, 16, 24])
        for cap_report in cap_reports:
            self.assertIn("runtime_gate_totals", cap_report["totals"])
            self.assertEqual(
                cap_report["cases"][0]["provider_callback_kind"],
                "local_fake_provider_callback",
            )
        serialized = serialize_runtime_effectiveness_audit(report)
        self.assertNotIn("Mr. Darcy", serialized)
        self.assertNotIn("Pemberley", serialized)
        self.assertNotIn("chrono-loom", serialized)

    def test_archive_audit_records_zero_render_and_unknown_package_cap_effects(self):
        with TemporaryDirectory() as temp_dir:
            archive_dir = Path(temp_dir)
            (archive_dir / "glossary_runtime_diagnostics.json").write_text(
                json.dumps(
                    {
                        "metadata_only": True,
                        "raw_payload_included": False,
                        "document_kind": "epub",
                        "source_language": "en",
                        "target_language": "ru",
                        "summary": {
                            "rendered_prompt_context_count": 0,
                            "prompt_context_included_event_count": 0,
                            "compliance_summary_count": 0,
                            "prepared_package_statuses": ["ready"],
                            "attachment_statuses": ["attached"],
                            "cache_policy_behaviors": ["default_runtime_cache"],
                        },
                        "prepared_package_events": [
                            {
                                "status": "ready",
                                "entry_count": 5,
                                "metadata_only": True,
                                "raw_payload_included": False,
                            }
                        ],
                        "adapter_events": [
                            {
                                "payload": {
                                    "fallback_reason": (
                                        "persistent_glossary_source_character_"
                                        "limit_exceeded"
                                    ),
                                    "battle_test_preflight": {
                                        "source_block_count": 2,
                                        "source_character_count": 3200,
                                    },
                                }
                            },
                            {
                                "payload": {
                                    "fallback_reason": (
                                        "persistent_glossary_prepared_package_"
                                        "no_applicable_entries"
                                    ),
                                    "battle_test_preflight": {
                                        "source_block_count": 1,
                                        "source_character_count": 500,
                                    },
                                }
                            },
                        ],
                        "prompt_context_events": [
                            {
                                "included": False,
                                "omission_reasons": [
                                    "persistent_glossary_prepared_package_"
                                    "no_applicable_entries"
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = audit_glossary_runtime_effectiveness(
                cases=(),
                archive_dir=archive_dir,
                package_caps=(8, 12, 16),
                gate_variants=(
                    RuntimeGateVariant(
                        name="current_12_blocks_2400_chars",
                        max_source_blocks=12,
                        max_source_characters=2400,
                    ),
                    RuntimeGateVariant(
                        name="relaxed_24_blocks_4800_chars",
                        max_source_blocks=24,
                        max_source_characters=4800,
                    ),
                ),
            )

        archive = report["archive_observation"]
        self.assertEqual(archive["status"], "available")
        self.assertTrue(archive["zero_render_observed"])
        self.assertEqual(archive["attached_entry_counts"], [5])
        self.assertEqual(
            archive["runtime_gate_observations"]["current_12_blocks_2400_chars"][
                "eligible_unit_count"
            ],
            1,
        )
        self.assertEqual(
            archive["runtime_gate_observations"]["relaxed_24_blocks_4800_chars"][
                "eligible_unit_count"
            ],
            2,
        )
        self.assertEqual(
            archive["package_cap_comparison"][0]["candidate_pool_entry_count"],
            "Unknown",
        )
        serialized = serialize_runtime_effectiveness_audit(report)
        self.assertNotIn("raw source", serialized.lower())


if __name__ == "__main__":
    unittest.main()
