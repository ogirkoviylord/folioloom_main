import json
import tempfile
import unittest
from pathlib import Path

from translator_service.glossary_contracts import (
    GlossaryEntry,
    GlossaryEntryCategory,
    GlossaryEntryStatus,
    GlossaryEvidenceRef,
    GlossaryEvidenceSurface,
    GlossaryEvidenceType,
    GlossaryLayer,
    GlossarySnapshot,
)
from translator_service.glossary_target_metadata_overlay import (
    GLOSSARY_TARGET_METADATA_OVERLAY_SCHEMA_VERSION,
    GlossaryTargetMetadataOverlayConfig,
    apply_glossary_target_metadata_overlay,
    load_glossary_target_metadata_overlay,
)


class GlossaryTargetMetadataOverlayTests(unittest.TestCase):
    def test_overlay_is_disabled_by_default(self):
        snapshot = _snapshot()
        result = apply_glossary_target_metadata_overlay(
            snapshot,
            _overlay_payload(),
            target_language="ru",
        )

        self.assertIs(result.snapshot, snapshot)
        self.assertEqual(result.status, "disabled")
        self.assertIn("target_metadata_overlay_disabled", result.reason_codes)
        self.assertEqual(result.metadata["metadata_only"], True)
        self.assertEqual(result.metadata["raw_payload_included"], False)

    def test_overlay_applies_by_source_alias_and_metadata_is_redacted(self):
        snapshot = _snapshot()
        result = apply_glossary_target_metadata_overlay(
            snapshot,
            _overlay_payload(
                entries=[
                    {
                        "entry_id": "untrusted-id-does-not-control-match",
                        "source_canonical": "Darcy",
                        "aliases": ["Fitzwilliam Darcy"],
                        "target_canonical": "Дарси",
                        "target_variants": ["Дарси", "мистер Дарси"],
                        "forbidden_variants": ["Дорси"],
                        "morphology_notes": ["variant-list only"],
                        "terminology_policy_metadata": {
                            "policy_id": "ru-variant-list",
                            "policy_version": "v1",
                            "match_mode": "variant_list",
                        },
                    }
                ]
            ),
            target_language="ru",
            config=GlossaryTargetMetadataOverlayConfig(enabled=True),
        )

        self.assertEqual(result.status, "applied")
        self.assertEqual(result.matched_entry_count, 1)
        entry = result.snapshot.entries[0]
        self.assertEqual(entry.target_canonical, "Дарси")
        self.assertEqual(entry.target_variants, ("Дарси", "мистер Дарси"))
        self.assertEqual(entry.forbidden_variants, ("Дорси",))
        self.assertEqual(entry.morphology_notes, ("variant-list only",))

        serialized = json.dumps(result.metadata, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("Дарси", serialized)
        self.assertNotIn("Fitzwilliam", serialized)
        self.assertNotIn("<glossary_context", serialized)
        self.assertEqual(result.metadata["matched_entry_count"], 1)

    def test_target_language_mismatch_falls_back_with_reason_code(self):
        snapshot = _snapshot()
        result = apply_glossary_target_metadata_overlay(
            snapshot,
            _overlay_payload(target_language="uk"),
            target_language="ru",
            config=GlossaryTargetMetadataOverlayConfig(enabled=True),
        )

        self.assertIs(result.snapshot, snapshot)
        self.assertEqual(result.status, "invalid")
        self.assertIn("target_metadata_overlay_target_missing", result.reason_codes)
        self.assertEqual(result.matched_entry_count, 0)

    def test_snapshot_target_language_mismatch_falls_back(self):
        snapshot = _snapshot(target_language="uk")
        result = apply_glossary_target_metadata_overlay(
            snapshot,
            _overlay_payload(target_language="ru"),
            target_language="ru",
            config=GlossaryTargetMetadataOverlayConfig(enabled=True),
        )

        self.assertIs(result.snapshot, snapshot)
        self.assertEqual(result.status, "invalid")
        self.assertIn(
            "target_metadata_overlay_snapshot_target_mismatch",
            result.reason_codes,
        )
        self.assertIsNone(result.snapshot.entries[0].target_canonical)

    def test_entry_limit_is_metadata_only_fallback(self):
        snapshot = _snapshot()
        entries = [
            {
                "source_canonical": f"Term {index}",
                "target_canonical": f"Термин {index}",
            }
            for index in range(3)
        ]
        result = apply_glossary_target_metadata_overlay(
            snapshot,
            _overlay_payload(entries=entries),
            target_language="ru",
            config=GlossaryTargetMetadataOverlayConfig(
                enabled=True,
                max_entries_per_target=2,
            ),
        )

        self.assertEqual(result.status, "invalid")
        self.assertIn(
            "target_metadata_overlay_entry_limit_exceeded",
            result.reason_codes,
        )
        serialized = json.dumps(result.metadata, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("Термин", serialized)

    def test_raw_and_secret_material_are_rejected_and_not_serialized(self):
        snapshot = _snapshot()
        result = apply_glossary_target_metadata_overlay(
            snapshot,
            _overlay_payload(
                entries=[
                    {
                        "source_canonical": "Darcy",
                        "target_canonical": "RAW TARGET",
                        "raw_source": "RAW SOURCE MUST NOT LEAK",
                        "rawPassage": "RAW PASSAGE MUST NOT LEAK",
                        ".env.local": "API_TOKEN=not-real",
                        "apiKey": "not-even-read",
                        "target_variants": ["sk-testsecret000000000000"],
                    }
                ]
            ),
            target_language="ru",
            config=GlossaryTargetMetadataOverlayConfig(enabled=True),
        )

        self.assertEqual(result.status, "invalid")
        self.assertIn("target_metadata_overlay_raw_field_present", result.reason_codes)
        self.assertIn(
            "target_metadata_overlay_secret_field_present",
            result.reason_codes,
        )
        self.assertIn(
            "target_metadata_overlay_secret_material_present",
            result.reason_codes,
        )
        serialized = json.dumps(result.metadata, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("RAW SOURCE MUST NOT LEAK", serialized)
        self.assertNotIn("RAW PASSAGE MUST NOT LEAK", serialized)
        self.assertNotIn("API_TOKEN", serialized)
        self.assertNotIn("RAW TARGET", serialized)
        self.assertNotIn("sk-testsecret", serialized)

    def test_entry_id_alone_does_not_match_retained_entry(self):
        snapshot = _snapshot()
        result = apply_glossary_target_metadata_overlay(
            snapshot,
            _overlay_payload(
                entries=[
                    {
                        "entry_id": "entry:darcy",
                        "source_canonical": "A different source",
                        "target_canonical": "Дарси",
                    }
                ]
            ),
            target_language="ru",
            config=GlossaryTargetMetadataOverlayConfig(enabled=True),
        )

        self.assertEqual(result.status, "loaded_no_matches")
        self.assertIn(
            "target_metadata_overlay_no_matching_retained_entries",
            result.reason_codes,
        )
        self.assertIsNone(result.snapshot.entries[0].target_canonical)

    def test_loader_reports_missing_file_without_reading_raw_payload(self):
        snapshot = _snapshot()
        with tempfile.TemporaryDirectory() as tmp:
            result = load_glossary_target_metadata_overlay(
                Path(tmp) / "missing.json",
                snapshot=snapshot,
                target_language="ru",
                config=GlossaryTargetMetadataOverlayConfig(enabled=True),
            )

        self.assertEqual(result.status, "missing")
        self.assertIn("target_metadata_overlay_missing", result.reason_codes)
        self.assertEqual(result.metadata["raw_payload_included"], False)


def _snapshot(*, target_language: str = "ru") -> GlossarySnapshot:
    return GlossarySnapshot(
        snapshot_id="snapshot:test",
        source_language="en",
        target_language=target_language,
        entries=(
            GlossaryEntry(
                entry_id="entry:darcy",
                category=GlossaryEntryCategory.NAME,
                layer=GlossaryLayer.HARD,
                status=GlossaryEntryStatus.VALIDATOR_ACCEPTED,
                source_canonical="Mr. Darcy",
                aliases=("Darcy",),
                evidence_refs=("evidence:darcy",),
                confidence=0.9,
            ),
        ),
        evidence=(
            GlossaryEvidenceRef(
                evidence_id="evidence:darcy",
                evidence_type=GlossaryEvidenceType.EXACT_REPEAT,
                unit_sequence=1,
                source_block_id="block-1",
                surface=GlossaryEvidenceSurface.BODY,
            ),
        ),
    )


def _overlay_payload(
    *,
    target_language: str = "ru",
    entries: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": GLOSSARY_TARGET_METADATA_OVERLAY_SCHEMA_VERSION,
        "overlay_id": "owner-approved-overlay",
        "scope": "local_owner_only_real_book_battle_test",
        "owner_approved": True,
        "source_language": "en",
        "targets": {
            target_language: {
                "entries": entries
                if entries is not None
                else [
                    {
                        "source_canonical": "Darcy",
                        "target_canonical": "Дарси",
                    }
                ]
            }
        },
    }


if __name__ == "__main__":
    unittest.main()
